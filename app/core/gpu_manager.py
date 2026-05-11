"""
GPU memory management utilities.
Handles VRAM monitoring, cleanup between pipeline stages, and device selection.
"""

import gc
from typing import Optional

import torch

from app.utils.logger import logger


class GPUManager:
    """
    Manages GPU resources across the 3D pipeline.

    Key responsibilities:
    - Monitor VRAM usage
    - Clean up between pipeline stages (critical for 24 GB RTX 3090)
    - Enforce memory limits
    - Provide device context
    """

    def __init__(self, device: str = "cuda:0", max_vram_gb: float = 20.0):
        self.device_str = device
        self.max_vram_gb = max_vram_gb

        if not torch.cuda.is_available():
            logger.warning("CUDA is not available — falling back to CPU")
            self.device = torch.device("cpu")
            self.has_gpu = False
        else:
            self.device = torch.device(device)
            self.has_gpu = True
            gpu_name = torch.cuda.get_device_name(self.device)
            total_mem = torch.cuda.get_device_properties(self.device).total_memory / (1024 ** 3)
            logger.info(f"GPU: {gpu_name} | Total VRAM: {total_mem:.1f} GB")

    # ── VRAM info ───────────────────────────────────────────────────────────

    def get_vram_usage(self) -> dict:
        """Return current VRAM usage in GB."""
        if not self.has_gpu:
            return {"allocated": 0, "reserved": 0, "free": 0, "total": 0}

        allocated = torch.cuda.memory_allocated(self.device) / (1024 ** 3)
        reserved = torch.cuda.memory_reserved(self.device) / (1024 ** 3)
        total = torch.cuda.get_device_properties(self.device).total_memory / (1024 ** 3)
        free = total - allocated

        return {
            "allocated": round(allocated, 2),
            "reserved": round(reserved, 2),
            "free": round(free, 2),
            "total": round(total, 2),
        }

    def log_vram(self, label: str = "") -> None:
        """Log current VRAM status."""
        usage = self.get_vram_usage()
        prefix = f"[{label}] " if label else ""
        logger.info(
            f"{prefix}VRAM — Allocated: {usage['allocated']:.2f} GB | "
            f"Reserved: {usage['reserved']:.2f} GB | "
            f"Free: {usage['free']:.2f} GB / {usage['total']:.2f} GB"
        )

    # ── Memory cleanup ──────────────────────────────────────────────────────

    def cleanup(self, label: str = "") -> None:
        """
        Aggressive GPU memory cleanup.
        Call this between pipeline stages to free VRAM.
        """
        if self.has_gpu:
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        gc.collect()

        if label:
            self.log_vram(f"After cleanup: {label}")

    def unload_model(self, model: Optional[object]) -> None:
        """
        Unload a model from GPU and free its memory.
        Pass None safely (no-op).
        """
        if model is None:
            return

        try:
            if hasattr(model, "cpu"):
                model.cpu()
            del model
        except Exception as e:
            logger.warning(f"Error unloading model: {e}")

        self.cleanup("model unload")

    # ── Context managers ────────────────────────────────────────────────────

    def check_memory(self, required_gb: float = 4.0) -> bool:
        """
        Check if enough VRAM is available.
        Returns True if there's sufficient free memory.
        """
        if not self.has_gpu:
            return True  # CPU mode, no VRAM limit

        usage = self.get_vram_usage()
        if usage["free"] < required_gb:
            logger.warning(
                f"Low VRAM: {usage['free']:.2f} GB free, "
                f"{required_gb:.2f} GB required"
            )
            return False
        return True

    def get_optimal_dtype(self) -> torch.dtype:
        """Return FP16 if the GPU supports it, else FP32."""
        if self.has_gpu:
            cap = torch.cuda.get_device_capability(self.device)
            if cap[0] >= 7:  # Volta+ (SM 7.0+)
                return torch.float16
        return torch.float32


# ── Module-level singleton ──────────────────────────────────────────────────

_gpu_manager: Optional[GPUManager] = None


def get_gpu_manager(device: str = "cuda:0", max_vram_gb: float = 20.0) -> GPUManager:
    """Get or create the singleton GPUManager."""
    global _gpu_manager
    if _gpu_manager is None:
        _gpu_manager = GPUManager(device=device, max_vram_gb=max_vram_gb)
    return _gpu_manager
