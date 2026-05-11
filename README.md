# StyleForge — Prompt-Guided 3D Avatar Generation with Garment Transfer

End-to-end pipeline that takes a **2D person photo + garment description**, generates a **virtual try-on image** (IDM-VTON), and converts it into a **web-ready 3D GLB avatar** (LHM).


## Architecture

```
┌─────────────────────────────────────────────────────┐
│              React Frontend  (port 5002)             │
│      Upload photo · Describe outfit · View 3D       │
└───────────────┬──────────────────┬────────────────┘
                │                    ▲
                ▼                    │
┌─────────────────────────────────────────────────────┐
│           2D Try-On Backend  (port 5000)             │
│     IDM-VTON via HuggingFace  ·  Proxy to 3D        │
└───────────────┬──────────────────┬────────────────┘
                │                    ▲
                ▼                    │
┌─────────────────────────────────────────────────────┐
│           3D Avatar Service  (port 5001)             │
│  Image → LHM → Gaussian Splatting → Mesh → GLB      │
└─────────────────────────────────────────────────────┘
```


## Project Structure

```
StyleForge/
├── config.yaml              # 3D service configuration (paths, params, server)
├── requirements.txt         # 3D service Python dependencies
├── run_server.py            # Start the 3D avatar service (port 5001)
├── setup.ps1                # One-click setup script (Windows)
├── start_all.ps1            # Start all 3 services at once
├── test_pipeline.py         # Integration tests for the 3D pipeline
├── .gitignore               # Git ignore rules
│
├── app/                     # 3D Avatar Service (FastAPI)
│   ├── main.py              # FastAPI app factory
│   ├── config.py            # Config loader (reads config.yaml)
│   ├── api/
│   │   ├── routes.py        # REST endpoints (/api/v1/try-on/3d, /download, etc.)
│   │   └── schemas.py       # Pydantic request/response models
│   ├── core/
│   │   ├── pipeline.py      # Main orchestrator (image → GLB)
│   │   ├── lhm_wrapper.py   # LHM model loading & inference
│   │   ├── gaussian_to_mesh.py  # Gaussian Splatting PLY → mesh
│   │   ├── mesh_processor.py    # Mesh optimization (decimate, smooth, clean)
│   │   ├── glb_exporter.py      # Export mesh as GLB with textures
│   │   └── gpu_manager.py       # GPU memory management
│   └── utils/
│       ├── file_utils.py    # File system helpers
│       ├── image_utils.py   # Image preprocessing
│       └── logger.py        # Logging setup (loguru)
│
├── backend/                 # 2D Try-On Backend (FastAPI)
│   ├── main.py              # IDM-VTON API + 3D proxy
│   ├── requirements.txt     # Python dependencies
│   ├── .env.example         # Environment variable template
│   ├── outputs/             # Generated try-on images
│   └── temp/                # Temp files during processing
│
├── frontend/                # React Frontend (Vite)
│   ├── package.json         # Node.js dependencies
│   ├── vite.config.js       # Vite config with API proxy
│   ├── index.html           # Entry HTML
│   ├── run.py               # Start frontend + backend together
│   └── src/
│       ├── App.jsx          # Root component with routing
│       ├── pages/
│       │   ├── Home.jsx     # Landing page
│       │   └── TryOn.jsx    # Main try-on page (2D + 3D)
│       ├── components/
│       │   ├── viewer/ModelViewer.jsx   # Three.js 3D model viewer
│       │   ├── upload/FileUploader.jsx  # Image upload component
│       │   └── common/                  # Shared UI components
│       ├── api/
│       │   ├── client.js    # Axios HTTP client
│       │   ├── tryon.js     # Try-on API calls (2D + 3D)
│       │   └── mock.js      # Mock data for testing without backend
│       ├── hooks/
│       │   ├── usePolling.js    # Job status polling hook
│       │   └── useFileUpload.js # File upload validation hook
│       └── utils/
│           └── constants.js     # API endpoints & config constants
│
├── scripts/
│   └── verify_setup.py     # Verify all dependencies are installed
│
├── outputs/                 # Generated GLB files (auto-created)
├── temp/                    # Temporary pipeline files
├── uploads/                 # Uploaded images
└── logs/                    # Application logs
```


