"""F9.6 NewsPipeline -- 뉴스 수집·분류·텔레그램 전송 파이프라인이다.

크롤링(F1) -> 분류(F2) -> 텔레그램 전송(C0.7).
CrawlEngine이 검증/중복 제거를 내부 처리하고, EventBus ARTICLE_COLLECTED로 기사를 받는다.
전체 분류된 뉴스(핵심+일반)를 텔레그램에 전달하며, 포맷터가 3섹션으로 구분한다.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from src.common.event_bus import EventType, get_event_bus
from src.common.logger import get_logger
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)


def _serialize_datetime(dt: object) -> str:
    """datetime 객체를 ISO 문자열로 변환한다. 이미 문자열이면 그대로 반환한다."""
    if dt is None:
        return ""
    if isinstance(dt, str):
        return dt
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)

# 매매 세션이 KST 기준이므로 뉴스 날짜 그룹핑도 KST를 사용한다
_KST = ZoneInfo("Asia/Seoul")

# 고영향 뉴스 임팩트 임계값 (F2 분류 결과의 impact_score 기준)
_HIGH_IMPACT_THRESHOLD: float = 0.7
# 캐시 키 — preparation.py와 동일한 키를 사용하여 endpoints가 읽을 수 있도록 한다
_CLASSIFIED_CACHE_KEY: str = "news:classified_latest"
_SUMMARY_CACHE_KEY: str = "news:latest_summary"
_DATES_CACHE_KEY: str = "news:dates"
_DAILY_CACHE_TTL: int = 86400  # 뉴스 캐시 통합 TTL 24시간 (dedup 48h와 정합)
# 헤드라인 캐시 TTL — 파이프라인 60분 주기보다 5분 여유
_HEADLINES_TTL: int = 3900

# 동시 실행 방지 락이다.
# 1. 파이프라인 중복 실행 방지: 두 번째 실행(0건)이 캐시를 덮어쓰는 것을 차단한다
# 2. preparation.py에서 import하여 .locked() 확인 — 경합 상태 방지 (M-1)
# 주의: 같은 이벤트 루프 내에서만 유효하다 (멀티프로세스 환경에서는 분산 lock 필요)
_pipeline_lock = asyncio.Lock()


class PipelineResult(BaseModel):
    """뉴스 파이프라인 결과이다."""
    crawled_count: int = 0
    classified_count: int = 0
    merged_count: int = 0
    high_impact_count: int = 0
    situation_count: int = 0
    translated_count: int = 0
    persisted_count: int = 0
    sent_to_telegram: bool = False
    errors: list[str] = []


async def _crawl_news(system: InjectedSystem) -> list[Any]:
    """CrawlEngine + EventBus 임시 수집 패턴으로 VerifiedArticle 목록을 반환한다."""
    engine = system.features.get("crawl_engine")
    scheduler = system.features.get("crawl_scheduler")
    if engine is None or scheduler is None:
        logger.warning("[Step 1] crawl_engine 또는 crawl_scheduler 미등록 — 건너뜀")
        return []

    # EventBus 임시 수집기: ARTICLE_COLLECTED 이벤트를 리스트에 적재한다
    collected: list[Any] = []

    def _collector(article: Any) -> None:
        """이벤트 핸들러 — 수집된 기사를 리스트에 추가한다."""
        try:
            collected.append(article)
        except Exception as exc:
            logger.warning("EventBus 기사 수집 실패 (무시): %s", exc)

    bus = get_event_bus()
    bus.subscribe(EventType.ARTICLE_COLLECTED, _collector)
    try:
        schedule = scheduler.build_schedule(fast_mode=True)
        result = await engine.run(schedule)
        logger.info(
            "[Step 1] 크롤링 완료: total=%d, new=%d, failed=%s, %.1f초",
            result.total, result.new_count,
            result.failed_sources, result.duration_seconds,
        )
    except Exception as exc:
        logger.error("[Step 1] 크롤링 실행 실패: %s", exc)
        raise
    finally:
        bus.unsubscribe(EventType.ARTICLE_COLLECTED, _collector)

    logger.info("[Step 1] EventBus로 수집된 기사: %d건", len(collected))
    return collected


async def _classify_articles(
    system: InjectedSystem,
    articles: list[Any],
) -> list[Any]:
    """NewsClassifier로 분류 후 ClassifiedNews 리스트를 반환한다."""
    if not articles:
        return []

    classifier = system.features.get("news_classifier")
    if classifier is None:
        logger.warning("[Step 2] news_classifier 미등록 — 분류 건너뜀")
        return []

    from src.agents.status_writer import (
        record_agent_complete,
        record_agent_error,
        record_agent_start,
    )

    cache = system.components.cache
    t0 = time.monotonic()
    await record_agent_start(cache, "news_classifier", f"뉴스 분류 ({len(articles)}건)")
    try:
        classified = await classifier.classify(articles)
        await record_agent_complete(
            cache, "news_classifier",
            f"분류 완료 ({len(classified)}건)",
            time.monotonic() - t0,
        )
    except Exception as exc:
        await record_agent_error(cache, "news_classifier", str(exc))
        raise
    logger.info("[Step 2] 뉴스 분류 완료: %d건", len(classified))

    return classified


async def _track_themes(system: InjectedSystem, classified: list[Any]) -> None:
    """Step 2.5: 분류된 뉴스에서 반복 테마를 추출하고 캐시에 누적한다.

    NewsThemeTracker가 미등록이거나 기사가 없으면 조용히 건너뛴다.
    """
    if not classified:
        return

    tracker = system.features.get("news_theme_tracker")
    if tracker is None:
        logger.debug("[Step 2.5] news_theme_tracker 미등록 — 테마 추적 건너뜀")
        return

    try:
        themes = await tracker.track(classified)
        logger.info("[Step 2.5] 뉴스 테마 추적 완료: %d개 테마", len(themes))

        # 테마 결과를 캐시에 저장하여 대시보드/분석에서 활용할 수 있도록 한다
        if themes:
            theme_dicts = [t.model_dump() for t in themes]
            await system.components.cache.write_json(
                "news:themes_latest", theme_dicts, ttl=_DAILY_CACHE_TTL,
            )
    except Exception as exc:
        logger.warning("[Step 2.5] 테마 추적 실패: %s", exc)


async def _filter_key_news(
    system: InjectedSystem,
    classified: list[Any],
) -> list[Any]:
    """Step 2.7: KeyNewsFilter로 고영향 핵심 뉴스를 필터링한다.

    KeyNewsFilter가 미등록이면 빈 목록을 반환한다.
    필터링 결과는 캐시에 저장하여 준비 단계 분석에서 활용할 수 있도록 한다.
    """
    if not classified:
        return []

    key_filter = system.features.get("key_news_filter")
    if key_filter is None:
        logger.debug("[Step 2.7] key_news_filter 미등록 — 건너뜀")
        return []

    from src.agents.status_writer import (
        record_agent_complete,
        record_agent_error,
        record_agent_start,
    )

    cache = system.components.cache
    t0 = time.monotonic()
    await record_agent_start(cache, "key_news_filter", f"핵심 뉴스 필터링 ({len(classified)}건)")
    try:
        # ClassifiedNews 객체 리스트를 그대로 전달한다
        key_news = key_filter.filter(classified)  # type: ignore[union-attr]
        logger.info("[Step 2.7] 핵심 뉴스 필터링 완료: %d건", len(key_news))

        # 핵심 뉴스를 캐시에 저장한다
        if key_news:
            key_dicts = [n.model_dump() for n in key_news]
            await system.components.cache.write_json(
                "news:key_latest", key_dicts, ttl=_DAILY_CACHE_TTL,
            )
        await record_agent_complete(
            cache, "key_news_filter",
            f"핵심 뉴스 {len(key_news)}건 필터링",
            time.monotonic() - t0,
        )
        return key_news
    except Exception as exc:
        logger.warning("[Step 2.7] 핵심 뉴스 필터링 실패: %s", exc)
        await record_agent_error(cache, "key_news_filter", str(exc))
        return []


async def _track_situations(
    system: InjectedSystem,
    key_news: list[Any],
) -> list[Any]:
    """Step 2.8: 핵심뉴스에서 진행 상황을 추적하고 보고서를 생성한다.

    situation_tracker가 미등록이면 빈 리스트를 반환한다 (graceful degradation).
    """
    if not key_news:
        return []

    tracker = system.features.get("situation_tracker")
    if tracker is None:
        logger.debug("[Step 2.8] situation_tracker 미등록 — 상황 추적 건너뜀")
        return []

    from src.agents.status_writer import (
        record_agent_complete,
        record_agent_error,
        record_agent_start,
    )

    cache = system.components.cache
    t0 = time.monotonic()
    await record_agent_start(cache, "situation_tracker", f"상황 추적 ({len(key_news)}건)")
    try:
        reports = await tracker.track(key_news)  # type: ignore[union-attr]
        logger.info("[Step 2.8] 진행 상황 보고서: %d건", len(reports))

        # 최신 보고서를 캐시에 저장한다
        if reports:
            report_dicts = [r.model_dump() for r in reports]
            await system.components.cache.write_json(
                "news:situation_reports_latest", report_dicts, ttl=_DAILY_CACHE_TTL,
            )
        await record_agent_complete(
            cache, "situation_tracker",
            f"상황 보고서 {len(reports)}건 생성",
            time.monotonic() - t0,
        )
        return reports
    except Exception as exc:
        logger.warning("[Step 2.8] 상황 추적 실패: %s", exc)
        await record_agent_error(cache, "situation_tracker", str(exc))
        return []


def _filter_high_impact(articles: list[dict]) -> list[dict]:
    """분류된 기사 중 고영향 뉴스만 필터링한다."""
    high_impact = [
        a for a in articles
        if a.get("impact_score", 0.0) >= _HIGH_IMPACT_THRESHOLD
    ]
    logger.info("[Step 3] 고영향 뉴스 필터링: %d/%d건", len(high_impact), len(articles))
    return high_impact


async def _send_to_telegram(
    system: InjectedSystem,
    articles: list[dict],
    situation_reports: list[Any] | None = None,
) -> bool:
    """전체 분류된 뉴스를 Claude Haiku로 3섹션(핵심/일반/상황) 정리 후 텔레그램으로 전송한다.

    Haiku가 뉴스를 핵심/일반으로 구분하고 직관적인 한국어 메시지를 생성한다.
    Haiku 호출 실패 시 동일 구조의 간단 포맷으로 폴백한다.
    상황 보고서는 포맷터 내부에서 통합 처리하므로 별도 전송하지 않는다.
    """
    news_sent = False
    if articles:
        from src.orchestration.phases.telegram_formatter import format_news_for_telegram

        ai = system.components.ai
        # 전체 뉴스 + 상황 보고서를 포맷터에 전달한다 — 포맷터가 핵심/일반/상황 3섹션으로 구분한다
        message = await format_news_for_telegram(ai, articles, situation_reports)
        if not message:
            message = _format_telegram_message(articles)
        try:
            result = await system.components.telegram.send_text(message)
            if result.success:
                logger.info(
                    "[Step 4] 텔레그램 전송 성공 (%d건 전체, Haiku 3섹션 포맷)",
                    len(articles),
                )
                news_sent = True
            else:
                logger.warning("[Step 4] 텔레그램 전송 실패: %s", result.error)
        except Exception as exc:
            logger.error("[Step 4] 텔레그램 전송 예외: %s", exc)
    else:
        logger.info("[Step 4] 전송할 뉴스 없음")

    return news_sent


def _format_telegram_message(articles: list[dict]) -> str:
    """고영향 뉴스 목록을 텔레그램 메시지로 포맷팅한다."""
    lines: list[str] = ["<b>[고영향 뉴스 알림]</b>", ""]
    for i, article in enumerate(articles[:10], start=1):
        title = article.get("title", "제목 없음")
        score = article.get("impact_score", 0.0)
        category = article.get("category", "미분류")
        direction = article.get("direction", "neutral")
        lines.append(f"{i}. [{category}] {title} (영향도: {score:.1f}, {direction})")
    if len(articles) > 10:
        lines.append(f"\n... 외 {len(articles) - 10}건")
    return "\n".join(lines)


def _impact_score_to_level(score: float) -> str:
    """impact_score(0.0~1.0)를 Flutter가 사용하는 문자열 레벨로 변환한다."""
    if score >= _HIGH_IMPACT_THRESHOLD:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _score_to_importance(score: float) -> str:
    """impact_score를 중요도 문자열로 변환한다."""
    if score >= 0.8:
        return "critical"
    if score >= _HIGH_IMPACT_THRESHOLD:
        return "key"
    return "normal"


def _to_flutter_article(article: dict) -> dict:
    """ClassifiedNews dict를 Flutter NewsArticle이 기대하는 형식으로 변환한다.

    필드 매핑: title→headline, impact_score→impact, tickers_affected→tickers.
    id는 URL의 SHA-256 해시로 생성한다.
    """
    url = article.get("url", "")
    article_id = hashlib.sha256(url.encode()).hexdigest()[:16] if url else ""
    score = article.get("impact_score", 0.0)
    direction = article.get("direction", "neutral")

    # direction에 따라 sentiment_score 부호를 결정한다
    # bearish → 음수, bullish → 양수, neutral → 0
    if direction == "bearish":
        sentiment = -score
    elif direction == "bullish":
        sentiment = score
    else:
        sentiment = 0.0

    # 번역된 제목이 content 앞에 "[한국어]" 접두어로 들어있으면 추출한다
    content = article.get("content", "")
    headline_kr = ""
    if content.startswith("[한국어]"):
        # "[한국어] 번역된제목\n\n원본내용" 형식에서 번역된 제목을 추출한다
        lines = content.split("\n", 1)
        headline_kr = lines[0].replace("[한국어]", "").strip()

    return {
        "id": article_id,
        "headline": article.get("title", ""),
        "headline_kr": headline_kr or None,
        "content": content,
        # reasoning은 이미 한국어이므로 summary_ko로 매핑한다
        "summary_ko": article.get("reasoning", "") or None,
        "url": url,
        "source": article.get("source", ""),
        "published_at": _serialize_datetime(article.get("published_at")),
        "tickers": article.get("tickers_affected", []),
        "sentiment_score": sentiment,
        "impact": _impact_score_to_level(score),
        "impact_score": score,
        "direction": direction,
        "category": article.get("category", "other"),
        "importance": _score_to_importance(score),
        "reasoning": article.get("reasoning", ""),
        # 단타 트레이딩 전용 필드이다
        "time_sensitivity": article.get("time_sensitivity", "analysis"),
        "actionability": article.get("actionability", "informational"),
        "leveraged_etf_impact": article.get("leveraged_etf_impact", ""),
    }


def _build_summary(today: str, articles: list[dict]) -> dict:
    """Flutter NewsSummary가 기대하는 형식의 요약 dict를 생성한다."""
    by_category: dict[str, int] = {}
    by_source: dict[str, int] = {}
    sentiment: dict[str, int] = {"bullish": 0, "bearish": 0, "neutral": 0}
    importance: dict[str, int] = {"critical": 0, "key": 0, "normal": 0}
    high_impact: list[dict] = []

    for a in articles:
        cat = a.get("category", "other")
        by_category[cat] = by_category.get(cat, 0) + 1
        src = a.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1
        direction = a.get("direction", "neutral")
        sentiment[direction] = sentiment.get(direction, 0) + 1
        imp = a.get("importance", "normal")
        importance[imp] = importance.get(imp, 0) + 1
        if a.get("impact") == "high":
            high_impact.append(a)

    return {
        "date": today,
        "total_articles": len(articles),
        "by_category": by_category,
        "by_source": by_source,
        "sentiment_distribution": sentiment,
        "high_impact_articles": high_impact[:20],
        "importance_distribution": importance,
    }


async def _cache_classified_results(
    system: InjectedSystem,
    classified: list[dict],
    high_impact: list[dict],
) -> None:
    """분류된 뉴스를 Flutter 대시보드용으로 **누적** 캐시한다.

    기존 캐시에 새 기사를 병합(ID 기준 중복 제거)하여 하루 동안 기사가 쌓인다.
    저장하는 키:
    - news:classified_latest — 원본 분류 결과 (trading_loop 참조용, 누적)
    - news:dates — 날짜 목록 (Flutter 날짜 사이드패널)
    - news:daily:{today} — 오늘 기사 목록 (Flutter 기사 리스트, 누적)
    - news:latest_summary — 요약 통계 (전체 누적 기사 기준)
    빈 결과는 기존 캐시를 덮어쓰지 않는다.
    """
    if not classified:
        logger.debug("[Cache] 분류된 뉴스 0건 — 기존 캐시 유지")
        return

    try:
        cache = system.components.cache
        today = datetime.now(_KST).strftime("%Y-%m-%d")

        # Flutter가 사용하는 형식으로 변환한다
        new_flutter = [_to_flutter_article(a) for a in classified]

        # 1) 원본 분류 결과 누적 (trading_loop 등 내부 참조용)
        existing_classified_raw = await cache.read_json(_CLASSIFIED_CACHE_KEY)
        existing_classified: list[dict] = (
            existing_classified_raw if isinstance(existing_classified_raw, list) else []
        )
        # URL 기준 중복 제거 후 병합 — 새 기사가 기존보다 우선한다
        classified_by_url: dict[str, dict] = {
            a.get("url", ""): a for a in existing_classified
        }
        for a in classified:
            classified_by_url[a.get("url", "")] = a
        merged_classified = list(classified_by_url.values())
        await cache.write_json(
            _CLASSIFIED_CACHE_KEY, merged_classified, ttl=_DAILY_CACHE_TTL,
        )

        # 2) 오늘 날짜의 기사 목록 누적 (Flutter daily news)
        daily_key = f"news:daily:{today}"
        existing_daily_raw = await cache.read_json(daily_key)
        existing_daily: list[dict] = (
            existing_daily_raw if isinstance(existing_daily_raw, list) else []
        )
        # article ID 기준 중복 제거 후 병합한다
        daily_by_id: dict[str, dict] = {
            a.get("id", ""): a for a in existing_daily
        }
        for fa in new_flutter:
            daily_by_id[fa.get("id", "")] = fa
        merged_daily = list(daily_by_id.values())
        await cache.write_json(daily_key, merged_daily, ttl=_DAILY_CACHE_TTL)

        # 3) 날짜 목록 갱신 — 누적된 전체 기사 수로 업데이트한다
        existing_dates_raw = await cache.read_json(_DATES_CACHE_KEY)
        existing_dates: list[dict] = (
            existing_dates_raw if isinstance(existing_dates_raw, list) else []
        )
        date_map: dict[str, dict] = {
            d["date"]: d for d in existing_dates if isinstance(d, dict)
        }
        date_map[today] = {"date": today, "article_count": len(merged_daily)}
        sorted_dates = sorted(
            date_map.values(), key=lambda x: x["date"], reverse=True,
        )
        await cache.write_json(_DATES_CACHE_KEY, sorted_dates[:90], ttl=_DAILY_CACHE_TTL)

        # 4) 요약 통계 — 누적된 전체 기사로 재계산한다
        summary = _build_summary(today, merged_daily)
        await cache.write_json(_SUMMARY_CACHE_KEY, summary, ttl=_DAILY_CACHE_TTL)
        await cache.write_json(
            f"news:summary:{today}", summary, ttl=_DAILY_CACHE_TTL,
        )

        # 5) 개별 기사 캐시 — GET /api/news/{article_id} 엔드포인트용
        # asyncio.gather로 병렬 처리하여 N+1 캐시 호출을 최적화한다
        article_tasks = [
            cache.write_json(f"news:article:{fa['id']}", fa, ttl=_DAILY_CACHE_TTL)
            for fa in new_flutter if fa.get("id")
        ]
        if article_tasks:
            await asyncio.gather(*article_tasks, return_exceptions=True)

        # 6) 티커별 뉴스 캐시 — GET /api/analysis/{ticker}/news 엔드포인트용
        # tickers_affected 필드를 기반으로 기사를 분류하여 news:{ticker}에 저장한다
        ticker_articles: dict[str, list[dict]] = {}
        for fa in new_flutter:
            tickers_list = fa.get("tickers", [])
            if not isinstance(tickers_list, list):
                continue
            for tk in tickers_list:
                if isinstance(tk, str) and tk:
                    ticker_articles.setdefault(tk, []).append(fa)
        ticker_tasks = []
        for tk, articles_for_tk in ticker_articles.items():
            # 기존 캐시를 읽어 누적한다 (ID 기준 중복 제거, 최대 50건)
            async def _update_ticker_news(
                _tk: str = tk, _new: list[dict] = articles_for_tk,
            ) -> None:
                existing_raw = await cache.read_json(f"news:{_tk}")
                existing: list[dict] = (
                    existing_raw if isinstance(existing_raw, list) else []
                )
                by_id: dict[str, dict] = {a.get("id", ""): a for a in existing}
                for a in _new:
                    by_id[a.get("id", "")] = a
                merged = list(by_id.values())[-50:]
                await cache.write_json(f"news:{_tk}", merged, ttl=_DAILY_CACHE_TTL)
            ticker_tasks.append(_update_ticker_news())
        if ticker_tasks:
            await asyncio.gather(*ticker_tasks, return_exceptions=True)

        logger.info(
            "[Cache] 캐시 누적 완료: 신규=%d, 전체=%d, 날짜=%d",
            len(new_flutter), len(merged_daily), len(sorted_dates),
        )
    except Exception as exc:
        logger.warning("[Cache] 캐시 저장 실패: %s", exc)


async def _safe_call(
    coro: object,
    fallback: list[Any],
    label: str,
    errors: list[str],
) -> list[Any]:
    """비동기 함수를 실행하되, 실패 시 fallback을 반환한다."""
    try:
        return await coro  # type: ignore[misc]
    except Exception as exc:
        logger.error("%s 실패: %s", label, exc)
        errors.append(f"{label} 실패: {exc}")
        return fallback


async def _merge_similar(articles: list[Any]) -> list[Any]:
    """Step 2.3: 유사 기사를 병합한다."""
    from src.crawlers.dedup.article_merger import ArticleMerger

    merger = ArticleMerger()
    return merger.merge(articles)


async def _translate_articles(system: InjectedSystem, articles: list[Any]) -> list[Any]:
    """Step 3: 뉴스를 한국어로 번역한다."""
    translator = system.features.get("news_translator")
    if translator is None:
        logger.debug("[Step 3] news_translator 미등록 — 번역 건너뜀")
        return articles
    return await translator.translate(articles)  # type: ignore[union-attr]


async def _persist_to_db(system: InjectedSystem, classified: list[dict]) -> int:
    """Step 3.5: 분류된 기사를 DB에 저장한다."""
    from src.orchestration.phases.article_persister import persist_articles

    saved, failed = await persist_articles(system.components.db, classified)
    if failed > 0:
        logger.warning("[Step 3.5] DB 저장 부분 실패: %d건 실패", failed)
    return saved


async def _collect_and_classify(
    system: InjectedSystem,
    errors: list[str],
) -> tuple[int, list[dict], list[Any], int, int]:
    """크롤링 -> 분류 -> 병합 -> 테마 -> 핵심 필터 -> 상황 추적 -> 번역을 실행한다.

    분류 결과는 ClassifiedNews 객체 상태에서 병합/테마/필터링을 수행한 후
    dict로 변환한다. 각 단계 실패는 파이프라인 전체를 중단시키지 않는다.

    Returns:
        (크롤링 수, 분류된 뉴스 dict 리스트, 상황 보고서 리스트, 병합 후 수, 번역 수)
    """
    raw_articles = await _safe_call(_crawl_news(system), [], "크롤링", errors)
    crawled_count = len(raw_articles)

    # 센티넬이 읽을 수 있도록 최신 헤드라인 제목을 캐시에 저장한다
    if raw_articles:
        try:
            titles = [
                getattr(a, "title", "") or ""
                for a in raw_articles if getattr(a, "title", "")
            ]
            if titles:
                await system.components.cache.write_json(
                    "news:latest_titles", titles[:50], ttl=_HEADLINES_TTL,
                )
        except Exception as exc:
            logger.warning("헤드라인 캐시 저장 실패 (무시): %s", exc)

    # ClassifiedNews 객체 리스트 — 테마 추적에 그대로 전달한다
    classified_objects: list[Any] = await _safe_call(
        _classify_articles(system, raw_articles), [], "분류", errors,
    )

    # Step 2.3: 유사 기사 병합 — 같은 사건 복수 보도를 하나로 합친다
    pre_merge = len(classified_objects)
    try:
        classified_objects = await _merge_similar(classified_objects)
    except Exception as exc:
        logger.warning("[Step 2.3] 유사 기사 병합 실패 (원본 유지): %s", exc)
        errors.append(f"유사 기사 병합 실패: {exc}")
    merged_count = len(classified_objects)

    # Step 2.5: 테마 추적 — ClassifiedNews 타입 필드(category, direction)를 직접 읽는다
    await _track_themes(system, classified_objects)

    # Step 2.7: 핵심 뉴스 필터링 — 임팩트 0.7 이상 뉴스를 별도 캐시에 저장한다
    key_news = await _filter_key_news(system, classified_objects)

    # Step 2.8: 진행 상황 추적 — 핵심뉴스에서 장기 이슈를 감지한다
    situation_reports = await _track_situations(system, key_news)

    # Step 3: 뉴스 번역 — MLX 로컬 모델로 제목을 한국어 번역한다
    translated_count = 0
    try:
        before = classified_objects
        classified_objects = await _translate_articles(system, classified_objects)
        translated_count = sum(
            1 for a, b in zip(before, classified_objects)
            if a.content != b.content
        )
    except Exception as exc:
        logger.warning("[Step 3] 번역 실패 (원본 유지): %s", exc)
        errors.append(f"번역 실패: {exc}")

    # 이후 단계(필터/텔레그램)는 dict 형식을 기대한다
    classified_dicts = [item.model_dump() for item in classified_objects]
    return crawled_count, classified_dicts, situation_reports, merged_count, translated_count


async def run_news_pipeline(system: InjectedSystem) -> PipelineResult:
    """뉴스 파이프라인을 실행한다.

    각 단계의 실패는 개별 격리하여 파이프라인이 중단되지 않는다.
    _pipeline_lock으로 동시 실행을 방지한다:
    - 이미 실행 중이면 즉시 반환한다 (에러 목록에 "파이프라인 이미 실행 중" 기록)
    - preparation.py도 이 락을 확인하여 분류 단계 경합을 방지한다
    """
    if _pipeline_lock.locked():
        logger.warning("=== 뉴스 파이프라인 이미 실행 중 — 건너뜀 ===")
        return PipelineResult(errors=["파이프라인 이미 실행 중"])

    async with _pipeline_lock:
        logger.info("=== 뉴스 파이프라인 시작 ===")
        errors: list[str] = []
        crawled_count, classified, situation_reports, merged_count, translated_count = (
            await _collect_and_classify(system, errors)
        )
        high_impact = _filter_high_impact(classified)

        # Step 3.5: 분류된 기사를 DB에 영구 저장한다
        persisted_count = 0
        try:
            persisted_count = await _persist_to_db(system, classified)
        except Exception as exc:
            logger.warning("[Step 3.5] DB 저장 실패 (파이프라인 계속): %s", exc)
            errors.append(f"DB 저장 실패: {exc}")

        # 분류 결과를 캐시에 저장하여 news endpoints에서 조회할 수 있도록 한다
        await _cache_classified_results(system, classified, high_impact)
        # 전체 분류된 뉴스(핵심+일반)를 텔레그램에 전달한다 — 포맷터가 3섹션으로 구분한다
        sent = await _send_to_telegram(system, classified, situation_reports)
        logger.info(
            "=== 뉴스 파이프라인 완료 (crawled=%d, merged=%d, classified=%d, "
            "translated=%d, persisted=%d, high_impact=%d, situations=%d, sent=%s) ===",
            crawled_count, merged_count, len(classified),
            translated_count, persisted_count, len(high_impact),
            len(situation_reports), sent,
        )
        return PipelineResult(
            crawled_count=crawled_count,
            classified_count=len(classified),
            merged_count=merged_count,
            high_impact_count=len(high_impact),
            situation_count=len(situation_reports),
            translated_count=translated_count,
            persisted_count=persisted_count,
            sent_to_telegram=sent,
            errors=errors,
        )
