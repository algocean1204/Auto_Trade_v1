# Stock Trading AI System V2 - 전체 데이터 흐름 문서

> 이 문서는 시스템의 전체 데이터 흐름을 포괄적으로 기술한다.
> Phase 3-7 고급 모듈(심리 관리, 마찰 비용, 하우스 머니, 교차 자산, 고래 감지, 볼륨 프로파일,
> 마이크로 레짐, 통계적 차익거래, 뉴스 페이딩, 윅 캐처, 스캘핑, ML 파이프라인)을 모두 포함한다.

---

## 1. 시스템 아키텍처 개요

```
                          +---------------------------+
                          |     Flutter Dashboard      |
                          |     (Port 8000 API)        |
                          +-------------+-------------+
                                        |
                                   REST API
                                        |
+-----------------------------------------------------------------------+
|                         FastAPI Monitoring Server                      |
|                    (50+ endpoints, Telegram Bot)                       |
+-----------------------------------------------------------------------+
        |                       |                       |
        v                       v                       v
+---------------+    +------------------+    +-------------------+
|  TradingSystem|    |   WebSocket      |    |   Scalping        |
|  Orchestrator |    |   Pipeline       |    |   Manager         |
|  (main.py)    |    |   (ws/manager)   |    |   (scalping/)     |
+-------+-------+    +--------+---------+    +--------+----------+
        |                      |                       |
        v                      v                       v
+-------+------+    +----------+----------+    +-------+--------+
| Crawl Engine |    | KIS WebSocket       |    | Redis Pub/Sub  |
| (30 sources) |    | (Real-time Tick)    |    | (Indicators)   |
+--------------+    +---------------------+    +----------------+
        |                      |                       |
        v                      v                       v
+-------+------+    +----------+----------+    +-------+--------+
| MLX/Claude   |    | OBI/CVD/VPIN/       |    | Volume Profile |
| Classifier   |    | ExecStrength        |    | Cross-Asset    |
+--------------+    +---------------------+    | Whale Tracker  |
        |                      |               +----------------+
        v                      v
+-------+------+    +----------+----------+
| DecisionMaker|    | Redis Storage       |
| (Claude AI)  |    | (realtime:*)        |
+--------------+    +---------------------+
        |
        v
+-------+-----------------------+
| Entry Strategy                |
| (6 Filters + Kelly Sizing)    |
+-------+-----------------------+
        |
        v
+-------+-----------------------+
| Risk Gate Pipeline (7 Gates)  |
| + Friction Hurdle             |
+-------+-----------------------+
        |
        v
+-------+-----------------------+
| Order Manager                 |
| (KIS API Execution)           |
+-------+-----------------------+
        |
        v
+-------+-----------------------+
| Position Monitor              |
| + Exit Strategy (12 Checks)   |
+-------+-----------------------+
        |
        v
+------------------+  +------------------+  +------------------+
| PostgreSQL 17    |  | Redis 7          |  | Telegram         |
| + pgvector       |  | (Cache/Pub)      |  | (Notifications)  |
+------------------+  +------------------+  +------------------+
```

---

## 2. 데이터 흐름 (Data Pipeline) 전체 요약

```
[데이터 수집]
  KIS WebSocket ──────────────┐
  30 Crawlers (RSS/API/Scrape) ┤
  FRED API (VIX, CPI, Rate)   ┤
  KIS REST API (가격/호가)     ┘
           │
           v
[전처리 & 분류]
  Parser ─→ Handler ─→ Redis Pub ─→ Indicator Calculator
  MLX/Claude ─→ NewsClassifier ─→ 분류 결과 DB 저장
           │
           v
[분석 & 판단]
  RegimeDetector ─→ 레짐 결정 (VIX 기반 5단계)
  ComprehensiveAnalysisTeam ─→ 종합 분석
  DecisionMaker(Claude) ─→ 매매 판단 리스트 생성
  RAGRetriever ─→ 관련 지식 검색 (ChromaDB + bge-m3)
           │
           v
[진입 필터링]
  EntryStrategy ─→ 6개 필터 + confidence 조정 + Kelly Sizing
  RiskGatePipeline ─→ 7개 게이트 순차 검증
  FrictionHurdle ─→ 마찰 비용 대비 기대수익 검증
           │
           v
[주문 실행]
  OrderManager ─→ KIS API (매수/매도 주문)
  SafetyChecker ─→ HardSafety + QuotaGuard 검증
  TaxTracker / FXManager / SlippageTracker ─→ 세금/환율/슬리피지 추적
           │
           v
[포지션 관리]
  PositionMonitor ─→ ExitStrategy (12단계 우선순위 체크)
  TrailingStopLoss ─→ ATR 동적 스탑
  ScalpingManager ─→ Time Stop / Liquidity / Spoofing 감시
           │
           v
[피드백 & 최적화]
  DailyFeedback ─→ 일일 성과 분석
  ExecutionOptimizer ─→ 파라미터 자동 조정
  WeeklyAnalysis ─→ 주간 분석 + ML 재훈련
  TelegramNotifier ─→ 보고서 발송
```

---

## 3. 실시간 데이터 파이프라인 (WebSocket)

KIS WebSocket에서 수신되는 실시간 데이터의 처리 흐름이다.

