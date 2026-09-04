# -*- coding: utf-8 -*-
"""The drop box: the CLI leaves a command, the watcher leaves a result.

A command file name is "<13-digit millisecond stamp>-<6 hex>.json", so plain
alphabetical order is oldest-first and two commands issued in the same
millisecond still get separate files. The watcher takes one at a time, writes
the result under the same id, then deletes the command.

The CLI deletes each result once it has read it. Results nobody came back for
(the CLI was killed, say) are swept by the watcher on its next start.

Pure Python (PRINCIPLES.md 4): no CODESYS imports.
"""
from __future__ import print_function

import os
import random

from cds.core import ipc

RESULT_TTL_S = 3600.0


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def new_id(now=None, suffix=None):
    """Make "<13-digit ms>-<6 hex>": sorts by age, unique within a millisecond."""
    if suffix is None:
        suffix = "%06x" % random.randint(0, 0xFFFFFF)
    return "%013d-%s" % (int(ipc.now(now) * 1000), suffix)


def write_command(root, instance_id, command, args=None, now=None, cmd_id=None):
    """Queue one command for an instance. Returns the record as written."""
    now = ipc.now(now)
    cmd = {
        "id": cmd_id or new_id(now),
        "command": command,
        "args": dict(args or {}),
        "created_at": ipc.iso(now),
    }
    ipc.write_json(_command_path(root, instance_id, cmd["id"]), cmd)
    return cmd


def list_command_ids(root, instance_id):
    """Queued command ids, oldest first (the file name sorts that way)."""
    names = ipc.json_names(ipc.command_dir(root, instance_id))
    return [n[:-len(".json")] for n in names]


def next_command(root, instance_id):
    """The oldest queued command, or None if the queue is empty."""
    for cmd_id in list_command_ids(root, instance_id):
        cmd = ipc.read_json(_command_path(root, instance_id, cmd_id))
        if cmd is not None:
            return cmd
    return None


def delete_command(root, instance_id, cmd_id):
    ipc.remove_file(_command_path(root, instance_id, cmd_id))


def _command_path(root, instance_id, cmd_id):
    return os.path.join(ipc.command_dir(root, instance_id), cmd_id + ".json")


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

def new_result(cmd, ok, error=None, messages=None, needs_input=None,
               stdout_tail=None, started_at=None, finished_at=None, data=None):
    """Build the result record for a finished command.

    started_at and finished_at are epoch seconds. A failed result must carry
    an error text, so "it failed and I don't know why" cannot be written
    (PRINCIPLES.md 6). needs_input names the argument that would have answered
    a dialog the script tried to pop. data is whatever this particular command
    has to hand back — status returns the live instance record there.
    """
    if not ok and not error:
        raise ValueError("a failed result must carry an error message")
    started = ipc.now(started_at)
    finished = ipc.now(finished_at)
    return {
        "id": cmd["id"],
        "ok": bool(ok),
        "command": cmd.get("command"),
        "started_at": ipc.iso(started),
        "finished_at": ipc.iso(finished),
        "elapsed_s": round(finished - started, 3),
        "messages": list(messages or []),
        "stdout_tail": stdout_tail or "",
        "error": error,
        "needs_input": needs_input,
        "data": data,
    }


def write_result(root, instance_id, result):
    ipc.write_json(_result_path(root, instance_id, result["id"]), result)


def read_result(root, instance_id, cmd_id):
    return ipc.read_json(_result_path(root, instance_id, cmd_id))


def take_result(root, instance_id, cmd_id):
    """Read a result and delete it. None if it is not there yet."""
    result = read_result(root, instance_id, cmd_id)
    if result is not None:
        ipc.remove_file(_result_path(root, instance_id, cmd_id))
    return result


def prune_results(root, instance_id, now=None, max_age=RESULT_TTL_S):
    """Delete results nobody came back for. Returns the ids removed."""
    now = ipc.now(now)
    directory = ipc.result_dir(root, instance_id)
    removed = []
    for name in ipc.json_names(directory):
        path = os.path.join(directory, name)
        if now - os.path.getmtime(path) <= max_age:
            continue
        ipc.remove_file(path)
        removed.append(name[:-len(".json")])
    return removed


def _result_path(root, instance_id, cmd_id):
    return os.path.join(ipc.result_dir(root, instance_id), cmd_id + ".json")
