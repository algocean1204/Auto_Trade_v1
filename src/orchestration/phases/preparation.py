"""F9.3 PreparationPhase -- 매매 시작 전 사전 준비를 실행한다."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from src.analysis.classifier.key_news_filter import HIGH_IMPACT_THRESHOLD
from src.common.event_bus import EventType, get_event_bus
from src.common.logger import get_logger
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)

# 매매 세션이 KST 기준이므로 뉴스 날짜 그룹핑도 KST를 사용한다
_KST = ZoneInfo("Asia/Seoul")

_HIGH_IMPACT_THRESHOLD: float = HIGH_IMPACT_THRESHOLD
_CLASSIFIED_CACHE_KEY: str = "news:classified_latest"
_SUMMARY_CACHE_KEY: str = "news:latest_summary"
# news_pipeline.py의 _DAILY_CACHE_TTL(86400)과 동일한 TTL을 사용한다.
# 이전 값(7200)은 뉴스 캐시가 2시간 만에 만료되어 파이프라인 실행 전에
# 소비자(trading_loop, continuous_analysis)가 빈 데이터를 읽는 문제가 있었다.
_CACHE_TTL: int = 86400


class InfraHealthResult(BaseModel):
    """인프라 건강 검사 결과이다."""
    db_ok: bool
    cache_ok: bool
    broker_ok: bool
    all_healthy: bool
    errors: list[str] = []


class PreparationResult(BaseModel):
    """사전 준비 결과이다."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    infra_health: InfraHealthResult
    ready: bool
    regime: str = "unknown"
    classified_count: int = 0
    safety_passed: bool = True
    errors: list[str] = []


async def check_infrastructure(system: InjectedSystem) -> InfraHealthResult:
    """인프라 건강 상태를 검사한다 (fail-fast)."""
    errors: list[str] = []
    try:
        async with system.components.db.get_session() as s:
            await s.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.error("DB 건강 검사 실패: %s", exc, exc_info=True)
        db_ok, _ = False, errors.append("DB 연결 실패")
    try:
        cache_ok = await system.components.cache.ping()
    except Exception as exc:
        logger.error("캐시 건강 검사 실패: %s", exc, exc_info=True)
        cache_ok = False
    if not cache_ok:
        errors.append("캐시 연결 실패")
    try:
        broker = system.components.broker
        # 가상/실전 중 하나라도 토큰 발급에 성공하면 정상으로 판단한다
        auths = [a for a in (broker.virtual_auth, broker.real_auth) if a is not None]
        if not auths:
            raise RuntimeError("가상/실전 인증 객체가 모두 None이다")
        broker_ok = False
        for auth in auths:
            try:
                await auth.get_token()
                broker_ok = True
                break
            except Exception:
                continue
        if not broker_ok:
            raise RuntimeError("모든 KIS 인증 토큰 발급 실패")
    except Exception as exc:
        logger.error("Broker 건강 검사 실패: %s", exc, exc_info=True)
        broker_ok, _ = False, errors.append("Broker 토큰 검증 실패")
    all_healthy = db_ok and cache_ok and broker_ok
    result = InfraHealthResult(
        db_ok=db_ok, cache_ok=cache_ok, broker_ok=broker_ok,
        all_healthy=all_healthy, errors=errors)
    level = logger.info if all_healthy else logger.warning
    level("인프라 건강 검사 %s: %s", "통과" if all_healthy else "실패", errors or "정상")
    return result


# -- Step 1~6 --

async def _refresh_kis_token(system: InjectedSystem) -> None:
    """KIS 토큰을 강제 재발급한다. (Step 1)

    매매 시작 시점에 항상 유효한 토큰을 확보하기 위해 강제 갱신한다.
    KIS 토큰은 상시 재발급 가능하므로 기존 토큰 만료 여부와 무관하게 갱신한다.
    """
    try:
        broker = system.components.broker
        if broker.virtual_auth is not None:
            await broker.virtual_auth.force_refresh()
        if broker.real_auth is not None:
            await broker.real_auth.force_refresh()
        logger.info("[Step 1] KIS 토큰 강제 재발급 완료")
    except Exception as exc:
        logger.warning("[Step 1] KIS 토큰 재발급 실패: %s", exc)


