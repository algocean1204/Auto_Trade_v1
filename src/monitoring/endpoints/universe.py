"""F7.8 UniverseEndpoints -- ETF 유니버스 관리 API이다.

유니버스 조회, 티커 추가/삭제/토글, 섹터 목록을 제공한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from src.common.logger import get_logger
from src.monitoring.schemas.universe_schemas import (
    AddTickerRequest,
    AutoAddRequest,
    MappingActionResponse,
    MappingAddRequest,
    MappingsResponse,
    SectorItem,
    SectorLeveragedItem,
    SectorsResponse,
    TickerActionResponse,
    TickerMappingItem,
    ToggleTickerRequest,
    UniverseResponse,
    UniverseTickerItem,
)
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

universe_router = APIRouter(prefix="/api/universe", tags=["universe"])

_system: InjectedSystem | None = None


def set_universe_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("UniverseEndpoints 의존성 주입 완료")


@universe_router.get("", response_model=UniverseResponse)
async def get_universe() -> UniverseResponse:
    """ETF 유니버스 전체 목록을 반환한다.

    Flutter UniverseTickerEx.fromJson 호환: direction, underlying 필드를 추가한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        registry = _system.components.registry
        all_tickers = registry.get_all()
        items: list[UniverseTickerItem] = []
        for t in all_tickers:
            # Flutter가 기대하는 direction(bull/bear)과 underlying 필드를 추가한다
            item = UniverseTickerItem(
                **t.model_dump(),
                direction="bear" if t.is_inverse else "bull",
                underlying=t.pair_ticker or t.ticker,
            )
            items.append(item)
        enabled_count = sum(1 for t in all_tickers if t.enabled)
        return UniverseResponse(universe=items, total=len(items), enabled=enabled_count)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("유니버스 조회 실패")
        raise HTTPException(status_code=500, detail="유니버스 조회 실패") from None


# 섹터명 한→영 매핑이다.
_SECTOR_NAMES: dict[str, tuple[str, str]] = {
    "semiconductor": ("반도체", "Semiconductor"),
    "tech": ("기술", "Technology"),
    "broad_market": ("시장 전체", "Broad Market"),
    "energy": ("에너지", "Energy"),
    "finance": ("금융", "Finance"),
    "healthcare": ("헬스케어", "Healthcare"),
    "biotech": ("바이오", "Biotech"),
    "real_estate": ("부동산", "Real Estate"),
    "crypto": ("가상자산", "Crypto"),
    "china": ("중국", "China"),
    "defense": ("방산", "Defense"),
    "ev": ("전기차", "Electric Vehicle"),
    "ai": ("인공지능", "AI"),
    "gold": ("금", "Gold"),
    "silver": ("은", "Silver"),
    "oil": ("원유", "Oil"),
    "natural_gas": ("천연가스", "Natural Gas"),
    "bonds": ("채권", "Bonds"),
}


