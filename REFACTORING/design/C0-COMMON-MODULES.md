# C0 — Common (공통 인프라) 모듈 설계서

> **문서 버전**: v1.0 | **작성일**: 2026-02-26
> **목적**: 리팩터링 후 모든 Feature 도메인이 공유하는 공통 인프라(인프라 레이어) 모듈을 정의한다.
> **패턴**: defalarm v3 — 각 모듈은 명확한 IN/OUT 명세, 내부 함수 목록, 체크리스트, 현재 파일 매핑을 포함한다.
> **원칙**:
> - 모든 공통 모듈은 `src/common/` 하위에 위치한다.
> - Feature 모듈은 공통 모듈을 **의존성 주입(DI)** 방식으로 사용한다 (직접 import 금지).
> - 공통 모듈끼리의 의존 방향: `C0.1(Config) → C0.2/C0.3/C0.4/C0.7/C0.8` (단방향).
> - 순환 의존성 절대 금지.

---

## 목차

| 모듈 ID | 이름 | 신규 위치 |
|---------|------|-----------|
| C0.1 | ConfigProvider | `src/common/config_provider.py` |
| C0.2 | DatabaseGateway | `src/common/database_gateway.py` |
| C0.3 | CacheGateway | `src/common/cache_gateway.py` |
| C0.4 | HttpClient | `src/common/http_client.py` |
| C0.5 | AiGateway | `src/common/ai_gateway.py` |
| C0.6 | BrokerGateway | `src/common/broker_gateway.py` |
| C0.7 | TelegramGateway | `src/common/telegram_gateway.py` |
| C0.8 | Logger | `src/common/logger.py` |
| C0.9 | ErrorHandler | `src/common/error_handler.py` |
| C0.10 | EventBus | `src/common/event_bus.py` |
| C0.11 | MarketClock | `src/common/market_clock.py` |
| C0.12 | TickerRegistry | `src/common/ticker_registry.py` |

---

## C0.1 ConfigProvider — 환경변수 & 설정 관리

### 역할

`.env` 파일, `strategy_params.json`, `filter_config.json`으로부터 설정값을 로드하고,
타입-안전한 설정 객체를 싱글톤으로 제공한다.
필수 키 누락 시 즉시 프로세스를 중단(fail-fast)하며, 로그에는 시크릿 값을 마스킹한다.
`strategy_params.json`은 핫 리로드를 지원하여 재시작 없이 파라미터를 반영한다.

### IN (입력)

| 소스 | 타입 | 설명 |
|------|------|------|
| `.env` 파일 | 파일 | KIS API 키, DB 접속정보, Telegram 토큰, Redis URL 등 모든 시크릿 |
| `strategy_params.json` | 파일 | 매매 전략 파라미터 (stop-loss 배율, Kelly 분수, Beast Mode 설정 등) |
| `filter_config.json` | 파일 | 크롤러 필터 설정 (블랙리스트, 소스별 가중치 등) |

### OUT (출력)

| 함수 | 반환 타입 | 설명 |
|------|-----------|------|
| `get_settings()` | `Settings` | pydantic BaseSettings 싱글톤. 모든 .env 값 포함 |
| `get_strategy_params()` | `dict[str, Any]` | strategy_params.json 전체 파싱 결과 |
| `get_filter_config()` | `dict[str, Any]` | filter_config.json 전체 파싱 결과 |
| `reload_strategy_params()` | `dict[str, Any]` | 파일을 다시 읽어 최신 파라미터 반환 (핫 리로드) |

### 내부 함수 목록

```python
# --- Atomic ---
def _load_env_file(path: str) -> None:
    """지정된 .env 파일을 로드하고 환경변수를 설정한다."""

def _validate_required_keys(settings: Settings) -> None:
    """필수 키(KIS 계좌번호, DB 패스워드 등)가 모두 설정됐는지 검증한다.
    누락 시 ValueError를 발생시켜 프로세스를 즉시 중단한다."""

def _mask_secret(value: str) -> str:
    """시크릿 문자열을 앞 4자리만 남기고 나머지는 ***로 마스킹한다."""

def _load_json_config(path: str) -> dict[str, Any]:
    """JSON 설정 파일을 로드하여 dict로 반환한다.
    파일 미존재 시 빈 dict를 반환하고 경고 로그를 남긴다."""

# --- Manager ---
def _build_settings_singleton() -> Settings:
    """Settings 싱글톤을 최초 한 번만 생성한다.
    생성 후 _validate_required_keys를 호출한다."""
```

### 체크리스트

- [ ] `db_password`가 비어 있으면 즉시 `ValueError` → 프로세스 종료
- [ ] `kis_real_account`, `kis_virtual_account`가 더미값(`00000000-01`)이면 `ValueError`
- [ ] 로그 출력 시 `app_key`, `app_secret`, `api_secret_key`, `telegram_bot_token` 마스킹
- [ ] `strategy_params.json` 핫 리로드: `reload_strategy_params()` 호출 시 파일 재파싱, 캐시 무효화
- [ ] `filter_config.json` 미존재 시 빈 dict 반환 (크롤러가 graceful degrade)
- [ ] `Settings.database_url` → asyncpg URL, `Settings.sync_database_url` → psycopg2 URL
- [ ] `Settings.redis_url` → 패스워드 유무에 따라 URL 자동 구성
- [ ] `model_config = {"env_file": ".env", "extra": "ignore"}` 유지 (미지정 키 무시)
- [ ] 단위 테스트: 필수 키 누락 시 ValueError, 마스킹 검증, 핫 리로드 검증

### 현재 파일 매핑

| 현재 파일 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| `src/utils/config.py` | `src/common/config_provider.py` | `get_filter_config()`, `reload_strategy_params()` 추가 |
| `strategy_params.json` | `strategy_params.json` (유지) | 변경 없음 |
| `filter_config.json` | `filter_config.json` (유지) | 변경 없음 |

---

## C0.2 DatabaseGateway — PostgreSQL 접속 & 세션

### 역할

비동기 SQLAlchemy 엔진과 세션 팩토리를 싱글톤으로 관리한다.
트랜잭션 자동 커밋/롤백, 벌크 인서트 헬퍼, 헬스체크를 제공한다.
모든 Feature 모듈은 이 게이트웨이를 통해서만 DB에 접근한다.

### IN (입력)

| 소스 | 타입 | 설명 |
|------|------|------|
| `C0.1.get_settings().database_url` | `str` | asyncpg 드라이버 PostgreSQL 연결 URL |
| `C0.1.get_settings().db_echo` | `bool` | SQL 쿼리 로깅 여부 (개발 환경에서만 True) |

### OUT (출력)

| 함수 | 반환 타입 | 설명 |
|------|-----------|------|
| `get_session()` | `AsyncContextManager[AsyncSession]` | 트랜잭션 래핑 비동기 세션 (commit/rollback 자동) |
| `get_engine()` | `AsyncEngine` | 싱글톤 엔진 인스턴스 (테스트 오버라이드용) |
| `init_db()` | `Coroutine[None]` | 시작 시 연결 검증 (`SELECT 1`) |
| `close_db()` | `Coroutine[None]` | 종료 시 엔진 dispose, Redis close |
| `health_check()` | `Coroutine[bool]` | DB 연결 상태 확인 (API 서버 /health 엔드포인트용) |
| `bulk_insert(session, model, rows)` | `Coroutine[int]` | 대량 레코드 삽입, 삽입된 행 수 반환 |

### 내부 함수 목록

