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
    """The filter expression is malformed or does not fit the table."""


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
            snippet = source[pos:].strip()
            if snippet[:1] in "'\"":
                raise ExprError(f"unterminated quote in filter: {snippet}")
            raise ExprError(f"unexpected character in filter at: {snippet}")
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

    def take(self) -> _Tok:
        tok = self.peek()
        if tok is None:
            raise ExprError(f"filter ends too early: {self.source!r}")
        self.i += 1
        return tok

    def parse(self) -> Predicate:
        if not self.tokens:
            raise ExprError("empty filter expression")
        pred = self.or_expr()
        tok = self.peek()
        if tok is not None:
            raise ExprError(f"unexpected {tok.text!r} in filter (missing 'and'/'or'?)")
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
                raise ExprError(f"expected ')' but found {close.text!r}")
            return inner
        return self.comparison()

    def comparison(self) -> Predicate:
        col_tok = self.take()
        if col_tok.kind not in ("word", "str"):
            raise ExprError(f"expected a column name but found {col_tok.text!r}")
        idx = self.table.resolve(col_tok.text)
        op_tok = self.take()
        if op_tok.keyword("is"):
            negate = False
            nxt = self.take()
            if nxt.keyword("not"):
                negate = True
                nxt = self.take()
            if not nxt.keyword("null", "empty"):
                raise ExprError(f"expected 'null' after 'is' but found {nxt.text!r}")
            return lambda row: is_null(row[idx]) != negate
        negate = False
        if op_tok.keyword("not"):
            negate = True
            op_tok = self.take()
            if not op_tok.keyword("in", "between"):
                raise ExprError(
                    f"expected 'in' or 'between' after 'not' but found {op_tok.text!r}"
                )
        if op_tok.keyword("in"):
            return self.in_list(idx, negate)
        if op_tok.keyword("between"):
            return self.between(idx, negate)
        if op_tok.kind != "op":
            raise ExprError(
                f"expected an operator after {col_tok.text!r} but found {op_tok.text!r}"
            )
        return _compare(self.table, idx, op_tok.text, self.value(op_tok.text))

    def value(self, after: str) -> str | _ColRef:
        tok = self.take()
        if tok.kind not in ("word", "str"):
            raise ExprError(f"expected a value after {after!r} but found {tok.text!r}")
        if tok.kind == "word" and tok.text.startswith("@"):
            name = tok.text[1:]
            if not name:
                nxt = self.peek()
                # The quoted name must follow '@' directly: @'unit price'.
                if nxt is None or nxt.kind != "str" or nxt.pos != tok.pos + 2:
                    raise ExprError("expected a column name after '@'")
                name = self.take().text
            return self.column_ref(name)
        return tok.text

    def column_ref(self, name: str) -> _ColRef:
        try:
            idx = self.table.resolve(name)
            return _ColRef(idx, self.table.columns[idx])
        except TableError as exc:
            raise ExprError(f"in '@{name}': {exc}") from None

    def in_list(self, idx: int, negate: bool) -> Predicate:
        open_tok = self.take()
        if open_tok.kind != "lparen":
            raise ExprError(f"expected '(' after 'in' but found {open_tok.text!r}")
        values: list[str | _ColRef] = []
        while True:
            tok = self.take()
            if tok.kind == "rparen":
                break
            if tok.kind == "str":
                values.append(tok.text)
            elif tok.kind == "word" and tok.text == "@":
                # @'quoted name': let value() read the name that follows.
                self.i -= 1
                values.append(self.value("in"))
            elif tok.kind == "word":
                # Commas are not separate tokens: "Paris," and "a,b" split here.
                for v in tok.text.split(","):
                    if v.startswith("@") and len(v) > 1:
                        values.append(self.column_ref(v[1:]))
                    elif v:
                        values.append(v)
            else:
                raise ExprError(f"unexpected {tok.text!r} in 'in' list")
        if not values:
            raise ExprError("empty 'in' list")
        if negate:
            # Each != predicate already rejects nulls, like != on its own.
            preds = [_compare(self.table, idx, "!=", v) for v in values]
            return lambda row: all(p(row) for p in preds)
        preds = [_compare(self.table, idx, "=", v) for v in values]
        return lambda row: any(p(row) for p in preds)

    def between(self, idx: int, negate: bool) -> Predicate:
        low = self.value("between")
        and_tok = self.take()
        if not and_tok.keyword("and"):
            raise ExprError(f"expected 'and' after {low!r} but found {and_tok.text!r}")
        high = self.value("and")
        ge = _compare(self.table, idx, ">=", low)
        le = _compare(self.table, idx, "<=", high)
        if negate:
            lt = _compare(self.table, idx, "<", low)
            gt = _compare(self.table, idx, ">", high)
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
