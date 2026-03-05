"""F9.5 ContinuousAnalysisLoop -- 30분 주기 연속 분석 루프를 관리한다.

매매 윈도우 내에서 주기적으로 시장 이슈를 분석하고
결과를 Redis에 캐시하여 다른 모듈이 참조할 수 있게 한다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from pydantic import BaseModel

from src.common.event_bus import EventType, get_event_bus
from src.common.logger import get_logger
from src.common.market_clock import TimeInfo
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)
_CACHE_KEY_PREFIX: str = "continuous_analysis"
_RESULT_TTL_SECONDS: int = 7200
_VIX_FALLBACK: float = 20.0
_ANALYSIS_SESSIONS: frozenset[str] = frozenset({
    "pre_market", "power_open", "mid_day",
})

class AnalysisLoopResult(BaseModel):
    """연속 분석 루프 결과이다."""
    iterations: int = 0
    issues_found: int = 0
    errors: list[str] = []

def is_analysis_window(time_info: TimeInfo) -> bool:
    """연속 분석 가능 시간대인지 판별한다."""
    return time_info.session_type in _ANALYSIS_SESSIONS

async def run_continuous_analysis(
    system: InjectedSystem,
    shutdown_event: asyncio.Event,
    interval_minutes: int = 30,
) -> AnalysisLoopResult:
    """30분 주기 연속 분석을 실행한다."""
    result = AnalysisLoopResult()
    logger.info("연속 분석 루프 시작 (주기=%d분)", interval_minutes)

    while not shutdown_event.is_set():
        time_info = system.components.clock.get_time_info()
        if not is_analysis_window(time_info):
            logger.info("분석 윈도우 외 세션(%s) -- 종료", time_info.session_type)
            break

        await _execute_iteration(system, result)

        if await _wait_or_shutdown(shutdown_event, interval_minutes):
            break

    _log_loop_summary(result)
    return result

async def _wait_or_shutdown(
    shutdown_event: asyncio.Event,
    interval_minutes: int,
) -> bool:
    """다음 주기까지 대기한다. shutdown 시 True를 반환한다."""
    try:
        await asyncio.wait_for(
            shutdown_event.wait(),
            timeout=interval_minutes * 60,
        )
        logger.info("shutdown 이벤트 수신 -- 루프 종료")
        return True
    except asyncio.TimeoutError:
        return False

async def _execute_iteration(
    system: InjectedSystem,
    result: AnalysisLoopResult,
) -> None:
    """단일 분석 반복: 뉴스 수집 -> 종합 분석을 실행하고 결과를 누적한다."""
    # 뉴스 파이프라인: 크롤링 -> 분류 -> 고영향 필터링 -> 텔레그램
    await _run_news_pipeline(system)
    # 섹터 로테이션 신호를 갱신한다 (trading_loop에서 cached_signal로 참조)
    await _refresh_sector_rotation(system)
    issues = await _run_single_analysis(system, result)
    result.iterations += 1
    result.issues_found += issues
    logger.info(
        "분석 #%d 완료 (이슈 %d건, 누적 %d건)",
        result.iterations, issues, result.issues_found,
    )

async def _refresh_sector_rotation(system: InjectedSystem) -> None:
    """섹터 로테이션 신호를 갱신한다.

    SectorRotation.evaluate()를 호출하여 cached_signal을 업데이트한다.
    trading_loop에서 cached_signal 속성으로 읽어 회피 섹터를 필터링한다.
    """
    try:
        sr = system.features.get("sector_rotation")
        if sr is None:
            return
        # 브로커 API로 7개 섹터 ETF 시세를 조회한다
        broker = system.components.broker
        sector_data: dict = {}
        for etf in ("XLK", "XLV", "XLF", "XLE", "XLY", "XLI", "XLU", "SPY"):
            try:
                price = await broker.virtual_client.get_current_price(etf)
                sector_data[etf] = {
                    "change_pct": getattr(price, "change_pct", 0.0),
                    "volume": getattr(price, "volume", 0),
                    "avg_volume": getattr(price, "avg_volume", 1),
                }
            except Exception:
                sector_data[etf] = {"change_pct": 0.0, "volume": 0, "avg_volume": 1}
        signal = await sr.evaluate(sector_data, broker)  # type: ignore[union-attr]
        logger.info(
            "섹터 로테이션 갱신: top3=%s, avoid=%s",
            signal.top3_prefer, signal.bottom2_avoid,
        )
    except Exception as exc:
        logger.warning("섹터 로테이션 갱신 실패 (무시): %s", exc)


async def _run_news_pipeline(system: InjectedSystem) -> None:
    """뉴스 파이프라인을 실행한다. 실패 시 건너뛴다."""
    try:
        from src.orchestration.phases.news_pipeline import run_news_pipeline
        result = await run_news_pipeline(system)
        logger.info(
            "뉴스 파이프라인: crawled=%d, classified=%d, high=%d, situations=%d",
            result.crawled_count, result.classified_count,
            result.high_impact_count, result.situation_count,
        )
    except Exception as exc:
        logger.warning("뉴스 파이프라인 실패 (건너뜀): %s", exc)

def _log_loop_summary(result: AnalysisLoopResult) -> None:
    """루프 종료 시 요약 로그를 출력한다."""
    logger.info(
        "연속 분석 루프 종료 (총 %d회, 이슈 %d건, 에러 %d건)",
        result.iterations, result.issues_found, len(result.errors),
    )

async def _run_single_analysis(
    system: InjectedSystem,
    result: AnalysisLoopResult,
) -> int:
    """ComprehensiveTeam으로 시장 이슈를 분석하고 Redis에 저장한다.

    Feature 미등록 또는 분석 실패 시 스텁 결과로 폴백한다.
    """
    try:
        team = system.features.get("comprehensive_team")
        if team is None:
            logger.warning("comprehensive_team 미등록 -- 스텁 폴백")
            data = _build_stub_result(system)
        else:
            context = await _build_analysis_context(system)
            report = await team.analyze(context)  # type: ignore[union-attr]
            data = _report_to_dict(report, system)
        await _cache_analysis_result(system, data)
        await get_event_bus().publish(EventType.TRADING_DECISION, result)
        return data.get("issues_count", 0)
    except Exception as exc:
        msg = f"분석 실행 실패: {exc}"
        logger.error(msg)
        result.errors.append(msg)
        return 0

async def _build_analysis_context(system: InjectedSystem) -> object:
    """실제 Feature 모듈에서 데이터를 수집하여 AnalysisContext를 생성한다."""
    from src.analysis.models import AnalysisContext

    # 실제 VIX 조회 후 레짐을 판별한다. VixFetcher 미등록 또는 실패 시 폴백을 사용한다
    vix = _VIX_FALLBACK
    try:
        vf = system.features.get("vix_fetcher")
        if vf is not None:
            vix = await vf.get_vix()  # type: ignore[union-attr]
    except Exception:
        pass
    regime_str = "sideways"
    detector = system.features.get("regime_detector")
    if detector is not None:
        try:
            regime = detector.detect(vix_value=vix)  # type: ignore[union-attr]
            regime_str = regime.regime_type
        except Exception as exc:
            logger.warning("레짐 판별 실패 (기본값 사용): %s", exc)

    # 포지션 조회
    positions_list: list[dict] = []
    monitor = system.features.get("position_monitor")
    if monitor is not None:
        try:
            pos_map = monitor.get_all_positions()  # type: ignore[union-attr]
            positions_list = [p.model_dump() for p in pos_map.values()]
        except Exception as exc:
            logger.warning("포지션 조회 실패: %s", exc)

    # Redis 캐시에서 뉴스 요약 / 지표 읽기
    cache = system.components.cache
    news_summary = "분석 데이터 없음"
    indicators: dict = {}
    try:
        raw_news = await cache.read("news:latest_summary")
        if raw_news:
            news_summary = raw_news
        raw_ind = await cache.read_json("indicators:latest")
        if raw_ind:
            indicators = raw_ind
    except Exception as exc:
        logger.warning("Redis 캐시 읽기 실패: %s", exc)

    # 매크로 데이터를 market_data에 포함한다 (순유동성, 콘탱고)
    market_data: dict = {}

    # NetLiquidityTracker: 캐시된 순유동성 바이어스를 분석 컨텍스트에 포함한다
    try:
        nlt = system.features.get("net_liquidity_tracker")
        if nlt is not None:
            lb = await nlt.get_cached()  # type: ignore[union-attr]
            market_data["net_liquidity"] = {
                "bias": lb.bias,
                "net_liquidity_bn": lb.net_liquidity_bn,
                "multiplier": lb.multiplier,
            }
    except Exception as exc:
        logger.warning("순유동성 바이어스 조회 실패 (무시): %s", exc)

    # ContangoDetector: VIX 기간구조 상태를 분석 컨텍스트에 포함한다
    try:
        cd = system.features.get("contango_detector")
        if cd is not None:
            contango = await cd.detect()  # type: ignore[union-attr]
            market_data["contango"] = {
                "signal": contango.signal,
                "ratio": contango.contango_ratio,
                "drag_estimate": contango.drag_estimate,
            }
    except Exception as exc:
        logger.warning("콘탱고 감지 실패 (무시): %s", exc)

    return AnalysisContext(
        news_summary=news_summary,
        indicators=indicators,
        regime=regime_str,
        positions=positions_list,
        market_data=market_data,
    )

def _report_to_dict(report: object, system: InjectedSystem) -> dict:
    """ComprehensiveReport를 캐시용 dict로 변환한다."""
    from src.analysis.models import ComprehensiveReport

    r: ComprehensiveReport = report  # type: ignore[assignment]
    time_info = system.components.clock.get_time_info()
    return {
        "timestamp": r.timestamp.isoformat(),
        "session": time_info.session_type,
        "issues_count": len(r.signals),
        "issues": r.signals,
        "confidence": r.confidence,
        "recommendations": r.recommendations,
        "regime_assessment": r.regime_assessment,
        "risk_level": r.risk_level,
    }

def _build_stub_result(system: InjectedSystem) -> dict:
    """Feature 미등록 시 스텁 분석 결과를 생성한다."""
    time_info = system.components.clock.get_time_info()
    return {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "session": time_info.session_type,
        "issues_count": 0,
        "issues": [],
        "summary": "ComprehensiveTeam 미등록 -- 스텁 분석",
    }

async def _cache_analysis_result(
    system: InjectedSystem,
    data: dict,
) -> None:
    """분석 결과를 Redis에 캐시한다."""
    key = f"{_CACHE_KEY_PREFIX}:latest"
    await system.components.cache.write_json(key, data, ttl=_RESULT_TTL_SECONDS)
    logger.debug("분석 결과 Redis 캐시 완료 (key=%s)", key)