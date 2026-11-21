# run_app.py - Root launcher for Support Ticket Triage Web Dashboard.

import os
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent
triage_dir = root_dir / "triage"
os.chdir(str(triage_dir))
if str(triage_dir) not in sys.path:
    sys.path.insert(0, str(triage_dir))

from run_app import main

if __name__ == "__main__":
    main()
