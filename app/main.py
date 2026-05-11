"""
FastAPI application — the main web server for the 3D Avatar service.

This server exposes the 3D pipeline as a REST API.
It runs on port 5001 alongside the 2D backend (port 5000).
The 2D backend proxies /api/v1/try-on/3d requests here.

Architecture:
  React Frontend (port 5002)
       │  POST /api/v1/try-on/3d
       ▼
  2D Backend (port 5000)
       │  proxy → http://localhost:5001/api/v1/try-on/3d
       ▼
  THIS 3D SERVICE (port 5001)
       │  LHM → Gaussian Splatting → Mesh → GLB
       ▼
  Returns { success, job_id, download_url }

The 3D service is MODEL-AGNOSTIC:
  It accepts any PNG image and produces a GLB model.
  Switching the 2D model requires ZERO changes here.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import settings
from app.utils.file_utils import ensure_dir
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup / shutdown lifecycle handler.
    """
    # ── Startup ──
    logger.info("=" * 60)
    logger.info("Avatar 3D Service starting up...")
    logger.info(f"Server: {settings.server.host}:{settings.server.port}")
    logger.info(f"LHM repo: {settings.lhm.repo_path}")
    logger.info(f"GPU device: {settings.gpu.device}")
    logger.info("=" * 60)

    # Create required directories
    ensure_dir(settings.paths.output_dir)
    ensure_dir(settings.paths.temp_dir)
    ensure_dir(settings.paths.upload_dir)

    yield

    # ── Shutdown ──
    logger.info("Avatar 3D Service shutting down...")
    # Cleanup any loaded models
    from app.api.routes import _pipeline
    if _pipeline is not None:
        _pipeline.cleanup()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="StyleForge 3D Avatar Service",
        description=(
            "Converts 2D try-on images into web-ready 3D GLB avatars "
            "using LHM reconstruction. Integrates with the StyleForge "
            "2D backend via a proxy endpoint on port 5000.\n\n"
            "Model-agnostic: works with any 2D model output (IDM-VTON, Gemini, etc.)"
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routes ──
    app.include_router(api_router)

    # ── Serve generated GLB files statically (optional) ──
    output_dir = Path(settings.paths.output_dir)
    ensure_dir(output_dir)
    app.mount(
        "/outputs",
        StaticFiles(directory=str(output_dir)),
        name="outputs",
    )

    return app


# Application instance — used by uvicorn
app = create_app()
