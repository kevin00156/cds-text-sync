# -*- coding: utf-8 -*-
"""Import: disk .st/.xml -> core diff/patch -> IDE. Disk wins."""
from __future__ import print_function

import os
import tempfile

from cds.ide import snapshot, apply
from cds.core import model, textfile, diff, patch
from cds.settings import Settings


def run(project, base_dir, settings=None, system=None):
    """Make `project` match the files in base_dir. Returns an apply summary.

    Reads the IDE once for the baseline, writes it once with the patch.
    Metadata/log output is debug-gated (settings.wants_metadata()).
    """
    settings = settings or Settings()
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
    result = apply.apply(project, import_path)        # one IDE call (write)

    if settings.wants_metadata():
        _write_run_metadata(base_dir, result)         # debug only
    return result


def _write_run_metadata(base_dir, result):
    # TODO(stage 3, debug only): write sync_metadata.json. Debug only.
    raise NotImplementedError("cds.app.import_._write_run_metadata")
