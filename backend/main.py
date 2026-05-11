import os
import io
import asyncio
import base64
import uuid
import time
import traceback
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError

from PIL import Image

load_dotenv()

# ── Model adapter (makes switching IDM-VTON ↔ another model trivial) ──
# When running from the project root: from backend.models import ...
# When running from backend/: from models import ...
try:
    from backend.models import get_model, ImageEnhancer
except ImportError:
    from models import get_model, ImageEnhancer

TRYON_MODEL_NAME = os.getenv("TRYON_MODEL", "idm_vton")
tryon_model = get_model(TRYON_MODEL_NAME)
image_enhancer = ImageEnhancer()

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

# URL of the 3D avatar generation service (used by proxy endpoints below)
AVATAR_3D_SERVICE_URL = os.getenv("AVATAR_3D_URL", "http://localhost:5001")

app = FastAPI(title="StyleForge Virtual Try-On API", version="2.0.0")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print("422 VALIDATION ERROR:", exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")


def preprocess_image(image_bytes: bytes, max_size: int = 1024) -> Image.Image:
    """
    Preprocess uploaded image: RGBA→RGB over white, resize to max_size.
    Raised from 768→1024 to preserve more detail for the diffusion model.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    background = Image.new("RGBA", img.size, (255, 255, 255, 255))
    background.paste(img, mask=img.split()[3])
    img = background.convert("RGB")
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    return img

def save_temp_image(img: Image.Image, name: str) -> str:
    path = TEMP_DIR / f"{name}_{uuid.uuid4().hex[:8]}.png"
    img.save(str(path))
    return str(path)


@app.get("/")
def root():
    return {"status": "running", "model": tryon_model.name, "docs": "/docs"}

@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": tryon_model.name,
        "enhancer_enabled": image_enhancer.enabled,
    }


@app.post("/api/v1/try-on/2d")
async def virtual_tryon_2d(request: Request):
    try:
        form = await request.form()
        print("Received form fields:", list(form.keys()))

        person_field = (
            form.get("user_image") or
            form.get("person_image") or
            form.get("image")
        )
        garment_field = (
            form.get("garment_reference") or
            form.get("garment_image") or
            form.get("garment")
        )

        instruction = str(form.get("instruction") or form.get("prompt") or "").strip()
        session_id  = str(form.get("session_id", ""))

        if person_field is None:
            raise HTTPException(400, f"No person image found. Got: {list(form.keys())}")

        person_bytes = await person_field.read()
        person_pil   = preprocess_image(person_bytes)
        person_path  = save_temp_image(person_pil, "person")

        has_garment  = False
        garment_path = None
        if garment_field and hasattr(garment_field, "read"):
            garment_bytes = await garment_field.read()
            if len(garment_bytes) > 100:
                garment_pil  = preprocess_image(garment_bytes)
                garment_path = save_temp_image(garment_pil, "garment")
                has_garment  = True

        if not has_garment:
            raise HTTPException(400, "Please upload a garment image. The try-on model requires both a person photo and a garment photo.")

        print(f"Calling {tryon_model.name}... instruction={instruction!r}")
        start = time.time()

        # ── Model-agnostic call via adapter ──────────────────────────────
        # IMPORTANT: tryon_model.predict() is a BLOCKING SYNCHRONOUS call
        # (gradio_client internally uses requests/httpx to call HuggingFace).
        # Running it directly in an async handler blocks the entire uvicorn
        # event loop for 60-300 s, preventing keepalives from being sent and
        # causing the Vite proxy to drop the connection → "Network error".
        # Fix: run it in the default ThreadPoolExecutor so the event loop
        # stays free to handle health checks and other requests while waiting.
        loop = asyncio.get_event_loop()
        result_image_path = await loop.run_in_executor(
            None,
            lambda: tryon_model.predict(
                person_path=person_path,
                garment_path=garment_path,
                instruction=instruction if instruction else "a garment",
            )
        )

        elapsed = round(time.time() - start, 2)
        print(f"{tryon_model.name} done in {elapsed}s")

        if not result_image_path or not Path(str(result_image_path)).exists():
            raise HTTPException(500, f"Model returned no image. Path: {result_image_path}")

        # ── Optional quality enhancement ────────────────────────────────
        output_id   = str(uuid.uuid4())[:8]
        enhanced_path = OUTPUT_DIR / f"tryon_{output_id}.png"
        image_enhancer.enhance(result_image_path, enhanced_path)

        with open(enhanced_path, "rb") as f:
            result_image_data = f.read()

        b64 = base64.b64encode(result_image_data).decode()
        print(f"Saved: tryon_{output_id}.png")

        try:
            Path(person_path).unlink()
            if garment_path: Path(garment_path).unlink()
        except Exception:
            pass

        return JSONResponse({
            "success":                True,
            "job_id":                 output_id,
            "output_id":              output_id,
            "status":                 "completed",
            "result_image":           f"data:image/png;base64,{b64}",
            "image_base64":           f"data:image/png;base64,{b64}",
            "download_url":           f"/outputs/tryon_{output_id}.png",
            "inference_time_seconds": elapsed,
            "session_id":             session_id,
        })

    except HTTPException:
        raise
    except Exception as e:
        # Print full traceback so the real cause is visible in the backend window
        traceback.print_exc()
        raise HTTPException(500, f"Pipeline error: {str(e)}")


@app.get("/api/v1/status/{job_id}")
async def job_status(job_id: str):
    # First check local 2D outputs
    path = OUTPUT_DIR / f"tryon_{job_id}.png"
    if path.exists():
        return {"job_id": job_id, "status": "completed", "download_url": f"/outputs/tryon_{job_id}.png",
                "result": {"download_url": f"/outputs/tryon_{job_id}.png", "preview_url": f"/outputs/tryon_{job_id}.png"}}

    # Not a 2D job — try the 3D service
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{AVATAR_3D_SERVICE_URL}/api/v1/status/{job_id}")
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception:
        pass

    return {"job_id": job_id, "status": "not_found"}

@app.get("/api/v1/history")
def get_history():
    files = sorted(OUTPUT_DIR.glob("tryon_*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"outputs": [{"id": f.stem.replace("tryon_", ""), "url": f"/outputs/{f.name}"} for f in files[:20]]}

@app.get("/api/v1/download/{output_id}")
async def download_result(output_id: str):
    # First check local 2D outputs
    path = OUTPUT_DIR / f"tryon_{output_id}.png"
    if path.exists():
        return FileResponse(path, media_type="image/png", filename=f"tryon_{output_id}.png")

    # Not a 2D file — proxy to the 3D service for GLB download
    import httpx
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(f"{AVATAR_3D_SERVICE_URL}/api/v1/download/{output_id}")
            if resp.status_code == 200:
                # Save the GLB locally and serve it
                glb_path = OUTPUT_DIR / f"avatar_3d_{output_id}.glb"
                with open(glb_path, "wb") as f:
                    f.write(resp.content)
                return FileResponse(
                    str(glb_path),
                    media_type="model/gltf-binary",
                    filename=f"styleforge_3d_{output_id}.glb",
                    headers={"Content-Disposition": f'attachment; filename="styleforge_3d_{output_id}.glb"'},
                )
    except Exception as e:
        print(f"[Download Proxy] 3D service error: {e}")

    raise HTTPException(404, "Output not found.")


# =============================================================================
#  3D PROXY — forwards /api/v1/try-on/3d to the 3D service (port 5001)
# =============================================================================
#
#  The React frontend sends ALL requests to this server (port 5000).
#  When the user clicks "Generate 3D", the frontend calls POST /api/v1/try-on/3d.
#
#  This proxy endpoint:
#    1. Reads the form data (user_image, output_id, instruction, session_id)
#    2. Forwards the request to the 3D service at http://localhost:5001
#    3. Returns the 3D service's response back to the frontend
#
#  The 3D service is MODEL-AGNOSTIC — it doesn't care which 2D model produced
#  the image. If you switch from IDM-VTON to Gemini or any other model,
#  NOTHING changes in the 3D pipeline.
# =============================================================================


@app.post("/api/v1/try-on/3d")
async def virtual_tryon_3d(request: Request):
    """
    Proxy endpoint for 3D avatar generation.

    Receives the same form fields as the 2D endpoint:
      - user_image: the person's photo (File)
      - output_id: ID from the 2D pipeline (so the 3D service finds the try-on result)
      - instruction: text prompt
      - session_id: session identifier

    Forwards everything to the 3D service (port 5001) and returns its response.
    """
    import httpx

    try:
        form = await request.form()
        print(f"[3D Proxy] Received form fields: {list(form.keys())}")

        # Build the forwarding payload
        # We send multipart form data to the 3D service
        files_to_send = {}
        data_to_send = {}

        # Forward output_id (the 3D service uses this to find the 2D result PNG)
        output_id = form.get("output_id")
        if output_id:
            data_to_send["output_id"] = str(output_id)

        # Forward text fields
        for field_name in ("instruction", "session_id"):
            value = form.get(field_name)
            if value:
                data_to_send[field_name] = str(value)

        # Forward the user_image file if provided
        image_field = (
            form.get("user_image") or
            form.get("image") or
            form.get("result_image")
        )
        if image_field and hasattr(image_field, "read"):
            image_bytes = await image_field.read()
            if len(image_bytes) > 100:
                filename = getattr(image_field, "filename", "image.png")
                content_type = getattr(image_field, "content_type", "image/png")
                files_to_send["user_image"] = (filename, image_bytes, content_type)

        target_url = f"{AVATAR_3D_SERVICE_URL}/api/v1/try-on/3d"
        print(f"[3D Proxy] Forwarding to {target_url}")
        print(f"[3D Proxy] Data fields: {list(data_to_send.keys())}")
        print(f"[3D Proxy] File fields: {list(files_to_send.keys())}")

        # Forward to the 3D service with a generous timeout (3D generation is slow)
        async with httpx.AsyncClient(timeout=600.0) as client:
            response = await client.post(
                target_url,
                data=data_to_send,
                files=files_to_send if len(files_to_send) > 0 else None,
            )

        print(f"[3D Proxy] 3D service returned status {response.status_code}")

        # Return the 3D service's response directly to the frontend
        return JSONResponse(
            status_code=response.status_code,
            content=response.json(),
        )

    except httpx.ConnectError:
        print("[3D Proxy] ERROR: Cannot reach 3D service at", AVATAR_3D_SERVICE_URL)
        raise HTTPException(
            503,
            "3D service is not running. Start it with: "
            "cd styleforge && python run_server.py"
        )
    except httpx.TimeoutException:
        print("[3D Proxy] ERROR: 3D service timed out")
        raise HTTPException(504, "3D generation timed out (>10 minutes)")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[3D Proxy] ERROR: {str(e)}")
        raise HTTPException(500, f"3D proxy error: {str(e)}")


@app.get("/api/v1/status-3d/{job_id}")
async def status_3d_proxy(job_id: str):
    """
    Proxy for 3D job status polling.
    The frontend's usePolling hook calls /api/v1/status/{job_id}.
    For 3D jobs, this forwards to the 3D service.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{AVATAR_3D_SERVICE_URL}/api/v1/status/{job_id}"
            )
        return JSONResponse(
            status_code=response.status_code,
            content=response.json(),
        )
    except httpx.ConnectError:
        return JSONResponse({"job_id": job_id, "status": "service_unavailable"})
    except Exception:
        return JSONResponse({"job_id": job_id, "status": "error"})