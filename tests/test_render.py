import json
from datetime import datetime

from tablepeek.render import format_value, render_csv, render_rows, render_table


def test_table_alignment_numbers_right():
    out = render_table(["name", "n"], [["a", "5"], ["bbb", "10"]], [False, True])
    assert out.splitlines() == [
        "name   n",
        "----  --",
        "a      5",
        "bbb   10",
    ]


def test_table_clips_wide_cells_and_escapes_newlines():
    out = render_table(["t"], [["x" * 50], ["a\nb"]], max_width=10)
    lines = out.splitlines()
    assert lines[2] == "xxxxxxx..."
    assert lines[3] == "a\\nb"


def test_table_max_width_zero_means_no_clipping():
    out = render_table(["t"], [["y" * 60]], max_width=0)
    assert "y" * 60 in out


def test_csv_quotes_when_needed():
    out = render_csv(["a", "b"], [["x,y", 'say "hi"']])
    assert out == 'a,b\n"x,y","say ""hi"""\n'


def test_json_is_typed():
    out = render_rows(
        "json",
        ["n", "f", "b", "d", "t"],
        [["1", "2.5", "yes", "2024-01-02", ""], ["", "3", "no", "", "x"]],
        ["int", "float", "bool", "date", "text"],
    )
    assert json.loads(out) == [
        {"n": 1, "f": 2.5, "b": True, "d": "2024-01-02", "t": None},
        {"n": None, "f": 3.0, "b": False, "d": None, "t": "x"},
    ]


def test_jsonl_one_object_per_line():
    out = render_rows("jsonl", ["a"], [["é"], ["2"]], ["text"])
    assert out == '{"a": "é"}\n{"a": "2"}\n'


def test_format_value():
    assert format_value(None) == ""
    assert format_value(3.0) == "3"
    assert format_value(2 / 3) == "0.6667"
    assert format_value(True) == "true"
    assert format_value(datetime(2024, 1, 2)) == "2024-01-02"
    assert format_value(datetime(2024, 1, 2, 9, 30)) == "2024-01-02 09:30:00"
