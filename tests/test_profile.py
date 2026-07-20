# -*- coding: utf-8 -*-
"""Tests for the JSON type profile (profiles/default.json).

The GUID tables in codesys_constants.pyw are now generated from the profile.
The golden-equivalence tests pin the generated tables to the exact values the
hardcoded k1.0.2 tables had, proving the profile refactor changes no
classification behavior (the single intended addition: the old upstream
persistent-GVL GUID is tolerated as an alias).
"""
import sys

import pytest


@pytest.fixture(scope="module")
def constants(legacy_loader):
    return legacy_loader("codesys_constants")


@pytest.fixture(scope="module")
def managers(legacy_loader):
    for dep in ("codesys_constants", "codesys_utils"):
        legacy_loader(dep)
    return legacy_loader("codesys_managers")


# The exact k1.0.2 hardcoded table (pre-profile), used as golden reference.
_OLD_TYPE_GUIDS = {
    "pou": "6f9dac99-8de1-4efc-8465-68ac443b7d08",
    "gvl": "ffbfa93a-b94d-45fc-a329-229860183b1d",
    "dut": "2db5746d-d284-4425-9f7f-2663a34b0ebc",
    "enum": "40989022-e4d2-4dc7-89d2-9a412930b20e",
    "action": "8ac092e5-3128-4e26-9e7e-11016c6684f2",
    "method": "f8a58466-d7f6-439f-bbb8-d4600e41d099",
    "method_alt": "62ebfd1c-d342-43e5-8efb-f22b6d8e4a04",
    "property": "5a3b8626-d3e9-4f37-98b5-66420063d91e",
    "property_accessor": "792f2eb6-721e-4e64-ba20-bc98351056db",
    "folder": "738bea1e-99bb-4f04-90bb-a7a567e74e3a",
    "device": "225bfe47-7336-4dbc-9419-4105a7c831fa",
    "plc_logic": "40b404f9-e5dc-42c6-907f-c89f4a517386",
    "application": "639b491f-5557-464c-af91-1471bac9f549",
    "library_manager": "adb5cb65-8e1d-4a00-b70a-375ea27582f3",
    "task_config": "ae1de277-a207-4a28-9efb-456c06bd52f3",
    "task": "98a2708a-9b18-4f31-82ed-a1465b24fa2d",
    "itf": "6654496c-404d-479a-aad2-8551054e5f1e",
    "itf_method": "f89f7675-27f1-46b3-8abb-b7da8e774ffd",
    "nvl_sender": "ffb96994-3252-4467-8507-6a1883584989",
    "nvl_receiver": "ea9e7828-b80c-4ec7-9f68-52210f019623",
    "param_list": "f89f7675-27f3-455b-b98a-243e8673a5a8",
    "persistent_gvl": "261bd6e6-249c-4232-bb6f-84c2fbeef430",
    "recipe_manager": "47225134-2e90-48e0-a42e-9ed7cf91c010",
    "recipe": "3e9a7218-1e43-4f9e-a0e2-656f4d36e8b4",
    "visu": "f18bec89-9fef-401d-9953-2f11739a6808",
    "textlist": "2bef0454-1bd3-412a-ac2c-af0f31dbc40f",
    "global_text_list": "63784cbb-9ba0-45e6-9d69-babf3f040511",
    "imagepool": "6507a8fd-035f-464a-bd5b-7f15e8ac084a",
    "visu_manager": "4d3fdb8f-ab50-4c35-9d3a-d4bb9bb9a628",
    "web_visu": "0fdbf158-1ae0-47d9-9269-cd84be308e9d",
    "alarm_config": "c0a56ce5-14a3-4757-ac56-3eab44c974b3",
    "alarm_group": "413e2a7d-adb1-4d2c-be29-6ae6e4fab820",
    "task_call": "6f9da924-d2e2-4467-9c9e-5e26bc1c1111",
    "symbol_config": "21d4fe94-4123-4e23-9091-ead220afbd1f",
    "target_visu": "bc63f5fa-d286-4786-994e-7b27e4f97bd5",
    "image": "9001d745-b9c5-4d77-90b7-b29c3f77a23b",
    "alarm_storage": "5bd56248-46fc-4108-be33-ed01ad87d070",
    "trace": "f7aa3620-8073-4c91-b6ec-86ed9eb60303",
    "project_info": "085afe48-c5d8-4ea5-ab0d-b35701fa6009",
    "alarm_config_item": "21f4ed1d-ec95-4666-820e-4abf64d93d6b",
    "device_module": "085766fd-043e-4545-8e8d-d651d56d5d3b",
    "file_object": "a56744ff-693f-4597-95f9-0e1c529fffc2",
    "alarm_class": "b8b46f61-c7c1-4259-87e4-26fe674798f9",
    "imagepool_variant": "bb0b9044-714e-4614-ad3e-33cbdf34d16b",
    "unit_conversion": "3662d04a-384c-4734-9189-9e8756910793",
    "softmotion_pool": "e9159722-55bc-49e5-8034-fbd278ef718f",
    "visu_style": "8e687a04-7ca7-42d3-be06-fcbda676c5ef",
    "task_local_gvl": "c2cda7a9-0ba4-4146-b563-22a42fa0eb72",
    "project_settings": "8753fe6f-4a22-4320-8103-e553c4fc8e04",
}

