# tablepeek

Inspect and query CSV/TSV files from the terminal. Look at the first rows,
see what type each column really is, get quick per-column statistics, and
filter, sort and select with a small expression language, then print the
result as an aligned table, CSV, JSON or JSON Lines.

**Who it is for:** anyone who gets a CSV export and wants answers ("how many
rows have no email?", "who joined before 2023?") without opening a
spreadsheet or writing a pandas script.

**Built with:** Python 3.10+ and the standard library only (no runtime
dependencies). Tests use pytest.

## Install

```sh
git clone https://github.com/Chad9100/tablepeek.git
cd tablepeek
python -m pip install .
```

That puts a `tablepeek` command on your PATH. `python -m tablepeek` works too.

## Usage

```text
tablepeek head   FILE [-n N]
tablepeek schema FILE
tablepeek stats  FILE [-c COLS] [-w EXPR]
tablepeek filter FILE EXPR
tablepeek sort   FILE COLS
tablepeek select FILE COLS
```

`FILE` can be `-` to read standard input. Every command accepts:

| Option | Meaning |
| --- | --- |
| `-d, --delimiter C` | field delimiter; default is auto-detect (`tab`, `comma`, `semicolon`, `pipe` also accepted) |
| `-e, --encoding E` | text encoding; default is auto-detect |
| `--no-header` | the first line is data; columns become `col1`, `col2`, ... |
| `--skip N` | ignore the first N lines, for files with a preamble before the header |
| `-f, --format F` | `table` (default), `csv`, `json` or `jsonl` |
| `--max-width N` | clip table cells wider than N characters (default 40, `0` = never) |

The row commands (`head`, `filter`, `sort`, `select`) share these options, so
one command can filter, sort and pick columns at once:

| Option | Meaning |
| --- | --- |
| `-w, --where EXPR` | keep rows matching EXPR |
| `-s, --sort COLS` | sort by columns, e.g. `city,age:desc` |
| `--desc` | reverse the sort (or the file order when there is no sort) |
| `-c, --columns COLS` | output only these columns (names or 1-based numbers) |
| `-n, --limit N` | output at most N rows (`head` defaults to 10) |
| `--count` | print only the number of matching rows |

They are applied in that order: filter, sort, limit, then columns. Errors
(unknown column, bad expression, unreadable file) go to stderr with exit
status 2.

### Examples

All output below is real, from [examples/people.csv](examples/people.csv).

```text
$ tablepeek head examples/people.csv -n 3
name   age  city   joined      active  score
-----  ---  -----  ----------  ------  -----
Alice   34  Paris  2023-04-12  yes      88.5
Bob     27  Lyon   2022-11-03  no         72
Chloe   41  Paris  2021-06-30  yes     91.25
```

Numeric columns are right-aligned.

```text
$ tablepeek schema examples/people.csv
examples/people.csv: 8 rows, 6 columns, delimiter comma, encoding utf-8

#  column  type   non_null  nulls  example
-  ------  -----  --------  -----  ----------
1  name    text          8      0  Alice
2  age     int           7      1  34
3  city    text          8      0  Paris
4  joined  date          7      1  2023-04-12
5  active  bool          8      0  yes
6  score   float         7      1  88.5
```

```text
$ tablepeek stats examples/people.csv
column  type   count  nulls  distinct  min         max            mean
------  -----  -----  -----  --------  ----------  ----------  -------
name    text       8      0         8  Alice       Hugo
age     int        7      1         7  27          52          35.8571
city    text       8      0         5  Berlin      Rome
joined  date       7      1         7  2020-02-20  2024-01-15
active  bool       8      0         2  false       true
score   float      7      1         7  65.5        91.25       78.6071

$ tablepeek stats examples/people.csv -c age,score -w active=yes
column  type   count  nulls  distinct   min    max     mean
------  -----  -----  -----  --------  ----  -----  -------
age     int        4      1         4    34     52    41.25
score   float      4      1         4  65.5  91.25  82.3125
```

```text
$ tablepeek filter examples/people.csv "age>30 and city=Paris"
name   age  city   joined      active  score
-----  ---  -----  ----------  ------  -----
Alice   34  Paris  2023-04-12  yes      88.5
Chloe   41  Paris  2021-06-30  yes     91.25

$ tablepeek filter examples/people.csv "joined<2023-01-01 or age is null" -c name,joined,age
name    joined      age
------  ----------  ---
Bob     2022-11-03   27
Chloe   2021-06-30   41
David   2024-01-15
Farid   2020-02-20   52
Giulia  2022-07-14   38

$ tablepeek filter examples/people.csv "city~par" --count
3
```

```text
$ tablepeek sort examples/people.csv city,age:desc -c name,city,age -n 5
name   city       age
-----  ---------  ---
David  Berlin
Hugo   Lyon        29
Bob    Lyon        27
Farid  Marseille   52
Chloe  Paris       41
```

```text
$ tablepeek select examples/people.csv name,score -w "score>=80" -f json
[
  {
    "name": "Alice",
    "score": 88.5
  },
  {
    "name": "Chloe",
    "score": 91.25
  },
  {
    "name": "Giulia",
    "score": 84.0
  }
]

$ tablepeek select examples/people.csv name,city -f csv -n 2
name,city
Alice,Paris
Bob,Lyon

$ tablepeek filter examples/people.csv "salary>1"
tablepeek: error: unknown column 'salary' (columns: name, age, city, joined, active, score)
  salary>1
  ^

$ tablepeek filter examples/people.csv "age>30 and joined>=last-year"
tablepeek: error: cannot compare date column 'joined' with 'last-year'
  age>30 and joined>=last-year
                     ^
```

Reading from a pipe (tab-separated here, detected automatically):

```text
$ printf 'id\tqty\n1\t5\n2\t7\n' | tablepeek head -
id  qty
--  ---
 1    5
 2    7
```

## Filter expressions

```text
age>30 and city=Paris
city=Lyon or (city=Paris and not age>=40)
joined>=2024-01-01
note~urgent            # case-insensitive "contains"
note!~draft            # does not contain
name=~'^[A-C]'         # regular expression (case-sensitive; '(?i)...' to ignore case)
email is null          # also: is not null
city in (Paris, Lyon)  # any of the listed values; also: not in
age between 20 and 30  # inclusive at both ends; also: not between
end > @start           # compare with another column of the same row
city='New York'        # quote values with spaces or operator characters
```

- Operators: `=` (or `==`), `!=`, `>`, `>=`, `<`, `<=`, `~`, `!~`, `=~`, plus
  `in (...)` and `between ... and ...` (each with an optional `not`). They
  compare by type like `=` and `>=`/`<=`, so `age in (9, 34)` is numeric and
  `joined between 2023-01-01 and 2023-12-31` is chronological. Quote list
  values that contain commas or spaces: `city in ('New York', Lyon)`.
- `and` binds tighter than `or`; `not` and parentheses work as usual.
  Keywords are case-insensitive.
- Values compare using the column's inferred type: `age<30` is numeric (so
  9 is less than 30), `joined>=2024-01-01` is chronological, `active=yes`
  matches `yes`/`true` in a bool column. Text compares exactly; use `~` for
  a case-insensitive match.
