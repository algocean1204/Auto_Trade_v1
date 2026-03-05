# F1~F3 모듈 설계 문서 (defalarm v3 패턴)

> 작성일: 2026-02-26
> 대상: F1 데이터 수집, F2 AI 분석, F3 지표 계산
> 패턴: defalarm v3 — Feature / Manager / Atom 3계층 분리

---

## 공통 규칙

| 계층 | 역할 | 크기 제한 |
|---|---|---|
| **Feature** | 비즈니스 도메인 경계 | 폴더로 구분 |
| **Manager** | 도메인 흐름 오케스트레이션 | 50줄 이내, Atom 호출만 |
| **Atom** | 단일 책임 순수 함수 | 30줄 이내, DI 필수 |

- 모든 Atom은 외부 인프라(DB, Redis, HTTP)를 직접 import하지 않는다
- 공통 인프라는 `C0` 레이어(core/)에 분리한다
- 데이터 흐름: Atom → Manager → Feature (역방향 참조 금지)
- 모든 함수에 Python 타입 힌트 필수 (`str | None`, `list[str]` 등)
- 모든 주석과 docstring은 한국어로 작성한다

---

## 의존 코어 레이어 (C0) 참조 표기

| 코드 | 실제 모듈 | 설명 |
|---|---|---|
| `C0.2` | `src/db/connection.get_session()` | DB 세션 |
| `C0.3` | `src/db/connection.get_redis()` | Redis 클라이언트 |
| `C0.4` | Finnhub / AlphaVantage API 키 | 외부 시세 API |
| `C0.5` | `src/analysis/claude_client.ClaudeClient` | AI 게이트웨이 |
| `C0.6` | `src/executor/kis_client.KISClient` | 브로커 게이트웨이 |
| `C0.11` | `src/crawler/crawl_scheduler.CrawlScheduler` | 세션 타입 판별 |

---

## F1. 데이터 수집 (Data Collection)

### 파이프라인 개요

```
스케줄 트리거
    │
    ▼
F1.1 CrawlScheduler          ← 야간/주간 모드 판별
    │ get_crawl_interval() → int
    │ should_crawl_now()   → bool
    │ get_active_sources() → list[str]
    ▼
F1.3 Crawlers (30개 병렬)    ← asyncio.gather 병렬 실행
    │ crawl() → list[RawArticle]
    ▼
F1.4 CrawlVerifier           ← 언어/나이/스팸 필터
    │ verify() → list[VerifiedArticle]
    ▼
F1.5 ArticleDeduplicator     ← Redis SHA-256 중복 제거
    │ deduplicate() → list[UniqueArticle]
    ▼
F1.6 ArticlePersister        ← PostgreSQL 저장
    │ persist() → PersistResult
    ▼
F1.7 CrawlEngineManager      ← 결과 집계 + 이벤트 발행
    │ run() → CrawlResult
    ▼
EventBus: CRAWL_COMPLETE 발행
```

---

### F1.1 CrawlScheduler

**모듈 ID**: `F1.1`
**역할**: KST 시각 기준으로 야간/주간 모드를 판별하고 소스별 크롤링 주기를 계산한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| 없음 (내부 시계 사용) | — | KST `datetime.now()` |

#### OUT

| 메서드 | 반환 타입 | 설명 |
|---|---|---|
| `get_session_type()` | `Literal["night", "day"]` | 야간/주간 모드 |
| `get_crawl_interval(source_key: str)` | `int` | 소스별 크롤링 간격(초) |
| `should_crawl_now(source_key: str, last_crawled: datetime \| None)` | `bool` | 지금 크롤링해야 하는지 여부 |
| `get_active_sources()` | `list[str]` | 현재 모드에서 활성화된 소스 키 목록 |

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `is_night_mode(now_kst: datetime) -> bool` | `bool` | 20:00~06:30 KST이면 True |
| `get_interval_for_source(source_key: str, is_night: bool, intervals: dict[str, int]) -> int` | `int` | 소스별 간격 룩업 + 폴백 |
| `filter_active_sources(source_keys: list[str], disabled: set[str]) -> list[str]` | `list[str]` | 느린 소스 자동 비활성화 필터 |

#### 현재 파일 매핑

- `src/crawler/crawl_scheduler.py` (현재 단일 클래스, 344줄 sources_config 참조)
- 야간 모드: 20:00 KST 이후 진입, 06:30 KST에 주간 전환
- Fast mode: 8개 우선 소스, 5초 타임아웃 (스캘핑 전용)

#### 체크리스트

- [ ] `is_night_mode()` Atom 분리 (현재 클래스 내부 인라인)
- [ ] `get_interval_for_source()` 순수 함수로 분리 (dict 룩업)
- [ ] 느린 소스 자동 비활성화 상태를 Redis에서 관리하는 Atom 추가
- [ ] fast mode 진입 조건을 Atom `is_fast_mode(session_type)` 로 분리

---

### F1.2 CrawlerBase

**모듈 ID**: `F1.2`
**역할**: 모든 크롤러의 공통 인터페이스를 정의하는 추상 기반 클래스이다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `source_key` | `str` | F1.7 → `sources_config.py` |
| `source_config` | `dict[str, Any]` | `CRAWL_SOURCES[source_key]` |

#### OUT

| 메서드 | 반환 타입 | 설명 |
|---|---|---|
| `crawl(since: datetime \| None)` | `list[RawArticle]` | 수집된 원시 기사 목록 |
| `safe_crawl(since: datetime \| None)` | `dict[str, Any]` | 에러 격리된 안전 크롤 |

#### RawArticle 스키마

```python
RawArticle = TypedDict("RawArticle", {
    "headline": str,       # 기사 제목
    "content": str,        # 본문 또는 요약 (비어있을 수 있음)
    "url": str,            # 원본 링크
    "published_at": datetime,  # UTC 발행 시각
    "source": str,         # 소스 키 (예: "reuters")
    "language": str,       # ISO 언어 코드 (예: "en", "ko")
})
```

#### 현재 파일 매핑

- `src/crawler/base_crawler.py` (ABC, 60줄)
- 공유 `aiohttp.ClientSession` 관리
- 타임아웃: total=30s, connect=10s

#### 체크리스트

- [ ] `safe_crawl()` 내 에러 핸들링을 `wrap_crawler_error(fn, source_key)` Atom으로 분리
- [ ] 타임아웃 상수를 `core/constants.py`로 이동
- [ ] 세션 생성/공유 로직을 `create_shared_session()` Atom으로 분리

---

### F1.3 Crawlers (30개 소스)

**모듈 ID**: `F1.3`
**역할**: 각 뉴스/데이터 소스에서 원시 기사를 수집하는 구체 크롤러 Atom 집합이다.

#### IN (공통)

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `source_config` | `dict[str, Any]` | `CRAWL_SOURCES` |
| `since` | `datetime \| None` | F1.7 (마지막 크롤 시각) |

#### OUT (공통)

| 반환 타입 | 설명 |
|---|---|
| `list[RawArticle]` | 수집된 원시 기사 (빈 리스트 = 수집 없음) |

#### 크롤러 분류

**RSS 기반 (15개)**

| 소스 키 | 크롤러 클래스 | 파일 |
|---|---|---|
| reuters | RSSCrawler | `rss_crawler.py` |
| bloomberg_rss | RSSCrawler | `rss_crawler.py` |
| yahoo_finance | RSSCrawler | `rss_crawler.py` |
| cnbc | RSSCrawler | `rss_crawler.py` |
| marketwatch | RSSCrawler | `rss_crawler.py` |
| wsj_rss | RSSCrawler | `rss_crawler.py` |
| ft | RSSCrawler | `rss_crawler.py` |
| fed_announcements | RSSCrawler | `rss_crawler.py` |
| ecb_press | RSSCrawler | `rss_crawler.py` |
| bbc_business | RSSCrawler | `rss_crawler.py` |
| nikkei_asia | RSSCrawler | `rss_crawler.py` |
| scmp | RSSCrawler | `rss_crawler.py` |
| yonhap_en | RSSCrawler | `rss_crawler.py` |
| hankyung | RSSCrawler | `rss_crawler.py` |
| mk | RSSCrawler | `rss_crawler.py` |

**API 기반 (7개)**

| 소스 키 | 크롤러 클래스 | 파일 |
|---|---|---|
| reddit | RedditCrawler | `reddit_crawler.py` |
| stocktwits | StocktwitsCrawler | `stocktwits_crawler.py` |
| polymarket | PolymarketCrawler | `polymarket_crawler.py` |
| kalshi | KalshiCrawler | `kalshi_crawler.py` |
| finnhub | FinnhubCrawler | `finnhub_crawler.py` |
| alphavantage | AlphaVantageCrawler | `alphavantage_crawler.py` |
| fred | FREDCrawler | `fred_crawler.py` |

**스크래핑/특수 기반 (8개)**

| 소스 키 | 크롤러 클래스 | 파일 |
|---|---|---|
| naver_finance | NaverFinanceCrawler | `naver_crawler.py` |
| investing_com | InvestingCrawler | `investing_crawler.py` |
| finviz | FinvizCrawler | `finviz_crawler.py` |
| cnn_fear_greed | FearGreedCrawler | `fear_greed_crawler.py` |
| econcal (경제지표) | EconomicCalendarCrawler | `economic_calendar.py` |
| stocknow | StockNowCrawler | `stocknow_crawler.py` |
| sec_edgar | SECEdgarCrawler | `sec_edgar_crawler.py` |
| dart | DARTCrawler | `dart_crawler.py` |

#### 체크리스트

- [ ] 각 크롤러의 `crawl()` 내부 파싱 로직을 `parse_{source}(raw: bytes) -> list[RawArticle]` Atom으로 분리
- [ ] RSS 파싱 공통 로직을 `parse_rss_feed(feed_url: str, session) -> list[dict]` 공유 Atom으로 추출
- [ ] 각 크롤러 30줄 초과 시 `fetch_{source}()` + `parse_{source}()` 2개 Atom으로 분리

