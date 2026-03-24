"""F7.12 IndicatorEndpoints -- 기술 지표 가중치 조회/수정 API이다.

지표 가중치 현황, RSI 데이터, 가중치 업데이트 기능을 제공한다.
신규: 지표 설정 업데이트(PUT /config), 실시간 지표 조회(GET /realtime/{ticker}),
      트리플 RSI 조회(GET /rsi/{ticker}).
모든 엔드포인트는 Pydantic 응답 모델을 반환한다.
"""
from __future__ import annotations

import json
from pathlib import Path as FilePath
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from src.common.logger import get_logger
from src.common.paths import get_data_dir
from src.monitoring.schemas.indicator_schemas import (
    BollingerData,
    IndicatorConfigResponse,
    IndicatorConfigUpdateRequest,
    IndicatorWeightsResponse,
    IndicatorWeightUpdateResponse,
    MacdData,
    RealtimeIndicatorResponse,
    RsiDataResponse,
    RsiIndicatorItem,
    TripleRsiResponse,
    WeightUpdateRequest,
)
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

indicators_router = APIRouter(prefix="/api/indicators", tags=["indicators"])

_system: InjectedSystem | None = None

def _strategy_params_path() -> FilePath:
    """strategy_params.json 경로를 반환한다. 호출 시점에 평가한다."""
    return get_data_dir() / "strategy_params.json"

# RSI 캐시 TTL(초) -- 5분이다
_RSI_CACHE_TTL: int = 300

# RSI 시그널 라인 SMA 기간이다
_RSI_SIGNAL_PERIOD: int = 9


# ── 의존성 주입 ────────────────────────────────────────────────────────────

def set_indicators_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("IndicatorEndpoints 의존성 주입 완료")


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

def _require_system() -> None:
    """시스템이 초기화되지 않았으면 503 예외를 발생시킨다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")


def _load_strategy_params() -> dict:
    """strategy_params.json을 로드한다. 없으면 빈 딕셔너리를 반환한다."""
    sp = _strategy_params_path()
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        _logger.exception("strategy_params.json 로드 실패")
        return {}


def _save_strategy_params(params: dict) -> None:
    """strategy_params.json에 데이터를 저장한다."""
    sp = _strategy_params_path()
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(
        json.dumps(params, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _to_float_or_none(val: Any) -> float | None:
    """값을 float으로 변환한다. 실패 시 None을 반환한다."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ── 기존 엔드포인트 (Pydantic 모델로 개선) ───────────────────────────────

@indicators_router.get("/weights", response_model=IndicatorWeightsResponse)
async def get_indicator_weights(
    _auth: str = Depends(verify_api_key),
) -> IndicatorWeightsResponse:
    """현재 지표 가중치를 반환한다."""
    _require_system()
    try:
        params = _load_strategy_params()
        weights: dict[str, float] = params.get("indicator_weights", {})
        return IndicatorWeightsResponse(weights=weights)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("지표 가중치 조회 실패")
        raise HTTPException(status_code=500, detail="가중치 조회 실패") from None


@indicators_router.get("/rsi", response_model=RsiDataResponse)
async def get_rsi_data(
    _auth: str = Depends(verify_api_key),
) -> RsiDataResponse:
    """티커별 RSI 현황을 반환한다.

    indicators:rsi 종합 캐시를 먼저 조회하고, 없으면 개별 티커별
    indicators:rsi:{ticker} 캐시를 집계하여 반환한다.
    """
    _require_system()
    try:
        cache = _system.components.cache  # type: ignore[union-attr]
        cached = await cache.read_json("indicators:rsi")
        if cached and isinstance(cached, dict):
            return RsiDataResponse(rsi_data=cached, message=None)
        # 개별 티커별 RSI 캐시를 집계한다
        registry = _system.components.registry  # type: ignore[union-attr]
        rsi_agg: dict[str, Any] = {}
        for meta in registry.get_universe():
            tk = meta.ticker
            tk_cached = await cache.read_json(f"indicators:rsi:{tk}")
            if tk_cached and isinstance(tk_cached, dict):
                rsi_agg[tk] = tk_cached
        if rsi_agg:
            return RsiDataResponse(rsi_data=rsi_agg, message=None)
        return RsiDataResponse(rsi_data={}, message="RSI 데이터가 없다")
    except HTTPException:
        raise
    except Exception:
        _logger.exception("RSI 데이터 조회 실패")
        raise HTTPException(status_code=500, detail="RSI 조회 실패") from None


