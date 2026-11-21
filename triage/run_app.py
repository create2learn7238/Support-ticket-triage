# run_app.py - Starts the Web Dashboard on 127.0.0.1:8000 and opens the browser automatically.

import sys
from pathlib import Path
import threading
import time
import webbrowser

# Ensure triage folder is on sys.path
triage_dir = Path(__file__).resolve().parent
if str(triage_dir) not in sys.path:
    sys.path.insert(0, str(triage_dir))

try:
    import uvicorn
except ImportError:
    print("ERROR: uvicorn is not installed in your Python environment.")
    print("Please install requirements-api.txt: pip install -r requirements-api.txt")
    sys.exit(1)


def open_browser(url: str) -> None:
    time.sleep(1.2)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}"

    print("=" * 64)
    print("   Support Ticket Triage — Web Dashboard")
    print(f"   Opening your browser at: {url}")
    print("   Press CTRL+C in this terminal to stop the server.")
    print("=" * 64)

    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    from src.api import app

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
