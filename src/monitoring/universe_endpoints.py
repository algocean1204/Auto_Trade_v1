"""
Flutter 대시보드용 유니버스 관리 API 엔드포인트.

ETF 유니버스(종목 추가/삭제/활성화), 본주-레버리지 매핑 관리,
섹터별 조회, 크롤링 수동 실행/상태 조회 엔드포인트를 제공한다.

엔드포인트 목록:
  GET    /universe                       - ETF 유니버스 전체 목록
  GET    /universe/sectors               - 전체 섹터 목록 + 종목수 요약
  GET    /universe/sectors/{sector_key}  - 특정 섹터 종목 리스트
  POST   /universe/add                   - 유니버스에 종목 추가
  POST   /universe/auto-add              - Claude가 자동으로 매핑 정보 조회 후 추가
  POST   /universe/toggle                - 종목 활성화/비활성화
  DELETE /universe/{ticker}              - 유니버스에서 종목 제거
  GET    /universe/mappings              - 본주-레버리지 매핑 전체
  POST   /universe/mappings/add          - 매핑 추가
  DELETE /universe/mappings/{underlying} - 매핑 제거
  POST   /crawl/manual                   - 수동 크롤링 실행
  GET    /crawl/status/{task_id}         - 크롤링 상태 조회
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from src.monitoring.auth import verify_api_key
from src.monitoring.schemas import (
    AddTickerRequest,
    CrawlDetailedStatusResponse,
    ManualCrawlResponse,
    ToggleTickerRequest,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Claude 프롬프트 템플릿 — 종목 자동 리서치용
# ---------------------------------------------------------------------------

_VALID_SECTORS = {
    "semiconductors", "big_tech", "ai_software", "ev_energy", "crypto",
    "finance", "quantum", "entertainment", "infrastructure", "consumer",
    "healthcare", "other",
}

TICKER_RESEARCH_PROMPT = """You are a US stock market expert. Given a ticker symbol, provide the following information in JSON format:

Ticker: {ticker}

Return EXACTLY this JSON structure:
{{
  "ticker": "{ticker}",
  "name": "Full Company Name",
  "sector": "semiconductors",
  "underlying_description": "Semiconductors / AI",
  "exchange": "NAS",
  "avg_daily_volume": 50000000,
  "bull_2x_etf": "NVDL",
  "bear_2x_etf": "NVDD",
  "sector_bull_etf": "SOXL",
  "sector_bear_etf": "SOXS",
  "notes": "Brief notes about the leveraged ETFs"
}}

