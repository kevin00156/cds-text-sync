# -*- coding: utf-8 -*-
"""Hash cache to skip unchanged objects on export.

Deliberately tiny: one JSON file of {relative_path: content_hash}. If the
hash matches, the object is unchanged and we skip writing it. No cache
version migrations, no Merkle tree — that complexity was not worth it.

This file is machine-local state, not project data: it must be gitignored
and never committed (see cds.settings.LOCAL_STATE_FILES).
"""
from __future__ import print_function

import codecs
import hashlib
import json
import os

CACHE_FILE = "sync_cache.json"


def content_hash(text):
    """Stable hash of a unit of content. SHA-1 is plenty here."""
    if text is None:
        text = ""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load(base_dir):
    """Load {rel_path: hash} from base_dir; return {} if absent/unreadable.

    A missing or corrupt cache is not an error — it just means "nothing known,
    rebuild everything". We never crash the sync over local cache state.
    """
    path = os.path.join(base_dir, CACHE_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with codecs.open(path, "r", "utf-8") as fh:
            data = json.load(fh)
    except (ValueError, IOError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save(base_dir, hashes):
    """Write {rel_path: hash} to base_dir atomically (temp file + rename)."""
    path = os.path.join(base_dir, CACHE_FILE)
    tmp = path + ".tmp"
    with codecs.open(tmp, "w", "utf-8") as fh:
        json.dump(hashes, fh, indent=2, sort_keys=True)
    if os.path.exists(path):
        os.remove(path)
    os.rename(tmp, path)
