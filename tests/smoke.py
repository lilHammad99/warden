"""Smoke tests: run with  .venv\\Scripts\\python -m tests.smoke [section]
Sections: imports, tools, memory, shell, find, search, recent, organize,
movefolder, copyfolder, makefolder, disk, document, explorer, archive, extract, recycle, clipboard, tasks, calc,
dates, convert, textstats, spreadsheet, jsondata, reminders, dispatch, agent, camera, vision, tts, hud, watch,
e2e, all
(default: safe set)
"""

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

PASS, FAIL = "  [PASS]", "  [FAIL]"
failures = []


def check(name, fn):
    try:
        out = fn()
        print(f"{PASS} {name}" + (f" -> {str(out)[:120]}" if out else ""))
    except Exception as e:
        failures.append(name)
        print(f"{FAIL} {name}: {e}")


def t_imports():
    def _all():
        from jarvis import agent, app, config  # noqa
        from jarvis.tools import apps, archive, browser, calc, camera, clipboard, convert, dates, disk, document, explorer, extract, files, find, jsondata, memory, organize, recent, recycle, registry, reminders, search, shell, spreadsheet, system, tasks, textstats, web  # noqa
        from jarvis.vision import cameras, describe, watcher  # noqa
        from jarvis.voice import loop, stt, tts, wake  # noqa
        return "all modules import"
    check("imports", _all)


def t_tools():
    from jarvis.tools import files, registry, system
    from jarvis.tools import apps, web, camera  # noqa: F401  (register)
    check("registry has tools", lambda: f"{len(registry.specs())} tools")
    check("get_time", lambda: registry.dispatch("get_time", {}))
    check("system_info", lambda: registry.dispatch("system_info", {}))
    import tempfile, os
    tmp = os.path.join(tempfile.gettempdir(), "jarvis_smoke.txt")
    check("write_file", lambda: registry.dispatch("write_file", {"path": tmp, "content": "hello"}))
    check("read_file", lambda: registry.dispatch("read_file", {"path": tmp}))


def t_memory():
    """Exercises long-term memory + its defenses against 8B hallucinations.
    No model needed, so it lives in the safe set."""
    from jarvis.tools import memory as mem
    from jarvis.tools import registry

    # isolate: use a temp store so we never touch the user's real memory
    import tempfile, os, pathlib
    mem._STORE = pathlib.Path(tempfile.gettempdir()) / "jarvis_mem_smoke.json"
    for p in (mem._STORE, mem._STORE.with_name("memory.corrupt.json")):
        if p.exists():
            os.remove(p)

    def happy_path():
        assert "Remembered" in registry.dispatch("remember", {"fact": "The user's name is the user"})
        assert "the user" in registry.dispatch("recall", {"query": "name"})
        assert mem.count() == 1
        # remember/recall show up in the injected preamble
        assert "the user" in mem.memory_preamble()
        return "remember/recall/preamble ok"
    check("memory happy path", happy_path)

    def dedup():
        registry.dispatch("remember", {"fact": "The user's name is the user"})
        return f"count still {mem.count()} (deduped)" if mem.count() == 1 \
            else (_ for _ in ()).throw(AssertionError("duplicate stored"))
    check("memory dedup", dedup)

    def hallucination_guards():
        # empty / whitespace / wrong-type args must NOT crash or store junk
        assert "Error" in registry.dispatch("remember", {"fact": "   "})
        assert "Error" in registry.dispatch("remember", {"fact": ""})
        assert registry.dispatch("remember", {}).startswith(("Error", "Remembered", "Already"))
        assert "Error" in registry.dispatch("forget", {"query": ""})
        # over-long "fact" (essay dump) is truncated, not rejected or unbounded
        long = registry.dispatch("remember", {"fact": "x" * 5000})
        assert "shortened" in long
        return f"guards held, count={mem.count()}"
    check("memory hallucination guards", hallucination_guards)

    def forget_flow():
        before = mem.count()
        assert "Forgotten" in registry.dispatch("forget", {"query": "the user"})
        assert mem.count() == before - 1
        assert "Nothing in memory matches" in registry.dispatch("forget", {"query": "zzzz"})
        return "forget ok"
    check("memory forget", forget_flow)

    def corrupt_store_recovers():
        mem._STORE.write_text("{ this is not valid json ", encoding="utf-8")
        # _load must not raise; corrupt file set aside, store treated as empty
        assert mem.count() == 0
        assert mem._STORE.with_name("memory.corrupt.json").exists()
        return "corrupt store recovered"
    check("memory corrupt-store recovery", corrupt_store_recovers)

    # store is empty again after the corrupt-recovery step: clean slate for the
    # update_fact tests below.
    def update_happy_path():
        registry.dispatch("remember", {"fact": "The wifi password is hunter2"})
        registry.dispatch("remember", {"fact": "The user lives in Rabat"})
        assert mem.count() == 2
        # a single match is REPLACED in place: count unchanged, not appended
        out = registry.dispatch("update_fact",
                                {"old": "wifi", "new": "The wifi password is dragon99"})
        assert "Updated" in out, out
        assert mem.count() == 2, "update must not add a fact"
        # recall + injected preamble reflect the new wording, not the old
        assert "dragon99" in registry.dispatch("recall", {"query": "wifi"})
        assert "dragon99" in mem.memory_preamble()
        assert "hunter2" not in mem.memory_preamble()
        # a no-match update changes nothing and points at remember
        r = registry.dispatch("update_fact", {"old": "zzzznope", "new": "whatever"})
        assert "Nothing in memory matches" in r and "remember" in r, r
        assert mem.count() == 2
        return "update single-match + no-match ok"
    check("memory update_fact happy path", update_happy_path)

    def update_guards():
        # ambiguous 'old' matching several facts changes NOTHING (safety)
        registry.dispatch("remember", {"fact": "The user likes green tea"})
        registry.dispatch("remember", {"fact": "The user likes long walks"})
        r = registry.dispatch("update_fact", {"old": "likes", "new": "one single thing"})
        assert "please be more specific" in r, r
        assert "one single thing" not in mem.memory_preamble(), "ambiguous update wrote anyway"
        # empty / missing / wrong-type args must not crash or corrupt the store
        assert "Error" in registry.dispatch("update_fact", {"old": "", "new": "x"})
        assert "Error" in registry.dispatch("update_fact", {"old": "wifi", "new": ""})
        assert "Error" in registry.dispatch("update_fact", {"new": "x"})   # missing old
        registry.dispatch("update_fact", {"old": 123, "new": 456})          # coerced, no raise
        # over-long 'new' is truncated (bounded), not stored unbounded
        lng = registry.dispatch("update_fact", {"old": "Rabat", "new": "y" * 5000})
        assert "shortened" in lng, lng
        # updating to a wording that already exists as a DIFFERENT fact must not
        # create a duplicate: the old one is dropped, one copy remains
        registry.dispatch("update_fact",
                          {"old": "green tea", "new": "The user likes long walks"})
        assert mem.memory_preamble().lower().count("long walks") == 1, "duplicate created"
        return "ambiguous-safety + guards + dedup-on-update ok"
    check("memory update_fact guards", update_guards)


def t_shell():
    """Exercises the safe run_command tool + its defenses. No model needed."""
    from jarvis.tools import shell  # noqa: F401  (register)
    from jarvis.tools import registry

    def happy_path():
        out = registry.dispatch("run_command", {"command": "whoami"})
        assert "Error" not in out and out.strip(), f"whoami gave: {out!r}"
        assert registry.dispatch("run_command", {"command": "hostname"}).strip()
        return "whoami/hostname ran"
    check("shell happy path", happy_path)

    def allowlist_blocks():
        # anything not on the allowlist is refused, not run
        for bad in ("del", "rm -rf /", "format c:", "shutdown", "powershell"):
            r = registry.dispatch("run_command", {"command": bad})
            assert "not an allowed command" in r, f"{bad!r} not blocked: {r}"
        return "disallowed commands blocked"
    check("shell allowlist", allowlist_blocks)

    def injection_is_inert():
        # shell metacharacters can't escape: only the first token is parsed,
        # and it isn't on the allowlist, so the whole thing is refused
        r = registry.dispatch("run_command", {"command": "ipconfig & del /q *"})
        # 'ipconfig' IS allowed; the '& del ...' is ignored (never shelled)
        assert "Error" not in r or "not an allowed" in r
        r2 = registry.dispatch("run_command", {"command": "whoami; rm -rf ~"})
        assert "not an allowed command" in r2  # 'whoami;' != 'whoami'...
        return "injection inert"
    check("shell injection inert", injection_is_inert)

    def host_validation():
        assert "needs a host" in registry.dispatch("run_command", {"command": "ping"})
        bad = registry.dispatch("run_command", {"command": "ping", "target": "google.com & del *"})
        assert "not a valid host" in bad, f"bad host not rejected: {bad}"
        return "host arg validated"
    check("shell host validation", host_validation)

    def wrong_types_dont_crash():
        assert "Error" in registry.dispatch("run_command", {"command": ""})
        assert "Error" in registry.dispatch("run_command", {})
        registry.dispatch("run_command", {"command": 123})  # must not raise
        return "wrong-type args survived"
    check("shell wrong-type guards", wrong_types_dont_crash)


def t_find():
    """Exercises the find_files tool + its defenses against 8B hallucinations.
    Uses a temp tree inside the user's home, so no models are needed and it
    lives in the safe set."""
    import os
    import pathlib
    from jarvis.tools import find  # noqa: F401  (register)
    from jarvis.tools import registry

    # build an isolated sandbox INSIDE the home folder (find only searches home)
    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_find_smoke"
    (sandbox / "sub").mkdir(parents=True, exist_ok=True)
    (sandbox / "budget_2026.xlsx").write_text("x", encoding="utf-8")
    (sandbox / "sub" / "my_cv.pdf").write_text("x", encoding="utf-8")
    # a pruned dir that must NOT be descended into
    (sandbox / "node_modules").mkdir(exist_ok=True)
    (sandbox / "node_modules" / "budget_junk.xlsx").write_text("x", encoding="utf-8")

    try:
        def happy_path():
            out = registry.dispatch("find_files", {"name": "budget", "folder": "jarvis_find_smoke"})
            assert "budget_2026.xlsx" in out, out
            # nested file found via recursion
            deep = registry.dispatch("find_files", {"name": "cv", "folder": "jarvis_find_smoke"})
            assert "my_cv.pdf" in deep, deep
            return "found top-level + nested files"
        check("find happy path", happy_path)

        def wildcard():
            out = registry.dispatch("find_files", {"name": "*.xlsx", "folder": "jarvis_find_smoke"})
            assert "budget_2026.xlsx" in out, out
            return "wildcard match ok"
        check("find wildcard", wildcard)

        def prunes_noise_dirs():
            # node_modules is pruned, so its budget_junk.xlsx must not appear
            out = registry.dispatch("find_files", {"name": "budget", "folder": "jarvis_find_smoke"})
            assert "budget_junk.xlsx" not in out, f"node_modules not pruned: {out}"
            return "noise dirs pruned"
        check("find prunes noise dirs", prunes_noise_dirs)

        def containment_guard():
            # searching outside the home folder must be refused, not run
            r = registry.dispatch("find_files", {"name": "config", "folder": "C:\\Windows"})
            assert "only search inside your own folders" in r, r
            return "escape outside home blocked"
        check("find containment guard", containment_guard)

        def hallucination_guards():
            assert "Error" in registry.dispatch("find_files", {"name": ""})
            assert "Error" in registry.dispatch("find_files", {})           # missing arg
            assert "too broad" in registry.dispatch("find_files", {"name": "*"})
            # wrong types / missing folder must not raise
            registry.dispatch("find_files", {"name": 123, "folder": "jarvis_find_smoke"})
            miss = registry.dispatch("find_files", {"name": "x", "folder": "jarvis_find_smoke/nope"})
            assert "does not exist" in miss, miss
            return "guards held"
        check("find hallucination guards", hallucination_guards)

        def no_match_is_friendly():
            out = registry.dispatch("find_files", {"name": "zzzznotathing", "folder": "jarvis_find_smoke"})
            assert "No files matching" in out, out
            return "no-match message ok"
        check("find no-match message", no_match_is_friendly)
    finally:
        import shutil
        shutil.rmtree(sandbox, ignore_errors=True)


def t_search():
    """Exercises the search_files tool (content search) + its defenses against
    8B hallucinations. Uses a temp tree inside the user's home (search only
    looks under home), so no models are needed and it lives in the safe set."""
    import os
    import pathlib
    from jarvis.tools import search  # noqa: F401  (register)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_search_smoke"
    (sandbox / "sub").mkdir(parents=True, exist_ok=True)
    (sandbox / "notes.txt").write_text(
        "shopping list\nthe wifi password is hunter2\nremember the milk\n",
        encoding="utf-8")
    (sandbox / "sub" / "diary.md").write_text(
        "today I worked on the BUDGET report\nand nothing else\n",
        encoding="utf-8")
    # a file with non-ASCII content: match line must be sanitised, not crash
    (sandbox / "accents.txt").write_text(
        "cafe budget expose naive\n", encoding="utf-8")
    # a pruned dir that must NOT be descended into
    (sandbox / "node_modules").mkdir(exist_ok=True)
    (sandbox / "node_modules" / "junk.txt").write_text(
        "wifi password leak here\n", encoding="utf-8")
    # a binary file that must be skipped, not read as text
    (sandbox / "blob.bin").write_bytes(b"wifi password\x00\x01\x02binary")

    try:
        def happy_path():
            out = registry.dispatch(
                "search_files", {"query": "wifi password", "folder": "jarvis_search_smoke"})
            assert "notes.txt" in out, out
            assert "hunter2" in out, out          # the matched line is shown
            assert "2:" in out                    # with its line number
            return "found text + line number"
        check("search happy path", happy_path)

        def case_insensitive_and_nested():
            # lower-case query matches upper-case text in a nested file
            out = registry.dispatch(
                "search_files", {"query": "budget", "folder": "jarvis_search_smoke"})
            assert "diary.md" in out, out
            return "case-insensitive + nested ok"
        check("search case-insensitive nested", case_insensitive_and_nested)

        def name_filter():
            # limiting to *.md must exclude notes.txt / accents.txt
            out = registry.dispatch(
                "search_files",
                {"query": "budget", "folder": "jarvis_search_smoke", "name": "*.md"})
            assert "diary.md" in out and "accents.txt" not in out, out
            return "name pattern filter ok"
        check("search name filter", name_filter)

        def prunes_and_skips_binary():
            out = registry.dispatch(
                "search_files", {"query": "wifi password", "folder": "jarvis_search_smoke"})
            # node_modules pruned -> its junk.txt hit must not appear
            assert "junk.txt" not in out, f"node_modules not pruned: {out}"
            # binary file skipped -> blob.bin must not appear
            assert "blob.bin" not in out, f"binary not skipped: {out}"
            return "noise dirs pruned + binary skipped"
        check("search prunes noise + skips binary", prunes_and_skips_binary)

        def output_is_ascii():
            out = registry.dispatch(
                "search_files", {"query": "budget", "folder": "jarvis_search_smoke"})
            out.encode("ascii")  # raises if any non-ASCII leaked through
            return "output stayed pure ASCII"
        check("search ascii-only output", output_is_ascii)

        def containment_guard():
            # searching outside the home folder must be refused, not run
            r = registry.dispatch(
                "search_files", {"query": "password", "folder": "C:\\Windows"})
            assert "only search inside your own folders" in r, r
            return "escape outside home blocked"
        check("search containment guard", containment_guard)

        def hallucination_guards():
            assert "Error" in registry.dispatch("search_files", {"query": ""})
            assert "Error" in registry.dispatch("search_files", {})   # missing arg
            # wrong types must not raise
            registry.dispatch("search_files", {"query": 123, "folder": "jarvis_search_smoke"})
            registry.dispatch("search_files", {"query": "x", "folder": "jarvis_search_smoke", "name": 5})
            # bare '*' name filter is treated as no filter, not a crash
            registry.dispatch(
                "search_files",
                {"query": "wifi", "folder": "jarvis_search_smoke", "name": "*"})
            # missing folder is a friendly message, not a crash
            miss = registry.dispatch(
                "search_files", {"query": "x", "folder": "jarvis_search_smoke/nope"})
            assert "does not exist" in miss, miss
            return "guards held"
        check("search hallucination guards", hallucination_guards)

        def no_match_is_friendly():
            out = registry.dispatch(
                "search_files", {"query": "zzzznotathing", "folder": "jarvis_search_smoke"})
            assert "No files containing" in out, out
            return "no-match message ok"
        check("search no-match message", no_match_is_friendly)
    finally:
        import shutil
        shutil.rmtree(sandbox, ignore_errors=True)


