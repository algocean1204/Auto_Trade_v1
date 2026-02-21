"""
Pre-market 준비 단계 모듈.

TradingSystem에서 분리된 run_preparation_phase() 함수를 제공한다.
매일 23:00 KST에 호출되어 전체 크롤링 -> 검증 -> 분류 -> 분석 -> 안전 체크를 수행한다.
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from src.analysis.prompts import get_system_prompt
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.main import TradingSystem

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

_PREP_ARTICLE_LIMIT: int = 20           # 준비 단계 분류용 최신 기사 조회 건수
_MAX_HIGH_IMPACT_TELEGRAM: int = 10     # 텔레그램 HIGH 임팩트 뉴스 최대 전송 건수
_MAX_TICKERS_PER_SIGNAL: int = 5        # 신호당 최대 표시 종목 수


async def run_preparation_phase(ts: TradingSystem) -> dict[str, Any]:
    """Pre-market 준비 단계를 실행한다 (23:00 KST).

    Args:
        ts: TradingSystem 인스턴스. 필요한 모든 의존성을 갖고 있다.

    Returns:
        준비 단계 실행 결과.
    """
    logger.info("========== PREPARATION PHASE START (23:00 KST) ==========")
    results: dict[str, Any] = {}

    try:
        # 1. Infrastructure check
        logger.info("[1/10] Infrastructure check...")
        infra_status = await ts._check_infrastructure()
        results["infrastructure"] = infra_status
        if not infra_status["all_ok"]:
            await ts.alert_manager.send_alert(
                "system", "Infrastructure check failed", str(infra_status), "critical",
            )
            return results

        # 2. Full crawling (23:05~23:25)
        logger.info("[2/10] Full crawling (20+ sources)...")
        crawl_result = await ts.crawl_engine.run(mode="full")
        results["crawl"] = crawl_result
        logger.info(
            "Crawl complete: saved=%d, total_raw=%d",
            crawl_result.get("saved", 0),
            crawl_result.get("total_raw", 0),
        )

        # 2-1. Fear & Greed 일일 수집 (장 시작 전 기준값 확보)
        logger.info("[2-1] Fear & Greed daily collection...")
        try:
            fg_result = await ts.crawl_engine.run(
                mode="full",
                source_keys=["cnn_fear_greed"],
            )
            results["fear_greed"] = fg_result
            logger.info(
                "Fear & Greed 수집 완료: %d건",
                fg_result.get("saved", 0),
            )
        except Exception as exc:
            logger.warning("Fear & Greed 수집 실패: %s", exc)

        # 3. Crawl verification (23:25~23:28)
        logger.info("[3/10] Crawl verification (Claude Sonnet)...")
        verification_prompt = ts.crawl_verifier.build_verification_prompt(crawl_result)
        verification_response = await ts.fallback_router.call(
            verification_prompt,
            task_type="crawl_verification",
            system_prompt=get_system_prompt("crawl_verification"),
        )
        verification_result = ts.crawl_verifier.parse_verification_result(verification_response)
        results["verification"] = verification_result
        logger.info("Crawl quality: %s", verification_result.get("overall_quality", "unknown"))

        # 4. Classification + Summarization (23:28~23:48)
        logger.info("[4/10] Classification + Summarization (batch)...")
        articles = await ts._fetch_latest_articles(limit=_PREP_ARTICLE_LIMIT)
        classified_signals = await ts.classifier.classify_and_store_batch(articles)
        results["classified_signals"] = classified_signals
        logger.info("Classified %d signals", len(classified_signals))

        # 4-1. 분류된 주요 뉴스 텔레그램 전송
        _high_impact_signals = [
            s for s in classified_signals if s.get("impact") == "high"
        ]
        _medium_count = sum(1 for s in classified_signals if s.get("impact") == "medium")
        _low_count = sum(1 for s in classified_signals if s.get("impact") == "low")

        try:
            if _high_impact_signals and ts.telegram_notifier:
                # 기사 원문 정보와 분류 결과를 매칭하여 메시지 구성
                article_map = {str(a.get("id", "")): a for a in articles}
                msg_lines = []
                for sig in _high_impact_signals[:_MAX_HIGH_IMPACT_TELEGRAM]:
                    article = article_map.get(str(sig.get("id", "")), {})
                    title = article.get("title", sig.get("id", "N/A"))
                    tickers = ", ".join(sig.get("tickers", [])[:_MAX_TICKERS_PER_SIGNAL])
                    direction = sig.get("direction", "neutral")
                    score = sig.get("sentiment_score", 0.0)
                    category = sig.get("category", "other")
                    direction_emoji = (
                        "📈" if direction == "bullish"
                        else "📉" if direction == "bearish"
                        else "➡️"
                    )
                    msg_lines.append(
                        f"{direction_emoji} [{category.upper()}] {title}\n"
                        f"  종목: {tickers} | 감성: {score:+.2f}"
                    )

                if msg_lines:
                    summary_msg = "\n\n".join(msg_lines)
                    await ts.telegram_notifier.send_message(
                        title=f"Pre-Market 주요뉴스 ({len(_high_impact_signals)}건)",
                        message=summary_msg,
                        severity="warning",
                    )
                    logger.info(
                        "Pre-Market 주요뉴스 텔레그램 전송 완료: %d건",
                        len(_high_impact_signals),
                    )
        except Exception as exc:
            logger.warning("Pre-Market 텔레그램 뉴스 전송 실패: %s", exc)

        # medium/low impact 요약 전송
        try:
            if ts.telegram_notifier:
                await ts.telegram_notifier.send_message(
                    title="Pre-Market 뉴스 분류 완료",
                    message=(
                        f"전체: {len(classified_signals)}건\n"
                        f"HIGH: {len(_high_impact_signals)}건\n"
                        f"MEDIUM: {_medium_count}건\n"
                        f"LOW: {_low_count}건"
                    ),
                    severity="info",
                )
        except Exception as exc:
            logger.warning("뉴스 분류 요약 텔레그램 전송 실패: %s", exc)

        # Auto-update RAG documents
        try:
            await ts.rag_doc_updater.update_from_daily(classified_signals)
        except Exception as exc:
            logger.warning("RAG 문서 업데이트 실패: %s", exc)

        # 5. Market analysis (23:48~23:55)
        logger.info("[5/10] Market analysis (Opus)...")
        vix = await ts._fetch_vix()
        regime = await ts.regime_detector.detect(vix, classified_signals)
        results["regime"] = regime
        logger.info("Market regime: %s (VIX=%.2f)", regime.get("regime", "unknown"), vix)

        # 5-1. 종합분석팀 시장 분석
        logger.info("[5-1] Comprehensive Analysis Team...")
        try:
            if ts.comprehensive_team is not None:
                # Fear & Greed 점수 조회
                fg_score: float | None = None
                try:
                    from src.monitoring.fred_client import fetch_cnn_fear_greed
                    fg_data = await fetch_cnn_fear_greed()
                    fg_score = fg_data.get("score") if fg_data else None
                except Exception as fg_exc:
                    logger.warning("종합분석팀 Fear&Greed 조회 실패: %s", fg_exc)

                # 기술적 지표 수집 (주요 섹터 본주 기준)
                tech_indicators: dict = {}
                try:
                    from src.utils.ticker_mapping import SECTOR_TICKERS
                    _key_tickers = ["SOXX", "QQQ", "SPY"]
                    for _sector_info in SECTOR_TICKERS.values():
                        for _t in _sector_info["tickers"][:2]:
                            if _t not in _key_tickers:
                                _key_tickers.append(_t)
                        if len(_key_tickers) >= 10:
                            break

                    for _t in _key_tickers[:10]:
                        try:
                            # PriceDataFetcher.fetch()는 존재하지 않는다.
                            # 올바른 메서드명은 get_daily_prices()이다.
                            _df = await ts.data_fetcher.get_daily_prices(_t, days=100)
                            if _df is not None and not _df.empty:
                                tech_indicators[_t] = ts.technical_calculator.calculate_all(_df)
                        except Exception as ind_exc:
                            logger.debug("종합분석팀 지표 조회 실패 (%s): %s", _t, ind_exc)
                except Exception as tech_exc:
                    logger.warning("종합분석팀 기술적 지표 수집 실패: %s", tech_exc)

                # 포지션 조회
                positions_list: list[dict] = []
                try:
                    pos_dict = await ts.position_monitor.sync_positions()
                    positions_list = list(pos_dict.values())
                except Exception as pos_exc:
                    logger.debug("종합분석팀 포지션 조회 실패: %s", pos_exc)

                # 과거분석 타임라인 (Redis에 저장된 것 있으면)
                historical_ctx: str | None = None
                try:
                    hist_raw = await ts.redis.get("historical_analysis:latest")
                    if hist_raw:
                        historical_ctx = hist_raw if isinstance(hist_raw, str) else hist_raw.decode("utf-8")
                except Exception:
                    pass

                # 종합분석 실행
                comprehensive_result = await ts.comprehensive_team.analyze_market(
                    classified_articles=classified_signals,
                    regime=regime,
                    tech_indicators=tech_indicators,
                    positions=positions_list,
                    historical_context=historical_ctx,
                    fear_greed=fg_score,
                    vix=vix,
                )
                results["comprehensive_analysis"] = comprehensive_result
                ts._comprehensive_analysis = comprehensive_result

                # Redis에 저장
                try:
                    ca_json = json.dumps(comprehensive_result, ensure_ascii=False, default=str)
                    await ts.redis.set("comprehensive_analysis:latest", ca_json, ex=7200)
                except Exception as redis_exc:
                    logger.warning("종합분석 Redis 저장 실패: %s", redis_exc)

                # 텔레그램 전송
                try:
                    if ts.telegram_notifier:
                        await ts.telegram_notifier.send_comprehensive_analysis(
                            comprehensive_result
                        )
                except Exception as tg_exc:
                    logger.warning("종합분석 텔레그램 전송 실패: %s", tg_exc)

                logger.info(
                    "종합분석팀 완료: outlook=%s, confidence=%.2f",
                    comprehensive_result.get("session_outlook", "unknown"),
                    comprehensive_result.get("confidence", 0.0),
                )
            else:
                logger.debug("comprehensive_team 미초기화 -- 종합분석 건너뜀")
        except Exception as exc:
            logger.warning("종합분석팀 실행 실패: %s", exc)

        # 6. Account safety 3종 세트 확인
        logger.info("[6/10] Account safety check...")
        try:
            account_check = await ts.account_safety.check_all()
            results["account_safety"] = account_check
            if not account_check.get("safe_to_trade"):
                await ts.alert_manager.send_alert(
                    "system", "Account safety check failed", str(account_check), "critical",
                )
        except Exception as exc:
            logger.warning("계좌 안전 점검 실패: %s", exc)

        # 7. 환율 기록
        logger.info("[7/10] FX rate recording...")
        try:
            rate = await ts.fx_manager.fetch_current_rate()
            await ts.fx_manager.record_rate(rate)
            results["fx_rate"] = rate
        except Exception as exc:
            logger.warning("환율 기록 실패: %s", exc)

        # 8. Risk backtest auto-run (Addendum 26)
        logger.info("[8/10] Risk backtest auto-run...")
        try:
            backtest_result = await ts.risk_backtester.run_backtest()
            results["risk_backtest"] = backtest_result
        except Exception as exc:
            logger.warning("리스크 백테스트 자동 실행 실패: %s", exc)

        # 9. Profit target refresh (Addendum 25)
        logger.info("[9/10] Profit target refresh...")
        try:
            await ts.profit_target_manager.get_monthly_target_from_db()
            await ts.profit_target_manager.update_aggression()
        except Exception as exc:
            logger.warning("수익 목표 갱신 실패: %s", exc)

        # 9-1. Ticker-level AI parameter optimization (1일 1회)
        logger.info("[9-1] Ticker-level AI parameter optimization...")
        try:
            if ts.ticker_params_manager is not None:
                ticker_opt_result = await ts.ticker_params_manager.ai_optimize_all(
                    ts.kis_client
                )
                results["ticker_params_optimization"] = ticker_opt_result
                logger.info(
                    "종목별 파라미터 최적화 완료: %s",
                    ticker_opt_result.get("status", "unknown"),
                )
            else:
                logger.debug("ticker_params_manager 미초기화 -- 종목별 최적화 건너뜀")
        except Exception as exc:
            logger.warning("종목별 파라미터 AI 최적화 실패: %s", exc)

        # 10. Safety check (23:55~23:59)
        logger.info("[10/10] Safety check...")
        safety_result = await ts.safety_checker.pre_session_check()
        results["safety"] = safety_result

        if not safety_result.get("safe_to_trade", False):
            await ts.alert_manager.send_alert(
                "safety", "Safety check FAILED", str(safety_result), "critical",
            )
        else:
            logger.info("Safety check PASSED - ready to trade")

        logger.info("========== PREPARATION PHASE COMPLETE ==========")

    except Exception as exc:
        logger.exception("Preparation phase failed: %s", exc)
        await ts.alert_manager.send_alert(
            "system", "Preparation phase exception", str(exc), "critical",
        )
        results["error"] = str(exc)

    return results
