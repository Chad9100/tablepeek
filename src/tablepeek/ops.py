"""Row operations (sort) and per-column summaries (schema, stats)."""

from __future__ import annotations

from collections import Counter

from tablepeek.infer import convert, is_null
from tablepeek.table import Table, TableError


def parse_sort_spec(table: Table, spec: str, descending: bool = False) -> list[tuple[int, bool]]:
    """Parse ``city,age:desc`` into ``[(index, descending), ...]``.

    ``--desc`` flips every key's direction.
    """
    keys: list[tuple[int, bool]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, direction = part.rpartition(":")
        if not name or direction.lower() not in ("asc", "desc"):
            name, direction = part, "asc"
        desc = direction.lower() == "desc"
        keys.append((table.resolve(name), desc != descending))
    if not keys:
        raise TableError("empty sort key")
    return keys


def _sort_value(cell: str, kind: str):
    try:
        value = convert(cell, kind)
    except ValueError:  # cannot happen for inferred kinds, but be safe
        value = cell
    if isinstance(value, str):
        return (value.casefold(), value)
    return value


def sort_rows(table: Table, rows: list[list[str]], keys: list[tuple[int, bool]]) -> list[list[str]]:
    """Stable multi-key sort by typed values; nulls always go last."""
    result = list(rows)
    for idx, desc in reversed(keys):
        kind = table.kinds[idx]
        present = [r for r in result if not is_null(r[idx])]
        nulls = [r for r in result if is_null(r[idx])]
        present.sort(key=lambda r: _sort_value(r[idx], kind), reverse=desc)
        result = present + nulls
    return result


def _example(values: list[str]) -> str:
    for v in values:
        if not is_null(v):
            return v.strip()
    return ""


def schema(table: Table) -> list[dict]:
    """One record per column: name, type, nulls, non-null count, example."""
    out = []
    for i, name in enumerate(table.columns):
        values = [row[i] for row in table.rows]
        nulls = sum(1 for v in values if is_null(v))
        out.append(
            {
                "column": name,
                "type": table.kinds[i],
                "non_null": len(values) - nulls,
                "nulls": nulls,
                "example": _example(values),
            }
        )
    return out


def stats(
    table: Table,
    rows: list[list[str]],
    indices: list[int] | None = None,
    top: int = 0,
) -> list[dict]:
    """Per-column count, nulls, distinct, min, max and (numeric) mean.

    With ``top`` > 0 each record also gets a ``top`` list of the most
    frequent ``{"value", "count"}`` pairs (ties keep first-seen order).
    """
    if indices is None:
        indices = list(range(len(table.columns)))
    out = []
    for i in indices:
        kind = table.kinds[i]
        values = []
        nulls = 0
        for row in rows:
            cell = row[i]
            if is_null(cell):
                nulls += 1
                continue
            values.append(convert(cell, kind))
        counts = Counter(_distinct_key(v) for v in values)
        record: dict = {
            "column": table.columns[i],
            "type": kind,
            "count": len(values),
            "nulls": nulls,
            "distinct": len(counts),
            "min": None,
            "max": None,
            "mean": None,
        }
        if top > 0:
            record["top"] = [
                {"value": v, "count": n} for v, n in counts.most_common(top)
            ]
        if values:
            keyed = [_sort_value(v, "text") if isinstance(v, str) else v for v in values]
            lo = min(range(len(values)), key=keyed.__getitem__)
            hi = max(range(len(values)), key=keyed.__getitem__)
            record["min"], record["max"] = values[lo], values[hi]
            if kind in ("int", "float"):
                record["mean"] = sum(values) / len(values)
        out.append(record)
    return out


def _distinct_key(value):
    if isinstance(value, str):
        return value.strip()
    return value
