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
tablepeek stats  FILE [-c COLS] [-w EXPR] [--top N] [--hist [--bins N]]
tablepeek group  FILE COLS [-a AGGS] [-w EXPR] [-n N]
tablepeek filter FILE EXPR
tablepeek sort   FILE COLS
tablepeek select FILE COLS
tablepeek completion {bash,zsh,fish}
```

`FILE` can be `-` to read standard input. Every command accepts:

| Option | Meaning |
| --- | --- |
| `-d, --delimiter C` | field delimiter; default is auto-detect (`tab`, `comma`, `semicolon`, `pipe` also accepted) |
| `-e, --encoding E` | text encoding; default is auto-detect |
| `--no-header` | the first line is data; columns become `col1`, `col2`, ... |
| `--skip N` | ignore the first N lines, for files with a preamble before the header |
| `--decimal-comma` | read European numbers (`1.234,5`) as `1234.5`; thousands dots are removed |
| `--dayfirst` | read ambiguous slash dates such as `07/03/2024` as day/month (see below) |
| `--null TOKEN` | also treat cells equal to TOKEN (for example `-` or `?`) as null; repeat for several tokens. Matching nulls show as empty cells |
| `--sample N` | infer column types from the first N rows only; later values that do not fit are reported on stderr and treated as null |
| `-f, --format F` | `table` (default), `csv`, `md` (Markdown table), `json` or `jsonl` |
| `--out-delimiter C` | delimiter for `-f csv` output (default comma; `tab`, `semicolon`, `pipe` also accepted) |
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

`stats --top N` adds a `top` column with the N most frequent values and their
counts (ties keep first-seen order). In `json`/`jsonl` output `top` is a list
of `{"value", "count"}` objects.

`stats --hist` draws an equal-width histogram (`--bins N`, default 8) for each
numeric column after the summary table; the last bin includes the maximum. It
works with table output, and in `json`/`jsonl` output numeric columns get a
`hist` list of `{"from", "to", "count"}`.

```text
$ tablepeek stats examples/people.csv -c age --hist --bins 4
column  type  count  nulls  distinct  min  max     mean
------  ----  -----  -----  --------  ---  ---  -------
age     int       7      1         7   27   52  35.8571

age
  27 .. 33.25  3  ##############################
33.25 .. 39.5  2  ####################
39.5 .. 45.75  1  ##########
  45.75 .. 52  1  ##########
```

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

$ tablepeek stats examples/people.csv --top 2 -c city,active
column  type  count  nulls  distinct  min     max   mean  top
------  ----  -----  -----  --------  ------  ----  ----  -------------------
city    text      8      0         5  Berlin  Rome        Paris (3), Lyon (2)
active  bool      8      0         2  false   true        true (5), false (3)
```

Grouping (`group`). `-a` takes `count`, `sum:COL`, `mean:COL`, `min:COL`,
`max:COL`, `distinct:COL` (default `count`); nulls are skipped, groups keep
first-seen order, and several key columns can be given:

```text
$ tablepeek group examples/people.csv city -a count,mean:score,max:age
city       count  mean_score  max_age
---------  -----  ----------  -------
Paris          3       86.25       41
Lyon           2          71       29
Berlin         1
Marseille      1        65.5       52
Rome           1          84       38

$ tablepeek group examples/people.csv active,city -a sum:score -f md
| active | city | sum_score |
| --- | --- | ---: |
| true | Paris | 179.75 |
| false | Lyon | 142 |
| true | Berlin |  |
| false | Paris | 79 |
| true | Marseille | 65.5 |
| true | Rome | 84 |
```

Custom null tokens (`--null`). In `examples/dashes.csv` a dash marks a missing
value, so by default `qty` and `price` are inferred as text:

```text
$ tablepeek schema examples/dashes.csv
examples/dashes.csv: 4 rows, 3 columns, delimiter comma, encoding utf-8

#  column  type  non_null  nulls  example
-  ------  ----  --------  -----  -------
1  item    text         4      0  pen
2  qty     text         4      0  10
3  price   text         4      0  1.5

$ tablepeek schema examples/dashes.csv --null -
examples/dashes.csv: 4 rows, 3 columns, delimiter comma, encoding utf-8

#  column  type   non_null  nulls  example
-  ------  -----  --------  -----  -------
1  item    text          4      0  pen
2  qty     int           2      2  10
3  price   float         3      1  1.5

$ tablepeek filter examples/dashes.csv "qty is null" --null -
item   qty  price
-----  ---  -----
ruler        2.25
tape         0.99
```

European numbers (`--decimal-comma`). `examples/european.csv` writes numbers
as `1.234,50`, so `preis` is text by default. With the switch, thousands dots
are removed and the decimal comma becomes a point (cells are shown
normalized, so `1.234,50` prints as `1234.50`):

