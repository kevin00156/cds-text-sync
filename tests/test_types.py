# -*- coding: utf-8 -*-
"""Tests for cds.types — the one module implemented in the scaffold.

Demonstrates PRINCIPLES.md §10: core is pure, so core is tested. Add a test
module here for every cds.core / cds.types module as it gets implemented.
"""
from cds import types


def test_type_names_round_trip():
    for name, guid in types.TYPE_GUIDS.items():
        assert types.TYPE_NAMES[guid] == name


def test_is_textual():
    assert types.is_textual(types.TYPE_GUIDS["pou"])
    assert types.is_textual(types.TYPE_GUIDS["gvl"])
    assert not types.is_textual(types.TYPE_GUIDS["device"])
    assert not types.is_textual("not-a-guid")


def test_has_implementation():
    assert types.has_implementation(types.TYPE_GUIDS["method"])
    assert not types.has_implementation(types.TYPE_GUIDS["gvl"])


def test_textual_types_have_names():
    for guid in types.TEXTUAL_TYPES:
        assert guid in types.TYPE_NAMES
