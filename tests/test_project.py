# -*- coding: utf-8 -*-
"""Tests for cds.ide.project — asking the IDE what it has open.

The happy paths are covered through the watcher; what matters here is that
every question answers None instead of raising when the IDE is not in a state
to answer it. A watcher that dies because nobody has a project open is useless.
"""
from cds.ide import project


class Info(object):
    def __init__(self, values):
        self.values = values


class Primary(object):
    def __init__(self, path=None, values=None, info=True):
        self.path = path
        self._info = Info(values if values is not None else {}) if info else None

    def get_project_info(self):
        return self._info


class Projects(object):
    def __init__(self, primary=None):
        self.primary = primary


class Hostile(object):
    """A property collection that raises on lookup, as .NET ones can."""

    values = property(lambda self: (_ for _ in ()).throw(RuntimeError("nope")))


def test_no_project_open_answers_nothing():
    empty = Projects()
    assert project.path_of(empty) is None
    assert project.prop(empty, "cds-sync-folder") is None
    assert project.sync_dir(empty) is None


def test_a_project_object_that_has_no_info_answers_nothing():
    projects = Projects(Primary(r"C:\p\x.project", info=False))
    assert project.prop(projects, "cds-sync-folder") is None


def test_a_property_lookup_that_blows_up_answers_nothing():
    projects = Projects(Hostile())
    assert project.prop(projects, "cds-sync-folder") is None


def test_a_missing_property_answers_nothing():
    projects = Projects(Primary(r"C:\p\x.project", {}))
    assert project.prop(projects, "cds-sync-folder") is None


def test_a_property_set_to_nothing_answers_nothing():
    projects = Projects(Primary(r"C:\p\x.project", {"cds-sync-folder": None}))
    assert project.sync_dir(projects) is None


def test_a_relative_sync_folder_needs_a_project_to_resolve_against():
    projects = Projects(Primary(None, {"cds-sync-folder": "./sync"}))
    assert project.sync_dir(projects) is None


def test_forward_slashes_in_a_relative_folder_still_resolve():
    projects = Projects(Primary(r"C:\p\x.project",
                                {"cds-sync-folder": "./out/sync"}))
    assert project.sync_dir(projects).endswith("sync")
    assert project.sync_dir(projects).startswith("C:")


def test_the_ide_name_leads_with_the_executable():
    assert project.ide_name().endswith(")")
    assert "(" in project.ide_name()
