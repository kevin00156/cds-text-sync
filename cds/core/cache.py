# -*- coding: utf-8 -*-
"""Hash cache to skip unchanged objects on export.

Deliberately tiny: one JSON file of {relative_path: content_hash}. If the
hash matches, the object is unchanged and we skip writing it. No cache
version migrations, no Merkle tree — that complexity was not worth it.

This file is machine-local state, not project data: it must be gitignored
and never committed (see cds.settings.LOCAL_STATE_FILES).
"""
from __future__ import print_function

import hashlib

CACHE_FILE = "sync_cache.json"


def content_hash(text):
    """Stable hash of a unit of content. SHA-1 is plenty here."""
    if text is None:
        text = ""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load(base_dir):
    """Load {rel_path: hash} from base_dir; return {} if absent/unreadable."""
    # TODO(stage 3): read CACHE_FILE; tolerate missing/corrupt -> {}.
    raise NotImplementedError("cds.core.cache.load")


def save(base_dir, hashes):
    """Write {rel_path: hash} to base_dir."""
    # TODO(stage 3): atomic write of CACHE_FILE.
    raise NotImplementedError("cds.core.cache.save")
