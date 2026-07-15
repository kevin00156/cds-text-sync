# -*- coding: utf-8 -*-
"""Tests for the kind pragma (//% cds-text-sync.kind=<kind>).

The pragma is written only for kinds that keyword sniffing cannot recover
from the ST text (persistent GVL, parameter list, action, interface method),
and lets disk->IDE creation reconstruct the right object kind - completing
the k1.0.1 persistent-GVL fix (export worked, recreate-from-disk did not).
"""
import io
import os

import pytest


@pytest.fixture(scope="module")
def env(legacy_loader):
    for dep in ("codesys_constants", "codesys_utils", "codesys_managers"):
        legacy_loader(dep)
    import sys
    engine = legacy_loader("codesys_compare_engine")
    return {
        "constants": sys.modules["codesys_constants"],
        "utils": sys.modules["codesys_utils"],
        "managers": sys.modules["codesys_managers"],
        "engine": engine,
    }


_PERSISTENT_DECL = "VAR_GLOBAL PERSISTENT RETAIN\n    g_iCount : INT;\nEND_VAR"
_PLAIN_GVL_DECL = "VAR_GLOBAL\n    g_x : INT;\nEND_VAR"
_FB_DECL = "FUNCTION_BLOCK FB_Test\nVAR\nEND_VAR"
_ACTION_BODY = "x := x + 1;"


class TestNeedsKindPragma:
    @pytest.mark.parametrize("kind,content,expected", [
        ("persistent_gvl", _PERSISTENT_DECL, True),   # sniffs as plain gvl
        ("param_list", "VAR_GLOBAL CONSTANT\n  p : INT := 1;\nEND_VAR", True),
        ("action", _ACTION_BODY, True),               # no keyword at all
        ("itf_method", "METHOD DoIt : BOOL", True),   # sniffs as method
        ("gvl", _PLAIN_GVL_DECL, False),
        ("pou", _FB_DECL, False),
        ("dut", "TYPE E_Mode :\n(\n  Idle := 0\n);\nEND_TYPE", False),
        ("method", "METHOD DoIt : BOOL", False),
        (None, _FB_DECL, False),
    ])
    def test_truth_table(self, env, kind, content, expected):
        assert env["utils"].needs_kind_pragma(kind, content) is expected


class TestCreateFromKindPragma:
    """create_new_object must resolve the kind pragma to the profile's
    primary GUID and hand it to the manager."""

    class _StubManager(object):
        def __init__(self):
            self.calls = []

        def create(self, container, name, file_path, type_guid):
            self.calls.append((name, type_guid))
            return None  # creation outcome is not under test

    def _write(self, tmp_path, name, text):
        p = os.path.join(str(tmp_path), name)
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_kind_pragma_overrides_sniffed_type(self, env, tmp_path):
        engine = env["engine"]
        constants = env["constants"]
        stub = self._StubManager()
        managers = {"default": stub, "native": stub}

        path = self._write(
            tmp_path, "PersistentVars.st",
            "//% cds-text-sync.kind=persistent_gvl\n\n" + _PERSISTENT_DECL + "\n")
        engine.create_new_object("PersistentVars.st", path, managers, {}, {},
                                 object())
        assert stub.calls, "manager.create was never called"
        _, got_guid = stub.calls[0]
        assert got_guid == constants.TYPE_GUIDS["persistent_gvl"]

    def test_no_pragma_falls_back_to_sniffing(self, env, tmp_path):
        engine = env["engine"]
        constants = env["constants"]
        stub = self._StubManager()
        managers = {"default": stub, "native": stub}

        path = self._write(tmp_path, "GVL.st", _PLAIN_GVL_DECL + "\n")
        engine.create_new_object("GVL.st", path, managers, {}, {}, object())
        assert stub.calls[0][1] == constants.TYPE_GUIDS["gvl"]

    def test_unknown_kind_fails_loud(self, env, tmp_path):
        engine = env["engine"]
        stub = self._StubManager()
        managers = {"default": stub, "native": stub}

        path = self._write(
            tmp_path, "Weird.st",
            "//% cds-text-sync.kind=no_such_kind\n\n" + _PLAIN_GVL_DECL + "\n")
        res = engine.create_new_object("Weird.st", path, managers, {}, {},
                                       object())
        assert res is None
        assert not stub.calls, "must not create an object of a guessed kind"


class TestSpecialGvlCreation:
    """POUManager routes special GVL kinds away from the create_pou fallback."""

    class FakeObj(object):
        type = "261bd6e6-249c-4232-bb6f-84c2fbeef430"  # persistent_gvl primary

        def get_name(self):
            return "PersistentVars"

    class FakeContainer(object):
        def __init__(self):
            self.created = []

        def create_child(self, name, type_guid):
            self.created.append((name, type_guid))
            return TestSpecialGvlCreation.FakeObj()

        def create_pou(self, name, pou_type):  # pragma: no cover - must not run
            raise AssertionError("persistent GVL must never be created as a POU")

    class DeadContainer(object):
        """No creation APIs at all."""

    def _persistent_file(self, tmp_path):
        p = os.path.join(str(tmp_path), "PersistentVars.st")
        with io.open(p, "w", encoding="utf-8") as f:
            f.write("//% cds-text-sync.kind=persistent_gvl\n\n"
                    + _PERSISTENT_DECL + "\n")
        return p

    def test_uses_typed_child_api_not_create_pou(self, env, tmp_path):
        mgr = env["managers"].POUManager()
        constants = env["constants"]
        container = self.FakeContainer()
        obj = mgr.create(container, "PersistentVars",
                         self._persistent_file(tmp_path),
                         constants.TYPE_GUIDS["persistent_gvl"])
        assert obj is not None
        assert container.created == [
            ("PersistentVars", constants.TYPE_GUIDS["persistent_gvl"])]

    def test_no_creation_api_fails_loud_not_silent_pou(self, env, tmp_path):
        mgr = env["managers"].POUManager()
        constants = env["constants"]
        obj = mgr.create(self.DeadContainer(), "PersistentVars",
                         self._persistent_file(tmp_path),
                         constants.TYPE_GUIDS["persistent_gvl"])
        assert obj is None


class TestExportSideRendering:
    """The export path puts the kind pragma in the file but keeps it out of
    the state hash (identity metadata, not object state)."""

    def test_kind_not_part_of_state_hash(self, env):
        utils = env["utils"]
        assert utils.build_state_hash(_PERSISTENT_DECL, {}) == \
            utils.build_state_hash(_PERSISTENT_DECL, {})
        # normalize_sync_attrs ignores non-ATTR_ORDER keys like "kind"
        assert utils.normalize_sync_attrs({"kind": "persistent_gvl"}) == ()

    def test_render_and_reparse_round_trip(self, env):
        utils = env["utils"]
        rendered = utils.render_sync_pragmas(
            {"kind": "persistent_gvl", "exclude_from_build": True},
            _PERSISTENT_DECL)
        pragmas, clean = utils.parse_sync_pragmas(rendered)
        assert pragmas["kind"] == "persistent_gvl"
        assert pragmas["exclude_from_build"] == "true"
        assert clean == _PERSISTENT_DECL
        # and the build attrs extracted for comparison exclude the kind
        assert utils.attrs_from_pragmas(pragmas) == {"exclude_from_build": True}
