# -*- coding: utf-8 -*-
"""Unit tests for the offline call-tree tool (tools/call_tree*.py).

Uses synthetic .st snippets in this fork's export format (declaration,
`// === IMPLEMENTATION ===` marker, implementation). Adapted from upstream
tests/unit/test_call_tree.py (commit f09c438).
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "tools"))

# ---------------------------------------------------------------------------
# Helpers - synthetic ST text builders
# ---------------------------------------------------------------------------


def _st_text(declaration, implementation):
    """Build a .st file in this fork's export format."""
    parts = [declaration]
    parts.append("")
    parts.append("// === IMPLEMENTATION ===")
    parts.append("")
    parts.append(implementation)
    return "\n".join(parts)


# A minimal PROGRAM declaration.
_PROGRAM_DECL = """PROGRAM MAIN
VAR
    conveyor : FB_Conveyor;
    timer : TON;
    x : INT;
END_VAR
"""

# A minimal function block declaration.
_FB_DECL = """FUNCTION_BLOCK FB_Conveyor
VAR_INPUT
    speed : INT;
END_VAR
VAR
    running : BOOL;
END_VAR
"""

# A minimal function declaration.
_FUNC_DECL = """FUNCTION F_Calculate : INT
VAR_INPUT
    a : INT;
    b : INT;
END_VAR
VAR
    result : INT;
END_VAR
"""

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def system_catalog():
    """Return a minimal system catalog dict (matching sys_funcs.json subset)."""
    return {
        "functions": {"ABS", "SQRT", "SEL", "MAX", "MIN", "GT", "EQ", "SIN", "COS"},
        "function_blocks": {"TON", "TOF", "TP", "R_TRIG", "F_TRIG"},
    }


@pytest.fixture
def project_symbols():
    """Return a minimal set of project-defined symbols."""
    return {
        "MAIN": {"kind": "program", "guid": "guid-main"},
        "FB_Conveyor": {"kind": "function_block", "guid": "guid-fb-conveyor"},
        "F_Calculate": {"kind": "function", "guid": "guid-f-calculate"},
    }


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------


class TestBlankComments:
    """Tests for _blank_comments (comment stripping)."""

    def test_line_comment(self):
        from call_tree import _blank_comments

        result = _blank_comments("x := 1; // this is a comment\ny := 2;")
        assert "//" not in result
        assert "x := 1;" in result
        assert "y := 2;" in result

    def test_block_comment(self):
        from call_tree import _blank_comments

        result = _blank_comments("x := (* block *) 1;")
        assert "(*" not in result
        assert "*)" not in result
        assert "x := " in result
        assert "1;" in result

    def test_pragma(self):
        from call_tree import _blank_comments

        result = _blank_comments('x := {some pragma "text"}1;')
        assert "{" not in result
        assert "}" not in result
        assert "x := " in result
        assert "1;" in result

    def test_string_literals_preserved(self):
        from call_tree import _blank_comments

        result = _blank_comments("s := 'hello // not a comment';")
        assert "'hello // not a comment'" in result


class TestLoadSystemCatalog:
    """Tests for load_system_catalog."""

    def test_load_default(self):
        """Can load the shipped sys_funcs.json."""
        from call_tree import load_system_catalog

        catalog = load_system_catalog()
        assert "ABS" in catalog["functions"]
        assert "TON" in catalog["function_blocks"]
        assert "SIN" in catalog["functions"]

    def test_load_from_custom_path(self):
        """Load from a custom JSON file."""
        from call_tree import load_system_catalog

        data = {
            "functions": ["CUSTOM_FUNC"],
            "function_blocks": ["CUSTOM_FB"],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f)
            f.flush()
            path = f.name
        try:
            catalog = load_system_catalog(path)
            assert "CUSTOM_FUNC" in catalog["functions"]
            assert "CUSTOM_FB" in catalog["function_blocks"]
        finally:
            os.unlink(path)


