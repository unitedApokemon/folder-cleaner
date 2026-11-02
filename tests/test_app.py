"""Clicks through the Streamlit app with Streamlit's built-in test runner."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def button(at, text):
    return next(b for b in at.button if text in b.label)


def checkbox(at, text):
    return next(c for c in at.sidebar.checkbox if text in c.label)


def test_full_flow(tmp_path):
    (tmp_path / "essay.docx").write_bytes(b"E" * 100)
    (tmp_path / "essay_final.docx").write_bytes(b"E" * 100)
    (tmp_path / "pic.png").write_bytes(b"P")
    (tmp_path / "song.mp3").write_bytes(b"S")
    before = sorted(p.name for p in tmp_path.iterdir())

    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    at.sidebar.text_input[0].input(f'"{tmp_path}"').run()  # quoted, like Windows "Copy as path"
    button(at, "Scan").click().run()
    assert {m.label: m.value for m in at.metric}["Duplicate groups"] == "1"
    assert len(at.dataframe[0].value) == 4
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # dry run moved nothing

    checkbox(at, "Dry run").uncheck().run()
    button(at, "Apply").click().run()
    assert not at.exception
    assert (tmp_path / "_Duplicates" / "essay_final.docx").exists()
    assert (tmp_path / "Images" / "pic.png").exists()

    button(at, "Undo").click().run()
    assert not at.exception
    assert sorted(p.name for p in tmp_path.iterdir() if not p.name.startswith("_organizer_log")) == before


def test_bad_path_shows_error():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.text_input[0].input("/no/such/folder").run()
    assert any("Not a folder" in e.value for e in at.error)
