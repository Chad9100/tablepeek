"""Loading a delimited text file into a Table.

Handles encoding detection (UTF-8, UTF-8 with BOM, UTF-16 with BOM, then a
cp1252 fallback), delimiter sniffing, header clean-up and ragged rows.
"""

from __future__ import annotations

import codecs
import csv
import io
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

CANDIDATE_DELIMITERS = [",", "\t", ";", "|"]
DELIMITER_NAMES = {",": "comma", "\t": "tab", ";": "semicolon", "|": "pipe"}
_DELIMITER_ALIASES = {
    "comma": ",",
    "tab": "\t",
    "\\t": "\t",
    "semicolon": ";",
    "pipe": "|",
}
SNIFF_BYTES = 64 * 1024
SNIFF_ROWS = 50

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


class TableError(Exception):
    """A file could not be read or parsed as a table."""


@dataclass
class Table:
    columns: list[str]
    rows: list[list[str]]
    delimiter: str = ","
    encoding: str = "utf-8"
    source: str = "<stdin>"
    long_rows: int = 0  # rows with extra non-empty fields that were dropped
    short_rows: int = 0  # rows padded with empty fields
    _kinds: list[str] | None = field(default=None, repr=False)

    @property
    def kinds(self) -> list[str]:
        """Inferred type of every column (computed once, over all rows)."""
        if self._kinds is None:
            from tablepeek.infer import infer_column

            self._kinds = [
                infer_column(row[i] for row in self.rows)
                for i in range(len(self.columns))
            ]
        return self._kinds

    def resolve(self, name: str) -> int:
        """Return the index of a column given by name or 1-based number.

        Exact names win, then a unique case-insensitive match, then a number.
        """
        if name in self.columns:
            return self.columns.index(name)
        folded = [i for i, c in enumerate(self.columns) if c.casefold() == name.casefold()]
        if len(folded) == 1:
            return folded[0]
        if name.isdigit() and 1 <= int(name) <= len(self.columns):
            return int(name) - 1
        raise TableError(
            f"unknown column {name!r} (columns: {', '.join(self.columns)})"
        )

    def resolve_list(self, spec: str) -> list[int]:
        """Resolve a comma-separated list of columns."""
        names = [part.strip() for part in spec.split(",")]
        if not any(names):
            raise TableError("empty column list")
        return [self.resolve(n) for n in names if n]


def parse_delimiter(value: str) -> str:
    """Turn a user-supplied delimiter (``tab``, ``\\t``, ``;``) into one char."""
    value = _DELIMITER_ALIASES.get(value.lower(), value)
    if len(value) != 1:
        raise TableError(f"delimiter must be a single character, got {value!r}")
    return value


def decode(data: bytes, encoding: str | None = None) -> tuple[str, str]:
    """Decode bytes, returning ``(text, encoding_used)``.

    With no explicit encoding: a BOM decides (UTF-8 or UTF-16); otherwise
    strict UTF-8 is tried, then cp1252, then latin-1 (which never fails).
    """
    if encoding:
        try:
            text = data.decode(encoding)
        except LookupError:
            raise TableError(f"unknown encoding: {encoding}") from None
        except UnicodeDecodeError as exc:
            raise TableError(
                f"cannot decode as {encoding}: {exc.reason} at byte {exc.start}"
            ) from None
        if text.startswith("﻿"):
            text = text[1:]
        return text, encoding
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace"), "utf-8-sig"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace"), "utf-16"
    for candidate in ("utf-8", "cp1252"):
        try:
            return data.decode(candidate), candidate
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


def skip_lines(text: str, count: int, source: str = "<stdin>") -> str:
    """Drop the first ``count`` physical lines (preamble before the header)."""
    lines = text.splitlines(keepends=True)
    if count >= len(lines):
        raise TableError(
            f"{source}: --skip {count} leaves no data (file has {len(lines)} lines)"
        )
    return "".join(lines[count:])


