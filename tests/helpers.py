"""Small Git helpers for building tiny repositories in tests."""
from __future__ import annotations

from pathlib import Path

from tests.test_review_source import git


def make_repo(root: Path, base: dict[str, str], head: dict[str, str]) -> tuple[Path, str, str]:
    """Commit ``base`` files, then ``head`` files (deleting base files absent from head)."""
    git(root, "init", "-q")
    git(root, "config", "user.name", "Review tests")
    git(root, "config", "user.email", "review@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    hooks = root / "empty-hooks"
    hooks.mkdir()
    git(root, "config", "core.hooksPath", str(hooks))
    commits = []
    for index, files in enumerate((base, head)):
        for name in set(base) - set(files):
            (root / name).unlink()
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-qm", f"commit {index}")
        commits.append(git(root, "rev-parse", "HEAD"))
    return root, commits[0], commits[1]
