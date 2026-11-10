"""Value and column type inference: int, float, date, bool, text."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

KINDS = ("int", "float", "date", "bool", "text")

NULL_TOKENS = frozenset({"", "na", "n/a", "null", "none", "nan"})
TRUE_TOKENS = frozenset({"true", "yes"})
FALSE_TOKENS = frozenset({"false", "no"})

# Leading zeros ("007", "02134") are identifiers, not numbers.
_INT_RE = re.compile(r"[+-]?(?:0|[1-9]\d*)")
_FLOAT_RE = re.compile(r"[+-]?(?:(?:0|[1-9]\d*)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_DATE_RE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?")
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f",
)


def is_null(value: str) -> bool:
    return value.strip().lower() in NULL_TOKENS


def parse_date(value: str) -> datetime | None:
    value = value.strip()
    if not _DATE_RE.fullmatch(value):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_bool(value: str) -> bool | None:
    v = value.strip().lower()
    if v in TRUE_TOKENS:
        return True
    if v in FALSE_TOKENS:
        return False
    return None


def value_kind(value: str) -> str:
    """Classify one cell: ``null`` or one of KINDS."""
    v = value.strip()
    if v.lower() in NULL_TOKENS:
        return "null"
    if _INT_RE.fullmatch(v):
        return "int"
    if _FLOAT_RE.fullmatch(v):
        return "float"
    if v.lower() in TRUE_TOKENS or v.lower() in FALSE_TOKENS:
        return "bool"
    if parse_date(v) is not None:
        return "date"
    return "text"


def infer_column(values: Iterable[str]) -> str:
    """Infer a column's type from its cells, ignoring nulls.

    All ints gives int; ints mixed with floats gives float; anything else
    mixed gives text. An all-null column is text.
    """
    kinds: set[str] = set()
    for value in values:
        kind = value_kind(value)
        if kind == "null":
            continue
        kinds.add(kind)
        if kind == "text":
            return "text"
    if not kinds:
        return "text"
    if kinds == {"int"}:
        return "int"
    if kinds <= {"int", "float"}:
        return "float"
    if len(kinds) == 1:
        return kinds.pop()
    return "text"


def convert(value: str, kind: str):
    """Convert a cell to a Python value for ``kind``; None for nulls.

    Raises ValueError if the cell does not fit the kind.
    """
    if is_null(value):
        return None
    v = value.strip()
    if kind == "int":
        return int(v)
    if kind == "float":
        if not _FLOAT_RE.fullmatch(v):
            raise ValueError(f"not a number: {value!r}")
        return float(v)
    if kind == "bool":
        b = parse_bool(v)
        if b is None:
            raise ValueError(f"not a boolean: {value!r}")
        return b
    if kind == "date":
        d = parse_date(v)
        if d is None:
            raise ValueError(f"not a date: {value!r}")
        return d
    return value