```
KIS WebSocket (실전 서버)
    │
    ├─ [호가 데이터 수신 (TR_ORDERBOOK_US)]
    │       │
    │       v
    │   MessageParser.parse_orderbook_fields()
    │       │
    │       v
    │   OrderbookHandler.handle() ──→ Orderbook 모델 생성
    │       │
    │       v
    │   OBICalculator.calculate() ──→ OBI 값 산출
    │   OBICalculator.get_smoothed() ──→ 평활 OBI
    │   OBICalculator.get_signal() ──→ "buy"/"sell"/"neutral"
    │       │
    │       v
    │   RedisPublisher.publish_orderbook()
    │       ├─ realtime:orderbook:{ticker} ──→ 호가 스냅샷
    │       └─ realtime:indicator:{ticker} ──→ OBI 값 포함
    │
    ├─ [체결 데이터 수신 (TR_TRADE_US)]
    │       │
    │       v
    │   MessageParser.parse_trade_fields()
    │       │
    │       v
    │   TradeHandler.handle() ──→ Trade 모델 생성
    │       │
    │       ├─ CVDCalculator.update(trade) ──→ 누적 거래량 델타
    │       │   └─ detect_divergence() ──→ 가격-CVD 다이버전스 감지
    │       │
    │       ├─ ExecutionStrengthTracker.update(trade) ──→ 체결강도 추적
    │       │   ├─ get_trend() ──→ "bullish"/"bearish"/"stable"
    │       │   └─ is_surge() ──→ 급등 여부
    │       │
    │       ├─ VPINCalculator.update(trade) ──→ VPIN 독성 흐름 지표
    │       │   ├─ is_toxic() ──→ 독성 여부 (>0.85)
    │       │   └─ get_toxicity_level() ──→ "safe"/"caution"/"toxic"
    │       │
    │       v
    │   RedisPublisher.publish_trade() ──→ realtime:trade:{ticker}
    │   RedisPublisher.publish_indicators() ──→ realtime:indicator:{ticker}
    │       │
    │       │   게시되는 지표 키:
    │       │   {
    │       │     "cvd": float,              // 누적 거래량 델타
    │       │     "cvd_divergence": str|null, // "bullish"/"bearish"/null
    │       │     "execution_strength": float,// 체결강도 (0~200)
    │       │     "exec_trend": str,          // 추세 방향
    │       │     "exec_surge": bool,         // 급등 여부
    │       │     "vpin": float,              // 0.0~1.0
    │       │     "vpin_toxic": bool,         // 독성 여부
    │       │     "vpin_level": str,          // 독성 등급
    │       │     "obi": float,              // Order Book Imbalance
    │       │     "obi_signal": str          // 매수/매도/중립
    │       │   }
    │       │
    │       v
    │   TickWriter.write(trade) ──→ PostgreSQL tick_data 테이블
    │
    └─ [체결통보 수신 (암호화)]
            │
            v
        NoticeHandler.handle() ──→ AES 복호화 → 주문 체결 확인
```

### 3-1. 볼륨 프로파일 누적기 (Volume Profile)

```
realtime:trade:{ticker} (Redis)
    │
    v
VolumeProfileAccumulator.add_tick(price, volume, is_buy)
    │
    ├─ 가격을 PRICE_BUCKET_SIZE 단위로 버킷팅
    ├─ 매수/매도 구분하여 버킷별 거래량 누적
    └─ PROFILE_RESET_HOUR(KST)에 자동 초기화
    │
    v
PocCalculator.find_poc(volumes)
    │
    └─ Point of Control (최다 거래 가격대) 탐색
    │
    v
PocSignalGenerator.generate(poc, current_price)
    │
    └─ POC 대비 현재가 위치 → 지지/저항 신호 생성
```

### 3-2. 교차 자산 분석기 (Cross-Asset)

```
Redis(realtime:indicator:{리더종목})
    │
    v
LeaderAggregator.aggregate(etf_ticker)
    │
    ├─ 리더 종목(NVDA, AAPL 등)의 OBI/CVD를 가중 합산
    └─ SectorMicroMomentum 스냅샷 생성
    │
    v
DivergenceDetector.detect(etf_ticker, momentum)
    │
    ├─ 리더 OBI > 0.5 & ETF OBI < 0.1 → 불리시 다이버전스
    └─ 리더 OBI < -0.5 & ETF OBI > -0.1 → 베어리시 다이버전스
    │
    v
MomentumScorer.score(etf_ticker, momentum, divergence)
    │
    ├─ 모멘텀 가중치 (0.4) + 다이버전스 가중치 (0.35) + 가격 속도 (0.25)
    └─ 최종 신호: "strong_buy"/"buy"/"neutral"/"sell"/"strong_sell"
```

### 3-3. 고래 활동 감지기 (Whale Tracker)

```
Redis(realtime:trade:{ticker})
    │
    v
BlockDetector.detect(trade)
    │
    └─ 대량 체결 (블록 트레이드) 감지 → BlockTradeSignal
    │
    v
IcebergDetector.detect(orderbook_snapshots)
    │
    └─ 반복 소량 주문 패턴 (아이스버그 오더) 감지 → IcebergSignal
    │
    v
WhaleScorer.score(ticker)
    │
    ├─ 최근 30초간 블록 + 아이스버그 이벤트 집계
    ├─ 매수/매도 고래 금액 산출
    └─ WhaleScore: net_pressure, dominant_side, confidence
```

---

## 4. 진입 전략 흐름 (Entry Flow)

EntryStrategy.evaluate_entry()의 전체 처리 파이프라인이다.

