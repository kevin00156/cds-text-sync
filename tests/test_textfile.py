# -*- coding: utf-8 -*-
"""Tests for cds.core.textfile — the canonical on-disk format and tree IO."""
from cds import types
from cds.core import textfile
from cds.core.model import ProjectObject

POU = types.TYPE_GUIDS["pou"]
GVL = types.TYPE_GUIDS["gvl"]
METHOD = types.TYPE_GUIDS["method"]
PROPERTY = types.TYPE_GUIDS["property"]
VISU = types.TYPE_GUIDS["visu"]


def _pou(name, decl, impl, path=None):
    obj = ProjectObject(None, name, POU, path or [])
    obj.declaration = decl
    obj.implementation = impl
    return obj


# ── .st format round-trips ──────────────────────────────────────────────

def test_format_st_round_trip_with_impl():
    text = textfile.format_st("PROGRAM Main\nVAR\nEND_VAR", "x := 1;", True)
    decl, impl = textfile.parse_st(text)
    assert decl == "PROGRAM Main\nVAR\nEND_VAR"
    assert impl == "x := 1;"


def test_format_st_decl_only_keeps_impl_marker_for_pou():
    # POUs always carry an IMPLEMENTATION section, even when empty.
    text = textfile.format_st("PROGRAM Main", "", can_have_impl=True)
    assert textfile.IMPL_MARKER in text
    decl, impl = textfile.parse_st(text)
    assert decl == "PROGRAM Main"
    assert impl == ""


def test_format_st_gvl_has_no_marker():
    text = textfile.format_st("VAR_GLOBAL\nEND_VAR", None, can_have_impl=False)
    assert textfile.IMPL_MARKER not in text


def test_property_round_trip():
    text = textfile.format_property("PROPERTY P : INT", "get := 1;", "x := set;")
    decl, get_impl, set_impl = textfile.parse_property(text)
    assert decl == "PROPERTY P : INT"
    assert get_impl == "get := 1;"
    assert set_impl == "x := set;"


def test_property_get_only():
    text = textfile.format_property("PROPERTY P : INT", "get := 1;", None)
    decl, get_impl, set_impl = textfile.parse_property(text)
    assert get_impl == "get := 1;"
    assert set_impl is None


# ── type inference ────────────────────────────────────────────────────────

def test_infer_type_from_keywords():
    assert textfile.infer_type("a.st", "PROGRAM Main") == POU
    assert textfile.infer_type("a.st", "FUNCTION_BLOCK FB") == POU
    assert textfile.infer_type("a.st", "VAR_GLOBAL\nEND_VAR") == GVL
    assert textfile.infer_type("a.st", "METHOD M : BOOL") == METHOD
    assert textfile.infer_type("a.st", "PROPERTY P : INT") == PROPERTY


def test_infer_type_ignores_comments_and_pragmas():
    content = "// a comment\n(* block *)\n{attribute 'qualified'}\nPROGRAM Main"
    assert textfile.infer_type("a.st", content) == POU


def test_infer_type_unknown_is_none():
    assert textfile.infer_type("a.st", "this is not ST") is None


def test_infer_type_from_xml_filename():
    assert textfile.infer_type("HMI/Screen.visu.xml", "<x/>") == VISU
    assert textfile.infer_type("Logic/FB.pou_xml.xml", "<x/>") == POU


# ── filenames ─────────────────────────────────────────────────────────────

def test_filename_plain_and_nested():
    pou = _pou("Main", "PROGRAM Main", "")
    assert textfile.filename_for(pou) == "Main.st"

    method = ProjectObject(None, "Run", METHOD, ["App"])
    method.parent_name = "FB"
    assert textfile.filename_for(method) == "FB.Run.st"


def test_rel_path_uses_forward_slashes():
    pou = _pou("Main", "PROGRAM Main", "", path=["App", "Logic"])
    assert textfile.rel_path_for(pou) == "App/Logic/Main.st"


def test_xml_extension():
    visu = ProjectObject(None, "Screen", VISU, ["HMI"])
    visu.xml = "<Visu/>"
    assert textfile.rel_path_for(visu) == "HMI/Screen.visu.xml"


# ── write_tree / read_tree round-trip (disk IO) ─────────────────────────────

def test_write_then_read_tree_round_trip(tmp_path):
    base = str(tmp_path)
    prog = _pou("Main", "PROGRAM Main\nVAR\nEND_VAR", "x := 1;", path=["App"])
    gvl = ProjectObject(None, "Globals", GVL, ["App"])
    gvl.declaration = "VAR_GLOBAL\n  g : INT;\nEND_VAR"
    method = ProjectObject(None, "Run", METHOD, ["App"])
    method.parent_name = "Main"
    method.declaration = "METHOD Run : BOOL"
    method.implementation = "Run := TRUE;"

    written = textfile.write_tree([prog, gvl, method], base)
    assert "App/Main.st" in written
    assert "App/Globals.gvl.st" not in written  # gvl ext is .st, not .gvl.st
    assert "App/Main.Run.st" in written

    objs = {o.name: o for o in textfile.read_tree(base)}
    assert objs["Main"].type_guid == POU
    assert objs["Main"].implementation == "x := 1;"
    assert objs["Globals"].type_guid == GVL
    assert objs["Run"].type_guid == METHOD
    assert objs["Run"].parent_name == "Main"


def test_read_tree_skips_reserved_and_hidden(tmp_path):
    base = tmp_path
    (base / "App").mkdir()
    (base / "App" / "Main.st").write_text("PROGRAM Main", encoding="utf-8")
    (base / "sync_cache.json").write_text("{}", encoding="utf-8")
    (base / ".gitignore").write_text("x", encoding="utf-8")
    hidden = base / ".docs"
    hidden.mkdir()
    (hidden / "Note.st").write_text("PROGRAM Hidden", encoding="utf-8")

    names = sorted(o.name for o in textfile.read_tree(str(base)))
    assert names == ["Main"]


def test_xml_object_body_passthrough(tmp_path):
    base = str(tmp_path)
    visu = ProjectObject(None, "Screen", VISU, ["HMI"])
    visu.xml = "<Visu>raw</Visu>"
    textfile.write_tree([visu], base)
    objs = textfile.read_tree(base)
    assert len(objs) == 1
    assert objs[0].xml == "<Visu>raw</Visu>"
    assert objs[0].type_guid == VISU
