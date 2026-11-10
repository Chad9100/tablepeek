import json
import subprocess
import sys

import pytest

from tablepeek.cli import main

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


def test_head_default_and_limit(people, capsys):
    code, out, _ = run(capsys, "head", people)
    assert code == 0
    lines = out.splitlines()
    assert lines[0].split() == ["name", "age", "city", "score"]
    assert len(lines) == 2 + 5
    _, out, _ = run(capsys, "head", people, "-n", "2")
    assert len(out.splitlines()) == 4


def test_schema_table_has_summary_line(people, capsys):
    code, out, _ = run(capsys, "schema", people)
    assert code == 0
    assert "5 rows, 4 columns, delimiter comma, encoding utf-8" in out
    assert any(line.split()[1:3] == ["age", "int"] for line in out.splitlines()[2:] if line.strip())


def test_schema_json(people, capsys):
    _, out, _ = run(capsys, "schema", people, "-f", "json")
    doc = json.loads(out)
    assert doc["rows"] == 5
    assert doc["delimiter"] == ","
    assert [c["type"] for c in doc["columns"]] == ["text", "int", "text", "float"]
    assert doc["columns"][1]["nulls"] == 1


def test_stats_json_with_where(people, capsys):
    _, out, _ = run(capsys, "stats", people, "-w", "city=Paris", "-c", "age,score", "-f", "json")
    recs = {r["column"]: r for r in json.loads(out)}
    assert recs["age"]["min"] == 30
    assert recs["age"]["max"] == 41
    assert recs["score"]["mean"] == pytest.approx((88.5 + 91.25 + 79) / 3, abs=1e-6)


def test_filter_csv_output(people, capsys):
    code, out, _ = run(capsys, "filter", people, "age>30 and city=Paris", "-f", "csv")
    assert code == 0
    assert out == "name,age,city,score\nAlice,34,Paris,88.5\nChloe,41,Paris,91.25\n"


def test_filter_count(people, capsys):
    _, out, _ = run(capsys, "filter", people, "city=Paris", "--count")
    assert out == "3\n"


def test_filter_column_to_column(people, capsys):
    code, out, _ = run(capsys, "filter", people, "score > @age and age > 30", "-c", "name", "-f", "csv")
    assert code == 0
    assert out == "name\nAlice\nChloe\n"


def test_sort_select_limit_pipeline(people, capsys):
    _, out, _ = run(capsys, "sort", people, "score:desc", "-c", "name", "-n", "3", "-f", "csv")
    assert out == "name\nChloe\nAlice\nEmma\n"


def test_select_with_where_json(people, capsys):
    _, out, _ = run(capsys, "select", people, "name,age", "-w", "age<30", "-f", "json")
    assert json.loads(out) == [{"name": "Bob", "age": 27}]


def test_head_desc_without_sort_reverses(people, capsys):
    _, out, _ = run(capsys, "head", people, "--desc", "-n", "1", "-c", "name", "-f", "csv")
    assert out == "name\nEmma\n"


def test_explicit_delimiter_and_no_header(tmp_path, capsys):
    p = tmp_path / "data.txt"
    p.write_text("1:a\n2:b\n", encoding="utf-8")
    _, out, _ = run(capsys, "head", str(p), "-d", ":", "--no-header", "-f", "csv")
    assert out == "col1,col2\n1,a\n2,b\n"


def test_cp1252_file(tmp_path, capsys):
    p = tmp_path / "legacy.csv"
    p.write_bytes("ville;prix\nMontréal;5€\n".encode("cp1252"))
    _, out, _ = run(capsys, "schema", str(p))
    assert "delimiter semicolon, encoding cp1252" in out
    _, out, _ = run(capsys, "head", str(p), "-f", "json")
    assert json.loads(out) == [{"ville": "Montréal", "prix": "5€"}]


def test_long_rows_warning(tmp_path, capsys):
    p = tmp_path / "r.csv"
    p.write_text("a,b\n1,2,3\n", encoding="utf-8")
    code, _, err = run(capsys, "head", str(p))
    assert code == 0
    assert "1 row(s) had more fields than the header" in err


@pytest.mark.parametrize(
    "argv, message",
    [
        (["filter", "{f}", "salary>1"], "unknown column 'salary'"),
        (["filter", "{f}", "age>"], "ends too early"),
        (["sort", "{f}", "zip"], "unknown column 'zip'"),
        (["head", "{missing}"], "no such file"),
        (["head", "{f}", "-e", "bogus-enc"], "unknown encoding"),
    ],
)
def test_errors_exit_2(people, tmp_path, capsys, argv, message):
    argv = [a.format(f=people, missing=str(tmp_path / "x.csv")) for a in argv]
    code, out, err = run(capsys, *argv)
    assert code == 2
    assert out == ""
    assert err.startswith("tablepeek: error:")
    assert message in err


def test_filter_error_points_at_position(people, capsys):
    code, out, err = run(capsys, "filter", people, "age>30 and city>=@scor")
    assert code == 2
    assert out == ""
    assert err.splitlines() == [
        "tablepeek: error: in '@scor': unknown column 'scor' (columns: name, age, city, score)",
        "  age>30 and city>=@scor",
        "                   ^",
    ]


def test_usage_error_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["head"])
    assert exc.value.code == 2


def test_module_entry_point_reads_stdin():
    proc = subprocess.run(
        [sys.executable, "-m", "tablepeek", "filter", "-", "n>1", "-f", "csv"],
        input=b"n\tx\n1\ta\n2\tb\n",
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.replace(b"\r\n", b"\n") == b"n,x\n2,b\n"


def test_skip_preamble_lines(tmp_path, capsys):
    p = tmp_path / "report.csv"
    p.write_text("Quarterly report\nexported 2024-01-01\nname,age\nAnn,30\nBob,25\n", encoding="utf-8")
    code, out, _ = run(capsys, "filter", str(p), "age>26", "--skip", "2", "-f", "csv")
    assert code == 0
    assert out.splitlines() == ["name,age", "Ann,30"]


def test_skip_too_many_lines_is_an_error(people, capsys):
    code, _, err = run(capsys, "head", people, "--skip", "99")
    assert code == 2
    assert "--skip 99 leaves no data" in err
