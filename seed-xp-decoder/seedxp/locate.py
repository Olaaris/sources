"""Locate a SEED installation on the local machine.

SEED (Klang Games) installs through its own launcher rather than Steam, so
there is no registry of library folders to consult.  These are the default
paths the launcher uses, plus the usual Proton/Wine prefixes for Linux users.
"""

from __future__ import annotations

import os
from pathlib import Path

# Marker files/directories that identify a Unity game install root.
_ROOT_MARKERS = ("SEED_Data", "Seed_Data", "SEED.app", "Contents/Resources/Data")

_CANDIDATE_TEMPLATES = [
    # Windows
    "{localappdata}/Programs/SEED",
    "{localappdata}/SEED",
    "{programfiles}/SEED",
    "{programfiles}/Klang Games/SEED",
    "{programfilesx86}/Klang Games/SEED",
    # macOS
    "{home}/Applications/SEED.app",
    "/Applications/SEED.app",
    "{home}/Library/Application Support/SEED",
    # Linux via Proton/Wine prefixes
    "{home}/.steam/steam/steamapps/common/SEED",
    "{home}/.local/share/Steam/steamapps/common/SEED",
    "{home}/.wine/drive_c/Program Files/Klang Games/SEED",
    "{home}/Games/SEED",
]


def _expand(template: str) -> Path:
    values = {
        "home": os.path.expanduser("~"),
        "localappdata": os.environ.get(
            "LOCALAPPDATA", os.path.expanduser("~/AppData/Local")
        ),
        "programfiles": os.environ.get("ProgramFiles", "C:/Program Files"),
        "programfilesx86": os.environ.get(
            "ProgramFiles(x86)", "C:/Program Files (x86)"
        ),
    }
    return Path(template.format(**values))


def looks_like_install(root: Path) -> bool:
    """True when `root` has the shape of a Unity game install."""
    if not root.is_dir():
        return False
    for marker in _ROOT_MARKERS:
        if (root / marker).exists():
            return True
    # Fall back to any *_Data directory holding Unity's managed assemblies.
    for child in root.glob("*_Data"):
        if (child / "globalgamemanagers").exists() or (child / "Managed").is_dir():
            return True
    return False


def candidates() -> list[Path]:
    """Every default install path for the current platform, existing or not."""
    return [_expand(template) for template in _CANDIDATE_TEMPLATES]


def find_installs() -> list[Path]:
    """Return the default install paths that actually contain a SEED install."""
    found: list[Path] = []
    for path in candidates():
        if looks_like_install(path) and path not in found:
            found.append(path)
    return found


def data_dirs(root: Path) -> list[Path]:
    """The Unity data directories inside an install root."""
    dirs = [d for d in root.glob("*_Data") if d.is_dir()]
    macos_data = root / "Contents" / "Resources" / "Data"
    if macos_data.is_dir():
        dirs.append(macos_data)
    return dirs
