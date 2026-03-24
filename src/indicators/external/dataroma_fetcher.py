"""외부 지표 -- Dataroma 슈퍼인베스터 포트폴리오 추적기이다.

Dataroma 13F 공시 페이지에서 워렌 버핏, 체이스 콜먼, 데이비드 테퍼, 조지 소로스 등
슈퍼인베스터 포트폴리오를 스크래핑하여 반도체/기술주 보유 현황을 추적한다.
API 키 불필요 (HTML 스크래핑). 캐시 키: macro:superinvestor (TTL 7일).

추적 투자자 선정 기준:
  - 반도체/빅테크 보유 비중이 높은 13F 공시 대상 헤지펀드를 우선한다.
  - Bridgewater(Ray Dalio)는 Dataroma에 미등록이므로 제외했다.

테이블 컬럼 구조 (2026-03 기준):
  [0] History | [1] Stock | [2] % of Portfolio | [3] Recent Activity
  [4] Shares | [5] Reported Price | [6] Value | [7] (empty)
  [8] Current Price | [9] +/- Reported | [10] 52W Low | [11] 52W High
"""
from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient
    from src.common.http_client import AsyncHttpClient

logger = get_logger(__name__)

# Dataroma 13F 보유 현황 URL이다
_BASE_URL: str = "https://www.dataroma.com/m/holdings.php"

# 추적 대상 슈퍼인베스터이다 (코드, 이름, 펀드명)
# 반도체/빅테크 보유 비중이 높은 펀드를 우선 선정했다
_INVESTORS: list[dict[str, str]] = [
    {"code": "BRK", "name": "Warren Buffett", "fund": "Berkshire Hathaway"},
    {"code": "TGM", "name": "Chase Coleman", "fund": "Tiger Global Management"},
    {"code": "AM", "name": "David Tepper", "fund": "Appaloosa Management"},
    {"code": "SAM", "name": "George Soros", "fund": "Soros Fund Management"},
]

# 캐시 설정이다
_CACHE_KEY: str = "macro:superinvestor"
_CACHE_TTL: int = 86400 * 7  # 7일 — 13F 분기 공시 주기를 고려한다
_LAST_SUCCESS_KEY: str = "macro:superinvestor:last_success"
_LAST_SUCCESS_TTL: int = 86400 * 14  # 14일 폴백 유지

# 매매 대상 관련 티커이다 — 반도체 + 빅테크 + 주요 ETF
_RELEVANT_TICKERS: set[str] = {
    "NVDA", "AMD", "AVGO", "QCOM", "INTC",
    "AAPL", "MSFT", "AMZN", "GOOGL", "META",
    "SOXX", "QQQ", "SPY",
}

# 요청 설정이다
_REQUEST_TIMEOUT: float = 15.0
_MAX_RETRIES: int = 2
_RETRY_DELAY: float = 2.0
_INTER_INVESTOR_DELAY: float = 2.0  # 투자자 간 요청 지연(초)이다

# 스크래핑용 브라우저 헤더이다
_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.dataroma.com/m/home.php",
}

# 회사명 + 티커 추출이다 — <a href="...stock.php?sym=AAPL">...</a>
_COMPANY_LINK_PATTERN = re.compile(
    r'<a[^>]*href="[^"]*stock\.php\?sym=([A-Z]+)"[^>]*>\s*(.*?)\s*</a>',
    re.DOTALL,
)

# 활동(Activity) 추출이다 — Buy, Sell, Add, Reduce, New 등
_ACTIVITY_PATTERN = re.compile(
    r'(Buy|Sell|Add|Reduce|New|Unchanged)',
    re.IGNORECASE,
)

# 숫자 정리 — 쉼표, 공백, $, % 제거이다
_CLEAN_NUMBER = re.compile(r'[,\s$%]')

# 전체 보유 테이블을 감싸는 패턴이다
_HOLDINGS_TABLE_PATTERN = re.compile(
    r'<table[^>]*id="grid"[^>]*>(.*?)</table>',
    re.DOTALL,
)


def _clean_text(text: str) -> str:
    """HTML 태그를 제거하고 공백을 정리한다."""
    cleaned = re.sub(r'<[^>]+>', '', text)
    return cleaned.strip()


