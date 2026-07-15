# -*- coding: utf-8 -*-
"""Call extraction and symbol resolution for the offline call-tree tool.

CPython 3 only (see call_tree_parse.py for why the IronPython rule does not
apply). Adapted from upstream commit f09c438; the IDE-snapshot symbol source
was removed — this fork resolves everything from the exported .st text.
"""

from __future__ import annotations

import io
import json
import os
import re

from call_tree_parse import (
    _blank_comments,
    _clean_for_calls,
    _line_number,
    detect_owner_kind,
    iter_st_files,
    parse_var_blocks,
    pou_name,
    read_text,
    split_decl_impl,
)

_CALL_PATTERN = re.compile(r"(\b[A-Za-z_]\w*)\s*\(")

_METHOD_CALL_PATTERN = re.compile(
    r"(\b[A-Za-z_]\w*)\s*\.\s*(\b[A-Za-z_]\w*)\s*\("
)

# Language keywords and elementary types that look like calls when followed
# by '(' — e.g. IF(..)..., STRING(80) — and must never be reported.
_KEYWORDS = {
    "IF", "FOR", "WHILE", "REPEAT", "CASE", "UNTIL", "ELSIF",
    "AND", "OR", "NOT", "XOR", "MOD", "DIV",
    "TRUE", "FALSE", "NULL", "THIS", "SUPER", "SELF",
    "VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_STAT", "VAR_GLOBAL",
    "END_VAR", "END_IF", "END_FOR", "END_WHILE", "END_REPEAT", "END_CASE",
    "THEN", "DO", "OF", "TO", "BY", "RETURN", "EXIT", "CONTINUE",
    "PROGRAM", "FUNCTION", "FUNCTION_BLOCK", "METHOD", "ACTION",
    "TYPE", "END_TYPE", "STRUCT", "END_STRUCT",
    "INTERFACE", "END_INTERFACE", "IMPLEMENTATION",
    "INT", "DINT", "UINT", "UDINT", "WORD", "DWORD", "BYTE", "BOOL",
    "REAL", "LREAL", "SINT", "USINT", "LINT", "ULINT",
    "TIME", "DATE", "STRING", "WSTRING", "CHAR", "ARRAY",
    "REFERENCE", "POINTER",
}

_IEC_OPERATORS = {
    "MOVE", "SEL", "MUX", "GT", "GE", "EQ", "LE", "LT", "NE",
    "AND", "OR", "XOR", "NOT", "MOD", "DIV", "MUL", "ADD", "SUB",
    "SHL", "SHR", "ROL", "ROR", "ADR", "REF", "SIZEOF",
}

_TO_CONVERSIONS = {
    "TO_INT", "TO_DINT", "TO_REAL", "TO_LREAL", "TO_BOOL",
    "TO_STRING", "TO_WSTRING", "TO_TIME", "TO_DATE",
    "TO_BYTE", "TO_WORD", "TO_DWORD",
}


def load_system_catalog(path: str | None = None) -> dict:
    """Load the system-function catalog.

    Returns a dict with keys ``functions`` and ``function_blocks``, each a
    ``set`` of uppercase names.
    """
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "sys_funcs.json")
    with io.open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {
        "functions": {n.upper() for n in data.get("functions", [])},
        "function_blocks": {n.upper() for n in data.get("function_blocks", [])},
    }


def _collect_local_symbols(decl: str) -> dict[str, str]:
    """Build a dict ``{variable_name: type_name}`` from VAR blocks."""
    symbols: dict[str, str] = {}
    for block in parse_var_blocks(decl):
        for member in block.get("members", []):
            name = member.get("name", "")
            typ = member.get("type", "")
            if name and typ:
                # Strip array dimensions like ARRAY[0..7] OF BOOL -> BOOL
                bare = re.sub(
                    r"\bARRAY\b.*?\bOF\b", "", typ, flags=re.IGNORECASE
                ).strip()
                if not bare:
                    bare = typ
                symbols[name] = bare
    return symbols


def _extract_method_calls(clean_text: str, original_text: str) -> list[dict]:
    """Find ``instance.method(...)`` patterns."""
    calls: list[dict] = []
    for m in _METHOD_CALL_PATTERN.finditer(clean_text):
        instance = m.group(1)
        method = m.group(2)
        offset = m.start()
        calls.append(
            {
                "kind": "method_call",
                "instance": instance,
                "method": method,
                "callee_raw": f"{instance}.{method}",
                "offset": offset,
                "line": _line_number(original_text, offset),
            }
        )
    return calls


