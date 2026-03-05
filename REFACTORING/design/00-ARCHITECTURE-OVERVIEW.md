# 00. Stock Trading AI System V2 — 리팩토링 아키텍처 개요

> 작성일: 2026-02-26
> 버전: v1.0
> 설계 원칙: 모듈 = 블록. 각 블록의 IN/OUT 형식을 명확히 고정하고, 블록을 조립하여 기능을 완성한다.

---

## 1. 설계 철학

### 1.1 핵심 원칙

현재 시스템은 `src/main.py`가 1,000줄을 초과하고, 수십 개의 모듈이 서로 직접 참조하며, 인프라 코드가 비즈니스 로직과 뒤섞여 있다. 리팩토링의 목표는 다음과 같다.

**모듈 = 블록이다.** 각 블록은 명확한 입력(IN)과 출력(OUT) 계약을 가지며, 블록을 조립하여 전체 기능을 완성한다. 어떤 블록도 내부 구현을 외부에 노출하지 않는다.

### 1.2 3계층 구조 (비협상 원칙)

```
Feature (도메인 경계)
    └── Manager (오케스트레이션, 50줄 이하)
            └── Atom (순수 함수, 30줄 이하)
```

| 계층 | 역할 | 규칙 |
|---|---|---|
| **Atom** | 가장 작은 단위 순수 함수 | 하나의 함수 = 하나의 동작. 외부 인프라 직접 import 금지. 파라미터로 DI. 30줄 이하. |
| **Manager** | 비즈니스 로직 순서 제어 | 직접 로직 수행 금지. Atom 호출 + 데이터 전달만. 50줄 이하. |
| **Feature** | 비즈니스 도메인 단위 | 폴더로 구분. Feature 간 직접 호출 금지. EventBus로 통신. |

### 1.3 5대 설계 원칙

1. **단방향 의존성**: 하위 계층 → 상위 계층 참조 금지. Atom은 Manager를, Manager는 Feature를 알지 못한다.
2. **DI 필수**: Atom은 DB, Redis, HTTP 클라이언트를 직접 import하지 않는다. Manager가 Common에서 꺼내 파라미터로 주입한다.
3. **Common 분리**: 인프라(DB, Redis, 로깅, 설정)는 반드시 `src/common/`에 구현한다. Feature 폴더 안에 인프라 코드를 두지 않는다.
4. **이벤트 디커플링**: Feature 간 직접 호출 금지. `C0.10 EventBus`를 통해서만 통신한다.
5. **파일 크기 제한**: Atom 30줄, Manager 50줄, 파일 200줄, 컴포넌트 150줄을 초과하지 않는다.

---

## 2. 기술 스택

| 영역 | 기술 | 버전 | 역할 |
|---|---|---|---|
| 메인 백엔드 | FastAPI + Python | 3.12 LTS | 매매 로직, AI 분석, 크롤링, API 서버 |
| AI (클라우드) | Claude API | Sonnet/Opus | 종합 분석, 매매 판단 |
| AI (로컬) | Qwen3-30B-A3B (MLX) | 4bit 양자화 | 뉴스 분류, 폴백 추론 |
| 브로커 | KIS OpenAPI | v1 | 주문 실행, 잔고 조회, 시세 |
| DB | PostgreSQL 17 + pgvector | 17.x | 영구 저장, 벡터 임베딩 |
| 캐시 | Redis | 7.x | 실시간 데이터, 세션 캐시 |
| 대시보드 | Flutter | 최신 LTS | macOS Desktop 모니터링 & 제어 |
| 알림 | Telegram Bot API | v6+ | 매매 알림, 일일 보고서 |
| 스케줄링 | macOS LaunchAgent | - | 23:00~06:30 KST 야간 자동 실행 |
| ML | LightGBM + Optuna | 4.6.0 / 4.7.0 | 피처 학습, 하이퍼파라미터 최적화 |
| 벡터 DB | ChromaDB | 최신 | RAG 지식 관리 |

> **중요**: MLX 기반 로컬 AI는 Apple Silicon MPS 접근이 필요하므로 Docker 컨테이너 외부 호스트 머신에서 실행한다. FastAPI를 통해 `host.docker.internal`로 연결된다.

---

## 3. 모듈 블록 체계

모든 Feature는 `F{번호}_{도메인}/` 폴더로 구성된다. 각 Feature는 아래 표준 하위 구조를 따른다.

```
f{n}_{domain}/
├── manager/     ← Manager 계층 (비즈니스 로직 순서 제어)
├── atom/        ← Atom 계층 (순수 함수 단위)
├── schema/      ← Pydantic 스키마 (IN/OUT 계약)
└── __init__.py  ← 공개 인터페이스만 export
```

---

### C0. 공통 모듈 (Common)

> 위치: `src/common/`
> 규칙: Feature 폴더 안에 절대 두지 않는다. Manager가 여기서 인스턴스를 꺼내 Atom에 파라미터로 주입(DI)한다.

| ID | 모듈명 | 파일 | 역할 | IN | OUT |
|---|---|---|---|---|---|
| C0.1 | ConfigProvider | `config.py` | 환경변수 & 설정 관리 (.env, strategy_params.json) | - | `AppConfig` |
| C0.2 | DatabaseGateway | `database.py` | PostgreSQL 접속 & 세션 (SQLAlchemy async) | `AppConfig` | `AsyncSession` |
| C0.3 | CacheGateway | `cache.py` | Redis CRUD & pub/sub | `AppConfig` | Redis 클라이언트 |
| C0.4 | HttpClient | `http_client.py` | 외부 HTTP 통신 (aiohttp, httpx) | URL, headers, body | `HttpResponse` |
| C0.5 | AiGateway | `ai_gateway.py` | Claude API + MLX 로컬 추론 공통 | `AiRequest` | `AiResponse` |
| C0.6 | BrokerGateway | `broker_gateway.py` | KIS OpenAPI 인증 & 통신 공통 | `KisRequest` | `KisResponse` |
| C0.7 | TelegramGateway | `telegram.py` | Telegram Bot 발송 | `str` (메시지) | `bool` (성공 여부) |
| C0.8 | Logger | `logger.py` | 구조화 로깅 (`get_logger`) | `module_name: str` | `Logger` |
| C0.9 | ErrorHandler | `error.py` | 예외 정의 & 글로벌 핸들러 | `Exception` | `ErrorResponse` |
| C0.10 | EventBus | `event_bus.py` | Feature 간 이벤트 통신 | `Event` | - |
| C0.11 | MarketClock | `market_clock.py` | 시장 시간, 세션 판별, 운영 윈도우 | - | `MarketSession` |
| C0.12 | TickerRegistry | `ticker_registry.py` | 티커 매핑, ETF 유니버스, 인버스 페어 | - | `TickerInfo` |