class TestCollectLocalSymbols:
    """Tests for _collect_local_symbols."""

    def test_var_block(self):
        from call_tree import _collect_local_symbols

        decl = """PROGRAM MAIN
VAR
    conveyor : FB_Conveyor;
    timer : TON;
    x : INT;
END_VAR
"""
        symbols = _collect_local_symbols(decl)
        assert symbols["conveyor"] == "FB_Conveyor"
        assert symbols["timer"] == "TON"
        assert symbols["x"] == "INT"

    def test_var_input_block(self):
        from call_tree import _collect_local_symbols

        decl = """FUNCTION F_Calc : INT
VAR_INPUT
    a : INT;
    b : INT;
END_VAR
"""
        symbols = _collect_local_symbols(decl)
        assert symbols["a"] == "INT"
        assert symbols["b"] == "INT"

    def test_empty_decl(self):
        from call_tree import _collect_local_symbols

        assert _collect_local_symbols("") == {}

    def test_no_var_blocks(self):
        from call_tree import _collect_local_symbols

        assert _collect_local_symbols("PROGRAM MAIN\nx := 1;") == {}


# ---------------------------------------------------------------------------
# Call extraction tests
# ---------------------------------------------------------------------------


class TestExtractFunctionCalls:
    """Tests for _extract_function_calls."""

    def test_simple_function_call(self):
        from call_tree import _clean_for_calls, _extract_function_calls

        impl = "result := F_Calculate(a := 10, b := 20);"
        clean = _clean_for_calls(impl)
        calls = _extract_function_calls(clean, impl, set())
        assert len(calls) == 1
        assert calls[0]["callee_raw"] == "F_Calculate"
        assert calls[0]["kind"] == "function_call"

    def test_keyword_not_extracted(self):
        from call_tree import _clean_for_calls, _extract_function_calls

        impl = """IF x > 0 THEN
    y := 1;
END_IF"""
        clean = _clean_for_calls(impl)
        calls = _extract_function_calls(clean, impl, set())
        assert len(calls) == 0

    def test_multiple_calls(self):
        from call_tree import _clean_for_calls, _extract_function_calls

        impl = "a := ABS(x); b := SQRT(y);"
        clean = _clean_for_calls(impl)
        calls = _extract_function_calls(clean, impl, set())
        assert len(calls) == 2
        names = {c["callee_raw"] for c in calls}
        assert names == {"ABS", "SQRT"}

    def test_call_in_expression(self):
        from call_tree import _clean_for_calls, _extract_function_calls

        impl = "x := MAX(a, b) + MIN(c, d);"
        clean = _clean_for_calls(impl)
        calls = _extract_function_calls(clean, impl, set())
        assert len(calls) == 2
        names = {c["callee_raw"] for c in calls}
        assert names == {"MAX", "MIN"}


class TestExtractMethodCalls:
    """Tests for _extract_method_calls."""

    def test_fb_method_call(self):
        from call_tree import _clean_for_calls, _extract_method_calls

        impl = "conveyor.Run(speed := 10);"
        clean = _clean_for_calls(impl)
        calls = _extract_method_calls(clean, impl)
        assert len(calls) == 1
        assert calls[0]["instance"] == "conveyor"
        assert calls[0]["method"] == "Run"
        assert calls[0]["kind"] == "method_call"

    def test_this_method_call(self):
        from call_tree import _clean_for_calls, _extract_method_calls

        impl = "THIS.DoWork(x := 1);"
        clean = _clean_for_calls(impl)
        calls = _extract_method_calls(clean, impl)
        assert len(calls) == 1
        assert calls[0]["instance"] == "THIS"
        assert calls[0]["method"] == "DoWork"


# ---------------------------------------------------------------------------
# Resolution tests
# ---------------------------------------------------------------------------


