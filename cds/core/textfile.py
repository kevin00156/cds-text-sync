# -*- coding: utf-8 -*-
"""The canonical on-disk format: ProjectObject <-> .st / .xml files.

Disk is the source of truth (PRINCIPLES.md §5). This module owns the mapping
between objects and files, including the rule that decides an object's type
from its file (so an AI can create a new object by writing a file).
"""
from __future__ import print_function


def write_tree(objects, base_dir):
    """Write each ProjectObject to its file under base_dir.

    Returns the set of relative paths written (for orphan cleanup).
    """
    # TODO(stage 1): port .st formatting (decl + IMPL_MARKER + impl) and the
    # native-xml sidecar writing for non-textual types.
    raise NotImplementedError("cds.core.textfile.write_tree")


def read_tree(base_dir):
    """Read base_dir back into a list of ProjectObject.

    Objects with no native guid are disk-only (candidates for creation on
    import). This is what makes "write a file, import it" work.
    """
    # TODO(stage 2): walk base_dir, parse each .st/.xml back into objects.
    raise NotImplementedError("cds.core.textfile.read_tree")


def infer_type(rel_path, content):
    """Infer the CODESYS type guid for a disk file (for new-object creation).

    Returns a type guid, or None if undeterminable. Callers MUST report a
    None result loudly (PRINCIPLES.md §6) — never silently drop the file.
    Keep all heuristics here so they are testable in one place.
    """
    # TODO(stage 2): infer from TypeGuid pragma, extension, and ST keywords
    # (FUNCTION_BLOCK / FUNCTION / PROGRAM / VAR_GLOBAL / TYPE ... etc).
    raise NotImplementedError("cds.core.textfile.infer_type")
