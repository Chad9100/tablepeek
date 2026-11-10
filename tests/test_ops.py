from datetime import datetime

import pytest

from tablepeek.ops import parse_sort_spec, schema, sort_rows, stats
from tablepeek.table import TableError, parse_text

CSV = """name,age,city,joined,score
bob,27,Lyon,2022-11-03,72
Alice,34,Paris,2023-04-12,88.5
Chloe,41,Paris,2021-06-30,
David,,Berlin,2024-01-15,60
Emma,9,Lyon,2023-09-01,79
"""


@pytest.fixture
def table():
    return parse_text(CSV, ",")


def col(rows, i=0):
    return [r[i] for r in rows]


def sort_by(table, spec, desc=False):
    return col(sort_rows(table, table.rows, parse_sort_spec(table, spec, desc)))


def test_sort_numeric(table):
    assert sort_by(table, "age") == ["Emma", "bob", "Alice", "Chloe", "David"]


def test_sort_desc_keeps_nulls_last(table):
    assert sort_by(table, "age:desc") == ["Chloe", "Alice", "bob", "Emma", "David"]
    assert sort_by(table, "age", desc=True)[-1] == "David"


def test_sort_text_is_case_insensitive(table):
    assert sort_by(table, "name") == ["Alice", "bob", "Chloe", "David", "Emma"]


def test_sort_multi_key(table):
    assert sort_by(table, "city,age:desc") == ["David", "bob", "Emma", "Chloe", "Alice"]


def test_sort_by_date(table):
    assert sort_by(table, "joined")[0] == "Chloe"


def test_sort_spec_errors(table):
    with pytest.raises(TableError):
        parse_sort_spec(table, " , ")
    with pytest.raises(TableError, match="unknown column"):
        parse_sort_spec(table, "zip")


def test_schema(table):
    s = {r["column"]: r for r in schema(table)}
    assert s["age"]["type"] == "int"
    assert s["age"]["nulls"] == 1
    assert s["score"]["type"] == "float"
    assert s["joined"]["type"] == "date"
    assert s["name"]["example"] == "bob"
    assert s["city"]["non_null"] == 5


def test_stats_values(table):
    s = {r["column"]: r for r in stats(table, table.rows)}
    assert s["age"]["min"] == 9
    assert s["age"]["max"] == 41
    assert s["age"]["mean"] == pytest.approx(27.75)
    assert s["city"]["distinct"] == 3
    assert s["city"]["mean"] is None
    assert s["name"]["min"] == "Alice"  # case-insensitive ordering
    assert s["joined"]["max"] == datetime(2024, 1, 15)
    assert s["score"]["count"] == 4


def test_stats_subset_and_empty(table):
    out = stats(table, [], [1])
    assert out == [
        {"column": "age", "type": "int", "count": 0, "nulls": 0, "distinct": 0,
         "min": None, "max": None, "mean": None}
    ]
