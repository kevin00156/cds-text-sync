# -*- coding: utf-8 -*-
"""Tests for cds.core.ipc — instance-directory layout and atomic JSON files."""
import io
import os

import pytest

from cds.core import ipc


def test_default_root_honors_the_env_override(monkeypatch):
    monkeypatch.setenv(ipc.ROOT_ENV, "D:\\somewhere")
    assert ipc.default_root() == "D:\\somewhere"


def test_default_root_lands_under_the_local_app_data(monkeypatch):
    monkeypatch.delenv(ipc.ROOT_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\x\\AppData\\Local")
    assert ipc.default_root().endswith(os.path.join("cds-text-sync", "instances"))


def test_instance_id_is_project_stem_plus_pid():
    assert ipc.make_instance_id("C:\\p\\softplc copy.project", 17340) == \
        "softplc_copy-17340"


def test_instance_id_survives_an_unsaved_project():
    assert ipc.make_instance_id(None, 5) == "unsaved-5"


def test_ensure_dirs_makes_both_mailboxes(tmp_path):
    root = str(tmp_path)
    ipc.ensure_dirs(root, "p-1")
    assert os.path.isdir(ipc.command_dir(root, "p-1"))
    assert os.path.isdir(ipc.result_dir(root, "p-1"))


def test_write_json_leaves_no_tmp_behind(tmp_path):
    path = str(tmp_path / "reg.json")
    ipc.write_json(path, {"a": 1})
    assert ipc.read_json(path) == {"a": 1}
    assert not os.path.exists(path + ".tmp")


def test_write_json_overwrites_an_existing_file(tmp_path):
    # The heartbeat rewrites the same name every couple of seconds; os.rename
    # alone cannot do that on Windows.
    path = str(tmp_path / "reg.json")
    ipc.write_json(path, {"beat": 1})
    ipc.write_json(path, {"beat": 2})
    assert ipc.read_json(path) == {"beat": 2}


def test_write_json_keeps_non_ascii_readable(tmp_path):
    path = str(tmp_path / "msg.json")
    ipc.write_json(path, {"text": u"匯入完成"})
    assert ipc.read_json(path)["text"] == u"匯入完成"


def test_read_json_returns_none_for_a_missing_file(tmp_path):
    assert ipc.read_json(str(tmp_path / "gone.json")) is None


def test_read_json_raises_on_a_corrupt_file(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        ipc.read_json(str(path))


def test_json_names_skips_tmp_files_and_sorts(tmp_path):
    for name in ("b.json", "a.json", "c.json.tmp", "notes.txt"):
        with io.open(str(tmp_path / name), "w", encoding="utf-8") as handle:
            handle.write(u"{}")
    assert ipc.json_names(str(tmp_path)) == ["a.json", "b.json"]


def test_json_names_is_empty_for_a_directory_that_does_not_exist(tmp_path):
    assert ipc.json_names(str(tmp_path / "nope")) == []


def test_remove_file_is_content_with_an_already_deleted_file(tmp_path):
    ipc.remove_file(str(tmp_path / "gone.json"))


def test_now_takes_the_pinned_value():
    assert ipc.now(1725453665.0) == 1725453665.0
    assert ipc.now() > 0


def test_iso_is_a_readable_stamp():
    assert ipc.iso(1725453665.0).startswith("20")
    assert "T" in ipc.iso(1725453665.0)
