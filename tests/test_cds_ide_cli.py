# -*- coding: utf-8 -*-
"""Tests for cli/cds_ide.py.

The CLI and the watcher are driven against each other in one process: the
CLI's wait is made to answer itself by running the real watcher's run_one, so
these cover the whole round trip minus the IDE.
"""
import json
import time

import pytest

from cds.core import commands, instances, ipc
from cds.ide import watcher
from cli import cds_ide
from tests.test_watcher import make_globals


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv(ipc.ROOT_ENV, str(tmp_path))
    return str(tmp_path)


@pytest.fixture
def watch(root):
    started = watcher.Watcher(make_globals(), root)
    started.start()
    return started


def answering(watch, monkeypatch):
    """Make the CLI's wait tick the watcher instead of sleeping."""
    def tick(_seconds):
        cmd = commands.next_command(watch.root, watch.instance_id)
        if cmd is not None:
            watch.run_one(cmd)
    monkeypatch.setattr(time, "sleep", tick)


# --- list ------------------------------------------------------------------

def test_list_says_so_when_nothing_is_listening(root, capsys):
    assert cds_ide.main(["list"]) == cds_ide.EXIT_OK
    assert "no IDE is listening" in capsys.readouterr().out


def test_list_shows_a_live_watcher(watch, capsys):
    assert cds_ide.main(["list"]) == cds_ide.EXIT_OK
    out = capsys.readouterr().out
    assert watch.instance_id in out and "softplc.project" in out


def test_list_hides_a_watcher_that_stopped_beating(root, capsys):
    instances.write(root, instances.new_registration(
        "ghost-1", 9, "old", "C:\\p\\ghost.project", now=ipc.now() - 600.0))
    cds_ide.main(["list"])
    assert "ghost-1" not in capsys.readouterr().out


def test_list_json_is_machine_readable(watch, capsys):
    cds_ide.main(["list", "--json"])
    regs = json.loads(capsys.readouterr().out)
    assert regs[0]["instance_id"] == watch.instance_id


# --- picking a target ------------------------------------------------------

def test_a_command_with_no_live_ide_exits_two(root, capsys):
    assert cds_ide.main(["ping"]) == cds_ide.EXIT_TARGET
    assert "no live IDE" in capsys.readouterr().err


def test_an_ambiguous_target_exits_two_and_lists_the_candidates(root, capsys):
    for pid in (11, 22):
        instances.write(root, instances.new_registration(
            "softplc-%d" % pid, pid, "ide", "C:\\p\\softplc.project"))
    assert cds_ide.main(["ping", "--target", "softplc"]) == cds_ide.EXIT_TARGET
    err = capsys.readouterr().err
    assert "softplc-11" in err and "softplc-22" in err


def test_a_project_name_finds_the_watcher(watch, monkeypatch):
    answering(watch, monkeypatch)
    assert cds_ide.main(["ping", "--target", "softplc"]) == cds_ide.EXIT_OK


# --- the round trip --------------------------------------------------------

def test_ping_comes_back(watch, monkeypatch, capsys):
    answering(watch, monkeypatch)
    assert cds_ide.main(["ping"]) == cds_ide.EXIT_OK
    assert "pong" in capsys.readouterr().out


def test_status_prints_what_the_ide_has_open(watch, monkeypatch, capsys):
    answering(watch, monkeypatch)
    assert cds_ide.main(["status"]) == cds_ide.EXIT_OK
    assert "softplc" in capsys.readouterr().out


def test_stop_ends_the_watcher(watch, monkeypatch):
    answering(watch, monkeypatch)
    assert cds_ide.main(["stop"]) == cds_ide.EXIT_OK
    assert watch.running is False


