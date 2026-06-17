"""Deterministic citation verification — the validator tier's ground truth.

The report's lesson: research's signature failure is citation hallucination, and
"always verify citations against the fetched source." An LLM validator that just
*asserts* it checked is not verification. This module re-fetches each cited URL
and grades it — code-enforced, not prompt-trusted (orgos's whole philosophy).

The hard gate is reachability: a fabricated or dead URL (4xx/DNS) is the most
common and most detectable citation failure, and we fail closed on it. Lexical
term-overlap is a softer signal (a real URL whose content doesn't match the
claim) surfaced as "weak" — informational, not a hard fail, because the heuristic
is too crude to confidently reject on its own. Transient errors (timeout, 5xx)
are "uncertain" and never downgrade a run — we don't punish a flaky network.
"""

from __future__ import annotations

import re
from typing import Callable, Literal

from pydantic import BaseModel, Field

# Fetcher contract: (url, timeout) -> (http_status | None, body_text).
Fetcher = Callable[[str, float], "tuple[int | None, str]"]

_URL_RE = re.compile(r"""https?://[^\s)\]}"'<>]+""")
_TRAILING = ".,;:!?)”’'\""  # punctuation that clings to a URL in prose

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "are",
    "but", "not", "you", "your", "its", "their", "they", "them", "was", "were",
    "which", "while", "into", "over", "under", "than", "then", "such", "also",
    "source", "sources", "http", "https", "www", "com", "org", "html",
}


class CitationCheck(BaseModel):
    """The verdict on one cited URL."""

    url: str
    claim: str = ""  # the line/sentence the URL was meant to support
    status: Literal["supported", "weak", "unreachable", "uncertain"]
    term_overlap: float = 0.0
    http_status: int | None = None
    detail: str = ""


class CitationReport(BaseModel):
    checks: list[CitationCheck] = Field(default_factory=list)
    passed: bool = True  # False if any citation is definitively unreachable

    def summary(self) -> str:
        if not self.checks:
            return "no citations found to verify"
        by = {"supported": 0, "weak": 0, "unreachable": 0, "uncertain": 0}
        for c in self.checks:
            by[c.status] += 1
        bad = [c.url for c in self.checks if c.status == "unreachable"]
        line = (
            f"{len(self.checks)} citation(s): {by['supported']} supported, "
            f"{by['weak']} weak, {by['unreachable']} unreachable, "
            f"{by['uncertain']} uncertain"
        )
        if bad:
            line += " | dead/fabricated: " + ", ".join(bad[:5])
        return line


def extract_urls(text: str) -> list[str]:
    """Pull http(s) URLs from text, de-duplicated in first-seen order, with
    clinging trailing punctuation stripped."""
    seen: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(_TRAILING)
        if url not in seen:
            seen.append(url)
    return seen


def _significant_terms(claim: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9.]{3,}", (claim or "").lower())
    return {w for w in words if w not in _STOPWORDS and not w.startswith("http")}


def _line_for_url(text: str, url: str) -> str:
    """The line containing the URL is the claim the citation should support."""
    for line in (text or "").splitlines():
        if url in line:
            return line.replace(url, " ").strip()
    return ""


def _http_fetch(url: str, timeout: float) -> tuple[int | None, str]:
    import httpx

    resp = httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "orgos-citation-verifier/1.0"},
    )
    return resp.status_code, resp.text[:20000]


def verify_citation(
    url: str,
    claim: str = "",
    *,
    fetcher: Fetcher | None = None,
    timeout: float = 10.0,
    overlap_threshold: float = 0.4,
) -> CitationCheck:
    """Re-fetch one URL and grade whether it supports its claim.

    - 4xx → ``unreachable`` (fabricated/dead — the hard-fail case).
    - 5xx / timeout / connection error → ``uncertain`` (transient, no downgrade).
    - 2xx + enough claim terms present → ``supported``; otherwise ``weak``.
    - 2xx with no claim text to match → ``supported`` (reachability is all we can
      check).
    """
    fetch = fetcher or _http_fetch
    try:
        status_code, body = fetch(url, timeout)
    except Exception as exc:  # noqa: BLE001 — any network failure is non-fatal
        return CitationCheck(
            url=url, claim=claim, status="uncertain",
            detail=f"fetch error: {type(exc).__name__}: {exc}"[:200],
        )

    if status_code is not None and 400 <= status_code < 500:
        return CitationCheck(
            url=url, claim=claim, status="unreachable",
            http_status=status_code, detail="client error (dead/fabricated URL)",
        )
    if status_code is not None and status_code >= 500:
        return CitationCheck(
            url=url, claim=claim, status="uncertain",
            http_status=status_code, detail="server error (transient)",
        )

    terms = _significant_terms(claim)
    if not terms:
        return CitationCheck(
            url=url, claim=claim, status="supported", http_status=status_code,
            term_overlap=1.0, detail="reachable; no claim terms to match",
        )

    body_l = body.lower()
    present = sum(1 for t in terms if t in body_l)
    overlap = present / len(terms)
    status: Literal["supported", "weak"] = (
        "supported" if overlap >= overlap_threshold else "weak"
    )
    return CitationCheck(
        url=url, claim=claim, status=status, http_status=status_code,
        term_overlap=round(overlap, 2), detail=f"{present}/{len(terms)} claim terms present",
    )


def verify_text(
    text: str,
    *,
    max_checks: int = 8,
    fetcher: Fetcher | None = None,
    timeout: float = 10.0,
) -> CitationReport:
    """Extract URLs from text and verify each against its surrounding line.

    ``passed`` is False iff any citation is definitively ``unreachable`` — the
    fail-closed gate. Weak/uncertain results are reported but don't fail the run.
    """
    urls = extract_urls(text)[:max_checks]
    checks = [
        verify_citation(u, claim=_line_for_url(text, u), fetcher=fetcher, timeout=timeout)
        for u in urls
    ]
    passed = not any(c.status == "unreachable" for c in checks)
    return CitationReport(checks=checks, passed=passed)