async def _run_news_crawl(system: InjectedSystem) -> tuple[int, list[Any]]:
    """뉴스 크롤링 + EventBus 임시 수집 패턴으로 기사를 반환한다. (Step 2)"""
    try:
        scheduler = system.features.get("crawl_scheduler")
        engine = system.features.get("crawl_engine")
        if scheduler is None or engine is None:
            logger.warning("[Step 2] 크롤링 Feature 미등록 (건너뜀)")
            return 0, []
        collected: list[Any] = []
        bus = get_event_bus()
        bus.subscribe(EventType.ARTICLE_COLLECTED, collected.append)
        try:
            schedule = scheduler.build_schedule(fast_mode=True)  # type: ignore[union-attr]
            result = await engine.run(schedule)  # type: ignore[union-attr]
            logger.info("[Step 2] 크롤링 완료: new=%d, collected=%d",
                        result.new_count, len(collected))
            return result.new_count, collected
        finally:
            bus.unsubscribe(EventType.ARTICLE_COLLECTED, collected.append)
    except Exception as exc:
        logger.warning("[Step 2] 뉴스 크롤링 실패 (건너뜀): %s", exc)
        return 0, []


async def _classify_news(system: InjectedSystem, articles: list[Any]) -> int:
    """뉴스를 분류하고 고영향 뉴스를 캐시한다. (Step 3)

    news_pipeline.py와 동일한 캐시 키를 사용하므로, 파이프라인 실행 중이면
    분류를 건너뛰어 경합을 방지한다. 텔레그램 전송은 news_pipeline에 위임한다.
    """
    if not articles:
        logger.info("[Step 3] 분류할 기사 없음 (건너뜀)")
        return 0

    # 뉴스 파이프라인이 이미 실행 중이면 분류를 건너뛴다 (캐시 키 경합 방지)
    try:
        from src.orchestration.phases.news_pipeline import _pipeline_lock
        if _pipeline_lock.locked():
            logger.info("[Step 3] 뉴스 파이프라인 실행 중 — 분류 건너뜀 (경합 방지)")
            return 0
    except ImportError:
        pass

    try:
        classifier = system.features.get("news_classifier")
        if classifier is None:
            logger.warning("[Step 3] NewsClassifier 미등록 (건너뜀)")
            return 0
        import asyncio as _asyncio
        classified = await _asyncio.wait_for(
            classifier.classify(articles),  # type: ignore[union-attr]
            timeout=120.0,  # 2분 타임아웃 — stuck 방지
        )
        classified_dicts = [item.model_dump() for item in classified]
        logger.info("[Step 3] 뉴스 분류 완료: %d건", len(classified_dicts))
        high_impact = [a for a in classified_dicts
                       if a.get("impact_score", 0.0) >= _HIGH_IMPACT_THRESHOLD]
        await _cache_classified(system, classified_dicts, high_impact)
        # 핵심 뉴스를 별도 키에 저장하여 연속 분석에서 활용할 수 있도록 한다
        if high_impact:
            # news_pipeline.py의 KeyNews 스키마와 동일한 형식으로 저장한다
            key_news_dicts = [
                {
                    "title": a.get("title", ""),
                    "impact_score": a.get("impact_score", 0.0),
                    "direction": a.get("direction", "neutral"),
                    "category": a.get("category", "other"),
                    "tickers_affected": a.get("tickers_affected", []),
                    "summary": a.get("reasoning", ""),
                    "source": a.get("source", "") or "unknown",
                }
                for a in high_impact[:20]
            ]
            await system.components.cache.write_json(
                "news:key_latest", key_news_dicts, ttl=_CACHE_TTL,
            )
        return len(classified_dicts)
    except Exception as exc:
        logger.warning("[Step 3] 뉴스 분류 실패 (건너뜀): %s", exc)
        return 0