Rules:
- sector MUST be one of: semiconductors, big_tech, ai_software, ev_energy, crypto, finance, quantum, entertainment, infrastructure, consumer, healthcare, other
- exchange: NAS (NASDAQ), NYS (NYSE), AMS (AMEX/NYSE Arca for ETFs)
- For bull_2x_etf/bear_2x_etf: Only include real, currently trading 2X leveraged ETFs. Set to null if none exists.
- For sector_bull_etf/sector_bear_etf: The sector-level 2X or 3X leveraged ETF. Set to null if none exists.
- avg_daily_volume: approximate recent average daily volume as an integer
- Return ONLY valid JSON, no markdown, no explanation, no extra text.
"""

# ---------------------------------------------------------------------------
# 모듈 레벨 의존성 레지스트리
# api_server.py 가 startup 시 set_universe_deps() 를 호출하여 주입한다.
# ---------------------------------------------------------------------------

_deps: dict[str, Any] = {}

# 크롤 태스크 저장소
# 구조: task_id -> {
#   "status": str,
#   "data": dict | None,
#   "progress_events": list[dict],  # 실시간 진행 이벤트 목록
#   "crawler_statuses": dict[str, dict],  # 크롤러별 최신 상태
#   "total_crawlers": int,
#   "completed_crawlers": int,
# }
_crawl_tasks: dict[str, dict[str, Any]] = {}
_MAX_CRAWL_TASKS = 50


def set_universe_deps(
    universe_manager: Any = None,
    crawl_engine: Any = None,
    claude_client: Any = None,
    classifier: Any = None,
) -> None:
    """런타임 의존성을 주입한다.

    api_server.py 의 set_dependencies() 호출 시 함께 호출되어야 한다.

    Args:
        universe_manager: 유니버스 관리 인스턴스.
        crawl_engine: 크롤링 엔진 인스턴스.
        claude_client: Claude AI 클라이언트 인스턴스 (auto-add 엔드포인트에 사용).
        classifier: NewsClassifier 인스턴스 (수동 크롤 후 분류에 사용).
    """
    _deps["universe_manager"] = universe_manager
    _deps["crawl_engine"] = crawl_engine
    _deps["claude_client"] = claude_client
    _deps["classifier"] = classifier


def _get(name: str) -> Any:
    """의존성을 조회한다. 없으면 503을 반환한다."""
    dep = _deps.get(name)
    if dep is None:
        raise HTTPException(
            status_code=503,
            detail=f"Service '{name}' is not available",
        )
    return dep


def _try_get(name: str) -> Any | None:
    """의존성을 조회한다. 없으면 None을 반환한다 (503 대신)."""
    return _deps.get(name)


# ---------------------------------------------------------------------------
# APIRouter
# ---------------------------------------------------------------------------

universe_router = APIRouter(tags=["universe"])


# ===================================================================
# Universe management endpoints
# ===================================================================


@universe_router.get("/universe")
async def get_universe() -> list[dict]:
    """전체 ETF 유니버스 목록을 반환한다."""
    um = _try_get("universe_manager")
    if um is None:
        return [
            {"ticker": "SOXL", "name": "Direxion Semiconductor Bull 3X", "direction": "bull", "enabled": True},
            {"ticker": "QLD", "name": "ProShares Ultra QQQ", "direction": "bull", "enabled": True},
            {"ticker": "SSO", "name": "ProShares Ultra S&P500", "direction": "bull", "enabled": True},
            {"ticker": "TQQQ", "name": "ProShares UltraPro QQQ", "direction": "bull", "enabled": True},
        ]
    tickers = um.get_all_tickers()
    result: list[dict] = []
    for ticker in tickers:
        info = um.get_ticker_info(ticker)
        if info is not None:
            result.append(info)
    return result


@universe_router.post("/universe/add")
async def add_ticker(
    body: AddTickerRequest,
    _: None = Depends(verify_api_key),
) -> dict:
    """유니버스에 새 종목을 추가한다."""
    um = _get("universe_manager")
    success = um.add_ticker(
        ticker=body.ticker,
        direction=body.direction,
        name=body.name,
        underlying=body.underlying,
        expense_ratio=body.expense_ratio,
        avg_daily_volume=body.avg_daily_volume,
        enabled=body.enabled,
    )
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Ticker {body.ticker} already exists or invalid direction",
        )
    return {"status": "ok", "ticker": body.ticker.upper()}


@universe_router.post("/universe/auto-add")
async def auto_add_ticker(
    request: Request,
    _: None = Depends(verify_api_key),
) -> JSONResponse:
    """종목 코드만 입력하면 Claude가 자동으로 매핑 정보를 조회하여 추가한다.

    Claude Sonnet을 호출하여 종목명, 섹터, 레버리지 ETF 정보 등을 조회하고,
    유니버스와 티커 매핑에 자동으로 등록한다.

    Request body:
        {"ticker": "NVDA"}

    Returns:
        추가된 종목의 전체 매핑 정보.

    Raises:
        400: ticker가 누락되거나 Claude 응답 파싱에 실패한 경우.
        409: 이미 유니버스에 존재하는 종목인 경우.
        503: Claude 클라이언트 또는 유니버스 매니저가 미주입인 경우.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "요청 바디가 올바른 JSON 형식이 아닙니다.", "error_code": "INVALID_JSON"},
            status_code=400,
        )

    ticker = body.get("ticker", "").strip().upper()
    if not ticker:
        return JSONResponse(
            {"error": "ticker 필드가 필요합니다.", "error_code": "MISSING_TICKER"},
            status_code=400,
        )

    # 유니버스 매니저 확인 — 이미 존재하는 종목인지 체크한다.
    um = _try_get("universe_manager")
    if um is not None and um.get_ticker_info(ticker) is not None:
        return JSONResponse(
            {
                "error": f"{ticker}은(는) 이미 유니버스에 존재합니다.",
                "error_code": "TICKER_ALREADY_EXISTS",
            },
            status_code=409,
        )

    # Claude 클라이언트 확인
    claude = _try_get("claude_client")
    if claude is None:
        return JSONResponse(
            {
                "error": "Claude 클라이언트가 초기화되지 않았습니다.",
                "error_code": "CLAUDE_NOT_AVAILABLE",
            },
            status_code=503,
        )

    # Claude 호출 — 종목 정보 조회
    prompt = TICKER_RESEARCH_PROMPT.format(ticker=ticker)
    logger.info("Claude 종목 자동 조회 시작 | ticker=%s", ticker)

    try:
        result = await claude.call(
            prompt=prompt,
            task_type="news_classification",  # Sonnet 사용 (빠름)
            use_cache=False,  # 티커 리서치는 캐시 불사용 (최신 정보 필요)
        )
        raw_content: str = result["content"]
    except Exception as exc:
        logger.error("Claude 호출 실패 | ticker=%s | error=%s", ticker, exc)
        return JSONResponse(
            {
                "error": f"Claude 호출 중 오류가 발생했습니다: {exc}",
                "error_code": "CLAUDE_CALL_FAILED",
            },
            status_code=500,
        )

    # Claude 응답 JSON 파싱
    try:
        info = claude._extract_json(raw_content)
        if not isinstance(info, dict):
            raise ValueError("JSON 응답이 딕셔너리 형식이 아닙니다.")
    except (ValueError, Exception) as exc:
        logger.error(
            "Claude 응답 JSON 파싱 실패 | ticker=%s | content=%s | error=%s",
            ticker, raw_content[:300], exc,
        )
        return JSONResponse(
            {
                "error": f"Claude 응답 파싱에 실패했습니다: {exc}",
                "error_code": "PARSE_FAILED",
                "raw_response": raw_content[:500],
            },
            status_code=400,
        )

    # 섹터 검증
    sector = (info.get("sector") or "other").lower().strip()
    if sector not in _VALID_SECTORS:
        logger.warning(
            "유효하지 않은 섹터값, 'other'로 대체 | ticker=%s | sector=%s",
            ticker, sector,
        )
        sector = "other"
    info["sector"] = sector

    # 필수 필드 기본값 처리
    name: str = info.get("name") or ticker
    underlying_description: str = info.get("underlying_description") or name
    exchange: str = (info.get("exchange") or "NAS").upper()
    avg_daily_volume: int = int(info.get("avg_daily_volume") or 0)
    bull_2x_etf: str | None = info.get("bull_2x_etf") or None
    bear_2x_etf: str | None = info.get("bear_2x_etf") or None
    if bull_2x_etf:
        bull_2x_etf = bull_2x_etf.upper().strip()
    if bear_2x_etf:
        bear_2x_etf = bear_2x_etf.upper().strip()

    added_to_universe = False
    added_mapping = False
    added_to_sector = False

    # 유니버스에 종목 추가 (bull 방향으로 등록)
    if um is not None:
        success = um.add_ticker(
            ticker=ticker,
            direction="bull",
            name=name,
            underlying=underlying_description,
            avg_daily_volume=avg_daily_volume,
            enabled=True,
        )
        if success:
            added_to_universe = True
            logger.info("유니버스 추가 완료 | ticker=%s | name=%s", ticker, name)
        else:
            logger.warning("유니버스 추가 실패 또는 이미 존재 | ticker=%s", ticker)

    # 본주-레버리지 매핑 추가 (bull/bear ETF 중 하나라도 있으면 추가)
    if bull_2x_etf or bear_2x_etf:
        from src.utils.ticker_mapping import add_mapping
        mapping_success = add_mapping(
            underlying=ticker,
            bull_2x=bull_2x_etf,
            bear_2x=bear_2x_etf,
        )
        if mapping_success:
            added_mapping = True
            logger.info(
                "레버리지 매핑 추가 완료 | underlying=%s | bull=%s | bear=%s",
                ticker, bull_2x_etf, bear_2x_etf,
            )
        else:
            logger.warning("레버리지 매핑 이미 존재 | underlying=%s", ticker)

    # SECTOR_TICKERS에 종목 추가
    from src.utils.ticker_mapping import add_ticker_to_sector
    sector_success = add_ticker_to_sector(ticker, sector)
    if sector_success:
        added_to_sector = True
        logger.info("섹터 추가 완료 | ticker=%s | sector=%s", ticker, sector)

    logger.info(
        "종목 자동 추가 완료 | ticker=%s | universe=%s | mapping=%s | sector=%s",
        ticker, added_to_universe, added_mapping, added_to_sector,
    )

    # 프로필 자동 생성 (추가 성공 시에만 수행)
    profile_generated = False
    profile_data: dict = {}
    if added_to_universe:
        try:
            from src.analysis.ticker_profiler import TickerProfiler
            profiler = TickerProfiler(claude_client=claude)
            profile_data = await profiler.generate_and_save(
                ticker=ticker,
                name=name,
                sector=sector,
                underlying=underlying_description,
            )
            profile_generated = bool(profile_data)
            logger.info("프로필 자동 생성 완료 | ticker=%s | success=%s", ticker, profile_generated)
        except Exception as profile_exc:
            logger.warning("프로필 자동 생성 실패 (%s): %s", ticker, profile_exc)

    return JSONResponse(
        {
            "status": "ok",
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "exchange": exchange,
            "underlying_description": underlying_description,
            "avg_daily_volume": avg_daily_volume,
            "bull_2x_etf": bull_2x_etf,
            "bear_2x_etf": bear_2x_etf,
            "sector_bull_etf": info.get("sector_bull_etf"),
            "sector_bear_etf": info.get("sector_bear_etf"),
            "notes": info.get("notes"),
            "added_to_universe": added_to_universe,
            "added_mapping": added_mapping,
            "added_to_sector": added_to_sector,
            "profile_generated": profile_generated,
            "profile": profile_data if profile_generated else None,
        },
        status_code=200,
    )


