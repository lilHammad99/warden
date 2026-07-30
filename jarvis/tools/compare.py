"""Compare two text files for Jarvis -- "what changed between these two files?"

The file family can already LOCATE a file (``find_files`` / ``search_files`` /
``recent_files``), REARRANGE it (``move_file`` / ``copy_file`` / ...), back it up
and restore it (``zip_files`` / ``unzip_files``), remove it (``recycle_file``),
report a whole folder's usage (``folder_size``), find files stored twice
(``find_duplicates``) and report the exact facts about one file (``file_info``).
``find_duplicates`` can tell the user two files are byte-for-byte IDENTICAL, but
nothing could say what is DIFFERENT between two specific files -- and an 8B model
cannot eyeball two documents and reliably report the changes.

``compare_files`` closes that gap: it reports whether two text files are
identical or different and, when they differ, exactly how many lines were added
and removed plus a short, bounded preview of the changed lines. It answers "did
this file change", "what's different between my draft and the final", "compare
config.yaml and config.backup", "are these two notes the same". It is read-only
and the natural companion to ``find_files`` (locate the two files, then diff
them) and ``file_info`` (facts about one file, differences between two).

Safety model (strict, because an 8B local model WILL eventually pass junk, the
wrong type, or point at the wrong thing):

- **Rooted in the user's home only.** BOTH paths are resolved and REJECTED unless
  they live inside the user's home directory (shared with ``find_files`` /
  ``organize``), including a ``..``-escape, so the model can never read a file
  under ``C:\\Windows`` or outside the user's own folders.
- **Text only.** A binary file (by extension OR a NUL-byte sniff) is refused
  rather than dumping a meaningless byte diff; a folder is refused too.
- **Bounded.** Each file is capped in size before it is read, the number of lines
  compared is capped, and the changed-line preview is capped in both the number
  of lines shown and the length of each line -- a giant or hostile file can't
  exhaust memory or flood the agent's context.
- **Pure ASCII out + read-only + never raises.** Nothing here writes, moves or
  deletes anything; wrong-type args are coerced, and any unexpected error comes
  back as a friendly, single-line ASCII string the model can read and recover
  from.
"""

import difflib
from pathlib import Path

from .find import _coerce
from .fileinfo import _is_binary
from .organize import _ascii, _first_str, _resolve_under_home
from .registry import tool

MAX_PATH_LEN = 400                    # a path, not an essay
MAX_FILE_BYTES = 5 * 1024 * 1024      # refuse to compare a file bigger than this (5 MB)
MAX_LINES = 200_000                   # most lines compared per file
MAX_PREVIEW_LINES = 40                # changed lines shown in the preview
MAX_LINE_LEN = 200                    # each previewed line truncated to this


def _read_text(p: Path):
    """Read a bounded number of lines of text from a file. Returns
    (lines, byte_count, truncated) or (None, 0, False) if unreadable. Never
    raises. Lines are decoded leniently; output is ASCII-forced later."""
    try:
        with open(p, "rb") as f:
            data = f.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None, 0, False
    over = len(data) > MAX_FILE_BYTES
    if over:
        data = data[:MAX_FILE_BYTES]
    text = data.decode("utf-8", "replace")
    lines = text.splitlines()
    truncated = over
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        truncated = True
    return lines, len(data), truncated


def _resolve_text_file(raw: str, which: str):
    """Resolve one path, confirm it is a text file inside home, and read it.
    Returns (lines, truncated, "") on success or (None, False, error). The
    ``which`` label ('first'/'second') is only used in messages."""
    p, err = _resolve_under_home(_coerce(raw, MAX_PATH_LEN))
    if p is None:
        return None, False, (err or f"Error: the {which} file path isn't valid, sir.")
    if not p.exists():
        return None, False, f"Error: I can't find the {which} file '{_ascii(str(p))}', sir."
    if p.is_dir():
        return None, False, (f"Error: the {which} one, '{_ascii(p.name)}', is a folder, "
                             "sir; give me two files to compare.")
    if not p.is_file():
        return None, False, f"Error: the {which} one, '{_ascii(p.name)}', isn't an ordinary file, sir."
    if _is_binary(p, p.suffix.lower()):
        return None, False, (f"Error: the {which} file '{_ascii(p.name)}' looks binary, sir; "
                             "I can only compare text files.")
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            return None, False, (f"Error: the {which} file '{_ascii(p.name)}' is too big to "
                                 f"compare (over {MAX_FILE_BYTES // (1024 * 1024)} MB), sir.")
    except OSError:
        pass
    lines, _n, truncated = _read_text(p)
    if lines is None:
        return None, False, f"Error: I couldn't read the {which} file, sir."
    return (p, lines, truncated), False, ""


