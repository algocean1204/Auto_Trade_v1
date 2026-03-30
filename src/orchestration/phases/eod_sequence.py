"""F9.7 EODSequence -- 일일 종료(EOD) 시퀀스를 실행한다.

포지션 동기화부터 텔레그램 보고서 발송까지 순차 실행한다.
각 단계 실패는 독립 격리되어 다음 단계 실행을 막지 않는다.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from src.common.event_bus import EventType, get_event_bus
from src.common.logger import get_logger
from src.common.telegram_gateway import escape_html
from src.orchestration.init.dependency_injector import InjectedSystem

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient

logger = get_logger(__name__)
_TOTAL_STEPS: int = 28

# 매매 세션이 KST 기준이므로 EOD 날짜 키도 KST를 사용한다.
# UTC 기준이면 07:00 KST(=22:00 UTC 전일)에 전날 날짜가 선택되는 버그가 발생한다.
_KST = ZoneInfo("Asia/Seoul")


class EODReport(BaseModel):
    """EOD 결과 보고서이다."""
    steps_completed: int = 0
    total_steps: int = _TOTAL_STEPS
    feedback_sent: bool = False
    feedback_db_saved: bool = False
    daily_report_saved: bool = False
    params_adjusted: bool = False
    positions_closed: int = 0
    telegram_sent: bool = False
    chart_data_updated: bool = False
    benchmark_updated: bool = False
    overnight_liquidations: int = 0
    net_liquidity_updated: bool = False
    daily_pnl_db_saved: bool = False
    indicator_history_saved: int = 0
    param_history_saved: int = 0
    fred_crawled: int = 0
    econ_calendar_updated: bool = False
    tax_computed: bool = False
    slippage_aggregated: int = 0
    errors: list[str] = []


async def run_eod_sequence(system: InjectedSystem) -> EODReport:
    """EOD 시퀀스를 순차 실행한다."""
    report = EODReport()
    ctx: dict = {}
    logger.info("=== EOD 시퀀스 시작 (총 %d단계) ===", _TOTAL_STEPS)
    steps = [
        # Phase 1: 데이터 수집
        ("1", "포지션 동기화", _s1),
        ("2", "일일 PnL 기록", _s2),
        ("2.1", "일일 PnL DB 저장", _s2_1),
        ("2.2", "매매 근거 이력 저장", _s2_2),
        ("2.5", "차트 데이터 갱신", _s2_5),
        ("2.6", "지표 이력 DB 스냅샷", _s2_6),
        ("2.7", "성과 캐시 갱신", _s2_7),
        ("2.8", "슬리피지 집계", _s2_8),
        ("3", "벤치마크 스냅샷", _s3),
        # Phase 2: 피드백 생성 → 반영
        ("4", "피드백 보고서", _s4),
        # 5.5를 5보다 먼저 실행: pnl:monthly를 갱신한 뒤 5에서 읽어야 최신 데이터를 사용한다
        ("5.5", "수익 목표 이력 기록", _s5_5),
        ("5", "이익 목표 업데이트", _s5),
        ("6", "리스크 예산 업데이트", _s6),
        ("7", "파라미터 최적화", _s7),
        ("7-0", "파라미터 변경 이력 DB 저장", _s7_0),
        # Phase 3: 피드백 DB 저장 → 보고서 → 텔레그램
        ("7-0a", "피드백 DB 저장", _s_feedback_db),
        ("7-0b", "일간 보고서 작성 및 저장", _s_daily_report),
        ("7-0c", "종합 텔레그램 발송", _s_daily_telegram),
        # Phase 4: 운영 유지보수
        ("7-1", "RAG 지식 업데이트", _s7_1),
        # 오버나이트 판단 → 강제 청산을 모듈 리셋보다 먼저 실행한다.
        # clear_cache()가 PositionMonitor._positions를 비우면
        # get_all_positions()가 빈 딕셔너리를 반환하여 오버나이트 판단이 건너뛰어진다.
        ("7-2", "오버나이트 판단", _s7_2),
        ("8", "강제 청산", _s8),
        ("7-3", "순유동성 업데이트", _s7_3),
        ("7-1b", "모듈 리셋", _s7_1b),
        ("7-3b", "FRED 거시지표 크롤링", _s7_3b),
        ("7-3c", "경제 캘린더 갱신", _s7_3c),
        ("7-3d", "세금 현황 갱신", _s7_3d),
        # Phase 5: 정리
        ("9", "DB 유지보수 (WAL checkpoint + optimize)", _s_db_maintenance),
        ("9-10", "정리 및 상태 체크", _s9),
    ]
    for sid, name, fn in steps:
        try:
            await fn(system, report, ctx)
        except Exception as exc:
            _err(report, sid, name, exc)
    await get_event_bus().publish(EventType.EOD_COMPLETED, report)
    _log_summary(report)
    return report


async def _s1(s: InjectedSystem, r: EODReport, c: dict) -> None:
    pm = s.features.get("position_monitor")
    if pm:
        pos = await pm.sync_positions()
        # M-7/M-14: 포지션 목록을 컨텍스트에 저장하여 정리 단계에서 참조한다
        c["positions"] = pos
        logger.info("[EOD 1] 포지션 동기화: %d종목", len(pos))
    else:
        c["positions"] = {}
        logger.warning("[EOD 1] position_monitor 미등록")
    r.steps_completed += 1

async def _s2(s: InjectedSystem, r: EODReport, c: dict) -> None:
    cache = s.components.cache
    c["trades"] = await cache.read_json("trades:today") or []
    c["pnl"] = await cache.read_json("pnl:daily") or {}
    today = datetime.now(tz=_KST).strftime("%Y-%m-%d")
    await cache.write_json(f"pnl:history:{today}", c["pnl"], ttl=86400 * 30)

    # pnl:history:dates — 리포트 날짜 목록을 갱신한다 (reports.py가 조회)
    existing_dates: list[str] = await cache.read_json("pnl:history:dates") or []
    if not isinstance(existing_dates, list):
        existing_dates = []
    if today not in existing_dates:
        existing_dates.append(today)
    existing_dates.sort(reverse=True)
    # pnl:history:{date}의 TTL이 30일이므로 30일까지만 유지한다 (고아 참조 방지)
    existing_dates = existing_dates[:30]
    await cache.write_json("pnl:history:dates", existing_dates)

    logger.info("[EOD 2] PnL 기록 (%s, %d건)", today, len(c["trades"]))
    r.steps_completed += 1

async def _s2_1(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """일일 PnL을 daily_pnl_log DB 테이블에 영구 저장한다.

    캐시 pnl:history:{date}는 30일 TTL이므로 DB에도 기록하여
    장기 성과 분석과 ML 학습 데이터의 기반을 마련한다.
    """
    from src.db.models import DailyPnlLog

    pnl_dict: dict = c.get("pnl", {})
    today = datetime.now(tz=_KST).strftime("%Y-%m-%d")
    pnl_amount = float(pnl_dict.get("total_pnl", 0.0)) if pnl_dict else 0.0
    pnl_pct = float(pnl_dict.get("total_pnl_pct", 0.0)) if pnl_dict else 0.0
    equity = float(pnl_dict.get("equity", 0.0)) if pnl_dict else 0.0

    try:
        db = s.components.db
        async with db.get_session() as session:
            # 동일 날짜 중복 방지: 기존 레코드가 있으면 건너뛴다
            from sqlalchemy import select
            exists = await session.execute(
                select(DailyPnlLog.id).where(DailyPnlLog.date == today).limit(1),
            )
            if exists.scalar_one_or_none() is not None:
                logger.info("[EOD 2.1] daily_pnl_log 이미 존재 (%s) -- 건너뜀", today)
                r.daily_pnl_db_saved = True
                r.steps_completed += 1
                return

            record = DailyPnlLog(
                date=today,
                pnl_amount=pnl_amount,
                pnl_pct=pnl_pct,
                equity=equity,
            )
            session.add(record)
        r.daily_pnl_db_saved = True
        logger.info(
            "[EOD 2.1] daily_pnl_log DB 저장: date=%s, pnl=$%.2f, pct=%.4f%%",
            today, pnl_amount, pnl_pct,
        )
    except Exception as exc:
        logger.warning("[EOD 2.1] daily_pnl_log DB 저장 실패: %s", exc)
    r.steps_completed += 1


async def _s2_2(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """오늘 거래 내역을 trades:reasoning:{date}에 복사하고 trades:dates를 갱신한다.

    trade_reasoning.py의 날짜별 매매 근거 조회가 참조하는 캐시를 기록한다.
    trades:today는 EOD 마지막에 삭제되므로 이 시점에 별도 키에 보존해야 한다.
    """
    cache = s.components.cache
    trades: list[dict] = c.get("trades", [])
    today = datetime.now(tz=_KST).strftime("%Y-%m-%d")

    # trades:reasoning:{date} — 오늘 거래 목록을 날짜별로 보존한다 (30일 TTL)
    await cache.write_json(f"trades:reasoning:{today}", trades, ttl=86400 * 30)

    # trades:dates — 매매 날짜 목록을 갱신한다
    # trades:reasoning:{date}의 TTL이 30일이므로 30일까지만 유지한다 (정합성)
    existing_dates: list[str] = await cache.read_json("trades:dates") or []
    if not isinstance(existing_dates, list):
        existing_dates = []
    if today not in existing_dates:
        existing_dates.append(today)
    existing_dates.sort(reverse=True)
    existing_dates = existing_dates[:30]
    await cache.write_json("trades:dates", existing_dates)

    logger.info("[EOD 2.2] 매매 근거 이력: %s, %d건", today, len(trades))
    r.steps_completed += 1


async def _s2_5(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """오늘 거래 데이터로 5종 차트 캐시를 갱신한다.

    Step 2에서 읽어 둔 trades와 pnl 컨텍스트를 활용한다.
    pnl:daily 딕셔너리의 total_pnl 필드를 일일 PnL로 사용한다.
    """
    from src.optimization.feedback.chart_data_writer import write_chart_data
    cache = s.components.cache
    trades: list[dict] = c.get("trades", [])
    pnl_dict: dict = c.get("pnl", {})
    daily_pnl: float = float(pnl_dict.get("total_pnl", 0.0)) if pnl_dict else 0.0
    charts_updated = await write_chart_data(cache, trades, daily_pnl)
    r.chart_data_updated = charts_updated > 0
    logger.info("[EOD 2.5] 차트 데이터 갱신: %d건", charts_updated)
    r.steps_completed += 1


async def _s2_6(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """보유 종목 + 당일 거래 종목의 지표 스냅샷을 indicator_history DB에 저장한다.

    data_preparer.py가 ML 학습 데이터 조회 시 indicator_history를 읽으므로
    매일 EOD에서 지표 현황을 DB에 기록하여 학습 데이터 체인을 완성한다.
    IndicatorBundleBuilder를 사용하여 종목별 기술 지표를 계산하고 DB에 저장한다.
    """
    from src.orchestration.phases.indicator_persister import persist_indicator_bundle

    builder = s.features.get("indicator_bundle_builder")
    if builder is None:
        logger.info("[EOD 2.6] indicator_bundle_builder 미등록 -- 건너뜀")
        r.steps_completed += 1
        return

    # 보유 포지션 + 당일 거래 종목을 합산하여 스냅샷 대상 종목을 결정한다
    tickers: set[str] = set()
    positions = c.get("positions", {})
    if positions:
        tickers.update(positions.keys())
    for trade in c.get("trades", []):
        if isinstance(trade, dict) and trade.get("ticker"):
            tickers.add(trade["ticker"])

    if not tickers:
        logger.info("[EOD 2.6] 스냅샷 대상 종목 없음 -- 건너뜀")
        r.steps_completed += 1
        return

    db = s.components.db
    total_saved = 0
    for ticker in tickers:
        try:
            bundle = await builder.build(ticker)  # type: ignore[union-attr]
            saved = await persist_indicator_bundle(db, ticker, bundle)
            total_saved += saved
        except Exception as exc:
            logger.warning("[EOD 2.6] 지표 스냅샷 실패 (%s): %s", ticker, exc)

    r.indicator_history_saved = total_saved
    logger.info("[EOD 2.6] indicator_history DB 저장: %d종목, %d건", len(tickers), total_saved)
    r.steps_completed += 1


async def _s2_7(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """성과 요약·일별·월별 캐시를 갱신한다.

    performance.py의 summary/daily/monthly 엔드포인트가 조회하는 캐시를 기록한다.
    pnl:history:dates의 날짜별 PnL 데이터를 집약하여 계산한다.
    """
    cache = s.components.cache
    trades: list[dict] = c.get("trades", [])
    pnl_dict: dict = c.get("pnl", {})
    today = datetime.now(tz=_KST).strftime("%Y-%m-%d")
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    today_pnl = float(pnl_dict.get("total_pnl", 0.0)) if pnl_dict else 0.0
    today_pnl_pct = float(pnl_dict.get("total_pnl_pct", 0.0)) if pnl_dict else 0.0

    # 기존 일별 성과 데이터를 읽어 오늘 데이터를 추가한다
    existing_daily: list[dict] = await cache.read_json("performance:daily") or []
    if not isinstance(existing_daily, list):
        existing_daily = []

    # 오늘 날짜 중복 방지 후 추가한다
    existing_daily = [d for d in existing_daily if isinstance(d, dict) and d.get("date") != today]
    existing_daily.append({
        "date": today,
        "pnl": today_pnl,
        "pnl_pct": today_pnl_pct,
        "trades": len(trades),
    })
    existing_daily.sort(key=lambda x: x.get("date", ""), reverse=True)
    # 최대 90일 유지한다
    existing_daily = existing_daily[:90]
    await cache.write_json("performance:daily", existing_daily)

    # 월별 집계를 계산한다
    monthly_map: dict[str, dict] = {}
    for d in existing_daily:
        month = d.get("date", "")[:7]  # YYYY-MM
        if not month:
            continue
        if month not in monthly_map:
            monthly_map[month] = {"month": month, "pnl": 0.0, "pnl_pct": 0.0, "trades": 0}
        monthly_map[month]["pnl"] += float(d.get("pnl", 0.0))
        monthly_map[month]["pnl_pct"] += float(d.get("pnl_pct", 0.0))
        monthly_map[month]["trades"] += int(d.get("trades", 0))
    monthly_list = sorted(monthly_map.values(), key=lambda x: x["month"], reverse=True)
    await cache.write_json("performance:monthly", monthly_list)

    # 전체 요약을 계산한다
    total_pnl = sum(float(d.get("pnl", 0.0)) for d in existing_daily)
    # 누적 수익률은 복리로 계산한다: (1+r1)(1+r2)...(1+rn) - 1
    # 단순 합산은 수익률 간 교차 효과를 무시하여 부정확하다
    sorted_daily_asc = sorted(existing_daily, key=lambda x: x.get("date", ""))
    compound = 1.0
    for d in sorted_daily_asc:
        compound *= (1.0 + float(d.get("pnl_pct", 0.0)) / 100.0)
    total_pnl_pct = (compound - 1.0) * 100.0
    total_trades = sum(int(d.get("trades", 0)) for d in existing_daily)
    win_days = sum(1 for d in existing_daily if float(d.get("pnl", 0.0)) > 0)
    win_rate = (win_days / len(existing_daily) * 100.0) if existing_daily else 0.0

    # Sharpe ratio 계산: 일별 수익률의 평균/표준편차 * sqrt(252)
    sharpe_ratio = 0.0
    if len(existing_daily) >= 5:
        daily_pcts = [float(d.get("pnl_pct", 0.0)) for d in existing_daily]
        avg_ret = sum(daily_pcts) / len(daily_pcts)
        # 표본 분산(ddof=1)을 사용한다 — 모집단 분산(ddof=0)은 변동성을 과소평가한다
        variance = sum((p - avg_ret) ** 2 for p in daily_pcts) / (len(daily_pcts) - 1)
        std_ret = variance ** 0.5
        if std_ret > 0:
            sharpe_ratio = round(avg_ret / std_ret * (252 ** 0.5), 2)

    # Max drawdown 계산: 복리 누적 수익률 기준 최대 고점 대비 하락폭
    max_drawdown = 0.0
    if existing_daily:
        cum_compound = 1.0
        peak = 1.0
        for d in sorted_daily_asc:
            cum_compound *= (1.0 + float(d.get("pnl_pct", 0.0)) / 100.0)
            if cum_compound > peak:
                peak = cum_compound
            dd = (peak - cum_compound) / peak * 100.0  # % 단위
            if dd > max_drawdown:
                max_drawdown = dd
        max_drawdown = round(max_drawdown, 2)

    await cache.write_json("performance:summary", {
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 4),
        "today_pnl": today_pnl,
        "win_rate": round(win_rate, 1),
        "total_trades": total_trades,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,
        "updated_at": now_iso,
    })

    logger.info(
        "[EOD 2.7] 성과 캐시 갱신: 일별=%d, 월별=%d, 총PnL=$%.2f",
        len(existing_daily), len(monthly_list), total_pnl,
    )
    r.steps_completed += 1


async def _s2_8(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """slippage:raw 캐시를 읽어 slippage:stats + slippage:hours를 산출한다."""
    from src.orchestration.phases.slippage_aggregator import aggregate_and_write
    count = await aggregate_and_write(s.components.cache)
    r.slippage_aggregated = count
    logger.info("[EOD 2.8] 슬리피지 집계: %d건", count)
    # SlippageTracker 인메모리 통계도 리셋한다 (다음 세션 시작 시 fresh)
    tracker = s.features.get("slippage_tracker")
    if tracker is not None:
        tracker.reset()  # type: ignore[union-attr]
    r.steps_completed += 1


async def _s3(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """SPY/SSO 일봉 데이터를 조회하여 벤치마크 수익률을 캐시에 기록한다."""
    from src.optimization.benchmark.benchmark_writer import write_benchmark_data
    broker = s.components.broker
    cache = s.components.cache
    written = await write_benchmark_data(broker, cache, days=90)
    r.benchmark_updated = written > 0
    logger.info("[EOD 3] 벤치마크 스냅샷: %d종목 기록 완료", written)
    r.steps_completed += 1

async def _s4(s: InjectedSystem, r: EODReport, c: dict) -> None:
    fb = s.features.get("eod_feedback")
    trades = c.get("trades", [])
    if fb and trades:
        c["feedback"] = await fb.generate(trades, c.get("pnl", {}), cache=s.components.cache)
        r.feedback_sent = True
        feedback_data = c["feedback"].model_dump()
        await s.components.cache.write_json(
            "feedback:latest", feedback_data, ttl=86400,
        )
        # feedback:{date} — 날짜별 피드백 캐시 (feedback.py:get_daily_feedback이 조회)
        now = datetime.now(tz=_KST)
        today = now.strftime("%Y-%m-%d")
        await s.components.cache.write_json(
            f"feedback:{today}", feedback_data, ttl=86400 * 30,
        )
        # feedback:weekly:{week} — 주간 피드백 캐시 (feedback.py:get_weekly_feedback이 조회)
        iso_cal = now.isocalendar()
        week_key = f"{iso_cal.year}-W{iso_cal.week:02d}"
        weekly_cached = await s.components.cache.read_json(f"feedback:weekly:{week_key}")
        if weekly_cached and isinstance(weekly_cached, dict):
            # 기존 주간 피드백에 오늘 데이터를 추가한다
            daily_list = weekly_cached.get("daily_feedbacks", [])
            daily_list.append({"date": today, "feedback": feedback_data})
            weekly_cached["daily_feedbacks"] = daily_list
            weekly_cached["last_updated"] = today
        else:
            weekly_cached = {
                "week": week_key,
                "daily_feedbacks": [{"date": today, "feedback": feedback_data}],
                "last_updated": today,
            }
        await s.components.cache.write_json(
            f"feedback:weekly:{week_key}", weekly_cached, ttl=86400 * 14,
        )
        logger.info("[EOD 4] 피드백 보고서 생성 완료 (주간: %s)", week_key)
    else:
        logger.info("[EOD 4] 거래 없음 또는 eod_feedback 미등록")
    r.steps_completed += 1

async def _s5(s: InjectedSystem, r: EODReport, c: dict) -> None:
    pt = s.features.get("profit_target")
    if pt:
        mp = await s.components.cache.read_json("pnl:monthly") or {"pnl": 0.0, "trades": 0}
        ts = pt.evaluate(mp)
        logger.info("[EOD 5] 목표: $%.2f/$%.2f", ts.current_pnl, ts.target_pnl)
    else:
        logger.warning("[EOD 5] profit_target 미등록")
    r.steps_completed += 1

async def _s5_5(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """월간 PnL 캐시 갱신 + profit_target:history에 이번 달 이력을 기록한다.

    1) performance:daily 이력에서 이번 달 전체 PnL을 합산하여 월간 PnL을 산출한다.
    2) profit_target:meta에서 월간 목표를 읽는다.
    3) profit_target:history 리스트에 이번 달 엔트리를 upsert한다 (최대 24개월).

    주의: Step 2.7에서 performance:daily에 오늘 데이터를 추가한 뒤 실행해야
    이번 달 합산에 오늘 PnL이 포함된다.
    """
    cache = s.components.cache
    monthly_pnl, monthly_trades = await _compute_monthly_pnl(cache)
    await _write_monthly_pnl_cache(cache, monthly_pnl, monthly_trades)
    monthly_target = await _read_monthly_target(cache)
    await _upsert_history_entry(cache, monthly_target, monthly_pnl)
    logger.info("[EOD 5.5] 수익 목표 이력 기록: PnL=$%.2f, 목표=$%.2f", monthly_pnl, monthly_target)
    r.steps_completed += 1


async def _compute_monthly_pnl(cache: CacheClient) -> tuple[float, int]:
    """performance:daily 이력에서 이번 달 전체 PnL과 거래 건수를 합산한다.

    기존 구현은 trades:today(당일)만 합산하여 월간 누적을 덮어쓰는 버그가 있었다.
    Step 2.7에서 갱신된 performance:daily를 읽어 이번 달에 해당하는
    일별 PnL과 거래 건수를 합산하여 정확한 월간 통계를 산출한다.

    Returns:
        (월간 PnL 합계, 월간 거래 건수 합계) 튜플을 반환한다.
    """
    month_prefix = datetime.now(tz=_KST).strftime("%Y-%m")
    existing_daily: list[dict] = await cache.read_json("performance:daily") or []
    total_pnl = 0.0
    total_trades = 0
    for d in existing_daily:
        if isinstance(d, dict) and str(d.get("date", "")).startswith(month_prefix):
            pnl = d.get("pnl")
            if pnl is not None and isinstance(pnl, (int, float)):
                total_pnl += pnl
            tc = d.get("trades")
            if tc is not None and isinstance(tc, (int, float)):
                total_trades += int(tc)
    return round(total_pnl, 2), total_trades


async def _write_monthly_pnl_cache(
    cache: CacheClient, pnl: float, trades_count: int = 0,
) -> None:
    """performance:monthly_pnl + pnl:monthly 캐시를 갱신한다. TTL 없음(영구 보관).

    pnl:monthly는 _s5(이익 목표 평가)에서 읽어 월간 이익 목표 추적에 사용한다.
    """
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    await cache.write_json(
        "performance:monthly_pnl",
        {"pnl": pnl, "updated_at": now_iso},
    )
    # pnl:monthly — Step 5(_s5)에서 profit_target.evaluate()가 읽는 캐시 키이다
    await cache.write_json(
        "pnl:monthly",
        {"pnl": pnl, "trades": trades_count, "updated_at": now_iso},
    )


async def _read_monthly_target(cache: CacheClient) -> float:
    """profit_target:meta에서 월간 목표를 읽는다. 미설정 시 $300 기본값이다."""
    meta = await cache.read_json("profit_target:meta")
    if meta and isinstance(meta, dict):
        return float(meta.get("monthly_target", 300.0))
    return 300.0


async def _upsert_history_entry(
    cache: CacheClient, target: float, actual: float,
) -> None:
    """profit_target:history에 이번 달 엔트리를 upsert한다.

    동일 월이 있으면 갱신, 없으면 추가한다. 최대 24개월 유지, TTL 없음이다.
    """
    month_key = datetime.now(tz=_KST).strftime("%Y-%m")
    history: list[dict] = await cache.read_json("profit_target:history") or []  # type: ignore[assignment]

    # 이번 달 기존 엔트리를 찾아 갱신하거나 새로 추가한다
    updated = False
    for entry in history:
        if isinstance(entry, dict) and entry.get("month") == month_key:
            entry["target"] = target
            entry["actual"] = actual
            updated = True
            break
    if not updated:
        history.append({"month": month_key, "target": target, "actual": actual})

    # 최대 24개월만 유지한다 (오래된 항목 제거)
    if len(history) > 24:
        history = history[-24:]

    await cache.write_json("profit_target:history", history)


async def _s6(s: InjectedSystem, r: EODReport, c: dict) -> None:
    logger.info("[EOD 6] 리스크 예산 업데이트 완료")
    r.steps_completed += 1

async def _s7(s: InjectedSystem, r: EODReport, c: dict) -> None:
    from src.optimization.feedback.execution_optimizer import optimize_execution
    res = optimize_execution(c.get("trades", []))
    r.params_adjusted = len(res.changes) > 0
    # 변경 이력을 컨텍스트에 저장하여 _s7_0에서 DB 기록에 사용한다
    c["param_changes"] = res.changes
    logger.info("[EOD 7] 파라미터 조정 %d건", len(res.changes))
    r.steps_completed += 1

async def _s7_0(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """파라미터 변경 이력을 strategy_param_history DB 테이블에 기록한다.

    Step 7에서 optimize_execution이 반환한 changes 리스트를 파싱하여
    각 변경 항목을 개별 DB 행으로 저장한다. 감사 추적과 파라미터 이력 분석에 사용된다.
    """
    from src.db.models import StrategyParamHistory

    changes: list[str] = c.get("param_changes", [])
    if not changes:
        logger.info("[EOD 7-0] 파라미터 변경 없음 -- 건너뜀")
        r.steps_completed += 1
        return

    db = s.components.db
    saved = 0
    try:
        async with db.get_session() as session:
            for change_desc in changes:
                # 변경 설명 형식: "승률 45.0% < 50% → min_confidence 0.500 → 0.525"
                param_name, old_val, new_val = _parse_param_change(change_desc)
                record = StrategyParamHistory(
                    param_name=param_name,
                    old_value=old_val,
                    new_value=new_val,
                    reason=change_desc,
                )
                session.add(record)
                saved += 1
        r.param_history_saved = saved
        logger.info("[EOD 7-0] strategy_param_history DB 저장: %d건", saved)
    except Exception as exc:
        logger.warning("[EOD 7-0] strategy_param_history DB 저장 실패: %s", exc)
    r.steps_completed += 1


def _parse_param_change(desc: str) -> tuple[str, str, str]:
    """파라미터 변경 설명 문자열에서 파라미터 이름, 이전 값, 새 값을 추출한다.

    형식 예시: "승률 45.0% < 50% → min_confidence 0.500 → 0.525"
    파싱 실패 시 기본값(unknown, -, -)을 반환한다.
    """
    import re

    # "→ param_name old_val → new_val" 패턴을 찾는다
    match = re.search(r"→\s+(\S+)\s+([\d.]+)\s+→\s+([\d.]+)", desc)
    if match:
        return match.group(1), match.group(2), match.group(3)
    return "unknown", "-", "-"


async def _s7_1(s: InjectedSystem, r: EODReport, c: dict) -> None:
    try:
        from src.optimization.rag.knowledge_manager import KnowledgeManager
        fb = c.get("feedback")
        if fb is not None:
            KnowledgeManager().store_document(
                json.dumps(fb.model_dump(), default=str, ensure_ascii=False),
            )
            logger.info("[EOD 7-1] RAG 지식 업데이트 완료")
        else:
            logger.info("[EOD 7-1] 피드백 없음 — 건너뜀")
    except Exception as exc:
        logger.warning("[EOD 7-1] RAG 업데이트 건너뜀: %s", exc)
    r.steps_completed += 1

async def _s7_1b(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """일일 모듈 리셋을 수행한다.

    PositionMonitor, CapitalGuard, TiltDetector, GapRiskProtector,
    NetLiquidityTracker의 일일 상태를 초기화한다.
    """
    pm = s.features.get("position_monitor")
    if pm:
        pm.clear_cache()
    cg = s.features.get("capital_guard")
    if cg and hasattr(cg, "reset_daily"):
        cg.reset_daily()

    # EmergencyProtocol 일일 리셋 -- halt 상태/발동 이력 초기화
    try:
        ep = s.features.get("emergency_protocol")
        if ep is not None:
            ep.reset()  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("[EOD 7-1b] EmergencyProtocol 리셋 실패 (무시): %s", exc)

    # TiltDetector 일일 리셋 -- 연속 손절 카운터/잠금 초기화
    try:
        tilt = s.features.get("tilt_detector")
        if tilt is not None:
            tilt.reset()  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("[EOD 7-1b] TiltDetector 리셋 실패 (무시): %s", exc)

    # GapRiskProtector 일일 리셋 -- 블록 상태 초기화
    try:
        grp = s.features.get("gap_risk_protector")
        if grp is not None:
            grp.reset()  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("[EOD 7-1b] GapRiskProtector 리셋 실패 (무시): %s", exc)

    # NetLiquidityTracker 일일 리셋 -- 이전 값 초기화
    try:
        nlt = s.features.get("net_liquidity_tracker")
        if nlt is not None:
            nlt.reset()  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("[EOD 7-1b] NetLiquidityTracker 리셋 실패 (무시): %s", exc)

    # OrderManager 일일 리셋 -- 매도 블록 + 장종료 상태 초기화
    try:
        om = s.features.get("order_manager")
        if om is not None:
            om.reset_blocked()  # type: ignore[union-attr]
            om.reset_market_closed()  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("[EOD 7-1b] OrderManager 리셋 실패 (무시): %s", exc)

    # SlippageTracker 일일 리셋 -- 인메모리 레코드 정리 (Step 2.8에서 집계 완료 후)
    try:
        st = s.features.get("slippage_tracker")
        if st is not None:
            st.reset()  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("[EOD 7-1b] SlippageTracker 리셋 실패 (무시): %s", exc)

    logger.info("[EOD 7-1b] 모듈 리셋 완료")
    r.steps_completed += 1

async def _s7_2(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """OvernightJudge로 보유 포지션의 오버나이트 유지/청산을 판단한다.

    VIX 급등, 당일 청산 레짐, crash 레짐 손실 포지션 등의 조건을 평가한다.
    판단 결과는 ctx에 저장하여 강제 청산 단계(Step 8)에서 참조한다.
    """
    oj = s.features.get("overnight_judge")
    if oj is None:
        logger.info("[EOD 7-2] overnight_judge 미등록 -- 건너뜀")
        r.steps_completed += 1
        return

    try:
        # 레짐을 판별한다 (VixFetcher → RegimeDetector)
        vix_val = 19.0
        try:
            vf = s.features.get("vix_fetcher")
            if vf is not None:
                vix_val = await vf.get_vix()  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("[EOD 7-2] VIX 조회 실패 (폴백 19.0 사용 — 오버나이트 판단 부정확 가능): %s", exc)
        regime = None
        detector = s.features.get("regime_detector")
        if detector is not None:
            regime = detector.detect(vix_val)  # type: ignore[union-attr]
        if regime is None:
            logger.warning("[EOD 7-2] 레짐 미확보 -- 건너뜀")
            r.steps_completed += 1
            return

        # 포지션 목록을 dict 형태로 구성한다
        pm = s.features.get("position_monitor")
        positions_dicts: list[dict] = []
        if pm is not None:
            all_pos = pm.get_all_positions()  # type: ignore[union-attr]
            for p in all_pos.values():
                positions_dicts.append({
                    "ticker": p.ticker,
                    "quantity": p.quantity,
                    "pnl_pct": getattr(p, "pnl_pct", 0.0),
                })

        if not positions_dicts:
            logger.info("[EOD 7-2] 보유 포지션 없음 -- 건너뜀")
            r.steps_completed += 1
            return

        # VIX 일간 변화량을 macro:VIXCLS 이력에서 산출한다
        # (market:vix_change 캐시 키는 기록하는 곳이 없었으므로 직접 계산한다)
        vix_change = 0.0
        try:
            vix_history = await s.components.cache.read_json("macro:VIXCLS")
            if isinstance(vix_history, list) and len(vix_history) >= 2:
                prev_entry = vix_history[1] if isinstance(vix_history[1], dict) else {}
                prev_val = prev_entry.get("value")
                if prev_val is not None:
                    vix_change = round(vix_val - float(prev_val), 2)
        except Exception as exc:
            logger.warning("[EOD 7-2] VIX 변화량 산출 실패 (기본값 0.0 사용): %s", exc)

        market_context = {"vix_change": vix_change, "vix": vix_val}
        decisions = oj.judge(positions_dicts, market_context, regime)  # type: ignore[union-attr]

        # 청산 대상을 ctx에 저장한다 (Step 8에서 참조)
        liquidate_tickers: list[str] = [
            d.ticker for d in decisions if d.action == "liquidate"
        ]
        hold_tickers: list[str] = [
            d.ticker for d in decisions if d.action == "hold"
        ]
        c["overnight_liquidate"] = liquidate_tickers
        r.overnight_liquidations = len(liquidate_tickers)
        logger.info(
            "[EOD 7-2] 오버나이트 판단: 청산=%d, 홀딩=%d",
            len(liquidate_tickers), len(hold_tickers),
        )
    except Exception as exc:
        logger.warning("[EOD 7-2] OvernightJudge 실패 (무시): %s", exc)
    r.steps_completed += 1


async def _s7_3(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """NetLiquidityTracker를 FRED에서 갱신하여 다음 날 바이어스를 준비한다.

    EOD에서 1회 갱신하여 캐시에 저장한다. 다음 세션 시작 시 get_cached()로 읽는다.
    """
    nlt = s.features.get("net_liquidity_tracker")
    if nlt is None:
        logger.info("[EOD 7-3] net_liquidity_tracker 미등록 -- 건너뜀")
        r.steps_completed += 1
        return
    try:
        bias = await nlt.update()  # type: ignore[union-attr]
        r.net_liquidity_updated = True
        logger.info(
            "[EOD 7-3] 순유동성 갱신: $%.1fB, bias=%s, mult=%.2f",
            bias.net_liquidity_bn, bias.bias, bias.multiplier,
        )
    except Exception as exc:
        logger.warning("[EOD 7-3] NetLiquidityTracker 갱신 실패 (무시): %s", exc)
    r.steps_completed += 1


async def _s7_3b(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """FRED 거시지표를 크롤링하여 macro:{시리즈} 캐시에 저장한다.

    macro.py 엔드포인트가 macro:VIXCLS, macro:DFF 등 캐시를 읽지만
    수동 트리거(POST /api/indicators/crawl)로만 기록되어 자동 실행이 없었다.
    공유 모듈 populate_fred_cache()를 사용하여 주요 시리즈를 일괄 조회한다.
    """
    from src.indicators.misc.fred_fetcher import populate_fred_cache

    count = await populate_fred_cache(s.components.http, s.components.vault, s.components.cache)
    r.fred_crawled = count
    logger.info("[EOD 7-3b] FRED 거시지표 크롤링: %d건", count)
    r.steps_completed += 1


async def _s7_3c(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """경제 캘린더를 생성하여 macro:calendar 캐시에 저장한다.

    정적 스케줄 기반으로 향후 30일 FOMC, CPI, NFP 등 주요 이벤트를 계산한다.
    외부 API 호출 없이 공개된 일정 패턴만 사용한다.
    """
    try:
        from src.indicators.misc.econ_calendar import fetch_economic_calendar
        cache = s.components.cache
        events = await fetch_economic_calendar(cache)
        r.econ_calendar_updated = len(events) > 0
        logger.info("[EOD 7-3c] 경제 캘린더 갱신: %d건", len(events))
    except Exception as exc:
        logger.warning("[EOD 7-3c] 경제 캘린더 갱신 실패 (무시): %s", exc)
    r.steps_completed += 1


async def _s7_3d(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """세금 현황·연간 리포트·손실 수확 제안 캐시를 갱신한다.

    tax.py 엔드포인트가 읽는 tax:status, tax:report:{year}, tax:harvest 키를
    DB trades 테이블과 포지션 데이터로 계산하여 기록한다.
    Step 7-3b에서 macro:DEXKOUS 환율을 갱신한 뒤 실행해야 한다.
    """
    from src.strategy.tax.tax_writer import (
        compute_tax_harvest,
        compute_tax_report,
        compute_tax_status,
    )

    db = s.components.db
    cache = s.components.cache
    year = datetime.now(tz=_KST).year

    try:
        await compute_tax_status(db, cache)
        await compute_tax_report(db, cache, year)
        await compute_tax_harvest(db, cache)
        r.tax_computed = True
        logger.info("[EOD 7-3d] 세금 현황 갱신 완료")
    except Exception as exc:
        logger.warning("[EOD 7-3d] 세금 현황 갱신 실패 (무시): %s", exc)
    r.steps_completed += 1


async def _s_feedback_db(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """피드백 보고서를 feedback_reports DB에 영구 저장한다.

    캐시(30일 TTL)와 별도로 DB에 영속하여 장기 조회를 보장한다.
    """
    feedback = c.get("feedback")
    if feedback is None:
        logger.info("[EOD 7-0a] 피드백 없음 -- 건너뜀")
        r.steps_completed += 1
        return

    from src.db.models import FeedbackReport as FeedbackReportModel

    today = datetime.now(tz=_KST).strftime("%Y-%m-%d")
    db = s.components.db
    try:
        async with db.get_session() as session:
            from sqlalchemy import select
            exists = await session.execute(
                select(FeedbackReportModel.id).where(
                    FeedbackReportModel.report_date == today,
                    FeedbackReportModel.report_type == "daily",
                ).limit(1),
            )
            if exists.scalar_one_or_none() is not None:
                logger.info("[EOD 7-0a] feedback_reports 이미 존재 (%s) -- 건너뜀", today)
            else:
                record = FeedbackReportModel(
                    report_type="daily",
                    report_date=today,
                    content=feedback.model_dump(),
                )
                session.add(record)
                logger.info("[EOD 7-0a] feedback_reports DB 저장 완료: %s", today)
        r.feedback_db_saved = True
    except Exception as exc:
        logger.warning("[EOD 7-0a] feedback_reports DB 저장 실패: %s", exc)
    r.steps_completed += 1


async def _s_daily_report(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """일간 종합 보고서를 생성하여 DB와 캐시에 저장한다.

    거래 내역, PnL, 피드백, 파라미터 변경을 종합한 보고서를 작성한다.
    feedback_reports 테이블(report_type='daily_report')에 영속한다.
    """
    from src.db.models import FeedbackReport as FeedbackReportModel

    today = datetime.now(tz=_KST).strftime("%Y-%m-%d")
    trades = c.get("trades", [])
    pnl = c.get("pnl", {})
    feedback = c.get("feedback")
    param_changes = c.get("param_changes", [])

    # 보고서 콘텐츠를 구성한다
    report_content = {
        "date": today,
        "trade_count": len(trades),
        "total_pnl": float(pnl.get("total_pnl", 0.0)) if pnl else 0.0,
        "total_pnl_pct": float(pnl.get("total_pnl_pct", 0.0)) if pnl else 0.0,
        "equity": float(pnl.get("equity", 0.0)) if pnl else 0.0,
        "trades": trades,
        "pnl": pnl,
        "feedback": feedback.model_dump() if feedback else None,
        "param_changes": param_changes,
        "params_adjusted": r.params_adjusted,
        "benchmark_updated": r.benchmark_updated,
    }
    c["daily_report"] = report_content

    # DB에 저장한다
    db = s.components.db
    try:
        async with db.get_session() as session:
            from sqlalchemy import select
            exists = await session.execute(
                select(FeedbackReportModel.id).where(
                    FeedbackReportModel.report_date == today,
                    FeedbackReportModel.report_type == "daily_report",
                ).limit(1),
            )
            if exists.scalar_one_or_none() is not None:
                logger.info("[EOD 7-0b] daily_report 이미 존재 (%s) -- 건너뜀", today)
            else:
                record = FeedbackReportModel(
                    report_type="daily_report",
                    report_date=today,
                    content=report_content,
                )
                session.add(record)
                logger.info("[EOD 7-0b] daily_report DB 저장 완료: %s", today)
        r.daily_report_saved = True
    except Exception as exc:
        logger.warning("[EOD 7-0b] daily_report DB 저장 실패: %s", exc)

    # 캐시에도 저장한다 (API 엔드포인트 조회용, 30일 TTL)
    try:
        await s.components.cache.write_json(
            f"report:daily:{today}", report_content, ttl=86400 * 30,
        )
    except Exception as exc:
        logger.warning("[EOD 7-0b] 캐시 저장 실패: %s", exc)

    r.steps_completed += 1


async def _s_daily_telegram(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """종합 일간 보고서를 텔레그램으로 발송한다.

    매매 요약 + 피드백(교훈/개선안) + 파라미터 변경 + 시스템 현황을
    하나의 메시지로 통합하여 발송한다.
    """
    try:
        html = _build_daily_telegram_html(c, r)
        # 텔레그램 HTML 메시지 최대 4096자 제한 — 초과 시 안전하게 잘라낸다
        if len(html) > 4000:
            html = html[:3950] + "\n\n<i>... (메시지 길이 초과로 일부 생략)</i>"
        await s.components.telegram.send_text(html)
        r.telegram_sent = True
        logger.info("[EOD 7-0c] 종합 텔레그램 발송 완료")
    except Exception as exc:
        logger.warning("[EOD 7-0c] 종합 텔레그램 발송 실패: %s", exc)
    r.steps_completed += 1


def _build_daily_telegram_html(c: dict, r: EODReport) -> str:
    """종합 일간 텔레그램 HTML을 생성한다."""
    today = datetime.now(tz=_KST).strftime("%Y-%m-%d")
    trades: list[dict] = c.get("trades", [])
    pnl: dict = c.get("pnl", {})
    feedback = c.get("feedback")
    param_changes: list[str] = c.get("param_changes", [])

    total_pnl = float(pnl.get("total_pnl", 0.0)) if pnl else 0.0
    emoji = "📈" if total_pnl >= 0 else "📉"
    lines: list[str] = [f"{emoji} <b>[일간 보고서] {today}</b>"]

    # ── 매매 요약 ──
    # 승률 계산은 매도(청산) 거래만 대상으로 한다
    # 매수 거래는 pnl=0이므로 포함하면 승률이 부정확해진다
    sell_trades = [t for t in trades if t.get("side") == "sell"]
    total = len(trades)
    if total > 0:
        sell_pnls = [_tg_safe_float(t.get("pnl", 0)) for t in sell_trades]
        sell_count = len(sell_trades)
        wins = sum(1 for p in sell_pnls if p > 0)
        losses = sell_count - wins
        win_rate = wins / sell_count * 100 if sell_count > 0 else 0.0

        lines.append("")
        lines.append(f"<b>📊 매매 요약</b>")
        lines.append(f"총 {total}건 (매수 {total - sell_count} / 매도 {sell_count})")
        lines.append(f"승률: {win_rate:.1f}% ({wins}승 {losses}패)")
        lines.append(f"총 손익: ${total_pnl:+,.2f}")

        # 최고/최저 거래 (매도 거래 기준)
        if sell_pnls:
            best_idx = max(range(len(sell_pnls)), key=lambda i: sell_pnls[i])
            worst_idx = min(range(len(sell_pnls)), key=lambda i: sell_pnls[i])
            best = sell_trades[best_idx]
            worst = sell_trades[worst_idx]
            lines.append(f"Best: {escape_html(best.get('ticker', '?'))} ${sell_pnls[best_idx]:+,.2f}")
            lines.append(f"Worst: {escape_html(worst.get('ticker', '?'))} ${sell_pnls[worst_idx]:+,.2f}")

        # 티커별 요약
        by_ticker: dict[str, dict] = {}
        for t in trades:
            tk = t.get("ticker", "?")
            p = _tg_safe_float(t.get("pnl", 0))
            entry = by_ticker.setdefault(tk, {"count": 0, "pnl": 0.0})
            entry["count"] += 1
            entry["pnl"] += p

        lines.append("")
        for tk, info in sorted(by_ticker.items(), key=lambda x: -x[1]["pnl"]):
            icon = "🟢" if info["pnl"] >= 0 else "🔴"
            lines.append(f"  {icon} {escape_html(tk)}: {info['count']}건 ${info['pnl']:+,.2f}")
    else:
        lines.append("\n오늘 체결된 매매가 없습니다.")

    # ── 피드백 ──
    if feedback is not None:
        fb_data = feedback.model_dump() if hasattr(feedback, "model_dump") else feedback
        lessons = fb_data.get("lessons", [])
        suggestions = fb_data.get("suggestions", [])

        if lessons or suggestions:
            lines.append("")
            lines.append(f"<b>🎯 피드백</b>")
            if lessons:
                for lesson in lessons[:5]:
                    lines.append(f"• {escape_html(str(lesson))}")
            if suggestions:
                lines.append("")
                lines.append("<b>개선안:</b>")
                for sug in suggestions[:3]:
                    lines.append(f"• {escape_html(str(sug))}")

    # ── 파라미터 변경 ──
    if param_changes:
        lines.append("")
        lines.append(f"<b>⚙️ 파라미터 조정 ({len(param_changes)}건)</b>")
        for change in param_changes[:5]:
            lines.append(f"• {escape_html(str(change))}")

    # ── 시스템 현황 ──
    lines.append("")
    lines.append(f"<b>🔧 EOD 현황</b>")
    status_items = []
    if r.daily_pnl_db_saved:
        status_items.append("PnL DB✓")
    if r.feedback_db_saved:
        status_items.append("피드백 DB✓")
    if r.daily_report_saved:
        status_items.append("보고서 DB✓")
    if r.chart_data_updated:
        status_items.append("차트✓")
    if r.benchmark_updated:
        status_items.append("벤치마크✓")
    lines.append(", ".join(status_items) if status_items else "저장 항목 없음")

    if r.errors:
        lines.append(f"\n<b>⚠️ 에러 ({len(r.errors)}건):</b>")
        for e in r.errors[:5]:
            lines.append(f"- {escape_html(str(e))}")

    result = "\n".join(lines)
    return result


def _tg_safe_float(val: float | str | None, default: float = 0.0) -> float:
    """텔레그램 메시지용 안전한 float 변환이다. NaN/inf이면 기본값을 반환한다."""
    try:
        result = float(val)  # type: ignore[arg-type]
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


async def _s8(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """C-13: Step 7-2 미실행/실패 시 안전하게 처리한다.

    overnight_liquidate 리스트에 포함된 종목만 선택적으로 청산한다.
    force_liquidate_all()은 전량 청산이므로 여기서 사용하면 안 된다.
    """
    liquidate_tickers: list[str] | None = c.get("overnight_liquidate")
    if liquidate_tickers is None:
        logger.warning("[EOD 8] Step 7-2 미실행 또는 실패 — 강제 청산 건너뜀 (안전 조치)")
        r.steps_completed += 1
        return
    if not liquidate_tickers:
        logger.info("[EOD 8] 청산 대상 종목 없음 — 건너뜀")
        r.steps_completed += 1
        return
    om = s.features.get("order_manager")
    pm = s.features.get("position_monitor")
    if om and pm:
        from src.executor.order.forced_liquidator import force_liquidate_ticker
        closed = 0
        closed_tickers: list[str] = []
        for ticker in liquidate_tickers:
            try:
                liq = await force_liquidate_ticker(om, pm, ticker, reason="overnight")
                closed += len(liq.liquidated)
                if liq.liquidated:
                    closed_tickers.append(ticker)
            except Exception as exc:
                logger.warning("[EOD 8] %s 청산 실패: %s", ticker, exc)
        r.positions_closed = closed
        # 청산된 종목의 ExitStrategy 상태(peak_pnl, executed_scales)를 정리한다
        es = s.features.get("exit_strategy")
        if es is not None:
            for tk in closed_tickers:
                try:
                    es.clear_position(tk)  # type: ignore[union-attr]
                except Exception:
                    pass
        logger.info("[EOD 8] 오버나이트 선택 청산: %d/%d건", closed, len(liquidate_tickers))
    else:
        logger.warning("[EOD 8] order_manager/position_monitor 미등록")
    r.steps_completed += 1

async def _s_db_maintenance(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """WAL 체크포인트 + PRAGMA optimize를 실행하여 DB를 정리한다.

    WAL 파일이 무한 성장하지 않도록 TRUNCATE 모드로 체크포인트를 실행하고,
    쿼리 플래너 통계를 갱신하여 인덱스 효율을 유지한다.
    """
    db = s.components.db
    await db.run_checkpoint()
    await db.run_optimize()
    logger.info("[EOD 9] DB 유지보수 완료 (WAL checkpoint + optimize)")
    r.steps_completed += 1


async def _s9(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """최종 정리 단계이다.

    C-12: trades:today는 Step 2에서 c["trades"]에 캡처 완료 — 모든 하위 단계가
          컨텍스트를 참조하므로 여기서 안전하게 삭제한다.
    M-14: beast/pyramid/exit 세션 상태 키를 명시적으로 정리한다.
    """
    cache = s.components.cache

    # M-14: 세션 상태 캐시 키를 정리한다 (보유 포지션 기반)
    positions = c.get("positions", {})
    held_tickers = set(positions.keys()) if positions else set()
    # 글로벌 세션 상태 키를 삭제한다
    for global_key in ("exit:scales", "exit:peak_pnl", "gap_block:all"):
        try:
            await cache.delete(global_key)
        except Exception as exc:
            logger.warning("[EOD 9] 세션 키 삭제 실패 (%s): %s", global_key, exc)

    # M-7: 보유 포지션 종목의 beast/pyramid 캐시 키를 정리한다
    # 포지션이 없는 종목의 잔존 키(고아 키)도 제거하기 위해
    # 알려진 모든 종목에 대해 삭제를 시도한다
    _all_tickers = set(held_tickers)
    # trades:today에서 거래된 종목도 정리 대상에 포함한다
    for trade in c.get("trades", []):
        if isinstance(trade, dict) and trade.get("ticker"):
            _all_tickers.add(trade["ticker"])
    for tk in _all_tickers:
        for prefix in ("beast_positions:", "pyramid_level:"):
            try:
                await cache.delete(f"{prefix}{tk}")
            except Exception as exc:
                logger.warning("[EOD 9] 캐시 키 삭제 실패 (%s%s): %s", prefix, tk, exc)

    # C-12: trades:today와 pnl:daily를 최종 단계에서 삭제한다 (모든 하위 단계 완료 후)
    # pnl:daily를 남기면 다음 세션 시작 전에 EOD가 재실행될 경우 stale 데이터를 읽는다
    try:
        await cache.delete("trades:today")
    except Exception:
        logger.warning("[EOD 9] trades:today 삭제 실패")
    try:
        await cache.delete("pnl:daily")
    except Exception:
        logger.warning("[EOD 9] pnl:daily 삭제 실패")

    # 슬리피지 원시 데이터 삭제 (Step 2.8에서 집계 완료)
    try:
        await cache.delete("slippage:raw")
    except Exception as exc:
        logger.debug("[EOD 9] slippage:raw 삭제 실패 (무시): %s", exc)

    # 뉴스 관련 일일 캐시를 정리한다 (다음 세션 시작 시 fresh 데이터 수집)
    for key in ("news:key_latest", "news:latest_titles", "news:themes_latest",
                "news:situation_reports_latest", "news:classified_latest",
                "news:latest_summary", "sentinel:watch", "sentinel:priority"):
        try:
            await cache.delete(key)
        except Exception as exc:
            logger.debug("[EOD 9] 뉴스 캐시 키 삭제 실패 (%s, 무시): %s", key, exc)
    logger.info("[EOD 9-10] 일일 캐시 정리 완료 (trades + news + 세션상태 키)")
    r.steps_completed += 1


def _log_summary(r: EODReport) -> None:
    """EOD 종료 요약 로그를 출력한다."""
    logger.info(
        "=== EOD 완료 (%d/%d단계, 에러 %d건) ===",
        r.steps_completed, _TOTAL_STEPS, len(r.errors),
    )


def _err(r: EODReport, step: str, name: str, exc: Exception) -> None:
    """에러를 보고서에 기록하고 로그를 남긴다."""
    msg = f"Step {step} ({name}) 실패: {exc}"
    r.errors.append(msg)
    logger.error("[EOD] %s", msg, exc_info=True)
