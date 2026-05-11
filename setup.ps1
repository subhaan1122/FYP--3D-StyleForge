# ===========================================================================
# Avatar 3D Pipeline — Full Setup Script (Windows PowerShell)
# ===========================================================================
# Run this ONCE on your RTX 3090 PC to install everything.
#
# Usage:
#   Open PowerShell as Administrator
#   cd <project-root>\styleforge
#   .\setup.ps1
#
# Prerequisites:
#   - Python 3.10 or 3.11 installed and on PATH
#   - CUDA 12.1+ drivers installed
#   - Git installed
# ===========================================================================

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Avatar 3D Pipeline — Setup Script"     -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Check Python
# ---------------------------------------------------------------------------
Write-Host "[1/6] Checking Python..." -ForegroundColor Yellow
try {
    $pyVersion = python --version 2>&1
    Write-Host "  Found: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Python not found. Please install Python 3.10 or 3.11." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 2. Create virtual environment
# ---------------------------------------------------------------------------
$venvPath = ".\venv"
if (!(Test-Path $venvPath)) {
    Write-Host "[2/6] Creating virtual environment..." -ForegroundColor Yellow
    python -m venv $venvPath
    Write-Host "  Created: $venvPath" -ForegroundColor Green
} else {
    Write-Host "[2/6] Virtual environment already exists." -ForegroundColor Green
}

# Activate
Write-Host "  Activating virtual environment..." -ForegroundColor Yellow
& "$venvPath\Scripts\Activate.ps1"

# ---------------------------------------------------------------------------
# 3. Install PyTorch with CUDA 12.1
# ---------------------------------------------------------------------------
Write-Host "[3/6] Installing PyTorch with CUDA 12.1..." -ForegroundColor Yellow
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: PyTorch installation failed!" -ForegroundColor Red; exit 1 }

# Verify CUDA
python -c "import torch; print(f'  PyTorch {torch.__version__}  CUDA available: {torch.cuda.is_available()}  Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"

# ---------------------------------------------------------------------------
# 4. Install project dependencies
# ---------------------------------------------------------------------------
Write-Host "[4/6] Installing project dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt

# Optional: xatlas for high-quality UV unwrapping
Write-Host "  Installing xatlas (optional, for better texture quality)..." -ForegroundColor Yellow
pip install xatlas 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WARNING: xatlas installation failed. Texture baking will use fallback mode." -ForegroundColor DarkYellow
}

# ---------------------------------------------------------------------------
# 5. Clone and set up LHM (if not already present)
# ---------------------------------------------------------------------------
$lhmPath = Join-Path (Split-Path $PSScriptRoot) "models\lhm-source"
Write-Host "[5/6] Setting up LHM (Large Human Model)..." -ForegroundColor Yellow
Write-Host "  LHM path: $lhmPath" -ForegroundColor Gray

if (!(Test-Path $lhmPath)) {
    Write-Host "  Cloning LHM repository..." -ForegroundColor Yellow
    git clone https://github.com/3DAIGC/LHM.git $lhmPath
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Git clone failed!" -ForegroundColor Red; exit 1 }

    Write-Host "  Installing LHM dependencies..." -ForegroundColor Yellow
    Push-Location $lhmPath
    if (Test-Path "requirements.txt") {
        pip install -r requirements.txt
    }
    if (Test-Path "setup.py") {
        pip install -e .
    }
    Pop-Location
    Write-Host "  LHM setup complete." -ForegroundColor Green
} else {
    Write-Host "  LHM already exists at $lhmPath" -ForegroundColor Green
}

# Check for LHM pretrained weights (using junctions from lhm-weights)
$weightsScript = Join-Path $PSScriptRoot "..\scripts\setup_lhm_weights.ps1"
if (Test-Path $weightsScript) {
    Write-Host "  Linking LHM weights..." -ForegroundColor Yellow
    & $weightsScript
} else {
    Write-Host "  Weight setup script not found at: $weightsScript" -ForegroundColor Yellow
    Write-Host "  Run it manually: scripts\setup_lhm_weights.ps1" -ForegroundColor Yellow
}

# Verify checkpoint is accessible
$pretrained = Join-Path $lhmPath "pretrained_models"
$ckptFound = Get-ChildItem (Join-Path $lhmPath "exps") -Recurse -Filter "model.safetensors" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($ckptFound) {
    $sizeMB = [math]::Round($ckptFound.Length / 1MB, 0)
    Write-Host "  Model checkpoint found: $($ckptFound.Name) ($sizeMB MB)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  *** IMPORTANT ***" -ForegroundColor Red
    Write-Host "  LHM model checkpoint (model.safetensors) not found!" -ForegroundColor Red
    Write-Host "  Make sure models/lhm-weights/ contains the downloaded weights." -ForegroundColor Red
    Write-Host "  Then re-run: ..\scripts\setup_lhm_weights.ps1" -ForegroundColor Red
    Write-Host ""
}

# ---------------------------------------------------------------------------
# 6. Create required directories
# ---------------------------------------------------------------------------
Write-Host "[6/6] Creating directories..." -ForegroundColor Yellow
$dirs = @("outputs", "temp", "uploads", "logs", "backend\outputs", "backend\temp")
foreach ($dir in $dirs) {
    if (!(Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

# Install 2D backend deps
$backendReqs = Join-Path $PSScriptRoot "backend\requirements.txt"
if (Test-Path $backendReqs) {
    Write-Host "  Installing 2D backend dependencies..." -ForegroundColor Yellow
    pip install -r $backendReqs
}

Write-Host "  Directories created." -ForegroundColor Green

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Run verification:  python scripts\verify_setup.py"
Write-Host "  2. Start all:         .\start_all.ps1"
Write-Host "  3. Open frontend:     http://localhost:5002"
Write-Host "  4. API docs (3D):     http://localhost:5001/docs"
Write-Host "  5. API docs (2D):     http://localhost:5000/docs"
Write-Host ""
