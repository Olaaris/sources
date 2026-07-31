"""Walk an install tree and classify every file in it."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator

from . import magic

# Skipped wholesale: large, never data-bearing, and slow to hash.
_SKIP_SUFFIXES = {".dll", ".so", ".dylib", ".exe", ".pdb", ".mp4", ".bnk", ".wem"}


@dataclass(frozen=True)
class Entry:
    """One classified file."""

    path: str
    size: int
    kind: str
    sha256: str

    def as_dict(self) -> dict:
        return asdict(self)


def walk(root: Path, hash_limit: int = 64 * 1024 * 1024) -> Iterator[Entry]:
    """Yield a classified `Entry` for every file under `root`.

    Files larger than `hash_limit` are classified but not hashed, so that a
    full-install inventory stays fast.
    """
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        yield Entry(
            path=str(path.relative_to(root)),
            size=size,
            kind=magic.sniff_file(path),
            sha256=_sha256(path) if size <= hash_limit else "",
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def summarize(entries: list[Entry]) -> dict[str, dict[str, int]]:
    """Aggregate an inventory by file kind."""
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    for entry in entries:
        counts[entry.kind] += 1
        sizes[entry.kind] += entry.size
    return {
        kind: {"files": counts[kind], "bytes": sizes[kind]}
        for kind in sorted(counts, key=lambda k: -counts[k])
    }