def _extract_function_calls(
    clean_text: str,
    original_text: str,
    method_call_offsets: set[int],
) -> list[dict]:
    """Find bare ``identifier(...)`` patterns, filtering out method calls and
    keywords."""
    calls: list[dict] = []
    for m in _CALL_PATTERN.finditer(clean_text):
        offset = m.start()
        # Skip if offset is part of a method call (already handled)
        if offset in method_call_offsets:
            continue
        name = m.group(1).upper()
        if name in _KEYWORDS:
            continue
        # Dot-prefixed calls are extracted by _extract_method_calls, so we
        # skip them here to avoid duplicates.
        preceding = clean_text[:offset].rstrip()
        if preceding and preceding[-1] == ".":
            continue

        calls.append(
            {
                "kind": "function_call",
                "callee_raw": m.group(1),
                "offset": offset,
                "line": _line_number(original_text, offset),
            }
        )
    return calls


def _merge_calls(func_calls, method_calls):
    """Merge and sort call candidates by offset."""
    combined = func_calls + method_calls
    combined.sort(key=lambda c: c["offset"])
    return combined


def _is_implicit_type_conversion(name: str) -> bool:
    """Check if name looks like an implicit type conversion (e.g. INT_TO_BOOL)."""
    return bool(re.match(r"^[A-Z_]+_TO_[A-Z_]+$", name)) or name in _TO_CONVERSIONS


def _is_standard_iec_operator(name: str) -> bool:
    """Check if name is a standard IEC operator that uses function-call syntax."""
    return name in _IEC_OPERATORS


def _resolve_callee_kind(
    callee: str, project_symbols: dict, system_catalog: dict
) -> str:
    """Determine the kind of a resolved callee name."""
    name = callee.split(".")[-1]
    if name in project_symbols:
        return project_symbols[name].get("kind", "unknown")
    if name.upper() in system_catalog.get("function_blocks", set()):
        return "system_function_block"
    if name.upper() in system_catalog.get("functions", set()):
        return "system_function"
    return "unknown"


def _record(owner_name, file_path, call, callee, callee_kind, call_kind, **extra):
    rec = {
        "caller": owner_name,
        "callee": callee,
        "callee_kind": callee_kind,
        "call_kind": call_kind,
        "file": file_path,
        "line": call["line"],
    }
    rec.update(extra)
    return rec


