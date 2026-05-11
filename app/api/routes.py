"""
FastAPI routes for the 3D avatar generation service.

URL patterns match the frontend's API_ENDPOINTS contract:
  POST /api/v1/try-on/3d       — Generate GLB from a 2D try-on result image
  POST /api/v1/convert-ply     — Convert existing PLY to GLB (skip LHM)
  GET  /api/v1/status/{job_id} — Check job status (compatible w/ frontend polling)
  GET  /api/v1/download/{id}   — Download the generated GLB file
  GET  /health                 — Health check + GPU status

INTEGRATION ARCHITECTURE:
========================

  React Frontend (port 5173)
       │
       │  POST /api/v1/try-on/3d  { user_image, output_id, instruction, session_id }
       ▼
  2D Backend (port 5000)           ── proxy ──►  3D Service (port 5001)
       │                                              │
       │  has tryon_{output_id}.png                  │  reads that PNG via output_id
       │  in backend/outputs/                        │  runs LHM → mesh → GLB
       │                                              │  saves GLB in 3d/outputs/
       ▼                                              ▼
  forwards response to frontend              returns {success, job_id, download_url}

MODEL-AGNOSTIC DESIGN:
  • The 3D pipeline only needs a PNG image — it does NOT care which 2D model
    produced it (IDM-VTON, Gemini, Stable Diffusion, etc.)
  • If you swap the 2D model, the only contract is: the 2D output is saved as
    a PNG file and its output_id is passed to the 3D endpoint.
  • ZERO changes needed in this file when switching 2D models.
"""

import asyncio
import base64
from pathlib import Path
from typing import Optional

import torch
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.config import settings
from app.core.pipeline import Avatar3DPipeline, PipelineResult
from app.utils.file_utils import ensure_dir, generate_job_id
from app.utils.logger import logger

# No prefix — routes use full /api/v1/ paths to match the frontend exactly
router = APIRouter(tags=["3D Avatar"])

# ── Shared state ────────────────────────────────────────────────────────────
_pipeline: Optional[Avatar3DPipeline] = None
_job_store: dict[str, dict] = {}  # In-memory job status store


def _get_pipeline() -> Avatar3DPipeline:
    """Lazily initialize the pipeline singleton."""
    global _pipeline
    if _pipeline is None:
        _pipeline = Avatar3DPipeline()
    return _pipeline


def _save_result(result: PipelineResult) -> dict:
    """Save pipeline result and return the response dict."""
    data = result.to_dict()
    if (result.glb_path and result.glb_path.exists()) or \
       (result.video_path and result.video_path.exists()):
        data["download_url"] = f"/api/v1/download/{result.job_id}"
        data["glb_download_url"] = data["download_url"]
    _job_store[result.job_id] = data
    return data


def _find_2d_output_image(output_id: str) -> Optional[Path]:
    """
    Locate the 2D try-on output image from the 2D backend.
    The 2D backend saves files as: outputs/tryon_{output_id}.png

    MODEL-AGNOSTIC: regardless of whether IDM-VTON, Gemini, or any
    other model produced the image, this function finds it by output_id.

    Searches multiple directories to handle different startup configurations:
      - backend/outputs/ (when 2D backend CWD is styleforge/backend/)
      - outputs/         (when 2D backend CWD is styleforge/ root)
      - ../outputs/      (project root outputs)
    """
    project_root = Path(__file__).resolve().parent.parent.parent  # styleforge/

    # Build a list of candidate directories to search
    search_dirs: list[Path] = []

    # 1. Configured tryon_outputs_dir (from config.yaml)
    tryon_dir = Path(settings.integration.tryon_outputs_dir)
    if not tryon_dir.is_absolute():
        tryon_dir = (project_root / tryon_dir).resolve()
    search_dirs.append(tryon_dir)

    # 2. styleforge/outputs/ (if backend runs from project root)
    search_dirs.append((project_root / "outputs").resolve())

    # 3. Project workspace root outputs (d:\3D\outputs/)
    search_dirs.append((project_root.parent / "outputs").resolve())

    # 4. styleforge/backend/outputs/ (explicit)
    search_dirs.append((project_root / "backend" / "outputs").resolve())

    # 5. uploads directory
    search_dirs.append((project_root / "uploads").resolve())

    # De-duplicate while preserving order
    seen = set()
    unique_dirs = []
    for d in search_dirs:
        if d not in seen:
            seen.add(d)
            unique_dirs.append(d)

    # Search each directory for the output image
    filenames_to_try = [
        f"tryon_{output_id}.png",
        f"{output_id}.png",
        f"tryon_{output_id}.jpg",
        f"{output_id}.jpg",
    ]

    for search_dir in unique_dirs:
        if not search_dir.exists():
            continue

        # Try exact filename matches
        for fname in filenames_to_try:
            candidate = search_dir / fname
            if candidate.exists():
                logger.info(f"Found 2D output: {candidate}")
                return candidate

        # Search for any file containing the output_id
        for f in search_dir.iterdir():
            if f.is_file() and output_id in f.name and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                logger.info(f"Found 2D output (partial match): {f}")
                return f

    # Last resort: recursive search in outputs and uploads
    for search_dir in [project_root / "outputs", project_root / "uploads",
                        project_root / "backend" / "outputs"]:
        if search_dir.exists():
            for f in search_dir.rglob(f"*{output_id}*"):
                if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                    logger.info(f"Found 2D output (recursive): {f}")
                    return f

    logger.warning(
        f"2D output image not found for output_id={output_id}. "
        f"Searched: {[str(d) for d in unique_dirs]}"
    )
    return None