async def _cache_classified(
    system: InjectedSystem, classified: list[dict[str, Any]],
    high_impact: list[dict[str, Any]],
) -> None:
    """분류된 뉴스와 고영향 요약을 캐시에 저장한다.

    빈 결과는 기존 캐시를 덮어쓰지 않는다 (분류 실패 시 데이터 유실 방지).
    """
    if not classified:
        logger.debug("[Step 3] 분류된 뉴스 0건 — 기존 캐시 유지")
        return
    try:
        cache = system.components.cache
        # 기존 캐시와 URL 기준 중복 제거 후 병합한다 (news_pipeline.py와 동일 패턴)
        existing_raw = await cache.read_json(_CLASSIFIED_CACHE_KEY)
        existing: list[dict] = existing_raw if isinstance(existing_raw, list) else []
        classified_by_url: dict[str, dict] = {a.get("url", ""): a for a in existing}
        for a in classified:
            classified_by_url[a.get("url", "")] = a
        merged = list(classified_by_url.values())
        await cache.write_json(_CLASSIFIED_CACHE_KEY, merged, ttl=_CACHE_TTL)
        # news_pipeline.py의 _build_summary()와 동일한 스키마로 작성한다
        sentiment: dict[str, int] = {"bullish": 0, "bearish": 0, "neutral": 0}
        by_category: dict[str, int] = {}
        for a in classified:
            direction = a.get("direction", "neutral")
            sentiment[direction] = sentiment.get(direction, 0) + 1
            cat = a.get("category", "other")
            by_category[cat] = by_category.get(cat, 0) + 1
        await cache.write_json(
            _SUMMARY_CACHE_KEY,
            {
                "date": datetime.now(_KST).strftime("%Y-%m-%d"),
                "total_articles": len(classified),
                "by_category": by_category,
                "sentiment_distribution": sentiment,
                "high_impact_articles": high_impact[:20],
            },
            ttl=_CACHE_TTL,
        )
        logger.info("[Step 3] 캐시 저장: 신규=%d, 누적=%d, high=%d",
                     len(classified), len(merged), len(high_impact))
    except Exception as exc:
        logger.warning("[Step 3] 캐시 저장 실패: %s", exc)



async def _detect_regime(system: InjectedSystem) -> str:
    """현재 시장 레짐을 감지한다. (Step 4)"""
    try:
        detector = system.features.get("regime_detector")
        if detector is None:
            logger.warning("[Step 4] RegimeDetector 미등록 (건너뜀)")
            return "unknown"
        # VixFetcher로 실제 VIX를 조회한다. 실패 시 폴백 19.0을 사용한다
        vix = 19.0
        try:
            vf = system.features.get("vix_fetcher")
            if vf is not None:
                vix = await vf.get_vix()  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("[Step 4] VIX 조회 실패, 폴백 사용: %s", exc)
        regime = detector.detect(vix)  # type: ignore[union-attr]
        logger.info("[Step 4] 레짐 감지: %s (VIX=%.1f)", regime.regime_type, vix)
        return regime.regime_type
    except Exception as exc:
        logger.warning("[Step 4] 레짐 감지 실패 (건너뜀): %s", exc)
        return "unknown"


