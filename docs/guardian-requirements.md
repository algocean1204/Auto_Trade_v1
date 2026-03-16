# Guardian Requirements Log -- Session 5 (SQLite/In-Memory Migration)

## User Original Requirements (전문)
사용자는 현재 Docker(PostgreSQL+Redis) 상시 서버 구조에서 다음으로 전환을 요청했다:

1. **PostgreSQL → SQLite**: aiosqlite 드라이버, WAL 모드, Docker 완전 제거
2. **Redis → 인메모리 dict**: Python dict + asyncio.Lock으로 Redis 대체, Docker 완전 제거
3. **Flutter 체인 UI**: 토큰 발급 버튼 → (1시간 이내) → 서버 시작 버튼 활성화 → (서버 연결) → 자동매매 + News 버튼 활성화
4. **KIS 토큰 독립 발급**: 서버 없이 토큰만 발급하는 경량 스크립트
5. **데이터 마이그레이션**: 기존 PostgreSQL 데이터 전체를 SQLite로 이관 (Docker 볼륨 백업)
6. **자동 매매 시작**: LaunchAgent 제거, Flutter 앱에서 버튼으로만 시작
7. **서버 자동 종료**: 07:00 KST에 자동 종료 (기존 로직 유지)

## Current Phase: Step 1 (SQLite 전환)
## Phase Goal: PostgreSQL → SQLite(aiosqlite) + Redis → 인메모리 dict 전환
## Active Agents: backend-db (SQLite migration)

## Critical Requirements (즉시 개입 필요)
- [CRITICAL] Docker 의존성 완전 제거 (PostgreSQL, Redis 컨테이너 불필요)
- [CRITICAL] 기존 데이터 전체 보존 (마이그레이션 스크립트 필수)
- [CRITICAL] aiosqlite 드라이버 + WAL 모드 적용
- [CRITICAL] Redis 대체: Python dict + asyncio.Lock (Pub/Sub 포함)
- [CRITICAL] CacheClient 인터페이스 100% 호환 유지 (read/write/read_json/write_json/atomic_list_append/publish/subscribe/aclose)
- [CRITICAL] SessionFactory 인터페이스 유지 (get_session 컨텍스트 매니저)
- [CRITICAL] secret_vault.py에서 DATABASE_URL/REDIS_URL 필수 키 요구사항 변경 필요
- [CRITICAL] preparation.py의 `cache._client.ping()` 직접 접근 제거 필요 (추상화 위반)

## Standard Requirements (Phase 완료 전 확인)
- Korean comments/docstrings 유지
- snake_case files/functions, PascalCase classes
- try/except + logging on all public methods
- async/await throughout
- SRP: Atomic 30줄, Manager 50줄, file 200줄 제한
- No workarounds -- proper integration required
- Python type hints on all parameters/return types
- from __future__ import annotations at top of every file

## 감시 대상 파일 (Step 1)
### 핵심 변경 대상
- src/common/database_gateway.py (PostgreSQL → SQLite 엔진)
- src/common/cache_gateway.py (Redis → 인메모리 dict)
- src/common/secret_vault.py (필수 키 목록 변경)
- src/db/models.py (PostgreSQL 전용 타입 → 범용 타입)
- src/main.py (시스템 초기화 흐름)
- src/orchestration/init/system_initializer.py (인프라 초기화)
- alembic/ (마이그레이션 환경 재구성)

### 영향 받는 파일 (간접)
- src/orchestration/phases/preparation.py (인프라 건강 검사)
- src/websocket/storage/redis_publisher.py (Pub/Sub 의존)
- src/monitoring/endpoints/system.py (DB/Redis 상태 점검)
- 모든 cache.read/write 호출 파일 (인터페이스 호환 필수)

## PostgreSQL 전용 코드 잔존 위치 (변환 필수)
1. database_gateway.py: asyncpg 드라이버, pool_size/max_overflow/pool_recycle 설정
2. secret_vault.py: DATABASE_URL, REDIS_URL 필수 키, postgresql+asyncpg:// URL 자동 생성
3. alembic/env.py: asyncpg→psycopg2 변환 로직, PostgreSQL URL 구성
4. alembic/versions/0001*.py: `from sqlalchemy.dialects import postgresql`, `postgresql.JSON`
5. preparation.py:57: `cache._client.ping()` -- Redis 직접 접근 (추상화 위반)
6. system.py: "Database(PostgreSQL)" 텍스트, DB/Redis 상태 점검 로직
7. 각종 docs/agents 문서: "PostgreSQL" 참조 (non-blocking)

## Redis 전용 코드 잔존 위치 (변환 필수)
1. cache_gateway.py: redis.asyncio, Lua 스크립트 (atomic_list_append), Pub/Sub
2. secret_vault.py: REDIS_URL 필수 키, redis:// URL 자동 생성
3. preparation.py: cache._client.ping() 직접 접근
4. websocket/storage/redis_publisher.py: cache.publish() Pub/Sub 사용
5. system_initializer.py: get_cache_client(redis_url=...)

## 이전 세션 수정 사항 (리그레션 금지)
- Session 3+4에서 해결된 15건 위반 (docs/guardian-violations.md 참조)
- V1 감사 10건 수정 사항 유지 확인 필수

---

## Phase: DB-ORM-Backend-Frontend 연결 감사 V3 (2026-03-15)

### 감사 요약
- 5개 ORM 모델 변경 사항과 전체 코드베이스 정합성 검증 완료
- **P0 위반 4건** 발견: SQL 쿼리 broken, recorded_at NULL, Alembic 불일치, Alembic PG 드라이버
- **P1 위반 3건** 발견: FxRate 필드명, FeedbackReport 동명 클래스, V2-001 미해결
- **P2 위반 3건**, **P3 위반 2건**
- 상세 보고서: `docs/guardian-violations-v3.md`

