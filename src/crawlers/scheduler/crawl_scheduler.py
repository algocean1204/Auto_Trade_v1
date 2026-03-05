"""F1 데이터 수집 -- KST 시각 기반 크롤링 스케줄러이다.

야간/주간 모드를 판별하고, 소스별 크롤링 주기를 계산한다.
fast mode에서는 우선순위 높은 8개 소스만 짧은 타임아웃으로 동작한다.
"""
from __future__ import annotations

from src.common.logger import get_logger
from src.common.market_clock import MarketClock, TimeInfo
from src.crawlers.models import CrawlSchedule, SourceConfig

logger = get_logger(__name__)

# fast mode에서 사용할 최대 소스 수와 타임아웃이다
_FAST_MODE_MAX_SOURCES: int = 8
_FAST_MODE_TIMEOUT: int = 5

# 세션별 크롤링 간격(초)이다
_NIGHT_INTERVALS: dict[str, int] = {
    "rss": 300,       # 5분
    "api": 180,       # 3분
    "scraping": 600,  # 10분
    "social": 300,    # 5분
    "prediction": 900,  # 15분
}

_DAY_INTERVALS: dict[str, int] = {
    "rss": 1800,       # 30분
    "api": 900,        # 15분
    "scraping": 3600,  # 60분
    "social": 1800,    # 30분
    "prediction": 3600,  # 60분
}

# 전체 소스 정의이다 (30개)
_ALL_SOURCES: list[SourceConfig] = [
    # RSS 소스 (15개)
    SourceConfig(name="reuters", url="https://www.reutersagency.com/feed/", source_type="rss", priority=1),
    SourceConfig(name="bloomberg_rss", url="https://feeds.bloomberg.com/markets/news.rss", source_type="rss", priority=1),
    SourceConfig(name="yahoo_finance", url="https://finance.yahoo.com/news/rssindex", source_type="rss", priority=2),
    SourceConfig(name="cnbc", url="https://www.cnbc.com/id/100003114/device/rss/rss.html", source_type="rss", priority=2),
    SourceConfig(name="marketwatch", url="https://feeds.marketwatch.com/marketwatch/topstories/", source_type="rss", priority=2),
    SourceConfig(name="wsj_rss", url="https://feeds.a.dj.com/rss/RSSMarketsMain.xml", source_type="rss", priority=2),
    SourceConfig(name="ft", url="https://www.ft.com/?format=rss", source_type="rss", priority=3),
    SourceConfig(name="fed_announcements", url="https://www.federalreserve.gov/feeds/press_all.xml", source_type="rss", priority=1),
    SourceConfig(name="ecb_press", url="https://www.ecb.europa.eu/rss/press.html", source_type="rss", priority=3),
    SourceConfig(name="bbc_business", url="https://feeds.bbci.co.uk/news/business/rss.xml", source_type="rss", priority=4),
    SourceConfig(name="nikkei_asia", url="https://asia.nikkei.com/rss", source_type="rss", priority=4),
    SourceConfig(name="scmp", url="https://www.scmp.com/rss/91/feed", source_type="rss", priority=5),
    SourceConfig(name="yonhap_en", url="https://en.yna.co.kr/RSS/news.xml", source_type="rss", priority=5),
    SourceConfig(name="hankyung", url="https://www.hankyung.com/feed/all-news", source_type="rss", priority=5),
    SourceConfig(name="mk", url="https://www.mk.co.kr/rss/30000001/", source_type="rss", priority=5),
    # API 소스 (7개)
    SourceConfig(name="finnhub", url="https://finnhub.io/api/v1/news", source_type="api", priority=1),
    SourceConfig(name="alphavantage", url="https://www.alphavantage.co/query", source_type="api", priority=2),
    SourceConfig(name="fred", url="https://api.stlouisfed.org/fred/series/observations", source_type="api", priority=2),
    SourceConfig(name="feargreed", url="https://production.dataviz.cnn.io/index/fearandgreed/graphdata", source_type="api", priority=3),
    SourceConfig(name="finviz", url="https://finviz.com/api/news_all.ashx", source_type="api", priority=3),
    SourceConfig(name="stocktwits", url="https://api.stocktwits.com/api/2/streams/trending.json", source_type="api", priority=4),
    SourceConfig(name="dart", url="https://opendart.fss.or.kr/api/list.json", source_type="api", priority=5),
    # Scraping 소스 (8개) -- 기본 비활성
    SourceConfig(name="investing_com", url="https://www.investing.com/news/stock-market-news", source_type="scraping", priority=6, enabled=False),
    SourceConfig(name="seekingalpha", url="https://seekingalpha.com/market-news", source_type="scraping", priority=6, enabled=False),
    SourceConfig(name="zerohedge", url="https://www.zerohedge.com", source_type="scraping", priority=7, enabled=False),
    SourceConfig(name="tradingview", url="https://www.tradingview.com/news/", source_type="scraping", priority=7, enabled=False),
    SourceConfig(name="benzinga", url="https://www.benzinga.com/news", source_type="scraping", priority=6, enabled=False),
    SourceConfig(name="theblock", url="https://www.theblock.co/latest", source_type="scraping", priority=8, enabled=False),
    SourceConfig(name="cointelegraph", url="https://cointelegraph.com/rss", source_type="scraping", priority=8, enabled=False),
    SourceConfig(name="nasdaq_news", url="https://www.nasdaq.com/news-and-insights", source_type="scraping", priority=6, enabled=False),
]


def _is_night_mode(time_info: TimeInfo) -> bool:
    """야간 모드(20:00~06:30 KST) 여부를 판별한다."""
    return time_info.is_trading_window


def _filter_enabled(sources: list[SourceConfig]) -> list[SourceConfig]:
    """활성화된 소스만 필터링한다."""
    return [s for s in sources if s.enabled]


def _apply_fast_mode(sources: list[SourceConfig]) -> list[SourceConfig]:
    """fast mode: 우선순위 상위 8개 소스만 선택하고 타임아웃을 5초로 설정한다."""
    sorted_sources = sorted(sources, key=lambda s: s.priority)
    top_sources = sorted_sources[:_FAST_MODE_MAX_SOURCES]
    return [s.model_copy(update={"timeout": _FAST_MODE_TIMEOUT}) for s in top_sources]


class CrawlScheduler:
    """KST 시각 기반 크롤링 스케줄러이다.

    MarketClock의 TimeInfo를 받아 야간/주간 모드를 판별하고,
    활성 소스 목록과 크롤링 주기를 담은 CrawlSchedule을 반환한다.
    """

    def __init__(self, market_clock: MarketClock) -> None:
        """스케줄러를 초기화한다."""
        self._clock = market_clock

    def build_schedule(self, fast_mode: bool = False) -> CrawlSchedule:
        """현재 시각 기반으로 크롤링 스케줄을 생성한다."""
        time_info = self._clock.get_time_info()
        is_night = _is_night_mode(time_info)
        intervals = _NIGHT_INTERVALS if is_night else _DAY_INTERVALS

        sources = _filter_enabled(_ALL_SOURCES)
        if fast_mode:
            sources = _apply_fast_mode(sources)

        logger.info(
            "스케줄 생성: session=%s, night=%s, fast=%s, sources=%d",
            time_info.session_type, is_night, fast_mode, len(sources),
        )

        return CrawlSchedule(
            session_type=time_info.session_type,
            active_sources=sources,
            intervals=intervals,
            is_fast_mode=fast_mode,
        )
