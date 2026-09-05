# -*- coding: utf-8 -*-
"""Drive a running CODESYS IDE from the command line.

Talks to the watcher started by Project_watch.py inside the IDE. Nothing here
touches CODESYS: it writes a command file, waits for the result file, prints
it. CPython 3, standard library only.

    python cli/cds_ide.py list
    python cli/cds_ide.py ping [--target softplc]
    python cli/cds_ide.py status
    python cli/cds_ide.py export [--delete-orphans]
    python cli/cds_ide.py import --yes [--force]
    python cli/cds_ide.py compare
    python cli/cds_ide.py build [--app NAME]
    python cli/cds_ide.py stop

Exit codes: 0 fine, 1 the command failed (needs_input counts), 2 no single
live IDE matched, 3 timed out waiting for the answer.
"""
from __future__ import print_function

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cds.core import commands, instances, ipc  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TARGET = 2
EXIT_TIMEOUT = 3

DEFAULT_TIMEOUT_S = 120.0
POLL_S = 0.05

_HELP = {
    "ping": "check that an IDE is answering",
    "status": "show what an IDE has open right now",
    "export": "write the project out to the sync folder",
    "import": "read the sync folder back into the project",
    "compare": "report how the project and the sync folder differ",
    "build": "build the application and report the error count",
    "stop": "tell a watcher to shut down",
}

# Extra flags per command, and how they become the command's args. A flag left
# out arrives as None so the watcher can tell "not said" from "said no".
FLAGS = {
    "export": [("--delete-orphans", "delete the sync files with no object behind them")],
    "import": [("--yes", "confirm the import; without it the watcher asks"),
               ("--force", "go ahead despite a version or computer mismatch")],
    "build": [("--app", "which application to build, when there are several")],
}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cds_ide", description="Drive a running CODESYS IDE.")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_shared(sub.add_parser("list", help="show the IDEs that are listening"))
    for name in ("ping", "status", "export", "import", "compare", "build", "stop"):
        command = _add_target(sub.add_parser(name, help=_HELP[name]))
        for flag, help_text in FLAGS.get(name, []):
            if flag == "--app":
                command.add_argument(flag, default=None, help=help_text)
            else:
                command.add_argument(flag, action="store_true", default=None,
                                     help=help_text)
    return parser


def command_args(ns):
    """Turn the parsed flags back into the args the watcher reads."""
    return dict((flag.lstrip("-").replace("-", "_"),
                 getattr(ns, flag.lstrip("-").replace("-", "_")))
                for flag, _ in FLAGS.get(ns.command, []))


def _add_shared(parser):
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                        help="seconds to wait for the answer (default 120); "
                             "also how long a busy IDE counts as alive")
    parser.add_argument("--json", action="store_true",
                        help="print the raw record instead of a summary")
    return parser


def _add_target(parser):
    parser.add_argument("--target", help="instance id, or a project name")
    return _add_shared(parser)


# --------------------------------------------------------------------------
# Talking to a watcher
# --------------------------------------------------------------------------

GONE = "gone"  # the watcher shut down while we were waiting


def send(root, instance_id, name, args, timeout, poll=POLL_S):
    """Queue a command and wait for its result.

    None means it timed out; GONE means the watcher went away. A command that
    times out is un-queued, so it cannot fire later against an IDE whose owner
    has walked away. If the watcher already claimed it, the result it writes
    is swept by that watcher's next start instead.
    """
    cmd = commands.write_command(root, instance_id, name, args)
    deadline = time.time() + timeout
    try:
        while True:
            result = commands.take_result(root, instance_id, cmd["id"])
            if result is not None:
                return result
            if instances.read(root, instance_id) is None:
                # The instance directory goes with the registration, so the
                # answer is not coming. For `stop` that IS the answer; for
                # anything else, better to say so than to wait out the clock.
                return GONE
            if time.time() >= deadline:
                commands.delete_command(root, instance_id, cmd["id"])
                return None
            time.sleep(poll)
    except KeyboardInterrupt:
        commands.delete_command(root, instance_id, cmd["id"])
        raise


def live_instances(root, busy_timeout=DEFAULT_TIMEOUT_S):
    return [r for r in instances.read_all(root)
            if instances.is_alive(r, busy_timeout=busy_timeout)]


# --------------------------------------------------------------------------
# The subcommands
# --------------------------------------------------------------------------

def run_list(root, ns):
    regs = live_instances(root, ns.timeout)
    if ns.json:
        print(json.dumps(regs, indent=2, sort_keys=True))
        return EXIT_OK
    if not regs:
        print("no IDE is listening; start Project_watch.py in one")
        return EXIT_OK
    for reg in regs:
        print("%-28s %-6s %s" % (reg["instance_id"], reg.get("state", "?"),
                                 reg.get("project_path") or "(no project)"))
    return EXIT_OK


def run_on_target(root, ns):
    try:
        # --timeout is how long the caller will wait, so it is also how long a
        # busy instance still counts as alive. Both places, one meaning.
        reg = instances.resolve_target(live_instances(root, ns.timeout),
                                       ns.target, busy_timeout=ns.timeout)
    except instances.TargetError as exc:
        return _report_target_error(exc)
    result = send(root, reg["instance_id"], ns.command, command_args(ns),
                  ns.timeout)
    if result is GONE:
        return _report_gone(ns.command, reg["instance_id"])
    if result is None:
        print("timed out after %gs waiting for %s"
              % (ns.timeout, reg["instance_id"]), file=sys.stderr)
        return EXIT_TIMEOUT
    return _report(result, ns.json)


def _report_gone(command, instance_id):
    """The watcher vanished mid-wait: what that means depends on the ask."""
    if command == "stop":
        print("info: %s is gone" % instance_id)
        return EXIT_OK
    print("%s stopped before answering %s" % (instance_id, command),
          file=sys.stderr)
    return EXIT_FAILED


def _report_target_error(exc):
    print(str(exc), file=sys.stderr)
    for reg in exc.matches:
        print("  %-28s %s" % (reg["instance_id"],
                              reg.get("project_path") or "(no project)"),
              file=sys.stderr)
    return EXIT_TARGET


def _report(result, as_json):
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return EXIT_OK if result.get("ok") else EXIT_FAILED
    said = []
    for message in result.get("messages") or []:
        said.append(message.get("text", ""))
        print("%s: %s" % (message.get("level", "info"), said[-1]))
    for key, value in sorted((result.get("data") or {}).items()):
        print("  %-16s %s" % (key, value))
    needs = result.get("needs_input")
    if needs:
        said.append(needs.get("question"))
        print("needs input: %s (answer with --%s)"
              % (said[-1], needs.get("arg")), file=sys.stderr)
    # The error repeats the first bad message, or the question. Say it once.
    if result.get("error") and result["error"] not in said:
        print("error: " + result["error"], file=sys.stderr)
    if _wants_tail(result) and result.get("stdout_tail"):
        print("--- output from the IDE ---", file=sys.stderr)
        print(result["stdout_tail"], file=sys.stderr)
    return EXIT_OK if result.get("ok") else EXIT_FAILED


def _wants_tail(result):
    """When the summary is not the whole answer, show what the script printed.

    A failure always earns the room. So does compare, whose useful output is
    the per-object list it prints — the messages only carry the counts.
    """
    return not result.get("ok") or result.get("command") == "compare"


def main(argv=None):
    ns = build_parser().parse_args(argv)
    root = ipc.default_root()
    if ns.command == "list":
        return run_list(root, ns)
    return run_on_target(root, ns)


if __name__ == "__main__":
    sys.exit(main())
