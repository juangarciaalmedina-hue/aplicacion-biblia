import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent

for path in (ROOT, ROOT / "vendor_py"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _load_local_package(name: str, init_path: Path):
    spec = importlib.util.spec_from_file_location(
        name,
        init_path,
        submodule_search_locations=[str(init_path.parent)],
    )
    if not spec or not spec.loader:
        raise ModuleNotFoundError(name)

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


try:
    import flet as ft
except ModuleNotFoundError as exc:
    if exc.name != "flet":
        raise

    ft = None
    for candidate in (ROOT / "flet" / "__init__.py", ROOT / "vendor_py" / "flet" / "__init__.py"):
        if candidate.exists():
            ft = _load_local_package("flet", candidate)
            break

    if ft is None:
        raise

from biblia_app.main import main as app_main


if __name__ == "__main__":
    ft.run(app_main)
