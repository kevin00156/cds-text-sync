# -*- coding: utf-8 -*-
"""Tests for cds.ide.display — what the status window is told to show.

The window itself is WinForms and needs an IDE; every decision it paints is
made here, which is the point of the split.
"""
from cds.core import ipc
from cds.ide import display, watcher

from tests.test_watcher import make_globals

T0 = 1725453665.0


def a_watcher(root, **state):
    watch = watcher.Watcher(make_globals(), root)
    watch.started_epoch = T0
    watch.__dict__.update(state)
    return watch


def test_an_idle_watcher_says_it_is_listening(tmp_path):
    picture = display.describe(a_watcher(str(tmp_path)), now=T0)
    assert picture["headline"] == "LISTENING"
    assert picture["level"] == display.IDLE


def test_a_running_command_names_itself(tmp_path):
    watch = a_watcher(str(tmp_path), doing="export")
    picture = display.describe(watch, now=T0)
    assert picture["headline"] == "BUSY: export"
    assert picture["level"] == display.BUSY


def test_a_failure_stays_red_until_something_succeeds(tmp_path):
    # A red bar the user did not see happen is the whole point of it.
    watch = a_watcher(str(tmp_path),
                      last={"command": "import", "ok": False, "elapsed": 2.0})
    assert display.describe(watch, now=T0)["level"] == display.FAILED

    watch.last = {"command": "build", "ok": True, "elapsed": 1.0}
    assert display.describe(watch, now=T0)["level"] == display.IDLE


def test_busy_wins_over_a_previous_failure(tmp_path):
    watch = a_watcher(str(tmp_path), doing="build",
                      last={"command": "import", "ok": False, "elapsed": 2.0})
    assert display.describe(watch, now=T0)["level"] == display.BUSY


def test_the_second_line_names_the_project_and_the_instance(tmp_path):
    watch = a_watcher(str(tmp_path))
    picture = display.describe(watch, now=T0)
    assert picture["project"] == "softplc"
    assert picture["instance_id"] == watch.instance_id


def test_a_watcher_with_no_project_open_still_has_a_second_line(tmp_path):
    watch = watcher.Watcher(make_globals(None), str(tmp_path))
    assert display.describe(watch)["project"] == "no project"


def test_the_third_line_counts_what_has_happened(tmp_path):
    watch = a_watcher(str(tmp_path), done=12,
                      last={"command": "export", "ok": True, "elapsed": 7.53})
    detail = display.describe(watch, now=T0 + 2472.0)["detail"]
    assert "done 12" in detail
    assert "last export ok 7.5s" in detail
    assert "up 00:41:12" in detail


def test_a_failed_last_command_says_so_in_the_third_line(tmp_path):
    watch = a_watcher(str(tmp_path), done=1,
                      last={"command": "import", "ok": False, "elapsed": 3.0})
    assert "last import FAILED" in display.describe(watch, now=T0)["detail"]


def test_the_third_line_ends_with_the_heartbeat(tmp_path):
    # Proof of life: a clock that stops moving means the watcher stopped.
    watch = a_watcher(str(tmp_path))
    watch.reg["heartbeat_epoch"] = T0
    detail = display.describe(watch, now=T0)["detail"]
    assert detail.endswith("beat " + ipc.iso(T0).split("T")[-1])


def test_the_clock_is_hours_minutes_seconds():
    assert display.elapsed_clock(0) == "00:00:00"
    assert display.elapsed_clock(59) == "00:00:59"
    assert display.elapsed_clock(3661) == "01:01:01"
    assert display.elapsed_clock(-5) == "00:00:00"  # a clock change, not a fact
