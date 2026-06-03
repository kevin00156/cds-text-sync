# -*- coding: utf-8 -*-
"""The canonical on-disk format: ProjectObject <-> .st / .xml files.

Disk is the source of truth (PRINCIPLES.md §5). This module owns the mapping
between objects and files: the .st text format (declaration / implementation /
property accessors), the filename rules, and the rule that infers an object's
type from its file so an AI can create a new object by writing one.

Pure Python, no CODESYS imports. Runs in CI and inside IronPython 2.7.
"""
from __future__ import print_function

import codecs
import os
import re

from cds import types
from cds.core.model import ProjectObject

IMPL_MARKER = types.IMPL_MARKER
GET_MARKER = types.PROPERTY_GET_MARKER
SET_MARKER = types.PROPERTY_SET_MARKER


# ── filenames ────────────────────────────────────────────────────────────

def clean_filename(name):
    """Replace characters that are illegal in filenames with '_'."""
    out = name or ""
    for ch in types.FORBIDDEN_FILENAME_CHARS:
        out = out.replace(ch, "_")
    return out


def _extension(type_guid):
    """The file extension token for a type: '.st', or '.<typename>.xml'."""
    if types.is_textual(type_guid):
        return ".st"
    name = types.TYPE_NAMES.get(type_guid, "native")
    return "." + name + ".xml"


def filename_for(obj):
    """The leaf filename for an object (no directory part)."""
    base = clean_filename(obj.name)
    if obj.parent_name and types.is_nested(obj.type_guid):
        base = clean_filename(obj.parent_name) + "." + base
    return base + _extension(obj.type_guid)


def rel_path_for(obj):
    """The object's path relative to base_dir, using forward slashes."""
    parts = [clean_filename(p) for p in obj.path]
    parts.append(filename_for(obj))
    return "/".join(parts)


# ── .st text format ──────────────────────────────────────────────────────

def format_st(declaration, implementation, can_have_impl=False):
    """Render declaration + implementation into canonical .st text.

    The IMPL_MARKER is emitted when there is implementation text, or when the
    type always has an implementation section (POU/action/method) even if
    empty, so the round-trip is stable.
    """
    lines = []
    decl = (declaration or "").strip()
    if decl:
        lines.append(decl)
    impl = (implementation or "").strip()
    if impl or can_have_impl:
        if lines:
            lines.append("")
        lines.append(IMPL_MARKER)
        if impl:
            lines.append(impl)
    return "\n".join(lines)


def parse_st(content):
    """Split canonical .st text into (declaration, implementation)."""
    if IMPL_MARKER in content:
        decl, impl = content.split(IMPL_MARKER, 1)
        return decl.strip(), impl.strip()
    return content.strip(), None


def format_property(declaration, get_impl, set_impl):
    """Render a property's declaration + GET/SET accessors into one file."""
    lines = []
    decl = (declaration or "").strip()
    if decl:
        lines.append(decl)
    get = (get_impl or "").strip()
    setv = (set_impl or "").strip()
    if get:
        if lines:
            lines.append("")
        lines.append(IMPL_MARKER)
        lines.append(GET_MARKER)
        lines.append(get)
    if setv:
        if not get:
            if lines:
                lines.append("")
            lines.append(IMPL_MARKER)
        lines.append("")
        lines.append(SET_MARKER)
        lines.append(setv)
    return "\n".join(lines)


def parse_property(content):
    """Split a property file into (declaration, get_impl, set_impl)."""
    if IMPL_MARKER not in content:
        return content.strip(), None, None
    decl, impl = content.split(IMPL_MARKER, 1)
    decl = decl.strip()
    impl = impl.strip()
    if GET_MARKER in impl:
        _, after_get = impl.split(GET_MARKER, 1)
        if SET_MARKER in after_get:
            get_part, set_part = after_get.split(SET_MARKER, 1)
            return decl, get_part.strip(), set_part.strip()
        return decl, after_get.strip(), None
    if SET_MARKER in impl:
        _, set_part = impl.split(SET_MARKER, 1)
        return decl, None, set_part.strip()
    return decl, impl, None


# ── type inference (for disk-only / new objects) ───────────────────────────

_KEYWORD_TYPES = {
    "PROGRAM": "pou",
    "FUNCTION_BLOCK": "pou",
    "FUNCTION": "pou",
    "VAR_GLOBAL": "gvl",
    "TYPE": "dut",
    "INTERFACE": "itf",
    "METHOD": "method",
    "PROPERTY": "property",
    "ACTION": "action",
}

_COMMENT_RE = re.compile(r"\(\*[\s\S]*?\*\)")
_PRAGMA_RE = re.compile(r"\{[\s\S]*?\}")
_LINE_COMMENT_RE = re.compile(r"//.*")


