from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class RedactionResult:
    text: str | None
    tags: list[str] = field(default_factory=list)


DEFAULT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    (
        "authorization",
        re.compile(r"(?i)\b(authorization\s*:\s*)(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"),
    ),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    (
        "sensitive-env",
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|KEY)[A-Z0-9_]*\s*[:=]\s*)"
            r"([^\s'\"`;,]+)"
        ),
    ),
    ("url-credentials", re.compile(r"([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@", re.I)),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("cookie", re.compile(r"(?i)\b(cookie\s*:\s*)[^\n\r]+")),
    ("session-id", re.compile(r"(?i)\b(session[_-]?id\s*[:=]\s*)[A-Za-z0-9._~+/=-]{12,}")),
)


def redact_text(text: str | None, custom_regexes: Iterable[str] = ()) -> RedactionResult:
    if text is None:
        return RedactionResult(None, [])
    redacted = text
    tags: list[str] = []
    for tag, pattern in DEFAULT_PATTERNS:
        redacted, changed = _replace(pattern, redacted, tag)
        if changed:
            tags.append(tag)
    for index, regex in enumerate(custom_regexes, start=1):
        pattern = re.compile(regex, re.DOTALL)
        redacted, changed = _replace(pattern, redacted, f"custom-{index}")
        if changed:
            tags.append(f"custom-{index}")
    return RedactionResult(redacted, sorted(set(tags)))


def _replace(pattern: re.Pattern[str], text: str, tag: str) -> tuple[str, bool]:
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        if tag == "authorization" and match.lastindex and match.lastindex >= 1:
            return f"{match.group(1)}[REDACTED:{tag}]"
        if tag == "sensitive-env" and match.lastindex and match.lastindex >= 1:
            return f"{match.group(1)}[REDACTED:{tag}]"
        if tag == "url-credentials" and match.lastindex and match.lastindex >= 1:
            return f"{match.group(1)}[REDACTED:{tag}]@"
        if tag in {"cookie", "session-id"} and match.lastindex and match.lastindex >= 1:
            return f"{match.group(1)}[REDACTED:{tag}]"
        return f"[REDACTED:{tag}]"

    return pattern.sub(repl, text), changed
