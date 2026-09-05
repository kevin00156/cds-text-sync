# -*- coding: utf-8 -*-
"""
Project_watch.py - Keep this IDE listening for commands from the cds-ide CLI

Run it from Tools > Scripting. It arms a timer and ends immediately, so the
IDE is yours again straight away; the timer then polls a directory under
%LOCALAPPDATA%\\cds-text-sync\\instances for commands and answers them.

Run it a second time to stop the watcher. `cds_ide.py stop` does the same
thing from a terminal. The work lives in cds/ide/session.py and watcher.py.
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from cds.ide import session


def main():
    session.main(globals(), version=session.script_version())


if __name__ == "__main__":
    main()
