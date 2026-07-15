# -*- coding: utf-8 -*-
"""Regression test for parent-before-child ST import ordering.

Methods/actions/properties of a POU are stored on disk as "<Parent>.<Child>.st"
and must be created AFTER their parent "<Parent>.st" exists. The disk scan
returns files in alphabetical order, where "<FB>.Method.st" sorts BEFORE
"<FB>.st" (the '.' separator is < alphanumerics), so without explicit ordering
the child is processed first, the parent is not found, and the importer used to
fall back to creating a POU with an invalid dotted name. See sync_debug.log:
    "Failed to create MC_BasicControl.DoSetPosition: The name
     'MC_BasicControl.DoSetPosition' is not valid for this object."

order_st_files_parents_first() must put parents first regardless of input order.
"""
import os

import pytest


@pytest.fixture(scope="module")
def engine(legacy_loader):
    # Dependencies must be importable first (engine imports from them at load).
    for dep in ("codesys_constants", "codesys_utils", "codesys_managers"):
        legacy_loader(dep)
    return legacy_loader("codesys_compare_engine")


def _depths(items, order_fn):
    return [base.count(".")
            for base in (os.path.splitext(it["path"].split("/")[-1])[0]
                         for it in order_fn(items))]


def test_parent_before_children_same_folder(engine):
    # Alphabetical (disk scan) order: children before parent.
    items = [
        {"path": "Device/Application/Function Blocks/MC_BasicControl/MC_BasicControl.DoSetPosition.st"},
        {"path": "Device/Application/Function Blocks/MC_BasicControl/MC_BasicControl.Home.st"},
        {"path": "Device/Application/Function Blocks/MC_BasicControl/MC_BasicControl._ClearAllExecute.st"},
        {"path": "Device/Application/Function Blocks/MC_BasicControl/MC_BasicControl.st"},
    ]
    ordered = engine.order_st_files_parents_first(items)
    names = [it["path"].split("/")[-1] for it in ordered]
    # Parent FB file must come before every one of its method files.
    assert names[0] == "MC_BasicControl.st"
    assert names.index("MC_BasicControl.st") < names.index("MC_BasicControl.DoSetPosition.st")


def test_property_accessor_after_property(engine):
    # Three nesting levels: FB -> Property -> Get/Set accessor.
    items = [
        {"path": "FB/FB.Speed.Get.st"},
        {"path": "FB/FB.Speed.st"},
        {"path": "FB/FB.st"},
    ]
    assert _depths(items, engine.order_st_files_parents_first) == [0, 1, 2]


def test_stable_within_same_depth(engine):
    # Files at the same nesting depth keep their original relative order.
    items = [
        {"path": "a/Zebra.st"},
        {"path": "a/Alpha.st"},
        {"path": "a/Mango.st"},
    ]
    ordered = [it["path"] for it in engine.order_st_files_parents_first(items)]
    assert ordered == ["a/Zebra.st", "a/Alpha.st", "a/Mango.st"]


def test_does_not_mutate_input(engine):
    items = [{"path": "FB/FB.Method.st"}, {"path": "FB/FB.st"}]
    before = list(items)
    engine.order_st_files_parents_first(items)
    assert items == before