```
[Claude AI 매매 판단]
  DecisionMaker.make_decision() ──→ {ticker, action, confidence, reason}
          │
          v
[Crash 레짐 / VIX 셧다운 체크]
  regime == "crash" 또는 VIX >= shutdown_threshold → 전원 차단, return []
          │
          v
[Kelly Criterion 계산]
  _calculate_kelly_fraction(global + ticker-level) → kelly_fraction
          │
          v
  ┌───── for each decision ─────┐
  │                              │
  │  [유효 종목 검증]             │
  │  is_valid_ticker() → False면 스킵│
  │          │                   │
  │          v                   │
  │  [방향 일치 확인]             │
  │  Claude action + 기술적 ind_direction │
  │  일치 시 → confidence +0.10  │
  │          │                   │
  │          v                   │
  │  [OBV 추세 확인]             │
  │  OBV 상승(매수): +0.05      │
  │  OBV 하락(매수): -0.10      │
  │          │                   │
  │          v                   │
  │  [거래량 확인 필터]           │
  │  20일 평균 1.5배 미만:       │
  │    confidence -0.15          │
  │          │                   │
  │          v                   │
  │  [MIN_CONFIDENCE 필터]       │
  │  adjusted_confidence < min   │
  │    → 스킵                    │
  │          │                   │
  │          v                   │
  │  ┌── Phase 3-7 추가 필터 ──┐ │
  │  │                          │ │
  │  │  (1) OBI 필터 [NEW]      │ │
  │  │  Redis realtime:indicator │ │
  │  │  매수: OBI > +0.3 요구   │ │
  │  │  매도: OBI < -0.3 요구   │ │
  │  │  미충족 → 스킵           │ │
  │  │          │                │ │
  │  │          v                │ │
  │  │  (2) Cross-Asset [NEW]   │ │
  │  │  MomentumScorer.score()  │ │
  │  │  strong_buy/buy: +0.05   │ │
  │  │  strong_sell/sell: -0.05  │ │
  │  │          │                │ │
  │  │          v                │ │
  │  │  (3) Whale Signal [NEW]  │ │
  │  │  WhaleScorer.score()     │ │
  │  │  방향 일치 + conf>0.5:   │ │
  │  │    +0.03 보너스           │ │
  │  │          │                │ │
  │  │          v                │ │
  │  │  (4) Micro-Regime [NEW]  │ │
  │  │  RegimeClassifier        │ │
  │  │  CHOPPY → min 0.80 요구  │ │
  │  │  미달 → 스킵             │ │
  │  │          │                │ │
  │  │          v                │ │
  │  │  (5) ML Predictor [NEW]  │ │
  │  │  LightGBM 매수 확률      │ │
  │  │  P < 0.5 → 매수 스킵     │ │
  │  │          │                │ │
  │  │  └──────────────────────┘ │
  │          │                   │
  │          v                   │
  │  [Inverse ETF 판단]          │
  │  regime + action → bull/bear │
  │          │                   │
  │          v                   │
  │  [포지션 크기 계산]           │
  │  Kelly Fraction 기반 상한    │
  │  종목당 max 15%              │
  │  전체 max 80%                │
  │  House Money 배율 적용 [NEW] │
  │    defensive(0.5x) / normal(1.0x) │
  │    aggressive(1.5x) / ultra(2.0x) │
  │          │                   │
  │          v                   │
  │  (6) Friction Hurdle [NEW]   │
  │  HurdleCalculator.calculate()│
  │  스프레드 + 수수료 + SEC +   │
  │  슬리피지 = 총 마찰 비용     │
  │  기대수익 < 마찰*3 → 스킵   │
  │          │                   │
  │          v                   │
  │  [진입 후보 생성]             │
  │  candidate dict 생성         │
  │                              │
  └──────────────────────────────┘
          │
          v
[Risk Gate Pipeline 검증] (별도 섹션 참조)
          │
          v
[Order Manager → KIS API 주문 실행]
```

---

## 5. 청산 전략 흐름 (Exit Flow)

ExitStrategy.check_exit_conditions()의 우선순위 체인이다.
위에서부터 순서대로 체크하며, 조건 충족 시 즉시 반환한다.

```
[포지션 모니터링 루프]
  PositionMonitor.monitor_all()
          │
          v
  ┌───── for each position ─────┐
  │                              │
  │  [1] 손절 (STOP LOSS) ◀── 최우선 │
  │  ATR 동적 스탑:              │
  │    stop_level = entry - ATR * 레짐별 승수 │
  │    strong_bull: 2.5x         │
  │    mild_bull: 2.0x           │
  │    sideways: 1.5x            │
  │    mild_bear: 1.2x           │
  │    crash: 1.0x               │
  │  폴백: 고정 -2% 손절         │
  │  → action: sell (전량, immediate) │
  │          │                   │
  │          v                   │
  │  [2] 트레일링 스탑 (TRAILING STOP) │
  │  ATR 동적 트레일링:          │
  │    stop = highest - ATR * 레짐별 승수 │
  │    strong_bull: 1.5x         │
  │    mild_bull: 1.5x           │
  │    sideways: 1.2x            │
  │    mild_bear: 1.0x           │
  │    crash: 1.0x               │
  │  폴백: 고정 비율 트레일링    │
  │  → action: sell (전량, immediate) │
  │          │                   │
  │          v                   │
  │  [3] 손익분기 스탑 (BREAKEVEN STOP) │
  │  수익 >= 1.5% → 스탑을 진입가로 이동 │
  │  현재가 < 진입가 → 청산      │
  │  → action: sell (전량, immediate) │
  │          │                   │
  │          v                   │
  │  [4] VIX 긴급 청산            │
  │  VIX > 35.0 → 전량 즉시 청산 │
  │  → action: sell (전량, immediate) │
  │          │                   │
  │          v                   │
  │  [4.5] 뉴스 페이딩 청산 [NEW] │
  │  SpikeDetector:              │
  │    60초 윈도우 가격 급등 감지 │
  │  FadeSignalGenerator:        │
  │    스파이크 디케이 단계 추적  │
  │    exit_all 또는 fade_short   │
  │  → action: sell (전량, immediate) │
  │          │                   │
  │          v                   │
  │  [4.7] StatArb 청산 [NEW]    │
  │  PairMonitor:                │
  │    본주-레버리지 스프레드 추적│
  │    평균 회귀 신호 발생 시    │
  │  → action: sell (즉시 청산)  │
  │          │                   │
  │          v                   │
  │  [5] 익절 (TAKE PROFIT)      │
  │  분할 익절 활성화 시:        │
  │    Level 1 (목표 70%): 30% 매도 │
  │    Level 2 (목표 100%): 30% 매도 │
  │    Level 3 (목표 150%): 40% 매도 │
  │  비활성 시: 전량 익절        │
  │  레짐별 목표:                │
  │    strong_bull: 4.0%         │
  │    mild_bull: 3.0%           │
  │    sideways: 2.0%            │
  │    mild_bear: 2.5%           │
  │    crash: 1.5%               │
  │  → action: sell/partial_sell │
  │          │                   │
  │          v                   │
  │  [6] 보유 기간 규칙          │
  │    day 3: 50% 부분 청산      │
  │    day 4: 75% 부분 청산      │
  │    day 5: 100% 강제 청산     │
  │  → action: partial_sell/sell │
  │          │                   │
  │          v                   │
  │  [6.5] 레버리지 Decay 체크   │
  │  LeverageDecayCalculator:    │
  │    변동성 드래그 기반 강제 청산│
  │  → action: sell              │
  │          │                   │
  │          v                   │
  │  [7] EOD 청산                │
  │  마감 30분 전 → 잔여 포지션 정리│
  │  → action: sell              │
  │                              │
  └──────────────────────────────┘
```

---

## 6. 긴급 프로토콜 (Emergency Protocols)

EmergencyProtocol 클래스가 관리하는 6가지 위기 대응 체계이다.