---

### F1.4 CrawlVerifier

**모듈 ID**: `F1.4`
**역할**: 수집된 원시 기사의 품질을 검증하고 유효하지 않은 기사를 제거한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `articles` | `list[RawArticle]` | F1.3 Crawlers 출력 |
| `filter_config` | `VerifierConfig` | 환경 설정 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `list[VerifiedArticle]` | 검증 통과 기사 목록 |

#### VerifiedArticle 스키마

```python
VerifiedArticle = TypedDict("VerifiedArticle", {
    **RawArticle,          # RawArticle 모든 필드 포함
    "quality_score": float,  # 0.0~1.0 검증 품질 점수
    "verified_at": datetime, # 검증 시각
})
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `is_valid_language(article: RawArticle, allowed: set[str]) -> bool` | `bool` | 허용 언어 확인 |
| `is_fresh(article: RawArticle, max_age_hours: int) -> bool` | `bool` | 24시간 이내 기사인지 확인 |
| `is_financial_relevant(headline: str, keywords: frozenset[str]) -> bool` | `bool` | 금융 관련성 키워드 매칭 |
| `is_spam(headline: str, spam_patterns: list[str]) -> bool` | `bool` | 스팸 패턴 감지 |
| `compute_quality_score(article: RawArticle) -> float` | `float` | 0~1 품질 점수 계산 |

#### 현재 파일 매핑

- `src/crawler/crawl_verifier.py` (프롬프트 생성 + 파싱, Claude Sonnet 호출은 외부)
- `MIN_SOURCES_RATIO = 0.5` — 소스 50% 이상 데이터 반환 필요
- `MIN_ARTICLES_COUNT = 10` — 최소 10개 기사
- `MAX_DUP_RATIO = 0.7` — 중복률 70% 이하

#### 체크리스트

- [ ] Claude Sonnet 호출 로직을 Manager 레벨로 이동 (Verifier는 프롬프트 생성만)
- [ ] `is_valid_language()`, `is_fresh()`, `is_financial_relevant()` 분리
- [ ] `parse_verification_result(response: dict) -> str` Atom에서 `.get("content", "")` 추출 보장

---

### F1.5 ArticleDeduplicator

**모듈 ID**: `F1.5`
**역할**: Redis SHA-256 해시 기반으로 48시간 내 중복 기사를 제거한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `articles` | `list[VerifiedArticle]` | F1.4 CrawlVerifier 출력 |
| `redis_client` | `aioredis.Redis` | C0.3 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `list[UniqueArticle]` | 중복 제거된 기사 목록 |

#### UniqueArticle 스키마

```python
UniqueArticle = TypedDict("UniqueArticle", {
    **VerifiedArticle,       # VerifiedArticle 모든 필드
    "content_hash": str,     # SHA-256 헤드라인 해시
    "is_new": bool,          # 새 기사 여부
})
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `compute_hash(headline: str) -> str` | `str` | SHA-256 정규화 해시 계산 |
| `make_redis_key(prefix: str, content_hash: str) -> str` | `str` | Redis 키 조합 |
| `is_duplicate(redis, key: str) -> bool` | `bool` (async) | Redis SET 중복 확인 |
| `mark_seen(redis, key: str, ttl: int) -> None` | `None` (async) | Redis에 해시 등록 (TTL 48h) |
| `batch_filter(redis, articles: list[VerifiedArticle]) -> list[UniqueArticle]` | `list` (async) | 배치 중복 처리 |

#### 현재 파일 매핑

- `src/crawler/dedup.py` — `DedupChecker` 클래스 (Redis-backed, 48h TTL)
- `crawl:dedup:` 키 접두사 사용
- 헤드라인 소문자 + strip 정규화 후 SHA-256 해싱

#### 체크리스트

- [ ] `DedupChecker` → Atom 함수 집합으로 분리 (stateless)
- [ ] Redis 클라이언트를 생성자가 아닌 각 Atom 함수의 파라미터로 DI
- [ ] 배치 체크 Atom: Redis pipeline으로 성능 최적화

---

### F1.6 ArticlePersister

**모듈 ID**: `F1.6`
**역할**: 중복 제거된 기사를 PostgreSQL에 저장하고 저장 통계를 반환한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `articles` | `list[UniqueArticle]` | F1.5 ArticleDeduplicator 출력 |
| `session` | `AsyncSession` | C0.2 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `PersistResult` | 저장 통계 |

```python
@dataclass
class PersistResult:
    saved_count: int        # 신규 저장 건수
    duplicate_count: int    # DB 레벨 중복 건수
    error_count: int        # 저장 실패 건수
    duration_seconds: float # 저장 소요 시간
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `to_db_model(article: UniqueArticle) -> Article` | `Article` | UniqueArticle → ORM 모델 변환 |
| `upsert_articles(session, models: list[Article]) -> tuple[int, int]` | `(saved, dup)` (async) | PostgreSQL upsert (충돌 무시) |
| `update_crawl_checkpoint(session, source_key: str, last_at: datetime) -> None` | `None` (async) | 크롤 체크포인트 갱신 |

#### 현재 파일 매핑

- `src/crawler/crawl_engine.py` 내부 인라인 로직 (분리 대상)
- `src/db/models.py` — `Article`, `CrawlCheckpoint` ORM 모델
- PostgreSQL `ON CONFLICT DO NOTHING` upsert 사용

#### 체크리스트

- [ ] `CrawlEngine` 내부 DB 저장 로직 → `ArticlePersister` 모듈로 분리
- [ ] `to_db_model()` Atom: 순수 변환 함수 (DB 호출 없음)
- [ ] `upsert_articles()` Atom: 배치 크기 100 기준 청킹

---

### F1.7 CrawlEngineManager (오케스트레이터)

**모듈 ID**: `F1.7`
**역할**: F1.1~F1.6 Atom들을 순서대로 호출하여 전체 크롤링 파이프라인을 실행하는 Manager이다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `session_type` | `Literal["night", "day"]` | F1.1 CrawlScheduler |
| `force_fast_mode` | `bool` | 외부 트리거 (스캘핑 모드) |
| `db_session` | `AsyncSession` | C0.2 |
| `redis_client` | `aioredis.Redis` | C0.3 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `CrawlResult` | 크롤링 최종 결과 |

```python
@dataclass
class CrawlResult:
    total_raw: int               # 수집 원시 기사 수
    verified: int                # 검증 통과 기사 수
    unique: int                  # 중복 제거 기사 수
    saved: int                   # DB 저장 기사 수
    duplicates_removed: int      # 중복 제거 수
    duration_seconds: float      # 전체 소요 시간
    mode: Literal["night", "day", "fast"]  # 실행 모드
    source_stats: dict[str, SourceStat]    # 소스별 통계
    error_sources: list[str]     # 에러 발생 소스 목록
```

#### 파이프라인 호출 순서

```python
# Manager는 Atom 호출과 데이터 전달만 수행한다. 직접 로직 없음.
async def run(self, ...) -> CrawlResult:
    # 1. 스케줄 확인
    sources = self.scheduler.get_active_sources()

    # 2. 크롤러 병렬 실행 (asyncio.gather)
    raw_results = await asyncio.gather(*[
        crawler.safe_crawl(since=last_crawled)
        for crawler in self._build_crawlers(sources)
    ])

    # 3. 검증
    verified = await self.verifier.verify(flatten(raw_results))

    # 4. 중복 제거
    unique = await self.deduplicator.batch_filter(redis, verified)

    # 5. 저장
    persist_result = await self.persister.upsert_articles(session, unique)

    # 6. 이벤트 발행
    await self.event_bus.publish("CRAWL_COMPLETE", result)

    return build_crawl_result(...)
```

#### 현재 파일 매핑

- `src/crawler/crawl_engine.py` (1,099줄 → Manager 50줄 + Atom들로 분리 대상)
- 현재 1,099줄 단일 파일: 스케줄링, 크롤링, 검증, 중복제거, DB저장 모두 혼재

#### 체크리스트

- [ ] 1,099줄 → Manager 50줄 + F1.1~F1.6 Atom 모듈로 분리
- [ ] `asyncio.gather` 크롤러 병렬 실행 + 에러 격리 (`return_exceptions=True`)
- [ ] 이벤트 버스 발행 (`CRAWL_COMPLETE`) Atom 추가
- [ ] `_CRAWLER_REGISTRY` → `core/crawler_registry.py`로 이동

---

## F2. AI 분석 (AI Analysis)

### 파이프라인 개요

```
뉴스/시장 데이터 수신
    │
    ▼
F2.1 NewsClassifier          ← 배치 20건씩 Claude Sonnet 분류
    │ list[ClassifiedArticle]
    ▼
F2.9 KeyNewsFilter           ← high-impact 기사 추출
    │ list[KeyArticle]
    ▼
F2.2 RegimeDetector          ← VIX + Claude Opus 레짐 판별
    │ RegimeResult
    ▼
F2.3 ComprehensiveTeam       ← 3분석관 병렬 + 리더 종합
    │ AnalysisResult
    ▼
F2.4 DecisionMaker           ← Claude Opus 최종 매매 판단
    │ list[TradingDecision]
    ▼
