"""Phase 11: Deployment & Execution.

Kalshi execution adapter for placing/canceling orders through Abbot.
All execution goes through here — the operator never needs to log into
Kalshi directly for normal operation.

Safety:
  - Only executes for configs in APPROVED status
  - Only executes in PAPER_ONLY, LIVE_SMALL, or LIVE_SCALED modes
  - ANALYSIS_ONLY mode produces signals but never places orders
  - All actions are logged
  - Paper mode simulates execution without real orders

The actual order placement uses the Kalshi SDK's OrdersApi.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from abbot.types import ApprovalStatus, DeploymentMode, MonkConfig

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of an execution attempt."""

    success: bool
    action: str  # "buy", "sell", "cancel", "paper_buy", "paper_sell"
    ticker: str
    side: str
    size: float
    price: float
    order_id: str | None = None
    error: str | None = None
    is_paper: bool = False
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def execute_order(
    config: MonkConfig,
    ticker: str,
    side: str,
    size: float,
    price: float,
) -> ExecutionResult:
    """Execute an order through Abbot.

    Checks approval status and deployment mode before executing.
    Paper mode logs the order without placing it on Kalshi.

    Args:
        config: The Monk config authorizing this trade.
        ticker: Kalshi market ticker.
        side: "yes" or "no".
        size: Number of contracts.
        price: Limit price in dollars.

    Returns:
        ExecutionResult with success/failure status.
    """
    mode = config.deployment.mode
    approval = config.deployment.approval_status

    # --- Safety checks ---
    if approval != ApprovalStatus.APPROVED:
        return ExecutionResult(
            success=False, action="blocked", ticker=ticker, side=side,
            size=size, price=price, error=f"Config not approved (status: {approval.value})",
        )

    if mode == DeploymentMode.ANALYSIS_ONLY:
        return ExecutionResult(
            success=False, action="blocked", ticker=ticker, side=side,
            size=size, price=price, error="ANALYSIS_ONLY mode — no execution",
        )

    # --- Risk checks ---
    max_size = config.risk.max_position_size or 50.0
    if size * price > max_size:
        return ExecutionResult(
            success=False, action="blocked", ticker=ticker, side=side,
            size=size, price=price,
            error=f"Position size ${size * price:.2f} exceeds limit ${max_size:.2f}",
        )

    # --- Paper execution ---
    if mode == DeploymentMode.PAPER_ONLY:
        logger.info(
            "[PAPER] %s %s %.0f @ $%.4f on %s (monk: %s)",
            "BUY" if side == "yes" else "SELL", side, size, price,
            ticker, config.identity.name,
        )
        return ExecutionResult(
            success=True, action=f"paper_{side}",
            ticker=ticker, side=side, size=size, price=price,
            order_id=f"paper-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            is_paper=True,
        )

    # --- Live execution ---
    if mode in (DeploymentMode.LIVE_SMALL, DeploymentMode.LIVE_SCALED):
        return _execute_live(config, ticker, side, size, price)

    return ExecutionResult(
        success=False, action="blocked", ticker=ticker, side=side,
        size=size, price=price, error=f"Unknown mode: {mode.value}",
    )


def cancel_order(config: MonkConfig, order_id: str) -> ExecutionResult:
    """Cancel an existing order."""
    if config.deployment.mode == DeploymentMode.PAPER_ONLY:
        logger.info("[PAPER] Cancel order %s (monk: %s)", order_id, config.identity.name)
        return ExecutionResult(
            success=True, action="cancel", ticker="", side="",
            size=0, price=0, order_id=order_id, is_paper=True,
        )

    try:
        from abbot.kalshi.client import get_kalshi_client
        client = get_kalshi_client()
        client._orders_api.cancel_order(order_id=order_id)

        logger.info("Canceled order %s (monk: %s)", order_id, config.identity.name)
        return ExecutionResult(
            success=True, action="cancel", ticker="", side="",
            size=0, price=0, order_id=order_id,
        )
    except Exception as e:
        logger.error("Failed to cancel %s: %s", order_id, str(e)[:200])
        return ExecutionResult(
            success=False, action="cancel", ticker="", side="",
            size=0, price=0, order_id=order_id, error=str(e)[:200],
        )


def _execute_live(
    config: MonkConfig,
    ticker: str,
    side: str,
    size: float,
    price: float,
) -> ExecutionResult:
    """Place a real order on Kalshi."""
    try:
        from abbot.kalshi.client import get_kalshi_client
        from kalshi_python_sync import CreateOrderRequest

        client = get_kalshi_client()

        # Convert price to cents (Kalshi uses integer cents)
        price_cents = int(price * 100)

        request = CreateOrderRequest(
            ticker=ticker,
            side=side,
            type="limit",
            count=int(size),
            yes_price=price_cents if side == "yes" else None,
            no_price=price_cents if side == "no" else None,
        )

        resp = client._orders_api.create_order(create_order_request=request)

        order_id = resp.order.order_id if resp.order else None

        logger.info(
            "[LIVE] %s %s %.0f @ $%.4f on %s → order %s (monk: %s)",
            "BUY" if side == "yes" else "SELL", side, size, price,
            ticker, order_id, config.identity.name,
        )

        return ExecutionResult(
            success=True, action=side, ticker=ticker, side=side,
            size=size, price=price, order_id=order_id,
        )

    except Exception as e:
        logger.error(
            "Order failed: %s %s %.0f @ $%.4f on %s — %s",
            side, side, size, price, ticker, str(e)[:200],
        )
        return ExecutionResult(
            success=False, action=side, ticker=ticker, side=side,
            size=size, price=price, error=str(e)[:200],
        )
