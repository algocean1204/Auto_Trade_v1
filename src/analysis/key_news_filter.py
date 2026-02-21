"""
핵심뉴스 필터링 모듈.

크롤링된 뉴스 중 시장에 중요한 영향을 미칠 수 있는
핵심뉴스를 분류하고 중요도를 판정한다.

분류 기준:
    - critical: 시장 전체 영향 (FOMC, CPI, 연준 발언, 트럼프 발표 등)
    - high: 모니터링 기업 직접 관련 (실적, 주요 뉴스)
    - medium: 관련 기업 (투자처, 경쟁사, 공급망)
    - low: 일반 뉴스
"""

from __future__ import annotations

import re
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 키워드 상수
# ---------------------------------------------------------------------------

# 시장 전체 영향 키워드 (소문자 비교)
_MARKET_WIDE_KEYWORDS: frozenset[str] = frozenset(
    {
        # 연준/통화정책
        "federal reserve",
        "fed reserve",
        "fomc",
        "rate decision",
        "interest rate",
        "rate hike",
        "rate cut",
        "monetary policy",
        "quantitative tightening",
        "qt",
        "powell",
        "federal open market",
        # 경제지표
        "cpi",
        "consumer price index",
        "ppi",
        "producer price index",
        "nonfarm payroll",
        "non-farm payroll",
        "unemployment rate",
        "jobs report",
        "gdp",
        "gross domestic product",
        "inflation",
        "deflation",
        # 정치/재정
        "trump",
        "tariff",
        "trade war",
        "trade deal",
        "yellen",
        "treasury secretary",
        "debt ceiling",
        "fiscal policy",
        "government shutdown",
        "sanctions",
        # 시장 이벤트
        "circuit breaker",
        "market crash",
        "black monday",
        "flash crash",
        "vix spike",
        "systemic risk",
        "financial crisis",
        "recession",
        "bear market",
        # 중앙은행 발언
        "fed chair",
        "fed governor",
        "fed president",
        "beige book",
        "jackson hole",
    }
)

# 실적 발표 관련 키워드
_EARNINGS_KEYWORDS: frozenset[str] = frozenset(
    {
        "earnings",
        "quarterly results",
        "q1",
        "q2",
        "q3",
        "q4",
        "revenue",
        "eps",
        "guidance",
        "forecast",
        "outlook",
        "beat",
        "miss",
        "in-line",
        "raised guidance",
        "lowered guidance",
        "profit warning",
        "revenue warning",
        "annual results",
        "full year",
    }
)

# 주요 기업 뉴스 키워드 (실적 외)
_COMPANY_MAJOR_KEYWORDS: frozenset[str] = frozenset(
    {
        "acquisition",
        "merger",
        "takeover",
        "buyout",
        "ipo",
        "spinoff",
        "spin-off",
        "layoffs",
        "mass layoff",
        "restructuring",
        "ceo resign",
        "ceo departure",
        "ceo appointment",
        "fda approval",
        "doj investigation",
        "sec investigation",
        "class action",
        "antitrust",
        "strategic review",
        "share buyback",
        "dividend cut",
        "dividend increase",
        "product launch",
    }
)

# VIX 급등/급락 키워드
_MARKET_VOLATILITY_KEYWORDS: frozenset[str] = frozenset(
    {
        "vix",
        "volatility index",
        "fear index",
        "market selloff",
        "sell-off",
        "market rally",
        "market plunge",
        "market surge",
        "stock crash",
        "index drop",
        "index surge",
    }
)

# 중요도 레이블
_IMPORTANCE_CRITICAL = "critical"
_IMPORTANCE_HIGH = "high"
_IMPORTANCE_MEDIUM = "medium"
_IMPORTANCE_LOW = "low"

# 중요도별 이모지 매핑
IMPORTANCE_EMOJI: dict[str, str] = {
    _IMPORTANCE_CRITICAL: "\U0001f534",  # 빨간 원
    _IMPORTANCE_HIGH: "\U0001f7e0",      # 주황 원
    _IMPORTANCE_MEDIUM: "\U0001f7e1",    # 노란 원
    _IMPORTANCE_LOW: "\U0001f7e2",       # 초록 원
}

