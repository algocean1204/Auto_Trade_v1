# AI 자동매매 시스템 V2

미국 2배 레버리지 ETF (SOXL, QLD, TSLL 등) AI 자동매매 시스템이다.

Claude AI가 30개 이상의 뉴스 소스를 분석하고, 기술적 지표와 매크로 경제 데이터를 종합하여 매매 의사결정을 내린다. 한국투자증권(KIS) OpenAPI를 통해 실제 주문을 실행하며, macOS LaunchAgent를 활용하여 매일 23:00~06:30 KST 야간 자동매매를 수행한다.

---

## 주요 기능

### AI 매매 의사결정
- Claude Opus/Sonnet 기반 종합 분석 (뉴스, 지표, 레짐 판단)
- Claude CLI (로컬 SDK) 또는 Anthropic API 모드 선택 가능
- 로컬 MLX 모델 (Qwen3-30B-A3B)로 뉴스 사전 분류
- RAG (Retrieval-Augmented Generation) 기반 과거 매매 패턴 학습
- 30분 단위 연속 시장 분석 (23:00~06:30 KST)

### 뉴스 크롤링 및 분류
- 30개 이상 뉴스 소스 자동 크롤링 (RSS, API, 스크래핑)
- Finnhub, AlphaVantage, FRED, Reddit, Investing.com, SEC Edgar 등
- 뉴스 영향도 자동 분류 (HIGH/MEDIUM/LOW)
- 한국어 번역 및 요약 자동 생성

### 기술적 지표 분석
- Triple RSI (7/14/21) + Signal Line (9)
- MACD, 볼린저밴드, 이동평균선
- 본주(underlying) 데이터 기반 레버리지 ETF 분석
- 17개 본주-레버리지 ETF 매핑 지원

### 매매 실행
- KIS OpenAPI 연동 (한국투자증권)
- 모의투자/실전투자 듀얼 모드 지원
- 진입/청산 전략 엔진
- 강제 청산 (최대 보유일 초과 시)

### 안전장치 체인
- HardSafety: 하드 리밋 (일일 최대 손실, VIX 서킷브레이커)
- SafetyChecker: 종합 안전 검증
- EmergencyProtocol: 긴급 프로토콜 (전량 매도)
- CapitalGuard: 자본금 보호 (잔고 검증, 주문 유효성)
- RiskGatePipeline: 6단계 리스크 게이트 (일일손실, 집중도, 연패, VaR, 예산, 트레일링)

### 모니터링 및 알림
- Flutter 대시보드 (macOS)
- Telegram 양방향 봇 (알림 수신 + 명령어 실행)
- 50개 이상 REST API 엔드포인트
- WebSocket 실시간 스트리밍 (포지션, 매매, 크롤링 진행, 알림)

### 데이터 관리
- PostgreSQL 17 + pgvector (벡터 검색)
- Redis 7 (캐싱, Pub/Sub, 세션 관리)
- 20개 ORM 모델 (매매, 뉴스, 지표, 세금, 리스크 등)

---

## 시스템 요구사항

| 항목 | 요구사항 |
|------|----------|
| OS | macOS (Apple Silicon 권장, M1 이상) |
| Python | 3.12+ |
| Flutter | 3.x+ (대시보드용) |
| Docker | Docker Desktop (PostgreSQL, Redis 컨테이너) |
| Claude CLI | Anthropic Claude Code CLI (Max/Pro 구독 필요) |
| Node.js | 최신 LTS (Claude CLI 의존) |
| RAM | 16GB 이상 (로컬 MLX 모델 사용 시 32GB+ 권장) |

---

## 아키텍처 개요

```
┌──────────────────────────────────────────────────────────────────┐
│                        Host (macOS)                              │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │  Claude CLI  │  │  API Server  │  │   Flutter Dashboard    │  │
│  │  (AI 분석)   │  │  (FastAPI)   │  │   (macOS Desktop)      │  │
│  │  port: N/A   │  │  port: 9500  │  │   port: 자동 할당       │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬─────────────┘  │
│         │                 │                      │                │
│  ┌──────┴─────────────────┴──────────────────────┘                │
│  │                                                                │
│  │  ┌──────────────────┐  ┌──────────────────┐                   │
│  │  │  MLX Classifier  │  │  Telegram Bot    │                   │
│  │  │  (로컬 AI 분류)   │  │  (양방향 봇)     │                   │
│  │  └──────────────────┘  └──────────────────┘                   │
│  │                                                                │
│  └────────────────────────────────────────────────────────────────│
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│                     Docker Compose                               │
│                                                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐               │
│  │  PostgreSQL 17       │  │  Redis 7             │               │
│  │  + pgvector          │  │  (AOF 영속화)         │               │
│  │  port: 5432          │  │  port: 6379           │               │
│  └─────────────────────┘  └─────────────────────┘               │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

                    ┌──────────────────┐
                    │   외부 서비스      │
                    │                  │
                    │  KIS OpenAPI     │
                    │  Finnhub API     │
                    │  FRED API        │
                    │  AlphaVantage    │
                    │  Telegram API    │
                    │  RSS Feeds       │
                    │  Claude API      │
                    └──────────────────┘
```

