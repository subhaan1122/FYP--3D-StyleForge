# StyleForge — Virtual Try-On (2D) + Image-to-3D Avatar (GLB)

StyleForge is an end-to-end demo that:

1) generates a **2D virtual try-on** image (person + garment) via a **2D FastAPI backend**
2) converts a 2D result image into a **web-ready 3D avatar** via a **3D FastAPI service** (default backend: **Hi3D / hitem3d.ai API**)
3) provides a **React + Vite** UI to upload, preview, generate, and view the 3D output.

Default local ports:

- Frontend (Vite): `http://localhost:5002`
- 2D Backend (FastAPI): `http://localhost:5000`
- 3D Service (FastAPI): `http://localhost:5001`

---

## Architecture

```
React Frontend (5002)
  └─ calls /api/* (via Vite proxy)
       ↓
2D Backend (5000)
  ├─ POST /api/v1/try-on/2d  (IDM-VTON via HuggingFace Space)
  └─ POST /api/v1/try-on/3d  (proxy → 3D service)
       ↓
3D Service (5001)
  ├─ POST /api/v1/try-on/3d  (async job + polling)
  └─ Hi3D cloud API (DEFAULT in config.yaml) → GLB
```

Key integration contract:

- 2D backend saves outputs as `backend/outputs/tryon_{output_id}.png`.
- 3D service can receive `output_id` and auto-locate that file (or accept an uploaded image).

---

## Repo Layout (what runs what)

```
.
├─ app/                    # 3D Avatar Service (FastAPI)
│  ├─ main.py               # FastAPI app (port 5001)
│  ├─ api/routes.py         # /api/v1/try-on/3d, /status, /download, /convert-ply
│  ├─ core/pipeline.py      # Image → Hi3D (hitem3d.ai) → GLB
│  └─ utils/                # logging, file utilities, preprocessing
│
├─ backend/                 # 2D Try-On Backend (FastAPI)
│  ├─ main.py               # /api/v1/try-on/2d + proxy endpoints
│  └─ models/               # model adapters (default: IDM-VTON)
│
├─ frontend/                # React + Vite UI (port 5002)
│  ├─ vite.config.js        # proxies /api → 5000
│  ├─ run.py                # convenience: start frontend + 2D backend
│  └─ src/                  # pages/components/hooks
│
├─ config.yaml              # 3D service configuration
├─ requirements.txt         # 3D service python deps
├─ backend/requirements.txt # 2D backend python deps
├─ run_server.py            # start 3D service (uvicorn)
├─ setup.ps1                # Windows full setup script (GPU-oriented)
├─ start_all.ps1            # Windows: start 3D + 2D + frontend
└─ scripts/verify_setup.py  # setup verification (GPU/local-backend checks)
```

Generated/runtime folders (created automatically):

- `backend/outputs/` — 2D try-on images (PNG)
- `backend/temp/` — temporary 2D files
- `outputs/<job_id>/` — 3D outputs (`<job_id>.glb`)
- `temp/<job_id>/` — 3D intermediate files
- `uploads/<job_id>/` — uploaded images for 3D jobs
- `logs/` — rotating logs (3D service)

---

## Requirements (default: Hi3D cloud)

The default running setup uses the **Hi3D / hitem3d.ai cloud API** (configured in [config.yaml](config.yaml)).

- No local GPU or model weights are required for the 3D step.
- You must provide API credentials via the root `.env`.

Baseline tooling:

- Windows + PowerShell (optional, for `setup.ps1` / `start_all.ps1`)
- Python 3.10+ (3.10/3.11 recommended)
- Node.js 18+ (frontend)

Notes:

- For Hi3D cloud mode you do **not** need CUDA, model weights, or a local GPU.
- `setup.ps1` / `scripts/verify_setup.py` are intended for a full local-GPU environment and may check CUDA-related dependencies (not required for the Hi3D-only path).

---

## Quick Start (Windows, recommended)

### 1) One-time setup

Option A (Hi3D cloud mode, no GPU required):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
pip install -r backend/requirements.txt
```

Option B (full setup script for a GPU dev machine with Git + CUDA drivers installed):

This is not required for the default Hi3D cloud mode.

```powershell
.\setup.ps1
```

Then set credentials in the root `.env`:

- `HITEM3D_ACCESS_KEY`
- `HITEM3D_SECRET_KEY`

And confirm [config.yaml](config.yaml) has `lhm.use_hitem3d: true`.

### 2) Start everything (3D + 2D + frontend)

```powershell
.\start_all.ps1
```

Note: [start_all.ps1](start_all.ps1) launches services using a Python executable chosen by the script (it tries `D:\python\python.exe` first, then falls back to `python` on PATH). If you want it to use the repo's `venv`, adjust the script or activate the venv before running equivalent manual commands.

If you used Option A above (installed into `./venv`), the simplest fix is to edit [start_all.ps1](start_all.ps1) and set `$pythonExe` to `"$ROOT\venv\Scripts\python.exe"`.

Open:

- Frontend: `http://localhost:5002`
- 2D docs: `http://localhost:5000/docs`
- 3D docs: `http://localhost:5001/docs`

---

## Manual Start (if you prefer separate terminals)

### 3D service (port 5001)

From the repo root:

```powershell
python run_server.py
```

### 2D backend (port 5000)

