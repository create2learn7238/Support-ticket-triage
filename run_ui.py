# run_ui.py - Root launcher that delegates to triage/run_ui.py.

import os
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent
triage_dir = root_dir / "triage"
os.chdir(str(triage_dir))
sys.path.insert(0, str(triage_dir))

from run_ui import main

if __name__ == "__main__":
    main()
