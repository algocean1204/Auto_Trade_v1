"""
네이버 금융 해외증시 뉴스 크롤러.

네이버 금융에서 해외증시 뉴스와 실시간 속보를 스크래핑하여
한국어 해외 시장 뉴스를 수집한다. BeautifulSoup으로 HTML을 파싱하며,
브라우저 수준의 User-Agent 헤더를 사용한다.

차단 방지를 위해 요청 간 최소 2초 간격과 지수 백오프를 적용한다.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.robotparser import RobotFileParser

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 네이버 금융 해외증시 뉴스 URL
_NAVER_OVERSEAS_URL = (
    "https://finance.naver.com/news/news_list.naver"
    "?mode=LSS3D&section_id=101&section_id2=258&section_id3=402"
)

# 네이버 금융 실시간 속보 URL
_NAVER_REALTIME_URL = (
    "https://finance.naver.com/news/news_list.naver?mode=RANK"
)

# 네이버 금융 뉴스 기사 상세 URL 베이스
_NAVER_ARTICLE_BASE = "https://finance.naver.com"

# macOS Safari User-Agent 문자열
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.2 Safari/605.1.15"
)

# 요청 헤더
_REQUEST_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://finance.naver.com/",
    "Connection": "keep-alive",
}

# 요청 간 최소 간격 (초)
_MIN_REQUEST_INTERVAL = 2.0

# 연속 차단 임계치: 이 횟수 이상 연속 차단 시 장기 대기
_CONSECUTIVE_BLOCK_THRESHOLD = 5

# 장기 대기 시간 (초): 연속 차단 시 30분 대기
_LONG_PAUSE_SECONDS = 30 * 60

# 최대 수집 기사 수 (페이지당)
_MAX_ARTICLES_PER_PAGE = 30

# 유효한 기사 텍스트로 인정하는 최소 글자 수 (미만이면 네비게이션으로 간주)
_MIN_ARTICLE_TEXT_LENGTH: int = 10

# KST 오프셋 (UTC+9)
_KST = timezone(timedelta(hours=9))


class NaverFinanceCrawler(BaseCrawler):
    """네이버 금융 해외증시 뉴스를 수집하는 크롤러.

    해외증시 메인 뉴스와 실시간 속보 두 페이지를 순차적으로
    스크래핑한다. URL 기반 중복 제거, 지수 백오프, robots.txt
    준수 기능을 내장한다.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)
        self._seen_urls: set[str] = set()
        self._consecutive_blocks: int = 0
        self._last_request_time: float = 0.0
        self._robots_checked: bool = False
        self._robots_allowed: bool = True

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """네이버 금융에서 해외증시 뉴스를 수집하여 반환한다.

        해외증시 메인과 실시간 속보 두 페이지를 순차적으로 크롤링한다.
        robots.txt를 먼저 확인하고, 차단 감지 시 지수 백오프를 적용한다.

        Args:
            since: 이 시점 이후의 뉴스만 수집. None이면 최근 24시간.

        Returns:
            표준 기사 딕셔너리 목록.
        """
        if since is None:
            since = datetime.now(tz=timezone.utc) - timedelta(hours=24)

        # robots.txt 확인
        if not self._robots_checked:
            await self._check_robots_txt()

        if not self._robots_allowed:
            logger.warning("[%s] robots.txt에 의해 크롤링 차단됨", self.name)
            return []

        # 연속 차단 상태 확인
        if self._consecutive_blocks >= _CONSECUTIVE_BLOCK_THRESHOLD:
            logger.warning(
                "[%s] 연속 %d회 차단 감지, %d분 대기 중",
                self.name, self._consecutive_blocks,
                _LONG_PAUSE_SECONDS // 60,
            )
            await asyncio.sleep(_LONG_PAUSE_SECONDS)
            self._consecutive_blocks = 0

        articles: list[dict[str, Any]] = []

        # 1. 해외증시 메인 뉴스
        overseas_articles = await self._scrape_page(
            _NAVER_OVERSEAS_URL, "overseas", since
        )
        articles.extend(overseas_articles)

        # 2. 실시간 속보
        realtime_articles = await self._scrape_page(
            _NAVER_REALTIME_URL, "realtime", since
        )
        articles.extend(realtime_articles)

        logger.info(
            "[%s] 총 %d건 수집 (해외증시: %d, 속보: %d)",
            self.name, len(articles),
            len(overseas_articles), len(realtime_articles),
        )

        return articles

    async def _check_robots_txt(self) -> None:
        """finance.naver.com의 robots.txt를 확인한다.

        크롤링이 허용되는지 여부를 판별하여 _robots_allowed에 저장한다.
        확인 실패 시 보수적으로 허용한다.
        """
        self._robots_checked = True
        robots_url = "https://finance.naver.com/robots.txt"

        try:
            session = await self.get_session()
            async with session.get(
                robots_url,
                headers={"User-Agent": _USER_AGENT},
                timeout=asyncio.timeout(10),
            ) as resp:
                if resp.status != 200:
                    logger.debug(
                        "[%s] robots.txt 응답 %d, 크롤링 허용으로 간주",
                        self.name, resp.status,
                    )
                    self._robots_allowed = True
                    return

                robots_text = await resp.text()

            rp = RobotFileParser()
            rp.parse(robots_text.splitlines())
            self._robots_allowed = rp.can_fetch(_USER_AGENT, _NAVER_OVERSEAS_URL)

            if not self._robots_allowed:
                logger.warning(
                    "[%s] robots.txt가 크롤링을 차단함", self.name
                )
            else:
                logger.debug("[%s] robots.txt 확인 완료, 크롤링 허용", self.name)

        except Exception as e:
            logger.debug(
                "[%s] robots.txt 확인 실패: %s, 크롤링 허용으로 간주",
                self.name, e,
            )
            self._robots_allowed = True

    async def _rate_limit(self) -> None:
        """요청 간 최소 간격을 적용한다.

        마지막 요청 이후 _MIN_REQUEST_INTERVAL 초 미만이면
        남은 시간만큼 대기한다.
        """
        import time

        now = time.monotonic()
        elapsed = now - self._last_request_time

        if elapsed < _MIN_REQUEST_INTERVAL:
            wait_time = _MIN_REQUEST_INTERVAL - elapsed
            await asyncio.sleep(wait_time)

        self._last_request_time = time.monotonic()

    async def _fetch_html(self, url: str) -> str | None:
        """URL에서 HTML을 가져온다.

        403/차단 시 지수 백오프를 적용한다. 연속 차단 횟수를 추적하여
        임계치 초과 시 장기 대기를 트리거한다.

        Args:
            url: 요청할 URL.

        Returns:
            HTML 문자열. 실패 시 None.
        """
        await self._rate_limit()

        session = await self.get_session()

        try:
            async with session.get(url, headers=_REQUEST_HEADERS) as resp:
                if resp.status == 403:
                    self._consecutive_blocks += 1
                    backoff = min(2 ** self._consecutive_blocks, 60)
                    logger.warning(
                        "[%s] HTTP 403 차단 (연속 %d회), %d초 백오프",
                        self.name, self._consecutive_blocks, backoff,
                    )
                    await asyncio.sleep(backoff)
                    return None

                if resp.status != 200:
                    logger.warning(
                        "[%s] HTTP %d 응답 (URL: %s)",
                        self.name, resp.status, url,
                    )
                    return None

                # 성공 시 연속 차단 카운터 초기화
                self._consecutive_blocks = 0
                html = await resp.text(encoding="euc-kr", errors="replace")
                return html

        except Exception as e:
            logger.error("[%s] HTTP 요청 실패 (%s): %s", self.name, url, e)
            return None

    async def _scrape_page(
        self,
        url: str,
        page_type: str,
        since: datetime,
    ) -> list[dict[str, Any]]:
        """단일 페이지를 스크래핑하여 기사 목록을 반환한다.

        Args:
            url: 스크래핑할 페이지 URL.
            page_type: 페이지 유형 ("overseas" 또는 "realtime").
            since: 이 시점 이후의 기사만 반환.

        Returns:
            기사 딕셔너리 목록.
        """
        html = await self._fetch_html(url)
        if not html:
            return []

        try:
            articles = self._parse_news_list(html, page_type, since)
            return articles
        except Exception as e:
            logger.error(
                "[%s] HTML 파싱 실패 (%s): %s",
                self.name, page_type, e, exc_info=True,
            )
            return []

    def _parse_news_list(
        self,
        html: str,
        page_type: str,
        since: datetime,
    ) -> list[dict[str, Any]]:
        """네이버 금융 뉴스 목록 HTML을 파싱한다.

        여러 CSS 셀렉터를 순서대로 시도하여 사이트 구조 변경에 대응한다.
        URL 기반 중복 제거를 수행한다.

        Args:
            html: 파싱할 HTML 문자열.
            page_type: 페이지 유형 ("overseas" 또는 "realtime").
            since: 이 시점 이후의 기사만 반환.

        Returns:
            파싱된 기사 딕셔너리 목록.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        articles: list[dict[str, Any]] = []

        # 네이버 금융 뉴스 목록 셀렉터 (우선순위 순)
        news_items = self._find_news_items(soup)

        for item in news_items[:_MAX_ARTICLES_PER_PAGE]:
            article = self._parse_single_item(item, page_type, since)
            if article:
                articles.append(article)

        logger.debug(
            "[%s] %s 페이지에서 %d건 파싱",
            self.name, page_type, len(articles),
        )

        return articles

    def _find_news_items(self, soup: Any) -> list[Any]:
        """뉴스 항목 요소를 찾는다.

        네이버 금융 뉴스 목록 페이지의 다양한 HTML 구조에 대응하기 위해
        여러 셀렉터를 순서대로 시도한다.

        Args:
            soup: BeautifulSoup 객체.

        Returns:
            뉴스 항목 Tag 목록.
        """
        # 셀렉터 목록 (네이버 금융 뉴스 리스트 구조에 맞게 순서대로 시도)
        selectors = [
            "li.newsList",                          # 뉴스 리스트 항목
            "dl",                                   # 뉴스 dl 구조
            ".type_1 li",                           # 뉴스 타입 1 리스트
            ".realtimeNewsList li",                  # 실시간 뉴스 리스트
            ".simpleNewsList li",                    # 단순 뉴스 리스트
            ".newsList li",                          # 일반 뉴스 리스트
            ".section_strategy .news_list li",       # 전략 섹션 뉴스
            "#contentarea_left .block1 li",          # 좌측 콘텐츠 블록
            ".news_area li",                         # 뉴스 영역 리스트
        ]

        for selector in selectors:
            items = soup.select(selector)
            if items:
                logger.debug(
                    "[%s] 셀렉터 '%s'로 %d개 항목 발견",
                    self.name, selector, len(items),
                )
                return items

        # 폴백: 뉴스 링크가 포함된 모든 <a> 태그
        links = soup.select("a[href*='news_read.naver'], a[href*='article_id']")
        if links:
            logger.debug(
                "[%s] 링크 셀렉터로 %d개 항목 발견",
                self.name, len(links),
            )
            return links

        logger.warning("[%s] 뉴스 항목을 찾을 수 없음", self.name)
        return []

    def _parse_single_item(
        self,
        item: Any,
        page_type: str,
        since: datetime,
    ) -> dict[str, Any] | None:
        """단일 뉴스 항목을 파싱하여 기사 딕셔너리로 변환한다.

        제목, URL, 언론사, 발행 시각을 추출하고 표준 형식으로 반환한다.

        Args:
            item: BeautifulSoup Tag 객체.
            page_type: 페이지 유형.
            since: 이 시점 이전의 기사는 None 반환.

        Returns:
            기사 딕셔너리. 유효하지 않거나 중복이면 None.
        """
        from bs4 import Tag

        if not isinstance(item, Tag):
            return None

        # 제목과 URL 추출
        title, article_url = self._extract_title_and_url(item)
        if not title:
            return None

        # URL 중복 확인
        if article_url in self._seen_urls:
            return None
        if article_url:
            self._seen_urls.add(article_url)

        # 언론사 추출
        publisher = self._extract_publisher(item)

        # 발행 시각 추출
        published_at = self._extract_published_at(item)

        # since 필터
        if published_at < since:
            return None

        # 요약 (제목 최대 200자)
        summary = title[:200]

        return {
            "headline": f"[Naver] {title}",
            "content": summary,
            "url": article_url,
            "published_at": published_at,
            "source": self.source_key,
            "language": "ko",
            "metadata": {
                "data_type": "news",
                "platform": "naver_finance",
                "page_type": page_type,
                "publisher": publisher,
            },
        }

    def _extract_title_and_url(self, item: Any) -> tuple[str, str]:
        """뉴스 항목에서 제목과 URL을 추출한다.

        다양한 HTML 구조에 대응하여 <a> 태그, <dd>, <dt> 등에서
        제목과 링크를 추출한다.

        Args:
            item: BeautifulSoup Tag 객체.

        Returns:
            (제목, URL) 튜플. 추출 실패 시 ("", "").
        """
        title = ""
        url = ""

        # <a> 태그에서 직접 추출
        link_tag = item.select_one(
            "a[href*='news_read.naver'], "
            "a[href*='article_id'], "
            "a[href*='/news/']"
        )
        if not link_tag:
            # item 자체가 <a> 태그일 수 있음
            if item.name == "a" and item.get("href"):
                link_tag = item

        if not link_tag:
            # dt/dd 구조에서 찾기
            dt_tag = item.select_one("dt a, dd a")
            if dt_tag:
                link_tag = dt_tag

        if link_tag:
            title = link_tag.get_text(strip=True)
            href = link_tag.get("href", "")
            if href:
                if href.startswith("http"):
                    url = href
                elif href.startswith("/"):
                    url = f"{_NAVER_ARTICLE_BASE}{href}"
                else:
                    url = href

        # 제목이 비어있으면 텍스트 전체에서 추출
        if not title:
            text = item.get_text(strip=True)
            # _MIN_ARTICLE_TEXT_LENGTH 미만은 네비게이션으로 간주
            if len(text) >= _MIN_ARTICLE_TEXT_LENGTH:
                title = text[:200]

        return title, url

    def _extract_publisher(self, item: Any) -> str:
        """뉴스 항목에서 언론사명을 추출한다.

        Args:
            item: BeautifulSoup Tag 객체.

        Returns:
            언론사명. 추출 실패 시 빈 문자열.
        """
        # 언론사 셀렉터 시도
        publisher_selectors = [
            ".press",
            ".info_press",
            ".articleSubject span",
            ".paper",
            "span.medium",
            ".media",
        ]
        for selector in publisher_selectors:
            el = item.select_one(selector)
            if el:
                return el.get_text(strip=True)

        # <img> 태그의 alt 속성에서 언론사 추출
        img = item.select_one("img[alt]")
        if img:
            alt = img.get("alt", "").strip()
            if alt and len(alt) < 30:
                return alt

        return ""

    def _extract_published_at(self, item: Any) -> datetime:
        """뉴스 항목에서 발행 시각을 추출하여 UTC로 반환한다.

        네이버 금융의 다양한 시간 표기(상대 시간, 절대 시간)를
        파싱하고 KST에서 UTC로 변환한다.

        Args:
            item: BeautifulSoup Tag 객체.

        Returns:
            UTC datetime 객체. 파싱 실패 시 현재 시각.
        """
        now = datetime.now(tz=timezone.utc)

        # 시간 관련 요소 탐색
        time_selectors = [
            ".wdate",
            ".date",
            "span.time",
            ".articleSubject em",
            "em",
            "span.txt",
        ]

        time_text = ""
        for selector in time_selectors:
            el = item.select_one(selector)
            if el:
                text = el.get_text(strip=True)
                # 시간 패턴이 포함된 텍스트인지 확인
                if re.search(r"\d", text):
                    time_text = text
                    break

        if not time_text:
            return now

        return self._parse_korean_time(time_text)

    @staticmethod
    def _parse_korean_time(time_text: str) -> datetime:
        """한국어 시간 문자열을 UTC datetime으로 파싱한다.

        지원 형식:
        - 상대 시간: "3분 전", "1시간 전", "2일 전"
        - 절대 시간: "2026.02.18 14:30", "2026-02-18 14:30"
        - 네이버 형식: "2026.02.18 오후 02:30", "2026.02.18 오전 09:15"

        Args:
            time_text: 파싱할 시간 문자열.

        Returns:
            UTC datetime 객체. 파싱 실패 시 현재 시각.
        """
        now = datetime.now(tz=timezone.utc)
        time_text = time_text.strip()

        if not time_text:
            return now

        # 상대 시간 패턴 (한국어)
        relative_patterns = [
            (r"(\d+)\s*초\s*전", "seconds"),
            (r"(\d+)\s*분\s*전", "minutes"),
            (r"(\d+)\s*시간\s*전", "hours"),
            (r"(\d+)\s*일\s*전", "days"),
        ]
        for pattern, unit in relative_patterns:
            match = re.search(pattern, time_text)
            if match:
                value = int(match.group(1))
                return now - timedelta(**{unit: value})

        # 네이버 오전/오후 포함 형식: "2026.02.18 오후 02:30"
        ampm_match = re.search(
            r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*(오전|오후)\s*(\d{1,2}):(\d{2})",
            time_text,
        )
        if ampm_match:
            try:
                year = int(ampm_match.group(1))
                month = int(ampm_match.group(2))
                day = int(ampm_match.group(3))
                ampm = ampm_match.group(4)
                hour = int(ampm_match.group(5))
                minute = int(ampm_match.group(6))

                if ampm == "오후" and hour < 12:
                    hour += 12
                elif ampm == "오전" and hour == 12:
                    hour = 0

                kst_dt = datetime(
                    year, month, day, hour, minute, tzinfo=_KST
                )
                return kst_dt.astimezone(timezone.utc)
            except (ValueError, OverflowError):
                pass

        # 절대 시간 형식: "2026.02.18 14:30" 또는 "2026-02-18 14:30"
        abs_match = re.search(
            r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\s+(\d{1,2}):(\d{2})",
            time_text,
        )
        if abs_match:
            try:
                kst_dt = datetime(
                    int(abs_match.group(1)),
                    int(abs_match.group(2)),
                    int(abs_match.group(3)),
                    int(abs_match.group(4)),
                    int(abs_match.group(5)),
                    tzinfo=_KST,
                )
                return kst_dt.astimezone(timezone.utc)
            except (ValueError, OverflowError):
                pass

        # 날짜만 있는 형식: "2026.02.18"
        date_match = re.search(
            r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})",
            time_text,
        )
        if date_match:
            try:
                kst_dt = datetime(
                    int(date_match.group(1)),
                    int(date_match.group(2)),
                    int(date_match.group(3)),
                    tzinfo=_KST,
                )
                return kst_dt.astimezone(timezone.utc)
            except (ValueError, OverflowError):
                pass

        # "HH:MM" 형식만 있으면 오늘 날짜로 간주
        time_only_match = re.search(r"(\d{1,2}):(\d{2})", time_text)
        if time_only_match:
            try:
                now_kst = datetime.now(tz=_KST)
                kst_dt = now_kst.replace(
                    hour=int(time_only_match.group(1)),
                    minute=int(time_only_match.group(2)),
                    second=0,
                    microsecond=0,
                )
                return kst_dt.astimezone(timezone.utc)
            except (ValueError, OverflowError):
                pass

        return now

    def reset_seen_urls(self) -> None:
        """중복 추적 URL 집합을 초기화한다.

        주기적 크롤링에서 메모리 누적을 방지하기 위해 호출한다.
        """
        count = len(self._seen_urls)
        self._seen_urls.clear()
        logger.debug("[%s] seen_urls 초기화 (%d건 제거)", self.name, count)
