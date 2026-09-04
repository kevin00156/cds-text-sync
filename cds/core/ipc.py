# -*- coding: utf-8 -*-
"""The instance directory: where it lives, and how to write a file in it.

This is the ground floor of the protocol between the in-IDE watcher and the
external CLI. One directory per running IDE:

    <root>/
        <instance-id>.json      registration + heartbeat  (cds.core.instances)
        <instance-id>/
            cmd/<id>.json       written by the CLI        (cds.core.commands)
            result/<id>.json    written by the watcher    (cds.core.commands)

The other side of every file here is a different process that may read at any
moment, so every write goes to ``<path>.tmp`` first and is then renamed over
the real name. Readers only ever look at ``.json``.

Pure Python on purpose (PRINCIPLES.md 4): no CODESYS imports, so it runs in CI
under CPython 3 and inside the IDE under IronPython 2.7 from the same source.
"""
from __future__ import print_function

import errno
import io
import json
import os
import re
import time

ROOT_ENV = "CDS_INSTANCES_DIR"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

def default_root():
    """Where instance directories live, unless CDS_INSTANCES_DIR overrides it."""
    override = os.environ.get(ROOT_ENV)
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA")
    if not base:  # not Windows: only ever hit by CI and by tests
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "cds-text-sync", "instances")


def make_instance_id(project_path, pid):
    """Build "<project stem>-<pid>", the name that identifies one IDE."""
    stem = os.path.splitext(os.path.basename(project_path or "unsaved"))[0]
    return "%s-%s" % (_UNSAFE.sub("_", stem) or "unsaved", pid)


def registration_path(root, instance_id):
    return os.path.join(root, instance_id + ".json")


def instance_dir(root, instance_id):
    return os.path.join(root, instance_id)


def command_dir(root, instance_id):
    return os.path.join(root, instance_id, "cmd")


def result_dir(root, instance_id):
    return os.path.join(root, instance_id, "result")


def ensure_dirs(root, instance_id):
    """Create the cmd/ and result/ directories for an instance."""
    makedirs(command_dir(root, instance_id))
    makedirs(result_dir(root, instance_id))


# --------------------------------------------------------------------------
# Files a second process may be reading
# --------------------------------------------------------------------------

def write_json(path, data):
    """Write data to path atomically, via <path>.tmp plus a rename."""
    makedirs(os.path.dirname(path))
    text = json.dumps(data, indent=2, sort_keys=True)
    if not isinstance(text, type(u"")):  # IronPython 2.7 hands back bytes
        text = text.decode("utf-8")
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    _replace(tmp, path)


def read_json(path):
    """Parse path, or return None if it is gone.

    A missing file is normal here (the other side deletes as it goes); a
    malformed one is not, and raises (PRINCIPLES.md 6).
    """
    try:
        with io.open(path, encoding="utf-8") as handle:
            text = handle.read()
    except (IOError, OSError) as exc:
        if getattr(exc, "errno", None) == errno.ENOENT:
            return None
        raise
    return json.loads(text)


def json_names(directory):
    """Sorted .json file names in directory; .tmp and anything else skipped."""
    try:
        names = os.listdir(directory)
    except (IOError, OSError) as exc:
        if getattr(exc, "errno", None) == errno.ENOENT:
            return []
        raise
    return sorted(n for n in names if n.endswith(".json"))


def remove_file(path):
    """Delete path, saying nothing if it was already gone."""
    try:
        os.remove(path)
    except (IOError, OSError) as exc:
        if getattr(exc, "errno", None) != errno.ENOENT:
            raise


def makedirs(path):
    if path and not os.path.isdir(path):
        os.makedirs(path)


def _replace(src, dst):
    """Rename src over dst. os.rename cannot overwrite on Windows."""
    replace = getattr(os, "replace", None)  # CPython 3 only, atomic
    if replace is not None:
        replace(src, dst)
        return
    if os.path.exists(dst):
        os.remove(dst)
    os.rename(src, dst)


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

def now(value=None):
    """Epoch seconds: value when the caller pins one, the clock otherwise."""
    return time.time() if value is None else float(value)


def iso(epoch):
    """The human-readable stamp that sits beside every epoch field."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))
