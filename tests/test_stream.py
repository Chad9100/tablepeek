import io
import json

import pytest

from tablepeek.cli import main
from tablepeek.table import TableError, open_stream

CSV = """name,age,city,score
Alice,34,Paris,88.5
Bob,27,Lyon,72
Chloe,41,Paris,91.25
David,,Berlin,
Emma,30,Paris,79
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
        ["head", "-n", "3"],
        ["head", "-c", "name,age", "-f", "json"],
        ["filter", "age>28 and city=Paris", "-f", "csv"],
        ["filter", "city in (Paris, Lyon)", "-f", "jsonl"],
        ["filter", "score is null", "-f", "md"],
        ["select", "name,3", "-n", "2"],
        ["filter", "age>28", "--count"],
    ],
)
def test_stream_matches_normal_output(capsys, people, argv):
    cmd, *rest = argv
    _, normal, _ = run(capsys, cmd, people, *rest)
    code, streamed, _ = run(capsys, cmd, people, *rest, "--stream")
    assert code == 0
    assert streamed == normal


def test_stream_stops_reading_early(tmp_path):
    p = tmp_path / "big.csv"
    p.write_text("n,v\n" + "".join(f"{i},{i * 2}\n" for i in range(5000)), encoding="utf-8")
    stream = open_stream(str(p), sample=10)
    it = iter(stream)
    taken = [next(it) for _ in range(12)]
    assert taken[-1] == ["11", "22"]
    assert len(stream.table.rows) == 10
    stream.close()


def test_stream_late_misfit_warns_and_nulls(capsys, tmp_path):
    p = tmp_path / "mixed.csv"
    p.write_text("id,qty\n1,5\n2,6\n3,oops\n4,8\n", encoding="utf-8")
    code, out, err = run(capsys, "head", str(p), "--stream", "--sample", "2", "-f", "jsonl")
    assert code == 0
    assert [json.loads(line)["qty"] for line in out.splitlines()] == [5, 6, None, 8]
    assert "column 'qty' was inferred as int from the first 2 rows" in err
    assert "'oops'" in err and "data row 3" in err


def test_stream_rejects_sorting(capsys, people):
    code, _, err = run(capsys, "sort", people, "age", "--stream")
    assert code == 2 and "cannot sort" in err
    code, _, err = run(capsys, "head", people, "--stream", "--desc")
    assert code == 2 and "cannot sort" in err


def test_stream_options_skip_null_bom_and_ragged(capsys, tmp_path):
    p = tmp_path / "odd.csv"
    p.write_bytes(b"\xef\xbb\xbfjunk line\nid;name;x\n1;a;-\n2;b\n3;c;4;extra\n")
    code, out, err = run(
        capsys, "head", str(p), "--stream", "--skip", "1", "--null", "-", "-f", "jsonl"
    )
    assert code == 0
    rows = [json.loads(line) for line in out.splitlines()]
    assert rows[0] == {"id": 1, "name": "a", "x": None}
    assert rows[1]["x"] is None
    assert rows[2]["x"] == 4
    assert "extra fields ignored" in err


def test_stream_cp1252_detected_from_first_chunk(capsys, tmp_path):
    p = tmp_path / "latin.csv"
    p.write_bytes("name,city\nRené,Orléans\n".encode("cp1252"))
    code, out, _ = run(capsys, "head", str(p), "--stream", "-f", "csv")
    assert code == 0 and "Orléans" in out


def test_stream_from_stdin(monkeypatch, capsys):
    class Stdin:
        buffer = io.BufferedReader(io.BytesIO(CSV.encode()))

    monkeypatch.setattr("sys.stdin", Stdin)
    code, out, _ = run(capsys, "filter", "-", "city=Lyon", "--stream", "-f", "csv")
    assert code == 0
    assert out == "name,age,city,score\nBob,27,Lyon,72\n"


def test_stream_errors(capsys, tmp_path):
    code, _, err = run(capsys, "head", str(tmp_path / "nope.csv"), "--stream")
    assert code == 2 and "no such file" in err
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    code, _, err = run(capsys, "head", str(empty), "--stream")
    assert code == 2 and "no data" in err
    code, _, err = run(capsys, "head", str(tmp_path), "--stream")
    assert code == 2 and "directory" in err


def test_open_stream_rejects_bad_sample(people):
    with pytest.raises(TableError):
        open_stream(people, sample=0)
