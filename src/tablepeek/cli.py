"""Command-line interface for tablepeek."""

from __future__ import annotations

import argparse
import json
import os
import sys

from tablepeek import __version__
from tablepeek.completion import SHELLS, generate
from tablepeek.expr import compile_filter
from tablepeek.ops import (
    agg_name, group_by, parse_agg_spec, parse_sort_spec, schema, sort_rows, stats,
)
from tablepeek.render import FORMATS, format_value, render_csv, render_rows, render_summary
from tablepeek.table import (
    DELIMITER_NAMES, STREAM_SAMPLE, Table, TableError, apply_sample, load,
    open_stream, parse_delimiter,
)

PROG = "tablepeek"


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more: {text}")
    return value


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("file", help="CSV/TSV file to read, or - for stdin")
    common.add_argument(
        "-d", "--delimiter",
        help="field delimiter (default: auto-detect; accepts tab, comma, semicolon, pipe)",
    )
    common.add_argument(
        "-e", "--encoding",
        help="text encoding (default: auto-detect utf-8 / utf-8-sig / utf-16 / cp1252)",
    )
    common.add_argument(
        "--no-header", action="store_true",
        help="first line is data; columns are named col1, col2, ...",
    )
    common.add_argument(
        "--skip", type=_positive_int, default=0, metavar="N",
        help="ignore the first N lines (preamble before the header)",
    )
    common.add_argument(
        "--null", action="append", default=[], metavar="TOKEN", dest="null_tokens",
        help="also treat TOKEN (e.g. -) as a null value; repeatable",
    )
    common.add_argument(
        "--decimal-comma", action="store_true",
        help="read European numbers (1.234,5) as 1234.5; thousands dots are removed",
    )
    common.add_argument(
        "--dayfirst", action="store_true",
        help="read ambiguous dates like 07/03/2024 as day/month (default: only "
             "columns where the order is clear from the data are converted)",
    )
    common.add_argument(
        "--sample", type=_positive_int, default=None, metavar="N",
        help="infer column types from the first N rows only; later values that "
             "do not fit are warned about and treated as null",
    )
    common.add_argument(
        "-f", "--format", choices=FORMATS, default="table",
        help="output format (default: table)",
    )
    common.add_argument(
        "--out-delimiter", metavar="C", default=",",
        help="delimiter for -f csv output (default: comma; accepts tab, semicolon, pipe)",
    )
    common.add_argument(
        "--max-width", type=_positive_int, default=40, metavar="N",
        help="clip table cells wider than N characters (default: 40, 0 = never)",
    )

    rowopts = argparse.ArgumentParser(add_help=False)
    rowopts.add_argument("-w", "--where", metavar="EXPR", help="keep rows matching EXPR")
    rowopts.add_argument(
        "-s", "--sort", metavar="COLS",
        help="sort by columns, e.g. city,age:desc",
    )
    rowopts.add_argument("--desc", action="store_true", help="reverse the sort order")
    rowopts.add_argument("-c", "--columns", metavar="COLS", help="output only these columns")
    rowopts.add_argument("-n", "--limit", type=_positive_int, metavar="N", help="output at most N rows")
    rowopts.add_argument("--count", action="store_true", help="print only the number of matching rows")
    rowopts.add_argument(
        "--stream", action="store_true",
        help="read the file row by row instead of loading it (head, filter, select; "
             "stops early at -n; types come from the first --sample rows, default 1000; "
             "no sorting, and slash dates are not converted)",
    )

    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Inspect and query CSV/TSV files from the terminal.",
        epilog=(
            "examples:\n"
            "  tablepeek head people.csv -n 5\n"
            "  tablepeek filter people.csv \"age>30 and city=Paris\" -c name,age\n"
            "  tablepeek group people.csv city -a count,mean:score\n"
            "\n"
            "Run 'tablepeek COMMAND -h' for the options of each command."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    def add(name, summary, examples, **kwargs):
        text = "examples:\n" + "".join(f"  tablepeek {line}\n" for line in examples)
        return sub.add_parser(
            name, help=summary, description=summary[0].upper() + summary[1:] + ".",
            epilog=text, formatter_class=argparse.RawDescriptionHelpFormatter, **kwargs,
        )

    p = add("completion", "print a shell completion script",
            ["completion bash > ~/.tablepeek-completion"])
    p.add_argument("shell", choices=SHELLS, help="shell to generate the script for")

    p = add("head", "show the first rows (default 10)",
            ["head data.csv", "head data.csv -n 3 -c name,city -f json",
             "head data.csv --skip 2 --null - --decimal-comma"],
            parents=[common, rowopts])
    p.set_defaults(limit_default=10)

    add("schema", "inferred column types and null counts",
        ["schema data.csv", "schema data.csv --sample 1000 -f json"], parents=[common])

    p = add("stats", "min/max/mean/distinct per column",
            ["stats data.csv", "stats data.csv -c age,score --hist",
             "stats data.csv --top 3 -w \"city=Paris\""],
            parents=[common])
    p.add_argument("-w", "--where", metavar="EXPR", help="summarise only rows matching EXPR")
    p.add_argument("-c", "--columns", metavar="COLS", help="summarise only these columns")
    p.add_argument(
        "--top", type=_positive_int, default=0, metavar="N",
        help="also show the N most frequent values per column",
    )
    p.add_argument(
        "--hist", action="store_true",
        help="show a histogram for each numeric column (table or json output)",
    )
    p.add_argument(
        "--bins", type=_positive_int, default=8, metavar="N",
        help="number of histogram bins (default 8)",
    )

    p = add("group", "aggregate rows grouped by columns",
            ["group data.csv city", "group data.csv city,active -a count,mean:score,max:age"],
            parents=[common])
    p.add_argument("keys", help="comma-separated columns to group by, e.g. city,active")
    p.add_argument(
        "-a", "--agg", default="count", metavar="AGGS",
        help="aggregates, e.g. count,mean:score,max:age "
        "(count, sum, mean, min, max, distinct; default: count)",
    )
    p.add_argument("-w", "--where", metavar="EXPR", help="group only rows matching EXPR")
    p.add_argument("-n", "--limit", type=_positive_int, metavar="N", help="output at most N groups")

    p = add("filter", "rows matching an expression",
            ["filter data.csv \"age>30 and city=Paris\"",
             "filter data.csv \"city in (Paris, Lyon)\" -s age:desc -n 5",
             "filter data.csv \"name=~'^[A-C]' and email is not null\" --count"],
            parents=[common, rowopts])
    p.epilog += (
        "\nexpression operators: = != > >= < <= ~ !~ =~ in (...) between X and Y\n"
        "  is null, is not null, and/or/not, parentheses, @column on the right side\n"
    )
    p.add_argument("expr", help="e.g. \"age>30 and city=Paris\"")

    p = add("sort", "rows sorted by columns",
            ["sort data.csv city,age:desc", "sort data.csv score --desc -n 3"],
            parents=[common, rowopts])
    p.add_argument("keys", help="columns to sort by, e.g. city,age:desc")

    p = add("select", "only some columns",
            ["select data.csv name,city", "select data.csv 1,3 -f csv --out-delimiter tab"],
            parents=[common, rowopts])
    p.add_argument("cols", help="comma-separated column names or 1-based numbers")
    return parser


def _warn(message: str) -> None:
    print(f"{PROG}: warning: {message}", file=sys.stderr)


def _load(args) -> Table:
    table = load(
        args.file,
        delimiter=args.delimiter,
        encoding=args.encoding,
        header=not args.no_header,
        skip=args.skip,
        null_tokens=args.null_tokens,
        decimal_comma=args.decimal_comma,
        dayfirst=args.dayfirst,
    )
    if table.long_rows:
        _warn(f"{table.long_rows} row(s) had more fields than the header; extra fields ignored")
    if args.sample is not None:
        for message in apply_sample(table, args.sample):
            _warn(message)
    return table


def _rows_command(args, table: Table) -> str:
    where = [e for e in (getattr(args, "expr", None), args.where) if e]
    sort_spec = getattr(args, "keys", None) or args.sort
    col_spec = getattr(args, "cols", None) or args.columns
    limit = args.limit if args.limit is not None else getattr(args, "limit_default", None)

    rows = table.rows
    for expr in where:
        pred = compile_filter(expr, table)
        rows = [r for r in rows if pred(r)]
    if sort_spec:
        rows = sort_rows(table, rows, parse_sort_spec(table, sort_spec, args.desc))
    elif args.desc:
        rows = list(reversed(rows))
    indices = table.resolve_list(col_spec) if col_spec else list(range(len(table.columns)))
    if args.count:
        return f"{len(rows)}\n"
    if limit is not None:
        rows = rows[:limit]
    columns = [table.columns[i] for i in indices]
    kinds = [table.kinds[i] for i in indices]
    out_rows = [[r[i] for i in indices] for r in rows]
    return render_rows(
        args.format, columns, out_rows, kinds, args.max_width, parse_delimiter(args.out_delimiter)
    )


def _stream_command(args):
    """Yield output text for head/filter/select without loading the file."""
    if args.command == "sort" or args.sort or args.desc:
        raise TableError("--stream cannot sort; drop --stream or the sort option")
    where = [e for e in (getattr(args, "expr", None), args.where) if e]
    col_spec = getattr(args, "cols", None) or args.columns
    limit = args.limit if args.limit is not None else getattr(args, "limit_default", None)
    stream = open_stream(
        args.file,
        delimiter=args.delimiter,
        encoding=args.encoding,
        header=not args.no_header,
        skip=args.skip,
        null_tokens=args.null_tokens,
        decimal_comma=args.decimal_comma,
        sample=args.sample if args.sample is not None else STREAM_SAMPLE,
    )
    table = stream.table
    try:
        preds = [compile_filter(expr, table) for expr in where]
        indices = table.resolve_list(col_spec) if col_spec else list(range(len(table.columns)))
        columns = [table.columns[i] for i in indices]
        kinds = [table.kinds[i] for i in indices]
        delim = parse_delimiter(args.out_delimiter)
        live = args.format in ("csv", "jsonl") and not args.count
        out, count = [], 0
        if live and args.format == "csv":
            yield render_csv(columns, [], delim)
        for row in stream:
            if limit is not None and not args.count and count >= limit:
                break
            if all(p(row) for p in preds):
                count += 1
                if args.count:
                    continue
                picked = [row[i] for i in indices]
                if live:
                    if args.format == "csv":
                        yield render_csv(columns, [picked], delim, header=False)
                    else:
                        yield render_rows("jsonl", columns, [picked], kinds)
                else:
                    out.append(picked)
        if args.count:
            yield f"{count}\n"
        elif not live:
            yield render_rows(args.format, columns, out, kinds, args.max_width, delim)
    finally:
        stream.close()
    if table.long_rows:
        _warn(f"{table.long_rows} row(s) had more fields than the header; extra fields ignored")
    for message in stream.warnings():
        _warn(message)


def _describe(table: Table) -> str:
    delim = DELIMITER_NAMES.get(table.delimiter, repr(table.delimiter))
    return (
        f"{table.source}: {len(table.rows)} rows, {len(table.columns)} columns, "
        f"delimiter {delim}, encoding {table.encoding}\n\n"
    )


def _schema_command(args, table: Table) -> str:
    columns = schema(table)
    if args.format == "jsonl":
        return render_summary("jsonl", columns)
    if args.format == "json":
        doc = {
            "file": table.source,
            "rows": len(table.rows),
            "delimiter": table.delimiter,
            "encoding": table.encoding,
            "columns": columns,
        }
        return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    records = [{"#": i, **rec} for i, rec in enumerate(columns, start=1)]
    body = render_summary(
        args.format, records, ("#", "non_null", "nulls"), args.max_width,
        parse_delimiter(args.out_delimiter),
    )
    return _describe(table) + body if args.format == "table" else body


def _stats_command(args, table: Table) -> str:
    rows = table.rows
    if args.where:
        pred = compile_filter(args.where, table)
        rows = [r for r in rows if pred(r)]
    indices = table.resolve_list(args.columns) if args.columns else None
    if args.hist and args.format not in ("table", "json", "jsonl"):
        raise TableError("--hist works with table, json or jsonl output")
    if args.hist and args.bins < 1:
        raise TableError("--bins must be at least 1")
    records = stats(table, rows, indices, args.top, args.bins if args.hist else 0)
    hists = []
    if args.format == "table":
        hists = [(r["column"], r.pop("hist")) for r in records if "hist" in r]
    if args.top and args.format in ("table", "csv"):
        for rec in records:
            rec["top"] = ", ".join(
                f"{format_value(t['value'])} ({t['count']})" for t in rec["top"]
            )
    right = ("count", "nulls", "distinct", "mean")
    if args.format == "table":
        right += tuple(
            k for k in ("min", "max")
            if records and all(r["type"] in ("int", "float") for r in records)
        )
    text = render_summary(
        args.format, records, right, args.max_width, parse_delimiter(args.out_delimiter)
    )
    if args.hist and args.format == "table":
        text += "".join(_hist_block(name, h) for name, h in hists)
    return text


def _hist_block(name: str, bins: list[dict]) -> str:
    labels = [
        f"{format_value(b['from'])} .. {format_value(b['to'])}" for b in bins
    ]
    counts = [b["count"] for b in bins]
    lw, cw, peak = max(map(len, labels)), max(len(str(c)) for c in counts), max(counts)
    lines = [f"\n{name}\n"]
    for label, n in zip(labels, counts):
        bar = "#" * (max(1, round(n / peak * 30)) if n else 0)
        lines.append(f"{label:>{lw}}  {n:>{cw}}  {bar}".rstrip() + "\n")
    return "".join(lines)


def _group_command(args, table: Table) -> str:
    rows = table.rows
    if args.where:
        pred = compile_filter(args.where, table)
        rows = [r for r in rows if pred(r)]
    keys = table.resolve_list(args.keys)
    aggs = parse_agg_spec(table, args.agg)
    records = group_by(table, rows, keys, aggs)
    if args.limit is not None:
        records = records[: args.limit]
    right = tuple(agg_name(table, f, i) for f, i in aggs)
    right += tuple(table.columns[i] for i in keys if table.kinds[i] in ("int", "float"))
    return render_summary(
        args.format, records, right, args.max_width, parse_delimiter(args.out_delimiter)
    )


def _write(text: str) -> None:
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:
        # Reader went away (e.g. piped into `head`); exit quietly.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "completion":
        _write(generate(args.shell, parser, PROG))
        return 0
    try:
        if getattr(args, "stream", False):
            for chunk in _stream_command(args):
                _write(chunk)
            return 0
        table = _load(args)
        if args.command == "schema":
            text = _schema_command(args, table)
        elif args.command == "group":
            text = _group_command(args, table)
        elif args.command == "stats":
            text = _stats_command(args, table)
        else:
            text = _rows_command(args, table)
    except TableError as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    _write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