---

## 빠른 시작

### 1. 저장소 클론

```bash
git clone <repository-url>
cd Stock_Trading
```

### 2. 환경 변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 필수 값을 입력한다
```

필수 환경 변수:
- `KIS_REAL_APP_KEY`, `KIS_REAL_APP_SECRET`: KIS 실전투자 인증키
- `KIS_VIRTUAL_APP_KEY`, `KIS_VIRTUAL_APP_SECRET`: KIS 모의투자 인증키
- `KIS_REAL_ACCOUNT`, `KIS_VIRTUAL_ACCOUNT`: 계좌번호 (XXXXXXXX-XX 형식)
- `DB_PASSWORD`: PostgreSQL 비밀번호

상세 설정 가이드는 [SETUP.md](./SETUP.md)를 참고한다.

### 3. Docker 시작 (DB + Redis)

```bash
docker compose up -d
```

### 4. Python 가상환경 및 의존성 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. DB 마이그레이션

```bash
# 초기 스키마는 Docker 시작 시 db/init.sql로 자동 생성된다
# Alembic 마이그레이션 적용 (추가 스키마 변경이 있는 경우):
alembic upgrade head
```

### 6. API 서버 시작

```bash
# 방법 1: 전체 시스템 시작 (API 서버 + 매매 루프)
python -m src.main

# 방법 2: API 서버만 단독 실행
uvicorn src.monitoring.api_server:app --host 0.0.0.0 --port 9500
```

### 7. Flutter 대시보드 실행

```bash
cd dashboard
flutter pub get
flutter run -d macos
```

---

## API 엔드포인트 목록

API 서버는 기본적으로 `http://localhost:9500`에서 실행된다.

### 헬스체크

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 확인 |

### 대시보드 (Dashboard)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/dashboard/accounts` | 계좌 정보 (실전/모의 듀얼 모드) |
| GET | `/dashboard/summary` | 대시보드 요약 (잔고, 포지션, 수익) |
| GET | `/dashboard/positions` | 현재 보유 포지션 목록 |
| GET | `/dashboard/trades/recent` | 최근 매매 내역 |
| GET | `/dashboard/charts/daily-returns` | 일별 수익률 차트 데이터 |
| GET | `/dashboard/charts/cumulative` | 누적 수익률 차트 데이터 |
| GET | `/dashboard/charts/heatmap/ticker` | 종목별 히트맵 데이터 |
| GET | `/dashboard/charts/heatmap/hourly` | 시간대별 히트맵 데이터 |
| GET | `/dashboard/charts/drawdown` | 드로다운 차트 데이터 |

### 전략 설정 (Strategy)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/strategy/params` | 현재 전략 파라미터 조회 |
| POST | `/strategy/params` | 전략 파라미터 수정 |

### 알림 (Alerts)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/alerts` | 알림 목록 조회 |
| GET | `/alerts/unread-count` | 읽지 않은 알림 수 |
| POST | `/alerts/{alert_id}/read` | 알림 읽음 처리 |

### 세금/환율 (Tax/FX)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/tax/status` | 세금 현황 (연간 손익, 과세 대상) |
| GET | `/tax/report/{year}` | 연도별 세금 리포트 |
| GET | `/tax/harvest-suggestions` | 세금 절감 제안 |
| GET | `/fx/status` | 현재 환율 정보 |
| GET | `/fx/effective-return/{trade_id}` | 환율 반영 실효 수익률 |
| GET | `/fx/history` | 환율 이력 |

### 슬리피지 (Slippage)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/slippage/stats` | 슬리피지 통계 |
| GET | `/slippage/optimal-hours` | 최적 매매 시간대 |

### 리포트 (Reports)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/reports/daily` | 최신 일일 보고서 |
| GET | `/reports/daily/list` | 일일 보고서 목록 |

### 피드백 (Feedback)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/feedback/daily/{date_str}` | 일별 피드백 리포트 |
| GET | `/feedback/weekly/{week_str}` | 주간 피드백 리포트 |
| GET | `/feedback/pending-adjustments` | 대기 중인 파라미터 조정 |
| POST | `/feedback/approve-adjustment/{id}` | 파라미터 조정 승인 |
| POST | `/feedback/reject-adjustment/{id}` | 파라미터 조정 거부 |

