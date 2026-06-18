"""SEC EDGAR — deterministic filings source for the research gate.

The official, free SEC API (data.sec.gov). Used to answer the one question that
most threatens a pairs trade: is there a pending corporate event that could
*permanently break* the cointegration relationship? Mergers, spinoffs, delistings
and activist stakes are exactly that, and they show up as specific filing forms —
so this is a deterministic early-warning, not an LLM guess.

SEC mandates a descriptive User-Agent with contact info (override via
SEC_EDGAR_UA). The ticker→CIK map is fetched once and cached in-process.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

_TICKER_MAP: dict[str, int] | None = None


def _ua() -> dict[str, str]:
    return {"User-Agent": os.environ.get("SEC_EDGAR_UA", "orgos-quant-desk contact@orgos.local")}


# Filing forms by structural risk to a cointegration relationship.
# HIGH: a corporate action that can permanently break the pair.
_HIGH_RISK_FORMS = {
    "425",        # merger prospectus / business-combination communication
    "S-4",        # registration of securities in M&A
    "DEFM14A", "PREM14A",  # merger proxy
    "SC 13D",     # activist >5% stake (potential breakup pressure)
    "SC 14D9", "SC TO-T", "SC TO-I",  # tender offer
    "15-12B", "15-12G",  # deregistration (going dark)
    "25", "25-NSE",       # delisting notice
}
# MEDIUM: a material event worth a human look (could be anything significant).
_MEDIUM_RISK_FORMS = {"8-K"}


def _norm_form(form: str) -> str:
    return (form or "").strip().upper()


def ticker_to_cik(ticker: str) -> int | None:
    """Resolve a ticker to its SEC CIK (cached map, fetched once)."""
    global _TICKER_MAP
    if _TICKER_MAP is None:
        import httpx

        r = httpx.get("https://www.sec.gov/files/company_tickers.json",
                      headers=_ua(), timeout=20)
        r.raise_for_status()
        _TICKER_MAP = {v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()}
    return _TICKER_MAP.get(ticker.strip().upper())


def recent_filings(ticker: str, *, days: int = 90, limit: int = 40) -> list[dict]:
    """Recent filings for a ticker within `days`, newest first.

    Each item: {form, date, primary_doc, accession}. Returns [] if the ticker
    can't be resolved (caller decides how to treat unknown tickers).
    """
    import httpx

    cik = ticker_to_cik(ticker)
    if cik is None:
        return []
    cik10 = str(cik).zfill(10)
    r = httpx.get(f"https://data.sec.gov/submissions/CIK{cik10}.json",
                  headers=_ua(), timeout=20)
    r.raise_for_status()
    recent = r.json().get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    docs = recent.get("primaryDocument", [])
    accns = recent.get("accessionNumber", [])
    cutoff = dt.date.today() - dt.timedelta(days=days)

    out: list[dict] = []
    for i, form in enumerate(forms):
        try:
            fdate = dt.date.fromisoformat(dates[i])
        except (ValueError, IndexError):
            continue
        if fdate < cutoff:
            continue
        out.append({
            "form": _norm_form(form),
            "date": dates[i],
            "primary_doc": docs[i] if i < len(docs) else "",
            "accession": accns[i] if i < len(accns) else "",
        })
        if len(out) >= limit:
            break
    return out


def assess_filings(filings: list[dict]) -> dict:
    """Classify a filing list into a structural-risk level for cointegration.

    HIGH if any merger/delisting/activist form is present; MEDIUM if any 8-K;
    else LOW. Returns the level plus the specific forms that triggered it.
    """
    high = sorted({f["form"] for f in filings if f["form"] in _HIGH_RISK_FORMS})
    medium = sorted({f["form"] for f in filings if f["form"] in _MEDIUM_RISK_FORMS})
    if high:
        level = "HIGH"
    elif medium:
        level = "MEDIUM"
    else:
        level = "LOW"
    return {"risk": level, "high_forms": high, "medium_forms": medium,
            "n_filings": len(filings)}
