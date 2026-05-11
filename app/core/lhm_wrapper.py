"""
LHM (Large Human Model) inference wrapper.

Runs LHM mesh export via subprocess using the official CLI::

    python -m LHM.launch infer.human_lrm \\
        model_name=LHM-1B \\
        image_input=<path> \\
        export_mesh=True \\
        motion_seqs_dir=None \\
        motion_img_dir=None

The subprocess approach is required because LHM has a complex startup
chain (accelerate, custom registries, SAM2, PoseEstimator, FaceDetector,
HuggingFace Hub, OmegaConf, etc.) that does not work reliably when
imported into a foreign FastAPI process.  Each inference call spawns a
fresh Python process whose CWD is the LHM repo root, so every relative
path inside LHM (``./pretrained_models/``, ``./exps/``, …) resolves
correctly.

Output
------
Gaussian Splatting PLY file — later converted to a triangulated mesh by
``GaussianToMesh`` and exported to web-ready GLB by ``GLBExporter``.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from app.config import settings
from app.core.gpu_manager import get_gpu_manager
from app.utils.file_utils import ensure_dir
from app.utils.logger import logger


class LHMWrapper:
    """
    Wrapper around 3DAIGC/LHM for single-image → 3D human reconstruction.

    Uses subprocess to call LHM's official ``python -m LHM.launch`` CLI.
    The output is a Gaussian Splatting PLY that the downstream
    ``GaussianToMesh`` module converts to a triangulated mesh.

    Usage::

        wrapper = LHMWrapper()
        wrapper.load_model()           # no-op (model loads inside subprocess)
        ply = wrapper.run_inference("input.png", "output_dir/")
        wrapper.unload_model()         # VRAM freed when subprocess exits
    """

    def __init__(self):
        cfg = settings.lhm
        self.repo_path = Path(cfg.repo_path).resolve()
        self.weights_path = Path(cfg.weights_path).resolve()
        self.model_name = cfg.model_name
        self.device = cfg.device
        self.gpu = get_gpu_manager()

        # Validate paths
        if not self.repo_path.exists():
            raise FileNotFoundError(
                f"LHM source code not found at {self.repo_path}. "
                "Please verify models/lhm-source exists."
            )

        self._validate_weights()

    # ── Validation ──────────────────────────────────────────────────────────

    def _validate_weights(self) -> None:
        """Check that pretrained weights and model checkpoint are accessible."""
        pretrained = self.repo_path / "pretrained_models"
        exps = self.repo_path / "exps"

        issues: list[str] = []

        # pretrained_models must be populated
        if not pretrained.exists() or not any(pretrained.iterdir()):
            src = self.weights_path / "pretrained_models"
            if src.exists():
                issues.append(
                    f"pretrained_models/ is empty in {self.repo_path}. "
                    f'Create junction: mklink /J "{pretrained}" "{src}"'
                )
            else:
                issues.append(
                    f"pretrained_models/ not found at {pretrained} or {src}."
                )

        # exps/ must contain the model checkpoint (model.safetensors)
        if not exps.exists() or not any(exps.rglob("model.safetensors")):
            src = self.weights_path / "exps"
            if src.exists():
                issues.append(
                    f"exps/ missing model weights in {self.repo_path}. "
                    f'Create junction: mklink /J "{exps}" "{src}"'
                )
            else:
                issues.append(
                    f"Model weights not found in exps/ at {exps} or {src}."
                )

        if issues:
            msg = (
                "LHM weight setup incomplete — run: "
                "scripts\\setup_lhm_weights.ps1\n"
                + "\n".join(f"  • {i}" for i in issues)
            )
            logger.warning(msg)

    def weights_ready(self) -> bool:
        """Return True if all weights and prior models are in place."""
        pretrained = self.repo_path / "pretrained_models"
        exps = self.repo_path / "exps"
        has_pretrained = pretrained.exists() and any(pretrained.iterdir())
        has_weights = exps.exists() and any(exps.rglob("model.safetensors"))
        return has_pretrained and has_weights

    # ── Model Loading (no-op for subprocess mode) ───────────────────────────

    def load_model(self) -> None:
        """
        No-op — the model loads inside the child process.
        Kept for API compatibility with the pipeline orchestrator.
        """
        self.gpu.log_vram("LHM ready (subprocess mode — model loads on demand)")

    # ── Inference ───────────────────────────────────────────────────────────

    def run_inference(
        self,
        image_path: str | Path,
        output_dir: str | Path,
    ) -> Path:
        """
        Run LHM mesh inference on a single image.

        Parameters
        ----------
        image_path : path to the preprocessed 2D image (PNG / JPG)
        output_dir : directory where the output PLY will be copied

        Returns
        -------
        Path to the generated Gaussian Splatting PLY file.

        Raises
        ------
        FileNotFoundError
            If the input image does not exist.
        RuntimeError
            If LHM inference fails or produces no output.
        """
        image_path = Path(image_path).resolve()
        output_dir = Path(output_dir).resolve()
        ensure_dir(output_dir)

        if not image_path.exists():
            raise FileNotFoundError(f"Input image not found: {image_path}")

        if not self.weights_ready():
            raise RuntimeError(
                "LHM weights not set up. "
                "Run scripts\\setup_lhm_weights.ps1 first."
            )

        logger.info(
            f"LHM inference starting | "
            f"model={self.model_name} | image={image_path.name}"
        )
        self.gpu.log_vram("Before LHM inference")
        t0 = time.time()

        ply_path = self._run_subprocess(image_path, output_dir)

        elapsed = time.time() - t0
        self.gpu.log_vram("After LHM inference")

        if ply_path is None or not ply_path.exists():
            raise RuntimeError(
                "LHM inference completed but no PLY file was produced. "
                "Check logs/avatar3d_*.log for LHM stderr output."
            )

        size_mb = ply_path.stat().st_size / 1e6
        logger.info(
            f"LHM inference complete | "
            f"PLY: {ply_path.name} ({size_mb:.1f} MB) | "
            f"Time: {elapsed:.1f}s"
        )
        return ply_path

    # ── Subprocess Execution ────────────────────────────────────────────────

    def _run_subprocess(
        self, image_path: Path, output_dir: Path
    ) -> Optional[Path]:
        """
        Execute ``python -m LHM.launch infer.human_lrm`` as a child process.

        CWD is set to the LHM repo root so all internal relative paths
        (``./pretrained_models/``, ``./exps/``, …) resolve correctly.

        Uses ``Popen`` + ``communicate(timeout=...)`` so that a timed-out
        process is **explicitly killed** before the exception propagates.
        With ``subprocess.run(timeout=...)`` the child stays alive on timeout,
        holds GPU memory, and prevents every subsequent inference from
        allocating VRAM — causing a cascade of 30-minute timeouts.
        """
        cmd = [
            sys.executable,
            "-u",  # unbuffered output — critical for subprocess capture
            "-m", "LHM.launch",
            "infer.human_lrm",
            f"model_name={self.model_name}",
            f"image_input={str(image_path)}",
            "export_mesh=True",
            "motion_seqs_dir=None",
            "motion_img_dir=None",
        ]

        # Build PYTHONPATH: repo root + engine sub-packages (required by
        # human_lrm.py: "from engine.pose_estimation.pose_estimator import …")
        engine_path = str(self.repo_path / "engine")
        engine_pose_path = str(self.repo_path / "engine" / "pose_estimation")
        existing_pp = os.environ.get("PYTHONPATH", "")
        pp_parts = [str(self.repo_path), engine_path, engine_pose_path]
        if existing_pp:
            pp_parts.append(existing_pp)

        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(pp_parts),
            "PYTHONUNBUFFERED": "1",
            # Force offline mode — model weights are already cached locally.
            # Without this, huggingface_hub may attempt network lookups that
            # hang indefinitely on restricted networks, burning the timeout.
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            # Ensure the right GPU is used
            "CUDA_VISIBLE_DEVICES": (
                self.device.split(":")[-1] if ":" in self.device else "0"
            ),
        }

        logger.info(f"LHM command: {' '.join(cmd)}")
        logger.info(f"LHM CWD:     {self.repo_path}")

        stdout_text = ""
        stderr_text = ""
        returncode = -1

        # Use Popen so we can kill the process explicitly on timeout.
        # subprocess.run(timeout=…) raises TimeoutExpired but leaves the
        # child running, which holds GPU memory and blocks future runs.
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.repo_path),
            env=env,
        ) as proc:
            try:
                stdout_text, stderr_text = proc.communicate(timeout=1800)
                returncode = proc.returncode
            except subprocess.TimeoutExpired:
                # Kill immediately — do NOT let it linger.
                proc.kill()
                # Drain remaining output so pipes don't block.
                stdout_text, stderr_text = proc.communicate()
                returncode = proc.returncode

                # Log the last output lines so we can see where it hung.
                last_stdout = (stdout_text or "").strip().splitlines()[-30:]
                last_stderr = (stderr_text or "").strip().splitlines()[-30:]
                for line in last_stdout:
                    logger.error(f"[LHM timeout stdout] {line}")
                for line in last_stderr:
                    logger.error(f"[LHM timeout stderr] {line}")

                raise RuntimeError(
                    "LHM inference timed out after 30 minutes — process killed. "
                    "Check logs for '[LHM timeout stdout/stderr]' to see where "
                    "it hung. Common causes: (1) GPU VRAM exhausted by a "
                    "previous zombie process — restart the service; "
                    "(2) Network call during model load — HF_HUB_OFFLINE is now "
                    "always set; (3) Try LHM-500M instead of LHM-1B."
                )

        # ── Log subprocess output ──
        stdout_lines = stdout_text.strip().splitlines() if stdout_text else []
        for line in stdout_lines[-50:]:
            logger.debug(f"[LHM] {line}")

        if stderr_text:
            lines = stderr_text.strip().splitlines()
            # Filter noisy but harmless warnings
            important = [
                l
                for l in lines
                if not any(
                    w in l.lower()
                    for w in ("futurewarning", "userwarning", "deprecat")
                )
            ]
            for line in (important or lines)[-40:]:
                logger.warning(f"[LHM stderr] {line}")

        if returncode != 0:
            tail = "\n".join(stderr_text.strip().splitlines()[-50:])
            logger.error(f"LHM exited with code {returncode}\n{tail}")
            raise RuntimeError(
                f"LHM inference failed (exit code {returncode}). "
                f"Last error: {stderr_text.strip().splitlines()[-1] if stderr_text.strip() else 'no stderr'}"
            )

        # ── Check for body-ratio skip ──
        # LHM silently skips images where the body ratio is ≤ 0.4
        # (the pose estimator can't detect enough of the body).
        # Detect this by checking stdout for the ratio message.
        body_ratio_fail = any(
            "body ratio is too small" in l for l in stdout_lines
        )
        if body_ratio_fail:
            logger.warning(
                "LHM body-ratio check failed — the input image does "
                "not show enough of the body (need > 40% visible). "
                "Ensure the input is a full-body or upper-body photo."
            )
            raise RuntimeError(
                "LHM rejected the input image: body ratio too small. "
                "The image must show a clearly visible human body "
                "(at least upper body). Please use a different image."
            )

        return self._find_output_ply(image_path, output_dir)

    # ── Output Discovery ────────────────────────────────────────────────────

    def _find_output_ply(
        self, image_path: Path, output_dir: Path
    ) -> Optional[Path]:
        """
        Locate the PLY written by LHM.

        LHM saves to::

            exps/meshs/<parent>/<child>/<step>/<image_stem>.ply

        where ``<image_stem>`` has dots replaced by underscores.
        """
        raw_stem = image_path.stem
        # LHM convention: split on '.' and join with '_'
        lhm_stem = "_".join(raw_stem.split(".")) if "." in raw_stem else raw_stem

        mesh_dir = self.repo_path / "exps" / "meshs"

        if mesh_dir.exists():
            # Strategy 1: exact LHM-style stem
            matches = list(mesh_dir.rglob(f"{lhm_stem}.ply"))

            # Strategy 2: original stem
            if not matches:
                matches = list(mesh_dir.rglob(f"{raw_stem}.ply"))

            # Strategy 3: partial match
            if not matches:
                matches = list(mesh_dir.rglob(f"*{raw_stem}*.ply"))

            # Strategy 4: most recently written PLY (< 10 min old)
            if not matches:
                now = time.time()
                all_plys = sorted(
                    mesh_dir.rglob("*.ply"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                matches = [p for p in all_plys if (now - p.stat().st_mtime) < 600]

            if matches:
                source_ply = matches[0]
                dest_ply = output_dir / "lhm_output.ply"
                shutil.copy2(source_ply, dest_ply)
                logger.info(f"Copied PLY: {source_ply} → {dest_ply}")
                return dest_ply

        # Fallback: check if something was written directly to output_dir
        for ply in output_dir.rglob("*.ply"):
            return ply

        logger.error(f"No PLY found in {mesh_dir} for stem '{lhm_stem}'")
        return None

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def unload_model(self) -> None:
        """
        No-op for subprocess mode — the child process releases all GPU
        memory on exit.  Run a cache cleanup just in case.
        """
        self.gpu.cleanup("LHM cleanup")
        logger.info("LHM cleanup complete")

    def __del__(self):
        try:
            self.unload_model()
        except Exception:
            pass