### 종합 분석 (Analysis)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/analysis/comprehensive/{ticker}` | 종목 종합 AI 분석 |
| GET | `/api/analysis/tickers` | 분석 가능 종목 목록 |
| GET | `/api/analysis/ticker-news/{ticker}` | 종목별 뉴스 |

### 기술적 지표 (Indicators)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/indicators/weights` | 지표 가중치 조회 |
| POST | `/indicators/weights` | 지표 가중치 수정 |
| GET | `/indicators/realtime/{ticker}` | 실시간 지표 조회 |
| GET | `/api/indicators/rsi/{ticker}` | Triple RSI 데이터 |
| PUT | `/api/indicators/config` | 지표 설정 변경 |

### 매크로 지표 (Macro)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/macro/indicators` | VIX, Fear&Greed, CPI, Fed Rate |
| GET | `/api/macro/history/{series_id}` | 매크로 지표 히스토리 |
| GET | `/api/macro/calendar` | FOMC 등 경제 캘린더 |
| GET | `/api/macro/rate-outlook` | 금리 전망 |
| GET | `/api/macro/cached-indicators` | 캐시된 매크로 지표 |
| GET | `/api/macro/analysis` | 매크로 종합 분석 |
| POST | `/api/macro/refresh` | 매크로 데이터 수동 갱신 |

### 뉴스 (News)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/news/dates` | 뉴스 보유 날짜 목록 |
| GET | `/api/news/summary` | 뉴스 요약 (날짜별) |
| GET | `/api/news/daily` | 일별 뉴스 목록 |
| GET | `/api/news/{article_id}` | 기사 상세 조회 |

### 매매 추론 (Trade Reasoning)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/trade-reasoning/dates` | 매매 추론 보유 날짜 |
| GET | `/api/trade-reasoning/daily` | 일별 매매 추론 목록 |
| GET | `/api/trade-reasoning/{reasoning_id}` | 매매 추론 상세 |
| PUT | `/api/trade-reasoning/{reasoning_id}/feedback` | 사용자 피드백 등록 |

### 매매 원칙 (Principles)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/principles` | 매매 원칙 목록 |
| POST | `/api/principles` | 원칙 추가 |
| PUT | `/api/principles/core` | 핵심 원칙 수정 |
| PUT | `/api/principles/{id}` | 원칙 수정 |
| DELETE | `/api/principles/{id}` | 원칙 삭제 |

### 유니버스 관리 (Universe)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/universe` | ETF 유니버스 목록 |
| POST | `/universe/add` | 종목 수동 추가 |
| POST | `/universe/auto-add` | AI 기반 자동 종목 추가 |
| POST | `/universe/toggle` | 종목 활성/비활성 토글 |
| DELETE | `/universe/{ticker}` | 종목 삭제 |
| GET | `/universe/sectors` | 섹터 목록 |
| GET | `/universe/sectors/{sector_key}` | 섹터별 종목 |
| GET | `/universe/mappings` | 본주-레버리지 매핑 |
| POST | `/universe/mappings/add` | 매핑 추가 |
| DELETE | `/universe/mappings/{underlying}` | 매핑 삭제 |
| POST | `/universe/generate-profile/{ticker}` | 종목 프로필 생성 |
| POST | `/universe/generate-all-profiles` | 전체 프로필 일괄 생성 |
| GET | `/universe/profile-task/{task_id}` | 프로필 생성 태스크 상태 |
| GET | `/universe/profile/{ticker}` | 종목 프로필 조회 |

### 크롤링 (Crawl)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/crawl/manual` | 수동 크롤링 실행 |
| GET | `/crawl/status/{task_id}` | 크롤링 태스크 상태 조회 |

### 벤치마크 (Benchmark)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/benchmark/comparison` | AI vs SPY/SSO 성과 비교 |
| GET | `/benchmark/chart` | 벤치마크 차트 데이터 |
| GET | `/api/target/current` | 현재 수익 목표 |
| PUT | `/api/target/monthly` | 월별 수익 목표 설정 |
| PUT | `/api/target/aggression` | 공격성 수준 조정 |
| GET | `/api/target/history` | 수익 목표 히스토리 |
| GET | `/api/target/projection` | 수익 예측 |

### 긴급 프로토콜 및 리스크 (Emergency/Risk)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/emergency/stop` | 긴급 정지 (전량 매도) |
| POST | `/emergency/resume` | 긴급 정지 해제 |
| GET | `/emergency/status` | 긴급 프로토콜 상태 |
| GET | `/emergency/history` | 긴급 이벤트 히스토리 |
| GET | `/api/risk/status` | 리스크 종합 상태 |
| GET | `/api/risk/gates` | 리스크 게이트 상태 |
| PUT | `/api/risk/config` | 리스크 설정 변경 |
| GET | `/api/risk/budget` | 리스크 예산 현황 |
| GET | `/api/risk/backtest` | 백테스트 결과 |
| POST | `/api/risk/backtest/run` | 백테스트 실행 |
| GET | `/api/risk/streak` | 연패 감지 상태 |
| GET | `/api/risk/var` | VaR (Value at Risk) 조회 |
| GET | `/api/risk/dashboard` | 리스크 대시보드 종합 |

