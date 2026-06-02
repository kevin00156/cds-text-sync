# -*- coding: utf-8 -*-
"""cds.app — thin orchestration. Wires cds.ide and cds.core together.

Each function here reads top-to-bottom like the data-flow diagrams in
docs/REWORK_PLAN.md §4. If one of these grows logic of its own, that logic
belongs in core (if pure) or ide (if it touches CODESYS) — not here.
"""
