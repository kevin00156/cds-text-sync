# -*- coding: utf-8 -*-
"""What the status window should be showing right now.

Kept apart from the window itself so the decisions — is it busy, did the last
command fail, how long has it been up — are plain Python that CPython can
test. cds/ide/statusform.py only paints what this returns.
"""
from __future__ import print_function

from cds.core import ipc

IDLE = "idle"
BUSY = "busy"
FAILED = "failed"

LISTENING = "LISTENING"


def describe(watcher, now=None):
    """The three lines and the colour, from the watcher's own state.

    `level` is what the headline is painted with: busy while a command runs,
    failed until a later command succeeds, idle otherwise. Failure sticks on
    purpose — a red bar the user did not see happen is the whole point.
    """
    now = ipc.now(now)
    return {
        "headline": _headline(watcher),
        "level": _level(watcher),
        "project": watcher.reg.get("project_name") or "no project",
        "instance_id": watcher.instance_id,
        "detail": _detail(watcher, now),
    }


def _headline(watcher):
    if watcher.doing:
        return "BUSY: " + watcher.doing
    return LISTENING


def _level(watcher):
    if watcher.doing:
        return BUSY
    if watcher.last and not watcher.last.get("ok"):
        return FAILED
    return IDLE


def _detail(watcher, now):
    """done 3 · last export ok 7.5s · up 00:41:12 · beat 11:02:13"""
    parts = ["done %d" % watcher.done]
    if watcher.last:
        parts.append("last %s %s %.1fs" % (watcher.last.get("command"),
                                           "ok" if watcher.last.get("ok")
                                           else "FAILED",
                                           watcher.last.get("elapsed") or 0.0))
    parts.append("up " + elapsed_clock(now - watcher.started_epoch))
    beat = watcher.reg.get("heartbeat_epoch")
    if beat:
        parts.append("beat " + ipc.iso(beat).split("T")[-1])
    return " · ".join(parts)


def elapsed_clock(seconds):
    """Seconds as HH:MM:SS. Negative clocks are a clock change, not a fact."""
    seconds = int(max(0, seconds))
    return "%02d:%02d:%02d" % (seconds // 3600, (seconds // 60) % 60,
                               seconds % 60)
