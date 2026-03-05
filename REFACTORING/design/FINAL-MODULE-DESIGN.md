# Stock Trading AI System V2 -- FINAL MODULE DESIGN (v2.0)

> **작성일**: 2026-02-26
> **버전**: v2.0 FINAL
> **변경점**: 매매 시간 윈도우 변경(20:00~06:30 KST), SecretVault 독점 원칙, IN 다수/OUT 1개 엄격 적용
> **원칙**: 모듈 = 블록. 각 블록은 IN이 여럿이어도 OUT은 반드시 1개이다. 메인 파이프라인은 한 줄로 흐른다.

---

## 1. 설계 원칙

### 1.1 IN 다수 / OUT 1개 원칙 (비협상)

모든 모듈은 **입력(IN)은 여러 개를 받되, 출력(OUT)은 정확히 1개**만 반환한다.
이 원칙은 파이프라인을 일직선으로 유지하고, 모듈 간 계약을 명확히 한다.

```python
# 올바른 예시 -- IN 3개, OUT 1개
def check_obi_gate(
    obi_score: float,       # IN 1: OBI 점수
    threshold: float,       # IN 2: 임계값
    direction: str,         # IN 3: 방향 (bull/bear)
) -> GateResult:            # OUT: 정확히 1개
    """OBI 진입 조건을 검사한다."""
    ...

# 금지 예시 -- OUT이 2개 (tuple 반환)
def bad_example(data: dict) -> tuple[bool, str]:  # 금지!
    ...

# 복합 결과가 필요하면 Pydantic 모델 1개로 묶는다
class GateResult(BaseModel):
    """게이트 평가 결과이다."""
    passed: bool
    reason: str
    score: float
```

**Optional 반환 정책**: `T | None`은 허용한다 (검증 실패 시 None 등).
단, `Union[A, B]` (A/B 모두 데이터 타입)는 **금지**한다.
결과가 복수 타입일 수 있으면 상위 Pydantic 모델 1개로 묶어야 한다.

### 1.2 단일 책임 원칙 (1모듈 = 1기능, 비협상)

하나의 모듈은 **정확히 하나의 기능**만 수행한다.
"이 모듈이 무엇을 하는가?"에 대한 답이 한 문장을 초과하면 분리 대상이다.

```
# 올바른 분리
F1.4 CrawlVerifier     -- "수집된 기사의 품질을 검증한다"
F1.5 ArticleDeduplicator -- "중복 기사를 제거한다"

# 금지: 하나의 모듈이 검증 + 중복제거 + 저장을 모두 수행
```

### 1.3 SecretVault 독점 원칙 (비협상)

**모든 민감 정보(API 키, 패스워드, 토큰)는 오직 C0.1 SecretVault를 통해서만 접근한다.**

```python
# 금지: 직접 환경변수 접근
import os
api_key = os.environ["ANTHROPIC_API_KEY"]     # 금지!
api_key = os.getenv("KIS_APP_KEY")            # 금지!

# 올바른 방법: SecretVault에서만 조회
from src.common.secret_vault import SecretVault
vault = SecretVault(".env")
api_key = vault.get_secret("ANTHROPIC_API_KEY")   # 유일한 접근 경로
```

SecretVault가 아닌 경로로 시크릿에 접근하는 코드는 모두 리팩토링 대상이다.
CI/CD에서 `os.environ`, `os.getenv` 사용을 lint로 차단한다 (common/secret_vault.py 내부 제외).

### 1.4 3계층 구조 (비협상)

```
Feature (도메인 경계)
    +-- Manager (오케스트레이션, 50줄 이하)
            +-- Atom (순수 함수, 30줄 이하)
```

| 계층 | 역할 | 규칙 |
|---|---|---|
| **Atom** | 가장 작은 단위 순수 함수 | 1함수 = 1동작. 외부 인프라 직접 import 금지. 파라미터로 DI. 30줄 이하. |
| **Manager** | 비즈니스 로직 순서 제어 | 직접 로직 수행 금지. Atom 호출 + 데이터 전달만. 50줄 이하. |
| **Feature** | 비즈니스 도메인 단위 | 폴더로 구분. Feature 간 직접 호출 금지. EventBus로 통신. |

### 1.5 파일 크기 제한 (비협상)

| 대상 | 최대 줄 수 |
|---|---|
| Atom 함수 | 30줄 |
| Manager 클래스 | 50줄 |
| 일반 파일 | 200줄 |
| Flutter 컴포넌트 | 150줄 |
| `main.py` (엔트리포인트) | 50줄 |

### 1.6 추가 설계 규칙

1. **단방향 의존성**: 하위 -> 상위 참조 금지. Atom은 Manager를, Manager는 Feature를 알지 못한다.
2. **DI 필수**: Atom은 DB, Redis, HTTP 클라이언트를 직접 import하지 않는다. Manager가 Common에서 꺼내 파라미터로 주입한다.
3. **Common 분리**: 인프라(DB, Redis, 로깅, 설정)는 반드시 `src/common/`에 구현한다.
4. **이벤트 디커플링**: Feature 간 직접 호출 금지. `C0.10 EventBus`를 통해서만 통신한다.
5. **Pydantic 계약**: 모든 IN/OUT은 Pydantic BaseModel로 정의한다. 딕셔너리 반환 금지.
6. **한국어 주석**: 모든 docstring과 주석은 한국어로 작성한다. "왜 이렇게 하는지" 중심.
7. **타입 힌트 필수**: Python 3.10+ 문법 (`str | None`, `list[str]`). `Any` 최소화.
8. **datetime 직렬화**: `json.dumps(data, default=str)` 사용. datetime 객체 직접 직렬화 금지.

---

## 2. 매매 시간 윈도우 (NEW -- v2.0 변경사항)

### 2.1 핵심 변경

| 항목 | 기존 (v1) | 변경 (v2) |
|---|---|---|
| 시작 방식 | LaunchAgent 23:00 자동 시작 | 대시보드 버튼 수동 시작 |
| 매매 윈도우 | 23:00~06:30 KST | **20:00~다음날 06:30 KST** |
| 종료 방식 | 06:30 자동 종료 | **07:00 자동 종료** (06:30~07:00 피드백) |

### 2.2 자정 넘김 처리 로직

매매 윈도우가 자정을 넘기므로 단순 시간 비교가 불가하다.
아래 함수로 통일하며, 이 함수는 C0.11 MarketClock에 배치한다.

```python
def is_trading_window(now_kst: datetime) -> bool:
    """현재 KST 시각이 매매 가능 윈도우(20:00~다음날 06:30) 안에 있는지 판별한다."""
    hour = now_kst.hour
    minute = now_kst.minute
    # 20:00~23:59 -- 당일 저녁
    if hour >= 20:
        return True
    # 00:00~05:59 -- 다음날 새벽
    if hour < 6:
        return True
    # 06:00~06:29 -- 다음날 새벽 (마감 직전)
    if hour == 6 and minute < 30:
        return True
    # 06:30~19:59 -- 매매 불가 시간
    return False
```

### 2.3 대시보드 버튼 플로우

```
[사용자] 대시보드 "매매 시작" 버튼 클릭
    |
    v
[Flutter] POST /api/trading/start (Bearer 인증)
    |
    v
[F7.4 TradingControlEndpoints]
    |
    v
[C0.11 MarketClock] is_trading_window(now_kst)
    |
    +-- True  --> F9.3 PreparationPhase 시작 --> 매매 루프 진입
    |
    +-- False --> 400 에러: "매매 가능 시간이 아닙니다 (20:00~06:30 KST)"
```

### 2.4 Phase 타임라인

```
20:00 KST           사용자 "매매 시작" 버튼 가능 시작
    |
    v
20:00~20:30         [Preparation Phase]
                    - KIS 토큰 갱신 (실전/모의)
                    - 뉴스 크롤링 (30개 소스 병렬)
                    - 뉴스 분류 (MLX local + Claude)
                    - 레짐 감지 (VIX 기반)
                    - 종합분석팀 5인 페르소나 분석
                    - 안전 체크 체인
    |
    v
20:30~06:00         [Active Trading Loop]
                    - 정규장 전: 연속 분석(30분 주기)
                    - 23:30 ET 정규장 개시: Power Open (90초)
                    - Mid Day (180초)
                    - Power Hour (120초)
                    - 장 마감 후: After Monitor (30~60초, sync_positions only)
    |
    v
06:00~06:30         [Final Monitoring]
                    - 포지션 동기화
                    - 오버나이트 판단
                    - 마지막 안전 체크
    |
    v
06:30~07:00         [EOD Sequence]
                    - 일일 피드백 보고서 생성
                    - 파라미터 자동 최적화 (strategy_params.json)
                    - RAG 지식 업데이트
                    - 텔레그램 일일 보고서 전송
                    - 리소스 정리
    |
    v
07:00               [Auto Shutdown]
                    - 모든 연결 해제 (DB, Redis, WebSocket, KIS)
                    - 프로세스 종료
```

### 2.5 ET (미국 동부시간) 세션 매핑

| 세션 | ET | KST (EDT 서머타임, +13h) | KST (EST 표준시, +14h) | 루프 주기 |
|---|---|---|---|---|
| Pre-Market | 04:00~09:30 | 17:00~22:30 | 18:00~23:30 | 분석 전용 |
| Power Open | 09:30~10:00 | 22:30~23:00 | 23:30~00:00 | 90초 |
| Mid Day | 10:00~15:30 | 23:00~04:30 | 00:00~05:30 | 180초 |
| Power Hour | 15:30~16:00 | 04:30~05:00 | 05:30~06:00 | 120초 |
| After Market | 16:00~20:00 | 05:00~09:00 | 06:00~10:00 | sync only |

---

## 3. C0 공통 모듈 (12개)

> 위치: `src/common/`
> 규칙: Feature 폴더 안에 절대 두지 않는다. Manager가 여기서 인스턴스를 꺼내 Atom에 파라미터로 주입(DI)한다.

---

### C0.1 SecretVault

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.1 |
| **파일** | `src/common/secret_vault.py` |
| **1-line** | .env 파일에서 시크릿을 로드하고 타입 안전한 접근 인터페이스를 제공한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| env_file_path | `str` | 프로젝트 루트 `.env` 파일 경로 |

**OUT**: `SecretProvider`

```python
class SecretProvider:
    """시크릿 제공자 -- 모든 민감 정보의 유일한 접근 경로이다."""
    def get_secret(self, key: str) -> str: ...
    def get_secret_or_none(self, key: str) -> str | None: ...
    def has_secret(self, key: str) -> bool: ...
```

**내부 기능**: `.env` 파싱, 필수 키 검증 (fail-fast), 로그 마스킹, 싱글톤 보장

**현재 파일 -> 새 위치**:
- `src/utils/config.py` (pydantic-settings 기반) -> `src/common/secret_vault.py`
- `.env` 직접 참조하는 모든 코드 -> SecretVault.get_secret() 호출로 교체

**관리 대상 시크릿 (34개)**:

| 카테고리 | 키 |
|---|---|
| KIS API | KIS_APP_KEY, KIS_APP_SECRET, KIS_VIRTUAL_ACCOUNT, KIS_REAL_ACCOUNT |
| KIS 실전 | KIS_REAL_APP_KEY, KIS_REAL_APP_SECRET |
| DB | DATABASE_URL, REDIS_URL |
| AI | ANTHROPIC_API_KEY, CLAUDE_MODE |
| Telegram | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID |
| 외부 API | FINNHUB_API_KEY, ALPHAVANTAGE_API_KEY, FRED_API_KEY |
| Reddit | REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET |
| 인증 | API_SECRET_KEY |
| 기타 | DART_API_KEY, SEC_USER_AGENT 등 |

---

### C0.2 DatabaseGateway

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.2 |
| **파일** | `src/common/database_gateway.py` |
| **1-line** | PostgreSQL 비동기 세션 팩토리를 생성하고 제공한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| database_url | `str` | C0.1.get_secret("DATABASE_URL") |

**OUT**: `SessionFactory`

```python
class SessionFactory:
    """DB 세션 팩토리 -- async with get_session() as session 패턴이다."""
    async def get_session(self) -> AsyncContextManager[AsyncSession]: ...
    async def close(self) -> None: ...
```

**내부 기능**: SQLAlchemy 2.0 async engine 생성, 세션 풀 관리, 연결 해제

**현재 파일 -> 새 위치**: `src/db/connection.py` -> `src/common/database_gateway.py`

---

### C0.3 CacheGateway

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.3 |
| **파일** | `src/common/cache_gateway.py` |
| **1-line** | Redis 비동기 클라이언트를 생성하고 CRUD/Pub-Sub 인터페이스를 제공한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| redis_url | `str` | C0.1.get_secret("REDIS_URL") |

**OUT**: `CacheClient`

```python
class CacheClient:
    """Redis 캐시 클라이언트이다."""
    async def read(self, key: str) -> str | None: ...
    async def write(self, key: str, value: str, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def publish(self, channel: str, message: str) -> None: ...
    async def subscribe(self, channel: str) -> AsyncIterator[str]: ...
    async def aclose(self) -> None: ...
```

**내부 기능**: redis-py 5.0+ async 클라이언트, 연결 풀, pub/sub

**현재 파일 -> 새 위치**: `src/db/connection.py` (get_redis 부분) -> `src/common/cache_gateway.py`

---

### C0.4 HttpClient

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.4 |
| **파일** | `src/common/http_client.py` |
| **1-line** | 외부 HTTP 통신용 공유 비동기 클라이언트를 제공한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| timeout_config | `TimeoutConfig` | 기본값 (total=30s, connect=10s) |

**OUT**: `AsyncHttpClient`

```python
class AsyncHttpClient:
    """공유 HTTP 클라이언트이다."""
    async def get(self, url: str, headers: dict | None = None) -> HttpResponse: ...
    async def post(self, url: str, json: dict | None = None, headers: dict | None = None) -> HttpResponse: ...
    async def close(self) -> None: ...
```

**내부 기능**: aiohttp.ClientSession 공유, 타임아웃, 재시도, 에러 래핑

**현재 파일 -> 새 위치**: 크롤러/분석 모듈 내 개별 세션 생성 -> `src/common/http_client.py`

---

### C0.5 AiGateway

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.5 |
| **파일** | `src/common/ai_gateway.py` |
| **1-line** | Claude API와 MLX 로컬 모델에 대한 통합 AI 호출 인터페이스를 제공한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| anthropic_api_key | `str` | C0.1.get_secret("ANTHROPIC_API_KEY") |
| claude_mode | `str` | C0.1.get_secret("CLAUDE_MODE") |
| http_client | `AsyncHttpClient` | C0.4 |

**OUT**: `AiClient`

```python
class AiClient:
    """AI 통합 클라이언트 -- Claude API + MLX 로컬 폴백이다."""
    async def send_text(self, prompt: str, model: str = "sonnet") -> AiResponse: ...
    async def send_tools(self, prompt: str, tools: list[dict]) -> AiResponse: ...
    async def local_classify(self, text: str, categories: list[str]) -> ClassifyResult: ...
```

**내부 기능**: Claude API 호출, MLX 로컬 추론, 폴백 라우팅 (Claude 실패 -> MLX)

**현재 파일 -> 새 위치**:
- `src/analysis/claude_client.py` (649줄) -> `src/common/ai_gateway.py`
- `src/fallback/fallback_router.py` -> `src/common/ai_gateway.py` (폴백 로직 통합)
- `src/fallback/local_model.py` -> `src/common/ai_gateway.py` (MLX 인터페이스 통합)
- `src/ai/mlx_classifier.py` -> `src/common/ai_gateway.py` (분류 기능 통합)

---

### C0.6 BrokerGateway

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.6 |
| **파일** | `src/common/broker_gateway.py` |
| **1-line** | KIS OpenAPI 인증 및 주문/시세/잔고 통신 인터페이스를 제공한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| kis_app_key | `str` | C0.1.get_secret("KIS_APP_KEY") |
| kis_app_secret | `str` | C0.1.get_secret("KIS_APP_SECRET") |
| kis_real_app_key | `str` | C0.1.get_secret("KIS_REAL_APP_KEY") |
| kis_real_app_secret | `str` | C0.1.get_secret("KIS_REAL_APP_SECRET") |
| kis_virtual_account | `str` | C0.1.get_secret("KIS_VIRTUAL_ACCOUNT") |
| kis_real_account | `str` | C0.1.get_secret("KIS_REAL_ACCOUNT") |
| http_client | `AsyncHttpClient` | C0.4 |

**OUT**: `BrokerClient`

```python
class BrokerClient:
    """KIS 브로커 통합 클라이언트이다."""
    async def get_price(self, ticker: str, exchange: str) -> PriceData: ...
    async def get_balance(self) -> BalanceData: ...
    async def place_order(self, order: OrderRequest) -> OrderResult: ...
    async def get_exchange_rate(self) -> float: ...
    async def get_daily_candles(self, ticker: str, days: int) -> list[OHLCV]: ...
```

**내부 기능**: 듀얼 인증 (real_auth + virtual_auth), 토큰 캐시 (1일 1회), 모의거래 시장가->지정가 자동 변환

**현재 파일 -> 새 위치**:
- `src/executor/kis_auth.py` -> `src/common/broker_gateway.py`
- `src/executor/kis_client.py` (1,261줄) -> `src/common/broker_gateway.py` (분할)

---

### C0.7 TelegramGateway

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.7 |
| **파일** | `src/common/telegram_gateway.py` |
| **1-line** | Telegram Bot API를 통해 텍스트 및 이미지 메시지를 발송한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| bot_token | `str` | C0.1.get_secret("TELEGRAM_BOT_TOKEN") |
| chat_id | `str` | C0.1.get_secret("TELEGRAM_CHAT_ID") |

**OUT**: `TelegramSender`

```python
class TelegramSender:
    """텔레그램 메시지 발송 클라이언트이다."""
    async def send_text(self, message: str, parse_mode: str = "HTML") -> SendResult: ...
    async def send_photo(self, photo_path: str, caption: str = "") -> SendResult: ...
```

**내부 기능**: python-telegram-bot SDK 래핑, 메시지 길이 분할, 에러 핸들링

**현재 파일 -> 새 위치**: `src/monitoring/telegram_notifier.py` (발송 로직) -> `src/common/telegram_gateway.py`

---

### C0.8 Logger

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.8 |
| **파일** | `src/common/logger.py` |
| **1-line** | 모듈명 기반 구조화 로거를 생성한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| module_name | `str` | 호출 모듈의 `__name__` |

**OUT**: `Logger`

```python
def get_logger(module_name: str) -> Logger:
    """구조화 로거를 생성한다 -- 시크릿 값은 자동 마스킹된다."""
    ...
```

**현재 파일 -> 새 위치**: `src/utils/logger.py` -> `src/common/logger.py`

---

### C0.9 ErrorHandler

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.9 |
| **파일** | `src/common/error_handler.py` |
| **1-line** | 예외를 표준 ErrorResponse로 변환하고 글로벌 에러 핸들링을 제공한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| exception | `Exception` | 발생한 예외 객체 |

**OUT**: `ErrorResponse`

```python
class ErrorResponse(BaseModel):
    """표준 에러 응답이다."""
    error_code: str
    message: str
    detail: str | None = None
    timestamp: datetime
```

**현재 파일 -> 새 위치**: 각 모듈 내 분산된 에러 처리 -> `src/common/error_handler.py`

---

### C0.10 EventBus

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.10 |
| **파일** | `src/common/event_bus.py` |
| **1-line** | Feature 간 비동기 이벤트 발행/구독을 관리한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| event_type | `str` | 이벤트 유형 식별자 |
| payload | `BaseModel` | 이벤트 페이로드 |