# The old upstream persistent-GVL GUID, now tolerated as an alias.
_OLD_UPSTREAM_PERSISTENT = "3183921b-cc91-4712-9781-c3b6555122b5"
# Second Application GUID observed by upstream on other CODESYS versions.
_APPLICATION_ALT = "6394ad93-46a4-4927-8819-c1ca8654c6ad"


def _old_expandable(*kinds):
    return set(_OLD_TYPE_GUIDS[k] for k in kinds)


class TestGoldenEquivalence:
    """The generated tables must match the pre-profile hardcoded values."""

    def test_primary_guids_unchanged(self, constants):
        expected = dict(_OLD_TYPE_GUIDS)
        # enum / method_alt are no longer kinds - they are aliases of dut / method
        del expected["enum"]
        del expected["method_alt"]
        assert constants.TYPE_GUIDS == expected

    def test_exportable_types_unchanged(self, constants):
        old = _old_expandable(
            "pou", "gvl", "persistent_gvl", "dut", "enum", "itf",
            "nvl_sender", "nvl_receiver", "param_list", "textlist",
            "global_text_list", "symbol_config", "imagepool",
            "unit_conversion", "visu", "visu_manager", "alarm_config",
            "alarm_group", "alarm_storage", "task_config", "task",
            "library_manager", "trace", "softmotion_pool", "visu_style",
            "project_settings", "device", "file_object", "alarm_class",
            "imagepool_variant", "alarm_config_item", "device_module",
            "action", "method", "method_alt", "itf_method", "property",
            "property_accessor", "task_local_gvl",
        )
        # Single intended addition: the old upstream persistent-GVL alias
        assert set(constants.EXPORTABLE_TYPES) == old | {_OLD_UPSTREAM_PERSISTENT}

    def test_xml_types_unchanged(self, constants):
        old = _old_expandable(
            "visu", "textlist", "global_text_list", "imagepool",
            "symbol_config", "alarm_config", "alarm_group", "alarm_storage",
            "visu_manager", "task_config", "task", "library_manager",
            "trace", "softmotion_pool", "visu_style", "project_settings",
            "device", "device_module", "file_object", "alarm_class",
            "imagepool_variant", "alarm_config_item", "task_local_gvl",
            "nvl_sender", "nvl_receiver",
        )
        assert set(constants.XML_TYPES) == old

    def test_implementation_types_unchanged(self, constants):
        old = _old_expandable("pou", "action", "method", "method_alt")
        assert set(constants.IMPLEMENTATION_TYPES) == old


