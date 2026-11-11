import io

import pytest

from tablepeek.table import (
    TableError,
    decode,
    load,
    parse_delimiter,
    parse_text,
    sniff_delimiter,
)


def write(tmp_path, name, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_decode_plain_utf8():
    assert decode("café".encode("utf-8")) == ("café", "utf-8")


def test_decode_strips_utf8_bom():
    text, enc = decode(b"\xef\xbb\xbfname,age\n")
    assert text == "name,age\n"
    assert enc == "utf-8-sig"


def test_decode_utf16_bom():
    text, enc = decode("a\tb\n1\t2\n".encode("utf-16"))
    assert text == "a\tb\n1\t2\n"
    assert enc == "utf-16"


def test_decode_falls_back_to_cp1252():
    text, enc = decode("naïve,€5\n".encode("cp1252"))
    assert text == "naïve,€5\n"
    assert enc == "cp1252"


def test_decode_latin1_last_resort():
    # 0x81 is undefined in cp1252, and the bytes are not valid UTF-8.
    text, enc = decode(b"a\x81,b\n")
    assert enc == "latin-1"
    assert text.startswith("a")


def test_decode_explicit_encoding_errors():
    with pytest.raises(TableError, match="unknown encoding"):
        decode(b"x", "no-such-codec")
    with pytest.raises(TableError, match="cannot decode as utf-8"):
        decode(b"\xff\xfe\xfa", "utf-8")


@pytest.mark.parametrize(
    "text, expected",
    [
        ("a,b,c\n1,2,3\n", ","),
        ("a\tb\tc\n1\t2\t3\n", "\t"),
        ("a;b\n1,5;2\n3,25;4\n", ";"),
        ("a|b|c\n1|2|3\n", "|"),
        ('name,note\n"Smith; John","a; b; c"\n', ","),
    ],
)
def test_sniff_delimiter(text, expected):
    assert sniff_delimiter(text) == expected


def test_sniff_single_column_uses_preferred():
    assert sniff_delimiter("name\nAlice\nBob\n") == ","
    assert sniff_delimiter("name\nAlice\n", preferred="\t") == "\t"


def test_parse_delimiter_aliases():
    assert parse_delimiter("tab") == "\t"
    assert parse_delimiter("\\t") == "\t"
    assert parse_delimiter("semicolon") == ";"
    assert parse_delimiter("|") == "|"
    with pytest.raises(TableError):
        parse_delimiter("::")


def test_header_cleanup_blank_and_duplicate_names():
    t = parse_text("id,,id, name \n1,2,3,4\n", ",")
    assert t.columns == ["id", "col2", "id_2", "name"]


def test_ragged_rows_are_padded_and_trimmed():
    t = parse_text("a,b,c\n1,2\n1,2,3,4\n1,2,3,,\n", ",")
    assert t.rows == [["1", "2", ""], ["1", "2", "3"], ["1", "2", "3"]]
    assert t.short_rows == 1
    assert t.long_rows == 1  # trailing empty fields do not count


def test_quoted_fields_with_newlines_and_blank_lines():
    t = parse_text('a,b\n"line1\nline2",x\n\n3,y\n', ",")
    assert t.rows == [["line1\nline2", "x"], ["3", "y"]]


def test_no_header_names_columns():
    t = parse_text("1,2\n3,4,5\n", ",", header=False)
    assert t.columns == ["col1", "col2", "col3"]
    assert len(t.rows) == 2


def test_empty_file_is_an_error(tmp_path):
    with pytest.raises(TableError, match="empty"):
        load(write(tmp_path, "e.csv", b""))


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(TableError, match="no such file"):
        load(str(tmp_path / "nope.csv"))


def test_load_tsv_extension_prefers_tab(tmp_path):
    path = write(tmp_path, "x.tsv", b"only\nvalue\n")
    assert load(path).delimiter == "\t"


def test_load_bom_semicolon_crlf(tmp_path):
    data = "﻿nom;âge\r\nÉlodie;31\r\n".encode("utf-8")
    t = load(write(tmp_path, "fr.csv", data))
    assert t.columns == ["nom", "âge"]
    assert t.rows == [["Élodie", "31"]]
    assert t.delimiter == ";"
    assert t.encoding == "utf-8-sig"


def test_load_from_stdin_stream():
    t = load("-", stdin=io.BytesIO(b"x|y\n1|2\n"))
    assert t.source == "<stdin>"
    assert t.columns == ["x", "y"]


def test_resolve_columns():
    t = parse_text("Name,age,City\nA,1,B\n", ",")
    assert t.resolve("age") == 1
    assert t.resolve("city") == 2  # case-insensitive
    assert t.resolve("1") == 0  # 1-based number
    assert t.resolve_list("City, name") == [2, 0]
    with pytest.raises(TableError, match="unknown column 'zip'"):
        t.resolve("zip")


def test_normalize_decimal_comma():
    from tablepeek.table import normalize_decimal_comma as n

    assert n("1.234,5") == "1234.5"
    assert n("-2.480,00") == "-2480.00"
    assert n("39,9") == "39.9"
    assert n("1.050") == "1050"
    assert n("12") == "12"
    assert n("1.5") == "1.5"
    assert n("abc") == "abc"
    assert n("1,2,3") == "1,2,3"


def test_dates_detected_day_first():
    t = parse_text("d\n25/03/2024\n07/03/2024\n\n", ",")
    assert [r[0] for r in t.rows] == ["2024-03-25", "2024-03-07"]


def test_dates_detected_month_first_with_time():
    t = parse_text("d\n03/25/2024 10:30\n07/03/2024 08:05:09\n", ",")
    assert [r[0] for r in t.rows] == ["2024-03-25 10:30", "2024-07-03 08:05:09"]


def test_dates_ambiguous_need_dayfirst():
    text = "d\n07/03/2024\n05/04/2024\n"
    assert parse_text(text, ",").rows == [["07/03/2024"], ["05/04/2024"]]
    t = parse_text(text, ",", dayfirst=True)
    assert [r[0] for r in t.rows] == ["2024-03-07", "2024-04-05"]


def test_dates_conflicting_or_mixed_columns_untouched():
    conflict = "d\n25/03/2024\n03/25/2024\n"
    assert parse_text(conflict, ",", dayfirst=True).rows == [["25/03/2024"], ["03/25/2024"]]
    mixed = "d\n25/03/2024\nsoon\n"
    assert parse_text(mixed, ",", dayfirst=True).rows == [["25/03/2024"], ["soon"]]
    bad = "d\n31/02/2024\n"
    assert parse_text(bad, ",", dayfirst=True).rows == [["31/02/2024"]]


def test_parse_text_decimal_comma():
    t = parse_text("a;b\n1.234,5;x\n2,5;y\n", ";", decimal_comma=True)
    assert t.rows == [["1234.5", "x"], ["2.5", "y"]]
    t = parse_text("a;b\n1.234,5;x\n", ";")
    assert t.rows == [["1.234,5", "x"]]