```python
# --- Atomic ---
def _build_engine(database_url: str, echo: bool) -> AsyncEngine:
    """커넥션 풀 설정을 포함한 비동기 SQLAlchemy 엔진을 생성한다.
    pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=3600."""

def _build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """세션 팩토리를 생성한다. expire_on_commit=False 설정."""

async def _execute_health_query(session: AsyncSession) -> bool:
    """SELECT 1 쿼리를 실행하여 DB 응답을 확인한다."""

async def _bulk_insert_rows(
    session: AsyncSession,
    model: type,
    rows: list[dict[str, Any]]
) -> int:
    """SQLAlchemy bulk_insert_mappings를 사용하여 다수의 행을 삽입한다."""

# --- Manager ---
@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """트랜잭션 범위 세션을 yield하며 성공 시 commit, 예외 시 rollback한다."""
```

### 체크리스트

- [ ] 커넥션 풀: `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`, `pool_recycle=3600`
- [ ] `get_session()` 컨텍스트 매니저: 항상 `commit` → 예외 발생 시 `rollback` → `close`
- [ ] `bulk_insert()`: `insert().values()` + executemany 패턴, 단건 insert 루프 금지
- [ ] `health_check()`: 1초 타임아웃, `False` 반환 (예외 미전파)
- [ ] `init_db()`: 시작 실패 시 `SystemExit` 발생
- [ ] `close_db()`: 엔진 `dispose()` + Redis `aclose()` (redis-py 5.0.1+)
- [ ] 단위 테스트: 트랜잭션 롤백 검증, 커넥션 풀 설정 검증

### 현재 파일 매핑

| 현재 파일 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| `src/db/connection.py` | `src/common/database_gateway.py` | `health_check()`, `bulk_insert()` 신규 추가 |

> **주의**: `get_redis()`는 C0.3 CacheGateway로 분리한다. `src/db/connection.py`에서 Redis 관련 코드를 제거한다.

---

## C0.3 CacheGateway — Redis CRUD

### 역할

Redis에 대한 모든 읽기/쓰기/삭제/발행/구독 인터페이스를 단일 게이트웨이로 통합한다.
JSON 직렬화/역직렬화를 내장하여 호출부에서 별도 처리가 불필요하다.
모든 키는 `{domain}:{entity}:{id}` 네이밍 컨벤션을 강제한다.
TTL 없는 쓰기는 거부한다 (메모리 누수 방지).

### IN (입력)

| 소스 | 타입 | 설명 |
|------|------|------|
| `C0.1.get_settings().redis_url` | `str` | Redis 연결 URL (패스워드 포함 가능) |
| `C0.1.get_settings().redis_host/port/password` | `str/int/str` | 개별 연결 파라미터 |

### OUT (출력)

| 함수 | 반환 타입 | 설명 |
|------|-----------|------|
| `read(key: str)` | `Coroutine[Any \| None]` | 키로 JSON 역직렬화된 값 조회. 미존재 시 None |
| `write(key: str, value: Any, ttl: int)` | `Coroutine[bool]` | JSON 직렬화 후 저장. TTL 필수 (초 단위) |
| `delete(key: str)` | `Coroutine[bool]` | 키 삭제. 미존재 시 False |
| `exists(key: str)` | `Coroutine[bool]` | 키 존재 여부 확인 |
| `publish(channel: str, message: Any)` | `Coroutine[int]` | 채널에 JSON 직렬화 메시지 발행. 구독자 수 반환 |
| `subscribe(channel: str)` | `AsyncIterator[Any]` | 채널 구독. JSON 역직렬화 메시지 스트림 |
| `get_client()` | `aioredis.Redis` | 원시 Redis 클라이언트 (고급 사용 시에만) |
| `health_check()` | `Coroutine[bool]` | Redis PING 확인 |
| `close()` | `Coroutine[None]` | Redis 연결 종료 (`aclose()` 사용) |

### 내부 함수 목록

```python
# --- Atomic ---
def _build_redis_client(settings: Settings) -> aioredis.Redis:
    """aioredis.Redis 싱글톤을 생성한다.
    decode_responses=True, socket_keepalive=True 설정."""

def _serialize(value: Any) -> str:
    """Python 객체를 JSON 문자열로 직렬화한다.
    datetime은 ISO8601, Decimal은 float로 변환 (default=str)."""

def _deserialize(raw: str) -> Any:
    """JSON 문자열을 Python 객체로 역직렬화한다."""

def _validate_key(key: str) -> None:
    """{domain}:{entity}:{id} 형식의 키인지 검증한다.
    콜론이 최소 1개 없으면 ValueError를 발생시킨다."""

def _validate_ttl(ttl: int) -> None:
    """TTL이 0 이하면 ValueError를 발생시킨다."""

# --- Manager ---
async def _read_with_fallback(client: aioredis.Redis, key: str) -> Any | None:
    """Redis 조회 실패 시 None을 반환하고 에러를 로깅한다 (예외 미전파)."""

async def _subscribe_loop(
    pubsub: aioredis.client.PubSub,
    channel: str
) -> AsyncIterator[Any]:
    """Pub/Sub 채널을 구독하며 수신된 메시지를 역직렬화하여 yield한다."""
```

### 키 네이밍 컨벤션

```
positions:current:{account_id}          # 현재 포지션 캐시
regime:current:global                   # 현재 시장 레짐
price:realtime:{ticker}                 # 실시간 가격
balance:cache:{account_id}             # 잔고 캐시 (TTL=30s)
news:classified:{article_id}            # 분류된 뉴스
trading:control:status                  # 매매 활성화 상태
analysis:continuous:latest              # 최신 연속 분석 결과
```

### 체크리스트

- [ ] 모든 `write()` 호출에 TTL 필수. `ttl <= 0`이면 `ValueError`
- [ ] `_validate_key()`: 콜론(`:`) 미포함 시 `ValueError`
- [ ] `publish()`/`subscribe()`: 메시지 JSON 직렬화, `datetime.isoformat()` 사용
- [ ] `subscribe()`: 구독 취소(unsubscribe) 시 정상 종료, 예외 시 재연결 3회 시도
- [ ] `close()`: `aioredis.Redis.aclose()` 사용 (redis-py 5.0.1+ 호환)
- [ ] `health_check()`: PING 응답 확인, 타임아웃 1초, `False` 반환 (예외 미전파)
- [ ] 단위 테스트: TTL 누락 시 ValueError, 키 형식 검증, JSON 직렬화/역직렬화

### 현재 파일 매핑

| 현재 파일 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| `src/db/connection.py` (get_redis 부분) | `src/common/cache_gateway.py` | 독립 모듈로 분리, 키 검증 + TTL 강제 추가 |
| `src/main.py` (Redis 직접 호출 다수) | → CacheGateway 경유로 교체 | - |
| `src/executor/position_monitor.py` (Redis) | → CacheGateway 경유로 교체 | - |
| `src/analysis/regime_detector.py` (Redis) | → CacheGateway 경유로 교체 | - |

---

## C0.4 HttpClient — 외부 HTTP 통신

### 역할

비동기 HTTP 클라이언트 풀을 관리하고, 지수 백오프 재시도 로직을 제공한다.
도메인 예외 매핑을 통해 HTTP 상태 코드를 의미 있는 예외로 변환한다.
모든 외부 API 통신(KIS, FRED, Finnhub, AlphaVantage, Telegram 등)은 이 클라이언트를 사용한다.

### IN (입력)

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `timeout` | `float` | `30.0` | 요청 타임아웃 (초) |
| `max_connections` | `int` | `100` | 최대 동시 연결 수 |
| `max_keepalive_connections` | `int` | `20` | Keep-alive 유지 연결 수 |

### OUT (출력)

| 함수 | 반환 타입 | 설명 |
|------|-----------|------|
| `create_client(timeout, max_connections)` | `httpx.AsyncClient` | 설정이 적용된 비동기 HTTP 클라이언트 생성 |
| `retry_with_backoff(fn, max_retries, base_delay)` | `Coroutine[Response]` | 지수 백오프 재시도 래퍼. 최종 실패 시 NetworkError |
| `get_shared_client()` | `httpx.AsyncClient` | 공유 싱글톤 클라이언트 (수명: 애플리케이션 전체) |
| `close_shared_client()` | `Coroutine[None]` | 공유 클라이언트 종료 |

