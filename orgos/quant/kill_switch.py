"""Kill switch — orgos → Icarus risk halt, the one write into the live system.

Icarus's engine checks Redis `risk:structural_break:{pair_id}` every loop: value
"1" halts the pair (and a read error fail-closes to halt). orgos can SET that
"1" to slam the brake when it detects a relationship breaking under an active
position — but it NEVER clears a halt. Un-halting is a human/Mimir decision.
Halting is the only fail-safe direction: worst case it stops a trade that didn't
need stopping; it can never start or size one.

Everything except `publish_halt` is read-only. `assess_active_pairs` recommends
halts (HIGH-risk SEC filing on a leg of a pair you're actually trading); the
human (or the dashboard button) decides whether to pull the trigger.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import icarus_db
from .sec_edgar import assess_filings, recent_filings

ICARUS_PATH = Path(os.environ.get("ICARUS_PATH", "/home/th/quant-engine"))
RISK_KEY_PREFIX = os.environ.get("RISK_KEY_PREFIX", "risk:structural_break")
HALT_VALUE = "1"

# Dedicated brake for the options paper desk — independent of the equity-pair halts
# above. A structural break on a cointegration pair must NOT block options trading,
# so the options executor reads this key alone.
OPTIONS_HALT_KEY = os.environ.get("OPTIONS_HALT_KEY", "risk:options_halt")


def _redis_config() -> dict:
    """Resolve Redis connection from env, falling back to Icarus's .env."""
    cfg = {
        "host": os.environ.get("REDIS_HOST"),
        "port": os.environ.get("REDIS_PORT"),
        "db": os.environ.get("REDIS_DB"),
        "username": os.environ.get("REDIS_USER"),
        "password": os.environ.get("REDIS_PASSWORD"),
    }
    if not cfg["host"]:
        env = ICARUS_PATH / ".env"
        if env.exists():
            kv = {}
            for line in env.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    kv[k.strip()] = v.strip()
            cfg = {
                "host": kv.get("REDIS_HOST", "127.0.0.1"),
                "port": kv.get("REDIS_PORT", "6379"),
                "db": kv.get("REDIS_DB", "0"),
                "username": kv.get("REDIS_USER") or None,
                "password": kv.get("REDIS_PASSWORD") or None,
            }
    return {"host": cfg["host"] or "127.0.0.1", "port": int(cfg["port"] or 6379),
            "db": int(cfg["db"] or 0), "username": cfg["username"], "password": cfg["password"]}


def _redis_client():
    import redis  # sync client (orgos isn't async)

    c = _redis_config()
    return redis.Redis(host=c["host"], port=c["port"], db=c["db"],
                       username=c["username"], password=c["password"],
                       decode_responses=True, socket_timeout=5)


def halt_state() -> dict[int, bool]:
    """Current kill-switch state per active pair_id (True = halted). Read-only."""
    pairs = icarus_db.active_pairs()
    client = _redis_client()
    out: dict[int, bool] = {}
    try:
        for p in pairs:
            val = client.get(f"{RISK_KEY_PREFIX}:{p['pair_id']}")
            out[p["pair_id"]] = (val == HALT_VALUE)
    finally:
        client.close()
    return out


def options_halt_state() -> bool:
    """True if the dedicated options-desk halt is set. Read-only.

    Independent of pair halts: an equity-pair structural break does not stop options.
    """
    client = _redis_client()
    try:
        return client.get(OPTIONS_HALT_KEY) == HALT_VALUE
    finally:
        client.close()


def publish_options_halt(reason: str) -> dict:
    """SET the dedicated options-desk halt (set-only, like publish_halt)."""
    client = _redis_client()
    try:
        client.set(OPTIONS_HALT_KEY, HALT_VALUE)
    finally:
        client.close()
    return {"halted": True, "key": OPTIONS_HALT_KEY, "reason": reason,
            "note": "orgos sets halts only; clear the key manually to resume"}


def publish_halt(pair_id: int, reason: str) -> dict:
    """SET the kill switch for one pair (the one write orgos makes). Set-only."""
    client = _redis_client()
    try:
        client.set(f"{RISK_KEY_PREFIX}:{pair_id}", HALT_VALUE)
    finally:
        client.close()
    return {"pair_id": pair_id, "halted": True, "key": f"{RISK_KEY_PREFIX}:{pair_id}",
            "reason": reason, "note": "orgos sets halts only; un-halt in Icarus/Mimir"}


def assess_active_pairs(*, days: int = 30) -> dict:
    """Recommend halts for active pairs with a HIGH-risk SEC filing on a leg.

    Read-only. For each pair Icarus is trading, check both legs' recent filings;
    a HIGH-risk form (merger/delisting/activist) on a leg is exactly the
    structural break that voids a cointegration relationship → recommend halt.
    Also reports the current halt state. Recommends; does not act.
    """
    pairs = icarus_db.active_pairs()
    try:
        state = halt_state()
    except Exception:  # noqa: BLE001 — Redis may be down; still return SEC assessment
        state = {}

    assessments = []
    for p in pairs:
        legs = {}
        worst = "LOW"
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        for leg in (p["y"], p["x"]):
            # crypto legs won't resolve to a CIK; recent_filings returns [] → LOW
            a = assess_filings(recent_filings(leg, days=days))
            legs[leg] = a
            if order[a["risk"]] > order[worst]:
                worst = a["risk"]
        assessments.append({
            "pair_id": p["pair_id"], "pair": p["pair"],
            "structural_risk": worst,
            "recommend_halt": worst == "HIGH" and not state.get(p["pair_id"], False),
            "already_halted": state.get(p["pair_id"], False),
            "leg_filings": legs,
        })

    to_halt = [a for a in assessments if a["recommend_halt"]]
    return {
        "active_pairs": assessments,
        "recommend_halt": to_halt,
        "summary": (
            f"{len(assessments)} active pair(s); {len(to_halt)} recommended for halt; "
            f"{sum(1 for a in assessments if a['already_halted'])} already halted."
        ),
    }
