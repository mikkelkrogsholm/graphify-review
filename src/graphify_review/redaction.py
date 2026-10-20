"""Best-effort removal of secret-looking values from review output.

A safety net, not a reason to commit secrets. Replacements never change the number of
lines, so cited source ranges stay consistent. Patterns are bounded so hostile input
cannot make redaction slow. Values of secret-named environment variables are only
redacted when the caller passes ``environ`` explicitly, because that makes output
depend on the machine.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_BEGIN = re.compile(r"-----BEGIN [A-Z ]{0,30}PRIVATE KEY-----")
_END = re.compile(r"-----END [A-Z ]{0,30}PRIVATE KEY-----")
_BODY_LINE = re.compile(r"[A-Za-z0-9+/]{60,76}={0,2}")
_BODY_RUN = 3
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cloud key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("token", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer token", re.compile(r"(?i)\b(bearer\s{1,8})[A-Za-z0-9._~+/=-]{16,}")),
    ("url credentials", re.compile(r"(?i)\b([a-z][a-z0-9+.-]{0,31}://)[^\s/@:]{1,200}:[^\s/@]{1,200}@")),
    ("assigned secret", re.compile(
        r"""(?i)((?:password|passwd|secret|token|api[_-]?key|private[_-]?key)[A-Za-z0-9_.-]{0,64}"""
        r"""\s{0,8}[:=]\s{0,8})(["'])([^"'\n]{6,200})\2""")),
)
_SECRET_ENV = re.compile(r"(?i)(secret|token|passw|credential|api[_-]?key|private[_-]?key)")
_MIN_ENV_VALUE = 8


class Redactor:
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self.values = sorted({v for k, v in (environ or {}).items()
                              if _SECRET_ENV.search(k) and len(v) >= _MIN_ENV_VALUE and "\n" not in v},
                             key=len, reverse=True)
        self.counts: dict[str, int] = {}

    def _note(self, kind: str) -> str:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        return f"[redacted: {kind}]"

    def _private_keys(self, value: str, *, diff: bool = False) -> str:
        """Handle cut key blocks; ignore diff markers for detection and retain them in output."""
        if "PRIVATE KEY" not in value and not _BODY_LINE.search(value):
            return value
        lines = value.split("\n")

        def body(line: str) -> str:
            return (line[1:] if diff and line[:1] in (" ", "+", "-") else line).strip()

        def replacement(line: str) -> str:
            prefix = line[:1] if diff and line[:1] in (" ", "+", "-") else ""
            return prefix + self._note("private key")

        out: list[str] = []
        inside = False
        index = 0
        while index < len(lines):
            line = lines[index]
            if inside:
                out.append(replacement(line))
                inside = not _END.search(line)
            elif _BEGIN.search(line):
                out.append(replacement(line))
                inside = not _END.search(line)
            elif _BODY_LINE.fullmatch(body(line)):
                run = index
                while run < len(lines) and _BODY_LINE.fullmatch(body(lines[run])):
                    run += 1
                if run - index >= _BODY_RUN:
                    out.extend(replacement(item) for item in lines[index:run])
                    index = run
                    continue
                out.append(line)
            else:
                out.append(line)
            index += 1
        return "\n".join(out)

    def text(self, value: str, *, diff: bool = False) -> str:
        value = self._private_keys(value, diff=diff)
        for kind, pattern in _PATTERNS:
            if kind in ("bearer token", "url credentials"):
                value = pattern.sub(lambda m, k=kind: m.group(1) + self._note(k) + ("@" if k == "url credentials" else ""), value)
            elif kind == "assigned secret":
                value = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{self._note('assigned secret')}{m.group(2)}", value)
            else:
                value = pattern.sub(lambda m, k=kind: self._note(k), value)
        for secret in self.values:
            if secret in value:
                value = value.replace(secret, self._note("environment secret"))
        return value

    def walk(self, value: Any) -> Any:
        """Redact every string in nested lists and dicts; keys are left alone."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.walk(item) for item in value]
        if isinstance(value, dict):
            return {key: self.text(item, diff=True) if key == "patch" and isinstance(item, str) else self.walk(item)
                    for key, item in value.items()}
        return value

    def summary(self) -> dict:
        return {"count": sum(self.counts.values()), "kinds": dict(sorted(self.counts.items()))}