def _resolve_calls(
    calls: list[dict],
    local_symbols: dict[str, str],
    project_symbols: dict[str, dict],
    system_catalog: dict,
    owner_name: str,
    file_path: str,
    global_instance_types: dict[str, str] | None = None,
    gvl_members: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Resolve each raw call candidate against known symbols.

    Returns a list of resolved call records (caller, callee, callee_kind,
    call_kind, file, line, plus instance info for method calls).
    """
    resolved: list[dict] = []
    for call in calls:
        kind = call["kind"]
        if kind == "method_call":
            instance = call["instance"]
            method = call["method"]

            # Case 1: GVL member call — GVL_Name.Instance(...) is calling an
            # FB instance via a GVL path.
            if gvl_members and instance.lower() in gvl_members:
                gvl_name_lower = instance.lower()
                if method.lower() in gvl_members[gvl_name_lower]:
                    member_type = gvl_members[gvl_name_lower][method.lower()]
                    resolved.append(_record(
                        owner_name, file_path, call, member_type,
                        _resolve_callee_kind(member_type, project_symbols, system_catalog),
                        "function_call",
                        instance=f"{instance}.{method}",
                        instance_type=member_type,
                    ))
                    continue

            # Case 2: Known instance type (local or global)
            instance_type = local_symbols.get(instance, "")
            if not instance_type and global_instance_types:
                instance_type = global_instance_types.get(instance.lower(), "")

            if instance_type:
                callee = f"{instance_type}.{method}"
                resolved.append(_record(
                    owner_name, file_path, call, callee,
                    _resolve_callee_kind(callee, project_symbols, system_catalog),
                    "fb_method_call",
                    instance=instance,
                    instance_type=instance_type,
                ))
            else:
                resolved.append(_record(
                    owner_name, file_path, call, f"?{instance}.{method}",
                    "unknown", "unresolved_method",
                    instance=instance,
                    instance_type="?",
                ))
        elif kind == "function_call":
            callee_raw = call["callee_raw"]
            callee_upper = callee_raw.upper()

            # FB instance call — bare variable name that resolves to an FB type
            if global_instance_types and callee_raw.lower() in global_instance_types:
                inst_type = global_instance_types[callee_raw.lower()]
                resolved.append(_record(
                    owner_name, file_path, call, inst_type,
                    _resolve_callee_kind(inst_type, project_symbols, system_catalog),
                    "function_call",
                ))
                continue

            if callee_raw in project_symbols:
                sym = project_symbols[callee_raw]
                resolved.append(_record(
                    owner_name, file_path, call, callee_raw,
                    sym.get("kind", "unknown"), "function_call",
                ))
            elif callee_upper in system_catalog.get("function_blocks", set()):
                resolved.append(_record(
                    owner_name, file_path, call, callee_raw,
                    "system_function_block", "system_call",
                ))
            elif callee_upper in system_catalog.get("functions", set()):
                resolved.append(_record(
                    owner_name, file_path, call, callee_raw,
                    "system_function", "system_call",
                ))
            elif _is_implicit_type_conversion(callee_upper):
                resolved.append(_record(
                    owner_name, file_path, call, callee_raw,
                    "system_function", "system_call",
                ))
            elif _is_standard_iec_operator(callee_upper):
                resolved.append(_record(
                    owner_name, file_path, call, callee_raw,
                    "system_function", "system_call",
                ))
            else:
                resolved.append(_record(
                    owner_name, file_path, call, callee_raw,
                    "unknown", "unresolved",
                ))
    return resolved


def _collect_methods(decl: str) -> dict[str, dict]:
    """Extract METHOD definitions from a declaration block.

    Returns {qualified_name: {"kind": "method", "guid": ""}} plus a simple
    entry for the bare method name.
    """
    methods: dict[str, dict] = {}
    owner = pou_name(decl, None)
    blanked = _blank_comments(decl)
    for m in re.finditer(r"(?im)^\s*METHOD\s+([A-Za-z_]\w*)", blanked):
        method_name = m.group(1)
        qualified = f"{owner}.{method_name}" if owner else method_name
        methods[qualified] = {"kind": "method", "guid": ""}
        methods[method_name] = {"kind": "method", "guid": ""}
    return methods


def _collect_project_symbols_from_st_files(project_root: str) -> dict[str, dict]:
    """Scan .st files and extract POU/FB/function names from declarations.

    Returns {name: {"kind": str, "guid": ""}}.
    """
    symbols: dict[str, dict] = {}
    for st_path in iter_st_files(project_root):
        try:
            text = read_text(st_path)
        except OSError:
            continue
        decl, _ = split_decl_impl(text)
        if not decl:
            continue
        name = pou_name(decl, None)
        if name and name not in symbols:
            kind = detect_owner_kind(decl)
            symbols[name] = {"kind": kind or "unknown", "guid": ""}
        # Also check for methods (METHOD keyword in declaration)
        method_kind = _collect_methods(decl)
        if method_kind:
            symbols.update(method_kind)
    return symbols


def _build_global_instance_types(project_root: str) -> dict[str, str]:
    """Build a global ``{variable_name: type_name}`` map from ALL ``.st`` files.

    Keys are stored in *lowercase* for case-insensitive lookup because
    CODESYS is case-insensitive.
    """
    types: dict[str, str] = {}
    for st_path in iter_st_files(project_root):
        try:
            text = read_text(st_path)
        except OSError:
            continue
        decl, _ = split_decl_impl(text)
        if not decl:
            continue
        local_types = _collect_local_symbols(decl)
        for name, typ in local_types.items():
            key = name.lower()
            if key not in types or (typ and not types[key]):
                types[key] = typ
    return types


def _build_gvl_members(project_root: str) -> dict[str, dict[str, str]]:
    """Build a ``{gvl_name: {member_name: type_name}}`` map from GVL files.

    Keys are stored in *lowercase* for case-insensitive lookup.
    """
    members: dict[str, dict[str, str]] = {}
    for st_path in iter_st_files(project_root):
        try:
            text = read_text(st_path)
        except OSError:
            continue
        decl, _ = split_decl_impl(text)
        if not decl:
            continue
        kind = detect_owner_kind(decl)
        if kind != "gvl":
            continue
        # GVL declarations carry no name; fall back to the file stem
        # (e.g. LogComponent.st -> LogComponent).
        gvl_name = pou_name(decl, None)
        if not gvl_name:
            gvl_name = os.path.splitext(os.path.basename(st_path))[0]
        local_types = _collect_local_symbols(decl)
        if local_types:
            members[gvl_name.lower()] = {k.lower(): v for k, v in local_types.items()}
    return members


def _process_st_file(
    st_path: str,
    project_root: str,
    project_symbols: dict[str, dict],
    system_catalog: dict,
    global_instance_types: dict[str, str] | None = None,
    gvl_members: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Process a single .st file and return its resolved call records."""
    try:
        text = read_text(st_path)
    except OSError:
        return []

    decl, impl = split_decl_impl(text)
    if not impl:
        # No implementation section - nothing to analyze for calls
        return []

    # Owner info. Method files export as Parent.Method.st with a METHOD
    # header pou_name() cannot parse — the file stem gives the qualified name.
    stem = os.path.splitext(os.path.basename(st_path))[0]
    owner_name = pou_name(decl, stem)
    local_symbols = _collect_local_symbols(decl)

    rel_path = os.path.relpath(st_path, project_root)
    clean_impl = _clean_for_calls(impl)

    method_calls = _extract_method_calls(clean_impl, impl)
    method_offsets = {c["offset"] for c in method_calls}
    func_calls = _extract_function_calls(clean_impl, impl, method_offsets)

    all_calls = _merge_calls(func_calls, method_calls)

    return _resolve_calls(
        all_calls,
        local_symbols,
        project_symbols,
        system_catalog,
        owner_name,
        rel_path,
        global_instance_types=global_instance_types,
        gvl_members=gvl_members,
    )
