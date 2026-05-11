"""Quick test: send person + garment to the 2D try-on API."""
import httpx
import time
import base64

print("Sending 2D try-on request...")
print("Person: bg removed.png")
print("Garment: Garment.jpg")
print()

start = time.time()

with open("bg removed.png", "rb") as person_f, open("Garment.jpg", "rb") as garment_f:
    files = {
        "user_image": ("person.png", person_f, "image/png"),
        "garment_reference": ("garment.jpg", garment_f, "image/jpeg"),
    }
    data = {
        "instruction": "a garment",
        "session_id": "test_session_001",
    }

    response = httpx.post(
        "http://localhost:5000/api/v1/try-on/2d",
        files=files,
        data=data,
        timeout=300.0,
    )

elapsed = round(time.time() - start, 2)
print(f"Response: {response.status_code} ({elapsed}s)")

if response.status_code == 200:
    result = response.json()
    print(f"Success: {result.get('success')}")
    print(f"Output ID: {result.get('output_id')}")
    print(f"Inference time: {result.get('inference_time_seconds')}s")
    print(f"Download URL: {result.get('download_url')}")

    # Save the result image
    img_b64 = result.get("image_base64", "")
    if img_b64:
        if "," in img_b64:
            img_b64 = img_b64.split(",", 1)[1]
        img_bytes = base64.b64decode(img_b64)
        output_path = "outputs/test_2d_result.png"
        with open(output_path, "wb") as f:
            f.write(img_bytes)
        print(f"Result saved to: {output_path} ({len(img_bytes)/1024:.1f} KB)")
    else:
        print("No base64 image in response")
else:
    print(f"Error: {response.text[:500]}")
