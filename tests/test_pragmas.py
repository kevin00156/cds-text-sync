# -*- coding: utf-8 -*-
"""Tests for the sync pragma API (build-attribute sync, d85381d port).

parse_sync_pragmas / render_sync_pragmas are the ONE mechanism for every
//% cds-text-sync.<key>=<value> pragma line: build attributes and the kind
pragma both go through them.
"""
import os

import pytest


@pytest.fixture(scope="module")
def utils(legacy_loader):
    legacy_loader("codesys_constants")
    return legacy_loader("codesys_utils")


_ST = "FUNCTION_BLOCK FB_Test\nVAR\n    x : INT;\nEND_VAR\n\n// === IMPLEMENTATION ===\n\nx := 1;"


class TestParseSyncPragmas:
    def test_no_pragmas_returns_empty_and_unchanged(self, utils):
        pragmas, clean = utils.parse_sync_pragmas(_ST)
        assert pragmas == {}
        assert clean == _ST

    def test_parses_attr_pragma(self, utils):
        content = "//% cds-text-sync.exclude_from_build=true\n\n" + _ST
        pragmas, clean = utils.parse_sync_pragmas(content)
        assert pragmas == {"exclude_from_build": "true"}
        assert clean == _ST

    def test_parses_multiple_pragmas_and_unknown_keys(self, utils):
        content = ("//% cds-text-sync.kind=persistent_gvl\n"
                   "//% cds-text-sync.exclude_from_build=true\n"
                   "//% cds-text-sync.future_key=some value\n\n" + _ST)
        pragmas, clean = utils.parse_sync_pragmas(content)
        assert pragmas == {
            "kind": "persistent_gvl",
            "exclude_from_build": "true",
            "future_key": "some value",
        }
        assert clean == _ST

    def test_pragma_block_must_lead_the_file(self, utils):
        # A pragma-looking line inside the body is content, not a pragma.
        content = _ST + "\n//% cds-text-sync.exclude_from_build=true"
        pragmas, clean = utils.parse_sync_pragmas(content)
        assert pragmas == {}
        assert clean == content


class TestRenderSyncPragmas:
    def test_no_pragmas_renders_content_unchanged(self, utils):
        assert utils.render_sync_pragmas({}, _ST) == _ST

    def test_renders_kind_first_then_attr_order(self, utils):
        out = utils.render_sync_pragmas(
            {"kind": "persistent_gvl", "exclude_from_build": True,
             "link_always": True}, _ST)
        lines = out.split("\n")
        assert lines[0] == "//% cds-text-sync.kind=persistent_gvl"
        assert lines[1] == "//% cds-text-sync.exclude_from_build=true"
        assert lines[2] == "//% cds-text-sync.link_always=true"
        assert lines[3] == ""

    def test_round_trip(self, utils):
        rendered = utils.render_sync_pragmas(
            {"kind": "action", "external_implementation": True}, _ST)
        pragmas, clean = utils.parse_sync_pragmas(rendered)
        assert pragmas == {"kind": "action", "external_implementation": "true"}
        assert clean == _ST


class TestAttrsFromPragmas:
    def test_filters_to_registry_true_keys(self, utils):
        attrs = utils.attrs_from_pragmas({
            "exclude_from_build": "true",
            "link_always": "false",      # explicit false is NOT an attr
            "kind": "persistent_gvl",     # not a build attribute
            "unknown_key": "true",        # not in ATTR_REGISTRY
        })
        assert attrs == {"exclude_from_build": True}

    def test_empty(self, utils):
        assert utils.attrs_from_pragmas({}) == {}


class TestStateHash:
    def test_normalize_is_deterministic_and_ordered(self, utils):
        a = utils.normalize_sync_attrs({"link_always": True, "exclude_from_build": True})
        b = utils.normalize_sync_attrs({"exclude_from_build": True, "link_always": True})
        assert a == b
        assert a == (("exclude_from_build", True), ("link_always", True))

    def test_attr_flip_changes_hash_content_does_not(self, utils):
        base = utils.build_state_hash(_ST, {})
        flipped = utils.build_state_hash(_ST, {"exclude_from_build": True})
        assert base != flipped
        assert base == utils.build_state_hash(_ST, {})


class TestParseStFile:
    def test_three_tuple_with_pragmas_and_impl_split(self, utils, tmp_path):
        content = ("//% cds-text-sync.exclude_from_build=true\r\n\r\n"
                   "FUNCTION_BLOCK FB_Test\r\nVAR\r\nEND_VAR\r\n\r\n"
                   "// === IMPLEMENTATION ===\r\n\r\nx := 1;\r\n")
        p = tmp_path / "FB_Test.st"
        p.write_bytes(content.encode("utf-8"))
        decl, impl, pragmas = utils.parse_st_file(str(p))
        assert pragmas == {"exclude_from_build": "true"}
        assert decl.startswith("FUNCTION_BLOCK FB_Test")
        assert "\r" not in decl
        assert impl == "x := 1;"

    def test_plain_file_backward_compat(self, utils, tmp_path):
        p = tmp_path / "GVL.st"
        p.write_bytes(b"VAR_GLOBAL\n    g : INT;\nEND_VAR\n")
        decl, impl, pragmas = utils.parse_st_file(str(p))
        assert pragmas == {}
        assert decl.startswith("VAR_GLOBAL")
        assert impl is None

    def test_missing_file(self, utils, tmp_path):
        decl, impl, pragmas = utils.parse_st_file(str(tmp_path / "nope.st"))
        assert (decl, impl, pragmas) == (None, None, {})
