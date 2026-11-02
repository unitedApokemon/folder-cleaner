"""
Core logic for the file organizer / duplicate finder.
Kept separate from the Streamlit UI so it can be tested on its own.
"""
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

DUPLICATES_DIR = "_Duplicates"     # where extra copies are moved (nothing is ever deleted)
LOG_FILE = "_organizer_log.json"   # record of every move, used by undo

# File extension -> folder name. Anything not listed goes to "Other".
CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".odt", ".rtf", ".md"},
    "Spreadsheets": {".xls", ".xlsx", ".csv", ".ods"},
    "Presentations": {".ppt", ".pptx", ".odp", ".key"},
    "Videos": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
    "Audio": {".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Code": {".py", ".js", ".html", ".css", ".java", ".cpp", ".c", ".ipynb", ".json"},
}
OTHER = "Other"

# Every folder this app creates. Scans skip these, otherwise files that were
# already organized would be picked up and moved again on the next run.
MANAGED_DIRS = set(CATEGORIES) | {OTHER, DUPLICATES_DIR}


def category_for(path: Path) -> str:
    """Folder name for a file, based on its extension (case-insensitive, so .JPG works)."""
    ext = path.suffix.lower()
    for name, exts in CATEGORIES.items():
        if ext in exts:
            return name
    return OTHER


def is_hidden(path: Path, root: Path) -> bool:
    """True if the file or any folder between root and it starts with a dot."""
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def scan_files(root: Path, include_hidden=False, recursive=True):
    """List files under root, skipping hidden files, symlinks and the app's own folders."""
    root = root.resolve()
    pattern = root.rglob("*") if recursive else root.glob("*")
    files = []
    for p in pattern:
        # Skip folders, and skip symlinks: moving a shortcut is confusing and
        # hashing one would count the same file twice.
        if not p.is_file() or p.is_symlink():
            continue
        rel = p.relative_to(root)
        # Skip the app's own folders and log files (including damaged-log backups).
        if rel.parts[0] in MANAGED_DIRS or p.name.startswith("_organizer_log"):
            continue
        if not include_hidden and is_hidden(p, root):
            continue
        files.append(p)
    return sorted(files)


