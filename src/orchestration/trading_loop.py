"""
15분 매매 루프 1회 반복을 실행하는 모듈.

TradingSystem에서 분리된 run_trading_loop_iteration() 함수를 제공한다.
매 15분마다 호출되어 delta 크롤링 -> 분류 -> 리스크 체크 -> 의사결정 -> 매매 -> 모니터링을 수행한다.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.main import TradingSystem

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

_PRICE_HISTORY_DAYS: int = 200          # 기술적 지표 계산용 가격 데이터 기간 (영업일)
_MAX_ERROR_MSG_CHARS: int = 300         # 텔레그램 에러 메시지 최대 문자 수


async def run_trading_loop_iteration(ts: TradingSystem) -> dict[str, Any]:
    """15분 매매 루프의 1회 반복을 실행한다.

    Args:
        ts: TradingSystem 인스턴스. 필요한 모든 의존성을 갖고 있다.

    Returns:
        루프 반복 실행 결과.
    """
    from datetime import datetime, timezone

    logger.info("========== TRADING LOOP ITERATION ==========")
    results: dict[str, Any] = {}

    # 루프 카운터 증가 (일일 보고서용)
    ts._trading_loop_count += 1
    loop_num = ts._trading_loop_count
    loop_start_time = datetime.now(tz=timezone.utc)

    try:
        # 0. 긴급 프로토콜 체크 (circuit breaker)
        vix = await ts._fetch_vix()
        # SPY 일중 변동률 조회 (실패 시 None → 신규매수 보류 모드)
        spy_change: float | None = None
        spy_data_available = True
        try:
            spy_data = await ts.data_fetcher.fetch_current_price("SPY")
            if spy_data:
                raw_change = spy_data.get("change_pct")
                if isinstance(raw_change, (int, float)):
                    spy_change = float(raw_change)
            if spy_change is None:
                logger.warning("SPY change_pct 값이 없거나 유효하지 않음 - 데이터 부족 모드로 전환")
                spy_data_available = False
        except Exception as _spy_exc:
            logger.error(
                "SPY 일중 변동률 조회 실패 - 데이터 부족 모드로 전환 (신규매수 보류): %s",
                _spy_exc,
                exc_info=True,
            )
            spy_data_available = False

        # SPY 데이터 없을 시 circuit breaker 판단에 보수적 기본값 사용
        spy_change_for_cb: float = spy_change if spy_change is not None else 0.0
        if await ts.emergency_protocol.detect_circuit_breaker(vix, spy_change_for_cb):
            logger.warning("Circuit breaker 발동 - 이번 루프 건너뜀")
            # 리스크 게이트 차단으로 기록
            spy_display = f"{spy_change:+.2f}%" if spy_change is not None else "데이터 없음"
            ts._risk_gate_blocks.append({
                "loop": loop_num,
                "time": loop_start_time.isoformat(),
                "gate": "circuit_breaker",
                "reason": f"VIX={vix:.1f}, SPY 변동={spy_display}",
                "action": "halt",
            })
            try:
                spy_note = "" if spy_data_available else " (데이터 조회 실패)"
                spy_msg = f"{spy_change:+.2f}%{spy_note}" if spy_change is not None else f"조회 실패{spy_note}"
                await ts.telegram_notifier.send_message(
                    title="CIRCUIT BREAKER 발동",
                    message=f"VIX: {vix:.1f}\nSPY 변동: {spy_msg}\n모든 매매가 일시 중단되었습니다.",
                    severity="critical",
                )
            except Exception as exc:
                logger.debug("Circuit breaker 텔레그램 알림 실패: %s", exc)
            return {"skipped": True, "reason": "circuit_breaker"}

        # 1. Delta crawl (빠른 크롤링) + Tier 기반 크롤링
        logger.info("[1/7] Delta crawling...")
        crawl_result = await ts.crawl_engine.run(mode="delta")
        results["crawl"] = crawl_result
        new_articles_count = crawl_result.get("saved", 0)
        logger.info("Delta crawl: %d new articles", new_articles_count)

        # 1-1. Tier 기반 실시간 데이터 수집 (장애 격리)
        crawl_context = ""
        try:
            from src.crawler.ai_context_builder import build_ai_context_compact

            tier_result = await ts.crawl_engine.run_fault_isolated(
                source_keys=[
                    "cnn_fear_greed", "polymarket", "kalshi",
                    "finviz", "investing_com", "stocknow",
                ],
            )
            tier_articles = tier_result.get("articles", [])
            if tier_articles:
                crawl_context = build_ai_context_compact(tier_articles)
            results["tier_crawl"] = {
                "total_raw": tier_result.get("total_raw", 0),
                "source_stats": tier_result.get("source_stats", {}),
            }
            logger.info(
                "Tier 크롤링 완료: %d건, 컨텍스트 길이=%d",
                tier_result.get("total_raw", 0),
                len(crawl_context),
            )
        except Exception as exc:
            logger.warning("Tier 크롤링 실패 (무시하고 계속): %s", exc)

        # 2. Classify new articles (if any)
        if new_articles_count > 0:
            logger.info("[2/7] Classifying new articles...")
            articles = await ts._fetch_latest_articles(limit=new_articles_count)
            new_signals = await ts.classifier.classify_batch(articles)
            results["new_signals"] = new_signals
            logger.info("Classified %d new signals", len(new_signals))
        else:
            results["new_signals"] = []

        # 3. Risk gate pre-check (Addendum 26)
        logger.info("[3/7] Risk gate pre-check...")
        portfolio = await ts.position_monitor.get_portfolio_summary()
        gate_result = await ts.risk_gate_pipeline.check_all(portfolio)
        results["risk_gates"] = {
            "can_trade": gate_result.can_trade,
            "blocking_gates": gate_result.blocking_gates,
            "overall_action": gate_result.overall_action,
        }
        if not gate_result.can_trade:
            # 리스크 게이트 차단 내역을 누적 기록한다.
            for gr in gate_result.gate_results:
                if not gr.passed:
                    ts._risk_gate_blocks.append({
                        "loop": loop_num,
                        "time": loop_start_time.isoformat(),
                        "gate": gr.gate_name,
                        "reason": gr.message,
                        "action": gr.action,
                        "details": gr.details if hasattr(gr, "details") else {},
                    })
            logger.warning(
                "리스크 게이트 차단 - 매매 건너뜀 | blocking=%s",
                gate_result.blocking_gates,
            )
            try:
                await ts.telegram_notifier.send_message(
                    title="리스크 게이트 차단",
                    message=f"차단 게이트: {gate_result.blocking_gates}\n조치: {gate_result.overall_action}",
                    severity="warning",
                )
            except Exception as exc:
                logger.debug("리스크 게이트 텔레그램 알림 실패: %s", exc)
            return results

        # 4. Make decisions (with risk + profit context)
        logger.info("[4/7] Making trading decisions...")
        regime = await ts._get_current_regime()

        # 포지션 목록 추출 및 타입 정규화 (dict/list 모두 지원)
        raw_positions = portfolio.get("positions", [])
        positions = list(raw_positions.values()) if isinstance(raw_positions, dict) else raw_positions

        # SPY 데이터 부족 시 신규매수 보류 여부를 결정 컨텍스트에 전달한다.
        if not spy_data_available:
            logger.warning("SPY 데이터 부족 - 신규매수 보류 플래그 설정")

        # 관련 종목의 가격 데이터 조회 (레버리지 ETF는 본주 데이터로 분석)
        from src.utils.ticker_mapping import get_analysis_ticker as _get_analysis_ticker
        price_data: dict[str, Any] = {}
        tickers: set[str] = set()
        for sig in results.get("new_signals", []):
            tickers.update(sig.get("tickers", []))
        for ticker in tickers:
            try:
                # 레버리지 ETF인 경우 본주 티커로 가격 데이터를 조회한다.
                analysis_ticker = _get_analysis_ticker(ticker)
                if analysis_ticker not in price_data:
                    df = await ts.data_fetcher.get_daily_prices(analysis_ticker, days=_PRICE_HISTORY_DAYS)
                    if df is not None and not df.empty:
                        price_data[analysis_ticker] = df
                # 원래 티커로도 매핑하여 decision_maker의 fallback이 동작하도록 한다.
                if analysis_ticker != ticker and ticker not in price_data:
                    price_data[ticker] = price_data.get(analysis_ticker)
            except Exception as exc:
                logger.debug("티커 %s 가격 데이터 조회 실패: %s", ticker, exc)

        # 수익 목표 및 리스크 컨텍스트를 AI 판단에 추가 (Addendum 25/26)
        profit_context = await ts.profit_target_manager.get_context()
        risk_context = ts.risk_gate_pipeline.get_context()

        decisions = await ts.decision_maker.make_decision(
            results.get("new_signals", []),
            positions,
            regime.get("regime", "sideways"),
            price_data,
            crawl_context=crawl_context,
            profit_context=profit_context,
            risk_context=risk_context,
            comprehensive_analysis=ts._comprehensive_analysis,
        )
        results["decisions"] = decisions
        results["profit_context"] = profit_context
        results["risk_context"] = risk_context
        logger.info("Generated %d trade decisions", len(decisions))

        # AI 매매 판단 결과를 일일 보고서용으로 누적 기록한다.
        for dec in decisions:
            ts._today_decisions.append({
                "loop": loop_num,
                "time": loop_start_time.isoformat(),
                "ticker": dec.get("ticker", "?"),
                "action": dec.get("action", "hold"),
                "confidence": dec.get("confidence", 0.0),
                "reason": dec.get("reason", ""),
                "weight_pct": dec.get("weight_pct", 0.0),
                "direction": dec.get("direction", "long"),
                "time_horizon": dec.get("time_horizon", "intraday"),
                "take_profit_pct": dec.get("take_profit_pct", 0.0),
                "stop_loss_pct": dec.get("stop_loss_pct", 0.0),
            })

        # 5. Execute trades (with risk gate order-level check)
        logger.info("[5/7] Executing trades...")
        execution_results = await ts._execute_decisions(decisions, portfolio, vix)
        results["executions"] = execution_results
        logger.info("Executed %d trades", len(execution_results))

        # 주문 단위 리스크 게이트 차단도 누적 기록한다.
        for exec_r in execution_results:
            if exec_r is None:
                continue
            if exec_r.get("skipped") and exec_r.get("reason"):
                ts._risk_gate_blocks.append({
                    "loop": loop_num,
                    "time": loop_start_time.isoformat(),
                    "gate": "order_check",
                    "ticker": exec_r.get("decision", {}).get("ticker", "?"),
                    "reason": exec_r.get("reason", ""),
                    "action": "block",
                })

        # 매매 체결 시 텔레그램 알림 (AI 매매 근거 3줄 요약 포함)
        for exec_result in execution_results:
            if exec_result is None:
                continue
            try:
                ai_decision = exec_result.pop("_ai_decision", None)
                await ts.telegram_notifier.send_trade_notification(
                    exec_result,
                    decision=ai_decision,
                )
            except Exception as exc:
                logger.debug("매매 체결 텔레그램 알림 실패: %s", exc)

        # 6. Monitor positions (with trailing stop)
        logger.info("[6/7] Monitoring positions...")
        await ts.position_monitor.sync_positions()
        current_regime = regime.get("regime", "sideways") if isinstance(regime, dict) else str(regime)
        monitor_results = await ts.position_monitor.monitor_all(
            regime=current_regime, vix=vix,
        )
        results["monitoring"] = monitor_results
        logger.info("Monitored %d positions", len(monitor_results))

        # 7. Trailing stop check (Addendum 26)
        logger.info("[7/7] Trailing stop check...")
        try:
            current_prices: dict[str, float] = {}
            # positions는 함수 초입에서 항상 list로 정규화되어 있다.
            for pos in positions:
                t = pos.get("ticker", "")
                p = pos.get("current_price", 0.0)
                if t and p > 0:
                    current_prices[t] = p
            stop_signals = ts.trailing_stop_loss.check_all_positions(current_prices)
            if stop_signals:
                logger.warning("트레일링 스톱 발동: %d건", len(stop_signals))
                results["trailing_stop_signals"] = stop_signals
                # 트레일링 스톱 발동 텔레그램 알림
                try:
                    stop_msg = "\n".join(
                        f"- {s.get('ticker', '?')}: {s.get('loss_pct', 0):+.2f}%"
                        for s in stop_signals
                    )
                    await ts.telegram_notifier.send_message(
                        title=f"트레일링 스톱 발동 ({len(stop_signals)}건)",
                        message=stop_msg,
                        severity="critical",
                    )
                except Exception as exc:
                    logger.debug("트레일링 스톱 텔레그램 알림 실패: %s", exc)
        except Exception as exc:
            logger.warning("트레일링 스톱 체크 실패: %s", exc)

    except Exception as exc:
        logger.exception("Trading loop iteration failed: %s", exc)
        await ts.alert_manager.send_alert(
            "trading", "Trading loop iteration exception", str(exc), "error",
        )
        # 트레이딩 루프 오류 텔레그램 알림
        try:
            await ts.telegram_notifier.send_message(
                title="트레이딩 루프 오류",
                message=str(exc)[:_MAX_ERROR_MSG_CHARS],
                severity="critical",
            )
        except Exception as tg_exc:
            logger.debug("트레이딩 루프 오류 텔레그램 알림 실패: %s", tg_exc)
        results["error"] = str(exc)

    return results
