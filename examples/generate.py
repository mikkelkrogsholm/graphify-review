"""Run `uv run python -m examples.generate` to rebuild the authored demonstrations."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from graphify_review.graphify_adapter import inference_api
from graphify_review.review import (
    apply_checks, apply_narration, build_review, infer_behavior, save_review, write_output,
)
from graphify_review.review_documents import dump, evidence_document, facts_document, render_comment
from graphify_review.review_source import git_target
from tests.test_review import reply_for
from tests.test_review_source import repository
from tests.test_structure import structured_repository

PAGE_URL = "https://reviews.example.test/pr-14/"


def provider_demo(destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="graphify-review-example-") as temporary:
        root, base, head = repository.__wrapped__(Path(temporary).resolve())
        target = git_target(root, base, head)
        target["title"] = "Require an MFA challenge before creating a session"
        review = build_review(root, target)
        reply = reply_for(review,
            before_pseudocode="When signing in:\n    Create a session\n    Return the session",
            after_pseudocode="When signing in:\n    If MFA is required:\n        Return an MFA challenge\n    Otherwise:\n        Create and return a session")
        with patch.object(inference_api(), "_call_llm", return_value=reply):
            infer_behavior(review, backend="ollama", model="authored-demonstration")
        review["behavior_analysis"]["illustrative"] = True
        json_path, html_path = save_review(review, root)
        (destination / "review.json").write_bytes(json_path.read_bytes())
        (destination / "review.html").write_bytes(html_path.read_bytes())
    print(f"Generated {destination / 'review.html'}; pseudocode is explicitly mocked/authored.")


def interface_demo(destination: Path) -> None:
    """Two refs in, data files and a short comment out; the narration is authored, not model output."""
    folder = destination / "interface"
    folder.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="graphify-review-interface-") as temporary:
        root, base, head = structured_repository.__wrapped__(Path(temporary).resolve())
        target = git_target(root, base, head)
        review = build_review(root, target, title="Round totals and retire the legacy tax helper")
        evidence = evidence_document(review)
        story = next(s for s in evidence["stories"] if s["narratable"])
        narration = {
            "narrator": "authored-demonstration",
            "headline": "Totals are rounded to cents and the legacy tax helper is removed.",
            "summary": "total() now rounds its result. legacy_tax() was deleted although checkout() still calls it.",
            "safety": {"level": "careful", "text": "A removed helper is still referenced by checkout()."},
            "look": [{"title": "legacy_tax() removal", "where": "billing.py", "why": "checkout() still calls it"}],
            "not_proven": "No code was run.",
            "behavior_changes": [{
                "story_id": story["id"], "summary": "Totals are rounded; the tax helper is gone.",
                "before_pseudocode": "total: return the sum of items\nlegacy_tax: return amount times 0.2",
                "after_pseudocode": "total: return the sum of items rounded to 2 digits\nrounding: return value rounded to 2 digits",
                "evidence_ids": [e["id"] for e in story["evidence"]], "uncertainties": ["Callers of the removed helper were not analysed."]}]}
        checks = [{"name": "tests", "status": "ok", "text": "authored example"},
                  {"name": "reviewer", "status": "fail", "text": "authored example: removed helper is still used"}]
        apply_checks(review, checks)
        apply_narration(review, narration)
        review["behavior_analysis"]["illustrative"] = True
        _, html_path = save_review(review, root, output=Path(temporary) / "out")
        (folder / "narration.json").write_text(json.dumps(narration, indent=2) + "\n", encoding="utf-8")
        (folder / "checks.json").write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
        (folder / "review.html").write_bytes(html_path.read_bytes())
        write_output(folder / "facts.json", dump(facts_document(review)))
        write_output(folder / "evidence.json", dump(evidence_document(review)))
        write_output(folder / "comment.md", render_comment(review, PAGE_URL))
    print(f"Generated {folder}; the narration is authored, not model output.")


def main():
    destination = Path(__file__).resolve().parent
    provider_demo(destination)
    interface_demo(destination)


if __name__ == "__main__":
    main()
