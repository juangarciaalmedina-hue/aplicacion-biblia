from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
VENDOR_DIR = ROOT / "vendor_py"

if str(VENDOR_DIR) not in sys.path:
    sys.path.append(str(VENDOR_DIR))

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import flet as ft

from biblia_app.main import main as app_main


if __name__ == "__main__":
    ft.app(target=app_main)