- `=~` uses Python regular-expression syntax and matches anywhere in the
  cell's text, whatever the column type (`joined=~'^2023-'`). Quote patterns
  that contain spaces, parentheses or `=!<>~`; negate with `not`.
- `@name` on the right-hand side refers to another column of the same row:
  `spent > @budget`, `end >= @start`, `price between @low and @high`,
  `city in (@home, Paris)`. Quote names with spaces as `@'unit price'`.
  Two numeric columns (int or float) compare as numbers and two date or bool
  columns by their type. Columns of different types can only be tested with
  `=`/`!=` (as text) or `~`/`!~`; `=~` needs a literal pattern. Quote a
  literal value that starts with `@`: `handle='@bob'`.
- A null cell never matches a comparison (`age!=34` and `age not in (34)`
  skip rows with no age, and `end>@start` skips rows where either is null);
  test for it with `is null`.
- Column names match exactly first, then case-insensitively; quote names
  with spaces: `"unit price">10`.
- A mistake in an expression (unknown column, a value that does not fit the
  column's type, a missing `and`, an unclosed quote or parenthesis) is
  reported with the expression and a `^` under the offending spot.

## How detection works

- **Encoding:** a UTF-8 or UTF-16 byte-order mark decides; otherwise strict
  UTF-8 is tried, then cp1252 (Windows/Excel exports), then latin-1, which
  always succeeds. `schema` prints the encoding it used; `-e` overrides it.
- **Delimiter:** comma, tab, semicolon and pipe are each tried on the first
  50 rows; the one whose rows most consistently match the header's field
  count (and gives the most fields) wins. `.tsv` files prefer tab on a tie.
  Quoted fields are respected, so `"Smith; John"` does not fool it.
- **Types:** a column is `int` if every non-null value is an integer, `float`
  if they are all numbers, `bool` for `true/false/yes/no`, `date` for ISO
  dates (`2024-03-07`, `2024/3/7`, optionally with a time), otherwise `text`.
  Numbers with leading zeros (`007`, ZIP codes) stay text. Empty cells and
  `NA`, `N/A`, `null`, `None`, `NaN` count as null.
- **Messy files:** blank lines are skipped, short rows are padded, extra
  fields are dropped with a warning, and blank or duplicate header names
  become `col3` or `id_2`.

## Features

- `head`, `schema`, `stats`, `filter`, `sort`, `select` subcommands
- Type inference (int/float/date/bool/text) with null counts
- Per-column count, nulls, distinct, min, max and mean
- Filter expressions with typed comparisons, `and`/`or`/`not`, parentheses,
  contains, regular expressions, `in` lists, `between` ranges, column-to-column
  comparisons and null tests; errors point at the offending spot
- Stable multi-key sort by typed values, nulls last, per-key `:desc`
- Output as an aligned table, CSV, JSON (typed values) or JSON Lines
- Auto-detected encoding and delimiter; stdin support
- No dependencies; tested on Windows and Linux with Python 3.10 to 3.13

## Development

```sh
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"   # .venv\Scripts\ on Windows
pytest -q
```

See [ROADMAP.md](ROADMAP.md) for planned work.

## License

MIT, see [LICENSE](LICENSE).
