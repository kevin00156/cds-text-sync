# -*- coding: utf-8 -*-
"""Run one of the Project_*.py scripts with nobody there to click the dialogs.

The scripts were written for a human: they ask "Confirm Import?" and wait. The
watcher answers those questions from the command's arguments instead, and
refuses — loudly — to guess when the caller did not say.

Three things have to be swapped for that to hold:

    the script's own `system`   its module namespace gets a stand-in
    `__main__.system`           the shared .pyw modules look there, not at
                                the caller's globals (codesys_utils 517)
    codesys_ui.ask_yes_no       WinForms message boxes that never touch
                                system.ui at all (codesys_ui 48-90)

Everything is put back afterwards, whether the script finished or blew up.
"""
from __future__ import print_function

import codecs
import collections
import sys

# Dialog title -> (the command argument that answers it, the default).
# A default of None means the caller has to say; this will not guess.
YES_NO = {
    "Delete Orphaned Files?": ("delete_orphans", False),
    "Version Mismatch Warning": ("force", False),
    "Confirm Import": ("yes", None),
}

# Answering "yes" here would open Project_directory's own dialogs, so carrying
# on means "no": keep the sync folder that is already configured.
YES_NO_CANCEL = {
    "Computer Mismatch Detected": "force",
}

STDOUT_TAIL_LINES = 200

# These levels mean the script gave up. It has no return value to check —
# reporting through system.ui is the only signal it gives (see the four main()
# functions, which return None whether they worked or not).
BAD_LEVELS = ("warning", "error")


class NeedsInput(BaseException):
    """A dialog wanted an answer that the command did not carry.

    Deliberately not an Exception. This codebase wraps IDE calls in broad
    `except Exception` blocks — Project_Build.py 73 is one — that would
    swallow it and let the script carry on as though someone had clicked.
    Same reasoning as KeyboardInterrupt.
    """

    def __init__(self, question, arg=None):
        BaseException.__init__(self, question)
        self.question = question
        self.arg = arg

    def as_record(self):
        return {"question": self.question, "arg": self.arg}


class Outcome(object):
    """What came back from a script run: what it said, printed, and needs."""

    def __init__(self, messages, stdout_tail, needs=None, error=None):
        self.messages = messages
        self.stdout_tail = stdout_tail
        self.needs = needs
        self.error = error

    def ok(self):
        return not self.error_text()

    def error_text(self):
        """The reason this run failed, or None. Never a silent failure."""
        if self.error:
            return self.error
        if self.needs is not None:
            return self.needs.question
        for message in self.messages:
            if message["level"] in BAD_LEVELS:
                return message["text"]
        if not self.messages:
            # Every one of the four scripts calls system.ui.info when it
            # finishes (Project_export 383, Project_import 143,
            # Project_compare 149, Project_Build 393), so silence means it
            # gave up on a path that only print()s — and a caller told "ok"
            # would go on to build code that was never imported.
            return ("the script returned without reporting anything; see "
                    "stdout_tail for what it printed")
        return None


class SilentUI(object):
    """Stands in for system.ui: records what would have been shown."""

    def __init__(self, args):
        self.args = args or {}
        self.messages = []

    def info(self, text, *rest):
        self._record("info", text)

    def warning(self, text, *rest):
        self._record("warning", text)

    def error(self, text, *rest):
        self._record("error", text)

    def choose(self, caption, options):
        """Pick the application named by --app. No name given, no guess."""
        labels = [_text(str(option)) for option in options]
        wanted = self.args.get("app")
        if wanted is None:
            raise NeedsInput("%s (%s)" % (caption, ", ".join(labels)), "app")
        if wanted not in labels:
            raise NeedsInput("%r is not one of: %s" % (wanted, ", ".join(labels)),
                             "app")
        return labels.index(wanted)

    def __getattr__(self, name):
        """Every other dialog needs a person. Say so instead of hanging."""
        def refuse(*args, **kwargs):
            raise NeedsInput("system.ui.%s() wanted an answer from a person"
                             % name)
        return refuse

    def _record(self, level, text):
        self.messages.append({"level": level, "text": _text(text)})


class SilentSystem(object):
    """The real `system` with its .ui replaced. Everything else passes through."""

    def __init__(self, real, ui):
        self._real = real
        self.ui = ui

    def __getattr__(self, name):
        return getattr(self._real, name)


def running():
    """Is this module driving a script right now?

    Two overlapping runs would fight over sys.modules["codesys_ui"],
    __main__.system and sys.stdout, and one command's arguments would end up
    answering the other's dialogs. The flag is module-level rather than per
    watcher so a second caller — a Watcher built elsewhere, the MCP wrapper —
    is caught too, not just a re-entrant tick.

    It does NOT see a script the user started from the Tools menu: that goes
    through the IDE's own executor and never reaches this module. There is no
    known way to detect one from here (WATCHER_CLI_PLAN.md 15).
    """
    return _RUNNING["depth"] > 0


