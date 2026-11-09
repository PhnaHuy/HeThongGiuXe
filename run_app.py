"""Entry point runner for the Parking Management System."""

from __future__ import annotations

import sys
from multiprocessing import freeze_support
from pathlib import Path

# Ensure src/ is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from parking_app.ui.app import main  # noqa: E402

if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
