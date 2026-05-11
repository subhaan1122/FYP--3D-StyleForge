"""
IDM-VTON model adapter — calls the HuggingFace Spaces API via gradio_client.

This is the default model. To switch, set TRYON_MODEL env var to another
registered model name (see __init__.py).

Quality tuning knobs (env vars):
    IDM_VTON_DENOISE_STEPS  — diffusion steps (default 40, HF Spaces max is 40)
    IDM_VTON_SEED           — reproducibility seed (default 42)
    IDM_VTON_SPACE          — HF space ID (default yisol/IDM-VTON)
"""

import os
import time
import shutil
from pathlib import Path

from gradio_client import Client, handle_file

from models.base import BaseTryOnModel


class IDMVTONModel(BaseTryOnModel):
    """IDM-VTON via HuggingFace Spaces (gradio_client)."""

    name = "IDM-VTON"

    def __init__(self):
        self.space_id = os.getenv("IDM_VTON_SPACE", "yisol/IDM-VTON")
        self.denoise_steps = int(os.getenv("IDM_VTON_DENOISE_STEPS", "40"))
        self.seed = int(os.getenv("IDM_VTON_SEED", "42"))
        self._client = None

    def _get_client(self) -> Client:
        if self._client is None:
            self._client = Client(self.space_id)
        return self._client

    def predict(
        self,
        person_path: str | Path,
        garment_path: str | Path,
        instruction: str = "a garment",
        **kwargs,
    ) -> Path:
        """
        Call IDM-VTON on HuggingFace and return the result image path.

        Accepts optional kwargs:
            denoise_steps (int)
            seed (int)
        """
        denoise_steps = kwargs.get("denoise_steps", self.denoise_steps)
        seed = kwargs.get("seed", self.seed)

        last_error = None
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                print(f"[IDM-VTON] Attempt {attempt}/{max_retries} — connecting to {self.space_id}")
                client = self._get_client()

                result = client.predict(
                    dict={
                        "background": handle_file(str(person_path)),
                        "layers": [],
                        "composite": None,
                    },
                    garm_img=handle_file(str(garment_path)),
                    garment_des=instruction if instruction else "a garment",
                    is_checked=True,
                    is_checked_crop=True,   # auto-crops & aligns person — improves garment placement
                    denoise_steps=denoise_steps,
                    seed=seed,
                    api_name="/tryon",
                )

                # Result is a tuple — first element is the image path
                result_path = result[0] if isinstance(result, (list, tuple)) else result

                if not result_path or not Path(str(result_path)).exists():
                    raise RuntimeError(f"IDM-VTON returned no image. Raw result: {result}")

                return Path(str(result_path))

            except Exception as e:
                last_error = e
                print(f"[IDM-VTON] Attempt {attempt} failed: {e}")
                # Reset the client so the next attempt creates a fresh connection.
                # Stale gradio_client connections are the most common cause of
                # repeated 500s after the HF Space wakes up or restarts.
                self._client = None
                if attempt < max_retries:
                    wait = attempt * 5  # 5 s, 10 s
                    print(f"[IDM-VTON] Retrying in {wait}s...")
                    time.sleep(wait)

        raise RuntimeError(f"IDM-VTON failed after {max_retries} attempts. Last error: {last_error}")

    def cleanup(self) -> None:
        self._client = None