**DI 흐름 예시**:
```python
# Manager에서 Common 인프라를 꺼내 Atom에 주입한다
class ArticlePersistManager:
    def __init__(self, db: DatabaseGateway, cache: CacheGateway):
        self._db = db
        self._cache = cache

    async def persist(self, article: Article) -> None:
        # Atom에 인프라를 파라미터로 전달한다
        await persist_article_atom(article, session=self._db.session())
        await update_cache_atom(article.id, cache=self._cache)
```

---

### F1. 데이터 수집 (Data Collection)

> 위치: `src/f1_collection/`
> 사용 Common: C0.2, C0.3, C0.4, C0.8, C0.9
> 역할: 30개 뉴스 소스에서 기사를 수집하고 검증하여 DB에 저장한다.

| ID | 모듈명 | 계층 | 역할 | IN | OUT |
|---|---|---|---|---|---|
| F1.1 | CrawlScheduler | Manager | 크롤링 주기 관리 (야간/주간 모드, 빠른 모드 전환) | `MarketSession` | 스케줄 이벤트 |
| F1.2 | CrawlerBase | Atom | 크롤러 공통 인터페이스 & 타임아웃 처리 | `CrawlConfig` | `RawArticle[]` |
| F1.3 | Crawlers (30개) | Atom | 개별 소스 크롤러 (RSS/API/스크래핑) | `SourceConfig` | `RawArticle[]` |
| F1.4 | CrawlVerifier | Atom | 수집 결과 검증 (필드 완전성, 언어, 품질) | `RawArticle` | `VerifiedArticle \| None` |
| F1.5 | ArticleDeduplicator | Atom | 중복 제거 (content_hash 기반) | `VerifiedArticle`, Redis | `bool` (신규 여부) |
| F1.6 | ArticlePersister | Atom | DB 저장 (upsert) | `VerifiedArticle`, session | `ArticleId` |
| F1.7 | CrawlEngine | Manager | 전체 파이프라인 오케스트레이터 | `CrawlSchedule` | `CrawlResult` |

**이벤트 발행**: `ArticleCollected` → EventBus → F2 AI 분석 트리거

---

### F2. AI 분석 (AI Analysis)

> 위치: `src/f2_analysis/`
> 사용 Common: C0.2, C0.3, C0.5, C0.8, C0.12
> 역할: Claude API와 MLX 로컬 모델을 활용하여 뉴스를 분석하고 매매 판단을 생성한다.

| ID | 모듈명 | 계층 | 역할 | IN | OUT |
|---|---|---|---|---|---|
| F2.1 | NewsClassifier | Manager | 뉴스 분류 (영향도, 방향, 카테고리) | `Article[]` | `ClassifiedNews[]` |
| F2.2 | RegimeDetector | Atom | 시장 레짐 판별 (VIX 기반) | `float` (VIX) | `MarketRegime` |
| F2.3 | ComprehensiveTeam | Manager | 종합 분석 (5개 에이전트 페르소나 순차 실행) | `AnalysisContext` | `ComprehensiveReport` |
| F2.4 | DecisionMaker | Manager | 매매 판단 생성 (진입/청산/홀드) | `ComprehensiveReport`, `PortfolioState` | `TradingDecision` |
| F2.5 | OvernightJudge | Manager | 오버나이트 판단 (장 마감 후 포지션 유지 여부) | `Position[]`, `MarketContext` | `OvernightDecision[]` |
| F2.6 | ContinuousAnalysis | Manager | 30분 주기 연속 분석 루프 | `MarketSession` | `AnalysisSummary` |
| F2.7 | PromptRegistry | Atom | 프롬프트 템플릿 관리 (MASTER_ANALYST 등 5개) | `PromptKey` | `str` (프롬프트) |
| F2.8 | FallbackRouter | Manager | Claude → MLX 폴백 라우팅 | `AiRequest` | `AiResponse` |
| F2.9 | KeyNewsFilter | Atom | 핵심 뉴스 필터링 (영향도 임계값 이상) | `ClassifiedNews[]` | `KeyNews[]` |
| F2.10 | EODFeedbackReport | Manager | 일일 피드백 보고서 생성 | `DailyTrades[]`, `PnlSummary` | `FeedbackReport` |
| F2.11 | NewsThemeTracker | Manager | 뉴스 테마 추적 (반복 테마 감지) | `Article[]` | `ThemeSummary[]` |

**주의**: `FallbackRouter.call()`은 `dict` (`{"content": str, "model": str, "source": str, "confidence": float}`)를 반환한다. 파서에 전달하기 전 반드시 `.get("content", "")`로 추출한다.

---

### F3. 지표 (Indicators)

> 위치: `src/f3_indicators/`
> 사용 Common: C0.3, C0.6, C0.8
> 역할: KIS API와 외부 데이터 소스에서 가격 데이터를 수집하고 기술적/고급 지표를 계산한다.

