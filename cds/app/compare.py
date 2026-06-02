# -*- coding: utf-8 -*-
"""Compare: same as import up to the diff, but never touches the IDE."""
from __future__ import print_function

import os
import tempfile

from cds.ide import snapshot
from cds.core import model, textfile, diff


def run(project, base_dir, system=None):
    """Return Changes describing disk vs IDE. Read-only — no writes."""
    snapshot_path = os.path.join(tempfile.gettempdir(), "cds_snapshot.xml")
    snapshot.dump(project, snapshot_path)            # one IDE call (read)
    ide_objects = model.parse(snapshot_path)
    disk_objects = textfile.read_tree(base_dir)
    return diff.compute(disk_objects, ide_objects)
