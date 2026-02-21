"""
본주(underlying)와 레버리지 ETF 간 매핑을 관리한다.

레버리지 ETF는 본주 가격 데이터를 기반으로 기술적 분석을 수행하고,
실제 주문은 레버리지 ETF 티커로 실행한다.
"""

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Underlying → Leveraged ETF mapping
# Key: 분석용 본주 티커
# Value: {"bull": 2X long ETF, "bear": 2X inverse ETF}
UNDERLYING_TO_LEVERAGED: dict[str, dict[str, str | None]] = {
    # Index ETFs
    "SPY": {"bull": "SSO", "bear": "SDS"},
    "QQQ": {"bull": "QLD", "bear": "QID"},
    "SOXX": {"bull": "USD", "bear": "SSG"},   # Semiconductor index
    "IWM": {"bull": "UWM", "bear": "TWM"},    # Russell 2000
    "DIA": {"bull": "DDM", "bear": "DXD"},    # Dow Jones
    "XLK": {"bull": "ROM", "bear": "REW"},    # Technology
    "XLF": {"bull": "UYG", "bear": "SKF"},    # Financials
    "XLE": {"bull": "DIG", "bear": "DUG"},    # Energy
    # Individual stocks
    "TSLA": {"bull": "TSLL", "bear": "TSLS"},
    "NVDA": {"bull": "NVDL", "bear": "NVDS"},
    "AAPL": {"bull": "AAPB", "bear": "AAPD"},
    "AMZN": {"bull": "AMZU", "bear": "AMZD"},
    "META": {"bull": "METU", "bear": None},
    "GOOGL": {"bull": "GGLL", "bear": None},
    "GOOG": {"bull": "GGLL", "bear": None},
    "MSFT": {"bull": "MSFL", "bear": None},
    "AMD": {"bull": "AMDU", "bear": None},
    "COIN": {"bull": "CONL", "bear": None},
    # 신규 추가 매핑
    "MSTR": {"bull": "MSTU", "bear": "MSTZ"},
}

# Reverse mapping: 레버리지 ETF → 본주
LEVERAGED_TO_UNDERLYING: dict[str, str] = {}
for _underlying, _pairs in UNDERLYING_TO_LEVERAGED.items():
    if _pairs.get("bull"):
        LEVERAGED_TO_UNDERLYING[_pairs["bull"]] = _underlying
    if _pairs.get("bear"):
        LEVERAGED_TO_UNDERLYING[_pairs["bear"]] = _underlying


# ---------------------------------------------------------------------------
# 섹터별 종목 분류
# ---------------------------------------------------------------------------

SECTOR_TICKERS: dict[str, dict] = {
    "semiconductors": {
        "name_kr": "반도체",
        "name_en": "Semiconductors",
        "tickers": ["NVDA", "AVGO", "AMD", "MU", "INTC", "QCOM", "TSM", "ARM", "MRVL"],
        "sector_leveraged": {"bull": "SOXL", "bear": "SOXS"},
    },
    "big_tech": {
        "name_kr": "빅테크",
        "name_en": "Big Tech",
        "tickers": ["MSFT", "AAPL", "GOOG", "GOOGL", "AMZN", "META", "NFLX"],
        "sector_leveraged": {"bull": "QLD", "bear": "QID"},
    },
    "ai_software": {
        "name_kr": "AI/소프트웨어",
        "name_en": "AI / Software",
        "tickers": ["PLTR", "DDOG", "MDB", "ORCL", "DELL", "CRM", "ADBE", "NOW", "SNOW"],
        "sector_leveraged": {"bull": "ROM", "bear": "REW"},
    },
    "ev_energy": {
        "name_kr": "전기차/에너지",
        "name_en": "EV / Energy",
        "tickers": ["TSLA"],
        "sector_leveraged": {"bull": "TSLL", "bear": "TSLS"},
    },
    "crypto": {
        "name_kr": "크립토/블록체인",
        "name_en": "Crypto / Blockchain",
        "tickers": ["MSTR", "CLSK", "COIN", "BITX", "CONL", "ETHU", "SBIT", "MSTU", "MSTZ"],
        "sector_leveraged": {"bull": "BITX", "bear": "SBIT"},
    },
    "finance": {
        "name_kr": "금융",
        "name_en": "Finance",
        "tickers": ["BLK", "BAC", "BRKB", "PYPL", "SQ", "JPM", "V", "MA"],
        "sector_leveraged": {"bull": "UYG", "bear": "SKF"},
    },
    "quantum": {
        "name_kr": "양자컴퓨팅",
        "name_en": "Quantum Computing",
        "tickers": ["IONQ", "RGTI"],
        "sector_leveraged": None,
    },
    "entertainment": {
        "name_kr": "엔터테인먼트",
        "name_en": "Entertainment",
        "tickers": ["DIS", "DKNG"],
        "sector_leveraged": None,
    },
    "infrastructure": {
        "name_kr": "인프라/리츠",
        "name_en": "Infrastructure / REIT",
        "tickers": ["NSC", "EQIX"],
        "sector_leveraged": None,
    },
    "consumer": {
        "name_kr": "소비재",
        "name_en": "Consumer",
        "tickers": ["KO"],
        "sector_leveraged": None,
    },
    "healthcare": {
        "name_kr": "헬스케어",
        "name_en": "Healthcare",
        "tickers": ["NVO", "UNH", "LLY"],
        "sector_leveraged": {"bull": "RXL", "bear": "RXD"},
    },
    "other": {
        "name_kr": "기타",
        "name_en": "Other",
        "tickers": ["FIG", "UBER", "SHOP"],
        "sector_leveraged": None,
    },
}

