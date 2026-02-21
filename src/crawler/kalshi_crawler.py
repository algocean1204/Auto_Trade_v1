"""
Kalshi 예측 시장 크롤러.

Kalshi API를 통해 매크로 경제 예측 데이터를 수집한다.
Fed 금리, CPI, GDP, 고용 지표 시리즈를 추적하여
AI 판단에 활용할 매크로 컨텍스트를 생성한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Kalshi API 베이스 URL
_KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"

# 추적 대상 시리즈 티커
TRACKING_SERIES: dict[str, str] = {
    "KXFED": "Fed Funds Rate Decision",
    "KXCPI": "CPI / Inflation",
    "KXGDP": "GDP Growth",
    "KXNFP": "Non-Farm Payrolls",
}


class KalshiCrawler(BaseCrawler):
    """Kalshi API에서 매크로 경제 예측 시장 데이터를 수집하는 크롤러.

    KXFED(금리), KXCPI(물가), KXGDP(성장률), KXNFP(고용) 시리즈의
    활성 시장을 조회하고, 확률 데이터를 AI 컨텍스트로 변환한다.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """모든 추적 시리즈의 데이터를 수집하고 기사 형태로 반환한다."""
        all_data = await self.fetch_all()
        if not all_data:
            return []

        articles: list[dict[str, Any]] = []
        for item in all_data:
            series = item.get("series_ticker", "")
            title = item.get("title", "Unknown")
            yes_prob = item.get("yes_probability", 0)

            headline = (
                f"[Kalshi] {series}: {title} - "
                f"Yes {yes_prob:.1%}"
            )
            content = (
                f"Series: {series} ({TRACKING_SERIES.get(series, '')})\n"
                f"Market: {title}\n"
                f"Yes Probability: {yes_prob:.1%}\n"
                f"Volume: {item.get('volume', 0):,}\n"
                f"Status: {item.get('status', 'unknown')}"
            )

            articles.append({
                "headline": headline,
                "content": content,
                "url": f"https://kalshi.com/markets/{item.get('ticker', '')}",
                "published_at": datetime.now(tz=timezone.utc),
                "source": self.source_key,
                "language": "en",
                "metadata": {
                    "data_type": "prediction_market",
                    "platform": "kalshi",
                    "series_ticker": series,
                    "market_ticker": item.get("ticker", ""),
                    "title": title,
                    "yes_probability": yes_prob,
                    "volume": item.get("volume", 0),
                    "open_interest": item.get("open_interest", 0),
                    "status": item.get("status", ""),
                    "expiration": item.get("expiration", ""),
                },
            })

        # 매크로 컨텍스트 요약도 추가
        macro_ctx = self.to_macro_context(all_data)
        if macro_ctx:
            articles.append({
                "headline": "[Kalshi Macro] 매크로 컨텍스트 요약",
                "content": macro_ctx.get("summary", ""),
                "url": "https://kalshi.com",
                "published_at": datetime.now(tz=timezone.utc),
                "source": self.source_key,
                "language": "en",
                "metadata": {
                    "data_type": "macro_context",
                    "platform": "kalshi",
                    **macro_ctx,
                },
            })

        logger.info("[%s] Kalshi 시장 %d건 수집", self.name, len(articles))
        return articles

    async def fetch_all(self) -> list[dict[str, Any]]:
        """모든 추적 시리즈의 활성 시장 데이터를 수집한다.

        Returns:
            각 시장의 확률, 거래량, 상태 등을 포함하는 목록.
        """
        session = await self.get_session()
        all_markets: list[dict[str, Any]] = []

        for series_ticker, series_name in TRACKING_SERIES.items():
            try:
                url = f"{_KALSHI_API_BASE}/markets"
                params = {
                    "series_ticker": series_ticker,
                    "status": "open",
                    "limit": 10,
                }

                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.debug(
                            "[%s] Kalshi API HTTP %d (series=%s)",
                            self.name, resp.status, series_ticker,
                        )
                        continue

                    data = await resp.json()

                markets = data.get("markets", [])
                if not markets:
                    logger.debug(
                        "[%s] 시리즈 '%s'에 활성 시장 없음",
                        self.name, series_ticker,
                    )
                    continue

                for market in markets:
                    ticker = market.get("ticker", "")
                    title = market.get("title", market.get("subtitle", ""))
                    yes_price = market.get("yes_ask", 0) or market.get(
                        "last_price", 0
                    )

                    # 확률은 센트 단위 (0-100 -> 0.0-1.0)
                    if isinstance(yes_price, (int, float)) and yes_price > 1:
                        yes_probability = yes_price / 100.0
                    else:
                        yes_probability = float(yes_price) if yes_price else 0.0

                    volume = market.get("volume", 0)
                    open_interest = market.get("open_interest", 0)
                    status = market.get("status", "")
                    expiration = market.get(
                        "expiration_time",
                        market.get("close_time", ""),
                    )

                    all_markets.append({
                        "series_ticker": series_ticker,
                        "series_name": series_name,
                        "ticker": ticker,
                        "title": title,
                        "yes_probability": yes_probability,
                        "volume": volume,
                        "open_interest": open_interest,
                        "status": status,
                        "expiration": expiration,
                    })

            except Exception as e:
                logger.warning(
                    "[%s] 시리즈 '%s' 조회 실패: %s",
                    self.name, series_ticker, e,
                )
                continue

        logger.info(
            "[%s] 총 %d개 시장 데이터 수집 완료",
            self.name, len(all_markets),
        )
        return all_markets

    @staticmethod
    def to_macro_context(markets: list[dict[str, Any]]) -> dict[str, Any]:
        """수집된 시장 데이터를 AI용 매크로 컨텍스트로 변환한다.

        Fed 금리 인하 확률, CPI 방향성, GDP 전망, 고용 전망을
        요약하여 Claude 프롬프트에 주입할 수 있는 형태로 반환한다.

        Args:
            markets: fetch_all()의 반환값.

        Returns:
            매크로 컨텍스트 딕셔너리 (fed_rate_cut_probability, cpi_direction 등).
        """
        context: dict[str, Any] = {
            "fed_rate_cut_probability": None,
            "cpi_direction": None,
            "gdp_outlook": None,
            "employment_outlook": None,
            "summary": "",
        }

        summary_parts: list[str] = []

        # Fed 금리 관련 시장 분석
        fed_markets = [
            m for m in markets if m.get("series_ticker") == "KXFED"
        ]
        if fed_markets:
            # 금리 인하 관련 시장의 Yes 확률 평균
            cut_probs = [
                m["yes_probability"]
                for m in fed_markets
                if "cut" in m.get("title", "").lower()
                or "lower" in m.get("title", "").lower()
                or "decrease" in m.get("title", "").lower()
            ]
            if cut_probs:
                avg_cut = sum(cut_probs) / len(cut_probs)
                context["fed_rate_cut_probability"] = round(avg_cut, 3)
                summary_parts.append(
                    f"Fed 금리 인하 확률: {avg_cut:.1%}"
                )
            else:
                # 금리 인하 명시 없으면 가장 활성화된 시장 확률 사용
                top_fed = max(
                    fed_markets, key=lambda m: m.get("volume", 0)
                )
                context["fed_rate_cut_probability"] = round(
                    top_fed["yes_probability"], 3
                )
                summary_parts.append(
                    f"Fed 주요 시장 ({top_fed['title']}): "
                    f"Yes {top_fed['yes_probability']:.1%}"
                )

        # CPI 방향 분석
        cpi_markets = [
            m for m in markets if m.get("series_ticker") == "KXCPI"
        ]
        if cpi_markets:
            top_cpi = max(cpi_markets, key=lambda m: m.get("volume", 0))
            context["cpi_direction"] = {
                "market": top_cpi["title"],
                "probability": round(top_cpi["yes_probability"], 3),
            }
            summary_parts.append(
                f"CPI ({top_cpi['title']}): "
                f"Yes {top_cpi['yes_probability']:.1%}"
            )

        # GDP 전망
        gdp_markets = [
            m for m in markets if m.get("series_ticker") == "KXGDP"
        ]
        if gdp_markets:
            top_gdp = max(gdp_markets, key=lambda m: m.get("volume", 0))
            context["gdp_outlook"] = {
                "market": top_gdp["title"],
                "probability": round(top_gdp["yes_probability"], 3),
            }
            summary_parts.append(
                f"GDP ({top_gdp['title']}): "
                f"Yes {top_gdp['yes_probability']:.1%}"
            )

        # 고용 전망
        nfp_markets = [
            m for m in markets if m.get("series_ticker") == "KXNFP"
        ]
        if nfp_markets:
            top_nfp = max(nfp_markets, key=lambda m: m.get("volume", 0))
            context["employment_outlook"] = {
                "market": top_nfp["title"],
                "probability": round(top_nfp["yes_probability"], 3),
            }
            summary_parts.append(
                f"NFP ({top_nfp['title']}): "
                f"Yes {top_nfp['yes_probability']:.1%}"
            )

        context["summary"] = " | ".join(summary_parts) if summary_parts else "매크로 데이터 없음"

        return context