```text
$ tablepeek schema examples/european.csv
examples/european.csv: 4 rows, 3 columns, delimiter semicolon, encoding utf-8

#  column   type  non_null  nulls  example
-  -------  ----  --------  -----  --------
1  produkt  text         4      0  Stuhl
2  preis    text         4      0  1.234,50
3  menge    int          4      0  3

$ tablepeek schema examples/european.csv --decimal-comma
examples/european.csv: 4 rows, 3 columns, delimiter semicolon, encoding utf-8

#  column   type   non_null  nulls  example
-  -------  -----  --------  -----  -------
1  produkt  text          4      0  Stuhl
2  preis    float         4      0  1234.50
3  menge    int           4      0  3

$ tablepeek filter examples/european.csv "preis > 1100" --decimal-comma
produkt    preis  menge
-------  -------  -----
Stuhl    1234.50      3
Tisch    2480.00      1
```

Day-first and month-first dates. Columns of `dd/mm/yyyy` or `mm/dd/yyyy`
values (`/`, `.` or `-` separators, optional time) are rewritten as ISO dates
when the order is clear from the data: `25/03/2024` can only be day-first. If
every value in a column is ambiguous (`07/04/2024`), it stays text until you
pass `--dayfirst`. Columns that fit neither order, or mix in other text, are
never changed. In `examples/orders.csv`, `shipped` is detected on its own
while `due` needs the switch:

```text
$ tablepeek schema examples/orders.csv
examples/orders.csv: 4 rows, 3 columns, delimiter comma, encoding utf-8

#  column   type  non_null  nulls  example
-  -------  ----  --------  -----  ----------
1  order    text         4      0  A1
2  shipped  date         3      1  2024-03-25
3  due      text         4      0  07/04/2024

$ tablepeek schema examples/orders.csv --dayfirst
examples/orders.csv: 4 rows, 3 columns, delimiter comma, encoding utf-8

#  column   type  non_null  nulls  example
-  -------  ----  --------  -----  ----------
1  order    text         4      0  A1
2  shipped  date         3      1  2024-03-25
3  due      date         4      0  2024-04-07

$ tablepeek filter examples/orders.csv "due < 2024-04-04" --dayfirst
order  shipped     due
-----  ----------  ----------
A3     2024-03-12  2024-04-01
A4                 2024-04-03
```

With `--decimal-comma`, a lone dotted group such as `1.050` is read as the
thousands form (1050), so only use it on files that really are European.

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

$ tablepeek select examples/people.csv name,city,score -w "score>=80" -f md
| name | city | score |
| --- | --- | ---: |
| Alice | Paris | 88.5 |
| Chloe | Paris | 91.25 |
| Giulia | Rome | 84 |

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

## Built-in help

Every command has its own `-h` with copy-pasteable examples at the bottom;
`tablepeek filter -h` ends with:

```text
examples:
  tablepeek filter data.csv "age>30 and city=Paris"
  tablepeek filter data.csv "city in (Paris, Lyon)" -s age:desc -n 5
  tablepeek filter data.csv "name=~'^[A-C]' and email is not null" --count

expression operators: = != > >= < <= ~ !~ =~ in (...) between X and Y
  is null, is not null, and/or/not, parentheses, @column on the right side
```

## Shell completion

`tablepeek completion SHELL` prints a completion script for `bash`, `zsh` or
`fish`. It is generated from the real option list, so it always matches the
installed version: it completes subcommands, each subcommand's options, and
the values of `-f/--format`. Load it from your shell's startup file:

```sh
# bash (~/.bashrc)
source <(tablepeek completion bash)
# zsh: put the output in a file named _tablepeek on your $fpath
tablepeek completion zsh > ~/.zsh/completions/_tablepeek
# fish
tablepeek completion fish > ~/.config/fish/completions/tablepeek.fish
```

```text
$ tablepeek completion bash | head -8
# bash completion for tablepeek
_tablepeek() {
    local cur prev cmd i
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmd=""
    for ((i=1; i<COMP_CWORD; i++)); do
        case "${COMP_WORDS[i]}" in
```

The bash script was exercised in bash; the zsh and fish scripts are generated
the same way but have not been tried in those shells yet.

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

## Sampling types

By default a column's type comes from every row, so one stray value makes it
`text`. With `--sample N` the type comes from the first N rows only, and every
later value is checked against it. Values that do not fit are blanked (treated
as null) and one warning per column names the count and the first offender.
Real output for a small file where `qty` goes wrong after row 2:

```text
$ tablepeek schema mixed.csv --sample 2
tablepeek: warning: column 'qty' was inferred as int from the first 2 rows, but 2 later value(s) do not fit (first: 'x' in data row 3); treated as null
mixed.csv: 5 rows, 3 columns, delimiter comma, encoding utf-8

#  column  type  non_null  nulls  example
-  ------  ----  --------  -----  -------
1  id      int          5      0  1
2  qty     int          2      3  5
3  note    text         5      0  a
```

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

- `head`, `schema`, `stats`, `group`, `filter`, `sort`, `select` subcommands
- Type inference (int/float/date/bool/text) with null counts
- Per-column count, nulls, distinct, min, max and mean
- Filter expressions with typed comparisons, `and`/`or`/`not`, parentheses,
  contains, regular expressions, `in` lists, `between` ranges, column-to-column
  comparisons and null tests; errors point at the offending spot
- Stable multi-key sort by typed values, nulls last, per-key `:desc`
- Output as an aligned table, CSV (any delimiter), Markdown, JSON (typed
  values) or JSON Lines
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