## Quick Start
|-------------|---------|
| CUDA        | 12.1+ |
| GPU         | RTX 3060 12GB+ (RTX 3090 24GB recommended) |
| Node.js     | 18+ (for frontend) |
| Git         | Latest |

### 1. Setup (run once)

```powershell
cd <project-root>/styleforge
.\setup.ps1
```

This installs PyTorch + CUDA, all Python dependencies, sets up LHM, and creates directories.

### 2. Configure

Edit `config.yaml` paths to match your system:
```yaml
lhm:
  repo_path: "D:/LHM"      # ← Path to your cloned LHM repository
```

Or use environment variables for portability:

```powershell
$env:LHM_REPO_PATH = "D:\LHM"

### 3. Verify



```powershell
.\start_all.ps1
```


```powershell
# Terminal 1 — 3D Service (port 5001)
# Terminal 2 — 2D Backend (port 5000)
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 5000 --reload

# Terminal 3 — Frontend (port 5002)
cd frontend
npm install    # first time only
npm run dev
```

### 5. Open in Browser

- **Frontend**: http://localhost:5002
- **2D API Docs**: http://localhost:5000/docs
- **3D API Docs**: http://localhost:5001/docs

---

## API Endpoints

### 2D Backend (port 5000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/try-on/2d` | Virtual try-on (IDM-VTON) |
| `POST` | `/api/v1/try-on/3d` | Proxy → 3D service |
| `GET`  | `/api/v1/status/{id}` | Job status |
| `GET`  | `/api/v1/download/{id}` | Download result |
| `GET`  | `/api/v1/history` | Recent outputs |

### 3D Service (port 5001)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/try-on/3d` | Generate GLB from image |
| `POST` | `/api/v1/convert-ply` | Convert PLY to GLB (skip LHM) |
| `GET`  | `/api/v1/status/{id}` | Job status |
| `GET`  | `/api/v1/download/{id}` | Download GLB file |
| `GET`  | `/health` | Health check + GPU status |

---

## How It Works

1. **User uploads photo + describes outfit** → React frontend
2. **IDM-VTON generates 2D try-on image** → 2D backend calls HuggingFace
3. **2D result sent to 3D service** → proxy or direct upload
4. **LHM reconstructs 3D Gaussians** → from single 2D image
5. **Gaussians → Mesh** → Poisson reconstruction
6. **Mesh optimization** → decimate, smooth, clean, fill holes
7. **GLB export** → UV unwrap, texture bake, PBR material
8. **User views 3D model** → Three.js GLTFLoader in browser

---

## Testing

```powershell
# Synthetic test (no LHM required)
python test_pipeline.py --synthetic

# Test with an existing PLY file
python test_pipeline.py --ply "D:\LHM\outputs\your_output.ply"

# Test with a specific image (requires LHM)
python test_pipeline.py --image "path\to\person.png"
```

---

## Transferring to Another PC

1. Copy this entire folder to the target PC
2. Install Python 3.10+ and CUDA 12.1+ on the target PC
3. Run `.\setup.ps1` (creates venv, installs deps, sets up LHM)
4. Edit `config.yaml` → set `lhm.repo_path` to the LHM location on that PC
5. Run `.\start_all.ps1`

Alternatively, set environment variables instead of editing config.yaml:

```powershell
$env:LHM_REPO_PATH = "E:\Models\LHM"
$env:AVATAR_3D_PORT = "5001"
python run_server.py
```

---

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | RTX 3060 12GB | RTX 3090 24GB |
| RAM | 16 GB | 32 GB |
| Storage | 20 GB free | 50 GB free |
| Python | 3.10 | 3.10 or 3.11 |
| CUDA | 12.1 | 12.1+ |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "LHM checkpoint not found" | Download weights from LHM repo, place at path in config.yaml |
| "CUDA out of memory" | Set `lhm.use_fp16: true` and `gpu.aggressive_cleanup: true` in config |
| "PLY file has no faces" | Expected — LHM outputs Gaussians, not meshes. `gaussian_to_mesh.py` handles this |
| GLB file too large | Reduce `mesh_processing.target_faces` or `texture.atlas_resolution` |
| 3D service unreachable | Start it first: `python run_server.py` |
| Frontend can't reach backend | Check proxy in `frontend/vite.config.js` targets port 5000 |
