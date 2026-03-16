"""F7.5 AnalysisEndpoints -- 티커 종합 분석 API이다.

티커별 AI 분석 결과, 분석 가능 티커 목록, 티커별 뉴스를 제공한다.
캐시 미스 시 실시간 AI 분석을 트리거하여 결과를 생성한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query

from src.common.logger import get_logger
from src.monitoring.schemas.analysis_schemas import (
    AnalysisTickersResponse,
    ComprehensiveAnalysisResponse,
    TickerItem,
    TickerNewsResponse,
)

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

analysis_router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_system: InjectedSystem | None = None

# 분석 결과 캐시 TTL(초) -- 30분이다
_ANALYSIS_CACHE_TTL: int = 1800

# 캐시 신선도 판별 기준(초) -- 30분이다
_CACHE_FRESHNESS_SECONDS: int = 1800


def set_analysis_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("AnalysisEndpoints 의존성 주입 완료")


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────


def _is_cache_fresh(cached: dict) -> bool:
    """캐시된 분석 결과가 30분 이내인지 판별한다.

    timestamp 필드가 없거나 파싱 실패 시 stale로 간주한다.
    """
    ts_str = cached.get("timestamp") or cached.get("analysis_timestamp")
    if not ts_str:
        return False
    try:
        ts = datetime.fromisoformat(str(ts_str))
        # timezone-naive이면 UTC로 간주한다
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
        return age < _CACHE_FRESHNESS_SECONDS
    except (ValueError, TypeError):
        _logger.debug("캐시 timestamp 파싱 실패: %s", ts_str)
        return False


def _extract_news_summary(data: Any, ticker: str) -> str:
    """JSON으로 파싱된 뉴스 캐시 데이터에서 AI 분석용 텍스트 요약을 추출한다.

    잘린 JSON 문자열이 AI에 전달되는 것을 방지한다.
    dict이면 title/summary/headline 등의 필드를, list이면 각 항목의 제목을 연결한다.
    """
    if isinstance(data, dict):
        # 요약 필드 우선, 없으면 title/headline 사용
        text = (
            data.get("summary")
            or data.get("title")
            or data.get("headline")
            or data.get("headline_kr")
            or ""
        )
        return str(text)[:500] if text else f"{ticker} 분석 요청"

    if isinstance(data, list):
        # 뉴스 기사 목록에서 제목만 추출하여 세미콜론으로 연결한다
        titles: list[str] = []
        for item in data[:10]:
            if isinstance(item, dict):
                t = (
                    item.get("headline_kr")
                    or item.get("headline")
                    or item.get("title")
                    or ""
                )
                if t:
                    titles.append(str(t))
            elif isinstance(item, str):
                titles.append(item)
        return "; ".join(titles)[:500] if titles else f"{ticker} 분석 요청"

    # str이나 기타 타입이면 문자열로 변환 후 자른다
    return str(data)[:500]


async def _trigger_realtime_analysis(ticker: str) -> dict[str, Any] | None:
    """실시간 AI 분석을 트리거한다.

    다음 순서로 시도한다:
      1. ComprehensiveTeam이 등록되어 있으면 → AI 종합 분석 실행
      2. 미등록이면 → IndicatorBundleBuilder로 기술 지표 기반 기본 분석 생성
      3. 둘 다 불가하면 → KIS API로 최소한의 시장 데이터를 조회
    """
    assert _system is not None

    # 1. ComprehensiveTeam AI 분석 시도
    analysis_data = await _try_comprehensive_team_analysis(ticker)
    if analysis_data is not None:
        return analysis_data

    # 2. IndicatorBundleBuilder 기술 지표 기반 분석 폴백
    analysis_data = await _try_indicator_based_analysis(ticker)
    if analysis_data is not None:
        return analysis_data

    # 3. KIS API 최소 시장 데이터 폴백
    return await _try_kis_fallback(ticker)


async def _try_comprehensive_team_analysis(ticker: str) -> dict[str, Any] | None:
    """ComprehensiveTeam으로 5개 AI 페르소나 종합 분석을 실행한다.

    Feature 미등록 또는 분석 실패 시 None을 반환한다.
    """
    assert _system is not None
    team = _system.features.get("comprehensive_team")
    if team is None:
        _logger.debug("comprehensive_team 미등록 -- AI 분석 스킵")
        return None

    try:
        from src.analysis.models import AnalysisContext

        context = await _build_ticker_context(ticker)
        report = await team.analyze(context)  # type: ignore[union-attr]

        # ComprehensiveReport를 캐시용 dict로 변환한다
        recs = report.recommendations or []  # type: ignore[union-attr]
        sigs = report.signals or []  # type: ignore[union-attr]

        data: dict[str, Any] = {
            "ticker": ticker.upper(),
            "timestamp": report.timestamp.isoformat(),  # type: ignore[union-attr]
            "ai_available": True,
            "source": "comprehensive_team",
            "confidence": report.confidence,  # type: ignore[union-attr]
            "risk_level": report.risk_level,  # type: ignore[union-attr]
            "regime_assessment": report.regime_assessment,  # type: ignore[union-attr]
            "recommendations": recs,
            "signals": sigs,
            "ai_analysis": {
                "current_situation": _extract_readable_text(recs[:2]),
                "reasoning": f"확신도={report.confidence}, 위험={report.risk_level}",  # type: ignore[union-attr]
                "key_factors": _extract_key_factors(sigs[:5]),
                "risk_factors": [],
                "predictions": [],
                "recommendation": {
                    "action": _extract_action_from_signals(sigs),
                    "reasoning": _extract_readable_text(recs[:3]),
                },
            },
        }
        _logger.info("ComprehensiveTeam 분석 완료: %s (conf=%.2f)", ticker, report.confidence)  # type: ignore[union-attr]
        return data
    except Exception:
        _logger.exception("ComprehensiveTeam 분석 실패: %s", ticker)
        return None


async def _try_indicator_based_analysis(ticker: str) -> dict[str, Any] | None:
    """IndicatorBundleBuilder로 기술 지표 기반 기본 분석을 생성한다.

    AI 분석 없이 기술 지표 데이터만으로 응답을 구성한다.
    """
    assert _system is not None
    builder = _system.features.get("indicator_bundle_builder")
    if builder is None:
        _logger.debug("indicator_bundle_builder 미등록 -- 지표 기반 분석 스킵")
        return None

    try:
        bundle = await builder.build(ticker.upper())  # type: ignore[union-attr]
        tech = bundle.technical  # type: ignore[union-attr]

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        data: dict[str, Any] = {
            "ticker": ticker.upper(),
            "timestamp": now_iso,
            "analysis_timestamp": now_iso,
            "ai_available": False,
            "source": "indicator_bundle",
            "message": "기술 지표 기반 분석 (AI 미사용)",
        }

        if tech is not None:
            # TechnicalIndicators에서 기술 요약을 구성한다
            trend = "uptrend" if tech.ema_20 > tech.sma_200 else "downtrend" if tech.ema_20 < tech.sma_200 else "sideways"
            macd_signal = "bullish" if tech.macd_histogram > 0 else "bearish" if tech.macd_histogram < 0 else "neutral"

            data["technical_summary"] = {
                "composite_score": round((tech.rsi - 50) / 50, 2),
                "rsi_14": tech.rsi,
                "macd_signal": macd_signal,
                "trend": trend,
                "support": tech.bb_lower,
                "resistance": tech.bb_upper,
            }
            data["current_price"] = tech.bb_middle  # 볼린저 중간값을 근사 현재가로 사용한다

        _logger.info("지표 기반 분석 생성 완료: %s", ticker)
        return data
    except Exception:
        _logger.exception("지표 기반 분석 실패: %s", ticker)
        return None


async def _try_kis_fallback(ticker: str) -> dict[str, Any] | None:
    """KIS API로 최소한의 시장 데이터를 조회하여 기본 응답을 구성한다.

    AI와 IndicatorBundleBuilder 모두 불가할 때의 최종 폴백이다.
    BrokerClient.get_price()와 get_daily_candles()를 사용한다.
    """
    assert _system is not None

    try:
        broker = _system.components.broker
        ticker_upper = ticker.upper()

        # TickerRegistry에서 거래소 코드를 가져온다
        exchange = "NAS"
        try:
            registry = _system.components.registry
            exchange = registry.get_exchange_code(ticker_upper)
        except (KeyError, AttributeError):
            pass

        # KIS API로 현재가 조회를 시도한다
        current_price = 0.0
        price_change_pct = 0.0

        try:
            price_data = await broker.get_price(ticker_upper, exchange)
            current_price = price_data.price
            price_change_pct = price_data.change_pct
        except Exception:
            _logger.debug("KIS 현재가 조회 실패, 일봉으로 폴백: %s", ticker_upper)
            # 현재가 실패 시 일봉 데이터에서 추출한다
            try:
                candles = await broker.get_daily_candles(ticker_upper, days=5, exchange=exchange)
                if candles:
                    # 최신순 정렬 (KIS API는 최신→과거 순)
                    latest = candles[0]
                    current_price = latest.close
                    if len(candles) > 1:
                        prev_close = candles[1].close
                        if prev_close > 0:
                            price_change_pct = round(
                                ((current_price - prev_close) / prev_close) * 100, 2
                            )
            except Exception:
                _logger.debug("KIS 일봉 조회도 실패: %s", ticker_upper)

        if current_price <= 0:
            _logger.warning("KIS API 폴백: 가격 데이터를 가져올 수 없다: %s", ticker_upper)
            return None

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        return {
            "ticker": ticker_upper,
            "current_price": round(current_price, 2),
            "price_change_pct": price_change_pct,
            "timestamp": now_iso,
            "analysis_timestamp": now_iso,
            "ai_available": False,
            "source": "kis_fallback",
            "message": "기본 시장 데이터만 제공 (AI 분석 불가)",
            "technical_summary": {
                "composite_score": 0,
                "rsi_14": 50,
                "macd_signal": "neutral",
                "trend": "sideways",
                "support": 0,
                "resistance": 0,
            },
        }
    except Exception:
        _logger.exception("KIS API 폴백 실패: %s", ticker)
        return None


async def _build_ticker_context(ticker: str) -> object:
    """특정 티커용 AnalysisContext를 구성한다.

    continuous_analysis의 _build_analysis_context와 유사하지만
    특정 티커에 초점을 맞춘다.
    """
    from src.analysis.models import AnalysisContext

    assert _system is not None
    cache = _system.components.cache

    # VIX → 레짐 판별
    vix = 20.0
    regime_str = "sideways"
    try:
        vf = _system.features.get("vix_fetcher")
        if vf is not None:
            vix = await vf.get_vix()  # type: ignore[union-attr]
    except Exception:
        pass

    detector = _system.features.get("regime_detector")
    if detector is not None:
        try:
            regime = detector.detect(vix_value=vix)  # type: ignore[union-attr]
            regime_str = regime.regime_type  # type: ignore[union-attr]
        except Exception:
            pass

    # 포지션 조회
    positions_list: list[dict] = []
    monitor = _system.features.get("position_monitor")
    if monitor is not None:
        try:
            pos_map = monitor.get_all_positions()  # type: ignore[union-attr]
            positions_list = [p.model_dump() for p in pos_map.values()]
        except Exception:
            pass

    # 뉴스 / 지표 캐시
    news_summary = f"{ticker} 분석 요청"
    indicators: dict = {}
    try:
        # 티커별 뉴스를 JSON으로 읽어 요약 텍스트를 구성한다
        ticker_news = await cache.read_json(f"news:{ticker}")
        if ticker_news:
            news_summary = _extract_news_summary(ticker_news, ticker)
        else:
            # 글로벌 뉴스 요약도 JSON으로 읽어 잘린 JSON이 AI에 전달되지 않도록 한다
            global_news = await cache.read_json("news:latest_summary")
            if global_news:
                news_summary = _extract_news_summary(global_news, ticker)

        raw_ind = await cache.read_json("indicators:latest")
        if raw_ind and isinstance(raw_ind, dict):
            indicators = raw_ind
    except Exception:
        pass

    return AnalysisContext(
        news_summary=news_summary,
        indicators=indicators,
        regime=regime_str,
        positions=positions_list,
    )


async def _enrich_analysis_data(
    ticker: str, data: dict[str, Any],
) -> dict[str, Any]:
    """분석 결과에 대시보드 렌더링에 필요한 부가 데이터를 보강한다.

    current_price, price_change_pct, technical_summary, related_news,
    analysis_timestamp 등 Flutter 대시보드 모델이 기대하는 필드를 추가한다.
    이미 존재하는 필드는 덮어쓰지 않는다.
    """
    assert _system is not None
    ticker_upper = ticker.upper()

    # analysis_timestamp 보강 (timestamp → analysis_timestamp 매핑)
    if "analysis_timestamp" not in data and "timestamp" in data:
        data["analysis_timestamp"] = data["timestamp"]

    # current_price / price_change_pct 보강
    # 키가 없거나 값이 0 이하(이전 실패 결과)이면 실시간 가격을 조회한다
    existing_price = data.get("current_price")
    needs_price = existing_price is None or existing_price <= 0
    needs_change = "price_change_pct" not in data
    if needs_price or needs_change:
        try:
            broker = _system.components.broker
            # TickerRegistry에서 정확한 거래소 코드를 가져온다
            _exc = "NAS"
            try:
                _exc = _system.components.registry.get_exchange_code(ticker_upper)
            except (KeyError, AttributeError):
                pass
            price_data = await broker.get_price(ticker_upper, _exc)
            if price_data.price > 0:
                data["current_price"] = round(price_data.price, 2)
                data["price_change_pct"] = round(price_data.change_pct, 2)
            else:
                _logger.debug("브로커 가격 0 반환, 일봉 폴백 시도: %s", ticker_upper)
                raise ValueError("브로커 가격 0")
        except Exception:
            _logger.debug("브로커 가격 조회 실패, 일봉 폴백: %s", ticker_upper)
            # 일봉 데이터에서 최신 종가를 추출한다
            try:
                broker = _system.components.broker
                _exc2 = "NAS"
                try:
                    _exc2 = _system.components.registry.get_exchange_code(ticker_upper)
                except (KeyError, AttributeError):
                    pass
                candles = await broker.get_daily_candles(ticker_upper, days=5, exchange=_exc2)
                if candles and candles[0].close > 0:
                    data["current_price"] = round(candles[0].close, 2)
                    if len(candles) > 1 and candles[1].close > 0:
                        pct = ((candles[0].close - candles[1].close) / candles[1].close) * 100
                        data["price_change_pct"] = round(pct, 2)
                    else:
                        data.setdefault("price_change_pct", 0.0)
                else:
                    data.setdefault("current_price", 0.0)
                    data.setdefault("price_change_pct", 0.0)
            except Exception:
                _logger.debug("일봉 폴백도 실패: %s", ticker_upper)
                data.setdefault("current_price", 0.0)
                data.setdefault("price_change_pct", 0.0)

    # technical_summary 보강
    if "technical_summary" not in data:
        try:
            builder = _system.features.get("indicator_bundle_builder")
            if builder is not None:
                bundle = await builder.build(ticker_upper)  # type: ignore[union-attr]
                tech = bundle.technical  # type: ignore[union-attr]
                if tech is not None:
                    trend = "uptrend" if tech.ema_20 > tech.sma_200 else "downtrend" if tech.ema_20 < tech.sma_200 else "sideways"
                    macd_signal = "bullish" if tech.macd_histogram > 0 else "bearish" if tech.macd_histogram < 0 else "neutral"
                    data["technical_summary"] = {
                        "composite_score": round((tech.rsi - 50) / 50, 2),
                        "rsi_14": tech.rsi,
                        "macd_signal": macd_signal,
                        "trend": trend,
                        "support": tech.bb_lower,
                        "resistance": tech.bb_upper,
                    }
        except Exception:
            _logger.debug("기술지표 보강 실패: %s", ticker_upper)

    # price_history 보강 — KIS API 일봉 데이터를 조회한다
    if "price_history" not in data:
        try:
            broker = _system.components.broker
            # TickerRegistry에서 정확한 거래소 코드를 가져온다
            exchange = "NAS"
            try:
                registry = _system.components.registry
                exchange = registry.get_exchange_code(ticker_upper)
            except (KeyError, AttributeError):
                pass
            candles = await broker.get_daily_candles(ticker_upper, days=60, exchange=exchange)
            if candles:
                data["price_history"] = [
                    {
                        "date": c.date if isinstance(c.date, str) else c.date.isoformat() if hasattr(c.date, "isoformat") else str(c.date),
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                    }
                    for c in candles
                ]
        except Exception:
            _logger.debug("가격 히스토리 보강 실패: %s", ticker_upper)

    # related_news 보강 — Flutter가 기대하는 형식으로 변환한다
    if "related_news" not in data:
        try:
            cache = _system.components.cache
            raw = await cache.read_json(f"news:{ticker_upper}")
            if isinstance(raw, list):
                data["related_news"] = raw[:10]
            else:
                # 전체 뉴스에서 해당 티커 관련 기사를 필터링한다
                # news:classified_latest는 원본 분류 형식(title, tickers_affected)이므로
                # Flutter 형식(headline, headline_kr, summary_ko, tickers)으로 변환한다
                all_news = await cache.read_json("news:classified_latest")
                if isinstance(all_news, list):
                    from src.orchestration.phases.news_pipeline import _to_flutter_article

                    filtered = [
                        a for a in all_news
                        if ticker_upper in (a.get("tickers_affected") or [])
                    ]
                    data["related_news"] = [
                        _to_flutter_article(a) for a in filtered[:10]
                    ]
        except Exception:
            _logger.debug("뉴스 보강 실패: %s", ticker_upper)

    return data


def _extract_readable_text(items: list) -> str:
    """추천/시그널 항목 목록에서 사람이 읽을 수 있는 텍스트를 추출한다.

    항목이 dict이면 title/detail/reason/content 필드를 우선 사용한다.
    str이면 중괄호로 시작하는 dict 표현인지 확인하고 JSON 파싱한다.
    """
    readable_parts: list[str] = []
    for item in items:
        if isinstance(item, dict):
            text = (
                item.get("title")
                or item.get("detail")
                or item.get("reason")
                or item.get("content")
                or item.get("headline_kr")
                or item.get("headline")
                or ""
            )
            if text:
                readable_parts.append(str(text))
        elif isinstance(item, str):
            # Claude가 dict를 str로 반환하는 경우 JSON 파싱 시도한다
            stripped = item.strip()
            if stripped.startswith("{"):
                try:
                    parsed = json.loads(stripped.replace("'", '"'))
                    if isinstance(parsed, dict):
                        text = (
                            parsed.get("title")
                            or parsed.get("detail")
                            or parsed.get("reason")
                            or ""
                        )
                        if text:
                            readable_parts.append(str(text))
                            continue
                except (json.JSONDecodeError, ValueError):
                    pass
            # 일반 문자열이면 그대로 사용한다
            if stripped and not stripped.startswith("{"):
                readable_parts.append(stripped)
    return "; ".join(readable_parts) if readable_parts else ""


def _extract_key_factors(signals: list[dict]) -> list[str]:
    """시그널 목록에서 핵심 요인 문자열 리스트를 추출한다.

    각 시그널의 headline_kr, reason, source 등을 사람이 읽을 수 있는 형태로 변환한다.
    """
    factors: list[str] = []
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        text = sig.get("headline_kr") or sig.get("reason") or ""
        if not text:
            action = sig.get("action", "")
            source = sig.get("source", "")
            if action or source:
                text = f"{action} ({source})" if source else action
        if text:
            factors.append(str(text))
    return factors


def _extract_action_from_signals(signals: list[dict]) -> str:
    """시그널 목록에서 매매 행동을 추출한다."""
    for signal in signals:
        action = signal.get("action", "").lower()
        if action in ("buy", "sell"):
            return action
    return "hold"


# ── 엔드포인트 ─────────────────────────────────────────────────────────────


@analysis_router.get("/tickers", response_model=AnalysisTickersResponse)
async def get_analysis_tickers() -> AnalysisTickersResponse:
    """분석 가능한 티커 목록을 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        registry = _system.components.registry
        universe = registry.get_universe()
        tickers = [
            TickerItem(ticker=m.ticker, name=m.name, sector=m.sector)
            for m in universe
        ]
        return AnalysisTickersResponse(tickers=tickers, count=len(tickers))
    except HTTPException:
        raise
    except Exception:
        _logger.exception("분석 가능 티커 조회 실패")
        raise HTTPException(status_code=500, detail="티커 조회 실패") from None


