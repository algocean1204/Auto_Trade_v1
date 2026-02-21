# AI 자동매매 시스템 V2 - Claude Leader 레퍼런스

> 작성 일시: 2026-02-21
> 최종 갱신: 2026-02-21
> 대상 프로젝트: /Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading

이 문서는 AI 자동매매 시스템 V2의 전체 구조를 코드 기반으로 정리한 종합 레퍼런스이다. 모든 클래스명, 함수명, 시그니처는 실제 소스 코드에서 직접 확인한 것이다.

---

## 1. 프로젝트 개요

미국 2X 레버리지 ETF 자동매매 AI 시스템이다. KIS(한국투자증권) OpenAPI를 통해 실제 주문을 실행하고, Claude Opus/Sonnet AI가 매매 판단을 수행한다. MLX 기반 로컬 AI(Qwen3-30B-A3B)로 뉴스 분류를 처리하고, 31개 뉴스 소스에서 크롤링한 데이터를 분석한다. Claude Sonnet으로 핵심뉴스 한국어 번역 및 4단계 중요도 분류(critical/high/medium/low)를 수행한다.

| 항목 | 내용 |
|------|------|
| 프로젝트 타입 | Python 백엔드 + Flutter macOS Desktop 대시보드 |
| 실행 환경 | MacBook Pro M4 Pro 48GB RAM, macOS |
| Python 소스 | 145개 파일, 53,107줄 (src/) |
| Dart 소스 | 112개 파일, 42,317줄 (dashboard/lib/) |
| 테스트 | Python 43개 (19,021줄), Flutter 11개 |
| 총 코드 규모 | ~114,445줄 |
| DB | PostgreSQL 17 + pgvector (1024차원) + Redis 7 |
| AI | Claude Opus/Sonnet (local CLI / API) + MLX Qwen3-30B-A3B |
| 브로커 | KIS OpenAPI (한국투자증권) - 모의/실전 듀얼 모드 |
| 운영 시간 | 매일 22:00/23:00~07:00 KST (야간 매매, 서머타임 기준 변동) |

---

## 2. 실행 흐름 (전체 타임라인)

```
23:00 KST ──── LaunchAgent 기동 → auto_trading.sh 실행
   │            네트워크 확인 → Docker(PostgreSQL+Redis) 시작 → venv 활성화
   ▼
23:00~23:01 ── TradingSystem 초기화 (40+ 모듈 인스턴스 생성)
   │            DB/Redis/KIS 연결 → FastAPI 서버(포트 8000) 백그라운드 시작
   ▼
23:01 ──────── POST /api/trading/start → main_loop() 시작
   │            텔레그램 시작 알림 + 양방향 봇 가동
   ▼
23:01~23:59 ── 준비 단계 (10단계, ~60분)
   │            인프라 점검 → 전체 크롤링(31소스) → 검증 → 분류 → 레짐 분석 → 안전 점검
   ▼
23:00~06:30 ── 연속 분석 (30분 주기)
   │            delta 크롤링 → Tier 크롤링 → 분류 → Opus 이슈 분석 → Redis 저장
   ▼
22:30/23:30 ── 정규장 개장 → 15분 주기 트레이딩 루프 (7단계)
   │            크롤 → 분류 → 리스크 게이트 → AI 판단 → 실행 → 모니터링
   ▼
05:00/06:00 ── 정규장 마감 → EOD 단계 (10단계)
   │            오버나잇 판단 → 일일 피드백 → 벤치마크 → 보고서 → 리스크 리셋
   ▼
06:30 KST ──── 자동 종료 (_auto_stop_triggered=True)
               running=False → EOD 시퀀스 → 텔레그램 종료 알림 → shutdown()
```

### 2.1 세션 타입별 동작

| 세션 | 동작 | 주기 |
|------|------|------|
| `regular` (정규장) | 7단계 트레이딩 루프 | 15분 (`_TRADING_LOOP_SLEEP=900`) |
| `pre_market` / `after_market` | 포지션 모니터링만 | 30분 (`_MONITOR_ONLY_SLEEP=1800`) |
| `closed` (장 외) | EOD 실행 + 대기 | 동적 계산 |

### 2.2 주요 타이밍 상수 (src/main.py)

| 상수명 | 값 | 설명 |
|--------|-----|------|
| `_TRADING_LOOP_SLEEP` | 900초 (15분) | 정규 매매 루프 주기 |
| `_POSITION_MONITOR_SLEEP` | 300초 (5분) | 정규장 포지션 모니터링 주기 |
| `_MONITOR_ONLY_SLEEP` | 1800초 (30분) | 비정규 세션 모니터링 주기 |
| `_CONTINUOUS_ANALYSIS_INTERVAL` | 1800초 (30분) | 연속 분석 주기 |
| `_PREP_CHECK_INTERVAL` | 3600초 (1시간) | 준비 단계 재확인 간격 |
| `_SHUTDOWN_GRACE_PERIOD` | 2.0초 | API 서버 시작 대기 |
| `_SHUTDOWN_TIMEOUT` | 15.0초 | 시스템 종료 최대 대기 |
| `_PRICE_HISTORY_DAYS` | 200 | 기술적 지표 계산 기간 (영업일) |
| `_REGIME_CACHE_TTL` | 300초 (5분) | Redis 레짐 캐시 만료 |
| `_DOCKER_CHECK_TIMEOUT` | 5.0초 | Docker 상태 확인 타임아웃 |

### 2.3 VIX 기반 레짐 임계값

| 상수명 | 값 | 레짐 |
|--------|-----|------|
| `_VIX_STRONG_BULL` | 15.0 | VIX < 15 → strong_bull |
| `_VIX_MILD_BULL` | 20.0 | 15 <= VIX < 20 → mild_bull |
| `_VIX_SIDEWAYS` | 25.0 | 20 <= VIX < 25 → sideways |
| `_VIX_MILD_BEAR` | 30.0 | 25 <= VIX < 30 → mild_bear |
| (>=30) | - | VIX >= 30 → crash |
| `_VIX_DEFAULT_FALLBACK` | 20.0 | VIX 조회 실패 시 기본값 |

---

## 3. AI 모델 아키텍처

### 3.1 모델 정의 (src/analysis/claude_client.py)

```python
class ModelType(Enum):
    SONNET = "claude-sonnet-4-5-20250929"
    OPUS = "claude-opus-4-6"
```

### 3.2 태스크별 모델 라우팅 (MODEL_ROUTING)

| 태스크 키 | 모델 | 용도 |
|-----------|------|------|
| `news_classification` | Sonnet | 뉴스 분류 (빠름) |
| `news_translation` | Sonnet | 뉴스 한국어 번역 (배치 10건) |
| `delta_analysis` | Sonnet | 델타 분석 |
| `crawl_verification` | Sonnet | 크롤링 품질 검증 |
| `telegram_intent` | Sonnet | 텔레그램 의도 분석 |
| `telegram_chat` | Sonnet | 텔레그램 대화 + 번역 라우팅용 |
| `historical_market` | Sonnet | 과거 시장 분석 (비용 효율) |
| `historical_company` | Sonnet | 과거 기업 분석 |
| `historical_sector` | Sonnet | 과거 섹터 분석 |
| `historical_timeline` | Sonnet | 과거 타임라인 분석 |
| `trading_decision` | **Opus** | 매매 판단 (정확도 최우선) |
| `overnight_judgment` | **Opus** | 오버나잇 보유 판단 |
| `regime_detection` | **Opus** | 시장 레짐 감지 |
| `daily_feedback` | **Opus** | 일일 피드백 |
| `weekly_analysis` | **Opus** | 주간 분석 |
| `monthly_review` | **Opus** | 월간 리뷰 |
| `continuous_analysis` | **Opus** | 연속 분석 |
| `realtime_stock_analysis` | **Opus** | 실시간 종목 분석 |
| `comprehensive_macro` | **Opus** | 종합분석 - 매크로 |
| `comprehensive_technical` | **Opus** | 종합분석 - 기술 |
| `comprehensive_sentiment` | **Opus** | 종합분석 - 심리 |
| `comprehensive_leader` | **Opus** | 종합분석 - 리더 |
| `comprehensive_eod_report` | **Opus** | 종합분석 - EOD 보고서 |

### 3.3 ClaudeClient 클래스

소스: `src/analysis/claude_client.py` (649줄)

```python
class ClaudeClient:
    def __init__(self, mode="local", api_key=None, max_retries=3, cache_max_size=128, cache_ttl=300)
    async def call(self, prompt, task_type, system_prompt=None, max_tokens=4096, temperature=0.3, use_cache=True) -> dict
    async def call_json(self, prompt, task_type, system_prompt=None, max_tokens=4096, use_cache=True) -> dict | list
    async def _call_local(self, prompt, system_prompt, model, max_tokens, temperature) -> dict
    async def _call_with_retry(self, kwargs, task_type) -> object
    def get_usage_stats(self) -> dict
    def clear_cache(self) -> None
    def _extract_json(self, content) -> dict | list
```

