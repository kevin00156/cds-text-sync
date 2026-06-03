# -*- coding: utf-8 -*-
"""Compare disk objects against the IDE snapshot. Disk wins.

Pure comparison over ProjectObject lists. No IDE, no file IO: callers pass the
two object lists in (disk from textfile.read_tree, IDE from model.parse).
"""
from __future__ import print_function

from cds import types
from cds.core import textfile


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
    """Return Changes to make the IDE match disk.

    Objects are matched by their canonical relative path, which both sides
    derive identically from (path, name, type). Equality is by canonical
    serialized content, so formatting-only differences never show up as a
    change. Folders are structural and are not diffed as content.
    """
    disk = _by_path(disk_objects)
    ide = _by_path(ide_objects)

    changes = Changes()
    for key, obj in disk.items():
        match = ide.get(key)
        if match is None:
            changes.added.append(obj)
        elif _content(obj) != _content(match):
            changes.modified.append(obj)
    for key, obj in ide.items():
        if key not in disk:
            changes.removed.append(obj)
    return changes


def _by_path(objects):
    """Index content objects by canonical relative path (folders excluded)."""
    indexed = {}
    for obj in objects:
        if obj.type_guid == types.TYPE_GUIDS["folder"]:
            continue
        indexed[textfile.rel_path_for(obj)] = obj
    return indexed


def _content(obj):
    return textfile.object_body(obj)
