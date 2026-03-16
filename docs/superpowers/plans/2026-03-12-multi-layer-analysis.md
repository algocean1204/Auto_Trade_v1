# 다계층 분석 아키텍처 구현 계획

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sonnet 5개 순차 → 센티넬(2분) + Sonnet 4병렬 + Opus 3+1 다계층 분석 아키텍처로 교체한다.

**Architecture:** Layer 0(로컬AI+룰) → Layer 0.5(Sonnet 평가) → Layer 1(Sonnet 4병렬) → Layer 2(Opus 3+1). 센티넬 2분 루프와 정밀 분석 60분 루프가 독립 동작하며, 긴급 시 에스컬레이션 경로로 연결된다.

**Tech Stack:** Python 3.12, asyncio, MLX (Qwen2.5-7B), Claude Sonnet/Opus via AiClient, Redis, Pydantic

---

## Chunk 1: 센티넬 모델 + 룰 기반 이상 감지

### Task 1: 센티넬 Pydantic 모델 정의

**Files:**
- Create: `src/analysis/sentinel/__init__.py`
- Create: `src/analysis/sentinel/models.py`

- [ ] **Step 1: __init__.py 생성**

```python
"""센티넬 이상 감지 패키지이다."""
```

- [ ] **Step 2: models.py 생성**

```python
"""센티넬 이상 감지 모델이다."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel


class AnomalySignal(BaseModel):
    """단일 이상 신호이다."""

    rule: str                    # "price_crash", "vix_spike", "volume_surge", "position_danger", "news_urgent"
    level: Literal["urgent", "watch", "normal"]
    detail: str                  # 사람이 읽을 수 있는 설명
    value: float                 # 감지된 수치 (change_pct, vix_delta 등)
    threshold: float             # 임계값
    ticker: str = ""             # 관련 티커 (없으면 빈 문자열)


class AnomalyResult(BaseModel):
    """센티넬 1회 스캔 결과이다."""

    timestamp: datetime
    signals: list[AnomalySignal] = []
    highest_level: Literal["urgent", "watch", "normal"] = "normal"
    news_headlines_scanned: int = 0

    @property
    def has_anomaly(self) -> bool:
        """urgent 또는 watch 신호가 있는지 반환한다."""
        return self.highest_level != "normal"


class EscalationResult(BaseModel):
    """Sonnet 에스컬레이션 평가 결과이다."""

    action_needed: bool
    urgency: Literal["emergency", "next_cycle", "ignore"]
    reasoning: str
    suggested_action: str = ""   # "sell SOXL", "buy SQQQ" 등
    ticker: str = ""


class SentinelState(BaseModel):
    """센티넬 루프 상태이다."""

    iterations: int = 0
    anomalies_detected: int = 0
    escalations_triggered: int = 0
    emergencies_triggered: int = 0
    last_vix: float | None = None  # 이전 VIX 값 (급변 감지용)
    errors: list[str] = []
```

- [ ] **Step 3: 커밋**

```bash
git add src/analysis/sentinel/__init__.py src/analysis/sentinel/models.py
git commit -m "feat: 센티넬 이상 감지 Pydantic 모델 정의"
```

---

### Task 2: 룰 기반 이상 감지기 구현

**Files:**
- Create: `src/analysis/sentinel/anomaly_detector.py`

- [ ] **Step 1: anomaly_detector.py 생성**