- `_LRUCache`: TTL 기반 LRU 캐시 (기본 128항목, 300초 TTL)
- local 모드: `claude --print --model <model> --output-format text` CLI subprocess 호출
- api 모드: `anthropic.AsyncAnthropic` SDK 직접 호출 + 지수 백오프 재시도
- JSON 파싱 시 단계별 debug 로그 출력 (파싱 실패 디버깅용)
- 캐시 키 충돌 시 warning 로그 출력

### 3.4 시스템 프롬프트 (src/analysis/prompts.py)

| 프롬프트 | 설명 |
|----------|------|
| `MASTER_ANALYST_SYSTEM_PROMPT` | 5대 투자대가 페르소나 (Dalio, Soros, Druckenmiller, Simons, Jones) + 생존 매매 원칙 |
| `NEWS_ANALYST` | 뉴스 분류/영향 분석 전문 |
| `RISK_MANAGER` | 리스크 평가 전문 |
| `MACRO_STRATEGIST` | 거시경제 전략 전문 |

### 3.5 로컬 AI

| 모듈 | 클래스 | 설명 |
|------|--------|------|
| `src/ai/mlx_classifier.py` | `MLXClassifier` | Qwen3-30B-A3B MLX 추론 (뉴스 분류/감성분석) |
| `src/ai/knowledge_manager.py` | `KnowledgeManager` | ChromaDB + BGE-M3 RAG 지식 관리 |

---

## 4. 모듈 상세

### 4.1 오케스트레이터 (src/main.py)

**클래스**: `TradingSystem` (2,438줄)

**주요 메서드**:
| 메서드 | 설명 |
|--------|------|
| `__init__()` | 40+ 모듈 인스턴스 변수 초기화 (모두 None) |
| `initialize()` | 모든 모듈 비동기 초기화 → set_dependencies() |
| `shutdown()` | 안전 종료 (텔레그램→봇→API서버→KIS→DB→Redis) |
| `start_trading()` | running=True, main_loop() 태스크 생성 |
| `stop_trading(run_eod)` | running=False, EOD 옵션 실행 |
| `get_trading_status()` | 현재 매매 상태 딕셔너리 반환 |
| `main_loop()` | 메인 무한 루프 (세션별 분기) |
| `start_api_server()` | uvicorn 백그라운드 실행 |
| `run_preparation_phase()` | 10단계 준비 (orchestration 위임) |
| `run_trading_loop_iteration()` | 7단계 매매 루프 (orchestration 위임) |
| `run_eod_phase()` | EOD 10단계 |
| `run_weekly_analysis()` | 주간 분석 (일요일) |
| `run_continuous_crawl_analysis()` | 30분 연속 분석 (orchestration 위임) |
| `_get_current_regime()` | VIX 기반 레짐 판정 (Redis 캐시 5분) |
| `_fetch_vix()` | FRED VIXCLS 조회 (실패 시 기본값 20.0) |
| `_execute_decisions()` | AI 매매 결정 실행 |
| `_send_final_daily_report()` | 텔레그램 종합 보고서 + markdown 파일 |
| `_check_infrastructure()` | Docker/DB/Redis/KIS 인프라 점검 |
| `_check_live_readiness()` | 실전 전환 준비도 7가지 기준 평가 |

**Runtime State 변수**:
| 변수 | 타입 | 설명 |
|------|------|------|
| `running` | `bool` | 매매 루프 실행 플래그 |
| `_auto_stop_triggered` | `bool` | 06:30 KST 자동 종료 플래그 |
| `_control_lock` | `asyncio.Lock` | start/stop 동시 호출 방지 |
| `_continuous_analysis_iteration` | `int` | 연속 분석 반복 카운터 |
| `_continuous_analysis_previous_issues` | `str` | 이전 분석 이슈 요약 |
| `_today_decisions` | `list[dict]` | 금일 매매 결정 누적 |

### 4.2 오케스트레이션 모듈

#### 4.2.1 준비 단계 (src/orchestration/preparation.py)

**함수**: `run_preparation_phase(ts: TradingSystem)`

10단계: 인프라 점검 → 전체 크롤링(31소스) → Fear&Greed 수집 → 크롤링 검증(Sonnet) → 뉴스 분류+요약(Sonnet, 20건) → 시장 레짐 분석(Opus) → 계좌 안전 점검 → 환율 기록 → 리스크 백테스트 → 수익 목표 갱신 → 안전 점검

#### 4.2.2 트레이딩 루프 (src/orchestration/trading_loop.py)

**함수**: `run_trading_loop_iteration(ts: TradingSystem)` (328줄)

7단계 (+ 0단계 Circuit Breaker):
0. 긴급 프로토콜 체크 (VIX + SPY 변동) → 발동 시 전체 건너뜀
1. Delta 크롤링 + Tier 소스 실시간 데이터
2. 뉴스 분류 (Sonnet)
3. 리스크 게이트 사전 점검 (6개 게이트)
4. 매매 판단 (Opus) - DecisionMaker
5. 매매 실행 - OrderManager
6. 포지션 모니터링 - PositionMonitor
7. 트레일링 스톱 체크

**에러 처리 변경**: SPY 폴백 값 -3.0 하드코딩 → None + 중립값 사용, positions 타입 정규화 적용

#### 4.2.3 연속 분석 (src/orchestration/continuous_analysis.py)

**함수**: `run_continuous_crawl_analysis(ts: TradingSystem)`

9단계: Delta 크롤링 → Tier 소스 크롤링 → 최신 기사 조회 → 뉴스 분류(Sonnet) → 시장 상태 조회 → Opus 이슈 분석 → 이전 이슈 업데이트 → Redis 저장 → 텔레그램 알림(조건부)

- 윈도우: 23:00~06:30 KST
- 주기: 30분 (`_CONTINUOUS_ANALYSIS_INTERVAL`)
- Redis 키: `continuous_analysis:latest` (TTL 1시간), `continuous_analysis:history` (최대 50건)

#### 4.2.4 뉴스 파이프라인 (src/orchestration/news_pipeline.py) [신규]

**클래스**: `NewsPipeline` (384줄)

뉴스 수집부터 텔레그램 전송까지 전체 파이프라인을 단일 함수로 실행한다. 부분 실패를 허용하며 에러 발생 시에도 나머지 단계를 계속 진행한다. 핵심뉴스(critical/high/medium)만 번역하여 API 비용을 절감한다.

**실행 순서** (6단계):
1. 크롤링 (`crawl_engine.run`)
2. 최신 기사 조회 (DB, 기본 100건)
3. 뉴스 분류 (`classifier.classify_and_store_batch`)
4. 핵심뉴스 필터링 (`key_filter.filter_key_news`) — critical/high/medium만 추출
5. 핵심뉴스 한국어 번역 (`translator.translate_articles`) — 비용 절감
6. 텔레그램 전송 (`telegram_notifier.send_key_news_alert`) — 최대 10건

```python
class NewsPipeline:
    def __init__(self, crawl_engine, classifier, translator, key_filter, telegram_notifier)
    async def collect_and_send(self, crawl_mode="delta", article_limit=100, send_telegram=True) -> dict
```

**상수**:
| 상수 | 값 | 설명 |
|------|-----|------|
| `_MAX_KEY_NEWS_TELEGRAM` | 10 | 텔레그램 전송 최대 핵심뉴스 건수 |
| `_DEFAULT_CRAWL_MODE` | "delta" | 파이프라인 기본 크롤링 모드 |
| `_PIPELINE_ARTICLE_LIMIT` | 100 | DB 최신 기사 조회 건수 |

### 4.3 크롤링 파이프라인 (src/crawler/)

| 클래스/함수 | 파일 | 설명 |
|-------------|------|------|
| `CrawlEngine` | crawl_engine.py | 31개 소스 통합 크롤링 엔진 (797줄) |
| `CrawlScheduler` | crawl_scheduler.py | 야간/주간 모드 스케줄러 (452줄) |
| `CrawlVerifier` | crawl_verifier.py | 크롤링 품질 검증 (Sonnet) |
| `BaseCrawler` | base_crawler.py | 크롤러 기본 클래스 (104줄) |
| `CRAWL_SOURCES` | sources_config.py | 31개 소스 설정 딕셔너리 |

**헬퍼 함수** (sources_config.py):
- `get_sources_by_type(source_type)` → 유형별 소스
- `get_sources_by_priority(priority)` → 우선순위별 소스
- `get_enabled_source_keys()` → 활성화된 소스 키
- `get_sources_by_tier()` → 티어별 소스 그룹
- `get_tiered_schedule()` → 티어별 크롤링 스케줄

**CrawlEngine 추가 기능**:
- `_failed_crawlers`: 초기화 실패한 크롤러 추적 리스트 `[{"source_key": str, "reason": str}]`
- `get_crawler_status()`: 활성/실패 크롤러 상태 딕셔너리 반환
- `run_fault_isolated()`: 장애 격리 모드 크롤링 실행

**BaseCrawler 변경**: `safe_crawl()` 반환 타입이 `list` → `dict`로 변경
- 성공 시: `{"success": True, "articles": [...], "count": N}`
- 실패 시: `{"success": False, "articles": [], "error": "...", "count": 0}`

### 4.4 AI 분석 모듈 (src/analysis/)

