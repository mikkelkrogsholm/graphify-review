"""Compatibility is checked against the stock installed Graphify package."""
from __future__ import annotations

import ast
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import graphify
import pytest

from graphify_review import graphify_adapter as adapter
from graphify_review.cli import main


def test_published_graphify_is_used_without_the_contribution_modules():
    assert adapter.require_supported_graphify() == "0.9.92"
    # The development checkout must never satisfy the engine dependency.
    assert "site-packages" in Path(graphify.__file__).parts
    assert "graphify_review" not in str(Path(graphify.__file__).parent)


def test_only_adapter_imports_graphify_in_production():
    source = Path(__file__).parents[1] / "src" / "graphify_review"
    for path in source.glob("*.py"):
        if path.name == "graphify_adapter.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module == "graphify" or (node.module or "").startswith("graphify."))
            if isinstance(node, ast.Import):
                assert all(n.name != "graphify" and not n.name.startswith("graphify.") for n in node.names)


def test_unsupported_engine_fails_with_reinstall_instruction(monkeypatch):
    monkeypatch.setattr(adapter.metadata, "version", lambda *args: "9.0.0")
    with pytest.raises(adapter.GraphifyCompatibilityError, match="requires graphifyy==0.9.92"):
        adapter.require_supported_graphify()


def test_missing_engine_fails_with_install_instruction(monkeypatch):
    def absent(*args):
        raise metadata.PackageNotFoundError("graphifyy")
    monkeypatch.setattr(adapter.metadata, "version", absent)
    with pytest.raises(adapter.GraphifyCompatibilityError, match="Graphify is missing"):
        adapter.require_supported_graphify()


def test_cli_reports_engine_compatibility_errors(monkeypatch, capsys):
    from graphify_review import review_source
    def unsupported(*args):
        raise adapter.GraphifyCompatibilityError("unsupported test engine")
    monkeypatch.setattr(review_source, "repository_root", unsupported)
    assert main(["--base", "main", "--head", "feature"]) == 1
    assert "unsupported test engine" in capsys.readouterr().err


def test_cli_handles_version_mismatch_during_first_engine_import():
    code = (
        "from importlib import metadata\n"
        "metadata.version = lambda name: '9.0.0'\n"
        "from graphify_review.cli import main\n"
        "raise SystemExit(main(['--base', 'main', '--head', 'feature']))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert "requires graphifyy==0.9.92" in result.stderr
    assert "Traceback" not in result.stderr