def _parse_number(text: str) -> float:
    """숫자 문자열을 float로 변환한다. 실패 시 0.0을 반환한다."""
    cleaned = _CLEAN_NUMBER.sub('', _clean_text(text))
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _parse_holdings_html(html: str) -> list[dict[str, Any]]:
    """Dataroma 보유 현황 HTML에서 13F 테이블을 파싱한다.

    실제 테이블 컬럼 (12개):
      [0] History | [1] Stock | [2] % of Portfolio | [3] Recent Activity
      [4] Shares  | [5] Reported Price | [6] Value | [7] (empty)
      [8] Current Price | [9] +/- Reported | [10] 52W Low | [11] 52W High
    """
    holdings: list[dict[str, Any]] = []

    # grid 테이블을 찾는다
    table_match = _HOLDINGS_TABLE_PATTERN.search(html)
    if not table_match:
        logger.debug("Dataroma 보유 테이블(grid)을 찾지 못했다")
        return holdings

    table_html = table_match.group(1)

    # 모든 <tr>을 추출한다
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)

    for row in rows:
        # td 셀들을 추출한다
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) < 7:
            # 헤더 행이거나 불완전한 행은 건너뛴다
            continue

        # Cell[1]에서 티커와 회사명을 추출한다
        link_match = _COMPANY_LINK_PATTERN.search(cells[1])
        if not link_match:
            # Cell[0]에서도 시도 — 테이블 구조 변경 대비
            link_match = _COMPANY_LINK_PATTERN.search(cells[0])
            if not link_match:
                continue

        ticker = link_match.group(1).upper()
        company = _clean_text(link_match.group(2))
        # 회사명에서 "TICKER - " 접두사를 정리한다 (예: "AAPL - Apple Inc." → "Apple Inc.")
        prefix = f"{ticker} - "
        if company.startswith(prefix):
            company = company[len(prefix):]
        elif company.startswith("- "):
            company = company[2:]

        # Cell[2]: 포트폴리오 비중(%)
        portfolio_pct = _parse_number(cells[2])

        # Cell[3]: 최근 활동 (Buy, Sell, Reduce X%, Add X%, New)
        activity_text = _clean_text(cells[3])
        activity_match = _ACTIVITY_PATTERN.search(activity_text)
        activity = activity_match.group(1).capitalize() if activity_match else "Unchanged"

        # Cell[4]: 보유 주식 수
        shares = int(_parse_number(cells[4]))

        # Cell[5]: 보고 가격
        reported_price = _parse_number(cells[5])

        # Cell[6]: 보유 가치 (달러 문자열)
        value_text = _clean_text(cells[6])

        holdings.append({
            "ticker": ticker,
            "company": company,
            "portfolio_pct": portfolio_pct,
            "activity": activity,
            "shares": shares,
            "reported_price": reported_price,
            "value": value_text,
        })

    return holdings