def infer_type(rel_path, content):
    """Infer the CODESYS type guid for a disk file, or None if undeterminable.

    For .xml files the type comes from the "<name>.<typename>.xml" token. For
    .st files it is inferred from the leading ST keyword. A None result MUST be
    reported loudly by callers (PRINCIPLES.md §6), never dropped.
    """
    if rel_path.endswith(".xml"):
        return _xml_type_from_name(rel_path)
    text = _COMMENT_RE.sub("", content or "")
    text = _PRAGMA_RE.sub("", text)
    text = _LINE_COMMENT_RE.sub("", text)
    for line in text.splitlines():
        words = line.split()
        if not words:
            continue
        key = _KEYWORD_TYPES.get(words[0].upper())
        if key:
            return types.TYPE_GUIDS[key]
    return None


def _xml_type_from_name(rel_path):
    """Map "Foo.visu.xml" -> visu guid; "Foo.pou_xml.xml" -> pou guid."""
    base = os.path.basename(rel_path)[:-len(".xml")]
    if "." not in base:
        return None
    token = base.rsplit(".", 1)[1]
    if token == "pou_xml":
        return types.TYPE_GUIDS["pou"]
    return types.TYPE_GUIDS.get(token)


# ── object body ────────────────────────────────────────────────────────────

def object_body(obj):
    """The text to write for an object (xml passthrough, property, or .st)."""
    if obj.xml is not None:
        return obj.xml
    if obj.type_guid == types.TYPE_GUIDS["property"]:
        return format_property(obj.declaration, obj.get_impl, obj.set_impl)
    can_have_impl = types.has_implementation(obj.type_guid)
    return format_st(obj.declaration, obj.implementation, can_have_impl)


# ── tree IO ────────────────────────────────────────────────────────────────

def write_tree(objects, base_dir):
    """Write each object to its file under base_dir. Returns relative paths.

    Folders (no body) only ensure their directory exists. The returned set is
    every content file written, for orphan cleanup by the caller.
    """
    written = set()
    for obj in objects:
        if obj.type_guid == types.TYPE_GUIDS["folder"]:
            folder = [clean_filename(p) for p in obj.path] + [clean_filename(obj.name)]
            _ensure_dir(os.path.join(base_dir, *folder))
            continue
        rel = rel_path_for(obj)
        abs_path = os.path.join(base_dir, rel.replace("/", os.sep))
        _ensure_dir(os.path.dirname(abs_path))
        with codecs.open(abs_path, "w", "utf-8") as fh:
            fh.write(object_body(obj))
        written.add(rel)
    return written


def read_tree(base_dir):
    """Read base_dir into a list of ProjectObject. Disk-only objects (no guid)
    are candidates for creation on import."""
    objects = []
    for rel in _walk_content_files(base_dir):
        content = _read(os.path.join(base_dir, rel.replace("/", os.sep)))
        if rel.endswith(".xml"):
            objects.append(_object_from_xml(rel, content))
        else:
            objects.append(_object_from_st(rel, content))
    return objects


def _object_from_st(rel, content):
    type_guid = infer_type(rel, content)
    path = rel.split("/")[:-1]
    name, parent_name = _split_nested_name(rel, type_guid)
    obj = ProjectObject(None, name, type_guid, path)
    obj.parent_name = parent_name
    if type_guid == types.TYPE_GUIDS["property"]:
        obj.declaration, obj.get_impl, obj.set_impl = parse_property(content)
    else:
        obj.declaration, obj.implementation = parse_st(content)
    return obj


def _object_from_xml(rel, content):
    type_guid = infer_type(rel, content)
    path = rel.split("/")[:-1]
    base = os.path.basename(rel)[:-len(".xml")]
    name = base.rsplit(".", 1)[0] if "." in base else base
    obj = ProjectObject(None, name, type_guid, path)
    obj.xml = content
    return obj


def _split_nested_name(rel, type_guid):
    """Return (name, parent_name) from a .st filename.

    A dotted basename means a nested child "<parent>.<child>": this holds for
    known nested types and for undeterminable types (mirrors the legacy import
    heuristic), so an AI-written "FB.Method.st" lands inside FB.
    """
    base = os.path.basename(rel)[:-len(".st")]
    if "." in base and (type_guid is None or types.is_nested(type_guid)
                        or type_guid == types.TYPE_GUIDS["pou"]):
        parent_name, child = base.rsplit(".", 1)
        return child, parent_name
    return base, None


# ── filesystem helpers ─────────────────────────────────────────────────────

def _walk_content_files(base_dir):
    """Yield relative paths of .st/.xml content files, skipping hidden dirs,
    dotfiles, and engine-owned reserved files."""
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        rel_root = os.path.relpath(root, base_dir)
        if rel_root == ".":
            rel_root = ""
        for name in files:
            if name.startswith(".") or name in types.RESERVED_FILES:
                continue
            if not (name.endswith(".st") or name.endswith(".xml")):
                continue
            yield (rel_root.replace(os.sep, "/") + "/" + name).lstrip("/")


def _ensure_dir(path):
    if path and not os.path.isdir(path):
        os.makedirs(path)


def _read(abs_path):
    with codecs.open(abs_path, "r", "utf-8") as fh:
        return fh.read()
