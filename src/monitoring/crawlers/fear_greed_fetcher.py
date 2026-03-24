"""Fear & Greed Index 크롤러이다. CNN 공식 API(1순위) + 스크래핑 폴백(2순위)."""
from __future__ import annotations

import re

import aiohttp

from src.common.logger import get_logger

logger = get_logger(__name__)

# CNN F&G 점수 -> 레이블 변환 기준이다
_LABELS: list[tuple[int, int, str]] = [
    (0, 25, "Extreme Fear"),
    (25, 45, "Fear"),
    (45, 55, "Neutral"),
    (55, 75, "Greed"),
    (75, 101, "Extreme Greed"),
]

# 기본 HTTP 헤더이다
_BROWSER_UA: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _score_to_label(score: int) -> str:
    """점수(0-100)를 레이블로 변환한다."""
    for lo, hi, label in _LABELS:
        if lo <= score < hi:
            return label
    return "Neutral"


def _score_to_description(score: int, label: str) -> str:
    """점수와 레이블을 기반으로 설명 문자열을 생성한다."""
    descriptions: dict[str, str] = {
        "Extreme Fear": "시장에 극심한 공포가 만연하다",
        "Fear": "시장에 공포 심리가 감지된다",
        "Neutral": "시장 심리가 중립적이다",
        "Greed": "시장에 탐욕 심리가 감지된다",
        "Extreme Greed": "시장에 극단적 탐욕이 만연하다",
    }
    return descriptions.get(label, "시장 심리 데이터를 분석 중이다")


async def fetch_fear_greed() -> dict:
    """Fear & Greed Index를 가져온다. Tier 1 -> Tier 2 순서로 시도한다.

    Returns:
        {"score": int, "label": str, "description": str}
    """
    # Tier 1: CNN 공식 API
    result = await _tier1_cnn_api()
    if result is not None:
        return result

    logger.warning("Tier 1 CNN API 실패 -- Tier 2 폴백 시도")

    # Tier 2: CNN 페이지 스크래핑
    result = await _tier2_cnn_scrape()
    if result is not None:
        return result

    logger.warning("모든 티어 실패 -- 기본값 반환")
    return {"score": 50, "label": "Neutral", "description": "데이터를 가져올 수 없다"}


async def _tier1_cnn_api() -> dict | None:
    """CNN Fear & Greed 공식 API에서 데이터를 가져온다."""
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers = {"User-Agent": _BROWSER_UA}
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.debug("CNN API HTTP %d", resp.status)
                    return None
                data = await resp.json()
                fg = data.get("fear_and_greed", {})
                raw_score = fg.get("score")
                if raw_score is None:
                    logger.debug("CNN API 응답에 score 필드 부재")
                    return None
                # 0~100 범위로 클램핑하여 비정상 값을 방지한다
                score = max(0, min(100, int(raw_score)))
                label = _score_to_label(score)
                desc = fg.get("description", "") or _score_to_description(score, label)
                logger.info("Tier 1 CNN API: score=%d, label=%s", score, label)
                return {"score": score, "label": label, "description": desc}
    except Exception as exc:
        logger.debug("Tier 1 CNN API 실패: %s", exc)
        return None


async def _tier2_cnn_scrape() -> dict | None:
    """CNN Fear & Greed 페이지에서 스크래핑한다."""
    url = "https://edition.cnn.com/markets/fear-and-greed"
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": _BROWSER_UA}
            timeout = aiohttp.ClientTimeout(total=15)
            async with session.get(url, headers=headers, timeout=timeout) as resp:
                if resp.status != 200:
                    logger.debug("CNN scrape HTTP %d", resp.status)
                    return None
                text = await resp.text()
                # CNN 페이지에서 "score":XX 형태의 JSON 블록을 파싱한다
                match = re.search(r'"score"\s*:\s*(\d+)', text)
                if match:
                    # 0~100 범위로 클램핑하여 비정상 값을 방지한다
                    score = max(0, min(100, int(match.group(1))))
                    label = _score_to_label(score)
                    desc = _score_to_description(score, label)
                    logger.info("Tier 2 CNN scrape: score=%d, label=%s", score, label)
                    return {"score": score, "label": label, "description": desc}
                logger.debug("CNN scrape 페이지에서 score 패턴을 찾지 못했다")
                return None
    except Exception as exc:
        logger.debug("Tier 2 CNN scrape 실패: %s", exc)
        return None
