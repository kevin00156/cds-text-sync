# -*- coding: utf-8 -*-
"""Tests for cds.ide.watcher and the arming half in cds.ide.session.

The watcher takes the CODESYS globals as an argument instead of reaching for
them, and its timer comes from an injected factory, so a fake `system`, a fake
`projects` and a fake timer are enough to drive everything under CPython.
What this cannot show is whether the real IDE is clickable while the watcher
runs — that needs real mouse input (WATCHER_CLI_PLAN.md 14.5).
"""
import os
import sys

import pytest

from cds.core import commands, instances, ipc
from cds.ide import session, watcher


class FakeSystem(object):
    """Stands in for CODESYS's `system`."""

    def delay(self, milliseconds):
        pass


class FakeProjectInfo(object):
    """Shaped like CODESYS's project info: a .values mapping of properties."""

    def __init__(self, values):
        self.values = values


class FakeProject(object):
    def __init__(self, path):
        self.path = path
        self.props = {}

    def get_project_info(self):
        return FakeProjectInfo(self.props)


class FakeProjects(object):
    def __init__(self, path):
        self.primary = FakeProject(path) if path else None


class FakeTimer(object):
    """Stands in for System.Windows.Forms.Timer; ticks only when told to."""

    def __init__(self, interval_ms, handler):
        self.interval_ms = interval_ms
        self.handler = handler
        self.started = True
        self.disposed = False

    def Stop(self):
        self.started = False

    def Dispose(self):
        self.disposed = True


def make_globals(path="C:\\p\\softplc.project"):
    return {"system": FakeSystem(), "projects": FakeProjects(path)}


@pytest.fixture
def root(tmp_path):
    return str(tmp_path)


@pytest.fixture(autouse=True)
def no_leftover_watcher():
    """A watcher parks itself on sys; never let one leak between tests."""
    yield
    if session.current() is not None:
        delattr(session.sys, session.STATE_ATTR)


# --- registration ----------------------------------------------------------

