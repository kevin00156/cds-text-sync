# -*- coding: utf-8 -*-
"""Export: IDE snapshot -> core -> .st/.xml files on disk."""
from __future__ import print_function

import os
import tempfile

from cds.ide import snapshot
from cds.core import model, textfile, cache


def run(project, base_dir, system=None):
    """Export `project` to base_dir. Returns paths written.

    Reads the IDE exactly once (snapshot.dump); everything after is pure.
    """
    snapshot_path = os.path.join(tempfile.gettempdir(), "cds_snapshot.xml")
    snapshot.dump(project, snapshot_path)            # one IDE call

    objects = model.parse(snapshot_path)
    known = cache.load(base_dir)
    written = textfile.write_tree(objects, base_dir)
    cache.save(base_dir, _hashes_for(objects))
    return written


def _hashes_for(objects):
    # TODO(stage 3): {rel_path: cache.content_hash(body)} for each object.
    raise NotImplementedError("cds.app.export._hashes_for")
