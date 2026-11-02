"""
Streamlit UI for the file organizer / duplicate finder.
Run with:  streamlit run app.py

How Streamlit works (important for reading this file):
Streamlit runs this whole script from top to bottom every time the user
clicks a button or changes a setting. Normal variables are therefore reset on
every click. Anything that must survive between clicks (here, the scan
results) is kept in st.session_state, a dictionary that persists for the
browser tab. st.stop() ends the current run early, so nothing below it is drawn.

All the file logic lives in file_organizer.py; this file only handles the screen.
"""
from pathlib import Path

import pandas as pd
import streamlit as st

import file_organizer as fo

st.set_page_config(page_title="Folder Cleaner", page_icon="🗂️", layout="wide")
st.title("🗂️ Folder Cleaner")
st.caption("Organize files by type and find duplicates using SHA-256 hashing. "
           "Nothing is deleted: duplicates are moved to a _Duplicates folder.")

# ---- Settings ----
with st.sidebar:
    st.header("Settings")
    folder_text = st.text_input("Folder path", placeholder="e.g. C:\\Users\\me\\Downloads")
    recursive = st.checkbox("Include subfolders", value=False,
                            help="Files inside subfolders get pulled out into the type folders. "
                                 "Leave this off for folders that contain projects.")
    include_hidden = st.checkbox("Include hidden files (dotfiles)", value=False)
    organize = st.checkbox("Sort files into folders by type", value=True)
    move_dups = st.checkbox("Move duplicates to _Duplicates", value=True)
    dry_run = st.checkbox("Dry run (preview only)", value=True,
                          help="Shows what would happen without moving anything.")

# ---- Check the folder path ----
if not folder_text:
    st.info("Enter a folder path in the sidebar to begin.")
    st.stop()

# Remove surrounding spaces and quotes (Windows "Copy as path" adds quotes),
# and turn "~" into the home folder.
root = Path(folder_text.strip().strip('"')).expanduser()
if not root.is_dir():
    st.error(f"Not a folder: {root}")
    st.stop()
root = root.resolve()  # full absolute path, so comparisons between paths are reliable

# If the folder or scan settings changed since the last scan, throw the old
# results away. Otherwise the app would show (and could act on) files from a
# scan that no longer matches what's on screen.
settings = (str(root), recursive, include_hidden)
if st.session_state.get("settings") != settings:
    st.session_state.pop("scan", None)
    st.session_state["settings"] = settings

# ---- Buttons ----
# st.button returns True only during the run triggered by that click.
col1, col2 = st.columns(2)
if col1.button("🔍 Scan folder", type="primary"):
    with st.spinner("Scanning and hashing files..."):
        files = fo.scan_files(root, include_hidden, recursive)
        groups = fo.find_duplicates(files)
    # Saved so the results are still here after the next click (e.g. Apply).
    st.session_state["scan"] = {"files": files, "groups": groups}

if col2.button("↩️ Undo last run"):
    restored, errors = fo.undo_last(root)
    st.success(f"Restored {restored} file(s).")
    for e in errors:
        st.warning(e)
    st.session_state.pop("scan", None)  # files moved, so the old scan is out of date

scan = st.session_state.get("scan")
if not scan:
    st.stop()  # nothing scanned yet: show only the buttons

# ---- Summary ----
files, groups = scan["files"], scan["groups"]
# Every copy beyond the first is wasted space.
wasted = sum(g[0].stat().st_size * (len(g) - 1) for g in groups)

m1, m2, m3 = st.columns(3)
m1.metric("Files scanned", len(files))
m2.metric("Duplicate groups", len(groups))
m3.metric("Space used by duplicates", fo.human_size(wasted))

# ---- Breakdown by type ----
if files:
    counts = pd.Series([fo.category_for(f) for f in files]).value_counts()
    st.subheader("Files by type")
    st.bar_chart(counts)

# ---- Duplicate groups ----
if groups:
    st.subheader("Duplicates found")
    for i, g in enumerate(groups, 1):
        with st.expander(f"Group {i}: {g[0].name} ({len(g)} copies, "
                         f"{fo.human_size(g[0].stat().st_size)} each)"):
            for j, f in enumerate(g):
                label = "✅ keep (oldest)" if j == 0 else "➡️ duplicate"
                st.write(f"{label}: `{f.relative_to(root)}`")

# ---- Plan and run ----
# The plan is rebuilt on every run, so ticking "Sort files" or "Move duplicates"
# updates the preview straight away without rescanning.
plan = fo.plan_moves(root, files, groups, organize, move_dups)
st.subheader("Planned actions")
if not plan:
    st.success("Nothing to do: the folder is already organized.")
    st.stop()

st.dataframe(pd.DataFrame([{
    "From": str(p["source"].relative_to(root)),
    "To": str(p["destination"].relative_to(root)),
    "Reason": p["reason"],
} for p in plan]), width="stretch", hide_index=True)

if dry_run:
    st.info(f"Dry run: {len(plan)} move(s) shown above. "
            "Untick 'Dry run' in the sidebar to apply them.")
else:
    # The Apply button only exists when dry run is off, so files can't be
    # moved by accident.
    if st.button(f"Apply {len(plan)} move(s)", type="primary"):
        done, errors = fo.execute_moves(root, plan)
        st.success(f"Moved {len(done)} file(s). Use 'Undo last run' to reverse.")
        for e in errors:
            st.error(e)
        st.session_state.pop("scan", None)  # force a fresh scan before the next Apply
