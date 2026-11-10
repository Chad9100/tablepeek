"""Filter expressions such as ``age>30 and city=Paris``.

Grammar (keywords are case-insensitive)::

    expr       := and_expr ("or" and_expr)*
    and_expr   := not_expr ("and" not_expr)*
    not_expr   := "not" not_expr | "(" expr ")" | comparison
    comparison := COLUMN OP VALUE | COLUMN "is" ["not"] "null"
                | COLUMN ["not"] "in" "(" VALUE ("," VALUE)* ")"
                | COLUMN ["not"] "between" VALUE "and" VALUE
    OP         := = | == | != | > | >= | < | <= | ~ | !~ | =~
    VALUE      := LITERAL | "@" COLUMN

``~`` is a case-insensitive "contains"; ``!~`` its negation. Columns and
values may be quoted with '...' or "..." (needed for spaces or operator
characters). ``=~`` matches a Python regular expression anywhere in the
cell's text (case-sensitive; prefix the pattern with ``(?i)`` to ignore
case). Values compare by the column's inferred type, so ``age>9`` is
numeric and ``date>=2024-01-01`` is chronological. A null cell never matches
a comparison; use ``is null`` / ``is not null`` to test for it.
``in`` matches any listed value and ``between`` is inclusive at both ends;
both use the same typed comparison as ``=`` and ``>=``/``<=``.

A value written ``@name`` (or ``@'name with spaces'``) refers to another
column of the same row, so ``end>@start`` compares two columns. Numeric
columns compare as numbers and two date or bool columns by their type;
otherwise only ``=``/``!=`` (as text) and ``~``/``!~`` are allowed. Quote a
literal value that starts with ``@``: ``handle='@bob'``.

Errors raised while compiling carry the offset of the offending token, and
their text repeats the expression with a ``^`` under that spot.
"""

from __future__ import annotations

import re
from typing import Callable

from tablepeek.infer import convert, is_null
from tablepeek.table import Table, TableError

Predicate = Callable[[list[str]], bool]

