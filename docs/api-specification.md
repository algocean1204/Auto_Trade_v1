# Stock Trading AI System V2 — API 명세서

> 최종 검증일: 2026-03-01 | REST 136개 + WebSocket 6개 = 총 142개 엔드포인트
> FastAPI 서버 포트: 9501 (기본값) | 인증: Bearer Token (`Authorization` 헤더)

---

## 목차

1. [시스템 전체 흐름](#1-시스템-전체-흐름)
2. [DI Feature 레지스트리 (48개)](#2-di-feature-레지스트리-48개)
3. [API 엔드포인트 — 대시보드/모니터링](#3-대시보드--모니터링)
4. [API 엔드포인트 — 매매 제어](#4-매매-제어)
5. [API 엔드포인트 — 분석/뉴스](#5-분석--뉴스)
6. [API 엔드포인트 — 거시경제](#6-거시경제)
7. [API 엔드포인트 — 유니버스 관리](#7-유니버스-관리)
8. [API 엔드포인트 — 전략/지표](#8-전략--지표)
9. [API 엔드포인트 — 리스크/안전](#9-리스크--안전)
10. [API 엔드포인트 — 성과/보고서](#10-성과--보고서)
11. [API 엔드포인트 — 세금/비용](#11-세금--비용)
12. [API 엔드포인트 — AI 에이전트](#12-ai-에이전트)
13. [API 엔드포인트 — 매매 원칙/피드백](#13-매매-원칙--피드백)
14. [WebSocket 실시간 채널](#14-websocket-실시간-채널)
15. [Flutter 호환 별칭](#15-flutter-호환-별칭)

---

## 1. 시스템 전체 흐름

### 1.1 시작 → 매매 → EOD → 종료

```
[시스템 시작] main.py
  Step 1    initialize_system()     → SystemComponents 10개 초기화
  Step 1.5  inject_dependencies()   → InjectedSystem (Feature 48개)
  Step 1.6  universe_persister      → DB에서 유니버스 로드 (폴백: 하드코딩)
  Step 2    setup_signal_handlers() → SIGTERM/SIGINT 등록
  Step 3    start_server()          → FastAPI 항상 실행 (포트 9501)
  Step 4    shutdown_event.wait()   → 프로세스 신호 대기

[매매 시작] POST /api/trading/start 호출 시
  run_preparation()                 → 인프라 검사 + 크롤링 + 분류 + 레짐 + 분석 + 안전
  run_trading_loop()       (병렬)   → 세션별 90~180초 주기 (진입/청산)
  run_continuous_analysis() (병렬)  → 30분 주기 (뉴스 파이프라인 + AI 분석)

[EOD] 매매 윈도우 종료 후
  run_eod_sequence()                → 14단계 (PnL → 피드백 → 최적화 → 청산 → 보고)

[시스템 종료] SIGTERM/SIGINT
  graceful_shutdown()               → DB/Redis 연결 정리
```

### 1.2 준비 단계 (run_preparation)

| Step | 동작 | DI Feature | 실패 시 |
|------|------|-----------|--------|
| 0 | 인프라 건강 검사 (DB/Redis/Broker) | components | fail-fast 반환 |
| 1 | KIS 토큰 갱신 (실전+모의) | broker | 경고 후 계속 |
| 2 | 뉴스 크롤링 (fast_mode) | crawl_engine, crawl_scheduler | 0건으로 계속 |
| 3 | 뉴스 분류 + Redis 캐시 + 텔레그램 | news_classifier, telegram | 0건으로 계속 |
| 4 | 레짐 감지 (VIX 기반) | regime_detector, vix_fetcher | "unknown" |
| 5 | 종합 분석 (5 AI 에이전트) | comprehensive_team | 경고 후 계속 |
| 6 | 안전 체크 (긴급정지/손실한도) | emergency_protocol, capital_guard | ready=False |

### 1.3 매매 루프 (run_trading_loop) — 정규 세션

| 단계 | 동작 | DI Feature |
|------|------|-----------|
| 포지션 동기화 | 브로커 잔고 조회 | position_monitor |
| VIX + 레짐 | 시장 상태 판단 | vix_fetcher, regime_detector |
| 콘탱고 조회 | 선물 백워데이션/콘탱고 | contango_detector |
| 순유동성 | FRED Net Liquidity 바이어스 | net_liquidity_tracker |
| 틸트 감지 | 연속 손절 시 진입 차단 | tilt_detector |
| **청산 루프** | 보유 포지션별 청산 평가 | exit_strategy, order_manager |
| **피라미딩** | 추가 진입 조건 평가 | pyramiding |
| **진입 루프** | 유니버스 티커별 진입 평가 | 아래 참조 |

**진입 루프 상세 (티커별 순차):**

| 게이트 | Feature | 차단 조건 |
|--------|---------|----------|
| 섹터 로테이션 | sector_rotation | 회피 섹터 소속 |
| 갭 리스크 | gap_risk_protector | EXTREME 등급 |
| Beast Mode | beast_mode | A+ 셋업 시 즉시 주문 (별도 경로) |
| MicroRegime | micro_regime | choppy 제외 |
| NAV 프리미엄 | nav_premium_tracker | premium > 3% |
| 뉴스 페이딩 | news_fading | short 방향 fade 신호 |
| 일반 진입 | entry_strategy | 7개 게이트 종합 |
| 레버리지 디케이 | leverage_decay | 사이즈 0.5~1.0x 조정 |
| 안전 검사 | safety_checker, hard_safety | 비중/VIX/시간 제한 |
| 매수 실행 | order_manager | — |
| WickCatcher | wick_catcher | 추가 매수 조건 충족 시 |

**사이징 공식:** `final_qty = base_qty * liquidity_mult * gap_mult * nav_mult * decay_mult`

### 1.4 뉴스 파이프라인 (run_news_pipeline)

```
[Step 1]   CrawlEngine 크롤링+API          → VerifiedArticle[]
[Step 2]   NewsClassifier 분류 (MLX+Claude) → ClassifiedNews[]
[Step 2.3] ArticleMerger 유사기사 병합       → ClassifiedNews[] (축소)
[Step 2.5] NewsThemeTracker 테마 추적
[Step 2.7] KeyNewsFilter 중요뉴스 분리       → KeyNews[]
[Step 2.8] SituationTracker 타임라인 분리    → SituationReport[]
[Step 3]   NewsTranslator 한국어 번역        → translated fields 추가
[Step 3.5] ArticlePersister DB 저장          → PostgreSQL articles 테이블
[Step 4]   텔레그램 전송 + Redis 캐시        → 자동매매 참고
```

### 1.5 EOD 시퀀스 (run_eod_sequence) — 14단계

| Step | 이름 | DI Feature |
|------|------|-----------|
| 1 | 포지션 동기화 | position_monitor |
| 2 | 일일 PnL 기록 | Redis |
| 2.5 | 차트 데이터 갱신 (5종) | Redis charts:* |
| 3 | 벤치마크 스냅샷 | (stub) |
| 4 | AI 피드백 보고서 | eod_feedback |
| 5 | 이익 목표 평가 | profit_target |
| 6 | 리스크 예산 | (stub) |
| 7 | 파라미터 최적화 (+-5%) | execution_optimizer |
| 7-1 | RAG 지식 업데이트 | KnowledgeManager |
| 7-1b | 모듈 리셋 (5개) | position_monitor, capital_guard, tilt_detector, gap_risk_protector, net_liquidity_tracker |
| 7-2 | 오버나이트 판단 | overnight_judge, vix_fetcher, regime_detector |
| 7-3 | 순유동성 갱신 | net_liquidity_tracker |
| 8 | 강제 청산 | order_manager, position_monitor |
| 9~11 | 정리 + 텔레그램 보고 | telegram |

---

## 2. DI Feature 레지스트리 (48개)

### F1 — 크롤링 (2개)

| 키 | 클래스 | 모듈 경로 |
|----|--------|----------|
| `crawl_engine` | CrawlEngine | src.crawlers.engine.crawl_engine |
| `crawl_scheduler` | CrawlScheduler | src.crawlers.scheduler.crawl_scheduler |

### F2 — AI 분석 (10개)

| 키 | 클래스 | 모듈 경로 |
|----|--------|----------|
| `news_classifier` | NewsClassifier | src.analysis.classifier.news_classifier |
| `regime_detector` | RegimeDetector | src.analysis.regime.regime_detector |
| `comprehensive_team` | ComprehensiveTeam | src.analysis.team.comprehensive_team |
| `decision_maker` | DecisionMaker | src.analysis.decision.decision_maker |
| `overnight_judge` | OvernightJudge | src.analysis.decision.overnight_judge |
| `key_news_filter` | KeyNewsFilter | src.analysis.classifier.key_news_filter |
| `eod_feedback` | EODFeedbackReport | src.analysis.feedback.eod_feedback_report |
| `news_theme_tracker` | NewsThemeTracker | src.analysis.classifier.news_theme_tracker |
| `situation_tracker` | OngoingSituationTracker | src.analysis.classifier.situation_tracker |
| `news_translator` | NewsTranslator | src.analysis.classifier.news_translator |

### F3 — 지표 (9개)

| 키 | 클래스 | 모듈 경로 |
|----|--------|----------|
| `price_fetcher` | PriceDataFetcher | src.indicators.price.price_data_fetcher |
| `indicator_bundle_builder` | IndicatorBundleBuilder | src.indicators.bundle_builder |
| `vix_fetcher` | VixFetcher | src.indicators.misc.vix_fetcher |
| `whale_tracker` | WhaleTracker | src.indicators.whale.whale_tracker |
| `volume_profile` | VolumeProfile | src.indicators.volume_profile.volume_profile |
| `contango_detector` | ContangoDetector | src.indicators.misc.contango_detector |
| `nav_premium_tracker` | NAVPremiumTracker | src.indicators.misc.nav_premium_tracker |
| `leverage_decay` | LeverageDecay | src.indicators.misc.leverage_decay |
| `order_flow_aggregator` | OrderFlowAggregator | src.indicators.misc.order_flow_aggregator |

### F4 — 전략 (11개)

| 키 | 클래스 | 모듈 경로 |
|----|--------|----------|
| `entry_strategy` | EntryStrategy | src.strategy.entry.entry_strategy |
| `exit_strategy` | ExitStrategy | src.strategy.exit.exit_strategy |
| `strategy_params` | StrategyParamsManager | src.strategy.params.strategy_params |
| `profit_target` | ProfitTarget | src.strategy.params.profit_target |
| `beast_mode` | BeastMode | src.strategy.beast_mode.beast_mode |
| `stat_arb` | StatArb | src.strategy.stat_arb.stat_arb |
| `micro_regime` | MicroRegime | src.strategy.micro_regime.micro_regime |
| `news_fading` | NewsFading | src.strategy.news_fading.news_fading |
| `pyramiding` | Pyramiding | src.strategy.pyramiding.pyramiding |
| `sector_rotation` | SectorRotation | src.strategy.sector_rotation.sector_rotation |
| `wick_catcher` | WickCatcher | src.strategy.wick_catcher.wick_catcher |

### F5 — 실행 (2개)

| 키 | 클래스 | 모듈 경로 |
|----|--------|----------|
| `order_manager` | OrderManager | src.executor.order.order_manager |
| `position_monitor` | PositionMonitor | src.executor.position.position_monitor |

### F6 — 안전/리스크 (9개)

| 키 | 클래스 | 모듈 경로 |
|----|--------|----------|
| `hard_safety` | HardSafety | src.safety.hard_safety.hard_safety |
| `safety_checker` | SafetyChecker | src.safety.hard_safety.safety_checker |
| `emergency_protocol` | EmergencyProtocol | src.safety.emergency.emergency_protocol |
| `capital_guard` | CapitalGuard | src.safety.guards.capital_guard |
| `tilt_detector` | TiltDetector | src.risk.psychology.tilt_detector |
| `gap_risk_protector` | GapRiskProtector | src.risk.gates.gap_risk |
| `stop_loss` | StopLossManager | src.risk.gates.stop_loss |
| `losing_streak` | LosingStreakDetector | src.risk.gates.losing_streak |
| `net_liquidity_tracker` | NetLiquidityTracker | src.risk.macro.net_liquidity |

### F7 — 텔레그램 (1개)

| 키 | 클래스 | 모듈 경로 |
|----|--------|----------|
| `telegram_notifier` | TelegramNotifier | src.monitoring.telegram.telegram_notifier |

### F8 — 세금/비용 (2개)

| 키 | 클래스 | 모듈 경로 |
|----|--------|----------|
| `fx_manager` | FxManager | src.tax.fx_manager |
| `slippage_tracker` | SlippageTracker | src.tax.slippage_tracker |

### F9 — 최적화 + 유니버스 (2개)

| 키 | 클래스 | 모듈 경로 |
|----|--------|----------|
| `execution_optimizer` | ExecutionOptimizer | src.optimization.param_tuner.execution_optimizer |
| `universe_persister` | UniversePersister | src.common.universe_persister |

---

## 3. 대시보드 / 모니터링

### `/api/dashboard` (dashboard.py) — 4개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/dashboard/summary` | - | DashboardSummaryResponse | 대시보드 요약 (포지션, PnL, 세션 상태, 잔고) |
| GET | `/api/dashboard/positions` | - | PositionsResponse | 보유 포지션 목록. query: `mode` |
| GET | `/api/dashboard/accounts` | - | AccountsResponse | 모의+실전 계좌 잔고 |
| GET | `/api/dashboard/trades/recent` | - | RecentTradesResponse | 최근 체결 거래. query: `limit=10` |

### `/api/dashboard/charts` (charts.py) — 5개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/dashboard/charts/daily-returns` | - | ChartListResponse | 일별 PnL 수익률. query: `days=30` |
| GET | `/api/dashboard/charts/cumulative` | - | ChartListResponse | 누적 수익률 |
| GET | `/api/dashboard/charts/heatmap/ticker` | - | ChartListResponse | 티커별 히트맵. query: `days=30` |
| GET | `/api/dashboard/charts/heatmap/hourly` | - | ChartListResponse | 시간대별 히트맵 |
| GET | `/api/dashboard/charts/drawdown` | - | ChartListResponse | 최대 낙폭 |

### `/api/alerts` (alerts.py) — 3개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/alerts/` | - | AlertListResponse | 전체 알림 목록. query: `limit=100` |
| GET | `/api/alerts/unread-count` | - | AlertUnreadCountResponse | 읽지 않은 알림 수 |
| POST | `/api/alerts/{alert_id}/read` | - | AlertMarkReadResponse | 알림 읽음 처리 |

### `/api/system` (system.py) — 6개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/system/health` | - | HealthResponse | 헬스체크 (로드밸런서용) |
| GET | `/api/system/status` | - | SystemStatusResponse | Claude/KIS/DB/Redis 연결 상태 |
| GET | `/api/system/info` | - | SystemInfoResponse | 버전, 가동시간, 컴포넌트 수 |
| GET | `/api/system/clock` | - | ClockInfoResponse | MarketClock 시간 정보 |
| GET | `/api/system/ai-mode` | - | AiModeResponse | AI 백엔드 모드 (sdk/api/hybrid) |
| POST | `/api/system/ai-mode` | 필요 | AiModeResponse | AI 모드 전환. body: `{mode}` |

---

## 4. 매매 제어

### `/api/trading` (trading_control.py) — 3개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/trading/status` | - | TradingStatusResponse | 자동매매 실행 상태 |
| POST | `/api/trading/start` | 필요 | TradingActionResponse | 자동매매 시작. query: `force=false` |
| POST | `/api/trading/stop` | 필요 | TradingActionResponse | 자동매매 중지. query: `run_eod=true` |

### `/api/emergency` (emergency.py) — 3개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/emergency/status` | - | EmergencyStatusResponse | 긴급 정지 상태 |
| POST | `/api/emergency/stop` | 필요 | EmergencyActionResponse | 긴급 정지 실행. query: `reason` |
| POST | `/api/emergency/resume` | 필요 | EmergencyActionResponse | 긴급 정지 해제 |

### `/api/manual` (manual_trade.py) — 2개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| POST | `/api/manual/analyze` | - | ManualAnalyzeResponse | 수동 매매 전 AI 분석 |
| POST | `/api/manual/execute` | 필요 | ManualExecuteResponse | 수동 매매 실행 (실제 브로커 주문) |

**ManualExecuteRequest:**
```json
{
  "ticker": "SOXL",
  "action": "buy",     // "buy" | "sell"
  "quantity": 10,
  "price": 0.0         // 선택사항
}
```

---

## 5. 분석 / 뉴스

### `/api/analysis` (analysis.py) — 3개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/analysis/tickers` | - | AnalysisTickersResponse | 분석 가능 ETF 유니버스 목록 |
| GET | `/api/analysis/comprehensive/{ticker}` | - | ComprehensiveAnalysisResponse | 티커 종합 분석. query: `ai=true` |
| GET | `/api/analysis/ticker-news/{ticker}` | - | TickerNewsResponse | 티커별 관련 뉴스. query: `limit=20` |

### `/api/news` (news.py) — 6개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/news/dates` | - | NewsDatesResponse | 뉴스 존재 날짜 목록. query: `limit=30` |
| GET | `/api/news/daily` | - | DailyNewsResponse | 일별 뉴스. query: `date, limit=50, category, impact, offset` |
| GET | `/api/news/summary` | - | NewsSummaryResponse | 뉴스 요약. query: `date` |
| GET | `/api/news/{article_id}` | - | ArticleDetailResponse | 기사 상세 |
| POST | `/api/news/collect` | 필요 | NewsCollectResponse | 수동 뉴스 수집 트리거 |
| POST | `/api/news/collect-and-send` | 필요 | NewsCollectResponse | `/collect`의 Flutter 호환 별칭 |

### `/api/crawl` (crawl_control.py) — 2개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| POST | `/api/crawl/manual` | 필요 | CrawlStartResponse | 수동 크롤링 시작 (task_id 반환) |
| GET | `/api/crawl/status/{task_id}` | - | CrawlStatusResponse | 크롤링 태스크 진행 상태 |

---

## 6. 거시경제

### `/api/macro` (macro.py) — 7개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/macro/indicators` | - | MacroIndicatorsResponse | FRED 거시 지표 목록 (VIXCLS, DGS10 등 7종) |
| GET | `/api/macro/history/{series_id}` | - | MacroHistoryResponse | FRED 시리즈 이력. query: `limit=30` |
| GET | `/api/macro/calendar` | - | EconomicCalendarResponse | 경제 캘린더 이벤트 |
| GET | `/api/macro/net-liquidity` | - | NetLiquidityResponse | Net Liquidity (WALCL - TGA - RRP) |
| GET | `/api/macro/indicators/rich` | - | RichMacroResponse | Flutter용 거시지표 종합 (VIX, F&G, Fed Rate 등) |
| GET | `/api/macro/rate-outlook` | - | RateOutlookResponse | 금리 전망 (Fed Funds Rate) |
| GET | `/api/macro/cached-indicators` | - | CachedIndicatorsResponse | Redis 캐시된 FRED 시리즈 전체 원시 데이터 |

### `/api/indicators/crawl` (indicator_crawler.py) — 2개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/indicators/crawl/status` | - | CrawlStatusResponse | FRED 크롤링 상태 |
| POST | `/api/indicators/crawl` | 필요 | CrawlTriggerResponse | FRED 10개 시리즈 수동 크롤링 |

---

## 7. 유니버스 관리

### `/api/universe` (universe.py) — 10개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/universe` | - | UniverseResponse | ETF 유니버스 전체 목록 |
| GET | `/api/universe/sectors` | - | SectorsResponse | 섹터별 ETF 목록 |
| GET | `/api/universe/mappings` | - | MappingsResponse | 티커 매핑 (원본-레버리지 페어) |
| POST | `/api/universe/add` | 필요 | TickerActionResponse | 티커 추가 |
| PUT | `/api/universe/toggle` | 필요 | TickerActionResponse | 티커 활성/비활성 토글 |
| POST | `/api/universe/toggle` | 필요 | TickerActionResponse | PUT /toggle의 POST 별칭 |
| POST | `/api/universe/mappings/add` | 필요 | MappingActionResponse | 매핑 추가 |
| DELETE | `/api/universe/mappings/{underlying}` | 필요 | MappingActionResponse | 매핑 삭제 |
| POST | `/api/universe/auto-add` | 필요 | TickerActionResponse | 기본 메타로 자동 추가 |
| DELETE | `/api/universe/{ticker}` | 필요 | TickerActionResponse | 티커 삭제 |

**영속화**: 모든 변경(add/toggle/delete)은 인메모리 + PostgreSQL `universe_config` 테이블에 2중 저장한다.

**AddTickerRequest:**
```json
{
  "ticker": "TQQQ",
  "name": "ProShares UltraPro QQQ",
  "exchange": "AMS",
  "sector": "broad_market",
  "leverage": 3.0,
  "is_inverse": false,
  "pair_ticker": "SQQQ"
}
```

---

## 8. 전략 / 지표

### `/api/strategy` (strategy.py) — 7개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/strategy/params` | - | StrategyParamsResponse | `strategy_params.json` 전체 |
| PUT | `/api/strategy/params` | 필요 | StrategyParamsUpdateResponse | 전략 파라미터 부분 업데이트 |
| GET | `/api/strategy/ticker-params` | - | TickerParamsAllResponse | 티커별 파라미터 오버라이드 전체 |
| GET | `/api/strategy/ticker-params/{ticker}` | - | TickerParamsSingleResponse | 특정 티커 오버라이드 |
| PUT | `/api/strategy/ticker-params/{ticker}` | 필요 | TickerParamsUpdateResponse | 티커 파라미터 설정 |
| DELETE | `/api/strategy/ticker-params/{ticker}` | 필요 | TickerParamsDeleteResponse | 티커 오버라이드 삭제 |
| POST | `/api/strategy/ticker-params/ai-optimize` | 필요 | AiOptimizeResponse | AI 파라미터 최적화 트리거 |

### `/api/indicators` (indicators.py) — 6개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/indicators/weights` | - | IndicatorWeightsResponse | 지표 가중치 |
| PUT | `/api/indicators/weights` | 필요 | IndicatorWeightUpdateResponse | 가중치 업데이트 |
| GET | `/api/indicators/rsi` | - | RsiDataResponse | 전체 RSI 현황 |
| PUT | `/api/indicators/config` | 필요 | IndicatorConfigResponse | 지표 설정 갱신 |
| GET | `/api/indicators/realtime/{ticker}` | - | RealtimeIndicatorResponse | 실시간 기술 지표 (RSI, MACD, BB, ATR) |
| GET | `/api/indicators/rsi/{ticker}` | - | TripleRsiResponse | 트리플 RSI (7/14/21). query: `days=100` |

### `/api/orderflow` (order_flow.py) — 3개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/orderflow/snapshot` | - | OrderflowSnapshotResponse | 주문흐름 스냅샷 |
| GET | `/api/orderflow/history` | - | OrderflowHistoryResponse | 주문흐름 이력. query: `ticker, limit=50` |
| GET | `/api/orderflow/whale` | - | WhaleActivityResponse | 고래 활동. query: `limit=20` |

---

## 9. 리스크 / 안전

### `/api/risk` (risk.py) — 1개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/risk/dashboard` | - | RiskDashboardResponse | 리스크 대시보드 종합 |

**RiskDashboardResponse 주요 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| portfolio_var | float | 포트폴리오 VaR |
| max_drawdown_pct | float | 최대 낙폭 |
| current_drawdown_pct | float | 현재 낙폭 |
| position_concentration | float | 포지션 집중도 |
| regime | str | 시장 레짐 |
| vix_current | float | 현재 VIX |
| risk_score | int | 종합 리스크 스코어 (0~10) |
| warnings | list[str] | 리스크 경고 목록 |
| gates | list[GateEntry] | 안전 게이트 상태 |
| trailing_stop | TrailingStopData | StopLossManager 상태 |
| streak_counter | StreakData | LosingStreakDetector 상태 |

---

## 10. 성과 / 보고서

### `/api/performance` (performance.py) — 3개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/performance/summary` | - | PerformanceSummaryResponse | 성과 요약 (PnL, 승률, 샤프, MDD) |
| GET | `/api/performance/daily` | - | DailyPerformanceResponse | 일별 성과. query: `limit=30` |
| GET | `/api/performance/monthly` | - | MonthlyPerformanceResponse | 월별 성과. query: `limit=12` |

### `/api/benchmark` (benchmark.py) — 2개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/benchmark/comparison` | - | BenchmarkComparisonResponse | SPY/QQQ 대비 수익률 |
| GET | `/api/benchmark/chart` | - | BenchmarkChartResponse | 벤치마크 차트. query: `period` (1W/1M/3M/6M/1Y) |

### `/api/reports` (reports.py) — 2개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/reports/daily/list` | - | DailyReportListResponse | 일별 리포트 목록. query: `limit=30` |
| GET | `/api/reports/daily` | - | DailyReportResponse | 일별 상세 리포트. query: `date` (필수) |

### `/api/target` (profit_target.py) — 5개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/target/current` | - | ProfitTargetCurrentResponse | 월간 목표 달성 현황 |
| PUT | `/api/target/aggression` | 필요 | ProfitTargetAggressionResponse | 공격성 레벨 변경 (conservative/moderate/aggressive/max) |
| GET | `/api/target/monthly` | - | ProfitTargetMonthlyResponse | 이번 달 목표 현황 |
| GET | `/api/target/history` | - | ProfitTargetHistoryResponse | 월간 목표 이력. query: `limit=12` |
| GET | `/api/target/projection` | - | ProfitTargetProjectionResponse | 수익 추정치 (월간/연간) |

### `/api/trade-reasoning` (trade_reasoning.py) — 5개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/trade-reasoning/dates` | - | TradeDatesResponse | 매매 존재 날짜 목록 |
| GET | `/api/trade-reasoning/daily` | - | DailyReasoningResponse | 일별 매매 근거. query: `date` |
| GET | `/api/trade-reasoning/stats` | - | TradeStatsResponse | 매매 통계 (승률, 평균 수익/손실) |
| POST | `/api/trade-reasoning/{trade_id}/feedback` | 필요 | TradeFeedbackResponse | 매매 피드백 저장. body: `{rating, comment}` |
| PUT | `/api/trade-reasoning/{trade_id}/feedback` | 필요 | TradeFeedbackResponse | 매매 피드백 저장 (PUT 별칭) |

---

## 11. 세금 / 비용

### `/api/tax` (tax.py) — 3개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/tax/status` | - | TaxStatusResponse | 연초 대비 세금 현황 |
| GET | `/api/tax/report` | - | TaxReportResponse | 연간 세금 리포트. query: `year=2026` |
| GET | `/api/tax/harvest-suggestions` | - | TaxHarvestResponse | 세금 손실 수확 제안 |

### `/api/fx` (fx.py) — 2개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/fx/status` | - | FxStatusResponse | USD/KRW 환율 현황 |
| GET | `/api/fx/history` | - | FxHistoryResponse | 환율 이력. query: `limit=30` |

### `/api/slippage` (slippage.py) — 2개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/slippage/stats` | - | SlippageStatsResponse | 슬리피지 종합 통계 |
| GET | `/api/slippage/optimal-hours` | - | SlippageOptimalHoursResponse | 시간대별 최적 체결 시간 |

---

## 12. AI 에이전트

### `/api/agents` (agents.py) — 5개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/agents` | - | AgentsListResponse | AI 에이전트 + 시스템 모듈 전체 목록 |
| GET | `/api/agents/list` | - | AgentTeamsResponse | 에이전트 팀 목록 (6팀) |
| GET | `/api/agents/{agent_id}/history` | - | AgentHistoryResponse | 에이전트 활동 이력. query: `limit=20` |
| GET | `/api/agents/{agent_id}` | - | AgentDetailResponse | 에이전트 상세 + MD 콘텐츠 |
| PUT | `/api/agents/{agent_id}` | 필요 | AgentSaveResponse | 에이전트 MD 콘텐츠 저장 |

---

## 13. 매매 원칙 / 피드백

### `/api/principles` (principles.py) — 5개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/principles` | - | PrinciplesListResponse | 매매 원칙 목록 + 핵심 원칙 |
| POST | `/api/principles` | 필요 | PrincipleCreateResponse | 원칙 추가. body: `{title, content, category}` |
| PUT | `/api/principles/core` | 필요 | CorePrincipleResponse | 핵심 원칙 저장/수정 |
| PUT | `/api/principles/{id}` | 필요 | PrincipleUpdateResponse | 원칙 부분 수정 |
| DELETE | `/api/principles/{id}` | 필요 | PrincipleDeleteResponse | 원칙 삭제 |

### `/api/feedback` (feedback.py) — 6개

| 메서드 | 경로 | 인증 | 응답 모델 | 설명 |
|--------|------|------|----------|------|
| GET | `/api/feedback/daily/{date}` | - | FeedbackReportResponse | 일별 피드백 리포트. path: `YYYY-MM-DD` |
| GET | `/api/feedback/weekly/{week}` | - | FeedbackReportResponse | 주차 피드백 리포트. path: `YYYY-WNN` |
| GET | `/api/feedback/latest` | - | FeedbackReportResponse | 최근 피드백 리포트 |
| GET | `/api/feedback/pending-adjustments` | - | PendingAdjustmentsResponse | 승인 대기 전략 조정 목록 |
| POST | `/api/feedback/approve-adjustment/{id}` | 필요 | AdjustmentActionResponse | 조정 승인 |
| POST | `/api/feedback/reject-adjustment/{id}` | 필요 | AdjustmentActionResponse | 조정 거절 |

---

## 14. WebSocket 실시간 채널

| 경로 | 갱신 주기 | Redis 키 | 설명 |
|------|----------|---------|------|
| `WS /ws/dashboard` | 3초 | `ws:dashboard` | 대시보드 실시간 스트림 |
| `WS /ws/positions` | 3초 | `ws:positions` | 포지션 실시간 스트림 |
| `WS /ws/orderflow` | 3초 | `ws:orderflow` | 주문흐름 실시간 스트림 |
| `WS /ws/alerts` | 3초 | `ws:alerts` | 알림 실시간 스트림 |
| `WS /ws/trades` | 3초 | `ws:trades` | 매매 실시간 스트림 |
| `WS /ws/crawl/{task_id}` | 1초 | `crawl:task:{task_id}` | 크롤링 진행 상태 (완료 시 자동 종료) |

---

## 15. Flutter 호환 별칭

Flutter 대시보드의 하드코딩된 경로를 위한 별칭 라우터.

### `/agents` (agents_compat_router) — 3개

| 메서드 | 원본 경로 | 별칭 경로 |
|--------|----------|----------|
| GET | `/api/agents/list` | `/agents/list` |
| GET | `/api/agents/{id}` | `/agents/{id}` |
| PUT | `/api/agents/{id}` | `/agents/{id}` |

### `/feedback` (feedback_compat_router) — 4개

| 메서드 | 원본 경로 | 별칭 경로 |
|--------|----------|----------|
| GET | `/api/feedback/weekly/{week}` | `/feedback/weekly/{week}` |
| GET | `/api/feedback/pending-adjustments` | `/feedback/pending-adjustments` |
| POST | `/api/feedback/approve-adjustment/{id}` | `/feedback/approve-adjustment/{id}` |
| POST | `/api/feedback/reject-adjustment/{id}` | `/feedback/reject-adjustment/{id}` |

---

## 부록: DB 테이블 목록 (27개 + alembic_version)

> 출처: `src/db/models.py` ORM 클래스 (`__tablename__`)

| # | 테이블명 | ORM 클래스 | 용도 |
|---|---------|-----------|------|
| 1 | articles | Article | 뉴스 기사 영구 저장 (news_pipeline → ArticlePersister) |
| 2 | trades | Trade | 체결 거래 기록 (OrderManager → DB) |
| 3 | etf_universe | EtfUniverse | ETF 유니버스 마스터 (ticker, leverage, exchange) |
| 4 | indicator_history | IndicatorHistory | 지표 이력 (ticker별 지표값 + JSON 메타) |
| 5 | strategy_param_history | StrategyParamHistory | 전략 파라미터 변경 이력 (old → new + 사유) |
| 6 | feedback_reports | FeedbackReport | 피드백 보고서 (daily/weekly, JSON content) |
| 7 | crawl_checkpoints | CrawlCheckpoint | 크롤링 체크포인트 (source별 마지막 URL/시각) |
| 8 | pending_adjustments | PendingAdjustment | 대기 중 파라미터 조정 (승인 전 큐) |
| 9 | tax_records | TaxRecord | 세금 기록 (gain_usd, tax_krw, fx_rate) |
| 10 | fx_rates | FxRateRecord | 환율 기록 (USD/KRW, source) |
| 11 | slippage_log | SlippageLog | 슬리피지 기록 (order별 슬리피지 %) |
| 12 | emergency_events | EmergencyEvent | 긴급 정지 이력 (event_type, action_taken) |
| 13 | benchmark_snapshots | BenchmarkSnapshot | 벤치마크 스냅샷 (SPY 대비 포트폴리오) |
| 14 | capital_guard_log | CapitalGuardLog | 자본 보호 발동 로그 (guard_type, trigger_value) |
| 15 | notification_log | NotificationLog | 알림 발송 로그 (channel, event_type, success) |
| 16 | profit_targets | ProfitTarget | 수익 목표 (ticker별 target_pct, achieved) |
| 17 | daily_pnl_log | DailyPnlLog | 일별 PnL (date, pnl_amount, pnl_pct, equity) |
| 18 | risk_config | RiskConfig | 리스크 설정 (param_name/value 키-값 쌍) |
| 19 | risk_events | RiskEvent | 리스크 이벤트 (event_type, severity, detail) |
| 20 | backtest_results | BacktestResult | 백테스트 결과 (strategy, params JSON, metrics JSON) |
| 21 | fear_greed_history | FearGreedHistory | Fear&Greed 지수 이력 (CNN 등) |
| 22 | prediction_markets | PredictionMarket | 예측시장 데이터 (Polymarket/Kalshi 확률) |
| 23 | historical_analyses | HistoricalAnalysis | 과거 분석 결과 (analysis_type, ticker, result JSON) |
| 24 | historical_analysis_progress | HistoricalAnalysisProgress | 분석 진행 상태 (task_name, status, progress_pct) |
| 25 | tick_data | TickData | 틱 데이터 (ticker, price, volume, timestamp) |
| 26 | rag_documents | RagDocument | RAG 문서 (doc_type, title, content, embedding_id) |
| 27 | universe_config | UniverseConfig | 유니버스 설정 (DB source of truth, 0002 마이그레이션) |
| — | alembic_version | — | Alembic 마이그레이션 버전 관리 (현재: 0002) |

---

## 부록: Redis 키 규약

> 출처: `src/` 전체 코드의 `cache.read/write/read_json/write_json` 호출 전수 조사

### 뉴스 (News)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `news:classified_latest` | 2시간 | 분류된 뉴스 최신 | news_pipeline, preparation, trading_loop |
| `news:latest_summary` | 2시간 | 뉴스 요약 | news_pipeline, continuous_analysis |
| `news:key_latest` | 2시간 | 핵심 뉴스 (impact >= 0.7) | news_pipeline |
| `news:themes_latest` | 2시간 | 뉴스 테마 추적 결과 | news_pipeline |
| `news:situation_reports_latest` | 2시간 | 상황 보고서 | news_pipeline |
| `news:translated_latest` | 2시간 | 번역된 뉴스 | news_pipeline (NewsTranslator) |
| `news:dates` | 영구 | 뉴스 날짜 목록 | news endpoint |
| `news:daily:{date}` | 영구 | 날짜별 뉴스 아카이브 | news endpoint |
| `news:summary:{date}` | 영구 | 날짜별 뉴스 요약 | news endpoint |
| `news:article:{article_id}` | 영구 | 개별 기사 상세 | news endpoint |
| `news:{ticker}` | 영구 | 티커별 관련 뉴스 | analysis endpoint |

### 분석 (Analysis)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `analysis:comprehensive_report` | 2시간 | 종합 분석 보고서 | preparation, trading_loop |
| `analysis:{ticker}` | 30분 | 티커별 분석 캐시 | analysis endpoint |
| `continuous_analysis:latest` | 2시간 | 연속 분석 결과 | continuous_analysis loop |

### 상황 추적 (Situation/Theme)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `situation:active_ids` | 30일 | 활성 상황 ID 목록 | situation_tracker |
| `situation:{id}:meta` | 30일 | 상황 메타데이터 | situation_tracker |
| `situation:{id}:timeline` | 30일 | 상황 타임라인 | situation_tracker |
| `situation:last_telegram_ts:{id}` | 30일 | 텔레그램 마지막 전송 시각 | situation_tracker |
| `theme:{theme_name}` | 7일 | 뉴스 테마 추적 카운터 | news_theme_tracker |

### 매매 (Trades)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `trades:today` | 24시간 | 금일 거래 목록 | trading_loop, eod_sequence |
| `trades:recent` | 영구 | 최근 거래 목록 | dashboard endpoint |
| `trades:weekly` | 영구 | 주간 거래 목록 | weekly_analysis |
| `trades:dates` | 영구 | 거래 날짜 목록 | trade_reasoning endpoint |
| `trades:reasoning:{date}` | 영구 | 날짜별 매매 근거 | trade_reasoning endpoint |
| `trades:reasoning:latest` | 영구 | 최신 매매 근거 | trade_reasoning endpoint |
| `trades:stats` | 영구 | 매매 통계 | trade_reasoning endpoint |
| `trades:feedback:{trade_id}` | 영구 | 개별 매매 피드백 | trade_reasoning endpoint |

### PnL / 성과 (Performance)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `pnl:daily` | 24시간 | 금일 PnL | eod_sequence |
| `pnl:monthly` | 영구 | 월간 PnL | eod_sequence |
| `pnl:history:{date}` | 30일 | 일별 PnL 이력 | eod_sequence, reports endpoint |
| `pnl:history:dates` | 영구 | PnL 날짜 목록 | reports endpoint |
| `performance:summary` | 영구 | 성과 요약 | performance endpoint |
| `performance:daily` | 영구 | 일별 성과 | performance endpoint |
| `performance:monthly` | 영구 | 월별 성과 | performance endpoint |
| `performance:monthly_pnl` | 영구 | 월별 PnL 상세 | profit_target endpoint |

### 차트 (Charts)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `charts:daily_returns` | 90일 | 일별 수익률 차트 | chart_data_writer, charts endpoint |
| `charts:cumulative_returns` | 90일 | 누적 수익률 차트 | chart_data_writer, charts endpoint |
| `charts:heatmap_ticker` | 90일 | 티커별 히트맵 | chart_data_writer, charts endpoint |
| `charts:heatmap_hourly` | 90일 | 시간대별 히트맵 | chart_data_writer, charts endpoint |
| `charts:drawdown` | 90일 | 낙폭 차트 | chart_data_writer, charts endpoint |

### 지표 (Indicators)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `indicators:latest` | 영구 | 최신 지표 번들 | continuous_analysis, analysis endpoint |
| `indicators:rsi` | 영구 | RSI 전체 데이터 | indicators endpoint |
| `indicators:rsi:{ticker}` | 5분 | 티커별 RSI 캐시 | indicators endpoint |
| `indicators:realtime:{ticker}` | 영구 | 티커별 실시간 지표 | indicators endpoint |
| `indicators:config` | 영구 | 지표 설정값 | indicators endpoint |

### 시장 (Market)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `market:vix` | 1시간 | VIX 현재값 (FRED VIXCLS) | vix_fetcher, contango_detector |
| `market:vix9d` | 영구 | VIX 9일 | contango_detector |
| `market:vix3m` | 영구 | VIX 3개월 | contango_detector |
| `market:vix_change` | 영구 | VIX 변동률 | eod_sequence |
| `market:pair_prices` | 영구 | 페어트레이딩 시세 | trading_loop |
| `price:pre_close:{ticker}` | 영구 | 전일 종가 | trading_loop |

### 매크로 (Macro)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `macro:{series_id}` | 24시간 | FRED 시리즈 캐시 (VIXCLS, DGS10 등) | macro endpoint, indicator_crawler |
| `macro:calendar` | 영구 | 경제 캘린더 | macro endpoint |
| `macro:net_liquidity` | 1시간 | 순유동성 바이어스 | net_liquidity tracker |
| `macro:fear_greed` | 1시간 | Fear&Greed 지수 | macro endpoint |

### 주문흐름 (Order Flow)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `order_flow:raw:{ticker}` | 30초 | WebSocket 원시 주문흐름 | redis_publisher, order_flow_aggregator |
| `order_flow:obi:{ticker}` | 영구 | 주문장 불균형 | cross_asset_momentum |
| `orderflow:snapshot` | 영구 | 주문흐름 스냅샷 | order_flow endpoint |
| `orderflow:history:{ticker}` | 영구 | 티커별 주문흐름 이력 | order_flow endpoint |
| `orderflow:whale` | 영구 | 고래 활동 | order_flow endpoint |
| `whale:order_flow:{ticker}` | 영구 | 티커별 고래 주문흐름 | whale_tracker |
| `momentum:score:{ticker}` | 영구 | 크로스에셋 모멘텀 점수 | cross_asset_momentum |

### WebSocket 채널 캐시

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `ws:dashboard` | 30초 | 대시보드 실시간 데이터 | trading_loop → ws_manager |
| `ws:positions` | 30초 | 포지션 실시간 데이터 | trading_loop → ws_manager |
| `ws:trades` | 30초 | 매매 실시간 데이터 | trading_loop → ws_manager |
| `ws:orderflow` | — | 주문흐름 실시간 | ws_manager 구독 |
| `ws:alerts` | — | 알림 실시간 | ws_manager 구독 |
| `ws:trade:{ticker}` | — | 틱별 체결 Pub/Sub | redis_publisher |
| `ws:orderbook:{ticker}` | — | 틱별 호가 Pub/Sub | redis_publisher |

### 피드백 (Feedback)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `feedback:latest` | 24시간 | 최신 피드백 보고서 | eod_sequence, feedback endpoint |
| `feedback:{date}` | 영구 | 날짜별 피드백 | feedback endpoint, reports endpoint |
| `feedback:weekly:{week}` | 영구 | 주간 피드백 | feedback endpoint |
| `feedback:pending_adjustments` | 영구 | 대기 중 파라미터 조정 | feedback endpoint |
| `feedback:applied_adjustments` | 영구 | 적용 완료 조정 | feedback endpoint |

### 벤치마크 (Benchmark)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `benchmark:comparison` | 영구 | 벤치마크 비교 데이터 | benchmark endpoint |
| `benchmark:chart:{period}` | 영구 | 기간별 벤치마크 차트 (1M, 3M 등) | benchmark endpoint |

### 대시보드 (Dashboard)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `dashboard:buy_power` | 60초 | 매수 가용 잔액 캐시 | dashboard endpoint |

### 수익 목표 (Profit Target)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `profit_target:meta` | 영구 | 수익 목표 메타 | profit_target endpoint |
| `profit_target:history` | 영구 | 수익 목표 이력 | profit_target endpoint |

### 세금 / 환율 / 슬리피지

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `tax:status` | 영구 | 세금 현황 | tax endpoint |
| `tax:report:{year}` | 영구 | 연도별 세금 보고서 | tax endpoint |
| `tax:harvest` | 영구 | 세금 절세 기회 | tax endpoint |
| `fx:current` | 영구 | 현재 환율 | fx_scheduler, fx endpoint |
| `fx:history` | 영구 | 환율 이력 | fx_scheduler, fx endpoint |
| `slippage:stats` | 영구 | 슬리피지 통계 | slippage endpoint |
| `slippage:hours` | 영구 | 시간대별 슬리피지 | slippage endpoint |

### 에이전트 / 알림

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `agent:md:{agent_id}` | 영구 | 에이전트 문서 (MD 형식) | agents endpoint |
| `agent:status:{agent_id}` | 영구 | 에이전트 상태 | agents endpoint |
| `agent:history:{agent_id}` | 영구 | 에이전트 이력 | agents endpoint |
| `alerts:list` | 영구 | 알림 목록 | alerts endpoint |
| `alerts:read` | 영구 | 읽은 알림 ID 집합 | alerts endpoint |

### 매매 원칙 (Principles)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `trading:principles` | 영구 | 매매 원칙 목록 | principles endpoint |
| `principles:core` | 영구 | 핵심 원칙 텍스트 | principles endpoint |

### 유니버스 (Universe)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `universe:mappings` | 영구 | 유니버스 매핑 데이터 | universe endpoint |

### 크롤링 (Crawl)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `crawl:task:{task_id}` | 영구 | 크롤링 태스크 상태 | crawl_control endpoint |
| `dedup:{sha256_hash}` | 48시간 | 기사 중복 제거 해시 | article_dedup |

### 전략 (Strategy)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `stat_arb:spread:{base}/{etf}` | 24시간 | 스프레드 z-score | stat_arb module |

### ML / 최적화

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `ml:prepared_data:{start}:{end}` | 1시간 | ML 학습 데이터 캐시 | data_preparer |

### 안전 (Safety)

| 패턴 | TTL | 용도 | 주요 사용처 |
|------|-----|------|------------|
| `quota:kis_api:{window_id}` | 60초 | KIS API 호출 쿼터 | quota_guard |

### TTL 요약

| TTL | 키 도메인 |
|-----|----------|
| 30초 | `order_flow:raw:*`, `ws:dashboard`, `ws:positions`, `ws:trades` |
| 60초 | `dashboard:buy_power`, `quota:kis_api:*` |
| 5분 | `indicators:rsi:{ticker}` |
| 30분 | `analysis:{ticker}` |
| 1시간 | `market:vix`, `macro:net_liquidity`, `macro:fear_greed`, `ml:prepared_data:*` |
| 2시간 | `news:*_latest`, `analysis:comprehensive_report`, `continuous_analysis:latest` |
| 24시간 | `trades:today`, `feedback:latest`, `macro:{series_id}`, `stat_arb:spread:*` |
| 48시간 | `dedup:{hash}` |
| 7일 | `theme:{name}` |
| 30일 | `pnl:history:{date}`, `situation:*` |
| 90일 | `charts:*` |
| 영구 | 대부분의 엔드포인트 캐시 키 (수동 갱신) |