| ID | 모듈명 | 계층 | 역할 | IN | OUT |
|---|---|---|---|---|---|
| F3.1 | PriceDataFetcher | Manager | KIS API 가격 데이터 조회 (일봉 max 100) | `ticker: str`, KISClient | `OHLCV[]` |
| F3.2 | TechnicalCalculator | Atom | 기술적 지표 계산 (RSI, MACD, BB, ATR) | `OHLCV[]` | `TechnicalIndicators` |
| F3.3 | HistoryAnalyzer | Atom | 과거 데이터 패턴 분석 | `OHLCV[]` | `HistoryPattern` |
| F3.4 | IndicatorAggregator | Manager | 지표 종합 점수 (가중합) | `TechnicalIndicators` | `AggregatedScore` |
| F3.5 | IntradayFetcher | Manager | 장중 5분봉 데이터 조회 (Finnhub/AV) | `ticker: str` | `Candle5m[]` |
| F3.6 | IntradayCalculator | Atom | VWAP, 장중 RSI, 볼린저 밴드 계산 | `Candle5m[]` | `IntradayIndicators` |
| F3.7 | CrossAssetMomentum | Manager | 리더 맵(17쌍), 다이버전스, 모멘텀 스코어 | `ticker: str`, Redis | `MomentumScore` |
| F3.8 | VolumeProfile | Manager | POC, Value Area (70% 거래량), 지지/저항 | `OHLCV[]` | `VolumeProfileResult` |
| F3.9 | WhaleTracker | Manager | 블록 거래($200k+), 아이스버그(5+ 체결/1s) 감지 | `OrderFlow` | `WhaleSignal` |
| F3.10 | MACDDivergence | Atom | MACD 다이버전스 분석 | `OHLCV[]` | `DivergenceSignal` |
| F3.11 | ContangoDetector | Manager | VIX 기간구조 프록시, 레버리지 드래그 측정 | Redis | `ContangoState` |
| F3.12 | NAVPremiumTracker | Manager | 레버리지 ETF NAV 프리미엄/디스카운트 (10개 ETF) | `ticker: str` | `NAVPremiumState` |

**리더 맵 (F3.7)**: SOXL→[NVDA, AMD, TSM], QLD→[AAPL, MSFT, NVDA, GOOG] 등 17쌍.
다이버전스 조건: 리더 OBI > 0.5 + ETF OBI < 0.1 → 강세 신호.

---

### F4. 전략 (Strategy)

> 위치: `src/f4_strategy/`
> 사용 Common: C0.3, C0.8, C0.11, C0.12
> 역할: 진입/청산 전략, 특수 매매 모드, 리스크 조정 파라미터를 관리한다.

| ID | 모듈명 | 계층 | 역할 | IN | OUT |
|---|---|---|---|---|---|
| F4.1 | EntryStrategy | Manager | 진입 필터 체인 (7개 게이트: OBI, CrossAsset, Whale, MicroRegime, ML, Friction, RAG) | `EntryContext` | `EntryDecision` |
| F4.2 | ExitStrategy | Manager | 청산 전략 (익절/손절/트레일링/뉴스페이딩/StatArb 우선순위 체인) | `Position`, `MarketContext` | `ExitDecision` |
| F4.3 | BeastMode | Manager | 고확신 공격적 매매 모드 (A+ 셋업: confidence>0.9, OBI>+0.4, 볼륨 2x+) | `SetupScore` | `BeastDecision` |
| F4.4 | Pyramiding | Manager | 피라미딩 (+1%→50%, +2%→30%, +3%→20% 3단계 추가, 8개 안전 가드) | `Position`, `MarketState` | `PyramidOrder \| None` |
| F4.5 | StatArb | Manager | 통계적 차익거래 (Z-Score 페어: QQQ/QLD 등 5쌍) | `PairPrices` | `StatArbSignal` |
| F4.6 | MicroRegime | Manager | 미시 레짐 분류 (ER+ADX, 가중: 0.35\*ER+0.30\*DS+0.20\*AC+0.15\*vol) | `Candle5m[]` | `MicroRegime` |
| F4.7 | NewsFading | Manager | 뉴스 스파이크(>1%/60s) 페이딩 전략 | `PriceSpike` | `FadeSignal` |
| F4.8 | WickCatcher | Manager | 하방 윅 캐처 (VPIN>0.7+CVD<-0.6 활성화, -2/-3/-4% 진입) | `IntradayState` | `WickOrder \| None` |
| F4.9 | SectorRotation | Manager | 섹터 로테이션 분석 (7개 섹터, 가중 스코어, 상위3 선호/하위2 회피) | `SectorData` | `RotationSignal` |
| F4.10 | StrategyParams | Atom | 전략 파라미터 관리 (strategy_params.json R/W) | `ParamKey` | `ParamValue` |
| F4.11 | TickerParams | Atom | 티커별 파라미터 관리 (ATR 배수, 스탑 거리 등) | `ticker: str` | `TickerConfig` |
| F4.12 | Backtester | Manager | 백테스팅 프레임워크 (StrategyBacktester + grid_search) | `BacktestConfig` | `BacktestResult` |
| F4.13 | LeverageDecay | Atom | 레버리지 디케이 계산 (변동성 드래그 정량화) | `OHLCV[]` | `DecayScore` |
| F4.14 | ProfitTarget | Manager | 월간 수익 목표 관리 ($300/월 최소, 생존 매매) | `MonthlyPnl` | `TargetStatus` |

**Beast Mode 에고 시스템 (F4.3)**:
- Cold-Blooded Sniper: A+ 셋업만 진입 (AND 로직)
- Merciless Butcher: 120초 타임스탑 (포지션 자동 청산)
- Greedy Surfer: -0.5% 트레일링 (수익 최대화)
- 컨빅션 배수: 2.5x~3.0x 포지션 증폭 (선형 보간)

---

### F5. 실행 (Execution)

> 위치: `src/f5_execution/`
> 사용 Common: C0.6, C0.8, C0.12
> 역할: KIS OpenAPI를 통해 실제 주문을 실행하고 포지션을 관리한다.