```
┌─────────────────────────────────────────────────────────────────┐
│                     EMERGENCY PROTOCOL                          │
├─────────┬───────────────┬───────────────────────────────────────┤
│ 프로토콜 │ 감지 조건      │ 대응 조치                            │
├─────────┼───────────────┼───────────────────────────────────────┤
│ 1. Flash │ 개별 종목      │ 해당 종목 전량 매도                  │
│  Crash   │ 5분 내 -5%    │ + 1시간 매수 금지 (쿨다운)           │
│          │ 이상 급락      │ + DB 기록 + 알림                     │
├─────────┼───────────────┼───────────────────────────────────────┤
│ 2.Circuit│ VIX >= 35 또는│ 모든 신규 매수 중단                   │
│ Breaker  │ SPY 일일 -3%  │ 기존 포지션: trailing stop 0.5%로    │
│          │ 이상 하락      │ 타이트 조정. VIX < 30 해제            │
├─────────┼───────────────┼───────────────────────────────────────┤
│ 3.System │ 프로그램       │ 재시작 시 포지션 복원                 │
│  Crash   │ 비정상 종료    │ Redis/DB에서 상태 재로드              │
├─────────┼───────────────┼───────────────────────────────────────┤
│ 4.Network│ 네트워크       │ 지수 백오프 재연결                    │
│ Failure  │ 끊김 감지      │ 5→10→20→40→60초 간격 재시도          │
│          │               │ 180초 이상 끊김 시 긴급 조치           │
├─────────┼───────────────┼───────────────────────────────────────┤
│ 5.Runaway│ 일일 손실      │ 전면 청산 (모든 포지션)               │
│  Loss    │ -5% 도달       │ 당일 매매 완전 중단                   │
├─────────┼───────────────┼───────────────────────────────────────┤
│ 6. VPIN  │ VPIN > 0.85   │ 해당 종목 긴급 매도 [NEW]             │
│ Emergency│ (95th pctile) │ + 30분 매매 잠금 (쿨다운)             │
│          │               │ 독성 흐름 감지 시 자동 발동            │
└─────────┴───────────────┴───────────────────────────────────────┘
```

### 긴급 프로토콜 판단 흐름

```
매매 루프 시작
    │
    v
_fetch_vix() + SPY 일중 변동률 조회
    │
    v
EmergencyProtocol.detect_circuit_breaker(vix, spy_change)
    │
    ├─ VIX >= 35 또는 SPY <= -3% → CIRCUIT BREAKER 발동
    │   └─ 루프 전체 건너뜀, Telegram 알림
    │
    ├─ (루프 내) 포지션별 Flash Crash 체크
    │   └─ 5분 내 -5% → 즉시 전량 매도 + 1시간 쿨다운
    │
    ├─ (포지션 모니터) VPIN 독성 체크 [NEW]
    │   └─ VPIN > 0.85 → 긴급 매도 + 30분 잠금
    │
    └─ (루프 내) Runaway Loss 체크
        └─ 일일 손실 -5% → 전면 청산 + 당일 중단
```

---

## 7. 리스크 게이트 파이프라인 (Risk Gate Pipeline)

RiskGatePipeline.check_all()이 7개 게이트를 순차 실행한다.
**하나라도 실패하면 매매를 차단한다.**

```
┌──────────────────────────────────────────────────────────────┐
│                  RISK GATE PIPELINE                           │
│                  (순차 실행, 하나라도 FAIL → 차단)             │
├──────┬──────────────────┬────────────────────────────────────┤
│ Gate │ 모듈              │ 검증 내용                          │
├──────┼──────────────────┼────────────────────────────────────┤
│  1   │ DailyLossLimiter │ 일일 손실 한도 초과 여부            │
│      │                  │ 초과 → action: "block"              │
├──────┼──────────────────┼────────────────────────────────────┤
│  2   │ Concentration    │ 단일 종목/섹터 집중도 한도           │
│      │ Limiter          │ 종목당 max 15%, 전체 max 80%       │
├──────┼──────────────────┼────────────────────────────────────┤
│  3   │ LosingStreak     │ 연속 손실 감지                      │
│      │ Detector         │ 연패 N회 → 포지션 축소/차단         │
├──────┼──────────────────┼────────────────────────────────────┤
│  4   │ SimpleVaR        │ Value at Risk 초과 여부              │
│      │                  │ 포트폴리오 VaR 검증                  │
├──────┼──────────────────┼────────────────────────────────────┤
│  5   │ SectorCorrelation│ 섹터 상관관계 집중도                 │
│      │ Gate             │ 고상관 섹터 편중 방지                │
├──────┼──────────────────┼────────────────────────────────────┤
│  6   │ TiltEnforcer     │ 틸트(감정적 매매) 잠금 [NEW]        │
│      │ [Phase 3]        │ 잠금 중 → action: "halt"            │
│      │                  │ 연속 3손실/30분 -2% → 틸트 발동     │
├──────┼──────────────────┼────────────────────────────────────┤
│  7   │ HurdleCalculator │ 마찰 비용 허들 (주문 단위) [NEW]    │
│      │ [Phase 4]        │ 기대수익 < 마찰비용 * 3 → 차단     │
│      │                  │ 스프레드+수수료+SEC+슬리피지 합산    │
└──────┴──────────────────┴────────────────────────────────────┘

Pipeline 결과:
  can_trade: bool ──→ 모든 게이트 통과 여부
  blocking_gates: list[str] ──→ 차단된 게이트 이름
  overall_action: "allow"/"reduce"/"block"/"halt"
    (가장 심각한 action이 전체 action이 된다)
```

### 주문 단위 2차 검증

```
RiskGatePipeline.check_order(order, portfolio)
    │
    ├─ ConcentrationLimiter.check_order() → 주문 포함 집중도 재검증
    └─ 기타 주문 단위 게이트 검증
```

---

## 8. 스캘핑 마이크로매니지먼트 (Scalping Manager)

ScalpingManager가 3가지 하위 시스템을 통합 관리한다.

```
┌──────────────────────────────────────────────────────────────┐
│                   ScalpingManager                             │
│                   (src/scalping/manager.py)                   │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Redis(realtime:orderbook/trade/indicator)                   │
│      │                                                       │
│      ├────────────────┬─────────────────┬──────────────────  │
│      v                v                 v                    │
│  ┌─────────┐   ┌───────────┐   ┌──────────────┐            │
│  │TimeStop │   │ Liquidity │   │  Spoofing    │            │
│  │ System  │   │  Sizing   │   │ Detection   │            │
│  └────┬────┘   └─────┬─────┘   └──────┬───────┘            │
│       │              │                 │                     │
│       v              v                 v                     │
│  PositionTimer  DepthAnalyzer   SnapshotTracker              │
│       │              │                 │                     │
│       v              v                 v                     │
│  MomentumEval   SpreadMonitor   PatternDetector              │
│       │              │                 │                     │
│       v              v                 v                     │
│  TimeStopExec   ImpactEstimator ToxicityScorer               │
│       │              │                 │                     │
│       v              v                 v                     │
│  TimeStopAction LiquiditySizer  TradeLock                    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 8-1. Time Stop 시스템

```
register_entry(ticker, entry_price)
    │
    v
