# -*- coding: utf-8 -*-
"""cds.core — pure Python. NO CODESYS imports, ever (PRINCIPLES.md §4).

Everything here takes file paths / data in and returns data out, so it runs
in CI under CPython 3 and is fully unit-tested. Must also run under
IronPython 2.7: no type annotations, no f-strings, stdlib only.
"""