```python
"""센티넬 룰 기반 + 로컬 AI 이상 감지기이다.

2분 주기로 시장 상태를 스캔하여 이상 신호를 감지한다.
룰 기반: 가격 급변, VIX 급변, 거래량 급증, 포지션 위험 근접
로컬 AI: Qwen2.5 단일 모델로 뉴스 헤드라인 긴급도 분류
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.sentinel.models import AnomalyResult, AnomalySignal
from src.common.logger import get_logger
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)

# ── 룰 임계값 ──
_PRICE_CHANGE_THRESHOLD: float = 2.0      # |변동률| >= 2.0%
_VIX_DELTA_THRESHOLD: float = 3.0         # |VIX 변화| >= 3.0pt
_VOLUME_SURGE_MULTIPLIER: float = 3.0     # 거래량 >= 평균의 300%
_HARDSTOP_PROXIMITY_PCT: float = -0.7     # 손실률 <= -0.7% (하드스톱 -1.0% 근접)
_PROFIT_TARGET_RATIO: float = 0.8         # 수익목표의 80% 도달

# 센티넬 감시 대상 지수 ETF이다
_WATCH_ETFS: list[str] = ["SPY", "QQQ"]

# Redis 키이다
_VIX_PREV_KEY: str = "sentinel:vix_prev"
_VIX_PREV_TTL: int = 600  # 10분 (2분 주기 × 5회분 보존)


async def detect_anomalies(
    system: InjectedSystem,
    prev_vix: float | None = None,
) -> AnomalyResult:
    """룰 기반 + 로컬 AI로 이상 신호를 감지한다.

    각 룰은 독립적으로 실행되며, 하나가 실패해도 나머지는 계속 진행한다.
    """
    signals: list[AnomalySignal] = []
    headlines_scanned = 0

    # 1. 가격 급변 감지
    price_signals = await _check_price_change(system)
    signals.extend(price_signals)

    # 2. VIX 급변 감지
    vix_signals, new_vix = await _check_vix_spike(system, prev_vix)
    signals.extend(vix_signals)

    # 3. 거래량 급증 감지
    volume_signals = await _check_volume_surge(system)
    signals.extend(volume_signals)

    # 4. 포지션 위험 근접 감지
    position_signals = await _check_position_danger(system)
    signals.extend(position_signals)

    # 5. 로컬 AI 뉴스 헤드라인 스캔
    news_signals, headlines_scanned = await _check_news_headlines(system)
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
            [f"{s.rule}:{s.ticker}" for s in signals],
        )

    return result


async def _check_price_change(system: InjectedSystem) -> list[AnomalySignal]:
    """보유 포지션 + 감시 ETF의 가격 급변을 감지한다."""
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
            change = abs(price.change_pct)
            if change >= _PRICE_CHANGE_THRESHOLD:
                direction = "급등" if price.change_pct > 0 else "급락"
                signals.append(AnomalySignal(
                    rule="price_crash" if price.change_pct < 0 else "price_surge",
                    level="urgent",
                    detail=f"{ticker} {direction} {price.change_pct:+.2f}%",
                    value=price.change_pct,
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

    if prev_vix is None:
        # 첫 실행: 기준값만 저장하고 트리거 안 함
        logger.debug("VIX 기준값 설정: %.2f", current_vix)
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
    """감시 ETF + 보유 포지션의 거래량 급증(300%+)을 감지한다."""
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
    """보유 포지션의 하드스톱/수익목표 근접을 감지한다."""
    signals: list[AnomalySignal] = []
    monitor = system.features.get("position_monitor")
    if monitor is None:
        return signals

    try:
        positions = monitor.get_all_positions()
    except Exception as exc:
        logger.debug("포지션 조회 실패 (위험 체크 스킵): %s", exc)
        return signals

    # 레짐별 take_profit 조회
    take_profit = 3.0  # 기본값
    detector = system.features.get("regime_detector")
    if detector is not None:
        try:
            vf = system.features.get("vix_fetcher")
            vix = 20.0
            if vf is not None:
                vix = await vf.get_vix()
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
                rule="position_danger",
                level="watch",
                detail=f"{ticker} 수익목표 근접: PnL {pos.pnl_pct:.2f}% (목표 {take_profit:.1f}%)",
                value=pos.pnl_pct,
                threshold=take_profit * _PROFIT_TARGET_RATIO,
                ticker=ticker,
            ))

    return signals


async def _check_news_headlines(
    system: InjectedSystem,
) -> tuple[list[AnomalySignal], int]:
    """로컬 AI로 신규 뉴스 헤드라인의 긴급도를 분류한다.

    Qwen2.5 단일 모델로 빠르게 urgent/watch/normal 분류한다.
    앙상블 3모델 대신 단일 모델을 사용하여 속도를 우선한다.
    """
    signals: list[AnomalySignal] = []

    # fast_mode 크롤링으로 헤드라인 수집
    try:
        headlines = await _fetch_fresh_headlines(system)
    except Exception as exc:
        logger.debug("헤드라인 수집 실패 (스킵): %s", exc)
        return signals, 0

    if not headlines:
        return signals, 0

    # 로컬 AI 분류 (단일 모델, 속도 우선)
    ai = system.components.ai
    categories = ["urgent", "watch", "normal"]

    for title in headlines:
        try:
            result = await ai.local_classify(title, categories)
            if result.category == "urgent":
                signals.append(AnomalySignal(
                    rule="news_urgent",
                    level="urgent",
                    detail=f"긴급 뉴스: {title[:80]}",
                    value=result.confidence,
                    threshold=0.5,
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
            logger.debug("헤드라인 분류 실패 (스킵): %s", exc)

    return signals, len(headlines)


async def _fetch_fresh_headlines(system: InjectedSystem) -> list[str]:
    """fast_mode 크롤링으로 최신 헤드라인 제목 목록을 가져온다.

    기존 뉴스 파이프라인의 크롤링 엔진을 재사용하되,
    검증/분류 없이 제목만 빠르게 추출한다.
    """
    crawl_engine = system.features.get("crawl_engine")
    scheduler = system.features.get("crawl_scheduler")
    if crawl_engine is None or scheduler is None:
        return []

    schedule = scheduler.build_schedule(fast_mode=True)
    result = await crawl_engine.run(schedule)

    if result.new_count == 0:
        return []

    # EventBus로 발행된 기사 제목을 Redis에서 읽거나,
    # 크롤 결과에서 직접 제목 추출한다
    # 여기서는 Redis 캐시된 최신 기사 제목을 읽는다
    cache = system.components.cache
    try:
        cached = await cache.read_json("news:latest_titles")
        if cached and isinstance(cached, list):
            return cached[:30]  # 최대 30개 헤드라인
    except Exception:
        pass

    return []
```

