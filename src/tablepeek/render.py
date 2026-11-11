"""Output formats: aligned table, CSV, Markdown, JSON and JSON Lines."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from tablepeek.infer import convert

FORMATS = ("table", "csv", "md", "json", "jsonl")
NUMERIC = ("int", "float")


def format_value(value) -> str:
    """Human-friendly text for a Python value from a summary."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".") if abs(value) >= 1e-4 else f"{value:.4g}"
    if isinstance(value, datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return value.strftime("%Y-%m-%d")
        return value.isoformat(sep=" ")
    return str(value)


def json_value(value):
    if isinstance(value, datetime):
        return format_value(value)
    if isinstance(value, float):
        return round(value, 6)
    return value


def _clip(text: str, width: int) -> str:
    text = text.replace("\r\n", "\n").replace("\n", "\\n").replace("\t", " ")
    if width > 3 and len(text) > width:
        return text[: width - 3] + "..."
    return text


def render_table(
    columns: list[str],
    rows: list[list[str]],
    right: list[bool] | None = None,
    max_width: int = 40,
) -> str:
    """Render rows as an aligned plain-text table with a header rule."""
    right = right or [False] * len(columns)
    head = [_clip(c, max_width) for c in columns]
    body = [[_clip(cell, max_width) for cell in row] for row in rows]
    widths = [len(h) for h in head]
    for row in body:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(cells: list[str]) -> str:
        parts = [
            cell.rjust(widths[i]) if right[i] else cell.ljust(widths[i])
            for i, cell in enumerate(cells)
        ]
        return "  ".join(parts).rstrip()

    out = [line(head), "  ".join("-" * w for w in widths)]
    out.extend(line(row) for row in body)
    return "\n".join(out) + "\n"


def _md_cell(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\n", "<br>").replace("\t", " ")
    return text.replace("\\", "\\\\").replace("|", "\\|")


def render_markdown(
    columns: list[str], rows: list[list[str]], right: list[bool] | None = None
) -> str:
    """Render rows as a GitHub-flavoured Markdown table (numbers right-aligned)."""
    right = right or [False] * len(columns)
    head = "| " + " | ".join(_md_cell(c) for c in columns) + " |"
    rule = "| " + " | ".join("---:" if r else "---" for r in right) + " |"
    out = [head, rule]
    for row in rows:
        out.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
    return "\n".join(out) + "\n"


def render_csv(
    columns: list[str], rows: list[list[str]], delimiter: str = ",", header: bool = True
) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    if header:
        writer.writerow(columns)
    writer.writerows(rows)
    return buf.getvalue()


def typed_records(columns: list[str], rows: list[list[str]], kinds: list[str]) -> list[dict]:
    """Rows as dicts with JSON-friendly typed values (dates stay strings)."""
    records = []
    for row in rows:
        rec = {}
        for name, cell, kind in zip(columns, row, kinds):
            value = convert(cell, kind if kind != "date" else "text")
            if kind == "date" and value is not None:
                value = value.strip()
            rec[name] = value
        records.append(rec)
    return records


def render_rows(
    fmt: str,
    columns: list[str],
    rows: list[list[str]],
    kinds: list[str],
    max_width: int = 40,
    delimiter: str = ",",
) -> str:
    """Render table rows in any of FORMATS."""
    if fmt == "table":
        return render_table(columns, rows, [k in NUMERIC for k in kinds], max_width)
    if fmt == "csv":
        return render_csv(columns, rows, delimiter)
    if fmt == "md":
        return render_markdown(columns, rows, [k in NUMERIC for k in kinds])
    records = typed_records(columns, rows, kinds)
    return render_records_json(fmt, records)


def render_records_json(fmt: str, records: list[dict]) -> str:
    records = [{k: json_value(v) for k, v in r.items()} for r in records]
    if fmt == "jsonl":
        return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    return json.dumps(records, indent=2, ensure_ascii=False) + "\n"


def render_summary(
    fmt: str,
    records: list[dict],
    right_cols: tuple[str, ...] = (),
    max_width: int = 40,
    delimiter: str = ",",
) -> str:
    """Render summary records (schema, stats) in any of FORMATS."""
    if fmt in ("json", "jsonl"):
        return render_records_json(fmt, records)
    columns = list(records[0].keys()) if records else []
    rows = [[format_value(r[c]) for c in columns] for r in records]
    if fmt == "csv":
        return render_csv(columns, rows, delimiter)
    if fmt == "md":
        return render_markdown(columns, rows, [c in right_cols for c in columns])
    return render_table(columns, rows, [c in right_cols for c in columns], max_width)