결과 저장 (Redis + DB) + 이벤트 발행
```

---

### F2.1 NewsClassifier

**모듈 ID**: `F2.1`
**역할**: 크롤링된 기사를 배치 20건씩 Claude Sonnet으로 분류하여 영향도, 방향, 감성 점수를 부여한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `articles` | `list[Article]` | F1.7 CRAWL_COMPLETE 이벤트 |
| `claude_client` | `ClaudeClient` | C0.5 |
| `monitored_tickers` | `set[str]` | 전략 파라미터 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `list[ClassifiedArticle]` | 분류 완료 기사 목록 |

```python
@dataclass
class ClassifiedArticle:
    id: str                         # DB 기사 ID
    headline: str                   # 원본 헤드라인
    impact: Literal["high", "medium", "low"]  # 영향도
    direction: Literal["bullish", "bearish", "neutral"]  # 방향
    category: str                   # 분류 카테고리 (예: "monetary_policy")
    tickers_mentioned: list[str]    # 언급된 티커 목록
    sentiment_score: float          # -1.0 ~ +1.0 감성 점수
    summary_ko: str                 # 한국어 요약
    headline_kr: str                # 한국어 헤드라인
    companies_impact: dict[str, str]  # {티커: 영향도} 매핑
    importance: Literal["critical", "key", "normal"]  # 중요도 분류
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `classify_importance(classification: dict, monitored: set[str]) -> str` | `str` | critical/key/normal 중요도 분류 |
| `build_classification_batch(articles: list[Article], batch_size: int) -> list[list[Article]]` | `list` | 배치 20건씩 분할 |
| `parse_classification_response(response: str) -> list[dict]` | `list[dict]` | Claude 응답 JSON 파싱 |
| `validate_classification(result: dict, required: frozenset) -> bool` | `bool` | 필수 필드 검증 |
| `merge_translation(classification: dict, translation: dict) -> ClassifiedArticle` | `ClassifiedArticle` | 분류 + 번역 결과 병합 |

#### 현재 파일 매핑

- `src/analysis/classifier.py` (623줄)
- 배치 처리: 20건씩 병렬 분류
- 분류 후 별도 배치로 한국어 번역 + 기업 영향 분석 수행
- `_REQUIRED_FIELDS = {"id", "impact", "tickers", "direction", "sentiment_score", "category"}`

#### 체크리스트

- [ ] `classify_importance()` 이미 분리됨 — 순수 함수 유지
- [ ] `parse_classification_response()` Atom으로 분리 (현재 클래스 내부)
- [ ] 번역 배치 로직을 `TranslationBatch` Atom으로 분리
- [ ] 623줄 → Manager 50줄 + Atoms으로 분리

---

### F2.2 RegimeDetector

**모듈 ID**: `F2.2`
**역할**: VIX 지수와 Claude Opus 종합 분석으로 현재 시장 레짐을 판별한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `vix_value` | `float` | F3.1 PriceDataFetcher (FRED VIXCLS) |
| `news_signals` | `list[ClassifiedArticle]` | F2.1 출력 |
| `strategy_params` | `dict[str, Any]` | `strategy_params.json` |
| `claude_client` | `ClaudeClient` | C0.5 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `RegimeResult` | 레짐 판별 결과 |

```python
@dataclass
class RegimeResult:
    regime: Literal["strong_bull", "mild_bull", "sideways", "mild_bear", "crash"]
    vix: float                  # 현재 VIX 값
    confidence: float           # 0.0 ~ 1.0 신뢰도
    take_profit: float          # 익절 기준 (%)
    trailing_stop: float        # 트레일링 스탑 (%)
    max_hold_days: int          # 최대 보유일 (0=당일청산)
    changed: bool               # 이전 레짐 대비 변경 여부
    previous_regime: str | None # 이전 레짐
```

#### 레짐 기준 (VIX 기반 1차 분류)

| 레짐 | VIX 범위 | take_profit | trailing | max_hold |
|---|---|---|---|---|
| strong_bull | 0 ~ 15 | 0% (무제한) | 4.0% | 0 (당일) |
| mild_bull | 15 ~ 20 | 3.0% | 2.5% | 2일 |
| sideways | 20 ~ 25 | 2.0% | 1.5% | 0 (당일) |
| mild_bear | 25 ~ 35 | 방어적 인버스 | — | — |
| crash | 35+ | 5.0% | — | — |

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `classify_by_vix(vix: float, ranges: dict) -> str` | `str` | VIX 범위 기반 1차 분류 |
| `build_regime_prompt(vix: float, news: list, prev_regime: str) -> str` | `str` | Claude 프롬프트 생성 |
| `parse_regime_response(response: str) -> dict` | `dict` | Claude 응답 파싱 |
| `build_regime_params(regime: str, params: dict) -> dict` | `dict` | 레짐별 파라미터 조합 |
| `has_regime_changed(current: str, previous: str | None) -> bool` | `bool` | 레짐 변경 감지 |

#### 현재 파일 매핑

- `src/analysis/regime_detector.py`
- `data/regime.json` — 마지막 레짐 영속 저장
- VIX 조회 실패 시 기본 노출 비율 50% 사용

#### 체크리스트

- [ ] `classify_by_vix()` 순수 함수로 이미 분리 가능
- [ ] 레짐 파라미터 상수를 `core/regime_params.py`로 이동
- [ ] `data/regime.json` 읽기/쓰기를 `RegimeStore` Atom으로 분리
- [ ] HardSafety의 `set_current_regime()` 연동 명시

---

### F2.3 ComprehensiveTeam

**모듈 ID**: `F2.3`
**역할**: 매크로/기술/심리 3분석관이 병렬로 분석하고 리더가 종합하여 섹터/종목 강약을 판단한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `news_data` | `list[ClassifiedArticle]` | F2.1 출력 |
| `market_data` | `dict[str, Any]` | F3 종합 지표 |
| `positions` | `list[Position]` | 포지션 모니터 |
| `regime` | `str` | F2.2 RegimeDetector |
| `claude_client` | `ClaudeClient` | C0.5 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `AnalysisResult` | 종합 분석 결과 |

```python
@dataclass
class AnalysisResult:
    recommendations: list[dict]    # 종목별 강약 판단
    risk_assessment: dict          # 리스크 평가
    macro_outlook: str             # 거시경제 전망 요약
    sector_bias: dict[str, float]  # 섹터별 편향 점수
    generated_at: datetime         # 생성 시각
```

#### 분석관 구성 (3+1 구조)

| 역할 | 관점 | 프롬프트 빌더 |
|---|---|---|
| 분석관 1 (매크로/섹터) | 글로벌 매크로 + 섹터 로테이션 | `build_comprehensive_macro_prompt()` |
| 분석관 2 (기술적/모멘텀) | RSI, MACD, 볼린저밴드, 거래량 | `build_comprehensive_technical_prompt()` |
| 분석관 3 (심리/리스크) | 뉴스 센티먼트, Fear&Greed, 위험 | `build_comprehensive_sentiment_prompt()` |
| 리더 | 3 의견 종합 최종 판단 | `build_comprehensive_leader_prompt()` |

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `run_analyst(client, prompt: str, system: str, timeout: float) -> str` | `str` (async) | 단일 분석관 호출 |
| `gather_analyst_opinions(client, prompts: list[str]) -> list[str]` | `list[str]` (async) | 3분석관 병렬 실행 |
| `build_leader_synthesis(opinions: list[str], market: dict) -> str` | `str` | 리더 종합 프롬프트 생성 |
| `parse_analysis_result(response: str) -> AnalysisResult` | `AnalysisResult` | 리더 응답 파싱 |
| `truncate_articles(articles: list, max_count: int) -> list` | `list` | 프롬프트용 기사 수 제한 (최대 30개) |

#### 현재 파일 매핑

- `src/analysis/comprehensive_team.py` (480줄)
- `_ANALYST_TIMEOUT = 120.0` 초
- `_MAX_ARTICLES_FOR_PROMPT = 30`

#### 체크리스트

- [ ] `run_analyst()` Atom: Claude 단일 호출 순수 래퍼
- [ ] `gather_analyst_opinions()` Atom: `asyncio.gather` + 타임아웃 처리
- [ ] 프롬프트 빌더 → `F2.7 PromptRegistry`로 이동
- [ ] 480줄 → Manager 50줄 + Atoms으로 분리

---

### F2.4 DecisionMaker

**모듈 ID**: `F2.4`
**역할**: 뉴스 신호, RAG 과거 사례, 기술적 지표, 시장 레짐을 종합하여 Claude Opus로 최종 매매 판단을 수행한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `analysis_result` | `AnalysisResult` | F2.3 ComprehensiveTeam |
| `positions` | `list[Position]` | 포지션 모니터 |
| `regime` | `str` | F2.2 RegimeDetector |
| `indicators` | `CompositeScore` | F3.4 IndicatorAggregator |
| `rag_context` | `list[str]` | RAG 검색기 |
| `claude_client` | `ClaudeClient` | C0.5 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `list[TradingDecision]` | 실행 가능한 매매 명령 목록 |

```python
@dataclass
class TradingDecision:
    action: Literal["buy", "sell", "hold", "close"]
    ticker: str
    confidence: float           # 0.0 ~ 1.0
    reasons: list[str]          # 판단 근거
    position_size_pct: float    # 포지션 크기 (%)
    time_horizon: Literal["intraday", "swing"]
    direction: Literal["long", "short"]
```

#### 가중치 구조

- 뉴스 신호: **50%**
- 시장 레짐 + 매크로: **30%**
- 기술적 지표: **20%**

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `build_decision_prompt(news, regime, indicators, rag, positions) -> str` | `str` | Claude 판단 요청 프롬프트 생성 |
| `parse_decision_response(response: str) -> list[dict]` | `list[dict]` | Claude 응답 파싱 |
| `validate_decision(decision: dict, valid_actions: frozenset) -> bool` | `bool` | 필수 필드 + 허용 값 검증 |
| `apply_min_confidence(decisions: list, threshold: float) -> list` | `list` | 최소 신뢰도 이하 결정 필터링 |
| `get_analysis_ticker(ticker: str) -> str` | `str` | 레버리지 ETF → 분석용 기초 티커 변환 |

#### 현재 파일 매핑

- `src/analysis/decision_maker.py` (402줄)
- `MIN_CONFIDENCE`, `MAX_POSITION_PCT` → `src/strategy/params.py`
- `_VALID_ACTIONS = {"buy", "sell", "hold", "close"}`