### 내부 함수 목록

```python
# --- Atomic ---
def _build_client(
    timeout: float,
    max_connections: int,
    max_keepalive_connections: int
) -> httpx.AsyncClient:
    """httpx.AsyncClient를 limits와 timeout 설정을 적용하여 생성한다."""

def _is_retryable_status(status_code: int) -> bool:
    """재시도 대상 HTTP 상태코드(429, 500, 502, 503, 529)인지 확인한다."""

def _map_status_to_exception(status_code: int, message: str) -> Exception:
    """HTTP 상태 코드를 도메인 예외로 변환한다.
    401/403 → AuthError, 404 → NotFoundError, 429 → RateLimitError, 5xx → NetworkError."""

def _calculate_backoff_delay(attempt: int, base_delay: float) -> float:
    """지수 백오프 대기 시간을 계산한다. 2^attempt * base_delay, 최대 60초."""

# --- Manager ---
async def retry_with_backoff(
    fn: Callable[[], Coroutine[Response]],
    max_retries: int = 3,
    base_delay: float = 1.0
) -> Response:
    """비동기 함수를 최대 max_retries 회 재시도한다.
    재시도 대상: 네트워크 오류, 재시도 가능 HTTP 상태코드.
    최종 실패 시 NetworkError를 발생시킨다."""
```

### 체크리스트

- [ ] 재시도 대상 상태코드: `{429, 500, 502, 503, 529}` (KIS API와 Claude API 동일)
- [ ] 최대 재시도 횟수: 3회, 지수 백오프 딜레이: `1s → 2s → 4s` (최대 60초)
- [ ] 공유 클라이언트: 애플리케이션 시작 시 1회 생성, 종료 시 `aclose()`
- [ ] 타임아웃: 연결 5초, 읽기 30초 (KIS API 기준), 크롤러는 별도 5초 설정 가능
- [ ] User-Agent 헤더 기본값 설정
- [ ] 단위 테스트: 재시도 로직 검증, 도메인 예외 매핑 검증

### 현재 파일 매핑

| 현재 파일 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| `src/executor/kis_client.py` (httpx 직접 사용) | → HttpClient 경유로 교체 | 재시도 로직 HttpClient로 위임 |
| `src/monitoring/fred_client.py` (httpx 직접 사용) | → HttpClient 경유로 교체 | - |
| `src/crawler/*.py` (aiohttp/httpx 혼재) | → HttpClient 통일 | aiohttp → httpx 통일 |

---

## C0.5 AiGateway — Claude API + MLX 로컬 추론

### 역할

Claude API(Opus/Sonnet/Haiku)와 MLX 로컬 모델(Qwen3-30B-A3B)을 단일 게이트웨이로 통합한다.
태스크 타입별 모델 자동 라우팅, 토큰 사용량 추적, Quota 관리, 로컬 MLX 자동 폴백을 제공한다.
모든 AI 관련 호출은 반드시 이 게이트웨이를 경유한다.

### IN (입력)

| 소스 | 타입 | 설명 |
|------|------|------|
| `C0.1.get_settings().claude_mode` | `str` | `"local"` (Claude Code MAX CLI) 또는 `"api"` (Anthropic API) |
| `C0.1.get_settings().anthropic_api_key` | `str` | API 모드에서만 필요. local 모드 시 불필요 |
| `task_type` | `str` | 모델 라우팅 키. 예: `"trading_decision"`, `"news_classification"` |
| `system_prompt` | `str` | 시스템 프롬프트 |
| `user_prompt` | `str` | 사용자 프롬프트 |

### OUT (출력)

| 함수 | 반환 타입 | 설명 |
|------|-----------|------|
| `route_model(task_type: str)` | `str` | 태스크에 최적화된 모델 ID 반환 (opus/sonnet/haiku/local) |
| `send_text(system_prompt, user_prompt, model)` | `Coroutine[str]` | 텍스트 응답 반환. 실패 시 AiError |
| `send_json(system_prompt, user_prompt, model)` | `Coroutine[dict]` | JSON 파싱 응답 반환. 파싱 실패 시 AiError |
| `send_with_tools(system_prompt, user_prompt, tools)` | `Coroutine[ToolResult]` | 도구 호출 결과 반환 |
| `local_classify(text: str)` | `Coroutine[ClassificationResult]` | MLX Qwen3를 통한 로컬 분류 |
| `get_quota_status()` | `QuotaInfo` | 현재 API 사용량, 남은 Quota, 폴백 상태 반환 |

### 데이터 타입

```python
@dataclass
class ClassificationResult:
    """MLX 로컬 분류 결과."""
    relevance: str       # "high" | "medium" | "low"
    sentiment: str       # "bullish" | "bearish" | "neutral"
    impact: str          # "high" | "medium" | "low"
    confidence: float    # 0.0 ~ 1.0
    summary: str
    tickers_affected: list[str]

@dataclass
class QuotaInfo:
    """API Quota 상태."""
    total_calls: int
    used_calls: int
    remaining_calls: int
    fallback_active: bool
    last_error: str | None
    window_reset_at: datetime

@dataclass
class ToolResult:
    """도구 호출 결과."""
    content: str
    tool_calls: list[dict[str, Any]]
    model: str
    usage: dict[str, int]
```

### 모델 라우팅 테이블

| task_type | 모델 | 이유 |
|-----------|------|------|
| `trading_decision` | opus | 최고 정확도 필요 |
| `overnight_judgment` | opus | 리스크 판단 |
| `regime_detection` | opus | 시장 체제 분석 |
| `comprehensive_*` | opus | 3분석관 종합 |
| `news_classification` | sonnet | 속도 우선 |
| `delta_analysis` | sonnet | 빠른 델타 분석 |
| `crawl_verification` | sonnet | 대량 처리 |
| `telegram_intent` | sonnet | 실시간 응답 |

### 내부 함수 목록

```python
# --- Atomic ---
def _load_model_routing_table() -> dict[str, str]:
    """태스크 타입 → 모델 ID 매핑 테이블을 반환한다."""

async def _call_claude_api(
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int
) -> str:
    """Anthropic API를 직접 호출한다. 429 시 QuotaExhaustedError 발생."""

async def _call_claude_cli(
    model_id: str,
    system_prompt: str,
    user_prompt: str
) -> str:
    """Claude Code CLI를 subprocess로 호출한다.
    CLAUDECODE 환경변수를 unset하여 중첩 세션 오류를 방지한다."""

async def _call_mlx_local(text: str) -> ClassificationResult:
    """MLX Qwen3-30B-A3B를 사용하여 로컬 추론을 수행한다.
    confidence < 0.90 시 낮은 신뢰도 경고 로그를 남긴다."""

def _parse_json_response(raw: str) -> dict[str, Any]:
    """응답에서 JSON 블록을 추출하고 파싱한다.
    ```json ... ``` 코드블록 패턴 우선 파싱, 실패 시 전체 문자열 파싱 시도."""

def _track_token_usage(model_id: str, input_tokens: int, output_tokens: int) -> None:
    """모델별 토큰 사용량을 누적 추적한다. Quota 계산에 사용된다."""

# --- Manager ---
async def send_text(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    task_type: str | None = None
) -> str:
    """Claude API 또는 로컬 모델을 통해 텍스트 응답을 반환한다.
    Quota 초과 또는 API 장애 시 자동으로 로컬 MLX로 폴백한다."""

async def _handle_quota_exceeded() -> None:
    """Quota 소진 시 폴백 상태를 활성화하고 Telegram 경고를 발송한다."""
```

### 체크리스트

