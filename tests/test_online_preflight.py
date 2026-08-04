# -*- coding: utf-8 -*-
"""Pre-flight for the "logged into a device" import failure.

CODESYS refuses to create, move or delete any object belonging to an
application that is logged into a PLC. Before this check an import hit that
refusal once per object ("Cannot add an object because it affects a device you
are currently logged into"), deep in the run, after the compare and the safety
backup — never naming the one fix: log out.

find_logged_in_applications must therefore see EVERY application (aliased type
GUIDs, several devices, apps under 'PLC Logic'), stay cheap on big projects,
and — crucially — report nothing rather than guess when the online API cannot
answer, so a blind pre-flight never blocks a legitimate import.
"""
import sys

import pytest


@pytest.fixture(scope="module")
def env(legacy_loader):
    for dep in ("codesys_constants", "codesys_utils", "codesys_managers"):
        legacy_loader(dep)
    constants = sys.modules["codesys_constants"]
    module = legacy_loader("codesys_online")
    return module, constants.TYPE_GUIDS, constants.KIND_GUIDS


class Node(object):
    """Minimal stand-in for a CODESYS script object."""

    def __init__(self, name, type_guid, children=None):
        self._name = name
        self.type = type_guid
        self._children = children or []
        self.parent = None
        self.get_children_calls = 0
        for child in self._children:
            child.parent = self

    def get_name(self):
        return self._name

    def get_children(self, recursive=False):
        self.get_children_calls += 1
        return list(self._children)


class Session(object):
    """Stand-in for ScriptOnlineApplication."""

    def __init__(self, is_logged_in):
        self.is_logged_in = is_logged_in
        self.disposed = False

    def Dispose(self):
        self.disposed = True


class Online(object):
    """Stand-in for the CODESYS 'online' global."""

    def __init__(self, logged_in=(), unanswerable=()):
        self.logged_in = set(logged_in)
        self.unanswerable = set(unanswerable)
        self.sessions = []

    def create_online_application(self, application):
        name = application.get_name()
        if name in self.unanswerable:
            raise RuntimeError("No gateway configured")
        session = Session(name in self.logged_in)
        self.sessions.append(session)
        return session


def _project(children):
    return Node("Project", "project-type", children)


def _device(name, guids, app_name="Application", under_plc_logic=False,
            app_guid=None):
    app = Node(app_name, app_guid or guids["application"])
    if under_plc_logic:
        return Node(name, guids["device"],
                    [Node("Plc Logic", guids["plc_logic"], [app])])
    return Node(name, guids["device"], [app])


def _find(module, project, online, caller_globals=None):
    if caller_globals is None:
        caller_globals = {"online": online}
    return module.find_logged_in_applications(project, caller_globals)


# ── detection ──

def test_nothing_logged_in_reports_nothing(env):
    module, guids, _ = env
    project = _project([_device("PLC", guids)])
    assert _find(module, project, Online()) == []


def test_logged_in_application_is_reported_with_device_prefix(env):
    module, guids, _ = env
    project = _project([_device("CODESYS_Control_for_Linux_SL", guids)])
    online = Online(logged_in=["Application"])
    assert _find(module, project, online) == \
        ["CODESYS_Control_for_Linux_SL/Application"]


def test_application_under_plc_logic_is_found(env):
    module, guids, _ = env
    project = _project([_device("PLC", guids, under_plc_logic=True)])
    online = Online(logged_in=["Application"])
    assert _find(module, project, online) == ["PLC/Application"]


def test_only_the_logged_in_device_is_reported(env):
    module, guids, _ = env
    project = _project([
        _device("PLC_A", guids, app_name="App1"),
        _device("PLC_B", guids, app_name="App2"),
    ])
    online = Online(logged_in=["App2"])
    assert _find(module, project, online) == ["PLC_B/App2"]


def test_every_logged_in_application_is_reported(env):
    module, guids, _ = env
    project = _project([
        _device("PLC_A", guids, app_name="App1"),
        _device("PLC_B", guids, app_name="App2"),
    ])
    online = Online(logged_in=["App1", "App2"])
    assert _find(module, project, online) == ["PLC_A/App1", "PLC_B/App2"]


def test_alias_application_guid_is_detected(env):
    module, guids, kind_guids = env
    alias = kind_guids["application"][-1]
    assert alias != guids["application"], "profile lost the application alias"
    project = _project([_device("PLC", guids, app_guid=alias)])
    online = Online(logged_in=["Application"])
    # The alias is not the primary GUID, so get_container_prefix cannot see the
    # application — the label still has to name it.
    assert _find(module, project, online) == ["PLC/Application"]


def test_device_inside_a_folder_is_found(env):
    module, guids, _ = env
    project = _project([Node("Line1", guids["folder"],
                             [_device("PLC", guids)])])
    online = Online(logged_in=["Application"])
    assert _find(module, project, online) == ["PLC/Application"]


# ── blind pre-flight must not block ──

def test_no_online_global_reports_nothing(env):
    module, guids, _ = env
    project = _project([_device("PLC", guids)])
    assert module.find_logged_in_applications(project, {}) == []


def test_unanswerable_online_api_reports_nothing(env):
    module, guids, _ = env
    project = _project([_device("PLC", guids)])
    online = Online(logged_in=["Application"], unanswerable=["Application"])
    assert _find(module, project, online) == []


def test_unlistable_container_does_not_crash_the_walk(env):
    module, guids, _ = env

    class Deaf(Node):
        def get_children(self, recursive=False):
            raise RuntimeError("object is being edited")

    project = _project([
        Deaf("Broken", guids["device"]),
        _device("PLC", guids),
    ])
    online = Online(logged_in=["Application"])
    assert _find(module, project, online) == ["PLC/Application"]


# ── cost and hygiene ──

def test_every_session_is_disposed(env):
    module, guids, _ = env
    project = _project([
        _device("PLC_A", guids, app_name="App1"),
        _device("PLC_B", guids, app_name="App2"),
    ])
    online = Online(logged_in=["App1"])
    _find(module, project, online)
    assert len(online.sessions) == 2
    assert all(session.disposed for session in online.sessions)


def test_walk_stops_at_the_application(env):
    module, guids, _ = env
    pou = Node("MainProgram", guids["pou"])
    app = Node("Application", guids["application"], [pou])
    project = _project([Node("PLC", guids["device"], [app])])
    _find(module, project, Online())
    # Nothing below an application can be an application.
    assert app.get_children_calls == 0
    assert pou.get_children_calls == 0


def test_pou_pool_is_not_swept(env):
    module, guids, _ = env
    pous = [Node("POU%d" % i, guids["pou"]) for i in range(5)]
    pool = Node("Pool", guids["folder"], pous)
    project = _project([pool, _device("PLC", guids)])
    _find(module, project, Online())
    assert pool.get_children_calls == 1          # folders may hold devices
    assert all(p.get_children_calls == 0 for p in pous)


# ── message ──

def test_block_message_names_the_applications_and_the_fix(env):
    module, _, _ = env
    message = module.logged_in_block_message(["PLC/App1", "PLC2/App2"])
    assert "PLC/App1" in message and "PLC2/App2" in message
    assert "Logout" in message
