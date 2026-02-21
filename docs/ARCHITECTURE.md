# 시스템 아키텍처

이 문서는 AI 자동매매 시스템 V2의 내부 아키텍처, 모듈 구성, 데이터 흐름을 설명한다.

---

## 목차

1. [전체 시스템 구조](#1-전체-시스템-구조)
2. [모듈 구성 (src/ 구조)](#2-모듈-구성)
3. [데이터 흐름](#3-데이터-흐름)
4. [안전장치 체인](#4-안전장치-체인)
5. [듀얼 인증 시스템](#5-듀얼-인증-시스템)
6. [데이터베이스 스키마](#6-데이터베이스-스키마)
7. [API 서버 구조](#7-api-서버-구조)
8. [매매 루프 타이밍](#8-매매-루프-타이밍)
9. [크롤링 파이프라인](#9-크롤링-파이프라인)
10. [AI 분석 파이프라인](#10-ai-분석-파이프라인)

---

## 1. 전체 시스템 구조

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           TradingSystem (src/main.py)                   │
│                          메인 오케스트레이터                              │
│                                                                         │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │Crawling │→│Classific.│→│ Analysis │→│ Decision │→│ Execution │ │
│  │(30+ src)│  │(MLX+AI)  │  │(Claude)  │  │(Opus)    │  │(KIS API)  │ │
│  └────┬────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬─────┘ │
│       │            │             │              │              │        │
│  ┌────┴────────────┴─────────────┴──────────────┴──────────────┘        │
│  │                                                                      │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐          │
│  │  │ Safety   │  │  Risk    │  │ Feedback │  │ Monitoring │          │
│  │  │ Chain    │  │ Pipeline │  │ Loop     │  │ (API+WS)   │          │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────────┘          │
│  │                                                                      │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐          │
│  │  │ RAG      │  │ Strategy │  │ Tax/FX   │  │ Telegram   │          │
│  │  │ Retriever│  │ Engine   │  │ Tracker  │  │ Bot        │          │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────────┘          │
│  │                                                                      │
│  └──────────────────────────────────────────────────────────────────────│
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  Infrastructure                                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐  │
│  │ PostgreSQL 17    │  │ Redis 7          │  │ ChromaDB (RAG)       │  │
│  │ + pgvector       │  │ (Cache/PubSub)   │  │ (Vector Store)       │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 모듈 구성

### src/ 디렉토리 구조

```
src/
├── main.py                    # TradingSystem 오케스트레이터 (~1600 라인)
│
├── analysis/                  # AI 분석 모듈
│   ├── claude_client.py       # Claude CLI/API 클라이언트 (로컬 SDK + HTTP API)
│   ├── classifier.py          # 뉴스 분류기 (영향도: HIGH/MEDIUM/LOW)
│   ├── decision_maker.py      # 최종 매매 결정 (Claude Opus)
│   ├── overnight_judge.py     # 오버나이트 보유 판단
│   ├── prompts.py             # 시스템 프롬프트 (MASTER_ANALYST 등)
│   ├── regime_detector.py     # 시장 레짐 판별 (VIX 기반)
│   └── ticker_profiler.py     # 종목 프로필 생성
│
├── ai/                        # 로컬 AI 모듈
│   ├── mlx_classifier.py      # MLX 로컬 분류기 (Qwen3-30B-A3B)
│   └── knowledge_manager.py   # 지식 관리 (ChromaDB + BGE-M3)
│
├── crawler/                   # 뉴스 크롤링 파이프라인
│   ├── crawl_engine.py        # 크롤링 엔진 (전체 소스 통합 관리)
│   ├── crawl_scheduler.py     # 스케줄러 (night/day 모드)
│   ├── crawl_verifier.py      # 크롤링 품질 검증
│   ├── base_crawler.py        # 크롤러 추상 베이스 클래스
│   ├── sources_config.py      # 소스별 설정
│   ├── dedup.py               # 중복 제거 (content_hash)
│   ├── rss_crawler.py         # RSS 피드 크롤러
│   ├── finnhub_crawler.py     # Finnhub API
│   ├── finviz_crawler.py      # Finviz 스크래핑
│   ├── fred_crawler.py        # FRED 경제 데이터
│   ├── alphavantage_crawler.py# AlphaVantage API
│   ├── reddit_crawler.py      # Reddit (PRAW)
│   ├── investing_crawler.py   # Investing.com
│   ├── naver_crawler.py       # 네이버 금융 뉴스
│   ├── sec_edgar_crawler.py   # SEC EDGAR 공시
│   ├── fear_greed_crawler.py  # CNN Fear & Greed 지수
│   ├── polymarket_crawler.py  # Polymarket 예측 시장
│   ├── kalshi_crawler.py      # Kalshi 예측 시장
│   ├── stocktwits_crawler.py  # StockTwits
│   ├── stocknow_crawler.py    # StockNow
│   ├── economic_calendar.py   # 경제 캘린더
│   └── ai_context_builder.py  # AI 분석용 컨텍스트 빌더
│
├── db/                        # 데이터베이스
│   ├── connection.py          # SQLAlchemy 비동기 세션 + Redis 커넥션
│   └── models.py              # 20개 ORM 모델
│
├── executor/                  # 주문 실행
│   ├── kis_auth.py            # KIS OpenAPI 인증 (토큰 관리)
│   ├── kis_client.py          # KIS API 클라이언트 (주문, 잔고, 시세)
│   ├── order_manager.py       # 주문 관리 (진입/청산 실행)
│   ├── position_monitor.py    # 포지션 모니터링 (손절/익절/트레일링)
│   ├── universe_manager.py    # ETF 유니버스 관리
│   └── forced_liquidator.py   # 강제 청산 (최대 보유일 초과)
│
├── safety/                    # 안전장치
│   ├── hard_safety.py         # 하드 리밋 (일일 최대 손실, VIX 서킷)
│   ├── safety_checker.py      # 종합 안전 검증
│   ├── emergency_protocol.py  # 긴급 프로토콜 (전량 매도)
│   ├── capital_guard.py       # 자본금 보호
│   ├── account_safety.py      # 계좌 안전 검증
│   └── quota_guard.py         # AI 호출 쿼터 관리
│
├── risk/                      # 리스크 관리
│   ├── risk_gate.py           # 6단계 리스크 게이트 파이프라인
│   ├── daily_loss_limit.py    # 일일 손실 한도
│   ├── concentration.py       # 포지션 집중도 제한
│   ├── losing_streak.py       # 연패 감지
│   ├── simple_var.py          # VaR (Value at Risk) 계산
│   ├── risk_budget.py         # 리스크 예산 관리
│   ├── stop_loss.py           # 트레일링 스탑 로스
│   └── risk_backtester.py     # 리스크 설정 백테스트
│
├── strategy/                  # 매매 전략
│   ├── params.py              # 전략 파라미터 (strategy_params.json)
│   ├── entry_strategy.py      # 진입 전략 엔진
│   ├── exit_strategy.py       # 청산 전략 엔진
│   ├── profit_target.py       # 월별 수익 목표 관리
│   └── etf_universe.py        # ETF 유니버스 정의
│
├── indicators/                # 기술적 지표
│   ├── calculator.py          # 지표 계산기 (RSI, MACD, BB 등)
│   ├── aggregator.py          # 지표 종합 스코어링
│   ├── data_fetcher.py        # 가격 데이터 조회 (KIS API)
│   ├── weights.py             # 지표별 가중치 관리
│   └── history_analyzer.py    # 과거 패턴 분석
│
├── rag/                       # RAG (검색 증강 생성)
│   ├── embedder.py            # BGE-M3 임베딩 생성
│   ├── retriever.py           # 벡터 검색 + pgvector
│   └── doc_generator.py       # RAG 문서 자동 생성
│
├── feedback/                  # 피드백 루프
│   ├── daily_feedback.py      # 일일 성과 분석 (Claude)
│   ├── weekly_analysis.py     # 주간 종합 분석
│   ├── param_adjuster.py      # 파라미터 자동 조정 제안
│   └── rag_doc_updater.py     # RAG 문서 자동 갱신
│
├── fallback/                  # 폴백 라우터
│   └── fallback_router.py     # AI 장애 시 규칙 기반 매매
│
├── tax/                       # 세금/환율
│   ├── tax_tracker.py         # 양도소득세 계산 (USD+KRW)
│   ├── fx_manager.py          # 환율 관리 (KIS API, 1시간 주기 갱신)
│   └── slippage_tracker.py    # 슬리피지 추적
│
├── monitoring/                # API 서버 + 엔드포인트
│   ├── api_server.py          # FastAPI 앱 (미들웨어, WebSocket, 의존성 주입)
│   ├── dashboard_endpoints.py # 대시보드 API (40+ 엔드포인트)
│   ├── analysis_endpoints.py  # 종합 분석 API
│   ├── indicator_endpoints.py # 지표 API (RSI, 가중치)
│   ├── macro_endpoints.py     # 매크로 지표 API (VIX, CPI, 금리)
│   ├── news_endpoints.py      # 뉴스 API
│   ├── trade_endpoints.py     # 피드백/조정 API
│   ├── trade_reasoning_endpoints.py  # 매매 추론 API
│   ├── principles_endpoints.py       # 매매 원칙 CRUD
│   ├── universe_endpoints.py  # 유니버스 관리 + 크롤링 API
│   ├── benchmark_endpoints.py # 벤치마크 비교 API
│   ├── emergency_endpoints.py # 긴급 프로토콜 + 리스크 API
│   ├── system_endpoints.py    # 시스템 상태 API
│   ├── agent_endpoints.py     # 에이전트 관리 API
│   ├── alert.py               # 알림 관리자
│   ├── benchmark.py           # 벤치마크 비교 로직
│   ├── telegram_notifier.py   # 텔레그램 알림 발송
│   └── schemas.py             # Pydantic 스키마
│
├── orchestration/             # 오케스트레이션 (매매 루프 분리)
│   ├── __init__.py
│   ├── preparation.py         # Pre-market 준비 단계
│   └── continuous_analysis.py # 30분 단위 연속 분석
│
├── telegram/                  # 텔레그램 양방향 봇
│   ├── bot_handler.py         # 봇 핸들러 (polling 기반)
│   ├── commands.py            # 일반 명령어 (/status, /report 등)
│   └── trade_commands.py      # 매매 명령어 (/buy, /sell 등)
│
└── utils/                     # 공통 유틸리티
    ├── config.py              # Pydantic Settings (환경 변수)
    ├── logger.py              # 로거 설정 (get_logger)
    ├── market_hours.py        # 미국 시장 시간 관리 (정규장, 서머타임)
    └── ticker_mapping.py      # 본주-레버리지 ETF 매핑 (17쌍)
```

---

## 3. 데이터 흐름

### 매매 사이클 (15분 주기)

```
[1] 크롤링 (Delta)
    │
    ├── 30개 뉴스 소스에서 신규 기사 수집
    ├── content_hash 기반 중복 제거
    └── DB(articles)에 저장
    │
    ▼
[2] 분류 (Classification)
    │
    ├── MLX 로컬 모델로 사전 분류 (빠른 필터링)
    ├── Claude AI로 정밀 분류 (영향도: HIGH/MEDIUM/LOW)
    ├── 티커 매칭, 감성 점수 부여
    └── 한국어 번역 + 요약 생성
    │
    ▼
[3] 분석 (Analysis)
    │
    ├── 기술적 지표 계산 (RSI, MACD, BB, MA)
    ├── 매크로 지표 조회 (VIX, Fear&Greed, CPI, 금리)
    ├── 시장 레짐 판별 (strong_bull ~ crash, VIX 기반)
    ├── RAG 검색 (유사 과거 패턴)
    └── Claude Opus 종합 분석
    │
    ▼
[4] 판단 (Decision)
    │
    ├── Claude Opus가 매매 결정 생성
    │   ├── action: buy / sell / hold
    │   ├── ticker: 대상 종목
    │   ├── confidence: 신뢰도 (0.0~1.0)
    │   └── reason: 판단 근거
    │
    ├── 리스크 게이트 검증 (6단계)
    └── 안전장치 체인 검증
    │
    ▼
[5] 실행 (Execution)
    │
    ├── 진입 전략: 포지션 사이즈, 진입가 결정
    ├── KIS API 주문 실행
    ├── 세금/환율/슬리피지 기록
    └── Telegram 알림 발송
    │
    ▼
[6] 모니터링 (Monitor)
    │
    ├── 포지션 실시간 감시
    ├── 손절/익절/트레일링 스탑 체크
    ├── WebSocket으로 대시보드에 푸시
    └── 15분 후 [1]로 돌아간다
```

### Pre-market 준비 단계 (23:00 KST)

```
[1] 인프라 상태 확인 (DB, Redis, KIS API, Docker)
         │
         ▼
[2] 전체 크롤링 (Full Crawl)
    │   30개 소스에서 신규 기사 수집
    │
    ▼
[3] 뉴스 분류 (Classify)
    │   HIGH 영향 뉴스 식별
    │
    ▼
[4] Pre-market 분석
    │   ├── [4-1] HIGH 뉴스 텔레그램 전송
    │   ├── [4-2] 시장 레짐 판별
    │   ├── [4-3] 안전 체크 (서킷브레이커, VIX)
    │   └── [4-4] RAG 문서 갱신
    │
    ▼
[5] 시스템 준비 완료 → 매매 루프 진입 대기
```

### EOD 정리 단계 (장 마감 후)

```
[1] Overnight 판단 (보유 포지션 홀드/매도 결정)
         │
         ▼
[2] Daily Feedback (일일 성과 분석, Claude)
         │
         ▼
[3] 벤치마크 스냅샷 기록 (AI vs SPY vs SSO)
         │
         ▼
[4] Telegram 일일 종합 보고서 발송
         │
         ▼
[5] 수익 목표 업데이트 (월별 PnL + 공격성 조정)
         │
         ▼
[6] 리스크 예산 업데이트
         │
         ▼
[7] 일일 리스크 카운터 리셋
         │
         ▼
[8] 강제 청산 체크 (보유일 초과 포지션)
         │
         ▼
[9] 실전전환 준비도 체크 (7가지 기준)
```

---

## 4. 안전장치 체인

매매 주문이 실행되기 전에 다단계 안전 검증을 거친다.

```
주문 요청
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ [Gate 1] HardSafety                                  │
│  - 일일 최대 손실 제한 (-5%)                           │
│  - VIX 서킷브레이커 (VIX > 35 시 매매 중단)            │
│  - 최대 포지션 비율 제한 (15%/종목, 80%/전체)          │
│  - 일일 최대 매매 횟수 (30건)                          │
│  통과 실패 시 주문 거부                                │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│ [Gate 2] SafetyChecker                               │
│  - HardSafety + QuotaGuard 통합 검증                  │
│  - AI 호출 쿼터 확인                                   │
│  통과 실패 시 주문 거부                                │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│ [Gate 3] RiskGatePipeline (6단계)                     │
│                                                      │
│  [3-1] DailyLossLimiter: 일일 누적 손실 한도          │
│  [3-2] ConcentrationLimiter: 종목 집중도 제한         │
│  [3-3] LosingStreakDetector: 연패 감지 (N연패 시 쿨다운)│
│  [3-4] SimpleVaR: Value at Risk 한도 초과 검사        │
│  [3-5] RiskBudget: 리스크 예산 잔여량 확인             │
│  [3-6] TrailingStopLoss: 트레일링 손절 규칙            │
│                                                      │
│  하나라도 실패 시 주문 거부 + 사유 기록                  │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│ [Gate 4] EmergencyProtocol                           │
│  - 긴급 정지 상태 확인                                 │
│  - 긴급 정지 시 모든 매수 주문 거부                     │
│  통과 실패 시 주문 거부                                │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│ [Gate 5] CapitalGuard                                │
│  - 계좌 잔고 검증                                     │
│  - 주문 유효성 검증 (수량, 금액)                       │
│  - 3중 안전 검증 (safety_3set)                        │
│  통과 실패 시 주문 거부                                │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
        주문 실행 (KIS API)
```

---

## 5. 듀얼 인증 시스템

KIS OpenAPI는 모의투자와 실전투자가 별도 서버를 사용한다.

```
┌─────────────────────────────────────────────────────┐
│                    KISClient                         │
│                                                     │
│  ┌──────────────────┐  ┌──────────────────────────┐ │
│  │ Trading Auth     │  │ Real Auth (Price)        │ │
│  │ (모의/실전)       │  │ (시세 조회 전용)          │ │
│  │                  │  │                          │ │
│  │ 주문 실행:       │  │ 시세 조회:               │ │
│  │  - 매수/매도     │  │  - 현재가 조회            │ │
│  │  - 잔고 조회     │  │  - 일봉 데이터 (100일)   │ │
│  │  - 포지션 조회   │  │  - 환율 조회             │ │
│  │                  │  │  - VIX (FRED VIXCLS)     │ │
│  │ 모의: V prefix   │  │                          │ │
│  │ 실전: 일반 ID    │  │ 항상 실전 서버 사용       │ │
│  └──────────────────┘  └──────────────────────────┘ │
│                                                     │
│  토큰 캐시:                                          │
│  - data/kis_token.json       (매매용)                │
│  - data/kis_real_token.json  (시세 조회용)            │
│  - 24시간 유효, 1일 1회 발급                          │
└─────────────────────────────────────────────────────┘
```

### 주요 규칙

- 모의투자 서버에는 시세 API가 없다. 시세 조회는 항상 실전 서버를 사용한다.
- 시세 조회 TR_ID는 모의/실전 구분 없이 동일하다 (V prefix 불필요).
- 매매 TR_ID만 모의투자 시 V prefix를 붙인다.
- 모의투자에서 시장가 주문(order_type=01)이 불가능하다. 자동으로 지정가(현재가 +-0.5%)로 변환한다.

---

## 6. 데이터베이스 스키마

### ER 다이어그램 (핵심 테이블)

```
┌──────────────────┐      ┌──────────────────┐
│   etf_universe   │      │     articles     │
│──────────────────│      │──────────────────│
│ ticker (PK)      │      │ id (PK, UUID)    │
│ name             │      │ source           │
│ direction        │      │ headline         │
│ leverage         │      │ content          │
│ underlying       │      │ published_at     │
│ enabled          │      │ classification   │
│ avg_daily_volume │      │ sentiment_score  │
└──────────────────┘      │ headline_kr      │
                          │ summary_ko       │
┌──────────────────┐      │ companies_impact │
│     trades       │      └──────────────────┘
│──────────────────│
│ id (PK, UUID)    │      ┌──────────────────┐
│ ticker           │──────│  tax_records     │
│ direction        │      │──────────────────│
│ entry_price      │      │ trade_id (FK)    │
│ exit_price       │      │ realized_gain_usd│
│ entry_at         │      │ fx_rate_at_trade │
│ exit_at          │      │ realized_gain_krw│
│ pnl_pct          │      └──────────────────┘
│ pnl_amount       │
│ ai_confidence    │──────┌──────────────────┐
│ market_regime    │      │  slippage_log    │
│ exit_reason      │      │──────────────────│
└──────────────────┘      │ trade_id (FK)    │
                          │ expected_price   │
┌──────────────────┐      │ actual_price     │
│  rag_documents   │      │ slippage_pct     │
│──────────────────│      └──────────────────┘
│ id (PK, UUID)    │
│ doc_type         │      ┌──────────────────┐
│ ticker           │      │ benchmark_       │
│ title            │      │ snapshots        │
│ content          │      │──────────────────│
│ embedding (1024) │      │ date             │
│ relevance_score  │      │ ai_return_pct    │
└──────────────────┘      │ spy_buyhold_pct  │
                          │ sso_buyhold_pct  │
┌──────────────────┐      └──────────────────┘
│ profit_targets   │
│──────────────────│      ┌──────────────────┐
│ month            │      │ risk_events      │
│ target_usd       │      │──────────────────│
│ realized_pnl     │      │ event_type       │
│ aggression       │      │ gate_name        │
└──────────────────┘      │ severity         │
                          │ details (JSONB)  │
                          └──────────────────┘
```

### 전체 테이블 목록 (20개)

| 테이블 | PK 타입 | 설명 |
|--------|---------|------|
| `rag_documents` | UUID | RAG 벡터 문서 (1024차원 임베딩) |
| `etf_universe` | String | ETF 유니버스 (티커가 PK) |
| `trades` | UUID | 매매 기록 |
| `indicator_history` | BigInt | 기술적 지표 이력 |
| `strategy_param_history` | BigInt | 전략 파라미터 변경 이력 |
| `feedback_reports` | UUID | 피드백 리포트 |
| `crawl_checkpoints` | Int | 크롤링 체크포인트 |
| `articles` | UUID | 뉴스 기사 |
| `pending_adjustments` | UUID | 대기 중인 파라미터 조정 |
| `tax_records` | UUID | 세금 기록 (trades FK) |
| `fx_rates` | BigInt | 환율 이력 |
| `slippage_log` | UUID | 슬리피지 기록 (trades FK) |
| `emergency_events` | UUID | 긴급 이벤트 |
| `benchmark_snapshots` | UUID | 벤치마크 스냅샷 |
| `capital_guard_log` | UUID | 자본금 보호 로그 |
| `notification_log` | UUID | 알림 발송 이력 |
| `profit_targets` | BigInt | 월별 수익 목표 |
| `daily_pnl_log` | BigInt | 일별 손익 |
| `risk_config` | BigInt | 리스크 설정 |
| `risk_events` | BigInt | 리스크 이벤트 |
| `backtest_results` | BigInt | 백테스트 결과 |
| `crawl_data` | BigInt | 크롤링 원시 데이터 |
| `fear_greed_history` | BigInt | Fear & Greed 지수 이력 |
| `prediction_markets` | BigInt | 예측 시장 데이터 |

### 핵심 인덱스

- `articles`: `(source, crawled_at)`, `published_at`, `content_hash` (UNIQUE)
- `trades`: `ticker`, `entry_at`, `created_at`
- `rag_documents`: `doc_type`, `ticker` + pgvector HNSW 인덱스
- `indicator_history`: `(ticker, indicator_name, recorded_at)` 복합 인덱스

---

## 7. API 서버 구조

### 의존성 주입 패턴

```
TradingSystem.initialize()
    │
    ▼
set_dependencies(
    position_monitor, universe_manager, weights_manager,
    strategy_params, safety_checker, crawl_engine,
    kis_client, claude_client, classifier,
    emergency_protocol, capital_guard, ...
)
    │
    ▼
각 라우터 모듈에 필요한 의존성 전달:
    set_analysis_deps()
    set_indicator_deps()
    set_benchmark_deps()
    set_dashboard_deps()
    set_universe_deps()
    set_emergency_deps()
    set_trade_deps()
    set_macro_deps()
```

### 라우터 구성

```
FastAPI App (api_server.py)
    │
    ├── dashboard_router    → /dashboard/*, /strategy/*, /alerts/*,
    │                         /tax/*, /fx/*, /slippage/*, /reports/*
    ├── analysis_router     → /api/analysis/*
    ├── indicator_router    → /indicators/*, /api/indicators/*
    ├── macro_router        → /api/macro/*
    ├── news_router         → /api/news/*
    ├── trade_router        → /feedback/*
    ├── trade_reasoning_router → /api/trade-reasoning/*
    ├── principles_router   → /api/principles/*
    ├── universe_router     → /universe/*, /crawl/*
    ├── benchmark_router    → /benchmark/*, /api/target/*
    ├── emergency_router    → /emergency/*, /api/risk/*
    ├── system_router       → /system/*
    ├── agent_router        → /agents/*
    │
    └── WebSocket endpoints:
        /ws/positions       → 실시간 포지션 (2초 주기)
        /ws/trades          → 매매 알림 (Redis Pub/Sub)
        /ws/crawl/{task_id} → 크롤링 진행 상황
        /ws/alerts          → 전체 알림 스트림
```

### 미들웨어

1. **CORS**: 모든 origin 허용 (Flutter 대시보드 접근용)
2. **Cache-Control**: `no-store` (금융 데이터 캐싱 방지)
3. **Request Logging**: 요청/응답 시간 기록

### 인증

- REST API: `API_SECRET_KEY` 환경변수 기반 Bearer 토큰 (미설정 시 인증 비활성화)
- WebSocket: `?token=<API_SECRET_KEY>` 쿼리 파라미터

---

## 8. 매매 루프 타이밍

### 일일 스케줄 (KST 기준)

```
시간(KST)    이벤트
─────────────────────────────────────────────
23:00        LaunchAgent 시작
             Pre-market 준비 단계 실행
             전체 크롤링 + 분류 + 분석
             연속 분석 시작 (30분 주기)
             │
23:30~       연속 크롤링 분석 (30분 주기)
             시장 변화 추적 + 텔레그램 알림
             │
00:00        정규장 시작 (서머타임: 23:30)
(or 23:30)   15분 매매 루프 진입
             │
00:15        [루프] 델타 크롤링 → 분석 → 판단 → 실행
00:30        [루프]
00:45        [루프]
...          (15분 주기 반복)
             │
06:00        정규장 종료 (서머타임: 05:00)
(or 05:00)   EOD 정리 단계 실행
             Overnight 판단 + Daily Feedback
             텔레그램 일일 보고서
             │
06:30        LaunchAgent 종료
─────────────────────────────────────────────

일요일:       주간 분석 실행 (WeeklyAnalysis)
```

### 타이밍 상수

| 상수 | 값 | 설명 |
|------|-----|------|
| `_TRADING_LOOP_SLEEP` | 15분 | 정규 매매 루프 주기 |
| `_MONITOR_ONLY_SLEEP` | 5분 | 비정규 세션 모니터링 주기 |
| `_CONTINUOUS_ANALYSIS_INTERVAL` | 30분 | 연속 분석 주기 |
| `_PREP_CHECK_INTERVAL` | 1시간 | 준비 단계 재확인 간격 |
| `_REGIME_CACHE_TTL` | 5분 | Redis 레짐 캐시 TTL |

---

## 9. 크롤링 파이프라인

### 소스 목록 (30개 이상)

```
┌─────────────────────────────────────────────────────────────┐
│                    CrawlEngine                               │
│                                                             │
│  RSS Feeds:                                                 │
│    Reuters, AP, Bloomberg, CNBC, MarketWatch,               │
│    WSJ, TechCrunch, The Verge 등                           │
│                                                             │
│  API 기반:                                                  │
│    Finnhub (뉴스 + 시장 데이터)                              │
│    AlphaVantage (시장 뉴스)                                  │
│    FRED (VIX, CPI, 금리 등 매크로)                           │
│    Reddit (r/wallstreetbets, r/investing 등)                │
│                                                             │
│  스크래핑:                                                   │
│    Finviz (종목 스크리너 + 뉴스)                              │
│    Investing.com (경제 캘린더 + 뉴스)                         │
│    StockNow (실시간 뉴스)                                    │
│    Naver 금융 (한국 관점 뉴스)                                │
│    SEC EDGAR (공시 데이터)                                    │
│    CNN Fear & Greed (심리 지수)                              │
│                                                             │
│  예측 시장:                                                  │
│    Polymarket (정치/경제 예측)                                │
│    Kalshi (이벤트 예측)                                      │
│                                                             │
│  소셜:                                                      │
│    StockTwits (투자자 심리)                                   │
│    Reddit (커뮤니티 분석)                                     │
└─────────────────────────────────────────────────────────────┘
```

### 크롤링 모드

- **Full Crawl**: Pre-market 준비 시 전체 소스 크롤링 (23:00 KST)
- **Delta Crawl**: 매매 루프 중 신규 기사만 수집 (15분 주기)
- **Manual Crawl**: 대시보드에서 수동 크롤링 실행

### 중복 제거

`content_hash` (SHA-256) 기반으로 동일 기사의 중복 저장을 방지한다. `articles` 테이블의 `content_hash` 컬럼에 UNIQUE 제약이 걸려 있다.

---

## 10. AI 분석 파이프라인

### 2단계 분류 시스템

```
[Stage 1] MLX 로컬 분류 (빠른 필터링)
    │
    │  Qwen3-30B-A3B (Apple Silicon MPS)
    │  - 영향도 사전 분류 (0.5초/건)
    │  - LOW 영향 뉴스 필터링
    │
    ▼
[Stage 2] Claude AI 정밀 분류
    │
    │  Claude Sonnet/Opus
    │  - HIGH/MEDIUM 영향도 최종 판정
    │  - 관련 티커 매칭
    │  - 감성 점수 (-1.0 ~ +1.0)
    │  - 한국어 번역 + 요약
    │
    ▼
분류 완료 → DecisionMaker에 전달
```

### 시스템 프롬프트 (4개 역할)

| 프롬프트 | 역할 |
|----------|------|
| `MASTER_ANALYST` | 종합 분석 + 매매 판단 (메인) |
| `NEWS_ANALYST` | 뉴스 분류 + 영향도 평가 |
| `RISK_MANAGER` | 리스크 평가 + 포지션 사이징 |
| `MACRO_STRATEGIST` | 매크로 환경 분석 + 레짐 판단 |

### Survival Trading

시스템 운영비($300/월)를 반드시 수익으로 충당해야 한다는 원칙이 `MASTER_ANALYST` 프롬프트와 `strategy_params.json`에 내장되어 있다.

```json
{
  "survival_trading": {
    "monthly_cost_usd": 300,
    "monthly_target_usd": 500,
    "enabled": true
  }
}
```

### RAG (검색 증강 생성)

과거 매매 패턴과 시장 분석 결과를 벡터 데이터베이스에 저장하고, AI 분석 시 유사한 과거 사례를 검색하여 컨텍스트로 제공한다.

```
BGE-M3 임베딩 (1024차원)
    │
    ▼
pgvector (PostgreSQL) + ChromaDB (로컬)
    │
    ▼
RAGRetriever: 유사도 기반 Top-K 검색
    │
    ▼
DecisionMaker에 과거 사례 컨텍스트 주입
```

### VIX 기반 시장 레짐

| 레짐 | VIX 범위 | 매매 행동 |
|------|----------|----------|
| `strong_bull` | < 15 | 공격적 매수, 높은 포지션 비율 |
| `mild_bull` | 15~20 | 정상 매수, 표준 포지션 |
| `sideways` | 20~25 | 보수적 매수, 작은 포지션 |
| `mild_bear` | 25~30 | 최소 매수, 방어적 운영 |
| `crash` | > 30 | 매수 중단, 기존 포지션 축소 |

VIX가 35를 초과하면 서킷브레이커가 작동하여 모든 신규 매매를 중단한다.
