from recall_guard.sniff import sniff

HEADER = "ticket_id,created,title,description,customData"
TABLE = "a,b,c\n1,2,3\n4,5,6\n7,8,9\n"


def test_header_fingerprint_catches_renamed_file(tmp_path):
    f = tmp_path / "export.txt"
    f.write_text(HEADER + "\n1,2,3,4,5\n", encoding="utf-8")
    assert sniff(f, HEADER) == "header-fingerprint"


def test_header_fingerprint_beats_code_suffix(tmp_path):
    f = tmp_path / "schema.json"
    f.write_text(f'{{"cols": "{HEADER}"}}', encoding="utf-8")
    assert sniff(f, HEADER) == "header-fingerprint"


def test_delimited_table_caught_without_header(tmp_path):
    f = tmp_path / "dump.dat"
    f.write_text(TABLE, encoding="utf-8")
    assert sniff(f, None) == "delimited-table"


def test_semicolon_and_tab_tables(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text(TABLE.replace(",", ";"), encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text(TABLE.replace(",", "\t"), encoding="utf-8")
    assert sniff(a, None) == "delimited-table"
    assert sniff(b, None) == "delimited-table"


def test_code_and_markup_are_not_tables(tmp_path):
    f = tmp_path / "t.py"
    f.write_text(TABLE, encoding="utf-8")
    assert sniff(f, None) is None


def test_prose_and_short_files_pass(tmp_path):
    prose = tmp_path / "notes.txt"
    prose.write_text("hello world, this is fine\nsecond line\nthird line\n", encoding="utf-8")
    short = tmp_path / "short.txt"
    short.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    assert sniff(prose, None) is None
    assert sniff(short, None) is None


def test_archives_are_denied(tmp_path):
    f = tmp_path / "bundle.zip"
    f.write_bytes(b"PK\x03\x04 not really")
    assert sniff(f, None) == "archive"


def test_two_column_tables_need_five_lines(tmp_path):
    five = tmp_path / "two.txt"
    five.write_text("a,b\n1,2\n3,4\n5,6\n7,8\n", encoding="utf-8")
    four = tmp_path / "two4.txt"
    four.write_text("a,b\n1,2\n3,4\n5,6\n", encoding="utf-8")
    assert sniff(five, None) == "delimited-table"
    assert sniff(four, None) is None


def test_magic_bytes_catch_renamed_archives_and_parquet(tmp_path):
    for magic in (b"PK\x03\x04", b"\x1f\x8b", b"BZh9", b"\xfd7zXZ\x00", b"7z\xbc\xaf\x27\x1c"):
        f = tmp_path / "renamed.dat"
        f.write_bytes(magic + b"\x00\x01\x02" * 50)
        assert sniff(f, None) == "archive", magic
    blob = tmp_path / "notes.txt"
    blob.write_bytes(b"PAR1" + b"\x00\x01\x02" * 50)
    assert sniff(blob, None) == "binary-table"


def test_binary_without_archive_suffix_passes(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\x01\x02" * 100)
    assert sniff(f, None) is None


def test_utf16_export_with_header_is_caught(tmp_path):
    f = tmp_path / "export.dat"
    f.write_bytes((HEADER + "\n1,2,3,4,5\n").encode("utf-16"))  # BOM + UTF-16LE
    assert sniff(f, HEADER) == "header-fingerprint"
    g = tmp_path / "export_be.dat"
    g.write_bytes(b"\xfe\xff" + (HEADER + "\n1,2,3,4,5\n").encode("utf-16-be"))
    assert sniff(g, HEADER) == "header-fingerprint"


def test_utf16_delimited_table_without_bom_is_caught(tmp_path):
    f = tmp_path / "dump.dat"
    f.write_bytes(TABLE.encode("utf-16-le"))
    assert sniff(f, None) == "delimited-table"
    g = tmp_path / "dump_be.dat"
    g.write_bytes(TABLE.encode("utf-16-be"))
    assert sniff(g, None) == "delimited-table"


def test_utf16_bom_prose_passes(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_bytes("hello world\nsecond line\nthird line\n".encode("utf-16"))
    assert sniff(f, None) is None


def test_complete_twentieth_line_is_not_dropped(tmp_path):
    # exactly 20 complete lines, file not truncated: all 20 count (a 5-line 2-col table here)
    f = tmp_path / "t.dat"
    f.write_text("a,b\n" * 20, encoding="utf-8")
    assert sniff(f, None) == "delimited-table"
    short = tmp_path / "s.dat"
    short.write_text("a,b\n" * 4, encoding="utf-8")
    assert sniff(short, None) is None  # four complete 2-col lines stay below the bar


def test_truncated_read_keeps_the_complete_twentieth_line(tmp_path):
    f = tmp_path / "mixed.dat"
    # 19 table lines, then a complete prose line, then a long tail that forces truncation
    f.write_text("a,b,c\n" * 19 + "just prose\n" + "z" * 9000, encoding="utf-8")
    assert sniff(f, None) is None


def test_large_extensionless_text_is_denied(tmp_path):
    f = tmp_path / "dump"
    f.write_text("word " * 300_000, encoding="utf-8")
    assert sniff(f, None) == "large-text"
    assert sniff(f, None, large_check=False) is None


def test_missing_file_is_none(tmp_path):
    assert sniff(tmp_path / "nope", HEADER) is None
