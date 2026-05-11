"""
Verify that the setup is correct and all dependencies are available.

Run this after setup.ps1 to check everything before starting the server.

Usage:
    python scripts/verify_setup.py
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    color_code = "\033[92m" if condition else "\033[91m"
    reset = "\033[0m"
    msg = f"  [{color_code}{status}{reset}] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return condition


def main():
    print("\n" + "=" * 55)
    print("  Avatar 3D Pipeline — Setup Verification")
    print("=" * 55 + "\n")

    all_pass = True

    # ── 1. Python version ──
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 10)
    all_pass &= check("Python >= 3.10", ok, f"Found: {py_ver}")

    # ── 2. PyTorch + CUDA ──
    try:
        import torch
        has_cuda = torch.cuda.is_available()
        all_pass &= check("PyTorch installed", True, f"v{torch.__version__}")
        if has_cuda:
            gpu_name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            all_pass &= check("CUDA available", True, f"{gpu_name} ({vram:.1f} GB)")
        else:
            all_pass &= check("CUDA available", False, "No GPU detected — will run on CPU (very slow)")
    except ImportError:
        all_pass &= check("PyTorch installed", False, "pip install torch")

    # ── 3. Core dependencies ──
    deps = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "open3d": "open3d",
        "trimesh": "trimesh",
        "PIL (Pillow)": "PIL",
        "cv2 (OpenCV)": "cv2",
        "numpy": "numpy",
        "pydantic": "pydantic",
        "yaml (PyYAML)": "yaml",
        "plyfile": "plyfile",
        "loguru": "loguru",
    }

    for label, module in deps.items():
        try:
            __import__(module)
            all_pass &= check(f"{label}", True)
        except ImportError:
            all_pass &= check(f"{label}", False, f"pip install {label.split(' ')[0]}")

    # ── 4. CUDA extensions (critical for LHM) ──
    print("\n  CUDA Extensions:")
    cuda_deps = {
        "diff_gaussian_rasterization": "diff_gaussian_rasterization",
        "simple_knn": "simple_knn",
        "pytorch3d": "pytorch3d",
    }
    for label, module in cuda_deps.items():
        try:
            __import__(module)
            all_pass &= check(f"{label}", True)
        except ImportError:
            all_pass &= check(f"{label}", False, "Run: scripts\\build_cuda_deps.bat")

    # ── 5. Optional dependencies ──
    print("\n  Optional:")
    try:
        import xatlas
        check("xatlas (UV unwrapping)", True, "High-quality UV maps available")
    except ImportError:
        check("xatlas (UV unwrapping)", False, "Fallback UV will be used — pip install xatlas")

    # ── 5. Config file ──
    print("\n  Files:")
    config_path = project_root / "config.yaml"
    all_pass &= check("config.yaml exists", config_path.exists())

    # ── 6. LHM repo and weights ──
    print("\n  LHM Model:")
    try:
        from app.config import settings
        lhm_src = Path(settings.lhm.repo_path).resolve()
        lhm_wt = Path(settings.lhm.weights_path).resolve()
        model_name = settings.lhm.model_name

        all_pass &= check("LHM source directory", lhm_src.exists(), str(lhm_src))
        all_pass &= check("LHM weights directory", lhm_wt.exists(), str(lhm_wt))
        all_pass &= check(f"Model variant: {model_name}", True)

        # Check pretrained_models junction
        pretrained = lhm_src / "pretrained_models"
        has_pretrained = pretrained.exists() and any(pretrained.iterdir())
        all_pass &= check(
            "pretrained_models linked",
            has_pretrained,
            "junction OK" if has_pretrained else "Run: scripts\\setup_lhm_weights.ps1",
        )

        # Check model checkpoint
        exps = lhm_src / "exps"
        ckpt_files = list(exps.rglob("model.safetensors")) if exps.exists() else []
        has_ckpt = len(ckpt_files) > 0
        if has_ckpt:
            size_gb = ckpt_files[0].stat().st_size / (1024**3)
            all_pass &= check("Model checkpoint", True, f"{ckpt_files[0].name} ({size_gb:.1f} GB)")
        else:
            all_pass &= check(
                "Model checkpoint",
                False,
                "model.safetensors not found — Run: scripts\\setup_lhm_weights.ps1",
            )

        # Check key prior models
        for name, path in [
            ("Dense sample points", pretrained / "dense_sample_points" / "1_20000.ply"),
            ("Human model files", pretrained / "human_model_files"),
            ("Sapiens encoder", pretrained / "sapiens"),
            ("SAM2 segmentation", pretrained / "sam2"),
            ("Face detector", pretrained / "gagatracker" / "vgghead"),
        ]:
            ok = path.exists() if has_pretrained else False
            check(name, ok, str(path.name) if ok else "missing")

        # Check HuggingFace cache for model
        hf_cache = pretrained / "huggingface" / "models--3DAIGC--LHM-1B"
        if hf_cache.exists():
            hf_model_files = list(hf_cache.rglob("model.safetensors"))
            if hf_model_files:
                hf_size = hf_model_files[0].stat().st_size / (1024**3)
                ok = hf_size > 1.0  # Must be real file, not 0-byte placeholder
                all_pass &= check(
                    "HF cache model.safetensors",
                    ok,
                    f"{hf_size:.1f} GB" if ok else "0-byte placeholder — re-create hard link",
                )
            else:
                all_pass &= check("HF cache model.safetensors", False, "Not found in HF cache")
        else:
            all_pass &= check("HF cache directory", False, "Run inference once to create cache")
    except Exception as e:
        all_pass &= check("Config loading", False, str(e))

    # ── 7. Directories ──
    print("\n  Directories:")
    for dirname in ["outputs", "temp", "uploads", "logs", "backend", "frontend"]:
        d = project_root / dirname
        exists = d.exists()
        if not exists and dirname in ["outputs", "temp", "uploads", "logs"]:
            d.mkdir(parents=True, exist_ok=True)
        check(f"{dirname}/", exists, "created" if not exists else "exists")

    # ── Summary ──
    print("\n" + "=" * 55)
    if all_pass:
        print("  \033[92mAll checks passed! Ready to run.\033[0m")
        print("  Start with: python run_server.py")
    else:
        print("  \033[91mSome checks failed. Fix the issues above.\033[0m")
    print("=" * 55 + "\n")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
