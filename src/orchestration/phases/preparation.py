"""F9.3 PreparationPhase -- 매매 시작 전 사전 준비를 실행한다."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from src.common.event_bus import EventType, get_event_bus
from src.common.logger import get_logger
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)

_HIGH_IMPACT_THRESHOLD: float = 0.7
_CLASSIFIED_CACHE_KEY: str = "news:classified_latest"
_SUMMARY_CACHE_KEY: str = "news:latest_summary"
_CACHE_TTL: int = 7200


class InfraHealthResult(BaseModel):
    """인프라 건강 검사 결과이다."""
    db_ok: bool
    redis_ok: bool
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
        logger.error("DB 건강 검사 실패: %s", exc)
        db_ok, _ = False, errors.append("DB 연결 실패")
    try:
        redis_ok = bool(await system.components.cache._client.ping())
    except Exception as exc:
        logger.error("Redis 건강 검사 실패: %s", exc)
        redis_ok = False
    if not redis_ok:
        errors.append("Redis 연결 실패")
    try:
        await system.components.broker.virtual_auth.get_token()
        broker_ok = True
    except Exception as exc:
        logger.error("Broker 건강 검사 실패: %s", exc)
        broker_ok, _ = False, errors.append("Broker 토큰 검증 실패")
    all_healthy = db_ok and redis_ok and broker_ok
    result = InfraHealthResult(
        db_ok=db_ok, redis_ok=redis_ok, broker_ok=broker_ok,
        all_healthy=all_healthy, errors=errors)
    level = logger.info if all_healthy else logger.warning
    level("인프라 건강 검사 %s: %s", "통과" if all_healthy else "실패", errors or "정상")
    return result


# -- Step 1~6 --

async def _refresh_kis_token(system: InjectedSystem) -> None:
    """KIS 토큰을 갱신한다. (Step 1)"""
    try:
        await system.components.broker.virtual_auth.get_token()
        await system.components.broker.real_auth.get_token()
        logger.info("[Step 1] KIS 토큰 갱신 완료")
    except Exception as exc:
        logger.warning("[Step 1] KIS 토큰 갱신 실패: %s", exc)


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
    """뉴스를 분류하고 고영향 뉴스를 Redis + 텔레그램으로 전송한다. (Step 3)"""
    if not articles:
        logger.info("[Step 3] 분류할 기사 없음 (건너뜀)")
        return 0
    try:
        classifier = system.features.get("news_classifier")
        if classifier is None:
            logger.warning("[Step 3] NewsClassifier 미등록 (건너뜀)")
            return 0
        classified = await classifier.classify(articles)  # type: ignore[union-attr]
        classified_dicts = [item.model_dump() for item in classified]
        logger.info("[Step 3] 뉴스 분류 완료: %d건", len(classified_dicts))
        high_impact = [a for a in classified_dicts
                       if a.get("impact_score", 0.0) >= _HIGH_IMPACT_THRESHOLD]
        await _cache_classified(system, classified_dicts, high_impact)
        if high_impact:
            await _send_high_impact(system, high_impact)
        return len(classified_dicts)
    except Exception as exc:
        logger.warning("[Step 3] 뉴스 분류 실패 (건너뜀): %s", exc)
        return 0


async def _cache_classified(
    system: InjectedSystem, classified: list[dict[str, Any]],
    high_impact: list[dict[str, Any]],
) -> None:
    """분류된 뉴스와 고영향 요약을 Redis에 캐시한다.

    빈 결과는 기존 캐시를 덮어쓰지 않는다 (분류 실패 시 데이터 유실 방지).
    """
    if not classified:
        logger.debug("[Step 3] 분류된 뉴스 0건 — 기존 캐시 유지")
        return
    try:
        cache = system.components.cache
        await cache.write_json(_CLASSIFIED_CACHE_KEY, classified, ttl=_CACHE_TTL)
        await cache.write_json(
            _SUMMARY_CACHE_KEY,
            {"total": len(classified), "high_impact": len(high_impact),
             "items": high_impact[:20]},
            ttl=_CACHE_TTL)
        logger.info("[Step 3] Redis 캐시 저장: classified=%d, high=%d",
                     len(classified), len(high_impact))
    except Exception as exc:
        logger.warning("[Step 3] Redis 캐시 저장 실패: %s", exc)


async def _send_high_impact(
    system: InjectedSystem, high_impact: list[dict[str, Any]],
) -> None:
    """고영향 뉴스 요약을 텔레그램으로 전송한다."""
    try:
        lines = [f"<b>[준비 단계] 고영향 뉴스 {len(high_impact)}건</b>", ""]
        for i, a in enumerate(high_impact[:10], start=1):
            title, score = a.get("title", "제목 없음"), a.get("impact_score", 0.0)
            cat, direction = a.get("category", "미분류"), a.get("direction", "neutral")
            lines.append(f"{i}. [{cat}] {title} (영향도: {score:.1f}, {direction})")
        if len(high_impact) > 10:
            lines.append(f"\n... 외 {len(high_impact) - 10}건")
        await system.components.telegram.send_text("\n".join(lines))
        logger.info("[Step 3] 텔레그램 전송 완료 (%d건)", len(high_impact))
    except Exception as exc:
        logger.warning("[Step 3] 텔레그램 전송 실패: %s", exc)


async def _detect_regime(system: InjectedSystem) -> str:
    """현재 시장 레짐을 감지한다. (Step 4)"""
    try:
        detector = system.features.get("regime_detector")
        if detector is None:
            logger.warning("[Step 4] RegimeDetector 미등록 (건너뜀)")
            return "unknown"
        # VixFetcher로 실제 VIX를 조회한다. 실패 시 폴백 20.0을 사용한다
        vix = 20.0
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


async def _run_comprehensive_analysis(system: InjectedSystem) -> None:
    """사전 종합 분석을 실행하고 결과를 Redis에 저장한다. (Step 5)

    ComprehensiveTeam으로 5개 AI 에이전트를 순차 실행하여 시장 개장 전
    종합 분석 보고서를 생성한다. 결과는 trading_loop에서 DecisionMaker가 활용한다.
    """
    try:
        team = system.features.get("comprehensive_team")
        if team is None:
            logger.warning("[Step 5] ComprehensiveTeam 미등록 (건너뜀)")
            return

        # Redis에서 분류된 뉴스 요약을 읽어 컨텍스트를 구성한다
        cache = system.components.cache
        news_summary_data = await cache.read_json(_SUMMARY_CACHE_KEY) or {}
        classified_items = await cache.read_json(_CLASSIFIED_CACHE_KEY) or []

        # AnalysisContext를 구성한다
        from src.analysis.models import AnalysisContext
        news_summary = (
            f"총 {news_summary_data.get('total', 0)}건 중 "
            f"고영향 {news_summary_data.get('high_impact', 0)}건"
        )
        context = AnalysisContext(
            news_summary=news_summary,
            indicators={},
            regime="unknown",
            positions=[],
            market_data={"high_impact_items": classified_items[:5]},
        )

        logger.info("[Step 5] 종합 분석 시작 (5개 AI 에이전트 순차 실행)")
        report = await team.analyze(context)  # type: ignore[union-attr]

        # 분석 결과를 Redis에 캐시하여 trading_loop에서 활용할 수 있도록 한다
        report_data = report.model_dump(mode="json")
        await cache.write_json(
            "analysis:comprehensive_report",
            report_data,
            ttl=_CACHE_TTL,
        )
        logger.info(
            "[Step 5] 종합 분석 완료 (confidence=%.2f, risk=%s, signals=%d건)",
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
        logger.warning("[Step 6] 안전 체크 실패 (통과 처리): %s", exc)
        return True


async def _execute_steps(
    system: InjectedSystem, infra: InfraHealthResult,
) -> PreparationResult:
    """Step 1~6을 순차 실행하고 결과를 조립한다."""
    errors: list[str] = []
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
