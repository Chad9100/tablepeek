import pytest

from tablepeek.expr import ExprError, compile_filter
from tablepeek.table import TableError, parse_text

CSV = """name,age,city,joined,active,note
Alice,34,Paris,2023-04-12,yes,likes tea
Bob,27,Lyon,2022-11-03,no,
Chloe,41,Paris,2021-06-30,yes,Tea and cake
David,,Berlin,2024-01-15,yes,n/a
Emma,9,New York,2023-09-01,no,x
"""


@pytest.fixture
def table():
    return parse_text(CSV, ",")


def names(table, expr):
    pred = compile_filter(expr, table)
    return [r[0] for r in table.rows if pred(r)]


def test_and_with_numeric_and_text(table):
    assert names(table, "age>30 and city=Paris") == ["Alice", "Chloe"]


def test_numeric_comparison_is_not_lexical(table):
    # "9" > "30" as text, but 9 < 30 as numbers.
    assert names(table, "age<30") == ["Bob", "Emma"]


def test_or_not_and_parentheses(table):
    assert names(table, "city=Lyon or (city=Paris and not age>=40)") == ["Alice", "Bob"]


def test_and_binds_tighter_than_or(table):
    assert names(table, "city=Berlin or city=Paris and age>40") == ["Chloe", "David"]


def test_date_comparison(table):
    assert names(table, "joined>=2023-01-01") == ["Alice", "David", "Emma"]


def test_bool_comparison(table):
    assert names(table, "active=true") == ["Alice", "Chloe", "David"]


def test_contains_is_case_insensitive(table):
    assert names(table, "note~TEA") == ["Alice", "Chloe"]
    assert names(table, "note!~tea") == ["Emma"]


def test_quoted_values_and_columns(table):
    assert names(table, "city='New York'") == ["Emma"]
    assert names(table, '"name" != "Bob" and age > 40') == ["Chloe"]


def test_nulls_never_match_but_is_null_does(table):
    assert "David" not in names(table, "age!=34")
    assert names(table, "age is null") == ["David"]
    assert names(table, "note is null") == ["Bob", "David"]
    assert len(names(table, "note is not null")) == 3


def test_keywords_case_insensitive(table):
    assert names(table, "city=Paris AND age>40") == ["Chloe"]


def test_equality_with_non_number_falls_back_to_text(table):
    assert names(table, "age=unknown") == []


@pytest.mark.parametrize(
    "expr, message",
    [
        ("", "empty"),
        ("age>", "ends too early"),
        ("age 30", "expected an operator"),
        ("age>30 city=Paris", "missing 'and'"),
        ("(age>30", "ends too early"),
        ("city='Paris", "unterminated quote"),
        ("age>abc", "cannot compare int column 'age'"),
        ("age is maybe", "expected 'null'"),
    ],
)
def test_errors(table, expr, message):
    with pytest.raises(ExprError, match=message):
        compile_filter(expr, table)


def test_unknown_column_error(table):
    with pytest.raises(TableError, match="unknown column 'salary'"):
        compile_filter("salary>10", table)


def test_in_list(table):
    assert names(table, "city in (Paris, Lyon)") == ["Alice", "Bob", "Chloe"]
    assert names(table, "city in (Lyon,Berlin)") == ["Bob", "David"]
    assert names(table, "city IN ('New York', Lyon)") == ["Bob", "Emma"]


def test_in_list_is_typed(table):
    assert names(table, "age in (34.0, 9)") == ["Alice", "Emma"]
    assert names(table, "active in (true)") == ["Alice", "Chloe", "David"]


def test_not_in_skips_nulls(table):
    assert names(table, "age not in (34, 27)") == ["Chloe", "Emma"]
    assert names(table, "not city in (Paris)") == ["Bob", "David", "Emma"]


def test_between_is_inclusive_and_typed(table):
    assert names(table, "age between 9 and 34") == ["Alice", "Bob", "Emma"]
    assert names(table, "joined between 2022-01-01 and 2023-06-30") == ["Alice", "Bob"]


def test_between_combines_with_and(table):
    assert names(table, "age between 20 and 40 and city=Paris") == ["Alice"]
    assert names(table, "city=Berlin or age between 40 and 50") == ["Chloe", "David"]


def test_not_between_skips_nulls(table):
    assert names(table, "age not between 10 and 40") == ["Chloe", "Emma"]


@pytest.mark.parametrize(
    "expr, message",
    [
        ("city in Paris", "found 'Paris'"),
        ("city in ()", "empty 'in' list"),
        ("city in (Paris", "ends too early"),
        ("age between 1 30", "expected 'and'"),
        ("age between 1 and", "ends too early"),
        ("age between 1 and x", "cannot compare int column 'age'"),
        ("age not 30", "expected 'in' or 'between'"),
    ],
)
def test_in_between_errors(table, expr, message):
    with pytest.raises(ExprError, match=message):
        compile_filter(expr, table)