PositionTimer: 진입 시점부터 타이머 시작
    │
    v
MomentumEvaluator: Redis에서 체결 데이터 읽어 모멘텀 평가
    │
    ├─ 시간 초과 + 모멘텀 부재 → TIME_STOP 발동
    └─ 모멘텀 존재 → 타이머 연장
    │
    v
TimeStopExecutor: 청산 신호 생성 (TimeStopAction)
```

### 8-2. 유동성 기반 사이징

```
get_safe_sizing(ticker, base_qty, price)
    │
    v
DepthAnalyzer: 호가창 깊이 분석 (매수/매도 벽 탐색)
    │
    v
SpreadMonitor: 실시간 스프레드 추적
    │
    v
ImpactEstimator: 시장 충격 비용 추정
    │
    v
LiquidityAwareSizer: 안전 수량 산출
    └─ 주문량 > 호가 깊이 * 비율 → 수량 축소
```

### 8-3. 스푸핑 감지

```
check_toxicity(ticker, vpin_value)
    │
    v
SnapshotTracker: 호가창 스냅샷 시계열 추적
    │
    v
PatternDetector: 스푸핑 패턴 감지
    ├─ 대량 주문 후 즉시 취소
    └─ 호가창 양쪽 비대칭 반복
    │
    v
ToxicityScorer: VPIN + 패턴 감지 종합 독성 점수
    │
    v
TradeLock: 독성 > 임계치 → 해당 종목 매매 잠금
    └─ MIN_DETECTIONS 이상 감지 시 발동
```

---

## 9. 심리 관리 (Psychology - Tilt Management)

Phase 3에서 도입된 감정적 매매 방지 시스템이다.

```
[거래 완료]
    │
    v
LossTracker.record_trade(pnl_pct, ticker)
    │
    ├─ 인메모리 deque에 거래 결과 기록 (최대 1000건)
    └─ TradeResult: {timestamp, pnl_pct, ticker}
    │
    v
TiltDetector.detect()
    │
    ├─ 조건 1: 10분 윈도우 내 연속 손실 >= 3회
    ├─ 조건 2: 30분 윈도우 내 누적 PnL <= -2%
    │
    ├─ 양쪽 모두 미충족: NORMAL 상태
    ├─ 경고 수준 (임계값 66%): WARNING 상태
    └─ 하나라도 충족: TILTED 상태
    │
    v
TiltEnforcer._evaluate()
    │
    ├─ TILTED 감지 시:
    │   ├─ 잠금 발동 (TILT_LOCK_DURATION)
    │   ├─ _tilt_count_today 증가
    │   ├─ 재발 시 에스컬레이션: duration * ESCALATION_MULTIPLIER
    │   └─ 잠금 중 모든 신규 진입 차단
    │
    ├─ 잠금 만료 시:
    │   └─ RECOVERING 상태 전환 → 점진적 복귀
    │
    └─ is_entry_allowed() → Risk Gate Pipeline에서 호출
        ├─ 잠금 중: False (Gate 6 차단)
        └─ 잠금 아님: True (Gate 6 통과)

[에스컬레이션 흐름]
  1차 틸트: 기본 잠금 시간
  2차 틸트: 기본 * 에스컬레이션 배율
  3차 틸트: 기본 * 에스컬레이션^2
  ...
  매일 EOD에서 _tilt_count_today 리셋
```

---

## 10. ML 파이프라인 (Optimization)

주간 단위 자동 훈련 및 TimeTravelTrainer 리플레이 시스템이다.

### 10-1. 주간 자동 훈련 (Weekly Training)

```
[일요일 주간 분석 시 실행]
  run_weekly_training()
          │
          v
[Step 1] DataPreparer.prepare(tickers)
    KIS API에서 가격 데이터 수집 (SOXL, QLD, TQQQ)
          │
          v
[Step 2] FeatureEngineer.build_features(raw_df)
    기술적 지표 피처 생성:
    RSI(7/14/21), MACD, BB, ATR, 거래량 비율 등
          │
          v
[Step 3] TargetBuilder.build_targets(df)
    N분 후 수익률 기반 바이너리 타겟 생성
    (TARGET_GAIN_THRESHOLD 이상 → 1, 미만 → 0)
          │
          v
[Step 4] LGBMTrainer.train(features, targets)
    LightGBM 모델 훈련
          │
          v
[Step 5] OptunaOptimizer.optimize()
    하이퍼파라미터 최적화 (Optuna)
    trailing_stop_pct, take_profit_pct 등 탐색
          │
          v
[Step 6] WalkForwardEvaluator.evaluate()
    Walk-Forward 교차 검증
    Sharpe Ratio >= MIN_SHARPE 확인
          │
          v
[Step 7] 모델 저장 + strategy_params.json 업데이트
    models/lgbm_scalper.pkl 저장
    최적 파라미터 → strategy_params.json 반영
          │
          v
[EntryStrategy] set_ml_predictor()
    다음 주 매매 루프에서 ML 필터로 활용
```

### 10-2. TimeTravelTrainer (과거 리플레이)

```
TimeTravelTrainer.run_simulation(df, start_date, end_date)
    │
    v
[1분 단위 리플레이]
  for each minute in range:
    │
    ├─ FeatureEngineer로 해당 시점 피처 생성
    ├─ LightGBM 모델로 예측 (매수/홀드)
    ├─ 실제 N분 후 수익률로 정답 확인
    │
    ├─ 예측 성공: correct_count 증가
    └─ 예측 실패: failure_pattern 기록
        └─ RAGDocUpdater → ChromaDB에 실패 패턴 저장
           (향후 학습에 활용)
    │
    v
[주간 블록 단위 성과 집계]
  weekly_metrics: 정확도, Sharpe, 승률 등
