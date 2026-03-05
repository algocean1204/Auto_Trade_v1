# 📊 Stock Trading AI System V2 — 현재 상태 (리팩토링 전)

> 작성일: 2026-02-26
> 목적: 리팩토링 시작 전 현재 코드베이스의 상태를 정확히 문서화한다.
> 이 문서는 리팩토링의 "Before" 기준점(baseline)으로 사용한다.

---

## 1. 프로젝트 개요

### 1.1 시스템 설명
AI 기반 자동매매 시스템으로, 미국 2X 레버리지 ETF(SOXL, QLD, NVDL 등)를 대상으로 야간 자동매매를 수행한다.
KIS OpenAPI(한국투자증권)를 통해 실제 주문을 실행하며, Claude Opus/Sonnet과 로컬 MLX 모델을 결합하여 AI 기반 투자 판단을 내린다.

### 1.2 핵심 구성 요소

| 구분 | 내용 |
|---|---|
| **매매 대상** | 미국 2X 레버리지 ETF (SOXL, QLD, NVDL, SOXS, NVDS 등) |
| **브로커** | 한국투자증권 KIS OpenAPI (가상/실전 듀얼 계정) |
| **AI 판단** | Claude Opus (종합분석) + Claude Sonnet (실시간 판단) |
| **로컬 AI** | Qwen3-30B-A3B via MLX 4bit (16GB, Apple Silicon MPS) |
| **RAG** | ChromaDB + BGE-M3 임베딩 (지식 기반 검색) |
| **DB** | PostgreSQL 17 + pgvector + Redis 7 |
| **백엔드** | FastAPI (모니터링 서버, 포트 8000) |
| **대시보드** | Flutter (iOS/Android 모바일 앱) |
| **스케줄러** | macOS LaunchAgent (23:00~06:30 KST 야간 자동 실행) |
| **하드웨어** | MacBook Pro M4 Pro, 48GB RAM (MPS/GPU 로컬 AI 실행) |

### 1.3 매매 시간대

```
20:00 KST  → 준비 단계: 크롤링, 분류, 종합분석팀 분석, 안전 체크
23:00 KST  → 정규장 개시 (Power Open 90초 루프)
00:00~04:00→ 중간 세션 (Mid Session 180초 루프)
04:00~05:30→ Power Hour (120초 루프)
06:00~06:30→ EOD 정리, overnight 포지션 판단, Daily Feedback
06:30 KST  → 자동 종료 (LaunchAgent 재실행 대기)
```

### 1.4 주요 보안 체계

```
HardSafety → SafetyChecker → EmergencyProtocol → CapitalGuard
DeadmanSwitch (WebSocket 데이터 10초 이상 무응답 → Beast 청산)
MacroFlashCrashDetector (SPY/QQQ -1.0%/3분 → 전체 청산)
```

---

## 2. 코드베이스 통계

### 2.1 파일 수 및 규모

| 분류 | 파일 수 | 총 줄 수 |
|---|---|---|
| Python (src/) | 292개 | 84,524줄 |
| Dart (dashboard/lib/) | 121개 | 46,868줄 |
| **합계** | **413개** | **131,392줄** |

> Python 292개 중 모듈 파일(비 `__init__`, 비 `__pycache__`) 기준으로 실질적인 코드 파일은 약 215개이다.

### 2.2 테스트

| 분류 | 파일 수 | 비고 |
|---|---|---|
| Python 테스트 (`test_*.py`) | 42개 | src/ 하위 전체 |
| Dart 테스트 | 11개 | dashboard/test/ |

### 2.3 DB 테이블 (PostgreSQL 17 + pgvector)

총 26개 테이블:

| 테이블명 | 역할 |
|---|---|
| `rag_documents` | RAG 지식 문서 (pgvector 임베딩) |
| `etf_universe` | 매매 유니버스 ETF 목록 |
| `trades` | 체결 내역 |
| `indicator_history` | 기술적 지표 이력 |
| `strategy_param_history` | 전략 파라미터 변경 이력 |
| `feedback_reports` | 일일 피드백 보고서 |
| `crawl_checkpoints` | 크롤러 체크포인트 |
| `articles` | 수집된 뉴스 기사 |
| `pending_adjustments` | 보류 중인 포지션 조정 |
| `tax_records` | 세금 계산 기록 |
| `fx_rates` | 환율 이력 |
| `slippage_log` | 슬리피지 로그 |
| `emergency_events` | 비상 이벤트 기록 |
| `benchmark_snapshots` | 벤치마크 스냅샷 |
| `capital_guard_log` | 자본 보호 로그 |
| `notification_log` | 알림 발송 기록 |
| `profit_targets` | 목표 수익 설정 |
| `daily_pnl_log` | 일일 손익 로그 |
| `risk_config` | 리스크 설정값 |
| `risk_events` | 리스크 이벤트 기록 |
| `backtest_results` | 백테스트 결과 |
| `fear_greed_history` | 공포/탐욕 지수 이력 |
| `prediction_markets` | 예측 시장 데이터 |
| `historical_analyses` | 과거 분석 기록 |
| `historical_analysis_progress` | 분석 진행 상태 |
| `tick_data` | WebSocket 실시간 체결 데이터 |

