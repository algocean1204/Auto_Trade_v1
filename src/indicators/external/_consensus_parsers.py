"""애널리스트 컨센서스 응답 파서 모듈이다.

Nasdaq API, TipRanks API, TipRanks HTML 등 다양한 소스의
응답을 통일된 컨센서스 dict로 변환하는 순수 함수들을 제공한다.
"""
from __future__ import annotations

import json
import re
from typing import Any

from src.common.logger import get_logger

logger = get_logger(__name__)

# -- 정규식 패턴이다 --
_CONSENSUS_RE = re.compile(
    r'"consensusOverview"\s*:\s*\{([^}]+)\}', re.DOTALL,
)
_BEST_CONSENSUS_RE = re.compile(
    r'"bestConsensusOverview"\s*:\s*\{([^}]+)\}', re.DOTALL,
)
_PRICE_TARGET_RE = re.compile(
    r'"priceTarget"\s*:\s*\{([^}]+)\}', re.DOTALL,
)
_JSON_NUM_RE = re.compile(r'"(\w+)"\s*:\s*(-?\d+\.?\d*)')
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL,
)


def determine_consensus(buy: int, hold: int, sell: int) -> str:
    """Buy/Hold/Sell 카운트에서 종합 컨센서스를 결정한다."""
    total = buy + hold + sell
    if total == 0:
        return "N/A"
    buy_ratio = buy / total
    sell_ratio = sell / total
    if buy_ratio >= 0.7:
        return "Strong Buy"
    if buy_ratio >= 0.5:
        return "Moderate Buy"
    if sell_ratio >= 0.5:
        return "Sell"
    return "Hold"


def _safe_round(val: Any) -> float | None:
    """숫자를 안전하게 반올림한다. 변환 실패 시 None을 반환한다."""
    if val is None:
        return None
    try:
        return round(float(val), 2)
    except (ValueError, TypeError):
        return None


def _build_result(
    buy: int, hold: int, sell: int,
    avg_target: Any, high_target: Any, low_target: Any,
    source: str,
) -> dict[str, Any]:
    """통일된 컨센서스 결과 dict를 생성한다."""
    return {
        "buy": buy, "hold": hold, "sell": sell,
        "total": buy + hold + sell,
        "consensus": determine_consensus(buy, hold, sell),
        "avg_target": _safe_round(avg_target),
        "high_target": _safe_round(high_target),
        "low_target": _safe_round(low_target),
        "source": source,
    }


# ── Nasdaq API 파서이다 ──


