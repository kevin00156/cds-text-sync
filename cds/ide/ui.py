# -*- coding: utf-8 -*-
"""Thin wrapper over system.ui for dialogs and notifications.

Kept here (not in core) because it touches the CODESYS `system` global.
Falls back to print() when run outside the IDE so app code stays testable.
"""
from __future__ import print_function


def info(message, system=None):
    """Show an info message; print to stdout if no IDE is present."""
    if system is not None:
        system.ui.info(message)
    else:
        print(message)


def error(message, system=None):
    """Show an error message; print to stderr-style if no IDE is present."""
    if system is not None:
        system.ui.error(message)
    else:
        print("ERROR: " + message)


def ask_yes_no(title, message, system=None):
    """Ask a yes/no question. Returns True/False. Defaults to False headless."""
    # TODO: port the message-box logic from the old codesys_ui.pyw.
    raise NotImplementedError("cds.ide.ui.ask_yes_no")
