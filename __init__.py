VERSION = "2.0.0"
__version__ = VERSION

import importlib
import pkgutil
from pathlib import Path

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

def _merge(mod):
    for k, v in getattr(mod, "NODE_CLASS_MAPPINGS", {}).items():
        if k in NODE_CLASS_MAPPINGS and NODE_CLASS_MAPPINGS[k] is not v:
            print(f"[PG-nodes] WARNING: duplicate node key '{k}' — keeping last one")
        NODE_CLASS_MAPPINGS[k] = v
    for k, v in getattr(mod, "NODE_DISPLAY_NAME_MAPPINGS", {}).items():
        NODE_DISPLAY_NAME_MAPPINGS[k] = v

pkg_name = __name__
pkg_path = Path(__file__).parent

for info in pkgutil.iter_modules([str(pkg_path)]):
    name = info.name
    if name == "__init__" or name.startswith("_"):
        continue
    mod = importlib.import_module(f"{pkg_name}.{name}")
    if hasattr(mod, "NODE_CLASS_MAPPINGS"):
        _merge(mod)

WEB_DIRECTORY = "web"
