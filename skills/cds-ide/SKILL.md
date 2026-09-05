---
name: cds-ide
description: Drive a running CODESYS or DIADesigner-AX IDE from the shell with cds_ide.py — edit .st files, compare, import them into the IDE, build, and read the compile errors. Use when the user mentions CODESYS, DIADesigner, PLC Designer, a .st file, PLC/IEC 61131 code, structured text, importing into the IDE, or building a PLC application (CODESYS、DIADesigner、PLC 程式、.st 檔、匯入 IDE、編譯 PLC).
---

# Driving a CODESYS IDE from the shell

CODESYS project files are binary and cannot be edited. What can be edited are the
`.st` text files in the project's sync folder; the IDE is then told to read them
back in. The IDE must be open — this drives a running IDE, it is not a headless
compiler.

`cds_ide.py` lives at `cli/cds_ide.py` inside the cds-text-sync repo. If it is not
in the current project, ask the user where that repo is checked out.

## Before anything: is an IDE listening?

```
python cli/cds_ide.py list
```

One line per listening IDE. **Nothing listed means nobody can be driven** — ask the
user to open their project and run `Project_watch.py` once from **Tools > Scripting**.
That script finishes immediately and leaves a listener behind; the IDE stays usable.
Do not try to start an IDE yourself: a second instance cannot open a project that
another IDE already has open.

Find the sync folder — the only directory to edit — from:

```
python cli/cds_ide.py status --json      # data.sync_dir
```

`null` there means the project has no `cds-sync-folder` property set. Ask the user
to set it; do not guess a path.

## The loop

```
edit .st files under sync_dir
python cli/cds_ide.py compare            # read-only, shows what differs
python cli/cds_ide.py import --yes       # disk wins, writes into the IDE
python cli/cds_ide.py build              # or build --app NAME
# errors > 0 → read them, fix, go again
```

`export` runs the other way, writing the IDE's objects out as `.st`. Run it before
starting so the disk is current, or after an import to confirm it landed.

## Reading the answer

Exit codes: `0` done, `1` failed or a flag is missing, `2` no single live IDE
matched, `3` timed out (raise `--timeout`, default 120s; big imports and builds
need more).

With `--json`: `messages` carries what the IDE would have shown a person,
`stdout_tail` carries the detail (compare's per-object list, build's error list
with line numbers), `error` explains a failure, `needs_input` names the flag that
was missing, `data` is filled only by `status` and `list`.

## Flags answer the questions a person would have

A question with no flag behind it comes back as `needs_input`, exit code 1, and
**nothing in the IDE is changed**. That is the design. Supply the flag named in
`needs_input.arg` and run it again — never retry unchanged, never guess.

| `arg` | flag | the question |
|---|---|---|
| `yes` | `--yes` | "import N changes into the IDE?" — required for `import` |
| `force` | `--force` | version or computer mismatch; stop and ask the user instead of forcing |
| `app` | `--app NAME` | which application to build |
| `delete_orphans` | `--delete-orphans` | export found sync files with no object behind them |

## Several IDEs

With more than one listening, every command needs `--target`, taking either the
full instance id (`Shm_2026.07.29-14012`) or the project name (case-insensitive).
Without it the command exits 2 and lists the candidates.

## While a command runs, the IDE is frozen

Waiting costs the IDE nothing, but export, import and build each hold the UI thread
for seconds — that is the CODESYS object model, not a bug. Send one command at a
time and wait for it.

## Never

- Edit the `.project` file, or anything outside the sync folder.
- Import while the PLC is logged in — the tool refuses, and the IDE would reject
  every create, move and delete anyway.
- Start or close an IDE. The open project is someone's workbench.
- Use `--force` when unsure. It exists to override a safety check.

## The `.st` format

Declaration and implementation are split by one marker line:

```
FUNCTION_BLOCK Counter
VAR
    count : INT;
END_VAR

// === IMPLEMENTATION ===
count := count + 1;
```

Leading `//% cds-text-sync.<key>=<value>` lines are kind and build-attribute
pragmas; leave them alone unless deliberately changing that attribute. Creating a
new `.st` file creates a new object in the IDE, at the tree position matching its
folder.

Fuller detail, including every flag and the whole result schema, is in
`docs/AI_WORKFLOW.md` in the cds-text-sync repo.