async def _collect_external_data(system: InjectedSystem) -> dict[str, Any]:
    """외부 데이터 소스 캐시에서 AI 프롬프트용 요약을 수집한다.

    preparation Step 0.6에서 캐시에 저장된 데이터를 읽어
    AI 프롬프트에 주입할 요약 형태로 가공한다.
    """
    result: dict[str, Any] = {}
    cache = system.components.cache

    # Polymarket 예측시장 확률이다
    try:
        poly = await cache.read_json("prediction:polymarket")
        if poly and isinstance(poly, list):
            # 상위 5개 이벤트만 포함한다
            result["polymarket"] = [
                {
                    "event": e.get("event_title", ""),
                    "markets": e.get("markets", [])[:3],
                    "volume": e.get("total_volume", 0),
                }
                for e in poly[:5]
            ]
    except Exception:
        pass

    # Trading Economics 고영향 경제 이벤트이다
    try:
        te = await cache.read_json("macro:te:calendar")
        if te and isinstance(te, list):
            high_medium = [e for e in te if e.get("importance") in ("high", "medium")]
            result["econ_calendar"] = [
                {
                    "event": e.get("event", ""),
                    "date": e.get("date", ""),
                    "time_et": e.get("time_et", ""),
                    "importance": e.get("importance", ""),
                    "actual": e.get("actual", ""),
                    "forecast": e.get("forecast", ""),
                    "previous": e.get("previous", ""),
                }
                for e in high_medium[:10]
            ]
    except Exception:
        pass

    # ETF 자금 유출입이다
    try:
        from src.indicators.external.etf_flow_fetcher import _CACHE_KEY_PREFIX as _ETF_PREFIX
        etf_tickers = ["SOXL", "QLD", "SPY"]
        flows: list[dict[str, Any]] = []
        for tk in etf_tickers:
            d = await cache.read_json(f"{_ETF_PREFIX}:{tk}")
            if d and isinstance(d, dict):
                flows.append({
                    "ticker": tk,
                    "aum_raw": d.get("aum_raw", ""),
                    "flow_5d_raw": d.get("flow_5d_raw", ""),
                    "flow_1m_raw": d.get("flow_1m_raw", ""),
                })
        if flows:
            result["etf_flows"] = flows
    except Exception:
        pass

    # TipRanks 애널리스트 컨센서스이다
    try:
        tipranks = system.features.get("tipranks_fetcher")
        if tipranks is not None and hasattr(tipranks, "fetch_summary"):
            # 캐시된 데이터가 있으면 fetch_summary가 캐시에서 읽는다
            summary = await tipranks.fetch_summary()  # type: ignore[union-attr]
            if summary and "데이터 없음" not in summary:
                result["analyst_consensus"] = summary
    except Exception:
        pass

    # Dataroma 슈퍼인베스터 관련 보유이다
    try:
        dataroma = await cache.read_json("macro:superinvestor")
        if dataroma and isinstance(dataroma, dict):
            summary = dataroma.get("summary", {})
            relevant = summary.get("relevant_tickers_found", {})
            if relevant:
                result["superinvestor_holdings"] = relevant
    except Exception:
        pass

    return result


async def _run_comprehensive_analysis(system: InjectedSystem) -> None:
    """사전 종합 분석을 실행하고 결과를 캐시에 저장한다. (Step 5)

    ComprehensiveTeam으로 4에이전트 병렬 분석(Layer 1) 후
    Opus 3+1 팀이 최종 판단(Layer 2)을 내린다.
    결과는 trading_loop에서 DecisionMaker가 활용한다.
    """
    try:
        team = system.features.get("comprehensive_team")
        if team is None:
            logger.warning("[Step 5] ComprehensiveTeam 미등록 (건너뜀)")
            return

        # 캐시에서 분류된 뉴스 요약을 읽어 컨텍스트를 구성한다
        cache = system.components.cache
        news_summary_data = await cache.read_json(_SUMMARY_CACHE_KEY) or {}
        classified_items = await cache.read_json(_CLASSIFIED_CACHE_KEY) or []

        # AnalysisContext를 구성한다
        from src.analysis.models import AnalysisContext
        high_impact_list = news_summary_data.get("high_impact_articles", [])
        news_summary = (
            f"총 {news_summary_data.get('total_articles', 0)}건 중 "
            f"고영향 {len(high_impact_list)}건"
        )
        # 외부 데이터 소스에서 캐시된 데이터를 수집한다
        external_data = await _collect_external_data(system)
        market_data: dict[str, Any] = {"high_impact_items": classified_items[:5]}
        if external_data:
            market_data["external"] = external_data
        context = AnalysisContext(
            news_summary=news_summary,
            indicators={},
            regime="unknown",
            positions=[],
            market_data=market_data,
        )

        logger.info("[Step 5] Layer 1 종합 분석 시작 (4에이전트 병렬)")
        import asyncio as _asyncio
        layer1_reports = await _asyncio.wait_for(
            team.analyze(context),  # type: ignore[union-attr]
            timeout=300.0,  # 5분 타임아웃 — 4에이전트 병렬 실행
        )
        logger.info("[Step 5] Layer 1 완료: %d 에이전트", len(layer1_reports))

        # Layer 2: Opus 3+1 팀 최종 판단
        from src.analysis.team.opus_judgment import opus_team_judgment
        market_context: dict = {
            "regime": "unknown",
            "news_summary": news_summary,
            "positions": [],
        }
        report = await _asyncio.wait_for(
            opus_team_judgment(system.components.ai, layer1_reports, market_context),
            timeout=300.0,  # 5분 타임아웃 — Opus 3+1 팀
        )

        # 분석 결과를 캐시에 저장하여 trading_loop에서 활용할 수 있도록 한다
        report_data = report.model_dump(mode="json")
        await cache.write_json(
            "analysis:comprehensive_report",
            report_data,
            ttl=_CACHE_TTL,
        )
        logger.info(
            "[Step 5] Layer 2 완료 (confidence=%.2f, risk=%s, signals=%d건)",
            report.confidence, report.risk_level, len(report.signals),
        )
    except Exception as exc:
        logger.warning("[Step 5] 종합 분석 실패 (건너뜀): %s", exc)


