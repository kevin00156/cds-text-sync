# -*- coding: utf-8 -*-
"""Offline static call-tree builder for this fork's exported .st projections.

Builds a JSON call graph (and optionally renders a text subtree) from a sync
directory, without touching the CODESYS IDE. CPython 3 only.

Usage:
    python tools/call_tree.py <sync-dir> [root-pou] [-o out.json]
                              [--sys-funcs path] [--max-depth N]

Adapted from upstream ArthurkaX/cds-text-sync commit f09c438
(cli/external_engine/call_tree.py), minus the IDE-snapshot symbol source.
"""

from __future__ import annotations

import argparse
import io
import json
import time

# Re-exported so tests (and callers) can treat call_tree as the single
# public surface of the tool.
from call_tree_parse import (  # noqa: F401
    IMPL_MARKER,
    _blank_comments,
    _clean_for_calls,
    iter_st_files,
    pou_name,
    split_decl_impl,
)
from call_tree_resolve import (  # noqa: F401
    _build_global_instance_types,
    _build_gvl_members,
    _collect_local_symbols,
    _collect_project_symbols_from_st_files,
    _extract_function_calls,
    _extract_method_calls,
    _process_st_file,
    _resolve_calls,
    load_system_catalog,
)


def build_call_tree(
    project_root: str,
    system_catalog_path: str | None = None,
) -> dict:
    """Build a call tree from an exported sync directory.

    Returns a dict with ``meta`` (source counts), ``calls`` (resolved call
    records) and ``symbols`` (project-defined POU names and kinds).
    """
    system_catalog = load_system_catalog(system_catalog_path)

    project_symbols = _collect_project_symbols_from_st_files(project_root)

    # Cross-file variable maps for instance resolution
    global_instance_types = _build_global_instance_types(project_root)
    gvl_members = _build_gvl_members(project_root)

    all_calls: list[dict] = []
    source_count = 0
    for st_path in iter_st_files(project_root):
        calls = _process_st_file(
            st_path,
            project_root,
            project_symbols,
            system_catalog,
            global_instance_types=global_instance_types,
            gvl_members=gvl_members,
        )
        if calls:
            all_calls.extend(calls)
        source_count += 1

    output_symbols = {
        name: {"kind": info.get("kind", "unknown"), "guid": info.get("guid", "")}
        for name, info in project_symbols.items()
    }

    return {
        "meta": {
            "source_count": source_count,
            "system_catalog": system_catalog_path or "sys_funcs.json",
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "calls": all_calls,
        "symbols": output_symbols,
    }


def write_call_tree(data: dict, output_path: str) -> None:
    """Write the call tree report as formatted JSON."""
    with io.open(output_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def run_call_tree(
    project_root: str,
    output_path: str | None = None,
    system_catalog_path: str | None = None,
) -> dict:
    """Convenience entry point: build and optionally write the call tree."""
    data = build_call_tree(project_root, system_catalog_path)
    if output_path:
        write_call_tree(data, output_path)
    return data


def filter_subtree(calls: list[dict], root_pou: str) -> list[dict]:
    """Return the call records reachable from *root_pou* (case-insensitive).

    Walks caller -> callee edges breadth-first; a callee becomes the next
    caller key, so FB_X.Method edges chain into FB_X.Method's own calls.
    """
    by_caller: dict[str, list[dict]] = {}
    for c in calls:
        by_caller.setdefault(c["caller"].lower(), []).append(c)

    result: list[dict] = []
    seen: set[str] = set()
    queue = [root_pou.lower()]
    while queue:
        key = queue.pop(0)
        if key in seen:
            continue
        seen.add(key)
        for edge in by_caller.get(key, []):
            result.append(edge)
            queue.append(edge["callee"].lower())
    return result


def render_tree(calls: list[dict], root_pou: str, max_depth: int = 10) -> str:
    """Render the call subtree under *root_pou* as an indented text tree."""
    by_caller: dict[str, list[dict]] = {}
    for c in calls:
        by_caller.setdefault(c["caller"].lower(), []).append(c)

    lines = [root_pou]

    def _walk(name: str, prefix: str, depth: int, path: set[str]) -> None:
        edges = by_caller.get(name.lower(), [])
        for idx, edge in enumerate(edges):
            last = idx == len(edges) - 1
            branch = "`-- " if last else "|-- "
            callee = edge["callee"]
            note = edge["callee_kind"]
            loc = "{0}:{1}".format(edge["file"], edge["line"])
            suffix = ""
            child_key = callee.lower()
            if child_key in path:
                suffix = "  (recursion)"
            elif depth >= max_depth and by_caller.get(child_key):
                suffix = "  (max depth)"
            lines.append("{0}{1}{2}  [{3}]  ({4}){5}".format(
                prefix, branch, callee, note, loc, suffix))
            if suffix:
                continue
            _walk(callee, prefix + ("    " if last else "|   "),
                  depth + 1, path | {child_key})

    _walk(root_pou, "", 1, {root_pou.lower()})
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an offline call tree from exported .st files.")
    parser.add_argument("project_root", help="sync directory with .st exports")
    parser.add_argument("root_pou", nargs="?", default=None,
                        help="POU to render a text subtree for (e.g. MAIN)")
    parser.add_argument("-o", "--output", default=None,
                        help="write the full call tree as JSON to this path")
    parser.add_argument("--sys-funcs", default=None,
                        help="custom system-function catalog JSON")
    parser.add_argument("--max-depth", type=int, default=10,
                        help="max depth for the text subtree (default 10)")
    args = parser.parse_args(argv)

    data = run_call_tree(args.project_root, args.output, args.sys_funcs)

    if args.root_pou:
        print(render_tree(data["calls"], args.root_pou, args.max_depth))
    else:
        print("{0} source files, {1} calls, {2} symbols".format(
            data["meta"]["source_count"], len(data["calls"]),
            len(data["symbols"])))
    if args.output:
        print("call tree written to {0}".format(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
