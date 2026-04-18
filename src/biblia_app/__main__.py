import os

import flet as ft

from .main import main


if __name__ == "__main__":
    os.environ.setdefault("FLET_PLATFORM", "android")
    ft.app(target=main)