```powershell
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 5000 --reload
```

### Frontend (port 5002)

```powershell
cd frontend
npm install
npm run dev
```

Alternative: start **frontend + 2D backend** together with:

```powershell
python frontend/run.py
```

This convenience script will also create `backend/.env` from `backend/.env.example` if it is missing. (You still need to start the 3D service separately.)

Note: the frontend proxies `/api` and `/outputs` to `http://localhost:5000` via [frontend/vite.config.js](frontend/vite.config.js).

---

## Configuration

### 3D service config: [config.yaml](config.yaml)

The 3D service reads [config.yaml](config.yaml) via [app/config.py](app/config.py).

Common knobs:

- `server.host` / `server.port` (default 5001)
- `integration.tryon_outputs_dir` (default `backend/outputs`)
- `paths.output_dir` / `paths.temp_dir` / `paths.upload_dir`
- `lhm.use_hitem3d` (cloud mode)

Note: the YAML section is named `lhm:` for historical reasons; it contains the Hi3D toggle (`use_hitem3d`) that selects the image-to-3D backend.

Environment overrides supported by the 3D service:

- `TRYON_OUTPUTS_DIR` — overrides `integration.tryon_outputs_dir`
- `AVATAR_3D_PORT` — overrides `server.port`

### Secrets / API keys

The repo includes a root `.env` file. The 3D service loads it on startup (via `python-dotenv`) so cloud credentials can be provided without hardcoding them.

If using **Hi3D cloud** (hitem3d.ai), set these in the root `.env`:

- `HITEM3D_ACCESS_KEY`
- `HITEM3D_SECRET_KEY`

If using the **2D backend** with IDM-VTON, create `backend/.env` (copy from [backend/.env.example](backend/.env.example)) and set:

- `HF_TOKEN` (recommended for HuggingFace access/priority)

---

## API

### 2D backend (port 5000)

- `POST /api/v1/try-on/2d`
  - multipart form fields: `user_image` (file), `garment_reference` (file), `instruction` (text), `session_id` (text)
  - returns: `output_id` and a base64 preview image (and saves `backend/outputs/tryon_{output_id}.png`)

- `POST /api/v1/try-on/3d`
  - proxy to the 3D service; forwards `output_id` and/or `user_image`

- `GET /api/v1/status/{id}`
  - returns job status for 2D outputs, otherwise forwards to 3D status

- `GET /api/v1/download/{id}`
  - downloads 2D PNG or proxies 3D output

- `GET /api/v1/history`
  - lists recent 2D outputs

### 3D service (port 5001)

- `POST /api/v1/try-on/3d`
  - accepts (model-agnostic):
    - `output_id` (to locate a saved 2D output), or
    - `user_image` (file upload), or
    - `image_base64` / `image_path` (JSON)
  - response is **asynchronous** by default: returns `{ status: "processing", job_id }`, then poll status

- `GET /api/v1/status/{job_id}`
  - polling endpoint used by the frontend

- `GET /api/v1/download/{job_id}`
  - downloads the generated output:
    - `.glb`

- `POST /api/v1/convert-ply`
  - convert an existing Gaussian PLY to GLB

- `GET /health`
  - GPU availability + basic status

---

## Testing

Pipeline tests live under [tests/](tests/):

```powershell
# Synthetic Gaussian→Mesh→GLB test
python tests/test_pipeline.py --synthetic

# Convert an existing PLY to GLB
python tests/test_pipeline.py --ply "path\\to\\gaussian_output.ply"

# Test the 3D service health (server must be running)
python tests/test_pipeline.py --api
```

There are also ad-hoc quality scripts:

- [scripts/verify_setup.py](scripts/verify_setup.py) — full local-GPU environment verification (optional)
- [test_3d_quality.py](test_3d_quality.py) — API call helper for 3D quality runs
- [backend/test_quality.py](backend/test_quality.py) — 2D try-on quality check

---

## Troubleshooting

- Frontend can't reach APIs
  - Ensure frontend is running on 5002 and backend on 5000; Vite proxy is configured in [frontend/vite.config.js](frontend/vite.config.js).

- 3D jobs stay in `processing`
  - First run can be slow (model warmup / cloud queue). Check `logs/avatar3d_*.log` and the 3D docs at `http://localhost:5001/docs`.

- Hi3D cloud mode fails immediately
  - Ensure `HITEM3D_ACCESS_KEY` and `HITEM3D_SECRET_KEY` exist in the root `.env`, and that `lhm.use_hitem3d: true` in [config.yaml](config.yaml).

- 2D try-on fails
  - Ensure `backend/.env` exists (copy from [backend/.env.example](backend/.env.example)). IDM-VTON depends on HuggingFace Space availability and network access.

---

## Appendix (optional): alternative image-to-3D backends

This repo contains additional backend paths that are not part of the default Hi3D-running setup.

- `lhm.use_remote_api` can be enabled to use a remote backend that returns an `.mp4` preview.
- Local backend model folders (if enabled): by default [config.yaml](config.yaml) points to `../models/lhm-source` and `../models/lhm-weights` (one level above this repo).
- Env override: `LHM_REPO_PATH` (overrides `lhm.repo_path`).

If you enable the local backend and see missing weights, re-run validation:

```powershell
python scripts/verify_setup.py
```
