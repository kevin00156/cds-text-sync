# -*- coding: utf-8 -*-
"""In-memory project model + parsing the native snapshot into it.

ProjectObject is the single currency the whole core passes around. It is
deliberately dumb: data, no behavior.
"""
from __future__ import print_function


class ProjectObject(object):
    """One CODESYS object (POU, GVL, DUT, folder, device, ...).

    Attributes (all plain data):
        guid         native object guid, or None for disk-only new objects
        name         object name
        type_guid    CODESYS type guid (see cds.types)
        path         folder path as a list of names, e.g. ["App", "Logic"]
        parent_name  owning POU/interface name for nested children
                     (action/method/property), else None
        declaration  declaration text (None if not applicable)
        implementation  implementation text (None if not applicable)
        get_impl     property GET accessor text (decl + impl), else None
        set_impl     property SET accessor text (decl + impl), else None
        xml          raw native XML for non-textual objects (None otherwise)
    """

    def __init__(self, guid, name, type_guid, path):
        self.guid = guid
        self.name = name
        self.type_guid = type_guid
        self.path = path or []
        self.parent_name = None
        self.declaration = None
        self.implementation = None
        self.get_impl = None
        self.set_impl = None
        self.xml = None

    def __repr__(self):
        return "ProjectObject(%r, type=%r, path=%r)" % (
            self.name, self.type_guid, "/".join(self.path))


def parse(snapshot_xml_path):
    """Parse a native snapshot.xml into a list of ProjectObject.

    Pure: reads a file, returns objects. No IDE. Uses xml.etree (available in
    both CPython 3 and IronPython 2.7).

    SEAM (blocked): the exact element structure of a full-project
    export_native dump is CODESYS-version-specific and cannot be authored
    blind. Implement against a real sample snapshot.xml committed to
    fixtures/ (see docs/REWORK_PLAN.md stage 1). Until then this raises so it
    fails loud (PRINCIPLES.md §6) rather than returning wrong data.
    """
    raise NotImplementedError(
        "cds.core.model.parse: needs a real export_native snapshot sample "
        "to implement correctly (see fixtures/ and docs/REWORK_PLAN.md).")