_RUNNING = {"depth": 0}


def run(ide_globals, script_path, entry, args):
    """Exec script_path, call its entry function, hand back an Outcome.

    The script is exec'd under a name that is not "__main__" so its own
    `if __name__ == "__main__"` guard does not fire and run it twice.
    """
    ui = SilentUI(args)
    silent = SilentSystem(ide_globals["system"], ui)
    namespace = dict(ide_globals)
    namespace["__name__"] = "cds_watcher_script"
    namespace["__file__"] = script_path
    namespace["system"] = silent
    _RUNNING["depth"] += 1
    try:
        _exec_file(script_path, namespace)  # reloads the codesys_* modules
        return _call(namespace, entry, silent, ui, args)
    finally:
        _RUNNING["depth"] -= 1


def _call(namespace, entry, silent, ui, args):
    """Run the entry function with the stand-ins installed, then take them out."""
    tee = _Tee(sys.stdout)
    undo = _install(silent, ui, args)
    sys.stdout = tee
    try:
        namespace[entry]()
        return Outcome(ui.messages, tee.tail())
    except NeedsInput as need:
        return Outcome(ui.messages, tee.tail(), needs=need)
    except Exception:
        import traceback
        return Outcome(ui.messages, tee.tail(), error=traceback.format_exc())
    finally:
        sys.stdout = tee.stream
        undo()


def _install(silent, ui, args):
    """Swap in the stand-ins the .pyw modules will reach for. Returns the undo."""
    main = sys.modules["__main__"]
    had_system = hasattr(main, "system")
    old_system = getattr(main, "system", None)
    main.system = silent

    codesys_ui = sys.modules.get("codesys_ui")
    old_ui = {}
    if codesys_ui is not None:
        for name, replacement in _ui_patches(ui, args).items():
            old_ui[name] = getattr(codesys_ui, name, None)
            setattr(codesys_ui, name, replacement)

    def undo():
        if had_system:
            main.system = old_system
        else:
            delattr(main, "system")
        for name, original in old_ui.items():
            setattr(codesys_ui, name, original)
    return undo


def _ui_patches(ui, args):
    """The codesys_ui functions that open windows of their own."""
    return {
        "ask_yes_no": _yes_no(args),
        "ask_yes_no_cancel": _yes_no_cancel(args),
        "show_compare_dialog": _no_compare_dialog(ui),
    }


def _yes_no(args):
    def ask_yes_no(title, message):
        if title not in YES_NO:
            raise NeedsInput("unexpected dialog %r: %s" % (title, message))
        name, default = YES_NO[title]
        given = args.get(name)
        if given is not None:
            return bool(given)
        if default is None:
            raise NeedsInput("%s: %s" % (title, message), name)
        return default
    return ask_yes_no


def _yes_no_cancel(args):
    def ask_yes_no_cancel(title, message):
        name = YES_NO_CANCEL.get(title)
        if name is None:
            raise NeedsInput("unexpected dialog %r: %s" % (title, message))
        return "no" if args.get(name) else "cancel"
    return ask_yes_no_cancel


def _no_compare_dialog(ui):
    """Compare's picker window cannot be opened here, so report its contents.

    The counts come straight from what the window would have listed; the
    per-object lines are already on stdout, so they reach stdout_tail.
    """
    def show_compare_dialog(different, new_in_ide, new_on_disk,
                            unchanged_count=0, moved=None, *rest):
        ui.info("modified %d, only in IDE %d, only on disk %d, moved %d, "
                "identical %d (nothing was changed; compare only looks)"
                % (len(different), len(new_in_ide), len(new_on_disk),
                   len(moved or []), unchanged_count))
        return None, []
    return show_compare_dialog


def _exec_file(path, namespace):
    """Compile from bytes: IronPython 2.7 rejects a coding declaration in
    unicode source, and chokes on a BOM."""
    handle = open(path, "rb")
    try:
        source = handle.read()
    finally:
        handle.close()
    if source.startswith(codecs.BOM_UTF8):
        source = source[len(codecs.BOM_UTF8):]
    exec(compile(source, path, "exec"), namespace)


class _Tee(object):
    """Passes writes through to the real stdout and keeps the last lines."""

    def __init__(self, stream, max_lines=STDOUT_TAIL_LINES):
        self.stream = stream
        self._lines = collections.deque(maxlen=max_lines)
        self._partial = u""

    def write(self, text):
        if self.stream is not None:
            self.stream.write(text)
        parts = (self._partial + _text(text)).split(u"\n")
        self._partial = parts.pop()
        self._lines.extend(parts)

    def flush(self):
        if self.stream is not None:
            self.stream.flush()

    def tail(self):
        lines = list(self._lines)
        if self._partial:
            lines.append(self._partial)
        return u"\n".join(lines)


def _text(value):
    """Bytes or unicode in, unicode out. IronPython 2.7 hands back both."""
    if isinstance(value, type(u"")):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return type(u"")(value)
