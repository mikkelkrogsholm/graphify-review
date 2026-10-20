"""Run `uv run python -m examples.generate` to rebuild the authored demonstration."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from graphify_review.graphify_adapter import inference_api
from graphify_review.review import build_review, infer_behavior, save_review
from graphify_review.review_source import git_target
from tests.test_review import reply_for
from tests.test_review_source import repository


def main():
    destination = Path(__file__).resolve().parent
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


if __name__ == "__main__":
    main()