### 2.4 API 엔드포인트

| 분류 | 수량 |
|---|---|
| REST API (GET/POST/PUT/DELETE) | 약 90개 |
| WebSocket | 4개 |
| **합계** | **약 94개** |

### 2.5 크롤러 소스

총 30개 소스 (24개 크롤러 파일이 다수 소스 담당):

- RSS: Reuters, Bloomberg, WSJ, AP, CNBC 등
- API: Finnhub, AlphaVantage, FRED, Fear&Greed, Finviz
- 스크래핑: Naver, StockNow, SEC Edgar, Kalshi, Polymarket
- 소셜: Reddit (r/stocks, r/investing, r/wallstreetbets), StockTwits
- 예측시장: Kalshi, Polymarket
- 공시: DART (한국), SEC (미국)

---

## 3. 현재 디렉토리 구조

```
Stock_Trading/
├── src/                           # 핵심 Python 소스 (292개 파일, 84,524줄)
│   ├── main.py                    # ★ God Object (3,255줄, 111 imports)
│   ├── ai/                        # 로컬 AI (3개 파일)
│   │   ├── __init__.py
│   │   ├── knowledge_manager.py   # ChromaDB + BGE-M3 (691줄)
│   │   └── mlx_classifier.py      # Qwen3-30B-A3B MLX 분류기
│   ├── analysis/                  # Claude AI 분석 (13개 파일)
│   │   ├── classifier.py          # 뉴스 분류 (623줄, lazy imports 5개)
│   │   ├── claude_client.py       # Claude API 클라이언트 (649줄)
│   │   ├── comprehensive_team.py  # 종합분석팀 오케스트레이터
│   │   ├── decision_maker.py      # 매매 결정 (cross-layer: monitoring import)
│   │   ├── eod_feedback_report.py # EOD 피드백 보고서 (신규)
│   │   ├── key_news_filter.py     # 핵심 뉴스 필터 (520줄)
│   │   ├── news_theme_tracker.py  # 뉴스 테마 추적 (신규)
│   │   ├── news_translator.py     # 뉴스 번역
│   │   ├── overnight_judge.py     # 오버나이트 판단
│   │   ├── prompts.py             # ★ 시스템 프롬프트 모음 (1,896줄)
│   │   ├── regime_detector.py     # VIX 기반 시장 레짐 탐지
│   │   └── ticker_profiler.py     # 티커 프로파일링 (lazy imports)
│   ├── crawler/                   # 뉴스 크롤링 파이프라인 (24개 파일)
│   │   ├── crawl_engine.py        # ★ 크롤링 엔진 (1,099줄)
│   │   ├── crawl_scheduler.py     # 야간/주간 모드 스케줄러
│   │   ├── crawl_verifier.py      # 크롤링 결과 검증
│   │   ├── base_crawler.py        # 기본 크롤러 인터페이스
│   │   ├── rss_crawler.py         # RSS 피드 크롤러
│   │   ├── finnhub_crawler.py     # Finnhub API
│   │   ├── alphavantage_crawler.py # AlphaVantage API
│   │   ├── naver_crawler.py       # 네이버 증권 (670줄)
│   │   ├── reddit_crawler.py      # Reddit API (PRAW)
│   │   ├── investing_crawler.py   # Investing.com (511줄)
│   │   └── (기타 14개 크롤러)
│   ├── db/                        # 데이터베이스 (3개 파일)
│   │   ├── connection.py          # DB/Redis 연결 관리
│   │   ├── models.py              # SQLAlchemy ORM 모델 (675줄, 26 테이블)
│   │   └── __init__.py
│   ├── executor/                  # KIS API 실행 계층 (8개 파일)
│   │   ├── kis_client.py          # ★ KIS API 클라이언트 (1,261줄)
│   │   ├── kis_auth.py            # KIS 인증 (토큰 관리)
│   │   ├── order_manager.py       # 주문 관리 (668줄)
│   │   ├── position_monitor.py    # 포지션 모니터 (588줄, cross-layer!)
│   │   ├── universe_manager.py    # 매매 유니버스 관리
│   │   ├── forced_liquidator.py   # 강제 청산
│   │   └── position_bootstrap.py  # 포지션 부트스트래퍼
│   ├── fallback/                  # AI 폴백 라우터 (3개 파일)
│   │   ├── fallback_router.py     # Claude → MLX 폴백
│   │   └── local_model.py         # 로컬 모델 인터페이스
│   ├── feedback/                  # EOD 피드백 시스템 (13개 파일)
│   │   ├── daily_feedback.py      # 일일 피드백 생성
│   │   ├── weekly_analysis.py     # 주간 분석
│   │   ├── rag_doc_updater.py     # RAG 문서 업데이트
│   │   ├── param_adjuster.py      # 파라미터 자동 조정
│   │   ├── time_performance.py    # 시간대별 성과 분석 (551줄)
│   │   └── execution_optimizer/   # 실행 최적화 (6개 파일)
│   │       ├── trade_analyzer.py
│   │       ├── param_tuner.py
│   │       ├── param_writer.py
│   │       └── runner.py
│   ├── filter/                    # 뉴스 필터링 (3개 파일)
│   │   ├── rule_filter.py         # 규칙 기반 필터
│   │   ├── similarity_checker.py  # 중복 뉴스 체크
│   │   └── filter_config.json     # 필터 설정 (JSON)
│   ├── indicators/                # 기술적 지표 (32개 파일)
│   │   ├── aggregator.py          # 지표 종합기
│   │   ├── calculator.py          # 기술 지표 계산 (ATR, RSI 등)
│   │   ├── data_fetcher.py        # KIS API 가격 데이터 (lazy import)
│   │   ├── macd_divergence.py     # MACD 다이버전스 (713줄)
│   │   ├── contango_detector.py   # 콘탱고 탐지
│   │   ├── nav_premium.py         # NAV 프리미엄 트래커
│   │   ├── cross_asset/           # 크로스 에셋 모멘텀 (5개 파일)
│   │   │   ├── leader_map.py      # 17쌍 리더-팔로워 맵
│   │   │   ├── leader_aggregator.py
│   │   │   ├── divergence_detector.py
│   │   │   └── momentum_scorer.py
│   │   ├── volume_profile/        # 볼륨 프로파일 (6개 파일)
│   │   │   ├── accumulator.py
│   │   │   ├── calculator.py      # POC + Value Area
│   │   │   ├── signal_generator.py
│   │   │   └── redis_feeder.py
│   │   └── whale/                 # 고래 탐지 (4개 파일)
│   │       ├── block_detector.py  # $200k+ 블록 탐지
│   │       ├── iceberg_detector.py
│   │       └── whale_scorer.py
│   ├── macro/                     # 거시경제 (2개 파일)
│   │   └── net_liquidity.py       # FRED Net Liquidity 필터 (575줄)
│   ├── monitoring/                # ★ FastAPI 모니터링 서버 (32개 파일, 최대)
│   │   ├── api_server.py          # FastAPI 앱 + 의존성 주입 (666줄)
│   │   ├── dashboard_endpoints.py # ★ 대시보드 API (1,840줄, cross-layer!)
│   │   ├── analysis_endpoints.py  # 분석 API (918줄)
│   │   ├── universe_endpoints.py  # 유니버스 API (1,048줄)
│   │   ├── telegram_notifier.py   # 텔레그램 알림 (717줄)
│   │   ├── fred_client.py         # FRED 데이터 클라이언트 (674줄)
│   │   ├── indicator_crawler.py   # 실시간 지표 크롤러 (661줄)
│   │   ├── benchmark.py           # 벤치마크 비교
│   │   ├── schemas.py             # Pydantic 스키마
│   │   ├── trading_control_endpoints.py # 매매 제어 API
│   │   └── (기타 22개 엔드포인트 파일)
│   ├── optimization/              # ML 파이프라인 (11개 파일)
│   │   ├── data_preparer.py       # 학습 데이터 준비
│   │   ├── feature_engineer.py    # 피처 엔지니어링 (21개 피처)
│   │   ├── lgbm_trainer.py        # LightGBM 학습
│   │   ├── optuna_optimizer.py    # Optuna 하이퍼파라미터 최적화
│   │   ├── walk_forward.py        # Walk-Forward 검증
│   │   ├── auto_trainer.py        # 주간 자동 재학습
│   │   └── time_travel.py         # 분 단위 과거 재현 → ChromaDB
│   ├── orchestration/             # 실행 오케스트레이션 (5개 파일)
│   │   ├── continuous_analysis.py # 30분 단위 연속 분석 (23:00~06:30)
│   │   ├── news_pipeline.py       # 뉴스 파이프라인
│   │   ├── preparation.py         # 준비 단계
│   │   └── trading_loop.py        # 매매 루프 반복 단위
│   ├── psychology/                # 심리적 안전장치 (6개 파일)
│   │   ├── loss_tracker.py        # 손실 추적
│   │   ├── tilt_detector.py       # 틸트 탐지 (3손실/10분 OR -2%/30분)
│   │   └── tilt_enforcer.py       # 틸트 강제 1시간 거래 중단
│   ├── rag/                       # RAG 파이프라인 (5개 파일)
│   │   ├── embedder.py            # BGE-M3 임베딩
│   │   ├── retriever.py           # 벡터 검색
│   │   ├── doc_manager.py         # 문서 CRUD
│   │   └── doc_generator.py       # 문서 생성
│   ├── risk/                      # 리스크 관리 (22개 파일)
│   │   ├── risk_gate.py           # 7-Gate 리스크 파이프라인
│   │   ├── daily_loss_limit.py    # 일일 손실 한도
│   │   ├── concentration.py       # 집중도 한도
│   │   ├── sector_correlation.py  # 섹터 상관관계 Gate 5
│   │   ├── gap_risk.py            # 갭 리스크 보호
│   │   ├── friction/              # 마찰비용 (6개 파일)
│   │   │   ├── hurdle_calculator.py # 최소 수익 허들
│   │   │   ├── spread_cost.py
│   │   │   └── slippage_cost.py
│   │   └── house_money/           # 하우스 머니 (5개 파일)
│   │       ├── daily_pnl_tracker.py
│   │       └── multiplier_engine.py # 0.5x~2.0x 포지션 배율
│   ├── safety/                    # 시스템 안전장치 (9개 파일)
│   │   ├── hard_safety.py         # 포지션 한도 (15% per ticker)
│   │   ├── safety_checker.py      # 종합 안전 체크
│   │   ├── emergency_protocol.py  # 비상 프로토콜 (704줄)
│   │   ├── capital_guard.py       # 자본 보호
│   │   ├── account_safety.py      # 계정 안전
│   │   ├── quota_guard.py         # API 할당량 보호
│   │   ├── deadman_switch.py      # 데드맨 스위치 (cross-layer!)
│   │   └── macro_flash_crash.py   # 매크로 플래시 크래시 탐지
│   ├── scalping/                  # 스캘핑 엔진 (18개 파일)
│   │   ├── manager.py             # 스캘핑 매니저 (537줄)
│   │   ├── liquidity/             # 유동성 분석 (4개 파일)
│   │   │   ├── depth_analyzer.py
│   │   │   ├── impact_estimator.py
│   │   │   └── spread_monitor.py
│   │   ├── spoofing/              # 스푸핑 탐지 (4개 파일)
│   │   │   ├── pattern_detector.py
│   │   │   ├── snapshot_tracker.py
│   │   │   └── toxicity_scorer.py
│   │   └── time_stop/             # 시간 스탑 (4개 파일)
│   │       ├── evaluator.py
│   │       ├── executor.py
│   │       └── timer.py
│   ├── strategy/                  # 매매 전략 (40개 파일, 최대 규모)
│   │   ├── entry_strategy.py      # ★ 진입 전략 (1,450줄, 7-filter)
│   │   ├── exit_strategy.py       # ★ 청산 전략 (1,517줄)
│   │   ├── backtester.py          # ★ 백테스터 (1,324줄)
│   │   ├── etf_universe.py        # ETF 유니버스 정의 (888줄)
│   │   ├── params.py              # 전략 파라미터 로더
│   │   ├── ticker_params.py       # 티커별 파라미터 (673줄)
│   │   ├── profit_target.py       # 목표 수익 관리 (620줄)
│   │   ├── pyramiding.py          # 피라미딩 (632줄)
│   │   ├── sector_rotation.py     # 섹터 로테이션
│   │   ├── beast_mode/            # 비스트 모드 (6개 파일)
│   │   │   ├── detector.py        # A+ 셋업 탐지
│   │   │   ├── conviction_sizer.py # 2.5x~3.0x 포지션 증폭
│   │   │   └── beast_exit.py      # 비스트 전용 청산
│   │   ├── micro_regime/          # 마이크로 레짐 (5개 파일)
│   │   │   ├── regime_classifier.py
│   │   │   ├── trend_detector.py
│   │   │   └── volatility_analyzer.py
│   │   ├── news_fading/           # 뉴스 페이딩 (5개 파일)
│   │   │   ├── spike_detector.py  # >1%/60초 급등 탐지
│   │   │   ├── decay_analyzer.py
│   │   │   └── fade_signal_generator.py
│   │   ├── stat_arb/              # 통계적 차익거래 (6개 파일)
│   │   │   ├── pair_monitor.py    # 5쌍 페어 모니터
│   │   │   ├── spread_calculator.py # Z-Score
│   │   │   └── signal_generator.py
│   │   └── wick_catcher/          # 윅 캐처 (5개 파일)
│   │       ├── activation_checker.py # VPIN>0.7 + CVD<-0.6
│   │       ├── order_placer.py    # -2/-3/-4% 지정가
│   │       └── bounce_exit.py     # +2% 반등 청산
│   ├── tax/                       # 세금/환율 (4개 파일)
│   │   ├── tax_tracker.py         # 세금 계산
│   │   ├── fx_manager.py          # 환율 관리
│   │   └── slippage_tracker.py    # 슬리피지 추적
│   ├── telegram/                  # 텔레그램 봇 (7개 파일)
│   │   ├── bot_handler.py         # 봇 핸들러 (621줄)
│   │   ├── commands.py            # 명령어 처리
│   │   ├── formatters.py          # 메시지 포맷
│   │   ├── nl_processor.py        # 자연어 처리
│   │   └── trade_commands.py      # 매매 명령
│   ├── utils/                     # 유틸리티 (5개 파일)
│   │   ├── config.py              # 환경변수 설정 (pydantic-settings)
│   │   ├── logger.py              # 로거 팩토리
│   │   ├── market_hours.py        # 시장 시간 관리 (692줄)
│   │   └── ticker_mapping.py      # 티커-섹터 매핑
│   └── websocket/                 # KIS WebSocket 실시간 (22개 파일)
│       ├── manager.py             # WebSocket 연결 관리
│       ├── subscriber.py          # 구독 관리 (lazy import)
│       ├── parser.py              # 메시지 파싱
│       ├── crypto.py              # AES 암호화 (pycryptodome)
│       ├── handlers/              # 메시지 핸들러 (4개 파일)
│       │   ├── trade_handler.py   # 체결 핸들러
│       │   ├── orderbook_handler.py
│       │   └── notice_handler.py
│       ├── indicators/            # 실시간 지표 계산 (4개 파일)
│       │   ├── obi.py             # Order Book Imbalance
│       │   ├── vpin.py            # Volume-Synchronized PIN
│       │   ├── cvd.py             # Cumulative Volume Delta
│       │   └── execution_strength.py
│       └── storage/               # 데이터 저장 (3개 파일)
│           ├── tick_writer.py     # DB 기록 (lazy import)
│           └── redis_publisher.py # Redis 발행
│
├── dashboard/                     # Flutter 모바일 대시보드
│   └── lib/                       # (121개 파일, 46,868줄)
│       ├── main.dart
│       ├── app.dart
│       ├── screens/               # 화면 (28개 파일)
│       ├── providers/             # 상태 관리 (Provider)
│       ├── services/              # API 서비스
│       ├── models/                # 데이터 모델
│       ├── widgets/               # 재사용 위젯
│       ├── constants/             # 상수
│       ├── l10n/                  # 다국어
│       ├── theme/                 # 테마
│       └── utils/                 # 유틸리티
│
├── REFACTORING/                   # 리팩토링 문서
├── data/                          # 런타임 데이터
│   ├── kis_token.json             # KIS 토큰 (1일 1토큰)
│   ├── ticker_params.json         # 티커별 파라미터
│   └── trading_principles.json    # 매매 원칙
├── strategy_params.json           # 전략 파라미터 (40개 키)
├── requirements.txt               # Python 의존성
└── scripts/                       # 자동화 스크립트
```

