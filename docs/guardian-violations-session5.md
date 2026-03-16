# Guardian Violation Report -- Session 5 (SQLite/In-Memory Migration)

> 작성일: 2026-03-15
> 감사 범위: Step 1 -- PostgreSQL→SQLite + Redis→인메모리 dict 전환
> 목적: 마이그레이션 진행 상황 모니터링 + 규칙 준수 검증

---

## 1. 마이그레이션 진행 상황 (초기 스캔)

### 완료된 작업
| 파일 | 변경 내용 | 상태 |
|---|---|---|
| `src/db/models.py` | `func.now()` → `text("(datetime('now'))")`, `postgresql.JSON` → 범용 `JSON`, docstring 갱신 | **완료** |

### 미완료 작업 (감시 대상)
| 파일 | 필요 변경 | 상태 |
|---|---|---|
| `src/common/database_gateway.py` | asyncpg→aiosqlite, pool 설정 제거, WAL 모드 | **미착수** |
| `src/common/cache_gateway.py` | redis→dict+Lock, Pub/Sub 대체 | **미착수** |
| `src/common/secret_vault.py` | DATABASE_URL/REDIS_URL 필수 키 변경 | **미착수** |
| `src/orchestration/init/system_initializer.py` | DB/cache 초기화 로직 변경 | **미착수** |
| `src/orchestration/phases/preparation.py` | `_client.ping()` 제거 | **미착수** |
| `alembic/env.py` | PostgreSQL→SQLite 전환 | **미착수** |
| `alembic/versions/` | postgresql 방언 제거 또는 SQLite용 신규 생성 | **미착수** |
| `docker-compose.yml` | 제거 또는 보관 처리 | **미착수** |
| `scripts/` | 마이그레이션 스크립트 | **미착수** |

---

## 2. 현재 발견된 위반 사항

### [VIOLATION-S5-001] 심각도: P1 -- models.py 변경과 database_gateway.py 불일치

- **발견 위치**: `src/db/models.py` ↔ `src/common/database_gateway.py`
- **위반 유형**: 중간 상태 불일치 -- 부분 마이그레이션으로 인한 런타임 실패 위험
- **위반 상세**:
  - `models.py`는 이미 SQLite 문법으로 변경됨 (`text("(datetime('now'))")`, 범용 `JSON`)
  - `database_gateway.py`는 여전히 asyncpg 드라이버 + PostgreSQL 전용 설정 사용
  - 현재 상태로는 models.py의 server_default가 PostgreSQL 엔진에서 오류 발생 가능
  - `(datetime('now'))`는 SQLite 전용 함수이다. PostgreSQL에서는 `now()`를 사용해야 한다.
- **영향**: 시스템 시작 시 CREATE TABLE이나 INSERT에서 `datetime('now')` 함수 미인식 오류 발생 가능
- **수정 방안**: database_gateway.py의 SQLite 전환을 models.py와 함께 완료해야 한다. 또는 models.py를 원복하고 gateway 전환 후 동시에 적용해야 한다.
- **상태**: **OPEN** -- 마이그레이션 작업이 진행 중이므로 과도기적 상태로 인정하되, Step 1 완료 시까지 반드시 해결 필요

---

### [VIOLATION-S5-002] 심각도: P1 -- preparation.py의 Redis 내부 API 직접 접근

- **발견 위치**: `src/orchestration/phases/preparation.py:57`
- **위반 유형**: 추상화 위반 -- CacheClient 공개 인터페이스 외부의 내부 속성 접근
- **위반 상세**:
  ```python
  redis_ok = bool(await system.components.cache._client.ping())
  ```
  - `_client`는 private 속성 (언더스코어 접두사)이다
  - 인메모리 dict 전환 시 `_client` 속성이 존재하지 않아 AttributeError 발생
  - CacheClient에 `ping()` 또는 `health_check()` public 메서드를 추가해야 한다
- **수정 방안**: CacheClient에 `async def ping(self) -> bool` public 메서드를 추가하고, preparation.py에서 `cache.ping()` 호출로 변경
- **상태**: **OPEN**

---

### [VIOLATION-S5-003] 심각도: P2 -- Alembic 마이그레이션 파일의 PostgreSQL 방언 잔존