def t_recent():
    """Exercises the recent_files tool (search by TIME) + its defenses against
    8B hallucinations. Uses a temp tree inside the user's home with controlled
    modification times, so it is deterministic, needs no model, and lives in
    the safe set."""
    import os
    import pathlib
    import time
    from jarvis.tools import recent  # noqa: F401  (register)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_recent_smoke"
    (sandbox / "sub").mkdir(parents=True, exist_ok=True)
    now = time.time()

    def _touch(rel, days_ago):
        p = sandbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        t = now - days_ago * 86400
        os.utime(p, (t, t))
        return p

    # newest -> oldest, spanning the default 7-day window boundary
    _touch("fresh_today.txt", 0.01)       # ~15 min ago
    _touch("report.docx", 2)              # 2 days ago
    _touch("sub/notes.md", 5)             # 5 days ago, nested
    _touch("ancient.txt", 400)            # well outside any sane window
    # a pruned dir whose (very recent) file must NOT surface
    (sandbox / "node_modules").mkdir(exist_ok=True)
    nm = sandbox / "node_modules" / "build.log"
    nm.write_text("x", encoding="utf-8")
    os.utime(nm, (now, now))

    try:
        def happy_path_and_order():
            out = registry.dispatch("recent_files", {"folder": "jarvis_recent_smoke"})
            # recent files inside the 7-day default show; the 400-day one doesn't
            assert "fresh_today.txt" in out, out
            assert "report.docx" in out and "notes.md" in out, out
            assert "ancient.txt" not in out, f"old file leaked: {out}"
            # newest first: fresh_today must appear before report.docx
            assert out.index("fresh_today.txt") < out.index("report.docx"), out
            return "lists recent files newest-first"
        check("recent happy path + ordering", happy_path_and_order)

        def days_window():
            # a 1-day window drops the 2- and 5-day-old files
            out = registry.dispatch("recent_files",
                                    {"folder": "jarvis_recent_smoke", "days": 1})
            assert "fresh_today.txt" in out, out
            assert "report.docx" not in out and "notes.md" not in out, out
            return "days window narrows results"
        check("recent days window", days_window)

        def name_filter():
            out = registry.dispatch(
                "recent_files",
                {"folder": "jarvis_recent_smoke", "name": "*.md"})
            assert "notes.md" in out, out
            assert "report.docx" not in out and "fresh_today.txt" not in out, out
            return "name pattern filter ok"
        check("recent name filter", name_filter)

        def prunes_noise_dirs():
            out = registry.dispatch("recent_files", {"folder": "jarvis_recent_smoke"})
            assert "build.log" not in out, f"node_modules not pruned: {out}"
            return "noise dirs pruned"
        check("recent prunes noise dirs", prunes_noise_dirs)

        def output_is_ascii():
            registry.dispatch("recent_files",
                              {"folder": "jarvis_recent_smoke"}).encode("ascii")
            return "output stayed pure ASCII"
        check("recent ascii-only output", output_is_ascii)

        def containment_guard():
            r = registry.dispatch("recent_files", {"folder": "C:\\Windows"})
            assert "only search inside your own folders" in r, r
            return "escape outside home blocked"
        check("recent containment guard", containment_guard)

        def no_match_is_friendly():
            out = registry.dispatch(
                "recent_files",
                {"folder": "jarvis_recent_smoke", "name": "*.zzz"})
            assert "No files changed" in out, out
            return "no-match message ok"
        check("recent no-match message", no_match_is_friendly)

        def hallucination_guards():
            # no args at all is valid (whole home, last 7 days) -- must not crash
            registry.dispatch("recent_files", {})
            # wrong-type / junk 'days' is coerced to the default, never raises
            for junk in ("soon", -5, 0, True, 1e400, float("inf"), [1, 2], {}):
                registry.dispatch(
                    "recent_files", {"folder": "jarvis_recent_smoke", "days": junk})
            # an absurd but finite window is clamped, not overflowed
            big = registry.dispatch(
                "recent_files", {"folder": "jarvis_recent_smoke", "days": 10 ** 9})
            assert "fresh_today.txt" in big, big
            # a "3 days" phrase in days extracts the number
            phrase = registry.dispatch(
                "recent_files", {"folder": "jarvis_recent_smoke", "days": "3 days"})
            assert "report.docx" in phrase and "notes.md" not in phrase, phrase
            # wrong-type folder/name must not raise
            registry.dispatch("recent_files", {"folder": 5, "name": 7})
            # bare '*' name filter is treated as no filter, not a crash
            registry.dispatch(
                "recent_files", {"folder": "jarvis_recent_smoke", "name": "*"})
            # a missing folder is a friendly message, not a crash
            miss = registry.dispatch(
                "recent_files", {"folder": "jarvis_recent_smoke/nope"})
            assert "does not exist" in miss, miss
            return "guards held"
        check("recent hallucination guards", hallucination_guards)
    finally:
        import shutil
        shutil.rmtree(sandbox, ignore_errors=True)


def t_organize():
    """Exercises the move_file / copy_file tools (file management) + their
    defenses against 8B hallucinations. Works entirely inside a temp tree in the
    user's home (the only place these tools touch), so it is deterministic,
    needs no model, and lives in the safe set."""
    import os
    import pathlib
    import shutil
    from jarvis.tools import organize as org  # noqa: F401  (register)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_organize_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)
    (sandbox / "sub").mkdir(parents=True, exist_ok=True)

    def mk(rel, text="x"):
        p = sandbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    saved_cap = org.MAX_COPY_BYTES
    try:
        def move_into_folder():
            mk("a.txt")
            out = registry.dispatch("move_file",
                {"source": "jarvis_organize_smoke/a.txt",
                 "dest": "jarvis_organize_smoke/sub"})
            assert "Moved" in out, out
            assert (sandbox / "sub" / "a.txt").exists()
            assert not (sandbox / "a.txt").exists(), "source not removed"
            return "moved a file into a folder"
        check("organize move into folder", move_into_folder)

        def rename_in_place():
            mk("old.txt")
            # a bare new name renames the file inside its OWN folder
            out = registry.dispatch("move_file",
                {"source": "jarvis_organize_smoke/old.txt", "dest": "new.txt"})
            assert "Renamed" in out, out
            assert (sandbox / "new.txt").exists()
            assert not (sandbox / "old.txt").exists()
            return "renamed a file in place"
        check("organize rename in place", rename_in_place)

        def copy_duplicate_keeps_original():
            mk("notes.txt", "hello")
            out = registry.dispatch("copy_file",
                {"source": "jarvis_organize_smoke/notes.txt",
                 "dest": "notes_backup.txt"})
            assert "Copied" in out, out
            assert (sandbox / "notes.txt").exists(), "original vanished"
            assert (sandbox / "notes_backup.txt").read_text(encoding="utf-8") == "hello"
            return "duplicated a file, original kept"
        check("organize copy duplicate", copy_duplicate_keeps_original)

        def never_overwrites():
            mk("src1.txt", "A")
            mk("keep.txt", "B")
            out = registry.dispatch("move_file",
                {"source": "jarvis_organize_smoke/src1.txt", "dest": "keep.txt"})
            assert "won't overwrite" in out, out
            # the existing file is untouched and the source is left in place
            assert (sandbox / "keep.txt").read_text(encoding="utf-8") == "B"
            assert (sandbox / "src1.txt").exists()
            return "refuses to overwrite an existing file"
        check("organize never overwrites", never_overwrites)

        def alt_arg_names():
            # the model may use from/to instead of source/dest -> still works
            mk("alt.txt")
            out = registry.dispatch("move_file",
                {"from": "jarvis_organize_smoke/alt.txt",
                 "to": "jarvis_organize_smoke/sub"})
            assert "Moved" in out, out
            assert (sandbox / "sub" / "alt.txt").exists()
            return "alt from/to arg names handled"
        check("organize alt arg names", alt_arg_names)

        def containment_guard():
            # moving OUT of the user's home must be refused, not run
            mk("esc.txt")
            r = registry.dispatch("move_file",
                {"source": "jarvis_organize_smoke/esc.txt",
                 "dest": "C:\\Windows\\esc.txt"})
            assert "only work inside your own folders" in r, r
            assert (sandbox / "esc.txt").exists(), "source moved despite guard"
            return "escape outside home blocked"
        check("organize containment guard", containment_guard)

        def missing_source_is_friendly():
            r = registry.dispatch("move_file",
                {"source": "jarvis_organize_smoke/ghost.txt", "dest": "x.txt"})
            assert "can't find" in r, r
            return "missing source is a friendly message"
        check("organize missing source", missing_source_is_friendly)

        def refuses_directory_source():
            r = registry.dispatch("move_file",
                {"source": "jarvis_organize_smoke/sub", "dest": "sub_renamed"})
            assert "folder" in r and "only move or copy files" in r, r
            return "a folder source is refused"
        check("organize refuses directory source", refuses_directory_source)

        def copy_size_cap():
            org.MAX_COPY_BYTES = 4              # temporarily tiny
            mk("big.txt", "0123456789")         # 10 bytes > 4
            r = registry.dispatch("copy_file",
                {"source": "jarvis_organize_smoke/big.txt", "dest": "big_copy.txt"})
            assert "too large" in r, r
            assert not (sandbox / "big_copy.txt").exists()
            org.MAX_COPY_BYTES = saved_cap
            return "oversized copy refused"
        check("organize copy size cap", copy_size_cap)

        def output_is_ascii():
            mk("asc.txt")
            registry.dispatch("move_file",
                {"source": "jarvis_organize_smoke/asc.txt",
                 "dest": "jarvis_organize_smoke/sub"}).encode("ascii")
            return "output stayed pure ASCII"
        check("organize ascii-only output", output_is_ascii)

        def hallucination_guards():
            # empty / missing args -> friendly error, never a crash
            assert "Error" in registry.dispatch("move_file", {"source": "", "dest": "x"})
            assert "Error" in registry.dispatch("move_file", {"source": "a", "dest": ""})
            assert "Error" in registry.dispatch("move_file", {})
            assert "Error" in registry.dispatch("copy_file", {})
            # wrong types must not raise
            registry.dispatch("move_file", {"source": 123, "dest": 456})
            registry.dispatch("copy_file", {"source": ["a"], "dest": {}})
            return "guards held"
        check("organize hallucination guards", hallucination_guards)
    finally:
        org.MAX_COPY_BYTES = saved_cap
        shutil.rmtree(sandbox, ignore_errors=True)


