"""Tests for the core logic. Run with:  pytest"""
import os
import time

import file_organizer as fo


def files_in(d):
    return sorted(str(p.relative_to(d)).replace("\\", "/") for p in d.rglob("*") if p.is_file())


def organize(d, **scan_kwargs):
    files = fo.scan_files(d, **scan_kwargs)
    return fo.execute_moves(d, fo.plan_moves(d, files, fo.find_duplicates(files)))


def test_duplicates_matched_by_content_not_name(tmp_path):
    (tmp_path / "photo.jpg").write_bytes(b"A" * 5000)
    (tmp_path / "copy.jpg").write_bytes(b"A" * 5000)
    (tmp_path / "other.jpg").write_bytes(b"B" * 5000)  # same size, different content
    old = time.time() - 1000
    os.utime(tmp_path / "photo.jpg", (old, old))
    groups = fo.find_duplicates(fo.scan_files(tmp_path))
    assert len(groups) == 1
    assert [p.name for p in groups[0]] == ["photo.jpg", "copy.jpg"]  # oldest kept first


def test_dotfiles_skipped_unless_asked(tmp_path):
    (tmp_path / ".DS_Store").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / "a.txt").write_text("x")
    assert [p.name for p in fo.scan_files(tmp_path)] == ["a.txt"]
    assert len(fo.scan_files(tmp_path, include_hidden=True)) == 3


def test_subfolders_only_when_recursive(tmp_path):
    (tmp_path / "top.txt").write_text("1")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.txt").write_text("2")
    assert [p.name for p in fo.scan_files(tmp_path, recursive=False)] == ["top.txt"]
    assert len(fo.scan_files(tmp_path, recursive=True)) == 2


def test_filename_collisions_never_overwrite(tmp_path):
    for s in ("s1", "s2"):
        (tmp_path / s).mkdir()
        (tmp_path / s / "notes.txt").write_text(s)
    (tmp_path / "Documents").mkdir()
    (tmp_path / "Documents" / "notes.txt").write_text("existing")
    organize(tmp_path)
    docs = tmp_path / "Documents"
    assert sorted(os.listdir(docs)) == ["notes (1).txt", "notes (2).txt", "notes.txt"]
    assert sorted(p.read_text() for p in docs.iterdir()) == ["existing", "s1", "s2"]


def test_planning_is_a_dry_run(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "b.txt").write_text("1")
    before = files_in(tmp_path)
    files = fo.scan_files(tmp_path)
    plan = fo.plan_moves(tmp_path, files, fo.find_duplicates(files))
    assert len(plan) == 2
    assert files_in(tmp_path) == before


def test_organized_files_are_not_rescanned(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "b.txt").write_text("1")
    organize(tmp_path)
    assert fo.scan_files(tmp_path) == []


def test_undo_restores_everything(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.txt").write_text("1")
    (tmp_path / "y.mp3").write_bytes(b"2")
    (tmp_path / "z.txt").write_text("1")
    before = {p: (tmp_path / p).read_bytes() for p in files_in(tmp_path)}
    organize(tmp_path, recursive=True)
    assert not (tmp_path / "sub").exists()  # emptied folder cleaned up
    restored, errors = fo.undo_last(tmp_path)
    assert restored == 3 and not errors
    after = {p: (tmp_path / p).read_bytes() for p in files_in(tmp_path) if p != fo.LOG_FILE}
    assert after == before
    assert not any((tmp_path / c).exists() for c in fo.MANAGED_DIRS)


def test_undo_never_overwrites(tmp_path):
    (tmp_path / "r.txt").write_text("old")
    organize(tmp_path)
    (tmp_path / "r.txt").write_text("new")
    restored, errors = fo.undo_last(tmp_path)
    assert restored == 0 and errors
    assert (tmp_path / "r.txt").read_text() == "new"


def test_undo_with_nothing_to_undo(tmp_path):
    restored, errors = fo.undo_last(tmp_path)
    assert restored == 0 and errors


def test_damaged_log_does_not_lose_undo(tmp_path):
    (tmp_path / fo.LOG_FILE).write_text("{not json")
    (tmp_path / "m.txt").write_text("1")
    organize(tmp_path)
    assert fo.undo_last(tmp_path)[0] == 1
    assert (tmp_path / "m.txt").exists()
    assert any(n.startswith("_organizer_log_damaged") for n in os.listdir(tmp_path))


def test_file_deleted_after_scan(tmp_path):
    (tmp_path / "p.txt").write_text("w")
    (tmp_path / "q.txt").write_text("w")
    files = fo.scan_files(tmp_path)
    (tmp_path / "q.txt").unlink()
    assert fo.find_duplicates(files) == []
    plan = fo.plan_moves(tmp_path, files, [])
    done, errors = fo.execute_moves(tmp_path, plan)
    assert len(done) == 1 and len(errors) == 1


def test_unusual_filenames(tmp_path):
    names = {"my file.TXT": "Documents", "résumé.pdf": "Documents", "Makefile": "Other",
             "archive.tar.gz": "Archives", "विद्यार्थी.png": "Images"}
    for n in names:
        (tmp_path / n).write_text(n)
    plan = fo.plan_moves(tmp_path, fo.scan_files(tmp_path), [])
    assert {p["source"].name: p["destination"].parent.name for p in plan} == names
    done, errors = fo.execute_moves(tmp_path, plan)
    assert len(done) == 5 and not errors


def test_human_size():
    assert [fo.human_size(n) for n in (0, 1023, 1024, 1536, 5 * 1024**3)] == \
        ["0 B", "1023 B", "1.0 KB", "1.5 KB", "5.0 GB"]
