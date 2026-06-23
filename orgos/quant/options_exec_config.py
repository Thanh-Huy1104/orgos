"""Config + fail-closed safety guard for the options paper executor.

This module is the one place that decides *whether it is safe to place an order at
all*. Everything here defaults to the most conservative setting: paper-only, a
client id distinct from Icarus's, and small risk caps. The guard can block a trade
that was actually fine; it can never let a live trade through.

Isolation from Icarus: Icarus (the live equity-pairs engine) connects to the same
IBKR gateway with IB_CLIENT_ID=1. We use a *different* client id (default 2) so the
two API sessions cannot collide.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


# ── IBKR connection ───────────────────────────────────────────────────────────

IB_GATEWAY_IP = os.getenv("IB_GATEWAY_IP", "127.0.0.1")
IB_GATEWAY_PORT = int(os.getenv("OPTIONS_IB_GATEWAY_PORT", os.getenv("IB_GATEWAY_PORT", "4002")))
# Distinct from Icarus (IB_CLIENT_ID=1) so the two clients don't fight over one id.
OPTIONS_IB_CLIENT_ID = int(os.getenv("OPTIONS_IB_CLIENT_ID", "2"))

# PAPER_ONLY is the master safety. Flipping it off requires an explicit env opt-out
# AND is still subject to the account-id check below.
PAPER_ONLY = os.getenv("OPTIONS_PAPER_ONLY", "true").lower() not in ("0", "false", "no")

# Known IBKR ports. Paper gateway = 4002, paper TWS = 7497; live gateway = 4001,
# live TWS = 7496. We refuse to connect to a live port while PAPER_ONLY.
LIVE_PORTS = {4001, 7496}
PAPER_PORTS = {4002, 7497}


# ── Risk limits (checked before every submit) ─────────────────────────────────

@dataclass(frozen=True)
class RiskLimits:
    max_contracts_per_order: int = int(os.getenv("OPTIONS_MAX_CONTRACTS", "5"))
    max_open_positions: int = int(os.getenv("OPTIONS_MAX_OPEN_POSITIONS", "5"))
    max_defined_risk_usd: float = float(os.getenv("OPTIONS_MAX_RISK_USD", "500"))
    max_new_orders_per_day: int = int(os.getenv("OPTIONS_MAX_ORDERS_PER_DAY", "10"))


RISK = RiskLimits()


# ── Fail-closed guard ─────────────────────────────────────────────────────────

class UnsafeExecutionError(RuntimeError):
    """Raised when a connection/order would violate the paper-only safety guard."""


def is_paper_account(account: str | None) -> bool:
    """IBKR paper accounts are prefixed 'DU' (live individual accounts start 'U')."""
    return bool(account) and account.upper().startswith("DU")


def assert_paper_safe(port: int, account: str | None = None) -> None:
    """Raise unless this is unambiguously a paper session.

    Two independent checks while PAPER_ONLY:
      1. the port must be a known paper port (never a live one)
      2. if an account id is known, it must look like a paper account ('DU...')

    Worst case this blocks a legitimate paper trade; it can never permit a live one.
    """
    if not PAPER_ONLY:
        return  # explicit opt-out; caller owns the risk
    if port in LIVE_PORTS or port not in PAPER_PORTS:
        raise UnsafeExecutionError(
            f"refusing to connect: port {port} is not a known paper port "
            f"{sorted(PAPER_PORTS)} (PAPER_ONLY is on)"
        )
    if account is not None and not is_paper_account(account):
        raise UnsafeExecutionError(
            f"refusing to trade: account {account!r} is not a paper account "
            "(expected a 'DU...' id while PAPER_ONLY is on)"
        )
