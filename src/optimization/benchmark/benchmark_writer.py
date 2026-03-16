"""벤치마크 일봉 데이터 수집기 -- SPY/SSO 일별 수익률을 캐시에 기록한다.

KIS OpenAPI로 SPY·SSO 일봉(close)을 가져와 일별 수익률(%)을 계산한 뒤
benchmark:spy_daily / benchmark:sso_daily 캐시 키에 저장한다.
GET /api/benchmark/comparison·chart 엔드포인트가 이 데이터를 읽어 비교한다.
"""
from __future__ import annotations

from src.common.broker_gateway import BrokerClient, OHLCV
from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger

logger = get_logger(__name__)

# 벤치마크 대상 종목과 캐시 키, 거래소 코드 매핑이다
_BENCHMARKS: list[tuple[str, str, str]] = [
    ("SPY", "benchmark:spy_daily", "AMS"),
    ("SSO", "benchmark:sso_daily", "AMS"),
]

_TTL_SECONDS: int = 86400  # 24시간


def _compute_daily_returns(candles: list[OHLCV]) -> list[dict]:
    """종가 기반 일별 수익률(%)을 계산한다.

    캔들은 최신→과거 순서로 들어오므로 역순 정렬 후 계산한다.
    엔드포인트가 기대하는 키: date, return_pct.
    """
    # 날짜 오름차순(과거→최신)으로 정렬한다
    sorted_candles = sorted(candles, key=lambda c: c.date)
    results: list[dict] = []
    for i, candle in enumerate(sorted_candles):
        if i == 0 or sorted_candles[i - 1].close == 0.0:
            # 첫 번째 봉은 전일 데이터가 없으므로 수익률 0으로 기록한다
            results.append({"date": candle.date, "return_pct": 0.0})
            continue
        prev_close = sorted_candles[i - 1].close
        pct = round((candle.close - prev_close) / prev_close * 100, 4)
        results.append({"date": candle.date, "return_pct": pct})
    return results


async def write_benchmark_data(
    broker: BrokerClient,
    cache: CacheClient,
    days: int = 90,
) -> int:
    """SPY/SSO 일봉을 조회하여 일별 수익률을 캐시에 기록한다.

    Returns:
        기록에 성공한 벤치마크 종목 수 (0~2).
    """
    written = 0
    for ticker, cache_key, exchange in _BENCHMARKS:
        try:
            candles = await broker.get_daily_candles(ticker, days, exchange)
            if not candles:
                logger.warning("벤치마크 %s: 일봉 데이터 없음 (건너뜀)", ticker)
                continue
            returns = _compute_daily_returns(candles)
            await cache.write_json(cache_key, returns, ttl=_TTL_SECONDS)
            written += 1
            logger.info("벤치마크 %s: %d일 수익률 기록 완료", ticker, len(returns))
        except Exception as exc:
            logger.warning("벤치마크 %s 기록 실패 (건너뜀): %s", ticker, exc)
    return written
