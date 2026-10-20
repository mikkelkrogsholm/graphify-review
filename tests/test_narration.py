"""An explanation written elsewhere is validated, labeled and optional."""
from __future__ import annotations

import copy

import pytest

from graphify_review import review
from graphify_review.review_html import render_review
from tests.test_structure import structured, structured_repository  # noqa: F401


def entry(model, **changes):
    story = model["stories"][0]
    return {"story_id": story["id"], "summary": "Totals are rounded to cents.",
            "before_pseudocode": "Return the sum.", "after_pseudocode": "Return the sum rounded to 2 digits.",
            "evidence_ids": story["evidence_ids"], "uncertainties": ["Rounding mode not shown."], **changes}


def test_valid_narration_is_attached_and_labeled(structured):
    review.apply_narration(structured, {"narrator": "writer-1", "headline": "Rounding", "behavior_changes": [entry(structured)]})
    behavior = structured["stories"][0]["behavior"]
    assert behavior["confidence"] == "INFERRED" and behavior["method"] == "external_narration"
    analysis = structured["behavior_analysis"]
    assert analysis["status"] == "complete" and analysis["source"] == "external_narration"
    assert analysis["narrator"] == "writer-1"
    review.validate_review(structured)
    page = render_review(structured)
    assert "MODEL-WRITTEN NARRATION" in page and "writer-1" in page


def test_the_page_and_structure_work_without_a_narration(structured):
    page = render_review(structured)
    assert "Behavioral pseudocode unavailable" in page and "Structural risk: High" in page
    assert structured["behavior_analysis"]["status"] == "not_requested"


@pytest.mark.parametrize("data", [None, [], "text", 5])
def test_non_object_narration_fails_softly(structured, data):
    review.apply_narration(structured, data)
    assert structured["behavior_analysis"]["status"] == "failed"
    assert all(s["behavior"] is None for s in structured["stories"])
    render_review(structured)


@pytest.mark.parametrize("change", [
    {"story_id": "change-99"}, {"evidence_ids": ["nope"]}, {"evidence_ids": []}, {"summary": ""},
    {"before_pseudocode": 5}, {"uncertainties": "x"}, {"after_pseudocode": "x" * 7000}])
def test_invalid_entries_are_rejected_not_repaired(structured, change):
    review.apply_narration(structured, {"behavior_changes": [entry(structured, **change)]})
    assert structured["stories"][0]["behavior"] is None
    assert structured["behavior_analysis"]["status"] == "failed"
    assert structured["behavior_analysis"]["rejected"] == 1


def test_citations_must_cover_every_available_side(structured):
    story = structured["stories"][0]
    head_only = [e["id"] for e in structured["evidence"] if e["id"] in story["evidence_ids"] and e["side"] == "head"]
    review.apply_narration(structured, {"behavior_changes": [entry(structured, evidence_ids=head_only)]})
    assert structured["stories"][0]["behavior"] is None


def test_unknown_keys_are_ignored_and_summary_only_is_valid(structured):
    review.apply_narration(structured, {"future_field": {"x": 1}, "summary": "A short note."})
    assert structured["narration"]["summary"] == "A short note."
    assert structured["behavior_analysis"]["status"] == "complete"


def test_unknown_safety_level_reads_as_careful(structured):
    review.apply_narration(structured, {"safety": {"level": "totally-fine", "text": "Trust me."}})
    assert structured["narration"]["safety"]["level"] == "careful"


def test_duplicate_story_entries_count_once(structured):
    review.apply_narration(structured, {"behavior_changes": [entry(structured), entry(structured)]})
    assert structured["behavior_analysis"]["accepted"] == 1 and structured["behavior_analysis"]["rejected"] == 1
    assert structured["behavior_analysis"]["status"] == "partial"


def test_a_new_narration_replaces_an_earlier_one(structured):
    review.apply_narration(structured, {"behavior_changes": [entry(structured)], "headline": "first"})
    review.apply_narration(structured, {"headline": "second"})
    assert structured["stories"][0]["behavior"] is None and structured["narration"]["headline"] == "second"


