#!/usr/bin/env python3
"""
run.py — Start both servers with ONE command.
Location: frontend/run.py

Usage:
    python run.py
"""

import subprocess
import sys
import time
import signal
import threading
import platform
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent.parent  # project root (StyleForge/)
BACKEND_DIR  = ROOT / "backend"              # backend/
FRONTEND_DIR = Path(__file__).parent         # frontend/

BACKEND_PORT  = 5000
FRONTEND_PORT = 5002

# ── Windows fix: npm → npm.cmd ────────────────────────────────────────────────
NPM = "npm.cmd" if platform.system() == "Windows" else "npm"

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def log(prefix, line, color=RESET):
    print(f"{color}{BOLD}[{prefix}]{RESET} {line}", flush=True)

def stream(proc, prefix, color):
    for line in iter(proc.stdout.readline, ""):
        if line:
            log(prefix, line.rstrip(), color)

def check_env():
    env_file = BACKEND_DIR / ".env"
    if not env_file.exists():
        # Auto-create from example if available
        example = BACKEND_DIR / ".env.example"
        if example.exists():
            import shutil
            shutil.copy2(example, env_file)
            print(f"{YELLOW}[SETUP] Created .env from .env.example{RESET}")
            return
        print(f"\n{RED}ERROR: backend/.env not found!{RESET}")
        print(r"Create it:  copy backend\.env.example backend\.env")
        sys.exit(1)

def install_backend_deps():
    req = BACKEND_DIR / "requirements.txt"
    if not req.exists():
        return
    print(f"{CYAN}[SETUP] Installing Python dependencies...{RESET}")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req), "-q"], check=True)
    print(f"{GREEN}[SETUP] Python deps ready.{RESET}")

def install_frontend_deps():
    if not (FRONTEND_DIR / "node_modules").exists():
        print(f"{CYAN}[SETUP] Running npm install...{RESET}")
        subprocess.run([NPM, "install"], cwd=FRONTEND_DIR, check=True)
        print(f"{GREEN}[SETUP] npm deps ready.{RESET}")

def start_backend():
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "0.0.0.0", "--port", str(BACKEND_PORT), "--reload"],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

def start_frontend():
    return subprocess.Popen(
        [NPM, "run", "dev"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

def main():
    print(f"""
{BOLD}{GREEN}╔══════════════════════════════════════════════╗
║    StyleForge — Virtual Try-On Dev Server    ║
╚══════════════════════════════════════════════╝{RESET}
""")
    check_env()
    install_backend_deps()
    install_frontend_deps()

    print(f"\n{GREEN}Starting servers...{RESET}\n")
    backend_proc  = start_backend()
    time.sleep(2)
    frontend_proc = start_frontend()

    threading.Thread(target=stream, args=(backend_proc,  "BACKEND ", CYAN),  daemon=True).start()
    threading.Thread(target=stream, args=(frontend_proc, "FRONTEND", GREEN), daemon=True).start()

    time.sleep(3)
    print(f"""
{BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {GREEN}✓ Backend   →  http://localhost:{BACKEND_PORT}{RESET}
  {GREEN}✓ API Docs  →  http://localhost:{BACKEND_PORT}/docs{RESET}
  {GREEN}✓ Frontend  →  http://localhost:{FRONTEND_PORT}{RESET}
{BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}
  Press Ctrl+C to stop both servers
""")

    def shutdown(sig, frame):
        print(f"\n{YELLOW}Shutting down...{RESET}")
        backend_proc.terminate()
        frontend_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    backend_proc.wait()
    frontend_proc.wait()

if __name__ == "__main__":
    main()