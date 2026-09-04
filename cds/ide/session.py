# -*- coding: utf-8 -*-
"""Install a watcher into a running IDE, and take it back out.

Everything here exists because the script that starts the watcher has to end.
While a script runs the main thread belongs to it, and system.delay() pumps
repaints and posted messages but NOT mouse and keyboard — the window looks
alive and cannot be clicked. So the script arms a WinForms timer and returns,
and the watcher lives on in the IDE's own message loop
(WATCHER_CLI_PLAN.md 14; do not undo this without reading that section).

Two consequences shape this module. The watcher has to be kept somewhere that
outlives the script's namespace, which is why it is parked on `sys`. And the
timer has to be created through .NET, which is why nothing here runs under
CPython — the testable half is cds/ide/watcher.py.
"""
from __future__ import print_function

import os
import sys

from cds.ide.watcher import REPO_ROOT, Watcher

TICK_MS = 250

# Where the live watcher is parked. A script's module namespace is not
# guaranteed to survive the script returning; sys always is. The timer hangs
# off the watcher kept here, which is what stops it being collected.
STATE_ATTR = "_cds_watcher"


def main(ide_globals, root=None, version=None, timer_factory=None):
    """Arm the watcher and return, or stop the one this IDE already has.

    Running the script a second time stops it, the way the 1.6.x daemon
    worked. Returning promptly is the feature, not an implementation detail.
    """
    live = current()
    if live is not None:
        stop(live)
        return None
    watcher = Watcher(ide_globals, root, version)
    watcher.start()
    factory = timer_factory or _winforms_timer
    watcher.timer = factory(TICK_MS, _on_tick(watcher))
    setattr(sys, STATE_ATTR, watcher)
    print("watcher: run Project_watch.py again to stop it")
    return watcher


def stop(watcher):
    """The single way out, whether the CLI asked or the script was re-run."""
    if watcher.timer is not None:
        watcher.timer.Stop()
        watcher.timer.Dispose()
        watcher.timer = None
    watcher.running = False
    watcher.shutdown()
    if current() is watcher:
        delattr(sys, STATE_ATTR)


def current():
    """The watcher this IDE is running, or None."""
    return getattr(sys, STATE_ATTR, None)


def _on_tick(watcher):
    """What the timer calls, so the Watcher never has to know about `sys`.

    The teardown runs at the *start* of the tick after `stop` was answered,
    which leaves the caller a whole interval to collect that answer before the
    instance directory goes away.
    """
    def on_tick(sender=None, event_args=None):
        if not watcher.running:
            stop(watcher)
            return
        watcher.tick()
    return on_tick


def _winforms_timer(interval_ms, handler):
    """A timer hung on the IDE's own message loop. Ticks on the UI thread."""
    import clr
    clr.AddReference("System.Windows.Forms")
    from System.Windows.Forms import Timer
    timer = Timer()
    timer.Interval = interval_ms
    timer.Tick += handler
    timer.Start()
    return timer


def script_version():
    """The version the other Project_*.py scripts report. IDE-side only:
    `imp` is gone from CPython 3.12, and nothing under test calls this."""
    import imp
    path = os.path.join(REPO_ROOT, "codesys_constants.pyw")
    return imp.load_source("codesys_constants", path).SCRIPT_VERSION
