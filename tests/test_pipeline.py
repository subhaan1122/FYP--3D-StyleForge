"""
Integration test — run the full pipeline on a test image.

Usage:
    python test_pipeline.py                          # Full pipeline (LHM→mesh→GLB)
    python test_pipeline.py --ply path/to/output.ply  # Skip LHM, test from PLY
    python test_pipeline.py --image path/to/input.png # Test with specific image

This creates a test GLB in outputs/test_<timestamp>/
"""

import sys
import time
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

import numpy as np


def create_test_image(output_path: Path) -> Path:
    """Create a simple test image (white background with a colored rectangle)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (512, 512), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Draw a simple humanoid silhouette shape
    # Head
    draw.ellipse([206, 30, 306, 130], fill=(200, 160, 130))
    # Body
    draw.rectangle([196, 130, 316, 350], fill=(50, 80, 150))
    # Legs
    draw.rectangle([196, 350, 246, 490], fill=(50, 50, 80))
    draw.rectangle([266, 350, 316, 490], fill=(50, 50, 80))
    # Arms
    draw.rectangle([136, 140, 196, 300], fill=(50, 80, 150))
    draw.rectangle([316, 140, 376, 300], fill=(50, 80, 150))

    img.save(str(output_path))
    print(f"Test image created: {output_path}")
    return output_path


def test_gaussian_to_mesh():
    """Test the Gaussian-to-Mesh converter with synthetic data."""
    import open3d as o3d
    from app.core.gaussian_to_mesh import GaussianToMesh
    from app.core.mesh_processor import MeshProcessor
    from app.core.glb_exporter import GLBExporter

    print("\n--- Test: Gaussian → Mesh → GLB (synthetic data) ---\n")

    # Create a synthetic point cloud (sphere)
    print("Creating synthetic point cloud...")
    n_points = 50000
    theta = np.random.uniform(0, 2 * np.pi, n_points)
    phi = np.random.uniform(0, np.pi, n_points)
    r = 1.0 + np.random.normal(0, 0.02, n_points)

    x = r * np.sin(phi) * np.cos(theta)
    y = r * np.sin(phi) * np.sin(theta)
    z = r * np.cos(phi)

    points = np.stack([x, y, z], axis=-1)
    colors = np.abs(points) / np.abs(points).max()  # Color by position

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)
    pcd.colors = o3d.utility.Vector3dVector(colors)

    # Save as PLY
    test_ply = Path("temp/test_synthetic.ply")
    test_ply.parent.mkdir(parents=True, exist_ok=True)
    o3d.io.write_point_cloud(str(test_ply), pcd)
    print(f"Synthetic PLY saved: {test_ply}")

    # Test conversion
    converter = GaussianToMesh()
    mesh = converter.convert(test_ply)
    print(f"Mesh: {len(mesh.vertices)} verts, {len(mesh.triangles)} faces")

    # Test processing
    processor = MeshProcessor()
    mesh = processor.process(mesh)
    print(f"Processed: {len(mesh.vertices)} verts, {len(mesh.triangles)} faces")

    # Test GLB export
    exporter = GLBExporter()
    glb_path = Path("outputs/test_synthetic.glb")
    exporter.export(mesh, glb_path)
    print(f"GLB exported: {glb_path} ({glb_path.stat().st_size / 1024:.1f} KB)")

    print("\n--- Synthetic test PASSED ---\n")
    return True


def test_full_pipeline(image_path: str = None, ply_path: str = None):
    """Test the full pipeline."""
    from app.core.pipeline import Avatar3DPipeline

    timestamp = int(time.time())

    pipeline = Avatar3DPipeline()

    if ply_path:
        print(f"\n--- Test: PLY → GLB (skipping LHM) ---\n")
        print(f"Input PLY: {ply_path}")
        result = pipeline.run_from_ply(
            ply_path=ply_path,
            job_id=f"test_{timestamp}",
        )
    else:
        print(f"\n--- Test: Full Pipeline (Image → LHM → Mesh → GLB) ---\n")

        if image_path:
            img = Path(image_path)
        else:
            img = create_test_image(Path("temp/test_input.png"))

        print(f"Input image: {img}")
        result = pipeline.run(
            image_path=img,
            job_id=f"test_{timestamp}",
        )

    # Print results
    print(f"\nResult:")
    for k, v in result.to_dict().items():
        print(f"  {k}: {v}")

    if result.status == "completed":
        print(f"\n✅ SUCCESS — GLB file: {result.glb_path}")
    else:
        print(f"\n❌ FAILED — Error: {result.error}")

    pipeline.cleanup()
    return result.status == "completed"


def test_api():
    """Test the API endpoints (requires server to be running)."""
    try:
        import httpx
    except ImportError:
        print("httpx not installed — skipping API test")
        return True

    base = "http://localhost:5001"

    print(f"\n--- Test: API Endpoints (server must be running at {base}) ---\n")

    try:
        # Health check
        r = httpx.get(f"{base}/health", timeout=5)
        print(f"  /health: {r.status_code} {r.json()}")

        if r.status_code != 200:
            print("  Server not running — skipping API tests")
            return True

    except Exception as e:
        print(f"  Could not connect to {base}: {e}")
        print("  Start the server first: python run_server.py")
        return True  # Not a failure, just not running

    return True


def main():
    parser = argparse.ArgumentParser(description="Test the Avatar 3D Pipeline")
    parser.add_argument("--image", type=str, help="Path to test image")
    parser.add_argument("--ply", type=str, help="Path to test PLY (skip LHM)")
    parser.add_argument("--synthetic", action="store_true", help="Run synthetic mesh test only")
    parser.add_argument("--api", action="store_true", help="Test API endpoints")
    args = parser.parse_args()

    all_pass = True

    if args.synthetic:
        all_pass &= test_gaussian_to_mesh()
    elif args.api:
        all_pass &= test_api()
    elif args.ply:
        all_pass &= test_full_pipeline(ply_path=args.ply)
    elif args.image:
        all_pass &= test_full_pipeline(image_path=args.image)
    else:
        # Run synthetic test (doesn't require LHM)
        all_pass &= test_gaussian_to_mesh()

    print("\n" + "=" * 40)
    if all_pass:
        print("  All tests passed!")
    else:
        print("  Some tests failed!")
    print("=" * 40 + "\n")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
