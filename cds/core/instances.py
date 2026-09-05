# -*- coding: utf-8 -*-
"""Which IDEs are running a watcher, and which one did the caller mean.

Each watcher keeps a registration file beside its instance directory and
rewrites it every couple of seconds. That heartbeat is the only evidence the
CLI has that an IDE is still there, and it is enough — do NOT reach for
os.kill(pid, 0) to double-check, because on Windows CPython that call
terminates the target process instead of probing it.

Timestamps are stored twice: an ISO string for whoever opens the file, and an
epoch number for the arithmetic here. Deriving one from the other would mean
parsing local time, and local time has an hour a year where that is ambiguous.

Pure Python (PRINCIPLES.md 4): no CODESYS imports.
"""
from __future__ import print_function

import os
import shutil

from cds.core import ipc

STATE_IDLE = "idle"
STATE_BUSY = "busy"

# Starting points, not settled numbers (WATCHER_CLI_PLAN.md 11.3).
HEARTBEAT_INTERVAL_S = 2.0
ALIVE_TIMEOUT_S = 10.0
BUSY_TIMEOUT_S = 120.0
STALE_TIMEOUT_S = 60.0


# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------

def new_registration(instance_id, pid, ide, project_path,
                     sync_dir=None, watcher_version=None, now=None):
    """Build the registration record for a watcher that just started."""
    now = ipc.now(now)
    reg = {
        "instance_id": instance_id,
        "pid": pid,
        "ide": ide,
        "sync_dir": sync_dir,
        "started_at": ipc.iso(now),
        "watcher_version": watcher_version,
    }
    set_project(reg, project_path)
    set_state(reg, STATE_IDLE, now)
    return stamp_heartbeat(reg, now)


def set_project(reg, project_path):
    """Record which project the IDE has open; it can change without a restart."""
    reg["project_path"] = project_path
    reg["project_name"] = os.path.splitext(os.path.basename(project_path or ""))[0]
    return reg


def stamp_heartbeat(reg, now=None):
    """Mark the watcher as still running. Both fields, same instant."""
    now = ipc.now(now)
    reg["heartbeat"] = ipc.iso(now)
    reg["heartbeat_epoch"] = now
    return reg


def set_state(reg, state, now=None):
    """Switch between idle and busy, recording when a busy stretch began."""
    now = ipc.now(now)
    reg["state"] = state
    reg["busy_since"] = ipc.iso(now) if state == STATE_BUSY else None
    reg["busy_since_epoch"] = now if state == STATE_BUSY else None
    return reg


def is_alive(reg, now=None, idle_timeout=ALIVE_TIMEOUT_S,
             busy_timeout=BUSY_TIMEOUT_S):
    """Is this instance still there?

    An idle watcher must have beaten recently. A busy one cannot beat at all
    while a command holds the main thread, so it is trusted for as long as the
    caller is willing to wait for that command.
    """
    now = ipc.now(now)
    if reg.get("state") == STATE_BUSY:
        started = reg.get("busy_since_epoch")
        return started is not None and (now - float(started)) <= busy_timeout
    beat = reg.get("heartbeat_epoch")
    return beat is not None and (now - float(beat)) <= idle_timeout


# --------------------------------------------------------------------------
# The files
# --------------------------------------------------------------------------

def write(root, reg):
    ipc.write_json(ipc.registration_path(root, reg["instance_id"]), reg)


def read(root, instance_id):
    return ipc.read_json(ipc.registration_path(root, instance_id))


def read_all(root):
    """Every registration under root, alive or not, sorted by instance id."""
    out = []
    for name in ipc.json_names(root):
        reg = ipc.read_json(os.path.join(root, name))
        if reg is not None:
            out.append(reg)
    return out


def delete(root, instance_id):
    """Drop an instance: its registration file and its whole directory."""
    ipc.remove_file(ipc.registration_path(root, instance_id))
    shutil.rmtree(ipc.instance_dir(root, instance_id), ignore_errors=True)


def prune_stale(root, now=None, max_age=STALE_TIMEOUT_S):
    """Delete registrations left behind by watchers that died.

    Only idle instances are ever pruned. A busy one is running a command and
    cannot beat while it does; a real import on a real project takes minutes,
    and deleting its directory pulls cmd/ and result/ out from under a live
    process — queued commands vanish and the caller waits for an answer that
    can no longer be written.

    Tying this to the command timeout (the CLI's 120 seconds) looked like
    protection but only covered commands shorter than that, which is not the
    interesting case. Cleaning up after a dead watcher and deciding a command
    has taken too long are different jobs; they do not get to share a number.
    An instance stuck in busy is cleared by re-running Project_watch.py.

    Returns the instance ids that were removed.
    """
    now = ipc.now(now)
    removed = []
    for reg in read_all(root):
        if reg.get("state") == STATE_BUSY:
            continue
        if now - float(reg.get("heartbeat_epoch") or 0.0) <= max_age:
            continue
        delete(root, reg["instance_id"])
        removed.append(reg["instance_id"])
    return removed


# --------------------------------------------------------------------------
# Picking one
# --------------------------------------------------------------------------

class TargetError(Exception):
    """No single instance matched. matches is empty, or holds the candidates."""

    def __init__(self, message, matches=None):
        Exception.__init__(self, message)
        self.matches = list(matches or [])


def resolve_target(regs, target=None, now=None, busy_timeout=BUSY_TIMEOUT_S):
    """Pick the one live instance the caller meant.

    An exact instance id wins. Otherwise target is read as a project name
    (case-insensitive); with no target at all, a lone live instance is it.
    Anything else raises TargetError so the caller can list the candidates.
    """
    alive = [r for r in regs if is_alive(r, now, busy_timeout=busy_timeout)]
    if target:
        for reg in alive:
            if reg.get("instance_id") == target:
                return reg
        matches = [r for r in alive
                   if (r.get("project_name") or "").lower() == target.lower()]
        nothing = "no live IDE matches %r" % (target,)
    else:
        matches = alive
        nothing = "no live IDE found"
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise TargetError(nothing)
    raise TargetError("several live IDEs match; pass --target", matches)