| 클래스 | 파일 | 설명 |
|--------|------|------|
| `ClaudeClient` | claude_client.py | Claude CLI/API 클라이언트 (649줄) |
| `NewsClassifier` | classifier.py | 뉴스 분류기 - Sonnet (620줄) |
| `NewsTranslator` | news_translator.py | 뉴스 한국어 번역 - Sonnet (287줄) [신규] |
| `KeyNewsFilter` | key_news_filter.py | 핵심뉴스 4단계 분류 필터 (520줄) [신규] |
| `RegimeDetector` | regime_detector.py | 시장 레짐 감지 - Opus (298줄) |
| `DecisionMaker` | decision_maker.py | 매매 의사결정 - Opus (443줄) |
| `OvernightJudge` | overnight_judge.py | 야간 보유 판단 - Opus (358줄) |
| `ComprehensiveAnalysisTeam` | comprehensive_team.py | 종합분석팀 - 3분석관+리더 (481줄) |
| `HistoricalAnalysisTeam` | historical_team.py | 과거분석팀 (836줄) |
| `TickerProfiler` | ticker_profiler.py | 종목 프로파일 생성 (449줄) |

#### 4.4.1 NewsTranslator (src/analysis/news_translator.py) [신규]

Claude Sonnet을 사용하여 크롤링된 영어 뉴스 기사를 한국어로 번역한다. 배치 처리(10건/회)로 API 호출 횟수를 최소화한다.

```python
class NewsTranslator:
    def __init__(self, claude_client: ClaudeClient)
    async def translate_articles(self, articles: list[dict]) -> list[dict]
    async def translate_and_save(self, articles: list[dict]) -> int
    async def _translate_batch(self, articles: list[dict]) -> list[dict]
    @staticmethod
    def _chunk_articles(articles: list, size: int) -> list[list]
```

- 배치 크기: `_TRANSLATE_BATCH_SIZE = 10`
- 라우팅: `telegram_chat` task_type으로 Sonnet 사용
- 번역 필드: `headline` → `headline_kr`, 내용 요약 → `summary_ko`
- DB 저장: Article 모델의 `headline_kr`, `summary_ko` 컬럼 업데이트
- 실패 시: 원문 유지, 파이프라인 중단 없음 (빈 문자열로 채움)

#### 4.4.2 KeyNewsFilter (src/analysis/key_news_filter.py) [신규]

크롤링된 뉴스 중 시장에 중요한 영향을 미칠 수 있는 핵심뉴스를 분류하고 중요도를 판정한다. 40+ 키워드 기반 4단계 분류.

```python
class KeyNewsFilter:
    def __init__(self, universe_tickers=None, ticker_mapping=None)
    def is_key_news(self, article: dict) -> tuple[bool, str]
    def classify_importance(self, article: dict) -> str  # "critical"/"high"/"medium"/"low"
    def filter_key_news(self, articles: list[dict]) -> list[dict]
```

**중요도 분류 기준**:
| 중요도 | 이모지 | 기준 |
|--------|--------|------|
| critical | 🔴 | 시장 전체 영향 (FOMC, CPI, Powell, Trump, tariff, recession 등 40+ 키워드) |
| high | 🟠 | 모니터링 기업 직접 관련 (실적발표, M&A, CEO 변경 등) |
| medium | 🟡 | 관련 기업 (섹터 내 경쟁사, 공급망) |
| low | 🟢 | 일반 뉴스 (필터링 대상 외) |

**키워드 그룹**:
- `_MARKET_WIDE_KEYWORDS` (40+): 연준/통화정책, 경제지표, 정치/재정, 시장 이벤트
- `_EARNINGS_KEYWORDS` (20+): 실적발표 관련
- `_COMPANY_MAJOR_KEYWORDS` (20+): M&A, IPO, 구조조정, CEO 변경, FDA 승인 등
- `_MARKET_VOLATILITY_KEYWORDS` (10+): VIX, 시장 급등/급락

### 4.5 매매 실행 모듈 (src/executor/)

| 클래스 | 파일 | 설명 |
|--------|------|------|
| `KISAuth` | kis_auth.py | KIS 인증/토큰 관리 (340줄) |
| `KISClient` | kis_client.py | KIS API 클라이언트 (1,201줄) |
| `OrderManager` | order_manager.py | 주문 관리 (668줄) |
| `PositionMonitor` | position_monitor.py | 포지션 모니터링 (455줄) |
| `ForcedLiquidator` | forced_liquidator.py | 강제 청산 (212줄) |
| `UniverseManager` | universe_manager.py | ETF 유니버스 관리 (330줄) |

**KIS 듀얼 인증 구조**:
- 모의투자: `kis_client` (모의 서버 주문) + `real_auth` (실전 서버 시세 조회)
- 실전투자: `kis_client` (실전 서버 주문+시세)
- 모의투자 시장가 주문 불가 → 자동 지정가 변환 (±0.5%)

**KISClient 예외 처리 개선**: `TimeoutException`, `HTTPStatusError`, `ValueError` 3단계 세분화

### 4.6 안전 체인 (src/safety/)

```
HardSafety (절대 불가침)
    → SafetyChecker (QuotaGuard + HardSafety 통합)
        → EmergencyProtocol (긴급 프로토콜)
            → CapitalGuard (자본금 보호)
```

| 클래스 | 파일 | 설명 |
|--------|------|------|
| `HardSafety` | hard_safety.py | 절대 불가침 규칙 (350줄) |
| `SafetyChecker` | safety_checker.py | 3중 안전 체크 (194줄) |
| `EmergencyProtocol` | emergency_protocol.py | 긴급 프로토콜 + Circuit Breaker (621줄) |
| `CapitalGuard` | capital_guard.py | 자본금 보호 - 3중 잔고 검증 (358줄) |
| `AccountSafetyChecker` | account_safety.py | 계좌 안전 검증 (312줄) |
| `QuotaGuard` | quota_guard.py | API 할당량 관리 (175줄) |

**HardSafety 주요 메서드**:
```python
class HardSafety:
    def __init__(self, params: Optional[StrategyParams] = None)
    def check_new_order(self, order: dict, portfolio: dict) -> tuple[bool, str]
    def check_position(self, position: dict) -> Optional[dict]
    def update_daily_pnl(self, pnl_pct: float) -> None
    def record_trade(self) -> None
    def reset_daily(self) -> None
    def check_vix(self, vix: float) -> bool
    def get_status(self) -> dict
```

**HardSafety 규칙**:
| 규칙 | 값 | 동작 |
|------|-----|------|
| 종목당 최대 포지션 | 15% | 초과 시 주문 거부 |
| 전체 포지션 합계 | 80% | 초과 시 주문 거부 |
| 일일 최대 거래 | 30건 | 초과 시 주문 거부 |
| 일일 손실 한도 | -5% | 도달 시 전면 매매 중단 |
| 단일 종목 손절 | -2% | 즉시 전량 매도 |
| 최대 보유 일수 | 5일 | 초과 시 강제 청산 |
| 보유 4일차 | - | 75% 부분 청산 |
| 보유 3일차 | - | 50% 부분 청산 |
| VIX 매매 중단 | 35 이상 | 신규 매수 전면 중단 |

### 4.7 리스크 관리 (src/risk/)

**RiskGatePipeline** (src/risk/risk_gate.py):
```python
class RiskGatePipeline:
    def __init__(self, daily_loss_limiter, concentration_limiter, losing_streak_detector, simple_var, risk_budget, trailing_stop_loss)
    async def check_all(self, portfolio, market_data=None) -> PipelineResult
    async def check_order(self, order, portfolio) -> GateResult
    def get_status(self) -> dict
    def get_context(self) -> dict
```

| 게이트 | 클래스 | 파일 | 설명 |
|--------|--------|------|------|
| Gate 1 | `DailyLossLimiter` | daily_loss_limit.py | 일일 손실 한도 |
| Gate 2 | `ConcentrationLimiter` | concentration.py | 종목 집중도 제한 |
| Gate 3 | `LosingStreakDetector` | losing_streak.py | 연속 손실 감지 |
| Gate 4 | `SimpleVaR` | simple_var.py | Value at Risk |
| Gate 5 | `RiskBudget` | risk_budget.py | 리스크 예산 |
| Gate 6 | `TrailingStopLoss` | stop_loss.py | 트레일링 스톱로스 |
| 보조 | `RiskBacktester` | risk_backtester.py | 리스크 백테스터 |

**데이터 클래스**:
```python
@dataclass
class GateResult:
    passed: bool
    action: str        # "allow", "reduce", "block", "halt"
    message: str
    gate_name: str
    details: dict

@dataclass
class PipelineResult:
    can_trade: bool
    gate_results: list[GateResult]
    blocking_gates: list[str]
    overall_action: str
```

### 4.8 전략 모듈 (src/strategy/)

| 클래스 | 파일 | 설명 |
|--------|------|------|
| `StrategyParams` | params.py | 전략 파라미터 관리 (strategy_params.json) |
| `EntryStrategy` | entry_strategy.py | 진입 전략 평가 (390줄) |
| `ExitStrategy` | exit_strategy.py | 청산 전략 평가 (430줄) |
| `ProfitTargetManager` | profit_target.py | 월간 수익 목표 관리 (620줄) |
| `TickerParamsManager` | ticker_params.py | 종목별 AI 최적화 파라미터 (673줄) |
| ETF 유니버스 정의 | etf_universe.py | ETF 유니버스 정의 (870줄) |

