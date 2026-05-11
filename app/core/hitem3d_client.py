"""
Hi3D (hitem3d.ai) API Client — Cloud-based image-to-3D generation.

Uses the Hi3D v2.1 "fast" model (resolution=1536fast) to convert a 2D image
into a GLB file without needing any local GPU or LHM weights.

API flow:
  1. POST /open-api/v1/auth/token        → obtain Bearer token (valid 24h)
  2. POST /open-api/v1/submit-task       → upload image, get task_id
  3. GET  /open-api/v1/query-task        → poll until state == "success"
  4. Download the GLB from data["url"]

Reference: https://docs.hitem3d.ai/en/api/api-reference/
"""

import base64
import os
import socket
import time
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.utils.logger import logger


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://api.hitem3d.ai"
_TOKEN_ENDPOINT = f"{_BASE_URL}/open-api/v1/auth/token"
_SUBMIT_ENDPOINT = f"{_BASE_URL}/open-api/v1/submit-task"
_QUERY_ENDPOINT = f"{_BASE_URL}/open-api/v1/query-task"

# Fast model: v2.1 + 1536fast  (~2 min geometry+texture)
_DEFAULT_MODEL = "hitem3dv2.1"
_DEFAULT_RESOLUTION = "1536fast"
_REQUEST_TYPE_ALL = "3"   # geometry + texture in one shot
_FORMAT_GLB = "2"

_POLL_INTERVAL_SECONDS = 8
_MAX_POLL_SECONDS = 600   # 10 minutes max


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class HiItem3DClient:
    """
    Thin client for the Hi3D image-to-3D API.

    Credentials are read from environment variables:
      HITEM3D_ACCESS_KEY  — the Access Key shown in the dashboard
      HITEM3D_SECRET_KEY  — the Secret Key shown in the dashboard

    Both are set in styleforge/.env and loaded at startup via python-dotenv
    (or any other mechanism that populates os.environ).
    """

    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        model: str = _DEFAULT_MODEL,
        resolution: str = _DEFAULT_RESOLUTION,
        output_format: str = _FORMAT_GLB,
    ):
        self.access_key = access_key or os.environ.get("HITEM3D_ACCESS_KEY", "")
        self.secret_key = secret_key or os.environ.get("HITEM3D_SECRET_KEY", "")

        if not self.access_key or not self.secret_key:
            raise EnvironmentError(
                "Hi3D API credentials not found. "
                "Set HITEM3D_ACCESS_KEY and HITEM3D_SECRET_KEY in styleforge/.env"
            )

        self.model = model
        self.resolution = resolution
        self.output_format = output_format

        self._token: Optional[str] = None
        self._token_obtained_at: float = 0.0
        self._token_ttl: float = 23 * 3600  # refresh 1h before expiry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_glb(
        self,
        image_path: str | Path,
        output_path: str | Path,
        timeout: int = _MAX_POLL_SECONDS,
    ) -> Path:
        """
        Full pipeline: upload image → poll → download GLB.

        Parameters
        ----------
        image_path  : path to the 2D PNG/JPEG image
        output_path : where to save the downloaded GLB file
        timeout     : maximum seconds to wait for the task to complete

        Returns
        -------
        Path to the saved GLB file.

        Raises
        ------
        RuntimeError  if the task fails or times out.
        """
        image_path = Path(image_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"[Hi3D] Submitting image: {image_path.name}")
        logger.info(f"[Hi3D] Model={self.model}  Resolution={self.resolution}")

        token = self._get_token()

        # ── Submit task ──────────────────────────────────────────────
        task_id = self._submit_task(token, image_path)
        logger.info(f"[Hi3D] Task submitted: {task_id}")

        # ── Poll ─────────────────────────────────────────────────────
        glb_url = self._poll_task(token, task_id, timeout)
        logger.info(f"[Hi3D] Task complete. Downloading GLB …")

        # ── Download ─────────────────────────────────────────────────
        self._download_file(glb_url, output_path)
        logger.info(f"[Hi3D] GLB saved: {output_path}")

        return output_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Return a valid Bearer token, refreshing if expired."""
        now = time.time()
        if self._token and (now - self._token_obtained_at) < self._token_ttl:
            return self._token

        creds = base64.b64encode(
            f"{self.access_key}:{self.secret_key}".encode()
        ).decode()

        resp = requests.post(
            _TOKEN_ENDPOINT,
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/json",
            },
            json={},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()

        if body.get("code") != 200:
            raise RuntimeError(f"[Hi3D] Auth failed: {body}")

        self._token = body["data"]["accessToken"]
        self._token_obtained_at = now
        logger.info("[Hi3D] Access token obtained.")
        return self._token

    def _make_session(self) -> requests.Session:
        """Return a requests Session with retry + generous socket timeout."""
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _submit_task(self, token: str, image_path: Path) -> str:
        """Upload the image and return the task_id."""
        mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"

        # Extend the OS-level socket timeout so slow servers don't abort the upload
        prev_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(300)
        try:
            session = self._make_session()
            with open(image_path, "rb") as fh:
                resp = session.post(
                    _SUBMIT_ENDPOINT,
                    headers={"Authorization": f"Bearer {token}"},
                    files={"images": (image_path.name, fh, mime)},
                    data={
                        "request_type": _REQUEST_TYPE_ALL,
                        "model": self.model,
                        "resolution": self.resolution,
                        "format": self.output_format,
                        "pbr": "1",
                    },
                    timeout=(15, 300),  # (connect_timeout, read_timeout)
                )
        finally:
            socket.setdefaulttimeout(prev_timeout)

        resp.raise_for_status()
        body = resp.json()

        if body.get("code") != 200:
            raise RuntimeError(f"[Hi3D] submit-task failed: {body}")

        return body["data"]["task_id"]

    def _poll_task(self, token: str, task_id: str, timeout: int) -> str:
        """Poll query-task until success; return the GLB download URL."""
        deadline = time.time() + timeout
        headers = {"Authorization": f"Bearer {token}"}

        while time.time() < deadline:
            resp = requests.get(
                _QUERY_ENDPOINT,
                headers=headers,
                params={"task_id": task_id},
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()

            if body.get("code") != 200:
                raise RuntimeError(f"[Hi3D] query-task error: {body}")

            data = body["data"]
            state = data.get("state", "unknown")
            logger.info(f"[Hi3D] Task {task_id[:16]}… state={state}")

            if state == "success":
                url = data.get("url")
                if not url:
                    raise RuntimeError("[Hi3D] Task succeeded but no download URL returned.")
                return url

            if state == "failed":
                raise RuntimeError(f"[Hi3D] Task failed: {data}")

            # created / queueing / processing → keep waiting
            time.sleep(_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"[Hi3D] Task {task_id} did not complete within {timeout}s."
        )

    @staticmethod
    def _download_file(url: str, dest: Path) -> None:
        """Stream-download a file from url to dest."""
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=8192):
                    fh.write(chunk)
