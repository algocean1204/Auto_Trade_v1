# F4~F6 모듈 설계 문서

> defalarm v3 패턴 기반 Feature 모듈 설계
> 작성일: 2026-02-26
> 대상: F4 (전략), F5 (실행), F6 (리스크 & 안전)

---

## 문서 사용 규칙

- **IN**: 해당 모듈이 외부에서 받는 입력 (타입 + 출처 명시)
- **OUT**: 해당 모듈이 반환하는 결과 (타입 명시)
- **Atom**: 순수 함수, 단일 책임, 30줄 이하, 외부 인프라 직접 import 금지
- **Manager**: Atom 호출만 허용, 50줄 이하, 직접 로직 수행 금지
- **체크리스트**: 리팩토링 완료 판단 기준

---

# F4. 전략 (Strategy)

## 개요

지표와 분석 결과를 받아 매수/매도 신호와 포지션 크기를 결정한다.
모든 전략 로직은 독립적인 Atom 함수로 분리되어 테스트 가능한 순수 함수 형태를 유지한다.

## 파이프라인

```
지표 + 분석 결과
       │
       ▼
F4.1 EntryStrategy ← 7개 진입 게이트 순차 평가
       │ EntrySignal
       ▼
F4.3 BeastMode ← A+ 셋업 조건 충족 시 활성화
       │ BeastSignal (conviction_multiplier 적용)
       ▼
F4.4 Pyramiding ← 기존 포지션 수익 중 추가 진입 판단
       │ PyramidSignal
       ▼
F4.2 ExitStrategy ← 우선순위 체인 기반 청산 판단
       │ ExitSignal
       ▼
결과 피드백 → F4.12 Backtester, src/feedback/execution_optimizer/
```

---

## F4.1 EntryStrategy

### 역할

7개 진입 게이트를 순차적으로 실행하여 특정 티커의 매수 진입 여부를 결정한다.
하나의 게이트라도 실패하면 진입을 차단하며 차단 원인을 기록한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `ticker` | `str` | 호출자 (position_monitor, main.py) |
| `analysis_result` | `AnalysisResult` | F2 (Continuous Analysis) |
| `indicators` | `IndicatorBundle` | F3 (Indicators) |
| `regime` | `str` | F6.1 HardSafety / macro 모듈 |
| `positions` | `list[Position]` | F5.4 PositionMonitor |
| `strategy_params` | `dict` | F4.10 StrategyParams |

### OUT

```python
@dataclass
class EntrySignal:
    should_enter: bool          # 진입 여부
    confidence: float           # 0.0 ~ 1.0
    position_size_pct: float    # 포트폴리오 대비 비율
    reasons: list[str]          # 진입 허용 사유 목록
    blocked_by: str | None      # 차단된 게이트 이름 (진입 불가 시)
```

### 7개 진입 게이트

| 게이트 번호 | 이름 | 조건 |
|-------------|------|------|
| Gate 1 | OBI | `obi_score > threshold` |
| Gate 2 | CrossAsset | leader ETF 모멘텀 정렬 |
| Gate 3 | Whale | 대형 주문 흐름 일치 |
| Gate 4 | MicroRegime | trending / mild_bull 이상 |
| Gate 5 | ML | `ml_prediction > threshold` |
| Gate 6 | Friction | friction 허들 이상 기대 수익 |
| Gate 7 | RAG | 과거 실패 패턴 미매칭 |

### Atom 함수 목록

```python
# feature/strategy/entry/atoms.py

def check_obi_gate(obi_score: float, threshold: float) -> GateResult:
    """OBI(호가창 불균형) 진입 조건을 검사한다."""
    ...

def check_cross_asset_gate(
    leader_scores: dict[str, float],
    min_alignment: float
) -> GateResult:
    """크로스에셋 모멘텀 정렬을 검사한다."""
    ...

def check_whale_gate(
    whale_score: float,
    direction: str,
    threshold: float
) -> GateResult:
    """고래 주문 흐름 일치 여부를 검사한다."""
    ...

def check_regime_gate(
    regime: str,
    ticker_type: str,
    allowed_regimes: list[str]
) -> GateResult:
    """현재 레짐이 진입 허용 조건인지 검사한다."""
    ...

def check_ml_gate(
    ml_prediction: float,
    threshold: float
) -> GateResult:
    """ML 예측 확률이 임계값 이상인지 검사한다."""
    ...

def check_friction_gate(
    expected_gain_pct: float,
    friction_hurdle: float
) -> GateResult:
    """거래 비용(스프레드+슬리피지) 대비 기대 수익이 충분한지 검사한다."""
    ...

def check_rag_gate(
    ticker: str,
    current_setup: dict,
    failure_patterns: list[dict]
) -> GateResult:
    """RAG 기반 과거 실패 패턴과 현재 셋업이 일치하는지 검사한다."""
    ...

def aggregate_gate_results(results: list[GateResult]) -> EntrySignal:
    """7개 게이트 결과를 종합하여 최종 EntrySignal을 생성한다."""
    ...
```

### Manager

```python
# feature/strategy/entry/manager.py

async def run_entry_pipeline(
    ticker: str,
    analysis_result: AnalysisResult,
    indicators: IndicatorBundle,
    regime: str,
    positions: list[Position],
    strategy_params: dict
) -> EntrySignal:
    """7개 진입 게이트를 순차 실행하여 EntrySignal을 반환한다."""
    # 각 Atom 호출 후 결과 집계만 수행한다
    ...
```

### 현재 파일 매핑

| 현재 경로 | 이전 줄수 | 리팩토링 후 경로 |
|-----------|-----------|-----------------|
| `src/strategy/entry_strategy.py` | 1,450줄 | `feature/strategy/entry/` |

### 체크리스트

- [ ] 각 게이트 Atom이 30줄 이하 순수 함수로 분리되었다
- [ ] `GateResult` 타입이 `core/types/strategy.py`에 정의되었다
- [ ] Manager가 Atom 호출 + 집계만 수행하며 50줄 이하이다
- [ ] 게이트 임계값이 모두 `strategy_params`에서 주입된다 (하드코딩 금지)
- [ ] 단위 테스트: 각 게이트 Atom 개별 테스트 커버리지 80% 이상
- [ ] `blocked_by` 필드가 모니터링 대시보드에서 조회 가능하다

---

## F4.2 ExitStrategy

### 역할

보유 포지션에 대해 우선순위 체인 기반으로 청산 여부와 청산 방식을 결정한다.
우선순위가 높은 청산 조건이 충족되면 하위 조건을 평가하지 않고 즉시 반환한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `position` | `Position` | F5.4 PositionMonitor |
| `indicators` | `IndicatorBundle` | F3 (Indicators) |
| `regime` | `str` | F6.1 HardSafety |
| `strategy_params` | `dict` | F4.10 StrategyParams |
| `market_data` | `MarketData` | F5.2 KISClient |

### OUT

```python
@dataclass
class ExitSignal:
    should_exit: bool
    reason: str
    exit_type: Literal[
        "emergency",
        "hard_stop",
        "beast_exit",
        "take_profit",
        "scaled_exit",
        "news_fade",
        "stat_arb",
        "trailing_stop",
        "time_stop",
        "eod"
    ]
    exit_pct: float     # 청산 비율 (0.0~1.0, 1.0 = 전량 청산)
    priority: int       # 낮을수록 높은 우선순위
```

### 청산 우선순위 체인

| 우선순위 | 청산 유형 | 조건 |
|----------|----------|------|
| 0 | `emergency` | EmergencyProtocol 트리거 |
| 1 | `hard_stop` | 손실 임계값 돌파 |
| 2 | `beast_exit` | Beast Mode ego 청산 조건 |
| 3 | `take_profit` | take_profit 목표가 도달 |
| 3.5 | `scaled_exit` | 분할 매도 (30%/30%/40%) |
| 4.5 | `news_fade` | 뉴스 스파이크 역방향 페이드 |
| 4.7 | `stat_arb` | 페어 Z-Score 정상화 |
| 5 | `trailing_stop` | 트레일링 손절가 하회 |
| 6 | `time_stop` | 최대 보유 시간 초과 |
| 9 | `eod` | 장 마감 전 강제 청산 |

### Atom 함수 목록

```python
# feature/strategy/exit/atoms.py

def check_emergency_exit(
    position: Position,
    emergency_state: dict
) -> ExitSignal | None:
    """긴급 청산 조건(EmergencyProtocol 트리거)을 확인한다."""
    ...

def check_hard_stop(
    entry_price: float,
    current_price: float,
    stop_loss_pct: float
) -> ExitSignal | None:
    """하드 손절가 하회 여부를 확인한다."""
    ...

def check_beast_exit(
    position: Position,
    beast_state: BeastState,
    current_price: float,
    elapsed_seconds: int
) -> ExitSignal | None:
    """Beast Mode 청산 조건(타임스탑, 트레일링)을 확인한다."""
    ...

def check_take_profit(
    entry_price: float,
    current_price: float,
    take_profit_pct: float
) -> ExitSignal | None:
    """익절 목표가 도달 여부를 확인한다."""
    ...

def build_scaled_exit_signal(
    position: Position,
    current_price: float,
    scale_config: dict
) -> ExitSignal | None:
    """분할 매도 단계(30%/30%/40%)를 계산한다."""
    ...

def check_news_fade_exit(
    fade_signal: FadeSignal,
    position: Position
) -> ExitSignal | None:
    """뉴스 스파이크 페이드 청산 조건을 확인한다."""
    ...

def check_stat_arb_exit(
    stat_arb_signal: StatArbSignal,
    position: Position
) -> ExitSignal | None:
    """페어 트레이딩 Z-Score 복귀 청산 조건을 확인한다."""
    ...

def check_trailing_stop(
    highest_price: float,
    current_price: float,
    trailing_pct: float
) -> ExitSignal | None:
    """트레일링 손절가 하회 여부를 확인한다."""
    ...

def check_time_stop(
    entry_time: datetime,
    max_hold_seconds: int
) -> ExitSignal | None:
    """최대 보유 시간 초과 여부를 확인한다."""
    ...

def check_eod_exit(
    current_time: datetime,
    eod_close_time: datetime
) -> ExitSignal | None:
    """장 마감 전 강제 청산 조건을 확인한다."""
    ...
```

