"""
Polymarket 예측 시장 크롤러.

Polymarket Gamma API를 통해 매크로 경제 관련 예측 시장 데이터를 수집한다.
경기침체, 금리, 인플레이션, 반도체, 관세 등 키워드로 시장을 추적한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Polymarket Gamma API 베이스 URL
_GAMMA_API_BASE = "https://gamma-api.polymarket.com"

# 추적 대상 키워드 (매크로 경제 관련)
TRACKING_KEYWORDS: list[str] = [
    "recession",
    "fed rate",
    "interest rate",
    "inflation",
    "CPI",
    "tariff",
    "semiconductor",
    "S&P 500",
    "NASDAQ",
    "GDP",
]

# 최대 반환 시장 수
_MAX_MARKETS = 20


class PolymarketCrawler(BaseCrawler):
    """Polymarket Gamma API에서 예측 시장 데이터를 수집하는 크롤러.

    매크로 경제 관련 키워드로 활성 시장을 검색하고,
    24시간 거래량 기준 상위 시장의 확률 데이터를 반환한다.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """예측 시장 데이터를 수집하여 기사 형태로 반환한다."""
        markets = await self.fetch_relevant_markets()
        if not markets:
            return []

        articles: list[dict[str, Any]] = []
        for market in markets:
            question = market.get("question", "Unknown")
            yes_prob = market.get("yes_probability", 0)
            volume_24h = market.get("volume_24h", 0)
            keyword = market.get("matched_keyword", "")

            headline = (
                f"[Polymarket] {question}: "
                f"Yes {yes_prob:.1%}"
            )
            content = (
                f"Question: {question}\n"
                f"Yes Probability: {yes_prob:.1%}\n"
                f"24h Volume: ${volume_24h:,.0f}\n"
                f"Matched Keyword: {keyword}"
            )

            articles.append({
                "headline": headline,
                "content": content,
                "url": market.get("url", ""),
                "published_at": datetime.now(tz=timezone.utc),
                "source": self.source_key,
                "language": "en",
                "metadata": {
                    "data_type": "prediction_market",
                    "platform": "polymarket",
                    "question": question,
                    "yes_probability": yes_prob,
                    "volume_24h": volume_24h,
                    "matched_keyword": keyword,
                    "market_id": market.get("market_id", ""),
                    "end_date": market.get("end_date", ""),
                },
            })

        logger.info("[%s] 예측 시장 %d건 수집", self.name, len(articles))
        return articles

    async def fetch_relevant_markets(self) -> list[dict[str, Any]]:
        """추적 키워드와 관련된 활성 예측 시장을 조회한다.

        각 키워드로 검색하고, 24시간 거래량 기준으로 정렬하여
        상위 20개 시장을 반환한다.

        Returns:
            시장 데이터 딕셔너리 목록 (question, yes_probability, volume_24h 등).
        """
        session = await self.get_session()
        all_markets: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for keyword in TRACKING_KEYWORDS:
            try:
                url = f"{_GAMMA_API_BASE}/markets"
                params = {
                    "tag": keyword,
                    "active": "true",
                    "closed": "false",
                    "limit": 10,
                    "order": "volume24hr",
                    "ascending": "false",
                }

                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.debug(
                            "[%s] Gamma API HTTP %d (keyword=%s)",
                            self.name, resp.status, keyword,
                        )
                        # tag 파라미터 대신 텍스트 검색 시도
                        params_alt = {
                            "slug_contains": keyword.lower().replace(" ", "-"),
                            "active": "true",
                            "closed": "false",
                            "limit": 10,
                        }
                        async with session.get(url, params=params_alt) as resp2:
                            if resp2.status != 200:
                                continue
                            markets = await resp2.json()
                    else:
                        markets = await resp.json()

                if not isinstance(markets, list):
                    continue

                for market in markets:
                    market_id = str(
                        market.get("id", market.get("condition_id", ""))
                    )
                    if not market_id or market_id in seen_ids:
                        continue
                    seen_ids.add(market_id)

                    # 확률과 거래량 추출
                    yes_prob = self._extract_probability(market)
                    volume_24h = self._extract_volume(market)

                    question = market.get(
                        "question", market.get("title", "Unknown")
                    )
                    slug = market.get("slug", "")
                    end_date = market.get("end_date_iso", "")

                    all_markets.append({
                        "market_id": market_id,
                        "question": question,
                        "yes_probability": yes_prob,
                        "volume_24h": volume_24h,
                        "matched_keyword": keyword,
                        "url": f"https://polymarket.com/event/{slug}"
                        if slug
                        else "",
                        "end_date": end_date,
                    })

            except Exception as e:
                logger.warning(
                    "[%s] 키워드 '%s' 검색 실패: %s",
                    self.name, keyword, e,
                )
                continue

        # 24시간 거래량 기준 상위 N개 정렬
        all_markets.sort(key=lambda m: m.get("volume_24h", 0), reverse=True)
        top_markets = all_markets[:_MAX_MARKETS]

        logger.info(
            "[%s] 총 %d개 시장 중 상위 %d개 선택",
            self.name, len(all_markets), len(top_markets),
        )
        return top_markets

    @staticmethod
    def _extract_probability(market: dict[str, Any]) -> float:
        """시장 데이터에서 Yes 확률을 추출한다."""
        # 다양한 API 응답 형식에 대응
        for key in ("outcomePrices", "outcome_prices"):
            prices = market.get(key)
            if prices:
                try:
                    if isinstance(prices, str):
                        import json
                        prices = json.loads(prices)
                    if isinstance(prices, list) and len(prices) > 0:
                        return float(prices[0])
                except (ValueError, TypeError, IndexError):
                    pass

        # bestAsk / bestBid 또는 yes_price
        for key in ("yes_price", "best_ask"):
            val = market.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass

        return 0.0

    @staticmethod
    def _extract_volume(market: dict[str, Any]) -> float:
        """시장 데이터에서 24시간 거래량을 추출한다."""
        for key in ("volume24hr", "volume_24h", "volume"):
            val = market.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        return 0.0