#### 체크리스트

- [ ] `parse_decision_response()` + `validate_decision()` Atom으로 분리
- [ ] `apply_min_confidence()` 순수 필터 Atom으로 분리
- [ ] 402줄 → Manager 50줄 + Atoms으로 분리

---

### F2.5 OvernightJudge

**모듈 ID**: `F2.5`
**역할**: 정규장 마감 전 보유 포지션의 오버나이트 보유 여부를 Claude Opus로 판단한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `positions` | `list[dict]` | 포지션 모니터 (`list(positions.values())`) |
| `signals` | `list[dict]` | 분류된 뉴스 신호 |
| `regime` | `str` | F2.2 RegimeDetector |
| `claude_client` | `ClaudeClient` | C0.5 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `list[OvernightVerdict]` | 포지션별 오버나이트 판단 |

```python
@dataclass
class OvernightVerdict:
    ticker: str
    decision: Literal["hold", "sell"]
    risk_level: Literal["low", "medium", "high"]
    reason: str
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `build_overnight_prompt(positions, signals, regime) -> str` | `str` | Claude 판단 프롬프트 생성 |
| `parse_overnight_response(response: str) -> list[dict]` | `list[dict]` | Claude 응답 파싱 |
| `is_bear_etf(ticker: str, bear_universe: frozenset) -> bool` | `bool` | Bear ETF 여부 확인 (Bear ETF는 하락장 홀딩 제외) |
| `validate_verdict(verdict: dict) -> bool` | `bool` | hold/sell 검증 |

#### 현재 파일 매핑

- `src/analysis/overnight_judge.py` (280줄)
- Bear ETF는 하락장(crash/mild_bear)에서 청산 제외
- `sync_positions()` 반환값 → `list(positions.values())` 변환 후 전달

#### 체크리스트

- [ ] `is_bear_etf()` Atom: `BEAR_2X_UNIVERSE` 참조 순수 함수
- [ ] 응답 파싱 Atom: 필수 필드 `{"ticker", "decision"}` 검증
- [ ] `sync_positions()` 반환 타입 변환 로직 문서화

---

### F2.6 ContinuousAnalysisManager

**모듈 ID**: `F2.6`
**역할**: 23:00~06:30 KST 동안 30분 주기로 delta 크롤링 + Opus 이슈 분석을 반복 실행하는 Manager이다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `trading_system` | `TradingSystem` | 메인 오케스트레이터 |
| `claude_client` | `ClaudeClient` | C0.5 |
| `redis_client` | `aioredis.Redis` | C0.3 |
| `interval_seconds` | `int` | 기본 1800 (30분) |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `ContinuousResult` | 단일 분석 실행 결과 |

```python
@dataclass
class ContinuousResult:
    issues: list[dict]          # 감지된 이슈 목록
    recommendations: list[dict] # 권고사항
    iteration: int              # 실행 횟수
    timestamp: datetime         # 실행 시각
    high_issues_count: int      # HIGH 등급 이슈 수
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `build_continuous_prompt(articles, prev_issues, context) -> str` | `str` | Opus 연속 분석 프롬프트 생성 |
| `parse_continuous_response(response: str) -> dict` | `dict` | 이슈/권고사항 파싱 |
| `cache_analysis_result(redis, result: dict, ttl: int) -> None` | `None` (async) | Redis에 분석 결과 캐시 (TTL 1h) |
| `push_history(redis, result: dict, max_len: int) -> None` | `None` (async) | Redis 히스토리 목록 관리 (최대 50개) |
| `filter_high_issues(issues: list, max_count: int) -> list` | `list` | 텔레그램 전송용 HIGH 이슈 필터링 (최대 3개) |

#### 현재 파일 매핑

- `src/orchestration/continuous_analysis.py` (278줄)
- `_ANALYSIS_CACHE_TTL = 3600` (1시간)
- `_ANALYSIS_HISTORY_MAX = 50` (Redis 보존 건수)
- `_MAX_HIGH_ISSUES_TELEGRAM = 3`

#### 체크리스트

- [ ] 함수형 `run_continuous_crawl_analysis()` → Manager 클래스로 리팩토링
- [ ] `TradingSystem` 직접 참조 제거 → 필요 의존성 DI로 주입
- [ ] `cache_analysis_result()` + `push_history()` Atom 분리

---

### F2.7 PromptRegistry

**모듈 ID**: `F2.7`
**역할**: 도메인별 분리된 프롬프트 템플릿을 관리하고 컨텍스트 데이터를 주입하여 완성된 프롬프트를 반환한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `prompt_type` | `str` | 호출 모듈 |
| `context_data` | `dict[str, Any]` | 호출 모듈 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `str` | 완성된 프롬프트 문자열 |

#### 파일 분리 계획 (1,896줄 → 5개 파일)

| 파일 | 담당 프롬프트 | 주요 함수 |
|---|---|---|
| `news_prompts.py` | 뉴스 분류, 번역, 테마 | `build_news_classification_prompt()`, `build_translation_prompt()` |
| `trading_prompts.py` | 매매 판단, 진입/청산 조건 | `build_trading_decision_prompt()`, `build_overnight_judgment_prompt()` |
| `analysis_prompts.py` | 종합 분석, 연속 분석 | `build_comprehensive_*_prompt()`, `build_continuous_analysis_prompt()` |
| `macro_prompts.py` | 거시경제, 레짐, 매크로 | `build_regime_detection_prompt()`, `build_macro_prompt()` |
| `risk_prompts.py` | 리스크 평가, EOD 피드백 | `build_risk_assessment_prompt()`, `build_eod_feedback_prompt()` |

#### 내부 Atom 함수 (공통)

| Atom | 서명 | 설명 |
|---|---|---|
| `get_system_prompt(role: str) -> str` | `str` | 역할별 시스템 프롬프트 반환 |
| `inject_context(template: str, context: dict) -> str` | `str` | 템플릿에 컨텍스트 주입 |
| `truncate_for_tokens(text: str, max_chars: int) -> str` | `str` | 토큰 한도 내 텍스트 잘라내기 |
| `serialize_datetime(obj: Any) -> str` | `str` | `json.dumps(default=str)` datetime 직렬화 |

#### 현재 파일 매핑

- `src/analysis/prompts.py` (1,896줄 → 5개 파일로 분리 대상)

#### 체크리스트

- [ ] 1,896줄 단일 파일 → 5개 도메인 파일로 분리
- [ ] `get_system_prompt()` 공통 Atom → `core/prompts_base.py`
- [ ] `serialize_datetime()` 공통 유틸 → `core/serializers.py`
- [ ] 모든 프롬프트에서 `json.dumps(default=str)` 사용 확인

---

### F2.8 FallbackRouter

**모듈 ID**: `F2.8`
**역할**: Claude API 호출을 래핑하여 장애 또는 Quota 초과 시 로컬 Qwen3 모델로 자동 전환하는 라우터이다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `request` | `dict[str, Any]` | 호출 모듈 (prompt, system, model 등) |
| `quota_guard` | `QuotaGuard` | `src/safety/quota_guard.py` |
| `claude_client` | `ClaudeClient` | C0.5 |
| `local_model` | `LocalModel \| None` | `src/fallback/local_model.py` |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `FallbackResponse` | AI 응답 (출처 명시) |

```python
@dataclass
class FallbackResponse:
    content: str                    # 응답 텍스트 (.get("content", "") 로 추출)
    model: str                      # 사용된 모델명
    source: Literal["claude", "local"]  # 응답 출처
    confidence: float               # 0.0 ~ 1.0 신뢰도
```

#### 라우팅 흐름

```
Claude 정상 + Quota 충분 → Claude 사용
429 에러 → QuotaGuard.safe_call() 재시도 3회
재시도 실패 / 장애 → Qwen3(로컬) 전환
Qwen3 confidence < 0.90 → 매매 스킵 (안전)
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `is_quota_exhausted(quota_guard) -> bool` | `bool` (async) | Quota 소진 여부 확인 |
| `call_claude_with_retry(client, request, max_retries: int) -> str` | `str` (async) | 재시도 포함 Claude 호출 |
| `call_local_model(local, request) -> FallbackResponse` | `FallbackResponse` (async) | 로컬 모델 호출 |
| `is_confidence_sufficient(confidence: float, threshold: float) -> bool` | `bool` | 신뢰도 기준 충족 여부 |
| `extract_content(response: dict) -> str` | `str` | 응답 dict에서 content 추출 (`.get("content", "")`) |

#### 현재 파일 매핑

- `src/fallback/fallback_router.py` (393줄)
- `src/fallback/local_model.py` — Qwen3-30B-A3B MLX 4bit 로컬 모델
- `extract_content()`: `FallbackRouter.call()` 반환값은 dict이므로 반드시 `.get("content", "")` 추출

#### 체크리스트

- [ ] `extract_content()` Atom 명시적 분리 (호출자가 파싱 실수 방지)
- [ ] `is_confidence_sufficient()` 기준값 `0.90` 상수화
- [ ] 393줄 → Manager 50줄 + Atoms으로 분리

---

### F2.9 KeyNewsFilter

**모듈 ID**: `F2.9`
**역할**: 분류된 기사 중 시장에 중요한 영향을 미치는 high-impact 기사만 추출한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `articles` | `list[ClassifiedArticle]` | F2.1 NewsClassifier |
| `filter_config` | `FilterConfig` | 환경 설정 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `list[KeyArticle]` | 핵심 기사 목록 |

```python
@dataclass
class KeyArticle:
    article: ClassifiedArticle
    priority: Literal["critical", "high", "medium", "low"]
    keyword_matched: list[str]  # 매칭된 핵심 키워드
    send_telegram: bool         # 텔레그램 전송 여부
