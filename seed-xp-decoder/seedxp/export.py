"""Render decoded XP tables as JSON, CSV or Markdown."""

from __future__ import annotations

import csv
import io
import json
from typing import Sequence

from .curves import Fit
from .tables import XpTable

Decoded = tuple[XpTable, Fit | None]


def to_json(decoded: Sequence[Decoded], indent: int = 2) -> str:
    payload = []
    for table, fit in decoded:
        entry = table.as_dict()
        entry["best_fit"] = fit.as_dict() if fit else None
        payload.append(entry)
    return json.dumps(
        {"tables": payload, "count": len(payload)}, indent=indent, ensure_ascii=False
    )


def to_csv(decoded: Sequence[Decoded]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["skill", "level", "xp_total", "xp_to_next", "source"])
    for table, _fit in decoded:
        deltas = dict(table.deltas())
        for level, total in table.totals():
            writer.writerow(
                [
                    table.skill,
                    level,
                    _format_number(total),
                    _format_number(deltas[level]) if level in deltas else "",
                    table.source,
                ]
            )
    return buffer.getvalue()


def to_markdown(decoded: Sequence[Decoded]) -> str:
    lines: list[str] = ["# Tables d'experience par skill", ""]
    if not decoded:
        lines.append("_Aucune table trouvee._")
        return "\n".join(lines) + "\n"

    lines.append(f"{len(decoded)} skill(s) decode(s).")
    lines.append("")

    for table, fit in decoded:
        lines.append(f"## {table.skill}")
        lines.append("")
        lines.append(f"- Source : `{table.source}`")
        if table.pointer:
            lines.append(f"- Emplacement : `{table.pointer}`")
        lines.append(f"- Niveau max : {table.max_level}")
        if fit:
            status = "exacte" if fit.is_exact else f"R2 = {fit.r_squared:.6f}"
            lines.append(f"- Formule ({fit.model}, {status}) : `{fit.formula}`")
        for note in table.notes:
            lines.append(f"- Note : {note}")
        lines.append("")
        lines.append("| Niveau | XP cumule | XP vers suivant |")
        lines.append("| ---: | ---: | ---: |")
        deltas = dict(table.deltas())
        for level, total in table.totals():
            step = _format_number(deltas[level]) if level in deltas else ""
            lines.append(f"| {level} | {_format_number(total)} | {step} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


FORMATS = {"json": to_json, "csv": to_csv, "markdown": to_markdown, "md": to_markdown}


def render(decoded: Sequence[Decoded], fmt: str) -> str:
    try:
        renderer = FORMATS[fmt.lower()]
    except KeyError:
        raise ValueError(
            f"unknown format {fmt!r}; expected one of {', '.join(sorted(FORMATS))}"
        ) from None
    return renderer(decoded)
