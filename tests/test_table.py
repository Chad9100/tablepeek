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