- [ ] **Step 2: 커밋**

```bash
git add src/analysis/sentinel/anomaly_detector.py
git commit -m "feat: 센티넬 룰 기반 + 로컬 AI 이상 감지기 구현"
```

---

### Task 3: Sonnet 에스컬레이션 + Opus 긴급 판단

**Files:**
- Create: `src/analysis/sentinel/escalation.py`

- [ ] **Step 1: escalation.py 생성**

```python
"""센티넬 에스컬레이션 -- Sonnet 평가 + Opus 긴급 판단이다.

센티넬이 urgent/watch 신호를 감지하면 Sonnet이 평가하고,
emergency 판정 시 Opus 1명이 즉시 긴급 매매 판단을 내린다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.analysis.models import ComprehensiveReport
from src.analysis.sentinel.models import AnomalyResult, EscalationResult
from src.common.ai_gateway import AiClient
from src.common.logger import get_logger
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)


async def evaluate_anomaly(
    ai: AiClient,
    anomaly: AnomalyResult,
    system: InjectedSystem,
) -> EscalationResult:
    """Sonnet으로 이상 신호를 평가하여 긴급도를 판정한다."""
    # 포지션 정보 수집
    positions_text = "보유 포지션 없음"
    monitor = system.features.get("position_monitor")
    if monitor is not None:
        try:
            positions = monitor.get_all_positions()
            if positions:
                lines = [f"  {t}: {p.quantity}주, PnL {p.pnl_pct:+.2f}%" for t, p in positions.items()]
                positions_text = "\n".join(lines)
        except Exception:
            pass

    signals_text = "\n".join(
        f"- [{s.level}] {s.rule}: {s.detail}" for s in anomaly.signals
    )

    prompt = (
        "너는 미국 2X 레버리지 ETF 단타 트레이딩 시스템의 긴급 평가관이다.\n\n"
        "센티넬이 아래 이상 신호를 감지했다. 매매 행동이 필요한 수준인지 판단하라.\n\n"
        f"[감지된 이상 신호]\n{signals_text}\n\n"
        f"[현재 보유 포지션]\n{positions_text}\n\n"
        "반드시 아래 JSON만 출력하라:\n"
        "{\n"
        '  "action_needed": true/false,\n'
        '  "urgency": "emergency" | "next_cycle" | "ignore",\n'
        '  "reasoning": "한국어 판단 근거 (2~3문장)",\n'
        '  "suggested_action": "sell SOXL" 또는 "buy SQQQ" 등 (action_needed=false면 빈 문자열)",\n'
        '  "ticker": "관련 티커 (없으면 빈 문자열)"\n'
        "}\n\n"
        "판단 기준:\n"
        "- emergency: 즉시 매매 안 하면 큰 손실 위험 (하드스톱 임박, 급락 진행 중)\n"
        "- next_cycle: 중요하지만 다음 정기 분석(60분)에서 반영해도 늦지 않음\n"
        "- ignore: 일시적 노이즈, 이미 반영됨, 또는 오판\n"
    )

    try:
        response = await ai.send_text(prompt, model="sonnet", max_tokens=512)
        parsed = _parse_json(response.content)

        result = EscalationResult(
            action_needed=parsed.get("action_needed", False),
            urgency=parsed.get("urgency", "ignore"),
            reasoning=parsed.get("reasoning", ""),
            suggested_action=parsed.get("suggested_action", ""),
            ticker=parsed.get("ticker", ""),
        )
        logger.info(
            "에스컬레이션 평가: urgency=%s, action=%s, reason=%s",
            result.urgency, result.suggested_action, result.reasoning[:60],
        )
        return result

    except Exception as exc:
        logger.warning("에스컬레이션 Sonnet 호출 실패: %s", exc)
        # Sonnet 실패 시 urgent 신호가 있으면 안전하게 next_cycle로 처리한다
        return EscalationResult(
            action_needed=True,
            urgency="next_cycle",
            reasoning=f"Sonnet 평가 실패, 안전하게 다음 정기 분석에 반영: {exc}",
        )


async def emergency_opus_judgment(
    ai: AiClient,
    anomaly: AnomalyResult,
    escalation: EscalationResult,
    system: InjectedSystem,
) -> ComprehensiveReport:
    """Opus 1명이 긴급 매매 판단을 내린다.

    정기 분석의 3+1 팀이 아닌, 리더 1명만 즉시 호출한다.
    결과는 ComprehensiveReport 형태로 반환하여 기존 파이프라인과 호환한다.
    """
    positions_text = "없음"
    monitor = system.features.get("position_monitor")
    if monitor is not None:
        try:
            positions = monitor.get_all_positions()
            if positions:
                lines = [f"  {t}: {p.quantity}주, 평균가 ${p.avg_price:.2f}, PnL {p.pnl_pct:+.2f}%" for t, p in positions.items()]
                positions_text = "\n".join(lines)
        except Exception:
            pass

    signals_text = "\n".join(f"- {s.detail}" for s in anomaly.signals)

    prompt = (
        "너는 미국 2X 레버리지 ETF 전문 긴급 트레이더이다.\n"
        "지금 즉각적인 매매 판단이 필요한 긴급 상황이다.\n\n"
        f"[긴급 상황]\n{signals_text}\n\n"
        f"[Sonnet 평가]\n{escalation.reasoning}\n"
        f"제안 행동: {escalation.suggested_action}\n\n"
        f"[보유 포지션]\n{positions_text}\n\n"
        "반드시 아래 JSON만 출력하라:\n"
        "{\n"
        '  "signals": [{"action": "sell/buy/hold", "ticker": "종목코드", "reason": "한국어 이유"}],\n'
        '  "confidence": 0.0~1.0,\n'
        '  "recommendations": ["구체적 행동 지시 (한국어)"],\n'
        '  "risk_level": "low" | "medium" | "high" | "critical",\n'
        '  "regime_assessment": "현재 시장 상태 한줄 평가 (한국어)"\n'
        "}\n\n"
        "핵심 원칙: 자본 보전 최우선. 확신 없으면 hold.\n"
    )

    try:
        response = await ai.send_text(prompt, model="opus", max_tokens=1024)
        parsed = _parse_json(response.content)

        report = ComprehensiveReport(
            signals=parsed.get("signals", []),
            confidence=parsed.get("confidence", 0.5),
            recommendations=parsed.get("recommendations", []),
            regime_assessment=parsed.get("regime_assessment", "긴급 판단"),
            risk_level=parsed.get("risk_level", "high"),
            timestamp=datetime.now(tz=timezone.utc),
        )
        logger.info(
            "긴급 Opus 판단: confidence=%.2f, risk=%s, signals=%d",
            report.confidence, report.risk_level, len(report.signals),
        )
        return report

    except Exception as exc:
        logger.error("긴급 Opus 판단 실패: %s", exc)
        # Opus 실패 시 보수적 hold 판단을 반환한다
        return ComprehensiveReport(
            signals=[{"action": "hold", "ticker": "", "reason": f"Opus 호출 실패: {exc}"}],
            confidence=0.3,
            recommendations=["Opus 긴급 판단 실패 — 포지션 유지, 다음 정기 분석 대기"],
            regime_assessment="긴급 판단 불가",
            risk_level="high",
            timestamp=datetime.now(tz=timezone.utc),
        )


def _parse_json(raw: str) -> dict:
    """AI 응답에서 JSON을 파싱한다."""
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.warning("JSON 파싱 실패: %s", raw[:200])
        return {}
```

