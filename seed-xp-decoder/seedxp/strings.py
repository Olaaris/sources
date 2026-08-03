"""Extract readable strings from binaries, to locate where config data lives.

Before a table can be decoded it has to be found.  Unity `.assets` files and
.NET assemblies are opaque, but the names around the data — field names, skill
identifiers, asset paths — survive as plain strings, and they say which file is
worth a closer look.

.NET keeps its string literals in UTF-16, Unity's serialized files use UTF-8,
so both encodings are scanned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .scan import has_level_hint, has_skill_hint, has_xp_hint

_ASCII_RUN = rb"[\x20-\x7e]{%d,}"

# The lookbehind matters: without it, an ASCII run sitting immediately before a
# UTF-16 one lends its last character to the match (`...Table` + `levelCurve`
# reads as `elevelCurve`), and the borrowed letter breaks token matching. A
# UTF-16 string preceded by a printable byte still loses its first character —
# unavoidable without knowing the container's own framing.
_UTF16_RUN = rb"(?<![\x20-\x7e])(?:[\x20-\x7e]\x00){%d,}"


@dataclass(frozen=True)
class Found:
    """One readable string recovered from a binary."""

    offset: int
    encoding: str
    text: str


def iter_strings(data: bytes, min_length: int = 6) -> Iterator[Found]:
    """Yield printable runs from `data`, in UTF-8 and UTF-16LE."""
    for match in re.finditer(_ASCII_RUN % min_length, data):
        yield Found(match.start(), "ascii", match.group().decode("ascii"))

    for match in re.finditer(_UTF16_RUN % min_length, data):
        text = match.group().decode("utf-16-le", errors="replace")
        yield Found(match.start(), "utf-16", text)


def looks_relevant(text: str) -> bool:
    """True when a string mentions skills, levels or experience."""
    return has_xp_hint(text) or has_skill_hint(text) or has_level_hint(text)


def search(
    path: Path,
    pattern: str | None = None,
    min_length: int = 6,
    max_bytes: int = 512 * 1024 * 1024,
) -> list[Found]:
    """Return the strings in `path` that match `pattern`, or that look relevant.

    With no pattern, the skill/level/xp hints used by the scanner apply, which
    is usually the right first pass on an unknown file.
    """
    try:
        if path.stat().st_size > max_bytes:
            return []
        data = path.read_bytes()
    except OSError:
        return []

    matches = re.compile(pattern, re.IGNORECASE) if pattern else None
    keep = (lambda text: bool(matches.search(text))) if matches else looks_relevant

    seen: set[str] = set()
    results = []
    for found in iter_strings(data, min_length):
        if not keep(found.text) or found.text in seen:
            continue
        seen.add(found.text)
        results.append(found)
    return results


def search_tree(
    root: Path, pattern: str | None = None, min_length: int = 6
) -> dict[str, list[Found]]:
    """Run `search` over every file under `root`, keeping only files that hit."""
    hits: dict[str, list[Found]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        found = search(path, pattern, min_length)
        if found:
            hits[str(path)] = found
    return hits
