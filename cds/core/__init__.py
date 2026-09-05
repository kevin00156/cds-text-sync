# -*- coding: utf-8 -*-
"""cds.core — pure Python. NO CODESYS imports, ever (PRINCIPLES.md §4).

The file protocol the in-IDE watcher and the external CLI talk over:

    ipc        where the instance directories are, and how to write a file
               in one that a second process may be reading
    instances  the registration files: heartbeat, liveness, picking a target
    commands   the command and result files, and their queue

Everything takes paths and data in and returns data out, so it runs in CI
under CPython 3 and inside the IDE under IronPython 2.7 from one source:
no type annotations, no f-strings, standard library only.
"""
