# utils/resources.py
import sys
from pathlib import Path

def resource_path(relative: str) -> str:
    """Devuelve la ruta a un recurso, compatible con PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return str(Path(sys._MEIPASS) / relative)
    return str(Path(relative))