- [ ] **Step 2: 커밋**

```bash
git add src/analysis/sentinel/escalation.py
git commit -m "feat: Sonnet 에스컬레이션 + Opus 긴급 판단 구현"
```

---

### Task 4: 센티넬 루프

**Files:**
- Create: `src/orchestration/loops/sentinel_loop.py`

- [ ] **Step 1: sentinel_loop.py 생성**

```python
"""센티넬 루프 -- 2분 주기 이상 감지 루프이다.

매매 윈도우 내에서 룰 기반 + 로컬 AI로 시장 이상을 감지하고,
urgent 신호 발생 시 Sonnet → Opus 에스컬레이션 경로를 실행한다.
"""
from __future__ import annotations

import asyncio

from src.analysis.sentinel.anomaly_detector import detect_anomalies
from src.analysis.sentinel.escalation import (
    emergency_opus_judgment,
    evaluate_anomaly,
)
from src.analysis.sentinel.models import SentinelState
from src.common.logger import get_logger
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)

_SENTINEL_INTERVAL_SECONDS: int = 120  # 2분
_SENTINEL_SESSIONS: frozenset[str] = frozenset({
    "pre_market", "power_open", "mid_day", "power_hour", "final_monitoring",
})


async def run_sentinel_loop(
    system: InjectedSystem,
    shutdown_event: asyncio.Event,
) -> SentinelState:
    """2분 주기 센티넬 루프를 실행한다.

    매매 윈도우 내에서만 동작하고, shutdown_event가 set되면 종료한다.
    """
    state = SentinelState()
    logger.info("센티넬 루프 시작 (주기=%d초)", _SENTINEL_INTERVAL_SECONDS)

    while not shutdown_event.is_set():
        time_info = system.components.clock.get_time_info()

        # preparation 세션이면 대기 후 재확인한다
        if time_info.session_type == "preparation":
            if await _wait_or_shutdown(shutdown_event, 60):
                break
            continue

        # 매매 윈도우 밖이면 종료한다
        if time_info.session_type not in _SENTINEL_SESSIONS:
            logger.info("센티넬: 매매 윈도우 외 (%s) -- 종료", time_info.session_type)
            break

        await _run_single_scan(system, state)

        if await _wait_or_shutdown(shutdown_event, _SENTINEL_INTERVAL_SECONDS):
            break

    logger.info(
        "센티넬 루프 종료: %d회 스캔, %d 이상 감지, %d 에스컬레이션, %d 긴급",
        state.iterations, state.anomalies_detected,
        state.escalations_triggered, state.emergencies_triggered,
    )
    return state


async def _run_single_scan(
    system: InjectedSystem,
    state: SentinelState,
) -> None:
    """단일 센티넬 스캔을 실행한다."""
    try:
        anomaly = await detect_anomalies(system, prev_vix=state.last_vix)
        state.iterations += 1

        # VIX 이전값 업데이트 (다음 스캔에서 비교용)
        vf = system.features.get("vix_fetcher")
        if vf is not None:
            try:
                state.last_vix = await vf.get_vix()
            except Exception:
                pass

        if not anomaly.has_anomaly:
            return

        state.anomalies_detected += 1

        # urgent 신호만 에스컬레이션한다
        if anomaly.highest_level != "urgent":
            # watch 신호는 Redis에 저장하여 다음 정기 분석에 반영한다
            await _store_watch_signals(system, anomaly)
            return

        # Sonnet 에스컬레이션 평가
        state.escalations_triggered += 1
        escalation = await evaluate_anomaly(system.components.ai, anomaly, system)

        if escalation.urgency == "ignore":
            logger.info("센티넬: Sonnet이 ignore 판정 — 무시")
            return

        if escalation.urgency == "next_cycle":
            logger.info("센티넬: 다음 정기 분석에 우선 반영")
            await _store_priority_signals(system, anomaly, escalation)
            return

        # emergency → Opus 긴급 판단
        if escalation.urgency == "emergency":
            state.emergencies_triggered += 1
            logger.warning("센티넬: EMERGENCY — Opus 긴급 판단 시작")
            report = await emergency_opus_judgment(
                system.components.ai, anomaly, escalation, system,
            )
            # 긴급 보고서를 Redis에 저장하여 TradingLoop이 즉시 소비하도록 한다
            await system.components.cache.write_json(
                "analysis:comprehensive_report",
                report.model_dump(mode="json"),
                ttl=300,  # 5분 TTL (긴급이므로 짧게)
            )
            # 텔레그램 긴급 알림
            try:
                telegram = system.components.telegram
                await telegram.send_text(
                    f"🚨 센티넬 긴급 판단\n"
                    f"신호: {anomaly.signals[0].detail}\n"
                    f"Opus 판단: {report.recommendations[0] if report.recommendations else 'N/A'}\n"
                    f"신뢰도: {report.confidence:.0%}",
                )
            except Exception as exc:
                logger.warning("긴급 텔레그램 전송 실패: %s", exc)

    except Exception as exc:
        msg = f"센티넬 스캔 실패: {exc}"
        logger.error(msg)
        state.errors.append(msg)


async def _store_watch_signals(
    system: InjectedSystem,
    anomaly: AnomalyResult,
) -> None:
    """watch 수준 신호를 Redis에 저장한다."""
    data = [s.model_dump(mode="json") for s in anomaly.signals if s.level == "watch"]
    if data:
        await system.components.cache.write_json("sentinel:watch", data, ttl=3600)


async def _store_priority_signals(
    system: InjectedSystem,
    anomaly: AnomalyResult,
    escalation: object,
) -> None:
    """next_cycle로 판정된 신호를 Redis에 우선순위로 저장한다."""
    data = {
        "signals": [s.model_dump(mode="json") for s in anomaly.signals],
        "escalation_reasoning": getattr(escalation, "reasoning", ""),
    }
    await system.components.cache.write_json("sentinel:priority", data, ttl=7200)


async def _wait_or_shutdown(
    shutdown_event: asyncio.Event,
    seconds: int,
) -> bool:
    """대기 중 shutdown 이벤트가 발생하면 True를 반환한다."""
    try:
        await asyncio.wait_for(shutdown_event.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False
```

