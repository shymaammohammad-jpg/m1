"""Start Raqib from an extracted checkout on Windows or Linux."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def fail(message: str) -> int:
    print(f"Raqib: {message}", file=sys.stderr)
    return 2


def open_when_ready(address: str, stop: threading.Event) -> None:
    # A local readiness request must never be sent through an Internet proxy.
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 45
    while not stop.wait(0.3):
        try:
            with client.open(f"{address}/api/health", timeout=1) as response:
                if json.load(response).get("status") == "ok":
                    webbrowser.open(address)
                    return
        except (OSError, ValueError):
            pass
        if time.monotonic() > deadline:
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the Raqib audit application.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    parser.add_argument("--check", action="store_true", help="Check installation without starting the service.")
    parser.add_argument("--port", type=int, default=None, help="Local port (default AUDIT_PORT or 8000).")
    arguments = parser.parse_args(argv)
    required = ["backend/app.py", "frontend/package.json", "reference_structure.json", "reference_circulars.json"]
    if not all((ROOT / name).is_file() for name in required):
        return fail("Extract the ENTIRE ZIP to a normal folder first, then open start_windows.bat in that folder.")

    # An Explorer .py association may use the global Python even after setup.
    local_python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if local_python.is_file() and Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        try:
            return subprocess.call([str(local_python), str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])], cwd=ROOT)
        except OSError as error:
            return fail(f"The local Python environment could not start: {error}. Run the installer again.")
        except KeyboardInterrupt:
            return 130
    if sys.version_info < (3, 12):
        return fail("Python 3.12 or newer is required. Install Python 3.12 and run install_windows.bat.")
    missing = [name for name in ("fastapi", "uvicorn", "multipart", "pypdf", "docx", "PIL", "playwright", "tzdata") if importlib.util.find_spec(name) is None]
    if missing:
        return fail("Missing Python packages: " + ", ".join(missing) + ". Run install_windows.bat (Windows) or bash scripts/install.sh (Linux) first.")
    if not (ROOT / "frontend/dist/index.html").is_file():
        return fail("The web interface has not been built. Run install_windows.bat (Windows) or bash scripts/install.sh (Linux) first.")
    if arguments.check:
        print("Raqib installation check passed. Start with start_windows.bat or python run.py.")
        return 0
    try:
        port = arguments.port if arguments.port is not None else int(os.environ.get("AUDIT_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        return fail("The port must be an integer between 1 and 65535.")
    host = "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            occupied = probe.connect_ex((host, port)) == 0
    except OSError:
        occupied = True
    if occupied:
        return fail(f"Port {port} is already in use. Close the other instance, or use python run.py --port {port + 1 if port < 65535 else 8000}.")
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.environ.setdefault("AUDIT_TESSDATA_DIR", str(ROOT / "data/tessdata"))
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    os.environ.setdefault("AUDIT_OCR_ON_UPLOAD", "0")
    address = f"http://{host}:{port}"
    print(f"Raqib is starting at {address}. Keep this window open; press Ctrl+C to stop.")
    stop = threading.Event()
    if not arguments.no_browser:
        threading.Thread(target=open_when_ready, args=(address, stop), daemon=True).start()
    try:
        import uvicorn
        uvicorn.run("backend.app:app", host=host, port=port)
    except KeyboardInterrupt:
        return 130
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