class TestResolveCalls:
    """Tests for _resolve_calls."""

    def test_resolve_internal_function_call(self, project_symbols, system_catalog):
        from call_tree import _resolve_calls

        calls = [
            {"kind": "function_call", "callee_raw": "F_Calculate", "line": 5},
        ]
        resolved = _resolve_calls(
            calls, {}, project_symbols, system_catalog, "MAIN", "MAIN.st"
        )
        assert len(resolved) == 1
        assert resolved[0]["callee"] == "F_Calculate"
        assert resolved[0]["call_kind"] == "function_call"
        assert resolved[0]["callee_kind"] == "function"

    def test_resolve_system_call(self, project_symbols, system_catalog):
        from call_tree import _resolve_calls

        calls = [
            {"kind": "function_call", "callee_raw": "ABS", "line": 10},
        ]
        resolved = _resolve_calls(
            calls, {}, project_symbols, system_catalog, "MAIN", "MAIN.st"
        )
        assert len(resolved) == 1
        assert resolved[0]["callee"] == "ABS"
        assert resolved[0]["call_kind"] == "system_call"
        assert resolved[0]["callee_kind"] == "system_function"

    def test_resolve_system_fb_call(self, project_symbols, system_catalog):
        from call_tree import _resolve_calls

        calls = [
            {"kind": "function_call", "callee_raw": "TON", "line": 15},
        ]
        resolved = _resolve_calls(
            calls, {}, project_symbols, system_catalog, "MAIN", "MAIN.st"
        )
        assert len(resolved) == 1
        assert resolved[0]["callee"] == "TON"
        assert resolved[0]["call_kind"] == "system_call"
        assert resolved[0]["callee_kind"] == "system_function_block"

    def test_resolve_method_call(self, project_symbols, system_catalog):
        from call_tree import _resolve_calls

        calls = [
            {
                "kind": "method_call",
                "instance": "conveyor",
                "method": "Run",
                "callee_raw": "conveyor.Run",
                "line": 20,
            },
        ]
        local_symbols = {"conveyor": "FB_Conveyor"}
        resolved = _resolve_calls(
            calls, local_symbols, project_symbols, system_catalog, "MAIN", "MAIN.st"
        )
        assert len(resolved) == 1
        assert resolved[0]["callee"] == "FB_Conveyor.Run"
        assert resolved[0]["call_kind"] == "fb_method_call"
        assert resolved[0]["instance"] == "conveyor"
        assert resolved[0]["instance_type"] == "FB_Conveyor"

    def test_resolve_unresolved(self, project_symbols, system_catalog):
        from call_tree import _resolve_calls

        calls = [
            {"kind": "function_call", "callee_raw": "UnknownFunc", "line": 25},
        ]
        resolved = _resolve_calls(
            calls, {}, project_symbols, system_catalog, "MAIN", "MAIN.st"
        )
        assert len(resolved) == 1
        assert resolved[0]["call_kind"] == "unresolved"
        assert resolved[0]["callee_kind"] == "unknown"


# ---------------------------------------------------------------------------
# Integration test with synthetic .st files
# ---------------------------------------------------------------------------


