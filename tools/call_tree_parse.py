# -*- coding: utf-8 -*-
"""ST text layer for the offline call-tree tool: file iteration, comment
blanking, decl/impl splitting, and VAR-block parsing.

CPython 3 only. This tool runs OUTSIDE the CODESYS IDE (plain `python` on an
exported sync directory), so the IronPython 2.7 compatibility rule
(PRINCIPLES.md #8) does not apply here.

Adapted from upstream ArthurkaX/cds-text-sync `cli/external_engine/`
(call_tree.py + the vendored parts of variable_map.py), commit f09c438,
retargeted at this fork's .st export format.
"""

from __future__ import annotations

import io
import os
import re

# Must match IMPL_MARKER in codesys_constants.pyw — the separator this fork's
# exporter writes between declaration and implementation in every .st file.
IMPL_MARKER = "// === IMPLEMENTATION ==="

_VAR_OPENERS = [
    "VAR_GLOBAL", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT",
    "VAR_TEMP", "VAR_STAT", "VAR_EXTERNAL", "VAR_CONFIG",
    "VAR_INST", "VAR",
]


def iter_st_files(root):
    """Yield absolute paths of every .st file under root."""
    for dirpath, _dirs, names in os.walk(root):
        for nm in names:
            if nm.lower().endswith(".st"):
                yield os.path.join(dirpath, nm)