@universe_router.post("/universe/toggle")
async def toggle_ticker(
    body: ToggleTickerRequest,
    _: None = Depends(verify_api_key),
) -> dict:
    """유니버스에서 종목을 활성화/비활성화한다."""
    um = _get("universe_manager")
    success = um.toggle_ticker(body.ticker, body.enabled)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Ticker {body.ticker} not found",
        )
    return {
        "status": "ok",
        "ticker": body.ticker.upper(),
        "enabled": body.enabled,
    }


@universe_router.delete("/universe/{ticker}")
async def remove_ticker(
    ticker: str,
    _: None = Depends(verify_api_key),
) -> dict:
    """유니버스에서 종목을 제거한다."""
    um = _get("universe_manager")
    success = um.remove_ticker(ticker)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Ticker {ticker} not found",
        )
    return {"status": "ok", "ticker": ticker.upper()}


# ===================================================================
# Universe mapping endpoints
# ===================================================================


@universe_router.get("/universe/sectors")
async def get_universe_sectors() -> dict:
    """전체 섹터 목록과 각 섹터의 종목수 요약을 반환한다.

    Returns:
        sectors 키에 섹터별 요약 정보 리스트를 담은 딕셔너리.
        각 항목: sector_key, name_kr, name_en, total, enabled, disabled, sector_leveraged
    """
    um = _try_get("universe_manager")
    if um is None:
        # universe_manager 미주입 시 정적 데이터 반환
        from src.utils.ticker_mapping import SECTOR_TICKERS
        sectors = [
            {
                "sector_key": key,
                "name_kr": info["name_kr"],
                "name_en": info["name_en"],
                "total": len(info["tickers"]),
                "enabled": len(info["tickers"]),
                "disabled": 0,
                "sector_leveraged": info.get("sector_leveraged"),
                "tickers": list(info["tickers"]),
            }
            for key, info in SECTOR_TICKERS.items()
        ]
        return {"sectors": sectors}

    try:
        summary = um.get_sector_summary()
        return {"sectors": summary}
    except Exception as exc:
        logger.error("섹터 요약 조회 실패: %s", exc)
        raise HTTPException(status_code=500, detail="섹터 요약 조회 중 오류가 발생했습니다.")