### Manager

```python
# feature/strategy/exit/manager.py

async def run_exit_pipeline(
    position: Position,
    indicators: IndicatorBundle,
    regime: str,
    strategy_params: dict,
    market_data: MarketData
) -> ExitSignal:
    """우선순위 체인 순서로 청산 조건을 확인하여 첫 번째 매칭 ExitSignal을 반환한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 이전 줄수 | 리팩토링 후 경로 |
|-----------|-----------|-----------------|
| `src/strategy/exit_strategy.py` | 1,517줄 | `feature/strategy/exit/` |

### 체크리스트

- [ ] 각 청산 유형이 독립적인 Atom 함수로 분리되었다
- [ ] 우선순위 순서가 Manager의 호출 순서로만 제어된다 (조건 내부에 하드코딩 금지)
- [ ] `exit_pct`가 분할 매도 시 올바르게 계산된다 (30%/30%/40%)
- [ ] Beast Mode 청산은 BeastState 의존성을 DI로 주입받는다
- [ ] EOD 청산 시간이 `strategy_params`에서 설정 가능하다
- [ ] 단위 테스트: 각 Atom에 대해 경계값 케이스 포함

---

## F4.3 BeastMode

### 역할

A+ 셋업 조건이 충족될 때 Beast Mode를 활성화하고, 에고(Ego) 유형에 따라 포지션 크기 배율과 청산 전략을 결정한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `confidence` | `float` | F2 (AI Analysis) |
| `obi_score` | `float` | F3.1 OBICalculator |
| `leader_momentum` | `float` | F3.3 LeaderAggregator |
| `volume_ratio` | `float` | F3 Volume |
| `whale_alignment` | `bool` | F3.4 WhaleScorer |
| `regime` | `str` | F6.1 HardSafety |
| `vix` | `float` | F6 매크로 |
| `strategy_params` | `dict` | F4.10 StrategyParams |
| `daily_beast_count` | `int` | 당일 Beast 활성화 횟수 |
| `last_failure_time` | `datetime \| None` | 최근 실패 시간 |

### OUT

```python
@dataclass
class BeastSignal:
    activated: bool
    conviction_score: float         # 0.0 ~ 1.0
    conviction_multiplier: float    # 2.5x ~ 3.0x
    ego_type: Literal["sniper", "butcher", "surfer"] | None
    position_size_pct: float
    rejection_reason: str | None
```

### A+ 셋업 조건 (AND 로직)

| 조건 | 임계값 |
|------|--------|
| AI 신뢰도 | `confidence > 0.9` |
| OBI 점수 | `obi_score > +0.4` |
| 리더 모멘텀 | `leader_momentum > 0.6` |
| 거래량 배율 | `volume_ratio >= 2.0` |
| 고래 정렬 | `whale_alignment == True` |

### 가중 합성 점수

```
conviction = 0.30 * confidence
           + 0.25 * obi_score
           + 0.20 * leader_momentum
           + 0.15 * min(volume_ratio / 3.0, 1.0)
           + 0.10 * (1.0 if whale_alignment else 0.0)
```

### 에고(Ego) 유형

| 에고 | 별명 | 특징 |
|------|------|------|
| `sniper` | Cold-Blooded Sniper | A+ 셋업 진입, 빠른 익절 |
| `butcher` | Merciless Butcher | 120초 타임스탑 강제 청산 |
| `surfer` | Greedy Surfer | -0.5% 트레일링 |

### 가드 조건

- `regime in ["strong_bull", "mild_bull"]` 이어야 한다
- `vix < 25` 이어야 한다
- `daily_beast_count < 5` 이어야 한다
- `last_failure_time`이 5분 이내가 아니어야 한다
- 에러 발생 시 즉시 청산 (Fail-Closed)
- HardSafety 15% 포지션 한도가 Beast 40% 한도보다 우선한다

### Atom 함수 목록

```python
# feature/strategy/beast_mode/atoms.py

def check_aplus_setup(
    confidence: float,
    obi_score: float,
    leader_momentum: float,
    volume_ratio: float,
    whale_alignment: bool,
    thresholds: dict
) -> bool:
    """A+ 셋업 AND 조건 5가지를 동시에 검사한다."""
    ...

def calculate_conviction_score(
    confidence: float,
    obi_score: float,
    leader_momentum: float,
    volume_ratio: float,
    whale_alignment: bool
) -> float:
    """가중 합성 점수(0.0~1.0)를 계산한다."""
    ...

def calculate_conviction_multiplier(conviction_score: float) -> float:
    """conviction_score를 2.5x~3.0x 범위의 배율로 선형 변환한다."""
    ...

def select_ego_type(
    regime: str,
    conviction_score: float,
    vix: float
) -> Literal["sniper", "butcher", "surfer"]:
    """현재 조건에 맞는 에고 유형을 선택한다."""
    ...

def check_beast_guards(
    regime: str,
    vix: float,
    daily_beast_count: int,
    last_failure_time: datetime | None,
    cooldown_seconds: int
) -> tuple[bool, str | None]:
    """Beast Mode 활성화 가드 조건을 확인한다. (통과 여부, 거부 사유) 반환."""
    ...

def calculate_beast_position_size(
    base_size_pct: float,
    conviction_multiplier: float,
    hard_limit_pct: float
) -> float:
    """HardSafety 한도를 초과하지 않는 Beast 포지션 크기를 계산한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/strategy/beast_mode/config.py` | `feature/strategy/beast_mode/config.py` |
| `src/strategy/beast_mode/models.py` | `feature/strategy/beast_mode/models.py` |
| `src/strategy/beast_mode/detector.py` | `feature/strategy/beast_mode/atoms.py` (일부) |
| `src/strategy/beast_mode/conviction_sizer.py` | `feature/strategy/beast_mode/atoms.py` (일부) |
| `src/strategy/beast_mode/beast_exit.py` | `feature/strategy/exit/atoms.py` `check_beast_exit()` |
| `src/strategy/beast_mode/__init__.py` | `feature/strategy/beast_mode/manager.py` |

### 체크리스트

- [ ] AND 조건 5가지가 단일 Atom `check_aplus_setup()`에서만 평가된다
- [ ] `conviction_multiplier` 선형 보간 로직이 순수 함수로 분리되었다
- [ ] 가드 조건 실패 시 `rejection_reason`이 반드시 채워진다
- [ ] `beast_exit` Atom이 `exit/atoms.py`로 통합되었다
- [ ] Fail-Closed: 예외 발생 시 `BeastSignal(activated=False)` 반환
- [ ] `strategy_params.json`의 `beast_mode_enabled` 플래그가 적용된다
- [ ] Danger Zone (09:30-10:00 ET, 15:30-16:00 ET) 차단이 가드에 포함된다

---

## F4.4 Pyramiding

### 역할

수익 중인 포지션에 단계적으로 추가 진입(피라미딩)하여 수익을 극대화한다.
각 레벨의 안전 가드를 순차 확인하며 Ratchet Stop(손절가 상향)을 함께 계산한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `position` | `Position` | F5.4 PositionMonitor |
| `current_price` | `float` | F5.2 KISClient |
| `strategy_params` | `dict` | F4.10 StrategyParams |

### OUT

```python
@dataclass
class PyramidSignal:
    should_add: bool
    add_level: int              # 1, 2, 3
    add_size_pct: float         # 전체 대비 추가 비율
    ratchet_stop: float         # 새 손절가
    rejection_reason: str | None
```

### 3단계 추가 진입

| 레벨 | 수익 조건 | 추가 비율 |
|------|----------|----------|
| 1 | `+1%` | 기존 포지션의 50% |
| 2 | `+2%` | 기존 포지션의 30% |
| 3 | `+3%` | 기존 포지션의 20% |

### Atom 함수 목록

```python
# feature/strategy/pyramiding/atoms.py

def get_current_pyramid_level(position: Position) -> int:
    """현재 포지션의 피라미딩 레벨을 반환한다."""
    ...

def check_profit_threshold(
    entry_price: float,
    current_price: float,
    level: int,
    thresholds: list[float]
) -> bool:
    """해당 레벨의 수익 임계값에 도달했는지 확인한다."""
    ...

def run_pyramid_guards(
    position: Position,
    portfolio: dict,
    strategy_params: dict
) -> tuple[bool, str | None]:
    """8개 안전 가드를 순차 확인한다. (통과 여부, 거부 사유) 반환."""
    ...

def calculate_add_size(
    position_size: float,
    level: int,
    ratios: list[float]
) -> float:
    """레벨별 추가 진입 크기를 계산한다."""
    ...

def calculate_ratchet_stop(
    current_price: float,
    level: int,
    ratchet_offsets: list[float]
) -> float:
    """피라미딩 레벨에 따른 Ratchet Stop 가격을 계산한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 이전 줄수 | 리팩토링 후 경로 |
|-----------|-----------|-----------------|
| `src/strategy/pyramiding.py` | 632줄 | `feature/strategy/pyramiding/` |

### 체크리스트

- [ ] 8개 안전 가드가 단일 `run_pyramid_guards()` Atom에 집약된다
- [ ] 레벨 비율(50%/30%/20%)이 `strategy_params`에서 설정 가능하다
- [ ] Ratchet Stop이 매 피라미딩 후 반드시 갱신된다
- [ ] 이미 레벨 3에 도달한 포지션은 추가 진입을 시도하지 않는다

---

## F4.5 StatArb

### 역할

5개 ETF 페어의 가격 스프레드 Z-Score를 모니터링하여 통계적 차익 거래 신호를 생성한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `pair` | `tuple[str, str]` | 설정 (5 페어 고정) |
| `price_data` | `dict[str, list[float]]` | F5.2 KISClient |

### OUT

