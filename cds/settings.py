# -*- coding: utf-8 -*-
"""Settings + the metadata policy. Pure data, no CODESYS imports.

Settings come from CODESYS project properties (read by the ide layer, see
PROP_* names) and are passed into app/core as a plain object. core never
reads settings from the IDE itself (PRINCIPLES.md §4).

Metadata policy (the whole point of this module):

    Always written      content files (.st / .xml), .gitattributes
    Local cache only     sync_cache.json   (gitignored, machine state)
    Debug only           sync_metadata.json, *.log

In normal mode we write the project and nothing else. Run summaries go to the
IDE console / popup, not to files. Turn on debug to get the audit trail and
logs back. This keeps git diffs to actual code changes (PRINCIPLES.md §6/§7).
"""
from __future__ import print_function

# CODESYS project-property names (stored inside the .project, not in git).
PROP_DEBUG = "cds-sync-debug"
PROP_FOLDER = "cds-sync-folder"

# Files that are debug-only output. Never written unless Settings.debug.
DEBUG_ONLY_FILES = (
    "sync_metadata.json",
    "sync_debug.log",
    "compare.log",
)

# Local machine state: written normally but must be gitignored, never tracked.
LOCAL_STATE_FILES = (
    "sync_cache.json",
)


class Settings(object):
    """Plain-data settings bag. Defaults are the quiet, normal-mode behavior."""

    def __init__(self, debug=False):
        self.debug = debug

    @classmethod
    def from_props(cls, get_prop):
        """Build Settings from a get_prop(name, default) callable.

        The ide layer passes a function that reads CODESYS project properties;
        tests pass a dict's .get. Keeps core free of any IDE dependency.
        """
        return cls(debug=bool(get_prop(PROP_DEBUG, False)))

    def wants_metadata(self):
        """True if debug-only metadata/log files should be written."""
        return self.debug
