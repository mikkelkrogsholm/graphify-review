"""Hostile PR text, source, narration and check data must stay inert on the page."""
from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser

import pytest

from graphify_review import review
from graphify_review.review_html import render_review
from graphify_review.review_source import git_target
from tests.helpers import make_repo
from tests.test_structure import structured, structured_repository  # noqa: F401

ALLOWED_TAGS = {"html", "head", "meta", "title", "style", "body", "main", "div", "p", "span", "a", "b", "h1", "h2", "h3",
                "nav", "details", "summary", "ul", "ol", "li", "pre", "code", "small", "strong", "section", "footer",
                "table", "thead", "tbody", "tr", "th", "td", "svg", "title", "defs", "marker", "path", "g", "rect",
                "text", "br"}
PAYLOADS = ["<script>alert(1)</script>", '"><img src=x onerror=alert(1)>', "</style><script>alert(1)</script>",
            "javascript:alert(1)", "<!-- x -->", "&lt;b&gt;", "\u202eevil", "\x00nul", "<svg onload=alert(1)>",
            "' onmouseover='alert(1)"]


class Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.hrefs, self.csp, self.style = [], [], "", ""
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        data = dict(attrs)
        assert not any(key.startswith("on") or key == "style" for key in data), (tag, data)
        if tag == "meta" and (data.get("http-equiv") or "").lower() == "content-security-policy":
            self.csp = str(data["content"])
        if "href" in data:
            self.hrefs.append(data["href"])
        self._in_style = tag == "style"

    def handle_endtag(self, tag):
        self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.style += data


def audit(page: str) -> Audit:
    parser = Audit()
    parser.feed(page)
    assert set(parser.tags) <= ALLOWED_TAGS, set(parser.tags) - ALLOWED_TAGS
    assert all(href.startswith("#") or href.startswith("https://") for href in parser.hrefs), parser.hrefs
    return parser


def test_csp_forbids_everything_but_the_pages_own_style_by_hash(structured):
    parser = audit(render_review(structured))
    digest = base64.b64encode(hashlib.sha256(parser.style.encode()).digest()).decode()
    assert parser.csp == f"default-src 'none'; style-src 'sha256-{digest}'; base-uri 'none'; form-action 'none'"
    assert "unsafe-inline" not in parser.csp and "script-src" not in parser.csp


@pytest.mark.parametrize("payload", PAYLOADS)
def test_hostile_text_never_becomes_markup(structured, payload):
    structured["target"]["title"] = payload
    structured["target"]["description"] = payload
    review.apply_checks(structured, [{"name": payload, "status": "fail", "text": payload}])
    review.apply_narration(structured, {
        "narrator": payload, "headline": payload, "summary": payload, "not_proven": payload,
        "safety": {"level": "safe", "text": payload}, "look": [{"title": payload, "why": payload, "where": payload}],
        "behavior_changes": [{"story_id": structured["stories"][0]["id"], "summary": payload,
                              "before_pseudocode": payload, "after_pseudocode": payload,
                              "evidence_ids": structured["stories"][0]["evidence_ids"], "uncertainties": [payload]}]})
    page = render_review(structured)
    parser = audit(page)
    assert "script" not in parser.tags and "img" not in parser.tags
    assert "<script" not in page and "<img" not in page and "<svg onload" not in page
    assert "\u202e" not in page and "\x00" not in page


def test_no_raw_hostile_tags_survive_anywhere(structured):
    payload = "<script>alert(1)</script><img src=x onerror=alert(1)>"
    structured["target"]["title"] = payload
    review.apply_narration(structured, {"summary": payload, "headline": payload})
    page = render_review(structured)
    assert "<script" not in page and "<img" not in page


def test_bidi_and_zero_width_source_characters_are_made_visible(tmp_path):
    trojan = "def check(user):\n    if user == 'admin\u202e \u2066':\n        return True\n    return False\n"
    root, base, head = make_repo(tmp_path, {"auth.py": "def check(user):\n    return False\n"}, {"auth.py": trojan})
    page = render_review(review.build_review(root, git_target(root, base, head)))
    assert "\u202e" not in page and "\u2066" not in page
    assert "⟦U+202E⟧" in page and "⟦U+2066⟧" in page


def test_hostile_file_and_symbol_names_are_escaped(tmp_path):
    base = {"a.py": "def f():\n    return 1\n"}
    head = {"a.py": "def f():\n    return 2\n", "<script>x</script>.py": "def g():\n    return 1\n"}
    root, b, h = make_repo(tmp_path, base, head)
    page = render_review(review.build_review(root, git_target(root, b, h)))
    audit(page)
    assert "<script>x" not in page and "&lt;script&gt;x" in page


def test_redaction_marks_committed_secrets_and_is_disclosed(tmp_path):
    secret = "ghp_" + "q" * 30
    root, b, h = make_repo(tmp_path, {"cfg.py": "TOKEN_NAME = 'x'\n"},
                           {"cfg.py": f"TOKEN_NAME = 'x'\nGITHUB = '{secret}'\n"})
    model = review.build_review(root, git_target(root, b, h))
    page = render_review(model)
    assert secret not in repr(model) and secret not in page
    assert model["redactions"]["count"] >= 1 and "were redacted" in page
    kept = review.build_review(root, git_target(root, b, h), redact=False)
    assert secret in repr(kept) and kept["redactions"]["enabled"] is False