class TestLegacyKindNames:
    """Retired kind names stay parseable in export filenames and kind pragmas.

    Regression: collapsing 'method_alt' into an alias of 'method' dropped it
    from TYPE_NAMES.values(), which was what filename parsing keyed on. Old
    exports named '<Name>.method_alt.xml' were then read with the suffix still
    glued to the object name ("Init.method_alt"), so every IDE lookup for them
    failed and import reported "could not find Init.method_alt after import".
    """

    def test_retired_names_are_accepted_suffixes(self, constants):
        assert "method_alt" in constants.KNOWN_TYPE_SUFFIXES
        assert "enum" in constants.KNOWN_TYPE_SUFFIXES

    def test_current_kinds_and_pou_xml_are_accepted_suffixes(self, constants):
        for kind in constants.KIND_GUIDS:
            assert kind in constants.KNOWN_TYPE_SUFFIXES
        assert "pou_xml" in constants.KNOWN_TYPE_SUFFIXES

    def test_unknown_suffix_is_rejected(self, constants):
        # Guards against a blanket "anything after the last dot is a type"
        # rule, which would truncate legitimate dotted object names.
        assert "SomeChild" not in constants.KNOWN_TYPE_SUFFIXES

    def test_every_retired_name_resolves_to_a_live_kind(self, constants):
        for old_name, kind in constants.LEGACY_KIND_NAMES.items():
            assert constants.kind_of(old_name) == kind
            assert kind in constants.KIND_GUIDS

    def test_retired_names_are_not_live_kinds(self, constants):
        for old_name in constants.LEGACY_KIND_NAMES:
            assert old_name not in constants.KIND_GUIDS
            assert old_name not in constants.TYPE_NAMES.values()

    def test_kind_pragma_with_retired_name_maps_to_primary_guid(self, constants):
        # A .st file written by an older version may carry
        # '//% cds-text-sync.kind=method_alt'; it must still create a method.
        assert constants.TYPE_GUIDS[constants.kind_of("method_alt")] == \
            _OLD_TYPE_GUIDS["method"]


class TestAliasResolution:
    def test_both_method_guids_resolve_to_method(self, constants):
        assert constants.kind_of(_OLD_TYPE_GUIDS["method"]) == "method"
        assert constants.kind_of(_OLD_TYPE_GUIDS["method_alt"]) == "method"

    def test_both_persistent_gvl_guids_resolve(self, constants):
        assert constants.kind_of(_OLD_TYPE_GUIDS["persistent_gvl"]) == "persistent_gvl"
        assert constants.kind_of(_OLD_UPSTREAM_PERSISTENT) == "persistent_gvl"
        # ...but the primary (creation) GUID is the SP21-P4-verified one
        assert constants.TYPE_GUIDS["persistent_gvl"] == _OLD_TYPE_GUIDS["persistent_gvl"]

    def test_enum_guid_resolves_to_dut(self, constants):
        assert constants.kind_of(_OLD_TYPE_GUIDS["enum"]) == "dut"

    def test_application_alias(self, constants):
        assert constants.kind_of(_APPLICATION_ALT) == "application"

    def test_kind_of_accepts_kind_names_and_case(self, constants):
        assert constants.kind_of("pou") == "pou"
        assert constants.kind_of(_OLD_TYPE_GUIDS["pou"].upper()) == "pou"
        assert constants.kind_of("no-such-guid") is None

    def test_type_names_cover_aliases(self, constants):
        assert constants.TYPE_NAMES[_OLD_TYPE_GUIDS["method_alt"]] == "method"
        assert constants.TYPE_NAMES[_OLD_UPSTREAM_PERSISTENT] == "persistent_gvl"


