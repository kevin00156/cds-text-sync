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
        declaration  declaration text (None if not applicable)
        implementation  implementation text (None if not applicable)
        xml          raw native XML for non-textual objects (None otherwise)
    """

    def __init__(self, guid, name, type_guid, path):
        self.guid = guid
        self.name = name
        self.type_guid = type_guid
        self.path = path or []
        self.declaration = None
        self.implementation = None
        self.xml = None


def parse(snapshot_xml_path):
    """Parse a native snapshot.xml into a list of ProjectObject.

    Pure: reads a file, returns objects. No IDE. Uses xml.etree (available in
    both CPython 3 and IronPython 2.7).
    """
    # TODO(stage 1): walk the native XML, build ProjectObject per object.
    raise NotImplementedError("cds.core.model.parse")
