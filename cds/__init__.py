# -*- coding: utf-8 -*-
"""cds — CODESYS text sync, reworked.

Layering (see PRINCIPLES.md and docs/REWORK_PLAN.md):
    cds.ide   -> only layer allowed to touch CODESYS API (IronPython 2.7)
    cds.core  -> pure Python, no CODESYS imports, unit-tested in CI
    cds.app   -> thin orchestration wiring ide + core together
"""
VERSION = "k1.0.1"