**OUT**: `EventDeliveryResult`

```python
class EventDeliveryResult(BaseModel):
    """이벤트 배달 결과이다."""
    event_type: str
    delivered_to: int
    failed: int
```

**이벤트 목록**:

| 이벤트 | 발행자 | 구독자 |
|---|---|---|
| `ArticleCollected` | F1.7 | F2.1 |
| `TradingDecision` | F2.4 | F5.3 |
| `PositionChanged` | F5.4 | F7.18 |
| `EmergencyLiquidation` | F6.3 | F5.3 |
| `CrashDetected` | F6.13 | F6.3 |
| `EODStarted` | F9.7 | F8.9 |
| `BeastEntry` | F4.3 | F6.12 |
| `PyramidTriggered` | F4.4 | F6.7, F7.19 |
| `TiltDetected` | F6.8 | F6.5, F7.19 |
| `InfraHealthChanged` | F9.3 | F7.15, F7.19 |
| `WeeklyReportGenerated` | F9.9 | F7.19 |

**현재 파일 -> 새 위치**: 신규 생성 `src/common/event_bus.py`

---

### C0.11 MarketClock

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.11 |
| **파일** | `src/common/market_clock.py` |
| **1-line** | 현재 KST/ET 시각, 매매 윈도우 판별, 시장 세션 유형을 제공한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| system_clock | `Callable[[], datetime]` | `datetime.now(tz=ZoneInfo("Asia/Seoul"))` |

**OUT**: `TimeInfo`

```python
class TimeInfo(BaseModel):
    """시간 정보 종합 객체이다."""
    now_kst: datetime
    now_et: datetime
    is_trading_window: bool          # 20:00~06:30 KST
    session_type: Literal[
        "preparation",       # 20:00~20:30
        "pre_market",        # 20:30~23:30 (분석 전용)
        "power_open",        # 23:30~00:00 (90초 루프)
        "mid_day",           # 00:00~05:30 (180초 루프)
        "power_hour",        # 05:30~06:00 (120초 루프)
        "final_monitoring",  # 06:00~06:30
        "eod_sequence",      # 06:30~07:00
        "closed"             # 07:00~20:00
    ]
    is_regular_session: bool         # ET 09:30~16:00
    is_danger_zone: bool             # ET 09:30~10:00 또는 15:30~16:00
    loop_interval_seconds: int       # 현재 세션의 루프 주기
```

**핵심 함수**:

```python
def is_trading_window(now_kst: datetime) -> bool:
    """매매 가능 윈도우(20:00~다음날 06:30 KST)를 판별한다."""
    hour = now_kst.hour
    minute = now_kst.minute
    if hour >= 20:
        return True
    if hour < 6:
        return True
    if hour == 6 and minute < 30:
        return True
    return False
```

**현재 파일 -> 새 위치**:
- `src/utils/market_hours.py` (692줄) -> `src/common/market_clock.py`
- `src/safety/account_safety.py` (auto_stop_window) -> `src/common/market_clock.py`
- `src/monitoring/calendar_helpers.py` -> `src/common/market_clock.py`

---

### C0.12 TickerRegistry

| 항목 | 내용 |
|---|---|
| **모듈 ID** | C0.12 |
| **파일** | `src/common/ticker_registry.py` |
| **1-line** | ETF 유니버스, 인버스 페어, 거래소 코드, 섹터 매핑 정보를 제공한다 |

**IN**:

| 입력 | 타입 | 출처 |
|---|---|---|
| db_session | `SessionFactory` | C0.2 |

**OUT**: `TickerInfo`

```python
class TickerInfo:
    """티커 정보 레지스트리이다."""
    def get_universe(self) -> list[TickerMeta]: ...
    def get_pair(self, ticker: str) -> str | None: ...          # 인버스 페어
    def get_exchange_code(self, ticker: str) -> str: ...         # NAS/AMS/NYS
    def get_sector(self, ticker: str) -> str: ...
    def is_inverse(self, ticker: str) -> bool: ...
    def is_enabled(self, ticker: str) -> bool: ...
```

**현재 파일 -> 새 위치**:
- `src/strategy/etf_universe.py` (888줄) -> `src/common/ticker_registry.py`
- `src/utils/ticker_mapping.py` -> `src/common/ticker_registry.py`
- `src/executor/universe_manager.py` -> `src/common/ticker_registry.py` (읽기 부분)

---

## 4. F1~F10 Feature 모듈

---

### F1. 데이터 수집 (Data Collection)

> 위치: `src/f1_collection/`
> 사용 Common: C0.1, C0.2, C0.3, C0.4, C0.8, C0.9

#### F1.1 CrawlScheduler

| 항목 | 내용 |
|---|---|
| **1-line** | KST 시각 기준으로 야간/주간 모드를 판별하고 소스별 크롤링 주기를 계산한다 |
| **IN** | time_info: `TimeInfo` (C0.11) |
| **OUT** | `CrawlSchedule` (session_type, active_sources, intervals) |
| **Atom** | is_night_mode(), get_interval_for_source(), filter_active_sources() |
| **현재 파일** | `src/crawler/crawl_scheduler.py` + `src/crawler/sources_config.py` |

#### F1.2 CrawlerBase

| 항목 | 내용 |
|---|---|
| **1-line** | 모든 크롤러의 공통 인터페이스와 타임아웃/에러 격리를 정의한다 |
| **IN** | source_config: `SourceConfig`, http_client: `AsyncHttpClient` (C0.4) |
| **OUT** | `list[RawArticle]` |
| **현재 파일** | `src/crawler/base_crawler.py` |

#### F1.3 Crawlers (30개 소스)

| 항목 | 내용 |
|---|---|
| **1-line** | 개별 뉴스/데이터 소스에서 원시 기사를 수집한다 |
| **IN** | source_config: `SourceConfig`, since: `datetime | None`, http_client: `AsyncHttpClient` |
| **OUT** | `list[RawArticle]` |

**30개 크롤러 분류**:

| 유형 | 소스 | 파일 |
|---|---|---|
| RSS (15) | reuters, bloomberg_rss, yahoo_finance, cnbc, marketwatch, wsj_rss, ft, fed_announcements, ecb_press, bbc_business, nikkei_asia, scmp, yonhap_en, hankyung, mk | `rss_crawler.py` |
| API (7) | finnhub, alphavantage, fred, fear_greed, finviz, stocktwits, dart | `finnhub_crawler.py`, `alphavantage_crawler.py`, `fred_crawler.py`, `fear_greed_crawler.py`, `finviz_crawler.py`, `stocktwits_crawler.py`, `dart_crawler.py` |
| 스크래핑 (4) | naver, stocknow, investing, sec_edgar | `naver_crawler.py`, `stocknow_crawler.py`, `investing_crawler.py`, `sec_edgar_crawler.py` |
| 소셜 (2) | reddit (3 subreddits), stocktwits | `reddit_crawler.py`, `stocktwits_crawler.py` |
| 예측시장 (2) | kalshi, polymarket | `kalshi_crawler.py`, `polymarket_crawler.py` |

#### F1.4 CrawlVerifier

| 항목 | 내용 |
|---|---|
| **1-line** | 수집된 원시 기사의 필드 완전성, 언어, 나이, 품질을 검증한다 |
| **IN** | raw_article: `RawArticle` |
| **OUT** | `VerifiedArticle | None` (검증 실패 시 None) |
| **현재 파일** | `src/crawler/crawl_verifier.py` |

#### F1.5 ArticleDeduplicator

| 항목 | 내용 |
|---|---|
| **1-line** | SHA-256 해시 기반으로 Redis에서 기사 중복 여부를 판별한다 |
| **IN** | verified_article: `VerifiedArticle`, cache: `CacheClient` (C0.3) |
| **OUT** | `DeduplicationResult` (is_new: bool) |
| **현재 파일** | `src/crawler/dedup.py` |

#### F1.6 ArticlePersister

| 항목 | 내용 |
|---|---|
| **1-line** | 검증된 기사를 PostgreSQL에 upsert 저장한다 |
| **IN** | verified_article: `VerifiedArticle`, session: `AsyncSession` (C0.2) |
| **OUT** | `PersistResult` (article_id, is_new) |
| **현재 파일** | `src/crawler/crawl_engine.py` (저장 로직 부분) |

#### F1.7 CrawlEngine

| 항목 | 내용 |
|---|---|
| **1-line** | 전체 크롤링 파이프라인을 오케스트레이션하고 결과를 집계한다 |
| **IN** | crawl_schedule: `CrawlSchedule`, crawlers: `list[CrawlerBase]`, verifier: `CrawlVerifier`, dedup: `ArticleDeduplicator`, persister: `ArticlePersister` |
| **OUT** | `CrawlResult` (total, new_count, failed_sources, duration) |
| **이벤트 발행** | `ArticleCollected` -> EventBus -> F2.1 |
| **현재 파일** | `src/crawler/crawl_engine.py` (1,099줄) |

#### F1.8 AiContextBuilder

| 항목 | 내용 |
|---|---|
| **1-line** | 수집된 기사를 AI 분석용 컨텍스트 문자열로 조합한다 |
| **IN** | articles: `list[VerifiedArticle]`, max_tokens: `int` |
| **OUT** | `AiContext` (context_text, article_count, truncated) |
| **현재 파일** | `src/crawler/ai_context_builder.py` |

---

### F2. AI 분석 (AI Analysis)

> 위치: `src/f2_analysis/`
> 사용 Common: C0.2, C0.3, C0.5, C0.8, C0.12

#### F2.1 NewsClassifier

| 항목 | 내용 |
|---|---|
| **1-line** | 뉴스를 영향도/방향/카테고리별로 분류한다 (MLX 로컬 + Claude 폴백) |
| **IN** | articles: `list[VerifiedArticle]`, ai_client: `AiClient` (C0.5) |
| **OUT** | `list[ClassifiedNews]` |
| **현재 파일** | `src/analysis/classifier.py` (623줄) |

#### F2.2 RegimeDetector

| 항목 | 내용 |
|---|---|
| **1-line** | VIX 값으로 시장 레짐 (strong_bull/mild_bull/sideways/mild_bear/crash)을 판별한다 |
| **IN** | vix_value: `float` |
| **OUT** | `MarketRegime` (regime_type, vix, params) |
| **Atom** | classify_regime(vix) -> str, get_regime_params(regime_type) -> `RegimeParams` |
| **현재 파일** | `src/analysis/regime_detector.py` |

```python
class RegimeParams(BaseModel):
    """레짐별 전략 파라미터이다."""
    take_profit: float          # 익절 목표 (0이면 트레일링만)
    trailing_stop: float        # 트레일링 스탑 퍼센트
    max_hold_days: int          # 최대 보유일 (0이면 EOD 청산)
    position_multiplier: float  # 포지션 배수 (0.5x ~ 1.5x)
    allow_bull_entry: bool      # Bull ETF 진입 허용 여부
    allow_bear_entry: bool      # Bear/Inverse ETF 진입 허용 여부
    prefer_inverse: bool        # 인버스 우선 여부 (mild_bear/crash)
```

#### F2.3 ComprehensiveTeam

| 항목 | 내용 |
|---|---|
| **1-line** | 5개 AI 에이전트 페르소나를 순차 실행하여 종합 분석 보고서를 생성한다 |
| **IN** | analysis_context: `AnalysisContext` (뉴스, 지표, 레짐, 포지션), ai_client: `AiClient` (C0.5) |
| **OUT** | `ComprehensiveReport` (signals, confidence, recommendations) |

**5개 에이전트 페르소나**:

| 페르소나 | 역할 | 프롬프트 키 |
|---|---|---|
| MASTER_ANALYST | 종합 분석 총괄, 최종 판단 | `MASTER_ANALYST` |
| NEWS_ANALYST | 뉴스 영향 분석, 감정 판단 | `NEWS_ANALYST` |
| RISK_MANAGER | 리스크 평가, 포지션 사이징 | `RISK_MANAGER` |
| MACRO_STRATEGIST | 거시 경제 분석, 레짐 판단 | `MACRO_STRATEGIST` |
| SHORT_TERM_TRADER | 단기 매매 타이밍, 기술적 분석 | `SHORT_TERM_TRADER` |

**현재 파일**: `src/analysis/comprehensive_team.py` + `src/analysis/prompts.py` (1,896줄)

#### F2.4 DecisionMaker

| 항목 | 내용 |
|---|---|
| **1-line** | 종합 분석 결과와 포트폴리오 상태를 기반으로 매매 판단 (진입/청산/홀드)을 생성한다 |
| **IN** | comprehensive_report: `ComprehensiveReport`, portfolio_state: `PortfolioState` |
| **OUT** | `TradingDecision` (action, ticker, confidence, size_pct, reason) |
| **이벤트 발행** | `TradingDecision` -> EventBus -> F5.3 |
| **현재 파일** | `src/analysis/decision_maker.py` |

#### F2.5 OvernightJudge

| 항목 | 내용 |
|---|---|
| **1-line** | 장 마감 후 보유 포지션의 오버나이트 유지/청산 여부를 판단한다 |
| **IN** | positions: `list[Position]`, market_context: `MarketContext`, regime: `MarketRegime` |
| **OUT** | `list[OvernightDecision]` (ticker, action, reason) |
| **현재 파일** | `src/analysis/overnight_judge.py` |

#### F2.6 ContinuousAnalysis

| 항목 | 내용 |
|---|---|
| **1-line** | 30분 주기로 Opus 모델을 호출하여 실시간 이슈를 분석한다 |
| **IN** | market_session: `TimeInfo` (C0.11), ai_client: `AiClient` (C0.5), cache: `CacheClient` (C0.3) |
| **OUT** | `AnalysisSummary` (issues, signals, timestamp) |
| **현재 파일** | `src/orchestration/continuous_analysis.py` |

#### F2.7 PromptRegistry

| 항목 | 내용 |
|---|---|
| **1-line** | 5개 AI 에이전트 시스템 프롬프트 템플릿을 관리한다 |
| **IN** | prompt_key: `str` |
| **OUT** | `str` (프롬프트 텍스트) |
| **현재 파일** | `src/analysis/prompts.py` (1,896줄 -> 5개 파일로 분할) |

#### F2.8 ~~FallbackRouter~~ (C0.5 AiGateway로 통합됨 -- 참조용)

> **주의**: 이 모듈은 독립 모듈이 아니다. C0.5 AiGateway에 폴백 라우팅 로직이 통합되었다.
> 기존 `src/fallback/fallback_router.py` + `src/fallback/local_model.py`의 기능은
> C0.5 AiGateway의 `send_text()` / `local_classify()` 내부에서 자동 처리된다.
> 이 섹션은 마이그레이션 추적용으로만 남긴다.

| 항목 | 내용 |
|---|---|
| **상태** | **DEPRECATED -- C0.5 AiGateway로 통합 완료** |
| **기존 1-line** | Claude API 실패 시 MLX 로컬 모델로 폴백 라우팅한다 |
| **통합 위치** | C0.5 AiGateway (`src/common/ai_gateway.py`) |
| **현재 파일** | `src/fallback/fallback_router.py` + `src/fallback/local_model.py` → 삭제 대상 |

#### F2.9 KeyNewsFilter

| 항목 | 내용 |
|---|---|
| **1-line** | 영향도 임계값 이상의 핵심 뉴스만 필터링한다 |
| **IN** | classified_news: `list[ClassifiedNews]`, threshold: `float` |
| **OUT** | `list[KeyNews]` |
| **현재 파일** | `src/analysis/key_news_filter.py` (520줄) |

#### F2.10 EODFeedbackReport

| 항목 | 내용 |
|---|---|
| **1-line** | 일일 매매 결과를 종합하여 피드백 보고서를 생성한다 |
| **IN** | daily_trades: `list[TradeRecord]`, pnl_summary: `PnlSummary`, ai_client: `AiClient` |
| **OUT** | `FeedbackReport` (summary, lessons, suggestions) |
| **현재 파일** | `src/analysis/eod_feedback_report.py` (신규) |

#### F2.11 NewsThemeTracker

| 항목 | 내용 |
|---|---|
| **1-line** | 반복 출현하는 뉴스 테마를 감지하고 추적한다 |
| **IN** | articles: `list[ClassifiedNews]`, cache: `CacheClient` (C0.3) |
| **OUT** | `list[ThemeSummary]` (theme, frequency, trend) |
| **현재 파일** | `src/analysis/news_theme_tracker.py` (신규) |

#### F2.12 NewsTranslator

| 항목 | 내용 |
|---|---|
| **1-line** | 영어 뉴스를 한국어로 번역한다 |
| **IN** | article: `ClassifiedNews`, ai_client: `AiClient` (C0.5) |
| **OUT** | `TranslatedNews` |
| **현재 파일** | `src/analysis/news_translator.py` |

#### F2.13 TickerProfiler

| 항목 | 내용 |
|---|---|
| **1-line** | 특정 티커의 종합 프로파일 (뉴스, 지표, 분석 결합)을 생성한다 |
| **IN** | ticker: `str`, news: `list[ClassifiedNews]`, indicators: `IndicatorBundle` |
| **OUT** | `TickerProfile` |
| **현재 파일** | `src/analysis/ticker_profiler.py` |

---

### F3. 지표 (Indicators)

> 위치: `src/f3_indicators/`
> 사용 Common: C0.3, C0.4, C0.6, C0.8

#### F3.1 PriceDataFetcher

| 항목 | 내용 |
|---|---|
| **1-line** | KIS API로 일봉/분봉 가격 데이터를 조회한다 |
| **IN** | ticker: `str`, broker: `BrokerClient` (C0.6), days: `int` |
| **OUT** | `list[OHLCV]` |
| **현재 파일** | `src/indicators/data_fetcher.py` |

#### F3.2 TechnicalCalculator

| 항목 | 내용 |
|---|---|
| **1-line** | RSI, MACD, 볼린저 밴드, ATR 등 기술적 지표를 계산한다 |
| **IN** | candles: `list[OHLCV]` |
| **OUT** | `TechnicalIndicators` (rsi, macd, bb, atr, ema, sma) |
| **Atom** | calc_rsi(), calc_macd(), calc_bollinger(), calc_atr() |
| **현재 파일** | `src/indicators/calculator.py` |

```python
class TechnicalIndicators(BaseModel):
    """기술적 지표 종합 결과이다."""
    rsi: float
    macd: float
    macd_signal: float
    macd_histogram: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    atr: float
    ema_20: float
    ema_50: float
    sma_200: float
```

#### F3.3 HistoryAnalyzer

| 항목 | 내용 |
|---|---|
| **1-line** | 과거 가격 패턴을 분석한다 |
| **IN** | candles: `list[OHLCV]` |
| **OUT** | `HistoryPattern` (patterns, support_levels, resistance_levels) |
| **현재 파일** | `src/indicators/history_analyzer.py` |

#### F3.4 IndicatorAggregator

| 항목 | 내용 |
|---|---|
| **1-line** | 여러 기술적 지표를 가중합으로 종합 점수화한다 |
| **IN** | technical: `TechnicalIndicators`, weights: `WeightConfig` |
| **OUT** | `AggregatedScore` (total_score, components) |
| **현재 파일** | `src/indicators/aggregator.py` + `src/indicators/weights.py` |

#### F3.5 IntradayFetcher

| 항목 | 내용 |
|---|---|
| **1-line** | Finnhub/AlphaVantage에서 5분봉 장중 데이터를 조회한다 |
| **IN** | ticker: `str`, http_client: `AsyncHttpClient` (C0.4), api_keys: (C0.1) |
| **OUT** | `list[Candle5m]` |
| **현재 파일** | `src/indicators/intraday_fetcher.py` |

