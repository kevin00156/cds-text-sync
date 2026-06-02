# Coding Principles

These are the rules for this codebase. They are not suggestions. If a change
violates one of these, the change is wrong — fix the change, not the rule.

The spirit: **KISS and the UNIX philosophy.** Small things that each do one
job well, that you can read in one sitting, and that compose. If you cannot
explain a module in one sentence, it is doing too much.

---

## 1. One job per module. One job per function.

- A module has a single responsibility, stated in its first docstring line.
- A function does one thing. If you need "and" to describe it, split it.
- If you cannot name a function without `_and_`, `_handle_`, `_do_`, or
  `_process_`, you do not yet understand the job. Think harder, then name it.

## 2. Size limits are hard limits, not goals.

- **Files: 300 lines soft, 400 lines hard.** A file over 400 lines is a bug.
  (The version we are replacing had a 3868-line file and three 1000+ line
  files. That is how you lose control of a codebase. Never again.)
- **Functions: 40 lines soft, 60 hard.** A 200-line function with a giant
  `if/elif` chain is a dispatch table that has not been written yet.
- A dispatcher with more than ~5 branches is a `dict`, not an `if/elif`.

## 3. The expensive boundary gets crossed once.

- Calling the CODESYS API from IronPython is the expensive operation. Every
  round-trip costs. **Do not loop over objects making one API call each.**
- Read the whole project in ONE batch call (`export_native`). Write it back
  in ONE batch call (`import_native`). Everything in between is plain Python
  on local data and is effectively free.
- This single rule is the entire performance story. Honor it and the tool is
  fast. Break it and you are back to the slow version, no matter how clever
  the rest is.

## 4. Two layers, and the boundary is sacred.

- `cds/ide/` — the ONLY code allowed to import or touch CODESYS globals
  (`system`, `projects`, `online`, `clr`, ...). Keep it thin: it moves data
  in and out of the IDE and does nothing clever.
- `cds/core/` — pure Python. **It must never import anything CODESYS.** It
  takes file paths and data in, returns data out. Because of this it runs in
  CI under CPython 3 and is fully unit-tested.
- If you are tempted to import `system` inside `core/`, you have put logic in
  the wrong layer. Move the logic out; pass the data in.

## 5. Disk is the source of truth. Text is the format.

- The `.st` (and minimal `.xml` sidecar) files on disk are canonical. The
  native snapshot is a *transport*, never the truth. This is what lets a human
  or an AI create a new object by writing a file — and have it import cleanly.
- A file on disk with no matching object in the IDE means **create it**, not
  "ignore it."

## 6. Fail loud. Never skip silently.

- No bare `except:`. Catch the specific exception you expect. Let the rest
  crash — a crash with a traceback is a gift; a silent skip is a bug report
  you will get six months later with no information.
- If you cannot handle an object, say so — by name, on screen and in the log.
  "It just didn't import and I don't know why" is the single worst outcome and
  the reason we are rewriting this.

## 7. No dead code. No parallel paths.

- One way to do a thing. Not a "new" way and a "legacy fallback" living side by
  side forever. When you replace something, delete the old one in the same PR.
- No commented-out code. Git remembers; you do not need to.

## 8. Cross-runtime: `core/` must run on IronPython 2.7 *and* CPython 3.

- The IDE ships IronPython 2.7. Code that runs inside it is Python 2/3
  compatible: `from __future__ import print_function`, **no type annotations**
  (they are a syntax error in 2.7), no f-strings, no `pathlib`-only idioms.
- Standard library only. If a feature needs a pip package, it does not run
  inside CODESYS — keep it out of `core/` and `ide/`.

## 9. No premature abstraction.

- Write the concrete thing first. Extract an abstraction only on the third
  copy, never on the first guess. A base class with one subclass is not an
  abstraction, it is two files where one would do.
- YAGNI. Delete the option nobody asked for.

## 10. Tests follow the boundary.

- Everything in `core/` has a unit test. No exceptions — that is why `core/`
  is pure.
- `ide/` is verified by hand against a real IDE and by a small set of
  fixture-based smoke tests (snapshot in, expected files out).
