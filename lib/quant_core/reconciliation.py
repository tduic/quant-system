"""Position reconciliation logic.

Compares internal portfolio state (from Redis) against exchange-reported
balances (from Coinbase REST API) and flags discrepancies.

This runs as a periodic check, not as a service — called from the
post-trade service on a timer or from a CLI command.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field

from quant_core.models import now_ms

logger = logging.getLogger(__name__)


@dataclass
class PositionDiscrepancy:
    """A mismatch between internal and exchange positions."""

    symbol: str = ""
    internal_quantity: float = 0.0
    exchange_quantity: float = 0.0
    difference: float = 0.0
    difference_pct: float = 0.0
    severity: str = "info"  # info, warning, critical

    def to_json(self) -> str:
        return json.dumps(asdict(self))


@dataclass
class ReconciliationReport:
    """Result of a reconciliation run."""

    timestamp: int = 0
    symbols_checked: int = 0
    discrepancies: list[PositionDiscrepancy] = field(default_factory=list)
    exchange_balances: dict[str, float] = field(default_factory=dict)
    internal_positions: dict[str, float] = field(default_factory=dict)
    status: str = "ok"  # ok, warning, critical
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def reconcile_positions(
    internal_positions: dict[str, float],
    exchange_balances: dict[str, float],
    tolerance_pct: float = 0.01,
) -> ReconciliationReport:
    """Compare internal positions against exchange balances.

    Args:
        internal_positions: symbol -> signed quantity from Redis
        exchange_balances: symbol -> balance from exchange API
        tolerance_pct: acceptable difference as fraction (0.01 = 1%)

    Returns:
        ReconciliationReport with any discrepancies flagged
    """
    all_symbols = set(internal_positions.keys()) | set(exchange_balances.keys())
    discrepancies = []
    worst_severity = "ok"

    for symbol in sorted(all_symbols):
        internal = internal_positions.get(symbol, 0.0)
        exchange = exchange_balances.get(symbol, 0.0)
        diff = abs(internal - exchange)

        if diff == 0.0:
            continue

        reference = max(abs(internal), abs(exchange), 0.0001)
        diff_pct = diff / reference

        if diff_pct <= tolerance_pct:
            severity = "info"
        elif diff_pct <= tolerance_pct * 10:
            severity = "warning"
            if worst_severity == "ok":
                worst_severity = "warning"
        else:
            severity = "critical"
            worst_severity = "critical"

        discrepancies.append(PositionDiscrepancy(
            symbol=symbol,
            internal_quantity=internal,
            exchange_quantity=exchange,
            difference=internal - exchange,
            difference_pct=diff_pct * 100,
            severity=severity,
        ))

    if discrepancies:
        logger.warning(
            "Reconciliation found %d discrepancies (worst=%s)",
            len(discrepancies),
            worst_severity,
        )
        for d in discrepancies:
            logger.warning(
                "  %s: internal=%.8f exchange=%.8f diff=%.8f (%.2f%%) [%s]",
                d.symbol,
                d.internal_quantity,
                d.exchange_quantity,
                d.difference,
                d.difference_pct,
                d.severity,
            )

    return ReconciliationReport(
        timestamp=now_ms(),
        symbols_checked=len(all_symbols),
        discrepancies=discrepancies,
        exchange_balances=exchange_balances,
        internal_positions=internal_positions,
        status=worst_severity,
    )


def fetch_exchange_balances(coinbase_client) -> dict[str, float]:
    """Fetch current balances from Coinbase.

    Returns a dict of symbol -> available balance for non-zero positions.
    """
    try:
        accounts = coinbase_client.get_accounts()
        balances = {}
        for account in accounts.get("accounts", []):
            currency = account.get("currency", "")
            available = float(account.get("available_balance", {}).get("value", 0.0))
            if available != 0.0 and currency != "USD":
                # Normalize to our internal symbol format: "BTC" -> "BTCUSD"
                symbol = f"{currency}USD"
                balances[symbol] = available
        return balances
    except Exception:
        logger.exception("Failed to fetch exchange balances")
        return {}