```python
@dataclass
class StatArbSignal:
    z_score: float
    signal: Literal["long", "short", "neutral"]
    pair: str                   # 예: "QQQ/QLD"
    spread: float
    confidence: float
```

### 5개 페어

| 레버리지 ETF | 기초 ETF | 방향 |
|-------------|---------|------|
| QLD | QQQ | 2x Long NASDAQ |
| SSO | SPY | 2x Long S&P500 |
| UWM | IWM | 2x Long Russell2000 |
| DDM | DIA | 2x Long Dow Jones |
| SOXL | SOXX | 3x Long Semiconductor |

### Atom 함수 목록

```python
# feature/strategy/stat_arb/atoms.py

def calculate_spread(
    price_a: list[float],
    price_b: list[float],
    hedge_ratio: float
) -> list[float]:
    """두 티커 간 가격 스프레드 시계열을 계산한다."""
    ...

def calculate_z_score(
    spread_series: list[float],
    lookback: int
) -> float:
    """스프레드의 Z-Score를 계산한다."""
    ...

def generate_stat_arb_signal(
    z_score: float,
    entry_threshold: float,
    exit_threshold: float
) -> Literal["long", "short", "neutral"]:
    """Z-Score 기반 매매 방향을 결정한다. Z>2→short, Z<-2→long."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/strategy/stat_arb/spread_calculator.py` | `feature/strategy/stat_arb/atoms.py` `calculate_spread()` |
| `src/strategy/stat_arb/signal_generator.py` | `feature/strategy/stat_arb/atoms.py` `generate_stat_arb_signal()` |
| `src/strategy/stat_arb/pair_monitor.py` | `feature/strategy/stat_arb/manager.py` |
| `src/strategy/stat_arb/config.py` | `feature/strategy/stat_arb/config.py` |
| `src/strategy/stat_arb/models.py` | `core/types/strategy.py` (통합) |

### 체크리스트

- [ ] Z-Score 계산이 순수 함수로 분리되어 독립 테스트 가능하다
- [ ] 5개 페어 설정이 `config.py`에서 중앙 관리된다
- [ ] `generate_stat_arb_signal()`이 임계값을 하드코딩하지 않는다
- [ ] PairMonitor가 Atom 호출만 수행하는 Manager로 역할이 제한된다

---

## F4.6 MicroRegime

### 역할

단기 가격/거래량 데이터를 분석하여 현재 미시적 시장 레짐을 분류한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `price_data` | `list[float]` | F5.2 KISClient |
| `volume_data` | `list[float]` | F5.2 KISClient |

### OUT

```python
@dataclass
class MicroRegimeResult:
    regime: Literal["trending", "mean_reverting", "volatile", "quiet"]
    weights: dict[str, float]   # {"er": float, "ds": float, "ac": float, "vol": float}
    confidence: float
```

### 가중 합성 공식

```
score = 0.35 * ER (Efficiency Ratio)
      + 0.30 * DS (Directional Score)
      + 0.20 * AC (Autocorrelation)
      + 0.15 * (1 - normalized_vol)
```

### Atom 함수 목록

```python
# feature/strategy/micro_regime/atoms.py

def calculate_efficiency_ratio(prices: list[float], period: int) -> float:
    """가격 이동의 효율성 비율(Efficiency Ratio)을 계산한다."""
    ...

def calculate_directional_score(prices: list[float], adx_period: int) -> float:
    """ADX 기반 방향성 점수를 계산한다."""
    ...

def calculate_autocorrelation(prices: list[float], lag: int) -> float:
    """수익률 자기상관 계수를 계산한다."""
    ...

def classify_regime(composite_score: float, thresholds: dict) -> str:
    """복합 점수를 레짐 레이블로 분류한다."""
    ...

def build_regime_weights(er: float, ds: float, ac: float, vol: float) -> dict:
    """가중 합성 점수 계산에 사용된 각 요소 비율 딕셔너리를 생성한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/strategy/micro_regime/volatility_analyzer.py` | `feature/strategy/micro_regime/atoms.py` |
| `src/strategy/micro_regime/trend_detector.py` | `feature/strategy/micro_regime/atoms.py` |
| `src/strategy/micro_regime/regime_classifier.py` | `feature/strategy/micro_regime/atoms.py` `classify_regime()` |
| `src/strategy/micro_regime/config.py` | `feature/strategy/micro_regime/config.py` |
| `src/strategy/micro_regime/models.py` | `core/types/strategy.py` (통합) |

### 체크리스트

- [ ] ER / DS / AC 각 지표 계산이 독립 Atom으로 분리되었다
- [ ] `classify_regime()`의 임계값이 `config.py`에서 설정 가능하다
- [ ] MicroRegime 결과가 F4.1 EntryStrategy Gate 4에서 정상 소비된다

---

## F4.7 NewsFading

### 역할

뉴스로 인한 단기 가격 스파이크를 감지하고 평균 회귀 페이드 신호를 생성한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `ticker` | `str` | 호출자 |
| `price_history` | `list[tuple[datetime, float]]` | F5.2 KISClient (1분 캔들) |
| `news_events` | `list[NewsEvent]` | F1 (News Crawler) |

### OUT

```python
@dataclass
class FadeSignal:
    should_fade: bool
    spike_pct: float        # 스파이크 크기 (%)
    decay_estimate: float   # 예상 회귀 크기 (%)
    confidence: float
    direction: Literal["short", "neutral"]
```

### Atom 함수 목록

```python
# feature/strategy/news_fading/atoms.py

def detect_price_spike(
    price_history: list[tuple[datetime, float]],
    window_seconds: int,
    threshold_pct: float
) -> tuple[bool, float]:
    """지정 시간 내 가격이 임계값(1%) 이상 급등했는지 감지한다."""
    ...

def estimate_decay(
    spike_pct: float,
    time_since_spike: float,
    decay_model: dict
) -> float:
    """스파이크 이후 평균 회귀 예상 크기를 추정한다."""
    ...

def build_fade_signal(
    spike_detected: bool,
    spike_pct: float,
    decay_estimate: float,
    news_context: dict
) -> FadeSignal:
    """감지 결과와 추정 회귀를 종합하여 FadeSignal을 생성한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/strategy/news_fading/spike_detector.py` | `feature/strategy/news_fading/atoms.py` `detect_price_spike()` |
| `src/strategy/news_fading/decay_analyzer.py` | `feature/strategy/news_fading/atoms.py` `estimate_decay()` |
| `src/strategy/news_fading/fade_signal_generator.py` | `feature/strategy/news_fading/atoms.py` `build_fade_signal()` |
| `src/strategy/news_fading/config.py` | `feature/strategy/news_fading/config.py` |
| `src/strategy/news_fading/models.py` | `core/types/strategy.py` (통합) |

### 체크리스트

- [ ] 스파이크 감지 임계값 1% / 60초가 `config.py`에서 설정 가능하다
- [ ] `FadeSignal`이 F4.2 ExitStrategy 우선순위 4.5에서 소비된다
- [ ] 뉴스 없이 가격만으로도 스파이크 감지가 동작한다

---

## F4.8 WickCatcher

### 역할

VPIN과 CVD 조건이 충족될 때 급락 wick에서 반등을 노리는 지정가 주문을 배치한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `vpin` | `float` | F3 (Volume Profile) |
| `cvd` | `float` | F3 (Cumulative Volume Delta) |
| `current_price` | `float` | F5.2 KISClient |
| `price_data` | `list[float]` | F5.2 KISClient |

### OUT

```python
@dataclass
class WickSignal:
    activated: bool
    limit_prices: list[float]   # [-2%, -3%, -4%] 지정가 목록
    bounce_target: float        # +2% 반등 목표가
    rejection_reason: str | None
```

### 활성화 조건

```
VPIN > 0.7 AND CVD < -0.6
```

### Atom 함수 목록

```python
# feature/strategy/wick_catcher/atoms.py

def check_wick_activation(vpin: float, cvd: float) -> tuple[bool, str | None]:
    """VPIN > 0.7 AND CVD < -0.6 조건을 검사한다."""
    ...

def calculate_limit_prices(
    current_price: float,
    offsets: list[float]
) -> list[float]:
    """현재가 대비 -2%/-3%/-4% 지정가 목록을 계산한다."""
    ...

def calculate_bounce_target(current_price: float, bounce_pct: float) -> float:
    """반등 목표가(+2%)를 계산한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/strategy/wick_catcher/activation_checker.py` | `feature/strategy/wick_catcher/atoms.py` `check_wick_activation()` |
| `src/strategy/wick_catcher/order_placer.py` | `feature/strategy/wick_catcher/atoms.py` `calculate_limit_prices()` |
| `src/strategy/wick_catcher/bounce_exit.py` | `feature/strategy/wick_catcher/atoms.py` `calculate_bounce_target()` |
| `src/strategy/wick_catcher/config.py` | `feature/strategy/wick_catcher/config.py` |
| `src/strategy/wick_catcher/models.py` | `core/types/strategy.py` (통합) |

### 체크리스트

- [ ] 활성화 조건(0.7, -0.6)이 `config.py`에서 설정 가능하다
- [ ] 지정가 오프셋([-2%, -3%, -4%])이 설정 가능하다
- [ ] `WickSignal.limit_prices`가 실제 주문 실행 전 F5.3 OrderManager에서 소비된다

---

## F4.9 SectorRotation

### 역할

7개 섹터의 상대 강도를 계산하여 진입 선호 섹터와 회피 섹터를 결정한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `sector_data` | `dict[str, float]` | F5.2 KISClient (섹터별 수익률) |

### OUT

```python
@dataclass
class SectorSignal:
    top_sectors: list[str]      # 상위 3개 섹터
    bottom_sectors: list[str]   # 하위 2개 섹터
    prefer: list[str]           # 진입 선호 티커 목록
    avoid: list[str]            # 진입 회피 티커 목록
    scores: dict[str, float]    # 섹터별 점수
```

### Atom 함수 목록