def sniff_delimiter(text: str, preferred: str = ",") -> str:
    """Guess the delimiter from the first rows of ``text``.

    Each candidate is scored by how many sample rows have the same number of
    fields as the header, then by that field count. A candidate that gives a
    one-field header is ignored. Ties go to ``preferred``.
    """
    sample = text[: SNIFF_BYTES]
    if len(text) > SNIFF_BYTES and "\n" in sample:
        sample = sample[: sample.rfind("\n") + 1]
    order = [preferred] + [d for d in CANDIDATE_DELIMITERS if d != preferred]
    best, best_score = preferred, (0.0, 0)
    for delim in order:
        rows = []
        try:
            for row in csv.reader(io.StringIO(sample, newline=""), delimiter=delim):
                if row:
                    rows.append(row)
                if len(rows) >= SNIFF_ROWS:
                    break
        except csv.Error:
            continue
        if not rows or len(rows[0]) < 2:
            continue
        width = len(rows[0])
        consistent = sum(1 for r in rows if len(r) == width) / len(rows)
        score = (round(consistent, 3), width)
        if score > best_score:
            best, best_score = delim, score
    return best


def _clean_header(raw: list[str]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for i, name in enumerate(raw, start=1):
        name = name.strip() or f"col{i}"
        base, n = name, 2
        while name in seen:
            name = f"{base}_{n}"
            n += 1
        seen.add(name)
        columns.append(name)
    return columns


_EURO_NUMBER_RE = re.compile(r"([+-]?)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?")


def normalize_decimal_comma(cell: str) -> str:
    """Rewrite a European number (``1.234,5``) as ``1234.5``; leave others alone."""
    m = _EURO_NUMBER_RE.fullmatch(cell.strip())
    if not m:
        return cell
    sign, whole, frac = m.groups()
    out = sign + whole.replace(".", "")
    return f"{out}.{frac}" if frac is not None else out


_SLASH_DATE_RE = re.compile(
    r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})((?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?)"
)


def _iso_date(day: int, month: int, year: int, rest: str) -> str | None:
    try:
        datetime(year, month, day)
    except ValueError:
        return None
    out = f"{year:04d}-{month:02d}-{day:02d}"
    return out + (" " + rest[1:] if rest else "")


def normalize_dates(table: "Table", dayfirst: bool = False) -> None:
    """Rewrite ``07/03/2024``-style columns as ISO dates, in place.

    A column is converted only when every non-empty cell matches. The order
    is detected from the data: a value like ``25/03/2024`` can only be
    day-first, ``03/25/2024`` only month-first. If both orders fit (every
    value is ambiguous) the column is left alone unless ``dayfirst`` is set,
    which then wins. Columns where neither order fits stay as they are.
    """
    for i in range(len(table.columns)):
        parsed = []
        for row in table.rows:
            cell = row[i].strip()
            if not cell:
                continue
            m = _SLASH_DATE_RE.fullmatch(cell)
            if not m:
                parsed = []
                break
            parsed.append((int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)))
        if not parsed:
            continue
        as_day = all(_iso_date(a, b, y, r) for a, b, y, r in parsed)
        as_month = all(_iso_date(b, a, y, r) for a, b, y, r in parsed)
        if as_day and as_month:
            if not dayfirst:
                continue
            order = "day"
        elif as_day:
            order = "day"
        elif as_month:
            order = "month"
        else:
            continue
        for row in table.rows:
            m = _SLASH_DATE_RE.fullmatch(row[i].strip())
            if not m:
                continue
            a, b, y, r = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
            row[i] = _iso_date(a, b, y, r) if order == "day" else _iso_date(b, a, y, r)


