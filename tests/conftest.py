"""Keep test effects inside temporary projects and test-only provider state."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def _can_symlink():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "source"
        path.write_text("test", encoding="utf-8")
        try:
            (Path(directory) / "link").symlink_to(path)
        except (OSError, NotImplementedError):
            return False
        return True


@pytest.fixture
def requires_symlinks(_can_symlink):
    if not _can_symlink:
        pytest.skip("Symlink creation is unavailable on this platform.")


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path_factory, monkeypatch):
    from graphify.llm import backend_detection_env_vars

    home = tmp_path_factory.mktemp("test-home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("GRAPHIFY_NO_AUTO_REFRESH", "1")
    monkeypatch.delenv("GRAPHIFY_REVIEW_OUT", raising=False)
    monkeypatch.delenv("GRAPHIFY_OUT", raising=False)
    for key in backend_detection_env_vars():
        monkeypatch.delenv(key, raising=False)
