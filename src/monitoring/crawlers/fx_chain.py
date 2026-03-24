"""환율 폴백 체인 -- FxScheduler가 호출하는 10단계 환율 조회 함수이다.

1~5차 개별 소스 함수와 전체 체인 오케스트레이터를 포함한다.
각 함수는 독립 async 함수로, 시스템 의존성을 파라미터로 주입받는다.
성공 시 float 환율, 실패 시 None을 반환한다.
"""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)


async def try_kis_rate(system: InjectedSystem) -> float | None:
    """1차: KIS API(FxManager)로 USD/KRW 환율을 조회한다."""
    try:
        fx_manager = system.features.get("fx_manager")
        if fx_manager is None:
            _logger.debug("FxManager 미등록, KIS 환율 조회 스킵")
            return None

        fx_rate = await fx_manager.get_rate()
        if fx_rate is None:
            _logger.debug("KIS API 환율 조회 결과 None")
            return None

        rate_value = float(fx_rate.usd_krw)
        if 900 < rate_value < 2000:
            _logger.info("KIS API 환율 조회 성공: %.2f", rate_value)
            return rate_value

        _logger.warning("KIS API 환율 범위 이탈: %.2f", rate_value)
        return None
    except Exception:
        _logger.warning("KIS API 환율 조회 실패", exc_info=True)
        return None


async def try_google_finance() -> float | None:
    """2차: 구글 Finance 페이지에서 USD/KRW 환율을 크롤링한다."""
    try:
        from src.monitoring.crawlers.google_fx import (
            _try_google_finance as gf,
        )

        rate = await gf()
        if rate is not None:
            _logger.info("구글 Finance 환율: %.2f", rate)
        return rate
    except Exception:
        _logger.warning("구글 Finance 크롤링 실패", exc_info=True)
        return None


async def try_google_search() -> float | None:
    """3차: 구글 Search 결과에서 USD/KRW 환율을 크롤링한다."""
    try:
        from src.monitoring.crawlers.google_fx import (
            _try_google_search as gs,
        )

        rate = await gs()
        if rate is not None:
            _logger.info("구글 Search 환율: %.2f", rate)
        return rate
    except Exception:
        _logger.warning("구글 Search 크롤링 실패", exc_info=True)
        return None


async def try_naver_mobile() -> float | None:
    """4차: 네이버 모바일 API에서 USD/KRW 환율을 조회한다."""
    try:
        from src.monitoring.crawlers.naver_fx import (
            _try_naver_mobile_api,
        )

        rate = await _try_naver_mobile_api()
        if rate is not None:
            _logger.info("네이버 모바일 API 환율: %.2f", rate)
        return rate
    except Exception:
        _logger.warning("네이버 모바일 API 실패", exc_info=True)
        return None


async def try_naver_pc() -> float | None:
    """5차: 네이버 Finance PC 웹에서 USD/KRW 환율을 크롤링한다."""
    try:
        from src.monitoring.crawlers.naver_fx import _try_naver_web

        rate = await _try_naver_web()
        if rate is not None:
            _logger.info("네이버 PC 환율 크롤링: %.2f", rate)
        return rate
    except Exception:
        _logger.warning("네이버 PC 크롤링 실패", exc_info=True)
        return None


async def run_fallback_chain(
    system: InjectedSystem,
) -> tuple[float, str] | None:
    """10단계 폴백 체인을 순차 실행하여 환율을 조회한다.

    순서: KIS → 구글Finance → 구글Search → 네이버모바일 →
    네이버PC → FRED → 한국은행 → ExchangeRate-API → Yahoo → 캐시
    모든 실패 시 None을 반환한다.
    """
    from src.monitoring.crawlers.fx_fallbacks import (
        fetch_bok_rate,
        fetch_exchangerate_api,
        fetch_fred_cached_rate,
        fetch_last_success_rate,
        fetch_yahoo_finance_rate,
    )

    cache = system.components.cache
    http = system.components.http

    # 1~10차: 코루틴을 지연 생성하여 미await 경고를 방지한다
    steps: list[tuple[str, Callable[[], Coroutine[Any, Any, float | None]]]] = [
        ("KIS", lambda: try_kis_rate(system)),
        ("Google-Finance", try_google_finance),
        ("Google-Search", try_google_search),
        ("Naver-Mobile", try_naver_mobile),
        ("Naver-PC", try_naver_pc),
        ("FRED-DEXKOUS", lambda: fetch_fred_cached_rate(cache)),
        ("BOK", lambda: fetch_bok_rate(http)),
        ("ExchangeRate-API", lambda: fetch_exchangerate_api(http)),
        ("Yahoo-Finance", lambda: fetch_yahoo_finance_rate(http)),
        ("last_success", lambda: fetch_last_success_rate(cache)),
    ]
    for source, fn in steps:
        rate = await fn()
        if rate is not None:
            return rate, source

    _logger.warning("환율 조회 10단계 모두 실패")
    return None
