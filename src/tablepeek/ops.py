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


def histogram(values: list[float], bins: int) -> list[dict]:
    """Equal-width bins over min..max; the last bin includes the maximum."""
    lo, hi = min(values), max(values)
    if lo == hi:
        return [{"from": lo, "to": hi, "count": len(values)}]
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        counts[min(int((v - lo) / width), bins - 1)] += 1
    return [
        {"from": lo + i * width, "to": hi if i == bins - 1 else lo + (i + 1) * width, "count": n}
        for i, n in enumerate(counts)
    ]


def stats(
    table: Table,
    rows: list[list[str]],
    indices: list[int] | None = None,
    top: int = 0,
    bins: int = 0,
) -> list[dict]:
    """Per-column count, nulls, distinct, min, max and (numeric) mean.

    With ``top`` > 0 each record also gets a ``top`` list of the most
    frequent ``{"value", "count"}`` pairs (ties keep first-seen order).
    With ``bins`` > 0 numeric columns also get a ``hist`` list of
    ``{"from", "to", "count"}`` equal-width bins.
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
                if bins > 0:
                    record["hist"] = histogram(values, bins)
        out.append(record)
    return out


AGG_FUNCS = ("count", "sum", "mean", "min", "max", "distinct")


def parse_agg_spec(table: Table, spec: str) -> list[tuple[str, int | None]]:
    """Parse ``count,mean:score,max:age`` into ``[(func, column index), ...]``.

    ``count`` takes no column (it counts rows); every other function needs one.
    ``sum`` and ``mean`` need a numeric column.
    """
    aggs: list[tuple[str, int | None]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        func, _, col = part.partition(":")
        func = func.strip().lower()
        if func not in AGG_FUNCS:
            raise TableError(f"unknown aggregate {func!r} (use {', '.join(AGG_FUNCS)})")
        if func == "count" and not col.strip():
            aggs.append((func, None))
            continue
        if not col.strip():
            raise TableError(f"aggregate {func!r} needs a column, e.g. {func}:age")
        idx = table.resolve(col.strip())
        if func in ("sum", "mean") and table.kinds[idx] not in ("int", "float"):
            raise TableError(
                f"{func} needs a numeric column; {table.columns[idx]!r} is {table.kinds[idx]}"
            )
        aggs.append((func, idx))
    if not aggs:
        raise TableError("empty aggregate list")
    return aggs


def agg_name(table: Table, func: str, idx: int | None) -> str:
    return func if idx is None else f"{func}_{table.columns[idx]}"


def group_by(
    table: Table,
    rows: list[list[str]],
    key_indices: list[int],
    aggs: list[tuple[str, int | None]],
) -> list[dict]:
    """Group rows by the key columns and aggregate; groups keep first-seen order.

    Null cells are skipped by every aggregate except a bare ``count``, which
    counts rows. A null key forms its own group (shown as an empty cell).
    """
    groups: dict[tuple, list[list[str]]] = {}
    for row in rows:
        key = tuple("" if is_null(row[i]) else row[i].strip() for i in key_indices)
        groups.setdefault(key, []).append(row)
    names = [agg_name(table, f, i) for f, i in aggs]
    out = []
    for key, members in groups.items():
        rec: dict = {}
        for i, cell in zip(key_indices, key):
            value = convert(cell, table.kinds[i]) if cell else None
            rec[table.columns[i]] = value
        for name, (func, idx) in zip(names, aggs):
            if idx is None:
                rec[name] = len(members)
                continue
            vals = [convert(r[idx], table.kinds[idx]) for r in members if not is_null(r[idx])]
            if func == "count":
                rec[name] = len(vals)
            elif func == "distinct":
                rec[name] = len({_distinct_key(v) for v in vals})
            elif not vals:
                rec[name] = None
            elif func == "sum":
                rec[name] = sum(vals)
            elif func == "mean":
                rec[name] = sum(vals) / len(vals)
            else:
                keyed = [_sort_value(v, "text") if isinstance(v, str) else v for v in vals]
                pick = min if func == "min" else max
                rec[name] = vals[pick(range(len(vals)), key=keyed.__getitem__)]
        out.append(rec)
    return out


def _distinct_key(value):
    if isinstance(value, str):
        return value.strip()
    return value