async def _run_safety_check(system: InjectedSystem) -> bool:
    """안전 체크를 실행한다. (Step 6)"""
    try:
        ep = system.features.get("emergency_protocol")
        if ep is not None and ep.is_halted():  # type: ignore[union-attr]
            logger.warning("[Step 6] EmergencyProtocol 매매 중단 상태")
            return False
        cg = system.features.get("capital_guard")
        if cg is not None:
            if cg.is_daily_limit_reached():  # type: ignore[union-attr]
                logger.warning("[Step 6] 일일 손실 한도 도달")
                return False
            if cg.is_weekly_limit_reached():  # type: ignore[union-attr]
                logger.warning("[Step 6] 주간 손실 한도 도달")
                return False
        logger.info("[Step 6] 안전 체크 통과")
        return True
    except Exception as exc:
        logger.warning("[Step 6] 안전 체크 실패 (차단 처리 — fail-closed): %s", exc)
        return False


async def _restore_exit_state(system: InjectedSystem) -> None:
    """ExitStrategy의 캐시 영속 상태를 복원한다 (C-5 수정).

    프로세스 재시작 시 분할 청산/트레일링 스톱 상태를 복원하여
    중복 청산과 조기 트리거를 방지한다.
    """
    try:
        es = system.features.get("exit_strategy")
        if es is not None and hasattr(es, "load_state"):
            await es.load_state()  # type: ignore[union-attr]
            logger.info("[Step 0] ExitStrategy 상태 복원 완료")
    except Exception as exc:
        logger.warning("[Step 0] ExitStrategy 상태 복원 실패 (메모리 전용으로 계속): %s", exc)


async def _cleanup_orphan_cache_keys(system: InjectedSystem) -> None:
    """M-7: 보유 포지션에 없는 beast/pyramid 캐시 키를 정리한다.

    이전 세션에서 포지션을 매도했으나 캐시 키 삭제에 실패한 경우
    고아 키가 남을 수 있다. 세션 시작 시 동기화된 포지션을 기준으로
    잔존 키를 정리하여 다음 세션에서 잘못된 상태를 읽지 않도록 한다.
    """
    try:
        pm = system.features.get("position_monitor")
        if pm is None:
            return
        positions = await pm.sync_positions()  # type: ignore[union-attr]
        held_tickers = set(positions.keys()) if positions else set()
        cache = system.components.cache

        # 매매 대상 종목 목록에서 보유하지 않은 종목의 키를 삭제한다
        registry = system.components.registry
        if registry is not None:
            all_known = {m.ticker for m in registry.get_all()}
        else:
            all_known = set()
        # 보유하지 않은 종목의 beast/pyramid 키를 삭제한다
        orphan_tickers = all_known - held_tickers
        cleaned = 0
        for tk in orphan_tickers:
            for prefix in ("beast_positions:", "pyramid_level:"):
                try:
                    val = await cache.read(f"{prefix}{tk}")
                    if val is not None:
                        await cache.delete(f"{prefix}{tk}")
                        cleaned += 1
                        logger.info("[Step 0] 고아 캐시 키 삭제: %s%s", prefix, tk)
                except Exception as exc:
                    logger.debug("[Step 0] 고아 캐시 키 접근 실패 (%s%s, 무시): %s", prefix, tk, exc)
        if cleaned > 0:
            logger.info("[Step 0] 고아 캐시 키 정리 완료: %d건", cleaned)
    except Exception as exc:
        logger.warning("[Step 0] 고아 캐시 키 정리 실패 (무시): %s", exc)


