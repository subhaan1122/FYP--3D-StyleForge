"""
File-system utilities: directory creation, cleanup, path helpers.
"""

import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from app.utils.logger import logger


def ensure_dir(path: str | Path) -> Path:
    """Create directories if they don't exist and return the Path object."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def generate_job_id() -> str:
    """Return a unique job identifier."""
    return uuid.uuid4().hex[:16]


def job_output_dir(base_output_dir: str | Path, job_id: str) -> Path:
    """Create and return the output directory for a specific job."""
    d = Path(base_output_dir) / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def cleanup_dir(path: str | Path) -> None:
    """Remove a directory tree if it exists."""
    p = Path(path)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
        logger.info(f"Cleaned up directory: {p}")


def safe_filename(name: str) -> str:
    """Sanitize a filename, keeping only safe characters."""
    import re
    name = re.sub(r'[^\w\-.]', '_', name)
    return name[:200]  # limit length


def get_file_size_mb(path: str | Path) -> float:
    """Return file size in megabytes."""
    return os.path.getsize(path) / (1024 * 1024)


def find_file(directory: str | Path, extension: str) -> Optional[Path]:
    """
    Find the first file with the given extension in a directory.
    Extension should include the dot, e.g. '.ply'
    """
    d = Path(directory)
    if not d.exists():
        return None
    for f in sorted(d.iterdir()):
        if f.suffix.lower() == extension.lower():
            return f
    return None


def list_files(directory: str | Path, extension: str = "") -> list[Path]:
    """List files in a directory, optionally filtered by extension."""
    d = Path(directory)
    if not d.exists():
        return []
    files = sorted(d.iterdir())
    if extension:
        files = [f for f in files if f.suffix.lower() == extension.lower()]
    return [f for f in files if f.is_file()]
