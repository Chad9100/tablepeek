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
    # One pass over ``rows`` (any iterable) with running accumulators, so the
    # rows never have to be held in memory. Only histograms keep the values.
    accs = [
        {"n": 0, "nulls": 0, "counts": Counter(), "lo": None, "hi": None,
         "lokey": None, "hikey": None, "sum": 0,
         "values": [] if bins > 0 and table.kinds[i] in ("int", "float") else None}
        for i in indices
    ]
    for row in rows:
        for i, acc in zip(indices, accs):
            cell = row[i]
            if is_null(cell):
                acc["nulls"] += 1
                continue
            kind = table.kinds[i]
            v = convert(cell, kind)
            acc["n"] += 1
            acc["counts"][_distinct_key(v)] += 1
            key = _sort_value(v, "text") if isinstance(v, str) else v
            if acc["lokey"] is None or key < acc["lokey"]:
                acc["lo"], acc["lokey"] = v, key
            if acc["hikey"] is None or key > acc["hikey"]:
                acc["hi"], acc["hikey"] = v, key
            if kind in ("int", "float"):
                acc["sum"] += v
                if acc["values"] is not None:
                    acc["values"].append(v)
    out = []
    for i, acc in zip(indices, accs):
        kind = table.kinds[i]
        record: dict = {
            "column": table.columns[i],
            "type": kind,
            "count": acc["n"],
            "nulls": acc["nulls"],
            "distinct": len(acc["counts"]),
            "min": acc["lo"],
            "max": acc["hi"],
            "mean": None,
        }
        if top > 0:
            record["top"] = [
                {"value": v, "count": n} for v, n in acc["counts"].most_common(top)
            ]
        if acc["n"] and kind in ("int", "float"):
            record["mean"] = acc["sum"] / acc["n"]
            if acc["values"]:
                record["hist"] = histogram(acc["values"], bins)
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
    # ``rows`` may be any iterable: each group keeps one small accumulator per
    # aggregate (count, running sum, best value, distinct set), not its rows.
    names = [agg_name(table, f, i) for f, i in aggs]
    groups: dict[tuple, list] = {}
    for row in rows:
        key = tuple("" if is_null(row[i]) else row[i].strip() for i in key_indices)
        state = groups.get(key)
        if state is None:
            state = groups[key] = [0] + [
                {"n": 0, "sum": 0, "best": None, "bestkey": None, "set": set()}
                for _ in aggs
            ]
        state[0] += 1
        for acc, (func, idx) in zip(state[1:], aggs):
            if idx is None or is_null(row[idx]):
                continue
            v = convert(row[idx], table.kinds[idx])
            acc["n"] += 1
            if func == "distinct":
                acc["set"].add(_distinct_key(v))
            elif func in ("sum", "mean"):
                acc["sum"] += v
            elif func in ("min", "max"):
                k = _sort_value(v, "text") if isinstance(v, str) else v
                if acc["bestkey"] is None or (k < acc["bestkey"] if func == "min" else k > acc["bestkey"]):
                    acc["best"], acc["bestkey"] = v, k
    out = []
    for key, state in groups.items():
        rec: dict = {}
        for i, cell in zip(key_indices, key):
            value = convert(cell, table.kinds[i]) if cell else None
            rec[table.columns[i]] = value
        for name, (func, idx), acc in zip(names, aggs, state[1:]):
            if idx is None:
                rec[name] = state[0]
            elif func == "count":
                rec[name] = acc["n"]
            elif func == "distinct":
                rec[name] = len(acc["set"])
            elif not acc["n"]:
                rec[name] = None
            elif func == "sum":
                rec[name] = acc["sum"]
            elif func == "mean":
                rec[name] = acc["sum"] / acc["n"]
            else:
                rec[name] = acc["best"]
        out.append(rec)
    return out


def duplicates(
    table: Table, rows: list[list[str]], key_indices: list[int]
) -> list[dict]:
    """Key combinations that occur more than once, with their row counts.

    Most frequent first; ties keep first-seen order. A null key cell counts
    as an empty value, so two rows with an empty key are duplicates.
    """
    groups = group_by(table, rows, key_indices, [("count", None)])
    dupes = [g for g in groups if g["count"] > 1]
    dupes.sort(key=lambda g: -g["count"])
    return dupes


def _distinct_key(value):
    if isinstance(value, str):
        return value.strip()
    return value
