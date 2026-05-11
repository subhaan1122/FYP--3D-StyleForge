# StyleForge - Start All Services (Windows PowerShell)
# Starts the 3D Avatar Service (port 5001), 2D Backend (port 5000),
# and the React Frontend dev server (port 5002).
#
# Usage:
#   .\start_all.ps1                  # Start all 3 services
#   .\start_all.ps1 -SkipFrontend    # Backend + 3D only
#   .\start_all.ps1 -Only3D          # 3D service only

param(
    [switch]$SkipFrontend,
    [switch]$Only3D
)

$ErrorActionPreference = "Continue"
$ROOT = $PSScriptRoot

Write-Host ""
Write-Host "  =============================================" -ForegroundColor Cyan
Write-Host "       StyleForge - Starting Services          " -ForegroundColor Cyan
Write-Host "  =============================================" -ForegroundColor Cyan
Write-Host ""

# â”€â”€ Resolve Python â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Use the known absolute path first; fall back to PATH lookup.
$pythonExe = "D:\python\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $pythonExe -or -not (Test-Path $pythonExe)) {
    Write-Host "ERROR: Python not found at D:\python\python.exe and not on PATH." -ForegroundColor Red
    exit 1
}
Write-Host "[INFO] Using Python: $pythonExe" -ForegroundColor DarkGray

# â”€â”€ Helper: kill any process already using a port â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function Kill-Port($port) {
    $pids = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique
    foreach ($p in $pids) {
        if ($p -and $p -ne 0) {
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
            Write-Host "[INFO] Killed stale process PID $p on port $port" -ForegroundColor DarkGray
        }
    }
}

# Clear stale processes
Kill-Port 5001
Kill-Port 5000
Kill-Port 5002
Start-Sleep -Seconds 1

# â”€â”€ [1] Start 3D Avatar Service (port 5001) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Host "[1] Starting 3D Avatar Service on port 5001..." -ForegroundColor Green
$env:PYTHONPATH = $ROOT
Start-Process -FilePath $pythonExe `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5001", "--log-level", "info" `
    -WorkingDirectory $ROOT `
    -WindowStyle Normal

Start-Sleep -Seconds 3

if (-not $Only3D) {
    # â”€â”€ [2] Start 2D Try-On Backend (port 5000) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    Write-Host "[2] Starting 2D Try-On Backend on port 5000..." -ForegroundColor Green
    $backendDir = Join-Path $ROOT "backend"
    Start-Process -FilePath $pythonExe `
        -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000", "--reload" `
        -WorkingDirectory $backendDir `
        -WindowStyle Normal

    Start-Sleep -Seconds 3

    if (-not $SkipFrontend) {
        # â”€â”€ [3] Start React Frontend (port 5002) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        Write-Host "[3] Starting React Frontend on port 5002..." -ForegroundColor Green
        $frontendDir = Join-Path $ROOT "frontend"

        # Install deps if needed
        if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
            Write-Host "    Installing npm dependencies..." -ForegroundColor Yellow
            Push-Location $frontendDir
            & npm.cmd install
            Pop-Location
        }

        Start-Process -FilePath "npm.cmd" `
            -ArgumentList "run", "dev" `
            -WorkingDirectory $frontendDir `
            -WindowStyle Normal

        Start-Sleep -Seconds 4
    }
}

# â”€â”€ Verify services â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Host ""
Write-Host "  Verifying services..." -ForegroundColor Cyan

# Helper: wait up to $maxWait seconds for a port to start listening.
# The 3D service (5001) imports PyTorch + LHM weights and takes 15-30 s to bind.
# Ports 5000 and 5002 are fast (< 5 s).
function Wait-Port($port, $maxWait = 10, $interval = 2) {
    $elapsed = 0
    while ($elapsed -lt $maxWait) {
        $conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
        if ($conn) { return $true }
        Start-Sleep -Seconds $interval
        $elapsed += $interval
    }
    return $false
}

$ok = $true
foreach ($entry in @(
    @{ port = 5001; label = "3D Service "; maxWait = 45 },
    @{ port = 5000; label = "2D Backend "; maxWait = 15 },
    @{ port = 5002; label = "Frontend   "; maxWait = 20 }
)) {
    $port    = $entry.port
    $label   = $entry.label
    $maxWait = $entry.maxWait

    if ($port -eq 5002 -and ($SkipFrontend -or $Only3D)) { continue }
    if ($port -eq 5000 -and $Only3D) { continue }

    Write-Host "    Waiting for $label (port $port)..." -ForegroundColor DarkGray -NoNewline
    $up = Wait-Port $port $maxWait
    if ($up) {
        Write-Host " UP" -ForegroundColor Green
    } else {
        Write-Host " NOT STARTED (check the window that opened)" -ForegroundColor Red
        $ok = $false
    }
}

Write-Host ""
Write-Host "  =============================================" -ForegroundColor Cyan
Write-Host "  Services:" -ForegroundColor White
Write-Host "    3D Service  ->  http://localhost:5001/docs" -ForegroundColor Green
if (-not $Only3D) {
    Write-Host "    2D Backend  ->  http://localhost:5000/docs" -ForegroundColor Green
    if (-not $SkipFrontend) {
        Write-Host "    Frontend    ->  http://localhost:5002" -ForegroundColor $(if ($ok) { 'Green' } else { 'Yellow' })
    }
}
Write-Host "  =============================================" -ForegroundColor Cyan
if (-not $ok) {
    Write-Host "  WARNING: Some services failed to start. Check the opened windows." -ForegroundColor Red
}
Write-Host ""


