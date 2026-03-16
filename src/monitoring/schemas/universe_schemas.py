"""F7.8 UniverseSchemas -- 유니버스 API 요청/응답 Pydantic 모델을 정의한다.

universe 엔드포인트에서 사용하는 모든 요청/응답 모델을 관리한다.
엔드포인트 로직과 스키마 정의를 분리하여 SRP를 준수한다.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AddTickerRequest(BaseModel):
    """티커 추가 요청 모델이다."""

    ticker: str
    name: str
    exchange: str = "AMS"
    sector: str = "broad_market"
    leverage: float = 2.0
    is_inverse: bool = False
    pair_ticker: str | None = None


class ToggleTickerRequest(BaseModel):
    """티커 활성/비활성 토글 요청 모델이다."""

    ticker: str
    enabled: bool


class UniverseTickerItem(BaseModel):
    """유니버스 개별 티커 항목 모델이다.

    TickerMeta.model_dump() + direction/underlying 추가 필드를 포함한다.
    향후 추가 필드가 유입될 수 있으므로 extra='allow'로 설정한다.
    """

    model_config = ConfigDict(extra="allow")

    ticker: str = ""
    name: str = ""
    exchange: str = ""
    sector: str = ""
    leverage: float = 1.0
    is_inverse: bool = False
    pair_ticker: str | None = None
    enabled: bool = True
    direction: str = "bull"
    underlying: str = ""


class UniverseResponse(BaseModel):
    """유니버스 목록 응답 모델이다."""

    universe: list[UniverseTickerItem] = Field(default_factory=list)
    total: int = 0
    enabled: int = 0


class TickerMappingItem(BaseModel):
    """티커 매핑 항목 모델이다. 원본-레버리지 페어 매핑 정보를 나타낸다."""

    underlying: str
    bull_2x: str = ""
    bear_2x: str = ""
    sector: str = ""


class MappingsResponse(BaseModel):
    """티커 매핑 목록 응답 모델이다."""

    mappings: list[TickerMappingItem] = Field(default_factory=list)
    count: int = 0


class MappingAddRequest(BaseModel):
    """티커 매핑 추가 요청 모델이다."""

    underlying: str
    bull_2x: str = ""
    bear_2x: str = ""
    sector: str = ""


class MappingActionResponse(BaseModel):
    """매핑 추가/삭제 응답 모델이다."""

    status: str
    underlying: str


class AutoAddRequest(BaseModel):
    """유니버스 자동 추가 요청 모델이다."""

    ticker: str


class SectorLeveragedItem(BaseModel):
    """섹터 레버리지 ETF 매핑 모델이다."""

    bull: str | None = None
    bear: str | None = None


class SectorItem(BaseModel):
    """섹터 항목 모델이다. Flutter SectorData.fromJson 호환.

    키: sector_key, name_kr, name_en, tickers, sector_leveraged, enabled, total
    """

    sector_key: str = ""
    name_kr: str = ""
    name_en: str = ""
    tickers: list[str] = Field(default_factory=list)
    sector_leveraged: SectorLeveragedItem | None = None
    enabled: int = 0
    total: int = 0


class SectorsResponse(BaseModel):
    """섹터 목록 응답 모델이다."""

    sectors: list[SectorItem] = Field(default_factory=list)


class TickerActionResponse(BaseModel):
    """티커 추가/삭제/토글 응답 모델이다."""

    status: str
    ticker: str
    enabled: bool | None = None
    pair_ticker: str | None = None
