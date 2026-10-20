"""Untrusted text: invisible characters, URLs, markdown, and secret redaction."""
from __future__ import annotations

import re

import pytest

from graphify_review.redaction import Redactor
from graphify_review.textsafe import (
    clean, clip, markdown_code, markdown_line, reveal_invisible, safe_url, strip_controls,
)


def test_controls_and_bidi_are_dropped_but_emoji_joiners_stay():
    assert strip_controls("a\x00b\u202ec\u2066d\x1b[31me") == "abcd[31me"
    assert strip_controls("\U0001F469\N{ZERO WIDTH JOINER}\U0001F4BB") == "\U0001F469\N{ZERO WIDTH JOINER}\U0001F4BB"
    assert clean("  two   words\n\tnext ", 50) == "two words next"
    assert clean(None, 10) == "" and clean(5, 10) == ""
    assert clip("abcdefghij", 5) == "abcd…"


def test_multiline_clean_keeps_at_most_one_blank_line():
    assert clean("a\n\n\n\nb\r\nc", 50, multiline=True) == "a\n\nb\nc"


def test_invisible_characters_are_revealed_not_hidden():
    assert reveal_invisible("if (x) {\u202e}\n\tok") == "if (x) {⟦U+202E⟧}\n\tok"
    assert reveal_invisible("a\u200bb") == "a⟦U+200B⟧b"
    assert reveal_invisible("a" + chr(0x200D) + "b") == "a⟦U+200D⟧b"


@pytest.mark.parametrize("url,expected", [
    ("https://example.test/p/1", True), ("http://host:8080/a?b=c#d", True),
    ("javascript:alert(1)", False), ("data:text/html,x", False), ("//evil.test/x", False),
    ("/relative", False), ("https://user:pw@example.test/", False), ("https://exa mple.test/", False),
    ("https://example.test/<x>", False), ("https://example.test:99999/", False), ("ftp://example.test/", False),
    ("https://", False), ("", False)])
def test_only_plain_http_urls_are_links(url, expected):
    assert bool(safe_url(url)) is expected


@pytest.mark.parametrize("payload", [
    "<script>alert(1)</script>", "[click](http://evil.test)", "![i](http://evil.test/p.png)", "@everyone",
    "http://evil.test www.evil.test", "<!-- graphify-review -->", "```\nfence", "a | b * c _ d # e",
    "<img src=x onerror=alert(1)>"])
def test_markdown_lines_have_no_html_links_images_or_mentions(payload):
    text = markdown_line(payload, 300)
    assert "<" not in text and ">" not in text
    assert not re.search(r"(?<!\\)\]\(", text) and not re.search(r"(?<!\\)!\[", text)
    assert "http://evil.test" not in text and "www.evil" not in text
    assert "@everyone" not in text
    assert "```" not in text and "\n" not in text


def test_code_spans_cannot_be_closed_early():
    assert markdown_code("a`b<c>", 50) == "`a'b‹c›`"
    assert markdown_line("use `x` and `y", 50).count("`") % 2 == 0


def test_secret_redaction_formats_and_line_counts():
    redactor = Redactor({})
    key = "-----BEGIN RSA PRIVATE KEY-----\nAAAA\nBBBB\n-----END RSA PRIVATE KEY-----"
    text = redactor.text(f"{key}\nnext")
    assert text.count("\n") == key.count("\n") + 1 and "AAAA" not in text
    cases = ["AKIAABCDEFGHIJKLMNOP", "ghp_" + "a" * 30, "glpat-" + "b" * 24, "sk-" + "c" * 30,
             "eyJabcdefgh.eyJabcdefgh.abcdefghij", "Authorization: Bearer abcdefghijklmnop1234",
             "https://user:hunter2@example.test/x", 'password = "hunter2hunter2"', "api_key: 'abcdef123456'"]
    for case in cases:
        assert "[redacted" in redactor.text(case), case
    assert redactor.text("totally ordinary text 12345") == "totally ordinary text 12345"
    assert redactor.summary()["count"] >= len(cases) + 1


def test_environment_secret_values_are_redacted_by_name_only():
    redactor = Redactor({"DEPLOY_TOKEN": "s3cr3t-value-123", "EDITOR": "vim-is-nice-123", "SHORT_TOKEN": "abc"})
    assert redactor.text("x s3cr3t-value-123 y") == "x [redacted: environment secret] y"
    assert redactor.text("vim-is-nice-123 abc") == "vim-is-nice-123 abc"


def test_walk_redacts_nested_strings_without_changing_keys_or_numbers():
    redactor = Redactor({})
    value = {"a": ["ghp_" + "x" * 30, 3, {"b": 'secret = "abcdefghi"'}], "ghp_" + "y" * 30: 1}
    out = redactor.walk(value)
    assert "ghp_" not in out["a"][0] and out["a"][1] == 3 and "[redacted" in out["a"][2]["b"]
    assert any(key.startswith("ghp_") for key in out)


@pytest.mark.parametrize("payload", ["a." * 100_000, "a-" * 100_000, "password" * 100_000, "token:" * 100_000,
                                     "-----BEGIN PRIVATE KEY-----\n" * 20_000, "x://" * 50_000, "bearer " * 30_000])
def test_hostile_input_cannot_make_redaction_slow(payload):
    import time
    started = time.monotonic()
    Redactor().text(payload)
    assert time.monotonic() - started < 5


def test_private_key_without_end_or_header_is_still_redacted():
    redactor = Redactor()
    body = "\n".join("A" * 64 for _ in range(5))
    assert "AAAA" not in redactor.text(body)
    assert redactor.text(body).count("\n") == 4
    cut = "-----BEGIN PRIVATE KEY-----\nQUJD\nREVG\nmore text after"
    assert "QUJD" not in redactor.text(cut) and redactor.text(cut).count("\n") == 3
    assert redactor.text("A" * 64 + "\nordinary line") == "A" * 64 + "\nordinary line"  # a single line is kept


@pytest.mark.parametrize("prefix", ["-", "+", " "])
@pytest.mark.parametrize("width", [64, 76])
def test_body_only_private_keys_are_redacted_in_patches(prefix, width):
    body = "\n".join(prefix + letter * width for letter in "ABC")
    value = {"source": {"patch": "@@ -20,3 +20,3 @@\n" + body}}
    output = Redactor().walk(value)["source"]["patch"]
    assert not any(letter * width in output for letter in "ABC")
    assert output.split("\n")[1:] == [prefix + "[redacted: private key]"] * 3
    assert output.count("\n") == 3


def test_environment_values_are_not_read_unless_asked(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_HELPER", "development-value")
    assert Redactor().text("development-value") == "development-value"
    assert "redacted" in Redactor({"CREDENTIAL_HELPER": "development-value"}).text("development-value")


def test_view_urls_cannot_hide_invisible_characters():
    assert safe_url("https://example.test/a\u202eb") == "" and safe_url("https://example.test/a\u200bb") == ""