- [ ] **Step 2: 커밋**

```bash
git add src/orchestration/loops/sentinel_loop.py
git commit -m "feat: 2분 주기 센티넬 루프 구현"
```

---

## Chunk 2: Sonnet 4병렬 + Opus 3+1 팀

### Task 5: Opus 3+1 판단 팀

**Files:**
- Create: `src/analysis/team/opus_judgment.py`

- [ ] **Step 1: opus_judgment.py 생성**

```python
"""Opus 3+1 최종 판단 팀이다.

3명의 독립 분석가(공격형/균형형/보수형)가 병렬로 판단하고,
리더가 3의견을 종합하여 ComprehensiveReport를 생성한다.
앵커링 편향 방지를 위해 3명은 서로의 의견을 모른다.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from src.analysis.models import ComprehensiveReport
from src.common.ai_gateway import AiClient
from src.common.logger import get_logger

logger = get_logger(__name__)


_AGGRESSIVE_PROMPT = (
    "너는 공격형 2X 레버리지 ETF 트레이더이다.\n"
    "기회를 적극 포착하되, 리스크 대비 수익이 2:1 이상인 경우에만 진입한다.\n"
    "변동성은 기회다. 급락 시 인버스, 급등 시 불 포지션을 적극 활용한다.\n"
    "확신도 0.6 이상이면 매매를 추천한다.\n"
)

_BALANCED_PROMPT = (
    "너는 균형형 2X 레버리지 ETF 트레이더이다.\n"
    "리스크와 수익의 균형을 최우선으로 한다.\n"
    "레짐, VIX, 기술적 지표, 뉴스를 종합 판단한다.\n"
    "확신도 0.7 이상이면 매매를 추천한다.\n"
)

_CONSERVATIVE_PROMPT = (
    "너는 보수형 2X 레버리지 ETF 트레이더이다.\n"
    "자본 보전이 절대 원칙이다. 확실한 기회만 잡는다.\n"
    "불확실하면 무조건 hold. 하방 리스크를 항상 먼저 평가한다.\n"
    "확신도 0.85 이상이면 매매를 추천한다.\n"
)

_LEADER_PROMPT = (
    "너는 미국 2X 레버리지 ETF 매매 팀의 리더이다.\n"
    "3명의 독립 분석가(공격형/균형형/보수형)가 각자 판단한 결과를 받았다.\n"
    "이들의 의견을 종합하여 최종 매매 판단을 내려야 한다.\n\n"
    "종합 원칙:\n"
    "- 3명 만장일치 → 높은 확신도로 실행\n"
    "- 2:1 다수결 → 다수 의견 채택하되 반대 의견의 리스크 포인트 반영\n"
    "- 3명 모두 다른 의견 → hold (확신 부족)\n"
    "- 보수형이 critical risk 경고 시 → 무조건 hold (거부권)\n"
    "- 자본 보전 > 수익 극대화\n"
)


async def opus_team_judgment(
    ai: AiClient,
    layer1_reports: dict[str, str],
    context: dict,
) -> ComprehensiveReport:
    """Opus 3+1 팀이 Layer 1 분석을 기반으로 최종 판단한다.

    Phase 1: 3명 독립 병렬 판단 (앵커링 방지)
    Phase 2: 리더가 3의견 종합
    """
    # Layer 1 분석 결과를 텍스트로 정리
    l1_text = _format_layer1(layer1_reports)
    context_text = _format_context(context)
    base_input = f"{l1_text}\n\n{context_text}"

    # Phase 1: 3명 병렬 판단
    logger.info("Opus 팀 Phase 1: 3명 독립 분석 시작")
    aggressive_task = _analyst_judgment(ai, _AGGRESSIVE_PROMPT, base_input, "공격형")
    balanced_task = _analyst_judgment(ai, _BALANCED_PROMPT, base_input, "균형형")
    conservative_task = _analyst_judgment(ai, _CONSERVATIVE_PROMPT, base_input, "보수형")

    results = await asyncio.gather(
        aggressive_task, balanced_task, conservative_task,
        return_exceptions=True,
    )

    opinions: list[dict] = []
    for i, (name, result) in enumerate(
        zip(["공격형", "균형형", "보수형"], results),
    ):
        if isinstance(result, Exception):
            logger.warning("Opus %s 분석가 실패: %s", name, result)
            opinions.append({"analyst": name, "action": "hold", "error": str(result)})
        else:
            opinions.append(result)

    # Phase 2: 리더 종합
    logger.info("Opus 팀 Phase 2: 리더 종합 시작")
    report = await _leader_synthesis(ai, opinions, base_input)

    logger.info(
        "Opus 팀 판단 완료: confidence=%.2f, risk=%s, signals=%d",
        report.confidence, report.risk_level, len(report.signals),
    )
    return report


async def _analyst_judgment(
    ai: AiClient,
    persona: str,
    base_input: str,
    name: str,
) -> dict:
    """개별 분석가의 판단을 받는다."""
    prompt = (
        f"{persona}\n\n"
        f"아래 Sonnet 4에이전트의 분석 결과와 시장 데이터를 읽고 매매 판단을 내려라.\n\n"
        f"{base_input}\n\n"
        "반드시 아래 JSON만 출력하라:\n"
        "{\n"
        f'  "analyst": "{name}",\n'
        '  "action": "buy" | "sell" | "hold",\n'
        '  "ticker": "종목코드 (hold면 빈 문자열)",\n'
        '  "confidence": 0.0~1.0,\n'
        '  "risk_assessment": "low" | "medium" | "high" | "critical",\n'
        '  "reasoning": "한국어 판단 근거 (3~5문장)",\n'
        '  "key_risk": "가장 큰 리스크 요인 한줄 (한국어)"\n'
        "}\n"
    )

    response = await ai.send_text(prompt, model="opus", max_tokens=1024)
    parsed = _parse_json(response.content)
    parsed.setdefault("analyst", name)
    return parsed


async def _leader_synthesis(
    ai: AiClient,
    opinions: list[dict],
    base_input: str,
) -> ComprehensiveReport:
    """리더가 3의견을 종합하여 최종 ComprehensiveReport를 생성한다."""
    opinions_text = "\n\n".join(
        f"[{o.get('analyst', '?')}]\n"
        f"  action: {o.get('action', 'hold')}\n"
        f"  ticker: {o.get('ticker', '')}\n"
        f"  confidence: {o.get('confidence', 0)}\n"
        f"  risk: {o.get('risk_assessment', 'high')}\n"
        f"  reasoning: {o.get('reasoning', o.get('error', ''))}\n"
        f"  key_risk: {o.get('key_risk', '')}"
        for o in opinions
    )

    prompt = (
        f"{_LEADER_PROMPT}\n\n"
        f"[3명의 분석가 의견]\n{opinions_text}\n\n"
        f"[원본 Sonnet 분석 + 시장 데이터]\n{base_input}\n\n"
        "반드시 아래 JSON만 출력하라:\n"
        "{\n"
        '  "signals": [{"action": "buy/sell/hold", "ticker": "종목코드", "reason": "한국어"}],\n'
        '  "confidence": 0.0~1.0,\n'
        '  "recommendations": ["한국어 구체적 행동 지시"],\n'
        '  "regime_assessment": "현재 시장 상태 평가 (한국어)",\n'
        '  "risk_level": "low" | "medium" | "high" | "critical"\n'
        "}\n"
    )

    try:
        response = await ai.send_text(prompt, model="opus", max_tokens=1024)
        parsed = _parse_json(response.content)

        return ComprehensiveReport(
            signals=parsed.get("signals", [{"action": "hold", "ticker": "", "reason": "판단 불가"}]),
            confidence=parsed.get("confidence", 0.4),
            recommendations=parsed.get("recommendations", ["포지션 유지"]),
            regime_assessment=parsed.get("regime_assessment", ""),
            risk_level=parsed.get("risk_level", "medium"),
            timestamp=datetime.now(tz=timezone.utc),
        )
    except Exception as exc:
        logger.error("Opus 리더 판단 실패: %s", exc)
        return ComprehensiveReport(
            signals=[{"action": "hold", "ticker": "", "reason": f"리더 실패: {exc}"}],
            confidence=0.3,
            recommendations=["Opus 리더 판단 실패 — 포지션 유지"],
            regime_assessment="판단 불가",
            risk_level="high",
            timestamp=datetime.now(tz=timezone.utc),
        )


def _format_layer1(reports: dict[str, str]) -> str:
    """Layer 1 분석 결과를 텍스트로 정리한다."""
    parts = []
    for agent, content in reports.items():
        parts.append(f"=== {agent} ===\n{content}")
    return "\n\n".join(parts)


def _format_context(context: dict) -> str:
    """시장 컨텍스트를 텍스트로 정리한다."""
    lines = ["[시장 데이터]"]
    for key, value in context.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def _parse_json(raw: str) -> dict:
    """AI 응답에서 JSON을 파싱한다."""
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.warning("Opus JSON 파싱 실패: %s", raw[:200])
        return {}
```