### 4.9 기술적 지표 (src/indicators/)

| 클래스 | 파일 | 설명 |
|--------|------|------|
| `PriceDataFetcher` | data_fetcher.py | KIS API 가격 데이터 조회 (362줄) |
| `TechnicalCalculator` | calculator.py | RSI/MACD/볼린저/OBV 계산 (426줄) |
| `IndicatorAggregator` | aggregator.py | 지표 통합 (317줄) |
| `TickerHistoryAnalyzer` | history_analyzer.py | 지표 이력 분석 (501줄) |
| `WeightsManager` | weights.py | 지표 가중치 관리 (204줄) |

**PriceDataFetcher 에러 처리 개선**: 실패 시 빈 DataFrame 대신 `None` 반환, 예외 3단계 세분화 (TimeoutException / HTTPStatusError / ValueError)

### 4.10 피드백 루프 (src/feedback/)

| 클래스 | 파일 | 설명 |
|--------|------|------|
| `DailyFeedback` | daily_feedback.py | 일간 성과 분석 - Opus (389줄) |
| `WeeklyAnalysis` | weekly_analysis.py | 주간 분석 - Opus (304줄) |
| `ParamAdjuster` | param_adjuster.py | 파라미터 자동 조정 (280줄) |
| `RAGDocUpdater` | rag_doc_updater.py | RAG 문서 업데이트 (247줄) |

### 4.11 세금/환율 (src/tax/)

| 클래스 | 파일 | 설명 |
|--------|------|------|
| `TaxTracker` | tax_tracker.py | 양도소득세 추적 (284줄) |
| `FXManager` | fx_manager.py | USD/KRW 환율 관리 (491줄) |
| `SlippageTracker` | slippage_tracker.py | 슬리피지 추적 (278줄) |

### 4.12 RAG 시스템 (src/rag/)

| 클래스 | 파일 | 설명 |
|--------|------|------|
| `BGEEmbedder` | embedder.py | BGE-M3 임베딩 (1024차원) |
| `RAGRetriever` | retriever.py | 벡터 유사도 검색 |
| RAG 문서 생성 | doc_generator.py | RAG 문서 자동 생성 |
| RAG 문서 관리 | doc_manager.py | RAG 문서 CRUD |

### 4.13 텔레그램 봇 (src/telegram/)

| 클래스 | 파일 | 설명 |
|--------|------|------|
| `TelegramBotHandler` | bot_handler.py | 양방향 봇 핸들러 (621줄) |
| 명령어 처리 | commands.py | 봇 명령어 (445줄) |
| 메시지 포맷팅 | formatters.py | 메시지 포맷 (419줄) |
| 자연어 처리 | nl_processor.py | NLP 의도 분석 (325줄) |
| 권한 관리 | permissions.py | 사용자 권한 (108줄) |
| 매매 명령어 | trade_commands.py | 매매 관련 명령 (326줄) |

### 4.14 모니터링 (src/monitoring/)

| 클래스 | 파일 | 설명 |
|--------|------|------|
| FastAPI 앱 | api_server.py | FastAPI + WebSocket + 의존성 주입 (626줄) |
| `AlertManager` | alert.py | 알림 관리자 (267줄) |
| `TelegramNotifier` | telegram_notifier.py | 텔레그램 알림 발송 (715줄) |
| `BenchmarkComparison` | benchmark.py | AI vs SPY/SSO 비교 (421줄) |
| `LiveReadinessChecker` | live_readiness.py | 실전 준비 7가지 기준 (234줄) |
| `AccountModeManager` | account_mode.py | 모의/실전 듀얼 모드 관리 (180줄) |
| `IndicatorCrawler` | indicator_crawler.py | 매크로 지표 자동 크롤러 (652줄) |
| 뉴스 수집 엔드포인트 | news_collect_endpoints.py | 뉴스 수집+분류+번역+전송 (330줄) [신규] |

**TelegramNotifier 추가 메서드**:
```python
async def send_key_news_alert(
    self,
    key_articles: list[dict],
    total_count: int,
    key_count: int,
    timestamp: str | None = None,
) -> bool
```

**핵심뉴스 텔레그램 전송 형식**:
```
📰 핵심뉴스 알림 (2026-02-21 18:30)
🔴 [시장 전체] FOMC 금리 동결 결정
연준이 금리를 5.25%로 동결했다...
🟠 [실적발표] NVDA 4분기 실적 발표
엔비디아가 시장 예상 대폭 상회...
🟡 [관련기업] AMD 신규 AI 칩 발표
AMD가 차세대 AI 가속기를 발표...

총 수집: N건 | 핵심뉴스: M건
```

### 4.15 폴백 체계 (src/fallback/)

| 클래스 | 파일 | 설명 |
|--------|------|------|
| `FallbackRouter` | fallback_router.py | 할당량 초과 시 폴백 라우팅 (191줄) |
| 로컬 모델 폴백 | local_model.py | 로컬 모델 폴백 (146줄) |

### 4.16 유틸리티 (src/utils/)

| 클래스/함수 | 파일 | 설명 |
|-------------|------|------|
| `Settings` | config.py | Pydantic 환경설정 (150줄) |
| `get_logger(__name__)` | logger.py | 로깅 설정 (70줄) |
| `MarketHours` | market_hours.py | 미국 시장 시간 관리 (530줄) |
| 티커 매핑 함수들 | ticker_mapping.py | 본주-레버리지 매핑 (340줄) |

**MarketHours 변경**: 운영 윈도우 종료 시간 06:30 KST → 07:00 KST
- 비서머타임(EST): 23:00 KST ~ 익일 07:00 KST
- 서머타임(EDT): 22:00 KST ~ 익일 07:00 KST

### 4.17 필터링 (src/filter/)

| 파일 | 설명 |
|------|------|
| rule_filter.py | 규칙 기반 뉴스 필터 (195줄) |
| similarity_checker.py | 유사도 체크 (175줄) |
| filter_config.json | 필터 규칙 설정 |

---

## 5. API 엔드포인트 전체 목록

### 5.1 의존성 주입 (src/monitoring/api_server.py)

```python
def set_dependencies(
    position_monitor, universe_manager, weights_manager, strategy_params,
    safety_checker, fallback_router, crawl_engine, kis_client, claude_client,
    classifier, emergency_protocol, capital_guard, account_safety,
    tax_tracker, fx_manager, slippage_tracker, benchmark_comparison,
    telegram_notifier, profit_target_manager, risk_gate_pipeline,
    risk_budget, risk_backtester, indicator_crawler,
    virtual_kis_client, real_kis_client, position_monitors,
    trading_system, account_mode_manager, ticker_params_manager, historical_team
) -> None
```

추가 의존성 주입: `set_news_collect_deps(crawl_engine, classifier, claude_client, telegram_notifier)`

### 5.2 라우터 등록 (15개)

```python
app.include_router(agent_router)           # AI 에이전트
app.include_router(analysis_router)        # 종합분석
app.include_router(benchmark_router)       # 벤치마크/수익 목표
app.include_router(dashboard_router)       # 대시보드 핵심
app.include_router(emergency_router)       # 긴급/리스크
app.include_router(indicator_router)       # 기술 지표
app.include_router(macro_router)           # 거시경제
app.include_router(news_collect_router)    # 뉴스 수집+분류+번역+전송 [신규]
app.include_router(news_router)            # 뉴스
app.include_router(principles_router)      # 매매 원칙
app.include_router(system_router)          # 시스템 상태
app.include_router(trade_router)           # 매매/피드백
app.include_router(trade_reasoning_router) # 매매 근거
app.include_router(trading_control_router) # 자동매매 제어
app.include_router(universe_router)        # 유니버스/크롤링
```

### 5.3 Health / System

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 헬스체크 + 업타임 |
| GET | `/system/status` | 시스템 전체 상태 |
| GET | `/system/usage` | 리소스 사용량 |

### 5.4 Trading Control (자동매매 제어)

| 메서드 | 경로 | 인증 | 설명 |
|--------|------|------|------|
| GET | `/api/trading/status` | - | 매매 실행 상태 |
| POST | `/api/trading/start` | X-API-Key | 자동매매 시작 |
| POST | `/api/trading/stop` | X-API-Key | 자동매매 중지 |

### 5.5 News Collect (뉴스 수집+분류+번역+전송) [신규]

| 메서드 | 경로 | 인증 | 설명 |
|--------|------|------|------|
| POST | `/api/news/collect-and-send` | X-API-Key | 뉴스 수집→분류→핵심필터→번역→텔레그램 파이프라인 |

**응답 필드**: `status` ("sent"/"sent_no_key_news"), `news_count`, `key_news_count`, `crawl_saved`, `telegram_sent`