### 리더에게 전달한 즉시 수정 사항
1. [P0] data_preparer.py SQL `created_at` → `recorded_at` 변경 필요
2. [P0] indicator_persister.py에 `recorded_at` 타임스탬프 설정 추가 필요
3. [P0] Alembic env.py SQLite 전환 + 마이그레이션 파일 정합성 확보 필요
4. [P1] Flutter ticker-params PUT 본문 구조 수정 필요 (V2-001 이관)

---

## Phase: DB-ORM-Backend-Frontend 전수 연결 감사 V4 (2026-03-15)

### 감사 요약
- ORM 27모델 ↔ Alembic 3마이그레이션 ↔ Backend 30라우터 ↔ Flutter 22모델 전수 검증 완료
- Flutter ↔ Backend: **모든 주요 체인 정합성 확인** (20+ 영역)
- Raw SQL ↔ ORM: data_preparer.py 2개 쿼리 정합성 확인
- **P0 위반 4건**: Alembic 인프라 PostgreSQL 종속 (env.py + postgresql.JSON + now() + 5테이블 스키마 불일치)
- **P1 위반 3건**: secret_vault Redis 사잔코드, system.py PostgreSQL 참조, benchmark JSONResponse
- **P2 위반 5건**, **P3 위반 2건**
- 상세 보고서: `docs/guardian-violations-v4.md`

### 리더에게 전달한 즉시 수정 사항
1. [P0] Alembic env.py + 마이그레이션 파일 전면 SQLite 호환 재작성 필요
2. [P0] postgresql.JSON → sa.JSON 변환 (5개소)
3. [P0] now() → datetime('now') 변환 (29개소)
4. [P0] 5테이블 스키마 ORM 동기화 (indicator_history, fx_rates, notification_log, feedback_reports, crawl_checkpoints)
5. [P1] secret_vault.py REDIS_* 관련 코드 제거
6. [P1] system.py "PostgreSQL" → "SQLite" 수정
7. [P1] benchmark.py JSONResponse → Pydantic 모델 전환

### 이전 세션 대비 해결 확인
- V2-001 (ticker-params PUT): RESOLVED
- V3-P0-001 (data_preparer SQL): RESOLVED
- V3-P0-002 (indicator_persister recorded_at): RESOLVED
- V2-002 (noqa): RESOLVED (0건)

---

## Phase: DB-Backend-Frontend 2차 전수 연결 감사 V5 (2026-03-15)

### 감사 요약
- V4 수정사항 10건 재검증: **모두 RESOLVED, 리그레션 없음**
- 캐시 Writer↔Reader 체인 18개 키 전수 검증: **17개 정상, 1개 P1 위반**
- Flutter↔Backend 20+ 영역 모델 필드 매칭: **전체 정합성 확인**
- WebSocket 5채널 메시지 구조: **정상**
- Raw SQL↔ORM 3개 쿼리: **정상**
- Alembic 0004 27테이블: **ORM과 일치** (체인 실행 문제는 잔존)
- CLAUDE.md 핵심 규칙: **PASS** (noqa 0건, JSONResponse 0건, Pydantic 반환 100%)

### 신규 발견
1. [P0] Alembic 0001~0003 PostgreSQL 종속 체인 (런타임 영향 없음, alembic 명령 불가)
2. **[P1] EOD step 5가 존재하지 않는 캐시 키 "pnl:monthly"를 읽음 → 항상 $0.00으로 평가** (신규 발견)
3. [P2] Redis 독스트링 20+곳, PostgreSQL 독스트링 2곳, 파일 크기 초과 15+개
4. [P3] benchmark_writer.py 독스트링 Redis 참조

### 상세 보고서: `docs/guardian-violations-v5.md`

---

## Phase: Round 4 최종 감사 (2026-03-16)

### 감사 요약
- 최근 수정사항 6건 (SOS 버튼, 서버 버튼 분리, AppBar overflow, Flutter HIGH fixes, Guardian P0/P1 fixes, cache_publisher 리네임) 전수 검증
- **P0 위반 0건, P1 위반 0건** -- 다음 Phase 진입 가능
- P2 위반 3건: Flutter UI "Redis" 레이블 잔존, Python 함수 크기 초과(기존 부채), Dart 파일 크기 초과(기존 부채)
- P3 위반 2건: 한국어 주석 미준수 (경미)
- 상세 보고서: `docs/guardian-violations-r4.md`

### 검증 완료 항목
1. EmergencyButton STOP→SOS: PASS
2. SERVER 버튼 분리 (_ServerStartButton + _ServerStopButton): PASS
3. AppBar overflow 방지 (Flexible + SingleChildScrollView): PASS
4. cache_publisher 리네임 + import 체인: PASS
5. Python py_compile 12개 파일: PASS
6. Flutter dart analyze: PASS (error 0, warning 0)
7. Redis/RedisPublisher 참조 완전 제거 (Python): PASS
8. Backend cache 필드명 전환: PASS
9. Flutter JSON 파싱 하위 호환: PASS
10. Workaround 패턴 (noqa, @ts-ignore 등): PASS (0건)
11. Python return type hints: PASS

### 미해결 P2 (리더 보고 필요)
- R4-001: Flutter UI에서 "Redis"/"RDB" 표시 레이블이 남아있음 → "Cache" 변경 필요
- R4-004/R4-005: 파일/함수 크기 초과 (기존 부채, 대규모 리팩토링 필요)