```

---

## 11. EOD 시퀀스 (End of Day)

장 마감 후 run_eod_phase()에서 실행되는 10단계 + 추가 단계이다.

```
run_eod_phase() — 장 마감 후 실행
    │
    ├─ [1/9] Overnight Judgment
    │   OvernightJudge.judge(positions, signals, regime)
    │   → 보유 포지션 오버나이트 유지/청산 판단
    │   → 청산 결정 시 즉시 매도 실행
    │
    ├─ [2/9] Daily Feedback
    │   DailyFeedback.generate(today)
    │   → 당일 성과 분석 (승률, PnL, 거래 수 등)
    │   → RAGDocUpdater로 지식 업데이트
    │
    ├─ [3/9] Benchmark Snapshot
    │   BenchmarkComparison.record_daily_snapshot()
    │   → AI 수익률 vs SPY vs SSO 비교 기록
    │
    ├─ [4/9] Telegram 최종 종합 보고서
    │   _send_final_daily_report()
    │   → 일일 성과 + 매매 내역 + 리스크 게이트 차단 내역
    │
    ├─ [4-1] 종합분석팀 EOD 보고서
    │   ComprehensiveAnalysisTeam.generate_eod_report()
    │   → 오늘 분석 vs 실제 결과 비교
    │   → Redis 저장 (7일 보존) + Telegram 발송
    │
    ├─ [5/9] Daily PnL Log + Profit Target Update
    │   ProfitTargetManager.log_daily_pnl()
    │   → 월간 수익 목표 대비 진행률 갱신
    │   → 공격성 조절 (목표 달성 근접 시 보수적)
    │
    ├─ [6/9] Risk Budget Update
    │   RiskBudget.update_budget()
    │   → 다음 거래일 리스크 예산 재배분
    │
    ├─ [7/9] Reset Daily Risk Counters
    │   DailyLossLimiter.reset_daily()
    │   → 일일 손실 카운터 초기화
    │
    ├─ [7-1] Advanced Module Daily Reset [NEW]
    │   TiltEnforcer.reset_daily()
    │   → 틸트 카운터 / 에스컬레이션 리셋
    │   DailyPnlTracker.reset_daily()
    │   → 하우스 머니 PnL 추적기 리셋
    │
    ├─ [7-2] Execution Optimizer [NEW]
    │   run_eod_optimization()
    │   → 당일 거래 분석 (TradeAnalyzer)
    │   → 파라미터 튜닝 제안 (ParamTuner)
    │   → strategy_params.json 자동 조정 (ParamWriter)
    │   → Telegram 요약 발송
    │
    ├─ [8/9] Forced Liquidation Check
    │   ForcedLiquidator.check_and_liquidate()
    │   → 보유 3일 이상 포지션 강제 청산 (50%/75%/100%)
    │
    ├─ [9/9] Cleanup
    │   QuotaGuard.cleanup()
    │   → API 호출 제한 카운터 정리
    │
    └─ [10/10] Live Readiness Check
        LiveReadinessChecker.check_and_notify()
        → 7가지 기준 평가 (5거래일, 95% 가동률, 수익률 등)
        → 모의투자 → 실전 전환 준비도 Telegram 알림
```

### 주간 분석 시퀀스 (일요일)

```
run_weekly_analysis()
    │
    ├─ WeeklyAnalysis.generate(week_start)
    │   → 주간 성과 분석 + 파라미터 조정 제안
    │
    ├─ BenchmarkComparison.check_underperformance()
    │   → 벤치마크 대비 언더퍼포먼스 경고
    │
    ├─ Telegram 주간 리포트 발송
    │
    └─ run_weekly_training() [Phase 7 ML] [NEW]
        → LightGBM 모델 재훈련
        → Optuna 하이퍼파라미터 최적화
        → Walk-Forward 검증
        → strategy_params.json 업데이트