- [ ] `claude_mode="local"` 시 API 키 불필요, Quota 추적 건너뜀 (MAX 플랜 무제한)
- [ ] `claude_mode="api"` 시 `QuotaGuard` 연동, 90% 사용 시 폴백 전환
- [ ] CLI 모드 subprocess 호출 시 `CLAUDECODE` 환경변수 `unset` (중첩 세션 방지)
- [ ] CLI 호출 시 `--max-tokens` 플래그 사용 금지 (미지원)
- [ ] JSON 파싱: ```json ``` 코드블록 패턴 우선, 실패 시 전체 문자열 재시도
- [ ] MLX 폴백: `confidence < 0.90` 시 매매 스킵 권고 (AiGateway가 결정하지 않음, 호출부 판단)
- [ ] `FallbackRouter.call()` 반환값은 `dict` → `.get("content", "")` 추출 후 파서 전달
- [ ] `datetime` 직렬화: 프롬프트 빌더에서 `json.dumps(default=str)` 필수
- [ ] 토큰 사용량: 모델별 분리 추적, `/api/system/quota` 엔드포인트에서 조회 가능
- [ ] 단위 테스트: 모델 라우팅 검증, JSON 파싱 검증, 폴백 전환 검증

### 현재 파일 매핑

| 현재 파일 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| `src/analysis/claude_client.py` | `src/common/ai_gateway.py` | 통합 |
| `src/ai/mlx_classifier.py` | `src/common/ai_gateway.py` (또는 `src/common/ai_mlx.py`) | AiGateway의 Atomic 모듈로 통합 |
| `src/safety/quota_guard.py` | `src/common/ai_gateway.py` (내부 QuotaGuard) | 외부 노출 제거 |
| `src/fallback/fallback_router.py` | `src/common/ai_gateway.py` (내부 FallbackRouter) | AiGateway에 내재화 |

---

## C0.6 BrokerGateway — KIS OpenAPI 인증 & 통신

### 역할

한국투자증권(KIS) OpenAPI와의 모든 인증 및 통신을 단일 게이트웨이로 통합한다.
실전/모의 듀얼 인증, 1-day-1-token 정책, 토큰 파일 영속성, 거래소 코드 자동 매핑을 관리한다.
가상 거래에서 시장가 주문을 자동으로 지정가(±0.5%)로 변환한다.

### IN (입력)

| 소스 | 타입 | 설명 |
|------|------|------|
| `C0.1.get_settings().kis_*` | `Settings` | KIS API 키, 시크릿, 계좌번호, 모드 |
| `C0.4.create_client()` | `httpx.AsyncClient` | HTTP 클라이언트 인스턴스 |
| `ticker` | `str` | 종목 코드 (예: "SOXL", "NVDL") |
| `side` | `Literal["buy", "sell"]` | 매수/매도 |
| `qty` | `int` | 수량 |
| `price_type` | `Literal["market", "limit"]` | 주문 유형 |

### OUT (출력)

| 함수 | 반환 타입 | 설명 |
|------|-----------|------|
| `authenticate(virtual: bool)` | `Coroutine[KISAuth]` | 인증 토큰 발급/갱신. 토큰 파일에 영속화 |
| `get_price(ticker: str)` | `Coroutine[PriceData]` | 현재가 조회 (항상 실전 인증 사용) |
| `get_daily_prices(ticker, count)` | `Coroutine[list[PriceData]]` | 일봉 데이터 조회 (최대 100개) |
| `get_balance()` | `Coroutine[BalanceData]` | 잔고 조회 (30초 캐시 적용) |
| `get_buy_power()` | `Coroutine[float]` | 매수 가능 금액 조회 (USD) |
| `place_order(ticker, side, qty, price_type, price)` | `Coroutine[OrderResult]` | 주문 실행. 가상 시장가 → 지정가 자동 변환 |
| `cancel_order(order_id: str)` | `Coroutine[bool]` | 주문 취소 |
| `get_order_status(order_id: str)` | `Coroutine[OrderStatus]` | 주문 상태 조회 |
| `get_exchange_rate()` | `Coroutine[float]` | USD/KRW 환율 조회 |

### 데이터 타입

```python
@dataclass
class PriceData:
    """종목 현재가 데이터."""
    ticker: str
    price: float              # 현재가 (USD)
    open: float               # 시가
    high: float               # 고가
    low: float                # 저가
    volume: int               # 거래량
    timestamp: datetime

@dataclass
class BalanceData:
    """계좌 잔고 데이터."""
    cash_usd: float           # USD 주문가능금액 (VTTS3007R 기준)
    total_value_usd: float    # 총 평가금액
    positions: list[dict[str, Any]]  # 보유 종목 목록

@dataclass
class OrderResult:
    """주문 실행 결과."""
    order_id: str
    ticker: str
    side: str
    qty: int
    price: float
    status: str               # "submitted" | "filled" | "rejected"
    timestamp: datetime

@dataclass
class OrderStatus:
    """주문 상태."""
    order_id: str
    status: str               # "pending" | "filled" | "cancelled" | "rejected"
    filled_qty: int
    avg_price: float
```

### 내부 함수 목록

```python
# --- Atomic ---
async def _load_token_from_file(token_path: str) -> KISAuth | None:
    """토큰 파일(data/kis_token.json)에서 저장된 토큰을 로드한다.
    만료 시각이 현재보다 1시간 이상 남아있으면 재사용한다."""

async def _save_token_to_file(auth: KISAuth, token_path: str) -> None:
    """발급된 토큰을 파일에 영속화한다 (1-day-1-token 정책)."""

def _get_exchange_code(ticker: str, for_order: bool) -> str:
    """티커에 대응하는 거래소 코드를 반환한다.
    주문용: NASD/NYSE/AMEX. 시세용: NAS/NYS/AMS."""

def _convert_market_to_limit(price: float, side: str) -> float:
    """가상 거래에서 시장가를 지정가로 변환한다.
    매수: price * 1.005 (+0.5%), 매도: price * 0.995 (-0.5%)."""

def _is_sell_blocked(ticker: str) -> bool:
    """KIS 90000000 에러가 발생한 종목의 매도 재시도를 차단한다.
    _sell_blocked_tickers set에 포함된 종목은 True를 반환한다."""

def _parse_balance_response(response: dict) -> BalanceData:
    """KIS 잔고 조회 응답을 BalanceData로 변환한다.
    가상 모드에서는 VTTS3007R(ord_psbl_frcr_amt)으로 현금 보완한다."""

async def _request_with_auth(
    auth: KISAuth,
    method: str,
    path: str,
    data: dict[str, Any]
) -> dict[str, Any]:
    """인증 헤더를 포함한 KIS API 요청을 실행한다.
    시세 조회 경로는 항상 실전 인증(real_auth)을 사용한다."""

# --- Manager ---
async def place_order(
    ticker: str,
    side: str,
    qty: int,
    price_type: str = "market",
    price: float | None = None
) -> OrderResult:
    """주문을 실행한다.
    가상 모드 + 시장가 → 현재가 조회 후 지정가(±0.5%)로 자동 변환.
    _is_sell_blocked() True이면 OrderResult(status="blocked") 반환."""
```

### 체크리스트

- [ ] 토큰 파일: `data/kis_token.json` (가상), `data/kis_real_token.json` (실전)
- [ ] 1-day-1-token: 발급 후 23시간 이내이면 파일 토큰 재사용
- [ ] 시세 API: 실전/가상 모두 동일한 TR_ID 사용, 항상 `real_auth` URL 경유
- [ ] 거래 API: 가상은 V prefix TR_ID (`VTTT1002U` 등), 실전은 `JTTT1002U`
- [ ] 가상 시장가 주문: 현재가 조회 후 +0.5%/−0.5% 지정가로 자동 변환
- [ ] 잔고 캐시: 30초 TTL, Lock으로 동시 호출 방지, 500 에러 시 캐시 유지 (덮어쓰기 금지)
- [ ] 가상 잔고 현금: `VTTS3007R` 응답의 `ord_psbl_frcr_amt` 필드 사용
- [ ] KIS 90000000 에러: `_sell_blocked_tickers` 추가, EOD에서 초기화
- [ ] `exchange_rate` API: `_PRICE_API_PATHS`에 포함, `real_auth` 경유
- [ ] 단위 테스트: 토큰 영속성, 시장가→지정가 변환, 잔고 캐시 동시성 검증