def _diff_lines(a_lines, b_lines):
    """(added, removed, preview_lines) from a unified diff of two line lists.
    The preview is bounded in count and each line in length; pure ASCII."""
    added = removed = 0
    preview = []
    more = False
    for line in difflib.unified_diff(a_lines, b_lines, lineterm=""):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
        else:
            continue
        if len(preview) < MAX_PREVIEW_LINES:
            sign, body = line[0], line[1:]
            body = _ascii(body)
            if len(body) > MAX_LINE_LEN:
                body = body[:MAX_LINE_LEN] + "..."
            preview.append(f"  {sign} {body}")
        else:
            more = True
    return added, removed, preview, more


@tool(
    "compare_files",
    "Compare two TEXT files and report whether they are identical or different, "
    "and if different how many lines were added and removed plus a short preview "
    "of the changed lines. Use this when the user wants to know what changed "
    "between two files ('did this file change', 'what's different between my "
    "draft and the final', 'compare config.yaml and config.backup', 'are these "
    "two notes the same'). This is read-only -- it never changes anything. Give "
    "the two file paths (locate them first with find_files if you don't know "
    "them). Text files only, and only the user's own folders.",
    {
        "type": "object",
        "properties": {
            "file1": {
                "type": "string",
                "description": "The first file, e.g. 'Documents/draft.txt'.",
            },
            "file2": {
                "type": "string",
                "description": "The second file, e.g. 'Documents/final.txt'.",
            },
        },
        "required": ["file1", "file2"],
    },
)
def compare_files(file1: str = "", file2: str = "", **extra) -> str:
    a_raw = _first_str(file1, extra.get("a"), extra.get("first"), extra.get("old"),
                       extra.get("original"), extra.get("left"), extra.get("path1"),
                       extra.get("source"), extra.get("before"))
    b_raw = _first_str(file2, extra.get("b"), extra.get("second"), extra.get("new"),
                       extra.get("updated"), extra.get("right"), extra.get("path2"),
                       extra.get("target"), extra.get("dest"), extra.get("after"))
    if not a_raw or not b_raw:
        return ("Error: give me TWO files to compare, sir -- a first and a second "
                "one.")

    a_res, _u, a_err = _resolve_text_file(a_raw, "first")
    if a_res is None:
        return a_err
    b_res, _u2, b_err = _resolve_text_file(b_raw, "second")
    if b_res is None:
        return b_err

    a_path, a_lines, a_trunc = a_res
    b_path, b_lines, b_trunc = b_res
    a_name, b_name = _ascii(a_path.name), _ascii(b_path.name)

    if a_path == b_path:
        return (f"Those are the same file, sir ('{a_name}'), so of course they are "
                "identical.")

    header = f"Comparing '{a_name}' and '{b_name}':"
    if a_lines == b_lines:
        return f"{header}\nThey are identical, sir."

    added, removed, preview, more = _diff_lines(a_lines, b_lines)
    summary = (f"They are different, sir. {added} line{'s' if added != 1 else ''} "
               f"added, {removed} line{'s' if removed != 1 else ''} removed "
               f"(going from '{a_name}' to '{b_name}').")
    out = [header, summary]
    if preview:
        out.append("Changes (- from the first, + from the second):")
        out.extend(preview)
        if more:
            out.append("  ... (more changes not shown)")
    if a_trunc or b_trunc:
        out.append("Note: one or both files were large, so I compared the first "
                   "part only, sir.")
    return "\n".join(out)
