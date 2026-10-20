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


MAX_INPUT_BYTES = 1_000_000


def _read_json(path: Path) -> tuple[object | None, str]:
    """A bounded JSON input, or (None, why). Untrusted: never raises on content."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_INPUT_BYTES + 1)
    except OSError as exc:
        return None, f"cannot read {path.name} ({type(exc).__name__})"
    if len(raw) > MAX_INPUT_BYTES:
        return None, f"{path.name} is larger than {MAX_INPUT_BYTES} bytes"
    try:
        return json.loads(raw.decode("utf-8")), ""
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, f"{path.name} is not valid UTF-8 JSON"


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
    parser.add_argument("--title", help="Review title (default: derived from the target).")
    parser.add_argument("--facts", type=Path, metavar="FILE", help="Also write the structural facts as JSON.")
    parser.add_argument("--evidence", type=Path, metavar="FILE",
                        help="Also write bounded cited evidence and the narration contract as JSON.")
    parser.add_argument("--narration", type=Path, metavar="FILE",
                        help="Attach an explanation written elsewhere (validated, labeled model-written).")
    parser.add_argument("--checks", type=Path, metavar="FILE",
                        help="JSON verdicts of checks, tester and reviewer, shown on the page.")
    parser.add_argument("--comment", type=Path, metavar="FILE",
                        help="Also write a short markdown comment that links to the page (needs --view-url).")
    parser.add_argument("--view-url", help="Address of the published page, used by --comment.")
    parser.add_argument("--no-redact", action="store_true",
                        help="Keep secret-looking values (redacted by default) in the outputs.")
    parser.add_argument("--redact-env", action="store_true",
                        help="Also redact values of secret-named environment variables (output then depends on the machine).")
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
    if args.infer and args.narration:
        parser.error("--infer and --narration are alternatives; choose one source of explanations")
    if args.redact_env and args.no_redact:
        parser.error("--redact-env cannot be combined with --no-redact")
    if bool(args.comment) != bool(args.view_url):
        parser.error("--comment and --view-url go together")
    if args.view_url:
        from graphify_review.textsafe import safe_url
        if not safe_url(args.view_url):
            parser.error("--view-url must be a plain http or https address without credentials")

    # Imports happen after argument parsing: --help, --version, and invalid
    # options do not initialize Graphify or discover a model backend.
    try:
        from graphify_review.graphify_adapter import inference_api
        from graphify_review.review import (
            apply_checks, apply_narration, build_review, save_review, write_output,
        )
        from graphify_review.review_documents import (
            dump, evidence_document, facts_document, render_comment,
        )
        from graphify_review.review_source import git_target, pr_target, repository_root

        if args.backend and args.backend not in inference_api().BACKENDS:
            parser.error(f"unknown Graphify backend: {args.backend}")
        root = repository_root(Path.cwd())
        target = pr_target(root, args.number, args.repo) if args.number is not None else git_target(root, args.base, args.head)
        review = build_review(root, target, depth=args.depth, infer=args.infer,
                              backend=args.backend, model=args.model, title=args.title,
                              redact=not args.no_redact, redact_env=args.redact_env)
        notes = []
        if args.checks:
            data, why = _read_json(args.checks)
            if data is None:
                notes.append(f"checks not used: {why}")
            else:
                apply_checks(review, data)
        if args.narration:
            data, why = _read_json(args.narration)
            if data is None:
                notes.append(f"narration not used: {why}")
            apply_narration(review, data)
        json_path, html_path = save_review(review, root, output=args.output)
        for option, path, build in (("facts", args.facts, lambda: facts_document(review)),
                                    ("evidence", args.evidence, lambda: evidence_document(review))):
            if path:
                write_output(path, dump(build()))
        if args.comment:
            write_output(args.comment, render_comment(review, args.view_url))
        for note in notes:
            _print_console(f"Note: {note}", sys.stderr)
    except (RuntimeError, ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        _print_console(f"Review failed: {exc}", sys.stderr)
        return 1
    extra = "".join(f"\n{label}: {path}" for label, path in (
        ("Facts", args.facts), ("Evidence", args.evidence), ("Comment", args.comment)) if path)
    _print_console(f"Review generated: {review['target']['title']}\nChange stories: {len(review['stories'])}\n"
                   f"Risk: {review['structure']['risk']['level']}\n"
                   f"Behavior analysis: {review['behavior_analysis']['status']}\nJSON: {json_path}\nHTML: {html_path}{extra}",
                   sys.stdout)
    return 0