def test_narration_cannot_alter_structure_or_evidence(structured):
    before = copy.deepcopy({k: structured[k] for k in ("structure", "evidence", "graph_diff", "blast_radius")})
    review.apply_narration(structured, {"structure": {"risk": {"level": "low"}}, "evidence": [], "behavior_changes": [entry(structured)]})
    assert {k: structured[k] for k in before} == before


def test_secrets_in_narration_and_checks_are_redacted(structured):
    secret = "ghp_" + "z" * 30
    review.apply_narration(structured, {"summary": f"token {secret}", "behavior_changes": [entry(structured, summary=f"x {secret}")]})
    review.apply_checks(structured, [{"name": "ci", "status": "ok", "text": f"key {secret}"}])
    assert secret not in repr(structured) and structured["redactions"]["count"] >= 3
    assert secret not in render_review(structured)


def test_redaction_can_be_disabled(structured):
    secret = "ghp_" + "z" * 30
    review.apply_narration(structured, {"summary": secret}, redact=False)
    assert structured["narration"]["summary"] == secret


def test_checks_are_bounded_and_validated(structured):
    kept = review.apply_checks(structured, {"steps": [{"name": f"c{i}", "status": "ok" if i % 2 else "weird"} for i in range(40)]
                                            + [{"status": "ok"}, "junk"]})
    assert kept == review.MAX_CHECKS
    assert {c["status"] for c in structured["checks"]} == {"ok", "skipped"}
    review.validate_review(structured)
    assert "Checks, tester and reviewer" in render_review(structured)
    assert review.apply_checks(structured, "not a list") == 0 and structured["checks"] == []


@pytest.mark.parametrize("story_id", [["change-1"], {"a": 1}, 5, None, True])
def test_non_string_story_ids_are_rejected_not_fatal(structured, story_id):
    review.apply_narration(structured, {"behavior_changes": [{"story_id": story_id}]})
    assert structured["behavior_analysis"]["status"] == "failed" and structured["behavior_analysis"]["rejected"] == 1


def test_a_token_split_by_an_invisible_character_is_not_reassembled(structured):
    token = "ghp_" + "a" * 30
    split = token[:10] + "\u200b" + token[10:]
    review.apply_narration(structured, {"summary": split, "headline": split})
    review.apply_checks(structured, [{"name": "ci", "status": "ok", "text": split}])
    for value in (structured["narration"]["summary"], structured["narration"]["headline"], structured["checks"][0]["text"]):
        assert "ghp_" not in value and token[:10] not in value


def test_checks_are_redacted_before_they_are_clipped(structured):
    token = "ghp_" + "b" * 36
    review.apply_checks(structured, [{"name": "x" * 56 + " " + token, "status": "ok", "text": "y" * 577 + " " + token}])
    check = structured["checks"][0]
    assert "ghp_" not in check["name"] and "ghp_" not in check["text"]


def test_deeply_nested_or_hostile_narration_never_raises(structured):
    nested: object = "leaf"
    for _ in range(5000):
        nested = [nested]
    review.apply_narration(structured, {"summary": "ok", "future": nested})
    assert structured["behavior_analysis"]["status"] in ("complete", "failed")
    review.apply_narration(structured, {"behavior_changes": [entry(structured, uncertainties=["\u200b"])]})
    assert structured["behavior_analysis"]["status"] == "failed"


def test_environment_redaction_is_opt_in_and_recorded(structured_repository, monkeypatch):
    from graphify_review.review_source import git_target
    root, base, head = structured_repository
    monkeypatch.setenv("DEPLOY_TOKEN", "sum(items")
    plain = review.build_review(root, git_target(root, base, head))
    assert plain["redactions"]["environment"] is False and "[redacted: environment secret]" not in repr(plain)
    env = review.build_review(root, git_target(root, base, head), redact_env=True)
    assert env["redactions"]["environment"] is True and "[redacted: environment secret]" in repr(env)
    review.apply_checks(env, [{"name": "sum(items", "status": "ok"}])
    assert env["checks"][0]["name"] == "[redacted: environment secret]"
