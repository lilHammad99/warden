**What this changes**

**Why**

<!-- Link the issue if there is one. -->

**How you verified it**

<!-- What you actually ran, and what it printed. Not "should work". -->

```
```

**Checklist**

- [ ] The safe set passes: `.venv\Scripts\python -m tests.smoke`
- [ ] A new or changed tool has a section in `tests/smoke.py` covering its
      happy path, its containment guard, and junk input
- [ ] The tool never raises, stays inside the user's home, is bounded, and
      returns pure ASCII
- [ ] No new dependency — or if there is one, it is pure-Python and offline,
      pinned in `requirements.txt`, and imported lazily
- [ ] `CHANGELOG.md` and `docs/ROADMAP.md` updated if this is user-visible
- [ ] No personal information in the diff: no real names, emails, machine
      paths, locations, or hardware details