### 5.6 Dashboard (대시보드 핵심)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/dashboard/accounts` | 모의/실전 계좌 목록 |
| GET | `/dashboard/summary` | 대시보드 요약 |
| GET | `/dashboard/positions` | 현재 포지션 |
| GET | `/dashboard/trades/recent` | 최근 매매 내역 |
| GET | `/dashboard/charts/daily-returns` | 일별 수익률 차트 |
| GET | `/dashboard/charts/cumulative` | 누적 수익률 차트 |
| GET | `/dashboard/charts/heatmap/ticker` | 종목별 히트맵 |
| GET | `/dashboard/charts/heatmap/hourly` | 시간대별 히트맵 |
| GET | `/dashboard/charts/drawdown` | 드로다운 차트 |
| GET | `/strategy/params` | 전략 파라미터 조회 |
| POST | `/strategy/params` | 전략 파라미터 수정 |
| GET | `/strategy/ticker-params` | 종목별 파라미터 전체 |
| GET | `/strategy/ticker-params/{ticker}` | 특정 종목 파라미터 |
| POST | `/strategy/ticker-params/{ticker}/override` | 종목 파라미터 오버라이드 |
| DELETE | `/strategy/ticker-params/{ticker}/override` | 오버라이드 삭제 |
| POST | `/strategy/ticker-params/ai-optimize` | AI 파라미터 최적화 |
| GET | `/alerts` | 알림 목록 |
| GET | `/alerts/unread-count` | 미읽은 알림 수 |
| POST | `/alerts/{alert_id}/read` | 알림 읽음 처리 |
| GET | `/tax/status` | 세금 현황 |
| GET | `/tax/report/{year}` | 연도별 세금 보고서 |
| GET | `/tax/harvest-suggestions` | 세금 절약 제안 |
| GET | `/fx/status` | 환율 현황 |
| GET | `/fx/effective-return/{trade_id}` | 실효 수익률 |
| GET | `/fx/history` | 환율 이력 |
| GET | `/slippage/stats` | 슬리피지 통계 |
| GET | `/slippage/optimal-hours` | 최적 거래 시간대 |
| GET | `/reports/daily` | 최신 일일 보고서 |
| GET | `/reports/daily/list` | 일일 보고서 목록 |

### 5.7 Indicators (기술 지표)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/indicators/weights` | 지표 가중치 조회 |
| POST | `/indicators/weights` | 지표 가중치 수정 |
| GET | `/indicators/realtime/{ticker}` | 실시간 지표 |
| GET | `/api/indicators/rsi/{ticker}` | Triple RSI (7/14/21) |
| PUT | `/api/indicators/config` | 지표 설정 변경 |

### 5.8 Benchmark / Profit Target

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/benchmark/comparison` | AI vs SPY/SSO 비교 |
| GET | `/benchmark/chart` | 벤치마크 차트 데이터 |
| GET | `/api/target/current` | 현재 월 수익 목표 |
| PUT | `/api/target/monthly` | 월간 목표 수정 |
| PUT | `/api/target/aggression` | 공격성 오버라이드 |
| GET | `/api/target/history` | 목표 이력 |
| GET | `/api/target/projection` | 수익 예측 |

### 5.9 Emergency / Risk

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/emergency/stop` | 긴급 중지 (전체 청산) |
| POST | `/emergency/resume` | 긴급 해제 |
| GET | `/emergency/status` | 긴급 상태 |
| GET | `/emergency/history` | 긴급 이벤트 이력 |
| GET | `/api/risk/status` | 리스크 상태 |
| GET | `/api/risk/gates` | 리스크 게이트 현황 |
| PUT | `/api/risk/config` | 리스크 설정 변경 |
| GET | `/api/risk/budget` | 리스크 예산 |
| GET | `/api/risk/backtest` | 백테스트 결과 |
| POST | `/api/risk/backtest/run` | 백테스트 실행 |
| GET | `/api/risk/streak` | 연패 현황 |
| GET | `/api/risk/var` | VaR 계산 결과 |
| GET | `/api/risk/dashboard` | 리스크 대시보드 통합 |

### 5.10 Trade / Feedback

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/feedback/daily/{date_str}` | 일간 피드백 |
| GET | `/feedback/weekly/{week_str}` | 주간 피드백 |
| GET | `/feedback/pending-adjustments` | 대기 중 파라미터 조정 |
| POST | `/feedback/approve-adjustment/{id}` | 조정 승인 |
| POST | `/feedback/reject-adjustment/{id}` | 조정 거부 |

### 5.11 Trade Reasoning

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/trade-reasoning/dates` | 매매 근거 날짜 목록 |
| GET | `/api/trade-reasoning/daily/{date}` | 특정 날짜 매매 근거 |
| GET | `/api/trade-reasoning/detail/{trade_id}` | 개별 매매 근거 상세 |
| PUT | `/api/trade-reasoning/{trade_id}/feedback` | 사용자 피드백 |

### 5.12 Universe / Crawling

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/universe` | ETF 유니버스 목록 |
| POST | `/universe/add` | ETF 수동 추가 |
| POST | `/universe/auto-add` | ETF 자동 추가 |
| POST | `/universe/toggle` | ETF 활성화/비활성화 |
| DELETE | `/universe/{ticker}` | ETF 삭제 |
| GET | `/universe/sectors` | 섹터 목록 |
| GET | `/universe/sectors/{sector_key}` | 섹터 상세 |
| GET | `/universe/mappings` | 본주-레버리지 매핑 |
| POST | `/universe/mappings/add` | 매핑 추가 |
| DELETE | `/universe/mappings/{underlying}` | 매핑 삭제 |
| POST | `/universe/generate-profile/{ticker}` | 종목 프로파일 생성 |
| POST | `/universe/generate-all-profiles` | 전체 프로파일 생성 |
| GET | `/universe/profile-task/{task_id}` | 프로파일 생성 상태 |
| GET | `/universe/profile/{ticker}` | 종목 프로파일 조회 |
| POST | `/crawl/manual` | 수동 크롤링 실행 |
| GET | `/crawl/status/{task_id}` | 크롤링 상태 |

### 5.13 Analysis (종합분석)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/comprehensive/{ticker}` | 종목 종합분석 |
| GET | `/tickers` | 분석 가능 종목 목록 |
| GET | `/ticker-news/{ticker}` | 종목별 뉴스 |

### 5.14 Macro (거시경제)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/macro/indicators` | 매크로 지표 전체 |
| GET | `/api/macro/history/{series_id}` | 지표 이력 |
| GET | `/api/macro/calendar` | 경제 캘린더 |
| GET | `/api/macro/rate-outlook` | 금리 전망 |
| GET | `/api/macro/cached-indicators` | 캐시된 지표 |
| GET | `/api/macro/analysis` | 매크로 종합분석 |
| POST | `/api/macro/refresh` | 지표 새로고침 |

