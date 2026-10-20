"""Facts, narrator evidence, and the short comment."""
from __future__ import annotations

import json
import re

import pytest

from graphify_review import review
from graphify_review.review_documents import (
    COMMENT_MARKER, MAX_COMMENT_BYTES, dump, evidence_document, facts_document, render_comment,
)
from graphify_review.review_source import git_target
from tests.test_structure import structured, structured_repository  # noqa: F401

URL = "https://reviews.example.test/pr-14/"


def test_facts_describe_the_analysis_as_data(structured):
    facts = facts_document(structured)
    assert facts["schema"] == "graphify-review/facts/1"
    assert facts["risk"]["level"] == "high" and facts["risk_method"] == "structural_heuristic"
    assert facts["counts"]["changed_symbols"] == 3
    assert facts["tests"]["untested"] == ["rounding()"]
    assert facts["look_first"][0] == next(s["id"] for s in facts["symbols"] if s["label"] == "legacy_tax()")
    assert facts["engine"]["graphify"]
    assert {"id", "label", "status", "risk", "dependents", "tests"} <= set(facts["symbols"][0])
    assert all("snippet" not in json.dumps(s) for s in facts["symbols"])
    assert facts["target"]["head"] == structured["target"]["head"]


def test_facts_and_evidence_are_byte_identical_across_runs(structured_repository):
    root, base, head = structured_repository
    runs = [review.build_review(root, git_target(root, base, head)) for _ in range(2)]
    assert dump(facts_document(runs[0])) == dump(facts_document(runs[1]))
    assert dump(evidence_document(runs[0])) == dump(evidence_document(runs[1]))


def test_evidence_carries_cited_excerpts_and_the_narration_contract(structured):
    document = evidence_document(structured)
    story = document["stories"][0]
    assert story["narratable"] and story["evidence"]
    assert {e["side"] for e in story["evidence"]} == {"base", "head"}
    known = {e["id"] for e in structured["evidence"]}
    assert {e["id"] for e in story["evidence"]} <= known
    contract = document["narration_contract"]
    assert "behavior_changes" in contract and "untrusted" in document
    assert document["limits"]["omitted_by_budget"] == 0


def test_evidence_budget_is_disclosed(structured, monkeypatch):
    from graphify_review import review_documents
    monkeypatch.setattr(review_documents, "MAX_EVIDENCE_CHARS", 10)
    document = evidence_document(structured)
    assert document["limits"]["omitted_by_budget"] >= 1
    assert all(not s["narratable"] and not s["evidence"] for s in document["stories"])


def test_comment_is_short_marked_and_links_once(structured):
    text = render_comment(structured, URL)
    assert text.startswith(COMMENT_MARKER)
    assert len(text.encode("utf-8")) <= MAX_COMMENT_BYTES
    assert text.count(f"<{URL}>") == 1 and text.count("http") == 1
    assert "High risk" in text.splitlines()[1] or "high risk" in text.splitlines()[1]
    assert "legacy\\_tax" in text  # underscores are markdown-escaped
    assert "Numbers come from the structural analysis alone" in text


def test_comment_uses_checks_and_labelled_narration(structured):
    review.apply_checks(structured, [{"name": "tests", "status": "ok"}, {"name": "reviewer", "status": "fail"}])
    review.apply_narration(structured, {"headline": "Rounding added", "summary": "Totals are rounded.",
                                        "safety": {"level": "mostly", "text": "Small and local."}})
    text = render_comment(structured, URL)
    assert "✅ tests" in text and "❌ reviewer" in text
    assert "Totals are rounded." in text and "Mostly" in text
    assert "written by a model" in text


@pytest.mark.parametrize("limit", [400, 700, 1200])
def test_comment_shrinks_to_fit_but_keeps_marker_and_link(structured, limit):
    review.apply_checks(structured, [{"name": f"check {i} " + "x" * 30, "status": "ok"} for i in range(12)])
    review.apply_narration(structured, {"summary": "word " * 400, "look": [
        {"title": "t" * 100, "why": "w" * 300, "where": "f.py:1"}] * 5})
    text = render_comment(structured, URL, max_bytes=limit)
    assert len(text.encode("utf-8")) <= limit
    assert text.startswith(COMMENT_MARKER) and f"<{URL}>" in text


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "ftp://x.test/", "https://u:p@x.test/", "//x.test", ""])
def test_comment_refuses_unsafe_links(structured, bad):
    with pytest.raises(ValueError):
        render_comment(structured, bad)


HOSTILE = ["<script>alert(1)</script>", "[x](http://evil.test)", "![i](http://evil.test/p.png)", "@everyone",
           COMMENT_MARKER, "```\nfence", "&lt;b&gt;", "\u202eabc", "\x00nul"]


@pytest.mark.parametrize("payload", HOSTILE)
def test_hostile_text_stays_text_in_the_comment(structured, payload):
    review.apply_checks(structured, [{"name": payload, "status": "ok", "text": payload}])
    review.apply_narration(structured, {"headline": payload, "summary": payload,
                                        "safety": {"level": "safe", "text": payload},
                                        "look": [{"title": payload, "why": payload, "where": payload}]})
    text = render_comment(structured, URL)
    assert text.count(COMMENT_MARKER) == 1
    # Text inside a code span is literal; everything else must be inert.
    body = re.sub(r"`[^`]*`", "", text.replace(f"<{URL}>", "").replace(COMMENT_MARKER, ""))
    assert "<script" not in body and "<img" not in body and "@everyone" not in body
    assert "http://evil.test" not in body and "```" not in body
    assert "\u202e" not in text and "\x00" not in text
    assert len(text.encode("utf-8")) <= MAX_COMMENT_BYTES