```

---

## 12. 모듈 의존성 맵

각 모듈이 어떤 모듈에 의존하는지를 나타낸다.
화살표 방향은 "사용한다" 관계이다.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CORE INFRASTRUCTURE                              │
│                                                                         │
│  PostgreSQL 17 + pgvector ◄── SQLAlchemy 2.0 async ORM                  │
│  Redis 7 ◄── redis.asyncio (캐시, Pub/Sub, 실시간 데이터)               │
│  KIS API ◄── KISAuth + KISClient (인증, 주문, 시세)                     │
│  Claude API ◄── ClaudeClient (Opus/Sonnet, 매매 판단)                   │
│  MLX ◄── MLXClassifier (로컬 AI, Qwen3-30B-A3B)                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────────────────────┐
│                        DATA COLLECTION LAYER                            │
│                                                                         │
│  CrawlEngine (30 sources) ─────┐                                       │
│  KIS WebSocket ────────────────┤──→ Redis                               │
│  FRED API (VIX, CPI) ─────────┤                                        │
│  KIS REST (가격/호가) ─────────┘                                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────────────────────┐
│                        ANALYSIS LAYER                                   │
│                                                                         │
│  NewsClassifier ──→ MLXClassifier / ClaudeClient                       │
│  RegimeDetector ──→ ClaudeClient + VIX                                 │
│  ComprehensiveAnalysisTeam ──→ ClaudeClient                            │
│  RAGRetriever ──→ BGEEmbedder + ChromaDB/pgvector                      │
│                                                                         │
│  ┌── 실시간 지표 계산 (WebSocket → Redis) ──┐                           │
│  │ OBICalculator, CVDCalculator,            │                           │
│  │ VPINCalculator, ExecutionStrength        │                           │
│  └──────────────────────────────────────────┘                           │
│                                                                         │
│  ┌── Phase 3-7 고급 지표 ──────────────────┐                            │
│  │ LeaderAggregator ──→ Redis              │                            │
│  │ DivergenceDetector ──→ Redis            │                            │
│  │ MomentumScorer ──→ Redis                │                            │
│  │ BlockDetector ──→ Redis                 │                            │
│  │ IcebergDetector ──→ Redis               │                            │
│  │ WhaleScorer ──→ BlockDetector, Iceberg  │                            │
│  │ VolumeProfileAccumulator ──→ Redis      │                            │
│  │ PocCalculator, PocSignalGenerator       │                            │
│  └─────────────────────────────────────────┘                            │
│                                                                         │
│  ┌── 기술적 지표 ──────────────────────────┐                            │
│  │ PriceDataFetcher ──→ KISClient          │                            │
│  │ TechnicalCalculator (RSI, MACD, BB 등)  │                            │
│  │ IndicatorAggregator ──→ Calculator      │                            │
│  │ IntradayFetcher ──→ Redis/API           │                            │
│  │ IntradayCalculator (VWAP, 분봉 지표)    │                            │
│  └─────────────────────────────────────────┘                            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────────────────────┐
│                        DECISION LAYER                                   │
│                                                                         │
│  DecisionMaker ──→ ClaudeClient + RAGRetriever + IndicatorAggregator   │
│       │              + ProfitContext + RiskContext + ComprehensiveAnalysis│
│       │              + IntradayContext (VWAP)                            │
│       v                                                                 │
│  EntryStrategy ──→ StrategyParams + MarketHours                         │
│       │           + Redis (OBI 필터)                                    │
│       │           + MomentumScorer (Cross-Asset)                        │
│       │           + WhaleScorer (고래 신호)                              │
│       │           + HurdleCalculator (마찰 허들)                         │
│       │           + RegimeClassifier (마이크로 레짐)                     │
│       │           + LGBMTrainer (ML 예측)                               │
│       │           + TickerParamsManager (종목별 파라미터)                │
│       v                                                                 │
│  ExitStrategy ──→ StrategyParams + MarketHours                          │
│                 + LeverageDecayCalculator                               │
│                 + SpikeDetector + FadeSignalGenerator (뉴스 페이딩)      │
│                 + PairMonitor (StatArb 청산)                            │
│                 + TickerParamsManager                                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────────────────────┐
│                        RISK MANAGEMENT LAYER                            │
│                                                                         │
│  RiskGatePipeline (7 Gates):                                           │
│    ├─ DailyLossLimiter                                                 │
│    ├─ ConcentrationLimiter                                             │
│    ├─ LosingStreakDetector                                              │
│    ├─ SimpleVaR                                                        │
│    ├─ SectorCorrelationGate                                            │
│    ├─ TiltEnforcer ──→ TiltDetector ──→ LossTracker [Phase 3]          │
│    └─ HurdleCalculator ──→ SpreadCost + SlippageCost [Phase 4]         │
│                                                                         │
│  EmergencyProtocol (6 프로토콜)                                        │
│  CapitalGuard (자본 보호)                                              │
│  HardSafety (하드코딩 안전 규칙)                                       │
│  SafetyChecker ──→ QuotaGuard + HardSafety                             │
│                                                                         │
│  House Money Sizer [Phase 4]:                                           │
│    MultiplierEngine ──→ DailyPnlTracker                                │
│    (당일 수익 시 공격적, 손실 시 방어적 사이징)                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────────────────────┐
│                        EXECUTION LAYER                                  │
│                                                                         │
│  OrderManager ──→ KISClient + SafetyChecker                             │
│                 + TaxTracker + SlippageTracker                          │
│                                                                         │
│  PositionMonitor ──→ KISClient + ExitStrategy                           │
│                    + OrderManager + HardSafety                          │
│                                                                         │
│  ForcedLiquidator ──→ OrderManager                                     │
│  UniverseManager (ETF 종목 관리)                                       │
│                                                                         │
│  ScalpingManager [Phase 5]:                                             │
│    ├─ TimeStop: PositionTimer + MomentumEvaluator + TimeStopExecutor   │
│    ├─ Liquidity: DepthAnalyzer + SpreadMonitor + ImpactEstimator       │
│    │            + LiquidityAwareSizer                                   │
│    └─ Spoofing: SnapshotTracker + PatternDetector + ToxicityScorer     │
│                + TradeLock                                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────────────────────┐
│                        FEEDBACK & OPTIMIZATION LAYER                    │
│                                                                         │
│  DailyFeedback ──→ ClaudeClient + RAGDocUpdater                        │
│  WeeklyAnalysis ──→ ClaudeClient + ParamAdjuster                       │
│  ParamAdjuster ──→ StrategyParams (파라미터 조정 제안)                   │
│                                                                         │
│  ExecutionOptimizer [Phase 7]:                                          │
│    TradeAnalyzer → ParamTuner → ParamWriter                            │
│    (EOD 자동 파라미터 조정)                                             │
│                                                                         │
│  ML Pipeline [Phase 7]:                                                 │
│    DataPreparer → FeatureEngineer → TargetBuilder                      │
│    → LGBMTrainer → OptunaOptimizer → WalkForwardEvaluator              │
│    → AutoTrainer (주간 자동 실행)                                       │
│    + TimeTravelTrainer (과거 리플레이 시뮬레이션)                       │
│                                                                         │
│  BenchmarkComparison ──→ KISClient (SPY/SSO 비교)                      │
│  ProfitTargetManager (월간 수익 목표 관리)                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────────────────────┐
│                        MONITORING & NOTIFICATION LAYER                   │
│                                                                         │
│  FastAPI Server (50+ endpoints, port 8000)                              │
│  Flutter Dashboard (모바일/웹 대시보드)                                  │
│  TelegramNotifier (매매 알림, 일일/주간 보고서)                          │
│  TelegramBotHandler (양방향 명령)                                       │
│  AlertManager (시스템 경고)                                             │
│  IndicatorCrawler (1시간 주기 매크로 지표 크롤링)                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 13. 전략별 특수 모듈

### 13-1. 뉴스 페이딩 전략 (News Fading) [Phase 6]

```
[실시간 틱 데이터]
    │
    v
SpikeDetector.update(ticker, price, volume_per_sec)
    │
    ├─ 60초 롤링 윈도우에서 가격 변동률 추적
    ├─ 변동률 > NEWS_SPIKE_THRESHOLD_PCT → NewsSpike 생성
    └─ 활성 스파이크의 진행 단계 업데이트
        ├─ INITIAL: 급등 감지 직후
        ├─ PEAK_DETECTION: 최고가 탐색 중
        └─ FADING: 거래량 감소 + 가격 하락 추적
    │
    v
FadeSignalGenerator.generate(spike)
    │
    ├─ 스파이크 디케이 패턴 분석
    ├─ 거래량 연속 감소 (N틱) 확인
    └─ "exit_all" 또는 "fade_short" 신호 생성
    │
    v
ExitStrategy._check_news_fade_exit(position, current_price)
    └─ 해당 종목 보유 중이면 즉시 청산
```

### 13-2. 통계적 차익거래 (Stat-Arb) [Phase 6]

```
PairMonitor.check_all_pairs()
    │
    v
