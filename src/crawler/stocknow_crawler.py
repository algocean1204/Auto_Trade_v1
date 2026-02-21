"""
스톡나우(StockNow) 한국어 미국 주식 뉴스 크롤러.

Playwright를 사용하여 stocknow.co.kr에서 한국어 미국 주식 뉴스를 수집한다.
헤드리스 Chromium 브라우저로 동적 페이지를 렌더링한 후 파싱한다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 스톡나우 뉴스 페이지 URL
_STOCKNOW_URL = "https://stocknow.co.kr"

# 수집할 최대 뉴스 건수
_MAX_ARTICLES = 15

# 페이지 로딩 타임아웃 (초)
_PAGE_TIMEOUT = 15000  # 밀리초

# 페이지 재시도 대기 시간 (초)
_RATE_LIMIT_SLEEP: float = 3.0


class StockNowCrawler(BaseCrawler):
    """스톡나우 한국어 미국 주식 뉴스를 수집하는 크롤러.

    Playwright 헤드리스 Chromium을 사용하여 동적 렌더링 페이지를
    크롤링한다. 최대 15개의 최신 뉴스를 수집한다.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """스톡나우에서 뉴스를 수집하여 기사 형태로 반환한다."""
        articles = await self.fetch_news(since)
        return articles

    async def fetch_news(
        self, since: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Playwright로 스톡나우 뉴스 페이지를 스크래핑한다.

        헤드리스 Chromium 브라우저를 실행하고, networkidle 상태까지 대기한 뒤
        뉴스 목록을 파싱한다.

        Args:
            since: 이 시점 이후의 뉴스만 수집. None이면 전체 수집.

        Returns:
            기사 딕셔너리 목록.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[%s] playwright 패키지 미설치", self.name)
            return []

        articles: list[dict[str, Any]] = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="ko-KR",
                )
                page = await context.new_page()

                try:
                    await page.goto(
                        _STOCKNOW_URL,
                        timeout=_PAGE_TIMEOUT,
                        wait_until="networkidle",
                    )
                except Exception as e:
                    logger.warning(
                        "[%s] 페이지 로딩 타임아웃, domcontentloaded로 재시도: %s",
                        self.name, e,
                    )
                    try:
                        await page.goto(
                            _STOCKNOW_URL,
                            timeout=_PAGE_TIMEOUT,
                            wait_until="domcontentloaded",
                        )
                        await asyncio.sleep(_RATE_LIMIT_SLEEP)
                    except Exception as e2:
                        logger.error(
                            "[%s] 페이지 로딩 실패: %s", self.name, e2
                        )
                        await browser.close()
                        return []

                # 뉴스 항목 추출 - 다양한 셀렉터 시도
                news_items = await self._extract_news_items(page)

                for item in news_items[:_MAX_ARTICLES]:
                    title = item.get("title", "").strip()
                    if not title:
                        continue

                    url = item.get("url", "")
                    if url and not url.startswith("http"):
                        url = f"{_STOCKNOW_URL}{url}"

                    published_at = self._parse_time(
                        item.get("time_text", "")
                    )

                    if since and published_at < since:
                        continue

                    articles.append({
                        "headline": f"[StockNow] {title}",
                        "content": item.get("summary", title),
                        "url": url,
                        "published_at": published_at,
                        "source": self.source_key,
                        "language": "ko",
                        "metadata": {
                            "data_type": "news",
                            "platform": "stocknow",
                            "category": item.get("category", ""),
                            "time_text": item.get("time_text", ""),
                        },
                    })

                await browser.close()

        except Exception as e:
            logger.error(
                "[%s] 스크래핑 실패: %s", self.name, e, exc_info=True
            )
            return []

        logger.info("[%s] 스톡나우 뉴스 %d건 수집", self.name, len(articles))
        return articles

    async def _extract_news_items(self, page: Any) -> list[dict[str, Any]]:
        """페이지에서 뉴스 항목을 추출한다.

        여러 셀렉터를 순서대로 시도하여 사이트 구조 변경에 대응한다.
        """
        items: list[dict[str, Any]] = []

        # 셀렉터 목록 (우선순위 순)
        selectors = [
            "article",
            ".news-item",
            ".post-item",
            "[class*='news']",
            "[class*='article']",
            "[class*='post']",
            "a[href*='/news/']",
            "a[href*='/article/']",
        ]

        for selector in selectors:
            try:
                elements = await page.query_selector_all(selector)
                if not elements:
                    continue

                for el in elements:
                    item = await self._parse_news_element(el, page)
                    if item and item.get("title"):
                        items.append(item)

                if items:
                    logger.debug(
                        "[%s] 셀렉터 '%s'로 %d건 추출",
                        self.name, selector, len(items),
                    )
                    break

            except Exception as e:
                logger.debug(
                    "[%s] 셀렉터 '%s' 실패: %s",
                    self.name, selector, e,
                )
                continue

        # 셀렉터로 못 찾으면 전체 텍스트에서 링크 추출
        if not items:
            items = await self._fallback_extract(page)

        return items

    async def _parse_news_element(
        self, element: Any, page: Any
    ) -> dict[str, Any]:
        """단일 뉴스 요소를 파싱한다."""
        item: dict[str, Any] = {}

        try:
            # 제목 추출
            title_el = await element.query_selector(
                "h1, h2, h3, h4, .title, [class*='title']"
            )
            if title_el:
                item["title"] = await title_el.inner_text()
            else:
                text = await element.inner_text()
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                if lines:
                    item["title"] = lines[0][:200]

            # URL 추출
            link_el = await element.query_selector("a[href]")
            if link_el:
                item["url"] = await link_el.get_attribute("href") or ""
            else:
                href = await element.get_attribute("href")
                if href:
                    item["url"] = href

            # 시간 텍스트 추출
            time_el = await element.query_selector(
                "time, .date, .time, [class*='time'], [class*='date']"
            )
            if time_el:
                item["time_text"] = await time_el.inner_text()
                datetime_attr = await time_el.get_attribute("datetime")
                if datetime_attr:
                    item["time_text"] = datetime_attr

            # 요약 추출
            summary_el = await element.query_selector(
                ".summary, .description, .excerpt, p"
            )
            if summary_el:
                item["summary"] = await summary_el.inner_text()

            # 카테고리 추출
            cat_el = await element.query_selector(
                ".category, .tag, [class*='category'], [class*='tag']"
            )
            if cat_el:
                item["category"] = await cat_el.inner_text()

        except Exception as e:
            logger.debug("[%s] 뉴스 요소 파싱 오류: %s", self.name, e)

        return item

    async def _fallback_extract(self, page: Any) -> list[dict[str, Any]]:
        """셀렉터 기반 추출이 실패했을 때 대안으로 링크를 추출한다."""
        items: list[dict[str, Any]] = []
        try:
            links = await page.query_selector_all("a[href]")
            seen_titles: set[str] = set()

            for link in links:
                try:
                    text = (await link.inner_text()).strip()
                    href = await link.get_attribute("href") or ""

                    # 뉴스 같은 링크만 필터 (최소 10자 이상 텍스트)
                    if len(text) < 10 or text in seen_titles:
                        continue

                    # 네비게이션 링크 제외
                    nav_keywords = [
                        "로그인", "회원가입", "홈", "메뉴",
                        "about", "login", "signup", "home",
                    ]
                    if any(kw in text.lower() for kw in nav_keywords):
                        continue

                    seen_titles.add(text)
                    items.append({
                        "title": text[:200],
                        "url": href,
                        "summary": text,
                    })

                except Exception as exc:
                    logger.debug("[%s] 항목 파싱 실패: %s", self.name, exc)
                    continue

        except Exception as e:
            logger.debug("[%s] 폴백 추출 실패: %s", self.name, e)

        return items

    @staticmethod
    def _parse_time(time_text: str) -> datetime:
        """시간 텍스트를 datetime으로 파싱한다.

        '3분 전', '1시간 전', '2024-01-15' 등 다양한 형식을 지원한다.
        """
        from datetime import timedelta

        now = datetime.now(tz=timezone.utc)
        if not time_text:
            return now

        time_text = time_text.strip()

        # ISO 형식 시도
        try:
            dt = datetime.fromisoformat(time_text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass

        # 상대 시간 한국어 파싱
        import re

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

        # YYYY-MM-DD 또는 YYYY.MM.DD 형식
        date_match = re.search(
            r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", time_text
        )
        if date_match:
            try:
                return datetime(
                    int(date_match.group(1)),
                    int(date_match.group(2)),
                    int(date_match.group(3)),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                pass

        return now