def parse_nasdaq(data: dict) -> dict[str, Any] | None:
    """Nasdaq targetprice API 응답을 파싱한다.

    응답 구조: {data: {consensusOverview: {buy, hold, sell, priceTarget, ...}}}
    """
    try:
        co = data.get("data", {}).get("consensusOverview", {})
        if not co:
            return None

        buy = int(co.get("buy", 0))
        hold = int(co.get("hold", 0))
        sell = int(co.get("sell", 0))
        if buy + hold + sell == 0:
            return None

        return _build_result(
            buy, hold, sell,
            co.get("priceTarget"),
            co.get("highPriceTarget"),
            co.get("lowPriceTarget"),
            "nasdaq_api",
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("Nasdaq targetprice 파싱 실패: %s", exc)
        return None


# ── TipRanks API 파서이다 ──


def parse_tipranks_sentiment(data: dict) -> dict[str, Any] | None:
    """TipRanks getNewsSentiments 응답을 파싱한다."""
    try:
        c = data.get("consensus", {})
        if not c:
            return None

        buy = int(c.get("buy", 0))
        hold = int(c.get("hold", 0))
        sell = int(c.get("sell", 0))
        if buy + hold + sell == 0:
            return None

        pt = data.get("priceTarget", {})
        return _build_result(
            buy, hold, sell,
            pt.get("mean") or pt.get("average"),
            pt.get("high"), pt.get("low"),
            "tipranks_sentiment_api",
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("TipRanks sentiment 파싱 실패: %s", exc)
        return None


def parse_tipranks_overview(data: dict) -> dict[str, Any] | None:
    """TipRanks stockAnalysisOverview 응답을 파싱한다."""
    try:
        c = (
            data.get("consensusOverview")
            or data.get("consensus")
            or data.get("analystConsensus")
            or {}
        )
        if not c:
            return None

        buy = int(c.get("buy", 0))
        hold = int(c.get("hold", 0))
        sell = int(c.get("sell", 0))
        if buy + hold + sell == 0:
            return None

        pt = data.get("priceTarget") or data.get("bestPriceTarget") or {}
        return _build_result(
            buy, hold, sell,
            pt.get("mean") or pt.get("average") or pt.get("priceTarget"),
            pt.get("high") or pt.get("highest"),
            pt.get("low") or pt.get("lowest"),
            "tipranks_overview_api",
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("TipRanks overview 파싱 실패: %s", exc)
        return None


# ── TipRanks HTML 스크래핑 파서이다 ──


def _extract_nums(fragment: str) -> dict[str, float]:
    """JSON 프래그먼트에서 숫자 필드를 추출한다."""
    result: dict[str, float] = {}
    for m in _JSON_NUM_RE.finditer(fragment):
        try:
            result[m.group(1)] = float(m.group(2))
        except (ValueError, TypeError):
            continue
    return result


def parse_tipranks_forecast_html(html: str) -> dict[str, Any] | None:
    """TipRanks forecast 페이지 HTML에서 컨센서스를 추출한다."""
    try:
        # __NEXT_DATA__ 스크립트에서 추출 시도한다
        nd_match = _NEXT_DATA_RE.search(html)
        if nd_match:
            parsed = _parse_next_data(nd_match.group(1))
            if parsed:
                return parsed

        # 인라인 JSON에서 추출한다
        target = _BEST_CONSENSUS_RE.search(html) or _CONSENSUS_RE.search(html)
        if not target:
            return None

        nums = _extract_nums(target.group(1))
        buy = int(nums.get("buy", 0))
        hold = int(nums.get("hold", 0))
        sell = int(nums.get("sell", 0))
        if buy + hold + sell == 0:
            return None

        avg_t = high_t = low_t = None
        pm = _PRICE_TARGET_RE.search(html)
        if pm:
            pn = _extract_nums(pm.group(1))
            avg_t = pn.get("mean") or pn.get("average")
            high_t = pn.get("high") or pn.get("highest")
            low_t = pn.get("low") or pn.get("lowest")

        return _build_result(
            buy, hold, sell, avg_t, high_t, low_t,
            "tipranks_forecast_scrape",
        )
    except Exception as exc:
        logger.debug("TipRanks forecast HTML 파싱 실패: %s", exc)
        return None


def _parse_next_data(raw_json: str) -> dict[str, Any] | None:
    """__NEXT_DATA__ JSON에서 consensus를 재귀 탐색한다."""
    try:
        data = json.loads(raw_json)
        return _search_recursive(data, depth=0)
    except (json.JSONDecodeError, TypeError):
        return None


def _search_recursive(obj: Any, depth: int) -> dict[str, Any] | None:
    """중첩 dict에서 consensus를 재귀 탐색한다. 최대 깊이 8이다."""
    if depth > 8 or not isinstance(obj, dict):
        return None

    for key in ("consensusOverview", "analystConsensus", "bestConsensusOverview"):
        c = obj.get(key)
        if isinstance(c, dict) and "buy" in c:
            buy = int(c.get("buy", 0))
            hold = int(c.get("hold", 0))
            sell = int(c.get("sell", 0))
            if buy + hold + sell == 0:
                continue

            pt = obj.get("priceTarget", {})
            avg_t = pt.get("mean") or pt.get("average") if isinstance(pt, dict) else None
            high_t = pt.get("high") if isinstance(pt, dict) else None
            low_t = pt.get("low") if isinstance(pt, dict) else None

            return _build_result(
                buy, hold, sell, avg_t, high_t, low_t,
                "tipranks_nextdata_scrape",
            )

    for val in obj.values():
        if isinstance(val, dict):
            found = _search_recursive(val, depth + 1)
            if found:
                return found
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    found = _search_recursive(item, depth + 1)
                    if found:
                        return found
    return None