```python
# feature/strategy/sector_rotation/atoms.py

def calculate_sector_scores(
    sector_data: dict[str, float],
    weights: dict[str, float]
) -> dict[str, float]:
    """가중 점수 기반 섹터별 상대 강도를 계산한다."""
    ...

def rank_sectors(scores: dict[str, float]) -> tuple[list[str], list[str]]:
    """섹터를 점수 순으로 정렬하여 상위/하위 섹터를 반환한다."""
    ...

def map_tickers_to_sectors(
    tickers: list[str],
    sector_map: dict[str, str]
) -> tuple[list[str], list[str]]:
    """섹터 선호/회피를 티커 목록으로 변환한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/strategy/sector_rotation.py` | `feature/strategy/sector_rotation/` |

### 체크리스트

- [ ] 섹터-티커 매핑이 `config.py`에서 중앙 관리된다
- [ ] `SectorSignal`이 F4.1 EntryStrategy에서 소비된다 (Gate 2 또는 추가 필터)

---

## F4.10 StrategyParams

### 역할

`strategy_params.json`을 로드하고 레짐별 파라미터를 제공한다. 실행 최적화 결과에 의한 파라미터 갱신도 처리한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `params_path` | `Path` | `data/strategy_params.json` |

### OUT

```python
class StrategyParams:
    def get(self, key: str, default: Any = None) -> Any:
        """파라미터 값을 반환한다."""
        ...

    def update(self, key: str, value: Any) -> bool:
        """파라미터를 갱신하고 JSON에 저장한다."""
        ...

    def get_regime_params(self, regime: str) -> dict:
        """레짐별 파라미터(take_profit, trailing, max_hold_days)를 반환한다."""
        ...
```

### 레짐별 파라미터

| 레짐 | `take_profit` | `trailing_stop` | `max_hold_days` |
|------|--------------|----------------|----------------|
| `strong_bull` | `0` (무제한, 트레일링만) | `4.0%` | `0` (EOD) |
| `mild_bull` | `3.0%` | `2.5%` | `2` |
| `sideways` | `2.0%` | `1.5%` | `0` (EOD) |
| `mild_bear` | — (방어적 역방향) | — | — |
| `crash` | `5.0%` | — | — |

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/strategy/params.py` | `feature/strategy/params/manager.py` |

### 체크리스트

- [ ] `take_profit=0`일 때 ExitStrategy에서 익절 로직이 전체 스킵된다
- [ ] `max_hold_days=0`이 HardSafety 즉시 청산이 아닌 EOD 처리임이 명확히 문서화된다
- [ ] 파라미터 갱신 시 원본 백업이 `data/strategy_params_backup.json`에 저장된다

---

## F4.11 TickerParams

### 역할

티커별 개별 파라미터(stop_loss, take_profit, size 배율 등)를 관리하며 AI 최적화를 지원한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `ticker_params_path` | `Path` | `data/ticker_params.json` |

### OUT

```python
@dataclass
class TickerConfig:
    ticker: str
    stop_loss_pct: float
    take_profit_pct: float
    size_multiplier: float
    max_hold_hours: int
    custom_gates: list[str]     # 활성화할 게이트 목록
```

### 현재 파일 매핑

| 현재 경로 | 이전 줄수 | 리팩토링 후 경로 |
|-----------|-----------|-----------------|
| `src/strategy/ticker_params.py` | 673줄 | `feature/strategy/ticker_params/` |

### 체크리스트

- [ ] AI 최적화 경로가 Manager로 분리되어 Atom과 구분된다
- [ ] `optimize(ticker)`가 AI 호출을 포함하므로 `async`로 선언된다
- [ ] 미등록 티커는 기본값을 반환하며 예외를 발생시키지 않는다

---

## F4.12 Backtester

### 역할

전략 파라미터와 과거 데이터를 사용하여 백테스트를 실행하고 성과 지표를 계산한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `strategy_params` | `dict` | F4.10 StrategyParams |
| `historical_data` | `dict[str, DataFrame]` | F5.2 KISClient (최대 100 캔들/요청) |
| `date_range` | `tuple[date, date]` | 호출자 |

### OUT

```python
@dataclass
class BacktestResult:
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    trades: list[dict]
    grid_search_results: list[dict] | None
```

### 현재 파일 매핑

| 현재 경로 | 이전 줄수 | 리팩토링 후 경로 |
|-----------|-----------|-----------------|
| `src/strategy/backtester.py` | 1,324줄 | `feature/strategy/backtester/` |

### 체크리스트

- [ ] 각 성과 지표 계산이 독립 Atom으로 분리된다 (`calc_sharpe()`, `calc_drawdown()` 등)
- [ ] Grid Search가 Manager 레벨에서 Atom 반복 호출로 구현된다
- [ ] API 엔드포인트 `/api/backtest`가 이 Manager를 직접 호출한다

---

## F4.13 LeverageDecay

### 역할

레버리지 ETF의 변동성 손실(Volatility Decay)을 정량화하고 보유 기간에 따른 청산 필요성을 판단한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `ticker` | `str` | 호출자 |
| `holding_period_days` | `int` | 포지션 보유 일수 |
| `daily_returns` | `list[float]` | F5.2 KISClient |

### OUT

```python
@dataclass
class DecayResult:
    drag_pct: float         # 변동성 손실 추정치 (%)
    should_exit: bool       # 손실이 임계값 초과 시 청산 권고
    decay_threshold: float  # 적용된 임계값
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/strategy/leverage_decay.py` | `feature/strategy/leverage_decay/atoms.py` |

### 체크리스트

- [ ] Decay 계산 공식이 순수 함수로 구현된다
- [ ] 임계값이 `strategy_params`에서 주입된다

---

## F4.14 ProfitTarget

### 역할

월간 수익 목표 대비 현재 달성률을 추적하고 Aggression Level을 제공한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `monthly_target_usd` | `float` | `strategy_params.json` |
| `realized_pnl` | `float` | C0.2 (DB) |
| `unrealized_pnl` | `float` | F5.4 PositionMonitor |

### OUT

```python
@dataclass
class ProfitTargetStatus:
    target_usd: float
    realized: float
    unrealized: float
    total: float
    remaining: float
    achievement_pct: float
    aggression_level: Literal["conservative", "normal", "aggressive"]
```

### 현재 파일 매핑

| 현재 경로 | 이전 줄수 | 리팩토링 후 경로 |
|-----------|-----------|-----------------|
| `src/strategy/profit_target.py` | 620줄 | `feature/strategy/profit_target/` |

### 체크리스트

- [ ] Survival Trading $300/월 최소 기준이 Atom에 명시적으로 반영된다
- [ ] `aggression_level`이 F4.1 EntryStrategy에서 포지션 크기 조정에 활용된다

---

# F5. 실행 (Execution)

## 개요

전략 신호를 KIS OpenAPI를 통해 실제 주문으로 변환하고 체결 결과를 포지션에 반영한다.
KIS 듀얼 인증(실전/모의) 구조를 추상화하여 상위 모듈이 계정 유형을 신경 쓰지 않도록 한다.

## 파이프라인

```
EntrySignal | ExitSignal
       │
       ▼
F5.3 OrderManager ← 주문 유형 결정, 분할 매도 조정
       │ OrderRequest
       ▼
F5.2 KISClient ← REST API 호출, 가상 한도가 자동 지정가 변환
       │ OrderResult
       ▼
F5.4 PositionMonitor ← 포지션 업데이트, 실패 티커 관리
       │
       ▼
C0.2 DB + C0.3 Redis 저장
```

---

## F5.1 KISAuth

### 역할

KIS OpenAPI 인증 토큰을 관리하고 1일 1토큰 정책을 구현한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `app_key` | `str` | `.env` |
| `app_secret` | `str` | `.env` |
| `account` | `str` | `.env` (`KIS_VIRTUAL_ACCOUNT`, `KIS_REAL_ACCOUNT`) |
| `virtual` | `bool` | 계정 유형 구분 |

### OUT

```python
@dataclass
class KISAuth:
    access_token: str
    token_expires_at: datetime
    is_virtual: bool

    async def authenticate(self) -> str:
        """유효 토큰 반환 (만료 시 재발급)한다."""
        ...
```

### 토큰 캐시 경로

| 계정 유형 | 캐시 파일 |
|----------|----------|
| 실전 | `data/kis_real_token.json` |
| 모의 | `data/kis_token.json` |

### Atom 함수 목록

```python
# feature/execution/kis_auth/atoms.py

def load_cached_token(cache_path: Path) -> dict | None:
    """캐시된 토큰을 로드하고 유효성을 확인한다."""
    ...

def is_token_valid(token_data: dict) -> bool:
    """토큰 만료 시간을 확인하여 유효 여부를 반환한다."""
    ...

def save_token_cache(cache_path: Path, token_data: dict) -> None:
    """발급된 토큰을 JSON 파일에 저장한다."""
    ...

def build_auth_request(app_key: str, app_secret: str) -> dict:
    """KIS 인증 API 요청 바디를 생성한다."""
    ...

