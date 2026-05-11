"""
Remote LHM inference wrapper using the Gradio Client.

Calls the official 3DAIGC/LHM HuggingFace Space via the 3-step API:
  1. /assert_input_image  — validate the person image
  2. /prepare_working_dir — initialise the Space session
  3. /core_fn             — run LHM inference → returns rendered MP4 video

The Space returns a rendered 3D animation video (MP4), NOT a PLY file.
Because of this, when use_remote_api is true the pipeline skips the
Gaussian→Mesh→GLB stages and returns the video directly.

Activated by setting ``lhm.use_remote_api: true`` in config.yaml.

Limitations
-----------
- Requires an internet connection.
- The public Space may queue; expect 1-5 min wait during peak hours.
- Output is an MP4 video, not a GLB — the frontend shows a video player.
- The motion driving video (remote_motion_video in config) is uploaded
  to the Space on every call.
"""

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

from app.config import settings
from app.utils.logger import logger


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SPACE = "3DAIGC/LHM"

# Output type so the pipeline knows not to run Gaussian→Mesh→GLB
OUTPUT_TYPE = "video"


# ---------------------------------------------------------------------------
# Wrapper class
# ---------------------------------------------------------------------------

class LHMRemoteWrapper:
    """
    Drop-in interface for the remote 3DAIGC/LHM HuggingFace Space.

    Returns an MP4 video instead of a PLY file.  The pipeline detects this
    via the ``output_type`` property and skips the mesh/GLB stages.

    Usage::

        wrapper = LHMRemoteWrapper()
        wrapper.load_model()                    # connects to the Space
        mp4 = wrapper.run_inference("img.png", "output/dir/")
        wrapper.unload_model()                  # releases the client
    """

    #: Tells the pipeline what kind of file run_inference() returns.
    output_type: str = OUTPUT_TYPE

    def __init__(self, space: str = DEFAULT_SPACE):
        self.space = space
        self._client = None

        # HuggingFace token — gives higher priority in the ZeroGPU queue.
        # Set via env var HF_TOKEN or hf_token in config.yaml.
        self._hf_token: Optional[str] = (
            getattr(settings.lhm, "hf_token", None)
            or os.environ.get("HF_TOKEN")
            or None
        ) or None

        # Timeout in seconds for the /core_fn call (LHM inference is slow).
        # ZeroGPU queue wait + inference can exceed 5 minutes.
        self._timeout: int = int(
            getattr(settings.lhm, "remote_timeout_seconds", 600)
        )

        # Motion driving video
        cfg_video = getattr(settings.lhm, "remote_motion_video", None)
        if cfg_video:
            self._motion_video = Path(cfg_video).resolve()
        else:
            styleforge_root = Path(__file__).resolve().parent.parent.parent
            self._motion_video = (
                styleforge_root
                / ".." / "models" / "lhm-source" / "assets"
                / "sample_motion" / "mimo1" / "origin.mp4"
            ).resolve()

        logger.info(f"LHMRemoteWrapper | Space: {self.space!r}")
        logger.info(f"LHMRemoteWrapper | HF token: {'SET' if self._hf_token else 'NOT SET (lower queue priority)'}")
        logger.info(f"LHMRemoteWrapper | Timeout: {self._timeout}s")
        logger.info(f"LHMRemoteWrapper | Motion video: {self._motion_video}")

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def load_model(self) -> None:
        """Connect to the remote HuggingFace Space."""
        try:
            from gradio_client import Client
        except ImportError:
            raise RuntimeError(
                "gradio_client is not installed.  Run: pip install gradio_client"
            )

        logger.info(f"[Remote LHM] Connecting to {self.space} …")
        t0 = time.time()
        self._client = Client(self.space, token=self._hf_token)
        logger.info(f"[Remote LHM] Connected in {time.time() - t0:.1f}s")

    def unload_model(self) -> None:
        """Release the client (nothing to free — model runs remotely)."""
        self._client = None
        logger.info("[Remote LHM] Client released")

    # ── Inference ────────────────────────────────────────────────────────────

    def run_inference(
        self,
        image_path: str | Path,
        output_dir: str | Path,
    ) -> Path:
        """
        Run the 3-step LHM Space API and return the downloaded MP4 path.

        Parameters
        ----------
        image_path : preprocessed person image (PNG)
        output_dir : local directory to save the downloaded MP4

        Returns
        -------
        Path to the downloaded MP4 video file
        """
        if self._client is None:
            raise RuntimeError("Client not loaded — call load_model() first.")

        try:
            from gradio_client import handle_file
        except ImportError:
            raise RuntimeError(
                "gradio_client is not installed.  Run: pip install gradio_client"
            )

        image_path = Path(image_path).resolve()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not image_path.exists():
            raise FileNotFoundError(f"Input image not found: {image_path}")

        if not self._motion_video.exists():
            raise FileNotFoundError(
                f"Motion driving video not found: {self._motion_video}\n"
                "Check lhm.remote_motion_video in config.yaml or verify that "
                "models/lhm-source/assets/sample_motion/mimo1/origin.mp4 exists."
            )

        logger.info(f"[Remote LHM] Image     : {image_path}")
        logger.info(f"[Remote LHM] Motion    : {self._motion_video}")

        t0 = time.time()

        # Build FileData objects once so all 3 steps share the same references
        image_file = handle_file(str(image_path))

        # ── Critical: the Space's core_fn extracts the motion name from the
        # video FILENAME via os.path.basename(video_params).split("_")[0].
        # It then looks up ./assets/sample_motion/{name}/smplx_params/ on the
        # Space server.  Valid names: mimo1, mimo2, ex5, girl, taiji, nezha …
        # Our local file is named "origin.mp4", which would extract "origin" —
        # a directory that doesn't exist on the Space → silent crash / outputs:[].
        # Fix: copy the video to a temp file named "mimo1_origin.mp4" so that
        # split("_")[0] → "mimo1", which exists on the Space server.
        motion_name = "mimo1"
        tmp_video_path = Path(tempfile.gettempdir()) / f"{motion_name}_origin.mp4"
        shutil.copy2(self._motion_video, tmp_video_path)
        logger.info(f"[Remote LHM] Renamed motion video → {tmp_video_path.name} (Space lookup key: {motion_name!r})")

        # The Video component requires {"video": <FileData>, "subtitles": None}
        video_params = {"video": handle_file(str(tmp_video_path)), "subtitles": None}

        # ── Step 1: validate the input image ──────────────────────────────
        logger.info("[Remote LHM] Step 1/3: assert_input_image")
        self._client.predict(
            input_image=image_file,
            api_name="/assert_input_image",
        )

        # ── Step 2: prepare working directory ─────────────────────────────
        logger.info("[Remote LHM] Step 2/3: prepare_working_dir")
        self._client.predict(api_name="/prepare_working_dir")

        # ── Step 3: run LHM inference ─────────────────────────────────────
        logger.info(f"[Remote LHM] Step 3/3: core_fn (timeout={self._timeout}s, queue wait included …)")
        result = self._client.predict(
            image=image_file,
            video_params=video_params,
            api_name="/core_fn",
        )
        # result → (processed_image_dict, rendered_video_dict)

        elapsed = time.time() - t0
        logger.info(f"[Remote LHM] Inference done in {elapsed:.1f}s")
        logger.info(f"[Remote LHM] Raw result: {result!r}")

        # result[1] is the rendered video
        video_src = self._extract_file_path(result[1] if isinstance(result, (list, tuple)) else result)
        logger.info(f"[Remote LHM] Video path: {video_src}")

        src = Path(video_src)
        if not src.exists():
            raise RuntimeError(
                f"Downloaded video not found at: {src}\n"
                "gradio_client should have saved it automatically."
            )

        dest = output_dir / "lhm_rendered.mp4"
        shutil.copy2(src, dest)
        logger.info(f"[Remote LHM] Video saved to: {dest}")
        return dest

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_file_path(result) -> str:
        """
        Extract a local file path from the various Gradio return shapes.

        Gradio 4.x returns FileData / VideoData dicts:
          { "video": "/tmp/gradio/.../output.mp4", "subtitles": None }
          { "path": "/tmp/gradio/.../output.mp4" }
        Older versions return a plain string path.
        """
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            # Video component: {"video": path, "subtitles": ...}
            if "video" in result and result["video"]:
                v = result["video"]
                if isinstance(v, dict):
                    return v.get("path") or v.get("url") or str(v)
                return str(v)
            return (
                result.get("path")
                or result.get("name")
                or result.get("url")
                or str(result)
            )
        if isinstance(result, (list, tuple)) and len(result) > 0:
            return LHMRemoteWrapper._extract_file_path(result[0])
        raise ValueError(
            f"Cannot extract a file path from the Space response: {result!r}"
        )
