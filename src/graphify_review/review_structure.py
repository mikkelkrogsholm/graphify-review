"""Structural facts about changed symbols: who depends on them, which tests reach them, risk.

Everything here is derived deterministically from the base/head dependency graphs. Risk is a
documented structural heuristic (dependents, tests, change size), never a defect prediction.
"""
from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath

import networkx as nx

from graphify_review.graphify_adapter import affected_nodes

MAX_SYMBOLS = 100
MAX_LISTED = 50
MAX_LOOK_FIRST = 5
MEDIUM_DEPENDENTS = 3
HIGH_DEPENDENTS = 10
HIGH_DEPENDENT_FILES = 5
MEDIUM_CODE_FILES = 8
HIGH_CODE_FILES = 25
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
CHANGE_ORDER = {"changed": 0, "removed": 1, "added": 2}
_TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs"}
_TEST_SUFFIXES = ("_test.py", "_test.go", "Test.java", "Tests.cs", "_spec.rb")


def is_test_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    return (any(part in _TEST_DIRS for part in parts[:-1]) or name.startswith("test_")
            or name == "conftest.py" or name.endswith(_TEST_SUFFIXES)
            or ".test." in name or ".spec." in name)


def _is_file_node(data: dict) -> bool:
    source, label = str(data.get("source_file") or ""), str(data.get("label") or "")
    name = PurePosixPath(source).name
    return bool(source) and (label == name or (label.endswith("/" + name) and source.endswith(label)))


def _is_symbol(data: dict) -> bool:
    return bool(data.get("source_file")) and not _is_file_node(data) and data.get("file_type") == "code"


def _line(data: dict) -> int | None:
    text = str(data.get("source_location") or "")
    return int(text[1:].split("-")[0]) if text.startswith("L") and text[1:2].isdigit() else None


def _kind(data: dict) -> str:
    label = str(data.get("label") or "")
    if data.get("_callable_class"):
        return "class"
    if label.startswith(".") and label.endswith("()"):
        return "method"
    return "function" if label.endswith("()") else "other"


def _display(graph: nx.DiGraph, node: str) -> str:
    data = graph.nodes[node]
    label = str(data.get("label") or node)
    if _kind(data) == "method":
        for owner, _, edge in graph.in_edges(node, data=True):
            if edge.get("relation") == "method":
                return f"{graph.nodes[owner].get('label', owner)}{label}"
        return label.lstrip(".")
    return label


def _entry(graph: nx.DiGraph, node: str, **extra: object) -> dict:
    data = graph.nodes[node]
    path = str(data.get("source_file") or "")
    name = path if _is_file_node(data) else _display(graph, node)
    return {"id": str(node), "label": name, "file": path, "line": _line(data), **extra}


def _dependents(graph: nx.DiGraph, node: str, depth: int) -> list[dict]:
    return [_entry(graph, hit.node_id, relation=hit.via_relation, depth=hit.depth)
            for hit in affected_nodes(graph, node, depth=depth)]


def _distinct_tests(tests: list[dict]) -> list[dict]:
    """A test file reached only by an import is not a second test beside its own functions."""
    with_functions = {t["file"] for t in tests if t["label"] != t["file"]}
    return [t for t in tests if t["label"] != t["file"] or t["file"] not in with_functions]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _look_key(symbol: dict) -> tuple:
    still_used = symbol["status"] == "removed" and bool(symbol["dependent_count"])
    return (-RISK_ORDER[symbol["risk"]], not still_used, -symbol["dependent_count"],
            CHANGE_ORDER[symbol["status"]], symbol["file"], symbol["line"] or 0, symbol["label"])


