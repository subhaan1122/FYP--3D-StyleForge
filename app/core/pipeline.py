"""
Main 3D Avatar Pipeline — orchestrates the full 2D image → GLB workflow.

This is the central module that ties everything together:
  1. Preprocess the 2D image (from the virtual try-on output)
  2. Run LHM inference → Gaussian Splatting PLY
  3. Convert Gaussians → triangulated mesh
  4. Process / optimize the mesh
  5. Export as GLB

The pipeline is designed to:
  - Run sequentially (to fit in 24 GB VRAM)
  - Clean up GPU memory between stages
  - Produce a single GLB file ready for the React frontend

Usage:
    from app.core.pipeline import Avatar3DPipeline

    pipeline = Avatar3DPipeline()
    result = pipeline.run("input_image.png", job_id="abc123")
    print(result["glb_path"])
"""

import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings
from app.core.gpu_manager import GPUManager, get_gpu_manager
from app.core.lhm_wrapper import LHMWrapper
from app.core.lhm_remote_wrapper import LHMRemoteWrapper
from app.core.hitem3d_client import HiItem3DClient
from app.core.gaussian_to_mesh import GaussianToMesh
from app.core.mesh_processor import MeshProcessor
from app.core.glb_exporter import GLBExporter
from app.utils.logger import logger
from app.utils.file_utils import (
    ensure_dir,
    generate_job_id,
    job_output_dir,
    get_file_size_mb,
)
from app.utils.image_utils import preprocess_for_lhm


class PipelineResult:
    """Container for pipeline output and metadata."""

    def __init__(self):
        self.job_id: str = ""
        self.status: str = "pending"  # pending | processing | completed | failed
        self.glb_path: Optional[Path] = None
        self.ply_path: Optional[Path] = None
        self.video_path: Optional[Path] = None   # set when remote LHM returns MP4
        self.preprocessed_image_path: Optional[Path] = None
        self.total_time_seconds: float = 0.0
        self.stage_times: Dict[str, float] = {}
        self.mesh_stats: Dict[str, Any] = {}
        self.error: Optional[str] = None

    @property
    def output_path(self) -> Optional[Path]:
        """Return whichever output was produced (GLB or video)."""
        return self.glb_path or self.video_path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "glb_path": str(self.glb_path) if self.glb_path else None,
            "ply_path": str(self.ply_path) if self.ply_path else None,
            "video_path": str(self.video_path) if self.video_path else None,
            "output_type": "video" if self.video_path else "glb",
            "preprocessed_image": str(self.preprocessed_image_path) if self.preprocessed_image_path else None,
            "total_time_seconds": round(self.total_time_seconds, 2),
            "stage_times": {k: round(v, 2) for k, v in self.stage_times.items()},
            "mesh_stats": self.mesh_stats,
            "error": self.error,
        }