def parse_auth_response(response: dict) -> KISAuth:
    """KIS 인증 응답을 KISAuth 객체로 파싱한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/executor/kis_auth.py` | `feature/execution/kis_auth/` |

### 체크리스트

- [ ] 토큰 만료 여부 확인이 순수 함수 `is_token_valid()`로 분리된다
- [ ] 파일 I/O가 `load_cached_token()`, `save_token_cache()` Atom으로 격리된다
- [ ] 동시 호출 시 토큰 재발급이 1회만 실행되도록 asyncio.Lock이 적용된다

---

## F5.2 KISClient

### 역할

KIS OpenAPI의 시세/잔고/주문 엔드포인트를 통합하여 추상화된 인터페이스를 제공한다.
가격 API는 실전 인증(real_auth)을 사용하고, 거래 API는 계정 유형에 따른 인증을 사용한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `virtual_auth` | `KISAuth` | F5.1 KISAuth |
| `real_auth` | `KISAuth \| None` | F5.1 KISAuth (선택) |

### OUT

#### 시세 API

```python
async def get_current_price(ticker: str) -> float:
    """현재가를 조회한다."""

async def get_daily_prices(ticker: str, days: int) -> DataFrame:
    """일봉 데이터를 조회한다. (최대 100 캔들/요청)"""

async def get_orderbook(ticker: str) -> OrderBook:
    """호가창 데이터를 조회한다."""

async def get_exchange_rate() -> float:
    """달러/원 환율을 조회한다."""
```

#### 잔고 API

```python
async def get_balance() -> Balance:
    """계좌 잔고를 조회한다."""

async def get_positions() -> list[Position]:
    """보유 포지션 목록을 조회한다."""

async def get_buying_power() -> float:
    """주문 가능 금액(USD)을 조회한다."""
```

#### 주문 API

```python
async def buy(ticker: str, qty: int, price_type: str) -> OrderResult:
    """매수 주문을 실행한다."""

async def sell(ticker: str, qty: int, price_type: str) -> OrderResult:
    """매도 주문을 실행한다."""
```

### KIS 핵심 제약

| 제약 | 처리 방식 |
|------|----------|
| 모의 거래 시장가 불가 | ±0.5% 지정가 자동 변환 (`convert_market_to_limit()`) |
| 가격 API에 real_auth 필요 | `_PRICE_API_PATHS`로 라우팅 구분 |
| 모의 잔고 `cash=0` 문제 | `VTTS3007R`(매수가능금액조회) 보완 |
| 거래소 코드 구분 | `NAS`, `AMS`, `NYS` (종목별 설정) |

### Atom 함수 목록

```python
# feature/execution/kis_client/atoms.py

def build_request_headers(auth: KISAuth, tr_id: str) -> dict:
    """KIS API 요청 헤더를 생성한다."""
    ...

def parse_price_response(response: dict) -> float:
    """가격 API 응답에서 현재가를 파싱한다."""
    ...

def convert_market_to_limit(
    current_price: float,
    side: Literal["buy", "sell"],
    offset_pct: float = 0.005
) -> tuple[str, float]:
    """시장가를 ±0.5% 지정가로 변환한다. (가상 거래 전용)"""
    ...

def parse_orderbook(response: dict) -> OrderBook:
    """호가창 응답을 OrderBook 타입으로 파싱한다."""
    ...

def parse_positions(response: dict) -> list[Position]:
    """잔고 응답에서 포지션 목록을 파싱한다."""
    ...

def route_auth(
    api_path: str,
    real_auth: KISAuth | None,
    virtual_auth: KISAuth,
    price_api_paths: set[str]
) -> KISAuth:
    """API 경로에 따라 적절한 인증 객체를 선택한다."""
    ...

def parse_order_result(response: dict) -> OrderResult:
    """주문 API 응답을 OrderResult 타입으로 파싱한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 이전 줄수 | 리팩토링 후 경로 |
|-----------|-----------|-----------------|
| `src/executor/kis_client.py` | 1,261줄 | `feature/execution/kis_client/` |

### 체크리스트

- [ ] 모든 API 파싱 로직이 Atom 함수로 분리되어 mock 테스트가 가능하다
- [ ] `convert_market_to_limit()`이 모의 계정에서만 호출된다
- [ ] 90000000 에러 발생 시 `_sell_blocked_tickers`에 추가된다 (F5.4 위임)
- [ ] `real_auth=None`일 때 가격 API가 Fallback 처리된다
- [ ] `data/kis_real_token.json`, `data/kis_token.json` 경로가 `core/config.py`에서 관리된다

---

## F5.3 OrderManager

### 역할

EntrySignal 또는 ExitSignal을 받아 실제 KIS 주문으로 변환하고 분할 매도를 구현한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `signal` | `EntrySignal \| ExitSignal` | F4.1 or F4.2 |
| `kis_client` | `KISClient` | F5.2 KISClient |
| `position` | `Position \| None` | F5.4 PositionMonitor |
| `regime` | `str` | F6.1 HardSafety |

### OUT

```python
@dataclass
class OrderResult:
    success: bool
    order_id: str | None
    ticker: str
    side: Literal["buy", "sell"]
    qty: int
    price: float
    timestamp: datetime
    error_code: str | None
    error_message: str | None
```

### 분할 매도 규칙

| 단계 | 비율 | 트리거 |
|------|------|--------|
| 1차 | 30% | 1차 익절 목표 도달 |
| 2차 | 30% | 2차 익절 목표 도달 |
| 3차 | 40% | 최종 청산 |

### Atom 함수 목록

```python
# feature/execution/order_manager/atoms.py

def calculate_order_qty(
    position_size_pct: float,
    portfolio_value: float,
    current_price: float,
    exchange_rate: float
) -> int:
    """포지션 비율에 따른 주문 수량을 계산한다."""
    ...

def build_scaled_exit_orders(
    position: Position,
    exit_pct: float,
    scale_config: dict
) -> list[tuple[int, str]]:
    """분할 매도 수량과 단계를 생성한다."""
    ...

def select_price_type(
    is_virtual: bool,
    price_type: str
) -> tuple[str, float | None]:
    """계정 유형에 따라 주문 유형과 가격을 결정한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 이전 줄수 | 리팩토링 후 경로 |
|-----------|-----------|-----------------|
| `src/executor/order_manager.py` | 668줄 | `feature/execution/order_manager/` |

### 체크리스트

- [ ] 분할 매도 비율(30%/30%/40%)이 `strategy_params`에서 설정 가능하다
- [ ] 주문 실패 시 `OrderResult.success=False`로 반환하며 예외를 상위로 전파하지 않는다
- [ ] 주문 결과가 C0.2 DB에 저장된다 (Manager 책임)

---

## F5.4 PositionMonitor

### 역할

모든 보유 포지션을 주기적으로 점검하고 청산 신호를 실행한다.
비정규 세션에서는 잔고 동기화만 수행한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `kis_client` | `KISClient` | F5.2 KISClient |
| `exit_strategy` | `ExitStrategy` | F4.2 ExitStrategy |
| `hard_safety` | `HardSafety` | F6.1 HardSafety |
| `redis` | `Redis` | C0.3 Redis |

### OUT

```python
@dataclass
class MonitorResult:
    actions_taken: list[str]            # 실행된 청산 목록
    positions_updated: list[Position]   # 갱신된 포지션 목록
    sell_blocked: set[str]              # 매도 실패 티커 목록
```

### 주요 메서드

```python
async def monitor_all(regime: str, vix: float) -> MonitorResult:
    """정규 세션: 모든 포지션에 대해 청산 조건을 확인한다."""
    ...

async def sync_positions(self) -> dict[str, dict]:
    """비정규 세션(pre/after market): 잔고만 동기화한다."""
    ...
```

### `_sell_blocked_tickers` 규칙

- KIS 매도 API 90000000 에러 발생 시 해당 티커를 set에 추가한다
- 블록된 티커에 대해 재시도하지 않는다
- EOD(장 마감) 시 `main.py`에서 set을 초기화한다

### 현재 파일 매핑

| 현재 경로 | 이전 줄수 | 리팩토링 후 경로 |
|-----------|-----------|-----------------|
| `src/executor/position_monitor.py` | 588줄 | `feature/execution/position_monitor/` |

### 체크리스트

- [ ] `monitor_all()`이 정규 세션에서만 호출된다 (비정규 세션 가드 포함)
- [ ] `sync_positions()`가 `dict[str, dict]`를 반환함이 타입 힌트로 명시된다
- [ ] `_sell_blocked_tickers`가 EOD에서 반드시 초기화된다 (`main.py` 확인)
- [ ] 대시보드 자동 갱신이 3초 간격을 유지한다 (KIS API 과부하 방지)

---

## F5.5 UniverseManager

### 역할

거래 대상 ETF Universe를 관리하고 CRUD 인터페이스를 제공한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `db` | `AsyncSession` | C0.2 DB |

### OUT

```python
class UniverseManager:
    async def get_active_tickers(self) -> list[str]: ...
    async def add_ticker(self, ticker: str, config: dict) -> bool: ...
    async def remove_ticker(self, ticker: str) -> bool: ...
    async def toggle_ticker(self, ticker: str, enabled: bool) -> bool: ...
    async def auto_add_by_volume(self, min_volume: float) -> list[str]: ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/executor/universe_manager.py` | `feature/execution/universe_manager/` |
| `src/strategy/etf_universe.py` | `feature/execution/universe_manager/` (통합) |

### 체크리스트

- [ ] Inverse Pair (NVDL↔NVDS, SOXL↔SOXS)가 DB 스키마에서 연결된다
- [ ] `auto_add_by_volume()`이 주간 ML 학습 결과를 참조한다

---

## F5.6 AccountModeManager

### 역할

실전/모의 계정 전환을 관리하고 활성 KISClient를 제공한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `kis_mode` | `str` | `.env` (`KIS_MODE`) |
| `real_client` | `KISClient` | F5.2 KISClient |
| `virtual_client` | `KISClient` | F5.2 KISClient |

### OUT

```python
class AccountModeManager:
    def get_active_client(self) -> KISClient: ...
    async def switch_mode(self, mode: Literal["real", "virtual"]) -> bool: ...
    def current_mode(self) -> str: ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/executor/account_mode_manager.py` | `feature/execution/account_mode/` |

### 체크리스트

- [ ] 계정 전환 시 열린 포지션이 있으면 경고를 발생시킨다
- [ ] `get_active_client()`가 스레드 안전하게 구현된다

---

# F6. 리스크 & 안전 (Risk & Safety)

## 개요

매매 신호가 실제 주문으로 실행되기 전에 다단계 안전 체인을 통과해야 한다.
각 체크는 독립적인 Atom으로 구현되며 Manager가 체인을 조율한다.

## 파이프라인

```
EntrySignal | ExitSignal
       │
       ▼
F6.1 HardSafety ← 절대 한도 (포지션 15%, 일 손실 -5%)
       │
       ▼
