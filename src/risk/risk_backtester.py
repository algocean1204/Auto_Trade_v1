"""
리스크 백테스터 모듈 (Addendum 26)

과거 거래 데이터를 기반으로 리스크 규칙의 효과를 시뮬레이션한다.
대안 시나리오(더 엄격한/느슨한 규칙)를 비교하여 최적 설정을 제안한다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, func, select

from src.db.connection import get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RiskBacktester:
    """리스크 규칙의 과거 효과를 백테스트한다.

    과거 거래 데이터에 현재/대안 리스크 규칙을 적용하여
    실제 결과와 가상 결과를 비교한다.

    Attributes:
        lookback_days: 백테스트 기간 (일).
    """

    def __init__(self, lookback_days: int = 30) -> None:
        """RiskBacktester를 초기화한다.

        Args:
            lookback_days: 백테스트 기간.
        """
        self.lookback_days = lookback_days
        logger.info("RiskBacktester 초기화 | lookback=%dd", lookback_days)

    async def run_backtest(
        self,
        scenarios: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """백테스트를 실행한다.

        Args:
            scenarios: 시나리오 목록. None이면 기본 3개 시나리오 사용.

        Returns:
            백테스트 결과 딕셔너리.
        """
        try:
            # 과거 거래 데이터 로드
            trades = await self._load_trades()
            if not trades:
                return {
                    "status": "no_data",
                    "message": "백테스트할 거래 데이터 없음",
                }

            # 기본 시나리오
            if scenarios is None:
                scenarios = [
                    {
                        "name": "현재 설정",
                        "daily_loss_limit_pct": -2.0,
                        "stop_loss_pct": -5.0,
                        "trailing_stop_pct": -3.0,
                        "max_positions": 3,
                    },
                    {
                        "name": "보수적 대안",
                        "daily_loss_limit_pct": -1.5,
                        "stop_loss_pct": -3.0,
                        "trailing_stop_pct": -2.0,
                        "max_positions": 2,
                    },
                    {
                        "name": "적극적 대안",
                        "daily_loss_limit_pct": -3.0,
                        "stop_loss_pct": -7.0,
                        "trailing_stop_pct": -4.0,
                        "max_positions": 4,
                    },
                ]

            results: list[dict[str, Any]] = []
            for scenario in scenarios:
                sim_result = self._simulate_scenario(trades, scenario)
                results.append(sim_result)

            # 최적 시나리오 선정 (Sharpe ratio 기준)
            best = max(results, key=lambda r: r.get("sharpe_ratio", -999))

            backtest_result = {
                "status": "completed",
                "period_days": self.lookback_days,
                "total_trades": len(trades),
                "scenarios": results,
                "best_scenario": best["name"],
                "run_at": datetime.now(tz=timezone.utc).isoformat(),
            }

            # 결과 DB 저장
            await self._save_result(backtest_result)

            logger.info(
                "백테스트 완료 | trades=%d | scenarios=%d | best=%s",
                len(trades),
                len(results),
                best["name"],
            )

            return backtest_result
        except Exception as e:
            logger.error("백테스트 실행 실패: %s", e)
            return {"status": "error", "error": str(e)}

    def _simulate_scenario(
        self, trades: list[dict[str, Any]], scenario: dict[str, Any]
    ) -> dict[str, Any]:
        """특정 시나리오로 거래를 시뮬레이션한다.

        Args:
            trades: 과거 거래 데이터.
            scenario: 시나리오 설정.

        Returns:
            시뮬레이션 결과.
        """
        name = scenario.get("name", "unknown")
        daily_loss_limit = scenario.get("daily_loss_limit_pct", -2.0)
        stop_loss_pct = scenario.get("stop_loss_pct", -5.0)
        trailing_stop_pct = scenario.get("trailing_stop_pct", -3.0)

        total_pnl = 0.0
        wins = 0
        losses = 0
        blocked_trades = 0
        daily_pnl: dict[str, float] = {}
        daily_returns: list[float] = []

        current_daily_pnl = 0.0
        current_date_str = ""

        for trade in trades:
            trade_date = str(trade.get("date", ""))
            pnl_pct = trade.get("pnl_pct", 0.0) or 0.0
            pnl_amount = trade.get("pnl_amount", 0.0) or 0.0

            # 날짜 변경 시 리셋
            if trade_date != current_date_str:
                if current_date_str:
                    daily_pnl[current_date_str] = current_daily_pnl
                    daily_returns.append(current_daily_pnl)
                current_date_str = trade_date
                current_daily_pnl = 0.0

            # 일일 손실 한도 체크
            if current_daily_pnl <= daily_loss_limit:
                blocked_trades += 1
                continue

            # 스톱로스 적용
            adjusted_pnl = pnl_amount
            if pnl_pct < stop_loss_pct:
                # 스톱이 발동했으면 스톱 수준으로 제한
                adjusted_pnl = pnl_amount * (stop_loss_pct / pnl_pct) if pnl_pct != 0 else pnl_amount

            total_pnl += adjusted_pnl
            current_daily_pnl += adjusted_pnl

            if adjusted_pnl >= 0:
                wins += 1
            else:
                losses += 1

        # 마지막 날 포함
        if current_date_str:
            daily_pnl[current_date_str] = current_daily_pnl
            daily_returns.append(current_daily_pnl)

        total_trades = wins + losses
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

        # Sharpe ratio 계산 (간이)
        if daily_returns and len(daily_returns) > 1:
            import statistics
            mean_return = statistics.mean(daily_returns)
            std_return = statistics.stdev(daily_returns)
            sharpe_ratio = (mean_return / std_return) if std_return > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # 최대 drawdown 계산
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for ret in daily_returns:
            cumulative += ret
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_drawdown:
                max_drawdown = dd

        return {
            "name": name,
            "settings": scenario,
            "total_pnl_usd": round(total_pnl, 2),
            "total_trades": total_trades,
            "blocked_trades": blocked_trades,
            "win_rate_pct": round(win_rate, 2),
            "sharpe_ratio": round(sharpe_ratio, 4),
            "max_drawdown_usd": round(max_drawdown, 2),
        }

    async def _load_trades(self) -> list[dict[str, Any]]:
        """과거 거래 데이터를 DB에서 로드한다.

        Returns:
            거래 데이터 리스트.
        """
        try:
            from src.db.models import Trade

            since = datetime.now(tz=timezone.utc) - timedelta(days=self.lookback_days)

            async with get_session() as session:
                stmt = (
                    select(Trade)
                    .where(
                        and_(
                            Trade.exit_at >= since,
                            Trade.exit_price.isnot(None),
                        )
                    )
                    .order_by(Trade.exit_at.asc())
                )
                result = await session.execute(stmt)
                trades = result.scalars().all()

                return [
                    {
                        "id": str(t.id),
                        "ticker": t.ticker,
                        "pnl_pct": t.pnl_pct,
                        "pnl_amount": t.pnl_amount,
                        "date": str(t.exit_at.date()) if t.exit_at else "",
                        "entry_price": t.entry_price,
                        "exit_price": t.exit_price,
                    }
                    for t in trades
                ]
        except Exception as e:
            logger.error("거래 데이터 로드 실패: %s", e)
            return []

    async def _save_result(self, result: dict[str, Any]) -> None:
        """백테스트 결과를 DB에 저장한다.

        BacktestResult 모델: run_date, params(JSONB), total_return,
        max_drawdown, sharpe_ratio, win_rate, recommendation.
        """
        try:
            from src.db.models import BacktestResult

            best = result.get("best_scenario", "")
            scenarios = result.get("scenarios", [])
            best_scenario = next(
                (s for s in scenarios if s.get("name") == best), {}
            )

            async with get_session() as session:
                record = BacktestResult(
                    run_date=date.today(),
                    params={"scenarios": scenarios, "type": "risk"},
                    total_return=best_scenario.get("total_pnl_usd"),
                    max_drawdown=best_scenario.get("max_drawdown_usd"),
                    sharpe_ratio=best_scenario.get("sharpe_ratio"),
                    win_rate=best_scenario.get("win_rate_pct"),
                    recommendation=f"최적 시나리오: {best}",
                )
                session.add(record)
        except Exception as e:
            logger.warning("백테스트 결과 저장 실패: %s", e)

    async def get_latest_result(self) -> dict[str, Any] | None:
        """최신 백테스트 결과를 조회한다.

        Returns:
            최신 결과 딕셔너리. 없으면 None.
        """
        try:
            from src.db.models import BacktestResult

            async with get_session() as session:
                stmt = (
                    select(BacktestResult)
                    .order_by(BacktestResult.created_at.desc())
                    .limit(1)
                )
                result = await session.execute(stmt)
                record = result.scalar_one_or_none()

                if record:
                    return {
                        "id": str(record.id),
                        "run_date": str(record.run_date),
                        "params": record.params,
                        "total_return": float(record.total_return) if record.total_return else None,
                        "max_drawdown": float(record.max_drawdown) if record.max_drawdown else None,
                        "sharpe_ratio": float(record.sharpe_ratio) if record.sharpe_ratio else None,
                        "win_rate": float(record.win_rate) if record.win_rate else None,
                        "recommendation": record.recommendation,
                        "created_at": record.created_at.isoformat() if record.created_at else None,
                    }
                return None
        except Exception as e:
            logger.error("최신 백테스트 결과 조회 실패: %s", e)
            return None

    def get_status(self) -> dict[str, Any]:
        """현재 상태를 반환한다."""
        return {
            "lookback_days": self.lookback_days,
        }