# =============================================================================
#  POST /api/v1/try-on/3d  — Main 3D generation endpoint
# =============================================================================


@router.post("/api/v1/try-on/3d", summary="Generate 3D GLB from 2D try-on result")
async def generate_3d(request: Request):
    """
    Generate a 3D avatar (GLB) from the 2D try-on result image.

    Accepts MULTIPLE input methods (all are model-agnostic):
      • Form field `user_image`  — File upload (the 2D result or person image)
      • Form field `output_id`   — ID from the 2D pipeline → auto-locates the PNG
      • Form field `image_path`  — Direct server path to an image
      • JSON body `image_base64` — Base64-encoded image
      • JSON body `output_id`    — Same as above, via JSON

    The frontend (TryOn.jsx handleGenerate3D) sends:
      user_image, output_id, instruction, session_id  →  via FormData

    Returns (matching the 2D backend's response shape):
      {success, job_id, status, download_url, total_time_seconds, ...}
    """
    try:
        image_path = None
        job_id = generate_job_id()
        content_type = request.headers.get("content-type", "")

        # ── Parse from multipart form (the frontend's default) ──────────
        if "multipart/form-data" in content_type:
            form = await request.form()
            session_id = str(form.get("session_id", ""))
            instruction = str(form.get("instruction", ""))
            output_id_field = form.get("output_id")

            # Priority 1: output_id from the 2D pipeline → find the saved PNG
            if output_id_field and str(output_id_field).strip():
                image_path = _find_2d_output_image(str(output_id_field).strip())
                if image_path:
                    logger.info(f"Using 2D output for output_id={output_id_field}")

            # Priority 2: uploaded file (user_image / image / result_image)
            if image_path is None:
                image_field = (
                    form.get("user_image") or
                    form.get("image") or
                    form.get("result_image")
                )
                if image_field and hasattr(image_field, "read"):
                    image_bytes = await image_field.read()
                    if len(image_bytes) > 100:
                        upload_dir = ensure_dir(Path(settings.paths.upload_dir) / job_id)
                        image_path = upload_dir / "input_2d.png"
                        with open(image_path, "wb") as f:
                            f.write(image_bytes)
                        logger.info(f"Saved uploaded image: {image_path}")

        # ── Parse from JSON body ────────────────────────────────────────
        elif "application/json" in content_type:
            body = await request.json()
            output_id = body.get("output_id")
            image_b64 = body.get("image_base64")
            img_path = body.get("image_path")

            if img_path and Path(img_path).exists():
                image_path = Path(img_path)
            elif output_id:
                image_path = _find_2d_output_image(output_id)
            elif image_b64:
                image_path = _save_base64_image(image_b64, job_id)

        # ── Parse from URL-encoded form (fallback when proxy sends no files) ──
        elif "application/x-www-form-urlencoded" in content_type:
            form = await request.form()
            output_id_field = form.get("output_id")
            if output_id_field and str(output_id_field).strip():
                image_path = _find_2d_output_image(str(output_id_field).strip())

        else:
            # Try to read as form anyway (catchall)
            try:
                form = await request.form()
                output_id_field = form.get("output_id")
                if output_id_field and str(output_id_field).strip():
                    image_path = _find_2d_output_image(str(output_id_field).strip())
            except Exception:
                pass

        # ── Validate we have an image ───────────────────────────────────
        if image_path is None or not Path(image_path).exists():
            raise HTTPException(
                400,
                "No valid image provided. Send one of: "
                "output_id (from 2D pipeline), user_image (file upload), "
                "image_base64, or image_path.",
            )

        logger.info(f"Starting 3D generation | Job: {job_id} | Image: {image_path}")

        # ── Fire-and-forget: start pipeline in background, return job_id now ──
        #
        # The pipeline takes 5-20 min (LHM model load + inference + mesh export).
        # Waiting synchronously causes the 2D backend's httpx proxy (timeout=600s)
        # and the Vite proxy to drop the connection before the result arrives.
        #
        # Fix: kick off the work as a background asyncio Task and respond
        # immediately with {status: "processing", job_id}.  The frontend already
        # handles this — handleGenerate3D checks d.job_id and starts polling
        # /api/v1/status/{job_id} every 5 s (up to 30 min).
        #
        # The background task uses run_in_executor so the heavy synchronous
        # pipeline.run() runs in a thread pool and never blocks the event loop.

        # Seed the job store so polling returns "processing" right away
        _job_store[job_id] = {
            "job_id": job_id,
            "status": "processing",
            "glb_path": None,
            "download_url": None,
        }

        async def _run_pipeline_bg(img_path: str, jid: str) -> None:
            loop = asyncio.get_running_loop()
            try:
                pipeline = _get_pipeline()
                result = await loop.run_in_executor(
                    None,
                    lambda: pipeline.run(
                        image_path=img_path,
                        job_id=jid,
                        skip_preprocessing=False,
                    ),
                )
                _save_result(result)   # updates _job_store[jid]
                logger.info(
                    f"Background pipeline done | Job: {jid} | "
                    f"Status: {result.status} | "
                    f"Time: {result.total_time_seconds:.1f}s"
                )
            except Exception as bg_exc:
                logger.error(f"Background pipeline error | Job: {jid} | {bg_exc}")
                import traceback as _tb
                logger.error(_tb.format_exc())
                _job_store[jid] = {
                    "job_id": jid,
                    "status": "failed",
                    "error": str(bg_exc),
                }

        asyncio.create_task(_run_pipeline_bg(str(image_path), job_id))

        # Respond immediately — frontend will poll for completion
        return JSONResponse({
            "success": True,
            "job_id": job_id,
            "output_id": job_id,
            "status": "processing",
            "message": "3D generation started. Poll /api/v1/status/{job_id} for updates.",
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"generate_3d error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(500, f"3D pipeline error: {str(e)}")


# =============================================================================
#  POST /api/v1/convert-ply  — Convert PLY to GLB (skip LHM inference)
# =============================================================================


@router.post("/api/v1/convert-ply", summary="Convert existing PLY to GLB")
async def convert_ply(request: Request):
    """
    Convert an existing LHM PLY output to GLB format.
    Use this if you already ran LHM inference and just have the PLY file.
    """
    try:
        body = await request.json()
        ply_path = body.get("ply_path")
        if not ply_path or not Path(ply_path).exists():
            raise HTTPException(400, f"PLY file not found: {ply_path}")

        job_id = body.get("job_id") or generate_job_id()

        pipeline = _get_pipeline()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: pipeline.run_from_ply(ply_path=ply_path, job_id=job_id)
        )
        response_data = _save_result(result)

        if result.status == "failed":
            return JSONResponse(status_code=500, content={
                "success": False, "job_id": job_id,
                "status": "failed", "error": result.error,
            })

        return JSONResponse({
            "success": True,
            "job_id": result.job_id,
            "status": result.status,
            "download_url": response_data.get("download_url"),
            "total_time_seconds": result.total_time_seconds,
            "mesh_stats": result.mesh_stats,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"convert_ply error: {e}")
        raise HTTPException(500, str(e))


# =============================================================================
#  GET /api/v1/status/{job_id}  — Job status (frontend polling)
# =============================================================================


@router.get("/api/v1/status/{job_id}", summary="Check 3D generation job status")
async def get_status(job_id: str):
    """
    Check status of a 3D generation job.
    Compatible with the frontend's usePolling hook which expects:
      { job_id, status, result: { download_url, preview_url } }
    """
    # Check in-memory store first (current session)
    if job_id in _job_store:
        job = _job_store[job_id]
        dl_url = job.get("download_url") or job.get("glb_download_url")
        return JSONResponse({
            "job_id": job_id,
            "status": job.get("status", "unknown"),
            "download_url": dl_url,
            "result": {
                "download_url": dl_url,
                "preview_url": dl_url,
            },
            "total_time_seconds": job.get("total_time_seconds"),
            "mesh_stats": job.get("mesh_stats", {}),
        })

    # Fall back to disk — the job completed in a previous server session
    output_base = Path(settings.paths.output_dir) / job_id
    for fname in (f"{job_id}.glb", f"{job_id}.mp4"):
        if (output_base / fname).exists():
            dl_url = f"/api/v1/download/{job_id}"
            return JSONResponse({
                "job_id": job_id,
                "status": "completed",
                "download_url": dl_url,
                "output_type": "video" if fname.endswith(".mp4") else "glb",
                "result": {"download_url": dl_url, "preview_url": dl_url},
            })

    return JSONResponse({"job_id": job_id, "status": "not_found"})


# =============================================================================
#  GET /api/v1/download/{job_id}  — Download the generated GLB
# =============================================================================


@router.get("/api/v1/download/{job_id}", summary="Download the 3D output (GLB or MP4)")
async def download_glb(job_id: str):
    """
    Download the generated 3D output.
    - GLB  when running with local LHM weights
    - MP4  when running in remote API mode (3DAIGC/LHM Space)
    """
    output_path: Optional[Path] = None
    media_type = "model/gltf-binary"
    filename = f"styleforge_3d_{job_id}.glb"

    # Check in-memory store first (current session)
    if job_id in _job_store:
        job = _job_store[job_id]
        if job.get("status") != "completed":
            raise HTTPException(400, f"Output not ready for job {job_id}")
        # Prefer video_path (remote mode) then glb_path (local mode)
        if job.get("video_path") and Path(job["video_path"]).exists():
            output_path = Path(job["video_path"])
            media_type = "video/mp4"
            filename = f"styleforge_3d_{job_id}.mp4"
        elif job.get("glb_path") and Path(job["glb_path"]).exists():
            output_path = Path(job["glb_path"])
    else:
        # Fall back to disk — check for both formats
        base = Path(settings.paths.output_dir) / job_id
        mp4_candidate = base / f"{job_id}.mp4"
        glb_candidate = base / f"{job_id}.glb"
        if mp4_candidate.exists():
            output_path = mp4_candidate
            media_type = "video/mp4"
            filename = f"styleforge_3d_{job_id}.mp4"
        elif glb_candidate.exists():
            output_path = glb_candidate

    if output_path is None:
        raise HTTPException(404, f"Job {job_id} not found")
    if not output_path.exists():
        raise HTTPException(404, "Output file not found on disk")

    return FileResponse(
        path=str(output_path),
        media_type=media_type,
        filename=filename,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


# =============================================================================
#  GET /health  — Health check (same format as the 2D backend)
# =============================================================================


@router.get("/health", summary="Health check and GPU status")
async def health_check():
    """Check if the 3D service is running and report GPU availability."""
    gpu_available = torch.cuda.is_available()
    gpu_name = None
    vram_total = None
    vram_free = None

    if gpu_available:
        gpu_name = torch.cuda.get_device_name(0)
        total = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        allocated = torch.cuda.memory_allocated(0) / (1024 ** 3)
        vram_total = round(total, 2)
        vram_free = round(total - allocated, 2)

    return JSONResponse({
        "status": "ok",
        "service": "avatar-3d",
        "model": "LHM",
        "gpu_available": gpu_available,
        "gpu_name": gpu_name,
        "vram_total_gb": vram_total,
        "vram_free_gb": vram_free,
    })


# ── Helpers ─────────────────────────────────────────────────────────────────


def _save_base64_image(b64_data: str, job_id: Optional[str] = None) -> Path:
    """Decode a base64 image and save to the uploads directory."""
    jid = job_id or generate_job_id()
    upload_dir = ensure_dir(Path(settings.paths.upload_dir) / jid)

    # Strip data URI prefix if present (e.g. "data:image/png;base64,...")
    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]

    image_bytes = base64.b64decode(b64_data)
    save_path = upload_dir / "input.png"

    with open(save_path, "wb") as f:
        f.write(image_bytes)

    logger.info(f"Base64 image saved to: {save_path}")
    return save_path
