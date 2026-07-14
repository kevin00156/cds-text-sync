# -*- coding: utf-8 -*-
"""Regression tests for device-name remap on import.

Every device-contained object's path starts with the device name (see
get_container_prefix). When an export made under device 'A' is imported into a
project whose device is now named 'B', every disk path still begins with 'A/'.
Without remapping, find_object_by_path / ensure_folder_path fail to locate 'A'
and silently create a phantom top-level folder 'A', nesting everything OUTSIDE
the real device — the objects exist in the project (compare sees them) but never
appear under the device in the IDE.

build_device_remap() must recognise the renamed device (by structural match on
the second path level, e.g. 'Application') and map it back to the real device,
while leaving genuine project-global folders alone.
"""
import importlib.util
import os
import sys
from importlib.machinery import SourceFileLoader

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_legacy(module_name):
    # .pyw is only in importlib's SOURCE_SUFFIXES on Windows, so an explicit
    # loader is required for spec_from_file_location to work on Linux CI.
    path = os.path.join(REPO_ROOT, module_name + ".pyw")
    loader = SourceFileLoader(module_name, path)
    spec = importlib.util.spec_from_file_location(module_name, path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def env():
    for dep in ("codesys_constants", "codesys_utils", "codesys_managers"):
        _load_legacy(dep)
    constants = sys.modules["codesys_constants"]
    engine = _load_legacy("codesys_compare_engine")
    return engine, constants.TYPE_GUIDS


class Node(object):
    """Minimal stand-in for a CODESYS script object."""

    def __init__(self, name, type_guid, children=None):
        self._name = name
        self.type = type_guid
        self._children = children or []
        self.parent = None
        for child in self._children:
            child.parent = self

    def get_name(self):
        return self._name

    def get_children(self, recursive=False):
        return list(self._children)

    @property
    def guid(self):
        return "guid-" + self._name


def _project(devices_and_folders):
    return Node("Project", "project-type", devices_and_folders)


def _device(name, app_name="Application", guids=None, under_plc_logic=False):
    app = Node(app_name, guids["application"])
    if under_plc_logic:
        inner = Node("Plc Logic", guids["plc_logic"], [app])
        return Node(name, guids["device"], [inner])
    return Node(name, guids["device"], [app])


def _items(*paths):
    return [{"path": p} for p in paths]


# ── build_device_remap ──

def test_renamed_single_device_is_remapped(env):
    engine, guids = env
    project = _project([_device("Device", guids=guids)])
    items = _items(
        "CODESYS_Control_for_Linux_SL/Application/Foo.st",
        "CODESYS_Control_for_Linux_SL/Application/GVLs/Bar.st",
    )
    remap = engine.build_device_remap(project, items)
    assert remap == {"codesys_control_for_linux_sl": "Device"}


def test_matching_device_name_no_remap(env):
    engine, guids = env
    project = _project([_device("Device", guids=guids)])
    items = _items("Device/Application/Foo.st")
    assert engine.build_device_remap(project, items) == {}


def test_application_under_plc_logic_is_found(env):
    engine, guids = env
    project = _project([_device("Device", guids=guids, under_plc_logic=True)])
    items = _items("OldName/Application/Foo.st")
    assert engine.build_device_remap(project, items) == {"oldname": "Device"}


def test_global_folder_not_remapped(env):
    engine, guids = env
    # A new project-global pool (second level is a plain file, not 'Application').
    project = _project([_device("Device", guids=guids)])
    items = _items("GlobalPool/Bar.st")
    assert engine.build_device_remap(project, items) == {}


def test_ambiguous_multidevice_left_unmapped(env):
    engine, guids = env
    project = _project([
        _device("PLC_A", guids=guids),
        _device("PLC_B", guids=guids),
    ])
    # 'Application' exists under both devices -> can't tell which -> no remap.
    items = _items("OldDevice/Application/Foo.st")
    assert engine.build_device_remap(project, items) == {}


def test_picks_correct_device_in_multidevice(env):
    engine, guids = env
    # Only PLC_B has an 'App2' child, so the stray folder maps to PLC_B.
    project = _project([
        _device("PLC_A", app_name="App1", guids=guids),
        _device("PLC_B", app_name="App2", guids=guids),
    ])
    items = _items("OldDevice/App2/Foo.st")
    assert engine.build_device_remap(project, items) == {"olddevice": "PLC_B"}


def test_no_devices_no_remap(env):
    engine, guids = env
    project = _project([Node("JustAFolder", guids["folder"])])
    items = _items("Whatever/Application/Foo.st")
    assert engine.build_device_remap(project, items) == {}


# ── remap_path_device / apply_device_remap ──

def test_remap_path_device_rewrites_leading_segment(env):
    engine, _ = env
    remap = {"olddev": "Device"}
    assert engine.remap_path_device("OldDev/Application/Foo.st", remap) == \
        "Device/Application/Foo.st"


def test_remap_path_device_is_case_insensitive_and_normalises(env):
    engine, _ = env
    remap = {"olddev": "Device"}
    assert engine.remap_path_device("OLDDEV\\App\\Foo.st", remap) == \
        "Device/App/Foo.st"


def test_remap_path_device_noop_when_unmatched(env):
    engine, _ = env
    remap = {"olddev": "Device"}
    assert engine.remap_path_device("Other/Foo.st", remap) == "Other/Foo.st"
    assert engine.remap_path_device("Other/Foo.st", {}) == "Other/Foo.st"


def test_apply_device_remap_touches_logical_paths_only(env):
    engine, _ = env
    remap = {"olddev": "Device"}
    item = {
        "path": "OldDev/Application/Foo.st",
        "disk_path": "OldDev/Application/Foo.st",
        "ide_path": "Device/Application/Foo.st",
        "file_path": "C:/export/OldDev/Application/Foo.st",
    }
    engine.apply_device_remap([item], remap)
    assert item["path"] == "Device/Application/Foo.st"
    assert item["disk_path"] == "Device/Application/Foo.st"
    assert item["ide_path"] == "Device/Application/Foo.st"
    # The real on-disk file location must NOT be rewritten.
    assert item["file_path"] == "C:/export/OldDev/Application/Foo.st"


def test_summarize_device_remap_recovers_original_case(env):
    engine, guids = env
    project = _project([_device("Device", guids=guids)])
    items = _items("CODESYS_Control_for_Linux_SL/Application/Foo.st")
    remap = engine.build_device_remap(project, items)
    assert engine.summarize_device_remap(items, remap) == \
        ["CODESYS_Control_for_Linux_SL -> Device"]


def test_end_to_end_remap_then_apply(env):
    engine, guids = env
    project = _project([_device("Device", guids=guids)])
    items = _items(
        "CODESYS_Control_for_Linux_SL/Application/Foo.st",
        "CODESYS_Control_for_Linux_SL/Application/Sub/Bar.st",
        "GlobalPool/Baz.st",  # global folder stays put
    )
    remap = engine.build_device_remap(project, items)
    engine.apply_device_remap(items, remap)
    assert items[0]["path"] == "Device/Application/Foo.st"
    assert items[1]["path"] == "Device/Application/Sub/Bar.st"
    assert items[2]["path"] == "GlobalPool/Baz.st"