@universe_router.get("/universe/sectors/{sector_key}")
async def get_universe_sector_detail(sector_key: str) -> dict:
    """특정 섹터에 속한 종목 리스트를 반환한다.

    Args:
        sector_key: 섹터 키 (예: semiconductors, big_tech, crypto).

    Returns:
        sector_key, name_kr, name_en, tickers 키를 포함하는 딕셔너리.
        tickers는 해당 섹터에 속한 종목 정보 리스트.

    Raises:
        HTTPException 404: 존재하지 않는 섹터 키인 경우.
    """
    from src.utils.ticker_mapping import SECTOR_TICKERS

    sector_info = SECTOR_TICKERS.get(sector_key)
    if sector_info is None:
        raise HTTPException(
            status_code=404,
            detail=f"섹터를 찾을 수 없습니다: {sector_key}",
        )

    um = _try_get("universe_manager")
    if um is None:
        # universe_manager 미주입 시 정적 데이터 반환
        tickers = [
            {"ticker": t, "sector": sector_key, "enabled": True}
            for t in sector_info["tickers"]
        ]
        return {
            "sector_key": sector_key,
            "name_kr": sector_info["name_kr"],
            "name_en": sector_info["name_en"],
            "sector_leveraged": sector_info.get("sector_leveraged"),
            "tickers": tickers,
        }

    try:
        by_sector = um.list_by_sector()
        tickers = by_sector.get(sector_key, [])
        return {
            "sector_key": sector_key,
            "name_kr": sector_info["name_kr"],
            "name_en": sector_info["name_en"],
            "sector_leveraged": sector_info.get("sector_leveraged"),
            "tickers": tickers,
        }
    except Exception as exc:
        logger.error("섹터 종목 조회 실패 (sector_key=%s): %s", sector_key, exc)
        raise HTTPException(status_code=500, detail="섹터 종목 조회 중 오류가 발생했습니다.")


