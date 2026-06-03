# fixtures — real CODESYS native-export samples

The pure `cds/core` layer is tested without an IDE. But two modules cross into
CODESYS-specific territory and **cannot be authored blind**:

- `cds/core/model.parse` — native snapshot XML → `ProjectObject` list
- `cds/core/patch.build` — `Changes` → `import_native` XML (incl. create nodes)

Their correctness depends entirely on the exact XML that *your* CODESYS version
emits from `export_native`. That schema is version-specific and not in the docs,
so we pin it down from a **real sample committed here**, then implement + test
against it (PRINCIPLES.md §10, REWORK_PLAN.md stages 1–2).

## What to drop here

A single file named **`sample_snapshot.xml`** in this folder.

## How to produce it

1. Open a **small but representative** test project in CODESYS — ideally
   containing at least: a `PROGRAM`, a `FUNCTION_BLOCK` with a **method** and a
   **property** (GET + SET), a `GVL`, a `DUT`, and a couple of **folders** so
   the hierarchy shows up.
2. Open **Tools → Scripting** (the scripting immediate window) and run:

   ```python
   proj = projects.primary
   proj.export_native(proj.get_children(), r"C:\temp\snapshot.xml", recursive=True)
   ```

   (If that errors, try the explicit recursive list:
   `proj.export_native(proj.get_children(recursive=True), r"C:\temp\snapshot.xml", recursive=False)`.)
3. Copy `C:\temp\snapshot.xml` to `fixtures/sample_snapshot.xml` and commit it.

It is just a throwaway test project, so the contents are not sensitive — but
glance over it before committing if you reused a real project.

## After it lands

With the sample in place I can:

- implement `model.parse` to reproduce the object tree from it,
- add a fixture smoke test (sample in → expected file tree out),
- implement `patch.build` to emit `import_native`-compatible XML,
- then port `cds/ide/snapshot` + `cds/ide/apply`, wire `cds/app`, rewrite the
  `Project_*.py` entry points as thin shims, and finally delete the legacy
  `codesys_*.pyw` modules.
