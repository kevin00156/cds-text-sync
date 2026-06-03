# -*- coding: utf-8 -*-
"""Tests for cds.core.diff — disk-vs-IDE comparison, disk wins."""
from cds import types
from cds.core import diff
from cds.core.model import ProjectObject

POU = types.TYPE_GUIDS["pou"]
FOLDER = types.TYPE_GUIDS["folder"]


def _pou(name, impl, path=None):
    obj = ProjectObject(None, name, POU, path or [])
    obj.declaration = "PROGRAM " + name
    obj.implementation = impl
    return obj


def test_added_when_only_on_disk():
    disk = [_pou("New", "x := 1;")]
    changes = diff.compute(disk, [])
    assert [o.name for o in changes.added] == ["New"]
    assert not changes.modified and not changes.removed


def test_removed_when_only_in_ide():
    ide = [_pou("Gone", "x := 1;")]
    changes = diff.compute([], ide)
    assert [o.name for o in changes.removed] == ["Gone"]
    assert not changes.modified and not changes.added


def test_modified_when_content_differs():
    disk = [_pou("Main", "x := 2;")]
    ide = [_pou("Main", "x := 1;")]
    changes = diff.compute(disk, ide)
    assert [o.name for o in changes.modified] == ["Main"]
    # disk wins: the object kept is the disk version
    assert changes.modified[0].implementation == "x := 2;"


def test_identical_content_is_no_change():
    disk = [_pou("Main", "x := 1;")]
    ide = [_pou("Main", "x := 1;")]
    assert diff.compute(disk, ide).is_empty()


def test_match_is_path_sensitive():
    disk = [_pou("Main", "x := 1;", path=["A"])]
    ide = [_pou("Main", "x := 1;", path=["B"])]
    changes = diff.compute(disk, ide)
    assert [o.name for o in changes.added] == ["Main"]
    assert [o.name for o in changes.removed] == ["Main"]


def test_folders_are_not_diffed_as_content():
    disk = [ProjectObject(None, "F", FOLDER, [])]
    ide = []
    assert diff.compute(disk, ide).is_empty()