#### F3.6 IntradayCalculator

| 항목 | 내용 |
|---|---|
| **1-line** | VWAP, 장중 RSI, 볼린저 밴드를 계산한다 |
| **IN** | candles_5m: `list[Candle5m]` |
| **OUT** | `IntradayIndicators` (vwap, intraday_rsi, intraday_bb) |
| **현재 파일** | `src/indicators/intraday_calculator.py` + `src/indicators/intraday_macd.py` |

#### F3.7 CrossAssetMomentum

| 항목 | 내용 |
|---|---|
| **1-line** | 리더 맵(17쌍)으로 ETF와 기초 주식 간 모멘텀 정렬/다이버전스를 분석한다 |
| **IN** | ticker: `str`, cache: `CacheClient` (C0.3) |
| **OUT** | `MomentumScore` (alignment, divergence, leader_scores) |

**리더 맵**: SOXL->[NVDA,AMD,TSM], QLD->[AAPL,MSFT,NVDA,GOOG], 총 17쌍

```python
class MomentumScore(BaseModel):
    """크로스 에셋 모멘텀 점수이다."""
    alignment: float            # 리더-ETF 정렬도 (-1.0 ~ +1.0)
    divergence: float           # 다이버전스 크기
    leader_scores: dict[str, float]  # 리더 종목별 OBI 점수
    has_bullish_divergence: bool
    has_bearish_divergence: bool
```

**Atom**: leader_map.py, leader_aggregator.py, divergence_detector.py, momentum_scorer.py

**현재 파일**: `src/indicators/cross_asset/` (5개 파일)

#### F3.8 VolumeProfile

| 항목 | 내용 |
|---|---|
| **1-line** | POC(Point of Control)와 Value Area(70% 거래량)를 계산하여 지지/저항 수준을 도출한다 |
| **IN** | candles: `list[OHLCV]`, cache: `CacheClient` (C0.3) |
| **OUT** | `VolumeProfileResult` (poc_price, value_area_high, value_area_low, signals) |
| **Atom** | accumulator.py, calculator.py, signal_generator.py, redis_feeder.py |
| **현재 파일** | `src/indicators/volume_profile/` (6개 파일)

```python
class VolumeProfileResult(BaseModel):
    """볼륨 프로파일 분석 결과이다."""
    poc_price: float            # Point of Control 가격
    value_area_high: float      # Value Area 상단 (70% 거래량)
    value_area_low: float       # Value Area 하단
    is_above_poc: bool          # 현재 가격이 POC 위인지
    support_level: float | None
    resistance_level: float | None
    signals: list[str]          # 생성된 신호 목록
``` |

#### F3.9 WhaleTracker

| 항목 | 내용 |
|---|---|
| **1-line** | 블록 거래($200k+)와 아이스버그(5+ 체결/1s)를 감지하여 고래 점수를 산출한다 |
| **IN** | order_flow: `OrderFlowData`, cache: `CacheClient` (C0.3) |
| **OUT** | `WhaleSignal` (block_score, iceberg_score, direction, total_score) |
| **Atom** | block_detector.py, iceberg_detector.py, whale_scorer.py |
| **현재 파일** | `src/indicators/whale/` (4개 파일)

```python
class WhaleSignal(BaseModel):
    """고래 활동 감지 결과이다."""
    block_score: float          # 블록 거래 점수 (0.0 ~ 1.0)
    iceberg_score: float        # 아이스버그 주문 점수 (0.0 ~ 1.0)
    direction: str              # 고래 방향 (bullish/bearish/neutral)
    total_score: float          # 종합 고래 점수
    block_count: int            # 감지된 블록 거래 수
    iceberg_count: int          # 감지된 아이스버그 수
``` |

#### F3.10 MACDDivergence

| 항목 | 내용 |
|---|---|
| **1-line** | MACD 다이버전스(가격-지표 괴리)를 분석한다 |
| **IN** | candles: `list[OHLCV]` |
| **OUT** | `DivergenceSignal` (type, strength, confidence) |
| **현재 파일** | `src/indicators/macd_divergence.py` (713줄) |

#### F3.11 ContangoDetector

| 항목 | 내용 |
|---|---|
| **1-line** | VIX 기간구조 프록시와 레버리지 드래그를 측정한다 |
| **IN** | cache: `CacheClient` (C0.3), broker: `BrokerClient` (C0.6) |
| **OUT** | `ContangoState` (contango_ratio, drag_estimate, signal) |
| **현재 파일** | `src/indicators/contango_detector.py` |

#### F3.12 NAVPremiumTracker

| 항목 | 내용 |
|---|---|
| **1-line** | 레버리지 ETF 10종의 NAV 프리미엄/디스카운트를 추적한다 |
| **IN** | ticker: `str`, broker: `BrokerClient` (C0.6) |
| **OUT** | `NAVPremiumState` (premium_pct, multiplier_adjustment) |

**추적 대상 ETF**: SOXL, SOXS, QLD, QID, SSO, SDS, NVDL, NVDS, UWM, DDM

**현재 파일**: `src/indicators/nav_premium.py`

#### F3.13 OrderFlowAggregator

| 항목 | 내용 |
|---|---|
| **1-line** | WebSocket 실시간 체결 데이터를 집계하여 OBI/CVD/VPIN 등 주문 흐름 지표를 제공한다 |
| **IN** | cache: `CacheClient` (C0.3) |
| **OUT** | `OrderFlowSnapshot` (obi, cvd, vpin, execution_strength) |
| **현재 파일** | `src/indicators/order_flow_aggregator.py` |

#### F3.14 LeverageDecay

| 항목 | 내용 |
|---|---|
| **1-line** | 변동성 드래그로 인한 레버리지 디케이를 정량화한다 |
| **IN** | candles: `list[OHLCV]`, leverage: `float` |
| **OUT** | `DecayScore` (decay_pct, force_exit: bool) |
| **현재 파일** | `src/indicators/leverage_decay.py` |

---

### F4. 전략 (Strategy)

> 위치: `src/f4_strategy/`
> 사용 Common: C0.3, C0.8, C0.11, C0.12

#### F4.1 EntryStrategy

| 항목 | 내용 |
|---|---|
| **1-line** | 7개 진입 게이트를 순차 평가하여 매수 진입 여부를 결정한다 |
| **IN** | ticker: `str`, analysis_result: `AnalysisResult`, indicators: `IndicatorBundle`, regime: `MarketRegime`, positions: `list[Position]`, strategy_params: `StrategyParams` |
| **OUT** | `EntryDecision` (should_enter, confidence, position_size_pct, blocked_by) |

```python
class EntryDecision(BaseModel):
    """진입 판단 결과이다."""
    should_enter: bool          # 진입 여부
    confidence: float           # 확신도 (0.0 ~ 1.0)
    position_size_pct: float    # 포지션 크기 (총 자산 대비 %)
    blocked_by: str | None      # 차단 게이트 이름 (None이면 통과)
    gate_results: dict[str, bool]  # 각 게이트별 통과 여부
    ticker: str
    direction: str              # bull / bear
```

**7개 진입 게이트**:

| Gate | 이름 | 조건 | Atom |
|---|---|---|---|
| 1 | OBI | obi_score > threshold | check_obi_gate() |
| 2 | CrossAsset | 리더 ETF 모멘텀 정렬 | check_cross_asset_gate() |
| 3 | Whale | 대형 주문 흐름 일치 | check_whale_gate() |
| 4 | MicroRegime | trending/mild_bull 이상 | check_regime_gate() |
| 5 | ML | ml_prediction > threshold | check_ml_gate() |
| 6 | Friction | friction 허들 이상 기대 수익 | check_friction_gate() |
| 7 | RAG | 과거 실패 패턴 미매칭 | check_rag_gate() |

**현재 파일**: `src/strategy/entry_strategy.py` (1,450줄)

#### F4.2 ExitStrategy

| 항목 | 내용 |
|---|---|
| **1-line** | 우선순위 체인 기반으로 포지션 청산 여부와 방식을 결정한다 |
| **IN** | position: `Position`, indicators: `IndicatorBundle`, regime: `MarketRegime`, strategy_params: `StrategyParams`, market_data: `MarketData` |
| **OUT** | `ExitDecision` (should_exit, exit_type, exit_pct, priority, reason) |

```python
class ExitDecision(BaseModel):
    """청산 판단 결과이다."""
    should_exit: bool           # 청산 여부
    exit_type: str              # 청산 유형 (emergency/hard_stop/beast_exit/take_profit/...)
    exit_pct: float             # 청산 비율 (0.0 ~ 1.0, 분할 매도 시 < 1.0)
    priority: float             # 우선순위 (0=최고, 9=최저)
    reason: str                 # 청산 사유 설명
    ticker: str
    estimated_pnl_pct: float    # 예상 손익 퍼센트
```

**10개 청산 유형 (우선순위순)**:

| 우선순위 | 유형 | 조건 |
|---|---|---|
| 0 | emergency | EmergencyProtocol 트리거 |
| 1 | hard_stop | 손실 임계값 돌파 |
| 2 | beast_exit | Beast Mode ego 청산 조건 |
| 3 | take_profit | 익절 목표가 도달 (regime=strong_bull이면 skip, 트레일링만) |
| 3.5 | scaled_exit | 분할 매도 (30%/30%/40% at 70%/100%/150% target) |
| 4.5 | news_fade | 뉴스 스파이크 역방향 페이드 |
| 4.7 | stat_arb | 페어 Z-Score 정상화 |
| 5 | trailing_stop | 트레일링 손절가 하회 |
| 6 | time_stop | 최대 보유 시간 초과 |
| 9 | eod | 장 마감 전 강제 청산 |

**현재 파일**: `src/strategy/exit_strategy.py` (1,517줄)

#### F4.3 BeastMode

| 항목 | 내용 |
|---|---|
| **1-line** | A+ 셋업 조건 충족 시 고확신 공격적 매매 모드를 활성화하고 에고 유형별 포지션/청산 전략을 결정한다 |
| **IN** | confidence: `float`, obi_score: `float`, leader_momentum: `float`, volume_ratio: `float`, whale_alignment: `bool`, regime: `MarketRegime`, vix: `float`, strategy_params: `StrategyParams`, daily_beast_count: `int`, last_failure_time: `datetime | None` |
| **OUT** | `BeastDecision` (activated, conviction_multiplier, ego_type, position_size_pct, rejection_reason) |

```python
class BeastDecision(BaseModel):
    """Beast Mode 활성화 판단 결과이다."""
    activated: bool             # 활성화 여부
    conviction_multiplier: float  # 컨빅션 배수 (2.5x ~ 3.0x)
    ego_type: str | None        # 에고 유형 (sniper/butcher/surfer/None)
    position_size_pct: float    # 포지션 크기 (Beast 배수 적용 후)
    rejection_reason: str | None  # 거부 사유 (None이면 활성화)
    composite_score: float      # 가중 합성 점수
```

**A+ 셋업 조건 (AND 로직)**:
- confidence > 0.9
- obi_score > +0.4
- leader_momentum > 0.6
- volume_ratio >= 2.0
- whale_alignment == True

**3개 에고**:
- Cold-Blooded Sniper: A+ 셋업만 진입
- Merciless Butcher: 120초 타임스탑
- Greedy Surfer: -0.5% 트레일링

**가중 합성**: confidence(30%) + OBI(25%) + leader(20%) + volume(15%) + whale(10%)
**컨빅션 배수**: 2.5x~3.0x (선형 보간)
**가드**: strong_bull/mild_bull만, VIX<25, 최대 5회/일, 실패 후 5분 쿨다운

**현재 파일**: `src/strategy/beast_mode/` (6개 파일: config, models, detector, conviction_sizer, beast_exit, __init__)

#### F4.4 Pyramiding

| 항목 | 내용 |
|---|---|
| **1-line** | 기존 수익 포지션에 3단계 추가 진입 (피라미딩)을 수행한다 |
| **IN** | position: `Position`, market_state: `MarketState`, strategy_params: `StrategyParams` |
| **OUT** | `PyramidDecision` (should_add, level, add_size_pct, ratchet_stop) |

**3단계**: +1% -> 50%, +2% -> 30%, +3% -> 20%
**8개 안전 가드**: 최대 레벨, 최소 수익, 리스크 버짓, 집중도 등

**현재 파일**: `src/strategy/pyramiding.py` (632줄)

#### F4.5 StatArb

| 항목 | 내용 |
|---|---|
| **1-line** | 5개 페어의 Z-Score 기반 통계적 차익거래 신호를 생성한다 |
| **IN** | pair_prices: `PairPrices`, cache: `CacheClient` (C0.3) |
| **OUT** | `StatArbSignal` (pair, z_score, direction, signal_type) |

**5개 페어**: QQQ/QLD, SPY/SSO, IWM/UWM, DIA/DDM, SOXX/SOXL
**신호**: Z > 2 -> short, Z < -2 -> long

**Atom**: spread_calculator.py, signal_generator.py, pair_monitor.py
**현재 파일**: `src/strategy/stat_arb/` (6개 파일)

#### F4.6 MicroRegime

| 항목 | 내용 |
|---|---|
| **1-line** | 5분봉 기반 미시 레짐 (trending/mean_reverting/volatile/quiet)을 분류한다 |
| **IN** | candles_5m: `list[Candle5m]` |
| **OUT** | `MicroRegimeResult` (regime, score, weights) |

**가중치**: 0.35*ER + 0.30*DS + 0.20*AC + 0.15*vol
**4가지 레짐**: trending, mean_reverting, volatile, quiet

**Atom**: volatility_analyzer.py, trend_detector.py (ER+ADX), regime_classifier.py
**현재 파일**: `src/strategy/micro_regime/` (5개 파일)

#### F4.7 NewsFading

| 항목 | 내용 |
|---|---|
| **1-line** | 뉴스 스파이크(>1%/60s) 발생 후 역방향 페이딩 신호를 생성한다 |
| **IN** | price_spike: `PriceSpike`, news_context: `NewsContext` |
| **OUT** | `FadeSignal` (should_fade, direction, decay_estimate, entry_price) |

**Atom**: spike_detector.py, decay_analyzer.py, fade_signal_generator.py
**현재 파일**: `src/strategy/news_fading/` (5개 파일)

#### F4.8 WickCatcher

| 항목 | 내용 |
|---|---|
| **1-line** | 급격한 하방 윅에서 VPIN/CVD 조건 충족 시 역방향 진입한다 |
| **IN** | intraday_state: `IntradayState` (vpin, cvd, price) |
| **OUT** | `WickDecision` (should_catch, entry_prices, bounce_exit_pct) |

**활성화 조건**: VPIN > 0.7 + CVD < -0.6
**진입 가격**: -2%, -3%, -4%
**반등 청산**: +2%

**Atom**: activation_checker.py, order_placer.py, bounce_exit.py
**현재 파일**: `src/strategy/wick_catcher/` (5개 파일)

#### F4.9 SectorRotation

| 항목 | 내용 |
|---|---|
| **1-line** | 7개 섹터의 상대 강도를 분석하여 선호/회피 섹터를 결정한다 |
| **IN** | sector_data: `SectorData`, broker: `BrokerClient` (C0.6) |
| **OUT** | `RotationSignal` (top3_prefer, bottom2_avoid, scores) |

**7개 섹터**: Technology, Healthcare, Finance, Energy, Consumer, Industrial, Utilities
**현재 파일**: `src/strategy/sector_rotation.py`

#### F4.10 StrategyParams

| 항목 | 내용 |
|---|---|
| **1-line** | strategy_params.json 파일을 읽고 쓰며 40개 전략 파라미터를 관리한다 |
| **IN** | params_file_path: `str` |
| **OUT** | `StrategyParams` (모든 파라미터 타입 안전 접근) |
| **현재 파일** | `src/strategy/params.py` |

#### F4.11 TickerParams

| 항목 | 내용 |
|---|---|
| **1-line** | 티커별 개별 파라미터 (ATR 배수, 스탑 거리 등)를 관리한다 |
| **IN** | ticker: `str`, params_file: `str` |
| **OUT** | `TickerConfig` |
| **현재 파일** | `src/strategy/ticker_params.py` (673줄) |

#### F4.12 Backtester

| 항목 | 내용 |
|---|---|
| **1-line** | 과거 데이터로 전략을 백테스트하고 그리드 서치로 최적 파라미터를 탐색한다 |
| **IN** | backtest_config: `BacktestConfig`, historical_data: `list[OHLCV]` |
| **OUT** | `BacktestResult` (pnl, win_rate, sharpe, max_drawdown, best_params) |
| **현재 파일** | `src/strategy/backtester.py` (1,324줄) |

#### F4.13 ProfitTarget

| 항목 | 내용 |
|---|---|
| **1-line** | 월간 수익 목표 ($300/월 최소, 생존 매매)를 추적하고 관리한다 |
| **IN** | monthly_pnl: `MonthlyPnl` |
| **OUT** | `TargetStatus` (current_pnl, target_pnl, on_track, days_remaining) |
| **현재 파일** | `src/strategy/profit_target.py` (620줄) |

---

### F5. 실행 (Execution)

> 위치: `src/f5_execution/`
> 사용 Common: C0.6, C0.8, C0.12

#### F5.1 OrderManager

| 항목 | 내용 |
|---|---|
| **1-line** | 매수/매도/정정/취소 주문을 KIS API를 통해 실행한다 |
| **IN** | order_request: `OrderRequest`, broker: `BrokerClient` (C0.6) |
| **OUT** | `OrderResult` (order_id, status, filled_price, filled_qty) |
| **Atom** | build_order_params(request) -> dict, validate_order(request, portfolio) -> bool, submit_order(params, broker) -> RawResponse, parse_order_response(raw) -> OrderResult, convert_market_to_limit(price, slippage_pct) -> float |
| **현재 파일** | `src/executor/order_manager.py` (668줄) |

#### F5.2 PositionMonitor

| 항목 | 내용 |
|---|---|
| **1-line** | 보유 포지션을 실시간 모니터링하고 청산 판단을 실행한다 |
| **IN** | market_session: `TimeInfo` (C0.11), broker: `BrokerClient` (C0.6), regime: `MarketRegime` |
| **OUT** | `PositionState` (positions, sync_result, blocked_tickers) |
| **이벤트 발행** | `PositionChanged` -> EventBus -> F7.18 |
| **현재 파일** | `src/executor/position_monitor.py` (588줄) |

#### F5.3 UniverseManager

| 항목 | 내용 |
|---|---|
| **1-line** | ETF 유니버스의 CRUD (추가/삭제/활성화/비활성화)를 관리한다 |
| **IN** | universe_request: `UniverseRequest`, session: `AsyncSession` (C0.2) |
| **OUT** | `UniverseResult` (ticker_list, updated_count) |
| **현재 파일** | `src/executor/universe_manager.py` |

#### F5.4 ForcedLiquidator

| 항목 | 내용 |
|---|---|
| **1-line** | 긴급 상황에서 전체 포지션을 강제 청산한다 |
| **IN** | positions: `list[Position]`, broker: `BrokerClient` (C0.6) |
| **OUT** | `LiquidationResult` (liquidated_count, failed_tickers, total_value) |
| **현재 파일** | `src/executor/forced_liquidator.py` |

#### F5.5 PositionBootstrap

| 항목 | 내용 |
|---|---|
| **1-line** | 시스템 시작 시 브로커에서 현재 포지션을 동기화한다 |
| **IN** | broker: `BrokerClient` (C0.6) |
| **OUT** | `BootstrapResult` (positions, cash_available) |
| **현재 파일** | `src/executor/position_bootstrap.py` |

