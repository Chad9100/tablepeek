import json

import pytest

from tablepeek.cli import main

CSV = """name,age,city,score,joined
Alice,34,Paris,88.5,2024-01-05
Bob,27,Lyon,72,2023-11-30
Chloe,41,Paris,91.25,2022-06-01
David,,Berlin,,2024-02-10
Emma,30,Paris,79,2021-09-09
Frank,27,Lyon,65,2020-01-01
"""


@pytest.fixture
def people(tmp_path):
    p = tmp_path / "people.csv"
    p.write_text(CSV, encoding="utf-8")
    return str(p)


def run(capsys, *argv):
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


@pytest.mark.parametrize(
    "argv",
    [
        ["stats"],
        ["stats", "-f", "json"],
        ["stats", "--top", "2", "-f", "csv"],
        ["stats", "-c", "age,score", "--hist", "--bins", "4"],
        ["stats", "-w", "city=Paris"],
        ["group", "city"],
        ["group", "city", "-a", "count,sum:age,mean:score,min:joined,max:name,distinct:age"],
        ["group", "city,age", "-a", "count,max:score", "-w", "age>26", "-f", "jsonl"],
        ["group", "city", "-a", "mean:score", "-n", "2"],
    ],
)
def test_stream_summary_matches_normal_output(capsys, people, argv):
    cmd, *rest = argv
    _, normal, _ = run(capsys, cmd, people, *rest)
    code, streamed, _ = run(capsys, cmd, people, *rest, "--stream")
    assert code == 0
    assert streamed == normal


def test_stream_group_values(capsys, people):
    code, out, _ = run(capsys, "group", people, "city", "-a", "count,mean:age", "--stream", "-f", "json")
    assert code == 0
    rows = {r["city"]: r for r in json.loads(out)}
    assert rows["Paris"]["count"] == 3
    assert rows["Berlin"]["mean_age"] is None


def test_stream_summary_late_misfit_warns(capsys, tmp_path):
    p = tmp_path / "mixed.csv"
    p.write_text("id,qty\n1,5\n2,6\n3,oops\n4,8\n", encoding="utf-8")
    code, out, err = run(capsys, "stats", str(p), "--stream", "--sample", "2", "-c", "qty", "-f", "json")
    assert code == 0
    rec = json.loads(out)[0]
    assert rec["count"] == 3 and rec["nulls"] == 1
    assert "column 'qty' was inferred as int" in err


def test_stream_summary_errors(capsys, tmp_path):
    code, _, err = run(capsys, "stats", str(tmp_path / "nope.csv"), "--stream")
    assert code == 2 and "no such file" in err
    p = tmp_path / "a.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    code, _, err = run(capsys, "group", str(p), "zzz", "--stream")
    assert code == 2 and "zzz" in err
