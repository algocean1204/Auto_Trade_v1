"""
TickerRegistry (C0.12) -- ETF 유니버스, 인버스 페어, 거래소 코드, 섹터 매핑을 제공한다.
부팅 시 DB에서 유니버스를 로드한다. DB가 비어있으면 하드코딩 _ETF_RAW로 시드한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from src.common.universe_persister import UniversePersister

# -- 싱글톤 인스턴스 --
_instance: TickerRegistry | None = None


class TickerMeta(BaseModel):
    """개별 ETF 메타 정보이다.

    DB(UniverseConfig)에서 로드 시 id, created_at, updated_at 등
    extra 필드가 전달될 수 있으므로 무시한다.
    """

    model_config = ConfigDict(extra="ignore")

    ticker: str
    name: str
    exchange: str
    sector: str
    leverage: float
    is_inverse: bool
    pair_ticker: str | None
    enabled: bool


class ReferenceTicker(BaseModel):
    """비레버리지 참조 티커 정보이다. 시세 조회 전용으로 사용한다."""

    ticker: str
    exchange: str
    description: str


# -- 하드코딩 ETF 유니버스 (ticker, name, exchange, sector, leverage, is_inverse, pair, enabled) --
_ETF_RAW: list[tuple] = [
    ("SOXL", "Direxion 2x Semiconductor Bull", "AMS", "semiconductor", 2.0, False, "SOXS", True),
    ("SOXS", "Direxion 2x Semiconductor Bear", "AMS", "semiconductor", -2.0, True, "SOXL", True),
    ("QLD", "ProShares 2x QQQ Bull", "AMS", "tech", 2.0, False, "QID", True),
    ("QID", "ProShares 2x QQQ Bear", "AMS", "tech", -2.0, True, "QLD", True),
    ("SSO", "ProShares 2x S&P500 Bull", "AMS", "broad_market", 2.0, False, "SDS", True),
    ("SDS", "ProShares 2x S&P500 Bear", "AMS", "broad_market", -2.0, True, "SSO", True),
    ("UWM", "ProShares 2x Russell 2000 Bull", "AMS", "small_cap", 2.0, False, "TWM", True),
    ("TWM", "ProShares 2x Russell 2000 Bear", "AMS", "small_cap", -2.0, True, "UWM", True),
    ("DDM", "ProShares 2x Dow Jones Bull", "AMS", "broad_market", 2.0, False, "DXD", True),
    ("DXD", "ProShares 2x Dow Jones Bear", "AMS", "broad_market", -2.0, True, "DDM", True),
    ("NVDL", "GraniteShares 2x Long NVDA", "NAS", "semiconductor", 2.0, False, "NVDS", True),
    ("NVDS", "T-Rex 2x Inverse NVDA", "NAS", "semiconductor", -2.0, True, "NVDL", True),
    ("TQQQ", "ProShares 3x QQQ Bull", "NAS", "tech", 3.0, False, "SQQQ", False),
    ("SQQQ", "ProShares 3x QQQ Bear", "NAS", "tech", -3.0, True, "TQQQ", False),
]

_ETF_FIELDS: list[str] = [
    "ticker", "name", "exchange", "sector", "leverage", "is_inverse", "pair_ticker", "enabled",
]

# -- 참조 티커 (비레버리지, 시세 전용: ticker, exchange, description) --
_REF_RAW: list[tuple[str, str, str]] = [
    ("SPY", "AMS", "S&P500 벤치마크, 매크로 크래시 감지"),
    ("QQQ", "NAS", "NASDAQ 벤치마크, 매크로 크래시 감지"),
    ("IWM", "AMS", "Russell 2000 벤치마크"),
    ("DIA", "AMS", "Dow Jones 벤치마크"),
]

# -- 섹터 정의 --
SECTORS: list[str] = [
    "tech",
    "semiconductor",
    "broad_market",
    "small_cap",
    "energy",
    "financials",
    "healthcare",
]


def _build_ticker_map() -> dict[str, TickerMeta]:
    """튜플 데이터를 TickerMeta 딕셔너리로 변환한다."""
    return {
        row[0]: TickerMeta(**dict(zip(_ETF_FIELDS, row)))
        for row in _ETF_RAW
    }


class TickerRegistry:
    """티커 정보 레지스트리이다.

    ETF 유니버스 메타 정보를 조회하는 유일한 접근 경로이다.
    """

    def __init__(self) -> None:
        """하드코딩 데이터로 레지스트리를 초기화한다."""
        self._ticker_map: dict[str, TickerMeta] = _build_ticker_map()
        self._reference: list[ReferenceTicker] = [
            ReferenceTicker(ticker=t, exchange=e, description=d)
            for t, e, d in _REF_RAW
        ]

    def _get_meta(self, ticker: str) -> TickerMeta:
        """티커 메타 정보를 반환한다. 없으면 KeyError를 발생시킨다."""
        meta = self._ticker_map.get(ticker)
        if meta is None:
            raise KeyError(f"등록되지 않은 티커이다: {ticker}")
        return meta

    def get_universe(self) -> list[TickerMeta]:
        """활성화된(enabled=True) ETF 유니버스를 반환한다."""
        return [m for m in self._ticker_map.values() if m.enabled]

    def get_all(self) -> list[TickerMeta]:
        """비활성화 포함 전체 ETF 목록을 반환한다."""
        return list(self._ticker_map.values())

    def get_pair(self, ticker: str) -> str | None:
        """인버스 페어 티커를 반환한다. 페어가 없으면 None이다."""
        return self._get_meta(ticker).pair_ticker

    def get_exchange_code(self, ticker: str) -> str:
        """KIS 거래소 코드(NAS/AMS/NYS)를 반환한다."""
        return self._get_meta(ticker).exchange

    def get_sector(self, ticker: str) -> str:
        """해당 티커의 섹터를 반환한다."""
        return self._get_meta(ticker).sector

    def is_inverse(self, ticker: str) -> bool:
        """인버스 ETF인지 판별한다."""
        return self._get_meta(ticker).is_inverse

    def is_enabled(self, ticker: str) -> bool:
        """활성화된 ETF인지 판별한다."""
        return self._get_meta(ticker).enabled

    def get_reference_tickers(self) -> list[ReferenceTicker]:
        """참조 티커(비레버리지) 목록을 반환한다."""
        return list(self._reference)

    def get_bull_tickers(self) -> list[TickerMeta]:
        """활성화된 롱(Bull) ETF만 반환한다."""
        return [
            m for m in self._ticker_map.values()
            if m.enabled and not m.is_inverse
        ]

    def get_bear_tickers(self) -> list[TickerMeta]:
        """활성화된 숏(Bear/Inverse) ETF만 반환한다."""
        return [
            m for m in self._ticker_map.values()
            if m.enabled and m.is_inverse
        ]

    def get_by_sector(self, sector: str) -> list[TickerMeta]:
        """특정 섹터의 활성화된 ETF를 반환한다."""
        return [
            m for m in self._ticker_map.values()
            if m.enabled and m.sector == sector
        ]

    async def load_from_db(self, persister: UniversePersister) -> None:
        """DB에서 유니버스를 로드하여 내부 맵을 교체한다.

        DB가 비어있으면 persister가 하드코딩 데이터를 시드한 뒤 반환한다.
        로드 실패 시 기존 하드코딩 맵을 유지한다 (graceful degradation).
        """
        rows = await persister.load_or_seed()
        if rows:
            self._ticker_map = {
                r["ticker"]: TickerMeta(**r) for r in rows
            }

    def has_ticker(self, ticker: str) -> bool:
        """해당 티커가 레지스트리에 존재하는지 확인한다."""
        return ticker in self._ticker_map


def get_ticker_registry() -> TickerRegistry:
    """TickerRegistry 싱글톤을 반환한다."""
    global _instance
    if _instance is not None:
        return _instance

    _instance = TickerRegistry()
    return _instance


def reset_ticker_registry() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None
