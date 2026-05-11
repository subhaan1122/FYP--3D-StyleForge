"""
Model adapters for the 2D virtual try-on backend.

To switch models, set the TRYON_MODEL environment variable:
    TRYON_MODEL=idm_vton   (default)

To add a new model:
    1. Create a new file in this package (e.g., my_model.py)
    2. Subclass BaseTryOnModel
    3. Register it in MODEL_REGISTRY below
"""

from models.base import BaseTryOnModel
from models.idm_vton import IDMVTONModel
from models.enhancer import ImageEnhancer

MODEL_REGISTRY = {
    "idm_vton": IDMVTONModel,
}


def get_model(model_name: str = "idm_vton") -> BaseTryOnModel:
    """Instantiate a try-on model by name."""
    cls = MODEL_REGISTRY.get(model_name)
    if cls is None:
        raise ValueError(
            f"Unknown model '{model_name}'. "
            f"Available: {list(MODEL_REGISTRY.keys())}"
        )
    return cls()


__all__ = [
    "BaseTryOnModel",
    "IDMVTONModel",
    "ImageEnhancer",
    "MODEL_REGISTRY",
    "get_model",
]
