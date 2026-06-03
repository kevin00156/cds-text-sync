# -*- coding: utf-8 -*-
"""Tests for cds.core.cache — the tiny hash cache."""
from cds.core import cache


def test_content_hash_stable_and_handles_none():
    assert cache.content_hash("abc") == cache.content_hash("abc")
    assert cache.content_hash(None) == cache.content_hash("")
    assert cache.content_hash("a") != cache.content_hash("b")


def test_load_missing_returns_empty(tmp_path):
    assert cache.load(str(tmp_path)) == {}


def test_save_then_load_round_trip(tmp_path):
    base = str(tmp_path)
    data = {"App/Main.st": "deadbeef", "App/Globals.st": "cafe"}
    cache.save(base, data)
    assert cache.load(base) == data


def test_load_corrupt_returns_empty(tmp_path):
    (tmp_path / cache.CACHE_FILE).write_text("not json {{{", encoding="utf-8")
    assert cache.load(str(tmp_path)) == {}


def test_load_non_dict_returns_empty(tmp_path):
    (tmp_path / cache.CACHE_FILE).write_text("[1, 2, 3]", encoding="utf-8")
    assert cache.load(str(tmp_path)) == {}