# 중요도별 카테고리 한국어 표시
IMPORTANCE_CATEGORY_KR: dict[str, str] = {
    _IMPORTANCE_CRITICAL: "시장 전체",
    _IMPORTANCE_HIGH: "실적발표",
    _IMPORTANCE_MEDIUM: "관련기업",
    _IMPORTANCE_LOW: "일반",
}


class KeyNewsFilter:
    """핵심뉴스를 필터링하고 중요도를 분류한다.

    모니터링 기업 목록 및 ETF 유니버스를 기반으로
    뉴스의 시장 영향도를 판단한다.

    분류 기준:
        critical: 시장 전체 영향 (FOMC, 연준 발언, CPI 등)
        high: 모니터링 기업 직접 관련 (실적, M&A 등)
        medium: 관련 기업 (경쟁사, 공급망 등)
        low: 그 외 뉴스
    """

    def __init__(
        self,
        universe_tickers: list[str] | None = None,
        ticker_mapping: dict[str, Any] | None = None,
    ) -> None:
        """KeyNewsFilter를 초기화한다.

        Args:
            universe_tickers: 모니터링 기업 티커 목록 (대문자).
                None이면 ticker_mapping에서 자동으로 수집한다.
            ticker_mapping: 본주→레버리지 ETF 매핑 딕셔너리.
                None이면 기본 UNDERLYING_TO_LEVERAGED를 사용한다.
        """
        # 기본 매핑 로드
        try:
            from src.utils.ticker_mapping import (
                UNDERLYING_TO_LEVERAGED,
                SECTOR_TICKERS,
                _TICKER_TO_SECTOR,
            )

            self._underlying_to_leveraged = UNDERLYING_TO_LEVERAGED
            self._sector_tickers = SECTOR_TICKERS
            self._ticker_to_sector = _TICKER_TO_SECTOR
        except ImportError as exc:
            logger.warning("ticker_mapping 로드 실패, 빈 매핑 사용: %s", exc)
            self._underlying_to_leveraged = {}
            self._sector_tickers = {}
            self._ticker_to_sector = {}

        # 외부 매핑 오버라이드
        if ticker_mapping:
            self._underlying_to_leveraged = ticker_mapping

        # 모니터링 대상 티커 집합 구성
        if universe_tickers:
            self._monitored: set[str] = {t.upper() for t in universe_tickers}
        else:
            self._monitored = self._build_monitored_set()

        # 관련 기업 티커 집합 (섹터 내 종목 전체)
        self._related: set[str] = self._build_related_set()

        logger.info(
            "KeyNewsFilter 초기화 완료: 모니터링=%d개, 관련=%d개",
            len(self._monitored),
            len(self._related),
        )

    def is_key_news(self, article: dict[str, Any]) -> tuple[bool, str]:
        """핵심뉴스 여부와 분류 이유를 반환한다.

        Args:
            article: 뉴스 기사 딕셔너리.
                {"headline", "content", "tickers_mentioned", "classification"} 포함.

        Returns:
            (is_key, reason) 튜플:
                - is_key: True이면 핵심뉴스
                - reason: 분류 이유 (예: "시장 전체: FOMC 금리 결정")
        """
        importance = self.classify_importance(article)
        is_key = importance in (_IMPORTANCE_CRITICAL, _IMPORTANCE_HIGH, _IMPORTANCE_MEDIUM)
        reason = self._build_reason(article, importance)
        return is_key, reason

    def classify_importance(self, article: dict[str, Any]) -> str:
        """뉴스 중요도를 분류한다.

        Args:
            article: 뉴스 기사 딕셔너리.
                {"headline", "content", "tickers_mentioned", "classification"} 포함.

        Returns:
            "critical", "high", "medium", "low" 중 하나.
        """
        try:
            # 헤드라인 + 내용을 소문자로 합산
            headline = (article.get("headline") or "").lower()
            content = (article.get("content") or "")[:1000].lower()
            text = f"{headline} {content}"

            # 분류 결과에서 임팩트와 티커 추출
            classification = article.get("classification") or {}
            article_impact = classification.get("impact", "low")
            article_tickers: set[str] = {
                t.upper()
                for t in (article.get("tickers_mentioned") or [])
                if isinstance(t, str) and t.strip()
            }

            # 1. critical: 시장 전체 영향 키워드 매칭
            if self._matches_keywords(text, _MARKET_WIDE_KEYWORDS):
                return _IMPORTANCE_CRITICAL

            # 1-1. VIX/시장 변동성 + 분류 임팩트 high이면 critical
            if article_impact == "high" and self._matches_keywords(
                text, _MARKET_VOLATILITY_KEYWORDS
            ):
                return _IMPORTANCE_CRITICAL

            # 2. high: 모니터링 기업 직접 관련
            direct_overlap = article_tickers & self._monitored
            if direct_overlap:
                # 실적 발표 또는 주요 기업 이벤트
                if self._matches_keywords(
                    text, _EARNINGS_KEYWORDS | _COMPANY_MAJOR_KEYWORDS
                ):
                    return _IMPORTANCE_HIGH
                # 모니터링 종목 직접 언급 + 임팩트 high/medium
                if article_impact in ("high", "medium"):
                    return _IMPORTANCE_HIGH

            # 3. medium: 관련 기업 (섹터 내 경쟁사, 공급망)
            related_overlap = article_tickers & self._related
            if related_overlap and article_impact in ("high", "medium"):
                return _IMPORTANCE_MEDIUM

            # 4. medium: 실적 발표 키워드만 있어도 (섹터 관련성 있으면)
            article_sectors = {
                self._ticker_to_sector[t]
                for t in article_tickers
                if t in self._ticker_to_sector
            }
            monitored_sectors = {
                self._ticker_to_sector[t]
                for t in self._monitored
                if t in self._ticker_to_sector
            }
            if article_sectors & monitored_sectors and self._matches_keywords(
                text, _EARNINGS_KEYWORDS
            ):
                return _IMPORTANCE_MEDIUM

            return _IMPORTANCE_LOW

        except Exception as exc:
            logger.warning("중요도 분류 실패, 기본값 low 반환: %s", exc)
            return _IMPORTANCE_LOW

    def filter_key_news(
        self, articles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """기사 목록에서 핵심뉴스만 필터링한다.

        각 기사에 "importance", "importance_reason" 필드를 추가한다.

        Args:
            articles: 뉴스 기사 목록.

        Returns:
            핵심뉴스 목록 (critical, high, medium).
            중요도 순(critical → high → medium)으로 정렬된다.
        """
        if not articles:
            return []

        importance_order = {
            _IMPORTANCE_CRITICAL: 0,
            _IMPORTANCE_HIGH: 1,
            _IMPORTANCE_MEDIUM: 2,
            _IMPORTANCE_LOW: 3,
        }

        result: list[dict[str, Any]] = []
        for article in articles:
            importance = self.classify_importance(article)
            reason = self._build_reason(article, importance)
            if importance != _IMPORTANCE_LOW:
                result.append(
                    {
                        **article,
                        "importance": importance,
                        "importance_reason": reason,
                    }
                )

        # 중요도 순 정렬
        result.sort(key=lambda a: importance_order.get(a.get("importance", "low"), 3))

        logger.info(
            "핵심뉴스 필터링 완료: 전체 %d건 → 핵심 %d건",
            len(articles),
            len(result),
        )
        return result

    def _build_reason(self, article: dict[str, Any], importance: str) -> str:
        """중요도 분류 이유 문자열을 생성한다.

        Args:
            article: 뉴스 기사 딕셔너리.
            importance: 중요도 레이블.

        Returns:
            이유 문자열 (예: "시장 전체: FOMC 금리 결정").
        """
        try:
            headline = (article.get("headline") or "").lower()
            content = (article.get("content") or "")[:500].lower()
            text = f"{headline} {content}"

            category_kr = IMPORTANCE_CATEGORY_KR.get(importance, "일반")

            if importance == _IMPORTANCE_CRITICAL:
                # 매칭된 키워드 찾기
                matched = self._find_first_match(text, _MARKET_WIDE_KEYWORDS)
                if matched:
                    return f"{category_kr}: {matched}"
                matched = self._find_first_match(text, _MARKET_VOLATILITY_KEYWORDS)
                if matched:
                    return f"{category_kr}: {matched} 관련"
                return f"{category_kr}: 시장 전체 영향"

            elif importance == _IMPORTANCE_HIGH:
                article_tickers = {
                    t.upper()
                    for t in (article.get("tickers_mentioned") or [])
                    if isinstance(t, str)
                }
                overlap = article_tickers & self._monitored
                ticker_str = ", ".join(sorted(overlap)[:3])
                if self._matches_keywords(text, _EARNINGS_KEYWORDS):
                    return f"{category_kr}: {ticker_str} 실적 관련"
                return f"{category_kr}: {ticker_str} 직접 관련"

            elif importance == _IMPORTANCE_MEDIUM:
                article_tickers = {
                    t.upper()
                    for t in (article.get("tickers_mentioned") or [])
                    if isinstance(t, str)
                }
                overlap = article_tickers & self._related
                ticker_str = ", ".join(sorted(overlap)[:3])
                return f"{category_kr}: {ticker_str} 관련"

            return "일반 뉴스"

        except Exception as exc:
            logger.warning("이유 생성 실패: %s", exc)
            return "분류 이유 생성 실패"

    def _build_monitored_set(self) -> set[str]:
        """기본 매핑에서 모니터링 대상 티커 집합을 구성한다.

        본주 티커 + 레버리지 ETF 티커를 모두 포함한다.

        Returns:
            모니터링 대상 티커 집합.
        """
        monitored: set[str] = set()

        # 본주 티커
        for underlying in self._underlying_to_leveraged:
            monitored.add(underlying.upper())

        # 레버리지 ETF 티커
        for pairs in self._underlying_to_leveraged.values():
            if isinstance(pairs, dict):
                if pairs.get("bull"):
                    monitored.add(pairs["bull"].upper())
                if pairs.get("bear"):
                    monitored.add(pairs["bear"].upper())

        return monitored

    def _build_related_set(self) -> set[str]:
        """섹터 내 전체 종목에서 관련 기업 집합을 구성한다.

        모니터링 대상에 포함된 종목이 속한 섹터의 모든 종목을
        관련 기업으로 분류한다.

        Returns:
            관련 기업 티커 집합.
        """
        related: set[str] = set()

        # 모니터링 종목이 속한 섹터 확인
        monitored_sectors: set[str] = {
            self._ticker_to_sector[t]
            for t in self._monitored
            if t in self._ticker_to_sector
        }

        # 해당 섹터의 모든 종목 추가
        for sector_key in monitored_sectors:
            sector_info = self._sector_tickers.get(sector_key, {})
            for ticker in sector_info.get("tickers", []):
                related.add(ticker.upper())

        # 모니터링 종목 자체는 제외 (이미 _monitored에 있음)
        related -= self._monitored

        return related

    @staticmethod
    def _matches_keywords(text: str, keywords: frozenset[str]) -> bool:
        """텍스트에서 키워드 중 하나라도 매칭되는지 확인한다.

        Args:
            text: 검색 대상 텍스트 (소문자).
            keywords: 검색할 키워드 집합 (소문자).

        Returns:
            하나 이상의 키워드가 매칭되면 True.
        """
        for kw in keywords:
            if kw in text:
                return True
        return False

    @staticmethod
    def _find_first_match(text: str, keywords: frozenset[str]) -> str | None:
        """텍스트에서 첫 번째로 매칭된 키워드를 반환한다.

        Args:
            text: 검색 대상 텍스트 (소문자).
            keywords: 검색할 키워드 집합.

        Returns:
            첫 번째로 매칭된 키워드. 없으면 None.
        """
        for kw in sorted(keywords):  # 정렬하여 결정적 반환
            if kw in text:
                return kw
        return None