| ID | 모듈명 | 계층 | 역할 | IN | OUT |
|---|---|---|---|---|---|
| F5.1 | KISAuth | Manager | KIS 인증 (실전/모의 듀얼, 토큰 1일 1회 발급 & 캐시) | `KisCredentials` | `KisToken` |
| F5.2 | KISClient | Manager | KIS API 통신 (주문, 잔고, 시세, 환율) | `KisRequest`, `KisToken` | `KisResponse` |
| F5.3 | OrderManager | Manager | 주문 관리 (매수/매도/정정/취소, 모의→지정가 자동 변환) | `OrderRequest` | `OrderResult` |
| F5.4 | PositionMonitor | Manager | 포지션 모니터링 & 청산 판단 (블록 티커 관리) | `MarketSession` | `PositionState[]` |
| F5.5 | UniverseManager | Manager | ETF 유니버스 CRUD (활성/비활성 관리) | `UniverseRequest` | `Universe` |
| F5.6 | AccountModeManager | Atom | 모의/실전 계좌 전환 | `AccountMode` | `bool` |

**KIS 주요 규칙**:
- 실전 인증(`real_auth`)과 모의 인증(`virtual_auth`)을 분리하여 관리한다. 시세 API는 실전 인증만 사용한다.
- 토큰 파일: `data/kis_token.json`(모의), `data/kis_real_token.json`(실전). 하루 1회만 발급한다.
- 모의 거래 시 시장가 주문 불가 → `OrderManager`가 자동으로 ±0.5% 지정가로 변환한다.
- KIS 90000000 에러 (PLTZ/NVDL/TSLS 등): `_sell_blocked_tickers` set으로 반복 실패를 차단한다. EOD에 초기화한다.
- 거래소 코드: NAS(나스닥), AMS(아멕스/NYSE Arca ETF), NYS(NYSE).

---

### F6. 리스크 & 안전 (Risk & Safety)

> 위치: `src/f6_risk/`
> 사용 Common: C0.2, C0.3, C0.8
> 역할: 다중 계층 안전 장치를 통해 자본을 보호하고 시스템 안정성을 유지한다.

안전 체인 순서: **HardSafety → SafetyChecker → EmergencyProtocol → CapitalGuard**

| ID | 모듈명 | 계층 | 역할 | IN | OUT |
|---|---|---|---|---|---|
| F6.1 | HardSafety | Manager | 하드 안전 장치 (티커당 최대 15%, crash/mild_bear에서 Bull ETF 매수 이중 차단) | `OrderIntent` | `bool` (허용 여부) |
| F6.2 | SafetyChecker | Manager | 안전 체크 파이프라인 (다중 조건 순차 검증) | `SystemState` | `SafetyResult` |
| F6.3 | EmergencyProtocol | Manager | 긴급 프로토콜 (전체 포지션 즉시 청산) | `EmergencyTrigger` | `LiquidationResult` |
| F6.4 | CapitalGuard | Manager | 자본 보호 체크 (최소 자본 유지) | `AccountBalance` | `bool` |
| F6.5 | RiskGatePipeline | Manager | 리스크 게이트 체인 (7개: OBI, CrossAsset, Whale, Tilt, Friction, MacroLiquidity, SectorCor) | `TradeContext` | `GateResult` |
| F6.6 | DailyLossLimiter | Atom | 일일 손실 한도 체크 | `DailyPnl` | `bool` |
| F6.7 | ConcentrationLimiter | Atom | 집중도 제한 (단일 포지션 한도) | `Portfolio` | `bool` |
| F6.8 | LosingStreakDetector | Atom | 연패 감지 (3연패/10분 OR -2%/30분) | `TradeHistory` | `TiltRisk` |
| F6.9 | SimpleVaR | Atom | 간단 VaR 계산 (99% 신뢰도) | `Portfolio` | `float` (VaR) |
| F6.10 | RiskBudget | Manager | 리스크 예산 관리 (Kelly Criterion 25% 분수) | `Portfolio`, `Kelly` | `PositionSize` |
| F6.11 | TrailingStopLoss | Atom | 트레일링 스탑 (ATR 동적, 레짐 기반 배수) | `Position`, `ATR` | `StopPrice` |
| F6.12 | DeadmanSwitch | Manager | 데이터 단절 감지 (WebSocket 스탈 >10초 → Beast 포지션 청산) | `WebSocketState` | `LiquidationTrigger \| None` |
| F6.13 | MacroFlashCrash | Manager | 매크로 급락 감지 (SPY/QQQ -1.0%/3분 → 전체 청산) | `IndexPrices` | `CrashAlert \| None` |
| F6.14 | GapRiskProtector | Manager | 갭 리스크 보호 (Small/Medium/Large/Extreme 4단계) | `GapSize` | `GapAction` |
| F6.15 | TiltDetector | Manager | 틸트 감지 (심리적 과매매, 1시간 잠금) | `TradeHistory` | `TiltState` |
| F6.16 | FrictionCalculator | Atom | 마찰 비용 계산 (스프레드 + 슬리피지 × 2 = 최소 수익) | `TradeParams` | `FrictionCost` |
| F6.17 | HouseMoneyMultiplier | Atom | 하우스 머니 배수 (일일 PnL 기반: 0.5x/1.0x/1.5x/2.0x) | `DailyPnl` | `float` (배수) |
| F6.18 | AccountSafety | Manager | 계좌 안전 체크 (자동 정지 윈도우: 06:30~20:00 KST) | `MarketClock` | `bool` |
| F6.19 | QuotaGuard | Atom | API 쿼타 관리 (KIS 요청 속도 제한) | `RequestCount` | `bool` |

**레짐별 전략 파라미터**:
| 레짐 | VIX 범위 | 익절 | 트레일링 | 최대보유 |
|---|---|---|---|---|
| strong_bull | 0~15 | 0 (무제한, 트레일링만) | 4.0% | 당일 청산 |
| mild_bull | 15~20 | 3.0% | 2.5% | 2일 |
| sideways | 20~25 | 2.0% | 1.5% | 당일 청산 |
| mild_bear | 25~35 | 방어 인버스 모드 | - | 0.5x 배수 |
| crash | 35+ | 5.0% | - | 인버스 1.5x |