# 티커 → 섹터 역방향 인덱스 (빠른 조회용)
_TICKER_TO_SECTOR: dict[str, str] = {}
for _sector_key, _sector_info in SECTOR_TICKERS.items():
    for _ticker in _sector_info["tickers"]:
        _TICKER_TO_SECTOR[_ticker] = _sector_key


# ---------------------------------------------------------------------------
# 기존 함수
# ---------------------------------------------------------------------------


def get_underlying(leveraged_ticker: str) -> str:
    """레버리지 ETF 티커에서 본주 티커를 반환한다.

    Args:
        leveraged_ticker: 레버리지 ETF 티커 (예: "TSLL").

    Returns:
        본주 티커. 매핑이 없으면 입력값을 그대로 반환한다.
    """
    return LEVERAGED_TO_UNDERLYING.get(leveraged_ticker, leveraged_ticker)


def get_leveraged(underlying_ticker: str, direction: str = "bull") -> str | None:
    """본주 티커에서 레버리지 ETF 티커를 반환한다.

    Args:
        underlying_ticker: 본주 티커 (예: "TSLA").
        direction: "bull" (2X long) 또는 "bear" (2X inverse).

    Returns:
        레버리지 ETF 티커. 매핑이 없으면 None을 반환한다.
    """
    pairs = UNDERLYING_TO_LEVERAGED.get(underlying_ticker)
    if pairs:
        return pairs.get(direction)
    return None


def get_analysis_ticker(trade_ticker: str) -> str:
    """매매 티커에 대한 분석용 본주 티커를 반환한다.

    레버리지 ETF면 본주를 반환하고, 일반 주식이면 그대로 반환한다.
    기술적 지표 분석 시 본주 데이터를 활용하기 위해 사용한다.

    Args:
        trade_ticker: 매매 대상 티커 (레버리지 ETF 또는 일반 주식).

    Returns:
        분석용 티커. 레버리지 ETF면 해당 본주, 아니면 원래 티커.
    """
    return LEVERAGED_TO_UNDERLYING.get(trade_ticker, trade_ticker)


def get_all_mappings() -> list[dict]:
    """전체 본주-레버리지 매핑을 반환한다.

    Returns:
        매핑 목록. 각 항목: {"underlying", "bull_2x", "bear_2x"}
    """
    result = []
    for underlying, pairs in UNDERLYING_TO_LEVERAGED.items():
        result.append({
            "underlying": underlying,
            "bull_2x": pairs.get("bull"),
            "bear_2x": pairs.get("bear"),
        })
    return result


def add_mapping(
    underlying: str,
    bull_2x: str | None = None,
    bear_2x: str | None = None,
) -> bool:
    """본주-레버리지 매핑을 추가한다.

    Args:
        underlying: 본주 티커.
        bull_2x: 2X long ETF 티커. None이면 해당 방향 없음.
        bear_2x: 2X inverse ETF 티커. None이면 해당 방향 없음.

    Returns:
        추가 성공 여부. 이미 존재하는 경우 False.
    """
    if underlying in UNDERLYING_TO_LEVERAGED:
        logger.warning("이미 존재하는 매핑: %s", underlying)
        return False

    UNDERLYING_TO_LEVERAGED[underlying] = {"bull": bull_2x, "bear": bear_2x}
    if bull_2x:
        LEVERAGED_TO_UNDERLYING[bull_2x] = underlying
    if bear_2x:
        LEVERAGED_TO_UNDERLYING[bear_2x] = underlying
    logger.info("매핑 추가: %s → bull=%s, bear=%s", underlying, bull_2x, bear_2x)
    return True