- [ ] **Step 2: 커밋**

```bash
git add src/analysis/team/opus_judgment.py
git commit -m "feat: Opus 3+1 최종 판단 팀 구현"
```

---

### Task 6: ComprehensiveTeam 순차→병렬 전환

**Files:**
- Modify: `src/analysis/team/comprehensive_team.py`

- [ ] **Step 1: comprehensive_team.py에서 순차 실행을 병렬로 변경**

핵심 변경:
1. `_AGENT_ORDER`에서 `MASTER_ANALYST` 제거 (Layer 2로 이동)
2. 4에이전트를 `asyncio.gather`로 병렬 실행
3. 이전 에이전트 결과를 context에 포함하지 않음 (앵커링 방지)
4. 반환값을 4개 독립 분석 텍스트 dict로 변경

현재 `analyze()` 메서드의 순차 호출 루프를 병렬 `asyncio.gather`로 교체한다.
`_run_single_agent()` 메서드에서 `prior_results` 파라미터를 제거한다.

반환 타입을 `ComprehensiveReport` → `dict[str, str]`로 변경하고,
`ComprehensiveReport` 생성은 `opus_judgment.py`에서 수행한다.

- [ ] **Step 2: 커밋**

```bash
git add src/analysis/team/comprehensive_team.py
git commit -m "refactor: ComprehensiveTeam 순차→병렬 4에이전트 전환"
```