### 5.15 News / Principles / Agents

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/news/dates` | 뉴스 날짜 목록 |
| GET | `/api/news/summary` | 뉴스 요약 |
| GET | `/api/news/daily` | 일간 뉴스 |
| GET | `/api/news/{article_id}` | 기사 상세 |
| GET | `/api/principles` | 원칙 목록 |
| POST | `/api/principles` | 원칙 추가 |
| PUT | `/api/principles/core` | 핵심 원칙 수정 |
| PUT | `/api/principles/{id}` | 원칙 수정 |
| DELETE | `/api/principles/{id}` | 원칙 삭제 |
| GET | `/agents/list` | 에이전트 목록 |
| GET | `/agents/{agent_id}` | 에이전트 상세 |
| PUT | `/agents/{agent_id}` | 에이전트 상태 변경 |

---

## 6. WebSocket 엔드포인트

| 경로 | 설명 | 갱신 주기 | 인증 |
|------|------|-----------|------|
| `/ws/positions` | 실시간 포지션 업데이트 | 2초 | ?token=API_SECRET_KEY |
| `/ws/trades` | 매매 체결 알림 (Redis Pub/Sub) | 실시간 | ?token=API_SECRET_KEY |
| `/ws/crawl/{task_id}` | 크롤링 진행 상황 | 실시간 | ?token=API_SECRET_KEY |
| `/ws/alerts` | 시스템 알림 스트림 | 실시간 | ?token=API_SECRET_KEY |

---

## 7. DB 모델 (src/db/models.py)

25개 모델 (Base + 24 테이블):

| 모델명 | 테이블명 | 설명 |
|--------|----------|------|
| `RagDocument` | rag_documents | RAG 문서 + 1024차원 벡터 임베딩 |
| `EtfUniverse` | etf_universe | 거래 대상 ETF 유니버스 |
| `Trade` | trades | 매매 기록 (진입/청산/PnL/AI신호) |
| `IndicatorHistory` | indicator_history | 기술적 지표 이력 |
| `StrategyParamHistory` | strategy_param_history | 전략 파라미터 변경 이력 |
| `FeedbackReport` | feedback_reports | 일간/주간 피드백 보고서 |
| `CrawlCheckpoint` | crawl_checkpoints | 크롤링 체크포인트 |
| `Article` | articles | 크롤링된 뉴스 기사 (headline_kr, summary_ko 컬럼 포함) |
| `PendingAdjustment` | pending_adjustments | 대기 중 파라미터 조정 |
| `TaxRecord` | tax_records | 거래별 세금 기록 (FK→trades) |
| `FxRate` | fx_rates | USD/KRW 환율 이력 |
| `SlippageLog` | slippage_log | 체결 슬리피지 (FK→trades) |
| `EmergencyEvent` | emergency_events | 긴급 프로토콜 발동 이력 |
| `BenchmarkSnapshot` | benchmark_snapshots | AI vs 벤치마크 비교 스냅샷 |
| `CapitalGuardLog` | capital_guard_log | 자본금 안전 검증 로그 |
| `NotificationLog` | notification_log | 알림 발송 이력 |
| `ProfitTarget` | profit_targets | 월별 수익 목표 |
| `DailyPnlLog` | daily_pnl_log | 일별 손익 기록 |
| `RiskConfig` | risk_config | 리스크 파라미터 (key-value) |
| `RiskEvent` | risk_events | 리스크 이벤트 기록 |
| `BacktestResult` | backtest_results | 백테스트 결과 |
| `FearGreedHistory` | fear_greed_history | Fear & Greed 지수 이력 |
| `PredictionMarket` | prediction_markets | 예측시장 데이터 |
| `HistoricalAnalysis` | historical_analyses | 과거분석 결과 |
| `HistoricalAnalysisProgress` | historical_analysis_progress | 과거분석 진행 상태 |

**ORM 공통 패턴**:
- PK: `UUID(as_uuid=False)`, `default=lambda: str(uuid4())`
- 타임스탬프: `TIMESTAMP(timezone=True)`, `server_default=func.now()`
- JSON 필드: `JSONB` 타입
- 벡터: `Vector(1024)` (pgvector)
- 관계: SQLAlchemy 2.0 `Mapped` + `mapped_column` 문법

---

## 8. Flutter 대시보드

### 8.1 네비게이션 구조

```
ShellScreen (사이드바 + 콘텐츠 + 상태바)
├── OverviewScreen          # 대시보드 개요 (잔고, 포지션, 차트)
├── TradingScreen           # 매매 현황/전략 설정
├── RiskCenterScreen        # 리스크 센터 (게이트, VaR, 연패)
├── AnalyticsScreen         # 분석 (벤치마크, 세금, 환율, 슬리피지)
├── RsiScreen               # Triple RSI 차트 (7/14/21)
├── StockAnalysisScreen     # 종목 종합분석 (AI)
├── ReportsScreen           # 일간/주간 보고서
├── TradeReasoningScreen    # 매매 근거 (날짜별)
├── NewsScreen              # 뉴스 (날짜별, 기사 상세)
├── UniverseScreen          # ETF 유니버스 관리
├── AgentTeamScreen         # AI 에이전트 팀 구조
├── PrinciplesScreen        # 매매 원칙 CRUD
└── SettingsScreen          # 설정 (테마, 언어, 알림)
```

### 8.2 추가 화면 (26개+)

| 화면 | 파일 | 설명 |
|------|------|------|
| HomeDashboard | home_dashboard.dart | 자동매매 제어 카드 + 뉴스 수집 버튼 |
| AgentDetailScreen | agent_detail_screen.dart | 에이전트 상세 정보 |
| AlertHistory | alert_history.dart | 알림 이력 |
| AiReport | ai_report.dart | AI 분석 보고서 |
| ChartDashboard | chart_dashboard.dart | 차트 대시보드 |
| IndicatorSettings | indicator_settings.dart | 지표 설정 |
| ManualCrawlScreen | manual_crawl_screen.dart | 수동 크롤링 |
| ProfitTargetScreen | profit_target_screen.dart | 수익 목표 관리 |
| RiskDashboardScreen | risk_dashboard_screen.dart | 리스크 대시보드 |
| StrategySettings | strategy_settings.dart | 전략 파라미터 설정 (레짐 한국어 포맷팅) |
| TickerParamsScreen | ticker_params_screen.dart | 종목별 파라미터 (AI 재분석 에러 메시지 개선) |
| UniverseManagerScreen | universe_manager_screen.dart | 유니버스 관리 |
| SettingsScreen | settings_screen.dart | 설정 (레짐 한국어 포맷팅) |

### 8.3 대시보드 버튼 체계 (변경됨)

**기존**: 1개 시작/중지 버튼

**변경 후 (2모드)**:
| 상황 | 표시 버튼 |
|------|-----------|
| **항상** | "뉴스 수집 & 전송" 버튼 (파란색, 항상 활성) — `POST /api/news/collect-and-send` 호출 |
| **평일 23:00~07:00** | "자동매매 시작" 버튼 (활성) |
| **주말/공휴일** | 뉴스 버튼만 표시, 자동매매 버튼 숨김 |

**TradingControlProvider 변경**: 503 상태 코드 수신 시 상태 리셋, `collectAndSendNews()` 메서드 추가

### 8.4 주요 위젯 (27개)

SidebarNav, StatusBar, AlertPanel, EmergencyButton, GlassCard, StatCard, PositionCard, RsiChart, PnlLineChart, CumulativeChart, DrawdownChart, TickerHeatmap, HourlyHeatmap, FearGreedGauge, FearGreedChart, CpiChart, RateChart, MacroStatsRow, EconomicCalendarCard, CrawlProgressWidget, TickerAddDialog, WeightSlider, AgentTeamTree, ConfirmationDialog, EmptyState, SectionHeader

### 8.5 Provider (상태 관리, 24개)

DashboardProvider, ChartProvider, IndicatorProvider, TradeProvider, SettingsProvider, ProfitTargetProvider, RiskProvider, NavigationProvider, EmergencyProvider, TaxFxProvider, BenchmarkProvider, LocaleProvider, AgentProvider, MacroProvider, ReportProvider, UniverseProvider, NewsProvider, PrinciplesProvider, TradeReasoningProvider, StockAnalysisProvider, ThemeProvider, CrawlProgressProvider, TradingModeProvider, TradingControlProvider

### 8.6 API Service 변경

`dashboard/lib/services/api_service.dart`에 `collectAndSendNews()` 메서드 추가 — `POST /api/news/collect-and-send` 호출

### 8.7 Localization 변경

`dashboard/lib/l10n/app_strings.dart`에 6개 문자열 추가 (뉴스 수집 관련)

---

## 9. 크롤링 소스 (31개)

### 9.1 우선순위별 분류

| 우선순위 | 소스 |
|----------|------|
| 1 (Critical) | Reuters, Bloomberg, WSJ, FT, Fed, SEC EDGAR, ECB, Finviz |
| 2 (Important) | Yahoo Finance, CNBC, MarketWatch, BBC, Nikkei, SCMP, Yonhap, CNN Fear&Greed, Investing.com |
| 3 (Supplementary) | Reddit(WSB+Investing), StockTwits, Naver, DART, Polymarket, Kalshi, AlphaVantage, Finnhub, FRED |
| 4 (Supplementary-KR) | StockNow |

### 9.2 유형별 분류

| 유형 | 소스 |
|------|------|
| RSS | reuters, bloomberg_rss, yahoo_finance, cnbc, marketwatch, wsj, ft, bbc, ecb, fed, nikkei |
| API | finnhub, alphavantage, fred, reddit(x2), dart, sec_edgar, stocktwits |
| 스크래핑 | finviz, investing, naver, stocknow |
| 전용 | cnn_fear_greed, polymarket, kalshi, economic_calendar |

### 9.3 Tier 스케줄

| Tier | 주기 | 소스 |
|------|------|------|
| Tier 1 | 15분 | Finviz |
| Tier 2 | 1시간 | Investing.com, CNN Fear & Greed |
| Tier 3 | 30분 | Polymarket, Kalshi |
| Tier 4 | 1시간 | StockNow |

---

## 10. 티커 매핑 (src/utils/ticker_mapping.py)

### 10.1 본주 → 레버리지 ETF 매핑 (18쌍)

| 본주 | Bull (2X Long) | Bear (2X Inverse) | 카테고리 |
|------|----------------|-------------------|----------|
| SPY | SSO | SDS | Index (S&P 500) |
| QQQ | QLD | QID | Index (Nasdaq) |
| SOXX | USD | SSG | Semiconductor Index |
| IWM | UWM | TWM | Russell 2000 |
| DIA | DDM | DXD | Dow Jones |
| XLK | ROM | REW | Technology |
| XLF | UYG | SKF | Financials |
| XLE | DIG | DUG | Energy |
| TSLA | TSLL | TSLS | Individual |
| NVDA | NVDL | NVDS | Individual |
| AAPL | AAPB | AAPD | Individual |
| AMZN | AMZU | AMZD | Individual |
| META | METU | - | Individual |
| GOOGL | GGLL | - | Individual |
| GOOG | GGLL | - | Individual |
| MSFT | MSFL | - | Individual |
| AMD | AMDU | - | Individual |
| COIN | CONL | - | Individual |
| MSTR | MSTU | MSTZ | Individual |

### 10.2 섹터별 종목 분류 (12개 섹터)

| 섹터 키 | 한국어명 | 종목 | 섹터 레버리지 |
|---------|----------|------|--------------|
| `semiconductors` | 반도체 | NVDA, AVGO, AMD, MU, INTC, QCOM, TSM, ARM, MRVL | SOXL/SOXS |
| `big_tech` | 빅테크 | MSFT, AAPL, GOOG, GOOGL, AMZN, META, NFLX | QLD/QID |
| `ai_software` | AI/소프트웨어 | PLTR, DDOG, MDB, ORCL, DELL, CRM, ADBE, NOW, SNOW | ROM/REW |
| `ev_energy` | 전기차/에너지 | TSLA | TSLL/TSLS |
| `crypto` | 크립토/블록체인 | MSTR, CLSK, COIN, BITX, CONL, ETHU, SBIT, MSTU, MSTZ | BITX/SBIT |
| `finance` | 금융 | BLK, BAC, BRKB, PYPL, SQ, JPM, V, MA | UYG/SKF |
| `quantum` | 양자컴퓨팅 | IONQ, RGTI | - |
| `entertainment` | 엔터테인먼트 | DIS, DKNG | - |
| `infrastructure` | 인프라/리츠 | NSC, EQIX | - |
| `consumer` | 소비재 | KO | - |
| `healthcare` | 헬스케어 | NVO, UNH, LLY | RXL/RXD |
| `other` | 기타 | FIG, UBER, SHOP | - |

### 10.3 매핑 관련 함수

```python
def get_underlying(leveraged_ticker: str) -> str           # 레버리지 → 본주
def get_leveraged(underlying_ticker: str, direction="bull") -> str | None  # 본주 → 레버리지
def get_analysis_ticker(trade_ticker: str) -> str           # 매매 티커 → 분석용 본주
def get_all_mappings() -> list[dict]                        # 전체 매핑 목록
def add_mapping(underlying, bull_2x, bear_2x) -> bool       # 매핑 추가
def remove_mapping(underlying) -> bool                       # 매핑 제거
def get_sector(ticker: str) -> dict | None                  # 종목 → 섹터 정보
def get_tickers_by_sector(sector_key: str) -> list[str]     # 섹터 → 종목 리스트
def get_all_sectors() -> dict                               # 전체 섹터 정보
def get_sector_leveraged(ticker: str) -> dict | None        # 종목 → 섹터 레버리지
def add_ticker_to_sector(ticker, sector_key) -> bool        # 섹터에 종목 추가
```

---

## 11. 설정 파일

### 11.1 strategy_params.json

```json
{
  "take_profit_pct": 3.0,
  "trailing_stop_pct": 1.5,
  "stop_loss_pct": -2.0,
  "eod_close": true,
  "min_confidence": 0.7,
  "max_position_pct": 15.0,
  "max_total_position_pct": 80.0,
  "max_daily_trades": 30,
  "max_daily_loss_pct": -5.0,
  "max_hold_days": 5,
  "vix_shutdown_threshold": 35,
  "survival_trading": {
    "monthly_cost_usd": 300,
    "monthly_target_usd": 500,
    "enabled": true,
    "description": "시스템 운영비($300/월)를 반드시 수익으로 충당해야 한다"
  }
}
```

### 11.2 .env 환경변수 구조

| 카테고리 | 변수 | 설명 |
|----------|------|------|
| KIS 인증 | `KIS_VIRTUAL_APP_KEY/SECRET`, `KIS_REAL_APP_KEY/SECRET` | 모의/실전 API 키 |
| KIS 계좌 | `KIS_VIRTUAL_ACCOUNT=50167255-01`, `KIS_REAL_ACCOUNT=43122903-01` | 계좌번호 |
| KIS 모드 | `KIS_MODE=virtual` | virtual 또는 real |
| Claude AI | `CLAUDE_MODE=local`, `ANTHROPIC_API_KEY` | local(CLI) 또는 api |
| DB | `DB_HOST/PORT/USER/PASSWORD/NAME` | PostgreSQL 연결 |
| Redis | `REDIS_HOST/PORT/PASSWORD` | Redis 연결 |
| 크롤러 | `FINNHUB_API_KEY`, `ALPHAVANTAGE_API_KEY`, `FRED_API_KEY` | 외부 API 키 |
| 텔레그램 | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | 봇 + 수신자 |
| API | `API_PORT=8000`, `API_SECRET_KEY` | 서버 설정 |

### 11.3 data/trading_principles.json

7개 시스템 원칙 + 사용자 편집 가능 원칙. `core_principle` 필드로 핵심 원칙 별도 관리. CRUD API(`/api/principles`)로 관리한다.

---

## 12. 자동화/스케줄링

### 12.1 LaunchAgent (macOS)

| 항목 | 값 |
|------|-----|
| plist | `scripts/com.trading.autotrader.plist` |
| 실행 | `scripts/auto_trading.sh` |
| 시작 | 매일 23:00 KST |
| 종료 | 07:00 KST (MarketHours.is_operating_window()) |
| 재시작 | 비정상 종료 시 최대 10회 (`MAX_RESTARTS`) |
| 안정 판정 | 5분 이상 생존 (`STABLE_THRESHOLD=300`) |

### 12.2 자동 종료 메커니즘

```python
# src/main.py main_loop()
if not self._auto_stop_triggered and (
    _now_kst.hour > 6
    or (_now_kst.hour == 6 and _now_kst.minute >= 30)
):
    self._auto_stop_triggered = True
    self.running = False
    await self._run_shutdown_sequence()
    break
