# -*- coding: utf-8 -*-
"""
Project_watch.py - Keep this IDE listening for commands from the cds-ide CLI

Start it from Tools > Scripting and leave it running. It polls a directory
under %LOCALAPPDATA%\\cds-text-sync\\instances for commands and answers them,
so an external tool can drive this IDE without you closing the project.

Waiting does not block the IDE; running a command does, for as long as that
command takes. Stop it with `cds_ide.py stop`, or with Cancel on the progress
display. All of the work lives in cds/ide/watcher.py.
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from cds.ide import watcher


def main():
    watcher.main(globals(), version=_script_version())


def _script_version():
    """Report the same version the other Project_*.py scripts do."""
    import imp
    path = os.path.join(_SCRIPT_DIR, "codesys_constants.pyw")
    return imp.load_source("codesys_constants", path).SCRIPT_VERSION


if __name__ == "__main__":
    main()