F6.2 SafetyChecker ← HardSafety + QuotaGuard 통합
       │
       ▼
F6.5 RiskGatePipeline ← 7개 게이트 순차 통과
       │
       ▼
승인 → F5.3 OrderManager
차단 → 거부 사유 기록 + 알림
```

---

## F6.1 HardSafety

### 역할

절대 손실 한도와 포지션 한도를 강제 적용한다. 레짐별 매수 차단 로직을 포함한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `position` | `Position` | F5.4 PositionMonitor |
| `portfolio` | `Portfolio` | F5.2 KISClient |
| `regime` | `str` | 매크로 분석 |
| `ticker_type` | `str` | `"bull_etf"`, `"inverse_etf"`, `"stock"` |

### OUT

```python
@dataclass
class SafetyResult:
    passed: bool
    reason: str | None
    max_position_pct: float         # 허용된 최대 포지션 비율
    max_loss_triggered: bool        # 일일 손실 한도 초과 여부
```

### 하드 리밋

| 항목 | 한도 |
|------|------|
| 단일 포지션 | 포트폴리오의 15% |
| 일일 손실 | -5% |
| 최대 일일 거래 | 30회 |

### 레짐별 매수 차단

| 레짐 | Bull ETF 매수 | Inverse ETF 매수 |
|------|-------------|----------------|
| `crash` | 차단 | 허용 |
| `mild_bear` | 차단 | 허용 |
| `sideways` 이상 | 허용 | 제한 |

### Atom 함수 목록

```python
# feature/risk/hard_safety/atoms.py

def check_position_limit(
    new_position_pct: float,
    max_position_pct: float
) -> tuple[bool, str | None]:
    """단일 포지션 한도(15%)를 초과하는지 확인한다."""
    ...

def check_daily_loss_limit(
    daily_pnl_pct: float,
    limit_pct: float
) -> tuple[bool, str | None]:
    """일일 손실 한도(-5%)를 초과했는지 확인한다."""
    ...

def check_daily_trade_count(
    trade_count: int,
    max_trades: int
) -> tuple[bool, str | None]:
    """최대 일일 거래 횟수(30회)를 초과했는지 확인한다."""
    ...

def check_regime_buy_restriction(
    regime: str,
    ticker_type: str,
    allowed_map: dict[str, list[str]]
) -> tuple[bool, str | None]:
    """레짐별 매수 제한을 확인한다. crash/mild_bear에서 Bull ETF 차단."""
    ...

def check_overnight_holding(
    position: Position,
    regime: str,
    overnight_allowed: bool
) -> tuple[bool, str | None]:
    """오버나이트 보유 허용 여부를 확인한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/safety/hard_safety.py` | `feature/risk/hard_safety/` |

### 체크리스트

- [ ] `set_current_regime()`이 `_get_current_regime()` 내부에서만 호출된다
- [ ] Beast Mode의 40% 한도가 HardSafety의 15% 한도보다 항상 낮게 처리된다
- [ ] Inverse ETF(Bear)가 `crash`/`mild_bear`에서 오버나이트 보유에서 제외된다

---

## F6.2 SafetyChecker

### 역할

HardSafety와 QuotaGuard를 순차 실행하여 통합 안전 체크 결과를 반환한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `trade_request` | `TradeRequest` | F5.3 OrderManager |
| `hard_safety` | `HardSafety` | F6.1 |
| `quota_guard` | `QuotaGuard` | F6.19 |

### OUT

```python
@dataclass
class CheckResult:
    safe: bool
    violations: list[str]
    checked_at: datetime
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/safety/safety_checker.py` | `feature/risk/safety_checker/` |

### 체크리스트

- [ ] `violations`가 모든 실패 항목을 포함한다 (첫 번째 실패에서 중단하지 않는다)
- [ ] `SafetyChecker`가 단순 조율만 하며 자체 로직을 가지지 않는다

---

## F6.3 EmergencyProtocol

### 역할

6가지 긴급 시나리오를 모니터링하고 트리거 시 전체 또는 선택적 포지션 청산을 실행한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `trigger_event` | `EmergencyEvent` | 각 모니터링 모듈 |
| `portfolio` | `Portfolio` | F5.2 KISClient |
| `redis` | `Redis` | C0.3 Redis |

### OUT

```python
@dataclass
class EmergencyResult:
    triggered: bool
    scenario: str                       # 트리거된 시나리오 이름
    action: str                         # 실행된 조치
    positions_closed: list[str]         # 청산된 티커 목록
    halt_trading: bool                  # 매매 중지 여부
```

### 6가지 긴급 시나리오

| 번호 | 이름 | 조건 |
|------|------|------|
| 1 | VIX Spike | VIX 급등 임계값 초과 |
| 2 | Flash Crash | 단기 급락 감지 |
| 3 | Circuit Breaker | 시장 서킷 브레이커 발동 |
| 4 | API Failure | KIS API 연속 실패 |
| 5 | Data Staleness | 데이터 신선도 초과 |
| 6 | VPIN Emergency | VPIN > 0.85 + 30분 쿨다운 |

### Atom 함수 목록

```python
# feature/risk/emergency_protocol/atoms.py

def detect_vix_spike(current_vix: float, threshold: float) -> bool:
    """VIX가 임계값을 초과했는지 확인한다."""
    ...

def detect_flash_crash(price_history: list[float], threshold_pct: float) -> bool:
    """단시간 급락 비율이 임계값을 초과했는지 확인한다."""
    ...

def detect_api_failure(consecutive_failures: int, max_failures: int) -> bool:
    """KIS API 연속 실패 횟수가 한도를 초과했는지 확인한다."""
    ...

def detect_data_staleness(last_update: datetime, max_age_seconds: int) -> bool:
    """마지막 데이터 갱신 이후 시간이 허용치를 초과했는지 확인한다."""
    ...

def detect_vpin_emergency(vpin: float, threshold: float) -> bool:
    """VPIN이 0.85를 초과했는지 확인한다."""
    ...

def build_emergency_action(scenario: str, portfolio: Portfolio) -> EmergencyResult:
    """시나리오별 긴급 조치 계획을 생성한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 이전 줄수 | 리팩토링 후 경로 |
|-----------|-----------|-----------------|
| `src/safety/emergency_protocol.py` | 704줄 | `feature/risk/emergency_protocol/` |

### 체크리스트

- [ ] 각 시나리오 감지가 독립 Atom으로 분리되어 단독 테스트가 가능하다
- [ ] `halt_trading=True`인 경우 `main.py`에서 trading loop가 반드시 중단된다
- [ ] VPIN 긴급 쿨다운 30분이 Redis에 저장된다

---

## F6.4 CapitalGuard

### 역할

초기 자본 대비 현재 자산을 추적하여 자본 보호 조건을 강제한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `portfolio` | `Portfolio` | F5.2 KISClient |
| `initial_capital` | `float` | C0.2 DB (최초 설정값) |

### OUT

```python
@dataclass
class GuardResult:
    passed: bool
    check_type: str
    current_capital: float
    drawdown_from_peak: float
    details: dict
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/safety/capital_guard.py` | `feature/risk/capital_guard/` |

### 체크리스트

- [ ] Peak Capital이 Redis에 지속적으로 업데이트된다
- [ ] 최대 낙폭 한도 초과 시 `halt_trading` 신호를 EmergencyProtocol로 전달한다

---

## F6.5 RiskGatePipeline

### 역할

7개 리스크 게이트를 순차 실행하여 종합 리스크 평가를 수행한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `trade_request` | `TradeRequest` | F5.3 OrderManager |
| `portfolio` | `Portfolio` | F5.2 KISClient |

### OUT

```python
@dataclass
class GateResult:
    all_passed: bool
    failed_gates: list[str]
    risk_score: float               # 0.0 ~ 1.0
    gate_details: dict[str, dict]   # 각 게이트 결과 상세
```

### 7개 게이트

| 번호 | 게이트 | 담당 모듈 |
|------|--------|----------|
| 1 | DailyLoss | F6.6 |
| 2 | Concentration | F6.7 |
| 3 | LosingStreak | F6.8 |
| 4 | VaR | F6.9 |
| 5 | RiskBudget | F6.10 |
| 6 | Tilt | F6.15 |
| 7 | Friction | F6.16 |

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/risk/risk_gate.py` | `feature/risk/gate_pipeline/manager.py` |

### 체크리스트

- [ ] 각 게이트가 독립 모듈(F6.6~F6.16)로 구현되고 Manager가 호출만 한다
- [ ] `all_passed=False`일 때 `failed_gates`에 실패 게이트 이름이 모두 기록된다
- [ ] `risk_score`가 실패 게이트 수와 심각도를 반영한다

---

## F6.6 DailyLossLimiter

### 역할

일일 손실 비율이 임계값을 초과하는지 확인한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `daily_pnl` | `float` | C0.3 Redis (당일 P&L) |
| `portfolio_value` | `float` | F5.2 KISClient |
| `threshold_pct` | `float` | `strategy_params` |

### OUT

```python
@dataclass
class LossLimitResult:
    passed: bool
    current_loss_pct: float
    threshold_pct: float
```

### Atom 함수

```python
# feature/risk/daily_loss/atoms.py

def calculate_daily_loss_pct(daily_pnl: float, portfolio_value: float) -> float:
    """일일 손실 비율을 계산한다."""
    ...