class TestBuildCallTree:
    """Integration tests using a temporary directory of .st files."""

    def test_empty_directory(self):
        """An empty directory produces a valid empty report."""
        from call_tree import build_call_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            result = build_call_tree(tmpdir)
            assert result["meta"]["source_count"] == 0
            assert result["calls"] == []
            assert result["symbols"] == {}

    def test_single_program_with_function_calls(self, system_catalog):
        """A single .st file with a PROGRAM calling a function."""
        from call_tree import build_call_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a function file
            func_st = _st_text(
                "FUNCTION F_Calculate : INT\nVAR_INPUT a : INT; b : INT; END_VAR\n",
                "F_Calculate := a + b;",
            )
            with open(os.path.join(tmpdir, "F_Calculate.st"), "w") as f:
                f.write(func_st)

            # Create the main program file
            main_st = _st_text(
                _PROGRAM_DECL,
                "result := F_Calculate(a := 10, b := 20);\nIF result > 0 THEN\n"
                "  x := ABS(result);\nEND_IF",
            )
            with open(os.path.join(tmpdir, "MAIN.st"), "w") as f:
                f.write(main_st)

            result = build_call_tree(tmpdir)
            assert result["meta"]["source_count"] == 2

            # Check calls
            callers = {c["caller"] for c in result["calls"]}
            assert "MAIN" in callers

            main_calls = [c for c in result["calls"] if c["caller"] == "MAIN"]
            callees = {c["callee"] for c in main_calls}
            assert "F_Calculate" in callees
            assert "ABS" in callees

            # Check symbols
            assert "MAIN" in result["symbols"]
            assert "F_Calculate" in result["symbols"]

    def test_method_call_via_instance(self, system_catalog):
        """An FB .st file with a method call via instance variable."""
        from call_tree import build_call_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create the FB file
            fb_st = _st_text(
                _FB_DECL,
                "running := TRUE;\n",
            )
            with open(os.path.join(tmpdir, "FB_Conveyor.st"), "w") as f:
                f.write(fb_st)

            # Create MAIN that calls conveyor.Run()
            main_st = _st_text(
                _PROGRAM_DECL,
                "conveyor.Run(speed := 50);\n",
            )
            with open(os.path.join(tmpdir, "MAIN.st"), "w") as f:
                f.write(main_st)

            result = build_call_tree(tmpdir)
            main_calls = [c for c in result["calls"] if c["caller"] == "MAIN"]

            method_calls = [c for c in main_calls if c["call_kind"] == "fb_method_call"]
            assert len(method_calls) >= 1
            mc = method_calls[0]
            assert mc["instance"] == "conveyor"
            assert mc["instance_type"] == "FB_Conveyor"
            assert mc["callee"] == "FB_Conveyor.Run"

    def test_system_calls(self, system_catalog):
        """System functions like ABS, SQRT are properly tagged."""
        from call_tree import build_call_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            main_st = _st_text(
                _PROGRAM_DECL,
                "x := ABS(-10);\ny := SQRT(25);\n",
            )
            with open(os.path.join(tmpdir, "MAIN.st"), "w") as f:
                f.write(main_st)

            result = build_call_tree(tmpdir)
            main_calls = [c for c in result["calls"] if c["caller"] == "MAIN"]
            system_calls = [c for c in main_calls if c["call_kind"] == "system_call"]
            assert len(system_calls) == 2
            callees = {c["callee"] for c in system_calls}
            assert "ABS" in callees
            assert "SQRT" in callees

    def test_unresolved_call(self, system_catalog):
        """An unknown function reference is tagged as unresolved."""
        from call_tree import build_call_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            main_st = _st_text(
                _PROGRAM_DECL,
                "x := UnknownFunction(param := 1);\n",
            )
            with open(os.path.join(tmpdir, "MAIN.st"), "w") as f:
                f.write(main_st)

            result = build_call_tree(tmpdir)
            main_calls = [c for c in result["calls"] if c["caller"] == "MAIN"]
            unresolved = [c for c in main_calls if c["call_kind"] == "unresolved"]
            assert len(unresolved) >= 1
            assert unresolved[0]["callee"] == "UnknownFunction"

    def test_chained_nested_expressions(self, system_catalog):
        """Calls inside nested expressions are detected."""
        from call_tree import build_call_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            main_st = _st_text(
                _PROGRAM_DECL,
                "x := MAX(ABS(a), SQRT(b)) + MIN(c, d);\n",
            )
            with open(os.path.join(tmpdir, "MAIN.st"), "w") as f:
                f.write(main_st)

            result = build_call_tree(tmpdir)
            main_calls = [c for c in result["calls"] if c["caller"] == "MAIN"]
            callees = {c["callee"] for c in main_calls}
            assert "ABS" in callees
            assert "SQRT" in callees
            assert "MAX" in callees
            assert "MIN" in callees

    def test_pragma_headers_produce_no_phantom_calls(self):
        """Sync pragma headers (//% cds-text-sync.*) and block-comment pragmas
        never show up as calls or break decl parsing."""
        from call_tree import build_call_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            main_st = "\n".join([
                "//% cds-text-sync.kind=persistent_gvl",
                "//% cds-text-sync.exclude_from_build=true",
                "(* cds-text-sync: TypeGuid=\"{261bd6e6-249c-4232-bb6f-84c2fbeef430}\" *)",
                _st_text(_PROGRAM_DECL, "x := ABS(-1);"),
            ])
            with open(os.path.join(tmpdir, "MAIN.st"), "w") as f:
                f.write(main_st)

            result = build_call_tree(tmpdir)
            callees = {c["callee"] for c in result["calls"]}
            assert callees == {"ABS"}
            assert result["symbols"]["MAIN"]["kind"] == "program"


# ---------------------------------------------------------------------------
# Subtree filtering / rendering
# ---------------------------------------------------------------------------


class TestFilterSubtree:
    """Tests for filter_subtree and render_tree."""

    _CALLS = [
        {"caller": "MAIN", "callee": "FB_Motor.Start", "callee_kind": "unknown",
         "call_kind": "fb_method_call", "file": "MAIN.st", "line": 3},
        {"caller": "FB_Motor.Start", "callee": "LOG_Write", "callee_kind": "function",
         "call_kind": "function_call", "file": "FB_Motor.Start.st", "line": 5},
        {"caller": "Unrelated", "callee": "ABS", "callee_kind": "system_function",
         "call_kind": "system_call", "file": "Unrelated.st", "line": 1},
    ]

    def test_filter_reaches_transitive_callees(self):
        from call_tree import filter_subtree

        subtree = filter_subtree(self._CALLS, "MAIN")
        callees = {c["callee"] for c in subtree}
        assert callees == {"FB_Motor.Start", "LOG_Write"}

    def test_filter_is_case_insensitive(self):
        from call_tree import filter_subtree

        subtree = filter_subtree(self._CALLS, "main")
        assert len(subtree) == 2

    def test_filter_excludes_unreachable(self):
        from call_tree import filter_subtree

        subtree = filter_subtree(self._CALLS, "MAIN")
        callers = {c["caller"] for c in subtree}
        assert "Unrelated" not in callers

    def test_render_tree_handles_recursion(self):
        from call_tree import render_tree

        calls = [
            {"caller": "A", "callee": "B", "callee_kind": "function",
             "call_kind": "function_call", "file": "A.st", "line": 1},
            {"caller": "B", "callee": "A", "callee_kind": "program",
             "call_kind": "function_call", "file": "B.st", "line": 1},
        ]
        text = render_tree(calls, "A")
        assert "(recursion)" in text
        assert text.splitlines()[0] == "A"