### 시스템 (System)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/system/status` | 시스템 상태 (가동 시간, 모듈 상태) |
| GET | `/system/usage` | AI 사용량 통계 |

### 에이전트 (Agents)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/agents/list` | 에이전트 목록 |
| GET | `/agents/{agent_id}` | 에이전트 상세 정보 |
| PUT | `/agents/{agent_id}` | 에이전트 설정 변경 |

### WebSocket 엔드포인트

| 경로 | 설명 |
|------|------|
| `ws://localhost:9500/ws/positions` | 실시간 포지션 업데이트 (2초 주기) |
| `ws://localhost:9500/ws/trades` | 실시간 매매 알림 (Redis Pub/Sub) |
| `ws://localhost:9500/ws/crawl/{task_id}` | 크롤링 진행 상황 스트리밍 |
| `ws://localhost:9500/ws/alerts` | 실시간 알림 스트리밍 |

WebSocket 인증: `?token=<API_SECRET_KEY>` 쿼리 파라미터로 API 키를 전달한다. `API_SECRET_KEY`가 미설정인 개발 환경에서는 인증을 건너뛴다.

---

## 프로젝트 구조

```
Stock_Trading/
├── src/                          # 메인 소스 코드
│   ├── main.py                   # TradingSystem 오케스트레이터
│   ├── analysis/                 # AI 분석 모듈
│   ├── crawler/                  # 뉴스 크롤링 파이프라인 (30개 소스)
│   ├── db/                       # 데이터베이스 (모델, 커넥션, 마이그레이션)
│   ├── executor/                 # KIS API 주문 실행
│   ├── fallback/                 # AI 장애 시 폴백 라우터
│   ├── feedback/                 # 일일/주간 피드백 루프
│   ├── indicators/               # 기술적 지표 계산
│   ├── monitoring/               # FastAPI 서버 + REST 엔드포인트
│   ├── orchestration/            # 매매 루프 오케스트레이션
│   ├── rag/                      # RAG (검색 증강 생성)
│   ├── risk/                     # 리스크 관리 파이프라인
│   ├── safety/                   # 안전장치 체인
│   ├── strategy/                 # 진입/청산 전략
│   ├── tax/                      # 세금/환율/슬리피지 추적
│   ├── telegram/                 # 텔레그램 봇 핸들러
│   └── utils/                    # 공통 유틸리티
├── dashboard/                    # Flutter 대시보드 (macOS)
├── db/                           # DB 초기화 스크립트
│   └── init.sql                  # 초기 스키마
├── data/                         # 런타임 데이터 (토큰, 원칙 등)
├── scripts/                      # 자동화 스크립트
│   ├── auto_trading.sh           # 야간 자동매매 스크립트
│   ├── install_launchagent.sh    # LaunchAgent 설치/관리
│   └── start_dashboard.py        # 대시보드 시작 스크립트
├── tests/                        # 테스트 코드
├── docker-compose.yml            # PostgreSQL + Redis 컨테이너
├── strategy_params.json          # 매매 전략 파라미터
├── requirements.txt              # Python 의존성
└── .env.example                  # 환경 변수 템플릿
```

---

## 관련 문서

| 문서 | 설명 |
|------|------|
| [SETUP.md](./SETUP.md) | 상세 설치 가이드 |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 시스템 아키텍처 상세 |
| [TRADING_GUIDE.md](./TRADING_GUIDE.md) | 매매 시스템 운용 가이드 |

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| AI | Claude Opus/Sonnet (SDK/API), MLX (Qwen3-30B-A3B), ChromaDB |
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2.0, asyncio/aiohttp |
| Database | PostgreSQL 17 + pgvector, Redis 7 |
| Frontend | Flutter 3.x (macOS Desktop) |
| Broker | KIS OpenAPI (한국투자증권) |
| Infra | Docker Compose, macOS LaunchAgent |
| Monitoring | Telegram Bot, WebSocket, REST API |

---

## 라이선스

이 프로젝트는 개인 사용 목적으로 개발되었다. 사용 전 관련 법률 및 규정을 확인한다.

**면책 조항**: 이 시스템은 자동매매 소프트웨어이며, 투자 손실에 대한 책임은 사용자에게 있다. 모의투자로 충분히 테스트한 후 실전 전환을 권장한다.
