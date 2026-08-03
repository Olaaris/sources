"""Find skill/XP tables inside game data files.

The scanner makes no assumption about SEED's exact schema, because that schema
is only knowable from a real install.  Instead it recognises the *shapes* XP
data takes across shipped games:

  1. a named series of non-decreasing numbers   {"Farming": [0, 83, 174, ...]}
  2. rows carrying a level field and an xp field  [{"skill": ..., "level": 1, "xp": 0}, ...]
  3. a SQLite table with level-ish and xp-ish columns
  4. the same, as CSV

Everything it returns is a *candidate*: `decode` then validates the shape and
the curve fit before anything is reported as an XP table.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from . import magic, unityfs
from .tables import XpTable

# Field names in game data are overwhelmingly camelCase or snake_case
# (`xpRequired`, `total_exp`, `skillName`), so hints are matched against split
# tokens rather than by substring: `\bxp\b` never matches inside `xpRequired`.
_TOKEN_SPLIT = re.compile(
    r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)

XP_TOKENS = {"xp", "xps", "exp", "exps", "experience", "experiences"}
LEVEL_TOKENS = {
    "level", "levels", "lvl", "lvls", "rank", "ranks",
    "tier", "tiers", "grade", "grades", "stage", "stages",
}
SKILL_TOKENS = {
    "skill", "skills", "ability", "abilities", "profession", "professions",
    "craft", "crafts", "talent", "talents", "proficiency", "proficiencies",
    "competence", "competences", "discipline", "disciplines", "trade", "trades",
}

MIN_SERIES_LENGTH = 5


def tokenize(text: str) -> list[str]:
    """Split an identifier or JSON pointer into lowercase word tokens."""
    return [token.lower() for token in _TOKEN_SPLIT.split(text) if token]


def has_xp_hint(text: str) -> bool:
    return any(t in XP_TOKENS or t.startswith("experien") for t in tokenize(text))


def has_level_hint(text: str) -> bool:
    return any(t in LEVEL_TOKENS for t in tokenize(text))


def has_skill_hint(text: str) -> bool:
    return any(t in SKILL_TOKENS for t in tokenize(text))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_series(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < MIN_SERIES_LENGTH:
        return None
    if not all(_is_number(item) for item in value):
        return None
    return [float(item) for item in value]


def _non_decreasing(values: list[float]) -> bool:
    return all(b >= a for a, b in zip(values, values[1:]))


def _leaf_name(pointer: str) -> str:
    parts = [p for p in pointer.split("/") if p and not p.isdigit()]
    return parts[-1] if parts else "unknown"


def _find_key(row: dict, wanted, excluded=None) -> str | None:
    """First key matching `wanted` and not matching `excluded`.

    The exclusion keeps an ambiguous name like `experienceLevel` from being
    claimed as both the level column and the xp column.
    """
    for key in row:
        if not isinstance(key, str) or not wanted(key):
            continue
        if excluded is not None and excluded(key):
            continue
        return key
    return None


def walk_json(node: Any, pointer: str = "") -> Iterator[tuple[str, Any]]:
    """Yield every `(json-pointer, value)` pair in a decoded JSON document."""
    yield pointer or "/", node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk_json(value, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_json(value, f"{pointer}/{index}")


def candidates_from_json(document: Any, source: str) -> list[XpTable]:
    """Extract candidate XP tables from a decoded JSON document."""
    found: list[XpTable] = []

    for pointer, node in walk_json(document):
        series = _numeric_series(node)
        if series is not None and _non_decreasing(series):
            name = _leaf_name(pointer)
            # A bare series is only interesting when something on its path says
            # XP, otherwise every stat array in the file would match.
            if has_xp_hint(pointer) or has_skill_hint(pointer) or has_level_hint(pointer):
                found.append(
                    XpTable(
                        skill=name,
                        points=[(i + 1, v) for i, v in enumerate(series)],
                        source=source,
                        pointer=pointer,
                        cumulative=_looks_cumulative(series),
                        notes=["shape: named numeric series"],
                    )
                )
            continue

        found.extend(_candidates_from_rows(node, pointer, source))

    return found


def _candidates_from_rows(node: Any, pointer: str, source: str) -> list[XpTable]:
    """Recognise a list of row-dicts carrying level and xp fields."""
    if not isinstance(node, list) or len(node) < MIN_SERIES_LENGTH:
        return []
    rows = [row for row in node if isinstance(row, dict)]
    if len(rows) != len(node):
        return []

    sample = rows[0]
    level_key = _find_key(sample, has_level_hint, has_xp_hint)
    xp_key = _find_key(sample, has_xp_hint, has_level_hint)
    if not level_key or not xp_key or level_key == xp_key:
        return []

    skill_key = _find_key(sample, has_skill_hint, has_xp_hint)
    grouped: dict[str, list[tuple[int, float]]] = {}
    for row in rows:
        if not _is_number(row.get(level_key)) or not _is_number(row.get(xp_key)):
            return []
        skill = str(row.get(skill_key)) if skill_key else _leaf_name(pointer)
        grouped.setdefault(skill, []).append(
            (int(row[level_key]), float(row[xp_key]))
        )

    return [
        XpTable(
            skill=skill,
            points=points,
            source=source,
            pointer=pointer,
            cumulative=_looks_cumulative([v for _, v in sorted(points)]),
            notes=[f"shape: rows keyed on {level_key!r}/{xp_key!r}"],
        )
        for skill, points in grouped.items()
        if len(points) >= MIN_SERIES_LENGTH
    ]


def _looks_cumulative(values: list[float]) -> bool:
    """Decide whether a series holds running totals or per-level costs.

    Both shapes usually increase, so monotonicity says nothing.  What separates
    them is the first entry: a total-XP curve starts at 0 (level 1 costs
    nothing to have reached), a per-level cost table starts at a real price.
    """
    return not values or values[0] == 0


def candidates_from_sqlite(path: Path) -> list[XpTable]:
    found: list[XpTable] = []
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return found

    try:
        cursor = connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        for (table_name,) in cursor.fetchall():
            try:
                cursor.execute(f'PRAGMA table_info("{table_name}")')
                columns = [row[1] for row in cursor.fetchall()]
            except sqlite3.Error:
                continue

            level_col = next(
                (c for c in columns if has_level_hint(c) and not has_xp_hint(c)), None
            )
            xp_col = next(
                (c for c in columns if has_xp_hint(c) and not has_level_hint(c)), None
            )
            if not level_col or not xp_col:
                continue
            skill_col = next((c for c in columns if has_skill_hint(c)), None)

            selected = [level_col, xp_col] + ([skill_col] if skill_col else [])
            quoted = ", ".join(f'"{c}"' for c in selected)
            try:
                cursor.execute(f'SELECT {quoted} FROM "{table_name}"')
                rows = cursor.fetchall()
            except sqlite3.Error:
                continue

            grouped: dict[str, list[tuple[int, float]]] = {}
            for row in rows:
                try:
                    level, xp = int(row[0]), float(row[1])
                except (TypeError, ValueError):
                    continue
                skill = str(row[2]) if skill_col else table_name
                grouped.setdefault(skill, []).append((level, xp))

            for skill, points in grouped.items():
                if len(points) >= MIN_SERIES_LENGTH:
                    found.append(
                        XpTable(
                            skill=skill,
                            points=points,
                            source=str(path),
                            pointer=f"table:{table_name}",
                            cumulative=_looks_cumulative(
                                [v for _, v in sorted(points)]
                            ),
                            notes=[f"shape: sqlite {table_name}.{level_col}/{xp_col}"],
                        )
                    )
    finally:
        connection.close()
    return found


def candidates_from_csv(data: bytes, source: str) -> list[XpTable]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return []
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if len(rows) < MIN_SERIES_LENGTH:
        return []
    typed: list[dict] = []
    for row in rows:
        converted: dict[str, Any] = {}
        for key, value in row.items():
            if key is None:
                continue
            try:
                converted[key] = float(value) if value not in (None, "") else value
            except (TypeError, ValueError):
                converted[key] = value
        typed.append(converted)
    return _candidates_from_rows(typed, "/csv", source)


def scan_file(path: Path) -> list[XpTable]:
    """Scan one file for XP-table candidates, unpacking bundles as needed."""
    kind = magic.sniff_file(path)

    if kind == "sqlite":
        return candidates_from_sqlite(path)

    if kind in ("unityfs", "unityweb", "unityraw"):
        return _scan_bundle(path)

    try:
        data = path.read_bytes()
    except OSError:
        return []

    if kind == "json" or path.suffix.lower() == ".json":
        try:
            document = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return _scan_embedded_json(data, str(path))
        return candidates_from_json(document, str(path))

    if kind in ("csv", "tsv"):
        return candidates_from_csv(data, str(path))

    if kind == "text":
        return _scan_embedded_json(data, str(path))

    # Unity serialized files (`.assets`, `globalgamemanagers`) and .NET
    # assemblies are opaque binaries, but the config tables inside them are
    # still stored as readable strings, so carve JSON straight out of them.
    return _scan_binary(data, str(path))


def _scan_binary(data: bytes, source: str) -> list[XpTable]:
    """Carve JSON out of a binary, trying both UTF-8 and UTF-16LE.

    .NET assemblies keep their string literals in UTF-16, so a byte-level
    search for `{` finds nothing without the second pass.
    """
    found = _scan_embedded_json(data, source)

    try:
        widened = data.decode("utf-16-le", errors="ignore").encode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return found
    for table in _scan_embedded_json(widened, f"{source}#utf16"):
        table.notes.append("recovered from UTF-16 string data")
        found.append(table)
    return found


def _scan_bundle(path: Path) -> list[XpTable]:
    """Decompress a Unity bundle in memory and scan its payload."""
    try:
        _info, payload = unityfs.read_bundle(path)
    except (unityfs.UnityFSError, OSError, ValueError):
        return []
    return _scan_embedded_json(payload, f"{path}!bundle")


_JSON_START = re.compile(rb"[\{\[]")


def _scan_embedded_json(data: bytes, source: str) -> list[XpTable]:
    """Recover JSON documents embedded in a larger binary payload.

    Unity `TextAsset`s sit inside a serialized file surrounded by binary
    metadata, so the JSON has to be carved out by balancing brackets.
    """
    found: list[XpTable] = []
    for match in _JSON_START.finditer(data):
        blob = _balanced_slice(data, match.start())
        if blob is None or len(blob) < 32:
            continue
        try:
            document = json.loads(blob.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        found.extend(
            candidates_from_json(document, f"{source}@{match.start()}")
        )
    return found


def _balanced_slice(data: bytes, start: int, limit: int = 4 * 1024 * 1024) -> bytes | None:
    """Return the bracket-balanced slice beginning at `start`, if any."""
    opening = data[start : start + 1]
    closing = b"}" if opening == b"{" else b"]"
    depth = 0
    in_string = False
    escaped = False

    for index in range(start, min(len(data), start + limit)):
        byte = data[index : index + 1]
        if in_string:
            if escaped:
                escaped = False
            elif byte == b"\\":
                escaped = True
            elif byte == b'"':
                in_string = False
            continue
        if byte == b'"':
            in_string = True
        elif byte == opening:
            depth += 1
        elif byte == closing:
            depth -= 1
            if depth == 0:
                return data[start : index + 1]
    return None


def scan_tree(root: Path, max_bytes: int = 256 * 1024 * 1024) -> list[XpTable]:
    """Scan every file under `root`, skipping files larger than `max_bytes`."""
    found: list[XpTable] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size > max_bytes:
                continue
        except OSError:
            continue
        found.extend(scan_file(path))
    return found