def analyze_structure(graphs: dict, story_seeds: list[dict], changes: list[dict], depth: int,
                      *, code_files: dict[str, set[str]]) -> dict:
    """``story_seeds`` items: ``{"story_id", "seeds": {"base": [...], "head": [...]}, "methods": {...}}``."""
    touched = {side: {str(n) for item in story_seeds for n in item["seeds"][side]} for side in graphs}
    found: dict[str, dict] = {}
    for item in story_seeds:
        for side in ("base", "head"):
            for node in item["seeds"][side]:
                node = str(node)
                if node in graphs[side] and _is_symbol(graphs[side].nodes[node]) and node not in found:
                    found[node] = {"story_id": item["story_id"], "mapping": item["methods"][side]}
    omitted = max(0, len(found) - MAX_SYMBOLS)

    def priority(node: str) -> tuple:
        # Analyse removed symbols first, then the most depended-upon, so a budget cut keeps the riskiest.
        in_head = node in graphs["head"]
        return in_head, -graphs["head" if in_head else "base"].in_degree(node), node

    symbols = []
    for node in sorted(found, key=priority)[:MAX_SYMBOLS]:
        in_base, in_head = node in graphs["base"], node in graphs["head"]
        status = "changed" if in_base and in_head else "added" if in_head else "removed"
        side = "head" if in_head else "base"
        graph = graphs[side]
        record = {**_entry(graph, node), "kind": _kind(graph.nodes[node]), "status": status,
                  "story_id": found[node]["story_id"], "mapping": found[node]["mapping"]}
        record["is_test"] = is_test_path(record["file"])
        hits = _dependents(graph, node, depth)
        if status == "removed":
            hits = [h for h in hits if h["id"] in graphs["head"]]
        outside, tests = [], []
        for hit in hits:
            if is_test_path(hit["file"]):
                tests.append(hit)
            elif hit["id"] not in touched[side] and not (status == "removed" and hit["id"] in touched["base"]):
                outside.append(hit)
        outside.sort(key=lambda d: (d["label"] == d["file"], d["depth"], d["file"], d["line"] or 0, d["label"]))
        tests = _distinct_tests(sorted(tests, key=lambda d: (d["depth"], d["file"], d["line"] or 0, d["label"])))
        record.update(dependents=outside, tests=tests, class_tests=[], tests_from=None)
        symbols.append(record)
    by_id = {s["id"]: s for s in symbols}
    for symbol in symbols:
        if symbol["kind"] == "method" and not symbol["tests"] and symbol["status"] != "removed":
            owner = next((u for u, _, e in graphs["head"].in_edges(symbol["id"], data=True)
                          if e.get("relation") == "method"), None)
            if owner is not None:
                owner_tests = by_id[str(owner)]["tests"] if str(owner) in by_id else _distinct_tests(
                    [h for h in _dependents(graphs["head"], str(owner), depth) if is_test_path(h["file"])])
                # A class dependency does not establish that any particular method runs.
                symbol["class_tests"], symbol["tests_from"] = owner_tests[:MAX_LISTED], str(owner)
    for symbol in symbols:
        symbol["dependent_count"] = len(symbol["dependents"])
        symbol["dependent_files"] = len({d["file"] for d in symbol["dependents"]})
        symbol["test_count"] = len(symbol["tests"])
        symbol["risk"], symbol["reasons"] = _symbol_risk(symbol)
        symbol["dependents"] = symbol["dependents"][:MAX_LISTED]
        symbol["tests"] = symbol["tests"][:MAX_LISTED]
    code_changes = [c for c in changes if any(
        c[f"{side}_file"] in code_files[side] and not is_test_path(c[f"{side}_file"])
        for side in ("base", "head"))]
    changed_code_files = {c["head_file"] or c["base_file"] for c in code_changes}
    mapped_files = {side: {graphs[side].nodes[n]["source_file"] for n in touched[side]
                           if n in graphs[side] and _is_symbol(graphs[side].nodes[n])}
                    for side in ("base", "head")}
    unmapped = sorted({c["head_file"] or c["base_file"] for c in code_changes
                       if not any(c[f"{side}_file"] in mapped_files[side] for side in ("base", "head"))})
    test_files = {c["head_file"] for c in changes if c["head_file"] and is_test_path(c["head_file"])}
    test_gap = bool(changed_code_files) and not test_files
    ranked = sorted((s for s in symbols if not s["is_test"]), key=_look_key)
    level, reasons = "low", []
    if ranked and RISK_ORDER[ranked[0]["risk"]]:
        level = ranked[0]["risk"]
        reasons.append(f"{ranked[0]['label']} ({', '.join(ranked[0]['reasons'])})")
    size = "high" if len(changed_code_files) >= HIGH_CODE_FILES else "medium" if len(changed_code_files) >= MEDIUM_CODE_FILES else "low"
    if size != "low":
        reasons.append(f"{_plural(len(changed_code_files), 'code file')} changed")
        level = max(level, size, key=RISK_ORDER.__getitem__)
    if test_gap:
        reasons.append("code changed without any test changes")
        level = "medium" if level == "low" else level
    if omitted:
        reasons.append(f"{omitted} more changed symbols were not analysed, so risk may be understated")
        level = max(level, "medium", key=RISK_ORDER.__getitem__)
    if unmapped:
        reasons.append(f"{_plural(len(unmapped), 'changed code file')} without mapped symbols; test reachability is unknown")
        level = max(level, "medium", key=RISK_ORDER.__getitem__)
    names = Counter(s["label"] for s in symbols)
    untested = sorted({s["label"] if names[s["label"]] == 1 else f"{s['label']} in {s['file']}"
                       for s in symbols if not s["is_test"] and s["status"] != "removed" and not s["tests"]})
    symbols.sort(key=_look_key)
    return {"method": "structural_heuristic", "symbols": symbols, "omitted_symbols": omitted,
            "risk": {"level": level, "reasons": reasons},
            "tests": {"code_files_changed": len(changed_code_files), "test_files_changed": len(test_files),
                      "test_gap": test_gap, "untested": untested,
                      "unmapped_code_file_count": len(unmapped), "unmapped_code_files": unmapped[:MAX_LISTED]},
            "look_first": [s["id"] for s in ranked[:MAX_LOOK_FIRST]]}


def _symbol_risk(symbol: dict) -> tuple[str, list[str]]:
    if symbol["is_test"]:
        return "low", ["test code"]
    count, files, risk, reasons = symbol["dependent_count"], symbol["dependent_files"], "low", []
    if symbol["status"] == "removed" and count:
        risk, reasons = "high", [f"removed, but {_plural(count, 'place')} still use it"]
    elif count >= HIGH_DEPENDENTS:
        risk, reasons = "high", [f"{_plural(count, 'place')} depend on it"]
    elif files >= HIGH_DEPENDENT_FILES:
        risk, reasons = "high", [f"used from {_plural(files, 'file')}"]
    elif count >= MEDIUM_DEPENDENTS:
        risk, reasons = "medium", [f"{_plural(count, 'place')} depend on it"]
    elif count:
        reasons = [f"{_plural(count, 'place')} {'depends' if count == 1 else 'depend'} on it"]
    if symbol["status"] != "removed" and not symbol["test_count"]:
        risk = max(risk, "medium", key=RISK_ORDER.__getitem__)
        reasons.append("no test reaches it")
    return risk, reasons
