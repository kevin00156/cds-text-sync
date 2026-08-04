# -*- coding: utf-8 -*-
"""
codesys_online.py - Report which applications are currently logged into a PLC.

Import writes to the IDE object tree, and CODESYS refuses to create, move or
delete any object belonging to an application you are logged into ("Cannot add
an object because it affects a device you are currently logged into"). Without
this pre-flight that refusal arrives once per object, halfway through an
import, as a wall of SystemError tracebacks that says nothing about the one
thing the user has to do: log out.

Reads the CODESYS 'online' scripting global, so it can only answer inside the
IDE. Outside it - or when the online API declines to answer - it reports
nothing logged in: a pre-flight that cannot see must not block work it has no
evidence against.
"""
from __future__ import print_function

import sys

from codesys_constants import kind_of
from codesys_utils import safe_str, log_warning
from codesys_managers import get_container_prefix

# Applications sit at Device / [PLC Logic] / Application. Same depth guard as
# find_application_recursive, with slack for folders above the device.
MAX_DEPTH = 5

# The only kinds worth walking into, so the scan never sweeps a POU pool.
CONTAINER_KINDS = ("device", "plc_logic", "folder")


def find_logged_in_applications(project, caller_globals=None):
    """The 'Device/Application' labels of every application with a live login.

    Empty when nothing is logged in, and equally when the online API is absent
    or unable to answer (no gateway, script run outside the IDE, ...).
    """
    online_api = _resolve_online(caller_globals)
    if online_api is None:
        log_warning("Login pre-flight skipped: the CODESYS 'online' API is not "
                    "reachable from this script run")
        return []
    return [_app_label(app) for app in _find_applications(project)
            if _is_logged_in(online_api, app)]


def logged_in_block_message(app_labels):
    """The user-facing reason an import cannot run while a login is active."""
    return (
        "Import blocked: this project is logged into a PLC.\n\n"
        "Online application(s):\n  " + "\n  ".join(app_labels) + "\n\n"
        "CODESYS does not allow objects to be created, moved or deleted while "
        "an application is online, so the import would fail object by object.\n\n"
        "Log out (Online > Logout, Ctrl+F8) and run the import again."
    )


# --- Internals ---

def _resolve_online(caller_globals=None):
    """The CODESYS 'online' scripting global, or None outside the IDE.

    Mirrors resolve_system in codesys_utils: the global is injected into the
    running script's namespace, so the caller's globals() is the reliable
    source; __main__ and sys.modules cover scripts invoked another way.
    """
    if caller_globals and caller_globals.get("online") is not None:
        return caller_globals["online"]
    try:
        import __main__
        found = getattr(__main__, "online", None)
        if found is not None:
            return found
    except ImportError:
        pass
    return sys.modules.get("online")


def _find_applications(project):
    """Every application object in the project (bounded, pruned walk).

    Breadth-first through containers only: a project with thousands of POUs
    costs a handful of API calls, and nothing below an application is visited.
    """
    found = []
    level = [project]
    for _ in range(MAX_DEPTH):
        next_level = []
        for node in level:
            for child in _children(node):
                kind = _kind(child)
                if kind == "application":
                    found.append(child)
                elif kind in CONTAINER_KINDS:
                    next_level.append(child)
        if not next_level:
            break
        level = next_level
    return found


def _is_logged_in(online_api, app):
    """True when `app` holds a live PLC login. Unanswerable counts as False."""
    session = None
    try:
        session = online_api.create_online_application(app)
        return bool(session.is_logged_in)
    except Exception as e:
        log_warning("Login pre-flight: cannot read the login state of "
                    + _name(app) + ": " + safe_str(e))
        return False
    finally:
        _release(session)


def _release(session):
    """Drop an online session's connection to the device.

    ScriptOnline hands out a live connection; undisposed it stays open for the
    rest of the script run.
    """
    dispose = getattr(session, "Dispose", None)
    if dispose is None:
        return
    try:
        dispose()
    except Exception as e:
        log_warning("Login pre-flight: could not dispose an online session: "
                    + safe_str(e))


def _children(node):
    """Direct children of a tree node, empty when the IDE refuses to list them."""
    try:
        return node.get_children()
    except Exception as e:
        log_warning("Login pre-flight: cannot list the children of "
                    + _name(node) + ": " + safe_str(e))
        return []


def _kind(obj):
    """Profile kind name of an object, None when it has no readable type."""
    try:
        return kind_of(safe_str(obj.type))
    except Exception as e:
        log_warning("Login pre-flight: cannot read the type of "
                    + _name(obj) + ": " + safe_str(e))
        return None


def _app_label(app):
    """'Device/Application', the way the IDE's device tree shows it."""
    name = _name(app)
    parts = [part for part in get_container_prefix(app) if part]
    if name not in parts:
        parts.append(name)
    return "/".join(parts)


def _name(obj):
    """Display name of an object. Never raises - it feeds the error messages."""
    try:
        return safe_str(obj.get_name())
    except Exception:
        return "<unnamed object>"
