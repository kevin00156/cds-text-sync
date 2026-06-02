# -*- coding: utf-8 -*-
"""cds.ide — the ONLY layer allowed to touch the CODESYS API.

Keep it thin. It moves whole-project data in and out of the IDE in single
batch calls and does nothing clever. All logic lives in cds.core.
"""