**4계층 방어망 (Beast Mode용)**:
1. Network: DeadmanSwitch (데이터 단절)
2. Market: MacroFlashCrash (급락 감지)
3. Time: 위험 구간 잠금 (09:30~10:00 ET, 15:30~16:00 ET)
4. Price: 하드 스탑 -1.0% (일반 -2%보다 타이트)

---

### F7. 모니터링 API (Monitoring)

> 위치: `src/f7_monitoring/`
> 사용 Common: C0.2, C0.3, C0.6, C0.7, C0.8
> 역할: Flutter 대시보드와 외부 클라이언트에 시스템 상태를 실시간으로 제공한다.

| ID | 모듈명 | 계층 | 역할 | 엔드포인트 접두사 |
|---|---|---|---|---|
| F7.1 | ApiServer | Manager | FastAPI 앱 & 라우터 등록, CORS, 미들웨어 | - |
| F7.2 | DashboardEndpoints | Router | 대시보드 요약, 포지션, 거래내역 | `/api/dashboard` |
| F7.3 | AnalysisEndpoints | Router | 종합 분석, 뉴스 분석 결과 | `/api/analysis` |
| F7.4 | TradingControlEndpoints | Router | 매매 시작/중지 (Bearer 인증 필수) | `/api/trading` |
| F7.5 | MacroEndpoints | Router | 거시 경제 지표 (NetLiquidity 등) | `/api/macro` |
| F7.6 | NewsEndpoints | Router | 뉴스 조회, 수집 & 텔레그램 전송 | `/api/news` |
| F7.7 | UniverseEndpoints | Router | ETF 유니버스 관리 CRUD | `/api/universe` |
| F7.8 | EmergencyEndpoints | Router | 긴급 상태 & 리스크 대시보드 | `/api/emergency` |
| F7.9 | BenchmarkEndpoints | Router | 벤치마크 비교 (SPY/QQQ 대비) | `/api/benchmark` |
| F7.10 | TradeReasoningEndpoints | Router | 매매 근거 상세 조회 | `/api/reasoning` |
| F7.11 | IndicatorEndpoints | Router | 지표 가중치, RSI 현황 | `/api/indicators` |
| F7.12 | ManualTradeEndpoints | Router | 수동 매매 분석 & 실행 | `/api/manual` |
| F7.13 | PrinciplesEndpoints | Router | 매매 원칙 CRUD | `/api/principles` |
| F7.14 | AgentEndpoints | Router | AI 에이전트 관리 | `/api/agents` |
| F7.15 | SystemEndpoints | Router | 시스템 상태, 헬스체크 | `/api/system` |
| F7.16 | PerformanceEndpoints | Router | 성과 분석 (PnL, 승률, 드로우다운) | `/api/performance` |
| F7.17 | OrderFlowEndpoints | Router | 주문 흐름 분석 | `/api/orderflow` |
| F7.18 | WebSocketManager | Manager | 실시간 WebSocket 스트림 (3초 갱신) | `ws://` |
| F7.19 | TelegramNotifier | Manager | 텔레그램 알림 발송 (거래 알림, 일일 보고서) | - |
| F7.20 | IndicatorCrawler | Manager | 거시 지표 자동 크롤링 (FRED: TGA, WALCL, RRPONTSYD) | - |

**인증**: 매매 제어 API는 반드시 `Authorization: Bearer <API_SECRET_KEY>` 헤더를 사용한다. `X-API-Key`는 사용하지 않는다.

---

### F8. 최적화 & ML (Optimization)

> 위치: `src/f8_optimization/`
> 사용 Common: C0.2, C0.3, C0.5, C0.8
> 역할: LightGBM 모델 학습, 하이퍼파라미터 최적화, EOD 매매 파라미터 자동 조정을 수행한다.

| ID | 모듈명 | 계층 | 역할 | IN | OUT |
|---|---|---|---|---|---|
| F8.1 | DataPreparer | Atom | 학습 데이터 준비 (DB 조회, 정제) | `DateRange` | `DataFrame` |
| F8.2 | FeatureEngineer | Atom | 피처 엔지니어링 (21개 피처 생성) | `DataFrame` | `FeatureMatrix` |
| F8.3 | TargetBuilder | Atom | 타겟 라벨 생성 (P(+1%/5min)) | `DataFrame` | `LabelVector` |
| F8.4 | LGBMTrainer | Manager | LightGBM 학습 (TimeSeriesSplit) | `FeatureMatrix`, `LabelVector` | `LGBMModel` |
| F8.5 | OptunaOptimizer | Manager | 하이퍼파라미터 최적화 (TPE, 200 트라이얼) | `LGBMModel` | `BestParams` |
| F8.6 | WalkForward | Manager | 워크 포워드 검증 (4주 학습/1주 테스트) | `DataFrame`, `BestParams` | `WalkForwardResult` |
| F8.7 | AutoTrainer | Manager | 주간 자동 학습 파이프라인 | `cron` | `TrainingReport` |
| F8.8 | TimeTravelTrainer | Manager | 시간여행 학습 (분봉 리플레이 → ChromaDB RAG) | `HistoricalData` | `RAGEmbeddings` |
| F8.9 | ExecutionOptimizer | Manager | EOD 매매 최적화 (파라미터 ±5%, 최대 30% 이탈) | `DailyTrades[]` | `AdjustedParams` |
| F8.10 | KnowledgeManager | Manager | RAG 지식 관리 (ChromaDB + bge-m3, 임베딩 저장/조회) | `Document` | `EmbeddingVector` |

---

### F9. 오케스트레이션 (Orchestration)

> 위치: `src/f9_orchestration/`
> 사용 Common: ALL
> 역할: 전체 시스템 생명주기를 관리한다. 현재 `main.py` 1,000줄+ 코드를 이 계층으로 분리한다.

