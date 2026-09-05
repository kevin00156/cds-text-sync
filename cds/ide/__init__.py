# -*- coding: utf-8 -*-
"""cds.ide — the ONLY layer allowed to touch the CODESYS API.

    watcher     what one tick does: claim a command, answer it, beat
    session     arming a watcher in a live IDE and taking it back out
    silent      running a Project_*.py with nobody there to click its dialogs
    project     asking the IDE what it has open
    messages    reading the build's errors, and writing to the Messages panel
    statusform  the little window that says the watcher is alive

Only session and statusform need .NET; the rest take the CODESYS globals as
an argument, which is what lets CPython test them. IronPython 2.7 throughout.
"""