---

## 4. 핵심 문제점 (리팩토링 사유)

### 4.1 God Object — `src/main.py` (3,255줄)

`TradingSystem` 클래스 하나가 시스템 전체를 담당하고 있다. 이는 SRP(단일 책임 원칙)의 명백한 위반이다.

**문제 지표:**

| 항목 | 수치 |
|---|---|
| 총 줄 수 | 3,255줄 |
| 최상위 import 구문 | 111개 |
| 인스턴스 변수 (`self.*`) | 약 65개 |
| `initialize()` 메서드 줄 수 | 496줄 (432~927번 줄) |
| 클래스 메서드 수 | 30개 이상 |

**`__init__`에 선언된 모듈 그룹 (모두 `None`으로 초기화):**
```
Infrastructure, KIS Broker, Account Mode, Crawling, Analysis,
RAG, Indicators, Strategy, Execution, Safety, Fallback,
Feedback, Monitoring, Tax/FX, Telegram, Local AI,
Phase 3~12 Advanced Modules (15개 선택적 모듈)
```

**핵심 문제:** `initialize()` 한 메서드 안에서 DB 초기화, Redis 연결, KIS 인증, 30개 이상의 모듈 인스턴스화와 DI(의존성 주입), 설정 로딩이 모두 이루어진다.

