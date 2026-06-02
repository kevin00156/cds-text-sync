# -*- coding: utf-8 -*-
"""Write a batch of changes back into CODESYS in ONE call.

The other half of the performance story (PRINCIPLES.md §3). cds.core.patch
builds a single import.xml (including <Create...> nodes for objects that
exist on disk but not in the IDE); we apply it with one import_native call.
"""
from __future__ import print_function


def apply(project, import_xml_path):
    """Apply the patch at import_xml_path to `project`.

    ONE call to project.import_native(...). Returns an ApplyResult-like
    summary (counts of updated / created / deleted). Must fail loud and name
    any object it could not apply (PRINCIPLES.md §6) — never skip silently.
    """
    # TODO(stage 2): port import_native + new-object creation. Disk wins.
    raise NotImplementedError("cds.ide.apply.apply")