def t_movefolder():
    """Exercises the move_folder tool (move/rename a WHOLE folder) + its defenses
    against 8B hallucinations. Works entirely inside a temp tree in the user's
    home (the only place it touches), so it is deterministic, needs no model, and
    lives in the safe set."""
    import os
    import pathlib
    import shutil
    from jarvis.tools import organize as org  # noqa: F401  (register move_folder)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_movefolder_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)

    def mkdir(rel):
        p = sandbox / rel
        p.mkdir(parents=True, exist_ok=True)
        return p

    def mkfile(rel, text="x"):
        p = sandbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    try:
        sandbox.mkdir(parents=True, exist_ok=True)

        def move_into_folder():
            mkfile("Taxes/receipt.txt", "r")
            mkdir("Documents")
            out = registry.dispatch("move_folder",
                {"source": "jarvis_movefolder_smoke/Taxes",
                 "dest": "jarvis_movefolder_smoke/Documents"})
            assert "Moved folder" in out, out
            assert (sandbox / "Documents" / "Taxes" / "receipt.txt").exists()
            assert not (sandbox / "Taxes").exists(), "source folder not removed"
            return "moved a whole folder into another folder"
        check("movefolder move into folder", move_into_folder)

        def rename_in_place():
            mkfile("Old/inner.txt", "i")
            # a bare new name renames the folder inside its OWN parent
            out = registry.dispatch("move_folder",
                {"source": "jarvis_movefolder_smoke/Old", "dest": "New"})
            assert "Renamed folder" in out, out
            assert (sandbox / "New" / "inner.txt").exists()
            assert not (sandbox / "Old").exists()
            return "renamed a folder in place"
        check("movefolder rename in place", rename_in_place)

        def never_overwrites():
            mkfile("A/a.txt", "A")
            mkdir("Dest/A")            # a folder named A already sits in Dest
            out = registry.dispatch("move_folder",
                {"source": "jarvis_movefolder_smoke/A",
                 "dest": "jarvis_movefolder_smoke/Dest"})
            assert "won't overwrite or merge" in out, out
            assert (sandbox / "A" / "a.txt").exists(), "source moved despite guard"
            return "refuses to merge into an existing folder"
        check("movefolder never overwrites", never_overwrites)

        def refuses_into_own_subfolder():
            mkdir("Proj/sub")
            r = registry.dispatch("move_folder",
                {"source": "jarvis_movefolder_smoke/Proj",
                 "dest": "jarvis_movefolder_smoke/Proj/sub"})
            assert "into itself" in r, r
            assert (sandbox / "Proj" / "sub").exists(), "tree damaged"
            return "refuses moving a folder into its own subfolder"
        check("movefolder refuses into own subfolder", refuses_into_own_subfolder)

        def refuses_file_source():
            mkfile("solo.txt", "s")
            r = registry.dispatch("move_folder",
                {"source": "jarvis_movefolder_smoke/solo.txt", "dest": "gone"})
            assert "is a file" in r and "move_file" in r, r
            assert (sandbox / "solo.txt").exists()
            return "a file source is refused (points at move_file)"
        check("movefolder refuses file source", refuses_file_source)

        def refuses_home_folder():
            r = registry.dispatch("move_folder",
                {"source": str(home), "dest": "jarvis_movefolder_smoke/whoops"})
            assert "home folder" in r, r
            return "refuses to move the whole home folder"
        check("movefolder refuses home folder", refuses_home_folder)

        def alt_arg_names():
            mkfile("Alt/z.txt", "z")
            mkdir("Bin")
            out = registry.dispatch("move_folder",
                {"from": "jarvis_movefolder_smoke/Alt",
                 "into": "jarvis_movefolder_smoke/Bin"})
            assert "Moved folder" in out, out
            assert (sandbox / "Bin" / "Alt" / "z.txt").exists()
            return "alt from/into arg names handled"
        check("movefolder alt arg names", alt_arg_names)

        def containment_guard():
            mkdir("Esc")
            r = registry.dispatch("move_folder",
                {"source": "jarvis_movefolder_smoke/Esc",
                 "dest": "C:\\Windows\\Esc"})
            assert "only work inside your own folders" in r, r
            assert (sandbox / "Esc").exists(), "folder moved despite guard"
            return "escape outside home blocked"
        check("movefolder containment guard", containment_guard)

        def missing_source_is_friendly():
            r = registry.dispatch("move_folder",
                {"source": "jarvis_movefolder_smoke/ghost", "dest": "x"})
            assert "can't find" in r, r
            return "missing source is a friendly message"
        check("movefolder missing source", missing_source_is_friendly)

        def output_is_ascii():
            mkdir("Asc")
            mkdir("AscDest")
            registry.dispatch("move_folder",
                {"source": "jarvis_movefolder_smoke/Asc",
                 "dest": "jarvis_movefolder_smoke/AscDest"}).encode("ascii")
            return "output stayed pure ASCII"
        check("movefolder ascii-only output", output_is_ascii)

        def hallucination_guards():
            # empty / missing args -> friendly error, never a crash
            assert "Error" in registry.dispatch("move_folder", {"source": "", "dest": "x"})
            assert "Error" in registry.dispatch("move_folder", {"source": "a", "dest": ""})
            assert "Error" in registry.dispatch("move_folder", {})
            # wrong types must not raise
            registry.dispatch("move_folder", {"source": 123, "dest": 456})
            registry.dispatch("move_folder", {"source": ["a"], "dest": {}})
            return "guards held"
        check("movefolder hallucination guards", hallucination_guards)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def t_copyfolder():
    """Exercises the copy_folder tool (duplicate a WHOLE folder) + its defenses
    against 8B hallucinations. Works entirely inside a temp tree in the user's
    home (the only place it touches), so it is deterministic, needs no model, and
    lives in the safe set."""
    import os
    import pathlib
    import shutil
    from jarvis.tools import organize as org  # noqa: F401  (register copy_folder)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_copyfolder_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)

    def mkdir(rel):
        p = sandbox / rel
        p.mkdir(parents=True, exist_ok=True)
        return p

    def mkfile(rel, text="x"):
        p = sandbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    try:
        sandbox.mkdir(parents=True, exist_ok=True)

        def copy_into_folder():
            mkfile("Taxes/receipt.txt", "receipt")
            mkfile("Taxes/sub/note.txt", "note")
            mkdir("Backups")
            out = registry.dispatch("copy_folder",
                {"source": "jarvis_copyfolder_smoke/Taxes",
                 "dest": "jarvis_copyfolder_smoke/Backups"})
            assert "Copied folder" in out, out
            # the copy exists with its full contents...
            assert (sandbox / "Backups" / "Taxes" / "receipt.txt").exists()
            assert (sandbox / "Backups" / "Taxes" / "sub" / "note.txt").exists()
            # ...and the ORIGINAL is left exactly where it was
            assert (sandbox / "Taxes" / "receipt.txt").exists(), "original gone"
            return "copied a whole folder, original kept"
        check("copyfolder copy into folder", copy_into_folder)

        def copy_reports_count_and_size():
            mkfile("Counted/a.txt", "aaaa")
            mkfile("Counted/b.txt", "bb")
            out = registry.dispatch("copy_folder",
                {"source": "jarvis_copyfolder_smoke/Counted",
                 "dest": "Counted_copy"})
            assert "2 files" in out, out
            assert (sandbox / "Counted_copy" / "a.txt").exists()
            assert (sandbox / "Counted").exists()
            return "reports file count + size, renames a copy in place"
        check("copyfolder rename-in-place + count", copy_reports_count_and_size)

        def never_overwrites():
            mkfile("Src/a.txt", "A")
            mkdir("Dst/Src")           # a folder named Src already sits in Dst
            out = registry.dispatch("copy_folder",
                {"source": "jarvis_copyfolder_smoke/Src",
                 "dest": "jarvis_copyfolder_smoke/Dst"})
            assert "won't overwrite or merge" in out, out
            return "refuses to merge into an existing folder"
        check("copyfolder never overwrites", never_overwrites)

        def refuses_into_own_subfolder():
            mkdir("Proj/sub")
            r = registry.dispatch("copy_folder",
                {"source": "jarvis_copyfolder_smoke/Proj",
                 "dest": "jarvis_copyfolder_smoke/Proj/sub"})
            assert "into itself" in r, r
            return "refuses copying a folder into its own subfolder"
        check("copyfolder refuses into own subfolder", refuses_into_own_subfolder)

        def refuses_file_source():
            mkfile("solo.txt", "s")
            r = registry.dispatch("copy_folder",
                {"source": "jarvis_copyfolder_smoke/solo.txt", "dest": "gone"})
            assert "is a file" in r and "copy_file" in r, r
            assert (sandbox / "solo.txt").exists()
            return "a file source is refused (points at copy_file)"
        check("copyfolder refuses file source", refuses_file_source)

        def refuses_home_folder():
            r = registry.dispatch("copy_folder",
                {"source": str(home), "dest": "jarvis_copyfolder_smoke/whoops"})
            assert "home folder" in r, r
            return "refuses to copy the whole home folder"
        check("copyfolder refuses home folder", refuses_home_folder)

        def alt_arg_names():
            mkfile("Alt/z.txt", "z")
            mkdir("Bin")
            out = registry.dispatch("copy_folder",
                {"from": "jarvis_copyfolder_smoke/Alt",
                 "into": "jarvis_copyfolder_smoke/Bin"})
            assert "Copied folder" in out, out
            assert (sandbox / "Bin" / "Alt" / "z.txt").exists()
            assert (sandbox / "Alt" / "z.txt").exists(), "original gone"
            return "alt from/into arg names handled"
        check("copyfolder alt arg names", alt_arg_names)

        def containment_guard():
            mkdir("Esc")
            r = registry.dispatch("copy_folder",
                {"source": "jarvis_copyfolder_smoke/Esc",
                 "dest": "C:\\Windows\\Esc"})
            assert "only work inside your own folders" in r, r
            assert not pathlib.Path("C:\\Windows\\Esc").exists()
            return "escape outside home blocked"
        check("copyfolder containment guard", containment_guard)

        def missing_source_is_friendly():
            r = registry.dispatch("copy_folder",
                {"source": "jarvis_copyfolder_smoke/ghost", "dest": "x"})
            assert "can't find" in r, r
            return "missing source is a friendly message"
        check("copyfolder missing source", missing_source_is_friendly)

        def size_cap_refuses_before_copying():
            # temporarily lower the file-count cap so we don't create thousands
            # of files; the copy must be REFUSED and nothing written.
            mkfile("Big/1.txt"); mkfile("Big/2.txt"); mkfile("Big/3.txt")
            saved = org.MAX_COPY_FILES
            org.MAX_COPY_FILES = 2
            try:
                r = registry.dispatch("copy_folder",
                    {"source": "jarvis_copyfolder_smoke/Big",
                     "dest": "jarvis_copyfolder_smoke/BigCopy"})
            finally:
                org.MAX_COPY_FILES = saved
            assert "too many files" in r, r
            assert not (sandbox / "BigCopy").exists(), "copied despite size cap"
            return "over-cap folder refused, nothing written"
        check("copyfolder size cap", size_cap_refuses_before_copying)

        def output_is_ascii():
            mkdir("Asc")
            registry.dispatch("copy_folder",
                {"source": "jarvis_copyfolder_smoke/Asc",
                 "dest": "jarvis_copyfolder_smoke/AscCopy"}).encode("ascii")
            return "output stayed pure ASCII"
        check("copyfolder ascii-only output", output_is_ascii)

        def hallucination_guards():
            # empty / missing args -> friendly error, never a crash
            assert "Error" in registry.dispatch("copy_folder", {"source": "", "dest": "x"})
            assert "Error" in registry.dispatch("copy_folder", {"source": "a", "dest": ""})
            assert "Error" in registry.dispatch("copy_folder", {})
            # wrong types must not raise
            registry.dispatch("copy_folder", {"source": 123, "dest": 456})
            registry.dispatch("copy_folder", {"source": ["a"], "dest": {}})
            return "guards held"
        check("copyfolder hallucination guards", hallucination_guards)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def t_makefolder():
    """Exercises the make_folder tool (create a directory to organise into) + its
    defenses against 8B hallucinations. Works entirely inside a temp tree in the
    user's home (the only place it touches), so it is deterministic, needs no
    model, and lives in the safe set."""
    import os
    import pathlib
    import shutil
    from jarvis.tools import organize as org  # noqa: F401  (register make_folder)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_makefolder_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)
    sandbox.mkdir(parents=True, exist_ok=True)

    saved_depth = org.MAX_NEW_DEPTH
    try:
        def creates_nested_folder():
            # a multi-part path creates intermediate parents too
            out = registry.dispatch("make_folder",
                {"path": "jarvis_makefolder_smoke/Taxes/2026"})
            assert "Created folder" in out, out
            assert (sandbox / "Taxes" / "2026").is_dir(), "folder not created"
            return "created a nested folder (parents too)"
        check("make_folder creates nested folder", creates_nested_folder)

        def parent_plus_name():
            # the model may give a bare name + a separate parent folder
            out = registry.dispatch("make_folder",
                {"path": "Projects", "parent": "jarvis_makefolder_smoke"})
            assert "Created folder" in out, out
            assert (sandbox / "Projects").is_dir(), out
            return "parent + bare name joined"
        check("make_folder parent + name", parent_plus_name)

        def already_exists_is_friendly():
            # re-creating an existing folder is a friendly no-op, not an error
            registry.dispatch("make_folder", {"path": "jarvis_makefolder_smoke/Dup"})
            out = registry.dispatch("make_folder", {"path": "jarvis_makefolder_smoke/Dup"})
            assert "already exists" in out and "Error" not in out, out
            return "existing folder is a friendly no-op"
        check("make_folder existing folder", already_exists_is_friendly)

        def refuses_over_a_file():
            # a path that already exists as a FILE is refused, never overwritten
            (sandbox / "note.txt").write_text("keep me", encoding="utf-8")
            out = registry.dispatch("make_folder",
                {"path": "jarvis_makefolder_smoke/note.txt"})
            assert "already exists as a file" in out, out
            assert (sandbox / "note.txt").read_text(encoding="utf-8") == "keep me"
            return "won't clobber an existing file with a folder"
        check("make_folder refuses over a file", refuses_over_a_file)

        def alt_arg_names():
            # the model may use name=/directory= instead of path
            out = registry.dispatch("make_folder",
                {"name": "jarvis_makefolder_smoke/Alt"})
            assert "Created folder" in out, out
            assert (sandbox / "Alt").is_dir(), out
            return "alt name/directory arg names handled"
        check("make_folder alt arg names", alt_arg_names)

        def containment_guard():
            # creating OUTSIDE the user's home must be refused, never made
            r = registry.dispatch("make_folder", {"path": "C:\\Windows\\Jarvis_evil"})
            assert "only work inside your own folders" in r, r
            assert not pathlib.Path("C:\\Windows\\Jarvis_evil").exists()
            # a ..-escape out of home is also refused (resolved + re-checked)
            r2 = registry.dispatch("make_folder",
                {"path": "jarvis_makefolder_smoke/../../../Windows/Jarvis_evil2"})
            assert "only work inside your own folders" in r2, r2
            return "escape outside home blocked"
        check("make_folder containment guard", containment_guard)

        def depth_cap():
            org.MAX_NEW_DEPTH = 3              # temporarily tiny
            deep = "jarvis_makefolder_smoke/" + "/".join(f"d{i}" for i in range(10))
            r = registry.dispatch("make_folder", {"path": deep})
            assert "too deeply" in r, r
            assert not (sandbox / "d0").exists(), "deep tree created despite cap"
            org.MAX_NEW_DEPTH = saved_depth
            return "over-deep path refused"
        check("make_folder depth cap", depth_cap)

        def output_is_ascii():
            registry.dispatch("make_folder",
                {"path": "jarvis_makefolder_smoke/Asc"}).encode("ascii")
            return "output stayed pure ASCII"
        check("make_folder ascii-only output", output_is_ascii)

        def hallucination_guards():
            # empty / whitespace / missing args -> friendly error, never a crash
            assert "Error" in registry.dispatch("make_folder", {"path": ""})
            assert "Error" in registry.dispatch("make_folder", {"path": "   "})
            assert "Error" in registry.dispatch("make_folder", {})
            # the home folder itself is not "created"
            assert "home folder" in registry.dispatch("make_folder", {"path": "~"})
            # wrong types must not raise
            registry.dispatch("make_folder", {"path": 123})
            registry.dispatch("make_folder", {"path": ["a"]})
            registry.dispatch("make_folder", {"path": {}})
            return "guards held"
        check("make_folder hallucination guards", hallucination_guards)
    finally:
        org.MAX_NEW_DEPTH = saved_depth
        shutil.rmtree(sandbox, ignore_errors=True)


