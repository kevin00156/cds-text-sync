# -*- coding: utf-8 -*-
"""Acceptance launcher: put a watcher on a throwaway project, then get out.

For the real-input acceptance in WATCHER_CLI_PLAN.md 14.5. Start an IDE with

    <exe> --profile="<name>" --runscript="<this file>"

and it builds a scratch project, points cds-sync-folder at a sync folder
beside it, arms the watcher exactly the way Project_watch.py does, and
returns. Once it has returned the IDE belongs to the user again, which is the
thing being measured: clicking File must open its menu on every attempt.

Run it a second time in the same IDE and it stops the watcher instead.

Environment:
    CDS_PROBE_DIR        where to build (default %TEMP%\\cds-watcher-probe)
    CDS_PROBE_POUS       how many POUs to give it (default 3)
    CDS_PROBE_KEEPALIVE  "1" to park in system.delay() instead of returning.
                         Only for --noUI runs, which would otherwise exit the
                         moment the script ends. Never use it with a UI: it is
                         the very thing that makes the IDE unclickable.
"""
import os
import sys
import tempfile
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE_DIR = os.environ.get("CDS_PROBE_DIR",
                           os.path.join(tempfile.gettempdir(),
                                        "cds-watcher-probe"))
POU_COUNT = int(os.environ.get("CDS_PROBE_POUS", "3"))
KEEPALIVE = os.environ.get("CDS_PROBE_KEEPALIVE") == "1"

SYNC_DIR = os.path.join(PROBE_DIR, "sync")
PROJECT_PATH = os.path.join(PROBE_DIR, os.path.basename(PROBE_DIR) + ".project")


def open_or_create():
    """The scratch project, with cds-sync-folder pointing beside it."""
    for directory in (PROBE_DIR, SYNC_DIR):
        if not os.path.isdir(directory):
            os.makedirs(directory)
    if os.path.exists(PROJECT_PATH):
        project = projects.open(PROJECT_PATH)
    else:
        project = projects.create(PROJECT_PATH)
    info = project.get_project_info()
    (info.values if hasattr(info, "values") else info)["cds-sync-folder"] = SYNC_DIR
    return project


def fill(project):
    """Give it a few POUs so export and compare have something to chew on."""
    have = set()
    for child in project.get_children():
        try:
            have.add(str(child.get_name()))
        except Exception:
            pass
    made = 0
    for index in range(POU_COUNT):
        name = "Probe%03d" % index
        if name in have:
            continue
        pou = project.create_pou(name)
        pou.textual_declaration.replace(
            "FUNCTION_BLOCK %s\nVAR\n\tcounter : INT;\nEND_VAR" % name)
        pou.textual_implementation.replace("counter := counter + %d;" % index)
        made += 1
    if made:
        project.save()
    return made


def park():
    """Headless only: keep the process alive so the timer has somewhere to tick.

    system.delay() pumps posted messages, and a WinForms timer tick is one, so
    the watcher still runs. With a UI this would be exactly the bug we fixed.
    """
    print("probe: parked (CDS_PROBE_KEEPALIVE=1); no UI is usable while this runs")
    while session.current() is not None:
        system.delay(200)
    print("probe: watcher stopped, unparking")


print("probe: project  " + PROJECT_PATH)
print("probe: sync dir " + SYNC_DIR)

sys.path.insert(0, REPO_ROOT)
from cds.ide import session

if session.current() is not None:
    session.main(globals())          # second run in this IDE: stop
    print("probe: stopped the watcher")
else:
    project = open_or_create()
    print("probe: created %d POU(s)" % fill(project))
    started = session.main(globals(), version=session.script_version())
    print("probe: armed as " + started.instance_id)
    if KEEPALIVE:
        try:
            park()
        except Exception:
            print(traceback.format_exc())