@analysis_router.get(
    "/comprehensive/{ticker}",
    response_model=ComprehensiveAnalysisResponse,
)
async def get_comprehensive_analysis(
    ticker: str,
    ai: bool = Query(default=True, description="AI 분석 활성화 여부"),
) -> ComprehensiveAnalysisResponse:
    """티커 종합 분석 결과를 반환한다.

    1. 캐시에서 조회한다 -- 30분 이내 결과가 있으면 즉시 반환한다.
    2. 캐시 미스 또는 stale이면 실시간 분석을 트리거한다:
       a. ComprehensiveTeam AI 분석 (ai=True일 때)
       b. IndicatorBundleBuilder 기술 지표 폴백
       c. yfinance 기본 시장 데이터 폴백
    3. 분석 결과를 30분 TTL로 캐시에 저장한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        ticker_upper = ticker.upper()
        cache = _system.components.cache
        cache_key = f"analysis:{ticker_upper}"

        # 1. 캐시에서 신선한 결과를 조회한다
        cached = await cache.read_json(cache_key)
        if cached and isinstance(cached, dict) and _is_cache_fresh(cached):
            _logger.debug("종합 분석 캐시 히트 (fresh): %s", ticker_upper)
            enriched = await _enrich_analysis_data(ticker_upper, cached)
            return ComprehensiveAnalysisResponse(
                ticker=ticker_upper,
                analysis=enriched,
                source="cache",
            )

        # 2. 캐시 미스 또는 stale -- 실시간 분석을 트리거한다
        _logger.info("종합 분석 캐시 미스/stale, 실시간 분석 시작: %s (ai=%s)", ticker_upper, ai)
        analysis_data: dict[str, Any] | None = None

        if ai:
            analysis_data = await _trigger_realtime_analysis(ticker_upper)
        else:
            # ai=False이면 기술 지표 기반만 시도한다
            analysis_data = await _try_indicator_based_analysis(ticker_upper)
            if analysis_data is None:
                analysis_data = await _try_kis_fallback(ticker_upper)

        if analysis_data is not None:
            # 2.5. 대시보드 렌더링에 필요한 부가 데이터를 보강한다
            analysis_data = await _enrich_analysis_data(ticker_upper, analysis_data)
            # 3. 결과를 캐시에 저장한다
            await cache.write_json(cache_key, analysis_data, ttl=_ANALYSIS_CACHE_TTL)
            _logger.info(
                "실시간 분석 완료 및 캐시 저장: %s (source=%s)",
                ticker_upper, analysis_data.get("source", "unknown"),
            )
            return ComprehensiveAnalysisResponse(
                ticker=ticker_upper,
                analysis=analysis_data,
                source=analysis_data.get("source", "realtime"),
            )

        # 모든 분석 방법 실패 -- stale 캐시가 있으면 반환한다
        if cached and isinstance(cached, dict):
            _logger.warning("실시간 분석 실패, stale 캐시 반환: %s", ticker_upper)
            enriched = await _enrich_analysis_data(ticker_upper, cached)
            return ComprehensiveAnalysisResponse(
                ticker=ticker_upper,
                analysis=enriched,
                source="cache_stale",
                message="캐시된 분석 결과가 오래되었다 (실시간 분석 실패)",
            )

        return ComprehensiveAnalysisResponse(
            ticker=ticker_upper,
            analysis=None,
            message="분석 데이터를 생성할 수 없다",
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("종합 분석 조회 실패: %s", ticker)
        raise HTTPException(status_code=500, detail="분석 조회 실패") from None


@analysis_router.get(
    "/ticker-news/{ticker}",
    response_model=TickerNewsResponse,
)
async def get_ticker_news(ticker: str, limit: int = 20) -> TickerNewsResponse:
    """티커별 관련 뉴스를 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json(f"news:{ticker}")
        articles = cached if isinstance(cached, list) else []
        return TickerNewsResponse(ticker=ticker, articles=articles[:limit])
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 뉴스 조회 실패: %s", ticker)
        raise HTTPException(status_code=500, detail="뉴스 조회 실패") from None
