# -*- coding: utf-8 -*-
"""
codesys_constants.py - Shared constants for CODESYS scripts

Object-type GUIDs and per-kind sync policy are loaded from
profiles/default.json (edit that file to teach the engine new GUIDs or
change sync direction - no code changes needed). Behavior lists
(exportable / XML / implementation) stay in code, expressed as kinds and
expanded to GUID lists so every alias GUID is covered.

Runs under IronPython 2.7 (inside the CODESYS IDE) and CPython 3 (tests).
"""
from __future__ import print_function

import io
import json
import os
import zlib

# Script version - single source of truth for version tracking
# k* = kevin00156's independent fork line (diverged from upstream after old base)
SCRIPT_VERSION = "k1.0.2"

# Sync direction policy values allowed in the profile
_DIRECTION_VALUES = ("bidirectional", "export_only", "import_only", "disabled")


def _profile_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "profiles", "default.json")


def _load_profile():
    """Load and validate the type profile. Fails loud - a missing or broken
    profile must stop the scripts, not silently fall back to an empty type
    table (which would classify every object as skip)."""
    path = _profile_path()
    if not os.path.exists(path):
        raise ValueError(
            "Type profile not found: %s - the profiles/ directory must be "
            "installed next to codesys_constants.pyw" % path)
    f = io.open(path, "r", encoding="utf-8")
    try:
        raw = f.read()
    finally:
        f.close()
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ValueError("Type profile %s is not valid JSON: %s" % (path, e))

    aliases = data.get("guid_aliases")
    if not isinstance(aliases, dict) or not aliases:
        raise ValueError(
            "Type profile %s must define a non-empty 'guid_aliases' object" % path)
    for kind, guids in aliases.items():
        if not isinstance(guids, list) or not guids:
            raise ValueError(
                "Type profile %s: guid_aliases['%s'] must be a non-empty "
                "list of GUID strings" % (path, kind))

    direction = data.get("sync_direction", {})
    if not isinstance(direction, dict):
        raise ValueError(
            "Type profile %s: 'sync_direction' must be an object" % path)
    for kind, value in direction.items():
        if kind not in aliases:
            raise ValueError(
                "Type profile %s: sync_direction names unknown kind '%s'"
                % (path, kind))
        if value not in _DIRECTION_VALUES:
            raise ValueError(
                "Type profile %s: sync_direction['%s'] = '%s' is not one of %s"
                % (path, kind, value, "/".join(_DIRECTION_VALUES)))
    return data, raw


_PROFILE, _PROFILE_RAW = _load_profile()

PROFILE_NAME = _PROFILE.get("name", "unnamed")
# CRC of the raw profile text - stored in sync_cache.json so a profile edit
# invalidates cached classifications (they may be stale skips).
PROFILE_HASH = format(zlib.crc32(_PROFILE_RAW.encode("utf-8")) & 0xFFFFFFFF, "08x")

# kind -> [guid, ...]; the FIRST entry is the primary GUID (used when creating
# objects and as the normalized effective_type). Later entries are aliases -
# alternate GUIDs other CODESYS versions emit for the same kind.
KIND_GUIDS = {}
for _kind, _guids in _PROFILE["guid_aliases"].items():
    KIND_GUIDS[str(_kind)] = [str(_g).lower() for _g in _guids]

# kind -> primary GUID (keeps the historical TYPE_GUIDS["x"] lookup working)
TYPE_GUIDS = dict((_k, _v[0]) for _k, _v in KIND_GUIDS.items())

# any alias GUID -> kind
GUID_TO_KIND = {}
for _kind, _guids in KIND_GUIDS.items():
    for _g in _guids:
        GUID_TO_KIND[_g] = _kind

# Reverse mapping for human-readable type names (covers every alias)
TYPE_NAMES = dict(GUID_TO_KIND)

# kind -> sync direction (absent kinds are bidirectional)
SYNC_DIRECTION = dict((str(_k), str(_v))
                      for _k, _v in _PROFILE.get("sync_direction", {}).items())


def kind_of(guid_or_kind):
    """Resolve a GUID (any alias) or a kind name to the kind name, else None."""
    if guid_or_kind in KIND_GUIDS:
        return guid_or_kind
    return GUID_TO_KIND.get(str(guid_or_kind).lower())