```

#### 우선도 분류 기준

| 우선도 | 조건 | 예시 |
|---|---|---|
| critical | 시장 전체 영향 키워드 매칭 | FOMC, CPI, 연준 발언, 트럼프 발표 |
| high | 모니터링 기업 직접 관련 | 실적 발표, 주요 뉴스 |
| medium | 관련 기업 (투자처, 경쟁사, 공급망) | 공급망 변화, 경쟁사 뉴스 |
| low | 일반 뉴스 | 기타 금융 뉴스 |

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `match_market_wide_keywords(headline: str, keywords: frozenset) -> list[str]` | `list[str]` | 시장 전체 영향 키워드 매칭 |
| `match_ticker_keywords(tickers: list[str], monitored: set[str]) -> bool` | `bool` | 직접 티커 매칭 |
| `classify_priority(article: ClassifiedArticle, config: FilterConfig) -> str` | `str` | critical/high/medium/low 분류 |
| `should_send_telegram(priority: str, threshold: str) -> bool` | `bool` | 텔레그램 전송 기준 판단 |

#### 현재 파일 매핑

- `src/analysis/key_news_filter.py` (520줄)
- `_MARKET_WIDE_KEYWORDS` frozenset: 연준/통화정책, 경제지표, 지정학 등
- Pre-market phase (step 4-1): high-impact 뉴스 텔레그램 전송

#### 체크리스트

- [ ] 520줄 → Manager + Atoms으로 분리
- [ ] `_MARKET_WIDE_KEYWORDS` → `core/keywords.py`로 이동
- [ ] `classify_priority()` 순수 함수 분리

---

### F2.10 EODFeedbackReport

**모듈 ID**: `F2.10`
**역할**: 매매일 종료 후 뉴스/매매/판단/관점 5가지 영역에 대한 상세 피드백을 Claude Opus로 생성하고 Telegram으로 전송한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `daily_trades` | `list[dict]` | DB 당일 매매 내역 |
| `performance_metrics` | `dict[str, Any]` | 손익/통계 계산 결과 |
| `news_signals` | `list[ClassifiedArticle]` | F2.1 출력 |
| `claude_client` | `ClaudeClient` | C0.5 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `FeedbackReport` | 피드백 보고서 |

```python
@dataclass
class FeedbackReport:
    summary: str                    # 전체 요약
    by_domain: dict[str, str]       # 도메인별 피드백 (5개 영역)
    adjustments: list[str]          # 파라미터 조정 권고사항
    telegram_message: str           # 텔레그램 전송용 포맷 (최대 3800자)
    generated_at: datetime
```

#### 5개 피드백 영역

1. 뉴스 분석 품질
2. 매매 실행 정확도
3. 판단 품질 (신뢰도 보정)
4. 시장 관점 정합성
5. 시스템 운영 안정성

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `build_eod_feedback_prompt(trades, metrics, news) -> str` | `str` | 피드백 요청 프롬프트 생성 |
| `parse_feedback_response(response: str) -> dict` | `dict` | 응답 파싱 + 5개 영역 분리 |
| `format_telegram_message(report: dict, max_chars: int) -> str` | `str` | 텔레그램 메시지 포맷 (3800자 이내) |
| `extract_adjustments(feedback: dict) -> list[str]` | `list[str]` | 조정 권고사항 추출 |

#### 현재 파일 매핑

- `src/analysis/eod_feedback_report.py` (229줄, 신규 추가)
- `_FEEDBACK_MAX_CHARS = 3800`
- `_FEEDBACK_TIMEOUT = 120.0`

#### 체크리스트

- [ ] `build_eod_feedback_prompt()` → `F2.7 PromptRegistry`의 `risk_prompts.py`로 이동
- [ ] `format_telegram_message()` Atom: 텍스트 잘라내기 로직 포함
- [ ] 피드백 결과 Redis 캐시 여부 결정

---

### F2.11 NewsThemeTracker

**모듈 ID**: `F2.11`
**역할**: 관련 뉴스를 테마별로 그룹핑하고 시간순 진행상황을 Redis에 영속 추적한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `articles` | `list[ClassifiedArticle]` | F2.1 NewsClassifier |
| `redis_client` | `aioredis.Redis` | C0.3 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `ThemeResult` | 테마 추적 결과 |

```python
@dataclass
class ThemeResult:
    current_themes: list[dict]   # 현재 활성 테마 목록 (최대 10개)
    trending_up: list[str]       # 상승 트렌드 테마
    trending_down: list[str]     # 하락 트렌드 테마
    telegram_message: str | None # 텔레그램 전송용 요약
```

#### 테마 분류 키워드

| 테마 | 주요 키워드 |
|---|---|
| FOMC/금리 | fomc, fed, interest rate, powell, rate decision |
| CPI/인플레이션 | cpi, inflation, consumer price, pce |
| 고용지표 | nonfarm, unemployment, jobs report, jobless claims |
| 관세/무역 | tariff, trade war, trade deal, import duty |
| AI/반도체 | nvidia, nvda, semiconductor, chip, ai chip, gpu |
| 빅테크실적 | earnings, quarterly results, revenue, eps, guidance |

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `match_theme(headline: str, theme_keywords: dict) -> str \| None` | `str \| None` | 테마 키워드 매칭 |
| `load_active_themes(redis) -> dict` | `dict` (async) | Redis에서 활성 테마 로드 |
| `save_active_themes(redis, themes: dict, ttl_hours: int) -> None` | `None` (async) | Redis에 테마 저장 (TTL 24h) |
| `update_theme(theme: dict, article: ClassifiedArticle) -> dict` | `dict` | 테마에 새 기사 추가 |
| `detect_trend_change(theme_history: list) -> tuple[list, list]` | `(up, down)` | 상승/하락 트렌드 감지 |

#### 현재 파일 매핑

- `src/analysis/news_theme_tracker.py` (370줄, 신규 추가)
- Redis 키: `news_themes:active`, `news_themes:history`
- TTL 24시간, 테마당 최대 20개 업데이트

#### 체크리스트

- [ ] `_THEME_KEYWORDS` → `core/keywords.py`로 이동
- [ ] `load_active_themes()` + `save_active_themes()` Atom 분리 (Redis I/O)
- [ ] `match_theme()` 순수 함수 Atom으로 분리

---

## F3. 지표 (Indicators)

### 파이프라인 개요

```
KIS API / 외부 API
    │
    ▼
F3.1 PriceDataFetcher        ← 일봉 OHLCV + FRED VIX
    │ PriceHistory
    ▼
F3.2 TechnicalCalculator     ← pandas-ta 기술적 지표 계산
    │ TechnicalIndicators
    ├─────────────────────────┐
    ▼                         ▼
F3.3 HistoryAnalyzer         F3.5 IntradayFetcher (Finnhub/AV)
    │ HistoryAnalysis              │ IntradayData
    │                              ▼
    │                         F3.6 IntradayCalculator
    │                              │ IntradayMetrics
    └───────────┬─────────────────┘
                ▼
    F3.4 IndicatorAggregator
    │ CompositeScore (-1~+1)
    ├── F3.7 CrossAssetMomentum
    ├── F3.8 VolumeProfile
    ├── F3.9 WhaleTracker
    ├── F3.10 MACDDivergence
    ├── F3.11 ContangoDetector
    └── F3.12 NAVPremiumTracker
```

---

### F3.1 PriceDataFetcher

**모듈 ID**: `F3.1`
**역할**: KIS API로 일봉 OHLCV를 수집하고 FRED VIXCLS로 VIX 지수를 조회한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `ticker` | `str` | 전략 유니버스 |
| `period` | `int` | 요청 기간 (일수) |
| `kis_client` | `KISClient` | C0.6 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `PriceHistory` | OHLCV DataFrame + VIX |

```python
@dataclass
class PriceHistory:
    ticker: str
    dates: list[datetime]
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    volumes: list[int]
    vix: float                  # 현재 VIX (FRED VIXCLS)
    exchange: str               # NAS / AMS / NYS
```

#### 거래소 코드 매핑

| 코드 | 대상 |
|---|---|
| NAS | NASDAQ 개별주식 (AAPL, TSLA, NVDA 등) |
| AMS | AMEX/NYSE Arca ETF (SOXL, QLD, SPY 등) |
| NYS | NYSE 주식 |

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `get_exchange_code(ticker: str) -> str` | `str` | 티커 → 거래소 코드 매핑 |
| `fetch_daily_ohlcv(kis, ticker: str, exchange: str, period: int) -> list[dict]` | `list[dict]` (async) | KIS 일봉 조회 (최대 100캔들/요청) |
| `fetch_vix_fred(api_key: str, cache: dict) -> float` | `float` (async) | FRED VIXCLS 조회 + 인메모리 캐시 |
| `parse_kis_price_response(raw: list) -> PriceHistory` | `PriceHistory` | KIS 응답 → PriceHistory 변환 |
| `apply_vix_fallback(vix: float \| None) -> float` | `float` | VIX 조회 실패 시 기본값 20.0 반환 |

#### 현재 파일 매핑

- `src/indicators/data_fetcher.py` (362줄)
- VIX 인메모리 캐시: `_vix_cache: dict[str, tuple[float, Any]]`
- VIX 폴백: `_VIX_FALLBACK = 20.0` (KIS는 ^VIX 조회 불가)

#### 체크리스트

- [ ] `fetch_daily_ohlcv()` Atom: 100캔들 제한 청킹 처리 포함
- [ ] `fetch_vix_fred()` Atom: 캐시 키 `f"vix:{date}"` 형식
- [ ] `apply_vix_fallback()` Atom: 폴백값 상수화

---

### F3.2 TechnicalCalculator

**모듈 ID**: `F3.2`
**역할**: pandas-ta를 활용하여 OHLCV DataFrame에서 모멘텀, 추세, 변동성, 거래량 지표를 계산한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `df` | `pd.DataFrame` | F3.1 PriceDataFetcher (Open, High, Low, Close, Volume 컬럼) |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `TechnicalIndicators` | 계산된 기술적 지표 딕셔너리 |

```python
@dataclass
class TechnicalIndicators:
    # 모멘텀
    rsi_7: dict     # {"rsi": float, "signal": float, "state": str}
    rsi_14: dict
    rsi_21: dict
    macd: dict      # {"macd": float, "signal": float, "histogram": float}
    stochastic: dict  # {"k": float, "d": float}
    # 추세
    ma_cross: dict  # {"sma_20": float, "sma_50": float, "golden_cross": bool}
    adx: dict       # {"adx": float, "trend_strength": str}
    # 변동성
    bollinger: dict  # {"upper": float, "middle": float, "lower": float}
    atr_14: float
    # 거래량
    volume_ratio: float
    obv: float
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `calc_rsi(prices: pd.Series, period: int) -> dict` | `dict` | RSI + 과매수/과매도 신호 |
| `calc_macd(prices: pd.Series) -> dict` | `dict` | MACD(12,26,9) |
| `calc_bollinger(prices: pd.Series, period: int, std: float) -> dict` | `dict` | 볼린저밴드(20,2) |
| `calc_stochastic(high, low, close, k_period, d_period) -> dict` | `dict` | 스토캐스틱(14,3,3) |
| `calc_atr(high, low, close, period: int) -> float` | `float` | ATR(14) |
| `calc_obv(close: pd.Series, volume: pd.Series) -> float` | `float` | OBV |
| `calc_adx(high, low, close, period: int) -> dict` | `dict` | ADX(14) + 추세 강도 |
| `calc_volume_ratio(volume: pd.Series, period: int) -> float` | `float` | 현재 거래량 / 평균 거래량 비율 |