def t_disk():
    """Exercises the folder_size tool (disk usage) + its defenses against 8B
    hallucinations. Read-only, works entirely inside a temp tree in the user's
    home, so it is deterministic, needs no model, and lives in the safe set."""
    import os
    import pathlib
    import shutil
    from jarvis.tools import disk  # noqa: F401  (register folder_size)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_disk_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)
    (sandbox / "big").mkdir(parents=True, exist_ok=True)
    (sandbox / "small").mkdir(parents=True, exist_ok=True)
    (sandbox / "node_modules").mkdir(exist_ok=True)  # must be pruned

    # known sizes so totals + ordering are deterministic
    (sandbox / "big" / "a.bin").write_bytes(b"x" * 4096)
    (sandbox / "big" / "b.bin").write_bytes(b"x" * 4096)      # big = 8192 B
    (sandbox / "small" / "c.bin").write_bytes(b"x" * 100)     # small = 100 B
    (sandbox / "top.bin").write_bytes(b"x" * 500)             # a top-level file
    (sandbox / "node_modules" / "junk.bin").write_bytes(b"x" * 999999)

    try:
        def totals_and_pruning():
            out = registry.dispatch("folder_size", {"folder": "jarvis_disk_smoke"})
            # 4 real files counted (a, b, c, top); node_modules pruned entirely
            assert "4 files" in out, out
            assert "node_modules" not in out, "pruned dir leaked into output"
            # biggest item first: the 'big/' folder (8192 B) beats everything
            first_line = [ln for ln in out.splitlines() if ln.startswith("- ")][0]
            assert first_line.startswith("- big/"), first_line
            return "total + prune + biggest-first ok"
        check("folder_size totals + pruning + ordering", totals_and_pruning)

        def default_is_whole_home():
            # no folder arg is valid: it measures the whole home folder
            out = registry.dispatch("folder_size", {})
            assert "home folder" in out, out
            assert "Error" not in out, out
            return "no-arg -> whole home"
        check("folder_size default (whole home)", default_is_whole_home)

        def single_file():
            # pointed at a file, it reports just that file's size
            out = registry.dispatch("folder_size",
                {"folder": "jarvis_disk_smoke/top.bin"})
            assert "top.bin is 500 B" in out, out
            return "single file size reported"
        check("folder_size on a single file", single_file)

        def empty_folder():
            (sandbox / "empty").mkdir(exist_ok=True)
            out = registry.dispatch("folder_size", {"folder": "jarvis_disk_smoke/empty"})
            assert "empty" in out and "0 B" in out, out
            return "empty folder -> 0 B"
        check("folder_size empty folder", empty_folder)

        def alt_arg_names():
            out = registry.dispatch("folder_size", {"path": "jarvis_disk_smoke"})
            assert "4 files" in out, out
            out2 = registry.dispatch("folder_size", {"directory": "jarvis_disk_smoke"})
            assert "4 files" in out2, out2
            return "alt path/directory arg names handled"
        check("folder_size alt arg names", alt_arg_names)

        def containment_guard():
            # measuring OUTSIDE the user's home must be refused
            r = registry.dispatch("folder_size", {"folder": "C:\\Windows"})
            assert "only work inside your own folders" in r, r
            # a ..-escape out of home is also refused (resolved + re-checked)
            r2 = registry.dispatch("folder_size",
                {"folder": "jarvis_disk_smoke/../../../Windows"})
            assert "only work inside your own folders" in r2, r2
            return "escape outside home blocked"
        check("folder_size containment guard", containment_guard)

        def missing_folder():
            r = registry.dispatch("folder_size", {"folder": "jarvis_disk_smoke/nope"})
            assert "can't find" in r, r
            return "missing folder -> friendly message"
        check("folder_size missing folder", missing_folder)

        def output_is_ascii():
            registry.dispatch("folder_size", {"folder": "jarvis_disk_smoke"}).encode("ascii")
            registry.dispatch("folder_size", {}).encode("ascii")
            return "output stayed pure ASCII"
        check("folder_size ascii-only output", output_is_ascii)

        def hallucination_guards():
            # wrong types / weird shapes must not raise
            registry.dispatch("folder_size", {"folder": 123})
            registry.dispatch("folder_size", {"folder": ["a"]})
            registry.dispatch("folder_size", {"folder": {}})
            registry.dispatch("folder_size", {"folder": None})
            # an unexpected extra arg is dropped, call still succeeds
            out = registry.dispatch("folder_size",
                {"folder": "jarvis_disk_smoke", "reason": "curious"})
            assert "4 files" in out, out
            return "guards held"
        check("folder_size hallucination guards", hallucination_guards)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def t_document():
    """Exercises the read_document tool (read Word .docx / OpenDocument .odt) +
    its defenses against 8B hallucinations. Builds real .docx/.odt zips inside a
    temp tree in the user's home, so it is deterministic, needs no model, and
    lives in the safe set."""
    import os
    import pathlib
    import shutil
    import zipfile
    from jarvis.tools import document  # noqa: F401  (register read_document)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_doc_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)
    sandbox.mkdir(parents=True, exist_ok=True)

    WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def _make_docx(name, paras):
        body = "".join(
            f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
        xml = (f'<?xml version="1.0"?><w:document xmlns:w="{WNS}">'
               f"<w:body>{body}</w:body></w:document>")
        with zipfile.ZipFile(sandbox / name, "w") as z:
            z.writestr("word/document.xml", xml)

    # a normal document, plus one with Word's curly quotes / em-dash / accent to
    # prove the ASCII transliteration.
    _make_docx("report.docx",
               ["Hello sir, this is the budget report.",
                "Total is “1200” euros — for the café."])
    _make_docx("empty.docx", [""])

    ONS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    with zipfile.ZipFile(sandbox / "notes.odt", "w") as z:
        z.writestr("content.xml",
                   f'<?xml version="1.0"?><doc xmlns:text="{ONS}">'
                   f"<text:h>Meeting notes</text:h>"
                   f"<text:p>Buy milk and bread.</text:p></doc>")

    try:
        def happy_docx():
            out = registry.dispatch("read_document", {"path": "jarvis_doc_smoke/report.docx"})
            assert "Hello sir, this is the budget report." in out, out
            assert "word" in out and "report.docx" in out, out  # header
            return "docx text extracted"
        check("read_document reads a .docx", happy_docx)

        def ascii_transliteration():
            out = registry.dispatch("read_document", {"path": "jarvis_doc_smoke/report.docx"})
            out.encode("ascii")  # must be pure ASCII (would raise otherwise)
            assert '"1200"' in out, out          # curly quotes -> straight
            assert "cafe" in out, out            # accent stripped, not 'caf?'
            assert "—" not in out and "?" not in out, out
            return "curly quotes/dash/accent -> clean ASCII"
        check("read_document ascii-only output", ascii_transliteration)

        def reads_odt():
            out = registry.dispatch("read_document", {"path": "jarvis_doc_smoke/notes.odt"})
            assert "Meeting notes" in out and "Buy milk and bread." in out, out
            return "odt text extracted"
        check("read_document reads a .odt", reads_odt)

        def empty_document():
            out = registry.dispatch("read_document", {"path": "jarvis_doc_smoke/empty.docx"})
            assert "no readable text" in out, out
            return "empty doc -> friendly message"
        check("read_document empty document", empty_document)

        def alt_arg_names():
            out = registry.dispatch("read_document", {"file": "jarvis_doc_smoke/report.docx"})
            assert "budget report" in out, out
            out2 = registry.dispatch("read_document", {"document": "jarvis_doc_smoke/report.docx"})
            assert "budget report" in out2, out2
            return "alt file/document arg names handled"
        check("read_document alt arg names", alt_arg_names)

        def unsupported_types():
            (sandbox / "x.pdf").write_bytes(b"%PDF-1.4 fake")
            r = registry.dispatch("read_document", {"path": "jarvis_doc_smoke/x.pdf"})
            assert "PDF" in r and "Error" in r, r
            (sandbox / "plain.txt").write_text("hi")
            r2 = registry.dispatch("read_document", {"path": "jarvis_doc_smoke/plain.txt"})
            assert "read_file" in r2, r2
            return "pdf + plain-text steered elsewhere"
        check("read_document unsupported types", unsupported_types)

        def corrupt_document():
            (sandbox / "bad.docx").write_bytes(b"this is not a zip at all")
            r = registry.dispatch("read_document", {"path": "jarvis_doc_smoke/bad.docx"})
            assert "corrupt" in r or "isn't a valid" in r, r
            return "corrupt/non-zip -> friendly, no raise"
        check("read_document corrupt document", corrupt_document)

        def containment_guard():
            r = registry.dispatch("read_document", {"path": "C:\\Windows\\explorer.exe"})
            assert "only work inside your own folders" in r, r
            r2 = registry.dispatch("read_document",
                {"path": "jarvis_doc_smoke/../../../Windows/x.docx"})
            assert "only work inside your own folders" in r2, r2
            return "escape outside home blocked"
        check("read_document containment guard", containment_guard)

        def folder_and_missing():
            r = registry.dispatch("read_document", {"path": "jarvis_doc_smoke"})
            assert "is a folder" in r, r
            r2 = registry.dispatch("read_document", {"path": "jarvis_doc_smoke/nope.docx"})
            assert "can't find" in r2, r2
            return "folder + missing -> friendly messages"
        check("read_document folder/missing guards", folder_and_missing)

        def size_and_xml_caps():
            # shrink the uncompressed-xml cap: a normal doc is now refused as a
            # zip-bomb guard (returns empty-text message, never raises/hangs).
            orig = document.MAX_XML_BYTES
            document.MAX_XML_BYTES = 1
            try:
                r = registry.dispatch("read_document", {"path": "jarvis_doc_smoke/report.docx"})
                assert "no readable text" in r, r
            finally:
                document.MAX_XML_BYTES = orig
            return "oversized document part refused"
        check("read_document xml/size caps", size_and_xml_caps)

        def truncation():
            orig = document.MAX_CHARS
            document.MAX_CHARS = 10
            try:
                r = registry.dispatch("read_document", {"path": "jarvis_doc_smoke/report.docx"})
                assert "[truncated]" in r, r
            finally:
                document.MAX_CHARS = orig
            return "long document truncated with a note"
        check("read_document truncation", truncation)

        def hallucination_guards():
            # wrong types / weird shapes must not raise
            registry.dispatch("read_document", {"path": 123})
            registry.dispatch("read_document", {"path": ["a"]})
            registry.dispatch("read_document", {"path": {}})
            registry.dispatch("read_document", {"path": None})
            assert "Error" in registry.dispatch("read_document", {"path": ""})
            assert "Error" in registry.dispatch("read_document", {})  # missing arg
            # an unexpected extra arg is dropped, call still succeeds
            out = registry.dispatch("read_document",
                {"path": "jarvis_doc_smoke/report.docx", "reason": "curious"})
            assert "budget report" in out, out
            return "guards held"
        check("read_document hallucination guards", hallucination_guards)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def t_explorer():
    """Exercises the open_folder tool (reveal in Explorer) + its defenses against
    8B hallucinations. The real Explorer launch is swapped for a hermetic fake
    that just records what would have been opened, so nothing actually pops up;
    everything runs inside a temp tree in the user's home, so the test is
    deterministic, needs no model, and lives in the safe set."""
    import os
    import pathlib
    import shutil
    from jarvis.tools import explorer  # noqa: F401  (register open_folder)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_explorer_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)
    (sandbox / "sub").mkdir(parents=True, exist_ok=True)
    (sandbox / "sub" / "report.txt").write_text("hello", encoding="utf-8")

    # hermetic fake: record the (path, is_file) that WOULD be opened instead of
    # actually launching an Explorer window.
    opened = []
    real_reveal = explorer._reveal
    explorer._reveal = lambda path, is_file: opened.append((str(path), is_file))

    try:
        def open_a_folder():
            opened.clear()
            out = registry.dispatch("open_folder", {"folder": "jarvis_explorer_smoke"})
            assert "Opened" in out and "Error" not in out, out
            assert len(opened) == 1 and opened[0][1] is False, opened
            assert opened[0][0].endswith("jarvis_explorer_smoke"), opened
            return "folder opened (not as a file)"
        check("open_folder opens a folder", open_a_folder)

        def reveal_a_file():
            opened.clear()
            out = registry.dispatch("open_folder",
                {"folder": "jarvis_explorer_smoke/sub/report.txt"})
            assert "highlighted" in out and "Error" not in out, out
            # a file is revealed (is_file True), pointing at the file itself
            assert len(opened) == 1 and opened[0][1] is True, opened
            assert opened[0][0].endswith("report.txt"), opened
            return "file revealed + highlighted"
        check("open_folder reveals a file", reveal_a_file)

        def default_is_home():
            opened.clear()
            out = registry.dispatch("open_folder", {})
            assert "home folder" in out and "Error" not in out, out
            assert len(opened) == 1 and opened[0][1] is False, opened
            return "no-arg -> home folder"
        check("open_folder default (home)", default_is_home)

        def alt_arg_names():
            opened.clear()
            out = registry.dispatch("open_folder", {"path": "jarvis_explorer_smoke"})
            assert "Opened" in out, out
            out2 = registry.dispatch("open_folder", {"directory": "jarvis_explorer_smoke/sub"})
            assert "Opened" in out2, out2
            return "alt path/directory arg names handled"
        check("open_folder alt arg names", alt_arg_names)

        def containment_guard():
            opened.clear()
            # opening OUTSIDE the user's home must be refused (nothing launched)
            r = registry.dispatch("open_folder", {"folder": "C:\\Windows"})
            assert "only work inside your own folders" in r, r
            # a ..-escape out of home is also refused (resolved + re-checked)
            r2 = registry.dispatch("open_folder",
                {"folder": "jarvis_explorer_smoke/../../../Windows"})
            assert "only work inside your own folders" in r2, r2
            assert opened == [], "a blocked path must never launch Explorer"
            return "escape outside home blocked, nothing launched"
        check("open_folder containment guard", containment_guard)

        def missing_target():
            opened.clear()
            r = registry.dispatch("open_folder", {"folder": "jarvis_explorer_smoke/nope"})
            assert "can't find" in r, r
            assert opened == [], "a missing target must never launch Explorer"
            return "missing target -> friendly message"
        check("open_folder missing target", missing_target)

        def launch_failure_guard():
            # if the OS launch itself blows up, it must come back as a friendly
            # string, never raise or crash the agent.
            opened.clear()
            def boom(path, is_file):
                raise OSError("explorer exploded")
            explorer._reveal = boom
            try:
                r = registry.dispatch("open_folder", {"folder": "jarvis_explorer_smoke"})
                assert "Error" in r and "couldn't open" in r, r
            finally:
                explorer._reveal = lambda path, is_file: opened.append((str(path), is_file))
            return "OS launch failure surfaced as a message"
        check("open_folder launch-failure guard", launch_failure_guard)

        def output_is_ascii():
            registry.dispatch("open_folder", {"folder": "jarvis_explorer_smoke"}).encode("ascii")
            registry.dispatch("open_folder", {}).encode("ascii")
            registry.dispatch("open_folder", {"folder": "C:\\Windows"}).encode("ascii")
            return "output stayed pure ASCII"
        check("open_folder ascii-only output", output_is_ascii)

        def hallucination_guards():
            # wrong types / weird shapes must not raise
            registry.dispatch("open_folder", {"folder": 123})
            registry.dispatch("open_folder", {"folder": ["a"]})
            registry.dispatch("open_folder", {"folder": {}})
            registry.dispatch("open_folder", {"folder": None})
            # an unexpected extra arg is dropped, the call still succeeds
            opened.clear()
            out = registry.dispatch("open_folder",
                {"folder": "jarvis_explorer_smoke", "reason": "curious"})
            assert "Opened" in out, out
            return "guards held"
        check("open_folder hallucination guards", hallucination_guards)
    finally:
        explorer._reveal = real_reveal
        shutil.rmtree(sandbox, ignore_errors=True)


def t_archive():
    """Exercises the zip_files tool (backup/archive) + its defenses against 8B
    hallucinations. Works entirely inside a temp tree in the user's home (the
    only place it touches), so it is deterministic, needs no model, and lives in
    the safe set."""
    import os
    import pathlib
    import shutil
    import zipfile
    from jarvis.tools import archive as arc  # noqa: F401  (register)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_archive_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)
    (sandbox / "sub").mkdir(parents=True, exist_ok=True)

    def mk(rel, text="x"):
        p = sandbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    mk("a.txt", "hello")
    mk("sub/b.txt", "world")
    # a pruned dir whose file must NOT be swept into the archive
    (sandbox / "node_modules").mkdir(exist_ok=True)
    (sandbox / "node_modules" / "junk.txt").write_text("junk", encoding="utf-8")

    saved_total = arc.MAX_TOTAL_BYTES

    def _zpath(name):
        return home / name

    try:
        def zip_a_folder():
            out = registry.dispatch("zip_files",
                {"sources": "jarvis_archive_smoke", "dest": "jarvis_archive_bk.zip"})
            assert "Backed up" in out, out
            z = _zpath("jarvis_archive_bk.zip")
            assert z.exists(), "archive not created"
            with zipfile.ZipFile(z) as zf:
                names = zf.namelist()
            # both real files present; node_modules pruned; original stays put
            assert any(n.endswith("a.txt") for n in names), names
            assert any(n.endswith("b.txt") for n in names), names
            assert not any("junk.txt" in n for n in names), f"noise dir not pruned: {names}"
            assert (sandbox / "a.txt").exists(), "original vanished"
            z.unlink()
            return "zipped a folder, pruned noise, originals kept"
        check("archive zip folder", zip_a_folder)

        def zip_several_files():
            # a comma-separated list of files is accepted
            out = registry.dispatch("zip_files",
                {"sources": "jarvis_archive_smoke/a.txt, jarvis_archive_smoke/sub/b.txt",
                 "dest": "two_files"})   # missing .zip suffix is added
            assert "Backed up 2 files" in out, out
            z = _zpath("two_files.zip")
            assert z.exists(), "archive not created / .zip suffix not added"
            z.unlink()
            return "zipped several files, .zip suffix added"
        check("archive zip several files", zip_several_files)

        def alt_arg_names():
            # the model may use 'files'/'to' instead of sources/dest
            out = registry.dispatch("zip_files",
                {"files": "jarvis_archive_smoke/a.txt", "to": "alt_backup.zip"})
            assert "Backed up" in out, out
            _zpath("alt_backup.zip").unlink()
            return "alt files/to arg names handled"
        check("archive alt arg names", alt_arg_names)

        def never_overwrites():
            z = _zpath("keep.zip")
            z.write_text("existing", encoding="utf-8")
            out = registry.dispatch("zip_files",
                {"sources": "jarvis_archive_smoke/a.txt", "dest": "keep.zip"})
            assert "won't overwrite" in out, out
            assert z.read_text(encoding="utf-8") == "existing", "clobbered!"
            z.unlink()
            return "refuses to overwrite an existing archive"
        check("archive never overwrites", never_overwrites)

        def containment_guard():
            # a source outside home is skipped, a dest outside home is refused
            src = registry.dispatch("zip_files",
                {"sources": "C:\\Windows\\notepad.exe", "dest": "w.zip"})
            assert "nothing to back up" in src, src
            assert not _zpath("w.zip").exists()
            dst = registry.dispatch("zip_files",
                {"sources": "jarvis_archive_smoke/a.txt", "dest": "C:\\Windows\\x.zip"})
            assert "only work inside your own folders" in dst, dst
            return "escape outside home blocked (source + dest)"
        check("archive containment guard", containment_guard)

        def size_cap():
            arc.MAX_TOTAL_BYTES = 4              # temporarily tiny
            mk("big.txt", "0123456789")          # 10 bytes > 4
            out = registry.dispatch("zip_files",
                {"sources": "jarvis_archive_smoke/big.txt", "dest": "big.zip"})
            # the only file exceeds the cap -> nothing to back up, no archive
            assert "nothing to back up" in out or "too big" in out, out
            assert not _zpath("big.zip").exists()
            arc.MAX_TOTAL_BYTES = saved_total
            return "oversized backup refused, no partial archive"
        check("archive size cap", size_cap)

        def output_is_ascii():
            registry.dispatch("zip_files",
                {"sources": "jarvis_archive_smoke/a.txt", "dest": "ascii_bk.zip"}).encode("ascii")
            p = _zpath("ascii_bk.zip")
            if p.exists():
                p.unlink()
            return "output stayed pure ASCII"
        check("archive ascii-only output", output_is_ascii)

        def hallucination_guards():
            # empty / missing args -> friendly error, never a crash, no archive
            assert "Error" in registry.dispatch("zip_files", {"sources": "", "dest": "x.zip"})
            assert "Error" in registry.dispatch("zip_files", {"sources": "jarvis_archive_smoke", "dest": ""})
            assert "Error" in registry.dispatch("zip_files", {})
            # a non-existent source is a friendly message, not a crash
            miss = registry.dispatch("zip_files",
                {"sources": "jarvis_archive_smoke/ghost.txt", "dest": "g.zip"})
            assert "nothing to back up" in miss, miss
            assert not _zpath("g.zip").exists()
            # wrong types must not raise
            registry.dispatch("zip_files", {"sources": 123, "dest": 456})
            registry.dispatch("zip_files", {"sources": ["a"], "dest": {}})
            # a list source shape is accepted (JSON array from the model)
            out = registry.dispatch("zip_files",
                {"sources": ["jarvis_archive_smoke/a.txt"], "dest": "listshape.zip"})
            assert "Backed up" in out, out
            _zpath("listshape.zip").unlink()
            return "guards held"
        check("archive hallucination guards", hallucination_guards)
    finally:
        arc.MAX_TOTAL_BYTES = saved_total
        shutil.rmtree(sandbox, ignore_errors=True)
        for leftover in ("jarvis_archive_bk.zip", "two_files.zip", "alt_backup.zip",
                         "keep.zip", "w.zip", "x.zip", "g.zip", "big.zip",
                         "456.zip", "ascii_bk.zip", "listshape.zip"):
            p = home / leftover
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass


def t_extract():
    """Exercises the unzip_files tool (extract/unpack) + its defenses against 8B
    hallucinations and hostile archives (zip-slip, never-overwrite). Works
    entirely inside a temp tree in the user's home, crafts its own .zip files, so
    it is deterministic, needs no model, and lives in the safe set."""
    import os
    import pathlib
    import shutil
    import zipfile
    from jarvis.tools import extract as ext  # noqa: F401  (register)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_extract_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)
    sandbox.mkdir(parents=True, exist_ok=True)
    escape_marker = home / "jarvis_extract_escaped.txt"

    def mkzip(relname, entries):
        """entries: list of (arcname, data). Written under the sandbox."""
        zp = sandbox / relname
        zp.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for arc, data in entries:
                zf.writestr(arc, data)
        return zp

    try:
        if escape_marker.exists():
            escape_marker.unlink()

        # a normal archive with a nested folder
        mkzip("good.zip", [("a.txt", "hello"),
                           ("sub/b.txt", "world")])

        def extract_default_folder():
            out = registry.dispatch("unzip_files",
                {"source": "jarvis_extract_smoke/good.zip"})
            assert "Extracted 2 files" in out, out
            # default dest is a folder named after the archive, beside it
            d = sandbox / "good"
            assert (d / "a.txt").read_text(encoding="utf-8") == "hello", out
            assert (d / "sub" / "b.txt").read_text(encoding="utf-8") == "world", out
            # the archive itself is left in place
            assert (sandbox / "good.zip").exists(), "archive vanished"
            shutil.rmtree(d, ignore_errors=True)
            return "extracted into a default folder, archive kept"
        check("extract default folder", extract_default_folder)

        def extract_named_dest():
            out = registry.dispatch("unzip_files",
                {"source": "jarvis_extract_smoke/good.zip",
                 "dest": "jarvis_extract_smoke/out"})
            assert "Extracted" in out, out
            assert (sandbox / "out" / "a.txt").exists(), out
            return "extracted into a named folder"
        check("extract named dest", extract_named_dest)

        def never_overwrites():
            # a file already at the target is skipped, not clobbered
            (sandbox / "out" / "a.txt").write_text("KEEP", encoding="utf-8")
            out = registry.dispatch("unzip_files",
                {"source": "jarvis_extract_smoke/good.zip",
                 "dest": "jarvis_extract_smoke/out"})
            assert (sandbox / "out" / "a.txt").read_text(encoding="utf-8") == "KEEP", out
            assert "already existed" in out or "already extracted" in out, out
            return "existing files never overwritten"
        check("extract never overwrites", never_overwrites)

        def zip_slip_blocked():
            # a hostile entry tries to escape the extract folder with ../../
            mkzip("evil.zip", [("safe.txt", "ok"),
                               ("../../jarvis_extract_escaped.txt", "PWNED")])
            out = registry.dispatch("unzip_files",
                {"source": "jarvis_extract_smoke/evil.zip",
                 "dest": "jarvis_extract_smoke/evilout"})
            # the safe file lands inside, the escaping one is refused
            assert (sandbox / "evilout" / "safe.txt").exists(), out
            assert not escape_marker.exists(), "ZIP-SLIP ESCAPED THE FOLDER"
            assert "couldn't safely unpack" in out or "skipped" in out, out
            return "zip-slip entry blocked, stayed inside the folder"
        check("extract zip-slip blocked", zip_slip_blocked)

        def containment_guard():
            # source outside home refused; dest outside home refused
            s = registry.dispatch("unzip_files", {"source": "C:\\Windows\\x.zip"})
            assert "only work inside your own folders" in s or "can't find" in s, s
            d = registry.dispatch("unzip_files",
                {"source": "jarvis_extract_smoke/good.zip", "dest": "C:\\Windows\\out"})
            assert "only work inside your own folders" in d, d
            return "escape outside home blocked (source + dest)"
        check("extract containment guard", containment_guard)

        def bad_zip():
            (sandbox / "notzip.zip").write_text("this is not a zip", encoding="utf-8")
            out = registry.dispatch("unzip_files",
                {"source": "jarvis_extract_smoke/notzip.zip"})
            assert "isn't a valid .zip" in out, out
            return "corrupt archive reported, not crashed"
        check("extract bad zip", bad_zip)

        def alt_arg_names():
            out = registry.dispatch("unzip_files",
                {"archive": "jarvis_extract_smoke/good.zip", "into": "jarvis_extract_smoke/alt"})
            assert "Extracted" in out, out
            assert (sandbox / "alt" / "a.txt").exists(), out
            return "alt archive/into arg names handled"
        check("extract alt arg names", alt_arg_names)

        def output_is_ascii():
            registry.dispatch("unzip_files",
                {"source": "jarvis_extract_smoke/good.zip",
                 "dest": "jarvis_extract_smoke/asciiout"}).encode("ascii")
            return "output stayed pure ASCII"
        check("extract ascii-only output", output_is_ascii)

        def hallucination_guards():
            assert "Error" in registry.dispatch("unzip_files", {"source": ""})
            assert "Error" in registry.dispatch("unzip_files", {})
            miss = registry.dispatch("unzip_files",
                {"source": "jarvis_extract_smoke/ghost.zip"})
            assert "can't find" in miss, miss
            folder = registry.dispatch("unzip_files", {"source": "jarvis_extract_smoke"})
            assert "not a .zip" in folder or "folder" in folder, folder
            # wrong types must not raise
            registry.dispatch("unzip_files", {"source": 123, "dest": 456})
            registry.dispatch("unzip_files", {"source": ["a"], "dest": {}})
            assert not escape_marker.exists(), "escape happened during guards"
            return "guards held"
        check("extract hallucination guards", hallucination_guards)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
        if escape_marker.exists():
            try:
                escape_marker.unlink()
            except OSError:
                pass


def t_recycle():
    """Exercises the recycle_file tool (safe, undoable delete) + its defenses
    against 8B hallucinations. The real Recycle Bin call is swapped for a
    hermetic fake that moves the file into a sandbox 'trash' folder, so the test
    is deterministic, needs no model, never touches the user's real bin, and
    lives in the safe set."""
    import os
    import pathlib
    import shutil
    from jarvis.tools import recycle as rec  # noqa: F401  (register)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_recycle_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)
    (sandbox / "sub").mkdir(parents=True, exist_ok=True)
    trash = sandbox / "_fake_trash"
    trash.mkdir(exist_ok=True)

    def mk(rel, text="x"):
        p = sandbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    # hermetic fake: "recycle" == move into the sandbox trash (undoable, and it
    # never touches the user's real Recycle Bin)
    def fake_recycle(path):
        src = pathlib.Path(path)
        shutil.move(str(src), str(trash / src.name))

    saved_recycler = rec._send_to_recycle_bin
    saved_cap = rec.MAX_RECYCLE_BYTES
    rec._send_to_recycle_bin = fake_recycle
    try:
        def happy_path():
            mk("draft.txt", "old draft")
            out = registry.dispatch("recycle_file",
                {"path": "jarvis_recycle_smoke/draft.txt"})
            assert "Recycle Bin" in out and "restore" in out, out
            # the file left its place (removed from source)...
            assert not (sandbox / "draft.txt").exists(), "file not removed"
            # ...and is recoverable (our fake bin has it) -> nothing destroyed
            assert (trash / "draft.txt").exists(), "file not recoverable"
            return "sent a file to the (fake) bin, recoverable"
        check("recycle happy path", happy_path)

        def alt_arg_names():
            # the model may pass file=/source= instead of path
            mk("alt.txt")
            out = registry.dispatch("recycle_file",
                {"file": "jarvis_recycle_smoke/alt.txt"})
            assert "Recycle Bin" in out, out
            assert not (sandbox / "alt.txt").exists()
            return "alt file/source arg names handled"
        check("recycle alt arg names", alt_arg_names)

        def containment_guard():
            # a file OUTSIDE the user's home must be refused, never binned
            r = registry.dispatch("recycle_file", {"path": "C:\\Windows\\notepad.exe"})
            assert "only work inside your own folders" in r, r
            return "escape outside home blocked"
        check("recycle containment guard", containment_guard)

        def refuses_directory():
            r = registry.dispatch("recycle_file", {"path": "jarvis_recycle_smoke/sub"})
            assert "folder" in r and "whole folders" in r, r
            assert (sandbox / "sub").exists(), "folder was binned!"
            return "a folder is refused"
        check("recycle refuses directory", refuses_directory)

        def missing_source_is_friendly():
            r = registry.dispatch("recycle_file",
                {"path": "jarvis_recycle_smoke/ghost.txt"})
            assert "can't find" in r, r
            return "missing source is a friendly message"
        check("recycle missing source", missing_source_is_friendly)

        def size_cap():
            rec.MAX_RECYCLE_BYTES = 4              # temporarily tiny
            mk("big.txt", "0123456789")            # 10 bytes > 4
            r = registry.dispatch("recycle_file",
                {"path": "jarvis_recycle_smoke/big.txt"})
            assert "too large" in r, r
            # refused: the file is left exactly where it was, never touched
            assert (sandbox / "big.txt").exists(), "oversized file was binned"
            rec.MAX_RECYCLE_BYTES = saved_cap
            return "oversized delete refused, file kept"
        check("recycle size cap", size_cap)

        def recycler_failure_is_friendly():
            # if the OS delete itself fails, it's a friendly message, not a crash
            def boom(path):
                raise OSError("bin unavailable")
            rec._send_to_recycle_bin = boom
            mk("stay.txt")
            r = registry.dispatch("recycle_file",
                {"path": "jarvis_recycle_smoke/stay.txt"})
            assert "couldn't delete it" in r, r
            assert (sandbox / "stay.txt").exists(), "file vanished despite failure"
            rec._send_to_recycle_bin = fake_recycle
            return "OS failure surfaced, file kept"
        check("recycle os-failure guard", recycler_failure_is_friendly)

        def output_is_ascii():
            mk("asc.txt")
            registry.dispatch("recycle_file",
                {"path": "jarvis_recycle_smoke/asc.txt"}).encode("ascii")
            return "output stayed pure ASCII"
        check("recycle ascii-only output", output_is_ascii)

        def hallucination_guards():
            # empty / missing args -> friendly error, never a crash, never a bin
            assert "Error" in registry.dispatch("recycle_file", {"path": ""})
            assert "Error" in registry.dispatch("recycle_file", {"path": "   "})
            assert "Error" in registry.dispatch("recycle_file", {})
            # wrong types must not raise
            registry.dispatch("recycle_file", {"path": 123})
            registry.dispatch("recycle_file", {"path": ["a"]})
            registry.dispatch("recycle_file", {"path": {}})
            return "guards held"
        check("recycle hallucination guards", hallucination_guards)
    finally:
        rec._send_to_recycle_bin = saved_recycler
        rec.MAX_RECYCLE_BYTES = saved_cap
        shutil.rmtree(sandbox, ignore_errors=True)


def t_clipboard():
    """Exercises the clipboard tools + their defenses against 8B
    hallucinations. No model needed, so it lives in the safe set. The user's
    current clipboard text is saved and restored so the cycle is non-invasive."""
    from jarvis.tools import clipboard as clip  # noqa: F401  (register)
    from jarvis.tools import registry

    # save whatever the user currently has, to restore afterwards
    saved_text, _ = clip._read_clipboard_text()

    try:
        def round_trip():
            marker = "Jarvis clipboard smoke test 12345"
            out = registry.dispatch("set_clipboard", {"text": marker})
            assert "Copied" in out, out
            back = registry.dispatch("get_clipboard", {})
            assert marker in back, back
            return "set -> get round-trip ok"
        check("clipboard round-trip", round_trip)

        def hallucination_guards():
            # empty / missing / wrong-type text must not crash or store junk
            assert "Error" in registry.dispatch("set_clipboard", {"text": ""})
            assert "Error" in registry.dispatch("set_clipboard", {})
            # wrong type is coerced, not crashed
            assert "Copied" in registry.dispatch("set_clipboard", {"text": 42})
            assert "42" in registry.dispatch("get_clipboard", {})
            # oversized write is rejected, not dumped into memory
            big = registry.dispatch("set_clipboard", {"text": "x" * (clip.MAX_WRITE + 10)})
            assert "too much" in big, big
            return f"guards held (max_write={clip.MAX_WRITE})"
        check("clipboard hallucination guards", hallucination_guards)

        def read_is_bounded():
            # a huge clipboard is truncated on read, never returned unbounded
            registry.dispatch("set_clipboard", {"text": "y" * (clip.MAX_READ + 500)})
            out = registry.dispatch("get_clipboard", {})
            assert "truncated" in out, "large clipboard not truncated"
            assert len(out) < clip.MAX_READ + 200, "read not bounded"
            return "large read truncated"
        check("clipboard read bounded", read_is_bounded)
    finally:
        # restore the user's original clipboard text if we had it
        if saved_text:
            clip._write_clipboard_text(saved_text)


def t_tasks():
    """Exercises the to-do list tools + their defenses against 8B
    hallucinations. No model needed, so it lives in the safe set."""
    from jarvis.tools import tasks as tk
    from jarvis.tools import registry

    # isolate: use a temp store so we never touch the user's real to-do list
    import tempfile, os, pathlib
    tk._STORE = pathlib.Path(tempfile.gettempdir()) / "jarvis_tasks_smoke.json"
    for p in (tk._STORE, tk._STORE.with_name("tasks.corrupt.json")):
        if p.exists():
            os.remove(p)

    def happy_path():
        assert "Added" in registry.dispatch("add_task", {"task": "buy milk"})
        assert "Added" in registry.dispatch("add_task", {"task": "call the plumber"})
        assert tk.open_count() == 2
        out = registry.dispatch("list_tasks", {})
        assert "buy milk" in out and "call the plumber" in out, out
        # open tasks show up in the injected preamble
        assert "buy milk" in tk.tasks_preamble()
        return "add/list/preamble ok"
    check("tasks happy path", happy_path)

    def dedup():
        registry.dispatch("add_task", {"task": "buy milk"})
        return f"count still {tk.open_count()} (deduped)" if tk.open_count() == 2 \
            else (_ for _ in ()).throw(AssertionError("duplicate stored"))
    check("tasks dedup", dedup)

    def complete_flow():
        # by substring
        assert "Marked done" in registry.dispatch("complete_task", {"task": "milk"})
        assert tk.open_count() == 1
        # completed one no longer counts as open, shows under done
        done = registry.dispatch("list_tasks", {"which": "done"})
        assert "buy milk" in done and "[x]" in done, done
        # by number (1-based, against the open list)
        assert "Marked done" in registry.dispatch("complete_task", {"task": "1"})
        assert tk.open_count() == 0
        assert "all clear" in registry.dispatch("list_tasks", {})
        return "complete by text + number ok"
    check("tasks complete", complete_flow)

    def hallucination_guards():
        # empty / whitespace / wrong-type args must NOT crash or store junk
        assert "Error" in registry.dispatch("add_task", {"task": "   "})
        assert "Error" in registry.dispatch("add_task", {"task": ""})
        assert registry.dispatch("add_task", {}).startswith(("Error", "Added", "That is"))
        assert "Error" in registry.dispatch("complete_task", {"task": ""})
        assert "Error" in registry.dispatch("remove_task", {"task": ""})
        # wrong types must not raise
        registry.dispatch("add_task", {"task": 123})
        registry.dispatch("list_tasks", {"which": 5})
        # over-long task is truncated, not rejected or unbounded
        long = registry.dispatch("add_task", {"task": "x" * 5000})
        assert "shortened" in long, long
        # a bad number is a friendly message, not a crash
        assert "no task number" in registry.dispatch("complete_task", {"task": "999"})
        return f"guards held, open={tk.open_count()}"
    check("tasks hallucination guards", hallucination_guards)

    def remove_flow():
        # add a known removable task, then delete it by substring
        registry.dispatch("add_task", {"task": "return library book"})
        before = tk.open_count()
        assert "Removed" in registry.dispatch("remove_task", {"task": "library"})
        assert tk.open_count() == before - 1
        # a no-match delete is a friendly message, not a crash
        assert "Nothing" in registry.dispatch("remove_task", {"task": "zzzznope"})
        return "remove ok"
    check("tasks remove", remove_flow)

    def corrupt_store_recovers():
        tk._STORE.write_text("{ not valid json ", encoding="utf-8")
        # _load must not raise; corrupt file set aside, store treated as empty
        assert tk.open_count() == 0
        assert tk._STORE.with_name("tasks.corrupt.json").exists()
        return "corrupt store recovered"
    check("tasks corrupt-store recovery", corrupt_store_recovers)


def t_calc():
    """Exercises the calculate tool + its defenses against 8B hallucinations.
    No model needed, so it lives in the safe set."""
    from jarvis.tools import calc  # noqa: F401  (register)
    from jarvis.tools import registry

    def happy_path():
        assert registry.dispatch("calculate", {"expression": "2 + 2"}).endswith("4")
        assert registry.dispatch("calculate", {"expression": "(1250 * 1.2) / 3"}).endswith("500")
        assert registry.dispatch("calculate", {"expression": "3 ** 2"}).endswith("9")
        assert registry.dispatch("calculate", {"expression": "sqrt(144)"}).endswith("12")
        assert registry.dispatch("calculate", {"expression": "15/100 * 240"}).endswith("36")
        return "arithmetic + functions ok"
    check("calc happy path", happy_path)

    def constants_and_rounding():
        out = registry.dispatch("calculate", {"expression": "round(pi, 2)"})
        assert "3.14" in out, out
        # a whole-valued float renders as an int, not '12.0'
        assert registry.dispatch("calculate", {"expression": "10 / 2"}).endswith("5")
        return "constants + rounding ok"
    check("calc constants and formatting", constants_and_rounding)

    def rejects_code_execution():
        # hallucinated code-injection attempts must be refused, never run
        for evil in ("__import__('os').system('dir')", "open('x','w')",
                     "1 if True else 2", "[i for i in range(9)]",
                     "os.getcwd()", "eval('2+2')", "pi.__class__"):
            r = registry.dispatch("calculate", {"expression": evil})
            assert "Error" in r, f"{evil!r} not refused: {r}"
        return "code execution refused"
    check("calc rejects code", rejects_code_execution)

    def bounds_and_guards():
        # divide by zero -> friendly, not a crash
        assert "zero" in registry.dispatch("calculate", {"expression": "1/0"})
        # runaway power / factorial are capped, not hung
        assert "Error" in registry.dispatch("calculate", {"expression": "9 ** 9 ** 9"})
        assert "Error" in registry.dispatch("calculate", {"expression": "factorial(999999)"})
        # over-long expression is rejected, not evaluated
        assert "too long" in registry.dispatch("calculate", {"expression": "1+" * 400 + "1"})
        # empty / missing / wrong-type args must not crash
        assert "Error" in registry.dispatch("calculate", {"expression": ""})
        assert "Error" in registry.dispatch("calculate", {})
        registry.dispatch("calculate", {"expression": 123})  # coerced, no raise
        assert "Error" in registry.dispatch("calculate", {"expression": "2 +"})
        return "bounds + guards held"
    check("calc bounds and guards", bounds_and_guards)


def t_dates():
    """Exercises the date/time calculator + its defenses against 8B
    hallucinations. No model needed, so it lives in the safe set."""
    from datetime import date, datetime, timedelta
    from jarvis.tools import dates  # noqa: F401  (register)
    from jarvis.tools import registry

    def happy_path():
        # a fixed, unambiguous date: 2026-12-25 is a Friday
        out = registry.dispatch("weekday", {"date": "2026-12-25"})
        assert "Friday" in out, out
        # month-name form parses too
        assert "Friday" in registry.dispatch("weekday", {"date": "December 25 2026"})
        # today reports the real current day
        td = registry.dispatch("today", {})
        assert date.today().strftime("%B") in td, td
        return "weekday + today ok"
    check("dates happy path", happy_path)

    def days_math():
        # days_between is order-independent and exact
        out = registry.dispatch("days_between",
                                {"start": "2026-01-01", "end": "2026-01-31"})
        assert "30 days" in out, out
        # days_until agrees with a locally computed delta
        target = date.today() + timedelta(days=10)
        u = registry.dispatch("days_until", {"date": target.isoformat()})
        assert "10 days until" in u, u
        # a past date reads as "ago"
        past = (date.today() - timedelta(days=5)).isoformat()
        assert "ago" in registry.dispatch("days_until", {"date": past})
        return "days_between/days_until exact"
    check("dates arithmetic", days_math)

    def date_add_flow():
        # 90 days from a fixed base
        out = registry.dispatch("date_add", {"days": 90, "base": "2026-01-01"})
        assert "1 April 2026" in out, out
        # weeks shortcut and negative offsets
        assert "8 January 2026" in registry.dispatch(
            "date_add", {"weeks": 1, "base": "2026-01-01"})
        assert "before" in registry.dispatch(
            "date_add", {"days": -3, "base": "2026-01-10"})
        # no base -> today, zero offset -> today unchanged
        assert date.today().strftime("%B") in registry.dispatch("date_add", {"days": 0})
        return "date_add ok"
    check("dates date_add", date_add_flow)

    def hallucination_guards():
        # unparseable / empty / missing / wrong-type dates must not crash
        assert "Error" in registry.dispatch("weekday", {"date": "not a date"})
        assert "Error" in registry.dispatch("weekday", {"date": ""})
        assert "Error" in registry.dispatch("weekday", {})
        assert "Error" in registry.dispatch("days_until", {"date": "someday"})
        # ambiguous slash date is refused, not guessed
        assert "Error" in registry.dispatch("weekday", {"date": "12/25/2026"})
        # over-long input rejected
        assert "Error" in registry.dispatch("weekday", {"date": "2026-12-25 " + "x" * 60})
        # runaway offset is capped, not overflowed
        assert "too large" in registry.dispatch("date_add", {"days": 10 ** 12})
        # wrong-type args coerced, never raise
        registry.dispatch("weekday", {"date": 20261225})
        registry.dispatch("date_add", {"days": "5", "base": "2026-01-01"})
        registry.dispatch("date_add", {"days": True})
        return "guards held"
    check("dates hallucination guards", hallucination_guards)


def t_convert():
    """Exercises the unit converter + its defenses against 8B hallucinations.
    No model needed, so it lives in the safe set."""
    from jarvis.tools import convert  # noqa: F401  (register)
    from jarvis.tools import registry

    def happy_path():
        # length: 5 miles is exactly 8.04672 km
        out = registry.dispatch("convert_units",
                                {"value": 5, "from_unit": "mi", "to_unit": "km"})
        assert out.startswith("5 mi = 8.04672 km"), out
        # full unit names resolve too, and a whole float renders as an int
        km = registry.dispatch("convert_units",
                               {"value": 1, "from_unit": "kilometer", "to_unit": "meters"})
        assert "= 1000 m" in km, km
        # mass: 1 kg = 1000 g
        assert "= 1000 g" in registry.dispatch(
            "convert_units", {"value": 1, "from_unit": "kg", "to_unit": "grams"})
        return "length + mass conversions exact"
    check("convert happy path", happy_path)

    def temperature_is_affine():
        # temperature uses an offset scale, not a plain ratio
        assert "= 32 F" in registry.dispatch(
            "convert_units", {"value": 0, "from_unit": "C", "to_unit": "F"})
        assert "= 212 F" in registry.dispatch(
            "convert_units", {"value": 100, "from_unit": "celsius", "to_unit": "fahrenheit"})
        assert "= 273.15 K" in registry.dispatch(
            "convert_units", {"value": 0, "from_unit": "C", "to_unit": "K"})
        return "temperature converts correctly"
    check("convert temperature", temperature_is_affine)

    def forgiving_input():
        # model uses 'from'/'to' instead of from_unit/to_unit -> still works
        alt = registry.dispatch("convert_units",
                                {"value": 5, "from": "mi", "to": "km"})
        assert alt.startswith("5 mi = 8.04672 km"), alt
        # a whole phrase dumped into one field is parsed
        ph = registry.dispatch("convert_units", {"value": "5 miles to km"})
        assert ph.startswith("5 mi = 8.04672 km"), ph
        # numeric string value is coerced
        s = registry.dispatch("convert_units",
                              {"value": "2", "from_unit": "kg", "to_unit": "lb"})
        assert s.startswith("2 kg ="), s
        return "alt arg names + phrase + string value handled"
    check("convert forgiving input", forgiving_input)

    def cross_category_refused():
        # miles -> kilograms is nonsense: refused, not answered
        r = registry.dispatch("convert_units",
                              {"value": 5, "from_unit": "mi", "to_unit": "kg"})
        assert "can't convert length to mass" in r, r
        # mixing temperature with a linear unit is refused too
        r2 = registry.dispatch("convert_units",
                               {"value": 5, "from_unit": "C", "to_unit": "km"})
        assert "can't convert temperature" in r2, r2
        return "cross-category conversions refused"
    check("convert cross-category guard", cross_category_refused)

    def output_is_ascii():
        registry.dispatch("convert_units",
                          {"value": 1, "from_unit": "cup", "to_unit": "ml"}).encode("ascii")
        return "output stayed pure ASCII"
    check("convert ascii-only output", output_is_ascii)

    def hallucination_guards():
        # unknown units are refused, not guessed at
        assert 'do not know the unit "florbs"' in registry.dispatch(
            "convert_units", {"value": 5, "from_unit": "florbs", "to_unit": "km"})
        # missing value / units -> friendly error, not a crash
        assert "Error" in registry.dispatch(
            "convert_units", {"from_unit": "mi", "to_unit": "km"})
        assert "Error" in registry.dispatch(
            "convert_units", {"value": 5, "from_unit": "mi"})
        assert "Error" in registry.dispatch("convert_units", {})
        # absurd / non-finite magnitude is rejected, never overflows
        assert "Error" in registry.dispatch(
            "convert_units", {"value": 1e400, "from_unit": "m", "to_unit": "km"})
        assert "Error" in registry.dispatch(
            "convert_units", {"value": float("inf"), "from_unit": "m", "to_unit": "km"})
        # bool value is junk, not treated as 1
        assert "Error" in registry.dispatch(
            "convert_units", {"value": True, "from_unit": "m", "to_unit": "km"})
        # wrong types / odd shapes must not raise
        registry.dispatch("convert_units", {"value": "abc", "from_unit": 5, "to_unit": None})
        registry.dispatch("convert_units", {"value": [1, 2], "from_unit": {}, "to_unit": "km"})
        return "guards held"
    check("convert hallucination guards", hallucination_guards)


def t_reminders():
    """Exercises the reminders/timers tool + its defenses against 8B
    hallucinations. Firing is driven by due_reminders(now=<future>) so the test
    is fully deterministic -- no model and no real waiting. Safe set."""
    from datetime import datetime, timedelta
    from jarvis.tools import reminders as rem
    from jarvis.tools import registry

    # isolate: use a temp store so we never touch the user's real reminders
    import tempfile, os, pathlib
    rem._STORE = pathlib.Path(tempfile.gettempdir()) / "jarvis_rem_smoke.json"
    for p in (rem._STORE, rem._STORE.with_name("reminders.corrupt.json")):
        if p.exists():
            os.remove(p)

    def happy_path():
        out = registry.dispatch("set_reminder",
                                {"text": "check the oven", "minutes": 10})
        assert "Reminder set" in out and "check the oven" in out, out
        assert rem.pending_count() == 1
        lst = registry.dispatch("list_reminders", {})
        assert "check the oven" in lst, lst
        # pending reminders surface in the injected preamble
        assert "check the oven" in rem.reminders_preamble()
        return "set/list/preamble ok"
    check("reminders happy path", happy_path)

    def absolute_time():
        # an unambiguous 24-hour clock time is accepted
        out = registry.dispatch("set_reminder",
                                {"text": "call mum", "at": "23:59"})
        assert "Reminder set" in out, out
        assert rem.pending_count() == 2
        return "absolute time accepted"
    check("reminders absolute time", absolute_time)

    def firing_is_deterministic():
        # nothing is due right now...
        assert rem.due_reminders(datetime.now()) == []
        # ...but everything is due far in the future; they fire once, then clear
        fired = rem.due_reminders(datetime.now() + timedelta(days=2))
        assert "check the oven" in fired and "call mum" in fired, fired
        assert rem.pending_count() == 0, "fired reminders not cleared"
        assert rem.due_reminders(datetime.now() + timedelta(days=3)) == []
        return "due reminders fire exactly once"
    check("reminders firing", firing_is_deterministic)

    def cancel_flow():
        registry.dispatch("set_reminder", {"text": "water plants", "minutes": 30})
        registry.dispatch("set_reminder", {"text": "stand up", "minutes": 45})
        registry.dispatch("set_reminder", {"text": "read a book", "minutes": 60})
        before = rem.pending_count()
        # cancel by substring
        assert "Cancelled" in registry.dispatch("cancel_reminder", {"which": "plants"})
        assert rem.pending_count() == before - 1
        # cancel by list number (1 is now the soonest remaining)
        assert "Cancelled" in registry.dispatch("cancel_reminder", {"which": "1"})
        assert rem.pending_count() == before - 2
        # a no-match cancel (with something still pending) is friendly, not a crash
        assert "Nothing pending matches" in registry.dispatch(
            "cancel_reminder", {"which": "zzzznope"})
        return "cancel by text + number ok"
    check("reminders cancel", cancel_flow)

    def hallucination_guards():
        # empty / missing text
        assert "Error" in registry.dispatch("set_reminder", {"minutes": 5})
        assert "Error" in registry.dispatch("set_reminder", {})
        # no "when" at all
        assert "Error" in registry.dispatch("set_reminder", {"text": "x"})
        # both minutes AND at is refused, not guessed
        assert "Error" in registry.dispatch(
            "set_reminder", {"text": "x", "minutes": 5, "at": "10:00"})
        # negative / zero / absurd / non-numeric delays rejected, never overflow
        assert "Error" in registry.dispatch("set_reminder", {"text": "x", "minutes": -5})
        assert "Error" in registry.dispatch("set_reminder", {"text": "x", "minutes": 0})
        assert "Error" in registry.dispatch("set_reminder", {"text": "x", "minutes": 10 ** 12})
        assert "Error" in registry.dispatch("set_reminder", {"text": "x", "minutes": "soon"})
        # unreadable / ambiguous clock time refused, not guessed
        assert "Error" in registry.dispatch("set_reminder", {"text": "x", "at": "half past"})
        assert "Error" in registry.dispatch("set_reminder", {"text": "x", "at": "12/25/2026"})
        # wrong types must not raise
        registry.dispatch("set_reminder", {"text": 123, "minutes": "5"})
        registry.dispatch("cancel_reminder", {"which": 5})
        # over-long text is truncated, not rejected or unbounded
        long = registry.dispatch("set_reminder", {"text": "x" * 5000, "minutes": 5})
        assert "shortened" in long, long
        return "guards held"
    check("reminders hallucination guards", hallucination_guards)

    def corrupt_store_recovers():
        rem._STORE.write_text("{ not valid json ", encoding="utf-8")
        # _load must not raise; corrupt file set aside, store treated as empty
        assert rem.pending_count() == 0
        assert rem._STORE.with_name("reminders.corrupt.json").exists()
        return "corrupt store recovered"
    check("reminders corrupt-store recovery", corrupt_store_recovers)


def t_dispatch():
    """Exercises the self-correcting tool dispatcher: hallucinated tool names,
    junk argument shapes, extra/missing arguments. No model needed, so it lives
    in the safe set."""
    from jarvis.tools import calc  # noqa: F401  (register a real tool to hit)
    from jarvis.tools import registry

    def unknown_tool_suggests():
        # a misspelled/hallucinated name points back at the closest real tool
        r = registry.dispatch("calculatee", {"expression": "2+2"})
        assert "no tool called 'calculatee'" in r, r
        assert "Did you mean" in r and "calculate" in r, r
        # a totally bogus name still recovers gracefully (no crash, a nudge)
        r2 = registry.dispatch("florblegorp", {})
        assert "no tool called" in r2 and "list_tools" in r2, r2
        return "unknown tool names suggest a real one"
    check("dispatch unknown-tool recovery", unknown_tool_suggests)

    def bad_name_types_dont_crash():
        assert "Error" in registry.dispatch("", {})
        assert "Error" in registry.dispatch(None, {})
        assert "Error" in registry.dispatch(123, {})
        return "junk tool names survived"
    check("dispatch bad-name guards", bad_name_types_dont_crash)

    def normalizes_arg_shapes():
        # the model sometimes sends a JSON STRING instead of an object
        assert registry.dispatch("calculate", '{"expression": "2+2"}').endswith("4")
        # ...or a list / None / garbage: normalized to no-args, never a crash
        registry.dispatch("calculate", [1, 2, 3])
        registry.dispatch("calculate", None)
        registry.dispatch("calculate", "not json at all")
        return "odd argument shapes normalized"
    check("dispatch arg normalization", normalizes_arg_shapes)

    def drops_extra_args():
        # a valid call sprinkled with hallucinated extra keys STILL succeeds,
        # with a quiet note naming what was ignored
        r = registry.dispatch("calculate",
                              {"expression": "2+2", "reason": "why", "confidence": 1})
        assert r.startswith("2+2 = 4"), r
        assert "ignored unexpected argument" in r, r
        assert "reason" in r and "confidence" in r, r
        # a clean call must NOT get a note (we didn't break normal tools)
        clean = registry.dispatch("calculate", {"expression": "2+2"})
        assert clean == "2+2 = 4", clean
        return "extra args dropped, clean calls untouched"
    check("dispatch drops extra args", drops_extra_args)

    def reports_missing_required():
        # register a throwaway tool with a genuinely required argument
        @registry.tool("smoke_needy", "test-only tool",
                       {"type": "object",
                        "properties": {"x": {"type": "string"}},
                        "required": ["x"]})
        def _needy(x):
            return f"got {x}"
        miss = registry.dispatch("smoke_needy", {})
        assert "needs" in miss and "x" in miss, miss
        # supplying it works; adding junk still works (junk dropped)
        assert registry.dispatch("smoke_needy", {"x": "hi"}) == "got hi"
        assert registry.dispatch("smoke_needy",
                                 {"x": "hi", "junk": 1}).startswith("got hi")
        return "missing required arg reported by name"
    check("dispatch missing-required report", reports_missing_required)

    def list_tools_enumerates():
        out = registry.dispatch("list_tools", {})
        assert "Available tools" in out and "calculate" in out, out
        return "list_tools works"
    check("dispatch list_tools", list_tools_enumerates)


def t_agent():
    from jarvis import config as c
    from jarvis.agent import Agent
    from jarvis.tools import apps, files, system, web, camera  # noqa: F401
    cfg = c.load()
    a = Agent(cfg["models"]["chat"])
    check("agent chat (no tools)", lambda: a.chat("Say exactly: systems online"))
    check("agent chat (tool: time)", lambda: a.chat("what time is it?"))


def t_camera():
    from jarvis import config as c
    from jarvis.vision.cameras import CameraManager
    cfg = c.load()
    m = CameraManager(cfg["cameras"], cfg["default_camera"])
    def grab():
        f = m.grab_frame()
        return f"frame {f.shape}"
    check("webcam frame grab", grab)


def t_vision():
    from jarvis import config as c
    from jarvis.vision.cameras import CameraManager
    from jarvis.vision.describe import describe_frame
    cfg = c.load()
    m = CameraManager(cfg["cameras"], cfg["default_camera"])
    check("vision describe", lambda: describe_frame(
        m.grab_frame(), cfg["models"]["vision"], unload=cfg["models"]["chat"]))


def t_tts():
    import time
    from jarvis.voice.tts import Speaker
    def speak():
        s = Speaker()
        s.say("Systems online, sir.")
        time.sleep(4)
        s.stop()
        return f"speaker ok={s.ok}"
    check("tts speak", speak)


def t_hud():
    import time
    from jarvis import config as c
    from jarvis.voice.hud import create
    cfg = c.load()
    def demo():
        h = create(cfg)
        for st in ("idle", "listening", "thinking", "speaking"):
            h.state(st)
            for i in range(12):
                h.level((i % 10) / 10.0)
                time.sleep(0.05)
        ok = getattr(h, "ok", False)
        h.shutdown()
        time.sleep(0.3)
        return f"hud drew window ok={ok}"
    check("hud orb cycle", demo)


def t_watch():
    from jarvis import config as c
    from jarvis.vision.cameras import CameraManager
    cfg = c.load()
    m = CameraManager(cfg["cameras"], cfg["default_camera"])
    def yolo():
        from ultralytics import YOLO
        frame = m.grab_frame()
        results = YOLO("yolov8n.pt").predict(frame, classes=[0], conf=0.5, verbose=False)
        return f"persons detected: {sum(len(r.boxes) for r in results)}"
    check("yolo person detection", yolo)


def t_e2e():
    import os
    from jarvis import config as c
    from jarvis.agent import Agent
    from jarvis.tools import apps, files, system, web  # noqa: F401
    from jarvis.tools import camera
    cfg = c.load()
    camera.init(cfg, None)
    a = Agent(cfg["models"]["chat"])
    target = os.path.join(os.path.expanduser("~"), "Desktop", "jarvis_test_note.txt")
    if os.path.exists(target):
        os.remove(target)
    check("e2e write file", lambda: a.chat(
        "make a file on my desktop called jarvis_test_note.txt containing a "
        "two line hello note"))
    check("e2e file exists", lambda: f"exists={os.path.exists(target)}" if os.path.exists(target)
          else (_ for _ in ()).throw(AssertionError(f"{target} missing")))
    check("e2e start working", lambda: a.chat("start working"))
    import time; time.sleep(3)
    check("e2e stop working", lambda: a.chat("stop working"))
    camera.shutdown()


def t_textstats():
    """Exercises the count_words tool (exact word/char/line counting on text or
    a file) + its defenses against 8B hallucinations. Builds a temp tree inside
    the user's home; deterministic, needs no model, lives in the safe set."""
    import os
    import pathlib
    import shutil
    import zipfile
    from jarvis.tools import textstats as ts  # noqa: F401  (register count_words)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_words_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)
    sandbox.mkdir(parents=True, exist_ok=True)

    # a plain-text file with a known word count
    (sandbox / "essay.txt").write_text("one two three four five\n", encoding="utf-8")
    # a real .docx (a zip of xml), reusing read_document's extractor
    WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (f'<?xml version="1.0"?><w:document xmlns:w="{WNS}"><w:body>'
           "<w:p><w:r><w:t>alpha beta gamma</w:t></w:r></w:p>"
           "<w:p><w:r><w:t>delta</w:t></w:r></w:p></w:body></w:document>")
    with zipfile.ZipFile(sandbox / "resume.docx", "w") as z:
        z.writestr("word/document.xml", xml)
    (sandbox / "a.pdf").write_bytes(b"%PDF-1.4 not really")
    (sandbox / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (sandbox / "blob.log").write_bytes(b"abc\x00def binary")  # NUL -> not text

    saved_text_cap = ts.MAX_TEXT_LEN
    try:
        def counts_text():
            out = registry.dispatch(
                "count_words",
                {"text": "Hello world. This is a test!\nSecond line here."})
            assert "9 words" in out, out          # exact word count
            assert "2 lines" in out, out          # line count
            assert "3 sentences" in out, out      # rough sentence count
            assert "Reading time" in out and "speaking aloud" in out, out
            return "counted words/lines/sentences in text"
        check("count_words counts text", counts_text)

        def counts_plain_file():
            out = registry.dispatch(
                "count_words", {"path": "jarvis_words_smoke/essay.txt"})
            assert "essay.txt" in out and "5 words" in out, out
            return "counted a plain-text file"
        check("count_words counts a plain-text file", counts_plain_file)

        def counts_docx():
            out = registry.dispatch(
                "count_words", {"path": "jarvis_words_smoke/resume.docx"})
            assert "resume.docx" in out and "4 words" in out, out
            return "counted a Word .docx document"
        check("count_words counts a docx", counts_docx)

        def filename_in_text_field():
            # a common 8B slip: the file name dropped into 'text' -> still counts
            # the FILE, not the literal string
            out = registry.dispatch(
                "count_words", {"text": "jarvis_words_smoke/essay.txt"})
            assert "essay.txt" in out and "5 words" in out, out
            return "a filename in the text field is read as a file"
        check("count_words filename-in-text", filename_in_text_field)

        def refuses_pdf_and_binary():
            pdf = registry.dispatch("count_words", {"path": "jarvis_words_smoke/a.pdf"})
            assert "PDF" in pdf, pdf
            png = registry.dispatch("count_words", {"path": "jarvis_words_smoke/pic.png"})
            assert "isn't a text file" in png, png
            nul = registry.dispatch("count_words", {"path": "jarvis_words_smoke/blob.log"})
            assert "doesn't look like text" in nul, nul
            return "pdf + binary + NUL-byte files refused"
        check("count_words refuses non-text files", refuses_pdf_and_binary)

        def containment_guard():
            # a file outside the user's home must be refused, not read
            r = registry.dispatch(
                "count_words", {"path": "C:\\Windows\\System32\\drivers\\etc\\hosts"})
            assert "only work inside your own folders" in r, r
            return "escape outside home blocked"
        check("count_words containment guard", containment_guard)

        def folder_and_missing():
            fol = registry.dispatch("count_words", {"path": "jarvis_words_smoke"})
            assert "is a folder" in fol, fol
            miss = registry.dispatch("count_words", {"path": "jarvis_words_smoke/ghost.txt"})
            assert "can't find" in miss, miss
            return "folder source + missing file are friendly messages"
        check("count_words folder + missing", folder_and_missing)

        def long_text_is_truncated():
            ts.MAX_TEXT_LEN = 10            # temporarily tiny
            out = registry.dispatch("count_words", {"text": "word " * 50})
            assert "first part" in out, out
            ts.MAX_TEXT_LEN = saved_text_cap
            return "over-long text measured in part, not unbounded"
        check("count_words long-text truncation", long_text_is_truncated)

        def output_is_ascii():
            # non-ASCII input must still yield pure-ASCII output (counts only)
            registry.dispatch(
                "count_words", {"text": "cafe resume naive expose budget"}).encode("ascii")
            registry.dispatch(
                "count_words", {"path": "jarvis_words_smoke/essay.txt"}).encode("ascii")
            return "output stayed pure ASCII"
        check("count_words ascii-only output", output_is_ascii)

        def hallucination_guards():
            # empty / whitespace / missing args -> friendly error, never a crash
            assert "Error" in registry.dispatch("count_words", {})
            assert "Error" in registry.dispatch("count_words", {"text": ""})
            assert "Error" in registry.dispatch("count_words", {"text": "   "})
            # wrong types must not raise
            registry.dispatch("count_words", {"text": 123})
            registry.dispatch("count_words", {"text": ["a", "b"]})
            registry.dispatch("count_words", {"path": {}})
            registry.dispatch("count_words", {"path": None, "text": None})
            # an unexpected extra arg is dropped, the call still succeeds
            out = registry.dispatch(
                "count_words", {"text": "two words", "reason": "curious"})
            assert "2 words" in out, out
            return "guards held"
        check("count_words hallucination guards", hallucination_guards)
    finally:
        ts.MAX_TEXT_LEN = saved_text_cap
        shutil.rmtree(sandbox, ignore_errors=True)


def t_spreadsheet():
    """Exercises the read_csv tool (summarise a CSV/TSV data file: row/column
    counts, column names, preview) + its defenses against 8B hallucinations.
    Builds a temp tree inside the user's home; deterministic, needs no model,
    lives in the safe set."""
    import os
    import pathlib
    import shutil
    from jarvis.tools import spreadsheet as sp  # noqa: F401  (register read_csv)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_csv_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)
    sandbox.mkdir(parents=True, exist_ok=True)

    (sandbox / "sales.csv").write_text(
        "Date,Item,Amount\n"
        "2026-01-01,Coffee,3.50\n"
        "2026-01-02,Tea,2.00\n"
        "2026-01-03,Cake,4.25\n", encoding="utf-8")
    (sandbox / "many.csv").write_text(
        "id,name\n" + "".join(f"{i},row{i}\n" for i in range(1, 7)),
        encoding="utf-8")
    (sandbox / "gappy.csv").write_text(
        "a,b\n1,2\n\n3,4\n", encoding="utf-8")          # a blank interior row
    (sandbox / "data.tsv").write_text(
        "x\ty\n1\t2\n3\t4\n", encoding="utf-8")
    (sandbox / "semi.csv").write_text(
        "p;q;r\n1;2;3\n4;5;6\n", encoding="utf-8")
    (sandbox / "headeronly.csv").write_text("h1,h2,h3\n", encoding="utf-8")
    (sandbox / "empty.csv").write_text("", encoding="utf-8")
    (sandbox / "accent.csv").write_text(
        "name,city\ncafe,montreal\nrésumé,zürich\n", encoding="utf-8")
    (sandbox / "book.xlsx").write_bytes(b"PK\x03\x04 not really xlsx")
    (sandbox / "blob.csv").write_bytes(b"a,b\n1,\x00,2\n")   # NUL -> not text

    saved_rows = sp.MAX_ROWS
    try:
        def happy_csv():
            out = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke/sales.csv"})
            assert "sales.csv" in out, out
            assert "3 data rows" in out and "3 columns" in out, out
            assert "comma-separated" in out, out
            assert "Date, Item, Amount" in out, out
            assert "First 3 rows" in out and "Coffee" in out, out
            return "summarised a CSV (rows/cols/columns/preview)"
        check("read_csv summarises a CSV", happy_csv)

        def preview_count():
            deflt = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke/many.csv"})
            assert "6 data rows" in deflt and "First 5 rows" in deflt, deflt
            limited = registry.dispatch(
                "read_csv", {"path": "jarvis_csv_smoke/many.csv", "rows": 2})
            assert "First 2 rows" in limited, limited
            return "preview defaults to 5 and respects the rows arg"
        check("read_csv preview row count", preview_count)

        def blank_rows_skipped():
            out = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke/gappy.csv"})
            assert "2 data rows" in out, out       # the blank interior row not counted
            return "blank rows are not counted"
        check("read_csv skips blank rows", blank_rows_skipped)

        def tsv_file():
            out = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke/data.tsv"})
            assert "2 data rows" in out and "2 columns" in out, out
            assert "tab-separated" in out, out
            return "read a tab-separated .tsv"
        check("read_csv reads a TSV", tsv_file)

        def semicolon_sniffed():
            out = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke/semi.csv"})
            assert "3 columns" in out and "2 data rows" in out, out
            assert "semicolon-separated" in out, out
            return "sniffed a semicolon delimiter"
        check("read_csv sniffs the delimiter", semicolon_sniffed)

        def header_only():
            out = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke/headeronly.csv"})
            assert "0 data rows" in out and "3 columns" in out, out
            assert "No data rows to preview" in out, out
            return "header-only file has 0 data rows"
        check("read_csv header-only file", header_only)

        def empty_file():
            out = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke/empty.csv"})
            assert "empty" in out, out
            return "empty file is a friendly message"
        check("read_csv empty file", empty_file)

        def refuses_excel_and_binary():
            xl = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke/book.xlsx"})
            assert "Excel" in xl and "save it as CSV" in xl, xl
            nul = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke/blob.csv"})
            assert "doesn't look like a text data file" in nul, nul
            return "Excel steered + NUL-byte file refused"
        check("read_csv refuses non-text files", refuses_excel_and_binary)

        def containment_guard():
            r = registry.dispatch("read_csv", {"path": "C:\\Windows\\win.ini"})
            assert "only work inside your own folders" in r, r
            return "escape outside home blocked"
        check("read_csv containment guard", containment_guard)

        def folder_and_missing():
            fol = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke"})
            assert "is a folder" in fol, fol
            miss = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke/ghost.csv"})
            assert "can't find" in miss, miss
            return "folder source + missing file are friendly messages"
        check("read_csv folder + missing", folder_and_missing)

        def row_scan_cap():
            sp.MAX_ROWS = 2                    # header + 1 data row, then stop
            out = registry.dispatch("read_csv", {"path": "jarvis_csv_smoke/many.csv"})
            sp.MAX_ROWS = saved_rows
            assert "stopped early" in out, out
            return "a huge sheet stops early with a note"
        check("read_csv row scan cap", row_scan_cap)

        def output_is_ascii():
            registry.dispatch(
                "read_csv", {"path": "jarvis_csv_smoke/accent.csv"}).encode("ascii")
            return "output stayed pure ASCII"
        check("read_csv ascii-only output", output_is_ascii)

        def hallucination_guards():
            assert "Error" in registry.dispatch("read_csv", {})
            assert "Error" in registry.dispatch("read_csv", {"path": ""})
            assert "Error" in registry.dispatch("read_csv", {"path": "   "})
            # wrong types must not raise
            registry.dispatch("read_csv", {"path": 123})
            registry.dispatch("read_csv", {"path": ["a"]})
            registry.dispatch("read_csv", {"path": {}})
            registry.dispatch("read_csv", {"path": None})
            # a wrong-type rows arg must not raise (falls back to default)
            out = registry.dispatch(
                "read_csv", {"path": "jarvis_csv_smoke/sales.csv", "rows": "junk"})
            assert "3 data rows" in out, out
            registry.dispatch(
                "read_csv", {"path": "jarvis_csv_smoke/sales.csv", "rows": {}})
            # an unexpected extra arg is dropped, the call still succeeds; alt name
            out2 = registry.dispatch(
                "read_csv", {"file": "jarvis_csv_smoke/sales.csv", "reason": "curious"})
            assert "3 data rows" in out2, out2
            return "guards held"
        check("read_csv hallucination guards", hallucination_guards)
    finally:
        sp.MAX_ROWS = saved_rows
        shutil.rmtree(sandbox, ignore_errors=True)


def t_jsondata():
    """Exercises the read_json tool (summarise a JSON / JSON Lines data file:
    structure, field names + types, preview) + its defenses against 8B
    hallucinations. Builds a temp tree inside the user's home; deterministic,
    needs no model, lives in the safe set."""
    import os
    import pathlib
    import shutil
    from jarvis.tools import jsondata as jd  # noqa: F401  (register read_json)
    from jarvis.tools import registry

    home = pathlib.Path(os.path.expanduser("~"))
    sandbox = home / "jarvis_json_smoke"
    shutil.rmtree(sandbox, ignore_errors=True)
    sandbox.mkdir(parents=True, exist_ok=True)

    (sandbox / "config.json").write_text(
        '{"name": "Jarvis", "version": 2, "enabled": true, '
        '"models": {"chat": "qwen3:8b"}}', encoding="utf-8")
    (sandbox / "people.json").write_text(
        '[{"id": 1, "name": "Ann"}, {"id": 2, "name": "Bob"}, '
        '{"id": 3, "name": "Cy"}]', encoding="utf-8")
    (sandbox / "nums.json").write_text("[1, 2, 3, 4, 5, 6, 7]", encoding="utf-8")
    (sandbox / "scalar.json").write_text('"just a string"', encoding="utf-8")
    (sandbox / "log.jsonl").write_text(
        '{"evt": "a", "n": 1}\n{"evt": "b", "n": 2}\n\n{"evt": "c", "n": 3}\n',
        encoding="utf-8")
    (sandbox / "sneaky.json").write_text(          # jsonl content, .json ext
        '{"a": 1}\n{"a": 2}\n{"a": 3}\n', encoding="utf-8")
    (sandbox / "accent.json").write_text(
        '{"city": "zürich", "name": "résumé"}', encoding="utf-8")
    (sandbox / "empty.json").write_text("", encoding="utf-8")
    (sandbox / "broken.json").write_text('{"a": 1, ', encoding="utf-8")
    (sandbox / "deep.json").write_text("[" * 2000 + "]" * 2000, encoding="utf-8")
    (sandbox / "pic.png").write_bytes(b"\x89PNG not really")
    (sandbox / "blob.json").write_bytes(b'{"a":\x00}')     # NUL -> not text

    saved_jsonl = jd.MAX_JSONL_ROWS
    try:
        def happy_object():
            out = registry.dispatch("read_json", {"path": "jarvis_json_smoke/config.json"})
            assert "config.json" in out, out
            assert "object with 4 fields" in out, out
            assert "name (text)" in out and "version (number)" in out, out
            assert "enabled (true/false)" in out and "models (object)" in out, out
            assert "Preview:" in out and "qwen3:8b" in out, out
            return "summarised a JSON object (fields + types + preview)"
        check("read_json summarises an object", happy_object)

        def happy_array():
            out = registry.dispatch("read_json", {"path": "jarvis_json_smoke/people.json"})
            assert "array of 3 items" in out, out
            assert "items are objects" in out, out
            assert "id (number)" in out and "name (text)" in out, out
            return "summarised an array of objects"
        check("read_json summarises an array of objects", happy_array)

        def scalar_array():
            out = registry.dispatch("read_json", {"path": "jarvis_json_smoke/nums.json"})
            assert "array of 7 items" in out, out
            assert "first item is a number" in out, out
            return "array of scalars reports the item type"
        check("read_json array of scalars", scalar_array)

        def top_scalar():
            out = registry.dispatch("read_json", {"path": "jarvis_json_smoke/scalar.json"})
            assert "single text value" in out and "just a string" in out, out
            return "top-level scalar summarised"
        check("read_json top-level scalar", top_scalar)

        def jsonl_file():
            out = registry.dispatch("read_json", {"path": "jarvis_json_smoke/log.jsonl"})
            assert "JSON Lines with 3 records" in out, out    # blank line ignored
            assert "evt (text)" in out and "n (number)" in out, out
            return "read a .jsonl file (blank line skipped)"
        check("read_json reads JSON Lines", jsonl_file)

        def jsonl_without_ext():
            out = registry.dispatch("read_json", {"path": "jarvis_json_smoke/sneaky.json"})
            assert "JSON Lines with 3 records" in out, out    # .json but line-delimited
            return "line-delimited JSON detected without the extension"
        check("read_json JSONL fallback", jsonl_without_ext)

        def empty_file():
            out = registry.dispatch("read_json", {"path": "jarvis_json_smoke/empty.json"})
            assert "empty" in out, out
            return "empty file is a friendly message"
        check("read_json empty file", empty_file)

        def broken_json():
            out = registry.dispatch("read_json", {"path": "jarvis_json_smoke/broken.json"})
            assert "isn't valid JSON" in out, out
            return "invalid JSON is a friendly message"
        check("read_json invalid JSON", broken_json)

        def deep_json():
            out = registry.dispatch("read_json", {"path": "jarvis_json_smoke/deep.json"})
            # either the parser refuses the deep nest or it summarises -- never raises
            assert isinstance(out, str) and out, out
            out.encode("ascii")
            return "deeply nested JSON handled without crashing"
        check("read_json deep-nesting guard", deep_json)

        def refuses_binary():
            png = registry.dispatch("read_json", {"path": "jarvis_json_smoke/pic.png"})
            assert "isn't a JSON text file" in png, png
            nul = registry.dispatch("read_json", {"path": "jarvis_json_smoke/blob.json"})
            assert "doesn't look like a text file" in nul, nul
            return "binary ext steered + NUL-byte file refused"
        check("read_json refuses non-text files", refuses_binary)

        def containment_guard():
            r = registry.dispatch("read_json", {"path": "C:\\Windows\\win.ini"})
            assert "only work inside your own folders" in r, r
            return "escape outside home blocked"
        check("read_json containment guard", containment_guard)

        def folder_and_missing():
            fol = registry.dispatch("read_json", {"path": "jarvis_json_smoke"})
            assert "is a folder" in fol, fol
            miss = registry.dispatch("read_json", {"path": "jarvis_json_smoke/ghost.json"})
            assert "can't find" in miss, miss
            return "folder source + missing file are friendly messages"
        check("read_json folder + missing", folder_and_missing)

        def jsonl_scan_cap():
            jd.MAX_JSONL_ROWS = 2
            out = registry.dispatch("read_json", {"path": "jarvis_json_smoke/log.jsonl"})
            jd.MAX_JSONL_ROWS = saved_jsonl
            assert "stopped early" in out, out
            return "a huge JSONL file stops early with a note"
        check("read_json JSONL scan cap", jsonl_scan_cap)

        def output_is_ascii():
            registry.dispatch(
                "read_json", {"path": "jarvis_json_smoke/accent.json"}).encode("ascii")
            return "output stayed pure ASCII"
        check("read_json ascii-only output", output_is_ascii)

        def hallucination_guards():
            assert "Error" in registry.dispatch("read_json", {})
            assert "Error" in registry.dispatch("read_json", {"path": ""})
            assert "Error" in registry.dispatch("read_json", {"path": "   "})
            # wrong types must not raise
            registry.dispatch("read_json", {"path": 123})
            registry.dispatch("read_json", {"path": ["a"]})
            registry.dispatch("read_json", {"path": {}})
            registry.dispatch("read_json", {"path": None})
            # an unexpected extra arg is dropped, the call still succeeds; alt name
            out = registry.dispatch(
                "read_json", {"file": "jarvis_json_smoke/config.json", "reason": "curious"})
            assert "object with 4 fields" in out, out
            return "guards held"
        check("read_json hallucination guards", hallucination_guards)
    finally:
        jd.MAX_JSONL_ROWS = saved_jsonl
        shutil.rmtree(sandbox, ignore_errors=True)


SECTIONS = {"imports": t_imports, "tools": t_tools, "memory": t_memory,
            "shell": t_shell, "find": t_find, "search": t_search,
            "recent": t_recent, "organize": t_organize,
            "movefolder": t_movefolder, "copyfolder": t_copyfolder,
            "makefolder": t_makefolder, "disk": t_disk, "document": t_document,
            "explorer": t_explorer,
            "archive": t_archive,
            "extract": t_extract, "recycle": t_recycle, "clipboard": t_clipboard,
            "tasks": t_tasks, "calc": t_calc, "dates": t_dates,
            "convert": t_convert, "textstats": t_textstats,
            "spreadsheet": t_spreadsheet, "jsondata": t_jsondata,
            "reminders": t_reminders, "dispatch": t_dispatch, "agent": t_agent,
            "camera": t_camera, "vision": t_vision, "tts": t_tts,
            "hud": t_hud, "watch": t_watch, "e2e": t_e2e}

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "safe"
    if which == "all":
        for fn in SECTIONS.values():
            fn()
    elif which == "safe":
        t_imports(); t_tools(); t_memory(); t_shell(); t_find(); t_search()
        t_recent(); t_organize(); t_movefolder(); t_copyfolder(); t_makefolder(); t_disk()
        t_document(); t_explorer()
        t_archive(); t_extract()
        t_recycle(); t_clipboard()
        t_tasks(); t_calc(); t_dates(); t_convert(); t_textstats()
        t_spreadsheet(); t_jsondata()
        t_reminders(); t_dispatch()
    else:
        SECTIONS[which]()
    print("\nFAILURES:", failures if failures else "none")
    sys.exit(1 if failures else 0)