@universe_router.get("/universe/mappings")
async def get_universe_mappings() -> dict:
    """본주-레버리지 ETF 매핑 전체 목록을 반환한다."""
    from src.utils.ticker_mapping import get_all_mappings
    return {"mappings": get_all_mappings()}


@universe_router.post("/universe/mappings/add")
async def add_universe_mapping(
    body: dict,
    _: None = Depends(verify_api_key),
) -> dict:
    """본주-레버리지 매핑을 추가한다.

    Body: {"underlying": "TSLA", "bull_2x": "TSLL", "bear_2x": "TSLS"}
    """
    from src.utils.ticker_mapping import add_mapping

    underlying = body.get("underlying", "").upper().strip()
    if not underlying:
        raise HTTPException(status_code=400, detail="underlying 티커가 필요합니다.")

    bull_2x = body.get("bull_2x") or None
    bear_2x = body.get("bear_2x") or None
    if bull_2x:
        bull_2x = bull_2x.upper().strip()
    if bear_2x:
        bear_2x = bear_2x.upper().strip()

    success = add_mapping(underlying, bull_2x=bull_2x, bear_2x=bear_2x)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"이미 존재하는 매핑: {underlying}",
        )
    return {"status": "ok", "underlying": underlying, "bull_2x": bull_2x, "bear_2x": bear_2x}


@universe_router.delete("/universe/mappings/{underlying}")
async def remove_universe_mapping(
    underlying: str,
    _: None = Depends(verify_api_key),
) -> dict:
    """본주-레버리지 매핑을 제거한다."""
    from src.utils.ticker_mapping import remove_mapping

    success = remove_mapping(underlying.upper())
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"매핑을 찾을 수 없음: {underlying.upper()}",
        )
    return {"status": "ok", "removed": underlying.upper()}


# ===================================================================
# Ticker profile endpoints
# ===================================================================

# 백그라운드 프로필 생성 태스크 저장소
# 구조: task_id -> {"status": str, "results": dict | None}
_profile_tasks: dict[str, dict[str, Any]] = {}
_MAX_PROFILE_TASKS = 20


@universe_router.post("/universe/generate-profile/{ticker}")
async def generate_ticker_profile(
    ticker: str,
    _: None = Depends(verify_api_key),
) -> JSONResponse:
    """단일 종목의 프로필을 Claude Opus로 생성하고 RAG DB에 저장한다.

    Args:
        ticker: 종목 티커 심볼 (URL 경로).

    Returns:
        생성된 프로필 딕셔너리.

    Raises:
        503: Claude 클라이언트가 미주입인 경우.
        500: 프로필 생성에 실패한 경우.
    """
    ticker_upper = ticker.upper().strip()
    claude = _try_get("claude_client")
    if claude is None:
        return JSONResponse(
            {
                "error": "Claude 클라이언트가 초기화되지 않았습니다.",
                "error_code": "CLAUDE_NOT_AVAILABLE",
            },
            status_code=503,
        )

    # 유니버스에서 종목 정보 조회 (있으면 name/sector/underlying 사용)
    um = _try_get("universe_manager")
    name = ""
    sector = ""
    underlying = ""
    if um is not None:
        info = um.get_ticker_info(ticker_upper)
        if info is not None:
            name = info.get("name", "")
            sector = info.get("sector", "")
            underlying = info.get("underlying", "")

    try:
        from src.analysis.ticker_profiler import TickerProfiler
        profiler = TickerProfiler(claude_client=claude)
        profile = await profiler.generate_and_save(
            ticker=ticker_upper,
            name=name,
            sector=sector,
            underlying=underlying,
        )
        if not profile:
            return JSONResponse(
                {
                    "error": f"{ticker_upper} 프로필 생성에 실패했습니다.",
                    "error_code": "PROFILE_GENERATION_FAILED",
                },
                status_code=500,
            )
        return JSONResponse(
            {
                "status": "ok",
                "ticker": ticker_upper,
                "profile": profile,
            },
            status_code=200,
        )
    except Exception as exc:
        logger.error("프로필 생성 엔드포인트 오류 (%s): %s", ticker_upper, exc)
        return JSONResponse(
            {
                "error": f"프로필 생성 중 오류가 발생했습니다: {exc}",
                "error_code": "PROFILE_ERROR",
            },
            status_code=500,
        )


