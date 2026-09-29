import os

from inside_ai.tail import FileTail


def test_partial_line_is_held_until_newline(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_bytes(b'{"a":1}\n{"b":')
    t = FileTail(f)
    chunks, _ = t.poll()
    assert [c.line for c in chunks] == [b'{"a":1}']
    with f.open("ab") as fh:
        fh.write(b"2}\n")
    chunks, _ = t.poll()
    assert [c.line for c in chunks] == [b'{"b":2}']
    assert t.poll() == ([], False)


def test_start_at_end_skips_existing_but_keeps_unfinished_line(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_bytes(b'{"old":1}\n{"new":')
    t = FileTail.at_end(f)
    with f.open("ab") as fh:
        fh.write(b"1}\n")
    chunks, _ = t.poll()
    assert [c.line for c in chunks] == [b'{"new":1}']


def test_truncate_and_replace_trigger_reset(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_bytes(b'{"a":1}\n{"b":2}\n')
    t = FileTail(f)
    t.poll()
    f.write_bytes(b'{"c":3}\n')  # 더 짧게 다시 씀
    chunks, reset = t.poll()
    assert reset and [c.line for c in chunks] == [b'{"c":3}']

    g = tmp_path / "b.jsonl"
    g.write_bytes(b'{"c":3}\n{"d":4}\n')
    os.replace(g, f)  # inode 교체
    chunks, reset = t.poll()
    assert reset and len(chunks) == 2


def test_missing_file_is_quiet(tmp_path):
    t = FileTail.at_end(tmp_path / "none.jsonl")
    assert t.poll() == ([], False)


def test_bounded_reads_resume_and_long_lines(tmp_path):
    f = tmp_path / "a.jsonl"
    long_line = b'{"x":"' + b"y" * 50 + b'"}'
    f.write_bytes(b'{"a":1}\n' + long_line + b"\n" + b'{"b":2}\n')
    t = FileTail(f, max_read=10)
    got = []
    for _ in range(10):
        chunks, _ = t.poll()
        got += [c.line for c in chunks]
    assert got == [b'{"a":1}', long_line, b'{"b":2}']
