# -*- coding: utf-8 -*-
"""Import: disk .st/.xml -> core diff/patch -> IDE. Disk wins."""
from __future__ import print_function

import os
import tempfile

from cds.ide import snapshot, apply
from cds.core import model, textfile, diff, patch


def run(project, base_dir, system=None):
    """Make `project` match the files in base_dir. Returns an apply summary.

    Reads the IDE once for the baseline, writes it once with the patch.
    """
    tmp = tempfile.gettempdir()
    snapshot_path = os.path.join(tmp, "cds_snapshot.xml")
    import_path = os.path.join(tmp, "cds_import.xml")

    snapshot.dump(project, snapshot_path)            # one IDE call (read)
    ide_objects = model.parse(snapshot_path)
    disk_objects = textfile.read_tree(base_dir)

    changes = diff.compute(disk_objects, ide_objects)
    if changes.is_empty():
        return None
    patch.build(changes, import_path)
    return apply.apply(project, import_path)         # one IDE call (write)