@universe_router.post("/universe/generate-all-profiles")
async def generate_all_profiles(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_api_key),
) -> JSONResponse:
    """전체 모니터링 종목의 프로필을 백그라운드에서 일괄 생성한다.

    종목 수에 따라 수 분 이상 소요될 수 있다 (종목당 약 10초).
    반환된 task_id로 GET /universe/profile-task/{task_id} 를 폴링하여
    진행 상황을 확인할 수 있다.

    Returns:
        task_id와 시작 상태.

    Raises:
        503: Claude 클라이언트 또는 유니버스 매니저가 미주입인 경우.
    """
    from uuid import uuid4 as _uuid4

    claude = _try_get("claude_client")
    if claude is None:
        return JSONResponse(
            {
                "error": "Claude 클라이언트가 초기화되지 않았습니다.",
                "error_code": "CLAUDE_NOT_AVAILABLE",
            },
            status_code=503,
        )

    um = _try_get("universe_manager")
    if um is None:
        return JSONResponse(
            {
                "error": "유니버스 매니저가 초기화되지 않았습니다.",
                "error_code": "UNIVERSE_MANAGER_NOT_AVAILABLE",
            },
            status_code=503,
        )

    # 메모리 누수 방지
    if len(_profile_tasks) >= _MAX_PROFILE_TASKS:
        excess = len(_profile_tasks) - _MAX_PROFILE_TASKS + 1
        for key in list(_profile_tasks.keys())[:excess]:
            del _profile_tasks[key]

    task_id = str(_uuid4())
    _profile_tasks[task_id] = {"status": "started", "results": None}

    async def _run_all_profiles() -> None:
        try:
            from src.analysis.ticker_profiler import TickerProfiler
            profiler = TickerProfiler(claude_client=claude)
            results = await profiler.generate_all_profiles(um)
            _profile_tasks[task_id]["status"] = "completed"
            _profile_tasks[task_id]["results"] = results
        except Exception as exc:
            logger.error("전체 프로필 생성 실패 (task_id=%s): %s", task_id, exc)
            _profile_tasks[task_id]["status"] = "failed"
            _profile_tasks[task_id]["results"] = {"error": str(exc)}

    background_tasks.add_task(_run_all_profiles)
    return JSONResponse(
        {
            "status": "started",
            "task_id": task_id,
            "message": "전체 종목 프로필 생성이 백그라운드에서 시작되었습니다. task_id로 상태를 확인하세요.",
        },
        status_code=202,
    )


@universe_router.get("/universe/profile-task/{task_id}")
async def get_profile_task_status(task_id: str) -> JSONResponse:
    """전체 프로필 생성 태스크의 진행 상황을 반환한다.

    Args:
        task_id: generate-all-profiles 엔드포인트가 반환한 task_id.

    Returns:
        태스크 상태 (started / completed / failed) 및 결과.

    Raises:
        404: 존재하지 않는 task_id인 경우.
    """
    task = _profile_tasks.get(task_id)
    if task is None:
        return JSONResponse(
            {"error": f"태스크를 찾을 수 없습니다: {task_id}", "error_code": "TASK_NOT_FOUND"},
            status_code=404,
        )
    return JSONResponse(
        {
            "task_id": task_id,
            "status": task["status"],
            "results": task.get("results"),
        },
        status_code=200,
    )


