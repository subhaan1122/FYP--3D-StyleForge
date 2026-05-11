"""
Image preprocessing utilities for the 3D pipeline.
Prepares the 2D image (from the virtual try-on pipeline) for LHM inference.
"""

from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from app.utils.logger import logger


def load_image(image_path: str | Path) -> np.ndarray:
    """
    Load an image as a numpy array (RGB, uint8).
    Supports common formats: PNG, JPG, WEBP, BMP.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Failed to load image: {path}")

    # Handle RGBA → RGB
    if img.ndim == 3 and img.shape[2] == 4:
        # Composite over white background (cv2 loads as BGRA)
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        bgr = img[:, :, :3].astype(np.float32)
        white = np.ones_like(bgr) * 255.0
        img = (bgr * alpha + white * (1 - alpha)).astype(np.uint8)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    elif img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    return img


def save_image(img: np.ndarray, output_path: str | Path) -> Path:
    """Save a numpy (RGB) image to disk."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if img.ndim == 3 and img.shape[2] == 3:
        bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    else:
        bgr = img
    cv2.imwrite(str(path), bgr)
    return path


def resize_image(
    img: np.ndarray,
    target_size: int = 512,
    keep_aspect: bool = True,
) -> np.ndarray:
    """
    Resize an image to target_size.
    If keep_aspect is True, the image is resized so the longer side equals
    target_size, then padded with white to make it square.
    """
    h, w = img.shape[:2]

    if keep_aspect:
        scale = target_size / max(h, w)
        new_h, new_w = int(h * scale), int(w * scale)
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

        # Pad to square
        canvas = np.ones((target_size, target_size, 3), dtype=np.uint8) * 255
        y_off = (target_size - new_h) // 2
        x_off = (target_size - new_w) // 2
        canvas[y_off : y_off + new_h, x_off : x_off + new_w] = resized
        return canvas
    else:
        return cv2.resize(img, (target_size, target_size), interpolation=cv2.INTER_LANCZOS4)


def center_crop_person(
    img: np.ndarray,
    padding_ratio: float = 0.1,
) -> np.ndarray:
    """
    Attempt to center-crop around the person using foreground detection.

    Improvements over the naive single-threshold approach:
    - Threshold raised to 245 so light-coloured clothing (white shirts,
      cream dresses, pale skin) is NOT treated as background.
    - Morphological closing bridges internal white gaps inside clothing
      (e.g. the centre of a white shirt) so the bounding box stays intact.
    - Sanity check: if the detected region is < 10% of the image area,
      detection likely failed — return the original image unchanged.

    Falls back to the full image if detection fails or crop is too small.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    img_h, img_w = img.shape[:2]

    # Threshold at 245 (stricter than old 240).
    # Only pixels very close to pure white (255) are considered background.
    # This keeps off-white, cream and light-grey clothing as foreground.
    _, mask = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)

    # Morphological closing fills internal white regions inside clothing
    # (e.g. the front panel of a white shirt or a pale dress).
    # A 20×20 kernel bridges gaps up to ~20 pixels wide.
    close_kernel = np.ones((20, 20), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)

    coords = cv2.findNonZero(mask)
    if coords is None:
        logger.warning("Could not detect foreground — returning original image")
        return img

    x, y, w, h = cv2.boundingRect(coords)

    # Sanity check: the bounding box must cover at least 10% of the image.
    # If it is smaller, detection likely latched onto a tiny artifact —
    # return the full image to avoid an incorrectly tight crop.
    if w * h < 0.10 * img_w * img_h:
        logger.warning(
            f"Detected foreground too small ({w}\u00d7{h} px vs image "
            f"{img_w}\u00d7{img_h} px) — returning original image"
        )
        return img

    # Add padding
    pad_x = int(w * padding_ratio)
    pad_y = int(h * padding_ratio)
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(img_w, x + w + pad_x)
    y2 = min(img_h, y + h + pad_y)

    return img[y1:y2, x1:x2]


def preprocess_for_lhm(
    image_path: str | Path,
    output_path: str | Path,
    target_size: int = 512,
) -> Path:
    """
    Full preprocessing pipeline for LHM:
    1. Load image
    2. Center crop around person
    3. Resize to target_size (square, padded)
    4. Save and return path

    Parameters
    ----------
    image_path : path to input 2D image (from the virtual try-on pipeline)
    output_path : path to save preprocessed image
    target_size : resolution expected by LHM (default 512)

    Returns
    -------
    Path to the preprocessed image
    """
    logger.info(f"Preprocessing image: {image_path}")

    img = load_image(image_path)
    logger.debug(f"Loaded image shape: {img.shape}")

    # Center crop
    img = center_crop_person(img)
    logger.debug(f"After crop: {img.shape}")

    # Resize to LHM input resolution
    img = resize_image(img, target_size=target_size, keep_aspect=True)
    logger.debug(f"After resize: {img.shape}")

    # Save
    out = save_image(img, output_path)
    logger.info(f"Preprocessed image saved to: {out}")
    return out