_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<lparen>\() |
        (?P<rparen>\)) |
        (?P<op>>=|<=|!=|=~|==|!~|=|>|<|~) |
        '(?P<sq>[^']*)' |
        "(?P<dq>[^"]*)" |
        (?P<word>[^\s()=!<>~'"]+)
    )""",
    re.VERBOSE,
)


class ExprError(TableError):
    """The filter expression is malformed or does not fit the table.

    When ``source`` and ``pos`` are known, ``str()`` adds the expression and
    a caret under the offending character::

        unknown column 'salary' (columns: ...)
          salary>1
          ^
    """

    def __init__(self, message: str, source: str | None = None, pos: int | None = None):
        super().__init__(message)
        self.message, self.source, self.pos = message, source, pos

    def __str__(self) -> str:
        if self.source is None or self.pos is None:
            return self.message
        # Tabs and newlines would misalign the caret; show them as spaces.
        shown = re.sub(r"\s", " ", self.source)
        return f"{self.message}\n  {shown}\n  {' ' * self.pos}^"


class _Tok:
    __slots__ = ("kind", "text", "pos")

    def __init__(self, kind: str, text: str, pos: int):
        self.kind, self.text, self.pos = kind, text, pos

    def keyword(self, *words: str) -> bool:
        return self.kind == "word" and self.text.lower() in words


def tokenize(source: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    pos = 0
    while pos < len(source):
        if source[pos:].strip() == "":
            break
        m = _TOKEN_RE.match(source, pos)
        if not m or m.end() == pos:
            start = len(source) - len(source[pos:].lstrip())
            snippet = source[start:].rstrip()
            if snippet[:1] in "'\"":
                raise ExprError(f"unterminated quote in filter: {snippet}", source, start)
            raise ExprError(f"unexpected character in filter at: {snippet}", source, start)
        kind = m.lastgroup
        start = m.start(kind)
        if kind in ("sq", "dq"):
            tokens.append(_Tok("str", m.group(kind), start))
        else:
            tokens.append(_Tok(kind, m.group(kind), start))
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, source: str, table: Table):
        self.source = source
        self.tokens = tokenize(source)
        self.i = 0
        self.table = table

    def peek(self) -> _Tok | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def error(self, message: str, at: _Tok | int) -> ExprError:
        """An ExprError pointing at a token or a character offset."""
        if isinstance(at, _Tok):
            # A quoted token's pos is just inside the quote; point at the quote.
            at = at.pos - 1 if at.kind == "str" else at.pos
        return ExprError(message, self.source, at)

    def take(self) -> _Tok:
        tok = self.peek()
        if tok is None:
            raise self.error("filter ends too early", len(self.source.rstrip()))
        self.i += 1
        return tok

    def resolve(self, name: str, at: _Tok | int, prefix: str = "") -> int:
        try:
            return self.table.resolve(name)
        except TableError as exc:
            raise self.error(f"{prefix}{exc}", at) from None

    def compare(self, idx: int, op: str, raw: str | _ColRef, at: int) -> Predicate:
        try:
            return _compare(self.table, idx, op, raw)
        except ExprError as exc:
            if exc.pos is not None:
                raise
            raise self.error(exc.message, at) from None

    def parse(self) -> Predicate:
        if not self.tokens:
            raise ExprError("empty filter expression")
        pred = self.or_expr()
        tok = self.peek()
        if tok is not None:
            raise self.error(f"unexpected {tok.text!r} in filter (missing 'and'/'or'?)", tok)
        return pred

    def or_expr(self) -> Predicate:
        parts = [self.and_expr()]
        while (tok := self.peek()) is not None and tok.keyword("or"):
            self.take()
            parts.append(self.and_expr())
        if len(parts) == 1:
            return parts[0]
        return lambda row: any(p(row) for p in parts)

    def and_expr(self) -> Predicate:
        parts = [self.not_expr()]
        while (tok := self.peek()) is not None and tok.keyword("and"):
            self.take()
            parts.append(self.not_expr())
        if len(parts) == 1:
            return parts[0]
        return lambda row: all(p(row) for p in parts)

    def not_expr(self) -> Predicate:
        tok = self.peek()
        if tok is not None and tok.keyword("not"):
            self.take()
            inner = self.not_expr()
            return lambda row: not inner(row)
        if tok is not None and tok.kind == "lparen":
            self.take()
            inner = self.or_expr()
            close = self.take()
            if close.kind != "rparen":
                raise self.error(f"expected ')' but found {close.text!r}", close)
            return inner
        return self.comparison()

    def comparison(self) -> Predicate:
        col_tok = self.take()
        if col_tok.kind not in ("word", "str"):
            raise self.error(f"expected a column name but found {col_tok.text!r}", col_tok)
        idx = self.resolve(col_tok.text, col_tok)
        op_tok = self.take()
        if op_tok.keyword("is"):
            negate = False
            nxt = self.take()
            if nxt.keyword("not"):
                negate = True
                nxt = self.take()
            if not nxt.keyword("null", "empty"):
                raise self.error(f"expected 'null' after 'is' but found {nxt.text!r}", nxt)
            return lambda row: is_null(row[idx]) != negate
        negate = False
        if op_tok.keyword("not"):
            negate = True
            op_tok = self.take()
            if not op_tok.keyword("in", "between"):
                raise self.error(
                    f"expected 'in' or 'between' after 'not' but found {op_tok.text!r}",
                    op_tok,
                )
        if op_tok.keyword("in"):
            return self.in_list(idx, negate)
        if op_tok.keyword("between"):
            return self.between(idx, negate)
        if op_tok.kind != "op":
            raise self.error(
                f"expected an operator after {col_tok.text!r} but found {op_tok.text!r}",
                op_tok,
            )
        raw, pos = self.value(op_tok.text)
        return self.compare(idx, op_tok.text, raw, pos)

    def value(self, after: str) -> tuple[str | _ColRef, int]:
        """Read a literal or ``@column`` value; return it and its offset."""
        tok = self.take()
        if tok.kind not in ("word", "str"):
            raise self.error(f"expected a value after {after!r} but found {tok.text!r}", tok)
        if tok.kind == "word" and tok.text.startswith("@"):
            name = tok.text[1:]
            if not name:
                nxt = self.peek()
                # The quoted name must follow '@' directly: @'unit price'.
                if nxt is None or nxt.kind != "str" or nxt.pos != tok.pos + 2:
                    raise self.error("expected a column name after '@'", tok)
                name = self.take().text
            return self.column_ref(name, tok.pos), tok.pos
        return tok.text, (tok.pos - 1 if tok.kind == "str" else tok.pos)

    def column_ref(self, name: str, pos: int) -> _ColRef:
        idx = self.resolve(name, pos, prefix=f"in '@{name}': ")
        return _ColRef(idx, self.table.columns[idx])

    def in_list(self, idx: int, negate: bool) -> Predicate:
        open_tok = self.take()
        if open_tok.kind != "lparen":
            raise self.error(f"expected '(' after 'in' but found {open_tok.text!r}", open_tok)
        values: list[tuple[str | _ColRef, int]] = []
        while True:
            tok = self.take()
            if tok.kind == "rparen":
                break
            if tok.kind == "str":
                values.append((tok.text, tok.pos - 1))
            elif tok.kind == "word" and tok.text == "@":
                # @'quoted name': let value() read the name that follows.
                self.i -= 1
                values.append(self.value("in"))
            elif tok.kind == "word":
                # Commas are not separate tokens: "Paris," and "a,b" split here.
                pos = tok.pos
                for v in tok.text.split(","):
                    if v.startswith("@") and len(v) > 1:
                        values.append((self.column_ref(v[1:], pos), pos))
                    elif v:
                        values.append((v, pos))
                    pos += len(v) + 1
            else:
                raise self.error(f"unexpected {tok.text!r} in 'in' list", tok)
        if not values:
            raise self.error("empty 'in' list", open_tok)
        if negate:
            # Each != predicate already rejects nulls, like != on its own.
            preds = [self.compare(idx, "!=", v, pos) for v, pos in values]
            return lambda row: all(p(row) for p in preds)
        preds = [self.compare(idx, "=", v, pos) for v, pos in values]
        return lambda row: any(p(row) for p in preds)

    def between(self, idx: int, negate: bool) -> Predicate:
        low, low_pos = self.value("between")
        and_tok = self.take()
        if not and_tok.keyword("and"):
            raise self.error(
                f"expected 'and' after {low!r} but found {and_tok.text!r}", and_tok
            )
        high, high_pos = self.value("and")
        ge = self.compare(idx, ">=", low, low_pos)
        le = self.compare(idx, "<=", high, high_pos)
        if negate:
            lt = self.compare(idx, "<", low, low_pos)
            gt = self.compare(idx, ">", high, high_pos)
            return lambda row: lt(row) or gt(row)
        return lambda row: ge(row) and le(row)


_ORDER_OPS = {
    "=": lambda a, b: a == b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


class _ColRef:
    """A reference to another column (``@name``) on the right of an operator."""

    __slots__ = ("idx", "name")

    def __init__(self, idx: int, name: str):
        self.idx, self.name = idx, name

    def __repr__(self) -> str:
        return repr("@" + self.name)


_NUMERIC = ("int", "float")


def _compare_columns(table: Table, idx: int, op: str, other: int) -> Predicate:
    left, right = table.columns[idx], table.columns[other]
    lkind, rkind = table.kinds[idx], table.kinds[other]

    if op == "=~":
        raise ExprError(f"'=~' needs a literal pattern, not column '@{right}'")

    def both_present(row: list[str]) -> bool:
        return not is_null(row[idx]) and not is_null(row[other])

    if op in ("~", "!~"):
        want = op == "~"
        return lambda row: both_present(row) and (
            (row[other].lower() in row[idx].lower()) == want
        )

    fn = _ORDER_OPS[op]
    typed = (lkind in _NUMERIC and rkind in _NUMERIC) or (
        lkind == rkind and lkind in ("date", "bool")
    )
    if not typed:
        if lkind != rkind and op not in ("=", "==", "!="):
            raise ExprError(
                f"cannot order {lkind} column {left!r} against {rkind} column {right!r}"
            )
        return lambda row: both_present(row) and fn(row[idx].strip(), row[other].strip())

    def pred(row: list[str]) -> bool:
        try:
            a = convert(row[idx], lkind)
            b = convert(row[other], rkind)
        except ValueError:
            return False
        return a is not None and b is not None and fn(a, b)

    return pred


def _compare(table: Table, idx: int, op: str, raw: str | _ColRef) -> Predicate:
    if isinstance(raw, _ColRef):
        return _compare_columns(table, idx, op, raw.idx)
    name = table.columns[idx]
    kind = table.kinds[idx]

    if op == "=~":
        try:
            pattern = re.compile(raw)
        except re.error as exc:
            raise ExprError(f"bad regular expression {raw!r} for {name!r}: {exc}") from None
        return lambda row: (not is_null(row[idx])) and pattern.search(row[idx]) is not None

    if op in ("~", "!~"):
        needle = raw.lower()
        want = op == "~"
        return lambda row: (not is_null(row[idx])) and ((needle in row[idx].lower()) == want)

    fn = _ORDER_OPS[op]
    if kind == "text":
        return lambda row: (not is_null(row[idx])) and fn(row[idx].strip(), raw)

    target_kind = "float" if kind in ("int", "float") else kind
    try:
        target = convert(raw, target_kind)
    except ValueError:
        target = None
    if target is None:
        if op in ("=", "==", "!="):
            # e.g. qty=unknown on a numeric column: compare the raw text.
            return lambda row: (not is_null(row[idx])) and fn(row[idx].strip(), raw)
        raise ExprError(f"cannot compare {kind} column {name!r} with {raw!r}")

    def pred(row: list[str]) -> bool:
        try:
            value = convert(row[idx], kind)
        except ValueError:
            return False
        return value is not None and fn(value, target)

    return pred


def compile_filter(source: str, table: Table) -> Predicate:
    """Compile ``source`` into a predicate over the rows of ``table``."""
    return _Parser(source, table).parse()