| ID | 모듈명 | 계층 | 역할 | IN | OUT |
|---|---|---|---|---|---|
| F9.1 | SystemInitializer | Manager | 전체 초기화 (현재 main.py 상단 494줄 → 분리) | `AppConfig` | `SystemComponents` |
| F9.2 | DependencyInjector | Manager | 의존성 조립 & 주입 (모든 Feature의 Manager에 Common 인프라 주입) | `SystemComponents` | `InjectedSystem` |
| F9.3 | PreparationPhase | Manager | 사전 준비 단계 (20:00 KST, 토큰 갱신, 레짐 분석, 뉴스 분류) | `MarketClock` | `PreparationResult` |
| F9.4 | TradingLoop | Manager | 매매 루프 (세션별 동적 주기: PowerOpen 90s/Mid 180s/PowerHour 120s/Monitor 30~60s) | `MarketSession` | - |
| F9.5 | ContinuousAnalysis | Manager | 연속 분석 루프 (23:00~06:30 KST, 30분 주기 Opus 분석) | `MarketSession` | - |
| F9.6 | NewsPipeline | Manager | 뉴스 수집&분류&전송 파이프라인 | `CrawlSchedule` | `PipelineResult` |
| F9.7 | EODSequence | Manager | EOD 정리 시퀀스 (포지션 청산, 피드백, 파라미터 최적화, 리셋) | `EODTrigger` | `EODReport` |
| F9.8 | GracefulShutdown | Manager | 안전 종료 (SIGTERM/SIGINT 수신 → 포지션 정리 → 연결 해제) | `ShutdownSignal` | `ShutdownResult` |

**매매 루프 세션 주기**:
| 세션 | 시간 (ET) | 주기 |
|---|---|---|
| Power Open | 09:30~10:00 | 90초 |
| Mid Day | 10:00~15:30 | 180초 |
| Power Hour | 15:30~16:00 | 120초 |
| After Monitor | 16:00~ | 30~60초 (sync_positions only) |

**비정규 세션 (프리마켓/애프터마켓)**: `monitor_all()` 호출 금지. `sync_positions()`만 실행한다. 모의 거래 서버는 주문 실행이 불가하다.

---

### F10. 대시보드 (Flutter)

> 위치: `dashboard/`
> 역할: macOS Desktop 앱으로 시스템 상태를 실시간 모니터링하고 제어한다.

| ID | 모듈명 | 역할 | 규칙 |
|---|---|---|---|
| F10.1 | ApiClient | 도메인별 HTTP 클라이언트 분리 | 도메인당 1개 파일 (DashboardApiClient, TradingApiClient 등) |
| F10.2 | WebSocketClient | 실시간 WebSocket 연결 관리 | 3초 갱신, 재연결 로직 포함 |
| F10.3 | Providers | 도메인별 상태 관리 | Provider당 단일 책임. Flutter 의존성 없이 순수 Dart |
| F10.4 | Screens | 화면 위젯 조합 | 300줄 이하 유지. 위젯 추출로 분리 |
| F10.5 | Models | 순수 Dart 데이터 모델 | Flutter 의존성 제거. `fromJson`/`toJson` 포함 |
| F10.6 | Theme & Design Tokens | 테마 & 디자인 토큰 | 색상/타이포 하드코딩 금지. 토큰 참조만 허용 |

---

## 4. 의존성 흐름도

### 4.1 전체 모듈 의존 관계

```
┌─────────────────────────────────────────────────────────┐
│              C0 (Common) — 모든 Feature가 의존           │
│  Config · DB · Redis · HTTP · AI · Broker · Telegram    │
│  Logger · Error · EventBus · MarketClock · TickerReg    │
└───────────────────────────┬─────────────────────────────┘
                             │ 인프라 주입 (DI)
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
     F1 (수집)         F3 (지표)        F8 (ML)
         │                  │               │
         ▼                  ▼               │
     F2 (분석) ──────→ F4 (전략)            │
                             │               │
                             ▼               │
                       F5 (실행)  ←──────────┘
                             │
                             ▼
                       F6 (리스크)
                             │
            ┌────────────────┤
            ▼                ▼
     F7 (API)    F9 (오케스트레이션)
         │
         ▼
   F10 (대시보드)
```

### 4.2 EventBus 통신 목록

Feature 간 직접 함수 호출 대신 EventBus를 통해 통신한다.

| 발행자 | 이벤트 | 구독자 | 트리거 조건 |
|---|---|---|---|
| F1.7 CrawlEngine | `ArticleCollected` | F2.1 NewsClassifier | 신규 기사 수집 완료 |
| F2.4 DecisionMaker | `TradingDecision` | F5.3 OrderManager | 매매 판단 생성 |
| F5.4 PositionMonitor | `PositionChanged` | F7.18 WebSocketManager | 포지션 상태 변경 |
| F6.3 EmergencyProtocol | `EmergencyLiquidation` | F5.3 OrderManager | 긴급 청산 트리거 |
| F6.13 MacroFlashCrash | `CrashDetected` | F6.3 EmergencyProtocol | 급락 감지 |
| F9.7 EODSequence | `EODStarted` | F8.9 ExecutionOptimizer | EOD 파라미터 최적화 |
| F4.3 BeastMode | `BeastEntry` | F6.12 DeadmanSwitch | Beast 포지션 진입 |

---

## 5. DI (의존성 주입) 흐름

```
F9.1 SystemInitializer
    │
    ├─ C0.1 ConfigProvider.load()         → AppConfig
    │
    ├─ C0.2 DatabaseGateway(config)       → db
    ├─ C0.3 CacheGateway(config)          → cache
    ├─ C0.4 HttpClient(config)            → http
    ├─ C0.5 AiGateway(config, http)       → ai
    ├─ C0.6 BrokerGateway(config, http)   → broker
    ├─ C0.7 TelegramGateway(config, http) → telegram
    └─ C0.10 EventBus()                   → bus
            │
            ▼
    F9.2 DependencyInjector
            │
            ├─ F1.7 CrawlEngine(http, db, cache, bus)
            ├─ F2.3 ComprehensiveTeam(ai, cache, bus)
            ├─ F3.1 PriceDataFetcher(broker)
            ├─ F4.1 EntryStrategy(cache, bus)
            ├─ F5.2 KISClient(broker)
            ├─ F6.1 HardSafety(db, cache)
            └─ F7.1 ApiServer(db, cache, bus, telegram)
                        │
                        ▼
            Manager들은 주입받은 인프라를 Atom에 파라미터로 전달한다
```

