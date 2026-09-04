# -*- coding: utf-8 -*-
"""Manual probe: can the IDE's IronPython 2.7 import the cds package at all?

The whole watcher design rests on cds/core being importable from inside the
IDE. Nothing in this repo has ever done that — the live scripts load .pyw
files by path with imp.load_source instead. So find out before building on it
(WATCHER_CLI_PLAN.md 3.8 and 11.1).

Run it from Tools > Scripting > Execute Script File... inside any open IDE, or
headless with `CODESYS.exe --noUI --runscript="<this file>"`. It imports the
three protocol modules, exercises them against a scratch directory under
%TEMP%, and reports to the log beside this file — plus a message box, but only
when there is a UI to show it in. Nothing in your project is touched.
"""
import os
import sys
import tempfile
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "probe_cds_import.log")


def log(text):
    handle = open(LOG, "a")
    handle.write(text + "\n")
    handle.close()
    print(text)


def check():
    """Import the protocol and put one command through it. Returns a report."""
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    from cds.core import commands, instances, ipc

    root = os.path.join(tempfile.gettempdir(), "cds-probe-instances")
    instance_id = ipc.make_instance_id("C:\\probe\\demo.project", os.getpid())
    ipc.ensure_dirs(root, instance_id)

    reg = instances.new_registration(instance_id, os.getpid(), "probe",
                                     "C:\\probe\\demo.project")
    instances.write(root, reg)
    cmd = commands.write_command(root, instance_id, "ping")
    got = commands.next_command(root, instance_id)
    commands.write_result(root, instance_id, commands.new_result(got, True))
    result = commands.take_result(root, instance_id, cmd["id"])
    picked = instances.resolve_target(instances.read_all(root), "demo")
    instances.delete(root, instance_id)

    return "\n".join([
        "import cds.core: OK",
        "python: " + sys.version.replace("\n", " "),
        "instance id: " + instance_id,
        "round trip: " + str(bool(result and result["ok"])),
        "resolve_target: " + picked["instance_id"],
        "pid from: " + ("os.getpid" if hasattr(os, "getpid") else "MISSING"),
    ])


try:
    report = check()
except Exception:
    report = "import cds.core: FAILED\n\n" + traceback.format_exc()

log(report)
if system.ui_present:  # --noUI has no message box to pop, and must not block
    system.ui.info(report)