class Avatar3DPipeline:
    """
    End-to-end 3D avatar generation pipeline.

    Accepts a 2D image (the final output from the 2D virtual try-on pipeline)
    and produces a web-ready GLB file.
    """

    def __init__(self):
        self.gpu: GPUManager = get_gpu_manager(
            device=settings.gpu.device,
            max_vram_gb=settings.gpu.max_vram_gb,
        )

        # Select 3D backend: Hi3D cloud API, remote Gradio Space, or local LHM
        use_hitem3d = getattr(settings.lhm, "use_hitem3d", False)
        use_remote = getattr(settings.lhm, "use_remote_api", False)

        if use_hitem3d:
            logger.info("3D backend: Hi3D cloud API (hitem3d.ai) — no local GPU needed")
            self.hitem3d_client: Optional[HiItem3DClient] = HiItem3DClient()
            self.lhm: Optional[LHMRemoteWrapper | LHMWrapper] = None
        else:
            self.hitem3d_client = None
            if use_remote:
                logger.info(
                    "LHM backend: REMOTE (HuggingFace Space — no local weights needed)"
                )
                self.lhm: Optional[LHMRemoteWrapper | LHMWrapper] = LHMRemoteWrapper(
                    space=getattr(settings.lhm, "remote_space", "3DAIGC/LHM"),
                )
            else:
                logger.info("LHM backend: LOCAL (subprocess)")
                self.lhm = None  # lazy-initialised on first run

        self.gaussian_to_mesh = GaussianToMesh()
        self.mesh_processor = MeshProcessor()
        self.glb_exporter = GLBExporter()

        self._output_base = Path(settings.paths.output_dir)
        self._temp_base = Path(settings.paths.temp_dir)

        # Ensure directories exist
        ensure_dir(self._output_base)
        ensure_dir(self._temp_base)

        logger.info("Avatar3DPipeline initialized")

    # ── Main Entry Point ────────────────────────────────────────────────────

    def run(
        self,
        image_path: str | Path,
        job_id: Optional[str] = None,
        skip_preprocessing: bool = False,
    ) -> PipelineResult:
        """
        Run the full 3D pipeline.

        Parameters
        ----------
        image_path : path to the 2D image (from the virtual try-on output)
        job_id : optional identifier; auto-generated if not provided
        skip_preprocessing : set True if the image is already preprocessed
                             for LHM (512×512, centered, white background)

        Returns
        -------
        PipelineResult with paths to outputs and timing metadata
        """
        result = PipelineResult()
        result.job_id = job_id or generate_job_id()
        result.status = "processing"

        image_path = Path(image_path).resolve()
        output_dir = job_output_dir(self._output_base, result.job_id)
        temp_dir = job_output_dir(self._temp_base, result.job_id)

        overall_start = time.time()
        logger.info(f"=== Pipeline START | Job: {result.job_id} ===")
        logger.info(f"Input image: {image_path}")
        logger.info(f"Output dir:  {output_dir}")

        # ── Hi3D cloud API path (bypasses all local stages) ──────────────
        if self.hitem3d_client is not None:
            return self._run_hitem3d(image_path, result, output_dir, overall_start)

        try:
            # ── Stage 1: Preprocessing ──────────────────────────────────
            t0 = time.time()

            # Remote mode: the HuggingFace Space has its own internal
            # preprocessing (SAM2 segmentation + pose estimator).
            # Sending a white-background 896×896 square confuses its pose
            # detector and causes a RuntimeError inside core_fn.
            # Solution: skip local preprocessing; send the original image.
            is_remote = getattr(self.lhm, "output_type", "ply") == "video"

            if skip_preprocessing or is_remote:
                preprocessed = image_path
                if is_remote:
                    logger.info("Remote mode: skipping local preprocessing — Space handles it internally")
                else:
                    logger.info("Skipping preprocessing (already prepared)")
            else:
                preprocessed = preprocess_for_lhm(
                    image_path=image_path,
                    output_path=temp_dir / "preprocessed.png",
                    target_size=settings.lhm.input_resolution,
                )
            result.preprocessed_image_path = preprocessed
            result.stage_times["preprocessing"] = time.time() - t0

            # ── Stage 2: LHM Inference ──────────────────────────────────
            t0 = time.time()
            self.gpu.log_vram("Before LHM stage")

            # Lazy-initialise local wrapper (remote wrapper is created in __init__)
            if self.lhm is None:
                self.lhm = LHMWrapper()

            self.lhm.load_model()
            lhm_output = self.lhm.run_inference(
                image_path=preprocessed,
                output_dir=temp_dir / "lhm_output",
            )
            result.stage_times["lhm_inference"] = time.time() - t0

            # Free LHM from GPU memory before next stage
            # (remote wrapper has nothing to free, but unload_model() is safe)
            if settings.gpu.aggressive_cleanup:
                self.lhm.unload_model()
                self.gpu.cleanup("After LHM inference")

            # ── Remote mode: LHM returned a video — skip mesh stages ────
            lhm_output_type = getattr(self.lhm, "output_type", "ply")
            if lhm_output_type == "video":
                dest_video = output_dir / f"{result.job_id}.mp4"
                import shutil as _shutil
                _shutil.copy2(lhm_output, dest_video)
                result.video_path = dest_video
                result.status = "completed"
                result.total_time_seconds = time.time() - overall_start
                logger.info(f"=== Remote Pipeline COMPLETE | Job: {result.job_id} ===")
                logger.info(f"Video: {result.video_path}")
                logger.info(f"Total time: {result.total_time_seconds:.2f}s")
                return result

            result.ply_path = lhm_output

            # ── Stage 3: Gaussian → Mesh ────────────────────────────────
            t0 = time.time()
            self.gpu.log_vram("Before mesh reconstruction")

            raw_mesh = self.gaussian_to_mesh.convert(result.ply_path)

            # Save intermediate mesh (OBJ for debugging)
            intermediate_mesh_path = temp_dir / "raw_mesh.ply"
            self.gaussian_to_mesh.save_mesh(raw_mesh, intermediate_mesh_path)

            result.stage_times["mesh_reconstruction"] = time.time() - t0

            # ── Stage 4: Mesh Processing ────────────────────────────────
            t0 = time.time()

            # Pass the clean Gaussian point cloud so MeshProcessor can
            # re-transfer colors after smoothing+decimation move vertex positions.
            processed_mesh = self.mesh_processor.process(
                raw_mesh,
                source_pcd=self.gaussian_to_mesh.source_pcd,
            )

            result.mesh_stats = {
                "vertices": len(processed_mesh.vertices),
                "faces": len(processed_mesh.triangles),
                "has_colors": processed_mesh.has_vertex_colors(),
                "has_normals": processed_mesh.has_vertex_normals(),
            }
            result.stage_times["mesh_processing"] = time.time() - t0

            # ── Stage 5: GLB Export ─────────────────────────────────────
            t0 = time.time()

            glb_path = output_dir / f"{result.job_id}.glb"
            self.glb_exporter.export(processed_mesh, glb_path)

            result.glb_path = glb_path
            result.mesh_stats["glb_size_mb"] = round(get_file_size_mb(glb_path), 2)
            result.stage_times["glb_export"] = time.time() - t0

            # ── Done ────────────────────────────────────────────────────
            result.status = "completed"
            result.total_time_seconds = time.time() - overall_start

            logger.info(f"=== Pipeline COMPLETE | Job: {result.job_id} ===")
            logger.info(f"GLB: {result.glb_path}")
            logger.info(f"Total time: {result.total_time_seconds:.2f}s")
            logger.info(f"Stage times: {result.stage_times}")
            logger.info(f"Mesh stats: {result.mesh_stats}")

        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            result.total_time_seconds = time.time() - overall_start

            logger.error(f"Pipeline FAILED | Job: {result.job_id} | Error: {e}")
            import traceback
            logger.error(traceback.format_exc())

        finally:
            # Always cleanup GPU
            self.gpu.cleanup("Pipeline end")

        return result

    # ── Hi3D Cloud API path ─────────────────────────────────────────────────

    def _run_hitem3d(
        self,
        image_path: Path,
        result: PipelineResult,
        output_dir: Path,
        overall_start: float,
    ) -> PipelineResult:
        """
        Call the Hi3D cloud API to generate the GLB directly from a 2D image.
        No local GPU work is performed — the cloud model handles everything.
        """
        ensure_dir(output_dir)
        glb_path = output_dir / f"{result.job_id}.glb"

        try:
            t0 = time.time()
            self.hitem3d_client.generate_glb(
                image_path=image_path,
                output_path=glb_path,
            )
            result.stage_times["hitem3d_api"] = time.time() - t0

            result.glb_path = glb_path
            result.mesh_stats["glb_size_mb"] = round(get_file_size_mb(glb_path), 2)
            result.status = "completed"
            result.total_time_seconds = time.time() - overall_start

            logger.info(f"=== Hi3D Pipeline COMPLETE | Job: {result.job_id} ===")
            logger.info(f"GLB: {result.glb_path} ({result.mesh_stats['glb_size_mb']:.1f} MB)")
            logger.info(f"Total time: {result.total_time_seconds:.2f}s")

        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            result.total_time_seconds = time.time() - overall_start

            logger.error(f"Hi3D Pipeline FAILED | Job: {result.job_id} | Error: {e}")
            import traceback
            logger.error(traceback.format_exc())

        return result

    # ── Convenience: Run from PLY ───────────────────────────────────────────

    def run_from_ply(
        self,
        ply_path: str | Path,
        job_id: Optional[str] = None,
    ) -> PipelineResult:
        """
        Run the pipeline starting from an existing LHM PLY output.
        Skips LHM inference — useful for testing or when you already
        have the PLY file from a previous LHM run.

        Parameters
        ----------
        ply_path : path to the Gaussian Splatting PLY from LHM
        job_id : optional identifier

        Returns
        -------
        PipelineResult
        """
        result = PipelineResult()
        result.job_id = job_id or generate_job_id()
        result.status = "processing"
        result.ply_path = Path(ply_path)

        output_dir = job_output_dir(self._output_base, result.job_id)
        temp_dir = job_output_dir(self._temp_base, result.job_id)

        overall_start = time.time()
        logger.info(f"=== Pipeline (from PLY) START | Job: {result.job_id} ===")
        logger.info(f"Input PLY: {ply_path}")

        try:
            # ── Stage 3: Gaussian → Mesh ────────────────────────────────
            t0 = time.time()
            raw_mesh = self.gaussian_to_mesh.convert(ply_path)
            self.gaussian_to_mesh.save_mesh(raw_mesh, temp_dir / "raw_mesh.ply")
            result.stage_times["mesh_reconstruction"] = time.time() - t0

            # ── Stage 4: Mesh Processing ────────────────────────────────
            t0 = time.time()
            processed_mesh = self.mesh_processor.process(
                raw_mesh,
                source_pcd=self.gaussian_to_mesh.source_pcd,
            )
            result.mesh_stats = {
                "vertices": len(processed_mesh.vertices),
                "faces": len(processed_mesh.triangles),
                "has_colors": processed_mesh.has_vertex_colors(),
            }
            result.stage_times["mesh_processing"] = time.time() - t0

            # ── Stage 5: GLB Export ─────────────────────────────────────
            t0 = time.time()
            glb_path = output_dir / f"{result.job_id}.glb"
            self.glb_exporter.export(processed_mesh, glb_path)

            result.glb_path = glb_path
            result.mesh_stats["glb_size_mb"] = round(get_file_size_mb(glb_path), 2)
            result.stage_times["glb_export"] = time.time() - t0

            result.status = "completed"
            result.total_time_seconds = time.time() - overall_start

            logger.info(f"=== Pipeline (from PLY) COMPLETE ===")
            logger.info(f"GLB: {result.glb_path}")

        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            result.total_time_seconds = time.time() - overall_start
            logger.error(f"Pipeline FAILED: {e}")
            import traceback
            logger.error(traceback.format_exc())

        finally:
            self.gpu.cleanup("Pipeline end")

        return result

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Release all resources."""
        if self.lhm is not None:
            self.lhm.unload_model()
            self.lhm = None
        self.gpu.cleanup("Full pipeline cleanup")
        logger.info("Pipeline resources released")
