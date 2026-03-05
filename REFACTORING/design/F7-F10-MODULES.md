# F7–F10 모듈 설계 문서

> 리팩토링 대상: Feature 7 (모니터링 API) / Feature 8 (최적화 & ML) / Feature 9 (오케스트레이션) / Feature 10 (Flutter 대시보드)
> 패턴: defalarm v3 — Feature → Manager/Orchestrator → Atomic Module 3계층 구조
> 작성 기준: 현행 코드베이스 실측값 기반 (줄 수 포함)

---

## 공통 규칙 (전 Feature 공통)

| 항목 | 규칙 |
|---|---|
| 계층 흐름 | Feature → Manager → Atomic (단방향, 역참조 금지) |
| Atomic 크기 | 30줄 이하, 순수 함수, DI 필수 |
| Manager 크기 | 50줄 이하, 로직 수행 금지, Atom 호출+전달만 |
| 파일 크기 | 200줄 이하 (컴포넌트 150줄 이하) |
| 타입 힌트 | 모든 매개변수/반환값 필수 (Python 3.10+ 문법) |
| 주석 | 한국어, "왜 이렇게 하는지" 중심 |
| 금지 | 순환 의존성, 하드코딩 설정값, 300줄+ 단일 파일 |

---

---

# F7. 모니터링 API (Monitoring)

## 개요

현행 `src/monitoring/` 디렉터리에 32개 파일, 총 14,512줄이 존재한다.
`dashboard_endpoints.py` (1,840줄), `universe_endpoints.py` (1,048줄) 등 초대형 파일이 다수이며
라우터/서비스/스키마 로직이 혼재되어 SRP를 위반한다.
리팩토링 목표: 각 파일 200줄 이하, 도메인별 라우터 분리, 서비스 레이어 독립.

## 전체 파이프라인

```
클라이언트 HTTP 요청
    │
    ▼
F7.1 ApiServer (라우터 자동 등록, CORS, lifespan)
    │
    ▼
도메인별 Router (F7.2 ~ F7.17)
    │
    ▼
Handler (요청 파라미터 검증, 응답 직렬화)
    │
    ▼
Service Layer (비즈니스 로직 위임)
    │
    ▼
Core Gateway (C0.2 DB / C0.6 KIS / C0.5 AI / C0.7 Telegram)
    │
    ▼
JSON 응답
```

---

## F7.1 ApiServer

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/api_server.py` (666줄) |
| **IN** | all_routers: list[APIRouter], middleware_config: MiddlewareConfig, lifespan_fn: Callable |
| **OUT** | app: FastAPI (라우터 등록 완료, CORS 설정 완료) |
| **역할** | FastAPI 앱 생성, 라우터 자동 등록, CORS/인증 미들웨어, lifespan 이벤트, /health 엔드포인트 |

### Atomic 분리 계획

```
api_server/
  ├── app_factory.py          ← create_app(routers, config) → FastAPI
  ├── router_registry.py      ← register_all_routers(app, routers) → None
  ├── middleware_setup.py     ← setup_cors(app, origins), setup_auth_middleware(app)
  ├── lifespan_manager.py     ← build_lifespan(startup_fn, shutdown_fn) → Callable
  └── health_check.py         ← health_endpoint() → HealthResponse
```

### DI 컨테이너 패턴

```python
# 현재: 전역 변수 방식 (set_dependencies() 호출 필수)
# 목표: DIContainer 클래스로 캡슐화

class DIContainer:
    """의존성 주입 컨테이너 — 모든 서비스 인스턴스를 한 곳에서 관리한다."""
    trading_system: TradingSystem
    db_gateway: DatabaseGateway
    kis_client: KISClient
    ...
```

---

## F7.2 DashboardEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/dashboard_endpoints.py` (1,840줄) |
| **IN** | C0.6 KISClient, C0.2 DatabaseGateway, position_monitor: PositionMonitor |
| **OUT** | REST API 응답 (대시보드 요약, 포지션, 거래 내역, 차트, 계좌) |

### 분리 계획 (8개 라우터)

```
dashboard/
  ├── summary_router.py      ← GET /dashboard/summary, /positions, /trades/recent
  ├── chart_router.py        ← GET /dashboard/charts/*, /charts/pnl, /charts/drawdown
  ├── account_router.py      ← GET /dashboard/accounts, /decay
  ├── strategy_router.py     ← GET|PUT /strategy/params, /strategy/ticker-params
  ├── tax_fx_router.py       ← GET /tax/*, /fx/*
  ├── slippage_router.py     ← GET /slippage/*
  ├── feedback_router.py     ← GET /feedback/*, /reports/*
  └── alert_router.py        ← GET /alerts/*
```

### Endpoint 목록

