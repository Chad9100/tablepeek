# Roadmap

Estimates are rough working hours for one person.

## v0.1 (done)

- [x] `head`, `schema`, `stats`, `filter`, `sort`, `select` subcommands
- [x] Encoding detection (UTF-8, UTF-8/UTF-16 BOM, cp1252, latin-1) and
      delimiter sniffing (comma, tab, semicolon, pipe)
- [x] Type inference (int/float/date/bool/text) with null tokens
- [x] Filter expressions with typed comparisons, `and`/`or`/`not`,
      parentheses, `~` contains and `is null`
- [x] Multi-key typed sort with nulls last
- [x] Table, CSV, JSON and JSON Lines output; stdin input
- [x] pytest suite; CI on Ubuntu and Windows

## v0.2: richer expressions (about 4 h)

- [x] `city in (Paris, Lyon)` and `age between 20 and 30`
- [x] Regular-expression match operator (`=~`)
- [x] Column-to-column comparisons (`end > @start`)
- [x] Error messages that point at the position in the expression

## v0.3: more input formats (about 4 h)

- [x] Day-first and month-first dates (`07/03/2024`) with a `--dayfirst`
      switch, and detection when the column is unambiguous
- [x] Thousands separators and decimal commas (`1.234,5`) for European files
      (`--decimal-comma`)
- [x] `--skip N` for files with preamble lines before the header
- [x] Custom null tokens (`--null -`)

## v0.4: large files (about 5 h)

- [x] Stream `head`, `filter` and `select` instead of loading the whole file
      (`--stream`; streaming `stats` and `group` is still open)
- [x] Infer types from a sample (`--sample N`) with a clear warning when a
      later value breaks the inferred type
- [ ] Benchmark on a 1 GB synthetic file and document the numbers

## v0.5: grouping (about 4 h)

- [x] `tablepeek group FILE city --agg count,mean:score,max:age`
- [x] `stats --top N` showing the most frequent values per column
- [x] Histogram bars for numeric columns in `stats --hist`

## v1.0: release (about 3 h)

- [x] `--out-delimiter` and Markdown table output
- [ ] Publish to PyPI with a trusted-publishing GitHub workflow
- [x] Shell completion scripts (`tablepeek completion bash|zsh|fish`)
- [x] A `--help` review (examples in every command's help, operator summary
      in `filter -h`)

**Total for v0.2 to v1.0: about 20 hours.**
