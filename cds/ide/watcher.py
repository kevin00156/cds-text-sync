# -*- coding: utf-8 -*-
"""What one IDE's watcher does on each tick: claim a command, answer it, beat.

Nothing here starts or stops a watcher — cds/ide/session.py does that, and it
does it by arming a timer and letting the script end, because a script that
keeps running holds the main thread and leaves the IDE unclickable
(WATCHER_CLI_PLAN.md 14). Keeping that half out of this file is what lets this
half be tested under CPython.

Ticks land on the UI thread, so object-model calls from them are legal and no
cross-thread machinery is needed. No threads, no time.sleep(), no
execute_on_primary_thread (SP21 removed it).

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
from cds.ide import display, messages, project, silent


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
    """One IDE's listener: on every tick, claim a command, answer it, beat."""

    def __init__(self, ide_globals, root=None, version=None):
        if "system" not in ide_globals:
            raise KeyError("the watcher needs the IDE's globals, and this "
                           "mapping has no `system` in it")
        self.ide = ide_globals
        self.root = root or ipc.default_root()
        self.running = True
        self.busy = False
        self.timer = None
        now = ipc.now()
        path = self._open_project_path()
        self.reg = instances.new_registration(
            ipc.make_instance_id(path, os.getpid()), os.getpid(),
            project.ide_name(), path, watcher_version=version, now=now)
        self.instance_id = self.reg["instance_id"]
        self.started_epoch = now
        self.doing = None       # the command running right now, for the display
        self.done = 0
        self.last = None        # {"command", "ok", "elapsed"} of the last one
        self.display_to = None  # set by session when there is a window to feed
        self.form = None        # the window itself, so session can close it
        self._last_beat = 0.0
        self._deferring = False
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
        messages.note(self.ide, "cds-ide: listening as " + self.instance_id)
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

    def tick(self):
        """One turn: take a command if there is one, answer it, beat.

        Never raises — an exception escaping a WinForms handler becomes a
        thread-exception dialog that can take the IDE down. Returns whether a
        turn actually happened.
        """
        if not self.running or self.busy or silent.running():
            # Not running: the teardown belongs to whoever armed us. Busy: a
            # command is pumping messages of its own and the timer fired
            # again on top of it. silent.running(): some other caller has a
            # script going — this one is belt-and-braces, self.busy already
            # covers our own commands.
            return False
        self.busy = True
        try:
            cmd = commands.next_command(self.root, self.instance_id)
            if cmd is not None:
                self.run_one(cmd)
            self.beat_if_due()
            self._show()
        except SystemExit:
            raise
        except BaseException:
            print("watcher: tick failed\n" + traceback.format_exc())
        finally:
            self.busy = False
        return True

    def shutdown(self):
        """Leave nothing behind for the next watcher to trip over."""
        try:
            instances.delete(self.root, self.instance_id)
        except EnvironmentError as exc:
            # A CLI reading the file right now holds it open. Leaving the
            # registration behind is survivable — the next watcher's
            # prune_stale clears it — and raising here would bury whatever
            # actually stopped the loop.
            print("watcher: could not clear %s (%s)" % (self.instance_id, exc))
        messages.note(self.ide, "cds-ide: stopped " + self.instance_id)
        print("watcher: stopped " + self.instance_id)

    # -- one command -------------------------------------------------------

    def run_one(self, cmd):
        """Claim, run, and answer a single command. Never raises.

        Answering is inside the try as well: writing the result can hit the
        same Windows sharing violation as the heartbeat (section 12), and an
        instance left stuck in `busy` is worse than a lost answer. Once
        busy_since goes stale the CLI stops seeing the instance, while
        prune_stale keeps sparing it because the heartbeat is fresh — nothing
        recovers from that but restarting the script by hand.
        """
        started = ipc.now()
        result = None
        try:
            commands.delete_command(self.root, self.instance_id, cmd["id"])
            self._beat(started, instances.STATE_BUSY)
            self.doing = cmd.get("command")
            # Paint BUSY before the work starts: the IDE stops repainting for
            # the whole of an export, so afterwards is too late to say so.
            self._show()
            messages.note(self.ide, "cds-ide: %s started" % self.doing)
            result = self._answer(cmd, started)
            commands.write_result(self.root, self.instance_id, result)
            # A caller that gave up before we answered leaves its result
            # behind. Sweeping here keeps the directory bounded on a watcher
            # that runs for days; what we just wrote is far too young to catch.
            commands.prune_results(self.root, self.instance_id)
        except Exception:
            print("watcher: answering %s failed\n%s"
                  % (cmd.get("id"), traceback.format_exc()))
        finally:
            self._finished(cmd, result, started)
            self._beat(ipc.now(), instances.STATE_IDLE)
            self._show()
        return result

    def _finished(self, cmd, result, started):
        """Remember how that one went, for the status window and the log."""
        self.doing = None
        self.done += 1
        ok = bool(result and result.get("ok"))
        self.last = {"command": cmd.get("command"), "ok": ok,
                     "elapsed": ipc.now() - started}
        messages.note(self.ide, "cds-ide: %s %s in %.1fs"
                      % (cmd.get("command"), "ok" if ok else "FAILED",
                         self.last["elapsed"]),
                      ok=ok)

    def _show(self):
        """Push the current picture at whatever is displaying it.

        A window that throws is a cosmetic problem; it must not be able to
        stop the watcher answering commands.
        """
        if self.display_to is None:
            return
        try:
            self.display_to(display.describe(self))
        except Exception:
            print("watcher: status window failed\n" + traceback.format_exc())

    def _answer(self, cmd, started):
        """Turn one command into a result record, whatever it takes."""
        try:
            return self._dispatch(cmd, started)
        except silent.NeedsInput as need:  # a dialog outside a script run
            return commands.new_result(cmd, False, started_at=started,
                                       error=need.question,
                                       needs_input=need.as_record())
        except Exception:
            return commands.new_result(cmd, False, started_at=started,
                                       error=traceback.format_exc())

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
        """Hand back the instance record. The heartbeat keeps it current."""
        live = dict(self.reg)
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
        args = cmd.get("args") or {}
        outcome = silent.run(self.ide, os.path.join(REPO_ROOT, script), entry,
                             args)
        error = outcome.error_text() or _wrong_application(cmd, args, outcome)
        return commands.new_result(
            cmd, not error, started_at=started,
            error=error,
            messages=outcome.messages,
            stdout_tail=self._tail(cmd, outcome),
            needs_input=None if outcome.needs is None else outcome.needs.as_record())

    def _tail(self, cmd, outcome):
        """What the script printed, plus what the IDE has to say about it.

        Project_Build.py only reports counts; the errors themselves — object
        and line — live in the IDE's message store, and a caller that cannot
        see the IDE has no other way to reach them.
        """
        if cmd["command"] != "build":
            return outcome.stdout_tail
        report = messages.build_report(self.ide)
        if not report:
            return outcome.stdout_tail
        return "\n".join([outcome.stdout_tail, "--- build messages ---"] +
                         report)

    # -- instance record ---------------------------------------------------

    def _open_project_path(self):
        return project.path_of(self.ide.get("projects"))

    def _refresh_project(self):
        """Follow the project the IDE has open now, not the one it had at start.

        Closing a project and opening another does not restart the watcher,
        and `list` is how a caller picks its target, so a stale name here
        means it picks the wrong IDE or none at all. instance_id keeps its
        birth name — that one is a directory.
        """
        instances.set_project(self.reg, self._open_project_path())
        self.reg["sync_dir"] = project.sync_dir(self.ide.get("projects"))

    def beat_if_due(self, now=None):
        """Write the heartbeat, but only every HEARTBEAT_INTERVAL_S."""
        now = ipc.now(now)
        if now - self._last_beat < instances.HEARTBEAT_INTERVAL_S:
            return False
        return self._beat(now)

    def _beat(self, now, state=None):
        """Write the heartbeat, or shrug and let the next turn try again.

        On Windows the registration cannot be replaced while a CLI has it open
        for reading, and the CLI opens it on every command. The window is
        microseconds and the next attempt is one loop turn away, so a missed
        beat is not worth ending a watcher over. _last_beat is left alone so
        the retry happens on the next turn rather than in two seconds.
        """
        if state is not None:
            instances.set_state(self.reg, state, now)
        self._refresh_project()
        instances.stamp_heartbeat(self.reg, now)
        try:
            instances.write(self.root, self.reg)
        except EnvironmentError as exc:
            if not self._deferring:  # once per episode, not once per turn
                print("watcher: heartbeat deferred (%s)" % exc)
                self._deferring = True
            return False
        self._deferring = False
        self._last_beat = now
        return True


def _info(text):
    return {"level": "info", "text": text}


def _wrong_application(cmd, args, outcome):
    """Did build compile the application the caller asked for?

    Project_Build.py only offers the chooser when the project property
    cds-text-sync-multipleApps is already true, and it refreshes that flag
    *after* choosing. So the first build after a second application appears
    skips the chooser entirely, compiles the active one and reports success —
    with --app silently doing nothing. Check the name it reports instead.
    """
    wanted = args.get("app")
    if cmd.get("command") != "build" or not wanted:
        return None
    for message in outcome.messages:
        if wanted in message["text"]:
            return None
    return ("build did not use --app %r; the project's multiple-application "
            "flag is probably not set yet, so it built the active application "
            "instead. Run build again, or export once to refresh the flag."
            % (wanted,))
