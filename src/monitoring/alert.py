"""
Alert management system for the AI Trading System V2.

Manages trade execution alerts, stop-loss/take-profit events, system warnings,
and feedback summary notifications. Alerts are persisted in Redis for fast
retrieval and published via Redis Pub/Sub for real-time WebSocket delivery.
"""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.db.connection import get_redis
from src.utils.logger import get_logger

logger = get_logger(__name__)

_REDIS_KEY_ALERTS = "monitoring:alerts"
_REDIS_PUBSUB_CHANNEL = "monitoring:alerts:stream"
_MAX_ALERTS = 500


class AlertManager:
    """Alert lifecycle management.

    Responsibilities:
        - Trade execution alerts (entry/exit)
        - Stop-loss / take-profit events
        - System warnings (failures, quota, etc.)
        - Feedback summary notifications
        - Real-time broadcast via Redis Pub/Sub
    """

    # Severity levels
    SEVERITY_INFO = "info"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"

    # Alert types
    TYPE_TRADE_ENTRY = "trade_entry"
    TYPE_TRADE_EXIT = "trade_exit"
    TYPE_STOP_LOSS = "stop_loss"
    TYPE_TAKE_PROFIT = "take_profit"
    TYPE_TRAILING_STOP = "trailing_stop"
    TYPE_SYSTEM_WARNING = "system_warning"
    TYPE_SYSTEM_ERROR = "system_error"
    TYPE_QUOTA_WARNING = "quota_warning"
    TYPE_FEEDBACK_SUMMARY = "feedback_summary"
    TYPE_ADJUSTMENT_PENDING = "adjustment_pending"
    TYPE_VIX_WARNING = "vix_warning"
    TYPE_DAILY_LOSS = "daily_loss"

    async def send_alert(
        self,
        alert_type: str,
        title: str,
        message: str,
        severity: str = SEVERITY_INFO,
        data: dict[str, Any] | None = None,
    ) -> str:
        """Create and broadcast an alert.

        The alert is stored in a Redis list (capped at _MAX_ALERTS) and
        published to the alerts Pub/Sub channel for real-time consumers.

        Args:
            alert_type: Alert category (use TYPE_* constants).
            title: Short human-readable title.
            message: Detailed alert message.
            severity: One of "info", "warning", "critical".
            data: Optional structured payload.

        Returns:
            The generated alert ID.
        """
        alert_id = str(uuid4())
        alert = {
            "id": alert_id,
            "alert_type": alert_type,
            "title": title,
            "message": message,
            "severity": severity,
            "data": data or {},
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "read": False,
        }

        try:
            redis = get_redis()
            serialized = json.dumps(alert, ensure_ascii=False)

            # Push to list (newest first) and trim to max size
            await redis.lpush(_REDIS_KEY_ALERTS, serialized)
            await redis.ltrim(_REDIS_KEY_ALERTS, 0, _MAX_ALERTS - 1)

            # Publish for real-time consumers
            await redis.publish(_REDIS_PUBSUB_CHANNEL, serialized)

            logger.info(
                "Alert sent | type=%s | severity=%s | title=%s",
                alert_type,
                severity,
                title,
            )
        except Exception as exc:
            logger.error("Failed to send alert: %s", exc)

        return alert_id

    async def get_recent_alerts(
        self,
        limit: int = 50,
        alert_type: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recent alerts from the Redis list.

        Args:
            limit: Maximum number of alerts to return.
            alert_type: Filter by alert type. None for all.
            severity: Filter by severity level. None for all.

        Returns:
            List of alert dictionaries, newest first.
        """
        try:
            redis = get_redis()
            # Fetch more than limit when filtering to account for skipped items
            fetch_count = limit * 3 if (alert_type or severity) else limit
            raw_alerts = await redis.lrange(
                _REDIS_KEY_ALERTS, 0, fetch_count - 1
            )

            alerts: list[dict[str, Any]] = []
            for raw in raw_alerts:
                alert = json.loads(raw)

                if alert_type and alert.get("alert_type") != alert_type:
                    continue
                if severity and alert.get("severity") != severity:
                    continue

                alerts.append(alert)
                if len(alerts) >= limit:
                    break

            return alerts
        except Exception as exc:
            logger.error("Failed to retrieve alerts: %s", exc)
            return []

    async def mark_as_read(self, alert_id: str) -> bool:
        """Mark an alert as read.

        Scans the list to find the matching alert and updates its read flag.

        Args:
            alert_id: The alert ID to mark.

        Returns:
            True if the alert was found and updated.
        """
        try:
            redis = get_redis()
            raw_alerts = await redis.lrange(_REDIS_KEY_ALERTS, 0, -1)

            for i, raw in enumerate(raw_alerts):
                alert = json.loads(raw)
                if alert.get("id") == alert_id:
                    alert["read"] = True
                    updated = json.dumps(alert, ensure_ascii=False)
                    await redis.lset(_REDIS_KEY_ALERTS, i, updated)
                    return True
        except Exception as exc:
            logger.error("Failed to mark alert as read: %s", exc)
        return False

    async def clear_alerts(self) -> int:
        """Delete all alerts from the Redis list.

        Returns:
            Number of alerts that were deleted.
        """
        try:
            redis = get_redis()
            count = await redis.llen(_REDIS_KEY_ALERTS)
            await redis.delete(_REDIS_KEY_ALERTS)
            logger.info("Cleared %d alerts", count)
            return count
        except Exception as exc:
            logger.error("Failed to clear alerts: %s", exc)
            return 0

    async def get_unread_count(self) -> int:
        """Return the number of unread alerts.

        Returns:
            Count of unread alerts.
        """
        try:
            redis = get_redis()
            raw_alerts = await redis.lrange(_REDIS_KEY_ALERTS, 0, -1)
            return sum(
                1 for raw in raw_alerts
                if not json.loads(raw).get("read", False)
            )
        except Exception as exc:
            logger.error("Failed to count unread alerts: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Convenience methods for common alert scenarios
    # ------------------------------------------------------------------

    async def alert_trade_entry(
        self, ticker: str, side: str, quantity: int, price: float
    ) -> str:
        """Send a trade entry alert."""
        return await self.send_alert(
            alert_type=self.TYPE_TRADE_ENTRY,
            title=f"Trade Entry: {ticker}",
            message=(
                f"{side.upper()} {quantity} shares of {ticker} at ${price:.2f}"
            ),
            severity=self.SEVERITY_INFO,
            data={
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "price": price,
            },
        )

    async def alert_trade_exit(
        self,
        ticker: str,
        quantity: int,
        entry_price: float,
        exit_price: float,
        pnl_pct: float,
        reason: str,
    ) -> str:
        """Send a trade exit alert."""
        severity = self.SEVERITY_INFO if pnl_pct >= 0 else self.SEVERITY_WARNING
        return await self.send_alert(
            alert_type=self.TYPE_TRADE_EXIT,
            title=f"Trade Exit: {ticker} ({pnl_pct:+.2f}%)",
            message=(
                f"Closed {quantity} shares of {ticker} | "
                f"Entry ${entry_price:.2f} -> Exit ${exit_price:.2f} | "
                f"PnL: {pnl_pct:+.2f}% | Reason: {reason}"
            ),
            severity=severity,
            data={
                "ticker": ticker,
                "quantity": quantity,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl_pct": pnl_pct,
                "reason": reason,
            },
        )

    async def alert_stop_loss(
        self, ticker: str, price: float, loss_pct: float
    ) -> str:
        """Send a stop-loss trigger alert."""
        return await self.send_alert(
            alert_type=self.TYPE_STOP_LOSS,
            title=f"Stop-Loss: {ticker} ({loss_pct:+.2f}%)",
            message=f"Stop-loss triggered for {ticker} at ${price:.2f}",
            severity=self.SEVERITY_WARNING,
            data={"ticker": ticker, "price": price, "loss_pct": loss_pct},
        )

    async def alert_system_warning(self, title: str, message: str) -> str:
        """Send a system warning alert."""
        return await self.send_alert(
            alert_type=self.TYPE_SYSTEM_WARNING,
            title=title,
            message=message,
            severity=self.SEVERITY_WARNING,
        )

    async def alert_system_error(self, title: str, message: str) -> str:
        """Send a system error (critical) alert."""
        return await self.send_alert(
            alert_type=self.TYPE_SYSTEM_ERROR,
            title=title,
            message=message,
            severity=self.SEVERITY_CRITICAL,
        )
