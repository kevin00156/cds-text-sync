# -*- coding: utf-8 -*-
"""Turn a Changes set into a single native import.xml.

The patch is what cds.ide.apply feeds to import_native in one call. It must
include create nodes for `added` objects so disk-only files import cleanly
(PRINCIPLES.md §5).
"""
from __future__ import print_function


def build(changes, output_path):
    """Write a native import.xml for `changes` to output_path; return it.

    Modified + added objects become import/create nodes; removed objects are
    handled by the apply step (deletion is an IDE operation, not XML content).
    Pure: builds XML text from the model, writes one file.
    """
    # TODO(stage 2): build native XML via xml.etree. Reuse type info from
    # cds.types to emit the right node kind per object.
    raise NotImplementedError("cds.core.patch.build")
