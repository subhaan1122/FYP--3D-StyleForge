"""
Configuration loader.
Reads config.yaml and exposes settings as a typed dataclass-like object.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


# ── Section models ──────────────────────────────────────────────────────────

class LHMConfig(BaseModel):
    # Hi3D cloud API mode (no local GPU or weights needed)
    use_hitem3d: bool = True   # set False to fall back to local LHM

    # Remote API mode (no local weights needed)
    use_remote_api: bool = False
    remote_space: str = "3DAIGC/LHM"
    remote_api_name: str = "/core_fn"   # kept for reference; not used directly
    remote_motion_video: str = ""       # path to driving video; empty = use default mimo1
    hf_token: str = ""                  # HuggingFace token for higher ZeroGPU queue priority
    remote_timeout_seconds: int = 600   # max wait for /core_fn (queue + inference)

    # Local subprocess mode
    repo_path: str = "../models/lhm-source"
    weights_path: str = "../models/lhm-weights"
    model_name: str = "LHM-1B"
    device: str = "cuda:0"
    use_fp16: bool = True
    input_resolution: int = 512


class MeshReconstructionConfig(BaseModel):
    opacity_threshold: float = 0.15           # raised from 0.05 — filters noise/halo Gaussians
    poisson_depth: int = 10                   # was 9 — finer Poisson detail
    density_threshold_percentile: int = 5     # raised from 1 — removes Poisson floater fog
    min_cluster_size: int = 100              # lowered from 500 — arms/legs can be small clusters
    outlier_nb_neighbors: int = 25            # was 30
    outlier_std_ratio: float = 2.5            # was 2.0 — gentler outlier removal


class MeshProcessingConfig(BaseModel):
    target_faces: int = 100000               # was 80000 — more detail
    smoothing_iterations: int = 10           # Taubin needs more iters than Laplacian
    smoothing_lambda: float = 0.5            # raised from 0.3
    fill_holes: bool = True
    max_hole_size: int = 1000               # was 100 — fill larger structural gaps


class TextureConfig(BaseModel):
    atlas_resolution: int = 2048
    bake_texture_atlas: bool = True
    format: str = "png"


class GLBExportConfig(BaseModel):
    embed_textures: bool = True
    draco_compression: bool = False
    max_size_warning_mb: float = 50.0


class GPUConfig(BaseModel):
    device: str = "cuda:0"
    max_vram_gb: float = 20.0
    aggressive_cleanup: bool = True
    mixed_precision: bool = True


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 5001
    workers: int = 1
    reload: bool = False
    cors_origins: List[str] = [
        "http://localhost:5002",
        "http://localhost:5173",
        "http://localhost:5000",
        "http://127.0.0.1:5002",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5000",
    ]


class PathsConfig(BaseModel):
    output_dir: str = "outputs"
    temp_dir: str = "temp"
    upload_dir: str = "uploads"


class IntegrationConfig(BaseModel):
    """Settings for connecting to the 2D backend (IDM-VTON or any model)."""
    tryon_outputs_dir: str = "backend/outputs"
    backend_2d_url: str = "http://localhost:5000"


# ── Root config ─────────────────────────────────────────────────────────────

class AppConfig(BaseModel):
    lhm: LHMConfig = LHMConfig()
    mesh_reconstruction: MeshReconstructionConfig = MeshReconstructionConfig()
    mesh_processing: MeshProcessingConfig = MeshProcessingConfig()
    texture: TextureConfig = TextureConfig()
    glb_export: GLBExportConfig = GLBExportConfig()
    gpu: GPUConfig = GPUConfig()
    server: ServerConfig = ServerConfig()
    paths: PathsConfig = PathsConfig()
    integration: IntegrationConfig = IntegrationConfig()


def load_config(config_path: Optional[str | Path] = None) -> AppConfig:
    """
    Load configuration from YAML file.
    Falls back to defaults if the file is missing.
    Supports environment variable overrides for key paths.

    IMPORTANT: Relative paths in the config (repo_path, weights_path, etc.)
    are resolved relative to the config file's parent directory (styleforge/),
    NOT the current working directory.  This ensures the same paths work
    regardless of which directory the server is started from.
    """
    path = Path(config_path) if config_path else _CONFIG_PATH
    # The project root is the directory containing config.yaml (styleforge/)
    project_root = path.parent.resolve() if path.exists() else Path(__file__).resolve().parent.parent

    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            raw: Dict[str, Any] = yaml.safe_load(f) or {}
        config = AppConfig(**raw)
    else:
        config = AppConfig()

    # Environment variable overrides for portability
    import os
    if os.environ.get("LHM_REPO_PATH"):
        config.lhm.repo_path = os.environ["LHM_REPO_PATH"]
    if os.environ.get("TRYON_OUTPUTS_DIR"):
        config.integration.tryon_outputs_dir = os.environ["TRYON_OUTPUTS_DIR"]
    if os.environ.get("AVATAR_3D_PORT"):
        config.server.port = int(os.environ["AVATAR_3D_PORT"])

    # Resolve relative paths relative to the project root (styleforge/),
    # not the current working directory.  This is critical because the
    # server may be started from any directory.
    def _resolve(p: str) -> str:
        pp = Path(p)
        if not pp.is_absolute():
            return str((project_root / pp).resolve())
        return p

    config.lhm.repo_path = _resolve(config.lhm.repo_path)
    config.lhm.weights_path = _resolve(config.lhm.weights_path)
    config.paths.output_dir = _resolve(config.paths.output_dir)
    config.paths.temp_dir = _resolve(config.paths.temp_dir)
    config.paths.upload_dir = _resolve(config.paths.upload_dir)
    config.integration.tryon_outputs_dir = _resolve(config.integration.tryon_outputs_dir)

    return config


# Load .env so HITEM3D_* and other vars are available before building settings
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed — rely on shell environment

# Singleton — import `settings` in other modules
settings: AppConfig = load_config()
