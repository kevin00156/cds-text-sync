# -*- coding: utf-8 -*-
"""Shared test helpers: loader for the legacy .pyw engine modules."""
import importlib.util
import os
import sys
from importlib.machinery import SourceFileLoader

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_legacy(module_name):
    """Load a legacy .pyw module under CPython by file path (.pyw isn't
    importable by name). They guard CODESYS access inside functions, so module
    load is clean.

    .pyw is only in importlib's SOURCE_SUFFIXES on Windows, so an explicit
    loader is required for spec_from_file_location to work on Linux CI.
    """
    path = os.path.join(REPO_ROOT, module_name + ".pyw")
    loader = SourceFileLoader(module_name, path)
    spec = importlib.util.spec_from_file_location(module_name, path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def legacy_loader():
    """Session-wide access to load_legacy for test modules."""
    return load_legacy
