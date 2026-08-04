"""Rebuild a full XP table from SEED's banded progression config.

SEED does not ship a per-level table: `SkillProgressionConfig` holds a list of
`SkillTier`, each covering `StartLevel`..`EndLevel` at `XPPerLevel` points per
level (see `docs/static-data-schema.md`). A handful of tier values — read off
the in-game skills screen, or recovered from the server payload — expands into
the complete curve.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .tables import XpTable

_SPEC = re.compile(
    r"^\s*(?P<name>[^:]*?)\s*:\s*(?P<start>\d+)\s*-\s*(?P<end>\d+)\s*:\s*(?P<xp>\d+)\s*$"
)


class TierError(ValueError):
    """Raised when a tier specification is malformed or inconsistent."""


@dataclass(frozen=True)
class SkillTier:
    """One band of the progression curve, mirroring the game's own type."""

    name: str
    start_level: int
    end_level: int
    xp_per_level: int

    def covers(self, level: int) -> bool:
        return self.start_level <= level <= self.end_level


def parse_tier(spec: str) -> SkillTier:
    """Parse a `Name:start-end:xpPerLevel` specification."""
    match = _SPEC.match(spec)
    if not match:
        raise TierError(
            f"tier {spec!r} is not of the form 'Name:start-end:xpPerLevel'"
        )
    start = int(match.group("start"))
    end = int(match.group("end"))
    if end < start:
        raise TierError(f"tier {spec!r} ends ({end}) before it starts ({start})")
    return SkillTier(
        name=match.group("name") or f"{start}-{end}",
        start_level=start,
        end_level=end,
        xp_per_level=int(match.group("xp")),
    )


def load_tiers(path: Path) -> list[SkillTier]:
    """Read tiers from JSON shaped like the game's `SkillProgressionConfig`.

    Field names are matched case-insensitively, so a payload copied straight
    from the game's schema (`SkillTiers`, `StartLevel`, `XPPerLevel`) works
    unchanged.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(document, dict):
        for key in document:
            if key.lower() in ("skilltiers", "tiers"):
                document = document[key]
                break
    if not isinstance(document, list):
        raise TierError("expected a list of tiers, or an object holding 'SkillTiers'")

    def field(row: dict, *names: str):
        for key, value in row.items():
            if key.lower() in names:
                return value
        raise TierError(f"tier {row!r} has none of the fields {names}")

    tiers = []
    for row in document:
        if not isinstance(row, dict):
            raise TierError(f"expected a tier object, got {row!r}")
        tiers.append(
            SkillTier(
                name=str(field(row, "name")),
                start_level=int(field(row, "startlevel", "start")),
                end_level=int(field(row, "endlevel", "end")),
                xp_per_level=int(field(row, "xpperlevel", "xp", "experienceperlevel")),
            )
        )
    return tiers


def validate(tiers: list[SkillTier]) -> list[str]:
    """Report gaps and overlaps between tiers, without refusing to continue.

    Values read by hand off a game screen are easy to mistype, and a silent
    gap would quietly corrupt every level above it.
    """
    problems: list[str] = []
    ordered = sorted(tiers, key=lambda t: t.start_level)
    for current, following in zip(ordered, ordered[1:]):
        if following.start_level <= current.end_level:
            problems.append(
                f"paliers '{current.name}' et '{following.name}' se chevauchent "
                f"au niveau {following.start_level}"
            )
        elif following.start_level > current.end_level + 1:
            problems.append(
                f"trou entre '{current.name}' (fin {current.end_level}) et "
                f"'{following.name}' (debut {following.start_level})"
            )
    return problems


def cost_to_next(tiers: list[SkillTier], level: int) -> int | None:
    """XP needed to go from `level` to `level + 1`, or None if uncovered."""
    for tier in tiers:
        if tier.covers(level):
            return tier.xp_per_level
    return None


def build_table(
    tiers: list[SkillTier], skill: str = "Skill", max_level: int | None = None
) -> XpTable:
    """Expand tiers into a cumulative per-level XP table."""
    if not tiers:
        raise TierError("no tiers given")

    ordered = sorted(tiers, key=lambda t: t.start_level)
    first = ordered[0].start_level
    last = max_level or max(t.end_level for t in ordered)

    points: list[tuple[int, float]] = []
    running = 0.0
    for level in range(first, last + 1):
        points.append((level, running))
        step = cost_to_next(ordered, level)
        if step is None:
            break
        running += step

    notes = [
        "reconstruit depuis {} palier(s) SkillTier".format(len(ordered)),
        "; ".join(f"{t.name} {t.start_level}-{t.end_level} @ {t.xp_per_level}/niv"
                  for t in ordered),
    ]
    notes.extend(validate(ordered))

    return XpTable(
        skill=skill,
        points=points,
        source="SkillProgressionConfig",
        pointer="/SkillTiers",
        cumulative=True,
        notes=notes,
    )