### 현재 파일 매핑

| 현재 파일 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| `src/executor/kis_auth.py` | `src/common/broker_gateway.py` (내부 KISAuth) | BrokerGateway의 Atomic으로 통합 |
| `src/executor/kis_client.py` (1261줄) | `src/common/broker_gateway.py` | 리팩터링, 분류 명확화 |

---

## C0.7 TelegramGateway — Telegram Bot 발송

### 역할

Telegram Bot API를 통해 다중 수신자에게 메시지와 이미지를 발송하는 단일 게이트웨이를 제공한다.
기존 `telegram_notifier.py`의 717줄에서 순수 발송 인프라만 추출하여 독립 모듈로 분리한다.
비즈니스 로직(알림 내용 구성, 등급 판단 등)은 각 Feature 모듈에 위치한다.

### IN (입력)

| 소스 | 타입 | 설명 |
|------|------|------|
| `C0.1.get_settings().telegram_bot_token` | `str` | 1번 수신자 Bot 토큰 |
| `C0.1.get_settings().telegram_chat_id` | `str` | 1번 수신자 Chat ID |
| `C0.1.get_settings().telegram_bot_token_2` | `str` | 2번 수신자 Bot 토큰 (선택) |
| `C0.1.get_settings().telegram_chat_id_2` | `str` | 2번 수신자 Chat ID (선택) |

### OUT (출력)

| 함수 | 반환 타입 | 설명 |
|------|-----------|------|
| `send_text(text, parse_mode)` | `Coroutine[list[int]]` | 모든 수신자에게 텍스트 발송. 성공한 message_id 목록 반환 |
| `send_photo(photo_path, caption, parse_mode)` | `Coroutine[list[int]]` | 이미지 + 캡션 발송 |
| `send_to_recipient(recipient_id, text, parse_mode)` | `Coroutine[int | None]` | 특정 수신자에게만 발송 |
| `is_configured()` | `bool` | 최소 1개 수신자 설정 여부 확인 |

### 내부 함수 목록

