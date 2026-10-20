"""Test linkage, structural risk and look-first order from real extracted graphs."""
from __future__ import annotations

import pytest

from graphify_review import review
from graphify_review.review_source import git_target
from graphify_review.review_structure import is_test_path
from tests.test_review_source import git


@pytest.fixture
def structured_repository(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Review tests")
    git(tmp_path, "config", "user.email", "review@example.invalid")
    git(tmp_path, "config", "core.autocrlf", "false")
    hooks = tmp_path / "empty-hooks"
    hooks.mkdir()
    git(tmp_path, "config", "core.hooksPath", str(hooks))
    (tmp_path / "tests").mkdir()
    (tmp_path / "billing.py").write_text(
        "def legacy_tax(amount):\n    return amount * 0.2\n\ndef total(items):\n    return sum(items)\n",
        encoding="utf-8")
    (tmp_path / "checkout.py").write_text(
        "from billing import total, legacy_tax\n\ndef checkout(items):\n    return total(items) + legacy_tax(1)\n\n"
        "def preview(items):\n    return total(items)\n", encoding="utf-8")
    (tmp_path / "tests" / "test_billing.py").write_text(
        "from billing import total\n\ndef test_total():\n    assert total([1, 2]) == 3\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "billing.py").write_text(
        "def total(items):\n    return round(sum(items), 2)\n\ndef rounding(value):\n    return round(value, 2)\n",
        encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "head")
    return tmp_path, base, git(tmp_path, "rev-parse", "HEAD")


@pytest.fixture
def structured(structured_repository):
    root, base, head = structured_repository
    return review.build_review(root, git_target(root, base, head))


def by_label(model, label):
    return next(s for s in model["structure"]["symbols"] if s["label"] == label)


@pytest.mark.parametrize("path,expected", [
    ("tests/test_a.py", True), ("pkg/test_a.py", True), ("pkg/a_test.go", True), ("src/a.test.ts", True),
    ("src/a.spec.js", True), ("__tests__/a.js", True), ("conftest.py", True), ("pkg/a.py", False),
    ("pkg/latest.py", False), ("contest/a.py", False)])
def test_test_path_detection(path, expected):
    assert is_test_path(path) is expected


def test_symbol_status_and_dependents(structured):
    total, legacy, rounding = by_label(structured, "total()"), by_label(structured, "legacy_tax()"), by_label(structured, "rounding()")
    assert (total["status"], legacy["status"], rounding["status"]) == ("changed", "removed", "added")
    assert {d["label"] for d in total["dependents"]} >= {"checkout()", "preview()"}
    assert {d["label"] for d in legacy["dependents"]} == {"checkout()", "checkout.py"}  # caller and importing file
    assert total["mapping"] == "python_ast_span"


def test_tests_reaching_symbols_and_untested(structured):
    total = by_label(structured, "total()")
    assert any(t["file"] == "tests/test_billing.py" for t in total["tests"])
    assert by_label(structured, "rounding()")["test_count"] == 0
    assert structured["structure"]["tests"]["untested"] == ["rounding()"]
    assert all(t["file"] == "tests/test_billing.py" for s in structured["structure"]["symbols"] for t in s["tests"])


def test_removed_but_still_used_is_high_risk_and_first(structured):
    structure = structured["structure"]
    legacy = by_label(structured, "legacy_tax()")
    assert legacy["risk"] == "high"
    assert "still use it" in legacy["reasons"][0]
    assert structure["risk"]["level"] == "high"
    assert structure["look_first"][0] == legacy["id"]
    assert by_label(structured, "rounding()")["risk"] == "medium"
    assert "no test reaches it" in by_label(structured, "rounding()")["reasons"]


def test_code_changed_without_tests_is_flagged(structured):
    tests = structured["structure"]["tests"]
    assert tests["test_gap"] is True
    assert (tests["code_files_changed"], tests["test_files_changed"]) == (1, 0)
    assert "code changed without any test changes" in structured["structure"]["risk"]["reasons"]


def test_methods_borrow_their_classs_tests(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    (tmp_path / "tests").mkdir()
    (tmp_path / "calc.py").write_text("class Calc:\n    def add(self, a, b):\n        return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from calc import Calc\n\ndef test_calc():\n    assert Calc().add(1, 2) == 3\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "calc.py").write_text("class Calc:\n    def add(self, a, b):\n        return b + a\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "head")
    model = review.build_review(tmp_path, git_target(tmp_path, base, git(tmp_path, "rev-parse", "HEAD")))
    add = next(s for s in model["structure"]["symbols"] if s["label"].endswith("add()"))
    assert add["tests"] and add["tests_from"]
    assert model["structure"]["tests"]["untested"] == []


def test_structure_is_deterministic(structured_repository):
    root, base, head = structured_repository
    first = review.build_review(root, git_target(root, base, head))["structure"]
    second = review.build_review(root, git_target(root, base, head))["structure"]
    assert first == second


def test_budget_cut_keeps_the_riskiest_symbols_and_never_reads_low(structured_repository, monkeypatch):
    from graphify_review import review_structure
    monkeypatch.setattr(review_structure, "MAX_SYMBOLS", 1)
    root, base, head = structured_repository
    model = review.build_review(root, git_target(root, base, head))
    structure = model["structure"]
    assert [s["label"] for s in structure["symbols"]] == ["legacy_tax()"]  # removed-and-used is analysed first
    assert structure["omitted_symbols"] == 2 and structure["risk"]["level"] == "high"
    assert any("not analysed" in r for r in structure["risk"]["reasons"])


def test_omitted_symbols_raise_a_low_risk_to_medium():
    from graphify_review.review_structure import analyze_structure
    import networkx as nx
    graph = nx.DiGraph()
    graph.add_node("n", label="f()", source_file="a.py", source_location="L1", file_type="code")
    result = analyze_structure({"base": graph, "head": graph},
                               [{"story_id": "change-1", "seeds": {"base": [], "head": ["n"]}, "methods": {"base": "x", "head": "x"}}],
                               [{"head_file": "tests/test_a.py", "base_file": "tests/test_a.py"}], 2)
    assert result["omitted_symbols"] == 0 and result["risk"]["level"] in ("low", "medium")