class DataromaFetcher:
    """Dataroma 슈퍼인베스터 포트폴리오 추적기이다.

    Dataroma 웹사이트에서 13F 공시 보유 현황을 스크래핑한다.
    버핏, 체이스 콜먼(Tiger Global), 데이비드 테퍼(Appaloosa), 소로스를 추적한다.
    실패 시 마지막 성공 캐시를 폴백으로 사용한다.
    """

    def __init__(self, cache: CacheClient, http: AsyncHttpClient) -> None:
        """의존성을 주입받는다."""
        self._cache = cache
        self._http = http

    async def fetch(self) -> dict[str, Any]:
        """슈퍼인베스터 포트폴리오 데이터를 수집하여 캐시에 저장한다.

        Returns:
            투자자별 보유 현황 딕셔너리. 실패 시 폴백 캐시 또는 빈 딕셔너리.
            구조: {"investors": [...], "summary": {...}}
        """
        cached = await self._read_cache(_CACHE_KEY)
        if cached is not None:
            n_investors = len(cached.get("investors", []))
            logger.debug("Dataroma 캐시 히트: %d명 투자자", n_investors)
            return cached

        result = await self._fetch_all_investors()
        if result.get("investors"):
            await self._write_cache(result)
            n = len(result["investors"])
            logger.info("Dataroma 수집 완료: %d명 투자자", n)
            return result

        # 폴백: 마지막 성공 캐시
        fallback = await self._read_cache(_LAST_SUCCESS_KEY)
        if fallback:
            n = len(fallback.get("investors", []))
            logger.warning("Dataroma 스크래핑 실패 — 폴백 캐시 사용 (%d명)", n)
            return fallback

        logger.warning("Dataroma 수집 실패 — 데이터 없음")
        return {"investors": [], "summary": {}}

    async def get_relevant_holdings(self) -> dict[str, Any]:
        """매매 관련 티커만 필터링하여 반환한다.

        _RELEVANT_TICKERS에 속하는 종목만 각 투자자 보유 목록에서 추출한다.

        Returns:
            관련 종목 보유 현황. ticker_summary에 종목별 보유 투자자 수를 집계한다.
        """
        data = await self.fetch()
        investors = data.get("investors", [])
        if not investors:
            return {"investors": [], "ticker_summary": {}}

        filtered_investors: list[dict[str, Any]] = []
        # 종목별 보유 투자자를 집계한다
        ticker_holders: dict[str, list[dict[str, Any]]] = {}

        for investor in investors:
            relevant = [
                h for h in investor.get("holdings", [])
                if h.get("ticker") in _RELEVANT_TICKERS
            ]
            if relevant:
                filtered_investors.append({
                    "name": investor["name"],
                    "fund": investor["fund"],
                    "total_holdings": investor.get("total_holdings", 0),
                    "relevant_holdings": relevant,
                })
                for h in relevant:
                    t = h["ticker"]
                    if t not in ticker_holders:
                        ticker_holders[t] = []
                    ticker_holders[t].append({
                        "investor": investor["name"],
                        "portfolio_pct": h.get("portfolio_pct", 0),
                        "activity": h.get("activity", "Unknown"),
                    })

        # 보유 투자자 수 기준 내림차순 정렬
        ticker_summary = {
            ticker: {
                "holder_count": len(holders),
                "holders": holders,
            }
            for ticker, holders in sorted(
                ticker_holders.items(),
                key=lambda x: len(x[1]),
                reverse=True,
            )
        }

        return {
            "investors": filtered_investors,
            "ticker_summary": ticker_summary,
        }

    async def _fetch_all_investors(self) -> dict[str, Any]:
        """모든 추적 대상 투자자의 보유 현황을 수집한다."""
        investors_data: list[dict[str, Any]] = []

        for i, investor in enumerate(_INVESTORS):
            holdings = await self._fetch_investor(investor["code"])
            if holdings is not None:
                investors_data.append({
                    "name": investor["name"],
                    "fund": investor["fund"],
                    "code": investor["code"],
                    "total_holdings": len(holdings),
                    "holdings": holdings,
                })

            # 투자자 간 요청 지연 — rate limit 방지
            if i < len(_INVESTORS) - 1:
                await asyncio.sleep(_INTER_INVESTOR_DELAY)

        # 요약 정보 생성
        summary = _build_summary(investors_data)

        return {
            "investors": investors_data,
            "summary": summary,
        }

    async def _fetch_investor(self, code: str) -> list[dict[str, Any]] | None:
        """개별 투자자의 보유 현황을 스크래핑한다. 실패 시 None."""
        params = {"m": code}

        for attempt in range(_MAX_RETRIES):
            try:
                resp = await asyncio.wait_for(
                    self._http.get(
                        _BASE_URL, headers=_HEADERS, params=params,
                    ),
                    timeout=_REQUEST_TIMEOUT,
                )

                if resp.status == 403:
                    logger.warning(
                        "Dataroma 접근 차단 (403): code=%s — 건너뜀", code,
                    )
                    return None

                if resp.status == 429:
                    delay = _RETRY_DELAY * (attempt + 1)
                    logger.warning(
                        "Dataroma rate limit: code=%s — %.0fs 대기", code, delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                if not resp.ok:
                    logger.debug(
                        "Dataroma 응답 실패: code=%s status=%d", code, resp.status,
                    )
                    continue

                holdings = _parse_holdings_html(resp.body)
                if holdings:
                    logger.debug(
                        "Dataroma 파싱 성공: code=%s holdings=%d건",
                        code, len(holdings),
                    )
                    return holdings

                logger.warning(
                    "Dataroma 파싱 결과 0건: code=%s — HTML 구조 변경 가능성",
                    code,
                )
                return None

            except asyncio.TimeoutError:
                logger.debug(
                    "Dataroma 타임아웃: code=%s (시도 %d/%d)",
                    code, attempt + 1, _MAX_RETRIES,
                )
            except Exception as exc:
                logger.debug(
                    "Dataroma 스크래핑 실패: code=%s error=%s", code, exc,
                )
                return None

        return None

    async def _read_cache(self, key: str) -> dict[str, Any] | None:
        """캐시에서 데이터를 읽는다."""
        try:
            cached = await self._cache.read_json(key)
            if cached and isinstance(cached, dict):
                return cached
        except Exception as exc:
            logger.debug("Dataroma 캐시 읽기 실패 (%s): %s", key, exc)
        return None

    async def _write_cache(self, data: dict[str, Any]) -> None:
        """정식 캐시 + 폴백 캐시에 저장한다."""
        try:
            await self._cache.write_json(_CACHE_KEY, data, ttl=_CACHE_TTL)
            await self._cache.write_json(
                _LAST_SUCCESS_KEY, data, ttl=_LAST_SUCCESS_TTL,
            )
        except Exception as exc:
            logger.debug("Dataroma 캐시 저장 실패: %s", exc)


def _build_summary(investors: list[dict[str, Any]]) -> dict[str, Any]:
    """투자자 데이터에서 관련 티커 요약을 생성한다."""
    relevant_map: dict[str, list[str]] = {}
    for inv in investors:
        for h in inv.get("holdings", []):
            ticker = h.get("ticker", "")
            if ticker in _RELEVANT_TICKERS:
                if ticker not in relevant_map:
                    relevant_map[ticker] = []
                relevant_map[ticker].append(inv["name"])

    return {
        "total_investors": len(investors),
        "relevant_tickers_found": dict(relevant_map),
        "tracked_tickers": sorted(_RELEVANT_TICKERS),
    }