class TestWriteCallTree:
    """Tests for write_call_tree."""

    def test_writes_valid_json(self):
        from call_tree import write_call_tree

        data = {
            "meta": {"source_count": 0, "generated": "now"},
            "calls": [],
            "symbols": {},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            path = f.name
        try:
            write_call_tree(data, path)
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded["meta"]["source_count"] == 0
        finally:
            os.unlink(path)


class TestProcessStFile:
    """Tests for _process_st_file."""

    def test_no_implementation_returns_empty(self):
        """A .st file with no implementation section returns no calls."""
        from call_tree import _process_st_file

        with tempfile.TemporaryDirectory() as tmpdir:
            st_path = os.path.join(tmpdir, "empty.st")
            with open(st_path, "w") as f:
                f.write("PROGRAM Empty\nVAR\nEND_VAR")

            calls = _process_st_file(
                st_path, tmpdir, {}, {"functions": set(), "function_blocks": set()}
            )
            assert calls == []

    def test_file_with_only_declaration(self):
        """A .st file with only a declaration returns no calls."""
        from call_tree import _process_st_file

        with tempfile.TemporaryDirectory() as tmpdir:
            st_path = os.path.join(tmpdir, "dut.st")
            with open(st_path, "w") as f:
                f.write("TYPE MyStruct : STRUCT\n  x : INT;\nEND_STRUCT\nEND_TYPE")

            calls = _process_st_file(
                st_path, tmpdir, {}, {"functions": set(), "function_blocks": set()}
            )
            assert calls == []

    def test_method_file_owner_is_file_stem(self):
        """A Parent.Method.st file (METHOD header) gets its qualified owner
        name from the file stem."""
        from call_tree import _process_st_file

        with tempfile.TemporaryDirectory() as tmpdir:
            st_path = os.path.join(tmpdir, "FB_Motor.Start.st")
            with open(st_path, "w") as f:
                f.write(_st_text(
                    "METHOD Start : BOOL\nVAR_INPUT\nEND_VAR",
                    "x := ABS(-1);",
                ))

            calls = _process_st_file(
                st_path, tmpdir, {},
                {"functions": {"ABS"}, "function_blocks": set()},
            )
            assert len(calls) == 1
            assert calls[0]["caller"] == "FB_Motor.Start"


class TestCollectProjectSymbolsFromStFiles:
    """Tests for _collect_project_symbols_from_st_files."""

    def test_detects_pou(self):
        from call_tree import _collect_project_symbols_from_st_files

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "MAIN.st"), "w") as f:
                f.write(_st_text(_PROGRAM_DECL, "x := 1;"))

            symbols = _collect_project_symbols_from_st_files(tmpdir)
            assert "MAIN" in symbols
            assert symbols["MAIN"]["kind"] == "program"

    def test_detects_function(self):
        from call_tree import _collect_project_symbols_from_st_files

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "F_Calculate.st"), "w") as f:
                f.write(_st_text(_FUNC_DECL, ""))

            symbols = _collect_project_symbols_from_st_files(tmpdir)
            assert "F_Calculate" in symbols
            assert symbols["F_Calculate"]["kind"] == "function"

    def test_detects_function_block(self):
        from call_tree import _collect_project_symbols_from_st_files

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "FB_Conveyor.st"), "w") as f:
                f.write(_st_text(_FB_DECL, ""))

            symbols = _collect_project_symbols_from_st_files(tmpdir)
            assert "FB_Conveyor" in symbols
            assert symbols["FB_Conveyor"]["kind"] == "function_block"
