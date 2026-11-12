import json

import pytest

from tablepeek.cli import main

CSV = """id,city,qty
1,Paris,5
2,Lyon,3
3,Paris,5
4,Paris,7
5,Lyon,3
6,Rome,1
7,Paris,5
8,,2
9,,2
"""


@pytest.fixture
def path(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text(CSV, encoding="utf-8")
    return str(p)


def run(capsys, *argv):
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def recs(out):
    return [json.loads(line) for line in out.splitlines()]


def test_dupes_on_one_column_most_frequent_first(path, capsys):
    code, out, _ = run(capsys, "dupes", path, "city", "-f", "jsonl")
    assert code == 0
    assert recs(out) == [
        {"city": "Paris", "count": 4},
        {"city": "Lyon", "count": 2},
        {"city": None, "count": 2},
    ]


def test_dupes_default_uses_all_columns_but_id_makes_rows_unique(path, capsys):
    code, out, _ = run(capsys, "dupes", path, "-f", "jsonl")
    assert code == 0
    assert out == ""


def test_dupes_on_several_columns(path, capsys):
    code, out, _ = run(capsys, "dupes", path, "city,qty", "-f", "jsonl")
    assert recs(out)[0] == {"city": "Paris", "qty": 5, "count": 3}
    assert len(recs(out)) == 3


def test_dupes_where_limit_and_count(path, capsys):
    code, out, _ = run(capsys, "dupes", path, "city", "-w", "qty = 5", "-f", "jsonl")
    assert recs(out) == [{"city": "Paris", "count": 3}]
    code, out, _ = run(capsys, "dupes", path, "city", "-n", "1", "-f", "jsonl")
    assert len(recs(out)) == 1
    code, out, _ = run(capsys, "dupes", path, "city", "--count")
    assert out == "3\n"


def test_dupes_unknown_column_is_an_error(path, capsys):
    code, _, err = run(capsys, "dupes", path, "nope")
    assert code == 2
    assert "nope" in err
