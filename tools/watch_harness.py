# -*- coding: utf-8 -*-
"""Shared plumbing for the --runscript launchers that arm a watcher.

Not a script. `tools/probe_watcher_ui.py` and `tools/open_copy_and_watch.py`
both need to point a project's sync folder somewhere, arm the watcher the way
Project_watch.py does, and (headless only) keep the process alive; that lives
here so neither of them carries a copy of it.

IDE-side code: IronPython 2.7, and `system` and `projects` come from the
caller's globals.
"""
from __future__ import print_function

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from cds.ide import session  # noqa: E402

SYNC_FOLDER_PROP = "cds-sync-folder"


def ensure_dirs(*paths):
    for path in paths:
        if not os.path.isdir(path):
            os.makedirs(path)


# Prompts that stand between a script and an opened project, and the answer
# that gets past each. Only safe because this is pointed at a throwaway copy:
# upgrading the storage format makes the project unopenable by the older IDE
# it came from. Add keys as they turn up — LogMessageKeys prints unknown ones
# to stderr with their full text.
OPEN_ANSWERS = {
    "UpgradeProjectConfirmation": "Yes",
}


def answer_prompts(ide_globals, answers=None):
    """Pre-answer the dialogs an open would otherwise stop at.

    Also turns on LogMessageKeys, so any prompt with no answer here shows up
    in stderr by key and full text instead of just cancelling the operation.
    """
    system = ide_globals["system"]
    handling = ide_globals["PromptHandling"]
    result = ide_globals["PromptResult"]
    system.prompt_handling = (handling.LogMessageKeys |
                              handling.LogSimplePrompts |
                              handling.ProcessScriptPrompts)
    for key, answer in (OPEN_ANSWERS if answers is None else answers).items():
        system.prompt_answers[key] = getattr(result, answer)
    return system.prompt_answers


def open_project(ide_globals, path, update=None):
    """Open a project without anyone there to answer the version prompt.

    A project from an older IDE asks whether to upgrade its storage format,
    and headless the default answer is no — which cancels the open with "Do
    not upgrade the older version project". That is a prompt, not an update
    flag, so answer_prompts is what gets past it, and after that the plain
    one-argument open works.

    `update` asks for the IScriptProjects4 overload instead, naming
    VersionUpdateFlags members joined by "|" to also update devices, libraries
    and the compiler. Delta's ScriptEngine 4.0.0.0 throws a
    NullReferenceException on that overload, so it stays off by default.

    Password arguments are only passed on that path, and empty on purpose. An
    encrypted project or one with user management fails here rather than
    prompting, and failing is the right answer: credentials are not this
    tool's business.
    """
    answer_prompts(ide_globals)
    projects = ide_globals["projects"]
    flags = _update_flags(ide_globals, update) if update else None
    if flags is None:
        projects.open(path)
    else:
        projects.open(path, "", "", "", True, flags, False)
    # Deliberately not the handle open() returned. Upgrading the storage
    # format closes and reopens the project underneath, and the old handle
    # then throws NullReferenceException on the first use — Delta 1.10 does
    # exactly that on save(). primary is whatever is open now.
    return projects.primary


def _update_flags(ide_globals, update):
    """Turn "SilentMode|UpdateAll" into the .NET flags, or None if unavailable."""
    enum = ide_globals.get("VersionUpdateFlags")
    if enum is None:
        return None
    flags = None
    for name in update.split("|"):
        one = getattr(enum, name.strip())
        flags = one if flags is None else flags | one
    return flags


def point_sync_folder(project, sync_dir):
    """Set cds-sync-folder on the project. Absolute, so nothing is ambiguous."""
    info = project.get_project_info()
    values = info.values if hasattr(info, "values") else info
    values[SYNC_FOLDER_PROP] = sync_dir
    return sync_dir


def try_save(project):
    """Save, and say so if the IDE will not. The sync folder is already set in
    memory either way, which is all a watcher needs to read it.

    DIADesigner-AX 1.10 throws NullReferenceException from save() after it has
    upgraded a project's storage format, headless. Making that fatal would
    stop the run before it starts, over a step that is only about persistence.
    """
    try:
        project.save()
        return True
    except Exception as exc:
        print("harness: could not save (%s: %s)" % (type(exc).__name__, exc))
        return False


def arm(ide_globals):
    """Start the watcher, or stop it if this IDE already has one.

    Returns the watcher, or None when this run stopped one instead.
    """
    if session.current() is not None:
        session.main(ide_globals)
        print("harness: stopped the watcher")
        return None
    watcher = session.main(ide_globals, version=session.script_version())
    print("harness: armed as " + watcher.instance_id)
    return watcher


def park(ide_globals):
    """Headless only: hold the process open so the timer has somewhere to tick.

    system.delay() pumps posted messages and a timer tick is one, so the
    watcher runs. With a UI this is exactly the bug the timer design fixed —
    the window stays unclickable for as long as this loop runs.
    """
    system = ide_globals["system"]
    print("harness: parked; no UI is usable while this runs")
    while session.current() is not None:
        system.delay(200)
    print("harness: watcher stopped, unparking")