### 4.2 거대 파일 현황

#### 1000줄 초과 파일 (총 10개)

| 파일 | 줄 수 | 문제 |
|---|---|---|
| `src/main.py` | 3,255 | God Object, 모든 책임 집중 |
| `src/analysis/prompts.py` | 1,896 | 5개 시스템 프롬프트가 한 파일에 |
| `src/monitoring/dashboard_endpoints.py` | 1,840 | 모놀리식 엔드포인트 + cross-layer |
| `src/strategy/exit_strategy.py` | 1,517 | 과도하게 복잡한 청산 로직 |
| `src/strategy/entry_strategy.py` | 1,450 | 7개 필터 + 진입 로직이 한 파일 |
| `src/strategy/backtester.py` | 1,324 | 백테스트 + 그리드 서치 혼합 |
| `src/executor/kis_client.py` | 1,261 | KIS API 모든 호출 단일 파일 |
| `src/crawler/crawl_engine.py` | 1,099 | 크롤링 오케스트레이션 전체 |
| `src/monitoring/universe_endpoints.py` | 1,048 | 단일 기능에 너무 많은 줄 |
| `src/monitoring/analysis_endpoints.py` | 918 | 분석 API 모두 포함 |

#### 500줄 초과 파일 (총 39개)

200줄 초과: **159개** / 500줄 초과: **39개** / 1000줄 초과: **10개**