def sync_direction_of(guid_or_kind):
    """Return the profile sync direction for a GUID/kind ('bidirectional'
    when unset or unknown - never skip on missing information)."""
    kind = kind_of(guid_or_kind)
    if kind is None:
        return "bidirectional"
    return SYNC_DIRECTION.get(kind, "bidirectional")


def kind_allows_export(guid_or_kind):
    return sync_direction_of(guid_or_kind) in ("bidirectional", "export_only")


def kind_allows_import(guid_or_kind):
    return sync_direction_of(guid_or_kind) in ("bidirectional", "import_only")


def _expand_kinds(kinds):
    """Expand kind names to the flat list of ALL their GUIDs (aliases too)."""
    guids = []
    for kind in kinds:
        if kind not in KIND_GUIDS:
            raise ValueError(
                "Kind '%s' used by codesys_constants is missing from "
                "guid_aliases in %s" % (kind, _profile_path()))
        guids.extend(KIND_GUIDS[kind])
    return guids


# Kinds that contain exportable content (textual ST or native XML)
EXPORTABLE_KINDS = [
    "pou",
    "gvl",
    "persistent_gvl",   # Persistent GVL (PersistentVars) - textual decl like a regular GVL
    "dut",              # includes the SP21 P4 enumeration alias
    "itf",
    "nvl_sender",
    "nvl_receiver",
    "param_list",
    "textlist",
    "global_text_list",
    "symbol_config",
    "imagepool",
    "unit_conversion",
    "visu",
    "visu_manager",
    # web_visu and target_visu are NOT listed here - they are children of
    # visu_manager and exported as part of its recursive XML export.
    "alarm_config",
    "alarm_group",
    "alarm_storage",
    "task_config",
    "task",
    "library_manager",
    "trace",
    "softmotion_pool",
    "visu_style",
    "project_settings",
    "device",
    "file_object",
    "alarm_class",
    "imagepool_variant",
    "alarm_config_item",
    "device_module",
    "action",
    "method",           # includes the SP21 P4 alternate-method alias
    "itf_method",
    "property",
    "property_accessor",
    "task_local_gvl",   # Task Local GVL - same structure as regular GVL
]

# Kinds that can have implementation sections - these get the IMPLEMENTATION
# marker even when the implementation is empty
IMPLEMENTATION_KINDS = ["pou", "action", "method"]

# Kinds that are exported as native XML
XML_KINDS = [
    "visu",
    "textlist",
    "global_text_list",
    "imagepool",
    "symbol_config",
    "alarm_config",
    "alarm_group",
    "alarm_storage",
    "visu_manager",
    # web_visu and target_visu are part of visu_manager's recursive export
    "task_config",
    "task",
    "library_manager",
    "trace",
    "softmotion_pool",
    "visu_style",
    "project_settings",
    "device",
    "device_module",
    "file_object",
    "alarm_class",
    "imagepool_variant",
    "alarm_config_item",
    "task_local_gvl",
    "nvl_sender",
    "nvl_receiver",
]

# GUID lists consumed across the engine (alias-expanded)
EXPORTABLE_TYPES = _expand_kinds(EXPORTABLE_KINDS)
IMPLEMENTATION_TYPES = _expand_kinds(IMPLEMENTATION_KINDS)
XML_TYPES = _expand_kinds(XML_KINDS)

# Implementation section marker used in ST files
IMPL_MARKER = "// === IMPLEMENTATION ==="

# Property accessor markers for combined property files
PROPERTY_GET_MARKER = "// === GET ==="
PROPERTY_SET_MARKER = "// === SET ==="

# Default sync timeout in milliseconds
DEFAULT_TIMEOUT_MS = 10000

# Characters forbidden in filenames
FORBIDDEN_CHARS = ["<", ">", ":", "\"", "/", "\\", "|", "?", "*"]

# Files that should be ignored by the sync engine
RESERVED_FILES = {
    "_metadata.json", "_config.json", "_metadata.csv", "BASE_DIR",
    "sync_debug.log", "compare.log", ".project", ".gitattributes",
    ".gitignore", "sync_metadata.json", "sync_cache.json"
}
