"""File-type detection by content, for classifying an unknown game install."""

from __future__ import annotations

import json
from pathlib import Path

# (kind, magic bytes at offset 0)
_SIGNATURES: list[tuple[str, bytes]] = [
    ("unityfs", b"UnityFS\x00"),
    ("unityweb", b"UnityWeb\x00"),
    ("unityraw", b"UnityRaw\x00"),
    ("unity-archive", b"UnityArchive\x00"),
    ("sqlite", b"SQLite format 3\x00"),
    ("zip", b"PK\x03\x04"),
    ("gzip", b"\x1f\x8b"),
    ("lzma", b"\xfd7zXZ\x00"),
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("elf", b"\x7fELF"),
    ("pe", b"MZ"),
    ("macho", b"\xcf\xfa\xed\xfe"),
    ("macho-fat", b"\xca\xfe\xba\xbe"),
]

# Extensions worth reading as text even when the content sniff is inconclusive.
TEXTUAL_SUFFIXES = {
    ".json",
    ".txt",
    ".csv",
    ".tsv",
    ".xml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".toml",
    ".lua",
    ".js",
}


def sniff(data: bytes, name: str = "") -> str:
    """Classify a byte prefix into a coarse kind label."""
    for kind, magic in _SIGNATURES:
        if data.startswith(magic):
            return kind

    stripped = data.lstrip()
    if stripped[:1] in (b"{", b"["):
        return "json"

    suffix = Path(name).suffix.lower()
    if suffix in TEXTUAL_SUFFIXES:
        return suffix.lstrip(".")

    if not data:
        return "empty"
    if b"\x00" not in data and _mostly_printable(data):
        return "text"
    return "binary"


def _mostly_printable(data: bytes, threshold: float = 0.9) -> bool:
    printable = sum(1 for b in data if 0x20 <= b < 0x7F or b in (0x09, 0x0A, 0x0D))
    return printable / len(data) >= threshold


def sniff_file(path: Path, probe_bytes: int = 4096) -> str:
    """Classify a file on disk by reading only its first bytes."""
    try:
        with path.open("rb") as handle:
            head = handle.read(probe_bytes)
    except OSError:
        return "unreadable"
    return sniff(head, path.name)


def is_json(data: bytes) -> bool:
    try:
        json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    return True
