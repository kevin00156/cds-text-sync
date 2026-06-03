# -*- coding: utf-8 -*-
"""Export: IDE snapshot -> core -> .st/.xml files on disk."""
from __future__ import print_function

import os
import tempfile

from cds import types
from cds.ide import snapshot
from cds.core import model, textfile, cache
from cds.settings import Settings


def run(project, base_dir, settings=None, system=None):
    """Export `project` to base_dir. Returns paths written.

    Reads the IDE exactly once (snapshot.dump); everything after is pure.
    Writes only content files in normal mode; metadata is debug-gated.
    """
    settings = settings or Settings()
    snapshot_path = os.path.join(tempfile.gettempdir(), "cds_snapshot.xml")
    snapshot.dump(project, snapshot_path)            # one IDE call

    objects = model.parse(snapshot_path)
    written = textfile.write_tree(objects, base_dir)
    cache.save(base_dir, _hashes_for(objects))       # local-only (gitignored)

    if settings.wants_metadata():
        _write_run_metadata(base_dir, objects)       # debug only
    return written


def _hashes_for(objects):
    """{rel_path: content_hash} for every content object (folders excluded)."""
    hashes = {}
    for obj in objects:
        if obj.type_guid == types.TYPE_GUIDS["folder"]:
            continue
        hashes[textfile.rel_path_for(obj)] = cache.content_hash(
            textfile.object_body(obj))
    return hashes


def _write_run_metadata(base_dir, objects):
    # TODO(stage 3, debug only): write sync_metadata.json (version, timestamp,
    # duration, stats). Only ever called when settings.debug is on.
    raise NotImplementedError("cds.app.export._write_run_metadata")