def test_the_watcher_registers_itself_on_start(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    reg = instances.read(root, watch.instance_id)
    assert reg["project_name"] == "softplc"
    assert reg["pid"] == os.getpid()
    assert instances.is_alive(reg)


def test_start_makes_the_command_and_result_directories(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    assert os.path.isdir(ipc.command_dir(root, watch.instance_id))
    assert os.path.isdir(ipc.result_dir(root, watch.instance_id))


def test_shutdown_leaves_nothing_behind(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    watch.shutdown()
    assert instances.read(root, watch.instance_id) is None
    assert not os.path.exists(ipc.instance_dir(root, watch.instance_id))


def test_a_second_watcher_in_the_same_ide_is_refused(root):
    ide = make_globals()
    watcher.Watcher(ide, root).start()
    with pytest.raises(RuntimeError):
        watcher.Watcher(ide, root).start()


def test_a_stale_registration_is_cleared_on_start(root):
    dead = instances.new_registration("ghost-1", 9, "old", "C:\\p\\ghost.project",
                                      now=ipc.now() - 600.0)
    instances.write(root, dead)
    watcher.Watcher(make_globals(), root).start()
    assert instances.read(root, "ghost-1") is None


def test_start_sweeps_results_nobody_collected(root):
    watch = watcher.Watcher(make_globals(), root)
    ipc.ensure_dirs(root, watch.instance_id)
    commands.write_result(root, watch.instance_id, {"id": "old-1", "ok": True})
    stale = os.path.join(ipc.result_dir(root, watch.instance_id), "old-1.json")
    os.utime(stale, (ipc.now() - 7200.0, ipc.now() - 7200.0))
    watch.start()
    assert commands.read_result(root, watch.instance_id, "old-1") is None


# --- the heartbeat ---------------------------------------------------------

def test_the_heartbeat_waits_its_turn(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    now = ipc.now()
    assert watch.beat_if_due(now + 0.5) is False
    assert watch.beat_if_due(now + instances.HEARTBEAT_INTERVAL_S + 1.0) is True


def test_a_locked_registration_defers_the_beat_instead_of_killing_it(root,
                                                                     monkeypatch):
    # A CLI reading the file holds it open, and Windows will not let the
    # rename land. That is a missed beat, not the end of the watcher.
    watch = watcher.Watcher(make_globals(), root)
    watch.start()

    def locked(_root, _reg):
        raise OSError(13, "used by another process")

    monkeypatch.setattr(instances, "write", locked)
    now = ipc.now() + instances.HEARTBEAT_INTERVAL_S + 1.0
    assert watch.beat_if_due(now) is False
    monkeypatch.undo()
    # _last_beat was left alone, so the very next turn retries.
    assert watch.beat_if_due(now) is True


def test_a_long_lock_is_reported_once_not_every_turn(root, monkeypatch, capsys):
    # The retry happens on every tick; saying so each time would bury the
    # IDE's message view under hundreds of identical lines.
    watch = watcher.Watcher(make_globals(), root)
    watch.start()

    def locked(_root, _reg):
        raise OSError(13, "used by another process")

    monkeypatch.setattr(instances, "write", locked)
    now = ipc.now()
    for turn in range(20):
        watch.beat_if_due(now + instances.HEARTBEAT_INTERVAL_S + turn)
    assert capsys.readouterr().out.count("heartbeat deferred") == 1


def test_a_locked_registration_does_not_break_shutdown(root, monkeypatch):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()

    def locked(_root, _instance_id):
        raise OSError(13, "used by another process")

    monkeypatch.setattr(instances, "delete", locked)
    watch.shutdown()  # the reason the loop stopped must not be buried here


# --- one command -----------------------------------------------------------

def run(watch, name, args=None):
    """Queue a command, let the watcher take it, hand back the result."""
    cmd = commands.write_command(watch.root, watch.instance_id, name, args)
    watch.run_one(commands.next_command(watch.root, watch.instance_id))
    return commands.take_result(watch.root, watch.instance_id, cmd["id"])


def test_ping_answers(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    result = run(watch, "ping")
    assert result["ok"] is True
    assert "pong" in result["messages"][0]["text"]


def test_status_reports_the_project_that_is_open_now(root):
    ide = make_globals()
    watch = watcher.Watcher(ide, root)
    watch.start()
    ide["projects"].primary = FakeProject("C:\\p\\boiler.project")
    result = run(watch, "status")
    assert result["data"]["project_name"] == "boiler"
    assert result["data"]["instance_id"] == watch.instance_id


def test_status_does_not_report_itself_as_busy(root):
    # The watcher is busy *because* it is answering status, which tells the
    # caller nothing. `list` is where the live state belongs.
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    data = run(watch, "status")["data"]
    assert data["state"] == instances.STATE_IDLE
    assert data["busy_since"] is None


def test_status_survives_the_project_being_closed(root):
    ide = make_globals()
    watch = watcher.Watcher(ide, root)
    watch.start()
    ide["projects"].primary = None
    assert run(watch, "status")["data"]["project_path"] is None


def test_stop_takes_the_watcher_out_of_service(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    assert run(watch, "stop")["ok"] is True
    assert watch.running is False


def test_an_unknown_command_fails_loudly_and_says_what_it_knows(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    result = run(watch, "frobnicate")
    assert result["ok"] is False
    assert "frobnicate" in result["error"] and "ping" in result["error"]


def test_a_handler_that_raises_becomes_a_failed_result(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()

    def boom(cmd, started):
        raise ValueError("the IDE said no")

    watch.handlers["ping"] = boom
    result = run(watch, "ping")
    assert result["ok"] is False
    assert "the IDE said no" in result["error"]


def test_a_command_is_claimed_before_it_runs(root):
    # A watcher that dies mid-command must not find it queued again.
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    seen = {}

    def check(cmd, started):
        seen["queued"] = commands.list_command_ids(root, watch.instance_id)
        return commands.new_result(cmd, True, started_at=started)

    watch.handlers["ping"] = check
    run(watch, "ping")
    assert seen["queued"] == []


def test_the_instance_goes_busy_while_a_command_runs(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    seen = {}

    def check(cmd, started):
        seen["state"] = instances.read(root, watch.instance_id)["state"]
        return commands.new_result(cmd, True, started_at=started)

    watch.handlers["ping"] = check
    run(watch, "ping")
    assert seen["state"] == instances.STATE_BUSY
    assert instances.read(root, watch.instance_id)["state"] == instances.STATE_IDLE


def test_answering_sweeps_results_nobody_came_back_for(root):
    # A caller that timed out leaves its result behind; a watcher that runs
    # for days would otherwise collect them forever.
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    commands.write_result(root, watch.instance_id, {"id": "old-1", "ok": True})
    stale = os.path.join(ipc.result_dir(root, watch.instance_id), "old-1.json")
    os.utime(stale, (ipc.now() - 7200.0, ipc.now() - 7200.0))
    fresh = run(watch, "ping")
    assert commands.read_result(root, watch.instance_id, "old-1") is None
    assert fresh["ok"] is True  # and the answer just written survived


# --- the tick --------------------------------------------------------------

def test_a_tick_answers_one_queued_command(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    commands.write_command(root, watch.instance_id, "ping",
                           cmd_id="1725453665000-aaaaaa")
    assert watch.tick() is True
    assert commands.read_result(root, watch.instance_id,
                                "1725453665000-aaaaaa")["ok"] is True


def test_an_idle_tick_just_beats(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    assert watch.tick() is True
    assert commands.list_command_ids(root, watch.instance_id) == []


def test_a_tick_that_arrives_mid_command_turns_straight_around(root):
    # An import pumps messages of its own, so the timer fires again while the
    # import is still going. Two imports at once would be a disaster.
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    seen = []

    def reentrant(cmd, started):
        seen.append(watch.tick())  # the timer, firing inside the command
        return commands.new_result(cmd, True, started_at=started)

    watch.handlers["ping"] = reentrant
    commands.write_command(root, watch.instance_id, "ping")
    watch.tick()
    assert seen == [False]


def test_a_tick_never_lets_an_exception_escape(root, capsys):
    # An exception out of a WinForms handler becomes a thread-exception dialog.
    watch = watcher.Watcher(make_globals(), root)
    watch.start()

    def boom(*args, **kwargs):
        raise KeyboardInterrupt("even a BaseException")

    watch.beat_if_due = boom
    assert watch.tick() is True
    assert "tick failed" in capsys.readouterr().out
    assert watch.busy is False  # and the guard was released


# --- arming and disarming --------------------------------------------------

def test_main_arms_a_timer_and_returns(root):
    made = []

    def factory(interval_ms, handler):
        made.append(FakeTimer(interval_ms, handler))
        return made[-1]

    watch = session.main(make_globals(), root, timer_factory=factory)
    assert made[0].interval_ms == session.TICK_MS
    assert session.current() is watch
    assert instances.is_alive(instances.read(root, watch.instance_id))
    made[0].handler()  # a WinForms tick arrives with no arguments used here
    assert watch.running is True


def test_running_the_script_again_stops_the_watcher(root):
    timers = []

    def factory(interval_ms, handler):
        timers.append(FakeTimer(interval_ms, handler))
        return timers[-1]

    watch = session.main(make_globals(), root, timer_factory=factory)
    assert session.main(make_globals(), root, timer_factory=factory) is None
    assert len(timers) == 1  # the second run stopped, it did not start
    assert timers[0].started is False and timers[0].disposed is True
    assert session.current() is None
    assert instances.read(root, watch.instance_id) is None


def test_the_stop_command_tears_down_on_the_following_tick(root):
    # The answer to `stop` has to survive long enough to be collected.
    timers = []

    def factory(interval_ms, handler):
        timers.append(FakeTimer(interval_ms, handler))
        return timers[-1]

    watch = session.main(make_globals(), root, timer_factory=factory)
    on_tick = timers[0].handler
    cmd = commands.write_command(root, watch.instance_id, "stop")
    on_tick()
    assert commands.read_result(root, watch.instance_id, cmd["id"])["ok"] is True
    assert timers[0].started is True  # still there for the caller to read it

    on_tick()
    assert timers[0].started is False and timers[0].disposed is True
    assert instances.read(root, watch.instance_id) is None
    assert session.current() is None


# --- staying answerable when writing the answer fails ----------------------

def test_a_failure_after_the_command_still_puts_the_state_back(root,
                                                               monkeypatch):
    # Stuck in busy is worse than a lost answer: once busy_since goes stale
    # the CLI stops seeing the instance, and prune_stale keeps sparing it
    # because the heartbeat is fresh. Nothing recovers from that on its own.
    watch = watcher.Watcher(make_globals(), root)
    watch.start()

    def boom(*args, **kwargs):
        raise OSError(13, "used by another process")

    monkeypatch.setattr(commands, "write_result", boom)
    cmd = commands.write_command(root, watch.instance_id, "ping")
    watch.run_one(commands.next_command(root, watch.instance_id))
    assert instances.read(root, watch.instance_id)["state"] == \
        instances.STATE_IDLE
    assert watch.tick() is True  # and the watcher is still in service
    assert cmd["id"]


def test_a_command_is_still_claimed_when_answering_fails(root, monkeypatch):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    monkeypatch.setattr(commands, "prune_results",
                        lambda *a, **k: 1 / 0)
    commands.write_command(root, watch.instance_id, "ping")
    watch.run_one(commands.next_command(root, watch.instance_id))
    assert commands.list_command_ids(root, watch.instance_id) == []


# --- following the project the IDE has open now ----------------------------

def test_the_registration_follows_a_project_swap(root):
    # `list` is how a caller picks its target; a name frozen at start-up means
    # it picks the wrong IDE or none at all.
    ide = make_globals()
    watch = watcher.Watcher(ide, root)
    watch.start()
    ide["projects"].primary = FakeProject(r"C:\p\boiler.project")
    watch.beat_if_due(ipc.now() + instances.HEARTBEAT_INTERVAL_S + 1.0)
    reg = instances.read(root, watch.instance_id)
    assert reg["project_name"] == "boiler"
    assert reg["instance_id"] == watch.instance_id  # the directory keeps its name


def test_the_sync_folder_is_reported(root):
    ide = make_globals()
    ide["projects"].primary.props["cds-sync-folder"] = r"D:\work\sync"
    watch = watcher.Watcher(ide, root)
    watch.start()
    assert instances.read(root, watch.instance_id)["sync_dir"] == r"D:\work\sync"


def test_a_relative_sync_folder_resolves_against_the_project(root):
    ide = make_globals()
    ide["projects"].primary.props["cds-sync-folder"] = "./export"
    watch = watcher.Watcher(ide, root)
    watch.start()
    assert instances.read(root, watch.instance_id)["sync_dir"] == \
        os.path.normpath(r"C:\p\export")


def test_an_unset_sync_folder_reads_as_nothing(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    assert instances.read(root, watch.instance_id)["sync_dir"] is None


def test_the_ide_field_names_the_product(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    # IronPython 2.7.7 is both Delta 1.10 and Lenze 3.24, so the version
    # string alone cannot tell them apart.
    assert os.path.basename(sys.executable) in \
        instances.read(root, watch.instance_id)["ide"]


def test_globals_without_system_are_refused_at_once(root):
    with pytest.raises(KeyError):
        watcher.Watcher({"projects": FakeProjects(None)}, root)


# --- build compiled something else -----------------------------------------

def test_build_says_so_when_app_was_ignored(root):
    # Project_Build.py only offers the chooser once the project's
    # multiple-application flag is set, and it refreshes that flag afterwards,
    # so the first build after a second application appears ignores --app.
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    watch.handlers["build"] = _fake_build("Application")
    result = run(watch, "build", {"app": "AppB"})
    assert result["ok"] is False and "AppB" in result["error"]


def test_build_is_happy_when_the_named_app_comes_back(root):
    watch = watcher.Watcher(make_globals(), root)
    watch.start()
    watch.handlers["build"] = _fake_build("AppB")
    assert run(watch, "build", {"app": "AppB"})["ok"] is True


def _fake_build(app_name):
    """Stand in for the real script: report which application it compiled."""
    from cds.ide import silent

    def handler(cmd, started):
        outcome = silent.Outcome(
            [{"level": "info", "text": "%s\nErrors: 0" % app_name}], "")
        error = outcome.error_text() or watcher._wrong_application(
            cmd, cmd.get("args") or {}, outcome)
        return commands.new_result(cmd, not error, started_at=started,
                                   error=error, messages=outcome.messages)
    return handler