| Endpoint | Method | 현재 위치 | 분리 대상 |
|---|---|---|---|
| /dashboard/summary | GET | dashboard_endpoints.py | summary_router.py |
| /dashboard/positions | GET | dashboard_endpoints.py | summary_router.py |
| /dashboard/trades/recent | GET | dashboard_endpoints.py | summary_router.py |
| /dashboard/charts/pnl | GET | dashboard_endpoints.py | chart_router.py |
| /dashboard/charts/drawdown | GET | dashboard_endpoints.py | chart_router.py |
| /dashboard/charts/hourly | GET | dashboard_endpoints.py | chart_router.py |
| /dashboard/accounts | GET | dashboard_endpoints.py | account_router.py |
| /dashboard/decay | GET | dashboard_endpoints.py | account_router.py |
| /strategy/params | GET/PUT | dashboard_endpoints.py | strategy_router.py |
| /strategy/ticker-params | GET | dashboard_endpoints.py | strategy_router.py |
| /tax/* | GET | dashboard_endpoints.py | tax_fx_router.py |
| /fx/* | GET | dashboard_endpoints.py | tax_fx_router.py |
| /slippage/* | GET | dashboard_endpoints.py | slippage_router.py |
| /feedback/* | GET | dashboard_endpoints.py | feedback_router.py |
| /alerts/* | GET | dashboard_endpoints.py | alert_router.py |

### 서비스 레이어 분리

```python
# 현재: 핸들러 안에서 DB 직접 조회 + 비즈니스 로직 혼재
# 목표: Handler(요청/응답 처리) + Service(비즈니스 로직)

class DashboardSummaryService:
    """대시보드 요약 데이터를 조합한다 — DB + KIS 데이터를 통합한다."""
    async def get_summary(self, ...) -> DashboardSummary: ...

class PositionService:
    """포지션 목록을 정규화한다 — DB 포지션과 KIS 실시간을 병합한다."""
    async def get_positions(self, ...) -> list[PositionItem]: ...
```

---

## F7.3 AnalysisEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/analysis_endpoints.py` (918줄) |
| **IN** | C0.5 AiGateway, C0.6 KISClient, classifier: NewsClassifier |
| **OUT** | REST API (종목 분석, 뉴스 분석 결과) |

### Endpoint 목록

| Endpoint | Method | 설명 |
|---|---|---|
| /api/analysis/comprehensive/{ticker} | GET | Claude 종합 분석 (ComprehensiveTeam 호출) |
| /api/analysis/tickers | GET | 유니버스 종목 목록 + 간략 상태 |
| /api/analysis/ticker-news/{ticker} | GET | 종목별 최신 뉴스 분류 결과 |

### 분리 계획

```
analysis/
  ├── comprehensive_router.py   ← /api/analysis/comprehensive/{ticker}
  ├── ticker_router.py          ← /api/analysis/tickers, /api/analysis/ticker-news/{ticker}
  └── analysis_service.py       ← ComprehensiveTeam 호출, 결과 캐시 (Redis 5분)
```

### Atom 분리

```python
# Atom: 단일 책임
async def run_comprehensive_analysis(
    ticker: str,
    ai_gateway: AiGateway,
    db: DatabaseGateway,
) -> ComprehensiveResult:
    """종합 분석을 실행한다 — ComprehensiveTeam에 위임하고 결과를 반환한다."""
    ...

async def cache_analysis_result(
    ticker: str,
    result: ComprehensiveResult,
    redis: Redis,
    ttl_seconds: int,
) -> None:
    """분석 결과를 Redis에 캐시한다 — 중복 AI 호출을 방지한다."""
    ...
```

---

## F7.4 TradingControlEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/trading_control_endpoints.py` (221줄) |
| **IN** | trading_system: TradingSystem |
| **OUT** | REST API (매매 시작/중지/상태) |
| **상태** | 적절한 크기 — 구조 변경 없이 서비스 레이어만 추출 |

### Endpoint 목록

| Endpoint | Method | 인증 | 설명 |
|---|---|---|---|
| /api/trading/status | GET | Bearer | 현재 매매 상태 조회 |
| /api/trading/start | POST | Bearer | 매매 시작 (auto_stop_window 외) |
| /api/trading/stop | POST | Bearer | 매매 중지 |

### 인증 흐름

```
요청 → Authorization: Bearer <API_SECRET_KEY> 헤더 확인
    → 불일치: 401 Unauthorized
    → 일치: 비즈니스 로직 실행
```

---

## F7.5 MacroEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/macro_endpoints.py` (569줄) |
| **IN** | fred_client: FredClient, indicator_crawler: IndicatorCrawler |
| **OUT** | REST API (거시 지표, 달력, 금리 전망, 유동성) |

### Endpoint 목록

| Endpoint | Method | 설명 |
|---|---|---|
| /api/macro/indicators | GET | 주요 거시 지표 목록 (VIX, DXY, 10Y, CPI 등) |
| /api/macro/history/{series_id} | GET | FRED 시계열 데이터 조회 |
| /api/macro/calendar | GET | 경제 이벤트 달력 |
| /api/macro/rate-outlook | GET | Fed 금리 전망 |
| /api/macro/analysis | GET | Claude 거시 분석 요약 |
| /api/macro/net-liquidity | GET | Net Liquidity (WALCL - TGA - RRPONTSYD) |
| /api/macro/refresh | POST | 지표 강제 갱신 |

### 분리 계획

```
macro/
  ├── indicators_router.py    ← /indicators, /history/{series_id}
  ├── calendar_router.py      ← /calendar, /rate-outlook
  ├── liquidity_router.py     ← /net-liquidity
  ├── analysis_router.py      ← /analysis, /refresh
  └── macro_service.py        ← FredClient 조합, 캐시 관리
```

---

## F7.6 NewsEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/news_endpoints.py` (419줄) + `src/monitoring/news_collect_endpoints.py` (330줄) |
| **IN** | C0.2 DatabaseGateway, classifier: NewsClassifier, crawl_engine: CrawlEngine, telegram: TelegramGateway |
| **OUT** | REST API (뉴스 목록, 요약, 날짜별 조회, 수집 트리거) |

### Endpoint 목록

| Endpoint | Method | 설명 |
|---|---|---|
| /api/news/dates | GET | 뉴스가 있는 날짜 목록 |
| /api/news/daily | GET | 날짜별 뉴스 목록 |
| /api/news/{id} | GET | 뉴스 상세 조회 |
| /api/news/summary | GET | 오늘 뉴스 요약 |
| /api/news/collect-and-send | POST | 수동 크롤링 + 텔레그램 전송 트리거 |

### 분리 계획

```
news/
  ├── news_query_router.py     ← /dates, /daily, /{id}, /summary
  ├── news_collect_router.py   ← /collect-and-send
  └── news_service.py          ← DB 조회, 분류 결과 조합
```

---

## F7.7 UniverseEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/universe_endpoints.py` (1,048줄) |
| **IN** | universe_manager: UniverseManager, crawl_engine: CrawlEngine |
| **OUT** | REST API (유니버스 CRUD, 섹터 매핑, 크롤 작업 제어) |

### Endpoint 목록

| Endpoint | Method | 설명 |
|---|---|---|
| /universe | GET | 유니버스 전체 조회 |
| /universe/add | POST | 종목 추가 |
| /universe/toggle | POST | 종목 활성화/비활성화 |
| /universe/{ticker} | DELETE | 종목 삭제 |
| /universe/sectors | GET | 섹터 목록 |
| /universe/mappings | GET | 종목-섹터 매핑 |
| /crawl/manual | POST | 수동 크롤링 시작 |
| /crawl/status/{task_id} | GET | 크롤링 진행 상태 |

### 분리 계획

```
universe/
  ├── universe_crud_router.py   ← CRUD (GET/POST/DELETE /universe/*)
  ├── sector_router.py          ← /universe/sectors, /universe/mappings
  ├── crawl_router.py           ← /crawl/manual, /crawl/status/{task_id}
  └── universe_service.py       ← UniverseManager 위임, 검증 로직
```

---

## F7.8 EmergencyEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/emergency_endpoints.py` (491줄) |
| **IN** | emergency_protocol: EmergencyProtocol, risk modules |
| **OUT** | REST API (긴급 정지, 재개, 리스크 상태) |

### Endpoint 목록

| Endpoint | Method | 설명 |
|---|---|---|
| /emergency/stop | POST | 긴급 전체 청산 및 매매 중지 |
| /emergency/resume | POST | 긴급 정지 해제 |
| /emergency/status | GET | 긴급 상태 확인 |
| /api/risk/* | GET | 리스크 지표 조회 (gates, budget, config) |

### 분리 계획

```
emergency/
  ├── emergency_router.py    ← /stop, /resume, /status
  ├── risk_router.py         ← /api/risk/*
  └── emergency_service.py   ← EmergencyProtocol 위임
```

---

## F7.9 BenchmarkEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/benchmark_endpoints.py` (393줄) + `src/monitoring/benchmark.py` (421줄) |
| **IN** | benchmark_comparison: BenchmarkComparison, profit_target: ProfitTarget |
| **OUT** | REST API (벤치마크 비교, 목표 수익률) |

### Endpoint 목록

| Endpoint | Method | 설명 |
|---|---|---|
| /benchmark/comparison | GET | 전략 vs S&P500 수익률 비교 |
| /benchmark/chart | GET | 누적 수익률 차트 데이터 |
| /api/target | GET/PUT | 목표 수익률 조회/수정 |

---

## F7.10 TradeReasoningEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/trade_reasoning_endpoints.py` (522줄) |
| **IN** | C0.2 DatabaseGateway |
| **OUT** | REST API (매매 근거 기록 조회, 피드백 입력) |

### Endpoint 목록

| Endpoint | Method | 설명 |
|---|---|---|
| /api/trade-reasoning/dates | GET | 매매 근거가 있는 날짜 목록 |
| /api/trade-reasoning/daily | GET | 날짜별 매매 근거 목록 |
| /api/trade-reasoning/stats | GET | 정확도 통계 |
| /api/trade-reasoning/{id}/feedback | PUT | 피드백(정확/부정확) 입력 |

### 분리 계획

```
trade_reasoning/
  ├── reasoning_query_router.py   ← /dates, /daily, /stats
  ├── reasoning_feedback_router.py ← /{id}/feedback
  └── reasoning_service.py        ← DB 조회 + 통계 계산
```

---

## F7.11 IndicatorEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/indicator_endpoints.py` (388줄) |
| **IN** | weights_manager: WeightsManager, C0.6 KISClient |
| **OUT** | REST API (지표 가중치 조회/수정, 실시간 지표, RSI) |

### Endpoint 목록

| Endpoint | Method | 설명 |
|---|---|---|
| /indicators/weights | GET/POST | 지표 가중치 조회/수정 |
| /indicators/realtime/{ticker} | GET | 실시간 OBI/CVD/VPIN 조회 |
| /api/indicators/rsi/{ticker} | GET | RSI 조회 |

---

## F7.12 ManualTradeEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/manual_trade_endpoints.py` (523줄) |
| **IN** | C0.5 AiGateway, C0.6 KISClient, entry_strategy: EntryStrategy, exit_strategy: ExitStrategy |
| **OUT** | REST API (수동 분석, 수동 주문 실행) |

### Endpoint 목록

| Endpoint | Method | 설명 |
|---|---|---|
| /api/manual-trade/analyze | POST | 종목 수동 분석 (AI 분석 포함) |
| /api/manual-trade/execute | POST | 수동 주문 실행 (매수/매도) |

### 분리 계획

```
manual_trade/
  ├── analyze_router.py    ← /analyze (분석만, 부작용 없음)
  ├── execute_router.py    ← /execute (주문 실행, 인증 필수)
  └── manual_trade_service.py ← 분석+실행 오케스트레이션
```

---

## F7.13 PrinciplesEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/principles_endpoints.py` (355줄) |
| **IN** | C0.2 DatabaseGateway (trading_principles.json 또는 DB) |
| **OUT** | REST API (매매 원칙 CRUD) |
| **역할** | 매매 원칙 목록 조회, 생성, 수정, 삭제, 핵심 원칙 지정 |

---

## F7.14 AgentEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/agent_endpoints.py` (394줄) |
| **IN** | agent config files (JSON/YAML) |
| **OUT** | REST API (에이전트 목록, 상세, 프롬프트 수정) |

### Endpoint 목록

| Endpoint | Method | 설명 |
|---|---|---|
| /agents/list | GET | 에이전트 목록 |
| /agents/{id} | GET | 에이전트 상세 (프롬프트, 파라미터) |
| /agents/{id} | PUT | 에이전트 프롬프트/파라미터 수정 |

---

## F7.15 SystemEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/system_endpoints.py` (152줄) |
| **IN** | system status from all modules (Redis, DB, KIS 연결 상태) |
| **OUT** | REST API (시스템 전체 상태, 리소스 사용량) |
| **상태** | 적절한 크기 — 현행 구조 유지 |

### Endpoint 목록

| Endpoint | Method | 설명 |
|---|---|---|
| /system/status | GET | DB/Redis/KIS/WebSocket 연결 상태 |
| /system/usage | GET | CPU/메모리/디스크 사용량 |

---

## F7.16 PerformanceEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/performance_endpoints.py` (88줄) |
| **IN** | C0.2 DatabaseGateway, time_performance: TimePerformance |
| **OUT** | REST API (시간대별 성과 분석) |
| **상태** | 적절한 크기 — 현행 구조 유지 |

---

## F7.17 OrderFlowEndpoints

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/order_flow_endpoints.py` (160줄) |
| **IN** | C0.6 KISClient, WebSocket 실시간 데이터 |
| **OUT** | REST API (체결 강도, OBI, CVD 스냅샷) |
| **상태** | 적절한 크기 — 현행 구조 유지 |

---

## F7.18 WebSocketManager

| 항목 | 내용 |
|---|---|
| **현재 위치** | `src/websocket/` (9개 파일 + 3개 하위 디렉터리, 총 3,258줄) |
| **IN** | FastAPI app, KIS WebSocket 스트림, Redis pub/sub |
| **OUT** | WebSocket 엔드포인트 (실시간 데이터 Push) |

### 구성 파일

```
src/websocket/
  ├── manager.py (430줄)          ← WebSocket 연결 관리자 (연결/해제/브로드캐스트)
  ├── connection.py (369줄)       ← KIS WebSocket 연결 상태 머신
  ├── subscriber.py (342줄)       ← Redis Pub/Sub 구독, 클라이언트 Push
  ├── parser.py (300줄)           ← KIS 메시지 파싱 (암호화 해제 포함)
  ├── crypto.py (118줄)           ← AES-CBC 복호화 (KIS 암호화 메시지)
  ├── auth.py (102줄)             ← WebSocket 인증 토큰 검증
  ├── config.py (169줄)           ← KIS WebSocket 설정 (구독 코드 등)
  ├── models.py (189줄)           ← 메시지 도메인 모델
  ├── handlers/
  │   ├── base.py (67줄)          ← BaseHandler 추상 클래스
  │   ├── trade_handler.py (131줄)      ← 실시간 체결 처리
  │   ├── orderbook_handler.py (100줄)  ← 호가 처리
  │   └── notice_handler.py (160줄)     ← KIS 공지 처리
  ├── storage/
  │   ├── redis_publisher.py (130줄)    ← Redis 채널에 게시
  │   └── tick_writer.py (162줄)        ← PostgreSQL tick 저장
  └── indicators/
      ├── obi.py (101줄)           ← OBI 실시간 계산
      ├── cvd.py (106줄)           ← CVD 실시간 계산
      ├── vpin.py (135줄)          ← VPIN 실시간 계산
      └── execution_strength.py (108줄) ← 체결강도 계산
```

### WebSocket 엔드포인트

| 엔드포인트 | 방향 | 설명 |
|---|---|---|
| /ws/positions | Server→Client Push | 실시간 포지션 업데이트 |
| /ws/trades | Server→Client Push | 실시간 체결 이벤트 |
| /ws/crawl/{task_id} | Server→Client Push | 크롤링 진행 상황 |
| /ws/alerts | Server→Client Push | 실시간 알림 |
| /ws/realtime-tape/{ticker} | Server→Client Push | 실시간 체결 테이프 |

### 상태

각 파일이 이미 단일 책임을 가지므로 구조적으로 건전하다.
`manager.py` (430줄)가 한계를 초과하므로 ConnectionPool/BroadcastService로 분리를 권장한다.

---

## F7.19 TelegramNotifier

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/telegram_notifier.py` (717줄) |
| **IN** | C0.7 TelegramGateway, event_data: dict |
| **OUT** | 텔레그램 메시지 전송 (알림, 보고서, 뉴스, 긴급) |

### Atomic 분리 계획

```
telegram/
  ├── notifier.py (Manager, 50줄)          ← 전송 오케스트레이션
  ├── formatters/
  │   ├── trade_formatter.py               ← format_trade_message() → str
  │   ├── daily_report_formatter.py        ← format_daily_report() → str
  │   ├── news_formatter.py                ← format_news_summary() → str
  │   ├── emergency_formatter.py           ← format_emergency_alert() → str
  │   └── key_news_formatter.py            ← format_key_news() → str
  └── sender.py                            ← send_message(chat_id, text) → bool (Atom)
```

### 공개 인터페이스

```python
class TelegramNotifier:
    """텔레그램 알림 오케스트레이터 — 포매터와 게이트웨이를 조합한다."""

    async def send_trade_notification(self, trade: TradeEvent) -> None: ...
    async def send_daily_report(self, report: DailyReport) -> None: ...
    async def send_key_news(self, news: list[NewsItem]) -> None: ...
    async def send_emergency_alert(self, event: EmergencyEvent) -> None: ...
```

---

## F7.20 IndicatorCrawler

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/monitoring/indicator_crawler.py` (661줄) |
| **IN** | C0.4 HttpGateway, C0.5 AiGateway, C0.2 DatabaseGateway |
| **OUT** | 거시 지표 자동 크롤링 결과 저장 (1시간 주기) |
| **역할** | FRED, Fear & Greed, 달러인덱스, VIX 등 외부 지표 수집 및 DB 저장 |

### Atomic 분리 계획

```
indicator_crawler/
  ├── crawler_scheduler.py   ← 1시간 주기 스케줄러 (AsyncScheduler 패턴)
  ├── fred_fetcher.py        ← FRED API 호출 → list[IndicatorData]
  ├── fear_greed_fetcher.py  ← Fear & Greed Index 수집
  ├── indicator_writer.py    ← DB에 지표 저장 (Upsert)
  └── indicator_models.py    ← IndicatorData, IndicatorSeries 도메인 모델
```

### 지원 파일

| 파일 | 크기 | 역할 |
|---|---|---|
| `fred_client.py` | 674줄 | FRED API 래퍼 → F7.5/F7.20 공유 |
| `calendar_helpers.py` | 266줄 | 경제 달력 파싱 유틸 |
| `daily_report.py` | 484줄 | 일일 보고서 생성 → F7.2 feedback_router와 연동 |
| `live_readiness.py` | 424줄 | 장 시작 전 준비 상태 체크 |
| `benchmark.py` | 421줄 | BenchmarkComparison 구현체 → F7.9에서 사용 |
| `realtime_tape.py` | 247줄 | 실시간 체결 테이프 집계 |
| `alert.py` | 293줄 | 알림 생성/조회 로직 |
| `account_mode.py` | 117줄 | 실계좌/모의계좌 모드 전환 |
| `schemas.py` | 315줄 | Pydantic 요청/응답 스키마 |
| `auth.py` | - | API 인증 미들웨어 |
| `trade_endpoints.py` | 354줄 | 거래 내역 엔드포인트 (F7.2 summary_router와 통합) |

---

---

# F8. 최적화 & ML (Optimization)

## 개요

현행 `src/optimization/` 11개 파일 (2,375줄)과 `src/feedback/` 6개 파일 (2,210줄, execution_optimizer 포함)이 ML 파이프라인을 구성한다.
각 파일이 이미 단일 책임 원칙을 대체로 준수하나, `time_travel.py` (373줄), `walk_forward.py` (351줄) 등은 분리를 권장한다.

## 전체 파이프라인

```
C0.2 DB (historical data)
    │
    ▼
F8.1 DataPreparer          ← 원시 데이터 정제 및 정규화
    │
    ▼
F8.2 FeatureEngineer       ← 21개 피처 생성
    │
    ▼
F8.3 TargetBuilder         ← P(+1% in 5min) 타겟 생성
    │
    ├──────────────────────────────┐
    ▼                              ▼
F8.4 LGBMTrainer           F8.5 OptunaOptimizer
    │  TimeSeriesSplit             │  TPE, 200 trials
    └──────────────────────────────┘
                │
                ▼
          F8.6 WalkForward          ← 4wk train / 1wk test
                │
                ▼
          TrainedModel (저장 → models/)
                │
    ┌───────────┴───────────┐
    ▼                       ▼
F8.7 AutoTrainer       F8.8 TimeTravelTrainer
  (주간 자동 재학습)     (분봉 리플레이 → ChromaDB)
```

---

## F8.1 DataPreparer

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/optimization/data_preparer.py` (289줄) |
| **IN** | db: DatabaseGateway, date_range: tuple[date, date], tickers: list[str] |
| **OUT** | `PreparedData = {features: DataFrame, metadata: DatasetMeta}` |
| **역할** | DB에서 OHLCV + 지표 데이터 조회, 결측치 처리, 정규화 |

### Atomic 분리

```python
# Atom 1: 원시 데이터 조회
async def fetch_raw_ohlcv(
    db: DatabaseGateway,
    ticker: str,
    start: date,
    end: date,
) -> DataFrame:
    """OHLCV 데이터를 DB에서 조회한다 — 날짜 범위 내 전체 데이터를 반환한다."""
    ...

# Atom 2: 결측치 처리
def fill_missing_data(df: DataFrame, method: str = "forward") -> DataFrame:
    """결측치를 전방 채움으로 처리한다 — NaN이 전체의 10% 초과 시 경고를 로깅한다."""
    ...

# Atom 3: 정규화
def normalize_features(df: DataFrame, scaler_type: str = "minmax") -> tuple[DataFrame, Scaler]:
    """피처를 정규화한다 — 스케일러를 함께 반환해 역변환을 지원한다."""
    ...
```

---

## F8.2 FeatureEngineer

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/optimization/feature_engineer.py` (260줄) |
| **IN** | raw_data: DataFrame |
| **OUT** | feature_matrix: DataFrame (21개 피처) |

### 피처 목록 (21개)

| 그룹 | 피처 |
|---|---|
| 모멘텀 | RSI(14), MACD_line, MACD_signal, MACD_hist |
| 변동성 | BB_upper, BB_lower, BB_width, ATR(14) |
| 볼륨 | volume_ratio(5d avg), OBV_slope |
| 오더플로우 | OBI, CVD, VPIN |
| 섹터 | sector_momentum_score, leader_divergence |
| 고래 | whale_score |
| 레짐 | regime_label(encoded), vix_level |
| ML | ml_confidence (이전 예측값 피드백) |

---

## F8.3 TargetBuilder

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/optimization/target_builder.py` (113줄) |
| **IN** | price_data: DataFrame, horizon_minutes: int = 5, threshold_pct: float = 1.0 |
| **OUT** | target: Series (0 또는 1, P(+1% in 5min)) |
| **상태** | 적절한 크기 — 현행 구조 유지 |

---

## F8.4 LGBMTrainer

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/optimization/lgbm_trainer.py` (235줄) |
| **IN** | prepared_data: PreparedData, hyperparams: LGBMHyperparams |
| **OUT** | `TrainedModel = {model: LGBMClassifier, metrics: ModelMetrics, feature_importance: dict}` |
| **역할** | TimeSeriesSplit 교차 검증, 학습, 성능 측정 |

### Atomic 분리

```python
# Atom: 교차 검증
def run_timeseries_cv(
    model: LGBMClassifier,
    X: DataFrame,
    y: Series,
    n_splits: int = 5,
) -> list[FoldMetrics]:
    """시계열 분할 교차 검증을 실행한다 — 미래 데이터 누출을 방지한다."""
    ...

# Atom: 피처 중요도 추출
def extract_feature_importance(model: LGBMClassifier, feature_names: list[str]) -> dict[str, float]:
    """피처 중요도를 딕셔너리로 변환한다 — 상위 10개를 로깅한다."""
    ...
```

---

## F8.5 OptunaOptimizer

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/optimization/optuna_optimizer.py` (213줄) |
| **IN** | search_space: HyperparamSpace, objective_fn: Callable, n_trials: int = 200 |
| **OUT** | `BestParams = {params: dict[str, Any], score: float, trial_history: list}` |
| **역할** | Optuna TPE 샘플러로 LightGBM 하이퍼파라미터 탐색 |

---

## F8.6 WalkForward

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/optimization/walk_forward.py` (351줄) |
| **IN** | data: DataFrame, model_fn: Callable, train_window_weeks: int = 4, test_window_weeks: int = 1 |
| **OUT** | `WalkForwardResult = {period_returns: list[float], sharpe: float, stability_score: float, win_rate: float}` |

### Atomic 분리 (351줄 → 200줄 이하)

```
walk_forward/
  ├── splitter.py           ← generate_walk_forward_splits(data, train_w, test_w) → list[Split]
  ├── evaluator.py          ← evaluate_period(model, X_test, y_test) → PeriodResult
  ├── metrics_calculator.py ← calculate_sharpe(returns), calculate_stability(results) → float
  └── walk_forward.py       ← WalkForward Manager (50줄) — 위 Atom 조합
```

---

## F8.7 AutoTrainer

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/optimization/auto_trainer.py` (299줄) |
| **IN** | db: DatabaseGateway, schedule: TrainingSchedule (weekly) |
| **OUT** | TrainingComplete 이벤트 (모델 파일 저장 + 메트릭 DB 기록) |
| **역할** | 매주 자동으로 전체 ML 파이프라인(F8.1~F8.6)을 실행한다 |

---

## F8.8 TimeTravelTrainer

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/optimization/time_travel.py` (373줄) |
| **IN** | minute_replay_data: DataFrame, rag_store: ChromaDB |
| **OUT** | 역사적 패턴 → ChromaDB 저장 (벡터 검색 가능) |
| **역할** | 분봉 데이터를 과거부터 리플레이하며 패턴을 RAG 지식으로 축적한다 |

### Atomic 분리 (373줄 → 200줄 이하)

```
time_travel/
  ├── replay_engine.py      ← replay_minute_data(data, start, end) → Iterator[MinuteSnapshot]
  ├── pattern_extractor.py  ← extract_patterns(snapshot) → list[TradingPattern]
  ├── rag_writer.py         ← store_patterns_to_rag(patterns, rag_store) → int
  └── time_travel.py        ← TimeTravelTrainer Manager (50줄)
```

---

## F8.9 ExecutionOptimizer

| 항목 | 내용 |
|---|---|
| **현재 위치** | `src/feedback/execution_optimizer/` (5개 파일, 761줄) |
| **IN** | daily_trades: list[Trade], execution_metrics: ExecutionMetrics |
| **OUT** | `OptimizedParams = {adjustments: dict[str, float]}` → strategy_params.json 갱신 |
| **역할** | EOD 시 당일 매매 분석 → 파라미터 ±5% 조정, 최대 30% 편차 제한 |

### 현행 파일 구조 (이미 잘 분리됨)

```
execution_optimizer/
  ├── trade_analyzer.py (299줄)   ← 당일 매매 성과 분석 → TradeAnalysis
  ├── param_tuner.py (284줄)      ← 6가지 규칙 적용, 조정값 계산 → ParamAdjustments
  ├── param_writer.py (192줄)     ← strategy_params.json 백업 + 갱신
  ├── runner.py (144줄)           ← 전체 흐름 오케스트레이션
  └── config.py (51줄)            ← 조정 한계, 규칙 설정
```

### 상태

`trade_analyzer.py` (299줄)와 `param_tuner.py` (284줄)가 200줄 한계를 초과한다.
`trade_analyzer.py`는 EntryAnalyzer + ExitAnalyzer + SlippageAnalyzer로 분리를 권장한다.

---

## F8.10 KnowledgeManager (RAG)

| 항목 | 내용 |
|---|---|
| **현재 위치** | `src/ai/knowledge_manager.py` (691줄) + `src/rag/` (5개 파일) |
| **IN** | documents: list[str], embeddings_model: str = "bge-m3" |
| **OUT** | RAG 검색 결과: list[RetrievedDoc] |
| **역할** | ChromaDB 벡터 DB, bge-m3 1024차원 임베딩, 실패 패턴 검색 |

### 현행 RAG 파일

| 파일 | 역할 |
|---|---|
| `src/rag/retriever.py` | ChromaDB 유사도 검색 |
| `src/rag/indexer.py` | 문서 인덱싱 (임베딩 생성 + 저장) |
| `src/rag/document_store.py` | 컬렉션 관리 |
| `src/rag/query_builder.py` | 검색 쿼리 전처리 |
| `src/ai/knowledge_manager.py` | RAG 오케스트레이터 (691줄) |

### Atomic 분리 (691줄 → 200줄 이하)

```
knowledge/
  ├── knowledge_manager.py (Manager, 50줄)  ← index + retrieve 오케스트레이션
  ├── embedder.py                           ← embed_text(text) → list[float]
  ├── collection_manager.py                 ← create/delete/list collections
  ├── searcher.py                           ← semantic_search(query, n) → list[Doc]
  └── doc_formatter.py                      ← format_for_indexing(raw) → IndexDoc
```

---

## F8 지원 모듈 (feedback/)

| 파일 | 크기 | 역할 |
|---|---|---|
| `src/feedback/daily_feedback.py` | 456줄 | 일일 피드백 생성 (Claude 분석) |
| `src/feedback/param_adjuster.py` | 367줄 | 파라미터 조정 로직 (F8.9와 통합 검토) |
| `src/feedback/rag_doc_updater.py` | 407줄 | RAG 문서 갱신 (`update_from_daily()` 인터페이스) |
| `src/feedback/time_performance.py` | 551줄 | 시간대별 성과 분석 → F7.16에서 사용 |
| `src/feedback/weekly_analysis.py` | 409줄 | 주간 성과 분석 |

`time_performance.py` (551줄)는 HourlyAnalyzer + SessionAnalyzer + PerformanceFormatter로 분리를 권장한다.

---

---

# F9. 오케스트레이션 (Orchestration)

## 개요

현행 `src/main.py` (3,255줄) + `src/orchestration/` (4개 파일, 1,396줄)으로 구성된다.
`main.py`는 초기화(494줄), DI, 트레이딩 루프, EOD 시퀀스, 종료 핸들러가 모두 혼재한 최대 위반 파일이다.
리팩토링 목표: `main.py` → 50줄 이하의 엔트리포인트로 축소, 각 책임을 별도 모듈로 분리.

## 전체 파이프라인

```
macOS LaunchAgent (23:00 KST)
    │
    ▼
src/main.py (엔트리포인트, 50줄 이하)
    │
    ▼
F9.1 SystemInitializer     ← 모든 모듈 초기화 (순서: DB→Redis→KIS→WS→Crawler→AI→Safety→Strategy)
    │
    ▼
F9.2 DependencyInjector    ← set_dependencies() 자동화, DIContainer 구성
    │
    ▼
F9.3 PreparationPhase      ← 크롤링 → 분류 → VIX 확인 → 레짐 판별 → 포지션 동기화
    │
    ▼
F9.4 TradingLoop           ← 동적 주기 루프 (정규장/비정규장 분기)
    │
    ├─── F9.5 ContinuousAnalysis  ← 30분 주기 Opus 분석 (별도 태스크)
    ├─── F9.6 NewsPipeline         ← 크롤링 → 분류 → 전송 (별도 태스크)
    │
    ▼
F9.7 EODSequence           ← 장 마감 후 처리 (청산, 보고서, 피드백, ML 학습)
    │
    ▼
F9.8 GracefulShutdown      ← SIGTERM/SIGINT 처리, 리소스 정리
```

---

## F9.1 SystemInitializer

| 항목 | 내용 |
|---|---|
| **현재 위치** | `src/main.py` lines 432–926 (initialize() 메서드, ~494줄) |
| **IN** | .env 설정값, 각 모듈 클래스 참조 |
| **OUT** | `InitializedSystem` — 모든 모듈이 준비된 컨테이너 |

### 초기화 순서 (의존성 기반)

```
1. ConfigProvider (.env 로드)
2. DatabaseGateway (PostgreSQL 연결 풀 생성)
3. RedisGateway (Redis 연결 풀 생성)
4. KISAuthManager (토큰 로드 또는 발급)
5. KISClient (KIS REST API 클라이언트)
6. WebSocketManager (KIS 실시간 구독 시작)
7. CrawlEngine (30개 크롤러 등록)
8. AiGateway (Claude API 클라이언트)
9. MLXClassifier (로컬 Qwen3-30B MLX 로드)
10. Safety Chain (HardSafety → SafetyChecker → EmergencyProtocol → CapitalGuard)
11. Strategy Modules (Entry, Exit, Position, Scalping, Beast...)
12. Execution Modules (OrderManager, PositionMonitor, UniverseManager)
13. Feedback Modules (ExecutionOptimizer, RAGDocUpdater...)
14. Monitoring (ApiServer 시작, TelegramNotifier)
```

### Atomic 분리 계획

```
system_initializer/
  ├── initializer.py (Manager, 50줄)      ← 순서 조율
  ├── infra_init.py                        ← DB + Redis 초기화
  ├── kis_init.py                          ← KIS 인증 + 클라이언트 초기화
  ├── ai_init.py                           ← Claude + MLX 초기화
  ├── safety_init.py                       ← 안전장치 체인 초기화
  ├── strategy_init.py                     ← 전략 모듈 초기화
  └── monitoring_init.py                   ← API 서버 + 텔레그램 초기화
```

---

## F9.2 DependencyInjector

| 항목 | 내용 |
|---|---|
| **현재 위치** | `src/monitoring/api_server.py`의 `set_dependencies()` + main.py 내 DI 호출부 |
| **IN** | InitializedSystem (모든 모듈 인스턴스) |
| **OUT** | DIContainer (타입별 모듈 접근 가능) |

### 설계 방향

```python
class DIContainer:
    """의존성 주입 컨테이너 — 싱글턴으로 전 시스템에서 공유된다."""

    # 인프라
    db: DatabaseGateway
    redis: RedisGateway

    # 브로커
    kis_client: KISClient
    ws_manager: WebSocketManager

    # AI
    ai_gateway: AiGateway
    mlx_classifier: MLXClassifier
    knowledge_manager: KnowledgeManager

    # 안전장치
    hard_safety: HardSafety
    emergency_protocol: EmergencyProtocol
    capital_guard: CapitalGuard

    # 전략
    entry_strategy: EntryStrategy
    exit_strategy: ExitStrategy
    beast_mode: BeastModeDetector
    # ... 이하 생략

    def inject_all(self) -> None:
        """각 모듈에 set_dependencies()를 일괄 호출한다 — 순서 오류를 방지한다."""
        ...
```

---

## F9.3 PreparationPhase

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/orchestration/preparation.py` (329줄) |
| **IN** | market_clock: MarketClock, crawl_engine: CrawlEngine, classifier: NewsClassifier, kis_client: KISClient |
| **OUT** | `PreparationResult = {news_classified: list[News], regime: RegimeType, vix: float, positions_synced: bool}` |

### 실행 단계 (20:00 KST 시작)

```
1. 시장 시간 확인 (MarketClock) → 장 마감 전 준비 윈도우 확인
2. 크롤링 실행 (CrawlEngine.fast_crawl) → 핵심 8개 소스 우선
3. 뉴스 분류 (NewsClassifier) → 고영향 뉴스 필터링
4. 고영향 뉴스 텔레그램 전송
5. VIX 조회 (FRED VIXCLS API, fallback 20.0)
6. 레짐 판별 (RegimeDetector)
7. 포지션 동기화 (PositionMonitor.sync_positions)
8. 전략 파라미터 로드 (strategy_params.json)
```

### 현재 버그 수정 사항 반영

```python
# FallbackRouter.call()은 dict를 반환한다
# parse_verification_result()에 str이 아닌 dict가 전달되면 TypeError 발생
# 수정: .get("content", "") 추출 필수 (preparation.py:87)
result_text = fallback_result.get("content", "")  # dict에서 str 추출
```

---

## F9.4 TradingLoop

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/orchestration/trading_loop.py` (395줄) |
| **IN** | all strategy/execution/risk modules, regime: RegimeType, vix: float |
| **OUT** | `LoopResult = {trades_made: int, cycle_count: int, loop_ended_reason: str}` |

### 동적 루프 주기

| 세션 | 주기 | 조건 |
|---|---|---|
| Power Open | 90초 | 09:30-10:00 ET |
| Mid Session | 180초 | 10:00-15:30 ET (일반) |
| Power Hour | 120초 | 15:00-15:45 ET |
| Monitor | 30-60초 | 포지션 보유 시 30초, 없을 때 60초 |

### 비정규 장 처리 (핵심 버그 수정 반영)

```python
# 비정규 장(프리마켓/애프터마켓): sync_positions()만 실행
# monitor_all()은 정규장에서만 호출 — 가상 서버에서 주문 불가
if not market_clock.is_regular_session():
    await position_monitor.sync_positions()  # 포지션 동기화만
    continue  # monitor_all() 호출 금지
```

### 매크로 플래시 크래시 체크

```python
# 매 루프마다 확인 (Phase 9)
if await macro_flash_crash.check():
    await emergency_protocol.liquidate_all("FLASH_CRASH")
    break
```

---

## F9.5 ContinuousAnalysis

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/orchestration/continuous_analysis.py` (278줄) |
| **IN** | ai_gateway: AiGateway, crawl_engine: CrawlEngine, market_clock: MarketClock |
| **OUT** | 분석 결과 → Redis 저장 (TTL 30분) |
| **실행 시간** | 23:00~06:30 KST, 30분 주기 |

### 분석 흐름

```
30분 타이머
    │
    ▼
현재 뉴스 + 지표 수집 (fast_crawl)
    │
    ▼
Claude Opus 이슈 분석 (CONTINUOUS_ANALYST 프롬프트)
    │
    ▼
Redis 저장 (key: continuous_analysis:{timestamp})
    │
    ▼
중요 이슈 발견 시 → TelegramNotifier.send_emergency_alert()
```

---

## F9.6 NewsPipeline

| 항목 | 내용 |
|---|---|
| **현재 파일** | `src/orchestration/news_pipeline.py` (384줄) |
| **IN** | crawl_engine: CrawlEngine, classifier: NewsClassifier, telegram: TelegramNotifier |
| **OUT** | 크롤링 → 분류 → 저장 → 텔레그램 전송 완료 이벤트 |

### 파이프라인 단계

```
CrawlEngine.crawl_all() → raw articles
    │
    ▼
NewsClassifier.classify_batch() → classified articles
    │
    ▼
KeyNewsFilter.filter() → high_impact articles
    │
    ▼
DB 저장 (DatabaseGateway.bulk_insert_news)
    │
    ▼
TelegramNotifier.send_key_news(high_impact)
```

---

## F9.7 EODSequence

| 항목 | 내용 |
|---|---|
| **현재 위치** | `src/main.py`의 `_run_eod_sequence()` + `_run_daily_feedback()` |
| **IN** | all modules, db: DatabaseGateway, telegram: TelegramNotifier |
| **OUT** | EOD 완료 (포지션 청산, 보고서 생성, 파라미터 조정, ML 학습) |

### EOD 실행 순서

```
1. EOD 청산 (take_profit=0인 strong_bull 레짐 제외, max_hold_days=0 포지션)
2. 베어 ETF 홀딩 확인 (crash/mild_bear 레짐에서 인버스 ETF는 청산 제외)
3. 일일 피드백 생성 (DailyFeedback.generate)
4. 텔레그램 일일 보고서 전송
5. ExecutionOptimizer 실행 → strategy_params.json 갱신
6. RAGDocUpdater.update_from_daily() → ChromaDB 갱신
7. Phase 9 모듈 일일 리셋 (DeadmanSwitch, MacroFlashCrash)
8. _sell_blocked_tickers 초기화 (PositionMonitor)
9. 주간 요일 체크 → 금요일이면 AutoTrainer.run_weekly_training()
```

---

## F9.8 GracefulShutdown

| 항목 | 내용 |
|---|---|
| **현재 위치** | `src/main.py`의 `shutdown()` + SIGTERM/SIGINT 핸들러 |
| **IN** | SIGTERM 또는 SIGINT 신호 |
| **OUT** | 모든 리소스 정리 완료 |

### 종료 순서

```
1. running = False (루프 종료 신호)
2. 현재 루프 사이클 완료 대기 (최대 30초 timeout)
3. WebSocketManager.disconnect() (KIS WS 구독 해제)
4. CrawlEngine.shutdown() (진행 중인 크롤 중지)
5. 열린 포지션 저장 (DB 기록 확정)
6. ApiServer 종료 (FastAPI lifespan 종료)
7. Redis 연결 풀 정리 (redis.aclose())
8. DB 연결 풀 정리 (session factory 종료)
9. MLXClassifier 언로드 (GPU 메모리 해제)
```

---

---

# F10. 대시보드 (Flutter)

## 개요

현행 Flutter 대시보드는 `dashboard/lib/` 아래 28개 스크린, 28개 프로바이더, 22개 모델, 3개 서비스로 구성된다.
`api_service.dart` (1,544줄)가 단일 파일에 모든 도메인 API를 처리하는 최대 위반 파일이다.
28개 스크린 중 다수가 1,000줄을 초과한다.

## 전체 아키텍처 (목표 상태)

```
Flutter UI (Screens, 300줄 이하)
    │
    ▼
Provider Layer (28개, 상태 관리)
    │
    ▼
F10.1 ApiClient (도메인별 14개 클라이언트)
    │                            │
    ▼                            ▼
F10.2 WebSocketClient     F10.6 Theme & Design Tokens
    │
    ▼
FastAPI Backend (F7)
```

---

## F10.1 ApiClient (도메인별 분리)

| 항목 | 내용 |
|---|---|
| **현재 파일** | `dashboard/lib/services/api_service.dart` (1,544줄) |
| **목표** | 도메인별 14개 ApiClient로 분리, 각 200줄 이하 |

### BaseApiClient (공통 로직)

```dart
/// 모든 도메인 ApiClient의 기반 클래스 — HTTP 메서드와 인증 헤더를 통합 처리한다.
abstract class BaseApiClient {
  final String baseUrl;
  final String? apiKey;  // Authorization: Bearer 헤더에 사용

  Future<Map<String, dynamic>> get(String path, {Map<String, String>? params});
  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body);
  Future<Map<String, dynamic>> put(String path, Map<String, dynamic> body);
  Future<void> delete(String path);

  /// API 오류를 도메인 예외로 변환한다 — 404/500 등 HTTP 코드별 처리.
  T handleError<T>(int statusCode, String endpoint);
}
```

### 14개 도메인 ApiClient

| 클라이언트 | 담당 Endpoint 그룹 | 예상 줄 수 |
|---|---|---|
| `DashboardApi` | /dashboard/summary, /positions, /trades, /charts, /accounts | ~120줄 |
| `TradingApi` | /api/trading/status, /start, /stop | ~60줄 |
| `NewsApi` | /api/news/*, /api/news/collect-and-send | ~80줄 |
| `MacroApi` | /api/macro/* | ~100줄 |
| `RiskApi` | /api/risk/*, /emergency/* | ~90줄 |
| `StrategyApi` | /strategy/params, /strategy/ticker-params, /backtest | ~80줄 |
| `AnalysisApi` | /api/analysis/*, /api/indicators/* | ~90줄 |
| `UniverseApi` | /universe/*, /crawl/* | ~100줄 |
| `ReportApi` | /reports/*, /feedback/*, /benchmark/* | ~100줄 |
| `ManualTradeApi` | /api/manual-trade/analyze, /execute | ~60줄 |
| `PrinciplesApi` | /principles/* | ~80줄 |
| `AgentApi` | /agents/list, /agents/{id} | ~70줄 |
| `SystemApi` | /system/status, /system/usage, /health | ~60줄 |
| `TaxFxApi` | /tax/*, /fx/*, /slippage/* | ~90줄 |

### 디렉터리 구조

```
dashboard/lib/services/
  ├── base_api_client.dart        ← BaseApiClient (공통 HTTP + 인증)
  ├── websocket_service.dart      ← WebSocketClient (현행 유지)
  ├── server_launcher.dart        ← ServerLauncher (현행 유지)
  └── api/
      ├── dashboard_api.dart
      ├── trading_api.dart
      ├── news_api.dart
      ├── macro_api.dart
      ├── risk_api.dart
      ├── strategy_api.dart
      ├── analysis_api.dart
      ├── universe_api.dart
      ├── report_api.dart
      ├── manual_trade_api.dart
      ├── principles_api.dart
      ├── agent_api.dart
      ├── system_api.dart
      └── tax_fx_api.dart
```

---

## F10.2 WebSocketClient

| 항목 | 내용 |
|---|---|
| **현재 파일** | `dashboard/lib/services/websocket_service.dart` (189줄) |
| **IN** | ws_url: String, reconnect_config: ReconnectConfig |
| **OUT** | Stream<WebSocketMessage> (positions, trades, crawl, alerts, realtime-tape) |
| **상태** | 적절한 크기 — 타입 안전성 강화 개선 |

### 개선 사항

```dart
/// 재연결 상태를 UI에 노출한다 — 사용자가 연결 상태를 인지할 수 있다.
enum WsConnectionState { connecting, connected, reconnecting, disconnected }

class WebSocketService extends ChangeNotifier {
  WsConnectionState get connectionState => _connectionState;

  // 구독 채널별 타입 안전 스트림
  Stream<PositionUpdate> get positionUpdates => ...;
  Stream<TradeEvent> get tradeEvents => ...;
  Stream<AlertEvent> get alertEvents => ...;
}
```

---

## F10.3 Providers (도메인별)

| 항목 | 내용 |
|---|---|
| **현재 파일 수** | 28개 provider (총 3,393줄) |
| **최대 위반** | `trading_control_provider.dart` (510줄) |

### TradingControlProvider 분리

```dart
// 현재: trading_control_provider.dart (510줄)
// 서버 실행 로직(ServerLauncher 호출)과 매매 제어 로직이 혼재

// 분리:
// TradingControlProvider (매매 start/stop/status, ~150줄)
// ServerStatusProvider  (서버 실행 여부 확인, ~80줄)
```

### 적절한 크기 Provider (현행 유지)

| Provider | 줄 수 | 상태 |
|---|---|---|
| `news_provider.dart` | 319줄 | 경계선 — 필터 로직 분리 권장 |
| `crawl_progress_provider.dart` | 279줄 | 유지 |
| `dashboard_provider.dart` | 220줄 | 유지 |
| 나머지 24개 | 27~180줄 | 모두 적절 |

---

## F10.4 Screens (위젯 추출)

| 항목 | 내용 |
|---|---|
| **현재 상태** | 28개 스크린, 다수 1,000줄 초과 |
| **목표** | 각 스크린 300줄 이하, 나머지는 위젯으로 추출 |

### 위젯 추출 우선순위

| 스크린 | 현재 줄 수 | 추출 위젯 |
|---|---|---|
| `news_screen.dart` | 1,963줄 | NewsListWidget, NewsFilterBar, NewsArticleDetail, NewsSummaryPanel |
| `overview_screen.dart` | 1,919줄 | PortfolioSummaryCard, SystemStatusCard, PositionListCard, RecentTradesCard |
| `universe_screen.dart` | 1,827줄 | UniverseTickerList, SectorHeatmap, CrawlerStatusPanel |
| `home_dashboard.dart` | 1,754줄 | HomeStatsGrid, PositionCards, QuickActionPanel, AlertBanner |
| `stock_analysis_screen.dart` | 1,719줄 | AnalysisResultCard, TechnicalIndicatorPanel, AIAnalysisPanel |
| `trade_reasoning_screen.dart` | 1,587줄 | ReasoningTimeline, AccuracyStats, FeedbackButton |
| `rsi_screen.dart` | 1,429줄 | RsiChartView, TechnicalSummaryPanel, TickerSelectorBar |
| `principles_screen.dart` | 1,223줄 | PrincipleCard, PrincipleCategoryFilter, PrincipleEditor |
| `settings_screen.dart` | 1,046줄 | SettingsSection, EnvConfigForm, ThemeSwitcher |
| `risk_center_screen.dart` | 1,032줄 | RiskGateStatusList, BudgetProgressBar, EmergencyPanel |
| `manual_trade_screen.dart` | 1,030줄 | AnalysisInputForm, AnalysisResultPanel, OrderConfirmDialog |
| `ticker_params_screen.dart` | 1,029줄 | TickerParamCard, BulkEditPanel, ParamHistoryChart |

### 위젯 디렉터리 구조 (목표)

```
dashboard/lib/widgets/
  ├── common/               ← 전역 공통 (glass_card, stat_card, section_header, ...)
  ├── dashboard/            ← HomeStatsGrid, PositionCards, QuickActionPanel
  ├── news/                 ← NewsListWidget, NewsFilterBar, NewsArticleDetail
  ├── overview/             ← PortfolioSummaryCard, SystemStatusCard
  ├── analysis/             ← AnalysisResultCard, TechnicalIndicatorPanel
  ├── universe/             ← UniverseTickerList, SectorHeatmap
  ├── risk/                 ← RiskGateStatusList, BudgetProgressBar
  └── settings/             ← SettingsSection, EnvConfigForm
```

---

## F10.5 Models (순수 Dart)

| 항목 | 내용 |
|---|---|
| **현재 파일 수** | 22개 모델 (총 5,175줄) |
| **최대 파일** | `dashboard_models.dart` (535줄), `risk_models.dart` (495줄) |

### Flutter Color 의존성 제거

```dart
// 현재 문제: news_models.dart, stock_analysis_models.dart에 Flutter Color 참조
// 모델은 순수 Dart여야 한다 — 비즈니스 데이터만 보유

// 잘못된 예
class NewsItem {
  Color get sentimentColor => ... // Flutter 의존성 금지
}

// 올바른 예
class NewsItem {
  String sentiment; // "positive" | "negative" | "neutral"
  // Color는 Extension 또는 UI Helper에서 처리
}

// 별도 UI Helper
extension NewsItemUi on NewsItem {
  Color get sentimentColor => ... // UI 레이어에서만 사용
}
```

### 분리 권장 모델

| 파일 | 현재 줄 | 분리 방안 |
|---|---|---|
| `dashboard_models.dart` | 535줄 | PositionModels + TradeModels + SummaryModels |
| `risk_models.dart` | 495줄 | RiskGateModels + BudgetModels + EmergencyModels |
| `stock_analysis_models.dart` | 469줄 | AnalysisResultModels + TechnicalModels (Color 의존 제거) |

---

## F10.6 Theme & Design Tokens

| 항목 | 내용 |
|---|---|
| **현재 파일 수** | 7개 테마 파일 (적절) |
| **TradingColors** | 29개 커스텀 컬러 토큰 (다크/라이트 분리) |

### 현행 테마 파일

| 파일 | 역할 |
|---|---|
| `app_colors.dart` | 기본 컬러 팔레트 (semantic colors) |
| `app_spacing.dart` | 여백 토큰 (xs, sm, md, lg, xl) |
| `app_theme.dart` | ThemeData 생성 (light/dark) |
| `app_typography.dart` | 텍스트 스타일 토큰 |
| `chart_colors.dart` | 차트 전용 컬러 (up/down/neutral) |
| `domain_colors.dart` | 도메인별 컬러 (buy/sell/hold/regime) |
| `trading_colors.dart` | 매매 UI 전용 컬러 29개 |

### 개선 사항 (하드코딩 제거)

```dart
// 금지: 스크린 내 직접 Color 값 사용
Container(color: Color(0xFF1A1A2E))

// 권장: 테마 토큰 사용
Container(color: Theme.of(context).extension<TradingColors>()!.background)
```

---

---

# CROSS-CHECK: 전체 기능/로직/에이전트 누락 검증

현행 코드베이스의 모든 파일이 신규 설계(F1~F10 + Core)에 매핑되는지 검증한다.

---

## Python Backend (src/)

| 현재 파일/모듈 | 매핑된 신규 모듈 | 상태 |
|---|---|---|
| `src/main.py` (3,255줄) | F9.1 SystemInitializer + F9.2 DI + F9.4 TradingLoop + F9.7 EOD + F9.8 Shutdown | ✅ 분리됨 |
| `src/analysis/classifier.py` | F2.1 NewsClassifier | ✅ |
| `src/analysis/claude_client.py` | C0.5 AiGateway | ✅ |
| `src/analysis/comprehensive_team.py` | F2.3 ComprehensiveTeam | ✅ |
| `src/analysis/decision_maker.py` | F2.4 DecisionMaker | ✅ |
| `src/analysis/overnight_judge.py` | F2.5 OvernightJudge | ✅ |
| `src/analysis/regime_detector.py` | F2.2 RegimeDetector | ✅ |
| `src/analysis/prompts.py` (1,896줄) | F2.7 PromptRegistry (5개로 분리) | ✅ |
| `src/analysis/key_news_filter.py` | F2.9 KeyNewsFilter | ✅ |
| `src/analysis/eod_feedback_report.py` | F2.10 EODFeedbackReport | ✅ |
| `src/analysis/news_theme_tracker.py` | F2.11 NewsThemeTracker | ✅ |
| `src/analysis/ai_context_builder.py` | F2.3 내부 Atom | ✅ |
| `src/crawler/` (24개 파일) | F1.1~F1.7 | ✅ |
| `src/db/connection.py` | C0.2 DatabaseGateway | ✅ |
| `src/db/models.py` | C0.2 내 models/ 분리 | ✅ |
| `src/executor/kis_auth.py` | C0.6 KISGateway 내 AuthManager | ✅ |
| `src/executor/kis_client.py` | C0.6 KISGateway 내 KISClient | ✅ |
| `src/executor/order_manager.py` | F5.3 OrderManager | ✅ |
| `src/executor/position_monitor.py` | F5.4 PositionMonitor | ✅ |
| `src/executor/universe_manager.py` | F5.5 UniverseManager | ✅ |
| `src/executor/account_mode_manager.py` | F5.6 AccountModeManager | ✅ |
| `src/fallback/fallback_router.py` | C0.5 AiGateway 내 FallbackRouter | ✅ |
| `src/feedback/daily_feedback.py` (456줄) | F8 지원 모듈, F9.7 EOD에서 호출 | ✅ |
| `src/feedback/param_adjuster.py` (367줄) | F8.9 ExecutionOptimizer와 통합 검토 | ✅ |
| `src/feedback/rag_doc_updater.py` (407줄) | F8.10 KnowledgeManager 연동 | ✅ |
| `src/feedback/time_performance.py` (551줄) | F7.16 PerformanceEndpoints에서 사용, 분리 권장 | ⚠️ 분리 필요 |
| `src/feedback/weekly_analysis.py` (409줄) | F8 지원 모듈, F9.7 EOD에서 호출 | ✅ |
| `src/feedback/execution_optimizer/trade_analyzer.py` (299줄) | F8.9 — 분리 권장 | ⚠️ 분리 권장 |
| `src/feedback/execution_optimizer/param_tuner.py` (284줄) | F8.9 — 분리 권장 | ⚠️ 분리 권장 |
| `src/feedback/execution_optimizer/param_writer.py` (192줄) | F8.9 | ✅ |
| `src/feedback/execution_optimizer/runner.py` (144줄) | F8.9 | ✅ |
| `src/feedback/execution_optimizer/config.py` (51줄) | F8.9 | ✅ |
| `src/filter/` (필터 설정) | F1.4 CrawlVerifier 내 통합 | ✅ |
| `src/indicators/cross_asset/` | F3 CrossAssetMomentum | ✅ |
| `src/indicators/volume_profile/` | F3 VolumeProfile | ✅ |
| `src/indicators/whale/` | F3 WhaleTracker | ✅ |
| `src/indicators/contango_detector.py` | F3 ContangoDetector | ✅ |
| `src/indicators/nav_premium.py` | F3 NAVPremiumTracker | ✅ |
| `src/macro/net_liquidity.py` | F7.5 MacroEndpoints 내 NetLiquidityTracker | ✅ |
| `src/monitoring/api_server.py` (666줄) | F7.1 ApiServer | ✅ 분리 필요 |
| `src/monitoring/dashboard_endpoints.py` (1,840줄) | F7.2 DashboardEndpoints (8개 라우터) | ✅ 분리 필요 |
| `src/monitoring/analysis_endpoints.py` (918줄) | F7.3 AnalysisEndpoints | ✅ 분리 필요 |
| `src/monitoring/trading_control_endpoints.py` (221줄) | F7.4 TradingControlEndpoints | ✅ |
| `src/monitoring/macro_endpoints.py` (569줄) | F7.5 MacroEndpoints | ✅ 분리 필요 |
| `src/monitoring/news_endpoints.py` (419줄) | F7.6 NewsEndpoints | ✅ |
| `src/monitoring/news_collect_endpoints.py` (330줄) | F7.6 NewsEndpoints (통합) | ✅ |
| `src/monitoring/universe_endpoints.py` (1,048줄) | F7.7 UniverseEndpoints (3개 라우터) | ✅ 분리 필요 |
| `src/monitoring/emergency_endpoints.py` (491줄) | F7.8 EmergencyEndpoints | ✅ |
| `src/monitoring/benchmark_endpoints.py` (393줄) | F7.9 BenchmarkEndpoints | ✅ |
| `src/monitoring/benchmark.py` (421줄) | F7.9 BenchmarkComparison 구현체 | ✅ |
| `src/monitoring/trade_reasoning_endpoints.py` (522줄) | F7.10 TradeReasoningEndpoints | ✅ |
| `src/monitoring/indicator_endpoints.py` (388줄) | F7.11 IndicatorEndpoints | ✅ |
| `src/monitoring/manual_trade_endpoints.py` (523줄) | F7.12 ManualTradeEndpoints | ✅ |
| `src/monitoring/principles_endpoints.py` (355줄) | F7.13 PrinciplesEndpoints | ✅ |
| `src/monitoring/agent_endpoints.py` (394줄) | F7.14 AgentEndpoints | ✅ |
| `src/monitoring/system_endpoints.py` (152줄) | F7.15 SystemEndpoints | ✅ |
| `src/monitoring/performance_endpoints.py` (88줄) | F7.16 PerformanceEndpoints | ✅ |
| `src/monitoring/order_flow_endpoints.py` (160줄) | F7.17 OrderFlowEndpoints | ✅ |
| `src/monitoring/telegram_notifier.py` (717줄) | F7.19 TelegramNotifier | ✅ 분리 필요 |
| `src/monitoring/indicator_crawler.py` (661줄) | F7.20 IndicatorCrawler | ✅ 분리 필요 |
| `src/monitoring/fred_client.py` (674줄) | F7.5 + F7.20 공유 인프라 (C0.4 HttpGateway 통합) | ✅ |
| `src/monitoring/daily_report.py` (484줄) | F7.2 feedback_router에서 사용 | ✅ |
| `src/monitoring/live_readiness.py` (424줄) | F9.3 PreparationPhase에서 사용 | ✅ |
| `src/monitoring/calendar_helpers.py` (266줄) | F7.5 MacroEndpoints 지원 Atom | ✅ |
| `src/monitoring/realtime_tape.py` (247줄) | F7.17 OrderFlow 또는 F7.18 WebSocket 지원 | ✅ |
| `src/monitoring/alert.py` (293줄) | F7.2 alert_router 지원 | ✅ |
| `src/monitoring/account_mode.py` (117줄) | F5.6 AccountModeManager 지원 | ✅ |
| `src/monitoring/schemas.py` (315줄) | F7 공통 Pydantic 스키마 | ✅ |
| `src/monitoring/trade_endpoints.py` (354줄) | F7.2 summary_router에 통합 | ✅ |
| `src/monitoring/auth.py` | F7.1 ApiServer 미들웨어 | ✅ |
| `src/optimization/data_preparer.py` (289줄) | F8.1 DataPreparer | ✅ |
| `src/optimization/feature_engineer.py` (260줄) | F8.2 FeatureEngineer | ✅ |
| `src/optimization/target_builder.py` (113줄) | F8.3 TargetBuilder | ✅ |
| `src/optimization/lgbm_trainer.py` (235줄) | F8.4 LGBMTrainer | ✅ |
| `src/optimization/optuna_optimizer.py` (213줄) | F8.5 OptunaOptimizer | ✅ |
| `src/optimization/walk_forward.py` (351줄) | F8.6 WalkForward | ✅ 분리 필요 |
| `src/optimization/auto_trainer.py` (299줄) | F8.7 AutoTrainer | ✅ |
| `src/optimization/time_travel.py` (373줄) | F8.8 TimeTravelTrainer | ✅ 분리 필요 |
| `src/optimization/config.py` (124줄) | F8 설정 Atom | ✅ |
| `src/optimization/models.py` (106줄) | F8 도메인 모델 | ✅ |
| `src/orchestration/preparation.py` (329줄) | F9.3 PreparationPhase | ✅ |
| `src/orchestration/trading_loop.py` (395줄) | F9.4 TradingLoop | ✅ |
| `src/orchestration/continuous_analysis.py` (278줄) | F9.5 ContinuousAnalysis | ✅ |
| `src/orchestration/news_pipeline.py` (384줄) | F9.6 NewsPipeline | ✅ |
| `src/psychology/` (6개 파일) | F6.15 TiltDetector + TiltEnforcer + LossTracker | ✅ |
| `src/rag/` (5개 파일) | F8.10 KnowledgeManager | ✅ |
| `src/risk/` (22개 파일) | F6.5~F6.17 리스크 모듈 | ✅ |
| `src/safety/` (9개 파일) | F6.1~F6.4, F6.12, F6.13, F6.18, F6.19 안전장치 | ✅ |
| `src/scalping/liquidity/` | F3.8 VolumeProfile로 통합 | ✅ 통합 확인 필요 |
| `src/scalping/spoofing/` | F3.9 WhaleTracker 내 SpoofingDetector | ✅ 통합 확인 필요 |
| `src/scalping/time_stop/` | F4.2 ExitStrategy 내 TimeStop | ✅ 통합 확인 필요 |
| `src/scalping/manager.py` | F9.4 TradingLoop 내 스캘핑 모드 | ✅ 통합 확인 필요 |
| `src/strategy/` (40개 파일) | F4.1~F4.14 전략 모듈 | ✅ |
| `src/tax/` (4개 파일) | F7.2 tax_fx_router 지원 | ✅ |
| `src/telegram/` (7개 파일) | C0.7 TelegramGateway + F7.19 TelegramNotifier | ✅ |
| `src/utils/` (5개 파일) | C0.1 ConfigProvider, C0.8 Logger, C0.11 MarketClock | ✅ |
| `src/websocket/` (총 22개 파일) | F7.18 WebSocketManager | ✅ |
| `src/ai/` (3개 파일) | C0.5 AiGateway + F8.10 KnowledgeManager | ✅ |

---

## Flutter Dashboard (dashboard/lib/)

| 현재 파일/그룹 | 매핑된 신규 모듈 | 상태 |
|---|---|---|
| `services/api_service.dart` (1,544줄) | F10.1 (14개 도메인 ApiClient + BaseApiClient) | ✅ 분리 필요 |
| `services/websocket_service.dart` (189줄) | F10.2 WebSocketClient | ✅ |
| `services/server_launcher.dart` | F10.3 ServerStatusProvider 분리 | ✅ |
| `providers/trading_control_provider.dart` (510줄) | F10.3 → TradingControlProvider + ServerStatusProvider 분리 | ✅ 분리 필요 |
| `providers/news_provider.dart` (319줄) | F10.3 — 경계선, 필터 로직 분리 권장 | ⚠️ 분리 권장 |
| `providers/crawl_progress_provider.dart` (279줄) | F10.3 | ✅ |
| `providers/dashboard_provider.dart` (220줄) | F10.3 | ✅ |
| `providers/` (나머지 24개, 27~180줄) | F10.3 | ✅ 모두 적절 |
| `screens/news_screen.dart` (1,963줄) | F10.4 → NewsListWidget 등 4개 위젯 추출 | ✅ 분리 필요 |
| `screens/overview_screen.dart` (1,919줄) | F10.4 → 4개 위젯 추출 | ✅ 분리 필요 |
| `screens/universe_screen.dart` (1,827줄) | F10.4 → 3개 위젯 추출 | ✅ 분리 필요 |
| `screens/home_dashboard.dart` (1,754줄) | F10.4 → 4개 위젯 추출 | ✅ 분리 필요 |
| `screens/stock_analysis_screen.dart` (1,719줄) | F10.4 → 3개 위젯 추출 | ✅ 분리 필요 |
| `screens/trade_reasoning_screen.dart` (1,587줄) | F10.4 → 3개 위젯 추출 | ✅ 분리 필요 |
| `screens/rsi_screen.dart` (1,429줄) | F10.4 → 3개 위젯 추출 | ✅ 분리 필요 |
| `screens/` (나머지 21개) | F10.4 | 일부 분리 필요 |
| `models/dashboard_models.dart` (535줄) | F10.5 → 3개 모델 파일 분리 | ✅ 분리 필요 |
| `models/risk_models.dart` (495줄) | F10.5 → 3개 모델 파일 분리 | ✅ 분리 필요 |
| `models/stock_analysis_models.dart` (469줄) | F10.5 → Color 의존성 제거 + 분리 | ✅ 수정 필요 |
| `models/news_models.dart` (379줄) | F10.5 → Color 의존성 제거 | ✅ 수정 필요 |
| `models/` (나머지 18개) | F10.5 | ✅ 적절 |
| `theme/` (7개 파일) | F10.6 Theme & Design Tokens | ✅ |
| `widgets/` (28개 파일) | F10.4 공통 위젯 — 도메인별 서브디렉터리로 재구성 | ✅ 재구성 필요 |
| `constants/api_constants.dart` | F10.1 BaseApiClient 내 URL 상수 | ✅ |
| `l10n/app_strings.dart` | F10 l10n (현행 유지) | ✅ |
| `utils/env_loader.dart` | F10 utils (현행 유지) | ✅ |
| `animations/animation_utils.dart` | F10 animations (현행 유지) | ✅ |

---

## 설정 파일

| 파일 | 매핑 | 상태 |
|---|---|---|
| `.env` | C0.1 ConfigProvider | ✅ |
| `strategy_params.json` | C0.1 + F4.10 StrategyParams | ✅ |
| `data/ticker_params.json` | C0.12 + F4.11 TickerParams | ✅ |
| `data/trading_principles.json` | F7.13 PrinciplesEndpoints | ✅ |
| `src/filter/filter_config.json` | C0.1 + F1.4 CrawlVerifier | ✅ |
| `docker-compose.yml` | Infrastructure (변경 없음) | ✅ |
| `scripts/` | F9 Orchestration + Infrastructure | ✅ |
| `db/init.sql` | C0.2 DatabaseGateway | ✅ |

---

## 누락 검증 결과 요약

### 완전 매핑 확인됨
모든 파일이 신규 모듈(F1~F10 + Core C0.x)에 매핑된다.

### 분리 작업 우선순위

| 우선순위 | 파일 | 이유 |
|---|---|---|
| P0 (즉시) | `src/main.py` (3,255줄) | 시스템 최대 위반, F9.1~F9.8로 분리 |
| P0 (즉시) | `dashboard_endpoints.py` (1,840줄) | 8개 라우터로 분리 |
| P0 (즉시) | `services/api_service.dart` (1,544줄) | 14개 도메인 클라이언트로 분리 |
| P1 | `universe_endpoints.py` (1,048줄) | 3개 라우터로 분리 |
| P1 | `analysis_endpoints.py` (918줄) | 2개 라우터 + 서비스 레이어 |
| P1 | `telegram_notifier.py` (717줄) | 포매터 Atom 분리 |
| P1 | `api_server.py` (666줄) | DI 컨테이너 패턴으로 전환 |
| P2 | 대형 Flutter 스크린 7개 (1,400줄+) | 위젯 추출 |
| P2 | `time_performance.py` (551줄) | 분석기 3개 분리 |
| P3 | `time_travel.py` + `walk_forward.py` | 내부 Atom 추출 |
| P3 | 모델 파일 Color 의존성 제거 | 순수 Dart 달성 |

### 추가 확인 필요 항목
1. `src/scalping/liquidity/` → F3.8 VolumeProfile 통합 시 인터페이스 호환성 확인
2. `src/scalping/spoofing/` → F3.9 WhaleTracker 내 SpoofingDetector 위치 확정
3. `src/scalping/time_stop/` → F4.2 ExitStrategy 내 통합 방식 확정
4. `src/scalping/manager.py` → F9.4 TradingLoop 스캘핑 모드 분기 방식 확정
5. `src/feedback/param_adjuster.py` vs `src/feedback/execution_optimizer/param_tuner.py` → 중복 로직 통합 여부 결정
