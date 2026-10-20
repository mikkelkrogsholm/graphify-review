"""The sole production boundary to the unmodified Graphify distribution.

Corpus filtering and provider calls include version-specific Graphify helpers.
Pin the tested release instead of silently accepting changed extraction rules.
"""
from __future__ import annotations

from importlib import import_module, metadata

SUPPORTED_GRAPHIFY_VERSION = "0.9.92"


class GraphifyCompatibilityError(RuntimeError):
    """The installed graph engine does not match the tested integration."""


def require_supported_graphify() -> str:
    try:
        installed = metadata.version("graphifyy")
    except metadata.PackageNotFoundError as exc:
        raise GraphifyCompatibilityError(
            "Graphify is missing. Install graphify-review with its dependencies."
        ) from exc
    if installed != SUPPORTED_GRAPHIFY_VERSION:
        raise GraphifyCompatibilityError(
            f"Graphify {installed} is installed; this release requires graphifyy=="
            f"{SUPPORTED_GRAPHIFY_VERSION}. Reinstall graphify-review with its dependencies."
        )
    return installed


require_supported_graphify()

from graphify.affected import DEFAULT_AFFECTED_RELATIONS, affected_nodes  # noqa: E402
from graphify.analyze import graph_diff  # noqa: E402
from graphify.build import build_from_json  # noqa: E402
from graphify.callflow_html import stable_ascii_id  # noqa: E402
from graphify.cluster import cluster  # noqa: E402
from graphify.detect import (  # noqa: E402
    FileType, _BUILD_OUTPUT_SUFFIXES, _COVERAGE_ARTIFACT_DIRS, _COVERAGE_ARTIFACT_FILES,
    _is_noise_dir, _is_sensitive, classify_file, ignored_predicate,
)
from graphify.extract import extract  # noqa: E402
from graphify.paths import os_replace_with_fallback, write_text_atomic  # noqa: E402


def inference_api():
    """Load provider support only when inference or provider validation needs it."""
    return import_module("graphify.llm")
