from src.utils import (
    copy_file,
    move_file,
    delete_file,
    list_files,
    write_text,
    copy_dir,
    move_dir,
    delete_dir,
)


def test_copy_move_delete(tmp_path):
    src = tmp_path / "src.txt"
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
