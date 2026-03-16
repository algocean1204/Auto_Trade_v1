"""센티넬 룰 기반 + 로컬 AI 이상 감지기이다.

2분 주기로 시장 상태를 스캔하여 이상 신호를 감지한다.
룰 기반: 가격 급변, VIX 급변, 거래량 급증, 포지션 위험 근접
로컬 AI: Qwen2.5 + Llama3.1 + DeepSeek-R1 빠른 앙상블로 뉴스 헤드라인 긴급도 분류
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from src.analysis.sentinel.models import AnomalyResult, AnomalySignal, SentinelState
from src.common.logger import get_logger
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)

# ── 룰 임계값 ──
_PRICE_CHANGE_THRESHOLD: float = 2.0      # |변동률| >= 2.0%
_VIX_DELTA_THRESHOLD: float = 3.0         # |VIX 변화| >= 3.0pt
_VOLUME_SURGE_MULTIPLIER: float = 3.0     # 거래량 >= 평균의 300%
_HARDSTOP_PROXIMITY_PCT: float = -0.7     # 손실률 <= -0.7% (하드스톱 -1.0% 근접)
_PROFIT_TARGET_RATIO: float = 0.8         # 수익목표의 80% 도달
_VIX_FALLBACK: float = 20.0              # VIX 폴백값
_VIX_FALLBACK_TOLERANCE: float = 0.01    # 폴백 판정 허용 오차
_NEWS_URGENT_MIN_CONFIDENCE: float = 0.8  # 뉴스 urgent 최소 신뢰도 (watch=0.7보다 높아야 오탐 방지)
_MAX_HEADLINES_PER_SCAN: int = 15         # 스캔당 최대 분류 헤드라인 수

# 센티넬 감시 대상 지수 ETF이다
_WATCH_ETFS: list[str] = ["SPY", "QQQ"]


def _is_vix_fallback(value: float) -> bool:
    """VIX 값이 폴백값(20.0)인지 허용 오차 내에서 판별한다."""
    return abs(value - _VIX_FALLBACK) < _VIX_FALLBACK_TOLERANCE


async def detect_anomalies(
    system: InjectedSystem,
    state: SentinelState,
) -> tuple[AnomalyResult, float | None]:
    """룰 기반 + 로컬 AI로 이상 신호를 감지한다.

    각 룰은 독립적으로 실행되며, 하나가 실패해도 나머지는 계속 진행한다.
    state를 받아 이전 VIX/가격/헤드라인 해시를 참조하고 갱신한다.
    반환: (AnomalyResult, 갱신된 prev_vix)
    """
    signals: list[AnomalySignal] = []
    headlines_scanned = 0

    # 1. 가격 급변 감지 (스캔 간 변동 기반)
    price_signals = await _check_price_change(system, state)
    signals.extend(price_signals)

    # 2. VIX 급변 감지
    vix_signals, new_vix = await _check_vix_spike(system, state.last_vix)
    signals.extend(vix_signals)

    # 3. 거래량 급증 감지
    volume_signals = await _check_volume_surge(system)
    signals.extend(volume_signals)

    # 4. 포지션 위험 근접 감지
    position_signals = await _check_position_danger(system)
    signals.extend(position_signals)

    # 5. 로컬 AI 뉴스 헤드라인 스캔 (신규 헤드라인만, 중복 방지)
    news_signals, headlines_scanned = await _check_news_headlines(system, state)
    signals.extend(news_signals)

    # 최고 위험 수준 결정
    highest = "normal"
    for s in signals:
        if s.level == "urgent":
            highest = "urgent"
            break
        if s.level == "watch":
            highest = "watch"

    result = AnomalyResult(
        timestamp=datetime.now(tz=timezone.utc),
        signals=signals,
        highest_level=highest,
        news_headlines_scanned=headlines_scanned,
    )

    if signals:
        logger.info(
            "센티넬 감지: %d건 (최고=%s) %s",
            len(signals), highest,
            [f"{s.rule}:{s.ticker or 'N/A'}" for s in signals],
        )

    return result, new_vix


async def _check_price_change(
    system: InjectedSystem,
    state: SentinelState,
) -> list[AnomalySignal]:
    """보유 포지션 + 감시 ETF의 가격 급변을 감지한다.

    전일 대비 change_pct가 아닌, 이전 센티넬 스캔 대비 변동을 추적한다.
    이전 가격이 없으면 (첫 실행) 현재 가격만 저장하고 스킵한다.
    가격 조회 실패 시 해당 티커를 스킵한다 (false positive 방지).
    """
    signals: list[AnomalySignal] = []
    broker = system.components.broker

    # 감시 대상: 보유 포지션 티커 + 지수 ETF
    tickers: set[str] = set(_WATCH_ETFS)
    monitor = system.features.get("position_monitor")
    if monitor is not None:
        try:
            positions = monitor.get_all_positions()
            tickers.update(positions.keys())
        except Exception as exc:
            logger.debug("포지션 조회 실패 (가격 체크 스킵): %s", exc)

    for ticker in tickers:
        try:
            price = await broker.virtual_client.get_current_price(ticker)
            current_price = getattr(price, "current_price", None) or getattr(price, "last", 0.0)

            if current_price <= 0:
                continue

            prev_price = state.last_prices.get(ticker)

            # 현재 가격 저장 (다음 스캔에서 비교용)
            state.last_prices[ticker] = current_price

            if prev_price is None or prev_price <= 0:
                # 첫 실행: 기준 가격만 저장하고 트리거 안 한다
                continue

            # 이전 스캔 대비 변동률 계산
            delta_pct = ((current_price - prev_price) / prev_price) * 100

            if abs(delta_pct) >= _PRICE_CHANGE_THRESHOLD:
                direction = "급등" if delta_pct > 0 else "급락"
                signals.append(AnomalySignal(
                    rule="price_crash" if delta_pct < 0 else "price_surge",
                    level="urgent",
                    detail=f"{ticker} {direction} {delta_pct:+.2f}% (2분 내)",
                    value=delta_pct,
                    threshold=_PRICE_CHANGE_THRESHOLD,
                    ticker=ticker,
                ))
        except Exception as exc:
            logger.debug("가격 조회 실패 %s (스킵): %s", ticker, exc)

    return signals


async def _check_vix_spike(
    system: InjectedSystem,
    prev_vix: float | None,
) -> tuple[list[AnomalySignal], float | None]:
    """VIX 급변(±3pt 이상)을 감지한다.

    이전 VIX가 없으면 (첫 실행) 현재값만 저장하고 스킵한다.
    VIX 조회 실패 시 트리거하지 않는다 (false positive 방지).
    VIX 폴백값(20.0 ± 0.01)은 실제 관측이 아니므로 비교하지 않는다.
    """
    signals: list[AnomalySignal] = []
    vf = system.features.get("vix_fetcher")
    if vf is None:
        return signals, prev_vix

    try:
        current_vix = await vf.get_vix()
    except Exception as exc:
        logger.debug("VIX 조회 실패 (스킵): %s", exc)
        return signals, prev_vix

    # 폴백값이면 실제 데이터가 아니므로 비교 안 한다
    if _is_vix_fallback(current_vix):
        logger.debug("VIX 폴백값 감지 — 비교 스킵")
        return signals, prev_vix

    if prev_vix is None:
        # 첫 실행: 기준값만 저장하고 트리거 안 한다
        logger.debug("VIX 기준값 설정: %.2f", current_vix)
        return signals, current_vix

    # 이전값도 폴백이었으면 비교하지 않는다
    if _is_vix_fallback(prev_vix):
        return signals, current_vix

    delta = current_vix - prev_vix
    if abs(delta) >= _VIX_DELTA_THRESHOLD:
        direction = "급등" if delta > 0 else "급락"
        signals.append(AnomalySignal(
            rule="vix_spike",
            level="urgent",
            detail=f"VIX {direction}: {prev_vix:.1f} → {current_vix:.1f} (Δ{delta:+.1f})",
            value=delta,
            threshold=_VIX_DELTA_THRESHOLD,
        ))

    return signals, current_vix


async def _check_volume_surge(system: InjectedSystem) -> list[AnomalySignal]:
    """감시 ETF + 보유 포지션의 거래량 급증(300%+)을 감지한다.

    avg_volume이 0이거나 없으면 해당 티커를 스킵한다 (ZeroDivision 방지).
    """
    signals: list[AnomalySignal] = []
    broker = system.components.broker

    tickers: set[str] = set(_WATCH_ETFS)
    monitor = system.features.get("position_monitor")
    if monitor is not None:
        try:
            positions = monitor.get_all_positions()
            tickers.update(positions.keys())
        except Exception:
            pass

    for ticker in tickers:
        try:
            price = await broker.virtual_client.get_current_price(ticker)
            avg_vol = getattr(price, "avg_volume", 0)
            if avg_vol <= 0:
                continue
            ratio = price.volume / avg_vol
            if ratio >= _VOLUME_SURGE_MULTIPLIER:
                signals.append(AnomalySignal(
                    rule="volume_surge",
                    level="watch",
                    detail=f"{ticker} 거래량 급증: {ratio:.1f}x (평균 대비)",
                    value=ratio,
                    threshold=_VOLUME_SURGE_MULTIPLIER,
                    ticker=ticker,
                ))
        except Exception as exc:
            logger.debug("거래량 조회 실패 %s (스킵): %s", ticker, exc)

    return signals


async def _check_position_danger(system: InjectedSystem) -> list[AnomalySignal]:
    """보유 포지션의 하드스톱/수익목표 근접을 감지한다.

    포지션이 없으면 스킵한다.
    레짐별 take_profit을 조회하여 수익목표를 동적으로 적용한다.
    VIX 폴백값 사용 시 기본 take_profit을 적용한다.
    """
    signals: list[AnomalySignal] = []
    monitor = system.features.get("position_monitor")
    if monitor is None:
        return signals

    try:
        positions = monitor.get_all_positions()
    except Exception as exc:
        logger.debug("포지션 조회 실패 (위험 체크 스킵): %s", exc)
        return signals

    if not positions:
        return signals

    # 레짐별 take_profit 조회 (VIX 폴백이면 기본값 유지)
    take_profit = 3.0  # 기본값
    detector = system.features.get("regime_detector")
    if detector is not None:
        try:
            vf = system.features.get("vix_fetcher")
            vix = _VIX_FALLBACK
            if vf is not None:
                vix = await vf.get_vix()
            # 폴백값이면 기본 take_profit을 사용한다 (잘못된 레짐 판별 방지)
            if not _is_vix_fallback(vix):
                regime = detector.detect(vix_value=vix)
                take_profit = regime.params.take_profit
        except Exception:
            pass

    for ticker, pos in positions.items():
        # 하드스톱 근접: pnl_pct <= -0.7%
        if pos.pnl_pct <= _HARDSTOP_PROXIMITY_PCT:
            signals.append(AnomalySignal(
                rule="position_danger",
                level="urgent",
                detail=f"{ticker} 하드스톱 근접: PnL {pos.pnl_pct:.2f}% (스톱 -1.0%)",
                value=pos.pnl_pct,
                threshold=_HARDSTOP_PROXIMITY_PCT,
                ticker=ticker,
            ))
        # 수익목표 근접: pnl_pct >= take_profit * 0.8
        elif pos.pnl_pct >= take_profit * _PROFIT_TARGET_RATIO:
            signals.append(AnomalySignal(
                rule="profit_target_near",
                level="watch",
                detail=f"{ticker} 수익목표 근접: PnL {pos.pnl_pct:.2f}% (목표 {take_profit:.1f}%)",
                value=pos.pnl_pct,
                threshold=take_profit * _PROFIT_TARGET_RATIO,
                ticker=ticker,
            ))

    return signals


def _hash_headline(title: str) -> str:
    """헤드라인 제목의 SHA-256 해시를 반환한다."""
    return hashlib.sha256(title.encode()).hexdigest()[:16]


async def _check_news_headlines(
    system: InjectedSystem,
    state: SentinelState,
) -> tuple[list[AnomalySignal], int]:
    """로컬 AI 빠른 앙상블로 신규 뉴스 헤드라인의 긴급도를 분류한다.

    Qwen2.5 + Llama3.1 + DeepSeek-R1 3모델 빠른 앙상블(200자 제한)로
    urgent/watch/normal을 분류한다.
    이미 분류한 헤드라인은 해시로 추적하여 중복 분류를 방지한다.
    스캔당 최대 15건으로 제한하여 2분 예산을 보호한다.
    """
    signals: list[AnomalySignal] = []

    # 캐시에서 최근 헤드라인 읽기
    cache = system.components.cache
    try:
        cached = await cache.read_json("news:latest_titles")
        if not cached or not isinstance(cached, list):
            return signals, 0
        headlines: list[str] = cached[:50]
    except Exception as exc:
        logger.warning("헤드라인 캐시 읽기 실패 (스킵): %s", exc)
        return signals, 0

    if not headlines:
        return signals, 0

    # 신규 헤드라인만 필터링 (이미 분류한 것 제외)
    new_headlines: list[str] = []
    for title in headlines:
        h = _hash_headline(title)
        if h not in state.seen_headline_hashes:
            new_headlines.append(title)
            state.add_seen_hash(h)

    if not new_headlines:
        return signals, 0

    # 스캔당 최대 분류 수 제한 (2분 예산 보호)
    to_classify = new_headlines[:_MAX_HEADLINES_PER_SCAN]

    # 빠른 로컬 AI 앙상블 분류 (200자 제한, 속도 우선)
    ai = system.components.ai
    categories = ["urgent", "watch", "normal"]

    for title in to_classify:
        try:
            result = await ai.fast_local_classify(title, categories)
            if result.category == "urgent" and result.confidence >= _NEWS_URGENT_MIN_CONFIDENCE:
                signals.append(AnomalySignal(
                    rule="news_urgent",
                    level="urgent",
                    detail=f"긴급 뉴스: {title[:80]}",
                    value=result.confidence,
                    threshold=_NEWS_URGENT_MIN_CONFIDENCE,
                ))
            elif result.category == "watch" and result.confidence >= 0.7:
                signals.append(AnomalySignal(
                    rule="news_watch",
                    level="watch",
                    detail=f"주의 뉴스: {title[:80]}",
                    value=result.confidence,
                    threshold=0.7,
                ))
        except Exception as exc:
            logger.warning("헤드라인 분류 실패 '%s' (스킵): %s", title[:30], exc)

    logger.info(
        "뉴스 헤드라인 스캔: 전체=%d, 신규=%d, 분류=%d, 신호=%d",
        len(headlines), len(new_headlines), len(to_classify), len(signals),
    )
    return signals, len(to_classify)
