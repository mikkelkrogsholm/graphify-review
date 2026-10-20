"""Independent CLI; no changes to Graphify's command dispatcher."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

from graphify_review import __version__


def _print_console(message: str, stream: TextIO) -> None:
    """Keep redirected legacy consoles usable; artifacts retain their UTF-8 text."""
    encoding = getattr(stream, "encoding", None) or "utf-8"
    print(message.encode(encoding, errors="backslashreplace").decode(encoding), file=stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="graphify-review",
        description="Human-readable graphs, pseudocode, blast radius, and pinned source evidence.",
    )
    parser.add_argument("number", nargs="?", type=lambda value: int(value.lstrip("#")))
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--repo", "-R", help="GitHub repository for a PR; must match the checkout.")
    parser.add_argument("--base", "-b", help="Local comparison base (requires --head).")
    parser.add_argument("--head", help="Local comparison head; compares from the merge base.")
    parser.add_argument("--infer", action="store_true", help="Request cited behavioral pseudocode.")
    parser.add_argument("--backend", help="Existing Graphify provider (requires --infer).")
    parser.add_argument("--model", help="Model for the selected provider (requires --infer).")
    parser.add_argument("--depth", type=int, default=2, help="Blast-radius depth, 0-6 (default 2).")
    parser.add_argument("--output", type=Path, help="Output root (default: graphify-review-out).")
    args = parser.parse_args(argv)
    if not 0 <= args.depth <= 6:
        parser.error("--depth must be between 0 and 6")
    if args.number is not None and args.number <= 0:
        parser.error("PR number must be positive")
    if args.number is None and not (args.base and args.head):
        parser.error("provide a PR number, or both --base and --head for a local comparison")
    if args.number is not None and (args.base or args.head):
        parser.error("PR comparisons use their pinned base/head; omit --base and --head")
    if (args.backend or args.model) and not args.infer:
        parser.error("--backend/--model require --infer")
    if args.repo and args.number is None:
        parser.error("--repo applies to PR reviews")

    # Imports happen after argument parsing: --help, --version, and invalid
    # options do not initialize Graphify or discover a model backend.
    try:
        from graphify_review.graphify_adapter import inference_api
        from graphify_review.review import build_review, save_review
        from graphify_review.review_source import git_target, pr_target, repository_root

        if args.backend and args.backend not in inference_api().BACKENDS:
            parser.error(f"unknown Graphify backend: {args.backend}")
        root = repository_root(Path.cwd())
        target = pr_target(root, args.number, args.repo) if args.number is not None else git_target(root, args.base, args.head)
        review = build_review(root, target, depth=args.depth, infer=args.infer,
                              backend=args.backend, model=args.model)
        json_path, html_path = save_review(review, root, output=args.output)
    except (RuntimeError, ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        _print_console(f"Review failed: {exc}", sys.stderr)
        return 1
    _print_console(f"Review generated: {target['title']}\nChange stories: {len(review['stories'])}\n"
                   f"Behavior analysis: {review['behavior_analysis']['status']}\nJSON: {json_path}\nHTML: {html_path}",
                   sys.stdout)
    return 0