@indicators_router.put("/weights", response_model=IndicatorWeightUpdateResponse)
async def update_indicator_weights(
    req: WeightUpdateRequest,
    _key: str = Depends(verify_api_key),
) -> IndicatorWeightUpdateResponse:
    """지표 가중치를 업데이트한다. 인증 필수."""
    _require_system()
    try:
        params = _load_strategy_params()
        params["indicator_weights"] = req.weights
        _save_strategy_params(params)
        _logger.info("지표 가중치 업데이트 완료: %s", req.weights)
        return IndicatorWeightUpdateResponse(status="updated", weights=req.weights)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("지표 가중치 업데이트 실패")
        raise HTTPException(status_code=500, detail="가중치 업데이트 실패") from None


# ── 신규 엔드포인트 ───────────────────────────────────────────────────────

@indicators_router.put("/config", response_model=IndicatorConfigResponse)
async def update_indicator_config(
    req: IndicatorConfigUpdateRequest,
    _key: str = Depends(verify_api_key),
) -> IndicatorConfigResponse:
    """지표 설정을 업데이트한다. 인증 필수.

    strategy_params.json 내 indicator_config 섹션을 갱신한다.
    캐시에도 indicators:config 키로 캐시하여 빠른 조회를 지원한다.
    """
    _require_system()
    try:
        params = _load_strategy_params()

        # 기존 config와 병합한다
        existing_config: dict[str, Any] = params.get("indicator_config", {})
        merged_config = {**existing_config, **req.config}
        params["indicator_config"] = merged_config

        _save_strategy_params(params)

        # 캐시도 갱신한다
        cache = _system.components.cache  # type: ignore[union-attr]
        await cache.write_json("indicators:config", merged_config)

        _logger.info("지표 설정 업데이트 완료: %d개 항목", len(req.config))
        return IndicatorConfigResponse(updated=True, config=merged_config)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("지표 설정 업데이트 실패")
        raise HTTPException(status_code=500, detail="지표 설정 업데이트 실패") from None