class TestSyncDirection:
    def test_defaults_bidirectional(self, constants):
        assert constants.sync_direction_of("pou") == "bidirectional"
        assert constants.kind_allows_export("pou")
        assert constants.kind_allows_import("pou")

    def test_library_manager_export_only(self, constants):
        assert constants.sync_direction_of("library_manager") == "export_only"
        assert constants.kind_allows_export("library_manager")
        assert not constants.kind_allows_import("library_manager")

    def test_devices_disabled(self, constants):
        for kind in ("device", "device_module"):
            assert constants.sync_direction_of(kind) == "disabled"
            assert not constants.kind_allows_export(kind)
            assert not constants.kind_allows_import(kind)

    def test_unknown_guid_is_bidirectional(self, constants):
        # Never skip on missing information - the exportable check handles
        # unknown GUIDs separately.
        assert constants.sync_direction_of("ffffffff-0000-0000-0000-000000000000") \
            == "bidirectional"


class TestProfileValidation:
    def test_missing_profile_fails_loud(self, constants, tmp_path, monkeypatch):
        monkeypatch.setattr(constants, "_profile_path",
                            lambda: str(tmp_path / "nope.json"))
        with pytest.raises(ValueError, match="not found"):
            constants._load_profile()

    def test_invalid_json_fails_loud(self, constants, tmp_path, monkeypatch):
        bad = tmp_path / "default.json"
        bad.write_text("{ this is not json", encoding="utf-8")
        monkeypatch.setattr(constants, "_profile_path", lambda: str(bad))
        with pytest.raises(ValueError, match="not valid JSON"):
            constants._load_profile()

    def test_empty_alias_list_fails_loud(self, constants, tmp_path, monkeypatch):
        bad = tmp_path / "default.json"
        bad.write_text('{"guid_aliases": {"pou": []}}', encoding="utf-8")
        monkeypatch.setattr(constants, "_profile_path", lambda: str(bad))
        with pytest.raises(ValueError, match="non-empty"):
            constants._load_profile()

    def test_bad_direction_value_fails_loud(self, constants, tmp_path, monkeypatch):
        bad = tmp_path / "default.json"
        bad.write_text(
            '{"guid_aliases": {"pou": ["6f9dac99-8de1-4efc-8465-68ac443b7d08"]},'
            ' "sync_direction": {"pou": "sideways"}}',
            encoding="utf-8")
        monkeypatch.setattr(constants, "_profile_path", lambda: str(bad))
        with pytest.raises(ValueError, match="sideways"):
            constants._load_profile()


class TestClassifyNormalization:
    """classify_object must normalize alias GUIDs onto the primary GUID and
    honor profile sync direction."""

    class Node(object):
        def __init__(self, type_guid, parent=None):
            self.type = type_guid
            self.parent = parent
            self.has_textual_implementation = True

        def get_name(self):
            return "n"

    def test_method_alt_normalizes_to_method(self, constants, managers):
        obj = self.Node(_OLD_TYPE_GUIDS["method_alt"])
        eff, is_xml, skip = managers.classify_object(obj)
        assert eff == constants.TYPE_GUIDS["method"]
        assert not is_xml
        assert not skip

    def test_enum_normalizes_to_dut(self, constants, managers):
        obj = self.Node(_OLD_TYPE_GUIDS["enum"])
        eff, is_xml, skip = managers.classify_object(obj)
        assert eff == constants.TYPE_GUIDS["dut"]
        assert not skip

    def test_old_persistent_gvl_guid_classifies(self, constants, managers):
        obj = self.Node(_OLD_UPSTREAM_PERSISTENT)
        eff, is_xml, skip = managers.classify_object(obj)
        assert eff == constants.TYPE_GUIDS["persistent_gvl"]
        assert not skip

    def test_disabled_device_skips(self, constants, managers):
        obj = self.Node(_OLD_TYPE_GUIDS["device"])
        eff, is_xml, skip = managers.classify_object(obj)
        assert skip

    def test_unknown_guid_skips(self, managers):
        obj = self.Node("ffffffff-0000-0000-0000-000000000000")
        eff, is_xml, skip = managers.classify_object(obj)
        assert skip
