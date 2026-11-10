from datetime import datetime

import pytest

from tablepeek.infer import convert, infer_column, is_null, value_kind


@pytest.mark.parametrize(
    "value, kind",
    [
        ("42", "int"),
        ("-7", "int"),
        ("007", "text"),
        ("3.14", "float"),
        ("1e5", "float"),
        (".5", "float"),
        ("TRUE", "bool"),
        ("no", "bool"),
        ("2024-02-29", "date"),
        ("2024/3/7", "date"),
        ("2024-01-05T09:30:00", "date"),
        ("2024-13-01", "text"),
        ("Paris", "text"),
        ("", "null"),
        (" N/A ", "null"),
        ("null", "null"),
    ],
)
def test_value_kind(value, kind):
    assert value_kind(value) == kind


def test_infer_column_rules():
    assert infer_column(["1", "2", ""]) == "int"
    assert infer_column(["1", "2.5"]) == "float"
    assert infer_column(["yes", "no", "NA"]) == "bool"
    assert infer_column(["2024-01-01", "2024-01-02 10:00"]) == "date"
    assert infer_column(["1", "yes"]) == "text"
    assert infer_column(["", "NA"]) == "text"
    assert infer_column([]) == "text"


def test_convert_values():
    assert convert(" 12 ", "int") == 12
    assert convert("2", "float") == 2.0
    assert convert("Yes", "bool") is True
    assert convert("2024-01-05", "date") == datetime(2024, 1, 5)
    assert convert("NA", "int") is None
    assert convert(" keep ", "text") == " keep "
    with pytest.raises(ValueError):
        convert("abc", "float")


def test_is_null():
    assert is_null("  ")
    assert is_null("NaN")
    assert not is_null("0")
