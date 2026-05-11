"""
Mesh post-processing and optimization.

Takes the raw mesh from GaussianToMesh and optimizes it for web delivery:
- Decimation (reduce poly count for performance)
- Smoothing (remove noise)
- Hole filling
- Normal recomputation
- UV unwrapping for texture atlas baking
"""

from pathlib import Path
from typing import Optional

import numpy as np
import open3d as o3d
import trimesh

from app.config import settings
from app.utils.logger import logger


class MeshProcessor:
    """
    Processes and optimizes a mesh for web-ready GLB export.

    Usage:
        processor = MeshProcessor()
        optimized = processor.process(raw_mesh)
    """

    def __init__(self):
        cfg = settings.mesh_processing
        self.target_faces = cfg.target_faces
        self.smoothing_iterations = cfg.smoothing_iterations
        self.smoothing_lambda = cfg.smoothing_lambda
        self.fill_holes = cfg.fill_holes
        self.max_hole_size = cfg.max_hole_size

    # ── Main entry point ─────────────────────────────────────────────────────

    def process(
        self,
        mesh: o3d.geometry.TriangleMesh,
        source_pcd: Optional[o3d.geometry.PointCloud] = None,
    ) -> o3d.geometry.TriangleMesh:
        """
        Full processing pipeline.

        Parameters
        ----------
        mesh : raw Open3D TriangleMesh from GaussianToMesh
        source_pcd : optional clean Gaussian point cloud (with colors) from
                     GaussianToMesh.source_pcd.  When provided, a final KNN
                     color re-transfer is performed after decimation and BEFORE
                     normalize so that colors reflect final vertex positions
                     rather than the Poisson-era positions.

        Returns
        -------
        Optimized Open3D TriangleMesh
        """
        logger.info("Starting mesh processing...")
        self._log_mesh_stats(mesh, "Input")

        mesh = self._clean_mesh(mesh)
        mesh = self._remove_spikes(mesh)

        if self.fill_holes:
            mesh = self._fill_holes(mesh)

        # Loop subdivision: double triangle count, then quadric decimation
        # keeps MORE faces in high-curvature areas (face, hands, fingers)
        # and fewer in flat low-detail areas (back, sides of torso).
        mesh = self._subdivide(mesh)

        mesh = self._smooth(mesh)
        mesh = self._decimate(mesh)

        # Re-transfer colors from original Gaussian point cloud BEFORE normalizing.
        # Smoothing and decimation move/merge vertices, making earlier KNN colors
        # slightly inaccurate.  Re-painting here gives sharp, accurate colors at
        # the final vertex positions while the mesh is still in LHM world-space
        # (same coordinate system as source_pcd).
        if source_pcd is not None and source_pcd.has_colors():
            logger.info("Re-transferring colors from source point cloud (post-decimation)...")
            mesh = self._recolor_from_pcd(source_pcd, mesh)

        mesh = self._normalize_transform(mesh)

        self._log_mesh_stats(mesh, "Output")
        return mesh

    # ── Stage: clean ─────────────────────────────────────────────────────────

    def _clean_mesh(self, mesh: o3d.geometry.TriangleMesh) -> o3d.geometry.TriangleMesh:
        """Remove degenerate triangles and unreferenced vertices."""
        mesh.remove_degenerate_triangles()
        mesh.remove_duplicated_triangles()
        mesh.remove_duplicated_vertices()
        mesh.remove_non_manifold_edges()
        mesh.remove_unreferenced_vertices()
        logger.info("Mesh cleaned (degenerate/duplicate geometry removed)")
        return mesh

    # ── Stage: spike removal ─────────────────────────────────────────────────

    def _remove_spikes(
        self,
        mesh: o3d.geometry.TriangleMesh,
        max_aspect_ratio: float = 15.0,
    ) -> o3d.geometry.TriangleMesh:
        """
        Remove needle/spike triangles at the mesh silhouette boundary.

        Gaussian Splatting meshes have sharp boundary spikes where the
        Gaussians end abruptly.  These appear as jagged/spiky edges in
        the viewer.  We detect them by aspect ratio: a needle triangle has
        one very long edge relative to its shortest edge.
        Threshold 15x catches more silhouette needles than 20x while
        still preserving legitimate elongated triangles on curved surfaces.
        """
        vertices = np.asarray(mesh.vertices)
        triangles = np.asarray(mesh.triangles)

        v0 = vertices[triangles[:, 0]]
        v1 = vertices[triangles[:, 1]]
        v2 = vertices[triangles[:, 2]]

        e0 = np.linalg.norm(v1 - v0, axis=1)
        e1 = np.linalg.norm(v2 - v1, axis=1)
        e2 = np.linalg.norm(v0 - v2, axis=1)

        edges = np.stack([e0, e1, e2], axis=1)
        max_edge = edges.max(axis=1)
        min_edge = edges.min(axis=1).clip(min=1e-8)
        aspect = max_edge / min_edge

        spike_mask = aspect > max_aspect_ratio
        n_spikes = int(spike_mask.sum())

        if n_spikes > 0:
            mesh.remove_triangles_by_mask(spike_mask)
            mesh.remove_unreferenced_vertices()
            logger.info(
                f"Removed {n_spikes} spike/needle triangles (aspect > {max_aspect_ratio}x)"
            )
        else:
            logger.info("No spike triangles found")

        return mesh

    # ── Stage: hole fill ─────────────────────────────────────────────────────

    def _fill_holes(self, mesh: o3d.geometry.TriangleMesh) -> o3d.geometry.TriangleMesh:
        """
        Fill holes and always fix normals/winding using trimesh.
        Converts O3D → trimesh → repair → O3D.
        Saves vertex colors before repair and restores them after, because
        trimesh's fill_holes can add/reindex vertices which invalidates
        the visual's color array.
        """
        if not mesh.is_watertight():
            logger.info("Mesh is not watertight — attempting hole fill")
        try:
            # ── Save colors before repair ──────────────────────────────
            saved_colors = None
            n_verts_before = len(mesh.vertices)
            if mesh.has_vertex_colors():
                saved_colors = np.asarray(mesh.vertex_colors).copy()  # (N, 3) float

            tm = self._o3d_to_trimesh(mesh)
            trimesh.repair.fix_normals(tm)
            trimesh.repair.fix_winding(tm)
            trimesh.repair.fill_holes(tm)
            mesh = self._trimesh_to_o3d(tm)

            # ── Restore colors if they were lost during repair ─────────
            # fill_holes can add new vertices; if so, we interpolate colors
            # for the new ones via KNN from the original mesh vertices.
            n_verts_after = len(mesh.vertices)
            if saved_colors is not None and not mesh.has_vertex_colors():
                logger.info(
                    f"Restoring {len(saved_colors)} vertex colors after repair "
                    f"({n_verts_before} → {n_verts_after} verts)"
                )
                if n_verts_after == n_verts_before:
                    mesh.vertex_colors = o3d.utility.Vector3dVector(saved_colors)
                else:
                    # Build a temporary point cloud with old colors, then
                    # KNN-interpolate onto the new (possibly extended) vertices.
                    old_pcd = o3d.geometry.PointCloud()
                    # We need the original vertex positions; get them from saved mesh.
                    # Since we only have colors, approximate with new verts for new points
                    # by clipping index and using nearest saved color.
                    # Simple fallback: assign mean color to all new vertices.
                    mean_color = saved_colors.mean(axis=0)
                    new_colors = np.tile(mean_color, (n_verts_after, 1))
                    new_colors[:n_verts_before] = saved_colors[:min(n_verts_before, n_verts_after)]
                    mesh.vertex_colors = o3d.utility.Vector3dVector(new_colors)

            logger.info("Normals/winding fixed, holes filled")
        except Exception as e:
            logger.warning(f"Mesh repair failed (non-critical): {e}")

        return mesh

    # ── Stage: subdivision ─────────────────────────────────────────────────────

    def _subdivide(self, mesh: o3d.geometry.TriangleMesh) -> o3d.geometry.TriangleMesh:
        """
        One pass of Loop subdivision to redistribute triangles adaptively.

        Loop subdivision doubles the triangle count and positions new vertices
        on a smooth limit surface.  After subdivision, quadric-error decimation
        preserves MORE faces in high-curvature regions (face, ears, fingers)
        and aggressively simplifies low-curvature flat areas (back, torso sides).
        This produces a mesh whose triangle budget is spent where it matters most.

        Only runs when the mesh has fewer than 400k faces to keep memory safe.
        """
        n_faces = len(mesh.triangles)
        if n_faces > 400_000:
            logger.info(f"Subdivision skipped: mesh already has {n_faces} faces")
            return mesh

        logger.info(f"Loop subdivision: {n_faces} → ~{n_faces * 4} faces...")
        mesh = mesh.subdivide_loop(number_of_iterations=1)
        logger.info(f"Subdivision result: {len(mesh.triangles)} faces ({len(mesh.vertices)} verts)")
        mesh.compute_vertex_normals()
        return mesh

    # ── Stage: smoothing ─────────────────────────────────────────────────────

    def _smooth(self, mesh: o3d.geometry.TriangleMesh) -> o3d.geometry.TriangleMesh:
        """Apply Taubin smoothing with face/head geometry protection.

        The face and head are the highest-detail region of the avatar. Global
        smoothing erodes the nose bridge, lip contour, eye sockets and chin.
        This method applies Taubin to the full mesh but then blends the head
        vertices back toward their original (pre-smoothing) positions so that
        fine facial geometry is preserved while body surface noise is removed.

        Protection schedule (measured from the top of the mesh):
            top 0-22% of height  -> head/face: 100% original positions kept
            22-38%               -> neck/shoulder: linear blend 1.0 -> 0.0
            38-100%              -> body: fully smoothed
        """
        # Save original vertex positions before any smoothing
        verts_original = np.asarray(mesh.vertices, dtype=np.float64).copy()

        # Apply volume-preserving Taubin smoothing to the whole mesh
        mesh = mesh.filter_smooth_taubin(
            number_of_iterations=self.smoothing_iterations,
            lambda_filter=self.smoothing_lambda,
            mu=-0.53,
        )
        verts_smoothed = np.asarray(mesh.vertices, dtype=np.float64).copy()

        # ── Head / face geometry protection ───────────────────────────────
        # Detect height axis: largest bounding-box extent (Y for upright LHM output)
        extent_per_axis = verts_original.max(axis=0) - verts_original.min(axis=0)
        h_axis = int(np.argmax(extent_per_axis))   # 0=X, 1=Y (typical), 2=Z

        h_vals = verts_original[:, h_axis]
        h_min, h_max = h_vals.min(), h_vals.max()
        h_range = h_max - h_min

        # Protection zone boundaries as fractions of total body height from top
        HEAD_FRACTION  = 0.22   # top 22% = head + face: fully protected
        BLEND_FRACTION = 0.38   # 22-38% = neck/shoulder: linear blend

        head_boundary  = h_max - HEAD_FRACTION  * h_range   # lower edge of face zone
        blend_boundary = h_max - BLEND_FRACTION * h_range   # lower edge of blend zone

        # protect[i] = 1.0 -> keep original position (face/head, no smoothing)
        # protect[i] = 0.0 -> use smoothed position (body, full smoothing)
        protect = np.clip(
            (h_vals - blend_boundary) / (head_boundary - blend_boundary + 1e-9),
            0.0, 1.0,
        )

        # Blend: face keeps original, body keeps smoothed, neck/shoulder transitions
        verts_final = (
            verts_original * protect[:, None]
            + verts_smoothed * (1.0 - protect[:, None])
        )
        mesh.vertices = o3d.utility.Vector3dVector(verts_final)
        mesh.compute_vertex_normals()

        n_protected  = int((protect > 0.99).sum())
        n_transition = int(((protect > 0.01) & (protect < 0.99)).sum())
        logger.info(
            f"Taubin smoothing: {self.smoothing_iterations} iter, "
            f"\u03bb={self.smoothing_lambda}, \u03bc=-0.53 "
            f"| face protected: {n_protected} verts, blend: {n_transition} verts"
        )
        return mesh

    # ── Stage: decimation ────────────────────────────────────────────────────

    def _decimate(self, mesh: o3d.geometry.TriangleMesh) -> o3d.geometry.TriangleMesh:
        """Reduce face count to target for web performance."""
        n_faces = len(mesh.triangles)
        if n_faces <= self.target_faces:
            logger.info(
                f"Mesh has {n_faces} faces (\u2264 target {self.target_faces}) — skip decimation"
            )
            return mesh

        logger.info(f"Decimating: {n_faces} \u2192 {self.target_faces} faces")
        mesh = mesh.simplify_quadric_decimation(target_number_of_triangles=self.target_faces)
        actual = len(mesh.triangles)
        logger.info(f"Decimation result: {actual} faces")
        mesh.compute_vertex_normals()
        return mesh

    # ── Stage: recolor ────────────────────────────────────────────────────────

    def _recolor_from_pcd(
        self,
        source_pcd: o3d.geometry.PointCloud,
        mesh: o3d.geometry.TriangleMesh,
        k_neighbors: int = 5,
    ) -> o3d.geometry.TriangleMesh:
        """
        Re-transfer vertex colors from the original Gaussian point cloud to the
        mesh using vectorized k-nearest-neighbor interpolation via scipy.

        Called after smoothing + decimation to restore accurate colors at the
        final vertex positions.  Uses k=3 with inverse-distance^6 weighting
        (= dist_sq^3) for the sharpest possible color boundaries
        (e.g. jacket edge vs. jeans).

        IMPORTANT: call this BEFORE _normalize_transform so both the mesh and
        source_pcd are in the same LHM world-space coordinate system.
        """
        from scipy.spatial import cKDTree

        src_pts    = np.asarray(source_pcd.points,  dtype=np.float64)
        src_colors = np.asarray(source_pcd.colors,  dtype=np.float64)
        dst_pts    = np.asarray(mesh.vertices,       dtype=np.float64)

        tree = cKDTree(src_pts)
        dists, idxs = tree.query(dst_pts, k=k_neighbors, workers=-1)  # (N, k)

        if dists.ndim == 1:
            dists = dists[:, None]
            idxs  = idxs[:,  None]

        eps     = 1e-12
        weights = 1.0 / (dists ** 6 + eps)

        coincident             = dists[:, 0] < 1e-10
        weights[coincident]    = 0.0
        weights[coincident, 0] = 1.0
        weights /= weights.sum(axis=1, keepdims=True)

        mesh_colors = (src_colors[idxs] * weights[:, :, None]).sum(axis=1)
        mesh.vertex_colors = o3d.utility.Vector3dVector(np.clip(mesh_colors, 0.0, 1.0))
        logger.info("Post-decimation color re-transfer complete")
        return mesh

    # ── Stage: normalize ─────────────────────────────────────────────────────

    def _normalize_transform(self, mesh: o3d.geometry.TriangleMesh) -> o3d.geometry.TriangleMesh:
        """
        Center the mesh at origin and normalize scale.
        The avatar should be roughly centered and fit within a unit sphere
        for consistent web viewer behaviour.
        """
        center = mesh.get_center()
        mesh.translate(-center)

        bbox = mesh.get_axis_aligned_bounding_box()
        extent = bbox.get_extent()
        max_extent = float(extent.max())
        if max_extent > 0:
            scale_factor = 2.0 / max_extent
            mesh.scale(scale_factor, center=[0, 0, 0])

        mesh.compute_vertex_normals()
        logger.info("Normalized transform: centered at origin, max extent scaled to 2.0")
        return mesh

    # ── Conversion helpers ───────────────────────────────────────────────────

    @staticmethod
    def _o3d_to_trimesh(mesh: o3d.geometry.TriangleMesh) -> trimesh.Trimesh:
        """Convert Open3D TriangleMesh to trimesh.Trimesh."""
        vertices = np.asarray(mesh.vertices)
        triangles = np.asarray(mesh.triangles)

        tm = trimesh.Trimesh(vertices=vertices, faces=triangles, process=False)

        if mesh.has_vertex_colors():
            vc = np.asarray(mesh.vertex_colors)
            rgba = np.ones((len(vc), 4), dtype=np.uint8)
            rgba[:, :3] = (vc * 255).astype(np.uint8)
            tm.visual = trimesh.visual.ColorVisuals(mesh=tm, vertex_colors=rgba)

        return tm

    @staticmethod
    def _trimesh_to_o3d(tm: trimesh.Trimesh) -> o3d.geometry.TriangleMesh:
        """Convert trimesh.Trimesh to Open3D TriangleMesh, preserving vertex colors."""
        mesh = o3d.geometry.TriangleMesh()
        mesh.vertices = o3d.utility.Vector3dVector(np.asarray(tm.vertices, dtype=np.float64))
        mesh.triangles = o3d.utility.Vector3iVector(np.asarray(tm.faces, dtype=int))

        if tm.visual is not None:
            rgba = None
            try:
                if isinstance(tm.visual, trimesh.visual.ColorVisuals):
                    # Direct access — ColorVisuals has no .to_color() method.
                    rgba = tm.visual.vertex_colors  # uint8 RGBA (N, 4)
                else:
                    # TextureVisuals or other — try generic conversion.
                    rgba = tm.visual.to_color().vertex_colors
            except Exception as e:
                logger.debug(f"Color conversion in _trimesh_to_o3d: {e}")

            if rgba is not None and len(rgba) == len(tm.vertices):
                vc = np.asarray(rgba, dtype=np.float64)[:, :3] / 255.0
                mesh.vertex_colors = o3d.utility.Vector3dVector(np.clip(vc, 0.0, 1.0))

        mesh.compute_vertex_normals()
        return mesh

    # ── Logging helper ───────────────────────────────────────────────────────

    def _log_mesh_stats(self, mesh: o3d.geometry.TriangleMesh, label: str) -> None:
        """Log basic mesh statistics."""
        logger.info(
            f"[{label}] Vertices: {len(mesh.vertices)} | "
            f"Faces: {len(mesh.triangles)} | "
            f"Has colors: {mesh.has_vertex_colors()} | "
            f"Has normals: {mesh.has_vertex_normals()}"
        )
