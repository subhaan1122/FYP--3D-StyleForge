"""
Entry point to start the 3D Avatar Generation server.

Usage:
    python run_server.py
    python run_server.py --port 5001 --host 0.0.0.0
"""

import argparse
import uvicorn
from app.config import settings


def main():
    parser = argparse.ArgumentParser(description="Avatar 3D Generation Server")
    parser.add_argument("--host", default=settings.server.host, help="Host address")
    parser.add_argument("--port", type=int, default=settings.server.port, help="Port number")
    parser.add_argument("--reload", action="store_true", default=settings.server.reload, help="Auto-reload on code changes")
    parser.add_argument("--workers", type=int, default=settings.server.workers, help="Number of workers")
    args = parser.parse_args()

    print(f"""
    ╔══════════════════════════════════════════════╗
    ║       Avatar 3D Generation Service           ║
    ║──────────────────────────────────────────────║
    ║  Server:  http://{args.host}:{args.port}             ║
    ║  Docs:    http://{args.host}:{args.port}/docs        ║
    ║  Health:  http://{args.host}:{args.port}/health      ║
    ╚══════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        log_level="info",
    )


if __name__ == "__main__":
    main()
