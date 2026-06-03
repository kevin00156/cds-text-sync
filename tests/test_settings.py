# -*- coding: utf-8 -*-
"""Tests for cds.settings — the metadata-gating policy."""
from cds import settings
from cds.settings import Settings


def test_default_is_quiet():
    assert Settings().debug is False
    assert Settings().wants_metadata() is False


def test_debug_enables_metadata():
    assert Settings(debug=True).wants_metadata() is True


def test_from_props_reads_debug():
    props = {settings.PROP_DEBUG: True}
    s = Settings.from_props(props.get)
    assert s.debug is True


def test_from_props_defaults_quiet():
    s = Settings.from_props({}.get)
    assert s.wants_metadata() is False


def test_debug_files_are_not_local_state():
    # A file is either debug-only or local-cache, never both.
    assert not set(settings.DEBUG_ONLY_FILES) & set(settings.LOCAL_STATE_FILES)
