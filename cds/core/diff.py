# -*- coding: utf-8 -*-
"""Compare disk objects against the IDE snapshot. Disk wins.

Pure set/hash comparison. No IDE, no file IO beyond what callers pass in.
"""
from __future__ import print_function


class Changes(object):
    """The result of a diff: three flat lists of ProjectObject.

        modified  exists both sides, content differs (disk version wins)
        added     on disk, not in IDE  -> create in IDE
        removed   in IDE, not on disk  -> delete from IDE
    """

    def __init__(self):
        self.modified = []
        self.added = []
        self.removed = []

    def is_empty(self):
        return not (self.modified or self.added or self.removed)


def compute(disk_objects, ide_objects):
    """Return Changes describing how to make the IDE match disk.

    Match by guid when present, else by (path, name). Compare by content
    hash so unchanged objects are cheap to detect.
    """
    # TODO(stage 2): implement matching + content comparison.
    raise NotImplementedError("cds.core.diff.compute")
