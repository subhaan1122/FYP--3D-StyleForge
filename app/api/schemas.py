"""
Pydantic schemas for the 3D API.

These models document the API contract between the 3D service (port 5001),
the 2D backend proxy (port 5000), and the React frontend.

NOTE: The actual routes use JSONResponse for flexibility (so they can
      match the exact shape the frontend expects without schema rigidity).
      These models are used for:
        • OpenAPI documentation (/docs)
        • Type hints and validation where needed
        • Reference documentation for other developers

The response format mirrors the 2D backend's format:
  { success, job_id, output_id, status, download_url, ... }

This makes the frontend's handling code work uniformly for both 2D and 3D.
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# =============================================================================
#  Request schemas
# =============================================================================


class Generate3DRequest(BaseModel):
    """
    Request body for POST /api/v1/try-on/3d (JSON variant).

    The primary method is multipart form (file upload), which is handled
    directly in routes.py. This schema covers the JSON alternative.
    """
    output_id: Optional[str] = Field(
        None,
        description=(
            "Output ID from the 2D pipeline. The service locates "
            "outputs/tryon_{output_id}.png automatically."
        ),
    )
    image_path: Optional[str] = Field(
        None,
        description="Server-side path to the 2D result image",
    )
    image_base64: Optional[str] = Field(
        None,
        description="Base64-encoded image data (data URI or raw base64)",
    )
    skip_preprocessing: bool = Field(
        False,
        description="Skip image preprocessing (use if image is already LHM-ready)",
    )
    job_id: Optional[str] = Field(
        None,
        description="Custom job ID; auto-generated if omitted",
    )


class ConvertPLYRequest(BaseModel):
    """Request body for POST /api/v1/convert-ply."""
    ply_path: str = Field(
        ...,
        description="Path to the Gaussian Splatting PLY file from LHM",
    )
    job_id: Optional[str] = Field(None)


# =============================================================================
#  Response schemas  (mirrors the 2D backend's response shape)
# =============================================================================


class Generate3DResponse(BaseModel):
    """
    Response for POST /api/v1/try-on/3d.

    Matches the 2D backend structure so the frontend can handle
    both 2D and 3D responses with the same code.
    """
    success: bool = True
    job_id: str
    output_id: Optional[str] = None
    status: str = Field(description="completed | failed | processing")
    download_url: Optional[str] = Field(
        None,
        description="URL to download the GLB: /api/v1/download/{job_id}",
    )
    glb_download_url: Optional[str] = None
    total_time_seconds: Optional[float] = None
    stage_times: Dict[str, float] = {}
    mesh_stats: Dict[str, Any] = {}
    error: Optional[str] = None


class JobStatusResponse(BaseModel):
    """
    Response for GET /api/v1/status/{job_id}.

    The frontend's usePolling hook expects:
      { job_id, status, result: { download_url, preview_url } }
    """
    job_id: str
    status: str = Field(description="completed | failed | processing | not_found")
    download_url: Optional[str] = None
    result: Optional[Dict[str, Any]] = Field(
        None,
        description="Nested result with download_url and preview_url",
    )
    total_time_seconds: Optional[float] = None
    mesh_stats: Dict[str, Any] = {}


class HealthResponse(BaseModel):
    """Response for GET /health."""
    status: str = "ok"
    service: str = "avatar-3d"
    model: str = "LHM"
    gpu_available: bool = False
    gpu_name: Optional[str] = None
    vram_total_gb: Optional[float] = None
    vram_free_gb: Optional[float] = None


class ErrorResponse(BaseModel):
    """Standard error response."""
    success: bool = False
    detail: str
    error: Optional[str] = None
    error_code: Optional[str] = None