- **발견 위치**: `alembic/versions/0001_v2_clean_initial_schema.py`, `alembic/env.py`
- **위반 유형**: 마이그레이션 인프라 미전환
- **위반 상세**:
  - `0001_*.py:16`: `from sqlalchemy.dialects import postgresql`
  - `0001_*.py:106,152,444,445,511`: `postgresql.JSON(astext_type=...)` 사용
  - `alembic/env.py:39`: `postgresql+asyncpg://` URL 하드코딩
  - `alembic/env.py:42`: `asyncpg → psycopg2` 변환 로직 (SQLite에서는 불필요)
  - Alembic이 SQLite를 대상으로 동작하도록 전면 재구성 필요
- **수정 방안**: 
  1. env.py를 SQLite용으로 변경 (aiosqlite → 동기 sqlite3)
  2. 기존 마이그레이션 파일을 SQLite 호환으로 갱신하거나 신규 초기 마이그레이션 생성
- **상태**: **OPEN**

---

### [VIOLATION-S5-004] 심각도: P2 -- secret_vault.py의 불필요 필수 키 요구

- **발견 위치**: `src/common/secret_vault.py:18,52-69`
- **위반 유형**: 불필요한 의존성 -- SQLite 전환 후 DATABASE_URL/REDIS_URL 불필요
- **위반 상세**:
  - `_REQUIRED_KEYS`: `["DATABASE_URL", "REDIS_URL", "TELEGRAM_BOT_TOKEN"]` -- SQLite 전환 후 DATABASE_URL/REDIS_URL은 불필요
  - `_build_composite_secrets()`: PostgreSQL URL과 Redis URL 자동 생성 로직이 잔존
  - SQLite는 파일 경로만 필요하고, Redis는 완전히 제거되므로 이 로직이 무의미해진다
- **수정 방안**: _REQUIRED_KEYS에서 DATABASE_URL/REDIS_URL 제거, SQLite 파일 경로 설정으로 대체
- **상태**: **OPEN**

---

### [VIOLATION-S5-005] 심각도: P2 -- cache_gateway.py의 Lua 스크립트 (atomic_list_append)

- **발견 위치**: `src/common/cache_gateway.py:78-128`
- **위반 유형**: Redis 전용 기능 -- 인메모리 dict 전환 시 대체 구현 필요
- **위반 상세**:
  - `atomic_list_append()`는 Redis Lua 스크립트를 사용하여 원자적 리스트 추가를 구현
  - 인메모리 dict에서는 asyncio.Lock으로 원자성을 보장해야 한다
  - Pub/Sub (`publish`, `subscribe`)도 Redis 전용 기능이다 -- asyncio.Queue 또는 in-process 이벤트 버스로 대체 필요
- **수정 방안**: 인메모리 구현에서 Lock 기반 atomic append + asyncio 기반 Pub/Sub 구현
- **상태**: **OPEN**

---

### [VIOLATION-S5-006] 심각도: P3 -- 문서/코멘트의 "PostgreSQL" 참조 잔존

- **발견 위치**: 다수 파일
- **위반 유형**: 코드 위생 -- 변경된 아키텍처와 문서 불일치
- **위반 상세**: 다음 파일에서 "PostgreSQL" 참조가 남아있다:
  - `database_gateway.py:1-6,49,92,95` (docstring)
  - `secret_vault.py:60` (URL 조합 함수)
  - `universe_persister.py:23` (docstring)
  - `system.py:80,115` (엔드포인트 설명)
  - `article_persister.py:1` (모듈 docstring)
  - `agents/docs/`: 6개 문서에서 "PostgreSQL" 언급
- **수정 방안**: 모든 참조를 "SQLite"로 갱신 (Step 1 완료 시 일괄 처리)
- **상태**: **OPEN** (P3, Step 1 완료 시 일괄 처리)

---

### [VIOLATION-S5-007] 심각도: P2 -- websocket/redis_publisher.py의 Redis Pub/Sub 직접 사용

- **발견 위치**: `src/websocket/storage/redis_publisher.py:96,115`
- **위반 유형**: Redis 전용 기능 의존
- **위반 상세**:
  - WebSocket 서버가 Redis Pub/Sub를 통해 실시간 데이터를 브로드캐스트
  - 인메모리 dict 전환 시 Pub/Sub 채널이 존재하지 않음
  - 단일 프로세스 구조이므로 asyncio 기반 내부 이벤트 버스로 대체 가능
- **수정 방안**: CacheClient에 인메모리 Pub/Sub 구현 (asyncio.Queue 기반) 또는 EventBus 재활용
- **상태**: **OPEN**

