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
