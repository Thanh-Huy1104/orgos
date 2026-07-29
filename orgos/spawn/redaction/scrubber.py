"""Regex-based secret and PII scrubbing.

Design decisions:
  - Built-in patterns cover the ~80% case (API keys, tokens, private keys,
    Canadian SIN, credit-card, email). See ``_BUILTINS`` below.
  - Every match becomes a fixed placeholder ``[REDACTED:<kind>]`` so trail
    diffs stay readable and the audit-reader can filter by kind.
  - Consumers can register custom scrubbers with :func:`add_scrubber` — e.g.
    to add project-specific ID formats or internal hostnames.
  - :func:`scrub` is idempotent: running twice yields the same output.
  - Empty and non-string inputs pass through unchanged (avoid raising on
    audit paths where partial data is common).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

Scrubber = Callable[[str], str]


def luhn_valid(digits: str) -> bool:
    """Luhn checksum — validates credit cards AND Canadian SINs.

    Used to keep numeric-pattern rules honest: a 9-digit customer id or a
    13-digit epoch-millisecond timestamp matches the SIN/card *shapes* but
    almost never passes Luhn, so validation cuts the false-positive rate
    from "every long number" to "numbers that really checksum like the
    thing we're protecting". An audit library that scrubs timestamps and
    order ids destroys the trail it exists to keep.
    """
    ds = [int(c) for c in digits if c.isdigit()]
    if not ds:
        return False
    total = 0
    for i, d in enumerate(reversed(ds)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass(frozen=True)
class _Rule:
    kind: str
    pattern: re.Pattern[str]
    # "high" rules are near-zero-false-positive (key formats, PEM blocks) and
    # safe to apply automatically; "low" rules are shape-based PII matchers
    # that can hit legitimate data and are opt-in for automated paths.
    precision: str = "high"
    # Optional post-match validator (receives the matched text); the match is
    # only redacted when it returns True.
    validate: Callable[[str], bool] | None = None

    def apply(self, s: str) -> str:
        placeholder = f"[REDACTED:{self.kind}]"
        if self.validate is None:
            return self.pattern.sub(placeholder, s)
        return self.pattern.sub(
            lambda m: placeholder if self.validate(m.group(0)) else m.group(0), s
        )


# Order matters — more specific patterns run before their more general
# lookalikes so we don't over-redact (e.g. an OpenAI key looks like a
# generic long-token, so we redact it as "openai" first).
_BUILTINS: list[_Rule] = [
    _Rule(
        # Runs before openai_key so `sk-ant-...` gets the more specific label.
        "anthropic_key",
        re.compile(r"sk-ant-(?:api[0-9]{2}|admin[0-9]{2})-[A-Za-z0-9_-]{20,}"),
    ),
    _Rule(
        "openai_key",
        # sk-<48+ base62> or sk-proj-<...>; ``ant-`` is claimed by the anthropic
        # rule above, so exclude that prefix via negative lookahead.
        re.compile(r"sk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{20,}", re.IGNORECASE),
    ),
    _Rule(
        "aws_access_key",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    _Rule(
        "gcp_key",
        re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    ),
    _Rule(
        "github_token",
        # PATs, fine-grained, GHA and app tokens.
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"),
    ),
    _Rule(
        "slack_token",
        re.compile(r"xox[abpors]-[A-Za-z0-9-]{10,}"),
    ),
    _Rule(
        "jwt",
        # header.payload.sig — base64url segments.
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"
        ),
    ),
    _Rule(
        "private_key",
        # PEM blocks — DOTALL so newlines don't stop us. The bare
        # "BEGIN PRIVATE KEY" variant is PKCS#8, OpenSSL's default output.
        re.compile(
            r"-----BEGIN (?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY-----"
            r".*?-----END .*?PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    _Rule(
        "canadian_sin",
        # 9-digit SIN shape, gated by Luhn (SINs checksum) so plain 9-digit
        # ids don't get destroyed.
        re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b"),
        precision="low",
        validate=luhn_valid,
    ),
    _Rule(
        "credit_card",
        # 13-19 digits with optional single separators, gated by Luhn so
        # timestamps and long ids survive.
        re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),
        precision="low",
        validate=luhn_valid,
    ),
    _Rule(
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        precision="low",
    ),
]

_custom_rules: list[_Rule] = []


def add_scrubber(kind: str, pattern: str | re.Pattern[str], *, flags: int = 0) -> None:
    """Register a custom scrubber. ``kind`` shows up as the placeholder label."""
    compiled = pattern if isinstance(pattern, re.Pattern) else re.compile(pattern, flags)
    _custom_rules.append(_Rule(kind, compiled))


def remove_scrubber(kind: str) -> None:
    """Deregister every custom scrubber with the given ``kind``."""
    _custom_rules[:] = [r for r in _custom_rules if r.kind != kind]


def scrub(text: str | None, *, extra: Iterable[Scrubber] = ()) -> str | None:
    """Return ``text`` with all secret/PII matches replaced (both tiers).

    ``extra`` is an optional list of ad-hoc scrubber callables applied
    *after* the built-in and registered rules. Useful for consumer-specific
    transformations that don't warrant a global registration.
    """
    return _apply(text, _BUILTINS, extra)


def scrub_secrets(text: str | None, *, extra: Iterable[Scrubber] = ()) -> str | None:
    """High-precision tier only: API keys, tokens, JWT, private keys.

    This is what automated paths (the audit trail) apply by default —
    near-zero false positives, so forensic data survives. The shape-based
    PII rules (SIN, card, email) are opt-in via :func:`scrub`.
    Custom-registered rules are always applied.
    """
    high = [r for r in _BUILTINS if r.precision == "high"]
    return _apply(text, high, extra)


def _apply(
    text: str | None, rules: list[_Rule], extra: Iterable[Scrubber]
) -> str | None:
    if text is None or not isinstance(text, str) or not text:
        return text
    out = text
    for rule in rules:
        out = rule.apply(out)
    for rule in _custom_rules:
        out = rule.apply(out)
    for fn in extra:
        out = fn(out)
    return out
