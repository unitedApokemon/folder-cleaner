# Folder Cleaner

A Streamlit app that organizes a messy folder by file type and finds duplicate files using SHA-256 hashing.

## Features
- **Sort by type** into Images, Documents, Spreadsheets, Presentations, Videos, Audio, Archives, Code, Other
- **Duplicate detection**: groups files by size first, then hashes only the candidates, so it stays fast
- **Dry-run mode** (on by default): preview every move before anything happens
- **Filename collisions** handled: `report.pdf` becomes `report (1).pdf` instead of overwriting
- **Dotfiles** (e.g. `.gitignore`, `.DS_Store`) skipped unless you opt in
- **No repeat scanning**: the app's own output folders are excluded from later scans
- **Nothing deleted**: duplicates go to `_Duplicates`; every run is logged and can be undone
- **Subfolders off by default**: turning them on pulls nested files out into the type folders, which would break project folders

## Run it
Needs Python 3.10 or newer.
```
pip install -r requirements.txt
streamlit run app.py
```
Paste a folder path into the sidebar (on Windows, "Copy as path" with quotes works). Try it on a copy of a folder first.

## Tests
```
pip install -r requirements-dev.txt
pytest
```

## How it works
1. `scan_files` lists files, skipping hidden files, symlinks and the app's own folders.
2. `find_duplicates` groups files by size, then by SHA-256 hash. Only same-size files are hashed.
3. `plan_moves` builds the list of moves without touching anything. This is what dry run shows.
4. `execute_moves` moves the files and writes `_organizer_log.json`, which `undo_last` uses to reverse the run.

## Project files
- `file_organizer.py`: scanning, hashing, planning, moving and undo
- `app.py`: the Streamlit interface
- `tests/`: automated tests for the logic and the interface

## How this was built
I built this to clean up my own messy folders, which were full of duplicate
files. I used Python and LLMs as coding tools: the AI helped write and debug
the code, and I tested it, worked through how each part works, and learned
from the problems along the way.

Some of the problems and how they were solved:
- **Files being overwritten:** two files called `notes.txt` from different
  folders were both sent to `Documents/notes.txt`. The app now keeps track of
  names it has already used and renames the second one to `notes (1).txt`.
- **Files scanned twice:** after organizing, the next scan picked up files in
  the new folders and tried to move them again. The app now skips its own folders.
- **Hidden files:** system files like `.DS_Store` were being moved around.
  They're now skipped unless you choose to include them.
- **Losing the undo history:** if the log file got damaged, the app moved files
  and then crashed before recording them. It now keeps the damaged log aside
  and starts a fresh one.

Next I'd like to:
- Sort duplicates by file type inside the `_Duplicates` folder
- Let the user choose whether duplicates are moved to a folder or deleted
- Flag files that haven't been modified in over 6 months, so the user can decide
  whether to keep, archive, or delete them
