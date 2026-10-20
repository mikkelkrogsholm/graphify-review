"""The refs-only path: offline, read-only, deterministic, and driven by data files."""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from graphify_review import review_source
from graphify_review.cli import main
from tests.test_structure import structured_repository  # noqa: F401

URL = "https://reviews.example.test/pr-14/"


@pytest.fixture
def workdir(tmp_path_factory):
    """Outputs and inputs live outside the reviewed checkout."""
    return tmp_path_factory.mktemp("work")


def tree_state(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def run(root, base, head, out, *extra, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(root)
    return main(["--base", base, "--head", head, "--output", str(out), *extra])


def test_refs_mode_never_uses_a_forge_client_or_the_network(structured_repository, workdir, monkeypatch, capsys):
    root, base, head = structured_repository
    commands = []
    real = review_source._run

    def recording(repository, command, *args, **kwargs):
        commands.append(list(command))
        return real(repository, command, *args, **kwargs)

    def no_network(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(review_source, "_run", recording)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    assert run(root, base, head, workdir / "out", monkeypatch=monkeypatch) == 0
    assert commands and all(c[0] == "git" for c in commands)
    assert not any("fetch" in c or "clone" in c or "push" in c for c in commands)


def test_the_checkout_is_not_modified_and_output_goes_elsewhere(structured_repository, workdir, monkeypatch):
    root, base, head = structured_repository
    before = tree_state(root)
    out = workdir / "elsewhere"
    assert run(root, base, head, out, "--facts", str(out / "facts.json"), "--evidence", str(out / "evidence.json"),
               "--comment", str(out / "comment.md"), "--view-url", URL, monkeypatch=monkeypatch) == 0
    assert tree_state(root) == before
    assert not (root / "graphify-review-out").exists() and not (root / "graphify-out").exists()
    assert (out / "facts.json").is_file() and (out / "comment.md").is_file()


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs a non-root POSIX user")
def test_works_on_a_read_only_checkout(structured_repository, workdir, monkeypatch):
    root, base, head = structured_repository
    paths = [p for p in root.rglob("*")] + [root]
    try:
        for p in paths:
            p.chmod(p.stat().st_mode & ~0o222)
        assert run(root, base, head, workdir / "out", monkeypatch=monkeypatch) == 0
    finally:
        for p in paths:
            p.chmod(p.stat().st_mode | 0o700)
    assert list((workdir / "out").glob("reviews/*/review.html"))


def test_all_outputs_are_deterministic_across_runs(structured_repository, workdir, monkeypatch):
    root, base, head = structured_repository
    for name in ("one", "two"):
        out = workdir / name
        assert run(root, base, head, out, "--facts", str(out / "f.json"), "--evidence", str(out / "e.json"),
                   "--comment", str(out / "c.md"), "--view-url", URL, monkeypatch=monkeypatch) == 0
    for name in ("f.json", "e.json", "c.md"):
        assert (workdir / "one" / name).read_bytes() == (workdir / "two" / name).read_bytes(), name
    page = [next((workdir / d).glob("reviews/*/review.html")).read_bytes() for d in ("one", "two")]
    assert page[0] == page[1]


def test_two_step_flow_facts_then_external_narration_and_checks(structured_repository, workdir, monkeypatch, capsys):
    root, base, head = structured_repository
    out = workdir / "out"
    assert run(root, base, head, out, "--evidence", str(out / "evidence.json"), monkeypatch=monkeypatch) == 0
    evidence = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
    story = next(s for s in evidence["stories"] if s["narratable"])
    narration = {"narrator": "external-writer", "headline": "Totals are rounded and a tax helper is gone.",
                 "summary": "The total is now rounded. The old tax helper was removed.",
                 "safety": {"level": "careful", "text": "A removed helper is still called from checkout."},
                 "behavior_changes": [{"story_id": story["id"], "summary": "Rounding added.",
                                       "before_pseudocode": "Return the sum.", "after_pseudocode": "Return the rounded sum.",
                                       "evidence_ids": [e["id"] for e in story["evidence"]], "uncertainties": []}]}
    (workdir / "narration.json").write_text(json.dumps(narration), encoding="utf-8")
    (workdir / "checks.json").write_text(json.dumps([{"name": "tests", "status": "ok", "text": "12 passed"},
                                                      {"name": "reviewer", "status": "fail", "text": "see removed helper"}]),
                                          encoding="utf-8")
    capsys.readouterr()
    assert run(root, base, head, out, "--narration", str(workdir / "narration.json"), "--checks", str(workdir / "checks.json"),
               "--comment", str(out / "comment.md"), "--view-url", URL, monkeypatch=monkeypatch) == 0
    stdout = capsys.readouterr().out
    assert "Behavior analysis: complete" in stdout and "Risk: high" in stdout and "Comment:" in stdout
    model = json.loads(next(out.glob("reviews/*/review.json")).read_text(encoding="utf-8"))
    assert model["stories"][0]["behavior"]["method"] == "external_narration"
    assert [c["status"] for c in model["checks"]] == ["ok", "fail"]
    page = next(out.glob("reviews/*/review.html")).read_text(encoding="utf-8")
    assert "MODEL-WRITTEN" in page and "tests: Passed" in page and "reviewer: Failed" in page
    comment = (out / "comment.md").read_text(encoding="utf-8")
    assert len(comment.encode()) <= 3000 and "✅ tests" in comment and "❌ reviewer" in comment


@pytest.mark.parametrize("content", ["not json", "[1,2]", "binary", "oversized"])
def test_a_bad_narration_never_blocks_the_review(structured_repository, workdir, monkeypatch, capsys, content):
    root, base, head = structured_repository
    bad = workdir / "narration.json"
    payload = {"binary": b"\xff\xfe\x00", "oversized": b"x" * 1_100_000}.get(content, content.encode())
    bad.write_bytes(payload)
    out = workdir / "out"
    assert run(root, base, head, out, "--narration", str(bad), monkeypatch=monkeypatch) == 0
    model = json.loads(next(out.glob("reviews/*/review.json")).read_text(encoding="utf-8"))
    assert model["behavior_analysis"]["status"] == "failed"
    assert next(out.glob("reviews/*/review.html")).is_file()


def test_missing_narration_and_checks_files_are_noted(structured_repository, workdir, monkeypatch, capsys):
    root, base, head = structured_repository
    code = run(root, base, head, workdir / "out", "--narration", str(workdir / "absent.json"),
               "--checks", str(workdir / "absent2.json"), monkeypatch=monkeypatch)
    err = capsys.readouterr().err
    assert code == 0 and "narration not used" in err and "checks not used" in err


@pytest.mark.parametrize("extra", [
    ["--infer", "--narration", "n.json"], ["--comment", "c.md"], ["--view-url", URL],
    ["--comment", "c.md", "--view-url", "javascript:alert(1)"], ["--comment", "c.md", "--view-url", "https://u:p@x.test/"]])
def test_invalid_option_combinations_fail_before_retrieval(extra, monkeypatch):
    monkeypatch.setattr(review_source, "repository_root", lambda *a: pytest.fail("retrieval entered"))
    with pytest.raises(SystemExit) as error:
        main(["--base", "a", "--head", "b", *extra])
    assert error.value.code == 2


def test_title_and_redaction_options(structured_repository, workdir, monkeypatch):
    root, base, head = structured_repository
    out = workdir / "out"
    assert run(root, base, head, out, "--title", "Release 14", "--no-redact", monkeypatch=monkeypatch) == 0
    model = json.loads(next(out.glob("reviews/*/review.json")).read_text(encoding="utf-8"))
    assert model["target"]["title"] == "Release 14" and model["redactions"]["enabled"] is False


def test_hostile_narration_file_never_blocks_the_cli(structured_repository, workdir, monkeypatch):
    root, base, head = structured_repository
    bad = workdir / "narration.json"
    bad.write_text(json.dumps({"behavior_changes": [{"story_id": ["x"]}, "junk", None], "look": "no", "safety": []}), encoding="utf-8")
    assert run(root, base, head, workdir / "out", "--narration", str(bad), monkeypatch=monkeypatch) == 0


def test_redact_env_conflicts_with_no_redact(monkeypatch):
    monkeypatch.setattr(review_source, "repository_root", lambda *a: pytest.fail("retrieval entered"))
    with pytest.raises(SystemExit) as error:
        main(["--base", "a", "--head", "b", "--redact-env", "--no-redact"])
    assert error.value.code == 2