500줄 이상 주요 파일 (500~1000줄 구간):

| 파일 | 줄 수 |
|---|---|
| `src/strategy/etf_universe.py` | 888 |
| `src/monitoring/telegram_notifier.py` | 717 |
| `src/indicators/macd_divergence.py` | 713 |
| `src/safety/emergency_protocol.py` | 704 |
| `src/utils/market_hours.py` | 692 |
| `src/ai/knowledge_manager.py` | 691 |
| `src/db/models.py` | 675 |
| `src/monitoring/fred_client.py` | 674 |
| `src/strategy/ticker_params.py` | 673 |
| `src/crawler/naver_crawler.py` | 670 |
| `src/executor/order_manager.py` | 668 |
| `src/monitoring/api_server.py` | 666 |
| `src/monitoring/indicator_crawler.py` | 661 |
| `src/analysis/claude_client.py` | 649 |
| `src/strategy/pyramiding.py` | 632 |
| `src/analysis/classifier.py` | 623 |
| `src/telegram/bot_handler.py` | 621 |
| `src/strategy/profit_target.py` | 620 |
| `src/executor/position_monitor.py` | 588 |
| `src/macro/net_liquidity.py` | 575 |

### 4.3 계층 위반 (Cross-Layer Violations)

올바른 의존성 방향: `monitoring → strategy → executor → indicators → db`

