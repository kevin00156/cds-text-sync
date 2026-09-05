# -*- coding: utf-8 -*-
"""Open an existing project and arm a watcher on it, then get out.

For driving a real project without touching the original. Copy the `.project`
somewhere scratch, make a `sync\\` folder beside it, and start the IDE with

    <exe> --profile="<name>" --culture=en --runscript="<this file>"

having set CDS_OPEN_PROJECT to the copy. The project's cds-sync-folder is
pointed at the sync folder next to it, so nothing writes near the original.

Run it a second time in the same IDE and it stops the watcher instead.

Environment:
    CDS_OPEN_PROJECT   the .project to open (required)
    CDS_OPEN_SYNC      the sync folder (default: sync\\ beside the project)
    CDS_OPEN_KEEPALIVE "1" to park in system.delay() rather than returning.
                       For --noUI runs only, which would otherwise exit the
                       moment the script ends. Never with a UI.
    CDS_OPEN_UPDATE    VersionUpdateFlags to open with, "|"-joined, e.g.
                       "SilentMode|UpdateAll" to also update devices and
                       libraries. Off by default: Delta's ScriptEngine 4.0.0.0
                       throws on that overload. The storage-format upgrade an
                       older project asks about is handled either way.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import watch_harness

PROJECT_PATH = os.environ.get("CDS_OPEN_PROJECT")
SYNC_DIR = os.environ.get("CDS_OPEN_SYNC") or (
    os.path.join(os.path.dirname(PROJECT_PATH or "."), "sync"))
KEEPALIVE = os.environ.get("CDS_OPEN_KEEPALIVE") == "1"

if not PROJECT_PATH:
    print("open_copy_and_watch: set CDS_OPEN_PROJECT to the .project to open")
elif not os.path.exists(PROJECT_PATH):
    print("open_copy_and_watch: no such project: " + PROJECT_PATH)
else:
    print("open_copy_and_watch: project  " + PROJECT_PATH)
    print("open_copy_and_watch: sync dir " + SYNC_DIR)
    watch_harness.ensure_dirs(SYNC_DIR)
    project = watch_harness.open_project(globals(), PROJECT_PATH,
                                         os.environ.get("CDS_OPEN_UPDATE"))
    print("open_copy_and_watch: opened " + str(project.path))
    watch_harness.point_sync_folder(project, SYNC_DIR)
    watch_harness.try_save(project)
    if watch_harness.arm(globals()) is not None and KEEPALIVE:
        watch_harness.park(globals())