---

## 6. 목표 폴더 구조

```
src/
├── common/                    ← C0 공통 모듈 (인프라)
│   ├── config.py              ← C0.1 ConfigProvider
│   ├── database.py            ← C0.2 DatabaseGateway
│   ├── cache.py               ← C0.3 CacheGateway
│   ├── http_client.py         ← C0.4 HttpClient
│   ├── ai_gateway.py          ← C0.5 AiGateway
│   ├── broker_gateway.py      ← C0.6 BrokerGateway
│   ├── telegram.py            ← C0.7 TelegramGateway
│   ├── logger.py              ← C0.8 Logger
│   ├── error.py               ← C0.9 ErrorHandler
│   ├── event_bus.py           ← C0.10 EventBus
│   ├── market_clock.py        ← C0.11 MarketClock
│   └── ticker_registry.py     ← C0.12 TickerRegistry
│
├── f1_collection/             ← F1 데이터 수집
│   ├── manager/
│   │   ├── crawl_scheduler.py
│   │   └── crawl_engine.py
│   ├── atom/
│   │   ├── crawler_base.py
│   │   ├── crawl_verifier.py
│   │   ├── article_deduplicator.py
│   │   └── article_persister.py
│   ├── crawler/               ← 30개 개별 크롤러
│   └── schema/
│       └── article.py
│
├── f2_analysis/               ← F2 AI 분석
│   ├── manager/
│   │   ├── news_classifier.py
│   │   ├── comprehensive_team.py
│   │   ├── decision_maker.py
│   │   ├── overnight_judge.py
│   │   ├── continuous_analysis.py
│   │   ├── fallback_router.py
│   │   ├── eod_feedback_report.py
│   │   └── news_theme_tracker.py
│   ├── atom/
│   │   ├── regime_detector.py
│   │   ├── prompt_registry.py
│   │   └── key_news_filter.py
│   └── schema/
│       └── analysis.py
│
├── f3_indicators/             ← F3 지표
│   ├── manager/
│   │   ├── price_data_fetcher.py
│   │   ├── indicator_aggregator.py
│   │   ├── intraday_fetcher.py
│   │   ├── cross_asset_momentum.py
│   │   ├── volume_profile.py
│   │   ├── whale_tracker.py
│   │   ├── contango_detector.py
│   │   └── nav_premium_tracker.py
│   ├── atom/
│   │   ├── technical_calculator.py
│   │   ├── history_analyzer.py
│   │   ├── intraday_calculator.py
│   │   └── macd_divergence.py
│   └── schema/
│       └── indicator.py
│
├── f4_strategy/               ← F4 전략
│   ├── manager/
│   │   ├── entry_strategy.py
│   │   ├── exit_strategy.py
│   │   ├── beast_mode.py
│   │   ├── pyramiding.py
│   │   ├── stat_arb.py
│   │   ├── micro_regime.py
│   │   ├── news_fading.py
│   │   ├── wick_catcher.py
│   │   ├── sector_rotation.py
│   │   ├── backtester.py
│   │   └── profit_target.py
│   ├── atom/
│   │   ├── strategy_params.py
│   │   ├── ticker_params.py
│   │   └── leverage_decay.py
│   └── schema/
│       └── strategy.py
│
├── f5_execution/              ← F5 실행
│   ├── manager/
│   │   ├── kis_auth.py
│   │   ├── kis_client.py
│   │   ├── order_manager.py
│   │   ├── position_monitor.py
│   │   └── universe_manager.py
│   ├── atom/
│   │   └── account_mode_manager.py
│   └── schema/
│       └── order.py
│
├── f6_risk/                   ← F6 리스크 & 안전
│   ├── manager/
│   │   ├── hard_safety.py
│   │   ├── safety_checker.py
│   │   ├── emergency_protocol.py
│   │   ├── capital_guard.py
│   │   ├── risk_gate_pipeline.py
│   │   ├── risk_budget.py
│   │   ├── deadman_switch.py
│   │   ├── macro_flash_crash.py
│   │   ├── gap_risk_protector.py
│   │   ├── tilt_detector.py
│   │   └── account_safety.py
│   ├── atom/
│   │   ├── daily_loss_limiter.py
│   │   ├── concentration_limiter.py
│   │   ├── losing_streak_detector.py
│   │   ├── simple_var.py
│   │   ├── trailing_stop_loss.py
│   │   ├── friction_calculator.py
│   │   ├── house_money_multiplier.py
│   │   └── quota_guard.py
│   └── schema/
│       └── risk.py
│
├── f7_monitoring/             ← F7 모니터링 API
│   ├── router/
│   │   ├── dashboard.py
│   │   ├── analysis.py
│   │   ├── trading_control.py
│   │   ├── macro.py
│   │   ├── news.py
│   │   ├── universe.py
│   │   ├── emergency.py
│   │   ├── benchmark.py
│   │   ├── reasoning.py
│   │   ├── indicators.py
│   │   ├── manual_trade.py
│   │   ├── principles.py
│   │   ├── agents.py
│   │   ├── system.py
│   │   ├── performance.py
│   │   └── order_flow.py
│   ├── websocket/
│   │   └── manager.py
│   ├── manager/
│   │   ├── api_server.py
│   │   ├── telegram_notifier.py
│   │   └── indicator_crawler.py
│   └── schema/
│       └── response.py
│
├── f8_optimization/           ← F8 최적화 & ML
│   ├── manager/
│   │   ├── lgbm_trainer.py
│   │   ├── optuna_optimizer.py
│   │   ├── walk_forward.py
│   │   ├── auto_trainer.py
│   │   ├── time_travel_trainer.py
│   │   ├── execution_optimizer.py
│   │   └── knowledge_manager.py
│   ├── atom/
│   │   ├── data_preparer.py
│   │   ├── feature_engineer.py
│   │   └── target_builder.py
│   └── schema/
│       └── ml.py
│
├── f9_orchestration/          ← F9 오케스트레이션
│   ├── system_initializer.py
│   ├── dependency_injector.py
│   ├── preparation_phase.py
│   ├── trading_loop.py
│   ├── continuous_analysis.py
│   ├── news_pipeline.py
│   ├── eod_sequence.py
│   └── graceful_shutdown.py
│
└── main.py                    ← 엔트리포인트 (50줄 이하)
```