def file_hash(path: Path, chunk_size=1 << 20) -> str:
    """
    SHA-256 fingerprint of a file's contents. Two files with the same hash have
    identical contents, whatever their names.
    Reads 1 MB at a time (1 << 20 bytes) so a 4 GB video doesn't need 4 GB of memory.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        # Keep reading until f.read returns b"" (end of file).
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def find_duplicates(files):
    """
    Group files with identical content.
    Step 1: group by size. Checking size is instant, while hashing reads the
            whole file, and files of different sizes can't be identical.
    Step 2: hash only the files that share a size with another file.
    Returns a list of groups; the first file in each group (oldest) is the one kept.
    """
    # Files can disappear or become unreadable between scanning and here
    # (e.g. cloud sync), so every file access is wrapped in try/except.
    by_size = {}
    for f in files:
        try:
            by_size.setdefault(f.stat().st_size, []).append(f)
        except OSError:
            pass  # file deleted or unreadable since the scan: skip it

    by_hash = {}
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        for f in same_size:
            try:
                by_hash.setdefault(file_hash(f), []).append(f)
            except OSError:
                pass  # unreadable file: skip rather than crash

    def age(p):
        """Last-modified time; a file that vanished sorts last."""
        try:
            return p.stat().st_mtime
        except OSError:
            return float("inf")

    groups = [g for g in by_hash.values() if len(g) > 1]
    for g in groups:
        # Oldest first, so the original is kept and later copies are moved.
        # The path is a tie-breaker so the result is the same on every run.
        g.sort(key=lambda p: (age(p), str(p)))
    return groups


def read_log(root: Path):
    """
    Read the undo log: a list of runs, each with the moves it made.
    If the file is damaged (e.g. edited by hand), it is renamed and kept rather
    than crashing. Crashing here used to happen *after* files were moved, which
    left that run with no record and no way to undo it.
    """
    log_path = root.resolve() / LOG_FILE
    if not log_path.exists():
        return []
    try:
        log = json.loads(log_path.read_text(encoding="utf-8"))
        if isinstance(log, list):
            return log
    except (OSError, ValueError):
        pass
    log_path.rename(log_path.with_name(f"_organizer_log_damaged_{datetime.now():%Y%m%d_%H%M%S}.json"))
    return []


def write_log(root: Path, log):
    """Save the undo log. ensure_ascii=False keeps non-English filenames readable."""
    (root.resolve() / LOG_FILE).write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def unique_destination(dest: Path, reserved: set) -> Path:
    """
    Avoid filename collisions: if report.pdf exists (or is already planned),
    use report (1).pdf, report (2).pdf, ...

    `reserved` holds destinations already given out in this plan. Checking the
    disk alone isn't enough: if two folders both contain notes.txt, neither
    destination exists yet while planning, so both would get Documents/notes.txt
    and the second move would overwrite the first.
    """
    candidate, n = dest, 1
    while candidate.exists() or candidate in reserved:
        candidate = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        n += 1
    reserved.add(candidate)
    return candidate


def plan_moves(root: Path, files, duplicate_groups, organize=True, move_duplicates=True):
    """
    Build the list of moves without touching anything (this is what dry run shows).
    Each move is {"source", "destination", "reason"}.
    Planning and moving are separate functions so the preview and the real run
    are guaranteed to do the same thing.
    """
    root = root.resolve()
    reserved, plan = set(), []
    dup_set = set()  # extra copies, so they aren't also sorted by type below

    # Duplicates first: every copy except the first (oldest) goes to _Duplicates.
    if move_duplicates:
        for group in duplicate_groups:
            original = group[0]
            for dup in group[1:]:
                dup_set.add(dup)
                dest = unique_destination(root / DUPLICATES_DIR / dup.name, reserved)
                plan.append({"source": dup, "destination": dest,
                             "reason": f"duplicate of {original.relative_to(root)}"})
    # Then everything else goes into its type folder.
    if organize:
        for f in files:
            if f in dup_set:
                continue
            dest = root / category_for(f) / f.name
            if dest == f:  # already in the right place
                continue
            plan.append({"source": f, "destination": unique_destination(dest, reserved),
                         "reason": f"type: {category_for(f)}"})
    return plan


def execute_moves(root: Path, plan):
    """
    Carry out a plan and record each move in the log so it can be undone.
    Returns (moves that succeeded, error messages). One failed move (file in
    use, permission denied) is reported and skipped; it doesn't stop the rest.
    """
    done, errors = [], []
    for step in plan:
        src, dst = Path(step["source"]), Path(step["destination"])
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            # The user may have added a file between preview and Apply:
            # pick a fresh name rather than overwrite it.
            if dst.exists():
                dst = unique_destination(dst, set())
            shutil.move(str(src), str(dst))
            done.append({"source": str(src), "destination": str(dst)})
        except OSError as e:
            errors.append(f"{src}: {e}")

    # Remove subfolders this run left empty (undo recreates them if needed).
    # Deepest folders first, so a/b is removed before we try a. Then walk up
    # towards root, stopping at the first folder that still has something in it.
    root_r = root.resolve()
    emptied = {Path(m["source"]).parent for m in done}
    for folder in sorted(emptied, key=lambda p: len(p.parts), reverse=True):
        while folder != root_r and root_r in folder.parents:
            try:
                folder.rmdir()  # only succeeds if the folder is empty
            except OSError:
                break
            folder = folder.parent

    if done:
        log = read_log(root)
        log.append({"time": datetime.now().isoformat(timespec="seconds"), "moves": done})
        write_log(root, log)
    return done, errors


def undo_last(root: Path):
    """
    Move files from the most recent run back to where they were.
    Calling it again undoes the run before that, and so on.
    """
    log = read_log(root)
    if not log:
        return 0, ["Nothing to undo."]
    last = log.pop()
    restored, errors = 0, []
    # Undo in reverse order, the way you'd retrace your steps.
    for move in reversed(last["moves"]):
        # Swapped on purpose: we move from where the file went back to where it came from.
        src, dst = Path(move["destination"]), Path(move["source"])
        try:
            # Never overwrite: a new file may have been put in the old spot since.
            if dst.exists():
                errors.append(f"{dst} already exists, left {src} where it is")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            restored += 1
        except OSError as e:
            errors.append(f"{src}: {e}")
    write_log(root, log)
    # Remove the app's folders if undo emptied them.
    for d in MANAGED_DIRS:
        p = root.resolve() / d
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    return restored, errors


def human_size(n: int) -> str:
    """Turn a byte count into something readable, e.g. 1536 -> '1.5 KB'."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