---

### Task 7: continuous_analysis 60분 + 센티넬 연동

**Files:**
- Modify: `src/orchestration/loops/continuous_analysis.py`

- [ ] **Step 1: 주요 변경사항**

1. `interval_minutes` 기본값 30 → 60
2. `_execute_iteration()`에서 Layer 1 → Layer 2 파이프라인 호출
3. sentinel:priority Redis 키에서 우선 반영 데이터 읽기
4. sentinel:watch 신호를 분석 컨텍스트에 포함

```python
# 변경 전
async def run_continuous_analysis(system, shutdown_event, interval_minutes=30):
# 변경 후
async def run_continuous_analysis(system, shutdown_event, interval_minutes=60):
```

`_run_single_analysis()`에서:
1. ComprehensiveTeam.analyze() → 4에이전트 병렬 결과 (dict[str, str])
2. opus_team_judgment() → ComprehensiveReport
3. Redis 저장 (기존과 동일)

- [ ] **Step 2: 커밋**

```bash
git add src/orchestration/loops/continuous_analysis.py
git commit -m "refactor: 분석 주기 60분 + Layer1→Layer2 파이프라인 연동"
```

---

## Chunk 3: 통합 + DI 등록

### Task 8: dependency_injector에 센티넬 등록

**Files:**
- Modify: `src/orchestration/init/dependency_injector.py`

