# -*- coding: utf-8 -*-
"""Tests for cds.ide.watcher.

The watcher takes the CODESYS globals as an argument instead of reaching for
them, so a fake `system` and a fake `projects` are enough to drive the whole
loop under CPython. What this cannot show is whether the real IDE stays usable
while system.delay() runs — that is the hand test in WATCHER_CLI_PLAN.md 9.
"""
import os

import pytest

from cds.core import commands, instances, ipc
from cds.ide import watcher


class FakeSystem(object):
    """Counts delays and stops the loop, standing in for CODESYS's `system`."""

    def __init__(self, stop_after=None):
        self.abortable = False
        self.delays = 0
        self.stop_after = stop_after
        self.on_delay = None

    def delay(self, milliseconds):
        self.delays += 1
        if self.on_delay is not None:
            self.on_delay(self.delays)
        if self.stop_after is not None and self.delays >= self.stop_after:
            raise KeyboardInterrupt()


class FakeProject(object):
    def __init__(self, path):
        self.path = path


class FakeProjects(object):
    def __init__(self, path):
        self.primary = FakeProject(path) if path else None


def make_globals(path="C:\\p\\softplc.project", stop_after=None):
    return {"system": FakeSystem(stop_after), "projects": FakeProjects(path)}


@pytest.fixture
def root(tmp_path):
    return str(tmp_path)


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


def test_start_turns_on_cancelling(root):
    # Without this, Cancel on the progress display cannot stop the loop.
    ide = make_globals()
    watcher.Watcher(ide, root).start()
    assert ide["system"].abortable is True


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


def test_stop_ends_the_loop(root):
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


# --- the loop --------------------------------------------------------------

def test_the_loop_runs_a_queued_command_and_stops_on_stop(root):
    ide = make_globals(stop_after=200)
    watch = watcher.Watcher(ide, root)
    watch.start()
    commands.write_command(root, watch.instance_id, "ping",
                           cmd_id="1725453665000-aaaaaa")
    commands.write_command(root, watch.instance_id, "stop",
                           cmd_id="1725453665001-bbbbbb")
    watch.run()
    assert commands.read_result(root, watch.instance_id,
                                "1725453665000-aaaaaa")["ok"] is True
    assert ide["system"].delays == 2  # one per loop turn, not one per poll


def test_cancelling_the_script_shuts_the_watcher_down(root):
    ide = make_globals(stop_after=3)
    watch = watcher.main(ide, root)
    assert instances.read(root, watch.instance_id) is None
