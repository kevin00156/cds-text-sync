# -*- coding: utf-8 -*-
"""Tests for the pure helpers in cds.app.export (cache-hash building)."""
from cds import types
from cds.app import export
from cds.core import cache, textfile
from cds.core.model import ProjectObject

POU = types.TYPE_GUIDS["pou"]
FOLDER = types.TYPE_GUIDS["folder"]


def test_hashes_for_indexes_by_rel_path_and_skips_folders():
    pou = ProjectObject(None, "Main", POU, ["App"])
    pou.declaration = "PROGRAM Main"
    pou.implementation = "x := 1;"
    folder = ProjectObject(None, "App", FOLDER, [])

    hashes = export._hashes_for([pou, folder])

    assert list(hashes.keys()) == ["App/Main.st"]
    assert hashes["App/Main.st"] == cache.content_hash(textfile.object_body(pou))
