# run_ui.py - Launches the interactive web dashboard and opens it in your browser.

import sys
from pathlib import Path
import webbrowser

# Add triage directory to sys.path so src imports resolve cleanly
triage_dir = Path(__file__).resolve().parent
if str(triage_dir) not in sys.path:
    sys.path.insert(0, str(triage_dir))

try:
    import uvicorn
except ImportError:
    print("ERROR: uvicorn is not installed in your Python environment.")
    print("Run: pip install uvicorn fastapi")
    sys.exit(1)


def main():
    port = 8000
    host = "127.0.0.1"
    url = f"http://{host}:{port}"
    print("=" * 60)
    print("   Support Ticket Triage — Web Dashboard")
    print(f"   Opening your browser at: {url}")
    print("   Press CTRL+C in this terminal to stop the server.")
    print("=" * 60)

    # Open browser automatically after a short delay
    import threading
    import time

    def open_browser():
        time.sleep(1.2)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=open_browser, daemon=True).start()

    from src.api import app

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