async def _populate_fred_if_needed(system: InjectedSystem) -> None:
    """FRED 거시지표 캐시가 비어 있으면 채운다. (Step 0.5)

    서버 재시작 시 macro:* 캐시가 비어 있어 대시보드에
    시장환경 & 경제지표가 표시되지 않는 문제를 방지한다.
    이미 데이터가 있으면 API 호출을 건너뛴다.
    """
    try:
        from src.indicators.misc.fred_fetcher import (
            is_fred_cache_populated,
            populate_fred_cache,
        )
        cache = system.components.cache
        if await is_fred_cache_populated(cache):
            logger.info("[Step 0.5] FRED 캐시 이미 존재 -- 건너뜀")
            return
        http = system.components.http
        vault = system.components.vault
        count = await populate_fred_cache(http, vault, cache)
        logger.info("[Step 0.5] FRED 거시지표 캐시 초기화: %d건", count)
    except Exception as exc:
        logger.warning("[Step 0.5] FRED 캐시 초기화 실패 (건너뜀): %s", exc)


async def _populate_external_indicators(system: InjectedSystem) -> None:
    """외부 데이터 소스 캐시를 워밍업한다. (Step 0.6)

    Polymarket, Trading Economics, ETFdb, Macrotrends, TipRanks, Dataroma
    6개 소스를 병렬로 수집한다. 개별 실패 시 해당 소스만 건너뛴다.
    캐시가 이미 존재하면 API 호출을 건너뛴다.
    """
    import asyncio as _asyncio

    fetcher_keys = [
        ("polymarket_fetcher", "Polymarket"),
        ("tradingeconomics_fetcher", "TradingEconomics"),
        ("etf_flow_fetcher", "ETF Flow"),
        ("macrotrends_fetcher", "Macrotrends"),
        ("tipranks_fetcher", "TipRanks"),
        ("dataroma_fetcher", "Dataroma"),
    ]

    async def _safe_fetch(key: str, label: str) -> str | None:
        """개별 fetcher를 안전하게 실행한다."""
        fetcher = system.features.get(key)
        if fetcher is None:
            return None
        try:
            await _asyncio.wait_for(
                fetcher.fetch(),  # type: ignore[union-attr]
                timeout=60.0,
            )
            return label
        except Exception as exc:
            logger.warning("[Step 0.6] %s 수집 실패 (건너뜀): %s", label, exc)
            return None

    tasks = [_safe_fetch(key, label) for key, label in fetcher_keys]
    results = await _asyncio.gather(*tasks, return_exceptions=True)
    succeeded = [r for r in results if isinstance(r, str)]
    logger.info("[Step 0.6] 외부 데이터 워밍업 완료: %d/%d 소스", len(succeeded), len(fetcher_keys))


async def _execute_steps(
    system: InjectedSystem, infra: InfraHealthResult,
) -> PreparationResult:
    """Step 0~6을 순차 실행하고 결과를 조립한다."""
    errors: list[str] = []
    await _restore_exit_state(system)
    await _cleanup_orphan_cache_keys(system)
    await _populate_fred_if_needed(system)
    await _populate_external_indicators(system)
    await _refresh_kis_token(system)
    _crawl_count, articles = await _run_news_crawl(system)
    classified = await _classify_news(system, articles)
    regime = await _detect_regime(system)
    await _run_comprehensive_analysis(system)
    safety_passed = await _run_safety_check(system)
    if not safety_passed:
        errors.append("안전 체크 미통과")
    logger.info("=== 매매 준비 완료 (regime=%s, classified=%d, safety=%s) ===",
                regime, classified, safety_passed)
    return PreparationResult(
        infra_health=infra, ready=safety_passed, regime=regime,
        classified_count=classified, safety_passed=safety_passed, errors=errors)


async def run_preparation(system: InjectedSystem) -> PreparationResult:
    """매매 준비 단계를 순차 실행한다. 인프라 검사 실패 시 fail-fast 반환한다."""
    logger.info("=== 매매 준비 단계 시작 ===")
    infra = await check_infrastructure(system)
    if not infra.all_healthy:
        logger.error("인프라 검사 실패 -- 준비 단계 중단")
        try:
            await get_event_bus().publish(EventType.INFRA_HEALTH_CHANGED, infra)
        except Exception as exc:
            logger.warning("인프라 이벤트 발행 실패: %s", exc)
        return PreparationResult(infra_health=infra, ready=False, errors=infra.errors)
    return await _execute_steps(system, infra)
