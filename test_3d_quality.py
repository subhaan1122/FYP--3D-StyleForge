"""Test the 3D pipeline with improved mesh reconstruction settings."""
import requests
import json
import time

IMAGE = "D:/3D/styleforge/uploads/04b6c2248eb94179/input_2d.png"

print("Running 3D pipeline with fixed mesh settings...")
print("  opacity_threshold: 0.05 (was 0.15)")
print("  density_trim: 1% (was 10%)")
print("  poisson_depth: 10 (was 9)")
print("  smoothing: 1 iter @ 0.3 (was 3 @ 0.5)")
print("  color transfer: k=5 weighted (was k=1)")
print("  normal radius: adaptive ~3% of extent (was fixed 0.05)")
print()

t0 = time.time()
r = requests.post(
    "http://localhost:5001/api/v1/try-on/3d",
    files={"user_image": ("input.png", open(IMAGE, "rb"), "image/png")},
    timeout=600,
)
elapsed = time.time() - t0
d = r.json()

print(f"Status: {d.get('status')}")
print(f"Time:   {elapsed:.1f}s")

if d.get("status") == "completed":
    st = d.get("stage_times", {})
    ms = d.get("mesh_stats", {})
    print(f"\nStage times:")
    for k, v in st.items():
        print(f"  {k}: {v:.1f}s")
    print(f"\nMesh stats:")
    for k, v in ms.items():
        print(f"  {k}: {v}")
    print(f"\nDownload URL: {d.get('download_url')}")
    print(f"Output ID:    {d.get('output_id')}")
    
    # Download and check GLB size
    oid = d.get("output_id")
    dr = requests.get(f"http://localhost:5001/api/v1/download/{oid}", timeout=30)
    print(f"\nGLB size: {len(dr.content) / 1024:.0f} KB (HTTP {dr.status_code})")
else:
    print(f"Error: {d.get('error', d)}")