현재 위반 사례:

#### 위반 1: executor → strategy (역방향)
```python
# src/executor/position_monitor.py (24번째 줄)
from src.strategy.exit_strategy import ExitStrategy
```
- executor 계층이 strategy 계층을 직접 import한다.
- position_monitor는 ExitStrategy를 직접 호출하여 청산 로직을 실행한다.

#### 위반 2: analysis → monitoring (상위 계층 참조)
```python
# src/analysis/decision_maker.py (160번째 줄, lazy import)
from src.monitoring.fred_client import fetch_cnn_fear_greed
```
- analysis 계층이 monitoring 계층의 FRED 클라이언트를 직접 가져온다.
- 본래 FRED 데이터 페칭은 독립 인프라 모듈이어야 한다.

#### 위반 3: monitoring → strategy (하향 참조)
```python
# src/monitoring/dashboard_endpoints.py (798번째 줄, lazy import)
from src.strategy.params import REGIMES

# src/monitoring/dashboard_endpoints.py (1529번째 줄, lazy import)
from src.strategy.backtester import StrategyBacktester
```
- 모니터링 엔드포인트가 전략 파라미터와 백테스터를 직접 참조한다.

#### 위반 4: safety → strategy (횡단 참조)
```python
# src/safety/deadman_switch.py (20번째 줄, lazy import)
from src.strategy.beast_mode.beast_exit import BeastExitManager
```
- 안전장치 모듈이 특정 전략 모듈(Beast Exit)에 강결합되어 있다.

### 4.4 Lazy Import 남발 (총 168개 인스턴스)

함수/메서드 내부에서 `from src.*`를 수행하는 lazy import가 168개 존재한다.
이는 순환 참조를 회피하려는 임시방편이며, 실제로는 아키텍처적 결합 문제를 숨기고 있다.

```python
# 대표적 사례들
# src/analysis/decision_maker.py:160
async def _get_fear_greed(self):
    from src.monitoring.fred_client import fetch_cnn_fear_greed  # 순환 회피

# src/analysis/classifier.py:407
async def save_to_db(self, ...):
    from src.db.connection import get_session  # DI 없이 직접 import
    from src.db.models import Article as ArticleModel

# src/monitoring/dashboard_endpoints.py:1529
async def run_backtest(...):
    from src.strategy.backtester import StrategyBacktester  # 지연 로딩
```

**lazy import가 집중된 파일:**

| 파일 | lazy import 수 |
|---|---|
| `src/analysis/classifier.py` | 5개 |
| `src/analysis/ticker_profiler.py` | 4개 |
| `src/monitoring/dashboard_endpoints.py` | 3개 |
| `src/optimization/time_travel.py` | 3개 |
| `src/websocket/storage/tick_writer.py` | 3개 |
| `src/telegram/bot_handler.py` | 3개 |

### 4.5 Flutter 대시보드 문제

