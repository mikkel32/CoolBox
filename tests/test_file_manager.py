from coolbox.utils import (
    copy_file,
    move_file,
    delete_file,
    list_files,
    write_text,
    read_text,
    read_lines,
    write_lines,
    read_bytes,
    write_bytes,
    atomic_write,
    atomic_write_bytes,
    read_json,
    write_json,
    ensure_dir,
    touch_file,
    copy_dir,
    move_dir,
    delete_dir,
)


def test_copy_move_delete(tmp_path):
    src = tmp_path / "coolbox.txt"
    write_text(src, "hello")
    dest = tmp_path / "dest.txt"
    copy_file(src, dest)
    assert dest.read_text() == "hello"

    new_loc = tmp_path / "moved.txt"
    move_file(dest, new_loc)
    assert not dest.exists()
    assert new_loc.read_text() == "hello"

    delete_file(new_loc)
    assert not new_loc.exists()

    # Directory operations
    src_dir = tmp_path / "src_dir"
    dest_dir = tmp_path / "dest_dir"
    src_dir.mkdir()
    (src_dir / "f.txt").write_text("x")
    copy_dir(src_dir, dest_dir)
    assert (dest_dir / "f.txt").exists()

    new_dir = tmp_path / "moved_dir"
    move_dir(dest_dir, new_dir)
    assert not dest_dir.exists()
    assert (new_dir / "f.txt").exists()

    delete_dir(new_dir)
    assert not new_dir.exists()


def test_list_files(tmp_path):
    for i in range(3):
        (tmp_path / f"f{i}.txt").write_text("x")
    files = list_files(tmp_path, "*.txt")
    assert len(files) == 3


def test_atomic_write_and_ensure_dir(tmp_path):
    dest = tmp_path / "a" / "b" / "c.txt"
    atomic_write(dest, "hello")
    assert dest.read_text() == "hello"
    dest_bin = tmp_path / "d.bin"
    atomic_write_bytes(dest_bin, b"\x00\x01")
    assert dest_bin.read_bytes() == b"\x00\x01"
    data = {"a": 1}
    json_path = tmp_path / "data.json"
    write_json(json_path, data)
    assert read_json(json_path) == data
    p = tmp_path / "newdir"
    ret = ensure_dir(p)
    assert ret.is_dir() and ret.exists()


def test_read_write_bytes(tmp_path):
    f = tmp_path / "data.bin"
    write_bytes(f, b"abc")
    assert read_bytes(f) == b"abc"


def test_touch_file(tmp_path):
    f = tmp_path / "dir" / "file.txt"
    touch_file(f)
    assert f.exists()


def test_read_write_lines(tmp_path):
    f = tmp_path / "lines.txt"
    write_lines(f, ["a", "b", "c"])
    assert read_lines(f) == ["a", "b", "c"]


def test_encoding_support(tmp_path):
    f = tmp_path / "text.txt"
    write_text(f, "héllo", encoding="latin1")
    assert read_text(f, encoding="latin1") == "héllo"

    lines_f = tmp_path / "lines_enc.txt"
    write_lines(lines_f, ["ü", "ä"], encoding="latin1")
    assert read_lines(lines_f, encoding="latin1") == ["ü", "ä"]

    atomic_path = tmp_path / "enc" / "atomic.txt"
    atomic_write(atomic_path, "ß", encoding="latin1")
    assert atomic_path.read_text(encoding="latin1") == "ß"