def parse_text(
    text: str,
    delimiter: str,
    header: bool = True,
    encoding: str = "utf-8",
    source: str = "<stdin>",
    null_tokens: Sequence[str] = (),
    decimal_comma: bool = False,
    dayfirst: bool = False,
) -> Table:
    """Parse decoded text into a Table. Blank lines are skipped.

    Cells equal (after trimming) to one of ``null_tokens`` become empty
    strings, so every later stage sees them as nulls.
    """
    extra = frozenset(null_tokens)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    records: list[list[str]] = []
    try:
        for row in reader:
            if row:
                records.append(row)
    except csv.Error as exc:
        raise TableError(f"{source}: line {reader.line_num}: {exc}") from None
    if not records:
        raise TableError(f"{source}: no data (file is empty)")
    if header:
        columns = _clean_header(records[0])
        body = records[1:]
    else:
        width = max(len(r) for r in records)
        columns = [f"col{i}" for i in range(1, width + 1)]
        body = records
    width = len(columns)
    table = Table(columns, [], delimiter=delimiter, encoding=encoding, source=source)
    for row in body:
        if len(row) < width:
            row = row + [""] * (width - len(row))
            table.short_rows += 1
        elif len(row) > width:
            if any(cell.strip() for cell in row[width:]):
                table.long_rows += 1
            row = row[:width]
        if extra:
            row = ["" if cell.strip() in extra else cell for cell in row]
        if decimal_comma:
            row = [normalize_decimal_comma(cell) for cell in row]
        table.rows.append(row)
    normalize_dates(table, dayfirst)
    return table


def apply_sample(table: Table, sample: int) -> list[str]:
    """Infer column types from the first ``sample`` rows only.

    Later cells that do not fit the inferred type are replaced by empty
    strings (nulls) so every later stage can still convert them. One warning
    per affected column is returned, naming the count and the first offender.
    """
    from tablepeek.infer import convert, infer_column

    if sample < 1:
        raise TableError("--sample must be at least 1")
    head = table.rows[:sample]
    table._kinds = [
        infer_column(row[i] for row in head) for i in range(len(table.columns))
    ]
    warnings: list[str] = []
    for i, kind in enumerate(table._kinds):
        if kind == "text":
            continue
        bad = 0
        first = None
        for n, row in enumerate(table.rows[sample:], start=sample + 1):
            try:
                convert(row[i], kind)
            except ValueError:
                bad += 1
                if first is None:
                    first = (n, row[i])
                row[i] = ""
        if bad:
            warnings.append(
                f"column {table.columns[i]!r} was inferred as {kind} from the first "
                f"{sample} rows, but {bad} later value(s) do not fit "
                f"(first: {first[1]!r} in data row {first[0]}); treated as null"
            )
    return warnings


def load(
    path: str,
    delimiter: str | None = None,
    encoding: str | None = None,
    header: bool = True,
    stdin=None,
    skip: int = 0,
    null_tokens: Sequence[str] = (),
    decimal_comma: bool = False,
    dayfirst: bool = False,
) -> Table:
    """Read ``path`` (``-`` for stdin) into a Table."""
    if path == "-":
        stream = stdin if stdin is not None else sys.stdin.buffer
        data = stream.read()
        source = "<stdin>"
        preferred = ","
    else:
        p = Path(path)
        try:
            data = p.read_bytes()
        except FileNotFoundError:
            raise TableError(f"no such file: {path}") from None
        except IsADirectoryError:
            raise TableError(f"is a directory: {path}") from None
        except PermissionError:
            if p.is_dir():
                raise TableError(f"is a directory: {path}") from None
            raise TableError(f"permission denied: {path}") from None
        source = path
        preferred = "\t" if p.suffix.lower() in (".tsv", ".tab") else ","
    text, used = decode(data, encoding)
    if skip:
        text = skip_lines(text, skip, source)
    if delimiter is None:
        delim = sniff_delimiter(text, preferred)
    else:
        delim = parse_delimiter(delimiter)
    return parse_text(text, delim, header=header, encoding=used, source=source,
                      null_tokens=null_tokens, decimal_comma=decimal_comma,
                      dayfirst=dayfirst)
