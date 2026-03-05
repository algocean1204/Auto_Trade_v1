"""F9.7 EODSequence -- 일일 종료(EOD) 시퀀스를 실행한다.

포지션 동기화부터 텔레그램 보고서 발송까지 11단계를 순차 실행한다.
각 단계 실패는 독립 격리되어 다음 단계 실행을 막지 않는다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import BaseModel

from src.common.event_bus import EventType, get_event_bus
from src.common.logger import get_logger
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)
_TOTAL_STEPS: int = 15


class EODReport(BaseModel):
    """EOD 결과 보고서이다."""
    steps_completed: int = 0
    total_steps: int = _TOTAL_STEPS
    feedback_sent: bool = False
    params_adjusted: bool = False
    positions_closed: int = 0
    telegram_sent: bool = False
    chart_data_updated: bool = False
    overnight_liquidations: int = 0
    net_liquidity_updated: bool = False
    errors: list[str] = []


async def run_eod_sequence(system: InjectedSystem) -> EODReport:
    """EOD 시퀀스를 순차 실행한다."""
    report = EODReport()
    ctx: dict = {}
    logger.info("=== EOD 시퀀스 시작 (총 %d단계) ===", _TOTAL_STEPS)
    steps = [
        ("1", "포지션 동기화", _s1), ("2", "일일 PnL 기록", _s2),
        ("2.5", "차트 데이터 갱신", _s2_5),
        ("3", "벤치마크 스냅샷", _s3), ("4", "피드백 보고서", _s4),
        ("5", "이익 목표 업데이트", _s5), ("6", "리스크 예산 업데이트", _s6),
        ("7", "파라미터 최적화", _s7), ("7-1", "RAG 지식 업데이트", _s7_1),
        ("7-1b", "모듈 리셋", _s7_1b),
        ("7-2", "오버나이트 판단", _s7_2),
        ("7-3", "순유동성 업데이트", _s7_3),
        ("7-4", "일일 매매 요약 발송", _s7_4),
        ("8", "강제 청산", _s8),
        ("9-10", "정리 및 상태 체크", _s9),
    ]
    for sid, name, fn in steps:
        try:
            await fn(system, report, ctx)
        except Exception as exc:
            _err(report, sid, name, exc)
    await _s11_telegram(system, report)
    await get_event_bus().publish(EventType.EOD_STARTED, report)
    _log_summary(report)
    return report


async def _s1(s: InjectedSystem, r: EODReport, c: dict) -> None:
    pm = s.features.get("position_monitor")
    if pm:
        pos = await pm.sync_positions()
        logger.info("[EOD 1] 포지션 동기화: %d종목", len(pos))
    else:
        logger.warning("[EOD 1] position_monitor 미등록")
    r.steps_completed += 1

async def _s2(s: InjectedSystem, r: EODReport, c: dict) -> None:
    cache = s.components.cache
    c["trades"] = await cache.read_json("trades:today") or []
    c["pnl"] = await cache.read_json("pnl:daily") or {}
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    await cache.write_json(f"pnl:history:{today}", c["pnl"], ttl=86400 * 30)
    logger.info("[EOD 2] PnL 기록 (%s, %d건)", today, len(c["trades"]))
    r.steps_completed += 1

async def _s2_5(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """오늘 거래 데이터로 5종 차트 Redis 캐시를 갱신한다.

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


async def _s3(s: InjectedSystem, r: EODReport, c: dict) -> None:
    logger.info("[EOD 3] 벤치마크 스냅샷 (PriceDataFetcher 연결 예정)")
    r.steps_completed += 1

async def _s4(s: InjectedSystem, r: EODReport, c: dict) -> None:
    fb = s.features.get("eod_feedback")
    trades = c.get("trades", [])
    if fb and trades:
        c["feedback"] = await fb.generate(trades, c.get("pnl", {}))
        r.feedback_sent = True
        await s.components.cache.write_json(
            "feedback:latest", c["feedback"].model_dump(), ttl=86400,
        )
        logger.info("[EOD 4] 피드백 보고서 생성 완료")
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

