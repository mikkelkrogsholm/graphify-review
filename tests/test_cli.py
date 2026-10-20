"""Real standalone entry points and their boundary to an installed engine."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from graphify_review.cli import main
from tests.test_review_source import git, repository  # noqa: F401


@pytest.mark.parametrize("argv", [[], ["--base", "main"], ["--head", "feature"],
    ["0"], ["-1"], ["42", "--base", "main", "--head", "feature"],
    ["42", "--depth", "7"], ["42", "--depth", "-1"],
    ["42", "--backend", "ollama"], ["42", "--model", "test"],
    ["--base", "main", "--head", "feature", "--repo", "owner/repo"],
    ["42", "--infer", "--backend", "unknown-provider"]])
def test_invalid_arguments_fail_before_retrieval(argv, monkeypatch):
    from graphify_review import review_source
    monkeypatch.setattr(review_source, "repository_root", lambda *a: pytest.fail("retrieval entered"))
    with pytest.raises(SystemExit) as error:
        main(argv)
    assert error.value.code == 2


@pytest.mark.parametrize("option", ["--help", "--version"])
def test_help_and_version_do_not_initialize_graphify(option):
    code = (
        "import sys; from graphify_review.cli import main\n"
        f"try: main([{option!r}])\n"
        "except SystemExit as exc: assert exc.code == 0\n"
        "assert not any(m == 'graphify' or m.startswith('graphify.') for m in sys.modules)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "graphify-review" in result.stdout


@pytest.mark.parametrize("stream_encoding", ["utf-8", "cp1252", "ascii"])
def test_module_entry_point_uses_custom_output_and_preserves_project_state(repository, tmp_path, stream_encoding):
    root, base, head = repository
    canonical = root / "graphify-out"
    canonical.mkdir()
    for name in ("graph.json", ".graphify-extract-cache.json", "manifest.json"):
        (canonical / name).write_text(f"existing {name}", encoding="utf-8")
    before = {p.name: p.read_bytes() for p in canonical.iterdir()}
    (root / "auth.py").write_text("DIRTY WORKTREE", encoding="utf-8")
    git(root, "add", "auth.py")
    index = git(root, "diff", "--cached")
    output = tmp_path / "reviews with spaces 漢"
    result = subprocess.run([sys.executable, "-m", "graphify_review", "--base", base,
                             "--head", head, "--output", str(output)], cwd=root,
                            env={**os.environ, "PYTHONIOENCODING": stream_encoding},
                            capture_output=True, text=True, encoding=stream_encoding, timeout=60)
    assert result.returncode == 0, result.stderr
    files = list(output.glob("reviews/*/review.json"))
    assert len(files) == 1
    review = json.loads(files[0].read_text(encoding="utf-8"))
    assert review["target"]["head"] == head
    assert "→" in review["target"]["title"]
    assert review["behavior_analysis"]["status"] == "not_requested"
    assert "DIRTY WORKTREE" not in files[0].read_text(encoding="utf-8")
    assert files[0].with_suffix(".html").exists()
    assert (root / "auth.py").read_text(encoding="utf-8") == "DIRTY WORKTREE"
    assert git(root, "diff", "--cached") == index
    assert git(root, "rev-parse", "HEAD") == head
    assert {p.name: p.read_bytes() for p in canonical.iterdir()} == before


def test_missing_repository_is_a_concise_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["--base", "main", "--head", "feature"]) == 1
    assert "Review failed:" in capsys.readouterr().err