#### 지표 카탈로그

| 지표 | 카테고리 | 기본 가중치 |
|---|---|---|
| rsi_7 | momentum | 10 |
| rsi_14 | momentum | 15 |
| rsi_21 | momentum | 10 |
| macd | momentum | 20 |
| stochastic | momentum | 10 |
| ma_cross | trend | 20 |
| adx | trend | 5 |
| bollinger | volatility | 10 |
| atr | volatility | 10 |
| volume_ratio | volume | 10 |
| obv | volume | 5 |

#### 현재 파일 매핑

- `src/indicators/calculator.py` (453줄)
- `TechnicalCalculator.calculate_all(df)` — 전체 지표 일괄 계산
- `_RSI_OVERBOUGHT = 70.0`, `_RSI_OVERSOLD = 30.0`

#### 체크리스트

- [ ] 각 지표 계산 → 개별 Atom 함수로 분리 (각 30줄 이내)
- [ ] `calculate_all()` → Manager 역할 (Atom 순차 호출만)
- [ ] 453줄 → Manager 50줄 + 8개 Atom으로 분리

---

### F3.3 HistoryAnalyzer

**모듈 ID**: `F3.3`
**역할**: 가격 이력과 기술적 지표를 분석하여 추세, 지지/저항, 패턴을 감지한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `price_history` | `PriceHistory` | F3.1 PriceDataFetcher |
| `indicators` | `TechnicalIndicators` | F3.2 TechnicalCalculator |
| `ticker` | `str` | 전략 유니버스 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `HistoryAnalysis` | 이력 분석 결과 |

```python
@dataclass
class HistoryAnalysis:
    ticker: str
    trend: Literal["uptrend", "downtrend", "sideways"]
    support: float              # 지지선 가격
    resistance: float           # 저항선 가격
    volatility: float           # 변동성 (ATR 기반 %)
    patterns: list[str]         # 감지된 캔들 패턴 목록
    price_vs_ma: dict           # SMA20/50/200 대비 현재가 위치
    context: str                # 종목별 맥락 요약 (텍스트)
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `detect_trend(closes: list[float], sma_20: float, sma_50: float) -> str` | `str` | 추세 감지 (uptrend/downtrend/sideways) |
| `find_support(lows: list[float], window: int) -> float` | `float` | 최근 N일 지지선 감지 |
| `find_resistance(highs: list[float], window: int) -> float` | `float` | 최근 N일 저항선 감지 |
| `detect_patterns(df: pd.DataFrame) -> list[str]` | `list[str]` | 캔들 패턴 감지 |
| `compute_volatility_pct(atr: float, close: float) -> float` | `float` | ATR → % 변동성 변환 |

#### 현재 파일 매핑

- `src/indicators/history_analyzer.py` (501줄)
- `TickerHistoryAnalyzer` 클래스 (종목별 맥락 분석)

#### 체크리스트

- [ ] 501줄 → Manager + Atoms으로 분리
- [ ] `detect_patterns()` Atom: pandas-ta 캔들 패턴 활용
- [ ] `find_support()` + `find_resistance()` 순수 함수 분리

---

### F3.4 IndicatorAggregator

**모듈 ID**: `F3.4`
**역할**: 모든 기술적 지표에 가중치를 적용하여 단일 종합 점수(-1~+1)와 방향 신호를 생성한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `indicators` | `TechnicalIndicators` | F3.2 TechnicalCalculator |
| `history_analysis` | `HistoryAnalysis` | F3.3 HistoryAnalyzer |
| `weights` | `dict[str, float]` | `src/indicators/weights.py` |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `CompositeScore` | 종합 점수 |

```python
@dataclass
class CompositeScore:
    score: float                # -1.0 ~ +1.0 종합 점수
    direction: Literal["buy", "sell", "neutral"]  # 방향 신호
    signals: dict[str, float]   # 지표별 개별 점수
    confidence: float           # 0.0 ~ 1.0 신뢰도
    ticker: str
```

#### 방향 기준

- `score > 0.2` → `"buy"`
- `score < -0.2` → `"sell"`
- 그 외 → `"neutral"`

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `normalize_indicator(indicator: dict, indicator_type: str) -> float` | `float` | 지표 값 → -1~+1 정규화 |
| `apply_weights(scores: dict, weights: dict) -> float` | `float` | 가중 평균 점수 계산 |
| `classify_direction(score: float, buy_threshold: float, sell_threshold: float) -> str` | `str` | 방향 분류 |
| `compute_confidence(signals: dict, score: float) -> float` | `float` | 신호 일치도 기반 신뢰도 계산 |
| `get_rsi_scalar(rsi_dict: dict) -> float` | `float` | RSI dict에서 "rsi" float 스칼라 추출 |

#### 현재 파일 매핑

- `src/indicators/aggregator.py` (398줄)
- RSI 계열(`rsi_7`, `rsi_14`, `rsi_21`)은 dict에서 `"rsi"` 키로 스칼라 추출
- 방향 맵: `"bullish"→1.0`, `"neutral"→0.0`, `"bearish"→-1.0`

#### 체크리스트

- [ ] `normalize_indicator()` Atom: 각 지표 타입별 정규화 로직 포함
- [ ] `get_rsi_scalar()` Atom: RSI dict 스칼라 추출 명시 분리
- [ ] 398줄 → Manager 50줄 + Atoms으로 분리

---

### F3.5 IntradayFetcher

**모듈 ID**: `F3.5`
**역할**: KIS가 지원하지 않는 장중 분봉 데이터를 Finnhub(1차) / AlphaVantage(폴백)에서 수집하고 Redis에 캐싱한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `ticker` | `str` | 전략 유니버스 |
| `redis_client` | `aioredis.Redis` | C0.3 |
| `finnhub_key` | `str` | C0.4 (환경변수) |
| `av_key` | `str` | C0.4 (환경변수) |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `IntradayData` | 장중 분봉 데이터 |

```python
@dataclass
class IntradayData:
    ticker: str
    candles_5min: list[dict]    # [{t, o, h, l, c, v}, ...]
    fetched_at: datetime
    source: Literal["finnhub", "alphavantage", "cache"]
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `fetch_from_finnhub(ticker: str, session, api_key: str) -> list[dict]` | `list[dict]` (async) | Finnhub 5분봉 조회 |
| `fetch_from_alphavantage(ticker: str, session, api_key: str) -> list[dict]` | `list[dict]` (async) | AV 5분봉 폴백 조회 |
| `get_cached_candles(redis, cache_key: str) -> list[dict] \| None` | `list[dict] \| None` (async) | Redis 캐시 조회 |
| `set_cached_candles(redis, cache_key: str, data: list, ttl: int) -> None` | `None` (async) | Redis 캐시 저장 (TTL 90초) |
| `make_cache_key(ticker: str) -> str` | `str` | 캐시 키 생성 |

#### 현재 파일 매핑

- `src/indicators/intraday_fetcher.py` (299줄)
- `_CACHE_TTL = 90` 초 (1분봉 + 버퍼)
- Finnhub → AV 폴백 순서

#### 체크리스트

- [ ] `fetch_from_finnhub()` + `fetch_from_alphavantage()` Atom 분리
- [ ] 캐시 키 형식 표준화: `f"intraday:{ticker}:5min"`
- [ ] 네트워크 실패 시 캐시 데이터 반환 우선 전략 명시

---

### F3.6 IntradayCalculator

**모듈 ID**: `F3.6`
**역할**: 장중 5분봉 데이터에서 VWAP, 장중 RSI, 볼린저 위치를 계산한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `intraday_data` | `IntradayData` | F3.5 IntradayFetcher |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `IntradayMetrics` | 장중 지표 |