@indicators_router.get("/realtime/{ticker}", response_model=RealtimeIndicatorResponse)
async def get_realtime_indicators(
    ticker: str = Path(..., pattern=r"^[A-Za-z0-9]{1,10}$"),
    _auth: str = Depends(verify_api_key),
) -> RealtimeIndicatorResponse:
    """특정 티커의 실시간 기술 지표를 반환한다.

    IndicatorBundleBuilder 피처 또는 캐시에서 데이터를 조회한다.
    캐시 키: indicators:realtime:{ticker}
    피처가 없으면 캐시에서만 조회한다.
    """
    _require_system()
    try:
        from datetime import datetime, timezone

        ticker_upper = ticker.upper()
        cache = _system.components.cache  # type: ignore[union-attr]

        # IndicatorBundleBuilder 피처가 있으면 직접 계산을 시도한다
        bundle_builder = _system.features.get("indicator_bundle_builder")  # type: ignore[union-attr]
        if bundle_builder is not None:
            build_fn = getattr(bundle_builder, "build", None)
            if build_fn is not None:
                try:
                    raw_bundle = await build_fn(ticker_upper)
                    if isinstance(raw_bundle, dict) and raw_bundle:
                        # 빌드 결과를 캐시에 저장한다
                        # 실시간 지표는 5분 후 만료한다 (_TTL_INDICATORS와 동일)
                        await cache.write_json(
                            f"indicators:realtime:{ticker_upper}",
                            raw_bundle,
                            ttl=300,
                        )
                        return _build_realtime_response(ticker_upper, raw_bundle)
                except Exception:
                    _logger.warning(
                        "IndicatorBundleBuilder.build 실패, 캐시 폴백: %s",
                        ticker_upper,
                    )

        # 캐시에서 조회한다
        cached = await cache.read_json(f"indicators:realtime:{ticker_upper}")
        if isinstance(cached, dict):
            return _build_realtime_response(ticker_upper, cached)

        # 데이터가 없으면 빈 응답을 반환한다
        return RealtimeIndicatorResponse(
            ticker=ticker_upper,
            rsi=None,
            macd=None,
            bollinger=None,
            atr=None,
            volume=None,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("실시간 지표 조회 실패: %s", ticker)
        raise HTTPException(status_code=500, detail="실시간 지표 조회 실패") from None


# ── 트리플 RSI 엔드포인트 ──────────────────────────────────────────────────


@indicators_router.get("/rsi/{ticker}", response_model=TripleRsiResponse)
async def get_triple_rsi(
    ticker: str = Path(..., pattern=r"^[A-Za-z0-9]{1,10}$"),
    days: int = Query(default=100, ge=30, le=365, description="조회 일수"),
    _auth: str = Depends(verify_api_key),
) -> TripleRsiResponse:
    """특정 티커의 트리플 RSI(7, 14, 21) 데이터를 반환한다.

    1. 캐시(indicators:rsi:{ticker})에서 먼저 조회한다.
    2. 캐시 미스 시 KIS API로 일봉 데이터를 가져와 직접 계산한다.
    3. 계산 결과를 5분 TTL로 캐시에 저장한다.
    """
    _require_system()
    try:
        ticker_upper = ticker.upper()
        cache = _system.components.cache  # type: ignore[union-attr]
        cache_key = f"indicators:rsi:{ticker_upper}"

        # 1. 캐시에서 조회한다
        cached = await cache.read_json(cache_key)
        if cached and isinstance(cached, dict):
            _logger.debug("트리플 RSI 캐시 히트: %s", ticker_upper)
            return TripleRsiResponse(**cached)

        # 2. 캐시 미스 -- KIS API로 가격 데이터를 가져와 계산한다
        _logger.info("트리플 RSI 캐시 미스, KIS API로 직접 계산 시작: %s (days=%d)", ticker_upper, days)
        result = await _calculate_triple_rsi(ticker_upper, days)

        # 3. 결과를 캐시에 저장한다
        await cache.write_json(cache_key, result.model_dump(), ttl=_RSI_CACHE_TTL)
        _logger.info("트리플 RSI 계산 및 캐시 완료: %s", ticker_upper)

        return result
    except HTTPException:
        raise
    except Exception:
        _logger.exception("트리플 RSI 조회 실패: %s", ticker)
        raise HTTPException(status_code=500, detail="트리플 RSI 조회 실패") from None


async def _calculate_triple_rsi(ticker: str, days: int) -> TripleRsiResponse:
    """KIS API로 일봉을 가져와 RSI(7), RSI(14), RSI(21) 시리즈를 계산한다.

    각 RSI 기간마다 전체 시리즈, 시그널(SMA 9), 히스토그램을 생성한다.
    """
    import numpy as np

    closes, dates = await _fetch_closes_via_kis(ticker, days)

    if len(closes) < 30:
        _logger.warning("RSI 계산 불가: %s 종가 %d개 (최소 30개 필요)", ticker, len(closes))
        return TripleRsiResponse(ticker=ticker, analysis_ticker=ticker)

    closes_arr = np.array(closes, dtype=float)

    rsi_7 = _compute_rsi_indicator(closes_arr, period=7)
    rsi_14 = _compute_rsi_indicator(closes_arr, period=14)
    rsi_21 = _compute_rsi_indicator(closes_arr, period=21)

    consensus = _determine_consensus(rsi_7.rsi, rsi_14.rsi, rsi_21.rsi)
    divergence = _detect_divergence(rsi_7.rsi, rsi_14.rsi, rsi_21.rsi)

    return TripleRsiResponse(
        rsi_7=rsi_7,
        rsi_14=rsi_14,
        rsi_21=rsi_21,
        consensus=consensus,
        divergence=divergence,
        dates=dates,
        ticker=ticker,
        analysis_ticker=ticker,
    )


async def _fetch_closes_via_kis(
    ticker: str, days: int,
) -> tuple[list[float], list[str]]:
    """KIS API로 일봉 종가와 날짜를 가져온다.

    BrokerClient.get_daily_candles()를 사용하여 KIS 일봉 API를 호출한다.
    OHLCV 데이터에서 종가(close)와 날짜(date)를 추출한다.
    """
    if _system is None:
        return [], []

    try:
        broker = _system.components.broker
        # KIS API 일봉 조회 -- 여유분 포함하여 요청한다
        candles = await broker.get_daily_candles(ticker, days=days, exchange="NAS")

        if not candles:
            _logger.warning("KIS API 일봉 데이터 없음: %s", ticker)
            return [], []

        # KIS API는 최신→과거 순으로 반환하므로 시간순으로 역정렬한다
        candles_sorted = sorted(candles, key=lambda c: c.date)

        closes = [c.close for c in candles_sorted]
        dates = [c.date for c in candles_sorted]

        # 날짜 형식을 통일한다 (YYYYMMDD → YYYY-MM-DD)
        formatted_dates: list[str] = []
        for d in dates:
            if len(d) == 8 and d.isdigit():
                formatted_dates.append(f"{d[:4]}-{d[4:6]}-{d[6:8]}")
            else:
                formatted_dates.append(d)

        _logger.info("KIS API 일봉 %d개 조회 완료: %s", len(closes), ticker)
        return closes, formatted_dates
    except Exception as exc:
        _logger.error("KIS API 일봉 조회 실패 (%s): %s", ticker, exc)
        return [], []


def _compute_rsi_series(closes: "np.ndarray", period: int) -> list[float]:
    """Wilder 평활법으로 RSI 시리즈 전체를 계산한다.

    technical_calculator.py의 calc_rsi와 동일한 알고리즘이지만
    최종값이 아닌 전체 시리즈를 반환한다.
    """
    import numpy as np

    n = len(closes)
    if n < period + 1:
        return [50.0] * n

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # 초기 평균
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    # 결과 시리즈를 구성한다 (첫 period개는 50.0으로 채운다)
    rsi_values: list[float] = [50.0] * period

    # period 번째부터 RSI를 계산한다
    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(round(100.0 - (100.0 / (1.0 + rs)), 2))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
        avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(round(100.0 - (100.0 / (1.0 + rs)), 2))

    return rsi_values


def _compute_sma_series(values: list[float], period: int) -> list[float]:
    """SMA 시리즈를 계산한다. 기간 미달 구간은 누적 평균을 사용한다."""
    result: list[float] = []
    for i in range(len(values)):
        if i < period - 1:
            # 기간 미달: 누적 평균으로 채운다
            result.append(round(sum(values[: i + 1]) / (i + 1), 2))
        else:
            window = values[i - period + 1 : i + 1]
            result.append(round(sum(window) / period, 2))
    return result


def _compute_rsi_indicator(
    closes: "np.ndarray", period: int,
) -> RsiIndicatorItem:
    """특정 기간의 RSI 지표(시리즈 + 시그널 + 히스토그램)를 생성한다."""
    rsi_series = _compute_rsi_series(closes, period)
    signal_series = _compute_sma_series(rsi_series, _RSI_SIGNAL_PERIOD)

    # 최종 값
    current_rsi = rsi_series[-1] if rsi_series else 50.0
    current_signal = signal_series[-1] if signal_series else 50.0
    histogram = round(current_rsi - current_signal, 2)

    return RsiIndicatorItem(
        rsi=current_rsi,
        signal=current_signal,
        histogram=histogram,
        rsi_series=rsi_series,
        signal_series=signal_series,
        overbought=current_rsi > 70,
        oversold=current_rsi < 30,
    )


def _determine_consensus(rsi_7: float, rsi_14: float, rsi_21: float) -> str:
    """3개 RSI 값의 합의(consensus)를 판별한다.

    과반수가 같은 방향이면 해당 방향, 아니면 neutral이다.
    """
    bullish_count = sum(1 for r in (rsi_7, rsi_14, rsi_21) if r > 55)
    bearish_count = sum(1 for r in (rsi_7, rsi_14, rsi_21) if r < 45)

    if bullish_count >= 2:
        return "bullish"
    if bearish_count >= 2:
        return "bearish"
    return "neutral"


def _detect_divergence(rsi_7: float, rsi_14: float, rsi_21: float) -> bool:
    """RSI 기간 간 다이버전스를 감지한다.

    단기(7)와 장기(21) RSI 방향이 반대이면 다이버전스로 판단한다.
    """
    short_bullish = rsi_7 > 55
    long_bearish = rsi_21 < 45
    short_bearish = rsi_7 < 45
    long_bullish = rsi_21 > 55

    return (short_bullish and long_bearish) or (short_bearish and long_bullish)


# ── 실시간 지표 응답 빌더 ──────────────────────────────────────────────────


def _build_realtime_response(ticker: str, raw: dict) -> RealtimeIndicatorResponse:
    """원시 지표 dict를 RealtimeIndicatorResponse로 변환한다."""
    from datetime import datetime, timezone

    # MACD 구성 요소 파싱
    macd_raw = raw.get("macd")
    macd: MacdData | None = None
    if isinstance(macd_raw, dict):
        macd = MacdData(
            macd=_to_float_or_none(macd_raw.get("macd")),
            signal=_to_float_or_none(macd_raw.get("signal")),
            histogram=_to_float_or_none(macd_raw.get("histogram")),
        )

    # 볼린저 밴드 구성 요소 파싱
    bb_raw = raw.get("bollinger", raw.get("bb"))
    bollinger: BollingerData | None = None
    if isinstance(bb_raw, dict):
        bollinger = BollingerData(
            upper=_to_float_or_none(bb_raw.get("upper")),
            middle=_to_float_or_none(bb_raw.get("middle")),
            lower=_to_float_or_none(bb_raw.get("lower")),
        )

    return RealtimeIndicatorResponse(
        ticker=ticker,
        rsi=_to_float_or_none(raw.get("rsi")),
        macd=macd,
        bollinger=bollinger,
        atr=_to_float_or_none(raw.get("atr")),
        volume=_to_float_or_none(raw.get("volume")),
        timestamp=str(
            raw.get("timestamp", datetime.now(tz=timezone.utc).isoformat())
        ),
    )