---

## 7. 파일 크기 & 코딩 규칙

### 7.1 크기 한도 (비협상)

| 파일 유형 | 최대 줄 수 |
|---|---|
| Atom 함수 | 30줄 |
| Manager 클래스 | 50줄 |
| 일반 파일 | 200줄 |
| Flutter 컴포넌트 | 150줄 |
| `main.py` (엔트리포인트) | 50줄 |

### 7.2 Python 코딩 규칙

```python
# 올바른 Atom 예시 — 하나의 함수 = 하나의 동작, 외부 의존성 파라미터로 주입
async def persist_article_atom(
    article: VerifiedArticle,
    session: AsyncSession,  # DI: 외부에서 주입받는다
) -> ArticleId:
    """기사를 DB에 저장한다. 중복 시 upsert 처리한다."""
    ...
```

- **네이밍**: snake_case(파일/함수), PascalCase(클래스), UPPER_SNAKE_CASE(상수)
- **타입 힌트**: 모든 함수의 매개변수와 반환 타입에 필수. `Python 3.10+` 문법 (`str | None`, `list[str]`). `Any` 최소화.
- **주석**: 모든 docstring과 주석은 한국어로 작성한다. "왜 이렇게 하는지" 중심으로 서술한다.
- **비동기**: `async/await` 일관 사용. `async with get_session() as session`으로 DB 접근.
- **로깅**: `get_logger(__name__)`. 모든 public 메서드에 `try/except + logging`.
- **datetime 직렬화**: `json.dumps(data, default=str)` — datetime 객체 직접 직렬화 금지.

### 7.3 금지 패턴

```python
# 금지: Atom에서 인프라 직접 import
from src.common.database import get_session  # Atom 내부에서 금지

# 금지: DataFrame 불리언 평가
if df or other_df:  # 금지 — ValueError 발생
    ...
# 올바른 방법:
df if df is not None else other_df

# 금지: 모호한 함수명
def process_data(): ...   # 금지
def handle_all(): ...     # 금지

# 금지: 순수 무채색 (UI 색상)
color = "#000000"  # 금지 — Tinted Grey 사용
color = "#333333"  # 금지

# 금지: Feature 간 직접 호출
from src.f2_analysis import analyzer  # f1에서 f2 직접 import 금지
```

---

## 8. IN/OUT 계약 표준

모든 블록의 IN/OUT은 Pydantic 스키마로 정의한다. 딕셔너리 반환 금지.

```python
# schema/article.py
from pydantic import BaseModel
from datetime import datetime

class RawArticle(BaseModel):
    """크롤러가 수집한 원시 기사 데이터이다."""
    source: str
    url: str
    title: str
    content: str
    published_at: datetime | None = None

class VerifiedArticle(BaseModel):
    """검증 완료된 기사이다. CrawlVerifier가 생성한다."""
    source: str
    url: str
    title: str
    content: str
    content_hash: str        # 중복 제거용
    published_at: datetime
    language: str            # 언어 코드 (ko/en)
    quality_score: float     # 0.0~1.0

class ArticleId(BaseModel):
    """DB 저장 결과이다."""
    id: str
    is_new: bool             # 신규 여부 (True) vs 업데이트 (False)
```

---

## 9. 리팩토링 우선순위

현재 시스템에서 가장 긴급하게 분리가 필요한 모듈 순서이다.

| 우선순위 | 대상 | 현재 위치 | 목표 위치 | 이유 |
|---|---|---|---|---|
| P0 | Common 분리 | 각 모듈 내부 | `src/common/` | DI 기반 구축의 선행 조건 |
| P0 | main.py 분리 | `src/main.py` (1,000줄+) | `src/f9_orchestration/` | 단일 책임 원칙 위반 |
| P1 | F5 실행 | `src/executor/` | `src/f5_execution/` | KIS 인증/통신 혼재 |
| P1 | F6 리스크 | `src/safety/`, `src/risk/` | `src/f6_risk/` | 19개 모듈 난립 |
| P1 | F2 분석 | `src/analysis/` | `src/f2_analysis/` | 프롬프트/분류기 혼재 |
| P2 | F7 모니터링 | `src/monitoring/` | `src/f7_monitoring/` | 20개 라우터 단일 파일 |
| P2 | F4 전략 | `src/strategy/`, 분산 | `src/f4_strategy/` | 여러 폴더에 분산 |
| P3 | F3 지표 | `src/indicators/` | `src/f3_indicators/` | 구조 재정리 |
| P3 | F1 수집 | `src/crawler/` | `src/f1_collection/` | CrawlVerifier 파싱 버그 이력 |
| P4 | F8 ML | `src/optimization/` | `src/f8_optimization/` | 상대적으로 독립적 |

---

## 10. 설계 검증 체크리스트

각 블록 구현 완료 후 아래 항목을 검증한다.

- [ ] Atom이 30줄 이하인가?
- [ ] Manager가 50줄 이하인가?
- [ ] 파일이 200줄 이하인가?
- [ ] Atom 내부에서 DB/Redis/HTTP를 직접 import하지 않는가?
- [ ] Feature 간 직접 함수 호출 없이 EventBus로만 통신하는가?
- [ ] 모든 IN/OUT이 Pydantic 스키마로 정의되어 있는가?
- [ ] 모든 함수에 타입 힌트가 있는가?
- [ ] 모든 docstring이 한국어로 작성되어 있는가?
- [ ] `main.py`가 50줄 이하인가?
- [ ] 순환 의존성이 없는가?

---

*이 문서는 Stock Trading AI System V2 리팩토링의 최상위 설계 기준이다. 모든 세부 모듈 설계 문서는 이 문서를 기반으로 작성한다.*