```python
# --- Atomic ---
def _build_recipients(settings: Settings) -> list[_Recipient]:
    """설정에서 수신자 목록을 구성한다.
    토큰 또는 Chat ID가 없는 수신자는 제외한다."""

def _escape_markdown(text: str) -> str:
    """Telegram MarkdownV2 특수문자를 이스케이프한다.
    대상: . ! ( ) [ ] { } + - = | > # ~ `"""

async def _send_to_single(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str
) -> int | None:
    """단일 수신자에게 메시지를 발송한다.
    실패 시 None 반환, 예외 미전파 (graceful degradation)."""

async def _send_photo_to_single(
    bot_token: str,
    chat_id: str,
    photo_path: str,
    caption: str,
    parse_mode: str
) -> int | None:
    """단일 수신자에게 이미지를 발송한다."""

def _check_rate_limit() -> bool:
    """Telegram API Rate Limit(30msg/sec)을 초과하지 않는지 확인한다."""

# --- Manager ---
async def send_text(text: str, parse_mode: str = "MarkdownV2") -> list[int]:
    """모든 활성 수신자에게 메시지를 병렬 발송한다.
    수신자가 없으면 로그만 남기고 빈 목록 반환."""
```

### 체크리스트

- [ ] 수신자 미설정 시 graceful degradation (예외 미발생, 로그만 기록)
- [ ] `parse_mode="MarkdownV2"` 사용 시 특수문자 자동 이스케이프
- [ ] 다중 수신자 병렬 발송 (`asyncio.gather`)
- [ ] Rate Limit: 30msg/sec 준수, 초과 시 1초 대기
- [ ] Bot 연결 실패 시 해당 수신자만 비활성화, 나머지 수신자는 계속 발송
- [ ] `send_to_recipient()`: 특정 수신자 ID로만 발송 (알림 선택적 수신 지원)
- [ ] 단위 테스트: 이스케이프 검증, graceful degradation 검증

### 현재 파일 매핑

| 현재 파일 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| `src/monitoring/telegram_notifier.py` (717줄) | `src/common/telegram_gateway.py` | 순수 발송 인프라만 추출. 비즈니스 로직(알림 내용)은 Feature 모듈로 이동 |

---

## C0.8 Logger — 구조화 로깅

### 역할

모듈별 로거를 제공하고, 콘솔 + 날짜별 파일 로테이션 출력을 설정한다.
시크릿 데이터 자동 마스킹, 실행 시간 측정 데코레이터를 제공한다.
루트 로거 설정은 최초 1회만 실행(idempotent)한다.

### IN (입력)

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `name` | `str` | 로거 이름. 보통 `__name__` 전달 |

### OUT (출력)

| 함수 | 반환 타입 | 설명 |
|------|-----------|------|
| `get_logger(name: str)` | `logging.Logger` | 설정이 적용된 모듈별 로거 반환 |
| `setup_logging()` | `None` | 루트 로거 초기화. 중복 호출 무시 |
| `execution_time(logger)` | `Decorator` | 함수 실행 시간을 측정하여 DEBUG 레벨로 로깅 |

### 내부 함수 목록

```python
# --- Atomic ---
def _ensure_log_dir(log_dir: Path) -> None:
    """로그 디렉토리를 생성한다. 이미 존재하면 무시한다."""

def _build_console_handler(level: int) -> logging.StreamHandler:
    """콘솔 핸들러를 생성한다. 포맷: 시각|레벨|모듈|메시지."""

def _build_file_handler(log_dir: Path, level: int) -> TimedRotatingFileHandler:
    """날짜별 로테이션 파일 핸들러를 생성한다. 30일 보관, UTF-8 인코딩."""

def _suppress_noisy_loggers() -> None:
    """외부 라이브러리(httpx, asyncio, aiohttp, urllib3) 로그 레벨을 WARNING으로 제한한다."""

def _mask_sensitive_in_record(record: logging.LogRecord) -> logging.LogRecord:
    """로그 레코드에서 시크릿 패턴(토큰, API 키, 패스워드)을 마스킹한다."""

# --- Manager ---
def setup_logging() -> None:
    """루트 로거에 핸들러를 설정한다. 최초 1회만 실행된다.
    C0.1에서 log_level을 읽어 적용한다."""

def execution_time(logger: logging.Logger) -> Callable:
    """함수 실행 시간을 DEBUG 레벨로 로깅하는 데코레이터를 반환한다."""
```

### 로그 포맷

```
%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s
2026-02-26 23:00:00 | INFO     | src.executor.position_monitor | 포지션 모니터 시작
```

### 체크리스트

- [ ] 콘솔 + 파일 핸들러 동시 출력
- [ ] 파일 로테이션: `when="midnight"`, `backupCount=30`
- [ ] 로그 레벨: `C0.1.get_settings().log_level` 기반, 기본값 `INFO`
- [ ] 외부 라이브러리 레벨 제한: `httpx`, `httpcore`, `urllib3`, `asyncio`, `aiohttp`
- [ ] `get_logger()`: `setup_logging()` 자동 호출 (명시적 호출 불필요)
- [ ] `execution_time` 데코레이터: async/sync 함수 모두 지원
- [ ] 단위 테스트: 중복 초기화 방지, 파일 핸들러 생성 검증

### 현재 파일 매핑

| 현재 파일 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| `src/utils/logger.py` (78줄) | `src/common/logger.py` | `execution_time` 데코레이터, 시크릿 마스킹 추가 |

---

## C0.9 ErrorHandler — 예외 처리

### 역할

시스템 전체에서 일관된 도메인 예외 계층 구조를 정의하고,
예외 → HTTP 상태 코드 매핑 및 FastAPI 전역 예외 핸들러를 제공한다.
재시도 가능 여부를 분류하여 HttpClient와 AiGateway의 재시도 로직을 지원한다.

### IN (입력)

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `exception` | `Exception` | 처리할 예외 인스턴스 |
| `app` | `FastAPI` | 전역 핸들러 등록 대상 |

### OUT (출력)

| 클래스 / 함수 | 타입 | 설명 |
|--------------|------|------|
| `TradingSystemError` | `Exception` | 기반 예외 클래스 |
| `ValidationError` | `TradingSystemError` | 입력값 검증 실패 |
| `AuthError` | `TradingSystemError` | 인증/인가 실패 (HTTP 401/403) |
| `BrokerError` | `TradingSystemError` | KIS API 호출 실패 |
| `AiError` | `TradingSystemError` | Claude/MLX 호출 실패 |
| `NetworkError` | `TradingSystemError` | HTTP 통신 실패 |
| `QuotaError` | `AiError` | API Quota 소진 |
| `RateLimitError` | `NetworkError` | Rate Limit 초과 (재시도 가능) |
| `register_global_handlers(app)` | `None` | FastAPI 앱에 전역 예외 핸들러 등록 |
| `is_retryable(exc)` | `bool` | 재시도 가능한 예외인지 확인 |
| `to_http_status(exc)` | `int` | 예외를 HTTP 상태 코드로 변환 |

### 예외 계층 구조

```
TradingSystemError
├── ValidationError          # 400
├── AuthError                # 401/403
│   └── TokenExpiredError    # 401
├── NotFoundError            # 404
├── BrokerError              # 502
│   ├── OrderError           # 주문 실패
│   └── BalanceError         # 잔고 조회 실패
├── AiError                  # 503
│   ├── QuotaError           # Quota 소진
│   └── ModelError           # 모델 추론 실패
└── NetworkError             # 503
    └── RateLimitError       # 429, 재시도 가능
```

### 내부 함수 목록

```python
# --- Atomic ---
def _map_exception_to_status(exc: TradingSystemError) -> int:
    """도메인 예외를 HTTP 상태 코드로 매핑한다."""

def _format_error_response(exc: TradingSystemError) -> dict[str, Any]:
    """API 에러 응답 JSON을 생성한다.
    {"error": {"code": str, "message": str, "type": str}}"""

def _is_retryable_exception(exc: Exception) -> bool:
    """재시도 가능한 예외인지 확인한다.
    RateLimitError, NetworkError, 일부 BrokerError는 True."""

# --- Manager ---
def register_global_handlers(app: FastAPI) -> None:
    """FastAPI 앱에 TradingSystemError와 ValueError 전역 핸들러를 등록한다."""
```

### 체크리스트

- [ ] 모든 도메인 예외는 `TradingSystemError`를 상속
- [ ] `BrokerError`: KIS `rt_cd`, `msg_cd`, `msg` 필드 보존
- [ ] `AiError`: 모델 ID, 태스크 타입 필드 보존
- [ ] `is_retryable()`: `RateLimitError`, `NetworkError` → True, `AuthError`, `ValidationError` → False
- [ ] FastAPI 전역 핸들러: `TradingSystemError` → JSON 응답, `Exception` → 500 + 로깅
- [ ] 에러 응답에 시크릿 정보(토큰, 패스워드) 포함 금지
- [ ] 단위 테스트: 예외 계층 상속, HTTP 상태 매핑, 재시도 분류

### 현재 파일 매핑

| 현재 파일 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| 전체 코드베이스 (try/except 분산) | `src/common/error_handler.py` | 도메인 예외 중앙화 |
| `src/executor/kis_auth.py` (`KISAuthError`) | → `BrokerError.AuthError` | 통합 |
| `src/executor/kis_client.py` (`KISAPIError`, `KISOrderError`) | → `BrokerError`, `OrderError` | 통합 |
| `src/safety/quota_guard.py` (`QuotaExhaustedError`) | → `QuotaError` | 통합 |

---

## C0.10 EventBus — Feature 간 이벤트

### 역할

Feature 모듈 간 직접 호출을 제거하고 비동기 이벤트 기반 통신으로 전환한다.
이벤트 발행/구독 패턴을 통해 모듈 간 결합도를 낮춘다.
Dead Letter Queue로 처리 실패 이벤트를 보존하고, 이벤트 히스토리를 최근 100개까지 유지한다.

### IN (입력)

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `event_type` | `str` | 이벤트 식별자 (예: `"CRAWL_COMPLETE"`) |
| `payload` | `dict[str, Any]` | 이벤트 데이터 |
| `callback` | `Callable[[Event], Coroutine]` | 이벤트 수신 시 실행할 비동기 콜백 |

### OUT (출력)

| 함수 | 반환 타입 | 설명 |
|------|-----------|------|
| `publish(event_type, payload)` | `Coroutine[None]` | 이벤트 발행. 모든 구독자에게 비동기 전달 |
| `subscribe(event_type, callback)` | `str` | 구독 등록. subscription_id 반환 |
| `unsubscribe(subscription_id)` | `bool` | 구독 해제 |
| `get_event_history(event_type, limit)` | `list[Event]` | 최근 이벤트 히스토리 조회 |
| `get_dead_letters(limit)` | `list[Event]` | 처리 실패 이벤트 조회 |

### 이벤트 정의

```python
@dataclass
class Event:
    """시스템 이벤트."""
    event_type: str
    payload: dict[str, Any]
    event_id: str           # UUID
    published_at: datetime
    source_module: str      # 발행 모듈명

# 정의된 이벤트 타입
class EventType:
    CRAWL_COMPLETE = "CRAWL_COMPLETE"       # payload: {article_ids: list[str], count: int}
    NEWS_CLASSIFIED = "NEWS_CLASSIFIED"     # payload: {article_ids: list[str]}
    REGIME_CHANGED = "REGIME_CHANGED"       # payload: {old_regime: str, new_regime: str, vix: float}
    TRADE_EXECUTED = "TRADE_EXECUTED"       # payload: {ticker: str, side: str, price: float, qty: int}
    POSITION_UPDATED = "POSITION_UPDATED"  # payload: {positions: list[dict]}
    EMERGENCY_TRIGGERED = "EMERGENCY_TRIGGERED"  # payload: {reason: str, severity: str}
    EOD_COMPLETE = "EOD_COMPLETE"           # payload: {report: dict}
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE" # payload: {analysis_id: str, result: dict}
```

### 내부 함수 목록

```python
# --- Atomic ---
def _generate_event_id() -> str:
    """UUID4 기반 이벤트 ID를 생성한다."""

def _build_event(event_type: str, payload: dict, source_module: str) -> Event:
    """Event 인스턴스를 생성한다."""

async def _deliver_to_subscriber(
    callback: Callable,
    event: Event
) -> bool:
    """단일 구독자에게 이벤트를 전달한다.
    실패 시 False 반환, Dead Letter Queue에 추가한다."""

def _add_to_history(event: Event) -> None:
    """이벤트 히스토리에 추가한다. 최대 100개 유지 (FIFO)."""

def _add_to_dead_letters(event: Event, error: str) -> None:
    """처리 실패 이벤트를 Dead Letter Queue에 추가한다. 최대 50개 유지."""

# --- Manager ---
async def publish(event_type: str, payload: dict[str, Any], source_module: str = "") -> None:
    """이벤트를 모든 구독자에게 asyncio.gather로 병렬 전달한다.
    구독자 오류는 Dead Letter Queue에 기록하고, 다른 구독자 전달을 계속한다."""
```

### 체크리스트

- [ ] 구독자 콜백 실패가 다른 구독자 전달을 막지 않음 (격리)
- [ ] 이벤트 히스토리: 타입별 최근 100개 유지 (메모리 효율)
- [ ] Dead Letter Queue: 최근 50개 유지, `/api/system/dead-letters` 엔드포인트로 조회 가능
- [ ] 구독 해제: `unsubscribe(subscription_id)` 정상 동작
- [ ] `EMERGENCY_TRIGGERED` 이벤트: 모든 구독자에게 최우선 전달 (gather 앞에 배치)
- [ ] 현재 코드베이스의 직접 모듈 호출 → EventBus 이벤트로 점진적 전환
- [ ] 단위 테스트: 이벤트 전달, 구독 해제, Dead Letter 기록 검증

### 현재 파일 매핑

| 현재 상황 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| 없음 (모듈 간 직접 호출) | `src/common/event_bus.py` | 신규 구현 |
| `src/main.py` (직접 모듈 호출) | → EventBus 구독/발행으로 교체 | 점진적 전환 |

---

## C0.11 MarketClock — 시장 시간 & 세션

### 역할

미국 주식 시장 시간(KST 기준)과 세션 타입을 관리한다.
DST(서머타임) 자동 처리, US 공휴일 관리, 세션별 동적 루프 주기를 제공한다.
기존 `market_hours.py` 692줄을 원자적 함수로 재구성한다.

### IN (입력)

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `dt` | `datetime \| None` | 확인할 시점. None이면 현재 KST 시각 사용 |

### OUT (출력)

| 함수 | 반환 타입 | 설명 |
|------|-----------|------|
| `is_trading_window()` | `bool` | 자동매매 운영 윈도우 여부 (20:00~익일 07:00 KST) |
| `is_trading_day(dt)` | `bool` | 거래일 여부 (주말, 미국 공휴일 제외) |
| `get_session_type(dt)` | `SessionType` | 현재 세션 타입 반환 |
| `get_session_phase(dt)` | `SessionPhase` | 세분화된 세션 페이즈 반환 |
| `get_optimal_loop_interval(dt)` | `int` | 세션 페이즈별 최적 루프 주기(초) |
| `get_optimal_monitor_interval(dt)` | `int` | 세션 페이즈별 최적 모니터링 주기(초) |
| `is_rebalancing_window(dt)` | `bool` | 레버리지 ETF 리밸런싱 시간대 (15:45~16:00 ET) |
| `is_danger_zone(dt)` | `bool` | Beast Mode 금지 시간대 (09:30~10:00, 15:30~16:00 ET) |
| `get_market_schedule(dt)` | `MarketSchedule` | 해당 날짜 전체 시장 스케줄 (KST 기준) |
| `time_until_open(dt)` | `timedelta` | 다음 정규장 개장까지 남은 시간 |
| `time_until_close(dt)` | `timedelta` | 정규장 마감까지 남은 시간 |
| `should_eod_close(dt, minutes_before)` | `bool` | EOD 청산 시점 여부 (기본 30분 전) |

### 데이터 타입

```python
class SessionType(str, Enum):
    """시장 세션 타입."""
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_MARKET = "after_market"
    CLOSED = "closed"

class SessionPhase(str, Enum):
    """세분화된 세션 페이즈."""
    PRE_MARKET = "pre_market"    # 프리마켓
    POWER_OPEN = "power_open"    # 09:30~10:00 ET (루프 90초)
    MID_SESSION = "mid_session"  # 10:00~15:00 ET (루프 180초)
    POWER_HOUR = "power_hour"    # 15:00~16:00 ET (루프 120초)
    AFTER_HOURS = "after_hours"  # 애프터마켓
    CLOSED = "closed"            # 휴장

@dataclass
class MarketSchedule:
    """시장 스케줄 정보."""
    pre_market_start: datetime
    regular_open: datetime
    regular_close: datetime
    after_market_end: datetime
    is_trading_day: bool
```

### 내부 함수 목록

```python
# --- Atomic ---
def _now_kst() -> datetime:
    """현재 KST timezone-aware datetime을 반환한다."""

def _to_eastern(dt: datetime) -> datetime:
    """datetime을 US/Eastern으로 변환한다."""

def _to_kst(dt: datetime) -> datetime:
    """datetime을 KST로 변환한다."""

def _is_dst(dt: datetime) -> bool:
    """서머타임(EDT) 적용 여부를 확인한다. UTC offset이 -4시간이면 EDT."""

def _is_us_holiday(d: date) -> bool:
    """NYSE 휴장일인지 확인한다. 2025~2027 하드코딩."""

def _is_trading_day_us(d: date) -> bool:
    """미국 동부 기준 거래일인지 확인한다 (주말 + 공휴일 제외)."""

def _get_session_times_et(target_date: date) -> dict[str, datetime]:
    """주어진 날짜의 ET 기준 세션 시작/종료 시각을 반환한다."""

def _get_window_start_hour() -> int:
    """운영 윈도우 시작 시각(KST 시)을 반환한다. 고정값 20."""

# --- Manager ---
def get_session_phase(dt: datetime | None = None) -> SessionPhase:
    """정규장을 Power Open/Mid/Power Hour로 세분화하여 반환한다."""

def get_optimal_loop_interval(dt: datetime | None = None) -> int:
    """세션 페이즈에 따라 루프 주기를 반환한다.
    power_open=90, mid=180, power_hour=120, 비정규=900."""
```

### 세션 타임라인 (KST 기준, 비서머타임)

```
18:00  프리마켓 시작 (비DST) / 17:00 (DST)
20:00  운영 윈도우 시작 (크롤러, 분석 준비)
23:30  정규장 개장 (비DST) / 22:30 (DST)
23:30~01:00  Power Open (루프 90초)
01:00~07:00  Mid Session (루프 180초)
07:00~08:00  Power Hour (루프 120초)
07:45~08:00  리밸런싱 윈도우 (신규 진입 금지)
08:00  정규장 마감 (비DST)
익일 07:00  운영 윈도우 종료
```

### 체크리스트

- [ ] DST 처리: `zoneinfo.ZoneInfo("US/Eastern")` 기반, UTC offset으로 자동 감지
- [ ] 공휴일: 2025~2027 NYSE 기준 하드코딩 (연간 업데이트 필요)
- [ ] `is_danger_zone()`: 09:30~10:00 ET, 15:30~16:00 ET (Beast Mode 차단용)
- [ ] `is_rebalancing_window()`: 15:45~16:00 ET (레버리지 ETF 신규 진입 차단)
- [ ] 운영 윈도우: 토요일 20:00 이후는 False (일요일 새벽 미국 시장 미개장)
- [ ] 모든 반환 datetime은 timezone-aware (naive datetime 반환 금지)
- [ ] 단위 테스트: DST 전환 경계, 공휴일, 주말, 세션 페이즈 분류

### 현재 파일 매핑

| 현재 파일 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| `src/utils/market_hours.py` (692줄) | `src/common/market_clock.py` | `is_danger_zone()` 추가, Enum 타입 도입, 함수 원자화 |

---

## C0.12 TickerRegistry — 티커 매핑 & ETF 유니버스

### 역할

ETF 유니버스(Bull 2X, Bear 2X, 섹터, 크립토), 개별 주식, 레버리지 페어 매핑을 단일 레지스트리로 통합한다.
거래소 코드 매핑, 인버스 페어 조회, Bull/Bear 분류를 제공한다.
메모리 기반으로 운영하되, 향후 DB 백엔드 전환을 위한 인터페이스를 미리 정의한다.

### IN (입력)

| 소스 | 타입 | 설명 |
|------|------|------|
| `src/strategy/etf_universe.py` 상수 | `dict` | Bull/Bear/섹터/크립토 유니버스 초기 데이터 |
| `src/utils/ticker_mapping.py` 상수 | `dict` | Underlying → Leveraged ETF 매핑 |
| `C0.2.get_session()` | `AsyncSession` | 향후 DB 기반 유니버스 관리 시 사용 |

### OUT (출력)

| 함수 | 반환 타입 | 설명 |
|------|-----------|------|
| `get_universe(enabled_only)` | `list[ETFTicker]` | 전체(또는 활성만) ETF 유니버스 반환 |
| `get_bull_universe(enabled_only)` | `list[ETFTicker]` | Bull ETF + 개별주식 목록 |
| `get_bear_universe(enabled_only)` | `list[ETFTicker]` | Bear ETF 목록 |
| `get_inverse_pair(ticker)` | `str \| None` | 인버스 페어 티커 반환. 없으면 None |
| `get_underlying(ticker)` | `str \| None` | 레버리지 ETF의 기초 자산 티커 반환 |
| `get_exchange_code(ticker, for_order)` | `str` | 거래소 코드 반환. 주문용(NASD/NYSE/AMEX), 시세용(NAS/NYS/AMS) |
| `is_bull_etf(ticker)` | `bool` | Bull ETF 여부 |
| `is_bear_etf(ticker)` | `bool` | Bear ETF 여부 |
| `is_individual_stock(ticker)` | `bool` | 개별 주식 여부 (ETF 아님) |
| `toggle_ticker(ticker, enabled)` | `bool` | 티커 활성화/비활성화 (런타임) |
| `get_sector_tickers(sector)` | `list[str]` | 섹터별 티커 목록 반환 |
| `get_underlying_for_analysis(etf_ticker)` | `str` | 분석용 기초 자산 티커 반환 |

### 데이터 타입

```python
@dataclass
class ETFTicker:
    """ETF 또는 주식 종목 메타데이터."""
    ticker: str
    name: str
    underlying: str | None        # 기초 자산 티커 (ETF인 경우)
    exchange: str                 # "NASD" | "NYSE" | "AMEX"
    expense_ratio: float          # 0.0이면 개별 주식
    avg_daily_volume: int
    enabled: bool
    etf_type: str                 # "bull" | "bear" | "sector" | "crypto" | "stock"
    inverse_pair: str | None      # 인버스 페어 티커
    sector: str | None            # 섹터명
```

### 내부 함수 목록

```python
# --- Atomic ---
def _load_bull_universe() -> dict[str, ETFTicker]:
    """etf_universe.py의 BULL_2X_UNIVERSE를 ETFTicker dict로 변환한다."""

def _load_bear_universe() -> dict[str, ETFTicker]:
    """etf_universe.py의 BEAR_2X_UNIVERSE를 ETFTicker dict로 변환한다."""

def _load_individual_stocks() -> dict[str, ETFTicker]:
    """etf_universe.py의 INDIVIDUAL_STOCK_UNIVERSE를 ETFTicker dict로 변환한다."""

def _load_sector_leveraged() -> dict[str, ETFTicker]:
    """etf_universe.py의 SECTOR_LEVERAGED_UNIVERSE를 ETFTicker dict로 변환한다."""

def _build_inverse_pair_index(
    bull: dict[str, ETFTicker],
    bear: dict[str, ETFTicker]
) -> dict[str, str]:
    """Bull ↔ Bear 인버스 페어 양방향 인덱스를 생성한다."""

def _build_underlying_index(
    ticker_mapping: dict[str, dict[str, str | None]]
) -> dict[str, str]:
    """레버리지 ETF → Underlying 역방향 인덱스를 생성한다."""

def _get_exchange_code_for_ticker(ticker: str, for_order: bool) -> str:
    """티커에 대응하는 거래소 코드를 반환한다.
    SOXL, SOXS: AMEX → for_order=True이면 "AMEX", False이면 "AMS".
    기본 NASDAQ: for_order=True이면 "NASD", False이면 "NAS"."""

# --- Manager ---
class TickerRegistry:
    """ETF 유니버스 싱글톤 레지스트리."""

    def __init__(self) -> None:
        """유니버스 모듈 상수에서 deep copy하여 초기화한다."""

    def toggle_ticker(self, ticker: str, enabled: bool) -> bool:
        """런타임에 특정 티커를 활성화/비활성화한다.
        ticker가 존재하지 않으면 False를 반환한다."""
```

### 유니버스 구성

| 분류 | 종목 수 | 설명 |
|------|---------|------|
| Bull 2X ETF | 17종목 | SSO, QLD, SOXL, NVDL 등 |
| Bear 2X ETF | 14종목 | SDS, QID, SOXS, NVDS 등 |
| 섹터 레버리지 | SOXL/SOXS 포함 | 반도체 섹터 3X |
| 크립토 레버리지 | MSTU, CONL 등 | 암호화폐 관련 |
| 개별 주식 | 41종목 | NVDA, AAPL, TSLA 등 (분석용) |

### 체크리스트

- [ ] `NVDL ↔ NVDS`, `SOXL ↔ SOXS`, `TSLL ↔ TSLS` 인버스 페어 정확히 설정
- [ ] 거래소 코드: SOXL/SOXS는 AMEX(`AMS`/`AMEX`), 대부분 ETF는 NASDAQ(`NAS`/`NASD`)
- [ ] `toggle_ticker()`: deep copy된 인스턴스 수정 (원본 상수 불변)
- [ ] `get_universe(enabled_only=True)`: `enabled=True`인 종목만 반환
- [ ] `get_underlying()`: 레버리지 ETF → underlying, 개별 주식은 None
- [ ] 싱글톤 패턴: `get_ticker_registry()` 팩토리 함수로 인스턴스 공유
- [ ] 단위 테스트: 인버스 페어 조회, 거래소 코드 매핑, 토글 동작 검증

### 현재 파일 매핑

| 현재 파일 | 신규 위치 | 변경 내용 |
|-----------|-----------|-----------|
| `src/strategy/etf_universe.py` (888줄) | `src/common/ticker_registry.py` | 클래스 기반 레지스트리로 재구성 |
| `src/utils/ticker_mapping.py` (344줄) | `src/common/ticker_registry.py` | 통합, `ETFTicker` 타입 도입 |
| `src/executor/universe_manager.py` (342줄) | `src/common/ticker_registry.py` | `UniverseManager` → `TickerRegistry` 통합 |

---

## 공통 규칙 요약

### 의존 방향 (단방향)

```
C0.8 (Logger)
    ↑
C0.1 (Config) → C0.2 (DB) → C0.9 (Error)
              → C0.3 (Cache)
              → C0.4 (Http) → C0.5 (AI)
              → C0.7 (Telegram)
              → C0.6 (Broker) [uses C0.4]
              → C0.11 (Clock)
              → C0.12 (Ticker) [uses C0.2]
C0.10 (EventBus) ← 모든 Feature 모듈이 사용
```

### 신규 디렉토리 구조

```
src/
└── common/
    ├── __init__.py
    ├── config_provider.py    # C0.1
    ├── database_gateway.py   # C0.2
    ├── cache_gateway.py      # C0.3
    ├── http_client.py        # C0.4
    ├── ai_gateway.py         # C0.5
    ├── broker_gateway.py     # C0.6
    ├── telegram_gateway.py   # C0.7
    ├── logger.py             # C0.8
    ├── error_handler.py      # C0.9
    ├── event_bus.py          # C0.10
    ├── market_clock.py       # C0.11
    └── ticker_registry.py    # C0.12
```

### 크기 제한

| 파일 | 최대 줄 수 | 비고 |
|------|-----------|------|
| Atomic 함수 | 30줄 | 순수 함수, 단일 책임 |
| Manager 함수 | 50줄 | Atomic 호출 + 데이터 전달만 |
| 모듈 파일 | 200줄 | 초과 시 서브모듈로 분리 |

### 금지 사항

- Feature 모듈에서 `src/common/` 이외의 다른 Feature를 직접 import 금지
- `src/common/` 내 모듈이 Feature 모듈을 역참조 금지 (단방향)
- 순수 무채색(`#000000`, S=0% 그레이) 사용 금지 (Tinted Grey 정책과 무관하게 코드 내 하드코딩 금지)
- `Any` 타입 남용 금지 (명확한 타입 힌트 필수)
- 영어 주석 금지 (한국어 docstring 필수, ~한다/~이다 스타일)