#### 4.5.1 모놀리식 API 클라이언트
```
dashboard/lib/services/api_service.dart: 1,544줄
```
- 90개 이상의 API 호출 메서드가 단일 파일에 집중되어 있다.
- 기능별 분리 없이 모든 도메인(뉴스, 매매, 지표, 백테스트 등)이 혼합되어 있다.

#### 4.5.2 거대 화면 파일

| 파일 | 줄 수 |
|---|---|
| `screens/news_screen.dart` | 1,963 |
| `screens/overview_screen.dart` | 1,919 |
| `screens/universe_screen.dart` | 1,827 |
| `screens/home_dashboard.dart` | 1,754 |
| `screens/stock_analysis_screen.dart` | 1,719 |
| `screens/trade_reasoning_screen.dart` | 1,587 |
| `screens/rsi_screen.dart` | 1,429 |
| `screens/principles_screen.dart` | 1,223 |
| `screens/settings_screen.dart` | 1,046 |
| `screens/risk_center_screen.dart` | 1,032 |

28개 화면 파일 중 대부분이 1,000줄 이상이다. 각 화면이 UI, 비즈니스 로직, API 호출, 상태 관리를 모두 담당한다.

#### 4.5.3 모델 계층에 UI 코드 혼입 (계층 위반)

```dart
// dashboard/lib/models/news_models.dart (240번째 줄)
return const Color(0xFFDC2626); // red-600 → 모델에 UI 색상 하드코딩

// dashboard/lib/models/trade_reasoning_models.dart (187번째 줄)
Color confidenceColor(double confidence) { ... } // 모델 메서드가 Color 반환
```

모델 파일 4개(`news_models.dart`, `principles_models.dart`, `stock_analysis_models.dart`, `trade_reasoning_models.dart`)가 `flutter/material.dart`를 import하여 `Color` 객체를 반환한다. 이는 데이터 모델이 UI 프레임워크에 의존하는 명백한 계층 위반이다.

### 4.6 유령 의존성 (Ghost Dependencies)

#### 제거됐지만 requirements.txt에 남아있는 패키지
```
yfinance==0.2.51
```
- 코드베이스 전체에서 `import yfinance` 구문이 하나도 없다.
- PriceDataFetcher가 KIS API + FRED VIXCLS로 완전히 교체되었지만, requirements.txt에 계속 남아있다.

#### 코드에서 사용하지만 requirements.txt에 없는 패키지
```
pycryptodome
```
- `src/websocket/crypto.py`에서 `from Crypto.Cipher import AES`를 사용한다.
- KIS WebSocket 메시지 복호화에 필수적이지만, requirements.txt에 누락되어 있다.
- 신규 환경 설정 시 `pip install pycryptodome` 수동 설치가 필요하다.

### 4.7 설정 분산 문제

시스템 설정이 5개의 서로 다른 위치에 분산되어 있다:

| 위치 | 내용 | 파라미터 수 |
|---|---|---|
| `strategy_params.json` | 전략 파라미터 | 40개 |
| `data/ticker_params.json` | 티커별 개별 파라미터 | 가변 |
| `data/trading_principles.json` | 매매 원칙 (LLM 프롬프트 입력) | 가변 |
| `src/filter/filter_config.json` | 뉴스 필터 규칙 | 가변 |
| `.env` | 환경변수 (API 키, DB 연결 등) | 34개 |

`strategy_params.json`의 40개 파라미터 목록:
```
take_profit_pct, trailing_stop_pct, stop_loss_pct, eod_close,
min_confidence, max_position_pct, max_total_position_pct,
max_daily_trades, max_daily_loss_pct, max_hold_days,
vix_shutdown_threshold, scaled_exit_enabled, scaled_exit_ratios,
scaled_exit_levels, beast_mode_enabled, beast_min_confidence,
beast_min_obi, beast_conviction_multiplier, beast_max_position_pct,
beast_time_stop_seconds, beast_aggressive_trailing_pct,
beast_profit_threshold_pct, beast_max_daily_activations,
deadman_switch_enabled, deadman_stale_threshold_seconds,
macro_flash_crash_enabled, macro_crash_threshold_pct,
macro_crash_window_seconds, beast_danger_zone_open_minutes,
beast_danger_zone_close_minutes, beast_hard_stop_pct,
pyramiding_enabled, pyramid_max_levels, gap_risk_enabled,
contango_detection_enabled, sector_rotation_enabled,
nav_premium_enabled, net_liquidity_enabled,
net_liquidity_inject_multiplier, net_liquidity_drain_multiplier
```

또한, `main.py` 상단에 모듈 레벨 상수(magic number)가 다수 하드코딩되어 있다:
```python
_VIX_STRONG_BULL: float = 15.0
_VIX_MILD_BULL: float = 20.0
_VIX_SIDEWAYS: float = 25.0
_PRICE_HISTORY_DAYS: int = 200
_CONTINUOUS_ANALYSIS_INTERVAL: int = 30 * 60
```
이 값들이 `strategy_params.json`의 파라미터와 별도로 하드코딩되어 있어 혼란을 일으킨다.