```python
@dataclass
class IntradayMetrics:
    vwap: float                 # 거래량 가중 평균가
    intraday_rsi: float         # 장중 RSI(14)
    bb_position: float          # 볼린저밴드 위치 (-1~+1)
    volume_trend: Literal["increasing", "decreasing", "flat"]  # 거래량 추세
    current_vs_vwap: float      # 현재가 vs VWAP 괴리율 (%)
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `calc_vwap(candles: list[dict]) -> float` | `float` | VWAP 계산 (ΣPV / ΣV) |
| `calc_intraday_rsi(closes: list[float], period: int) -> float` | `float` | 장중 RSI 계산 |
| `calc_bb_position(closes: list[float], period: int, std: float) -> float` | `float` | 볼린저밴드 내 위치 (-1~+1) |
| `detect_volume_trend(volumes: list[int]) -> str` | `str` | 거래량 추세 감지 |
| `calc_price_vs_vwap(current_price: float, vwap: float) -> float` | `float` | 현재가 vs VWAP 괴리율 |

#### 현재 파일 매핑

- `src/indicators/intraday_calculator.py` (225줄)

#### 체크리스트

- [ ] 225줄 → 5개 Atom 함수 + Manager로 분리
- [ ] `calc_vwap()` 순수 함수: 입력 리스트만 처리
- [ ] 빈 candles 처리 Atom 추가

---

### F3.7 CrossAssetMomentum

**모듈 ID**: `F3.7`
**역할**: 레버리지 ETF와 리더 종목 간 선행-후행 관계를 분석하여 크로스 에셋 모멘텀 신호를 생성한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `ticker` | `str` | 레버리지 ETF 티커 |
| `leader_prices` | `dict[str, float]` | 리더 종목 실시간 가격 |
| `redis_client` | `aioredis.Redis` | C0.3 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `CrossAssetSignal` | 크로스 에셋 신호 |

```python
@dataclass
class CrossAssetSignal:
    ticker: str
    leader_obi: float           # 리더 종목 OBI (Order Book Imbalance)
    divergence: bool            # ETF-리더 괴리 감지 여부
    momentum_score: float       # -1.0 ~ +1.0 종합 모멘텀 점수
    leaders_aligned: bool       # 리더 종목들 방향 일치 여부
    top_leaders: list[str]      # 영향력 상위 리더 종목
```

#### 리더 맵 (주요)

| ETF | 리더 종목 (가중치) |
|---|---|
| SOXL / SOXS | NVDA(0.5), AMD(0.3), TSM(0.2) |
| QLD / QID | AAPL(0.25), MSFT(0.25), NVDA(0.25), GOOG(0.25) |
| TQQQ / SQQQ | QQQ 추종 |
| TSLL / TSLS | TSLA(1.0) |
| NVDL / NVDS | NVDA(1.0) |

#### 내부 Atom 함수 (현재 파일 기반)

| Atom (파일) | 서명 | 설명 |
|---|---|---|
| `LeaderMap.get_leaders(ticker: str)` | `list[LeaderEntry]` | 티커 → 리더 목록 조회 |
| `LeaderAggregator.aggregate(leaders, prices)` | `dict` | 리더 가중 평균 OBI 계산 |
| `DivergenceDetector.detect(etf_obi, leader_obi)` | `bool` | 괴리 감지 (leader>0.5 + ETF<0.1) |
| `MomentumScorer.score(leaders, divergence)` | `float` | 종합 모멘텀 점수 계산 |

#### 현재 파일 매핑

- `src/indicators/cross_asset/leader_map.py` (137줄) — LEADER_MAP 상수
- `src/indicators/cross_asset/leader_aggregator.py` (170줄)
- `src/indicators/cross_asset/divergence_detector.py` (137줄)
- `src/indicators/cross_asset/momentum_scorer.py` (204줄)
- `src/indicators/cross_asset/models.py` (81줄)

#### 체크리스트

- [ ] `LEADER_MAP` → `core/leader_map.py`로 이동 (순수 상수)
- [ ] 각 파일 Atom 함수가 30줄 이내인지 확인
- [ ] `DivergenceDetector.detect()` 조건 명시: leader_OBI > 0.5 AND ETF_OBI < 0.1

---

### F3.8 VolumeProfile

**모듈 ID**: `F3.8`
**역할**: 틱 데이터에서 가격-거래량 분포(Volume Profile)를 계산하여 POC와 Value Area를 도출한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `tick_data` | `list[TickData]` | 웹소켓 틱 스트림 |
| `redis_client` | `aioredis.Redis` | C0.3 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `VolumeProfileResult` | Volume Profile 분석 결과 |

```python
@dataclass
class VolumeProfileResult:
    ticker: str
    poc_price: float            # Point of Control (최대 거래량 가격)
    value_area_high: float      # Value Area 상단 (70% 거래량 포함)
    value_area_low: float       # Value Area 하단
    support_levels: list[float] # 지지 가격 레벨 목록
    resistance_levels: list[float]  # 저항 가격 레벨 목록
    signal: PocSignal           # 현재가 기반 매매 신호
```

#### 신호 유형 (PocSignal)

| 신호 | 조건 | 의미 |
|---|---|---|
| support_bounce | 가격이 POC 위에서 하락 → POC 근처 | 매수 신호 |
| resistance_test | 가격이 POC 아래에서 상승 → POC 근처 | 주의 신호 |
| range_bound | 가격이 Value Area 내부 | 레인지 트레이딩 |
| breakout | 가격이 Value Area 외부 이탈 | 추세 발생 가능 |

#### 내부 Atom 함수 (현재 파일 기반)

| Atom (파일) | 서명 | 설명 |
|---|---|---|
| `Accumulator.add(tick: TickData)` | `None` | 틱 데이터 가격-거래량 누적 |
| `PocCalculator.find_poc(profile: dict) -> float` | `float` | 최대 거래량 가격(POC) 탐색 |
| `PocCalculator.find_value_area(profile, poc, target_pct)` | `tuple[float, float]` | 70% Value Area 계산 |
| `PocSignalGenerator.generate(profile, current_price)` | `PocSignal` | POC 기반 신호 생성 |
| `RedisFeeder.push(redis, ticker, profile_data)` | `None` (async) | Redis에 프로파일 발행 |

#### 현재 파일 매핑

- `src/indicators/volume_profile/accumulator.py` (243줄)
- `src/indicators/volume_profile/calculator.py` (199줄)
- `src/indicators/volume_profile/signal_generator.py` (137줄)
- `src/indicators/volume_profile/redis_feeder.py` (324줄)
- `src/indicators/volume_profile/config.py` (51줄) — `POC_PROXIMITY_PCT` 등 상수
- `src/indicators/volume_profile/models.py` (106줄)

#### 체크리스트

- [ ] `Accumulator` → 순수 데이터 구조 + `add_tick()` Atom
- [ ] `PocCalculator.find_poc()` + `find_value_area()` 순수 함수 분리
- [ ] `RedisFeeder` 324줄 → Manager + Atoms으로 분리

---

### F3.9 WhaleTracker

**모듈 ID**: `F3.9`
**역할**: 실시간 틱 스트림에서 블록 트레이드와 아이스버그 오더를 감지하여 기관 매매 압력을 수치화한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `tick_data` | `list[TickData]` | 웹소켓 틱 스트림 |
| `block_threshold` | `float` | 기본값 $200,000 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `WhaleSignal` | 고래 활동 신호 |

```python
@dataclass
class WhaleSignal:
    ticker: str
    block_trades: list[dict]    # 감지된 블록 트레이드 목록
    iceberg_detected: bool      # 아이스버그 오더 감지 여부
    whale_score: float          # -1.0(강한 매도) ~ +1.0(강한 매수)
    net_flow: float             # 순 매수 흐름 (USD)
    confidence: float           # 신뢰도 (이벤트 수 기반)
    dominant_side: Literal["buy", "sell", "neutral"]
```

#### 감지 기준

| 유형 | 기준 |
|---|---|
| BlockDetector | 단일 거래 $200,000 이상 |
| IcebergDetector | 1초 내 5회 이상 동일 가격대 거래 |
| 고신뢰도 | 이벤트 3개 이상 (30초 집계 창) |

#### 내부 Atom 함수 (현재 파일 기반)

| Atom (파일) | 서명 | 설명 |
|---|---|---|
| `BlockDetector.detect(tick: TickData, threshold: float)` | `BlockTradeSignal \| None` | 블록 트레이드 감지 |
| `IcebergDetector.detect(ticks: list[TickData])` | `IcebergSignal \| None` | 아이스버그 오더 감지 |
| `WhaleScorer.score(blocks: list, icebergs: list, window_sec: float)` | `WhaleScore` | 30초 집계 종합 점수 |

#### 현재 파일 매핑

- `src/indicators/whale/block_detector.py` (216줄)
- `src/indicators/whale/iceberg_detector.py` (227줄)
- `src/indicators/whale/whale_scorer.py` (175줄)
- `src/indicators/whale/models.py` (95줄) — BlockTradeSignal, IcebergSignal, WhaleScore

#### 체크리스트

- [ ] `BlockDetector` 216줄 → `detect_block()` + `is_block_size()` Atom으로 분리
- [ ] `IcebergDetector` 227줄 → `detect_iceberg()` + `is_iceberg_pattern()` Atom으로 분리
- [ ] `WhaleScorer` `_SCORING_WINDOW = 30.0` 상수 → `core/constants.py`

---

### F3.10 MACDDivergence

**모듈 ID**: `F3.10`
**역할**: 가격과 MACD 히스토그램 간의 다이버전스를 감지하여 추세 반전 신호를 생성한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `price_history` | `PriceHistory` | F3.1 PriceDataFetcher |
| `macd_data` | `dict` | F3.2 TechnicalCalculator `macd` 출력 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `DivergenceSignal` | MACD 다이버전스 신호 |

```python
@dataclass
class DivergenceSignal:
    ticker: str
    bullish_divergence: bool    # 가격 저점 하락 + MACD 저점 상승 (매수 신호)
    bearish_divergence: bool    # 가격 고점 상승 + MACD 고점 하락 (매도 신호)
    strength: float             # 0.0 ~ 1.0 다이버전스 강도
    lookback_bars: int          # 분석 기간 (봉 수)
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `find_price_lows(closes: list[float], window: int) -> list[int]` | `list[int]` | 가격 저점 인덱스 탐색 |
| `find_price_highs(closes: list[float], window: int) -> list[int]` | `list[int]` | 가격 고점 인덱스 탐색 |
| `find_macd_lows(histogram: list[float], window: int) -> list[int]` | `list[int]` | MACD 저점 인덱스 탐색 |
| `detect_bullish_divergence(price_lows, macd_lows, closes, histogram) -> tuple[bool, float]` | `(bool, float)` | 상승 다이버전스 감지 + 강도 |
| `detect_bearish_divergence(price_highs, macd_highs, closes, histogram) -> tuple[bool, float]` | `(bool, float)` | 하락 다이버전스 감지 + 강도 |

