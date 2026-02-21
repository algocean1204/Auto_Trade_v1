"""
CNN Fear & Greed Index 크롤러.

CNN 내부 API를 통해 시장 공포/탐욕 지수를 수집한다.
역발상(contrarian) 매매 시그널 변환 기능을 포함한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# CNN Fear & Greed API 엔드포인트
_FEAR_GREED_API_URL = (
    "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
)

# 시그널 임계값
_EXTREME_FEAR_THRESHOLD = 25
_EXTREME_GREED_THRESHOLD = 75
_RAPID_SHIFT_THRESHOLD = 20


@dataclass
class FearGreedData:
    """CNN Fear & Greed 지수 데이터를 담는 구조체이다."""

    score: float
    rating: str  # "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
    previous_close: float
    one_week_ago: float
    one_month_ago: float
    daily_change: float
    historical: list[dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


class FearGreedCrawler(BaseCrawler):
    """CNN Fear & Greed 지수를 수집하고 트레이딩 시그널로 변환하는 크롤러.

    매일 장 시작 전 1회 실행하여 시장 심리 데이터를 확보한다.
    극단적 공포(<=25) 또는 극단적 탐욕(>=75) 시 역발상 시그널을 생성한다.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fear & Greed 지수를 수집하고 기사 형태로 반환한다."""
        fg_data = await self.fetch()
        if fg_data is None:
            return []

        signal = self.to_trading_signal(fg_data)

        headline = (
            f"[Fear & Greed] Score: {fg_data.score:.0f} - {fg_data.rating}"
        )
        content = (
            f"CNN Fear & Greed Index: {fg_data.score:.1f} ({fg_data.rating})\n"
            f"Previous Close: {fg_data.previous_close:.1f}\n"
            f"1 Week Ago: {fg_data.one_week_ago:.1f}\n"
            f"1 Month Ago: {fg_data.one_month_ago:.1f}\n"
            f"Daily Change: {fg_data.daily_change:+.1f}\n"
            f"Trading Signal: {signal.get('signal', 'NEUTRAL')}\n"
            f"Signal Reason: {signal.get('reason', 'N/A')}"
        )

        article = {
            "headline": headline,
            "content": content,
            "url": "https://edition.cnn.com/markets/fear-and-greed",
            "published_at": fg_data.timestamp,
            "source": self.source_key,
            "language": "en",
            "metadata": {
                "data_type": "fear_greed_index",
                "score": fg_data.score,
                "rating": fg_data.rating,
                "previous_close": fg_data.previous_close,
                "one_week_ago": fg_data.one_week_ago,
                "one_month_ago": fg_data.one_month_ago,
                "daily_change": fg_data.daily_change,
                "signal": signal,
            },
        }

        return [article]

    async def fetch(self) -> FearGreedData | None:
        """CNN API에서 Fear & Greed 지수 데이터를 조회한다.

        Returns:
            FearGreedData 객체 또는 실패 시 None.
        """
        session = await self.get_session()

        headers = {
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        try:
            async with session.get(
                _FEAR_GREED_API_URL, headers=headers
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "[%s] CNN API HTTP %d", self.name, resp.status
                    )
                    return None

                data = await resp.json()

        except Exception as e:
            logger.error(
                "[%s] CNN API 요청 실패: %s", self.name, e, exc_info=True
            )
            return None

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> FearGreedData | None:
        """CNN API 응답을 FearGreedData로 파싱한다."""
        try:
            fear_greed = data.get("fear_and_greed", {})
            score = float(fear_greed.get("score", 0))
            rating = str(fear_greed.get("rating", "Unknown"))
            previous_close = float(fear_greed.get("previous_close", 0))
            one_week_ago = float(
                fear_greed.get("previous_1_week", 0)
            )
            one_month_ago = float(
                fear_greed.get("previous_1_month", 0)
            )

            # 일일 변화량 계산
            daily_change = score - previous_close if previous_close else 0.0

            # 히스토리컬 데이터 (30일)
            historical: list[dict[str, Any]] = []
            fear_greed_hist = data.get("fear_and_greed_historical", {})
            hist_data = fear_greed_hist.get("data", [])
            for point in hist_data[-30:]:
                try:
                    ts = point.get("x", 0)
                    val = point.get("y", 0)
                    historical.append({
                        "timestamp": datetime.fromtimestamp(
                            ts / 1000, tz=timezone.utc
                        ).isoformat()
                        if ts > 1e9
                        else datetime.fromtimestamp(
                            ts, tz=timezone.utc
                        ).isoformat(),
                        "score": float(val),
                    })
                except (ValueError, TypeError):
                    continue

            timestamp_ms = fear_greed.get("timestamp", None)
            if timestamp_ms:
                try:
                    ts_val = float(timestamp_ms)
                    if ts_val > 1e12:
                        ts_val /= 1000
                    timestamp = datetime.fromtimestamp(ts_val, tz=timezone.utc)
                except (ValueError, TypeError):
                    timestamp = datetime.now(tz=timezone.utc)
            else:
                timestamp = datetime.now(tz=timezone.utc)

            fg_data = FearGreedData(
                score=score,
                rating=rating,
                previous_close=previous_close,
                one_week_ago=one_week_ago,
                one_month_ago=one_month_ago,
                daily_change=daily_change,
                historical=historical,
                timestamp=timestamp,
            )

            logger.info(
                "[%s] Fear & Greed 지수: %.1f (%s), 일변동: %+.1f",
                self.name, score, rating, daily_change,
            )
            return fg_data

        except Exception as e:
            logger.error(
                "[%s] 응답 파싱 실패: %s", self.name, e, exc_info=True
            )
            return None

    @staticmethod
    def to_trading_signal(fg_data: FearGreedData) -> dict[str, Any]:
        """Fear & Greed 데이터를 트레이딩 시그널로 변환한다.

        - score <= 25: CONTRARIAN_BUY (극단적 공포 = 매수 기회)
        - score >= 75: CONTRARIAN_SELL (극단적 탐욕 = 매도/관망)
        - |daily_change| >= 20: RAPID_SENTIMENT_SHIFT (급격한 심리 변화)
        - 그 외: NEUTRAL

        Args:
            fg_data: FearGreedData 객체.

        Returns:
            signal, score, reason을 포함하는 딕셔너리.
        """
        score = fg_data.score
        daily_change = fg_data.daily_change

        # 급격한 심리 변화 우선 검사
        if abs(daily_change) >= _RAPID_SHIFT_THRESHOLD:
            direction = "positive" if daily_change > 0 else "negative"
            return {
                "signal": "RAPID_SENTIMENT_SHIFT",
                "score": score,
                "rating": fg_data.rating,
                "daily_change": daily_change,
                "reason": (
                    f"Fear & Greed 지수 일일 변동 {daily_change:+.1f}p "
                    f"({direction}). 급격한 시장 심리 변화 감지."
                ),
                "severity": "high",
            }

        if score <= _EXTREME_FEAR_THRESHOLD:
            return {
                "signal": "CONTRARIAN_BUY",
                "score": score,
                "rating": fg_data.rating,
                "daily_change": daily_change,
                "reason": (
                    f"Fear & Greed 지수 {score:.0f} (극단적 공포). "
                    f"역발상 매수 시그널. "
                    f"1주 전: {fg_data.one_week_ago:.0f}, "
                    f"1개월 전: {fg_data.one_month_ago:.0f}"
                ),
                "severity": "medium",
            }

        if score >= _EXTREME_GREED_THRESHOLD:
            return {
                "signal": "CONTRARIAN_SELL",
                "score": score,
                "rating": fg_data.rating,
                "daily_change": daily_change,
                "reason": (
                    f"Fear & Greed 지수 {score:.0f} (극단적 탐욕). "
                    f"역발상 매도/관망 시그널. "
                    f"1주 전: {fg_data.one_week_ago:.0f}, "
                    f"1개월 전: {fg_data.one_month_ago:.0f}"
                ),
                "severity": "medium",
            }

        return {
            "signal": "NEUTRAL",
            "score": score,
            "rating": fg_data.rating,
            "daily_change": daily_change,
            "reason": (
                f"Fear & Greed 지수 {score:.0f} ({fg_data.rating}). "
                f"특이 시그널 없음."
            ),
            "severity": "low",
        }
