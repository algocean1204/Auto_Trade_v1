"""EOD 차트 데이터 계산 및 캐시 저장 모듈이다.

오늘의 거래 목록과 일일 PnL을 받아 5종 차트 캐시 키를 갱신한다.
EOD 시퀀스 Step 2.5에서 호출되며 90일 치 이력을 보관한다.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient

logger = get_logger(__name__)

# 차트 데이터 TTL: 90일 보관이다
_CHART_TTL: int = 86400 * 90
# 최대 보관 일수이다
_MAX_HISTORY_DAYS: int = 365


def _safe_float(val: float | str | None, default: float = 0.0) -> float:
    """안전하게 float으로 변환한다. NaN/inf/변환 불가 시 기본값을 반환한다."""
    if val is None:
        return default
    try:
        result = float(val)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


def _compute_pnl_pct(trades: list[dict], daily_pnl: float) -> float:
    """일일 PnL 비율(%)을 계산한다.

    매수 총액 대비 PnL 비율을 구한다. 매수 총액이 0이면 0.0을 반환한다.
    """
    total_investment = sum(
        _safe_float(t.get("price")) * _safe_float(t.get("quantity"))
        for t in trades
        if t.get("side") == "buy"
    )
    if total_investment <= 0:
        return 0.0
    return round(daily_pnl / total_investment * 100, 2)


def _build_ticker_heatmap(trades: list[dict]) -> list[dict]:
    """티커별 승률 히트맵 데이터를 생성한다.

    각 티커의 총 거래 수와 이익 거래 수를 집계하여 승률을 계산한다.
    """
    ticker_stats: dict[str, dict[str, int]] = {}
    for t in trades:
        ticker = t.get("ticker", "")
        if not ticker:
            continue
        if ticker not in ticker_stats:
            ticker_stats[ticker] = {"wins": 0, "total": 0}
        ticker_stats[ticker]["total"] += 1
        if _safe_float(t.get("pnl")) > 0:
            ticker_stats[ticker]["wins"] += 1

    return [
        {
            "ticker": ticker,
            "win_rate": round(s["wins"] / s["total"], 2) if s["total"] > 0 else 0.0,
            "trade_count": s["total"],
        }
        for ticker, s in ticker_stats.items()
    ]


def _build_hourly_heatmap(trades: list[dict]) -> list[dict]:
    """시간대별 승률 히트맵 데이터를 생성한다.

    거래 timestamp에서 시간(hour)을 추출하여 시간대별 승률을 집계한다.
    파싱 불가한 timestamp는 건너뛴다.
    """
    hour_stats: dict[int, dict[str, int]] = {}
    for t in trades:
        ts_str = t.get("timestamp", "")
        if not ts_str:
            continue
        try:
            hour = datetime.fromisoformat(str(ts_str)).hour
        except (ValueError, TypeError):
            continue
        if hour not in hour_stats:
            hour_stats[hour] = {"wins": 0, "total": 0}
        hour_stats[hour]["total"] += 1
        if _safe_float(t.get("pnl")) > 0:
            hour_stats[hour]["wins"] += 1

    return [
        {
            "hour": h,
            "win_rate": round(s["wins"] / s["total"], 2) if s["total"] > 0 else 0.0,
            "trade_count": s["total"],
        }
        for h, s in sorted(hour_stats.items())
    ]


def _compute_drawdown_pct(cumulative_list: list[dict]) -> float:
    """현재 누적 수익률 대비 낙폭(%)을 계산한다.

    전체 이력에서 최고점(peak)을 찾아 현재값과의 차이를 반환한다.
    현재값이 최고점 이상이면 0.0을 반환한다.
    """
    if not cumulative_list:
        return 0.0
    peak = max(_safe_float(c.get("cumulative_pct")) for c in cumulative_list)
    current = _safe_float(cumulative_list[-1].get("cumulative_pct"))
    return round(current - peak, 2) if current < peak else 0.0


def _compute_drawdown_detail(cumulative_list: list[dict]) -> dict[str, float]:
    """Flutter DrawdownPoint 모델에 필요한 peak, current, drawdown_pct를 계산한다.

    전체 누적 수익률 이력에서 최고점과 현재값을 추출하고 낙폭을 반환한다.
    """
    if not cumulative_list:
        return {"peak": 0.0, "current": 0.0, "drawdown_pct": 0.0}
    peak = max(_safe_float(c.get("cumulative_pct")) for c in cumulative_list)
    current = _safe_float(cumulative_list[-1].get("cumulative_pct"))
    dd_pct = round(current - peak, 2) if current < peak else 0.0
    return {"peak": round(peak, 2), "current": round(current, 2), "drawdown_pct": dd_pct}


async def write_chart_data(
    cache: CacheClient,
    trades: list[dict],
    daily_pnl: float,
) -> int:
    """오늘의 거래 데이터로 5종 차트 캐시를 갱신한다.

    캐시에 저장되는 키:
      - charts:daily_returns     : 일별 PnL 이력
      - charts:cumulative_returns: 누적 수익률 이력
      - charts:heatmap_ticker    : 티커별 승률 히트맵
      - charts:heatmap_hourly    : 시간대별 승률 히트맵
      - charts:drawdown          : 낙폭 이력

    Args:
        cache:     CacheClient 인스턴스
        trades:    오늘 체결된 거래 목록 (trades:today 캐시에서 읽은 값)
        daily_pnl: 당일 총 PnL ($)

    Returns:
        실제로 갱신된 키 수 (최대 5)
    """
    updated: int = 0
    # 매매 세션이 KST 기준이므로 차트 날짜 키도 KST를 사용한다
    today: str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    pnl_pct = _compute_pnl_pct(trades, daily_pnl)

    # --- 1. daily_returns: 오늘 항목을 추가한다 ---
    daily_returns: list[dict] = await cache.read_json("charts:daily_returns") or []
    # 같은 날짜 중복 방지: 마지막 항목이 오늘 날짜면 덮어쓴다
    # Flutter DailyReturn.fromJson이 pnl_amount, trade_count 키를 기대한다
    trade_count = len(trades)
    daily_entry = {
        "date": today,
        "pnl": round(daily_pnl, 2),
        "pnl_amount": round(daily_pnl, 2),
        "pnl_pct": pnl_pct,
        "trade_count": trade_count,
    }
    if daily_returns and daily_returns[-1].get("date") == today:
        daily_returns[-1] = daily_entry
    else:
        daily_returns.append(daily_entry)
    daily_returns = daily_returns[-_MAX_HISTORY_DAYS:]
    await cache.write_json("charts:daily_returns", daily_returns, ttl=_CHART_TTL)
    updated += 1
    logger.debug("[차트] daily_returns 갱신: %d일치", len(daily_returns))

    # portfolio:daily_returns — SimpleVaR(trading_loop.py)가 읽는 list[float] 형태이다
    # charts:daily_returns의 pnl_pct 값만 추출하여 기록한다
    pnl_pct_list: list[float] = [
        _safe_float(d.get("pnl_pct")) for d in daily_returns
    ]
    await cache.write_json("portfolio:daily_returns", pnl_pct_list, ttl=_CHART_TTL)

    # --- 2. cumulative_returns: 누적 수익률을 갱신한다 ---
    cumulative: list[dict] = await cache.read_json("charts:cumulative_returns") or []
    prev_cum = _safe_float(cumulative[-1].get("cumulative_pct")) if cumulative else 0.0
    new_cum = round(prev_cum + pnl_pct, 2)
    # Flutter CumulativeReturn.fromJson이 cumulative_pnl, cumulative_pct 키를 기대한다
    # cumulative_pnl에는 누적 PnL 금액($)을 저장한다
    prev_cum_pnl = _safe_float(cumulative[-1].get("cumulative_pnl")) if cumulative else 0.0
    new_cum_pnl = round(prev_cum_pnl + daily_pnl, 2)
    cum_entry = {"date": today, "cumulative_pct": new_cum, "cumulative_pnl": new_cum_pnl}
    if cumulative and cumulative[-1].get("date") == today:
        cumulative[-1] = cum_entry
    else:
        cumulative.append(cum_entry)
    cumulative = cumulative[-_MAX_HISTORY_DAYS:]
    await cache.write_json("charts:cumulative_returns", cumulative, ttl=_CHART_TTL)
    updated += 1
    logger.debug("[차트] cumulative_returns 갱신: 누적=%.2f%%", new_cum)

    # --- 3. heatmap_ticker: 티커별 승률을 갱신한다 ---
    heatmap_ticker = _build_ticker_heatmap(trades)
    await cache.write_json("charts:heatmap_ticker", heatmap_ticker, ttl=_CHART_TTL)
    updated += 1
    logger.debug("[차트] heatmap_ticker 갱신: %d종목", len(heatmap_ticker))

    # --- 4. heatmap_hourly: 시간대별 승률을 갱신한다 ---
    heatmap_hourly = _build_hourly_heatmap(trades)
    await cache.write_json("charts:heatmap_hourly", heatmap_hourly, ttl=_CHART_TTL)
    updated += 1
    logger.debug("[차트] heatmap_hourly 갱신: %d시간대", len(heatmap_hourly))

    # --- 5. drawdown: 낙폭 이력을 갱신한다 ---
    # 바로 위에서 cumulative를 갱신했으므로 인메모리 데이터를 직접 사용한다 (불필요한 캐시 재조회 제거)
    dd_result = _compute_drawdown_detail(cumulative)
    dd_pct = dd_result["drawdown_pct"]
    drawdown_data: list[dict] = await cache.read_json("charts:drawdown") or []
    # Flutter DrawdownPoint.fromJson이 peak, current, drawdown_pct 키를 기대한다
    dd_entry = {
        "date": today,
        "drawdown_pct": dd_pct,
        "peak": dd_result["peak"],
        "current": dd_result["current"],
    }
    if drawdown_data and drawdown_data[-1].get("date") == today:
        drawdown_data[-1] = dd_entry
    else:
        drawdown_data.append(dd_entry)
    drawdown_data = drawdown_data[-_MAX_HISTORY_DAYS:]
    await cache.write_json("charts:drawdown", drawdown_data, ttl=_CHART_TTL)
    updated += 1
    logger.debug("[차트] drawdown 갱신: %.2f%%", dd_pct)

    # risk:max_drawdown — 리스크 대시보드 API(risk.py)가 cache.read()로 읽는 키이다
    # 전체 이력에서 최대 낙폭(절대값이 가장 큰 음수)을 계산하여 문자열로 기록한다
    max_dd = min(
        (_safe_float(d.get("drawdown_pct")) for d in drawdown_data),
        default=0.0,
    )
    await cache.write("risk:max_drawdown", str(round(max_dd, 2)), ttl=_CHART_TTL)

    logger.info("차트 데이터 갱신 완료: %d건 (daily_pnl=$%.2f, pnl_pct=%.2f%%)",
                updated, daily_pnl, pnl_pct)
    return updated
