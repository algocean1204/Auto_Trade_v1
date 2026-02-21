"""
Flutter 대시보드용 기술적 지표 API 엔드포인트.

KIS API로 가격 데이터를 수집하고 Triple RSI(7/14/21), Signal(9),
지표 가중치 관리, 실시간 지표 조회, 지표 설정 변경 엔드포인트를 제공한다.

엔드포인트 목록:
  GET  /indicators/weights              - 지표 가중치 및 프리셋 조회
  POST /indicators/weights              - 지표 가중치 업데이트
  GET  /indicators/realtime/{ticker}    - 실시간 지표값 및 이력 조회
  GET  /api/indicators/rsi/{ticker}     - Triple RSI 차트 데이터 조회
  PUT  /api/indicators/config           - 지표 설정 업데이트 (가중치/활성화)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select

from src.db.connection import get_session
from src.db.models import IndicatorHistory
from src.monitoring.auth import verify_api_key
from src.monitoring.schemas import WeightsUpdateRequest
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 의존성 레지스트리
# api_server.py 가 startup 시 set_indicator_deps() 를 호출하여 주입한다.
# ---------------------------------------------------------------------------

_deps: dict[str, Any] = {}


def set_indicator_deps(
    weights_manager: Any = None,
    kis_client: Any = None,
) -> None:
    """런타임 의존성을 주입한다.

    api_server.py 의 set_dependencies() 호출 시 함께 호출되어야 한다.

    Args:
        weights_manager: 지표 가중치 관리 인스턴스.
        kis_client: KIS API 클라이언트 인스턴스.
    """
    _deps["weights_manager"] = weights_manager
    _deps["kis_client"] = kis_client


def _get(name: str) -> Any:
    """의존성을 조회한다. 없으면 503을 반환한다.

    Args:
        name: 의존성 이름.

    Returns:
        의존성 인스턴스.

    Raises:
        HTTPException: 해당 의존성이 초기화되지 않은 경우 503을 반환한다.
    """
    dep = _deps.get(name)
    if dep is None:
        raise HTTPException(
            status_code=503,
            detail=f"Service '{name}' is not available",
        )
    return dep


def _try_get(name: str) -> Any | None:
    """의존성을 조회한다. 없으면 None을 반환한다 (503 대신).

    Args:
        name: 의존성 이름.

    Returns:
        의존성 인스턴스 또는 None.
    """
    return _deps.get(name)


# ---------------------------------------------------------------------------
# APIRouter
# ---------------------------------------------------------------------------

indicator_router = APIRouter(tags=["indicators"])


# ---------------------------------------------------------------------------
# GET /indicators/weights
# ---------------------------------------------------------------------------


@indicator_router.get("/indicators/weights")
async def get_indicator_weights() -> dict:
    """현재 지표 가중치와 사용 가능한 프리셋 목록을 반환한다.

    weights_manager 가 초기화되지 않은 경우 기본값을 반환한다.

    Returns:
        weights, presets, enabled 키를 포함하는 딕셔너리.
    """
    wm = _try_get("weights_manager")
    if wm is None:
        return {
            "weights": {"technical": 30, "sentiment": 25, "macro": 20, "volume": 15, "ai_signal": 10},
            "presets": [],
            "enabled": [],
        }
    weights = await wm.get_weights()
    presets = await wm.list_presets()
    return {
        "weights": weights,
        "presets": list(presets.keys()),
        "enabled": await wm.get_enabled(),
    }


# ---------------------------------------------------------------------------
# POST /indicators/weights
# ---------------------------------------------------------------------------


@indicator_router.post("/indicators/weights")
async def update_indicator_weights(
    body: WeightsUpdateRequest,
    _: None = Depends(verify_api_key),
) -> dict:
    """지표 가중치를 업데이트한다. 합산이 100이 되어야 한다.

    Args:
        body: 지표명과 가중치(0~100)로 구성된 딕셔너리. 합산은 100이어야 한다.

    Returns:
        status, weights 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 400: 가중치 합산이 100이 아닌 경우.
        HTTPException 503: weights_manager 가 초기화되지 않은 경우.
    """
    wm = _get("weights_manager")
    try:
        await wm.set_weights(body.weights)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "ok", "weights": await wm.get_weights()}


# ---------------------------------------------------------------------------
# GET /indicators/realtime/{ticker}
# ---------------------------------------------------------------------------


@indicator_router.get("/indicators/realtime/{ticker}")
async def get_realtime_indicators(ticker: str) -> dict:
    """특정 티커의 실시간 지표값과 최근 24시간 이력을 반환한다.

    indicator_history 테이블에서 최근 24시간 데이터를 조회한다.
    각 지표의 최신값(latest)과 전체 이력(history)을 함께 반환한다.

    Args:
        ticker: 종목 심볼 (예: "SOXL", "QLD").

    Returns:
        ticker, indicators(최신값 맵), history(이력 목록), updated_at 키를
        포함하는 딕셔너리.

    Raises:
        HTTPException 500: DB 조회 중 내부 오류.
    """
    try:
        async with get_session() as session:
            since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
            stmt = (
                select(IndicatorHistory)
                .where(
                    and_(
                        IndicatorHistory.ticker == ticker.upper(),
                        IndicatorHistory.recorded_at >= since,
                    )
                )
                .order_by(IndicatorHistory.recorded_at.desc())
                .limit(200)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            # 지표명별 최신값 그룹화
            latest: dict[str, Any] = {}
            history: list[dict[str, Any]] = []
            for row in rows:
                name = row.indicator_name
                if name not in latest:
                    latest[name] = {
                        "value": row.value,
                        "recorded_at": row.recorded_at.isoformat(),
                        "metadata": row.metadata_ or {},
                    }
                history.append({
                    "indicator_name": name,
                    "value": row.value,
                    "recorded_at": row.recorded_at.isoformat(),
                })

            return {
                "ticker": ticker.upper(),
                "indicators": latest,
                "history": history,
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
    except Exception as exc:
        logger.error("Failed to get realtime indicators for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ---------------------------------------------------------------------------
# GET /api/indicators/rsi/{ticker}
# ---------------------------------------------------------------------------


@indicator_router.get("/api/indicators/rsi/{ticker}")
async def get_rsi_data(
    ticker: str,
    days: int = Query(default=100, ge=10, le=500),
) -> dict:
    """특정 티커의 3중 RSI 데이터를 반환한다. 차트 표시용.

    레버리지 ETF 티커를 입력하면 자동으로 본주 데이터를 사용한다.
    본주 데이터 조회 실패 시 원래 티커로 직접 재시도한다.
    두 시도 모두 실패한 경우에만 404를 반환한다.
    KIS 클라이언트가 초기화되지 않은 경우 503을 반환한다.

    Args:
        ticker: 종목 심볼 (예: "NVDA", "SOXL", "QLD").
        days: 조회할 가격 데이터 기간 (거래일 수, 기본 100).

    Returns:
        rsi_7, rsi_14, rsi_21, signal, dates, ticker, analysis_ticker 키를
        포함하는 딕셔너리.

    Raises:
        HTTPException 404: 데이터를 찾을 수 없는 경우.
        HTTPException 503: KIS 클라이언트가 초기화되지 않은 경우.
        HTTPException 500: 내부 처리 오류.
    """
    try:
        from src.indicators.calculator import TechnicalCalculator
        from src.indicators.data_fetcher import PriceDataFetcher
        from src.utils.ticker_mapping import get_analysis_ticker

        original_ticker = ticker.upper()
        analysis_ticker = get_analysis_ticker(original_ticker)
        kis_client = _deps.get("kis_client")

        if kis_client is None:
            raise HTTPException(
                status_code=503,
                detail="KIS 클라이언트가 초기화되지 않았습니다. 트레이딩 시스템이 실행 중인지 확인하세요.",
            )

        # RSI(21) + Signal(9) 계산을 위해 충분한 데이터가 필요하다.
        fetch_days = max(days + 60, 200)

        fetcher = PriceDataFetcher(kis_client)

        # 1차 시도: analysis_ticker (레버리지 ETF → 본주 매핑 적용)
        df = await fetcher.get_daily_prices(analysis_ticker, days=fetch_days)

        # 2차 시도: analysis_ticker 조회 실패 시 원래 티커로 직접 시도
        if (df is None or df.empty) and analysis_ticker != original_ticker:
            logger.warning(
                "RSI 데이터 없음 (analysis_ticker=%s), 원래 티커로 재시도: %s",
                analysis_ticker,
                original_ticker,
            )
            df = await fetcher.get_daily_prices(original_ticker, days=fetch_days)
            if df is not None and not df.empty:
                # 원래 티커로 성공한 경우 analysis_ticker를 원래 티커로 교체한다.
                analysis_ticker = original_ticker

        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail=f"데이터 없음: {original_ticker} (시도한 티커: {get_analysis_ticker(original_ticker)}, {original_ticker})",
            )

        calculator = TechnicalCalculator()
        triple_rsi = calculator.calculate_triple_rsi(df)

        # 날짜 레이블 추가 (rsi_14 시리즈 길이 기준)
        n_points = len(triple_rsi["rsi_14"]["rsi_series"])
        dates = [
            d.strftime("%Y-%m-%d")
            for d in df.index[-n_points:]
        ] if n_points > 0 else []

        triple_rsi["dates"] = dates
        triple_rsi["ticker"] = original_ticker
        triple_rsi["analysis_ticker"] = analysis_ticker

        return triple_rsi
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get RSI data for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ---------------------------------------------------------------------------
# PUT /api/indicators/config
# ---------------------------------------------------------------------------


@indicator_router.put("/api/indicators/config")
async def update_indicator_config(
    body: dict,
    _: None = Depends(verify_api_key),
) -> dict:
    """지표 설정을 업데이트한다. 가중치 변경, 지표 활성화/비활성화.

    Body:
    {
        "weights": {"rsi_7": 15, "rsi_14": 20, ...},  # optional
        "enabled": {"rsi_7": true, "macd": false, ...},  # optional
        "preset": "rsi_focused"  # optional, weights/enabled 보다 우선 적용
    }

    Args:
        body: preset, weights, enabled 키를 선택적으로 포함하는 딕셔너리.

    Returns:
        status, weights, enabled, preset_applied 등의 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 400: 가중치 값이 유효하지 않은 경우.
        HTTPException 422: 가중치 형식이 잘못된 경우.
        HTTPException 500: 내부 처리 오류.
    """
    wm = _try_get("weights_manager")
    if wm is None:
        from src.indicators.weights import WeightsManager
        wm = WeightsManager()

    try:
        result: dict[str, Any] = {}

        # preset 적용 (weights/enabled 보다 우선)
        if "preset" in body:
            preset_name = str(body["preset"])
            applied_weights = await wm.apply_preset(preset_name)
            result["preset_applied"] = preset_name
            result["weights"] = applied_weights

        # 가중치 직접 설정
        if "weights" in body and "preset" not in body:
            try:
                weights = {k: int(v) for k, v in body["weights"].items()}
            except (ValueError, TypeError, AttributeError) as exc:
                raise HTTPException(
                    status_code=422, detail="잘못된 가중치 형식입니다."
                ) from exc
            await wm.set_weights(weights)
            result["weights"] = await wm.get_weights()

        # 활성화 상태 변경
        if "enabled" in body:
            for indicator_name, flag in body["enabled"].items():
                await wm.set_enabled(indicator_name, bool(flag))
            result["enabled"] = await wm.get_enabled()

        if not result:
            result["weights"] = await wm.get_weights()
            result["enabled"] = await wm.get_enabled()

        result["status"] = "ok"
        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to update indicator config: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")
