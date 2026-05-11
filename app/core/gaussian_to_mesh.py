"""
Convert 3D Gaussian Splatting PLY output from LHM into a triangulated mesh.

LHM outputs 3D Gaussian parameters (position, covariance, SH coefficients,
opacity) stored in PLY format.  Standard mesh viewers cannot display this.

This module:
1. Reads the Gaussian PLY file
2. Filters low-opacity Gaussians
3. Removes statistical outliers
4. Estimates per-point normals
5. Runs Screened Poisson Surface Reconstruction to create a watertight mesh
6. Trims low-density regions
7. Extracts vertex colors from the Gaussian SH coefficients
8. Returns a clean Open3D TriangleMesh

References:
  - Kazhdan & Hoppe, "Screened Poisson Surface Reconstruction", 2013
  - Kerbl et al., "3D Gaussian Splatting for Real-Time Radiance Field Rendering", 2023
"""

from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import open3d as o3d
from plyfile import PlyData

from app.config import settings
from app.utils.logger import logger


class GaussianToMesh:
    """
    Converts a 3D Gaussian Splatting PLY file to a triangulated mesh.

    Usage:
        converter = GaussianToMesh()
        mesh = converter.convert("lhm_output.ply")
        # mesh is an open3d.geometry.TriangleMesh with vertex colors
    """

    def __init__(
        self,
        opacity_threshold: Optional[float] = None,
        poisson_depth: Optional[int] = None,
        density_threshold_percentile: Optional[int] = None,
        min_cluster_size: Optional[int] = None,
        outlier_nb_neighbors: Optional[int] = None,
        outlier_std_ratio: Optional[float] = None,
    ):
        cfg = settings.mesh_reconstruction
        self.opacity_threshold = opacity_threshold if opacity_threshold is not None else cfg.opacity_threshold
        self.poisson_depth = poisson_depth if poisson_depth is not None else cfg.poisson_depth
        self.density_pct = density_threshold_percentile if density_threshold_percentile is not None else cfg.density_threshold_percentile
        self.min_cluster_size = min_cluster_size if min_cluster_size is not None else cfg.min_cluster_size
        self.nb_neighbors = outlier_nb_neighbors if outlier_nb_neighbors is not None else cfg.outlier_nb_neighbors
        self.std_ratio = outlier_std_ratio if outlier_std_ratio is not None else cfg.outlier_std_ratio

        # Set during convert() — holds the clean Gaussian point cloud (post outlier-removal,
        # pre-Poisson) for use in final color re-transfer after mesh processing.
        self.source_pcd: o3d.geometry.PointCloud = o3d.geometry.PointCloud()

    # ── Public API ──────────────────────────────────────────────────────────

    def convert(self, ply_path: str | Path) -> o3d.geometry.TriangleMesh:
        """
        Full conversion pipeline: Gaussian PLY → TriangleMesh.

        Parameters
        ----------
        ply_path : path to the Gaussian Splatting PLY from LHM

        Returns
        -------
        open3d.geometry.TriangleMesh with vertex colors
        """
        ply_path = Path(ply_path)
        if not ply_path.exists():
            raise FileNotFoundError(f"PLY file not found: {ply_path}")

        logger.info(f"Converting Gaussian PLY to mesh: {ply_path}")

        # Step 1: Detect PLY type and load accordingly
        is_gaussian, pcd = self._load_ply(ply_path)

        if not is_gaussian:
            # It's already a standard mesh PLY — load directly.
            # IMPORTANT: O3D does not decode SH / custom colour channels
            # (f_dc_0/1/2) stored in the PLY, so mesh.has_vertex_colors()
            # returns False even though colour data is present.  We must
            # extract colours ourselves via plyfile and assign them.
            logger.info("PLY appears to be a standard mesh (has faces). Loading directly.")
            mesh = o3d.io.read_triangle_mesh(str(ply_path))
            if len(mesh.triangles) > 0:
                # Extract colours from SH/RGB fields if O3D missed them
                if not mesh.has_vertex_colors():
                    _plydata = PlyData.read(str(ply_path))
                    _v = _plydata["vertex"]
                    _props = [p.name for p in _v.properties]
                    _colors = self._extract_colors(_v, _props)
                    if _colors is not None:
                        mesh.vertex_colors = o3d.utility.Vector3dVector(_colors)
                        logger.info("Extracted SH colors and assigned to mesh vertices")
                logger.info(
                    f"Loaded standard mesh: {len(mesh.vertices)} verts, "
                    f"{len(mesh.triangles)} faces"
                )
                return mesh
            # Mesh has no triangles — fall back to point-cloud reconstruction
            logger.info("PLY mesh has no faces — reconstructing from point cloud")
            pcd = o3d.io.read_point_cloud(str(ply_path))

        n_points = len(pcd.points)
        logger.info(f"Point cloud: {n_points} points")

        if n_points < 100:
            raise ValueError(
                f"Too few points ({n_points}) after loading. "
                "The PLY file may be corrupted or empty."
            )

        # Step 2: Remove outliers
        pcd = self._remove_outliers(pcd)

        # Store clean point cloud — used for final color re-transfer in MeshProcessor
        # (after smoothing + decimation move vertex positions, we re-paint from source).
        self.source_pcd = pcd

        # Step 3: Estimate normals
        pcd = self._estimate_normals(pcd)

        # Step 4: Poisson surface reconstruction
        mesh, densities = self._poisson_reconstruction(pcd)

        # Step 5: Trim low-density regions
        mesh = self._trim_mesh(mesh, densities)

        # Step 6: Remove disconnected fragments
        mesh = self._remove_small_components(mesh)

        # Step 7: Transfer vertex colors via KNN from the original point cloud.
        # We ALWAYS run this, even if Poisson already set colors on the mesh.
        # Poisson's built-in color interpolation is an octree-blurred average that
        # bleeds colors across region boundaries (e.g. red jacket into dark jeans).
        # KNN transfer from the original point cloud is much sharper and accurate.
        mesh = self._transfer_colors(pcd, mesh)

        n_verts = len(mesh.vertices)
        n_faces = len(mesh.triangles)
        logger.info(f"Final mesh: {n_verts} vertices, {n_faces} faces")

        return mesh

    # ── PLY Loading ─────────────────────────────────────────────────────────

    def _load_ply(self, ply_path: Path) -> Tuple[bool, o3d.geometry.PointCloud]:
        """
        Load a PLY file, detecting whether it's Gaussian Splatting or standard.

        Returns (is_gaussian, point_cloud).
        """
        plydata = PlyData.read(str(ply_path))
        vertex = plydata["vertex"]
        props = [p.name for p in vertex.properties]

        logger.debug(f"PLY properties: {props}")

        # Check if it has faces (standard mesh) — do this FIRST.
        # LHM with export_mesh=True can output a real mesh PLY that also
        # contains Gaussian properties (opacity, f_dc_*).  If the PLY has
        # a face element with a meaningful number of triangles, treat it
        # as a standard mesh and skip the Gaussian→Poisson path entirely.
        has_faces = "face" in plydata
        if has_faces:
            n_faces = len(plydata["face"].data)
            if n_faces > 100:
                logger.info(
                    f"PLY has {n_faces} faces — treating as standard mesh "
                    f"(skipping Gaussian reconstruction)"
                )
                return False, o3d.geometry.PointCloud()

        # Detect Gaussian Splatting format
        # GS PLY files typically have: x, y, z, opacity, scale_0-2, rot_0-3, f_dc_0-2, etc.
        is_gaussian = "opacity" in props or "f_dc_0" in props

        # Extract positions
        xyz = np.stack(
            [vertex["x"], vertex["y"], vertex["z"]], axis=-1
        ).astype(np.float64)

        # Extract colors
        colors = self._extract_colors(vertex, props)

        # Filter by opacity if available
        if "opacity" in props:
            opacity = self._sigmoid(np.array(vertex["opacity"], dtype=np.float64))
            mask = opacity >= self.opacity_threshold
            logger.info(
                f"Opacity filter: {mask.sum()}/{len(mask)} points kept "
                f"(threshold={self.opacity_threshold})"
            )
            xyz = xyz[mask]
            if colors is not None:
                colors = colors[mask]
        else:
            mask = np.ones(len(vertex["x"]), dtype=bool)

        # Augment with surface samples from Gaussian ellipsoids.
        # Each Gaussian encodes not just a center but an oriented ellipsoid
        # (scale_0/1/2 + quaternion).  Sampling along the principal axes
        # at ±0.4σ gives 6 extra surface-hugging points per Gaussian.
        # Face/head Gaussians are tight (scale ≈ 0.011) so their samples
        # cluster densely → Poisson reconstructs fine facial geometry.
        # Body Gaussians are looser (scale ≈ 0.016) → samples spread out
        # evenly → good body coverage. Net: face gets ~7× the point density.
        xyz, colors = self._sample_ellipsoid_surface(vertex, props, mask, xyz, colors)

        # Build point cloud
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(xyz)
        if colors is not None:
            pcd.colors = o3d.utility.Vector3dVector(colors)

        return is_gaussian, pcd

    def _extract_colors(
        self, vertex, props: list
    ) -> Optional[np.ndarray]:
        """
        Extract RGB colors from the PLY vertex data.
        Handles multiple formats:
        - Spherical harmonics (f_dc_0, f_dc_1, f_dc_2)
        - Direct RGB (red, green, blue)
        - Uint8 RGB
        """
        n = len(vertex["x"])

        # Method 1: Spherical harmonics DC component (most common in GS)
        if all(p in props for p in ["f_dc_0", "f_dc_1", "f_dc_2"]):
            # SH DC coefficients → RGB via: color = SH_C0 * dc + 0.5
            SH_C0 = 0.28209479177387814  # 1 / (2 * sqrt(pi))
            r = vertex["f_dc_0"].astype(np.float64) * SH_C0 + 0.5
            g = vertex["f_dc_1"].astype(np.float64) * SH_C0 + 0.5
            b = vertex["f_dc_2"].astype(np.float64) * SH_C0 + 0.5
            colors = np.stack([r, g, b], axis=-1)
            colors = np.clip(colors, 0.0, 1.0)

            # --- Color enhancement ---
            # SH DC-only extraction discards view-dependent higher-order SH terms.
            # We apply a saturation boost to restore vivid colors. 1.3x makes
            # jacket reds, skin tones and dark jeans clearly distinguishable
            # without blowing highlights or crushing dark regions.
            lum = (0.2126 * colors[:, 0] +
                   0.7152 * colors[:, 1] +
                   0.0722 * colors[:, 2])[:, None]   # (N,1) luminance
            saturation_factor = 1.3  # vivid, accurate color reproduction
            colors = np.clip(lum + saturation_factor * (colors - lum), 0.0, 1.0)

            return colors

        # Method 2: Direct float RGB
        if all(p in props for p in ["red", "green", "blue"]):
            r = np.array(vertex["red"], dtype=np.float64)
            g = np.array(vertex["green"], dtype=np.float64)
            b = np.array(vertex["blue"], dtype=np.float64)
            colors = np.stack([r, g, b], axis=-1)
            # Normalize if values are in [0, 255]
            if colors.max() > 1.0:
                colors = colors / 255.0
            return np.clip(colors, 0.0, 1.0)

        # Method 3: Short-name RGB properties (r, g, b)
        if all(p in props for p in ["r", "g", "b"]):
            r = np.array(vertex["r"], dtype=np.float64)
            g = np.array(vertex["g"], dtype=np.float64)
            b = np.array(vertex["b"], dtype=np.float64)
            colors = np.stack([r, g, b], axis=-1)
            if colors.max() > 1.0:
                colors = colors / 255.0
            return np.clip(colors, 0.0, 1.0)

        logger.warning("No color data found in PLY — mesh will have default gray color")
        return None

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        """Numerically stable sigmoid function."""
        return np.where(
            x >= 0,
            1.0 / (1.0 + np.exp(-x)),
            np.exp(x) / (1.0 + np.exp(x)),
        )

    @staticmethod
    def _sample_ellipsoid_surface(
        vertex, props: list, mask: np.ndarray,
        xyz: np.ndarray, colors: Optional[np.ndarray],
        sigma: float = 0.4,
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        Augment the point cloud with surface samples from each Gaussian ellipsoid.

        Each 3DGS Gaussian is an oriented ellipsoid defined by:
          - centre  : xyz
          - scale   : exp(scale_0/1/2)  — half-axis lengths
          - rotation: quaternion rot_0(w)/rot_1(x)/rot_2(y)/rot_3(z)

        We sample 6 points per Gaussian at ±sigma along each principal axis.
        These points stay on the ellipsoid surface, faithfully representing
        the Gaussian's actual shape rather than just its centre.

        Effect on face quality:
          Head Gaussians median scale ≈ 0.011  → samples within 0.9 cm of centre
          Body Gaussians median scale ≈ 0.016  → samples within 1.4 cm of centre
        The face region gets 7× point density relative to the centres-only case,
        giving Screened Poisson far more data to reconstruct fine facial geometry.
        """
        need = ["scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
        if not all(p in props for p in need):
            logger.debug("No scale/rotation in PLY — skipping ellipsoid sampling")
            return xyz, colors

        n = len(xyz)

        # ── Extract and clamp scale ──────────────────────────────────────────
        sx = np.exp(np.clip(np.array(vertex["scale_0"])[mask], -10, 2)).astype(np.float64)
        sy = np.exp(np.clip(np.array(vertex["scale_1"])[mask], -10, 2)).astype(np.float64)
        sz = np.exp(np.clip(np.array(vertex["scale_2"])[mask], -10, 2)).astype(np.float64)
        # Clamp to 95th-percentile max to avoid exploding outliers
        s_ceil = np.percentile(np.stack([sx, sy, sz]).max(axis=0), 95)
        sx = np.clip(sx, 1e-6, s_ceil)
        sy = np.clip(sy, 1e-6, s_ceil)
        sz = np.clip(sz, 1e-6, s_ceil)

        # ── Extract and normalise quaternion [w, x, y, z] ───────────────────
        qw = np.array(vertex["rot_0"])[mask].astype(np.float64)
        qx = np.array(vertex["rot_1"])[mask].astype(np.float64)
        qy = np.array(vertex["rot_2"])[mask].astype(np.float64)
        qz = np.array(vertex["rot_3"])[mask].astype(np.float64)
        qn = np.sqrt(qw**2 + qx**2 + qy**2 + qz**2) + 1e-8
        qw, qx, qy, qz = qw/qn, qx/qn, qy/qn, qz/qn

        # ── Build rotation matrix columns (world-space axes of ellipsoid) ───
        # Column 0 = local-X axis in world coords
        ax = np.stack([1-2*(qy**2+qz**2),  2*(qx*qy+qw*qz),  2*(qx*qz-qw*qy)], axis=1)  # (N,3)
        # Column 1 = local-Y axis
        ay = np.stack([2*(qx*qy-qw*qz),  1-2*(qx**2+qz**2),  2*(qy*qz+qw*qx)], axis=1)
        # Column 2 = local-Z axis
        az = np.stack([2*(qx*qz+qw*qy),  2*(qy*qz-qw*qx),  1-2*(qx**2+qy**2)], axis=1)

        # ── Generate ±sigma samples along each axis ──────────────────────────
        all_pts:    list = [xyz]
        all_colors: list = [colors] if colors is not None else []

        for axis_dir, scale_vals in [(ax, sx), (ay, sy), (az, sz)]:
            for sign in (+1.0, -1.0):
                offset   = sign * sigma * scale_vals[:, None] * axis_dir  # (N,3)
                new_pts  = xyz + offset
                all_pts.append(new_pts)
                if colors is not None:
                    all_colors.append(colors)   # inherit parent Gaussian color

        new_xyz    = np.vstack(all_pts)                                      # (7N, 3)
        new_colors = np.vstack(all_colors) if colors is not None else None   # (7N, 3)

        logger.info(
            f"Ellipsoid sampling: {n} centers + {len(new_xyz)-n} surface pts "
            f"= {len(new_xyz)} total (\u03c3={sigma})"
        )
        return new_xyz, new_colors

    # ── Point Cloud Processing ──────────────────────────────────────────────

    def _remove_outliers(
        self, pcd: o3d.geometry.PointCloud
    ) -> o3d.geometry.PointCloud:
        """Remove statistical and radius-based outliers from the point cloud.
        
        Two-pass approach:
        1. Statistical outlier removal: removes points whose average neighbor
           distance is more than std_ratio standard deviations above the mean.
        2. Radius outlier removal: removes isolated points with fewer than
           6 neighbors within a local radius — catches remaining noise clusters
           that statistical removal misses.
        """
        n_before = len(pcd.points)

        # Pass 1: Statistical outlier removal
        pcd_clean, _ = pcd.remove_statistical_outlier(
            nb_neighbors=self.nb_neighbors,
            std_ratio=self.std_ratio,
        )

        # Pass 2: Radius-based outlier removal
        # Use adaptive radius = 2% of bounding box extent.
        # nb_points=4 (not 6): face Gaussians are genuinely sparser than the body
        # — a threshold of 6 can silently delete valid eyelid/eyebrow/hairline points.
        bbox = pcd_clean.get_axis_aligned_bounding_box()
        extent = float(np.max(bbox.get_extent()))
        radius = max(0.05, extent * 0.02)
        pcd_clean2, _ = pcd_clean.remove_radius_outlier(
            nb_points=4, radius=radius
        )

        n_after = len(pcd_clean2.points)
        logger.info(f"Outlier removal: {n_before} \u2192 {n_after} points (2-pass: statistical + radius r={radius:.4f})")
        return pcd_clean2

    def _estimate_normals(
        self, pcd: o3d.geometry.PointCloud
    ) -> o3d.geometry.PointCloud:
        """
        Estimate and orient normals for Poisson reconstruction.

        The search radius and neighbor count are critical for thin structures
        (arms, hands, fingers).  A radius too small means not enough
        neighbors → noisy/wrong normals → Poisson creates holes or
        inside-out geometry there.
        """
        # Adaptive radius: compute based on point cloud extent so it
        # works regardless of world-space scale.
        bbox = pcd.get_axis_aligned_bounding_box()
        extent = np.max(bbox.get_extent())
        # Use ~3% of bounding-box extent — balances local detail vs.
        # having enough neighbors on sparse regions.
        adaptive_radius = max(0.15, extent * 0.03)

        pcd.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(
                radius=adaptive_radius, max_nn=200
            )
        )

        # Step 1: propagate a consistent orientation throughout the surface
        # using the tangent-plane k-NN graph.  k=50 gives better consistency in
        # sparse regions (hands, feet, hair) than k=30.
        pcd.orient_normals_consistent_tangent_plane(k=50)

        # Step 2: determine if the consistent orientation is outward or inward.
        # For a body, outward normals have positive dot product with
        # (point - center).  Flip all normals if the majority point inward.
        points = np.asarray(pcd.points)
        normals = np.asarray(pcd.normals)
        center = np.asarray(pcd.get_center())
        radial = points - center                          # (N, 3) vectors from center
        dot = (radial * normals).sum(axis=1)              # positive = outward
        if dot.mean() < 0:                                # majority inward → flip all
            pcd.normals = o3d.utility.Vector3dVector(-normals)
            logger.info("Normals flipped to outward (majority were inward after tangent propagation)")
        else:
            logger.info("Normals already outward after tangent propagation")

        logger.info(
            f"Normals estimated (consistent tangent plane, "
            f"radius={adaptive_radius:.4f}, extent={extent:.3f})"
        )
        return pcd

    # ── Mesh Reconstruction ─────────────────────────────────────────────────

    def _poisson_reconstruction(
        self, pcd: o3d.geometry.PointCloud
    ) -> Tuple[o3d.geometry.TriangleMesh, np.ndarray]:
        """
        Screened Poisson Surface Reconstruction.
        Returns the mesh and per-vertex density values (for trimming).
        """
        logger.info(f"Running Poisson reconstruction (depth={self.poisson_depth})...")

        mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
            pcd,
            depth=self.poisson_depth,
            width=0,
            scale=1.05,
            linear_fit=True,
        )

        densities = np.asarray(densities)
        logger.info(
            f"Poisson result: {len(mesh.vertices)} verts, "
            f"{len(mesh.triangles)} faces"
        )
        return mesh, densities

    def _trim_mesh(
        self,
        mesh: o3d.geometry.TriangleMesh,
        densities: np.ndarray,
    ) -> o3d.geometry.TriangleMesh:
        """Remove low-density vertices (Poisson artifacts outside the object)."""
        threshold = np.percentile(densities, self.density_pct)
        vertices_to_remove = densities < threshold

        mesh.remove_vertices_by_mask(vertices_to_remove)

        logger.info(
            f"Density trimming: removed {vertices_to_remove.sum()} vertices "
            f"(threshold percentile={self.density_pct})"
        )
        return mesh

    def _remove_small_components(
        self, mesh: o3d.geometry.TriangleMesh
    ) -> o3d.geometry.TriangleMesh:
        """Remove small disconnected components (floating fragments)."""
        triangle_clusters, cluster_n_triangles, _ = (
            mesh.cluster_connected_triangles()
        )

        triangle_clusters = np.asarray(triangle_clusters)
        cluster_n_triangles = np.asarray(cluster_n_triangles)

        if len(cluster_n_triangles) == 0:
            return mesh

        # Keep only clusters larger than min_cluster_size
        small_clusters = cluster_n_triangles < self.min_cluster_size
        triangles_to_remove = small_clusters[triangle_clusters]

        n_removed = triangles_to_remove.sum()
        if n_removed > 0:
            mesh.remove_triangles_by_mask(triangles_to_remove)
            mesh.remove_unreferenced_vertices()
            logger.info(
                f"Removed {n_removed} triangles from "
                f"{small_clusters.sum()} small components"
            )

        return mesh

    # ── Color Transfer ──────────────────────────────────────────────────────

    def _transfer_colors(
        self,
        source_pcd: o3d.geometry.PointCloud,
        target_mesh: o3d.geometry.TriangleMesh,
        k_neighbors: int = 3,
    ) -> o3d.geometry.TriangleMesh:
        """
        Transfer vertex colors from the source point cloud to the mesh using
        vectorized k-nearest-neighbor interpolation via scipy.spatial.cKDTree.

        k=3 with inverse-distance^6 (= dist_sq^3) weighting gives the sharpest
        possible color boundaries — the nearest Gaussian dominates completely,
        and we only blend the 2 back-up neighbors to guard against single-point
        outliers.  Processes all mesh vertices in a single batched query.
        """
        from scipy.spatial import cKDTree

        if not source_pcd.has_colors():
            logger.warning("Source point cloud has no colors — setting default")
            n = len(target_mesh.vertices)
            target_mesh.vertex_colors = o3d.utility.Vector3dVector(
                np.full((n, 3), 0.7)
            )
            return target_mesh

        logger.info(
            f"Transferring colors (k={k_neighbors}, vectorized scipy cKDTree, dist^6 weighting) "
            f"from {len(source_pcd.points)} Gaussians to {len(target_mesh.vertices)} mesh vertices..."
        )

        src_pts    = np.asarray(source_pcd.points,  dtype=np.float64)
        src_colors = np.asarray(source_pcd.colors,  dtype=np.float64)
        dst_pts    = np.asarray(target_mesh.vertices, dtype=np.float64)

        # Build KD-tree and query ALL vertices at once (multi-threaded)
        tree = cKDTree(src_pts)
        dists, idxs = tree.query(dst_pts, k=k_neighbors, workers=-1)  # (N,k) each

        # Ensure 2-D even when k=1
        if dists.ndim == 1:
            dists = dists[:, None]
            idxs  = idxs[:,  None]

        # Inverse-distance^6 weighting (= 1/dist_sq^3 from the serial loop)
        eps      = 1e-12
        weights  = 1.0 / (dists ** 6 + eps)          # (N, k)

        # Coincident points: assign full weight to the nearest neighbor
        coincident          = dists[:, 0] < 1e-10
        weights[coincident] = 0.0
        weights[coincident, 0] = 1.0

        weights /= weights.sum(axis=1, keepdims=True)  # normalize rows

        # Weighted color sum: src_colors[idxs] → (N, k, 3)
        mesh_colors = (src_colors[idxs] * weights[:, :, None]).sum(axis=1)
        mesh_colors = np.clip(mesh_colors, 0.0, 1.0)

        target_mesh.vertex_colors = o3d.utility.Vector3dVector(mesh_colors)
        logger.info("Color transfer complete")
        return target_mesh

    # ── Utility: Save intermediate ──────────────────────────────────────────

    def save_mesh(
        self, mesh: o3d.geometry.TriangleMesh, output_path: str | Path
    ) -> Path:
        """Save the mesh to a file (OBJ, PLY, or STL)."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        o3d.io.write_triangle_mesh(str(path), mesh, write_vertex_colors=True)
        logger.info(f"Mesh saved to: {path}")
        return path
