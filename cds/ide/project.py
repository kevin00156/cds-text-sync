# -*- coding: utf-8 -*-
"""What the IDE has open right now: the project, its sync folder, the product.

Every function here takes the `projects` object the IDE injects and answers
one question about it, returning None rather than raising when the answer is
not available — a watcher must survive being asked while no project is open.

Reading the sync folder straight off the project property is deliberate.
codesys_utils.load_base_dir() does more: it can stop to ask about a computer
name mismatch, which is not something to do from a timer tick.
"""
from __future__ import print_function

import os
import sys

SYNC_FOLDER_PROP = "cds-sync-folder"


def path_of(projects_obj):
    """The primary project's path, or None when no project is open."""
    primary = getattr(projects_obj, "primary", None)
    path = getattr(primary, "path", None)
    return None if path is None else str(path)


def prop(projects_obj, name):
    """One project property as text, or None. Never raises."""
    primary = getattr(projects_obj, "primary", None)
    if primary is None:
        return None
    try:
        getter = getattr(primary, "get_project_info", None)
        info = getter() if getter else getattr(primary, "project_info", None)
        if info is None:
            return None
        value = getattr(info, "values", info)[name]
    except Exception:
        # The property may not be set, and older versions expose the
        # collection differently. Either way there is nothing to report.
        return None
    return None if value is None else str(value)


def sync_dir(projects_obj):
    """Where the .st files live, absolute, or None when it is not set.

    A relative value resolves against the project file, the same rule
    load_base_dir uses.
    """
    raw = prop(projects_obj, SYNC_FOLDER_PROP)
    if not raw:
        return None
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    project = path_of(projects_obj)
    if project is None:
        return None
    return os.path.normpath(os.path.join(os.path.dirname(project),
                                         raw.replace("/", os.sep)))


def ide_name():
    """Which product this is.

    sys.version alone cannot tell them apart — Delta 1.10 and Lenze 3.24 both
    report IronPython 2.7.7 — so lead with the executable's name.
    """
    executable = os.path.basename(getattr(sys, "executable", "") or "unknown")
    return "%s (%s)" % (executable, sys.version.replace("\n", " "))
