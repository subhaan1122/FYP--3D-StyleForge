"""
Base class for virtual try-on models.

Every model adapter must implement:
  - predict(person_path, garment_path, instruction, **kwargs) -> Path

This abstraction makes it trivial to swap IDM-VTON for another model
(e.g., Gemini, StableVTON, OOTDiffusion, etc.) without touching
the rest of the backend.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class BaseTryOnModel(ABC):
    """Abstract base for 2D virtual try-on models."""

    # Human-readable name shown in /health and logs
    name: str = "base"

    @abstractmethod
    def predict(
        self,
        person_path: str | Path,
        garment_path: str | Path,
        instruction: str = "a garment",
        **kwargs,
    ) -> Path:
        """
        Run the model and return the path to the result image.

        Parameters
        ----------
        person_path : path to the preprocessed person image
        garment_path : path to the preprocessed garment image
        instruction : text description of the garment
        **kwargs : model-specific options (e.g., denoise_steps, seed)

        Returns
        -------
        Path to the output image file (PNG)
        """
        ...

    def warmup(self) -> None:
        """Optional: pre-load model weights or connect to a remote API."""
        pass

    def cleanup(self) -> None:
        """Optional: release resources."""
        pass
