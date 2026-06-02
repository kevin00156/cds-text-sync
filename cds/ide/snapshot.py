# -*- coding: utf-8 -*-
"""Read the whole project out of CODESYS in ONE batch call.

This is half of the entire performance story (PRINCIPLES.md §3): we do not
walk objects one-by-one across the API boundary. We ask CODESYS to dump
everything to a single native XML file, then hand that file to cds.core.
"""
from __future__ import print_function


def dump(project, output_path):
    """Export every object in `project` to a native XML snapshot at output_path.

    ONE call to project.export_native(all_objects, ...). Returns output_path.
    The snapshot is a transport artifact, not the source of truth — callers
    parse it with cds.core.model and may delete it afterwards.
    """
    # TODO(stage 1): port the batch export_native logic from the old
    # ide_export_snapshot / NativeManager. Collect children recursively once,
    # filter unexportable externals, call export_native a single time.
    raise NotImplementedError("cds.ide.snapshot.dump")
