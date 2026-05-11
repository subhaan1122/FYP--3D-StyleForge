"""
GLB exporter — converts the processed mesh to a web-ready .glb file.

GLB (Binary glTF) is the standard format for web 3D viewers.
Three.js, React Three Fiber, Babylon.js, and model-viewer all support it.

This module handles:
1. Vertex-color to texture-atlas baking (optional but recommended)
2. UV unwrapping via xatlas (or simple projection fallback)
3. Material creation (PBR metallic-roughness)
4. GLB binary export with embedded textures

The output GLB can be loaded directly in the React frontend
with THREE.GLTFLoader.
"""

import io
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import open3d as o3d
import trimesh
from PIL import Image

from app.config import settings
from app.utils.logger import logger
from app.utils.file_utils import get_file_size_mb


class GLBExporter:
    """
    Exports an Open3D TriangleMesh or trimesh.Trimesh to GLB format.

    Usage:
        exporter = GLBExporter()
        glb_path = exporter.export(mesh, "output/avatar.glb")
    """

    def __init__(
        self,
        atlas_resolution: Optional[int] = None,
        bake_texture: Optional[bool] = None,
        embed_textures: Optional[bool] = None,
    ):
        tex_cfg = settings.texture
        glb_cfg = settings.glb_export

        self.atlas_resolution = atlas_resolution if atlas_resolution is not None else tex_cfg.atlas_resolution
        self.bake_texture = bake_texture if bake_texture is not None else tex_cfg.bake_texture_atlas
        self.embed_textures = embed_textures if embed_textures is not None else glb_cfg.embed_textures
        self.max_size_warning_mb = glb_cfg.max_size_warning_mb

    # ── Public API ──────────────────────────────────────────────────────────

    def export(
        self,
        mesh: o3d.geometry.TriangleMesh,
        output_path: str | Path,
    ) -> Path:
        """
        Export the mesh as a GLB file.

        Parameters
        ----------
        mesh : processed Open3D TriangleMesh with vertex colors
        output_path : where to save the .glb file

        Returns
        -------
        Path to the generated .glb file
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Exporting GLB to: {output_path}")

        # Convert O3D → trimesh (preserving vertex colors)
        tm = self._o3d_to_trimesh(mesh)
        has_vertex_colors = (
            hasattr(tm.visual, 'vertex_colors') and tm.visual.vertex_colors is not None
        )
        logger.info(
            f"Mesh for GLB: {len(tm.vertices)} verts, {len(tm.faces)} faces, "
            f"has_vertex_colors={has_vertex_colors}"
        )

        if self.bake_texture and has_vertex_colors:
            # Bake vertex colors into a texture atlas for better
            # appearance in web viewers
            try:
                baked = self._bake_vertex_colors_to_texture(tm)
                if baked is not None:
                    tm = baked
            except Exception as e:
                logger.warning(f"Texture baking failed ({e}), using vertex colors directly")

        # If we still have ColorVisuals (not baked to texture), ensure
        # it has a basic PBR material so Three.js renders it properly.
        if isinstance(tm.visual, trimesh.visual.ColorVisuals):
            # Keep vertex colors; set a neutral PBR material so metalness/roughness
            # don't override the colours.  doubleSided=True so the GLTF loader
            # renders back faces without needing the Three.js manual override.
            tm.visual.material = trimesh.visual.material.PBRMaterial(
                metallicFactor=0.0,
                roughnessFactor=0.9,
                doubleSided=True,
            )

        # Create a trimesh Scene (required for GLB export)
        scene = trimesh.Scene(geometry={"avatar": tm})

        # Export to GLB
        glb_data = scene.export(file_type="glb")

        with open(output_path, "wb") as f:
            f.write(glb_data)

        # Validate
        size_mb = get_file_size_mb(output_path)
        logger.info(f"GLB exported: {output_path} ({size_mb:.2f} MB)")

        if size_mb > self.max_size_warning_mb:
            logger.warning(
                f"GLB file is {size_mb:.1f} MB — exceeds {self.max_size_warning_mb} MB warning threshold. "
                "Consider increasing mesh decimation or reducing texture resolution."
            )

        return output_path

    def export_from_trimesh(
        self,
        tm: trimesh.Trimesh,
        output_path: str | Path,
    ) -> Path:
        """Convenience method: export a trimesh.Trimesh directly."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        scene = trimesh.Scene(geometry={"avatar": tm})
        glb_data = scene.export(file_type="glb")

        with open(output_path, "wb") as f:
            f.write(glb_data)

        size_mb = get_file_size_mb(output_path)
        logger.info(f"GLB exported: {output_path} ({size_mb:.2f} MB)")
        return output_path

    # ── Texture Baking ──────────────────────────────────────────────────────

    def _bake_vertex_colors_to_texture(
        self, tm: trimesh.Trimesh
    ) -> trimesh.Trimesh:
        """
        Bake per-vertex colors into a UV-mapped texture atlas.

        This produces much better results in web viewers than raw vertex colors
        because:
        - Three.js renders vertex colors with flat/Gouraud shading
        - Texture-mapped meshes look smoother and more realistic
        - Better PBR material support

        The UV unwrapping uses a simple per-face projection.
        For production quality, one could use xatlas, but this works well
        enough for human avatars.
        """
        logger.info(
            f"Baking vertex colors to texture atlas "
            f"({self.atlas_resolution}×{self.atlas_resolution})"
        )

        try:
            # Try xatlas-based UV unwrapping first (best quality)
            tm_uv = self._unwrap_with_xatlas(tm)
        except Exception as e:
            logger.warning(f"xatlas UV unwrapping failed: {e}")
            logger.info("Falling back to simple UV projection")
            tm_uv = self._unwrap_simple(tm)

        if tm_uv is None:
            logger.warning("UV unwrapping failed — exporting with vertex colors only")
            return tm

        return tm_uv

    def _unwrap_with_xatlas(self, tm: trimesh.Trimesh) -> Optional[trimesh.Trimesh]:
        """
        UV unwrap using xatlas (if installed).
        xatlas produces high-quality UV maps with minimal distortion.
        """
        try:
            import xatlas  # type: ignore
        except ImportError:
            raise ImportError(
                "xatlas not installed. Install with: pip install xatlas"
            )

        vertices = tm.vertices.astype(np.float32)
        faces = tm.faces.astype(np.uint32)

        # Run xatlas
        atlas = xatlas.Atlas()
        atlas.add_mesh(vertices, faces)
        atlas.generate()
        vmapping, new_faces, new_uvs = atlas[0]

        # Remap vertices and colors
        new_vertices = vertices[vmapping]

        # Get vertex colors
        if hasattr(tm.visual, 'vertex_colors') and tm.visual.vertex_colors is not None:
            old_colors = np.array(tm.visual.vertex_colors)
        else:
            old_colors = np.ones((len(vertices), 4), dtype=np.uint8) * 180

        new_colors = old_colors[vmapping]

        # Create texture atlas from vertex colors
        texture_image = self._create_texture_atlas(
            new_vertices, new_faces, new_uvs, new_colors
        )

        # Build new trimesh with UV coordinates and texture
        material = trimesh.visual.material.PBRMaterial(
            baseColorTexture=texture_image,
            metallicFactor=0.0,
            roughnessFactor=0.8,
        )

        visual = trimesh.visual.TextureVisuals(
            uv=new_uvs,
            material=material,
        )

        result = trimesh.Trimesh(
            vertices=new_vertices,
            faces=new_faces,
            visual=visual,
            process=False,
        )

        logger.info("xatlas UV unwrapping complete")
        return result

    def _unwrap_simple(self, tm: trimesh.Trimesh) -> Optional[trimesh.Trimesh]:
        """
        Simple UV unwrapping fallback using cylindrical projection.
        Suitable for human-shaped meshes (roughly upright, cylindrical body).
        """
        try:
            vertices = np.array(tm.vertices)
            faces = np.array(tm.faces)

            # Get vertex colors before creating new visual
            if hasattr(tm.visual, 'vertex_colors') and tm.visual.vertex_colors is not None:
                vertex_colors = np.array(tm.visual.vertex_colors)
            else:
                vertex_colors = np.ones((len(vertices), 4), dtype=np.uint8) * 180

            # Cylindrical projection UV
            # Assume Y-up orientation (standard for human models)
            center = vertices.mean(axis=0)
            v_centered = vertices - center

            # Theta: angle in XZ plane
            theta = np.arctan2(v_centered[:, 0], v_centered[:, 2])
            u = (theta + np.pi) / (2 * np.pi)  # [0, 1]

            # V: normalized height along Y axis
            y_min, y_max = v_centered[:, 1].min(), v_centered[:, 1].max()
            y_range = y_max - y_min
            if y_range < 1e-8:
                y_range = 1.0
            v = (v_centered[:, 1] - y_min) / y_range  # [0, 1]

            uvs = np.stack([u, v], axis=-1).astype(np.float64)

            # Create texture atlas from vertex colors
            texture_image = self._create_texture_atlas(
                vertices, faces, uvs, vertex_colors
            )

            material = trimesh.visual.material.PBRMaterial(
                baseColorTexture=texture_image,
                metallicFactor=0.0,
                roughnessFactor=0.8,
            )

            visual = trimesh.visual.TextureVisuals(
                uv=uvs,
                material=material,
            )

            result = trimesh.Trimesh(
                vertices=vertices,
                faces=faces,
                visual=visual,
                process=False,
            )

            logger.info("Simple cylindrical UV unwrapping complete")
            return result

        except Exception as e:
            logger.error(f"Simple UV unwrapping failed: {e}")
            return None

    def _create_texture_atlas(
        self,
        vertices: np.ndarray,
        faces: np.ndarray,
        uvs: np.ndarray,
        vertex_colors: np.ndarray,
    ) -> Image.Image:
        """
        Rasterize vertex colors into a texture atlas image.

        For each triangle, we sample the vertex colors and paint them
        into UV space to create the texture.
        """
        import cv2

        res = self.atlas_resolution
        texture = np.zeros((res, res, 3), dtype=np.uint8)

        # Ensure colors are uint8 [0, 255]
        if vertex_colors.dtype == np.float64 or vertex_colors.dtype == np.float32:
            if vertex_colors.max() <= 1.0:
                vc = (np.clip(vertex_colors[:, :3], 0, 1) * 255).astype(np.uint8)
            else:
                vc = np.clip(vertex_colors[:, :3], 0, 255).astype(np.uint8)
        else:
            vc = vertex_colors[:, :3].astype(np.uint8)

        for face in faces:
            # Get UV coordinates for this triangle
            uv_tri = uvs[face]  # (3, 2)
            color_tri = vc[face]  # (3, 3)

            # Convert UV to pixel coordinates
            px = np.clip((uv_tri[:, 0] * (res - 1)).astype(np.int32), 0, res - 1)
            py = np.clip(((1.0 - uv_tri[:, 1]) * (res - 1)).astype(np.int32), 0, res - 1)

            # Use average color for this face (fast cv2.fillPoly approach)
            avg_color = color_tri.mean(axis=0).astype(np.uint8)
            pts = np.array([[px[0], py[0]], [px[1], py[1]], [px[2], py[2]]], dtype=np.int32)
            cv2.fillPoly(texture, [pts], color=tuple(int(c) for c in avg_color))

        # Simple dilation to fill gaps between triangle edges
        texture = self._dilate_texture(texture, iterations=3)

        return Image.fromarray(texture, mode="RGB")

    @staticmethod
    def _dilate_texture(texture: np.ndarray, iterations: int = 3) -> np.ndarray:
        """
        Dilate the texture to fill 1-pixel gaps between triangle edges.
        Uses a simple kernel-based expansion.
        """
        import cv2

        mask = (texture.sum(axis=-1) == 0).astype(np.uint8)
        kernel = np.ones((3, 3), np.uint8)

        for _ in range(iterations):
            dilated = cv2.dilate(texture, kernel, iterations=1)
            # Only fill where original was empty
            fill_mask = mask[:, :, np.newaxis].astype(bool)
            texture = np.where(fill_mask, dilated, texture)
            mask = (texture.sum(axis=-1) == 0).astype(np.uint8)

        return texture

    # ── O3D → trimesh ───────────────────────────────────────────────────────

    @staticmethod
    def _o3d_to_trimesh(mesh: o3d.geometry.TriangleMesh) -> trimesh.Trimesh:
        """Convert Open3D TriangleMesh to trimesh, preserving vertex colors and normals."""
        vertices = np.asarray(mesh.vertices)
        faces = np.asarray(mesh.triangles)

        vertex_colors = None
        if mesh.has_vertex_colors():
            vc = np.asarray(mesh.vertex_colors)
            rgba = np.ones((len(vc), 4), dtype=np.uint8) * 255
            rgba[:, :3] = (np.clip(vc, 0, 1) * 255).astype(np.uint8)
            vertex_colors = rgba

        # Carry over pre-computed vertex normals so Three.js gets smooth shading
        vertex_normals = None
        if mesh.has_vertex_normals():
            vertex_normals = np.asarray(mesh.vertex_normals).copy()

        tm = trimesh.Trimesh(
            vertices=vertices,
            faces=faces,
            vertex_normals=vertex_normals,
            vertex_colors=vertex_colors,
            process=False,
        )

        return tm