#### F5.6 AccountModeManager

| 항목 | 내용 |
|---|---|
| **1-line** | 모의/실전 계좌 모드를 전환한다 |
| **IN** | target_mode: `Literal["virtual", "real"]` |
| **OUT** | `ModeChangeResult` (success, current_mode) |
| **현재 파일** | `src/monitoring/account_mode.py` |

---

### F6. 리스크 & 안전 (Risk & Safety)

> 위치: `src/f6_risk/`
> 사용 Common: C0.2, C0.3, C0.8

**안전 체인 순서**: HardSafety -> SafetyChecker -> EmergencyProtocol -> CapitalGuard

#### F6.1 HardSafety

| 항목 | 내용 |
|---|---|
| **1-line** | 티커당 최대 15% 한도를 강제하고 crash/mild_bear에서 Bull ETF 매수를 이중 차단한다 |
| **IN** | order_intent: `OrderIntent`, portfolio: `PortfolioState`, regime: `MarketRegime` |
| **OUT** | `SafetyCheckResult` (allowed, blocked_reason) |
| **현재 파일** | `src/safety/hard_safety.py` |

```python
class SafetyCheckResult(BaseModel):
    """안전 검사 결과이다."""
    allowed: bool               # 주문 허용 여부
    blocked_reason: str | None  # 차단 사유 (None이면 허용)
    checker_name: str           # 검사 수행 주체 (HardSafety/SafetyChecker)
    current_exposure_pct: float # 현재 노출 비율
    max_allowed_pct: float      # 최대 허용 비율
```

#### F6.2 SafetyChecker

| 항목 | 내용 |
|---|---|
| **1-line** | 다중 안전 조건을 순차 검증하는 파이프라인이다 |
| **IN** | system_state: `SystemState` |
| **OUT** | `SafetyResult` (all_passed, failed_checks) |
| **현재 파일** | `src/safety/safety_checker.py` |

#### F6.3 EmergencyProtocol

| 항목 | 내용 |
|---|---|
| **1-line** | 6개 긴급 시나리오에 대응하여 전체 포지션을 즉시 청산한다 |
| **IN** | emergency_trigger: `EmergencyTrigger` |
| **OUT** | `EmergencyResult` (liquidated, halt_trading, scenario) |
| **이벤트 발행** | `EmergencyLiquidation` -> EventBus -> F5.1 |

```python
class EmergencyAction(BaseModel):
    """긴급 프로토콜 트리거 정보이다."""
    scenario: str               # 시나리오 유형 (daily_loss/api_failure/vix_spike/data_loss/macro_crash/manual)
    severity: Literal["warning", "critical", "fatal"]
    trigger_value: float        # 트리거 기준값
    threshold: float            # 임계값

class EmergencyResult(BaseModel):
    """긴급 프로토콜 실행 결과이다."""
    liquidated: int             # 청산된 포지션 수
    halt_trading: bool          # 매매 중지 여부
    scenario: str               # 발동된 시나리오
    actions_taken: list[EmergencyAction]
    cooldown_until: datetime | None
```

**6개 긴급 시나리오**: 일일 손실 한도, API 장애, VIX 급등, 데이터 단절, 매크로 급락, 수동 트리거

**현재 파일**: `src/safety/emergency_protocol.py` (704줄)

#### F6.4 CapitalGuard

| 항목 | 내용 |
|---|---|
| **1-line** | 최소 자본 유지 여부를 확인한다 |
| **IN** | account_balance: `AccountBalance` |
| **OUT** | `CapitalGuardResult` (sufficient, current_capital, min_required) |
| **현재 파일** | `src/safety/capital_guard.py` |

#### F6.5 RiskGatePipeline

| 항목 | 내용 |
|---|---|
| **1-line** | 7개 리스크 게이트를 순차 실행하여 거래 허용 여부를 판정한다 |
| **IN** | trade_context: `TradeContext` |
| **OUT** | `RiskGateResult` (all_passed, blocked_gate, gate_details) |

```python
class RiskGateResult(BaseModel):
    """리스크 게이트 파이프라인 결과이다."""
    all_passed: bool            # 모든 게이트 통과 여부
    blocked_gate: int | None    # 차단된 게이트 번호 (None이면 통과)
    blocked_reason: str | None  # 차단 사유
    gate_details: list[GateDetail]  # 각 게이트별 상세 결과

class GateDetail(BaseModel):
    """개별 게이트 평가 결과이다."""
    gate_number: int
    gate_name: str
    passed: bool
    score: float
    threshold: float
```

**7개 리스크 게이트**:

| Gate | 이름 | 현재 파일 |
|---|---|---|
| 1 | OBI 리스크 | `src/risk/risk_gate.py` |
| 2 | CrossAsset 리스크 | `src/risk/risk_gate.py` |
| 3 | Whale 리스크 | `src/risk/risk_gate.py` |
| 4 | Tilt 중지 | `src/psychology/tilt_detector.py` |
| 5 | 섹터 상관관계 | `src/risk/sector_correlation.py` |
| 6 | Friction 차단 | `src/risk/friction/` |
| 7 | MacroLiquidity | `src/macro/net_liquidity.py` |

**현재 파일**: `src/risk/risk_gate.py`

#### F6.6 DailyLossLimiter

| 항목 | 내용 |
|---|---|
| **1-line** | 일일 손실이 한도를 초과했는지 확인한다 |
| **IN** | daily_pnl: `DailyPnl`, limit_pct: `float` |
| **OUT** | `LossLimitResult` (exceeded, current_loss_pct) |
| **현재 파일** | `src/risk/daily_loss_limit.py` |

#### F6.7 ConcentrationLimiter

| 항목 | 내용 |
|---|---|
| **1-line** | 단일 포지션 집중도가 한도를 초과했는지 확인한다 |
| **IN** | portfolio: `PortfolioState`, max_pct: `float` |
| **OUT** | `ConcentrationResult` (exceeded, ticker, current_pct) |
| **현재 파일** | `src/risk/concentration.py` |

#### F6.8 TiltDetector

| 항목 | 내용 |
|---|---|
| **1-line** | 연패(3손실/10분 OR -2%/30분)를 감지하여 틸트 상태를 판정한다 |
| **IN** | trade_history: `list[TradeRecord]` |
| **OUT** | `TiltState` (is_tilted, lock_until, trigger_reason) |
| **현재 파일** | `src/psychology/tilt_detector.py` + `src/psychology/loss_tracker.py` + `src/psychology/tilt_enforcer.py` |

#### F6.9 SimpleVaR

| 항목 | 내용 |
|---|---|
| **1-line** | 99% 신뢰도 VaR(Value at Risk)를 계산한다 |
| **IN** | portfolio: `PortfolioState`, returns: `list[float]` |
| **OUT** | `VaRResult` (var_99, expected_shortfall) |
| **현재 파일** | `src/risk/simple_var.py` |

#### F6.10 RiskBudget

| 항목 | 내용 |
|---|---|
| **1-line** | Kelly Criterion(25% 분수) 기반 포지션 사이징을 계산한다 |
| **IN** | portfolio: `PortfolioState`, win_rate: `float`, avg_win: `float`, avg_loss: `float` |
| **OUT** | `PositionSizeResult` (kelly_pct, adjusted_pct, max_position) |
| **현재 파일** | `src/risk/risk_budget.py` |

#### F6.11 StopLossManager

| 항목 | 내용 |
|---|---|
| **1-line** | ATR 동적 손절가와 레짐 기반 트레일링 스탑을 계산한다 |
| **IN** | position: `Position`, atr: `float`, regime: `MarketRegime` |
| **OUT** | `StopLossResult` (stop_price, trailing_pct, break_even_active) |
| **현재 파일** | `src/risk/stop_loss.py` |

#### F6.12 DeadmanSwitch

| 항목 | 내용 |
|---|---|
| **1-line** | WebSocket 데이터 무응답 10초 이상 시 Beast 포지션을 즉시 청산한다 |
| **IN** | websocket_state: `WebSocketState`, beast_positions: `list[Position]` |
| **OUT** | `DeadmanResult` (triggered, liquidated_count) |
| **현재 파일** | `src/safety/deadman_switch.py` |

#### F6.13 MacroFlashCrash

| 항목 | 내용 |
|---|---|
| **1-line** | SPY/QQQ가 3분 내 -1.0% 하락 시 전체 포지션을 즉시 청산한다 |
| **IN** | index_prices: `IndexPrices`, cache: `CacheClient` (C0.3) |
| **OUT** | `CrashDetectResult` (crash_detected, severity, affected_indices) |
| **이벤트 발행** | `CrashDetected` -> EventBus -> F6.3 |
| **현재 파일** | `src/safety/macro_flash_crash.py` |

#### F6.14 GapRiskProtector

| 항목 | 내용 |
|---|---|
| **1-line** | 갭 크기를 4단계(Small/Medium/Large/Extreme)로 분류하고 대응 조치를 결정한다 |
| **IN** | gap_size: `GapSize`, position: `Position` |
| **OUT** | `GapAction` (level, size_reduction_pct, block_duration, stop_adjustment) |

**4단계**: Small (무시), Medium (-30% 사이즈), Large (-50% + 스탑 확대), Extreme (30분 차단 + 타이트 스탑)

**현재 파일**: `src/risk/gap_risk.py`

#### F6.15 FrictionCalculator

| 항목 | 내용 |
|---|---|
| **1-line** | 거래 마찰 비용(스프레드 + 슬리피지)을 계산하고 최소 수익 허들을 도출한다 |
| **IN** | trade_params: `TradeParams` |
| **OUT** | `FrictionResult` (spread_cost, slippage_cost, total_friction, min_gain_hurdle) |
| **현재 파일** | `src/risk/friction/` (6개 파일: spread_cost, slippage_cost, hurdle_calculator, config, models) |

#### F6.16 HouseMoneyMultiplier

| 항목 | 내용 |
|---|---|
| **1-line** | 일일 PnL 기반으로 포지션 배수(0.5x/1.0x/1.5x/2.0x)를 결정한다 |
| **IN** | daily_pnl: `DailyPnl` |
| **OUT** | `MultiplierResult` (multiplier, pnl_band) |
| **현재 파일** | `src/risk/house_money/` (5개 파일: daily_pnl_tracker, multiplier_engine, config, models) |

#### F6.17 AccountSafety

| 항목 | 내용 |
|---|---|
| **1-line** | 매매 윈도우 밖에서의 자동 정지와 계좌 안전 상태를 관리한다 |
| **IN** | market_clock: `TimeInfo` (C0.11) |
| **OUT** | `AccountSafetyResult` (should_stop, reason) |
| **현재 파일** | `src/safety/account_safety.py` |

#### F6.18 QuotaGuard

| 항목 | 내용 |
|---|---|
| **1-line** | KIS API 요청 속도 제한을 관리한다 |
| **IN** | request_count: `int`, window_seconds: `int` |
| **OUT** | `QuotaResult` (allowed, remaining, reset_at) |
| **현재 파일** | `src/safety/quota_guard.py` |

#### F6.19 NetLiquidityTracker

| 항목 | 내용 |
|---|---|
| **1-line** | FRED에서 TGA/WALCL/RRPONTSYD를 조회하여 Net Liquidity 바이어스를 계산한다 |
| **IN** | cache: `CacheClient` (C0.3), http_client: `AsyncHttpClient` (C0.4), fred_api_key: `str` (C0.1) |
| **OUT** | `LiquidityBias` (net_liquidity_bn, bias: INJECT/DRAIN/NEUTRAL, multiplier) |
| **현재 파일** | `src/macro/net_liquidity.py` (575줄) |

#### F6.20 LosingStreakDetector

| 항목 | 내용 |
|---|---|
| **1-line** | 연속 손실 횟수를 추적한다 |
| **IN** | trade_history: `list[TradeRecord]` |
| **OUT** | `StreakResult` (consecutive_losses, max_streak, risk_level) |
| **현재 파일** | `src/risk/losing_streak.py` |

---

### F7. 모니터링 API (Monitoring)

> 위치: `src/f7_monitoring/`
> 사용 Common: C0.2, C0.3, C0.5, C0.6, C0.7, C0.8

#### F7.1 ApiServer

| 항목 | 내용 |
|---|---|
| **1-line** | FastAPI 앱을 생성하고 라우터를 자동 등록한다 |
| **IN** | all_routers: `list[APIRouter]`, middleware_config: `MiddlewareConfig`, lifespan: `Callable` |
| **OUT** | `FastAPI` (라우터 등록 완료 앱 인스턴스) |
| **Atom** | create_app(lifespan) -> FastAPI, register_routes(app, routers) -> None, configure_middleware(app, config) -> None, configure_cors(app) -> None, start_server(app, host, port) -> None |
| **현재 파일** | `src/monitoring/api_server.py` (666줄) |