@universe_router.get("/sectors", response_model=SectorsResponse)
async def get_sectors() -> SectorsResponse:
    """사용 가능한 섹터 목록을 반환한다.

    Flutter SectorData.fromJson 호환 형식으로 반환한다:
    sector_key, name_kr, name_en, tickers, sector_leveraged, enabled, total.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        from src.common.ticker_registry import SECTORS
        registry = _system.components.registry
        all_tickers = registry.get_all()

        # 섹터별 티커 목록과 bull/bear 페어를 수집한다
        sector_tickers: dict[str, list[str]] = {}
        sector_enabled: dict[str, int] = {}
        sector_bull: dict[str, str | None] = {}
        sector_bear: dict[str, str | None] = {}

        for t in all_tickers:
            s = t.sector
            sector_tickers.setdefault(s, []).append(t.ticker)
            if t.enabled:
                sector_enabled[s] = sector_enabled.get(s, 0) + 1
            # bull/bear 대표 티커 추출
            if not t.is_inverse:
                sector_bull.setdefault(s, t.ticker)
            else:
                sector_bear.setdefault(s, t.ticker)

        items: list[SectorItem] = []
        for s in SECTORS:
            tickers = sector_tickers.get(s, [])
            names = _SECTOR_NAMES.get(s, (s, s))
            leveraged = None
            bull = sector_bull.get(s)
            bear = sector_bear.get(s)
            if bull or bear:
                leveraged = SectorLeveragedItem(bull=bull, bear=bear)
            items.append(SectorItem(
                sector_key=s,
                name_kr=names[0],
                name_en=names[1],
                tickers=tickers,
                sector_leveraged=leveraged,
                enabled=sector_enabled.get(s, 0),
                total=len(tickers),
            ))
        return SectorsResponse(sectors=items)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("섹터 목록 조회 실패")
        raise HTTPException(status_code=500, detail="섹터 조회 실패") from None


@universe_router.post("/add", response_model=TickerActionResponse)
async def add_ticker(
    req: AddTickerRequest,
    _key: str = Depends(verify_api_key),
) -> TickerActionResponse:
    """유니버스에 티커를 추가한다. 페어 티커가 있으면 자동으로 함께 추가한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        registry = _system.components.registry
        if registry.has_ticker(req.ticker):
            raise HTTPException(
                status_code=409,
                detail=f"이미 존재하는 티커이다: {req.ticker}",
            )
        # 런타임 추가는 레지스트리 내부 map에 직접 삽입한다
        from src.common.ticker_registry import TickerMeta
        meta = TickerMeta(
            ticker=req.ticker, name=req.name, exchange=req.exchange,
            sector=req.sector, leverage=req.leverage,
            is_inverse=req.is_inverse, pair_ticker=req.pair_ticker,
            enabled=True,
        )
        registry._ticker_map[req.ticker] = meta
        persister = _system.features.get("universe_persister")
        if persister is not None:
            await persister.save_ticker(meta.model_dump())

        # 페어 티커가 있고 아직 등록되지 않았으면 자동 추가한다
        added_pair: str | None = None
        if req.pair_ticker and not registry.has_ticker(req.pair_ticker):
            added_pair = await _try_add_pair(registry, req.pair_ticker, persister)

        _logger.info("티커 추가 완료: %s (페어: %s)", req.ticker, added_pair)
        return TickerActionResponse(
            status="added", ticker=req.ticker, pair_ticker=added_pair,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 추가 실패: %s", req.ticker)
        raise HTTPException(status_code=500, detail="티커 추가 실패") from None


@universe_router.put("/toggle", response_model=TickerActionResponse)
async def toggle_ticker(
    req: ToggleTickerRequest,
    _key: str = Depends(verify_api_key),
) -> TickerActionResponse:
    """티커 활성/비활성 상태를 토글한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        registry = _system.components.registry
        if not registry.has_ticker(req.ticker):
            raise HTTPException(
                status_code=404,
                detail=f"등록되지 않은 티커이다: {req.ticker}",
            )
        registry._ticker_map[req.ticker].enabled = req.enabled
        # DB에 영속화한다
        persister = _system.features.get("universe_persister")
        if persister is not None:
            await persister.toggle_ticker(req.ticker, req.enabled)
        _logger.info("티커 토글: %s -> enabled=%s", req.ticker, req.enabled)
        return TickerActionResponse(
            status="toggled", ticker=req.ticker, enabled=req.enabled
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 토글 실패: %s", req.ticker)
        raise HTTPException(status_code=500, detail="티커 토글 실패") from None


@universe_router.post("/toggle", response_model=TickerActionResponse)
async def toggle_ticker_post(
    req: ToggleTickerRequest,
    _key: str = Depends(verify_api_key),
) -> TickerActionResponse:
    """티커 토글의 POST 별칭이다. Flutter 클라이언트 호환용."""
    return await toggle_ticker(req, _key)


# -- 매핑 캐시 키 --
_MAPPINGS_CACHE_KEY = "universe:mappings"


async def _load_mappings() -> list[dict]:
    """캐시에서 매핑 목록을 로드한다."""
    cache = _system.components.cache  # type: ignore[union-attr]
    cached = await cache.read_json(_MAPPINGS_CACHE_KEY)
    if cached and isinstance(cached, list):
        return cached
    return []


async def _save_mappings(mappings: list[dict]) -> None:
    """매핑 목록을 캐시에 저장한다."""
    cache = _system.components.cache  # type: ignore[union-attr]
    await cache.write_json(_MAPPINGS_CACHE_KEY, mappings)


@universe_router.get("/mappings", response_model=MappingsResponse)
async def get_mappings() -> MappingsResponse:
    """티커 매핑(원본-레버리지 페어) 목록을 반환한다.

    캐시에 저장된 매핑이 있으면 사용하고, 없으면 레지스트리에서 자동 생성한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        # 캐시에서 먼저 조회한다
        cached_mappings = await _load_mappings()
        if cached_mappings:
            items = [TickerMappingItem(**m) for m in cached_mappings]
            return MappingsResponse(mappings=items, count=len(items))

        # 캐시가 없으면 레지스트리에서 bull/bear 페어를 자동 생성한다
        registry = _system.components.registry
        all_tickers = registry.get_all()
        # bull 티커 기준으로 매핑을 구성한다 (is_inverse=False)
        pair_map: dict[str, TickerMappingItem] = {}
        for t in all_tickers:
            if not t.is_inverse and t.pair_ticker:
                pair_map[t.ticker] = TickerMappingItem(
                    underlying=t.ticker,
                    bull_2x=t.ticker,
                    bear_2x=t.pair_ticker or "",
                    sector=t.sector,
                )
        items = list(pair_map.values())
        return MappingsResponse(mappings=items, count=len(items))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 매핑 조회 실패")
        raise HTTPException(status_code=500, detail="매핑 조회 실패") from None


@universe_router.post("/mappings/add", response_model=MappingActionResponse)
async def add_mapping(
    req: MappingAddRequest,
    _key: str = Depends(verify_api_key),
) -> MappingActionResponse:
    """티커 매핑을 추가한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        mappings = await _load_mappings()
        # 중복 체크한다
        for m in mappings:
            if m.get("underlying") == req.underlying:
                raise HTTPException(
                    status_code=409,
                    detail=f"이미 존재하는 매핑이다: {req.underlying}",
                )
        mappings.append(req.model_dump())
        await _save_mappings(mappings)
        _logger.info("티커 매핑 추가: %s", req.underlying)
        return MappingActionResponse(status="added", underlying=req.underlying)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 매핑 추가 실패: %s", req.underlying)
        raise HTTPException(status_code=500, detail="매핑 추가 실패") from None


@universe_router.delete("/mappings/{underlying}", response_model=MappingActionResponse)
async def delete_mapping(
    underlying: str,
    _key: str = Depends(verify_api_key),
) -> MappingActionResponse:
    """티커 매핑을 삭제한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        mappings = await _load_mappings()
        original_len = len(mappings)
        mappings = [m for m in mappings if m.get("underlying") != underlying]
        if len(mappings) == original_len:
            raise HTTPException(
                status_code=404,
                detail=f"매핑을 찾을 수 없다: {underlying}",
            )
        await _save_mappings(mappings)
        _logger.info("티커 매핑 삭제: %s", underlying)
        return MappingActionResponse(status="deleted", underlying=underlying)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 매핑 삭제 실패: %s", underlying)
        raise HTTPException(status_code=500, detail="매핑 삭제 실패") from None


async def _try_add_pair(
    registry: object, pair_ticker: str, persister: object | None,
) -> str | None:
    """_ETF_RAW에서 페어 티커 메타데이터를 조회하여 자동 추가한다.

    추가 성공 시 페어 티커 코드를, 실패 시 None을 반환한다.
    """
    from src.common.ticker_registry import TickerMeta, _ETF_RAW, _ETF_FIELDS

    pair_raw = next((r for r in _ETF_RAW if r[0] == pair_ticker), None)
    if pair_raw is None:
        return None
    pair_meta = TickerMeta(**dict(zip(_ETF_FIELDS, pair_raw)))
    registry._ticker_map[pair_ticker] = pair_meta  # type: ignore[attr-defined]
    if persister is not None:
        await persister.save_ticker(pair_meta.model_dump())
    _logger.info("페어 티커 자동 추가 완료: %s", pair_ticker)
    return pair_ticker


@universe_router.post("/auto-add", response_model=TickerActionResponse)
async def auto_add_ticker(
    req: AutoAddRequest,
    _key: str = Depends(verify_api_key),
) -> TickerActionResponse:
    """티커 정보를 자동으로 조회하여 유니버스에 추가한다.

    _ETF_RAW에 메타데이터가 있으면 사용하고, 없으면 기본값으로 추가한다.
    페어 티커가 있으면 함께 자동 추가한다. 인증 필수.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        registry = _system.components.registry
        if registry.has_ticker(req.ticker):
            raise HTTPException(
                status_code=409,
                detail=f"이미 존재하는 티커이다: {req.ticker}",
            )
        from src.common.ticker_registry import TickerMeta, _ETF_RAW, _ETF_FIELDS

        # _ETF_RAW에서 메타데이터를 조회한다
        raw = next((r for r in _ETF_RAW if r[0] == req.ticker), None)
        if raw:
            meta = TickerMeta(**dict(zip(_ETF_FIELDS, raw)))
        else:
            meta = TickerMeta(
                ticker=req.ticker, name=req.ticker, exchange="AMS",
                sector="broad_market", leverage=2.0, is_inverse=False,
                pair_ticker=None, enabled=True,
            )
        registry._ticker_map[req.ticker] = meta
        persister = _system.features.get("universe_persister")
        if persister is not None:
            await persister.save_ticker(meta.model_dump())

        # 페어 티커가 있고 아직 등록되지 않았으면 자동 추가한다
        added_pair: str | None = None
        if meta.pair_ticker and not registry.has_ticker(meta.pair_ticker):
            added_pair = await _try_add_pair(registry, meta.pair_ticker, persister)

        _logger.info("티커 자동 추가 완료: %s (페어: %s)", req.ticker, added_pair)
        return TickerActionResponse(
            status="added", ticker=req.ticker, pair_ticker=added_pair,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 자동 추가 실패: %s", req.ticker)
        raise HTTPException(status_code=500, detail="자동 추가 실패") from None


@universe_router.delete("/{ticker}", response_model=TickerActionResponse)
async def delete_ticker(
    ticker: str,
    _key: str = Depends(verify_api_key),
) -> TickerActionResponse:
    """유니버스에서 티커를 삭제한다. 인증 필수.

    NOTE: 이 라우트는 와일드카드 경로이므로 반드시 다른 구체적 라우트 뒤에 등록해야 한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        registry = _system.components.registry
        if not registry.has_ticker(ticker):
            raise HTTPException(
                status_code=404,
                detail=f"등록되지 않은 티커이다: {ticker}",
            )
        del registry._ticker_map[ticker]
        # DB에서 삭제한다
        persister = _system.features.get("universe_persister")
        if persister is not None:
            await persister.delete_ticker(ticker)
        _logger.info("티커 삭제 완료: %s", ticker)
        return TickerActionResponse(status="deleted", ticker=ticker)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 삭제 실패: %s", ticker)
        raise HTTPException(status_code=500, detail="티커 삭제 실패") from None
