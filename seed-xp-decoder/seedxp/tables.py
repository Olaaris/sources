"""The XP-table model shared by the scanner, the curve fitter and the exporters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class XpTable:
    """An experience curve for one skill.

    `points` is a list of `(level, xp)` pairs.  `cumulative` records whether the
    XP figures are totals from level 1 or per-level increments; the scanner
    infers it and `normalized()` converts between the two.
    """

    skill: str
    points: list[tuple[int, float]]
    source: str = ""
    pointer: str = ""
    cumulative: bool = True
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.points = sorted(self.points, key=lambda p: p[0])

    @property
    def levels(self) -> list[int]:
        return [level for level, _ in self.points]

    @property
    def values(self) -> list[float]:
        return [value for _, value in self.points]

    @property
    def max_level(self) -> int:
        return self.levels[-1] if self.points else 0

    def deltas(self) -> list[tuple[int, float]]:
        """XP required to go from each level to the next."""
        if not self.cumulative:
            return list(self.points)
        out = []
        for (level, value), (_, next_value) in zip(self.points, self.points[1:]):
            out.append((level, next_value - value))
        return out

    def totals(self) -> list[tuple[int, float]]:
        """Cumulative XP at each level."""
        if self.cumulative:
            return list(self.points)
        running = 0.0
        out = []
        for level, value in self.points:
            out.append((level, running))
            running += value
        return out

    def is_monotonic(self) -> bool:
        return all(b >= a for a, b in zip(self.values, self.values[1:]))

    def as_dict(self) -> dict:
        return {
            "skill": self.skill,
            "source": self.source,
            "pointer": self.pointer,
            "cumulative": self.cumulative,
            "max_level": self.max_level,
            "points": [{"level": lvl, "xp": xp} for lvl, xp in self.points],
            "notes": list(self.notes),
        }


def merge(tables: Iterable[XpTable]) -> list[XpTable]:
    """Collapse duplicate tables for the same skill, keeping the longest one.

    A game install usually carries the same table more than once (a loose JSON
    plus a copy baked into a bundle); keeping the richest copy avoids reporting
    the same curve repeatedly.
    """
    best: dict[str, XpTable] = {}
    for table in tables:
        key = table.skill.strip().lower()
        current = best.get(key)
        if current is None or len(table.points) > len(current.points):
            if current is not None:
                table.notes.append(f"supersedes shorter table from {current.source}")
            best[key] = table
    return sorted(best.values(), key=lambda t: t.skill.lower())