#### F7.2 DashboardEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 대시보드 요약, 포지션, 거래 내역, 차트, 계좌 정보 API를 제공한다 |
| **엔드포인트** | /dashboard/summary, /positions, /trades/recent, /charts/*, /accounts, /decay |
| **현재 파일** | `src/monitoring/dashboard_endpoints.py` (1,840줄 -> 8개 라우터로 분할) |

#### F7.3 AnalysisEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 종합 분석, 뉴스 분석 결과 API를 제공한다 |
| **엔드포인트** | /api/analysis/comprehensive/{ticker}, /tickers, /ticker-news/{ticker} |
| **현재 파일** | `src/monitoring/analysis_endpoints.py` (918줄) |

#### F7.4 TradingControlEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 매매 시작/중지를 제어하고 시간 윈도우를 검증한다 (Bearer 인증 필수) |
| **엔드포인트** | POST /api/trading/start, POST /api/trading/stop, GET /api/trading/status |
| **핵심 변경** | start 시 C0.11.is_trading_window() 검증 필수. 실패 시 400 에러 반환 |
| **현재 파일** | `src/monitoring/trading_control_endpoints.py` |

#### F7.5 MacroEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 거시 경제 지표, 달력, 유동성 API를 제공한다 |
| **엔드포인트** | /api/macro/indicators, /history/{series_id}, /calendar, /rate-outlook, /analysis, /net-liquidity, /refresh |
| **현재 파일** | `src/monitoring/macro_endpoints.py` (569줄) |

#### F7.6 NewsEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 뉴스 조회, 요약, 수집 트리거 API를 제공한다 |
| **엔드포인트** | /api/news/dates, /daily, /{id}, /summary, /collect-and-send |
| **현재 파일** | `src/monitoring/news_endpoints.py` + `src/monitoring/news_collect_endpoints.py` |

#### F7.7 UniverseEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | ETF 유니버스 CRUD 및 크롤링 제어 API를 제공한다 |
| **엔드포인트** | /universe, /add, /toggle, /{ticker}, /sectors, /mappings, /crawl/manual, /crawl/status/{task_id} |
| **현재 파일** | `src/monitoring/universe_endpoints.py` (1,048줄) |

#### F7.8 EmergencyEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 긴급 정지/재개 및 리스크 대시보드 API를 제공한다 |
| **엔드포인트** | /emergency/stop, /resume, /status, /api/risk/* |
| **현재 파일** | `src/monitoring/emergency_endpoints.py` (491줄) |

#### F7.9 BenchmarkEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 벤치마크(SPY/QQQ) 대비 수익률 비교 API를 제공한다 |
| **엔드포인트** | /benchmark/comparison, /chart, /api/target |
| **현재 파일** | `src/monitoring/benchmark_endpoints.py` + `src/monitoring/benchmark.py` |

#### F7.10 TradeReasoningEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 매매 근거 상세 조회 및 피드백 API를 제공한다 |
| **엔드포인트** | /api/trade-reasoning/dates, /daily, /stats, /{id}/feedback |
| **현재 파일** | `src/monitoring/trade_reasoning_endpoints.py` (522줄) |

#### F7.11 IndicatorEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 지표 가중치 및 RSI 현황 API를 제공한다 |
| **엔드포인트** | /api/indicators/weights, /rsi |
| **현재 파일** | `src/monitoring/indicator_endpoints.py` |

#### F7.12 ManualTradeEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 수동 매매 분석 및 실행 API를 제공한다 |
| **엔드포인트** | /api/manual/analyze, /execute |
| **현재 파일** | `src/monitoring/manual_trade_endpoints.py` |

#### F7.13 PrinciplesEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 매매 원칙 CRUD API를 제공한다 |
| **엔드포인트** | /api/principles/* |
| **현재 파일** | `src/monitoring/principles_endpoints.py` |

#### F7.14 AgentEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | AI 에이전트 관리 API를 제공한다 |
| **엔드포인트** | /api/agents/* |
| **현재 파일** | `src/monitoring/agent_endpoints.py` |

#### F7.15 SystemEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 시스템 상태 및 헬스체크 API를 제공한다 |
| **엔드포인트** | /api/system/health, /status, /logs |
| **현재 파일** | `src/monitoring/system_endpoints.py` |

#### F7.16 PerformanceEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 성과 분석(PnL, 승률, 드로우다운) API를 제공한다 |
| **엔드포인트** | /api/performance/* |
| **현재 파일** | `src/monitoring/performance_endpoints.py` |

#### F7.17 OrderFlowEndpoints

| 항목 | 내용 |
|---|---|
| **1-line** | 주문 흐름 분석 API를 제공한다 |
| **엔드포인트** | /api/orderflow/* |
| **현재 파일** | `src/monitoring/order_flow_endpoints.py` |

#### F7.18 WebSocketManager

| 항목 | 내용 |
|---|---|
| **1-line** | 실시간 WebSocket 스트림 (3초 갱신)을 관리한다 |
| **IN** | cache: `CacheClient` (C0.3), positions: `PositionState` |
| **OUT** | `WebSocketFrame` (type, data, timestamp) |

**5개 WebSocket 스트림**:

| 스트림 | 내용 |
|---|---|
| /ws/dashboard | 대시보드 실시간 업데이트 |
| /ws/positions | 포지션 실시간 변동 |
| /ws/orderflow | 주문 흐름 실시간 |
| /ws/alerts | 긴급 알림 |
| /ws/trades | 체결 실시간 |

**현재 파일**: `src/monitoring/realtime_tape.py` + `src/websocket/manager.py`

#### F7.19 TelegramNotifier

| 항목 | 내용 |
|---|---|
| **1-line** | 텔레그램으로 매매 알림, 일일 보고서, 긴급 알림, 핵심 뉴스를 발송한다 |
| **IN** | event_type: `str`, data: `BaseModel`, telegram: `TelegramSender` (C0.7) |
| **OUT** | `NotifyResult` (sent, message_id) |

**알림 유형**: 매매 체결, 일일 보고서, 긴급 알림, 핵심 뉴스, 시스템 상태

**현재 파일**: `src/monitoring/telegram_notifier.py` (717줄)

#### F7.20 IndicatorCrawler

| 항목 | 내용 |
|---|---|
| **1-line** | FRED 거시 지표를 주기적으로 크롤링한다 (TGA, WALCL, RRPONTSYD) |
| **IN** | http_client: `AsyncHttpClient` (C0.4), fred_api_key: `str` (C0.1) |
| **OUT** | `IndicatorCrawlResult` (indicators_updated, last_crawl) |
| **현재 파일** | `src/monitoring/indicator_crawler.py` (661줄) + `src/monitoring/fred_client.py` (674줄) |

#### F7.21 AuthMiddleware

| 항목 | 내용 |
|---|---|
| **1-line** | Bearer 토큰 기반 API 인증을 수행한다 |
| **IN** | authorization_header: `str`, api_secret: `str` (C0.1) |
| **OUT** | `AuthResult` (authenticated, user_id) |
| **현재 파일** | `src/monitoring/auth.py` |

#### F7.22 Schemas

| 항목 | 내용 |
|---|---|
| **1-line** | API 요청/응답 Pydantic 스키마를 정의한다 |
| **현재 파일** | `src/monitoring/schemas.py` |

---

### F8. 최적화 & ML (Optimization)

> 위치: `src/f8_optimization/`
> 사용 Common: C0.2, C0.3, C0.5, C0.8

#### F8.1 DataPreparer

| 항목 | 내용 |
|---|---|
| **1-line** | DB에서 학습용 데이터를 조회하고 정제한다 |
| **IN** | date_range: `DateRange`, session: `AsyncSession` (C0.2) |
| **OUT** | `PreparedData` (DataFrame) |
| **현재 파일** | `src/optimization/data_preparer.py` |

#### F8.2 FeatureEngineer

| 항목 | 내용 |
|---|---|
| **1-line** | 21개 피처를 생성한다 (기술적 + 주문흐름 + 거시) |
| **IN** | prepared_data: `PreparedData` |
| **OUT** | `FeatureMatrix` (features, feature_names) |
| **현재 파일** | `src/optimization/feature_engineer.py` |

#### F8.3 TargetBuilder

| 항목 | 내용 |
|---|---|
| **1-line** | 타겟 라벨(P(+1%/5min))을 생성한다 |
| **IN** | prepared_data: `PreparedData` |
| **OUT** | `LabelVector` (labels, positive_ratio) |
| **현재 파일** | `src/optimization/target_builder.py` |

#### F8.4 LGBMTrainer

| 항목 | 내용 |
|---|---|
| **1-line** | LightGBM 모델을 TimeSeriesSplit으로 학습한다 |
| **IN** | features: `FeatureMatrix`, labels: `LabelVector` |
| **OUT** | `TrainedModel` (model, metrics, feature_importance) |
| **현재 파일** | `src/optimization/lgbm_trainer.py` |

#### F8.5 OptunaOptimizer

| 항목 | 내용 |
|---|---|
| **1-line** | TPE 알고리즘으로 200 트라이얼 하이퍼파라미터 최적화를 수행한다 |
| **IN** | trained_model: `TrainedModel`, features: `FeatureMatrix`, labels: `LabelVector` |
| **OUT** | `OptimizedParams` (best_params, best_score, trials_count) |
| **현재 파일** | `src/optimization/optuna_optimizer.py` |

#### F8.6 WalkForward

| 항목 | 내용 |
|---|---|
| **1-line** | 4주 학습/1주 테스트 워크 포워드 검증을 수행한다 |
| **IN** | prepared_data: `PreparedData`, optimized_params: `OptimizedParams` |
| **OUT** | `WalkForwardResult` (folds, avg_score, stability) |
| **현재 파일** | `src/optimization/walk_forward.py` |

#### F8.7 AutoTrainer

| 항목 | 내용 |
|---|---|
| **1-line** | 주간 자동 학습 파이프라인을 실행한다 |
| **IN** | cron_trigger: `CronTrigger` |
| **OUT** | `TrainingReport` (model_version, metrics, deployed) |
| **현재 파일** | `src/optimization/auto_trainer.py` |

#### F8.8 TimeTravelTrainer

| 항목 | 내용 |
|---|---|
| **1-line** | 분봉 리플레이로 과거를 재현하고 ChromaDB RAG에 임베딩한다 |
| **IN** | historical_data: `HistoricalData`, knowledge_manager: `KnowledgeManager` |
| **OUT** | `TimeTravelResult` (embeddings_count, patterns_found) |
| **현재 파일** | `src/optimization/time_travel.py` |

#### F8.9 ExecutionOptimizer

| 항목 | 내용 |
|---|---|
| **1-line** | EOD에 매매 결과를 분석하여 전략 파라미터를 +/-5% 자동 조정한다 (최대 30% 이탈) |
| **IN** | daily_trades: `list[TradeRecord]`, current_params: `StrategyParams` |
| **OUT** | `OptimizedParams` (adjusted_params, changes, backup_path) |
| **현재 파일** | `src/feedback/execution_optimizer/` (6개 파일: trade_analyzer, param_tuner, param_writer, runner, config, models) |

#### F8.10 KnowledgeManager

| 항목 | 내용 |
|---|---|
| **1-line** | ChromaDB + BGE-M3 기반 RAG 지식을 저장하고 검색한다 |
| **IN** | document: `Document`, query: `str` |
| **OUT** | `KnowledgeResult` (documents, scores, embedding_count) |
| **현재 파일** | `src/ai/knowledge_manager.py` (691줄) + `src/rag/` (5개 파일) |

---

### F9. 오케스트레이션 (Orchestration)

> 위치: `src/f9_orchestration/`
> 사용 Common: ALL
> 역할: 전체 시스템 생명주기를 관리한다. 현재 main.py (3,255줄)을 이 계층으로 분리한다.

#### F9.1 SystemInitializer

| 항목 | 내용 |
|---|---|
| **1-line** | 전체 시스템을 초기화한다 (Common -> Feature 순서로 인스턴스 생성) |
| **IN** | app_config: `SecretProvider` (C0.1) |
| **OUT** | `SystemComponents` (모든 Common + Feature 인스턴스) |
| **현재 파일** | `src/main.py` 432~927줄 (initialize 메서드) |

#### F9.2 DependencyInjector

| 항목 | 내용 |
|---|---|
| **1-line** | 모든 Feature의 Manager에 Common 인프라를 주입한다 |
| **IN** | system_components: `SystemComponents` |
| **OUT** | `InjectedSystem` (모든 의존성 조립 완료) |
| **현재 파일** | `src/main.py` + `src/monitoring/api_server.py` (set_dependencies) |

#### F9.3 PreparationPhase

| 항목 | 내용 |
|---|---|
| **1-line** | 매매 시작 전 사전 준비를 실행한다 (인프라 검사, 토큰 갱신, 크롤링, 분류, 레짐 감지) |
| **IN** | market_clock: `TimeInfo` (C0.11), components: `InjectedSystem` |
| **OUT** | `PreparationResult` (regime, classified_news, safety_status, ready, infra_health) |
| **현재 파일** | `src/orchestration/preparation.py` |

**내부 실행 순서**:

```
Step 0: InfrastructureHealthCheck (fail-fast)
    |   - Docker compose ps (DB/Redis 컨테이너 상태)
    |   - DB: SELECT 1 (연결 확인)
    |   - Redis: PING (연결 확인)
    |   - KIS: get_token() (인증 토큰 발급)
    |   - 실패 시 매매 시작 차단 + 텔레그램 알림
    |
    v
Step 1: C0.6 BrokerGateway: KIS 토큰 갱신 (실전/모의)
Step 2: F1.7 CrawlEngine: 30개 소스 크롤링
Step 3: F2.1 NewsClassifier: 뉴스 분류
Step 4: F2.2 RegimeDetector: VIX 기반 레짐 감지
Step 5: F2.3 ComprehensiveTeam: 5인 페르소나 분석
Step 6: F6.2 SafetyChecker: 안전 체크 체인
```

#### F9.4 TradingLoop

| 항목 | 내용 |
|---|---|
| **1-line** | 세션별 동적 주기로 매매 루프를 반복한다 |
| **IN** | market_session: `TimeInfo` (C0.11), components: `InjectedSystem` |
| **OUT** | `LoopIterationResult` (trades_executed, errors, next_interval) |
| **Atom** | determine_session(time_info) -> SessionType, calculate_interval(session_type) -> int, check_shutdown(time_info) -> bool, should_run_monitor_all(session_type) -> bool, sleep_with_interrupt(seconds, shutdown_event) -> bool |

**세션별 루프 주기**:

| 세션 | 시간 (ET) | 주기 | 동작 |
|---|---|---|---|
| Power Open | 09:30~10:00 | 90초 | 전체 monitor_all() |
| Mid Day | 10:00~15:30 | 180초 | 전체 monitor_all() |
| Power Hour | 15:30~16:00 | 120초 | 전체 monitor_all() |
| After Monitor | 16:00~ | 30~60초 | sync_positions() only |

**비정규 세션**: monitor_all() 호출 금지. sync_positions()만 실행한다.

**현재 파일**: `src/orchestration/trading_loop.py` + `src/main.py`

#### F9.5 ContinuousAnalysisLoop

| 항목 | 내용 |
|---|---|
| **1-line** | 30분 주기 연속 분석 루프를 관리한다 |
| **IN** | market_session: `TimeInfo` (C0.11), ai_client: `AiClient` (C0.5) |
| **OUT** | `AnalysisLoopResult` (iterations, issues_found) |
| **현재 파일** | `src/orchestration/continuous_analysis.py` |

#### F9.6 NewsPipeline

| 항목 | 내용 |
|---|---|
| **1-line** | 뉴스 수집 -> 분류 -> 텔레그램 전송 파이프라인을 실행한다 |
| **IN** | crawl_schedule: `CrawlSchedule`, components: `InjectedSystem` |
| **OUT** | `PipelineResult` (crawled, classified, sent_count) |
| **현재 파일** | `src/orchestration/news_pipeline.py` |

#### F9.7 EODSequence

| 항목 | 내용 |
|---|---|
| **1-line** | 일일 종료 시퀀스를 실행한다 (청산, 피드백, 파라미터 최적화, 리셋) |
| **IN** | eod_trigger: `EODTrigger`, components: `InjectedSystem` |
| **OUT** | `EODReport` (feedback_sent, params_adjusted, positions_closed) |

**EOD 단계** (main.py 실제 sub-steps 기준):

| Step | 내용 | 모듈 |
|---|---|---|
| 1 | 포지션 동기화 | F5.2 PositionMonitor.sync_positions() |
| 2 | 일일 PnL 기록 | F6.16 HouseMoneyMultiplier (DailyPnlTracker) |
| 3 | 벤치마크 스냅샷 | F7.9 BenchmarkComparison |
| 4 | 피드백 보고서 생성 | FF.1 DailyFeedback |
| 4-1 | 종합팀 EOD 분석 | F2.7 PromptRegistry + F2.3 ComprehensiveTeam |
| 5 | 이익 목표 업데이트 | F4.13 ProfitTarget |
| 6 | 리스크 예산 업데이트 | F6.10 RiskBudget |
| 7 | 파라미터 자동 최적화 | F8.9 ExecutionOptimizer |
| 7-1 | RAG 지식 업데이트 | FF.3 RAGDocUpdater (F8.10 KnowledgeManager) |
| 7-1b | Phase 9 모듈 일일 리셋 | F6.12 DeadmanSwitch + F6.13 MacroFlashCrash |
| 7-1c | Phase 10 모듈 일일 리셋 | F4.4 Pyramiding + F6.14 GapRiskProtector |
| 7-1d | Phase 12 모듈 일일 리셋 | F6.19 NetLiquidityTracker |
| 7-1e | 블록 티커 초기화 | F5.2 PositionMonitor (_sell_blocked_tickers reset) |
| 8 | 강제 청산 (EOD 보유분) | F5.4 ForcedLiquidator (max_hold_days=0 레짐) |
| 9 | QuotaGuard 정리 | F6.18 QuotaGuard |
| 10 | 라이브 준비 상태 체크 | F7.15 SystemEndpoints (live_readiness) |
| 11 | 텔레그램 일일 보고서 | FF.6 DailyReportGenerator + F7.19 TelegramNotifier |

**이벤트 발행**: `EODStarted` -> EventBus -> F8.9

**현재 파일**: `src/main.py` (EOD 로직 전체)

#### F9.8 GracefulShutdown

| 항목 | 내용 |
|---|---|
| **1-line** | SIGTERM/SIGINT 수신 시 포지션 정리 후 모든 연결을 해제하고 종료한다 |
| **IN** | shutdown_signal: `ShutdownSignal`, components: `InjectedSystem` |
| **OUT** | `ShutdownResult` (connections_closed, positions_safe, clean_exit) |
| **현재 파일** | `src/main.py` (shutdown 로직) |

#### F9.9 WeeklyAnalysisSequence

| 항목 | 내용 |
|---|---|
| **1-line** | 주간 종합 분석을 실행한다 (성과 분석, 벤치마크 비교, ML 재학습, 보고서 발송) |
| **IN** | week_number: `int`, trading_history: `list[TradeRecord]`, benchmark_data: `BenchmarkData` |
| **OUT** | `WeeklyReport` (win_rate, pnl, best_worst, patterns, model_retrained) |
| **실행 조건** | 일요일 00:00 KST (main.py 1578-1643 참조) |

**내부 실행 순서**:

```
Step 1: FF.2 WeeklyAnalysis -- 주간 성과 분석
    |
    v
Step 2: F7.9 BenchmarkComparison -- SPY/QQQ 대비 수익률 비교
    |
    v
Step 3: F8.7 AutoTrainer -- ML 모델 주간 재학습 (LightGBM + Optuna)
    |
    v
Step 4: F7.19 TelegramNotifier -- 주간 보고서 텔레그램 발송
```

**현재 파일**: `src/main.py` (1578~1643줄, 주간 분석 로직)

---

### F10. 대시보드 (Flutter)

> 위치: `dashboard/`
> 역할: macOS Desktop 앱으로 시스템 상태를 실시간 모니터링하고 제어한다.

#### F10.1 ApiClient (도메인별 분리)

| 항목 | 내용 |
|---|---|
| **1-line** | 도메인별 HTTP 클라이언트를 분리한다 |
| **현재 파일** | `dashboard/lib/services/api_service.dart` (1,544줄 -> 도메인당 1개 파일) |

**IN/OUT 계약**:

| 도메인 클라이언트 | IN | OUT |
|---|---|---|
| DashboardApiClient | baseUrl + `/dashboard/summary` | `DashboardSummary` |
| TradingApiClient | baseUrl + `/api/trading/{start,stop,status}` + Bearer token | `TradingStatus` |
| NewsApiClient | baseUrl + `/api/news/{dates,daily,summary}` + query params | `NewsList` / `NewsSummary` |
| AnalysisApiClient | baseUrl + `/api/analysis/comprehensive/{ticker}` | `AnalysisResult` |
| UniverseApiClient | baseUrl + `/universe/*` + CRUD params | `UniverseList` / `UniverseResult` |
| EmergencyApiClient | baseUrl + `/emergency/{stop,resume,status}` + Bearer token | `EmergencyStatus` |
| MacroApiClient | baseUrl + `/api/macro/*` | `MacroIndicators` / `LiquidityData` |
| BenchmarkApiClient | baseUrl + `/benchmark/*` | `BenchmarkComparison` |
| PerformanceApiClient | baseUrl + `/api/performance/*` | `PerformanceData` |
| OrderFlowApiClient | baseUrl + `/api/orderflow/*` | `OrderFlowSnapshot` |
| ManualTradeApiClient | baseUrl + `/api/manual/{analyze,execute}` + trade params | `TradeAnalysis` / `TradeResult` |

**분리 대상**:
- DashboardApiClient, TradingApiClient, NewsApiClient, AnalysisApiClient
- UniverseApiClient, EmergencyApiClient, MacroApiClient, BenchmarkApiClient
- PerformanceApiClient, OrderFlowApiClient, ManualTradeApiClient

#### F10.2 WebSocketClient

| 항목 | 내용 |
|---|---|
| **1-line** | 실시간 WebSocket 연결을 관리한다 (3초 갱신, 재연결 로직) |
| **IN** | server_url: `String` (ws://localhost:8000/ws/{channel}) |
| **OUT** | `Stream<WebSocketEvent>` (type, data, timestamp) |
| **현재 파일** | `dashboard/lib/services/websocket_service.dart` |

**5개 WebSocket 채널**: /ws/dashboard, /ws/positions, /ws/orderflow, /ws/alerts, /ws/trades

#### F10.3 Providers (도메인별 상태 관리)

**IN**: 각 Provider는 해당 도메인의 `ApiClient` 또는 `WebSocketClient`를 DI로 주입받는다.
**OUT**: 각 Provider는 `StateNotifier<AsyncValue<T>>`를 제공한다 (Riverpod).

| Provider | 현재 파일 | 책임 |
|---|---|---|
| DashboardProvider | `dashboard_provider.dart` | 대시보드 요약 상태 |
| TradingControlProvider | `trading_control_provider.dart` | 매매 제어 상태 |
| NewsProvider | `news_provider.dart` | 뉴스 상태 |
| UniverseProvider | `universe_provider.dart` | 유니버스 상태 |
| EmergencyProvider | `emergency_provider.dart` | 긴급 상태 |
| MacroProvider | `macro_provider.dart` | 거시 지표 상태 |
| BenchmarkProvider | `benchmark_provider.dart` | 벤치마크 상태 |
| ChartProvider | `chart_provider.dart` | 차트 데이터 |
| RiskProvider | `risk_provider.dart` | 리스크 상태 |
| TradeProvider | `trade_provider.dart` | 거래 상태 |
| TradeReasoningProvider | `trade_reasoning_provider.dart` | 매매 근거 상태 |
| StockAnalysisProvider | `stock_analysis_provider.dart` | 종목 분석 상태 |
| IndicatorProvider | `indicator_provider.dart` | 지표 상태 |
| AgentProvider | `agent_provider.dart` | AI 에이전트 상태 |
| PrinciplesProvider | `principles_provider.dart` | 매매 원칙 상태 |
| SettingsProvider | `settings_provider.dart` | 설정 상태 |
| ThemeProvider | `theme_provider.dart` | 테마 상태 |
| LocaleProvider | `locale_provider.dart` | 언어 상태 |
| NavigationProvider | `navigation_provider.dart` | 네비게이션 상태 |
| TaxFxProvider | `tax_fx_provider.dart` | 세금/환율 상태 |
| ProfitTargetProvider | `profit_target_provider.dart` | 수익 목표 상태 |
| ReportProvider | `report_provider.dart` | 보고서 상태 |
| ScalperTapeProvider | `scalper_tape_provider.dart` | 스캘퍼 테이프 상태 |
| ManualTradeProvider | `manual_trade_provider.dart` | 수동 매매 상태 |
| CrawlProgressProvider | `crawl_progress_provider.dart` | 크롤링 진행 상태 |
| TradingModeProvider | `trading_mode_provider.dart` | 매매 모드 상태 |

#### F10.4 Screens (28개)

| 스크린 | 현재 파일 | 줄 수 |
|---|---|---|
| HomeDashboard | `home_dashboard.dart` | 1,754 |
| OverviewScreen | `overview_screen.dart` | 1,919 |
| NewsScreen | `news_screen.dart` | 1,963 |
| UniverseScreen | `universe_screen.dart` | 1,827 |
| StockAnalysisScreen | `stock_analysis_screen.dart` | 1,719 |
| TradeReasoningScreen | `trade_reasoning_screen.dart` | 1,587 |
| RsiScreen | `rsi_screen.dart` | 1,429 |
| PrinciplesScreen | `principles_screen.dart` | 1,223 |
| SettingsScreen | `settings_screen.dart` | 1,046 |
| RiskCenterScreen | `risk_center_screen.dart` | 1,032 |
| TradingScreen | `trading_screen.dart` | - |
| ChartDashboard | `chart_dashboard.dart` | - |
| AnalyticsScreen | `analytics_screen.dart` | - |
| AlertHistory | `alert_history.dart` | - |
| AiReport | `ai_report.dart` | - |
| ManualTradeScreen | `manual_trade_screen.dart` | - |
| ManualCrawlScreen | `manual_crawl_screen.dart` | - |
| StrategySettings | `strategy_settings.dart` | - |
| IndicatorSettings | `indicator_settings.dart` | - |
| TickerParamsScreen | `ticker_params_screen.dart` | - |
| ProfitTargetScreen | `profit_target_screen.dart` | - |
| ReportsScreen | `reports_screen.dart` | - |
| RiskDashboardScreen | `risk_dashboard_screen.dart` | - |
| ScalperTapeScreen | `scalper_tape_screen.dart` | - |
| UniverseManagerScreen | `universe_manager_screen.dart` | - |
| AgentTeamScreen | `agent_team_screen.dart` | - |
| AgentDetailScreen | `agent_detail_screen.dart` | - |
| ShellScreen | `shell_screen.dart` | - |

#### F10.5 Models (22개)

| 모델 | 현재 파일 |
|---|---|
| DashboardModels | `dashboard_models.dart` |
| TradeModels | `trade_models.dart` |
| NewsModels | `news_models.dart` |
| UniverseModels | `universe_models.dart` |
| EmergencyModels | `emergency_models.dart` |
| MacroModels | `macro_models.dart` |
| BenchmarkModels | `benchmark_models.dart` |
| ChartModels | `chart_models.dart` |
| RiskModels | `risk_models.dart` |
| TradeReasoningModels | `trade_reasoning_models.dart` |
| StockAnalysisModels | `stock_analysis_models.dart` |
| IndicatorModels | `indicator_models.dart` |
| AgentModels | `agent_models.dart` |
| PrinciplesModels | `principles_models.dart` |
| RsiModels | `rsi_models.dart` |
| TaxModels | `tax_models.dart` |
| FxModels | `fx_models.dart` |
| SlippageModels | `slippage_models.dart` |
| ProfitTargetModels | `profit_target_models.dart` |
| ReportModels | `report_models.dart` |
| ScalperTapeModels | `scalper_tape_models.dart` |
| TickerParamsModels | `ticker_params_models.dart` |

#### F10.6 Widgets (재사용 위젯, 30개)

| 위젯 | 현재 파일 |
|---|---|
| GlassCard | `glass_card.dart` |
| StatCard | `stat_card.dart` |
| PositionCard | `position_card.dart` |
| SidebarNav | `sidebar_nav.dart` |
| StatusBar | `status_bar.dart` |
| SectionHeader | `section_header.dart` |
| EmptyState | `empty_state.dart` |
| ConfirmationDialog | `confirmation_dialog.dart` |
| EmergencyButton | `emergency_button.dart` |
| AlertPanel | `alert_panel.dart` |
| PnlLineChart | `pnl_line_chart.dart` |
| CumulativeChart | `cumulative_chart.dart` |
| DrawdownChart | `drawdown_chart.dart` |
| RsiChart | `rsi_chart.dart` |
| RateChart | `rate_chart.dart` |
| FearGreedGauge | `fear_greed_gauge.dart` |
| FearGreedChart | `fear_greed_chart.dart` |
| CpiChart | `cpi_chart.dart` |
| HourlyHeatmap | `hourly_heatmap.dart` |
| TickerHeatmap | `ticker_heatmap.dart` |
| ObiGaugeWidget | `obi_gauge_widget.dart` |
| CvdTrendWidget | `cvd_trend_widget.dart` |
| VpinToxicityWidget | `vpin_toxicity_widget.dart` |
| MacroStatsRow | `macro_stats_row.dart` |
| WeightSlider | `weight_slider.dart` |
| CrawlProgressWidget | `crawl_progress_widget.dart` |
| TickerAddDialog | `ticker_add_dialog.dart` |
| AgentTeamTree | `agent_team_tree.dart` |
| EconomicCalendarCard | `economic_calendar_card.dart` |
| AnimationUtils | `animation_utils.dart` |

#### F10.7 Theme & Design Tokens

| 파일 | 역할 |
|---|---|
| `app_theme.dart` | 전체 테마 정의 |
| `app_colors.dart` | 기본 색상 팔레트 |
| `app_typography.dart` | 타이포그래피 정의 |
| `app_spacing.dart` | 간격 토큰 |
| `chart_colors.dart` | 차트 전용 색상 |
| `domain_colors.dart` | 도메인별 색상 |
| `trading_colors.dart` | 매매 관련 색상 (매수/매도/수익/손실) |

---

### FW. WebSocket 실시간 (WebSocket Engine)

> 위치: `src/fw_websocket/`
> 사용 Common: C0.1, C0.3, C0.6, C0.8

#### FW.1 WebSocketConnection

| 항목 | 내용 |
|---|---|
| **1-line** | KIS WebSocket 연결을 관리한다 (인증, 재연결, AES 복호화) |
| **IN** | broker_config: `BrokerConfig` (C0.1, C0.6) |
| **OUT** | `ConnectionState` (connected, subscriptions) |
| **현재 파일** | `src/websocket/connection.py` + `src/websocket/auth.py` + `src/websocket/crypto.py` + `src/websocket/config.py` |

#### FW.2 MessageParser

| 항목 | 내용 |
|---|---|
| **1-line** | WebSocket 수신 메시지를 파싱한다 |
| **IN** | raw_message: `str | bytes` |
| **OUT** | `ParsedMessage` (type, data) |
| **현재 파일** | `src/websocket/parser.py` |

#### FW.3 TradeHandler

| 항목 | 내용 |
|---|---|
| **1-line** | 체결 메시지를 처리한다 |
| **IN** | parsed: `ParsedMessage` |
| **OUT** | `TradeEvent` (ticker, price, volume, time) |
| **현재 파일** | `src/websocket/handlers/trade_handler.py` |

#### FW.4 OrderbookHandler

| 항목 | 내용 |
|---|---|
| **1-line** | 호가창 메시지를 처리한다 |
| **IN** | parsed: `ParsedMessage` |
| **OUT** | `OrderbookSnapshot` (bids, asks) |
| **현재 파일** | `src/websocket/handlers/orderbook_handler.py` |

#### FW.5 NoticeHandler

| 항목 | 내용 |
|---|---|
| **1-line** | 공지/알림 메시지를 처리한다 |
| **IN** | parsed: `ParsedMessage` |
| **OUT** | `NoticeEvent` (type, content) |
| **현재 파일** | `src/websocket/handlers/notice_handler.py` |

#### FW.6 OBICalculator

| 항목 | 내용 |
|---|---|
| **1-line** | 호가창 데이터로 Order Book Imbalance를 계산한다 |
| **IN** | orderbook: `OrderbookSnapshot` |
| **OUT** | `OBIValue` (score: float, direction: str) |
| **현재 파일** | `src/websocket/indicators/obi.py` |

#### FW.7 VPINCalculator

| 항목 | 내용 |
|---|---|
| **1-line** | Volume-Synchronized PIN을 계산한다 |
| **IN** | trades: `list[TradeEvent]` |
| **OUT** | `VPINValue` (score: float, toxicity: str) |
| **현재 파일** | `src/websocket/indicators/vpin.py` |

#### FW.8 CVDCalculator

| 항목 | 내용 |
|---|---|
| **1-line** | Cumulative Volume Delta를 계산한다 |
| **IN** | trades: `list[TradeEvent]` |
| **OUT** | `CVDValue` (delta: float, trend: str) |
| **현재 파일** | `src/websocket/indicators/cvd.py` |

#### FW.9 ExecutionStrength

| 항목 | 내용 |
|---|---|
| **1-line** | 체결 강도를 계산한다 |
| **IN** | trades: `list[TradeEvent]` |
| **OUT** | `StrengthValue` (score: float) |
| **현재 파일** | `src/websocket/indicators/execution_strength.py` |

#### FW.10 TickWriter

| 항목 | 내용 |
|---|---|
| **1-line** | 실시간 체결 데이터를 DB에 기록한다 |
| **IN** | trade_event: `TradeEvent`, session: `AsyncSession` (C0.2) |
| **OUT** | `WriteResult` (success, rows_written) |
| **현재 파일** | `src/websocket/storage/tick_writer.py` |

#### FW.11 RedisPublisher

| 항목 | 내용 |
|---|---|
| **1-line** | 실시간 데이터를 Redis 채널에 발행한다 |
| **IN** | event: `TradeEvent | OrderbookSnapshot`, cache: `CacheClient` (C0.3) |
| **OUT** | `PublishResult` (published, channel) |
| **현재 파일** | `src/websocket/storage/redis_publisher.py` |

#### FW.12 WebSocketSubscriber

| 항목 | 내용 |
|---|---|
| **1-line** | 티커별 WebSocket 구독을 관리한다 |
| **IN** | tickers: `list[str]`, connection: `ConnectionState` |
| **OUT** | `SubscriptionResult` (subscribed, failed) |
| **현재 파일** | `src/websocket/subscriber.py` |

#### FW.13 WebSocketManager

| 항목 | 내용 |
|---|---|
| **1-line** | WebSocket 전체 생명주기를 관리하고 핸들러를 오케스트레이션한다 |
| **IN** | config: `WebSocketConfig`, handlers: `list[Handler]` |
| **OUT** | `ManagerState` (connected, active_subscriptions, last_message_time) |
| **현재 파일** | `src/websocket/manager.py` |

---

### FS. 스캘핑 (Scalping)

> 위치: `src/fs_scalping/`
> 사용 Common: C0.3, C0.6, C0.8

#### FS.1 ScalpingManager

| 항목 | 내용 |
|---|---|
| **1-line** | 스캘핑 전체 파이프라인(유동성 분석, 스푸핑 감지, 타임스탑)을 오케스트레이션한다 |
| **IN** | ticker: `str`, order_flow: `OrderFlowSnapshot`, strategy_params: `StrategyParams` |
| **OUT** | `ScalpingDecision` (safe_to_trade, adjusted_size, warnings) |
| **현재 파일** | `src/scalping/manager.py` (537줄) |

#### FS.2 DepthAnalyzer

| 항목 | 내용 |
|---|---|
| **1-line** | 호가창 깊이를 분석한다 |
| **IN** | orderbook: `OrderbookSnapshot` |
| **OUT** | `DepthAnalysis` (depth_score, imbalance, support_levels) |
| **현재 파일** | `src/scalping/liquidity/depth_analyzer.py` |

#### FS.3 ImpactEstimator

| 항목 | 내용 |
|---|---|
| **1-line** | 주문 실행 시 시장 충격을 추정한다 |
| **IN** | order_size: `float`, depth: `DepthAnalysis` |
| **OUT** | `ImpactEstimate` (expected_slippage_pct, impact_cost) |
| **현재 파일** | `src/scalping/liquidity/impact_estimator.py` |

#### FS.4 SpreadMonitor

| 항목 | 내용 |
|---|---|
| **1-line** | 실시간 스프레드를 모니터링한다 |
| **IN** | orderbook: `OrderbookSnapshot` |
| **OUT** | `SpreadState` (current_spread, avg_spread, spread_z_score) |
| **현재 파일** | `src/scalping/liquidity/spread_monitor.py` |

#### FS.5 LiquiditySizer

| 항목 | 내용 |
|---|---|
| **1-line** | 유동성 기반 최적 주문 크기를 결정한다 |
| **IN** | depth: `DepthAnalysis`, impact: `ImpactEstimate`, spread: `SpreadState` |
| **OUT** | `OptimalSize` (max_shares, recommended_shares) |
| **현재 파일** | `src/scalping/liquidity/sizer.py` |

#### FS.6 SpoofingDetector

| 항목 | 내용 |
|---|---|
| **1-line** | 호가창 스푸핑 패턴을 탐지한다 |
| **IN** | snapshots: `list[OrderbookSnapshot]` |
| **OUT** | `SpoofingSignal` (detected, pattern_type, confidence) |
| **Atom** | pattern_detector.py, snapshot_tracker.py, toxicity_scorer.py, trade_lock.py |
| **현재 파일** | `src/scalping/spoofing/` (4개 파일) |

#### FS.7 TimeStopManager

| 항목 | 내용 |
|---|---|
| **1-line** | 시간 기반 포지션 청산을 관리한다 |
| **IN** | position: `Position`, max_hold_seconds: `int` |
| **OUT** | `TimeStopResult` (should_exit, elapsed_seconds, reason) |
| **Atom** | timer.py, evaluator.py, executor.py |
| **현재 파일** | `src/scalping/time_stop/` (3개 파일) |

---

### FX. 세금 & 환율 (Tax & FX)

> 위치: `src/fx_tax/`
> 사용 Common: C0.2, C0.6, C0.8

#### FX.1 TaxTracker

| 항목 | 내용 |
|---|---|
| **1-line** | 매매별 세금을 계산하고 기록한다 |
| **IN** | trade: `TradeRecord`, session: `AsyncSession` (C0.2) |
| **OUT** | `TaxResult` (tax_amount, tax_rate, recorded) |
| **현재 파일** | `src/tax/tax_tracker.py` |

#### FX.2 FxManager

| 항목 | 내용 |
|---|---|
| **1-line** | USD/KRW 환율을 조회하고 관리한다 |
| **IN** | broker: `BrokerClient` (C0.6) |
| **OUT** | `FxRate` (usd_krw, last_updated) |
| **현재 파일** | `src/tax/fx_manager.py` |

#### FX.3 SlippageTracker

| 항목 | 내용 |
|---|---|
| **1-line** | 실제 체결가와 호가 차이(슬리피지)를 추적한다 |
| **IN** | order: `OrderResult`, expected_price: `float` |
| **OUT** | `SlippageRecord` (slippage_pct, slippage_amount) |
| **현재 파일** | `src/tax/slippage_tracker.py` |

---

### FT. 텔레그램 봇 (Telegram Bot)

> 위치: `src/ft_telegram/`
> 사용 Common: C0.7, C0.8

#### FT.1 BotHandler

| 항목 | 내용 |
|---|---|
| **1-line** | 텔레그램 봇 명령어를 수신하고 라우팅한다 |
| **IN** | update: `TelegramUpdate` |
| **OUT** | `BotResponse` (reply_text, parse_mode) |
| **현재 파일** | `src/telegram/bot_handler.py` (621줄) |

#### FT.2 CommandProcessor

| 항목 | 내용 |
|---|---|
| **1-line** | 정의된 명령어(/status, /positions, /stop 등)를 처리한다 |
| **IN** | command: `str`, args: `list[str]` |
| **OUT** | `CommandResult` (response_text, success) |
| **현재 파일** | `src/telegram/commands.py` |

#### FT.3 TradeCommands

| 항목 | 내용 |
|---|---|
| **1-line** | 텔레그램을 통한 수동 매매 명령을 처리한다 |
| **IN** | trade_command: `TradeCommand` |
| **OUT** | `TradeCommandResult` (executed, order_result) |
| **현재 파일** | `src/telegram/trade_commands.py` |

#### FT.4 MessageFormatter

| 항목 | 내용 |
|---|---|
| **1-line** | 알림 메시지를 HTML/Markdown 형식으로 포맷한다 |
| **IN** | data: `BaseModel`, template: `str` |
| **OUT** | `FormattedMessage` (text, parse_mode) |
| **현재 파일** | `src/telegram/formatters.py` |

#### FT.5 NLProcessor

| 항목 | 내용 |
|---|---|
| **1-line** | 자연어 입력을 매매 명령으로 변환한다 |
| **IN** | natural_text: `str`, ai_client: `AiClient` (C0.5) |
| **OUT** | `ParsedCommand` (command_type, params) |
| **현재 파일** | `src/telegram/nl_processor.py` |

#### FT.6 Permissions

| 항목 | 내용 |
|---|---|
| **1-line** | 텔레그램 사용자 권한을 확인한다 |
| **IN** | user_id: `int`, chat_id: `int` |
| **OUT** | `PermissionResult` (allowed, reason) |
| **현재 파일** | `src/telegram/permissions.py` |

---

### FF. 피드백 (Feedback)

> 위치: `src/ff_feedback/`
> 사용 Common: C0.2, C0.3, C0.5, C0.8

#### FF.1 DailyFeedback

| 항목 | 내용 |
|---|---|
| **1-line** | 일일 매매 성과를 분석하고 피드백을 생성한다 |
| **IN** | daily_trades: `list[TradeRecord]`, session: `AsyncSession` (C0.2) |
| **OUT** | `DailyFeedbackResult` (summary, lessons, improvements) |
| **현재 파일** | `src/feedback/daily_feedback.py` |

#### FF.2 WeeklyAnalysis

| 항목 | 내용 |
|---|---|
| **1-line** | 주간 성과 분석을 수행한다 |
| **IN** | weekly_data: `WeeklyData` |
| **OUT** | `WeeklyReport` (win_rate, pnl, best_worst, patterns) |
| **현재 파일** | `src/feedback/weekly_analysis.py` |

#### FF.3 RAGDocUpdater

| 항목 | 내용 |
|---|---|
| **1-line** | 일일 매매 결과를 RAG 지식 베이스에 반영한다 |
| **IN** | daily_result: `DailyFeedbackResult`, knowledge: `KnowledgeManager` |
| **OUT** | `UpdateResult` (documents_added, embeddings_created) |
| **현재 파일** | `src/feedback/rag_doc_updater.py` |

#### FF.4 ParamAdjuster

| 항목 | 내용 |
|---|---|
| **1-line** | 성과 기반으로 전략 파라미터를 미세 조정한다 |
| **IN** | feedback: `DailyFeedbackResult`, current_params: `StrategyParams` |
| **OUT** | `AdjustmentResult` (adjusted_keys, before_after) |
| **현재 파일** | `src/feedback/param_adjuster.py` |

#### FF.5 TimePerformance

| 항목 | 내용 |
|---|---|
| **1-line** | 시간대별 매매 성과를 분석한다 |
| **IN** | trades: `list[TradeRecord]` |
| **OUT** | `TimePerformanceResult` (hourly_pnl, best_hours, worst_hours) |
| **현재 파일** | `src/feedback/time_performance.py` (551줄) |

#### FF.6 DailyReportGenerator

| 항목 | 내용 |
|---|---|
| **1-line** | 일일 종합 보고서를 Markdown + summary dict로 생성한다 |
| **IN** | daily_trades: `list[TradeRecord]`, portfolio_summary: `PortfolioSummary`, analysis_results: `AnalysisSummary`, regime_info: `MarketRegime` |
| **OUT** | `DailyReport` (markdown_text, summary_dict, report_path) |

```python
class DailyReport(BaseModel):
    """일일 종합 보고서이다."""
    markdown_text: str          # Markdown 포맷 보고서 전문
    summary_dict: dict          # 텔레그램 발송용 요약 딕셔너리
    report_path: str            # docs/report/latest_report.md 저장 경로
    date: str                   # YYYY-MM-DD
    total_pnl_amount: float
    total_pnl_pct: float
    win_rate: float
    trade_count: int
    regime: str
```

**내부 기능**:
- 현재 main.py `_send_final_daily_report()` (670줄)에서 추출
- 일일 매매 요약, 포지션별 손익, 레짐 정보, 분석 결과를 종합
- `docs/report/latest_report.md` 파일 생성 및 업데이트
- F7.19 TelegramNotifier에 summary_dict 전달하여 텔레그램 발송

**현재 파일**: `src/main.py` (`_send_final_daily_report` 메서드) → `src/ff_feedback/daily_report_generator.py`

---

### FN. 뉴스 필터 (News Filter)

> 위치: `src/fn_filter/`
> 사용 Common: C0.3, C0.8

#### FN.1 RuleFilter

| 항목 | 내용 |
|---|---|
| **1-line** | 규칙 기반으로 뉴스를 필터링한다 (키워드, 소스, 시간) |
| **IN** | articles: `list[ClassifiedNews]`, rules: `FilterRules` |
| **OUT** | `FilterResult` (passed, filtered_out, reasons) |
| **현재 파일** | `src/filter/rule_filter.py` |

#### FN.2 SimilarityChecker

| 항목 | 내용 |
|---|---|
| **1-line** | 뉴스 간 유사도를 검사하여 중복성을 판별한다 |
| **IN** | article: `ClassifiedNews`, existing: `list[ClassifiedNews]` |
| **OUT** | `SimilarityResult` (is_duplicate, similarity_score, matched_id) |
| **현재 파일** | `src/filter/similarity_checker.py` |

---

## 5. 전체 파이프라인 (Main Pipeline)

### 5.1 최상위 흐름

```
[대시보드 버튼] --> [시간 체크] --> [준비] --> [매매 루프] --> [EOD] --> [종료]
```

```
Button Press (F10 Dashboard)
    |
    v
POST /api/trading/start (F7.4 TradingControlEndpoints)
    |
    v
C0.11 MarketClock.is_trading_window()
    |
    +-- False --> 400 "매매 가능 시간이 아닙니다 (20:00~06:30 KST)"
    |
    +-- True
        |
        v
F9.1 SystemInitializer --> SystemComponents
    |
    v
F9.2 DependencyInjector --> InjectedSystem
    |
    v
F9.3 PreparationPhase (20:00~20:30)
    |   |
    |   +-- Step 0: InfrastructureHealthCheck (DB, Redis, KIS -- fail-fast)
    |   +-- C0.6 BrokerGateway: KIS 토큰 갱신
    |   +-- F1.7 CrawlEngine: 30개 소스 크롤링
    |   +-- F2.1 NewsClassifier: 뉴스 분류
    |   +-- F2.2 RegimeDetector: VIX 기반 레짐 감지
    |   +-- F2.3 ComprehensiveTeam: 5인 페르소나 분석
    |   +-- F6.2 SafetyChecker: 안전 체크 체인
    |   |
    |   v
    |   PreparationResult
    |
    v
F9.4 TradingLoop (20:30~06:00)
    |   |
    |   +-- [매 루프 반복]
    |   |       |
    |   |       v
    |   |   F6.13 MacroFlashCrash: 급락 체크 (매 반복)
    |   |       |
    |   |       v
    |   |   F6.12 DeadmanSwitch: 데이터 단절 체크 (정규장)
    |   |       |
    |   |       v
    |   |   C0.11 MarketClock: 세션 타입 판별
    |   |       |
    |   |       +-- is_regular_session
    |   |       |       |
    |   |       |       v
    |   |       |   F5.2 PositionMonitor.monitor_all()
    |   |       |       |
    |   |       |       +-- F4.1 EntryStrategy (7 gates)
    |   |       |       +-- F4.2 ExitStrategy (10 types)
    |   |       |       +-- F4.3 BeastMode (A+ 셋업)
    |   |       |       +-- F4.4 Pyramiding (3 levels)
    |   |       |       +-- F5.1 OrderManager (주문 실행)
    |   |       |
    |   |       +-- non_regular_session
    |   |               |
    |   |               v
    |   |           F5.2 PositionMonitor.sync_positions() only
    |   |
    |   +-- [30분 주기]
    |   |       |
    |   |       v
    |   |   F9.5 ContinuousAnalysis (Opus 분석)
    |   |
    |   +-- [크롤링 주기]
    |           |
    |           v
    |       F9.6 NewsPipeline (수집 -> 분류 -> 전송)
    |
    v
F9.3 FinalMonitoring (06:00~06:30)
    |   |
    |   +-- F5.2 PositionMonitor.sync_positions()
    |   +-- F2.5 OvernightJudge: 오버나이트 판단
    |   +-- F6.2 SafetyChecker: 마지막 안전 체크
    |
    v
F9.7 EODSequence (06:30~07:00)
    |   |
    |   +-- Step 1: 포지션 동기화 (F5.2)
    |   +-- Step 2: 일일 PnL 기록 (F6.16)
    |   +-- Step 3: 벤치마크 스냅샷 (F7.9)
    |   +-- Step 4: 피드백 보고서 생성 (FF.1)
    |   +-- Step 4-1: 종합팀 EOD 분석 (F2.7 + F2.3)
    |   +-- Step 5: 이익 목표 업데이트 (F4.13)
    |   +-- Step 6: 리스크 예산 업데이트 (F6.10)
    |   +-- Step 7: 파라미터 자동 최적화 (F8.9)
    |   +-- Step 7-1: RAG 지식 업데이트 (FF.3)
    |   +-- Step 7-1b~e: Phase 9/10/12 모듈 리셋 + 블록 티커 초기화
    |   +-- Step 8: 강제 청산 (F5.4)
    |   +-- Step 9: QuotaGuard 정리 (F6.18)
    |   +-- Step 10: 라이브 준비 상태 체크 (F7.15)
    |   +-- Step 11: 텔레그램 일일 보고서 (FF.6 + F7.19)
    |
    v
F9.8 GracefulShutdown (07:00)
    |   |
    |   +-- DB 연결 해제
    |   +-- Redis 연결 해제
    |   +-- WebSocket 연결 해제
    |   +-- KIS 세션 정리
    |   +-- 프로세스 종료
    |
    v
[DONE]
```

### 5.2 안전 체인 (Safety Chain)

모든 매매 실행 전 반드시 통과해야 하는 4계층 안전 체인이다.

```
매매 의도 (OrderIntent)
    |
    v
F6.1 HardSafety (티커당 15%, Bull ETF 차단)
    |
    v
F6.2 SafetyChecker (종합 안전 조건)
    |
    v
F6.3 EmergencyProtocol (긴급 상황 감지)
    |
    v
F6.4 CapitalGuard (최소 자본 유지)
    |
    v
주문 실행 허용
```

### 5.3 Beast Mode 4계층 방어망

```
Network: F6.12 DeadmanSwitch (데이터 10초+ 무응답)
    |
    v
Market: F6.13 MacroFlashCrash (SPY/QQQ -1.0%/3분)
    |
    v
Time: F4.3 BeastMode.danger_zone (09:30~10:00 ET, 15:30~16:00 ET)
    |
    v
Price: Beast Hard Stop -1.0% (일반 -2%보다 타이트)
```

---

## 6. 크로스체크 테이블

### 6.1 Python 파일 매핑 (src/)

| 현재 파일 | 새 모듈 ID | 상태 |
|---|---|---|
| `src/main.py` (3,255줄) | F9.1~F9.8 (8개 모듈로 분리) | 분리 필수 |
| `src/__init__.py` | - | 유지 |
| **src/ai/** | | |
| `src/ai/__init__.py` | - | 유지 |
| `src/ai/knowledge_manager.py` (691줄) | F8.10 KnowledgeManager | 이동 |
| `src/ai/mlx_classifier.py` | C0.5 AiGateway (통합) | 통합 |
| **src/analysis/** | | |
| `src/analysis/__init__.py` | - | 유지 |
| `src/analysis/classifier.py` (623줄) | F2.1 NewsClassifier | 이동 |
| `src/analysis/claude_client.py` (649줄) | C0.5 AiGateway | 통합 |
| `src/analysis/comprehensive_team.py` | F2.3 ComprehensiveTeam | 이동 |
| `src/analysis/decision_maker.py` | F2.4 DecisionMaker | 이동 |
| `src/analysis/eod_feedback_report.py` | F2.10 EODFeedbackReport | 이동 |
| `src/analysis/key_news_filter.py` (520줄) | F2.9 KeyNewsFilter | 이동 |
| `src/analysis/news_theme_tracker.py` | F2.11 NewsThemeTracker | 이동 |
| `src/analysis/news_translator.py` | F2.12 NewsTranslator | 이동 |
| `src/analysis/overnight_judge.py` | F2.5 OvernightJudge | 이동 |
| `src/analysis/prompts.py` (1,896줄) | F2.7 PromptRegistry (5개 파일) | 분리 |
| `src/analysis/regime_detector.py` | F2.2 RegimeDetector | 이동 |
| `src/analysis/ticker_profiler.py` | F2.13 TickerProfiler | 이동 |
| **src/crawler/** | | |
| `src/crawler/__init__.py` | - | 유지 |
| `src/crawler/ai_context_builder.py` | F1.8 AiContextBuilder | 이동 |
| `src/crawler/alphavantage_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/base_crawler.py` | F1.2 CrawlerBase | 이동 |
| `src/crawler/crawl_engine.py` (1,099줄) | F1.7 CrawlEngine + F1.6 ArticlePersister | 분리 |
| `src/crawler/crawl_scheduler.py` | F1.1 CrawlScheduler | 이동 |
| `src/crawler/crawl_verifier.py` | F1.4 CrawlVerifier | 이동 |
| `src/crawler/dart_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/dedup.py` | F1.5 ArticleDeduplicator | 이동 |
| `src/crawler/economic_calendar.py` | F1.3 Crawlers | 이동 |
| `src/crawler/fear_greed_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/finnhub_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/finviz_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/fred_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/investing_crawler.py` (511줄) | F1.3 Crawlers | 이동 |
| `src/crawler/kalshi_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/naver_crawler.py` (670줄) | F1.3 Crawlers | 이동 |
| `src/crawler/polymarket_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/reddit_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/rss_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/sec_edgar_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/sources_config.py` | F1.1 CrawlScheduler (설정 통합) | 통합 |
| `src/crawler/stocknow_crawler.py` | F1.3 Crawlers | 이동 |
| `src/crawler/stocktwits_crawler.py` | F1.3 Crawlers | 이동 |
| **src/db/** | | |
| `src/db/__init__.py` | - | 유지 |
| `src/db/connection.py` | C0.2 DatabaseGateway + C0.3 CacheGateway | 분리 |
| `src/db/models.py` (675줄) | C0.2 (DB 모델은 Common에 유지) | 이동 |
| **src/executor/** | | |
| `src/executor/__init__.py` | - | 유지 |
| `src/executor/forced_liquidator.py` | F5.4 ForcedLiquidator | 이동 |
| `src/executor/kis_auth.py` | C0.6 BrokerGateway | 통합 |
| `src/executor/kis_client.py` (1,261줄) | C0.6 BrokerGateway (분할) | 분리 |
| `src/executor/order_manager.py` (668줄) | F5.1 OrderManager | 이동 |
| `src/executor/position_bootstrap.py` | F5.5 PositionBootstrap | 이동 |
| `src/executor/position_monitor.py` (588줄) | F5.2 PositionMonitor | 이동 |
| `src/executor/universe_manager.py` | F5.3 UniverseManager + C0.12 | 분리 |
| **src/fallback/** | | |
| `src/fallback/__init__.py` | - | 삭제 |
| `src/fallback/fallback_router.py` | C0.5 AiGateway (통합) | 통합 |
| `src/fallback/local_model.py` | C0.5 AiGateway (통합) | 통합 |
| **src/feedback/** | | |
| `src/feedback/__init__.py` | - | 유지 |
| `src/feedback/daily_feedback.py` | FF.1 DailyFeedback | 이동 |
| `src/feedback/execution_optimizer/__init__.py` | - | 유지 |
| `src/feedback/execution_optimizer/config.py` | F8.9 ExecutionOptimizer | 이동 |
| `src/feedback/execution_optimizer/models.py` | F8.9 ExecutionOptimizer | 이동 |
| `src/feedback/execution_optimizer/param_tuner.py` | F8.9 ExecutionOptimizer | 이동 |
| `src/feedback/execution_optimizer/param_writer.py` | F8.9 ExecutionOptimizer | 이동 |
| `src/feedback/execution_optimizer/runner.py` | F8.9 ExecutionOptimizer | 이동 |
| `src/feedback/execution_optimizer/trade_analyzer.py` | F8.9 ExecutionOptimizer | 이동 |
| `src/feedback/param_adjuster.py` | FF.4 ParamAdjuster | 이동 |
| `src/feedback/rag_doc_updater.py` | FF.3 RAGDocUpdater | 이동 |
| `src/feedback/time_performance.py` (551줄) | FF.5 TimePerformance | 이동 |
| `src/feedback/weekly_analysis.py` | FF.2 WeeklyAnalysis | 이동 |
| **src/filter/** | | |
| `src/filter/__init__.py` | - | 유지 |
| `src/filter/rule_filter.py` | FN.1 RuleFilter | 이동 |
| `src/filter/similarity_checker.py` | FN.2 SimilarityChecker | 이동 |
| **src/indicators/** | | |
| `src/indicators/__init__.py` | - | 유지 |
| `src/indicators/aggregator.py` | F3.4 IndicatorAggregator | 이동 |
| `src/indicators/calculator.py` | F3.2 TechnicalCalculator | 이동 |
| `src/indicators/contango_detector.py` | F3.11 ContangoDetector | 이동 |
| `src/indicators/cross_asset/__init__.py` | - | 유지 |
| `src/indicators/cross_asset/divergence_detector.py` | F3.7 CrossAssetMomentum | 이동 |
| `src/indicators/cross_asset/leader_aggregator.py` | F3.7 CrossAssetMomentum | 이동 |
| `src/indicators/cross_asset/leader_map.py` | F3.7 CrossAssetMomentum | 이동 |
| `src/indicators/cross_asset/models.py` | F3.7 CrossAssetMomentum | 이동 |
| `src/indicators/cross_asset/momentum_scorer.py` | F3.7 CrossAssetMomentum | 이동 |
| `src/indicators/data_fetcher.py` | F3.1 PriceDataFetcher | 이동 |
| `src/indicators/history_analyzer.py` | F3.3 HistoryAnalyzer | 이동 |
| `src/indicators/intraday_calculator.py` | F3.6 IntradayCalculator | 이동 |
| `src/indicators/intraday_fetcher.py` | F3.5 IntradayFetcher | 이동 |
| `src/indicators/intraday_macd.py` | F3.6 IntradayCalculator (통합) | 통합 |
| `src/indicators/leverage_decay.py` | F3.14 LeverageDecay | 이동 |
| `src/indicators/macd_divergence.py` (713줄) | F3.10 MACDDivergence | 분리 |
| `src/indicators/nav_premium.py` | F3.12 NAVPremiumTracker | 이동 |
| `src/indicators/order_flow_aggregator.py` | F3.13 OrderFlowAggregator | 이동 |
| `src/indicators/volume_profile/__init__.py` | - | 유지 |
| `src/indicators/volume_profile/accumulator.py` | F3.8 VolumeProfile | 이동 |
| `src/indicators/volume_profile/calculator.py` | F3.8 VolumeProfile | 이동 |
| `src/indicators/volume_profile/config.py` | F3.8 VolumeProfile | 이동 |
| `src/indicators/volume_profile/models.py` | F3.8 VolumeProfile | 이동 |
| `src/indicators/volume_profile/redis_feeder.py` | F3.8 VolumeProfile | 이동 |
| `src/indicators/volume_profile/signal_generator.py` | F3.8 VolumeProfile | 이동 |
| `src/indicators/weights.py` | F3.4 IndicatorAggregator | 통합 |
| `src/indicators/whale/__init__.py` | - | 유지 |
| `src/indicators/whale/block_detector.py` | F3.9 WhaleTracker | 이동 |
| `src/indicators/whale/iceberg_detector.py` | F3.9 WhaleTracker | 이동 |
| `src/indicators/whale/models.py` | F3.9 WhaleTracker | 이동 |
| `src/indicators/whale/whale_scorer.py` | F3.9 WhaleTracker | 이동 |
| **src/macro/** | | |
| `src/macro/__init__.py` | - | 유지 |
| `src/macro/net_liquidity.py` (575줄) | F6.19 NetLiquidityTracker | 이동 |
| **src/monitoring/** | | |
| `src/monitoring/__init__.py` | - | 유지 |
| `src/monitoring/account_mode.py` | F5.6 AccountModeManager | 이동 |
| `src/monitoring/agent_endpoints.py` | F7.14 AgentEndpoints | 이동 |
| `src/monitoring/alert.py` | F7.2 DashboardEndpoints (alert) | 통합 |
| `src/monitoring/analysis_endpoints.py` (918줄) | F7.3 AnalysisEndpoints | 분리 |
| `src/monitoring/api_server.py` (666줄) | F7.1 ApiServer | 분리 |
| `src/monitoring/auth.py` | F7.21 AuthMiddleware | 이동 |
| `src/monitoring/benchmark.py` (421줄) | F7.9 BenchmarkEndpoints | 이동 |
| `src/monitoring/benchmark_endpoints.py` (393줄) | F7.9 BenchmarkEndpoints | 통합 |
| `src/monitoring/calendar_helpers.py` | C0.11 MarketClock | 통합 |
| `src/monitoring/daily_report.py` | F7.19 TelegramNotifier | 통합 |
| `src/monitoring/dashboard_endpoints.py` (1,840줄) | F7.2 DashboardEndpoints (8개 라우터) | 분리 |
| `src/monitoring/emergency_endpoints.py` (491줄) | F7.8 EmergencyEndpoints | 분리 |
| `src/monitoring/fred_client.py` (674줄) | F7.20 IndicatorCrawler | 통합 |
| `src/monitoring/indicator_crawler.py` (661줄) | F7.20 IndicatorCrawler | 이동 |
| `src/monitoring/indicator_endpoints.py` | F7.11 IndicatorEndpoints | 이동 |
| `src/monitoring/live_readiness.py` | F7.15 SystemEndpoints | 통합 |
| `src/monitoring/macro_endpoints.py` (569줄) | F7.5 MacroEndpoints | 분리 |
| `src/monitoring/manual_trade_endpoints.py` | F7.12 ManualTradeEndpoints | 이동 |
| `src/monitoring/news_collect_endpoints.py` (330줄) | F7.6 NewsEndpoints | 통합 |
| `src/monitoring/news_endpoints.py` (419줄) | F7.6 NewsEndpoints | 통합 |
| `src/monitoring/order_flow_endpoints.py` | F7.17 OrderFlowEndpoints | 이동 |
| `src/monitoring/performance_endpoints.py` | F7.16 PerformanceEndpoints | 이동 |
| `src/monitoring/principles_endpoints.py` | F7.13 PrinciplesEndpoints | 이동 |
| `src/monitoring/realtime_tape.py` | F7.18 WebSocketManager | 이동 |
| `src/monitoring/schemas.py` | F7.22 Schemas | 이동 |
| `src/monitoring/system_endpoints.py` | F7.15 SystemEndpoints | 이동 |
| `src/monitoring/telegram_notifier.py` (717줄) | C0.7 TelegramGateway + F7.19 TelegramNotifier | 분리 |
| `src/monitoring/trade_endpoints.py` | F7.2 DashboardEndpoints (trade) | 통합 |
| `src/monitoring/trade_reasoning_endpoints.py` (522줄) | F7.10 TradeReasoningEndpoints | 이동 |
| `src/monitoring/trading_control_endpoints.py` | F7.4 TradingControlEndpoints | 이동 |
| `src/monitoring/universe_endpoints.py` (1,048줄) | F7.7 UniverseEndpoints | 분리 |
| **src/optimization/** | | |
| `src/optimization/__init__.py` | - | 유지 |
| `src/optimization/auto_trainer.py` | F8.7 AutoTrainer | 이동 |
| `src/optimization/config.py` | F8 schema | 이동 |
| `src/optimization/data_preparer.py` | F8.1 DataPreparer | 이동 |
| `src/optimization/feature_engineer.py` | F8.2 FeatureEngineer | 이동 |
| `src/optimization/lgbm_trainer.py` | F8.4 LGBMTrainer | 이동 |
| `src/optimization/models.py` | F8 schema | 이동 |
| `src/optimization/optuna_optimizer.py` | F8.5 OptunaOptimizer | 이동 |
| `src/optimization/target_builder.py` | F8.3 TargetBuilder | 이동 |
| `src/optimization/time_travel.py` | F8.8 TimeTravelTrainer | 이동 |
| `src/optimization/walk_forward.py` | F8.6 WalkForward | 이동 |
| **src/orchestration/** | | |
| `src/orchestration/__init__.py` | - | 유지 |
| `src/orchestration/continuous_analysis.py` | F9.5 ContinuousAnalysisLoop | 이동 |
| `src/orchestration/news_pipeline.py` | F9.6 NewsPipeline | 이동 |
| `src/orchestration/preparation.py` | F9.3 PreparationPhase | 이동 |
| `src/orchestration/trading_loop.py` | F9.4 TradingLoop | 이동 |
| **src/psychology/** | | |
| `src/psychology/__init__.py` | - | 유지 |
| `src/psychology/config.py` | F6.8 TiltDetector | 통합 |
| `src/psychology/loss_tracker.py` | F6.8 TiltDetector | 통합 |
| `src/psychology/models.py` | F6.8 TiltDetector | 통합 |
| `src/psychology/tilt_detector.py` | F6.8 TiltDetector | 통합 |
| `src/psychology/tilt_enforcer.py` | F6.8 TiltDetector | 통합 |
| **src/rag/** | | |
| `src/rag/__init__.py` | - | 유지 |
| `src/rag/doc_generator.py` | F8.10 KnowledgeManager | 통합 |
| `src/rag/doc_manager.py` | F8.10 KnowledgeManager | 통합 |
| `src/rag/embedder.py` | F8.10 KnowledgeManager | 통합 |
| `src/rag/retriever.py` | F8.10 KnowledgeManager | 통합 |
| **src/risk/** | | |
| `src/risk/__init__.py` | - | 유지 |
| `src/risk/concentration.py` | F6.7 ConcentrationLimiter | 이동 |
| `src/risk/daily_loss_limit.py` | F6.6 DailyLossLimiter | 이동 |
| `src/risk/friction/__init__.py` | - | 유지 |
| `src/risk/friction/config.py` | F6.15 FrictionCalculator | 이동 |
| `src/risk/friction/hurdle_calculator.py` | F6.15 FrictionCalculator | 이동 |
| `src/risk/friction/models.py` | F6.15 FrictionCalculator | 이동 |
| `src/risk/friction/slippage_cost.py` | F6.15 FrictionCalculator | 이동 |
| `src/risk/friction/spread_cost.py` | F6.15 FrictionCalculator | 이동 |
| `src/risk/gap_risk.py` | F6.14 GapRiskProtector | 이동 |
| `src/risk/house_money/__init__.py` | - | 유지 |
| `src/risk/house_money/config.py` | F6.16 HouseMoneyMultiplier | 이동 |
| `src/risk/house_money/daily_pnl_tracker.py` | F6.16 HouseMoneyMultiplier | 이동 |
| `src/risk/house_money/models.py` | F6.16 HouseMoneyMultiplier | 이동 |
| `src/risk/house_money/multiplier_engine.py` | F6.16 HouseMoneyMultiplier | 이동 |
| `src/risk/losing_streak.py` | F6.20 LosingStreakDetector | 이동 |
| `src/risk/risk_backtester.py` | F4.12 Backtester (통합) | 통합 |
| `src/risk/risk_budget.py` | F6.10 RiskBudget | 이동 |
| `src/risk/risk_gate.py` | F6.5 RiskGatePipeline | 이동 |
| `src/risk/sector_correlation.py` | F6.5 RiskGatePipeline (Gate 5) | 통합 |
| `src/risk/simple_var.py` | F6.9 SimpleVaR | 이동 |
| `src/risk/stop_loss.py` | F6.11 StopLossManager | 이동 |
| **src/safety/** | | |
| `src/safety/__init__.py` | - | 유지 |
| `src/safety/account_safety.py` | F6.17 AccountSafety | 이동 |
| `src/safety/capital_guard.py` | F6.4 CapitalGuard | 이동 |
| `src/safety/deadman_switch.py` | F6.12 DeadmanSwitch | 이동 |
| `src/safety/emergency_protocol.py` (704줄) | F6.3 EmergencyProtocol | 분리 |
| `src/safety/hard_safety.py` | F6.1 HardSafety | 이동 |
| `src/safety/macro_flash_crash.py` | F6.13 MacroFlashCrash | 이동 |
| `src/safety/quota_guard.py` | F6.18 QuotaGuard | 이동 |
| `src/safety/safety_checker.py` | F6.2 SafetyChecker | 이동 |
| **src/scalping/** | | |
| `src/scalping/__init__.py` | - | 유지 |
| `src/scalping/config.py` | FS.1 ScalpingManager | 통합 |
| `src/scalping/liquidity/__init__.py` | - | 유지 |
| `src/scalping/liquidity/depth_analyzer.py` | FS.2 DepthAnalyzer | 이동 |
| `src/scalping/liquidity/impact_estimator.py` | FS.3 ImpactEstimator | 이동 |
| `src/scalping/liquidity/sizer.py` | FS.5 LiquiditySizer | 이동 |
| `src/scalping/liquidity/spread_monitor.py` | FS.4 SpreadMonitor | 이동 |
| `src/scalping/manager.py` (537줄) | FS.1 ScalpingManager | 분리 |
| `src/scalping/models.py` | FS schema | 이동 |
| `src/scalping/spoofing/__init__.py` | - | 유지 |
| `src/scalping/spoofing/pattern_detector.py` | FS.6 SpoofingDetector | 이동 |
| `src/scalping/spoofing/snapshot_tracker.py` | FS.6 SpoofingDetector | 이동 |
| `src/scalping/spoofing/toxicity_scorer.py` | FS.6 SpoofingDetector | 이동 |
| `src/scalping/spoofing/trade_lock.py` | FS.6 SpoofingDetector | 이동 |
| `src/scalping/time_stop/__init__.py` | - | 유지 |
| `src/scalping/time_stop/evaluator.py` | FS.7 TimeStopManager | 이동 |
| `src/scalping/time_stop/executor.py` | FS.7 TimeStopManager | 이동 |
| `src/scalping/time_stop/timer.py` | FS.7 TimeStopManager | 이동 |
| **src/strategy/** | | |
| `src/strategy/__init__.py` | - | 유지 |
| `src/strategy/backtester.py` (1,324줄) | F4.12 Backtester | 분리 |
| `src/strategy/beast_mode/__init__.py` | - | 유지 |
| `src/strategy/beast_mode/beast_exit.py` | F4.3 BeastMode | 이동 |
| `src/strategy/beast_mode/config.py` | F4.3 BeastMode | 이동 |
| `src/strategy/beast_mode/conviction_sizer.py` | F4.3 BeastMode | 이동 |
| `src/strategy/beast_mode/detector.py` | F4.3 BeastMode | 이동 |
| `src/strategy/beast_mode/models.py` | F4.3 BeastMode | 이동 |
| `src/strategy/entry_strategy.py` (1,450줄) | F4.1 EntryStrategy | 분리 |
| `src/strategy/etf_universe.py` (888줄) | C0.12 TickerRegistry | 이동 |
| `src/strategy/exit_strategy.py` (1,517줄) | F4.2 ExitStrategy | 분리 |
| `src/strategy/micro_regime/__init__.py` | - | 유지 |
| `src/strategy/micro_regime/config.py` | F4.6 MicroRegime | 이동 |
| `src/strategy/micro_regime/models.py` | F4.6 MicroRegime | 이동 |
| `src/strategy/micro_regime/regime_classifier.py` | F4.6 MicroRegime | 이동 |
| `src/strategy/micro_regime/trend_detector.py` | F4.6 MicroRegime | 이동 |
| `src/strategy/micro_regime/volatility_analyzer.py` | F4.6 MicroRegime | 이동 |
| `src/strategy/news_fading/__init__.py` | - | 유지 |
| `src/strategy/news_fading/config.py` | F4.7 NewsFading | 이동 |
| `src/strategy/news_fading/decay_analyzer.py` | F4.7 NewsFading | 이동 |
| `src/strategy/news_fading/fade_signal_generator.py` | F4.7 NewsFading | 이동 |
| `src/strategy/news_fading/models.py` | F4.7 NewsFading | 이동 |
| `src/strategy/news_fading/spike_detector.py` | F4.7 NewsFading | 이동 |
| `src/strategy/params.py` | F4.10 StrategyParams | 이동 |
| `src/strategy/profit_target.py` (620줄) | F4.13 ProfitTarget | 분리 |
| `src/strategy/pyramiding.py` (632줄) | F4.4 Pyramiding | 분리 |
| `src/strategy/sector_rotation.py` | F4.9 SectorRotation | 이동 |
| `src/strategy/stat_arb/__init__.py` | - | 유지 |
| `src/strategy/stat_arb/config.py` | F4.5 StatArb | 이동 |
| `src/strategy/stat_arb/models.py` | F4.5 StatArb | 이동 |
| `src/strategy/stat_arb/pair_monitor.py` | F4.5 StatArb | 이동 |
| `src/strategy/stat_arb/signal_generator.py` | F4.5 StatArb | 이동 |
| `src/strategy/stat_arb/spread_calculator.py` | F4.5 StatArb | 이동 |
| `src/strategy/ticker_params.py` (673줄) | F4.11 TickerParams | 분리 |
| `src/strategy/wick_catcher/__init__.py` | - | 유지 |
| `src/strategy/wick_catcher/activation_checker.py` | F4.8 WickCatcher | 이동 |
| `src/strategy/wick_catcher/bounce_exit.py` | F4.8 WickCatcher | 이동 |
| `src/strategy/wick_catcher/config.py` | F4.8 WickCatcher | 이동 |
| `src/strategy/wick_catcher/models.py` | F4.8 WickCatcher | 이동 |
| `src/strategy/wick_catcher/order_placer.py` | F4.8 WickCatcher | 이동 |
| **src/tax/** | | |
| `src/tax/__init__.py` | - | 유지 |
| `src/tax/fx_manager.py` | FX.2 FxManager | 이동 |
| `src/tax/slippage_tracker.py` | FX.3 SlippageTracker | 이동 |
| `src/tax/tax_tracker.py` | FX.1 TaxTracker | 이동 |
| **src/telegram/** | | |
| `src/telegram/__init__.py` | - | 유지 |
| `src/telegram/bot_handler.py` (621줄) | FT.1 BotHandler | 분리 |
| `src/telegram/commands.py` | FT.2 CommandProcessor | 이동 |
| `src/telegram/formatters.py` | FT.4 MessageFormatter | 이동 |
| `src/telegram/nl_processor.py` | FT.5 NLProcessor | 이동 |
| `src/telegram/permissions.py` | FT.6 Permissions | 이동 |
| `src/telegram/trade_commands.py` | FT.3 TradeCommands | 이동 |
| **src/utils/** | | |
| `src/utils/__init__.py` | - | 유지 |
| `src/utils/config.py` | C0.1 SecretVault | 이동 |
| `src/utils/logger.py` | C0.8 Logger | 이동 |
| `src/utils/market_hours.py` (692줄) | C0.11 MarketClock | 분리 |
| `src/utils/ticker_mapping.py` | C0.12 TickerRegistry | 통합 |
| **src/websocket/** | | |
| `src/websocket/__init__.py` | - | 유지 |
| `src/websocket/auth.py` | FW.1 WebSocketConnection | 통합 |
| `src/websocket/config.py` | FW.1 WebSocketConnection | 통합 |
| `src/websocket/connection.py` | FW.1 WebSocketConnection | 이동 |
| `src/websocket/crypto.py` | FW.1 WebSocketConnection | 통합 |
| `src/websocket/handlers/__init__.py` | - | 유지 |
| `src/websocket/handlers/base.py` | FW schema | 이동 |
| `src/websocket/handlers/notice_handler.py` | FW.5 NoticeHandler | 이동 |
| `src/websocket/handlers/orderbook_handler.py` | FW.4 OrderbookHandler | 이동 |
| `src/websocket/handlers/trade_handler.py` | FW.3 TradeHandler | 이동 |
| `src/websocket/indicators/__init__.py` | - | 유지 |
| `src/websocket/indicators/cvd.py` | FW.8 CVDCalculator | 이동 |
| `src/websocket/indicators/execution_strength.py` | FW.9 ExecutionStrength | 이동 |
| `src/websocket/indicators/obi.py` | FW.6 OBICalculator | 이동 |
| `src/websocket/indicators/vpin.py` | FW.7 VPINCalculator | 이동 |
| `src/websocket/manager.py` | FW.13 WebSocketManager | 이동 |
| `src/websocket/models.py` | FW schema | 이동 |
| `src/websocket/parser.py` | FW.2 MessageParser | 이동 |
| `src/websocket/storage/__init__.py` | - | 유지 |
| `src/websocket/storage/redis_publisher.py` | FW.11 RedisPublisher | 이동 |
| `src/websocket/storage/tick_writer.py` | FW.10 TickWriter | 이동 |
| `src/websocket/subscriber.py` | FW.12 WebSocketSubscriber | 이동 |

### 6.2 Dart 파일 매핑 (dashboard/lib/)

| 현재 파일 | 새 모듈 ID | 상태 |
|---|---|---|
| `main.dart` | F10 엔트리포인트 | 유지 |
| `app.dart` | F10 앱 루트 | 유지 |
| **services/** | | |
| `services/api_service.dart` (1,544줄) | F10.1 ApiClient (11개 파일) | 분리 |
| `services/websocket_service.dart` | F10.2 WebSocketClient | 유지 |
| `services/server_launcher.dart` | F10 유틸 | 유지 |
| **providers/ (26개)** | | |
| `providers/dashboard_provider.dart` | F10.3 DashboardProvider | 유지 |
| `providers/trading_control_provider.dart` | F10.3 TradingControlProvider | 유지 |
| `providers/news_provider.dart` | F10.3 NewsProvider | 유지 |
| `providers/universe_provider.dart` | F10.3 UniverseProvider | 유지 |
| `providers/emergency_provider.dart` | F10.3 EmergencyProvider | 유지 |
| `providers/macro_provider.dart` | F10.3 MacroProvider | 유지 |
| `providers/benchmark_provider.dart` | F10.3 BenchmarkProvider | 유지 |
| `providers/chart_provider.dart` | F10.3 ChartProvider | 유지 |
| `providers/risk_provider.dart` | F10.3 RiskProvider | 유지 |
| `providers/trade_provider.dart` | F10.3 TradeProvider | 유지 |
| `providers/trade_reasoning_provider.dart` | F10.3 TradeReasoningProvider | 유지 |
| `providers/stock_analysis_provider.dart` | F10.3 StockAnalysisProvider | 유지 |
| `providers/indicator_provider.dart` | F10.3 IndicatorProvider | 유지 |
| `providers/agent_provider.dart` | F10.3 AgentProvider | 유지 |
| `providers/principles_provider.dart` | F10.3 PrinciplesProvider | 유지 |
| `providers/settings_provider.dart` | F10.3 SettingsProvider | 유지 |
| `providers/theme_provider.dart` | F10.3 ThemeProvider | 유지 |
| `providers/locale_provider.dart` | F10.3 LocaleProvider | 유지 |
| `providers/navigation_provider.dart` | F10.3 NavigationProvider | 유지 |
| `providers/tax_fx_provider.dart` | F10.3 TaxFxProvider | 유지 |
| `providers/profit_target_provider.dart` | F10.3 ProfitTargetProvider | 유지 |
| `providers/report_provider.dart` | F10.3 ReportProvider | 유지 |
| `providers/scalper_tape_provider.dart` | F10.3 ScalperTapeProvider | 유지 |
| `providers/manual_trade_provider.dart` | F10.3 ManualTradeProvider | 유지 |
| `providers/crawl_progress_provider.dart` | F10.3 CrawlProgressProvider | 유지 |
| `providers/trading_mode_provider.dart` | F10.3 TradingModeProvider | 유지 |
| **screens/ (28개)** | | |
| 28개 스크린 파일 | F10.4 Screens | 각 파일 150줄 이하로 위젯 추출 |
| **models/ (22개)** | | |
| 22개 모델 파일 | F10.5 Models | Color 참조 제거 (4개 파일) |
| **widgets/ (30개)** | | |
| 30개 위젯 파일 | F10.6 Widgets | 유지 |
| **theme/ (7개)** | | |
| 7개 테마 파일 | F10.7 Theme | 유지 |
| **기타** | | |
| `constants/api_constants.dart` | F10 상수 | 유지 |
| `l10n/app_strings.dart` | F10 다국어 | 유지 |
| `utils/env_loader.dart` | F10 유틸 | 유지 |
| `animations/animation_utils.dart` | F10.6 위젯 | 유지 |

### 6.4 Scripts 매핑

| 현재 파일 | 조치 | 비고 |
|---|---|---|
| `scripts/auto_trading.sh` | **삭제** | LaunchAgent용 -- 대시보드 버튼 시작으로 대체 |
| `scripts/com.trading.autotrader.plist` | **삭제** | LaunchAgent plist -- 불필요 |
| `scripts/install_launchagent.sh` | **삭제** | LaunchAgent 설치 스크립트 -- 불필요 |
| `scripts/launchagent_setup.py` | **삭제** | LaunchAgent 설정 Python -- 불필요 |
| `scripts/start_dashboard.py` | **수정** | API 서버 URL, 포트 등 v2 설정 반영 |
| `scripts/start_api.sh` | **수정** | uvicorn 실행 경로를 f7_monitoring 기준으로 변경 |
| `scripts/download_fallback_model.py` | **유지** | MLX 모델 다운로드 -- 변경 불필요 |
| `scripts/run_trading_system.sh` | **수정** | 엔트리포인트를 새 main.py(50줄) 경로로 변경 |
| `scripts/test_real_balance.py` | **유지** | KIS 잔고 테스트 유틸 -- 변경 불필요 |

> LaunchAgent 관련 4개 파일은 v2에서 대시보드 버튼 수동 시작 방식으로 완전 대체되므로 삭제한다.

### 6.5 통계 요약

| 구분 | 현재 | 목표 |
|---|---|---|
| Python 파일 | 292개 | ~200개 (통합으로 감소) |
| Dart 파일 | 121개 | ~130개 (API 클라이언트 분리로 증가) |
| 1000줄+ 파일 | 10개 | 0개 |
| 500줄+ 파일 | 39개 | 0개 |
| 200줄+ 파일 | 159개 | 0개 |
| main.py 줄 수 | 3,255 | 50줄 이하 |
| Lazy import | 168개 | 0개 |
| Cross-layer 위반 | 4개 | 0개 |
| os.environ 직접 접근 | 다수 | 0개 (SecretVault 독점) |
| Feature 간 직접 호출 | 다수 | 0개 (EventBus 전환) |

---

## 7. 설계 검증 체크리스트

각 모듈 구현 완료 후 아래 항목을 검증한다.

- [ ] 모든 모듈의 OUT이 정확히 1개인가?
- [ ] SecretVault 외에 os.environ/os.getenv 호출이 없는가?
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
- [ ] 매매 윈도우가 20:00~06:30 KST로 올바르게 구현되어 있는가?
- [ ] LaunchAgent 참조가 모두 제거되었는가?
- [ ] 대시보드 버튼 -> 시간 체크 -> 매매 시작 플로우가 올바른가?

---

*이 문서는 Stock Trading AI System V2 리팩토링의 최종 설계 기준이다. 모든 구현은 이 문서의 모듈 ID, IN/OUT 계약, 파이프라인을 준수한다.*
