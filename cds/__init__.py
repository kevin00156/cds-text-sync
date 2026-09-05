# -*- coding: utf-8 -*-
"""cds — the watcher and the file protocol behind the cds-ide CLI.

Two layers, and the boundary is the point (PRINCIPLES.md §4):

    cds.core  pure Python, no CODESYS imports, unit-tested in CI. The
              protocol the watcher and the CLI both speak.
    cds.ide   the only layer allowed near the CODESYS API. It runs under
              IronPython 2.7 inside the IDE.

The sync itself still lives in the Project_*.py scripts at the repo root and
the codesys_*.pyw modules beside them; the watcher presses their buttons
rather than reimplementing them. docs/WATCHER_CLI_PLAN.md is the whole story.
"""
VERSION = "k1.0.1"