def read_text(path: str) -> str:
    """Read a text file with lenient encoding."""
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def split_decl_impl(text):
    """Split a .st blob into (declaration, implementation).

    Splits on this fork's exporter marker (IMPL_MARKER). Returns
    (decl, None) when no implementation marker is found.
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    marker = "\n" + IMPL_MARKER + "\n"
    if marker in normalized:
        decl, impl = normalized.split(marker, 1)
        return decl, impl
    if IMPL_MARKER in normalized:
        decl, impl = normalized.split(IMPL_MARKER, 1)
        return decl, impl
    return normalized, None


def _blank_comments(text: str) -> str:
    """Replace comments and pragmas with spaces, preserving line numbers.

    Handles line comments (//), block comments (* ... *), and pragmas
    ({...}, nesting-aware). String literals are preserved so a // or (*
    inside a string is not treated as a comment.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        # String literal
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            while i < n:
                d = text[i]
                out.append(d)
                if d == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        out.append(text[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        # Line comment //
        if c == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        # Block comment (* ... *)
        if c == "(" and nxt == "*":
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == ")"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append("  ")
                i += 2
            continue
        # Pragmas { ... }
        if c == "{":
            depth = 1
            out.append(" ")
            i += 1
            while i < n and depth > 0:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _trim_string_literals(text: str) -> str:
    """Replace string-literal contents with spaces to reduce false matches."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            while i < n:
                d = text[i]
                if d == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        out.append(" ")
                        i += 2
                        continue
                    out.append(c)
                    i += 1
                    break
                out.append(" ")
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _clean_for_calls(text: str) -> str:
    """Prepare implementation text for call extraction.

    1. Blank comments (preserving line numbers).
    2. Blank string-literal contents (preserving delimiters and line numbers).
    """
    return _trim_string_literals(_blank_comments(text))


def _line_number(text: str, offset: int) -> int:
    """Return 1-based line number for *offset* in *text*."""
    return text[:offset].count("\n") + 1


def pou_name(decl, default):
    """Extract the POU name from a PROGRAM/FUNCTION_BLOCK/FUNCTION header."""
    blanked = _blank_comments(decl or "")
    m = re.search(
        r"(?im)^\s*(?:PROGRAM|FUNCTION_BLOCK|FUNCTION)\s+([A-Za-z_]\w*)",
        blanked)
    return m.group(1) if m else default


def detect_owner_kind(decl):
    """Classify a declaration blob by its leading keyword."""
    blanked = _blank_comments(decl or "")
    for raw in blanked.split("\n"):
        line = raw.strip()
        if not line:
            continue
        word = line.split()[0].upper()
        if word in ("PROGRAM",):
            return "program"
        if word in ("FUNCTION_BLOCK",):
            return "function_block"
        if word in ("FUNCTION", "METHOD"):
            return "function"
        if word == "TYPE":
            return "dut"
        if word.startswith("VAR_GLOBAL") or word == "VAR_GLOBAL":
            return "gvl"
        # An attribute-only first line was already blanked; keep scanning.
    return None


def _split_statements(body):
    """Yield (statement_text, offset_in_body) split on top-level ';'.

    Respects (), [], and string literals so initializers spanning lines or
    containing ';' are kept whole.
    """
    stmts = []
    depth = 0
    start = 0
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == "'" or c == '"':
            quote = c
            i += 1
            while i < n:
                if body[i] == quote:
                    if i + 1 < n and body[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if c in "([":
            depth += 1
        elif c in ")]":
            if depth > 0:
                depth -= 1
        elif c == ";" and depth == 0:
            stmts.append((body[start:i], start))
            start = i + 1
        i += 1
    tail = body[start:]
    if tail.strip():
        stmts.append((tail, start))
    return stmts


def _split_top_level(text, sep):
    """Find the first top-level occurrence of sep (':' or ':=').

    Returns index or -1. Respects brackets and strings.
    """
    depth = 0
    i = 0
    n = len(text)
    slen = len(sep)
    while i < n:
        c = text[i]
        if c == "'" or c == '"':
            quote = c
            i += 1
            while i < n:
                if text[i] == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if c in "([":
            depth += 1
        elif c in ")]":
            if depth > 0:
                depth -= 1
        elif depth == 0 and text[i:i + slen] == sep:
            # For ':' make sure it is not ':='
            if sep == ":" and text[i:i + 2] == ":=":
                i += 2
                continue
            return i
        i += 1
    return -1


def _parse_member_statement(stmt):
    """Parse 'name [AT %...] : type [:= init]' -> (names, type, initial) or None."""
    colon = _split_top_level(stmt, ":")
    if colon < 0:
        return None
    left = stmt[:colon].strip()
    right = stmt[colon + 1:].strip()
    if not left or not right:
        return None
    # Left side: may be "a, b, c" (multi-decl) and may contain "AT %MW0".
    at_idx = re.search(r"(?i)\bAT\b", left)
    if at_idx:
        left = left[:at_idx.start()].strip()
    names = [p.strip() for p in left.split(",") if p.strip()]
    if not names:
        return None
    # Reject if a name is not an identifier (guards against parsing garbage).
    for nm in names:
        if not re.match(r"^[A-Za-z_]\w*$", nm):
            return None
    # Right side: split type and initializer.
    assign = _split_top_level(right, ":=")
    if assign >= 0:
        typ = right[:assign].strip()
        init = right[assign + 2:].strip()
    else:
        typ = right.strip()
        init = ""
    typ = re.sub(r"\s+", " ", typ)
    return (names, typ, init)


def parse_var_blocks(decl):
    """Parse all VAR_* blocks. Returns [ {scope, members} ].

    member = {name, type, scope, line, initial}
    """
    blanked = _blank_comments(decl or "")
    blocks = []
    # Iterate lines to find block boundaries, then parse bodies by absolute
    # offset so line numbers stay accurate.
    lines = blanked.split("\n")
    line_starts = []
    pos = 0
    for ln in lines:
        line_starts.append(pos)
        pos += len(ln) + 1

    i = 0
    nlines = len(lines)
    while i < nlines:
        stripped = lines[i].strip()
        first = stripped.split()[0].upper() if stripped else ""
        opener = None
        if first in _VAR_OPENERS:
            opener = first
        if opener is None:
            i += 1
            continue
        scope = opener
        # Body starts right after this opener line.
        body_start = line_starts[i] + len(lines[i]) + 1
        # Find END_VAR.
        j = i + 1
        while j < nlines and lines[j].strip().upper() != "END_VAR" \
                and not lines[j].strip().upper().startswith("END_VAR"):
            j += 1
        body_end = line_starts[j] if j < nlines else len(blanked)
        body = blanked[body_start:body_end]
        members = []
        for stmt, off in _split_statements(body):
            parsed = _parse_member_statement(stmt)
            if not parsed:
                continue
            names, typ, init = parsed
            abs_off = body_start + off
            # Skip leading whitespace to point at the name.
            lead = len(stmt) - len(stmt.lstrip())
            line_no = blanked[:abs_off + lead].count("\n") + 1
            for nm in names:
                members.append({
                    "name": nm,
                    "type": typ,
                    "scope": scope,
                    "line": line_no,
                    "initial": init,
                })
        blocks.append({"scope": scope, "members": members})
        i = j + 1
    return blocks