#### 현재 파일 매핑

- `src/indicators/macd_divergence.py` (713줄)
- 713줄 단일 파일: Manager + Atoms으로 즉시 분리 필요

#### 체크리스트

- [ ] 713줄 → Manager 50줄 + 5개 Atom으로 분리 (최우선)
- [ ] `find_price_lows()` + `find_price_highs()` 공통 추상화 가능한지 검토
- [ ] 다이버전스 강도 계산 로직 Atom 분리

---

### F3.11 ContangoDetector

**모듈 ID**: `F3.11`
**역할**: VIX 선물 구조(프록시)와 실제 ETF 수익률 추적으로 레버리지 ETF의 컨탱고/백워데이션 상태를 감지한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `vix` | `float` | F3.1 PriceDataFetcher (FRED VIXCLS) |
| `vix3m` | `float \| None` | FRED VIX3M (선택적) |
| `etf_ticker` | `str` | 레버리지 ETF 티커 |
| `underlying_ticker` | `str` | 기초 ETF 티커 (예: QQQ) |
| `daily_returns` | `list[DailyReturn]` | 최근 수익률 이력 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `ContangoResult` | 컨탱고 감지 결과 |

```python
@dataclass
class ContangoResult:
    state: ContangoState        # CONTANGO / BACKWARDATION / NEUTRAL
    drag_pct: float             # 컨탱고 드래그 (%) — 음수이면 이익
    term_structure_signal: str  # "bearish_for_long" / "bullish_for_long" / "neutral"
    recommendation: str         # 포지션 조정 권고
    vix_spread: float           # VIX - VIX3M 스프레드
```

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `detect_term_structure(vix: float, vix3m: float) -> ContangoState` | `ContangoState` | VIX 선물 구조로 컨탱고/백워데이션 판별 |
| `calc_drag(returns: list[DailyReturn]) -> float` | `float` | 실제 수익률 추적으로 드래그 계산 |
| `classify_severity(drag_pct: float) -> str` | `str` | 드래그 심각도 분류 |
| `build_recommendation(state: ContangoState, drag: float) -> str` | `str` | 포지션 조정 권고 생성 |

#### VIX 기반 판별 규칙

- `VIX > VIX3M` (단기 > 장기) → 백워데이션 → 롱 레버리지에 유리
- `VIX < VIX3M` (단기 < 장기) → 컨탱고 → 롱 레버리지에 불리

#### 현재 파일 매핑

- `src/indicators/contango_detector.py` (391줄)
- `ContangoState` Enum: CONTANGO / BACKWARDATION / NEUTRAL
- `DailyReturn` 데이터클래스: date, etf_return, underlying_return, theoretical_return, drag
- **주의**: NVDD → NVDS 오타 수정 완료

#### 체크리스트

- [ ] `detect_term_structure()` Atom: VIX/VIX3M 프록시 판별 순수 함수
- [ ] `calc_drag()` Atom: `DailyReturn` 리스트에서 평균 드래그 계산
- [ ] 391줄 → Manager + Atoms으로 분리

---

### F3.12 NAVPremiumTracker

**모듈 ID**: `F3.12`
**역할**: 레버리지 ETF의 시장 가격과 이론적 NAV를 비교하여 프리미엄/디스카운트를 추적하고 포지션 크기 조정 계수를 제공한다.

#### IN

| 파라미터 | 타입 | 출처 |
|---|---|---|
| `etf_tickers` | `list[str]` | 레버리지 ETF 유니버스 |
| `etf_price` | `float` | ETF 현재 시장가 |
| `underlying_return_pct` | `float` | 기초 ETF 실시간 수익률 (%) |
| `leverage_factor` | `float` | 레버리지 배수 (예: 2.0) |
| `redis_client` | `aioredis.Redis` | C0.3 |

#### OUT

| 반환 타입 | 설명 |
|---|---|
| `dict[str, NAVPremium]` | 티커별 NAV 프리미엄 결과 |

```python
@dataclass
class NAVPremium:
    ticker: str
    premium_pct: float          # 프리미엄(+) / 디스카운트(-) %
    severity: Literal["high", "medium", "low", "fair"]
    entry_multiplier: float     # 진입 크기 조정 계수
    action: Literal["reduce", "increase", "normal"]
```

#### 조정 계수 기준

| 상태 | 임계값 | 조정 계수 | 액션 |
|---|---|---|---|
| 높은 프리미엄 | ≥ 2.0% | 0.50x | reduce |
| 중간 프리미엄 | ≥ 1.0% | 0.70x | reduce |
| 낮은 프리미엄 | ≥ 0.5% | 0.85x | reduce |
| 공정가치 | -0.5% ~ 0.5% | 1.00x | normal |
| 낮은 디스카운트 | ≤ -0.5% | 1.10x | increase |
| 중간 디스카운트 | ≤ -1.0% | 1.15x | increase |
| 높은 디스카운트 | ≤ -2.0% | 1.20x | increase |

#### 내부 Atom 함수

| Atom | 서명 | 설명 |
|---|---|---|
| `calc_nav_return(underlying_return: float, leverage: float) -> float` | `float` | 이론적 NAV 수익률 계산 |
| `calc_premium_pct(etf_price: float, nav_price: float) -> float` | `float` | 프리미엄/디스카운트 % 계산 |
| `classify_severity(premium_pct: float, thresholds: dict) -> str` | `str` | 심각도 분류 |
| `get_entry_multiplier(premium_pct: float, adj_map: dict) -> float` | `float` | 진입 계수 룩업 |
| `get_cached_nav(redis, ticker: str) -> dict \| None` | `dict \| None` (async) | Redis 캐시 조회 (TTL 15초) |

#### 현재 파일 매핑

- `src/indicators/nav_premium.py` (461줄)
- 캐시 TTL: `_CACHE_TTL = 15.0` 초
- 10개 레버리지 ETF 지원: SOXL, SOXS, QLD, QID, TQQQ, SQQQ, TSLL, TSLS, NVDL, NVDS

#### 체크리스트

- [ ] `calc_nav_return()` 순수 함수 Atom 분리
- [ ] `get_entry_multiplier()` 룩업 테이블 → `core/nav_thresholds.py` 상수
- [ ] 461줄 → Manager + Atoms으로 분리

---

## 모듈 간 의존성 요약

```
F1 (데이터 수집)
    └─ CRAWL_COMPLETE 이벤트 발행
         └─► F2.1 NewsClassifier
                  └─► F2.9 KeyNewsFilter
                  └─► F2.2 RegimeDetector (VIX from F3.1)
                            └─► F2.3 ComprehensiveTeam
                                      └─► F2.4 DecisionMaker
                                                └─► 실행 레이어 (F5 Trading)
                  └─► F2.5 OvernightJudge (장 마감 시)
                  └─► F2.6 ContinuousAnalysis (야간 30분 주기)
                  └─► F2.11 NewsThemeTracker

F3 (지표)
    F3.1 PriceDataFetcher
         └─► F3.2 TechnicalCalculator
                  └─► F3.3 HistoryAnalyzer
                  └─► F3.4 IndicatorAggregator ←── F3.3
                                                ←── F3.7 CrossAssetMomentum
                                                ←── F3.8 VolumeProfile
                                                ←── F3.9 WhaleTracker
                                                ←── F3.10 MACDDivergence
                                                ←── F3.11 ContangoDetector
                                                ←── F3.12 NAVPremiumTracker
    F3.5 IntradayFetcher → F3.6 IntradayCalculator → F3.4 보강

F3.4 CompositeScore → F2.4 DecisionMaker (기술적 지표 20% 가중치)
F2.7 PromptRegistry → F2.1, F2.2, F2.3, F2.4, F2.5, F2.6, F2.10 (프롬프트 제공)
F2.8 FallbackRouter → C0.5 Claude 대체 (Quota 초과 시)
```

---

## 리팩토링 우선순위

| 우선도 | 대상 | 현재 줄수 | 이유 |
|---|---|---|---|
| P0 (즉시) | F1.7 CrawlEngineManager | 1,099줄 | SRP 위반 최대 |
| P0 (즉시) | F2.7 PromptRegistry | 1,896줄 | 단일 파일 과다 |
| P0 (즉시) | F3.10 MACDDivergence | 713줄 | 200줄 초과 |
| P1 (이번 스프린트) | F2.1 NewsClassifier | 623줄 | Manager/Atom 미분리 |
| P1 (이번 스프린트) | F2.9 KeyNewsFilter | 520줄 | Manager/Atom 미분리 |
| P1 (이번 스프린트) | F3.3 HistoryAnalyzer | 501줄 | Manager/Atom 미분리 |
| P2 (다음 스프린트) | F3.2 TechnicalCalculator | 453줄 | Atom 분리 필요 |
| P2 (다음 스프린트) | F2.3 ComprehensiveTeam | 480줄 | Manager/Atom 미분리 |
| P2 (다음 스프린트) | F3.12 NAVPremiumTracker | 461줄 | Manager/Atom 미분리 |
| P3 (백로그) | F3.11 ContangoDetector | 391줄 | 상대적 우선도 낮음 |

---

*이 문서는 defalarm v3 패턴 기준으로 F1~F3 Feature 모듈의 설계 계약을 정의한다.*
*각 체크리스트 항목은 구현 전 반드시 완료 확인이 필요하다.*
