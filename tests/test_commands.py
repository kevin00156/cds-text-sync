# -*- coding: utf-8 -*-
"""Tests for cds.core.commands — the command/result drop box."""
import io
import os
import re

import pytest

from cds.core import commands, ipc

T0 = 1725453665.0  # a fixed "now" so nothing here depends on the clock


# --- commands --------------------------------------------------------------

def test_command_id_is_13_digits_and_6_hex():
    assert re.match(r"^\d{13}-[0-9a-f]{6}$", commands.new_id(now=T0))


def test_command_ids_from_the_same_millisecond_differ():
    ids = set(commands.new_id(now=T0) for _ in range(50))
    assert len(ids) > 1


def test_commands_come_back_oldest_first(tmp_path):
    root = str(tmp_path)
    for cmd_id in ("1725453665999-ffffff", "1725453665123-a3f9c1"):
        commands.write_command(root, "p-1", "ping", cmd_id=cmd_id)
    assert commands.list_command_ids(root, "p-1") == [
        "1725453665123-a3f9c1", "1725453665999-ffffff",
    ]
    assert commands.next_command(root, "p-1")["id"] == "1725453665123-a3f9c1"


def test_deleting_a_command_uncovers_the_next_one(tmp_path):
    root = str(tmp_path)
    first = commands.write_command(root, "p-1", "ping",
                                   cmd_id="1725453665123-a3f9c1")
    commands.write_command(root, "p-1", "status", cmd_id="1725453665999-ffffff")
    commands.delete_command(root, "p-1", first["id"])
    assert commands.next_command(root, "p-1")["command"] == "status"


def test_next_command_is_none_on_an_empty_queue(tmp_path):
    assert commands.next_command(str(tmp_path), "p-1") is None


def test_a_command_keeps_its_args(tmp_path):
    root = str(tmp_path)
    commands.write_command(root, "p-1", "import", {"yes": True, "force": False})
    assert commands.next_command(root, "p-1")["args"] == {
        "yes": True, "force": False,
    }


def test_the_command_queue_ignores_half_written_tmp_files(tmp_path):
    root = str(tmp_path)
    commands.write_command(root, "p-1", "ping", cmd_id="1725453665123-a3f9c1")
    tmp = os.path.join(ipc.command_dir(root, "p-1"), "0000000000001-aaaaaa.json.tmp")
    with io.open(tmp, "w", encoding="utf-8") as handle:
        handle.write(u"{half")
    assert commands.list_command_ids(root, "p-1") == ["1725453665123-a3f9c1"]


# --- results ---------------------------------------------------------------

def test_a_result_records_how_long_the_command_took():
    cmd = {"id": "1725453665123-a3f9c1", "command": "import"}
    result = commands.new_result(cmd, True, started_at=T0, finished_at=T0 + 4.2)
    assert result["elapsed_s"] == 4.2
    assert result["command"] == "import" and result["error"] is None


def test_a_failed_result_must_say_why():
    with pytest.raises(ValueError):
        commands.new_result({"id": "x", "command": "import"}, False)


def test_needs_input_rides_along_on_a_failed_result():
    result = commands.new_result({"id": "x", "command": "import"}, False,
                                 error="Confirm Import",
                                 needs_input={"question": "Confirm Import?",
                                              "arg": "yes"})
    assert result["ok"] is False
    assert result["needs_input"]["arg"] == "yes"


def test_take_result_reads_it_once(tmp_path):
    root = str(tmp_path)
    cmd = commands.write_command(root, "p-1", "ping",
                                 cmd_id="1725453665123-a3f9c1")
    commands.write_result(root, "p-1",
                          commands.new_result(cmd, True, started_at=T0,
                                              finished_at=T0 + 4.2))
    assert commands.take_result(root, "p-1", cmd["id"])["ok"] is True
    assert commands.take_result(root, "p-1", cmd["id"]) is None


def test_a_result_that_is_not_there_yet_reads_as_none(tmp_path):
    assert commands.read_result(str(tmp_path), "p-1", "nope") is None


def test_prune_results_drops_only_the_old_ones(tmp_path):
    root = str(tmp_path)
    ipc.ensure_dirs(root, "p-1")
    for cmd_id in ("1725453665123-a3f9c1", "1725453665999-ffffff"):
        commands.write_result(root, "p-1", {"id": cmd_id, "ok": True})
    old = os.path.join(ipc.result_dir(root, "p-1"), "1725453665123-a3f9c1.json")
    os.utime(old, (T0 - 7200.0, T0 - 7200.0))
    assert commands.prune_results(root, "p-1", now=T0) == ["1725453665123-a3f9c1"]
    assert commands.read_result(root, "p-1", "1725453665999-ffffff") is not None