---

## 3. 기존 위반 캐리오버 (Session 3+4 → Session 5)

| 이전 위반 | 심각도 | 상태 | 비고 |
|---|---|---|---|
| P2-007 type: ignore DI 패턴 | P2 | ACCEPTED | 아키텍처 한계, 변경 없음 |
| P2-011 파일 크기 200줄 초과 | P2 | PARTIALLY RESOLVED | 모델 분리 완료, 나머지 로직 크기 |
| V1-001~010 수정 사항 | -- | VERIFIED | 리그레션 없음 확인 필요 |

---

## 4. CLAUDE.md 규칙 준수 상태 (Step 1 시작 시점)

| 규칙 | 상태 | 비고 |
|---|---|---|
| 한국어 주석/독스트링 | **PASS** | models.py 변경 시 한국어 docstring 유지 확인 |
| Python 타입 힌트 | **PASS** | models.py 변경에 타입 힌트 포함됨 |
| No Workarounds | **PASS** | 신규 noqa/ts-ignore 추가 없음 |
| SRP / 파일 크기 | **PARTIAL** | 기존 초과 파일 유지 (캐리오버) |
| async/await | **PENDING** | 인메모리 캐시 구현 시 async 패턴 유지 확인 필요 |
| from __future__ import annotations | **PENDING** | 신규 파일 생성 시 확인 필요 |

---

## 5. 즉시 리더에게 전달할 사항

### [GUARDIAN CORRECTION - P1]
- **대상 에이전트**: backend-db
- **위반**: models.py가 SQLite 문법으로 변경되었으나 database_gateway.py는 여전히 PostgreSQL asyncpg 드라이버 사용 -- 중간 상태 불일치
- **원래 요구사항**: "PostgreSQL → SQLite: aiosqlite 드라이버, WAL 모드, Docker 완전 제거"
- **수정 지시**: database_gateway.py와 models.py를 동시에 전환해야 한다. 현재 중간 상태에서는 시스템이 부팅 불가하다. models.py의 `datetime('now')`는 SQLite 전용이므로, gateway가 아직 PostgreSQL이면 서버 시작 시 오류가 발생한다.
- **기한**: Step 1 완료 전 (즉시)

### [GUARDIAN CORRECTION - P1]
- **대상 에이전트**: backend-db
- **위반**: preparation.py:57에서 `cache._client.ping()` private 속성 직접 접근 -- 인메모리 전환 시 AttributeError
- **원래 요구사항**: "Redis → 인메모리 dict: Python dict + asyncio.Lock으로 Redis 대체"
- **수정 지시**: CacheClient에 `async def ping(self) -> bool` public 메서드를 추가하고, preparation.py에서 `await system.components.cache.ping()`으로 변경할 것
- **기한**: cache_gateway 전환 시 함께 처리

---

## 6. Step 1 완료 체크리스트

- [ ] database_gateway.py: aiosqlite 드라이버로 전환, WAL 모드 설정
- [ ] cache_gateway.py: 인메모리 dict + asyncio.Lock으로 전환
- [ ] cache_gateway.py: Pub/Sub를 asyncio 기반으로 대체
- [ ] cache_gateway.py: atomic_list_append를 Lock 기반으로 대체
- [ ] cache_gateway.py: ping() public 메서드 추가
- [ ] secret_vault.py: DATABASE_URL/REDIS_URL 필수 키 제거/변경
- [ ] system_initializer.py: DB/cache 초기화 로직 변경
- [ ] preparation.py: `_client.ping()` → `cache.ping()` 변경
- [ ] preparation.py: 인프라 건강 검사에서 Redis 검사 제거/변경
- [ ] alembic/env.py: SQLite용으로 재구성
- [ ] models.py ↔ gateway 일관성 확인
- [ ] 마이그레이션 스크립트 생성 (PostgreSQL → SQLite 데이터 이관)
- [ ] docker-compose.yml 보관/제거 처리
- [ ] 모든 `cache._client` 직접 접근 제거
- [ ] websocket/redis_publisher.py Pub/Sub 대체
- [ ] 한국어 docstring 유지 확인
- [ ] async/await 패턴 유지 확인
- [ ] from __future__ import annotations 포함 확인
- [ ] try/except + logging 패턴 유지 확인
- [ ] 시스템 부팅 테스트 통과
- [ ] 기존 V1 수정사항 리그레션 없음 확인
