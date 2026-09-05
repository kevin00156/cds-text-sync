# -*- coding: utf-8 -*-
"""Tests for cds.core.instances — heartbeat, liveness, and target picking."""
import io
import os

import pytest

from cds.core import instances, ipc

T0 = 1725453665.0  # a fixed "now" so nothing here depends on the clock


def make_reg(instance_id, project, now=T0, state=instances.STATE_IDLE,
             busy_at=None):
    reg = instances.new_registration(
        instance_id, 4242, "CODESYS 3.5.21.40",
        os.path.join("C:\\p", project + ".project"), now=now,
    )
    if state == instances.STATE_BUSY:
        instances.set_state(reg, instances.STATE_BUSY,
                            busy_at if busy_at is not None else now)
    return reg


# --- the record ------------------------------------------------------------

def test_a_new_registration_starts_idle_and_beating():
    reg = make_reg("softplc-1", "softplc")
    assert reg["state"] == instances.STATE_IDLE
    assert reg["project_name"] == "softplc"
    assert reg["heartbeat_epoch"] == T0


def test_heartbeat_moves_both_fields_together():
    reg = make_reg("p-1", "p")
    instances.stamp_heartbeat(reg, T0 + 60.0)
    assert reg["heartbeat_epoch"] == T0 + 60.0
    assert reg["heartbeat"] == ipc.iso(T0 + 60.0)


def test_going_idle_clears_busy_since():
    reg = make_reg("p-1", "p", state=instances.STATE_BUSY)
    instances.set_state(reg, instances.STATE_IDLE, T0)
    assert reg["busy_since"] is None and reg["busy_since_epoch"] is None


# --- liveness --------------------------------------------------------------

def test_a_fresh_idle_instance_is_alive():
    assert instances.is_alive(make_reg("p-1", "p"), now=T0 + 5.0)


def test_a_silent_idle_instance_is_dead():
    assert not instances.is_alive(make_reg("p-1", "p"), now=T0 + 30.0)


def test_a_busy_instance_stays_alive_while_its_command_could_still_run():
    # It cannot beat while a command holds the main thread, so busy_since,
    # not the heartbeat, decides.
    busy = make_reg("p-1", "p", state=instances.STATE_BUSY)
    assert instances.is_alive(busy, now=T0 + 90.0)


def test_a_busy_instance_past_the_timeout_is_dead():
    busy = make_reg("p-1", "p", state=instances.STATE_BUSY)
    assert not instances.is_alive(busy, now=T0 + 200.0)


def test_a_registration_with_no_heartbeat_at_all_is_dead():
    assert not instances.is_alive({"instance_id": "p-1"}, now=T0)


# --- the files -------------------------------------------------------------

def test_a_registration_round_trips(tmp_path):
    root = str(tmp_path)
    instances.write(root, make_reg("softplc-1", "softplc"))
    assert instances.read(root, "softplc-1")["pid"] == 4242


def test_read_all_ignores_half_written_tmp_files(tmp_path):
    root = str(tmp_path)
    instances.write(root, make_reg("p-1", "p"))
    with io.open(os.path.join(root, "p-2.json.tmp"), "w",
                 encoding="utf-8") as handle:
        handle.write(u"{half")
    assert [r["instance_id"] for r in instances.read_all(root)] == ["p-1"]


def test_delete_takes_the_directory_with_it(tmp_path):
    root = str(tmp_path)
    ipc.ensure_dirs(root, "p-1")
    instances.write(root, make_reg("p-1", "p"))
    instances.delete(root, "p-1")
    assert instances.read(root, "p-1") is None
    assert not os.path.exists(ipc.instance_dir(root, "p-1"))


# --- cleanup ---------------------------------------------------------------

def test_prune_stale_removes_a_dead_instance_and_its_directory(tmp_path):
    root = str(tmp_path)
    ipc.ensure_dirs(root, "p-1")
    instances.write(root, make_reg("p-1", "p"))
    assert instances.prune_stale(root, now=T0 + 300.0) == ["p-1"]
    assert instances.read_all(root) == []
    assert not os.path.exists(ipc.instance_dir(root, "p-1"))


def test_prune_stale_spares_an_instance_mid_command(tmp_path):
    # A three-minute import beats no heartbeat for three minutes. Deleting
    # that instance would pull the directory out from under a live watcher.
    root = str(tmp_path)
    ipc.ensure_dirs(root, "p-1")
    instances.write(root, make_reg("p-1", "p", state=instances.STATE_BUSY))
    assert instances.prune_stale(root, now=T0 + 90.0) == []
    assert len(instances.read_all(root)) == 1


def test_prune_stale_spares_a_beating_instance(tmp_path):
    root = str(tmp_path)
    instances.write(root, make_reg("p-1", "p"))
    assert instances.prune_stale(root, now=T0 + 5.0) == []


# --- target resolution -----------------------------------------------------

def two_live_instances():
    return [make_reg("softplc-1", "softplc"), make_reg("boiler-2", "boiler")]


def test_an_exact_instance_id_wins():
    picked = instances.resolve_target(two_live_instances(), "boiler-2", now=T0)
    assert picked["instance_id"] == "boiler-2"


def test_a_project_name_matches_regardless_of_case():
    picked = instances.resolve_target(two_live_instances(), "SoftPLC", now=T0)
    assert picked["instance_id"] == "softplc-1"


def test_no_target_picks_the_only_live_instance():
    regs = [make_reg("softplc-1", "softplc"),
            make_reg("boiler-2", "boiler", now=T0 - 300.0)]
    assert instances.resolve_target(regs, now=T0)["instance_id"] == "softplc-1"


def test_no_target_with_two_live_instances_hands_back_the_candidates():
    with pytest.raises(instances.TargetError) as caught:
        instances.resolve_target(two_live_instances(), now=T0)
    assert len(caught.value.matches) == 2


def test_an_ambiguous_project_name_hands_back_the_candidates():
    regs = [make_reg("softplc-1", "softplc"), make_reg("softplc-2", "softplc")]
    with pytest.raises(instances.TargetError) as caught:
        instances.resolve_target(regs, "softplc", now=T0)
    assert len(caught.value.matches) == 2


def test_no_live_instance_at_all_is_an_error():
    with pytest.raises(instances.TargetError) as caught:
        instances.resolve_target([make_reg("p-1", "p", now=T0 - 300.0)], now=T0)
    assert caught.value.matches == []


def test_a_dead_instance_is_not_a_target_even_by_exact_id():
    with pytest.raises(instances.TargetError):
        instances.resolve_target([make_reg("p-1", "p", now=T0 - 300.0)],
                                 "p-1", now=T0)


def test_prune_stale_never_touches_a_busy_instance(tmp_path):
    # A real import on a real project takes minutes. Tying this to the
    # command timeout only protected commands shorter than that, which is not
    # the interesting case: deleting the directory takes cmd/ and result/ away
    # from a live process.
    root = str(tmp_path)
    ipc.ensure_dirs(root, "p-1")
    instances.write(root, make_reg("p-1", "p", state=instances.STATE_BUSY))
    for elapsed in (150.0, 600.0, 86400.0):
        assert instances.prune_stale(root, now=T0 + elapsed) == []
    assert os.path.exists(ipc.instance_dir(root, "p-1"))


def test_prune_stale_still_clears_an_idle_corpse(tmp_path):
    root = str(tmp_path)
    instances.write(root, make_reg("p-1", "p"))
    assert instances.prune_stale(root, now=T0 + 150.0) == ["p-1"]