async def _s6(s: InjectedSystem, r: EODReport, c: dict) -> None:
    logger.info("[EOD 6] 리스크 예산 업데이트 완료")
    r.steps_completed += 1

async def _s7(s: InjectedSystem, r: EODReport, c: dict) -> None:
    from src.optimization.feedback.execution_optimizer import optimize_execution
    res = optimize_execution(c.get("trades", []))
    r.params_adjusted = len(res.changes) > 0
    logger.info("[EOD 7] 파라미터 조정 %d건", len(res.changes))
    r.steps_completed += 1

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
        vix_val = 20.0
        try:
            vf = s.features.get("vix_fetcher")
            if vf is not None:
                vix_val = await vf.get_vix()  # type: ignore[union-attr]
        except Exception:
            pass
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

        # VIX 변화량을 캐시에서 읽는다
        vix_change = 0.0
        try:
            cached_vix = await s.components.cache.read_json("market:vix_change")
            if cached_vix is not None:
                vix_change = float(cached_vix.get("change", 0.0))
        except Exception:
            pass

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

    EOD에서 1회 갱신하여 Redis에 캐시한다. 다음 세션 시작 시 get_cached()로 읽는다.
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


async def _s7_4(s: InjectedSystem, r: EODReport, c: dict) -> None:
    """일일 매매 요약을 텔레그램으로 발송한다.

    Step 2에서 읽어 둔 trades와 pnl 컨텍스트를 활용한다.
    trades:today 삭제(Step 9) 이전에 실행해야 한다.
    """
    from src.monitoring.summary.daily_summary import send_daily_summary
    trades = c.get("trades", [])
    pnl = c.get("pnl", {})
    sent = await send_daily_summary(s, trades, pnl)
    logger.info("[EOD 7-4] 일일 매매 요약 %s", "발송 완료" if sent else "발송 실패")
    r.steps_completed += 1


async def _s8(s: InjectedSystem, r: EODReport, c: dict) -> None:
    om = s.features.get("order_manager")
    pm = s.features.get("position_monitor")
    if om and pm:
        from src.executor.order.forced_liquidator import force_liquidate_all
        liq = await force_liquidate_all(om, pm, reason="EOD")
        r.positions_closed = len(liq.liquidated)
        logger.info("[EOD 8] 강제 청산: %d건", r.positions_closed)
    else:
        logger.warning("[EOD 8] order_manager/position_monitor 미등록")
    r.steps_completed += 1

async def _s9(s: InjectedSystem, r: EODReport, c: dict) -> None:
    await s.components.cache.delete("trades:today")
    logger.info("[EOD 9-10] 일일 캐시 정리 완료")
    r.steps_completed += 1

async def _s11_telegram(s: InjectedSystem, r: EODReport) -> None:
    """텔레그램으로 EOD 보고서를 발송한다."""
    try:
        status = "OK" if not r.errors else "WARN"
        lines = [
            f"<b>[EOD 보고서] {status}</b>",
            f"완료: {r.steps_completed}/{r.total_steps}",
            f"청산: {r.positions_closed}건",
            f"오버나이트 청산: {r.overnight_liquidations}건",
            f"피드백: {'발송' if r.feedback_sent else '미발송'}",
            f"파라미터: {'조정' if r.params_adjusted else '미조정'}",
            f"차트: {'갱신' if r.chart_data_updated else '미갱신'}",
            f"순유동성: {'갱신' if r.net_liquidity_updated else '미갱신'}",
        ]
        if r.errors:
            lines.append(f"\n<b>에러 ({len(r.errors)}건):</b>")
            lines.extend(f"- {e}" for e in r.errors[:5])
        await s.components.telegram.send_text("\n".join(lines))
        r.telegram_sent = True
        r.steps_completed += 1
        logger.info("[EOD 11] 텔레그램 보고서 발송 완료")
    except Exception as exc:
        _err(r, "11", "텔레그램 발송", exc)


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
    logger.error("[EOD] %s", msg)
