"""ETF 유니버스 런타임 관리자

메모리 기반으로 ETF 유니버스를 관리하며,
종목 추가/제거/토글 및 조회 기능을 제공한다.
향후 DB 연동을 위한 인터페이스를 갖춘다.
"""

import copy
import logging
from typing import Optional

from src.strategy.etf_universe import (
    BEAR_2X_UNIVERSE,
    BULL_2X_UNIVERSE,
    CRYPTO_LEVERAGED_UNIVERSE,
    INDIVIDUAL_STOCK_UNIVERSE,
    SECTOR_LEVERAGED_UNIVERSE,
    _INVERSE_PAIRS,
)

logger = logging.getLogger(__name__)


class UniverseManager:
    """ETF 유니버스 런타임 관리자.

    메모리에서 유니버스 상태를 관리한다.
    향후 DB 연동 시 _load_from_db / _save_to_db 를 구현하면 된다.
    """

    def __init__(self) -> None:
        """초기 유니버스를 모듈 상수에서 deep copy하여 로드.

        Bull 2X ETF + 개별 주요 주식(30종목)을 bull 유니버스에,
        Bear 2X ETF를 bear 유니버스에 로드한다.
        개별 주식은 expense_ratio=0.0으로 ETF와 구별된다.
        """
        self._bull: dict[str, dict] = copy.deepcopy(BULL_2X_UNIVERSE)
        # 개별 주요 주식을 bull 유니버스에 병합한다 (방향성 매수 모니터링용)
        for ticker, info in INDIVIDUAL_STOCK_UNIVERSE.items():
            if ticker not in self._bull:
                self._bull[ticker] = copy.deepcopy(info)
        # 섹터 레버리지 ETF(SOXL, SOXS 등)를 bull 유니버스에 병합한다
        for ticker, info in SECTOR_LEVERAGED_UNIVERSE.items():
            if ticker not in self._bull:
                self._bull[ticker] = copy.deepcopy(info)
        # 크립토 레버리지 ETF를 bull 유니버스에 병합한다
        for ticker, info in CRYPTO_LEVERAGED_UNIVERSE.items():
            if ticker not in self._bull:
                self._bull[ticker] = copy.deepcopy(info)
        self._bear: dict[str, dict] = copy.deepcopy(BEAR_2X_UNIVERSE)
        logger.info(
            "UniverseManager initialized: %d bull (incl. %d individual stocks, %d sector leveraged, %d crypto leveraged), %d bear tickers",
            len(self._bull),
            len(INDIVIDUAL_STOCK_UNIVERSE),
            len(SECTOR_LEVERAGED_UNIVERSE),
            len(CRYPTO_LEVERAGED_UNIVERSE),
            len(self._bear),
        )

    # ------------------------------------------------------------------
    # 종목 관리
    # ------------------------------------------------------------------

    def add_ticker(
        self,
        ticker: str,
        direction: str,
        name: str,
        underlying: str,
        expense_ratio: float = 0.95,
        avg_daily_volume: int = 0,
        enabled: bool = True,
    ) -> bool:
        """새 종목을 유니버스에 추가.

        Args:
            ticker: ETF 티커 심볼.
            direction: "bull" 또는 "bear".
            name: ETF 정식 명칭.
            underlying: 기초 지수/자산 이름.
            expense_ratio: 운용 보수 비율.
            avg_daily_volume: 일평균 거래량.
            enabled: 활성 여부.

        Returns:
            True이면 추가 성공, False이면 이미 존재.
        """
        ticker = ticker.upper()
        universe = self._get_universe(direction)
        if universe is None:
            logger.error("Invalid direction: %s", direction)
            return False

        if ticker in universe:
            logger.warning("Ticker %s already exists in %s universe", ticker, direction)
            return False

        universe[ticker] = {
            "name": name,
            "underlying": underlying,
            "expense_ratio": expense_ratio,
            "avg_daily_volume": avg_daily_volume,
            "enabled": enabled,
        }
        logger.info("Added %s to %s universe: %s", ticker, direction, name)
        return True

    def remove_ticker(self, ticker: str) -> bool:
        """유니버스에서 종목 제거.

        Args:
            ticker: ETF 티커 심볼.

        Returns:
            True이면 제거 성공, False이면 존재하지 않음.
        """
        ticker = ticker.upper()
        if ticker in self._bull:
            del self._bull[ticker]
            logger.info("Removed %s from bull universe", ticker)
            return True
        if ticker in self._bear:
            del self._bear[ticker]
            logger.info("Removed %s from bear universe", ticker)
            return True

        logger.warning("Ticker %s not found in any universe", ticker)
        return False

    def toggle_ticker(self, ticker: str, enabled: Optional[bool] = None) -> bool:
        """종목 활성/비활성 토글.

        Args:
            ticker: ETF 티커 심볼.
            enabled: 명시적 설정. None이면 현재 상태를 반전.

        Returns:
            True이면 토글 성공, False이면 종목이 없음.
        """
        ticker = ticker.upper()
        info = self._bull.get(ticker) or self._bear.get(ticker)
        if info is None:
            logger.warning("Cannot toggle unknown ticker: %s", ticker)
            return False

        old_state = info["enabled"]
        info["enabled"] = (not old_state) if enabled is None else enabled
        logger.info(
            "Ticker %s enabled: %s -> %s", ticker, old_state, info["enabled"]
        )
        return True

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    def list_enabled(self, direction: Optional[str] = None) -> list[str]:
        """활성 종목 리스트 반환.

        Args:
            direction: "bull", "bear", 또는 None(전체).

        Returns:
            활성화된 티커 리스트 (정렬됨).
        """
        result: list[str] = []
        if direction is None or direction == "bull":
            result.extend(
                t for t, info in self._bull.items() if info["enabled"]
            )
        if direction is None or direction == "bear":
            result.extend(
                t for t, info in self._bear.items() if info["enabled"]
            )
        return sorted(result)

    def get_ticker_info(self, ticker: str) -> Optional[dict]:
        """종목 상세 정보 반환.

        Args:
            ticker: ETF 티커 심볼.

        Returns:
            종목 정보 딕셔너리 또는 None.
        """
        ticker = ticker.upper()
        if ticker in self._bull:
            return {"ticker": ticker, "direction": "bull", **self._bull[ticker]}
        if ticker in self._bear:
            return {"ticker": ticker, "direction": "bear", **self._bear[ticker]}
        return None

    def get_inverse_pair(self, ticker: str) -> Optional[str]:
        """Bull<->Bear 반대 방향 종목 반환.

        Args:
            ticker: ETF 티커 심볼.

        Returns:
            반대 방향 티커 또는 None.
        """
        return _INVERSE_PAIRS.get(ticker.upper())

    def get_all_tickers(self) -> list[str]:
        """전체 종목 티커 리스트 반환."""
        return sorted(list(self._bull.keys()) + list(self._bear.keys()))

    @property
    def bull_count(self) -> int:
        """Bull 유니버스 종목 수."""
        return len(self._bull)

    @property
    def bear_count(self) -> int:
        """Bear 유니버스 종목 수."""
        return len(self._bear)

    @property
    def enabled_count(self) -> int:
        """활성 종목 수."""
        return len(self.list_enabled())

    # ------------------------------------------------------------------
    # Internal / 향후 DB 연동
    # ------------------------------------------------------------------

    def _get_universe(self, direction: str) -> Optional[dict[str, dict]]:
        """방향에 따른 유니버스 딕셔너리 반환."""
        if direction == "bull":
            return self._bull
        if direction == "bear":
            return self._bear
        return None

    def list_by_sector(self) -> dict[str, list[dict]]:
        """섹터별 종목 리스트를 반환한다.

        SECTOR_TICKERS 정의를 기반으로 유니버스에 존재하는 종목을
        섹터별로 그룹화하여 반환한다.

        Returns:
            섹터 키를 키로, 해당 섹터에 속한 종목 정보 리스트를 값으로 하는 딕셔너리.
            각 종목 항목은 ticker, name, direction, enabled, sector 필드를 포함한다.
        """
        try:
            from src.utils.ticker_mapping import SECTOR_TICKERS, _TICKER_TO_SECTOR
        except ImportError:
            logger.error("SECTOR_TICKERS 임포트 실패")
            return {}

        result: dict[str, list[dict]] = {
            sector_key: [] for sector_key in SECTOR_TICKERS
        }
        result["unknown"] = []

        all_bull = {**self._bull}
        all_bear = {**self._bear}

        for ticker, info in all_bull.items():
            sector_key = _TICKER_TO_SECTOR.get(ticker)
            if sector_key is None:
                # sector 필드가 info에 있으면 사용
                sector_key = info.get("sector") or "unknown"
            entry = {
                "ticker": ticker,
                "name": info.get("name", ticker),
                "direction": "bull",
                "enabled": info.get("enabled", True),
                "sector": sector_key,
            }
            bucket = result.get(sector_key)
            if bucket is None:
                result[sector_key] = []
                bucket = result[sector_key]
            bucket.append(entry)

        for ticker, info in all_bear.items():
            sector_key = _TICKER_TO_SECTOR.get(ticker)
            if sector_key is None:
                sector_key = info.get("sector") or "unknown"
            entry = {
                "ticker": ticker,
                "name": info.get("name", ticker),
                "direction": "bear",
                "enabled": info.get("enabled", True),
                "sector": sector_key,
            }
            bucket = result.get(sector_key)
            if bucket is None:
                result[sector_key] = []
                bucket = result[sector_key]
            bucket.append(entry)

        return result

    def get_sector_summary(self) -> list[dict]:
        """섹터별 요약 정보를 반환한다 (종목수, 활성화 수 등).

        Returns:
            섹터별 요약 딕셔너리 리스트. 각 항목:
            - sector_key: 섹터 키
            - name_kr: 한국어 섹터명
            - name_en: 영문 섹터명
            - total: 전체 종목 수
            - enabled: 활성 종목 수
            - disabled: 비활성 종목 수
            - sector_leveraged: 섹터 레버리지 ETF 정보 (bull/bear)
        """
        try:
            from src.utils.ticker_mapping import SECTOR_TICKERS
        except ImportError:
            logger.error("SECTOR_TICKERS 임포트 실패")
            return []

        by_sector = self.list_by_sector()
        summary: list[dict] = []

        for sector_key, sector_info in SECTOR_TICKERS.items():
            tickers_in_sector = by_sector.get(sector_key, [])
            enabled_count = sum(1 for t in tickers_in_sector if t.get("enabled"))
            ticker_symbols = [t["ticker"] for t in tickers_in_sector]
            summary.append({
                "sector_key": sector_key,
                "name_kr": sector_info["name_kr"],
                "name_en": sector_info["name_en"],
                "total": len(tickers_in_sector),
                "enabled": enabled_count,
                "disabled": len(tickers_in_sector) - enabled_count,
                "sector_leveraged": sector_info.get("sector_leveraged"),
                "tickers": ticker_symbols,
            })

        return summary

    def _load_from_db(self) -> None:
        """향후 DB에서 유니버스 상태를 로드하는 인터페이스."""
        raise NotImplementedError("DB integration not yet implemented")

    def _save_to_db(self) -> None:
        """향후 DB에 유니버스 상태를 저장하는 인터페이스."""
        raise NotImplementedError("DB integration not yet implemented")