- [ ] **Step 1: 센티넬 관련 feature 등록 추가 없음**

센티넬은 `InjectedSystem`의 기존 features를 참조만 하고,
자체가 feature로 등록될 필요는 없다 (루프로 실행됨).
`sentinel_loop`는 `continuous_analysis`처럼 orchestration 레벨에서 실행한다.

다만 크롤링 엔진/스케줄러가 feature로 등록되어 있는지 확인한다.

- [ ] **Step 2: trading_control.py에서 센티넬 루프 시작**

`_lifecycle()` 함수에서 trading_loop + continuous_analysis와 함께
sentinel_loop를 동시 실행 태스크로 추가한다.

```python
# 변경 전 (trading_control.py _lifecycle 내부):
loop_task = asyncio.create_task(run_trading_loop(...))
analysis_task = asyncio.create_task(run_continuous_analysis(...))

# 변경 후:
loop_task = asyncio.create_task(run_trading_loop(...))
analysis_task = asyncio.create_task(run_continuous_analysis(...))
sentinel_task = asyncio.create_task(run_sentinel_loop(...))
```

- [ ] **Step 3: 커밋**

```bash
git add src/orchestration/init/dependency_injector.py src/monitoring/endpoints/trading_control.py
git commit -m "feat: 센티넬 루프를 매매 생명주기에 통합"
```

---

### Task 9: 뉴스 헤드라인 캐시 연동

**Files:**
- Modify: `src/orchestration/phases/news_pipeline.py`

- [ ] **Step 1: 크롤링 시 최신 헤드라인을 Redis에 캐시**

센티넬이 `news:latest_titles` 키에서 헤드라인을 읽을 수 있도록,
뉴스 파이프라인 크롤링 단계에서 신규 기사 제목을 캐시한다.

```python
# _crawl_news() 또는 _collect_and_classify() 내부에서
# 크롤링 결과의 제목 목록을 Redis에 저장
titles = [a.title for a in raw_articles if a.title]
await cache.write_json("news:latest_titles", titles[:50], ttl=300)
```

- [ ] **Step 2: 커밋**

```bash
git add src/orchestration/phases/news_pipeline.py
git commit -m "feat: 크롤링 시 최신 헤드라인 Redis 캐시 추가"
```

---

### Task 10: 서버 재시작 + 통합 검증

- [ ] **Step 1: 서버 프로세스 확인 및 재시작**

```bash
# 기존 서버 확인
lsof -ti:9501
# 서버 재시작
kill $(lsof -ti:9501) && sleep 2 && cd /path/to/project && python3 src/main.py &
```

- [ ] **Step 2: 헬스 체크**

```bash
curl -s http://localhost:9501/api/health | python3 -m json.tool
```

- [ ] **Step 3: import 검증**

```bash
python3 -c "
from src.analysis.sentinel.models import AnomalyResult, SentinelState
from src.analysis.sentinel.anomaly_detector import detect_anomalies
from src.analysis.sentinel.escalation import evaluate_anomaly, emergency_opus_judgment
from src.analysis.team.opus_judgment import opus_team_judgment
from src.orchestration.loops.sentinel_loop import run_sentinel_loop
print('모든 import 성공')
"
```

- [ ] **Step 4: 커밋 (모든 변경 최종)**

```bash
git add -A
git commit -m "feat: 다계층 분석 아키텍처 v1 통합 완료"
```
