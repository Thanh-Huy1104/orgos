"""orgos.spawn.redaction — pre-audit scrubbing for secrets and PII.

Every string that goes into the audit trail or into span attributes should
first pass through :func:`scrub`. It applies a set of regex-based scrubbers
targeting the most common leak categories (API keys, JWT, private keys,
Canadian SIN, credit-card, email), and lets consumers register additional
patterns via :func:`add_scrubber`.

The intent is *defense in depth*, not perfect DLP. A determined leaker
can always trip the regex list; this catches the everyday accidents.
"""

from .scrubber import (
    Scrubber,
    add_scrubber,
    luhn_valid,
    remove_scrubber,
    scrub,
    scrub_secrets,
)

__all__ = [
    "Scrubber",
    "add_scrubber",
    "luhn_valid",
    "remove_scrubber",
    "scrub",
    "scrub_secrets",
]