def test_json_prints_the_whole_result(watch, monkeypatch, capsys):
    answering(watch, monkeypatch)
    cds_ide.main(["status", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert result["command"] == "status" and result["ok"] is True


def test_a_failed_command_exits_one(watch, monkeypatch, capsys):
    watch.handlers["ping"] = lambda cmd, started: commands.new_result(
        cmd, False, error="the IDE said no", started_at=started)
    answering(watch, monkeypatch)
    assert cds_ide.main(["ping"]) == cds_ide.EXIT_FAILED
    assert "the IDE said no" in capsys.readouterr().err


def test_the_reason_is_not_printed_twice(watch, monkeypatch, capsys):
    # error is usually just the first bad message wearing another hat.
    watch.handlers["ping"] = lambda cmd, started: commands.new_result(
        cmd, False, error="no project open", started_at=started,
        messages=[{"level": "error", "text": "no project open"}])
    answering(watch, monkeypatch)
    cds_ide.main(["ping"])
    printed = capsys.readouterr()
    assert (printed.out + printed.err).count("no project open") == 1


def test_a_failure_shows_what_the_script_printed(watch, monkeypatch, capsys):
    watch.handlers["ping"] = lambda cmd, started: commands.new_result(
        cmd, False, error="it broke", started_at=started,
        stdout_tail="the last thing the IDE said")
    answering(watch, monkeypatch)
    cds_ide.main(["ping"])
    assert "the last thing the IDE said" in capsys.readouterr().err


def test_a_command_that_needs_an_answer_exits_one(watch, monkeypatch, capsys):
    # The watcher sets error to the question itself (silent.Outcome), so the
    # CLI must not print that long text twice.
    watch.handlers["ping"] = lambda cmd, started: commands.new_result(
        cmd, False, error="Confirm Import?", started_at=started,
        needs_input={"question": "Confirm Import?", "arg": "yes"})
    answering(watch, monkeypatch)
    assert cds_ide.main(["ping"]) == cds_ide.EXIT_FAILED
    printed = capsys.readouterr()
    assert "--yes" in printed.err
    assert (printed.out + printed.err).count("Confirm Import?") == 1


# --- the flags the four real commands take ---------------------------------

def parse(argv):
    return cds_ide.command_args(cds_ide.build_parser().parse_args(argv))


def test_export_passes_the_orphan_choice():
    assert parse(["export", "--delete-orphans"]) == {"delete_orphans": True}


def test_a_flag_left_out_arrives_as_not_said():
    # None, not False: the watcher has to tell "leave them" from "did not say".
    assert parse(["export"]) == {"delete_orphans": None}


def test_import_carries_yes_and_force():
    assert parse(["import", "--yes"]) == {"yes": True, "force": None}
    assert parse(["import", "--yes", "--force"]) == {"yes": True, "force": True}


def test_import_without_yes_leaves_the_watcher_to_ask():
    assert parse(["import"]) == {"yes": None, "force": None}


def test_build_carries_the_application_name():
    assert parse(["build", "--app", "App_2"]) == {"app": "App_2"}


def test_compare_takes_no_arguments_of_its_own():
    assert parse(["compare"]) == {}


def test_the_arguments_reach_the_watcher(watch, monkeypatch):
    seen = {}

    def record(cmd, started):
        seen.update(cmd["args"])
        return commands.new_result(cmd, True, started_at=started)

    watch.handlers["export"] = record
    answering(watch, monkeypatch)
    cds_ide.main(["export", "--delete-orphans"])
    assert seen == {"delete_orphans": True}


# --- giving up -------------------------------------------------------------

def test_a_silent_watcher_times_out_with_exit_three(watch, capsys):
    assert cds_ide.main(["ping", "--timeout", "0"]) == cds_ide.EXIT_TIMEOUT
    assert "timed out" in capsys.readouterr().err


def test_a_timed_out_command_is_taken_off_the_queue(watch):
    # Otherwise it fires later, at an IDE whose owner has walked away.
    cds_ide.main(["ping", "--timeout", "0"])
    assert commands.list_command_ids(watch.root, watch.instance_id) == []


def test_ctrl_c_while_waiting_leaves_no_command_behind(watch, monkeypatch):
    def interrupt(_seconds):
        raise KeyboardInterrupt()
    monkeypatch.setattr(time, "sleep", interrupt)
    with pytest.raises(KeyboardInterrupt):
        cds_ide.main(["ping"])
    assert commands.list_command_ids(watch.root, watch.instance_id) == []


# --- --timeout means one thing -------------------------------------------

def busy_since(root, seconds_ago):
    reg = instances.new_registration("softplc-9", 9, "ide",
                                     r"C:\p\softplc.project")
    instances.set_state(reg, instances.STATE_BUSY, ipc.now() - seconds_ago)
    instances.write(root, reg)
    return reg


def test_timeout_stretches_how_long_a_busy_ide_counts_as_alive(root, capsys,
                                                               monkeypatch):
    # Raising --timeout is exactly how a caller says "I will wait for this
    # long import". list honoured that; the target lookup ignored it and
    # pre-filtered on the hardcoded 120 seconds instead.
    busy_since(root, 200.0)
    cds_ide.main(["list", "--timeout", "600"])
    assert "softplc-9" in capsys.readouterr().out

    reached = []

    def fake_send(root, instance_id, *args, **kwargs):
        reached.append(instance_id)
        return {"ok": True, "command": "ping", "messages": []}

    monkeypatch.setattr(cds_ide, "send", fake_send)
    assert cds_ide.main(["ping", "--timeout", "600"]) == cds_ide.EXIT_OK
    assert reached == ["softplc-9"]


def test_the_default_timeout_still_writes_off_a_long_gone_command(root, capsys):
    busy_since(root, 200.0)
    assert cds_ide.main(["ping"]) == cds_ide.EXIT_TARGET
    assert "no live IDE" in capsys.readouterr().err


# --- the watcher went away while we waited --------------------------------

def gone_after_first_wait(watch, monkeypatch):
    """Make the watcher vanish the moment the CLI settles in to wait."""
    def vanish(_seconds):
        instances.delete(watch.root, watch.instance_id)
    monkeypatch.setattr(time, "sleep", vanish)
    monkeypatch.setattr(cds_ide, "GONE_AFTER_S", 0.0)


def test_a_registration_blinking_out_mid_rewrite_is_not_death(watch,
                                                              monkeypatch):
    # IronPython has no os.replace, so the watcher's rewrite deletes the file
    # and renames the new one in. Calling a healthy IDE dead on one missed
    # read made every other status come back "stopped before answering".
    path = ipc.registration_path(watch.root, watch.instance_id)
    saved = ipc.read_json(path)
    turns = []

    def blink(_seconds):
        turns.append(len(turns))
        if len(turns) == 1:
            ipc.remove_file(path)          # mid-rewrite: no file right now
            return
        ipc.write_json(path, saved)        # ...and it is back
        cmd = commands.next_command(watch.root, watch.instance_id)
        if cmd is not None:
            watch.run_one(cmd)

    monkeypatch.setattr(time, "sleep", blink)
    assert cds_ide.main(["ping"]) == cds_ide.EXIT_OK


def test_stop_counts_a_vanished_watcher_as_success(watch, monkeypatch, capsys):
    # stop tears down one tick after answering, so the answer can be gone by
    # the time the CLI looks. The instance being gone IS the confirmation.
    gone_after_first_wait(watch, monkeypatch)
    assert cds_ide.main(["stop"]) == cds_ide.EXIT_OK
    assert "gone" in capsys.readouterr().out


def test_any_other_command_says_the_watcher_died(watch, monkeypatch, capsys):
    gone_after_first_wait(watch, monkeypatch)
    assert cds_ide.main(["export"]) == cds_ide.EXIT_FAILED
    assert "stopped before answering export" in capsys.readouterr().err


# --- compare's real answer is what it printed -----------------------------

def test_compare_shows_the_per_object_differences(watch, monkeypatch, capsys):
    watch.handlers["compare"] = lambda cmd, started: commands.new_result(
        cmd, True, started_at=started,
        messages=[{"level": "info", "text": "modified 1, only on disk 0"}],
        stdout_tail="M  Newcomer.st  (pou)")
    answering(watch, monkeypatch)
    assert cds_ide.main(["compare"]) == cds_ide.EXIT_OK
    printed = capsys.readouterr()
    assert "M  Newcomer.st" in printed.err


def test_a_successful_export_stays_quiet(watch, monkeypatch, capsys):
    watch.handlers["export"] = lambda cmd, started: commands.new_result(
        cmd, True, started_at=started,
        messages=[{"level": "info", "text": "Export complete!"}],
        stdout_tail="200 lines nobody asked for")
    answering(watch, monkeypatch)
    cds_ide.main(["export"])
    assert "nobody asked for" not in capsys.readouterr().err
