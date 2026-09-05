# -*- coding: utf-8 -*-
"""What the IDE has to say about the last build.

Project_Build.py reports counts — "1 errors, 90 warnings" — and writes the
table of individual errors to a log file only when the project is in debug
mode. A caller that cannot see the IDE needs the errors themselves: which
object, which line, what is wrong. The IDE keeps them in its own message
store under the build category, so read them from there rather than changing
that script.

Everything is defensive on purpose. IScriptMessage's members vary between
ScriptEngine versions, and a build whose errors could not be formatted is
still a build worth reporting.
"""
from __future__ import print_function

# The category Project_Build.py builds under and clears before each run.
BUILD_CATEGORY = "97F48D64-A2A3-4856-B640-75C046E37EA9"

MAX_LINES = 200


def note(ide_globals, text, ok=True):
    """Leave a line in the IDE's Messages panel.

    The status window says what is happening now; this is what happened
    earlier, in a place the user can scroll back through. Never raises: a
    watcher that cannot write a log line still has commands to answer, and
    the fake `system` used by the tests has no write_message at all.
    """
    system = ide_globals.get("system")
    severity = ide_globals.get("Severity")
    if system is None or not hasattr(system, "write_message"):
        return False
    try:
        level = severity.Information if ok else severity.Error
        system.write_message(level, text)
        return True
    except Exception:
        return False


def build_report(ide_globals, limit=MAX_LINES):
    """The build's errors and warnings as text lines, errors first.

    Empty when the IDE has nothing to say or will not say it in a shape this
    understands — never an exception, because it is called after a build that
    already has a result to report.
    """
    try:
        found = _fetch(ide_globals)
    except Exception:
        return []
    lines = [_format(item) for item in found]
    lines = [line for line in lines if line]
    lines.sort(key=lambda line: 0 if line.startswith("error") else 1)
    return lines[:limit]


def _fetch(ide_globals):
    system = ide_globals["system"]
    severity = ide_globals.get("Severity")
    if severity is not None and hasattr(system, "get_message_objects"):
        wanted = severity.Error | severity.Warning | severity.FatalError
        return list(system.get_message_objects(BUILD_CATEGORY, wanted))
    return list(system.get_messages(BUILD_CATEGORY))  # older engines: plain text


def _format(item):
    """One message as `severity  text  (object, position)`."""
    if isinstance(item, type("")) or isinstance(item, type(u"")):
        return _text(item)
    text = _first(item, ("text", "message", "Message", "Text"))
    if text is None:
        return _text(item)
    where = _where(item)
    return "%-8s %s%s" % (_severity(item), _text(text), where)


def _severity(item):
    name = _first(item, ("severity", "Severity"))
    return "" if name is None else str(name).lower()


def _where(item):
    """The object and position, when the message carries them."""
    obj = _first(item, ("object", "Object", "obj"))
    position = _first(item, ("position", "Position"))
    parts = []
    if obj is not None:
        parts.append(_name_of(obj))
    if position is not None and str(position) not in ("", "-1", "0"):
        parts.append("at %s" % position)
    return "  (%s)" % ", ".join(parts) if parts else ""


def _name_of(obj):
    getter = getattr(obj, "get_name", None)
    try:
        return _text(getter() if getter else obj)
    except Exception:
        return "?"


def _first(item, names):
    for name in names:
        value = getattr(item, name, None)
        if value is not None:
            return value
    return None


def _text(value):
    if isinstance(value, type(u"")):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return type(u"")(value)
