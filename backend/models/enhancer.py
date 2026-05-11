"""
Image quality enhancer — post-processing to improve 2D try-on output.

Fixes the quality loss introduced by:
  - HF Spaces image compression (JPEG artifacts, loss of detail)
  - Preprocessing downscaling (resolution loss)

Enhancement pipeline:
  1. Real-ESRGAN 4× neural upscale (GPU-accelerated)
  2. Adaptive unsharp-mask sharpening
  3. Bilateral denoising (edge-preserving)
  4. CLAHE contrast enhancement on luminance channel
  5. Downscale to target resolution with Lanczos (keeps detail from 4×)

Real-ESRGAN recovers texture detail that bicubic/Lanczos cannot.
The 4× upscale followed by a controlled downscale is a well-known
super-resolution trick: upscale high, then shrink to your target size,
keeping the hallucinated high-frequency detail.

Environment variables:
    ENHANCE_ENABLED      — "true" to enable (default "true")
    ENHANCE_TARGET_SIZE  — final output long-edge in px (default 1536)
    ENHANCE_SHARPEN      — sharpen strength 0.0-2.0 (default 0.7)
"""

import os
import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance


def _load_realesrgan(gpu_id: int = 0):
    """
    Lazy-load Real-ESRGAN upscaler.
    Uses RealESRGAN_x4plus which is trained on general images and works
    well on human bodies + clothing.  The model weights are auto-downloaded
    from GitHub on first use (~64 MB).
    """
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer

    model = RRDBNet(
        num_in_ch=3, num_out_ch=3, num_feat=64,
        num_block=23, num_grow_ch=32, scale=4,
    )
    upsampler = RealESRGANer(
        scale=4,
        model_path="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        model=model,
        tile=512,           # tile-based processing — fits in any VRAM
        tile_pad=32,        # increased from 10 — prevents colour seams at tile boundaries
        pre_pad=0,
        half=True,          # FP16 — faster, less VRAM
        gpu_id=gpu_id,
    )
    return upsampler


class ImageEnhancer:
    """Post-processing enhancer for 2D try-on results."""

    def __init__(
        self,
        enabled: bool | None = None,
        target_size: int | None = None,
        sharpen_strength: float | None = None,
    ):
        self.enabled = (
            enabled if enabled is not None
            else os.getenv("ENHANCE_ENABLED", "true").lower() == "true"
        )
        self.target_size = (
            target_size if target_size is not None
            else int(os.getenv("ENHANCE_TARGET_SIZE", "1536"))
        )
        self.sharpen_strength = (
            sharpen_strength if sharpen_strength is not None
            else float(os.getenv("ENHANCE_SHARPEN", "0.7"))
        )
        self._upsampler = None  # lazy-loaded on first use

    def _get_upsampler(self):
        """Lazy-load the Real-ESRGAN model (downloads weights on first call)."""
        if self._upsampler is None:
            try:
                self._upsampler = _load_realesrgan()
                print("[Enhancer] Real-ESRGAN loaded (GPU, FP16, tile=512)")
            except Exception as e:
                print(f"[Enhancer] WARNING: Real-ESRGAN failed to load: {e}")
                print("[Enhancer] Output quality will be reduced (2× Lanczos fallback active).")
                print("[Enhancer] Fix: pip install realesrgan basicsr  and ensure internet access on first run.")
                self._upsampler = "FAILED"
        return self._upsampler if self._upsampler != "FAILED" else None

    def enhance(self, image_path: str | Path, output_path: str | Path) -> Path:
        """
        Enhance the image and save to output_path.
        Returns the path to the enhanced image.
        If enhancement is disabled, copies the original unchanged.
        """
        image_path = Path(image_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.enabled:
            shutil.copy2(image_path, output_path)
            return output_path

        img = Image.open(image_path).convert("RGB")

        # Step 1: Neural upscale (Real-ESRGAN 4×) or Lanczos fallback
        img = self._upscale(img)

        # Step 2: Adaptive sharpen
        if self.sharpen_strength > 0:
            img = self._sharpen(img)

        # Step 3: Edge-preserving denoise
        img = self._denoise(img)

        # Step 4: CLAHE contrast enhancement
        img = self._enhance_contrast(img)

        # Step 5: Downscale to target size (keeps super-res detail)
        img = self._downscale_to_target(img)

        img.save(str(output_path), format="PNG", compress_level=3)
        return output_path

    def _upscale(self, img: Image.Image) -> Image.Image:
        """
        4× neural upscale with Real-ESRGAN.
        Falls back to Lanczos if the model can't load.
        """
        upsampler = self._get_upsampler()

        if upsampler is not None:
            # Real-ESRGAN expects BGR numpy array
            arr = np.array(img)[:, :, ::-1]  # RGB → BGR
            try:
                output, _ = upsampler.enhance(arr, outscale=4)
                # BGR → RGB → PIL
                result = Image.fromarray(output[:, :, ::-1])
                print(f"[Enhancer] Real-ESRGAN 4× upscale: {img.size} → {result.size}")
                return result
            except Exception as e:
                print(f"[Enhancer] WARNING: Real-ESRGAN inference failed: {e} — falling back to Lanczos")

        # Fallback: Lanczos 2× upscale
        w, h = img.size
        return img.resize((w * 2, h * 2), Image.LANCZOS)

    def _downscale_to_target(self, img: Image.Image) -> Image.Image:
        """
        After 4× upscale, downscale to target_size (long edge).
        This retains the recovered high-frequency detail from Real-ESRGAN
        while keeping the file size reasonable.
        """
        w, h = img.size
        max_dim = max(w, h)
        if max_dim <= self.target_size:
            return img
        scale = self.target_size / max_dim
        new_w = int(w * scale)
        new_h = int(h * scale)
        return img.resize((new_w, new_h), Image.LANCZOS)

    def _sharpen(self, img: Image.Image) -> Image.Image:
        """
        Adaptive unsharp mask — sharpens detail without amplifying noise.
        Uses PIL's UnsharpMask (radius, percent, threshold) for better
        control than the simple Sharpness enhancer.
        """
        # radius=2: moderate halo width
        # percent=int(strength*100): strength mapped to percentage
        # threshold=3: don't sharpen near-flat regions (avoids noise boost)
        pct = int(self.sharpen_strength * 100)
        return img.filter(ImageFilter.UnsharpMask(radius=2, percent=pct, threshold=3))

    def _denoise(self, img: Image.Image) -> Image.Image:
        """
        Edge-preserving bilateral filter — removes JPEG block artifacts
        without blurring edges (clothing seams, face features).
        """
        arr = np.array(img)
        # d=5: moderate kernel — removes JPEG block artifacts without over-blurring
        # sigmaColor=20: tighter colour range — preserves fabric patterns, stripes and prints
        # sigmaSpace=15: smaller spatial extent — prevents smearing clothing texture detail
        arr = cv2.bilateralFilter(arr, d=5, sigmaColor=20, sigmaSpace=15)
        return Image.fromarray(arr)

    def _enhance_contrast(self, img: Image.Image) -> Image.Image:
        """
        CLAHE on the L channel (LAB color space).
        clipLimit=2.0 gives a stronger but natural-looking boost.
        """
        arr = np.array(img)
        lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        lab = cv2.merge([l, a, b])
        arr = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
        return Image.fromarray(arr)
