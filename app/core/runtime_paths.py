"""Runtime resource resolution for source and packaged executions."""

from pathlib import Path
import sys


def application_root() -> Path:
    """Return the project root in source runs or the PyInstaller bundle root."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    """Resolve a packaged resource path without scattering bundle checks."""
    return application_root().joinpath(*parts)