@universe_router.get("/universe/profile/{ticker}")
async def get_ticker_profile(ticker: str) -> JSONResponse:
    """저장된 종목 프로필을 RAG DB에서 조회한다.

    Args:
        ticker: 종목 티커 심볼 (URL 경로).

    Returns:
        프로필 딕셔너리 (content, metadata 포함).

    Raises:
        404: 프로필이 존재하지 않는 경우.
    """
    ticker_upper = ticker.upper().strip()
    try:
        from src.db.connection import get_session
        from src.db.models import RagDocument
        from sqlalchemy import select

        async with get_session() as session:
            stmt = (
                select(RagDocument)
                .where(
                    RagDocument.ticker == ticker_upper,
                    RagDocument.doc_type == "ticker_profile",
                )
                .order_by(RagDocument.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

        if row is None:
            return JSONResponse(
                {
                    "error": f"{ticker_upper} 프로필이 존재하지 않습니다. 먼저 프로필을 생성하세요.",
                    "error_code": "PROFILE_NOT_FOUND",
                },
                status_code=404,
            )

        return JSONResponse(
            {
                "ticker": ticker_upper,
                "id": str(row.id),
                "title": row.title,
                "content": row.content,
                "metadata": row.metadata_,
                "source": row.source,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            },
            status_code=200,
        )
    except Exception as exc:
        logger.error("프로필 조회 오류 (%s): %s", ticker_upper, exc)
        return JSONResponse(
            {
                "error": f"프로필 조회 중 오류가 발생했습니다: {exc}",
                "error_code": "PROFILE_FETCH_ERROR",
            },
            status_code=500,
        )


# ===================================================================
# Crawl endpoints
# ===================================================================


@universe_router.post("/crawl/manual", response_model=ManualCrawlResponse)
async def start_manual_crawl(
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_api_key),
) -> ManualCrawlResponse:
    """수동 크롤링을 백그라운드에서 실행한다.

    반환되는 task_id로 GET /crawl/status/{task_id} (폴링) 또는
    WS /ws/crawl/{task_id} (실시간)를 통해 진행 상황을 추적할 수 있다.
    """
    engine = _get("crawl_engine")
    task_id = str(uuid4())

    # 메모리 누수 방지: 최대 크기 초과 시 오래된 항목부터 제거한다.
    if len(_crawl_tasks) >= _MAX_CRAWL_TASKS:
        excess = len(_crawl_tasks) - _MAX_CRAWL_TASKS + 1
        for key in list(_crawl_tasks.keys())[:excess]:
            del _crawl_tasks[key]

    _crawl_tasks[task_id] = {
        "status": "started",
        "data": None,
        "progress_events": [],
        "crawler_statuses": {},
        "total_crawlers": 0,
        "completed_crawlers": 0,
    }

    async def _on_progress(event: dict) -> None:
        """크롤 엔진에서 호출되는 진행 콜백. 이벤트를 메모리에 기록한다."""
        task = _crawl_tasks.get(task_id)
        if task is None:
            return

        # 전체 이벤트 목록에 추가한다 (최근 200개만 보관하여 메모리를 제한한다).
        events: list = task["progress_events"]
        events.append(event)
        if len(events) > 200:
            del events[:-200]

        ev_type = event.get("type", "")

        if ev_type == "crawl_started":
            task["total_crawlers"] = event.get("total_crawlers", 0)
            task["status"] = "running"

        elif ev_type == "crawler_start":
            key = event.get("crawler_key", event.get("crawler_name", ""))
            task["crawler_statuses"][key] = {
                "name": event.get("crawler_name", key),
                "key": key,
                "index": event.get("crawler_index", 0),
                "status": "running",
                "articles_count": 0,
                "message": event.get("message", ""),
                "timestamp": event.get("timestamp", ""),
            }

        elif ev_type == "crawler_done":
            key = event.get("crawler_key", event.get("crawler_name", ""))
            task["crawler_statuses"][key] = {
                "name": event.get("crawler_name", key),
                "key": key,
                "index": event.get("crawler_index", 0),
                "status": "completed",
                "articles_count": event.get("articles_count", 0),
                "message": event.get("message", ""),
                "timestamp": event.get("timestamp", ""),
            }
            task["completed_crawlers"] = task.get("completed_crawlers", 0) + 1

        elif ev_type == "crawl_summary":
            task["status"] = "completed"
            task["data"] = {
                "total_articles": event.get("total_articles", 0),
                "unique_articles": event.get("unique_articles", 0),
                "saved_articles": event.get("saved_articles", 0),
                "duplicates_removed": event.get("duplicates_removed", 0),
                "kept": event.get("kept", 0),
                "uncertain": event.get("uncertain", 0),
                "discarded": event.get("discarded", 0),
                "duration_seconds": event.get("duration_seconds", 0),
                "crawler_results": event.get("crawler_results", []),
            }

    async def _run_crawl() -> None:
        try:
            _crawl_tasks[task_id]["status"] = "running"
            result = await engine.run_with_progress(
                task_id=task_id,
                mode="delta",
                progress_callback=_on_progress,
            )
            # _on_progress 가 이미 완료 상태를 기록하지만
            # 콜백 없이 호출된 경우를 대비해 최종 결과를 보장한다.
            if _crawl_tasks[task_id]["status"] != "completed":
                _crawl_tasks[task_id]["status"] = "completed"
                _crawl_tasks[task_id]["data"] = result

            # 크롤 완료 후 미처리 기사를 분류하고 DB에 저장한다.
            classifier = _try_get("classifier")
            if classifier is None:
                logger.warning(
                    "Manual crawl 후 분류 건너뜀: classifier 의존성 미주입 (task_id=%s)",
                    task_id,
                )
            else:
                try:
                    _crawl_tasks[task_id]["status"] = "classifying"
                    from sqlalchemy import select
                    from src.db.connection import get_session
                    from src.db.models import Article as ArticleModel
                    import asyncio as _asyncio

                    async with get_session() as session:
                        stmt = (
                            select(ArticleModel)
                            .where(ArticleModel.is_processed.is_(False))
                            .order_by(ArticleModel.crawled_at.desc())
                            .limit(200)
                        )
                        db_result = await session.execute(stmt)
                        unprocessed = list(db_result.scalars().all())

                    if unprocessed:
                        articles_for_classify = [
                            {
                                "id": str(a.id),
                                "title": a.headline,
                                "summary": (a.content or "")[:500],
                                "source": a.source,
                                "published_at": (
                                    a.published_at.isoformat()
                                    if a.published_at else ""
                                ),
                            }
                            for a in unprocessed
                        ]
                        classified = await classifier.classify_and_store_batch(
                            articles_for_classify,
                        )
                        logger.info(
                            "Manual crawl 분류 완료: %d건 처리 (task_id=%s)",
                            len(classified), task_id,
                        )
                        # 분류 결과를 태스크 데이터에 반영한다.
                        if _crawl_tasks[task_id].get("data") is not None:
                            _crawl_tasks[task_id]["data"]["classified_count"] = len(classified)
                    else:
                        logger.info(
                            "Manual crawl 후 미처리 기사 없음 (task_id=%s)", task_id,
                        )

                    _crawl_tasks[task_id]["status"] = "completed"
                except Exception as classify_exc:
                    logger.error(
                        "Manual crawl 후 분류 실패 (task_id=%s): %s",
                        task_id, classify_exc,
                    )
                    # 분류 실패는 크롤 결과를 무효화하지 않는다.
                    _crawl_tasks[task_id]["status"] = "completed"

        except Exception as exc:
            logger.error("Manual crawl failed: %s", exc)
            _crawl_tasks[task_id]["status"] = "failed"
            _crawl_tasks[task_id]["data"] = {"error": str(exc)}

    background_tasks.add_task(_run_crawl)
    return ManualCrawlResponse(
        task_id=task_id,
        status="started",
        message="Crawl started in background",
    )


@universe_router.get("/crawl/status/{task_id}", response_model=CrawlDetailedStatusResponse)
async def get_crawl_status(task_id: str) -> CrawlDetailedStatusResponse:
    """크롤링 태스크의 현재 진행 상황을 반환한다.

    폴링 방식으로 크롤링 상태를 확인하려는 클라이언트를 위해
    크롤러별 상세 상태와 진행률을 포함한 응답을 반환한다.
    실시간 스트림은 WS /ws/crawl/{task_id} 를 사용한다.
    """
    task = _crawl_tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    total = task.get("total_crawlers", 0)
    completed = task.get("completed_crawlers", 0)

    # 크롤러 상태 목록을 인덱스 순서로 정렬한다.
    crawler_statuses = sorted(
        task.get("crawler_statuses", {}).values(),
        key=lambda x: x.get("index", 0),
    )

    return CrawlDetailedStatusResponse(
        task_id=task_id,
        status=task["status"],
        total_crawlers=total,
        completed_crawlers=completed,
        progress_pct=round(completed / total * 100, 1) if total > 0 else 0.0,
        crawler_statuses=list(crawler_statuses),
        data=task.get("data"),
    )