---

## 5. 기술 스택

### 5.1 Python 패키지 (requirements.txt 기준)

| 패키지 | 버전 | 역할 |
|---|---|---|
| fastapi | 0.115.6 | REST API 서버 |
| uvicorn | 0.34.0 | ASGI 서버 |
| pydantic | 2.10.5 | 데이터 검증/직렬화 |
| pydantic-settings | 2.7.1 | 환경변수 설정 관리 |
| sqlalchemy | 2.0.36 | ORM (async 모드) |
| asyncpg | 0.30.0 | PostgreSQL 비동기 드라이버 |
| alembic | 1.14.1 | DB 마이그레이션 |
| psycopg2-binary | 2.9.10 | PostgreSQL 동기 드라이버 |
| redis | 5.2.1 | Redis 클라이언트 (async) |
| aiohttp | 3.11.11 | 비동기 HTTP 클라이언트 |
| httpx | 0.28.1 | 동기/비동기 HTTP 클라이언트 |
| anthropic | 0.42.0 | Claude API SDK |
| python-kis | 1.0.0 | 한국투자증권 API |
| pandas | 3.0.0 | 데이터 분석 |
| numpy | 2.2.6 | 수치 계산 |
| pandas-ta | 0.4.71b0 | 기술적 지표 |
| yfinance | 0.2.51 | ⚠️ 사용하지 않음 (유령 의존성) |
| sentence-transformers | 3.3.1 | 임베딩 모델 |
| FlagEmbedding | 1.3.3 | BGE-M3 임베딩 |
| feedparser | 6.0.11 | RSS 피드 파싱 |
| finvizfinance | 1.3.0 | Finviz 데이터 |
| beautifulsoup4 | 4.12.3 | HTML 스크래핑 |
| investiny | 0.7.0 | Investing.com 데이터 |
| python-dotenv | 1.0.1 | .env 파일 로딩 |
| apscheduler | 3.10.4 | 작업 스케줄러 |
| websockets | 14.1 | WebSocket 클라이언트 |
| praw | 7.8.1 | Reddit API |
| python-telegram-bot | 21.10 | 텔레그램 봇 |
| mlx-lm | 0.21.2 | Apple MLX LLM (Qwen3) |
| playwright | 1.49.0 | 브라우저 자동화 |
| chromadb | 0.6.3 | 벡터 DB |
| **pycryptodome** | (미등록) | ⚠️ 코드에서 사용하지만 requirements.txt 누락 |

### 5.2 Flutter 패키지 (pubspec.yaml)

| 패키지 | 버전 | 역할 |
|---|---|---|
| fl_chart | ^0.69.0 | 차트 라이브러리 |
| intl | ^0.19.0 | 국제화/날짜 포맷 |
| web_socket_channel | ^3.0.0 | WebSocket 클라이언트 |
| provider | ^6.1.0 | 상태 관리 |
| http | ^1.2.0 | HTTP 클라이언트 |
| google_fonts | ^6.2.0 | 구글 폰트 |
| shared_preferences | ^2.3.3 | 로컬 설정 저장 |

### 5.3 인프라

| 구성 요소 | 버전/상세 |
|---|---|
| **PostgreSQL** | 17 + pgvector 확장 |
| **Redis** | 7 (캐시, 실시간 데이터, 세션) |
| **Docker** | docker-compose (DB, Redis 컨테이너) |
| **macOS LaunchAgent** | 23:00 시작, 06:30 종료 자동 스케줄 |
| **Apple Silicon MPS** | MLX (Qwen3-30B-A3B 16GB 4bit) 호스트 직접 실행 |
| **ChromaDB** | 벡터 저장소 (RAG, 로컬 파일 기반) |

---

## 6. 요약 — 리팩토링 우선순위

| 우선순위 | 항목 | 영향도 |
|---|---|---|
| P0 | `main.py` God Object 분해 | 전체 시스템 유지보수성 |
| P0 | Cross-layer 의존성 제거 | 아키텍처 건전성 |
| P1 | Lazy import 168개 정리 | 순환 참조 근본 해결 |
| P1 | 1000줄+ 파일 10개 분리 | 코드 가독성/테스트 가능성 |
| P1 | 유령 의존성 수정 (yfinance 제거, pycryptodome 추가) | 신규 환경 설정 오류 방지 |
| P2 | Flutter 모델 계층 `Color` 참조 제거 | Flutter 계층 위반 해소 |
| P2 | Flutter `api_service.dart` 도메인별 분리 | 유지보수성 |
| P3 | 설정 파일 통합/정규화 | 설정 관리 단순화 |

---

*이 문서는 리팩토링 계획의 기준점이 된다. 변경 내용은 리팩토링 진행 문서에 별도로 기록한다.*
