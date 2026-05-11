"""Quick test: run a 2D try-on and measure output quality."""
import requests
import time
from pathlib import Path
from PIL import Image
import cv2
import numpy as np

PERSON = "D:/3D/styleforge/uploads/04b6c2248eb94179/input_2d.png"
GARMENT = "D:/3D/styleforge/backend/temp/garment_47747829.png"

def measure(path):
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    lap = cv2.Laplacian(img, cv2.CV_64F).var()
    h, w = img.shape
    return w, h, round(lap, 2)

print("Running 2D try-on (denoise_steps=50 + Real-ESRGAN)...")
t0 = time.time()
r = requests.post(
    "http://localhost:5000/api/v1/try-on/2d",
    files={
        "user_image": ("person.png", open(PERSON, "rb"), "image/png"),
        "garment_reference": ("garment.png", open(GARMENT, "rb"), "image/png"),
    },
    data={"instruction": "a garment"},
    timeout=300,
)
elapsed = time.time() - t0
d = r.json()
print(f"Status: {d.get('status')} | Time: {elapsed:.1f}s | output_id: {d.get('output_id')}")

oid = d.get("output_id")
if oid:
    new_path = Path(f"outputs/tryon_{oid}.png")
    old_path = Path("outputs/tryon_9b5f715a.png")  # a known "before" image

    if new_path.exists():
        new_img = Image.open(new_path)
        print(f"\nNEW output: {new_img.size} | {new_path.stat().st_size // 1024} KB")
        nw, nh, nlap = measure(new_path)
        print(f"  Sharpness: {nlap}")

    if old_path.exists():
        old_img = Image.open(old_path)
        print(f"\nOLD output: {old_img.size} | {old_path.stat().st_size // 1024} KB")
        ow, oh, olap = measure(old_path)
        print(f"  Sharpness: {olap}")

        if new_path.exists():
            print(f"\n=== IMPROVEMENT ===")
            print(f"Resolution: {ow}x{oh} -> {nw}x{nh} ({(nw*nh)/(ow*oh):.1f}x pixels)")
            print(f"Sharpness:  {olap} -> {nlap} ({nlap/olap:.1f}x)")
            print(f"File size:  {old_path.stat().st_size//1024}KB -> {new_path.stat().st_size//1024}KB")
else:
    print("ERROR:", d)
