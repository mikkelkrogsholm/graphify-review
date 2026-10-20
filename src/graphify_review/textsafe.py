"""Helpers for text that cannot be trusted: PR text, source excerpts, external narration.

Control, bidirectional and other invisible format characters are removed from prose
and made visible in source excerpts, so a reviewer sees what a file really contains.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

ELLIPSIS = "…"
_BLANKS = re.compile(r"\n{3,}")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_ZWJ = chr(0x200D)


def _invisible(char: str) -> bool:
    category = unicodedata.category(char)
    return category in ("Cc", "Cs") or (category == "Cf" and char != _ZWJ)


def strip_controls(text: str, *, keep_newlines: bool = False) -> str:
    """Drop control and invisible format characters. A joiner stays for emoji sequences."""
    kept = []
    for char in text:
        if char == "\n" and keep_newlines:
            kept.append(char)
        elif char in "\t\r\f\v\n ":
            kept.append(" ")
        elif not _invisible(char):
            kept.append(char)
    return "".join(kept)


def reveal_invisible(text: str) -> str:
    """Show control and invisible characters (joiners included) as ``⟦U+XXXX⟧``; keep newline and tab."""
    return "".join(f"⟦U+{ord(c):04X}⟧" if c not in "\n\t" and (_invisible(c) or c == _ZWJ) else c for c in text)


def clip(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + ELLIPSIS


def clean(value: object, limit: int, *, multiline: bool = False) -> str:
    """One untrusted value as tidy text; anything that is not a string becomes empty."""
    if not isinstance(value, str):
        return ""
    text = strip_controls(value, keep_newlines=multiline)
    if multiline:
        lines = [_SPACE.sub(" ", line).strip() for line in text.split("\n")]
        text = _BLANKS.sub("\n\n", "\n".join(lines)).strip("\n")
    else:
        text = " ".join(text.split())
    return clip(text, limit)


def safe_url(value: object, limit: int = 500) -> str:
    """The address when it is a plain http(s) address without credentials, else empty."""
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if not url or len(url) > limit or any(ord(c) <= 32 or ord(c) == 127 or _invisible(c) or c in '<>"\\^`{|}' for c in url):
        return ""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not host or parts.username or parts.password:
        return ""
    return url


_CODE_SPAN = re.compile(r"`([^`]+)`")


def markdown_line(text: str, limit: int) -> str:
    """One untrusted line as safe markdown: no HTML, links, images or mentions."""
    text = clip(" ".join(strip_controls(text).split()), limit)
    text = re.sub(r"`{2,}", "'", text)
    if text.count("`") % 2:
        text = text.replace("`", "'")
    out = []
    for index, part in enumerate(_CODE_SPAN.split(text)):
        if index % 2:
            out.append("`" + part.replace("`", "'").replace("<", "‹").replace(">", "›") + "`")
            continue
        part = part.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        part = re.sub(r"([\[\]*_#!|\\~])", r"\\\1", part)
        part = part.replace("://", ":&#8203;//").replace("www.", "www&#8203;.").replace("@", "@&#8203;")
        out.append(part)
    return "".join(out)


def markdown_code(text: str, limit: int) -> str:
    text = clip(" ".join(strip_controls(text).split()), limit)
    return "`" + text.replace("`", "'").replace("<", "‹").replace(">", "›") + "`" if text else ""