Redis에서 본주/레버리지 최신 체결 가격 조회
    │
    v
SpreadCalculator.update(underlying_price, leveraged_price)
    │
    ├─ 이론 가격 = underlying_price * leverage_ratio
    ├─ 스프레드 = (leveraged_price - 이론 가격) / 이론 가격
    └─ z-score 계산 (평균 회귀 판단)
    │
    v
SignalGenerator.check(z_score, spread_history)
    │
    ├─ z-score > 상한 → 매도 신호 (고평가)
    ├─ z-score < 하한 → 매수 신호 (저평가)
    └─ z-score 정상 범위 → 보유 중이면 청산 (평균 회귀)
    │
    v
StatArbSignal → ExitStrategy._check_stat_arb_exit()
```

### 13-3. 윅 캐처 (Wick Catcher) [Phase 6]

```
ActivationChecker.check(ticker)
    │
    ├─ Redis에서 VPIN, CVD 조회
    ├─ VPIN > 0.7 AND CVD < -0.6 → 활성화
    └─ 독성 흐름 + 압도적 매도 압력 = 급락 윅 예상
    │
    v (활성화 시)
OrderPlacer.place_limit_order(ticker, price, quantity)
    │
    └─ 급락 예상 가격에 지정가 매수 주문
    │
    v (체결 시)
BounceExit.check_bounce(ticker, entry_price, current_price)
    │
    ├─ 반등 목표가 도달 → 즉시 익절
    └─ 시간 초과 또는 추가 하락 → 손절
```

---

## 14. 매매 루프 1회 반복 (Trading Loop Iteration)

run_trading_loop_iteration()의 7단계 + 보조 단계이다.

```
[0] 긴급 프로토콜 체크
    VIX 조회 + SPY 일중 변동률 조회
    circuit_breaker 감지 → True면 루프 전체 건너뜀

[1/7] Fast Crawling (장중 모드)
    CrawlEngine.run_fast() → 최대 10개 고속 소스, 5초 타임아웃
    실패 시 CrawlEngine.run(mode="delta") 폴백

[1-1] Tier 기반 실시간 데이터 수집
    CNN Fear&Greed, Polymarket, Kalshi, Finviz 등
    build_ai_context_compact() → AI 컨텍스트 문자열 생성

[2/7] Classify New Articles
    NewsClassifier.classify_batch() → 분류 결과

[3/7] Risk Gate Pre-Check
    RiskGatePipeline.check_all(portfolio)
    차단 → 루프 조기 종료 + Telegram 알림

[4/7] Make Trading Decisions
    _get_current_regime() → VIX 기반 레짐 결정
    가격 데이터 조회 (레버리지 ETF는 본주 데이터로 분석)

[4-1/7] 장중 분봉 데이터 수집 및 VWAP 계산
    IntradayFetcher + IntradayCalculator → VWAP, 분봉 지표

    DecisionMaker.make_decision() → Claude AI 매매 판단
    (profit_context + risk_context + comprehensive_analysis 포함)

[5/7] Execute Trades
    _execute_decisions() → EntryStrategy + RiskGate + OrderManager
    체결 시 Telegram 알림 (AI 매매 근거 3줄 요약)

[6/7] Monitor Positions
    PositionMonitor.sync_positions() + monitor_all(regime, vix)
    → ExitStrategy 12단계 체크

[7/7] Trailing Stop Check
    TrailingStopLoss.check_all_positions()
    발동 시 Telegram 알림
```

---

## 15. 전체 시스템 일과 타임라인 (KST 기준)

```
22:00~23:00  서버 상시 대기 (FastAPI on port 8000)
             Flutter 대시보드에서 Trading Start 버튼 또는
             POST /api/trading/start → 자동매매 루프 시작

23:00        [Pre-market 준비 단계]
             전체 크롤링 (30 sources) → 분류 → 분석
             종합분석팀(ComprehensiveAnalysisTeam) 분석
             안전 체크 + 레짐 결정 + Telegram 보고

23:00~06:00  [연속 분석 (30분 주기)]
             연속 크롤링 → 이슈 분석 → Redis 저장

23:30/00:30  [미국 정규장 개시 (서머타임/비서머타임)]
(DST/EST)    WebSocket 실시간 데이터 파이프라인 시작
             매매 루프 동적 주기:
               power_open (개장 직후): 90초
               mid_session (중반): 180초
               power_hour (마감 1시간 전): 120초

06:00        [Auto-Stop]
             _auto_stop_triggered → 매매 루프 종료
             → EOD 시퀀스 자동 실행
             → Telegram 종료 보고서
             (서버는 계속 실행, 다음날 대기)

일요일       [주간 분석]
             WeeklyAnalysis + BenchmarkComparison
             ML 파이프라인 재훈련 (LightGBM + Optuna)
             Telegram 주간 리포트
```

---

## 16. Redis 키 구조

시스템에서 사용하는 주요 Redis 키 목록이다.

```
realtime:trade:{ticker}          체결 데이터 (WebSocket)
realtime:orderbook:{ticker}      호가 데이터 (WebSocket)
realtime:indicator:{ticker}      실시간 지표 (OBI, CVD, VPIN 등)

trading:daily_summary:{date}     일일 매매 요약
trading:regime_cache             레짐 캐시 (TTL 300초)

comprehensive_analysis:{date}    종합분석팀 분석 결과
comprehensive_analysis:eod:{date} 종합분석팀 EOD 보고서

live_trading_recommended         실전전환 추천 플래그
```

---

## 17. 주요 설정 파일

```
strategy_params.json             전략 파라미터 (MIN_CONFIDENCE, 손절%, 익절% 등)
                                 + scaled_exit_enabled/ratios/levels
                                 + survival_trading 섹션

data/trading_principles.json     7개 시스템 원칙 + core_principle
                                 + 사용자 편집 가능 원칙

data/kis_token.json              KIS 모의투자 토큰 (1일 1회 발급)
data/kis_real_token.json         KIS 실전 토큰

models/lgbm_scalper.pkl          LightGBM 스캘핑 예측 모델

.env                             API 키, 계좌 번호, 포트 등
```

---

> 이 문서는 시스템의 전체 데이터 흐름을 한 눈에 파악할 수 있도록 작성되었다.
> 새로운 개발자가 이 문서만으로 시스템의 구조와 각 모듈의 역할을 이해할 수 있어야 한다.