def is_within_daily_limit(loss_pct: float, threshold_pct: float) -> bool:
    """일일 손실이 허용 범위 내인지 확인한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/risk/daily_loss_limit.py` | `feature/risk/daily_loss/` |

### 체크리스트

- [ ] 일일 P&L이 Redis에서 조회된다 (DB 직접 쿼리 금지)
- [ ] 임계값이 `strategy_params`에서 주입된다 (하드코딩 금지)

---

## F6.7 ConcentrationLimiter

### 역할

새 거래 추가 시 포트폴리오 집중도가 한도를 초과하는지 확인한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `positions` | `list[Position]` | F5.4 PositionMonitor |
| `new_trade` | `TradeRequest` | F5.3 OrderManager |
| `max_weight_pct` | `float` | `strategy_params` |

### OUT

```python
@dataclass
class ConcentrationResult:
    passed: bool
    max_weight_pct: float
    proposed_weight_pct: float
    ticker: str
```

### Atom 함수

```python
# feature/risk/concentration/atoms.py

def calculate_ticker_weight(
    ticker: str,
    positions: list[Position],
    new_value: float,
    portfolio_value: float
) -> float:
    """신규 거래 추가 후 해당 티커의 포트폴리오 비중을 계산한다."""
    ...

def is_within_concentration_limit(
    weight_pct: float,
    max_pct: float
) -> bool:
    """집중도가 한도 이내인지 확인한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/risk/concentration.py` | `feature/risk/concentration/` |

### 체크리스트

- [ ] HardSafety의 15% 한도와 Concentration 한도가 별도로 설정 가능하다
- [ ] 한도 설정이 겹칠 경우 더 엄격한 쪽이 우선한다

---

## F6.8 LosingStreakDetector

### 역할

연속 손실 또는 단시간 급격한 손실을 감지하여 매매를 일시 중지한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `recent_trades` | `list[Trade]` | C0.2 DB |
| `loss_count_window_minutes` | `int` | `strategy_params` (기본 10) |
| `loss_amount_window_minutes` | `int` | `strategy_params` (기본 30) |

### OUT

```python
@dataclass
class StreakResult:
    streak: int
    should_halt: bool
    cooldown_until: datetime | None
    trigger_reason: str | None
```

### 중지 조건

| 조건 | 설명 |
|------|------|
| 연속 손실 | 10분 내 3회 손실 |
| 누적 손실 | 30분 내 -2% 이상 |

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/risk/losing_streak.py` | `feature/risk/losing_streak/` |

### 체크리스트

- [ ] 1시간 매매 중지 기한이 Redis에 저장된다
- [ ] `src/psychology/` (TiltDetector/TiltEnforcer)와 책임이 분리된다 (Tilt = 감정 감지, LosingStreak = 패턴 감지)

---

## F6.9 SimpleVaR

### 역할

수익률 히스토리를 기반으로 Value at Risk를 계산하여 리스크 수준을 평가한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `returns` | `list[float]` | C0.2 DB (일별 수익률) |
| `confidence` | `float` | `strategy_params` (기본 0.95) |

### OUT

```python
@dataclass
class VaRResult:
    var_pct: float
    risk_level: Literal["low", "medium", "high", "extreme"]
    confidence: float
```

### Atom 함수

```python
# feature/risk/var/atoms.py

def calculate_historical_var(
    returns: list[float],
    confidence: float
) -> float:
    """역사적 시뮬레이션 방법으로 VaR를 계산한다."""
    ...

def classify_risk_level(var_pct: float, thresholds: dict) -> str:
    """VaR 수치를 리스크 레벨로 분류한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/risk/simple_var.py` | `feature/risk/var/` |

### 체크리스트

- [ ] VaR 계산이 numpy 없이 순수 Python으로 구현 가능하다 (의존성 최소화)
- [ ] `risk_level` 분류 임계값이 `config.py`에서 설정 가능하다

---

## F6.10 RiskBudget

### 역할

일일 손실 규모에 따라 잔여 리스크 예산과 포지션 크기 배율을 제공한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `daily_losses` | `float` | C0.3 Redis |
| `budget_config` | `dict` | `strategy_params` |

### OUT

```python
@dataclass
class RiskBudgetResult:
    remaining_pct: float            # 잔여 리스크 예산 (%)
    position_scale: float           # 포지션 크기 배율 (0.0~1.0)
    current_tier: str               # 현재 리스크 티어
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/risk/risk_budget.py` | `feature/risk/risk_budget/` |

### 체크리스트

- [ ] 티어별 포지션 배율이 `strategy_params`에서 설정 가능하다
- [ ] `position_scale`이 F5.3 OrderManager에서 주문 수량 계산에 반영된다

---

## F6.11 TrailingStopLoss

### 역할

포지션의 최고가 대비 현재가 낙폭을 계산하여 트레일링 손절가를 관리한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `position` | `Position` | F5.4 PositionMonitor |
| `current_price` | `float` | F5.2 KISClient |

### OUT

```python
@dataclass
class TrailingStopResult:
    should_stop: bool
    stop_price: float
    drawdown_pct: float
    highest_price: float
```

### Atom 함수

```python
# feature/risk/trailing_stop/atoms.py

def update_highest_price(
    current_highest: float,
    current_price: float
) -> float:
    """포지션 최고가를 갱신한다."""
    ...

def calculate_trailing_stop_price(
    highest_price: float,
    trailing_pct: float
) -> float:
    """트레일링 손절가를 계산한다."""
    ...

def is_stop_triggered(
    current_price: float,
    stop_price: float
) -> bool:
    """현재가가 손절가를 하회했는지 확인한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/risk/stop_loss.py` | `feature/risk/trailing_stop/` |

### 체크리스트

- [ ] `highest_price`가 포지션 데이터에 지속적으로 기록된다
- [ ] ATR 기반 동적 트레일링 배율이 레짐별로 다르게 적용된다

---

## F6.12 DeadmanSwitch

### 역할

WebSocket 데이터 신선도를 모니터링하여 데이터 단절 시 Beast Mode 포지션을 긴급 청산한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `last_data_timestamp` | `datetime` | WebSocket 수신 시간 |
| `threshold_seconds` | `float` | `strategy_params` (기본 10) |

### OUT

```python
@dataclass
class DeadmanResult:
    is_stale: bool
    stale_seconds: float
    action: Literal["liquidate_beast", "normal"]
    affected_tickers: list[str]
```

### Atom 함수

```python
# feature/risk/deadman_switch/atoms.py

def calculate_staleness_seconds(
    last_timestamp: datetime,
    now: datetime
) -> float:
    """마지막 데이터 수신 후 경과 시간을 계산한다."""
    ...

def is_data_stale(staleness_seconds: float, threshold: float) -> bool:
    """데이터가 임계값 이상 지연되었는지 확인한다."""
    ...

def determine_deadman_action(
    is_stale: bool,
    beast_positions: list[str]
) -> tuple[str, list[str]]:
    """데이터 단절 시 수행할 조치와 청산 대상 티커를 결정한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/safety/deadman_switch.py` | `feature/risk/deadman_switch/` |

### 체크리스트

- [ ] 10초 임계값이 `strategy_params`에서 설정 가능하다
- [ ] DeadmanSwitch가 정규 세션 중 `main.py` trading loop에서 매 반복 확인된다
- [ ] EOD에서 DeadmanSwitch 상태가 초기화된다

---

## F6.13 MacroFlashCrash

### 역할

SPY 또는 QQQ의 단기 급락을 감지하여 전체 포지션 청산과 매매 중지를 실행한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `spy_prices` | `list[tuple[datetime, float]]` | F5.2 KISClient (실시간) |
| `qqq_prices` | `list[tuple[datetime, float]]` | F5.2 KISClient (실시간) |
| `threshold_pct` | `float` | `strategy_params` (기본 -1.0%) |
| `window_seconds` | `int` | `strategy_params` (기본 180) |

### OUT

```python
@dataclass
class FlashCrashResult:
    crash_detected: bool
    ticker: str | None              # 감지된 티커 (SPY 또는 QQQ)
    drop_pct: float
    action: Literal["full_liquidation_halt", "normal"]
    detected_at: datetime | None
```

### Atom 함수

```python
# feature/risk/macro_flash_crash/atoms.py

def calculate_price_drop_in_window(
    prices: list[tuple[datetime, float]],
    window_seconds: int,
    now: datetime
) -> float:
    """지정 시간 창 내 최대 가격 하락폭을 계산한다."""
    ...

def is_flash_crash(drop_pct: float, threshold_pct: float) -> bool:
    """가격 하락이 플래시 크래시 임계값을 초과했는지 확인한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/safety/macro_flash_crash.py` | `feature/risk/macro_flash_crash/` |

### 체크리스트

- [ ] SPY와 QQQ 중 하나라도 조건 충족 시 즉시 전체 청산이 실행된다
- [ ] `main.py`에서 매 trading loop 반복마다 MacroFlashCrash가 확인된다
- [ ] 감지 후 `halt_trading` 플래그가 EmergencyProtocol과 공유된다
- [ ] Fallback: 데이터 없을 시 SPY circuit breaker -3.0으로 대체된다 (0.0 금지)

---

## F6.14 GapRiskProtector

### 역할

전일 종가 대비 현재가의 갭을 분석하여 포지션 크기와 손절가를 조정한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `ticker` | `str` | 호출자 |
| `prev_close` | `float` | F5.2 KISClient |
| `current_price` | `float` | F5.2 KISClient |

### OUT

```python
@dataclass
class GapRiskResult:
    gap_level: Literal["small", "medium", "large", "extreme"]
    gap_pct: float
    size_reduction: float       # 포지션 크기 축소 비율 (0.0~1.0)
    stop_adjustment: float      # 손절가 조정 배율
    block_minutes: int          # 진입 차단 시간 (분)
```

### 갭 분류 기준

| 갭 레벨 | 조건 | 조치 |
|---------|------|------|
| `small` | 갭 < 0.5% | 조치 없음 |
| `medium` | 0.5% ≤ 갭 < 1.5% | 포지션 -30% |
| `large` | 1.5% ≤ 갭 < 3.0% | 포지션 -50% + 손절 확대 |
| `extreme` | 갭 ≥ 3.0% | 30분 진입 차단 + 타이트 손절 |

### Atom 함수

```python
# feature/risk/gap_risk/atoms.py

def calculate_gap_pct(prev_close: float, current_price: float) -> float:
    """전일 종가 대비 갭 비율을 계산한다."""
    ...

def classify_gap_level(gap_pct: float, thresholds: dict) -> str:
    """갭 크기를 레벨로 분류한다."""
    ...

def build_gap_risk_result(
    gap_pct: float,
    gap_level: str,
    adjustment_map: dict
) -> GapRiskResult:
    """갭 레벨에 따른 리스크 조치 결과를 생성한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/risk/gap_risk.py` | `feature/risk/gap_risk/` |