def remove_mapping(underlying: str) -> bool:
    """본주-레버리지 매핑을 제거한다.

    Args:
        underlying: 제거할 본주 티커.

    Returns:
        제거 성공 여부. 존재하지 않으면 False.
    """
    if underlying not in UNDERLYING_TO_LEVERAGED:
        return False

    pairs = UNDERLYING_TO_LEVERAGED.pop(underlying)
    if pairs.get("bull") and pairs["bull"] in LEVERAGED_TO_UNDERLYING:
        del LEVERAGED_TO_UNDERLYING[pairs["bull"]]
    if pairs.get("bear") and pairs["bear"] in LEVERAGED_TO_UNDERLYING:
        del LEVERAGED_TO_UNDERLYING[pairs["bear"]]
    logger.info("매핑 제거: %s", underlying)
    return True


# ---------------------------------------------------------------------------
# 섹터 관련 헬퍼 함수
# ---------------------------------------------------------------------------


def get_sector(ticker: str) -> dict | None:
    """종목의 섹터 정보를 반환한다.

    Args:
        ticker: 종목 티커 심볼.

    Returns:
        섹터 정보 딕셔너리. {"sector_key", "name_kr", "name_en", "tickers", "sector_leveraged"}
        매핑이 없으면 None을 반환한다.
    """
    ticker = ticker.upper()
    sector_key = _TICKER_TO_SECTOR.get(ticker)
    if sector_key is None:
        return None
    sector_info = SECTOR_TICKERS[sector_key]
    return {
        "sector_key": sector_key,
        "name_kr": sector_info["name_kr"],
        "name_en": sector_info["name_en"],
        "tickers": sector_info["tickers"],
        "sector_leveraged": sector_info["sector_leveraged"],
    }


def get_tickers_by_sector(sector_key: str) -> list[str]:
    """섹터별 종목 리스트를 반환한다.

    Args:
        sector_key: 섹터 키 (예: "semiconductors", "big_tech").

    Returns:
        해당 섹터의 종목 티커 리스트. 존재하지 않는 섹터면 빈 리스트.
    """
    sector_info = SECTOR_TICKERS.get(sector_key)
    if sector_info is None:
        return []
    return list(sector_info["tickers"])


def get_all_sectors() -> dict:
    """전체 섹터 정보를 반환한다.

    Returns:
        SECTOR_TICKERS 딕셔너리의 복사본.
    """
    return dict(SECTOR_TICKERS)


def get_sector_leveraged(ticker: str) -> dict | None:
    """종목의 섹터 레버리지 ETF를 반환한다. 개별 레버리지가 없는 종목용.

    Args:
        ticker: 종목 티커 심볼.

    Returns:
        {"bull": ETF 티커, "bear": ETF 티커} 형태의 딕셔너리.
        섹터 레버리지가 없으면 None을 반환한다.
    """
    ticker = ticker.upper()
    sector_key = _TICKER_TO_SECTOR.get(ticker)
    if sector_key is None:
        return None
    sector_info = SECTOR_TICKERS[sector_key]
    return sector_info.get("sector_leveraged")


def add_ticker_to_sector(ticker: str, sector_key: str) -> bool:
    """런타임에 종목을 섹터에 추가한다.

    SECTOR_TICKERS와 _TICKER_TO_SECTOR 역방향 인덱스를 모두 갱신한다.
    이미 해당 섹터에 존재하는 종목이면 중복 추가하지 않는다.

    Args:
        ticker: 추가할 종목 티커 심볼 (대소문자 무관).
        sector_key: 대상 섹터 키 (예: "semiconductors", "big_tech").

    Returns:
        True이면 추가 성공(또는 이미 해당 섹터에 존재),
        False이면 sector_key가 존재하지 않는 경우.
    """
    ticker = ticker.upper()
    if sector_key not in SECTOR_TICKERS:
        logger.warning("존재하지 않는 섹터 키: %s", sector_key)
        return False

    if ticker not in SECTOR_TICKERS[sector_key]["tickers"]:
        SECTOR_TICKERS[sector_key]["tickers"].append(ticker)
        logger.info("섹터에 종목 추가: %s → %s", ticker, sector_key)

    # 역방향 인덱스도 갱신한다 (다른 섹터에 이미 있어도 덮어쓴다).
    _TICKER_TO_SECTOR[ticker] = sector_key
    return True
