# -*- coding: utf-8 -*-
"""The command loop that keeps one IDE listening while you keep working in it.

It never returns and it never leaves the main thread. Waiting is done with
system.delay(), which serves the IDE's message loop, so the IDE stays usable
between commands — see docs/RESEARCH_HTTP_IDE_CONTROL.md 3.2. While a command
actually runs the IDE is busy; that is the platform, not a bug here.

No threads, no time.sleep(), no execute_on_primary_thread (SP21 removed it).

A command is claimed by deleting its file *before* running it. The plan had
the delete last, but a watcher that dies mid-import would then find the same
import queued again on restart. A lost result costs the caller a timeout; a
repeated import costs it a project.
"""
from __future__ import print_function

import os
import sys
import traceback

from cds.core import commands, instances, ipc
from cds.ide import silent

POLL_MS = 50

# The repo root, where the Project_*.py scripts live: cds/ide/watcher.py -> ../../
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Command -> the live script it presses, and the function that is its button.
# These are the scripts in the repo root, not the cds.app stubs.
SCRIPTS = {
    "export": ("Project_export.py", "main"),
    "import": ("Project_import.py", "main"),
    "compare": ("Project_compare.py", "main"),
    "build": ("Project_Build.py", "main"),
}


class Watcher(object):
    """One IDE's command loop: claim, run, answer, beat, wait."""

    def __init__(self, ide_globals, root=None, version=None):
        self.ide = ide_globals
        self.system = ide_globals["system"]
        self.root = root or ipc.default_root()
        self.running = True
        now = ipc.now()
        path = self._open_project_path()
        self.reg = instances.new_registration(
            ipc.make_instance_id(path, os.getpid()), os.getpid(),
            sys.version.replace("\n", " "), path,
            watcher_version=version, now=now)
        self.instance_id = self.reg["instance_id"]
        self._last_beat = 0.0
        self.handlers = {
            "ping": self._ping,
            "status": self._status,
            "stop": self._stop,
        }
        for name in SCRIPTS:
            self.handlers[name] = self._run_script

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        """Claim an instance directory and announce we are listening."""
        instances.prune_stale(self.root)
        self._refuse_to_double_book()
        ipc.ensure_dirs(self.root, self.instance_id)
        commands.prune_results(self.root, self.instance_id)
        self._beat(ipc.now())
        self.system.abortable = True  # Cancel on the progress display -> KeyboardInterrupt
        print("watcher: listening as " + self.instance_id)
        print("watcher: " + ipc.instance_dir(self.root, self.instance_id))

    def _refuse_to_double_book(self):
        """Two watchers in one IDE would fight over the same directory."""
        existing = instances.read(self.root, self.instance_id)
        if existing is not None and instances.is_alive(existing):
            raise RuntimeError(
                "a watcher is already listening as %s (started %s) — stop it "
                "before starting another" % (self.instance_id,
                                             existing.get("started_at")))

    def run(self):
        """Poll until stop or Cancel. The only place that waits."""
        while self.running:
            cmd = commands.next_command(self.root, self.instance_id)
            if cmd is not None:
                self.run_one(cmd)
            self.beat_if_due()
            self.system.delay(POLL_MS)

    def shutdown(self):
        """Leave nothing behind for the next watcher to trip over."""
        instances.delete(self.root, self.instance_id)
        print("watcher: stopped " + self.instance_id)

    # -- one command -------------------------------------------------------

    def run_one(self, cmd):
        """Claim, run, and answer a single command. Never raises."""
        started = ipc.now()
        commands.delete_command(self.root, self.instance_id, cmd["id"])
        self._beat(started, instances.STATE_BUSY)
        try:
            result = self._dispatch(cmd, started)
        except silent.NeedsInput as need:  # a dialog outside a script run
            result = commands.new_result(cmd, False, started_at=started,
                                         error=need.question,
                                         needs_input=need.as_record())
        except Exception:
            result = commands.new_result(cmd, False, started_at=started,
                                         error=traceback.format_exc())
        commands.write_result(self.root, self.instance_id, result)
        self._beat(ipc.now(), instances.STATE_IDLE)
        return result

    def _dispatch(self, cmd, started):
        handler = self.handlers.get(cmd.get("command"))
        if handler is None:
            known = ", ".join(sorted(self.handlers))
            return commands.new_result(
                cmd, False, started_at=started,
                error="unknown command %r; this watcher knows %s"
                      % (cmd.get("command"), known))
        return handler(cmd, started)

    # -- the commands ------------------------------------------------------

    def _ping(self, cmd, started):
        return commands.new_result(cmd, True, started_at=started,
                                   messages=[_info("pong from " + self.instance_id)])

    def _status(self, cmd, started):
        """Hand back the instance record with the open project re-read.

        A project can be closed and another opened without restarting the
        watcher, so do not trust what __init__ saw. The instance id keeps the
        project it was born with — it names a directory that already exists.
        """
        live = instances.set_project(dict(self.reg), self._open_project_path())
        # Answering this is what makes us busy, so reporting "busy" would say
        # nothing. Report the state we go back to; `list` shows the live one.
        instances.set_state(live, instances.STATE_IDLE, started)
        return commands.new_result(cmd, True, started_at=started, data=live,
                                   messages=[_info(live["project_path"] or
                                                   "no project open")])

    def _stop(self, cmd, started):
        self.running = False
        return commands.new_result(cmd, True, started_at=started,
                                   messages=[_info("stopping " + self.instance_id)])

    def _run_script(self, cmd, started):
        """Press the button on one of the live Project_*.py scripts.

        The scripts report success and failure by popping dialogs, so the
        stand-in UI's messages are the only verdict there is.
        """
        script, entry = SCRIPTS[cmd["command"]]
        outcome = silent.run(self.ide, os.path.join(REPO_ROOT, script), entry,
                             cmd.get("args") or {})
        return commands.new_result(
            cmd, outcome.ok(), started_at=started,
            error=outcome.error_text(),
            messages=outcome.messages,
            stdout_tail=outcome.stdout_tail,
            needs_input=None if outcome.needs is None else outcome.needs.as_record())

    # -- instance record ---------------------------------------------------

    def _open_project_path(self):
        """The primary project's path, or None when no project is open."""
        primary = getattr(self.ide.get("projects"), "primary", None)
        path = getattr(primary, "path", None)
        return None if path is None else str(path)

    def beat_if_due(self, now=None):
        """Write the heartbeat, but only every HEARTBEAT_INTERVAL_S."""
        now = ipc.now(now)
        if now - self._last_beat < instances.HEARTBEAT_INTERVAL_S:
            return False
        self._beat(now)
        return True

    def _beat(self, now, state=None):
        if state is not None:
            instances.set_state(self.reg, state, now)
        instances.stamp_heartbeat(self.reg, now)
        instances.write(self.root, self.reg)
        self._last_beat = now


def _info(text):
    return {"level": "info", "text": text}


def main(ide_globals, root=None, version=None):
    """Entry point for Project_watch.py. Returns only when told to stop."""
    watcher = Watcher(ide_globals, root, version)
    watcher.start()
    try:
        watcher.run()
    except KeyboardInterrupt:  # the user hit Cancel on the progress display
        print("watcher: cancelled")
    finally:
        watcher.shutdown()
    return watcher