### 체크리스트

- [ ] 갭 임계값이 `strategy_params`에서 설정 가능하다
- [ ] `extreme` 갭 차단 시간이 Redis에 저장되어 재시작 후에도 유지된다

---

## F6.15 TiltDetector

### 역할

단기 손실 패턴을 감지하여 감정적 매매(Tilt) 상태를 판단하고 1시간 매매를 차단한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `recent_trades` | `list[Trade]` | C0.2 DB |
| `time_window_minutes` | `int` | `strategy_params` |

### OUT

```python
@dataclass
class TiltResult:
    tilted: bool
    lock_until: datetime | None
    reason: str
    loss_count: int
    loss_amount_pct: float
```

### Tilt 조건

| 조건 | 임계값 |
|------|--------|
| 연속 손실 횟수 | 10분 내 3회 |
| 누적 손실액 | 30분 내 -2% |

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/psychology/loss_tracker.py` | `feature/risk/tilt/atoms.py` |
| `src/psychology/tilt_detector.py` | `feature/risk/tilt/atoms.py` |
| `src/psychology/tilt_enforcer.py` | `feature/risk/tilt/manager.py` |
| `src/psychology/config.py` | `feature/risk/tilt/config.py` |
| `src/psychology/models.py` | `core/types/risk.py` (통합) |

### 체크리스트

- [ ] Tilt 잠금 시간(1시간)이 Redis에 저장된다
- [ ] LosingStreak(패턴 기반)과 Tilt(감정 기반)의 차이가 주석으로 명시된다
- [ ] F6.5 RiskGatePipeline Gate 6에서 TiltResult가 소비된다

---

## F6.16 FrictionCalculator

### 역할

예상 스프레드와 슬리피지를 합산하여 최소 수익 허들을 계산한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `ticker` | `str` | 호출자 |
| `expected_price` | `float` | F5.2 KISClient |
| `volume` | `float` | F5.2 KISClient |

### OUT

```python
@dataclass
class FrictionResult:
    spread_cost: float
    slippage_cost: float
    total_friction: float
    min_gain_required: float        # total_friction × 2
```

### 최소 수익 허들 공식

```
min_gain_required = (spread_cost + slippage_cost) × 2
```

### Atom 함수 목록

```python
# feature/risk/friction/atoms.py

def estimate_spread_cost(
    ticker: str,
    orderbook: OrderBook
) -> float:
    """호가 스프레드 비용을 추정한다."""
    ...

def estimate_slippage_cost(
    order_size: float,
    avg_volume: float,
    price: float
) -> float:
    """주문 크기와 거래량 비율로 슬리피지를 추정한다."""
    ...

def calculate_friction_hurdle(
    spread_cost: float,
    slippage_cost: float
) -> float:
    """(스프레드 + 슬리피지) × 2 = 최소 수익 허들을 계산한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/risk/friction/spread_cost.py` | `feature/risk/friction/atoms.py` `estimate_spread_cost()` |
| `src/risk/friction/slippage_cost.py` | `feature/risk/friction/atoms.py` `estimate_slippage_cost()` |
| `src/risk/friction/hurdle_calculator.py` | `feature/risk/friction/atoms.py` `calculate_friction_hurdle()` |
| `src/risk/friction/config.py` | `feature/risk/friction/config.py` |
| `src/risk/friction/models.py` | `core/types/risk.py` (통합) |

### 체크리스트

- [ ] 세 Atom이 독립적으로 테스트 가능하다
- [ ] `min_gain_required`가 F4.1 EntryStrategy Gate 6에서 소비된다
- [ ] 호가창이 없을 때 Fallback 스프레드 추정값이 `config.py`에 정의된다

---

## F6.17 HouseMoneyMultiplier

### 역할

당일 실현 수익에 따라 추가 리스크 감수 배율을 제공한다 (House Money Effect 활용).

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `daily_pnl` | `float` | C0.3 Redis |
| `tiers` | `dict` | `strategy_params` |

### OUT

```python
@dataclass
class HouseMoneyResult:
    multiplier: float           # 0.5x ~ 2.0x
    tier: str                   # 티어 이름
    daily_pnl: float
```

### 기본 티어 구성

| 수익 범위 | 배율 |
|----------|------|
| 손실 | 0.5x |
| ±0 | 1.0x |
| 목표의 50% 달성 | 1.5x |
| 목표 초과 | 2.0x |

### Atom 함수 목록

```python
# feature/risk/house_money/atoms.py

def determine_house_money_tier(
    daily_pnl: float,
    tier_thresholds: dict
) -> str:
    """일일 손익에 따른 House Money 티어를 결정한다."""
    ...

def get_tier_multiplier(tier: str, multiplier_map: dict) -> float:
    """티어에 따른 포지션 배율을 반환한다."""
    ...
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/risk/house_money/daily_pnl_tracker.py` | `feature/risk/house_money/atoms.py` |
| `src/risk/house_money/multiplier_engine.py` | `feature/risk/house_money/atoms.py` |
| `src/risk/house_money/config.py` | `feature/risk/house_money/config.py` |
| `src/risk/house_money/models.py` | `core/types/risk.py` (통합) |

### 체크리스트

- [ ] 티어 임계값과 배율이 `strategy_params`에서 설정 가능하다
- [ ] `multiplier`가 F5.3 OrderManager의 포지션 크기 계산에 반영된다

---

## F6.18 AccountSafety

### 역할

계좌 잔고와 포지션 상태를 점검하여 비정상 상태를 탐지한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `balance` | `Balance` | F5.2 KISClient |
| `positions` | `list[Position]` | F5.4 PositionMonitor |
| `redis` | `Redis` | C0.3 Redis |

### OUT

```python
@dataclass
class AccountSafetyResult:
    safe: bool
    warnings: list[str]
    errors: list[str]           # 즉각 조치 필요
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/safety/account_safety.py` | `feature/risk/account_safety/` |

### 체크리스트

- [ ] KIS 모의 잔고 `cash=0` 문제를 `VTTS3007R`로 보완하는 로직이 포함된다
- [ ] 에러 수준 문제가 EmergencyProtocol로 즉시 전달된다

---

## F6.19 QuotaGuard

### 역할

Claude AI API 호출 횟수를 추적하여 한도 초과를 방지한다.

### IN

| 파라미터 | 타입 | 출처 |
|----------|------|------|
| `usage_stats` | `dict` | C0.3 Redis (API 호출 카운터) |
| `quota_config` | `dict` | `strategy_params` |

### OUT

```python
@dataclass
class QuotaResult:
    can_call: bool
    remaining: int
    window_hours: int
    current_usage: int
    limit: int
```

### 현재 파일 매핑

| 현재 경로 | 리팩토링 후 경로 |
|-----------|-----------------|
| `src/safety/quota_guard.py` | `feature/risk/quota_guard/` |

### 체크리스트

- [ ] 호출 카운터가 Redis TTL로 자동 만료된다 (window_hours 설정)
- [ ] `can_call=False`일 때 F2 Analysis가 Fallback 분석을 사용한다
- [ ] F6.2 SafetyChecker가 QuotaGuard를 HardSafety 이후 순서로 체크한다

---

# 부록: 타입 중앙화 원칙

모든 공유 타입은 `core/types/` 아래에서 단일 정의된다. 각 Feature 모듈은 타입을 재정의하지 않고 import만 사용한다.

## 타입 파일 구조

```
core/
  types/
    strategy.py      # EntrySignal, ExitSignal, BeastSignal, PyramidSignal,
                     # StatArbSignal, MicroRegimeResult, FadeSignal, WickSignal,
                     # SectorSignal, BacktestResult, DecayResult, ProfitTargetStatus
    execution.py     # OrderResult, Position, Balance, OrderBook, TradeRequest
    risk.py          # SafetyResult, CheckResult, EmergencyResult, GuardResult,
                     # GateResult, FrictionResult, TiltResult, GapRiskResult,
                     # VaRResult, DeadmanResult, FlashCrashResult, HouseMoneyResult,
                     # QuotaResult, AccountSafetyResult
    common.py        # GateResult (단일 게이트), AnalysisResult, IndicatorBundle,
                     # MarketData, NewsEvent, Trade
```

---

# 부록: F4~F6 의존성 그래프

```
F4.1 EntryStrategy
  ├── F3 (Indicators): IndicatorBundle
  ├── F6.16 FrictionCalculator: friction_hurdle (Gate 6)
  ├── F4.6 MicroRegime: regime (Gate 4)
  └── F4.14 ProfitTarget: aggression_level (포지션 크기 조정)

F4.2 ExitStrategy
  ├── F4.3 BeastMode: BeastState (beast_exit 판단)
  ├── F4.7 NewsFading: FadeSignal (priority 4.5)
  └── F4.5 StatArb: StatArbSignal (priority 4.7)

F5.3 OrderManager
  ├── F4.1 / F4.2: 신호 소비
  ├── F5.2 KISClient: 주문 실행
  ├── F6.5 RiskGatePipeline: 최종 승인 전 게이트
  └── F6.17 HouseMoneyMultiplier: 포지션 크기 배율

F6.5 RiskGatePipeline
  ├── F6.6 DailyLossLimiter
  ├── F6.7 ConcentrationLimiter
  ├── F6.8 LosingStreakDetector
  ├── F6.9 SimpleVaR
  ├── F6.10 RiskBudget
  ├── F6.15 TiltDetector
  └── F6.16 FrictionCalculator

F6.1 HardSafety → F6.2 SafetyChecker → F6.5 RiskGatePipeline → F5.3 OrderManager
```

---

*이 문서는 리팩토링 진행에 따라 지속적으로 갱신된다.*
*각 모듈의 체크리스트는 PR 머지 조건으로 활용한다.*