```

**MarketHours 운영 윈도우**: 07:00 KST 종료 (market_hours.py)
**main.py 자동 종료**: 06:30 KST (main_loop 내 하드코딩)

### 12.3 수동 제어

- Flutter 대시보드: "자동매매 시작/중지" 버튼 + "뉴스 수집 & 전송" 버튼 (`TradingControlProvider`)
- API: `POST /api/trading/start` + `POST /api/trading/stop` (X-API-Key 인증)
- 뉴스 수집: `POST /api/news/collect-and-send` (X-API-Key 인증, 주말/공휴일에도 사용 가능)

### 12.4 주기적 태스크 요약

| 태스크 | 주기 | 실행 시간대 |
|--------|------|------------|
| 준비 단계 (10단계) | 1일 1회 | 22:00/23:00 KST |
| 트레이딩 루프 (7단계) | 15분 | 정규장 |
| 정규장 포지션 모니터링 | 5분 | 정규장 (루프 사이) |
| 연속 분석 (9단계) | 30분 | 23:00~06:30 KST |
| 프리/애프터마켓 모니터링 | 30분 | pre_market/after_market |
| EOD 단계 (10단계) | 1일 1회 | 장 마감 후 |
| 주간 분석 | 1주 1회 | 일요일 |
| 자동 종료 | 1일 1회 | 06:30 KST |
| 환율 갱신 (FXManager) | 1시간 | 서버 가동 중 |
| 매크로 지표 크롤링 | 1시간 | 서버 가동 중 |
| 뉴스 수집+전송 (수동) | 수동 트리거 | 항상 가능 (주말 포함) |
| WebSocket 포지션 | 2초 | 연결 중 |
| KIS 잔고 캐시 | 30초 TTL | 요청 시 |

---

## 13. 테스트 구조

### 13.1 Python (tests/, 43파일, 19,021줄)

| 테스트 파일 | 대상 | 줄수 |
|-------------|------|------|
| test_trading_system.py | TradingSystem 통합 | 1,220 |
| test_api_server.py | FastAPI 서버 | 1,217 |
| test_trading_control.py | 자동매매 제어 API | 1,066 |
| test_risk_modules.py | 리스크 모듈 전체 | 1,411 |
| test_crawler_modules.py | 크롤러 모듈 | 946 |
| test_trade_reasoning_endpoints.py | 매매 근거 API | 794 |
| test_principles_endpoints.py | 매매 원칙 API | 727 |
| test_api_e2e.py | E2E 테스트 | 709 |
| test_main_integration.py | 메인 통합 | 620 |
| test_profit_target.py | 수익 목표 | 618 |
| (+ 33개 추가) | - | - |

- 실행: `pytest` (Docker/PostgreSQL 없이 mock 기반)
- 공용 fixture: `conftest.py`
- 최종 결과: **753 테스트 통과, Quality Score 98/100 (Grade S)**

### 13.2 Flutter (dashboard/test/, 11파일)

widget_test, api_service_test, dashboard_provider_test, navigation_provider_test, theme_provider_test, trading_colors_test, empty_state_test, glass_card_test, sidebar_nav_test, app_strings_test, stock_analysis_models_test

---

## 14. 에러 처리 패턴

### 14.1 크롤러 에러 처리

**BaseCrawler.safe_crawl()** 반환 타입 변경:
- 이전: `list[dict]` (성공/실패 구분 불가)
- 현재: `dict` — `{"success": bool, "articles": list, "count": int, "error": str | None}`
- "0개 수집(정상)"과 "에러로 인한 0개"를 명확히 구분

**CrawlEngine**: `_failed_crawlers` 리스트로 초기화 실패 크롤러 추적, `get_crawler_status()` 메서드로 상태 조회

### 14.2 가격 데이터 에러 처리

**PriceDataFetcher**: 실패 시 빈 DataFrame 대신 `None` 반환
- 호출자에서 `df is None` 체크로 "데이터 없음"과 "정상적으로 비어있는 데이터" 구분
- 예외 3단계 세분화: `TimeoutException` → `HTTPStatusError` → `ValueError`

### 14.3 SPY Circuit Breaker 폴백

**이전**: SPY 데이터 미가용 시 하드코딩 fallback `-3.0` (과도하게 보수적)
**현재**: `None` 반환 + 중립값 사용 → 불필요한 긴급 프로토콜 발동 방지

### 14.4 KIS API 예외 처리

**KISClient**: 예외 타입 확장
- `TimeoutException`: 네트워크 타임아웃 별도 처리
- `HTTPStatusError`: HTTP 상태 코드별 분기
- `ValueError`: 응답 파싱 실패 별도 처리

### 14.5 뉴스 날짜 파싱

**RSSCrawler**: 날짜 파싱 실패 시 현재시간 폴백 제거 → `None` 반환 (기사 스킵)
- 잘못된 날짜로 기사가 저장되는 문제 방지

### 14.6 BenchmarkComparison

`df is None or df.empty` 2단계 검증 적용 — DataFrame truthiness 문제 방지

---

## 15. 코딩 컨벤션

### 15.1 네이밍 규칙

| 대상 | 규칙 | 예시 |
|------|------|------|
| 파일/함수 | snake_case | `crawl_engine.py`, `get_portfolio_summary()` |
| 클래스 | PascalCase | `TradingSystem`, `KISClient` |
| 상수 | UPPER_SNAKE_CASE | `MAX_POSITION_PCT`, `_TRADING_LOOP_SLEEP` |
| 모듈 레벨 상수 | `_` 접두사 | `_VIX_STRONG_BULL`, `_CA_WINDOW_HOUR_START` |

### 15.2 문서/주석

- Docstring: 한국어 (~한다/~이다 스타일)
- 타입 힌트: Python 3.12+ `X | None` 문법 전면 적용
- 모듈 헤더: 역할 + 주요 기능 설명

### 15.3 코드 패턴

```python
# 비동기 전면 사용
async with get_session() as session:
    ...

# 로깅 패턴
logger = get_logger(__name__)
try:
    result = await operation()
except SomeError as exc:
    logger.error("작업 실패: %s", exc, exc_info=True)

# JSON 직렬화 (datetime 호환)
json.dumps(data, default=str)

# ORM 패턴
id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
```

### 15.4 포맷

- 들여쓰기: 4 spaces (Python), 2 spaces (Dart)
- import 순서: 표준 라이브러리 → 서드파티 → 프로젝트 내부

---

## 16. 알려진 이슈/주의사항

### 16.1 Claude CLI 관련

- `claude` CLI에는 `--max-tokens` 플래그가 없다. `_call_local()`에서 제거함
- `CLAUDECODE` / `CLAUDE_CODE` 환경변수가 설정되면 subprocess에서 중첩 세션 에러가 발생한다 → `env.pop()` 처리
- `proc.communicate()`에 `asyncio.wait_for(timeout=300.0)` 필수 (무한 hang 방지)

### 16.2 KIS API 관련

- 모의투자 서버에는 시장가 주문(order_type=01)이 불가하다 → 자동 지정가 변환 (±0.5%)
- 모의투자 서버에는 시세 API가 없다 → `real_auth` 별도 인증으로 실전 서버에서 시세 조회
- 거래소 코드: NAS(NASDAQ), AMS(AMEX/NYSE Arca), NYS(NYSE)
- 일봉 API 최대 100개 캔들 per 요청
- 시세 API TR_ID에는 V 접두사 불필요 (실전과 동일). 주문 API만 V 접두사 사용
- KIS OPSQ2000 에러: 잘못된 계좌번호가 원인 → `.env`에 정확한 계좌번호 설정 필수
- KIS 예외 처리: `TimeoutException` / `HTTPStatusError` / `ValueError` 3단계 세분화

### 16.3 Python 코드 관련

- `yfinance` 완전 제거. `PriceDataFetcher(kis_client)` 사용
- `BenchmarkComparison(kis_client)` - KISClient 인자 필수
- VIX는 FRED VIXCLS만 사용 (KIS로 ^VIX 조회 불가), 실패 시 fallback 20.0
- DataFrame 비교: `df or other_df` 사용 금지 → `df if df is not None else other_df`
- DataFrame None 체크: `df is None or df.empty` 2단계 검증 필수 (BenchmarkComparison 등)
- positions 반환값은 `list[dict]`이지 `dict`가 아님 → `next()`로 특정 티커 검색
- `redis.aclose()` 사용 (redis-py 5.0.1+ 비동기)
- SPY circuit breaker: 데이터 미가용 시 fallback None + 중립값 사용 (-3.0 하드코딩 제거)
- datetime 객체가 포함된 데이터 → `json.dumps(default=str)` 필수
- `position_monitor.monitor_all()` 호출 시 `regime`, `vix` 인자 필수
- `position_monitor.sync_positions()` 반환값은 `dict[str, dict]` → `list(positions.values())`로 변환 필요
- `overnight_judge`의 `regime` 파라미터는 `dict` → `regime.get("regime", "")` 추출 후 비교
- `RAGDocUpdater`에는 `update_from_daily()` 메서드가 있음 (update_from_signals 아님)
- `TradingLog` 모델은 존재하지 않음 → Redis 사용
- `PriceDataFetcher` 실패 시 빈 DataFrame 대신 `None` 반환 → 호출자에서 None 체크 필수
- `BaseCrawler.safe_crawl()` 반환 타입: `dict` (이전 `list` 아님) — `{"success", "articles", "count", "error"}`
- RSS 날짜 파싱 실패 시 `None` 반환 (현재시간 폴백 제거) → 기사 스킵됨

### 16.4 인프라 관련

- MLX: Docker에서 실행 불가 (Apple Silicon MPS 필요) → 호스트 직접 실행
- LaunchAgent: TCC 이슈로 WorkingDirectory는 홈 디렉토리(`~`) 사용
- LaunchAgent: 네트워크 확인 시 `curl` 사용 (`ping` 불가)
- `start_dashboard.py`가 포트 8000 점유 → 트레이딩 시스템 시작 전 종료 필수
- Docker: PostgreSQL + Redis만 실행 (API 서버는 호스트)

### 16.5 운영 시간 관련

- `market_hours.py` 운영 윈도우 종료: 07:00 KST
- `main.py` 자동 종료: 06:30 KST (main_loop 내 하드코딩)
- 두 값이 다르므로 주의: 윈도우는 07:00까지이나 실제 자동 종료는 06:30에 발생

---

## 부록: 디렉토리 구조 요약

```
Stock_Trading/
├── src/                          # Python 백엔드 (145파일, 53,107줄)
│   ├── main.py                   # TradingSystem 오케스트레이터 (2,438줄)
│   ├── ai/                       # 로컬 AI (MLX + Knowledge)
│   ├── analysis/                 # AI 분석 (Claude + 분류기 + 번역기 + 핵심필터 + 판단기)
│   ├── crawler/                  # 뉴스 크롤링 (31개 소스)
│   ├── db/                       # DB (connection + models 25개)
│   ├── executor/                 # 매매 실행 (KIS + 주문 + 포지션)
│   ├── fallback/                 # AI 폴백 체계
│   ├── feedback/                 # 피드백 루프 (일간/주간)
│   ├── filter/                   # 뉴스 필터링
│   ├── indicators/               # 기술적 지표
│   ├── monitoring/               # FastAPI 서버 (15라우터, 80+엔드포인트, 4WS)
│   ├── orchestration/            # 오케스트레이션 (준비/매매/연속분석/뉴스파이프라인)
│   ├── rag/                      # RAG (BGE-M3 + ChromaDB)
│   ├── risk/                     # 리스크 관리 (7개 게이트)
│   ├── safety/                   # 안전 체인 (4단계)
│   ├── strategy/                 # 전략 (진입/청산/파라미터/수익목표)
│   ├── tax/                      # 세금/환율/슬리피지
│   ├── telegram/                 # 텔레그램 양방향 봇
│   └── utils/                    # 유틸리티 (설정/로깅/시장시간/티커매핑)
├── dashboard/                    # Flutter macOS Desktop (112파일, 42,317줄)
│   └── lib/
│       ├── models/               # 데이터 모델 (19파일)
│       ├── providers/            # 상태 관리 (24파일)
│       ├── screens/              # 화면 (26파일)
│       ├── services/             # API/WebSocket (2파일)
│       ├── theme/                # 디자인 토큰 (7파일)
│       └── widgets/              # 공용 위젯 (27파일)
├── tests/                        # Python 테스트 (43파일, 19,021줄)
├── scripts/                      # 자동화 스크립트
├── data/                         # 런타임 데이터 (토큰, 원칙, 에이전트 메모리)
├── knowledge/                    # RAG 지식베이스 (5개 JSONL)
├── db/init.sql                   # PostgreSQL 스키마
├── docker-compose.yml            # PostgreSQL + Redis
├── strategy_params.json          # 전략 파라미터
└── requirements.txt              # Python 의존성 (32개)
```

---

*이 문서는 AI 자동매매 시스템 V2의 전체 구조를 코드 기반으로 정리한 종합 레퍼런스이다. 소스 코드 변경 시 함께 갱신해야 한다.*
