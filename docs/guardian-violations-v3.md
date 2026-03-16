# Guardian Violations Report V3 -- DB-ORM-Backend-Frontend 종합 감사

> 작성일: 2026-03-15
> 감사 범위: ORM 모델 5개 변경 사항 ↔ Alembic 마이그레이션 ↔ 백엔드 코드 ↔ Flutter 프론트엔드
> 목적: SQLite 전환 후 ORM 5개 모델 스키마 변경에 따른 전체 코드베이스 정합성 검증

---

## 감사 대상 ORM 모델 변경 요약

| # | 테이블 | 변경 전 (Alembic 0001) | 변경 후 (ORM models.py) | 위험도 |
|---|---|---|---|---|
| 1 | indicator_history | id=String(UUID), created_at 존재 | id=Integer(autoincrement), recorded_at 추가, created_at 없음 | **P0** |
| 2 | feedback_reports | summary(Text) 컬럼 존재 | summary 제거, report_date(Date) 추가 | P2 |
| 3 | crawl_checkpoints | source/last_url/last_published | checkpoint_at/total_articles/source_stats | P2 |
| 4 | fx_rates | id=String(UUID), usd_krw 컬럼 | id=Integer(autoincrement), timestamp+usd_krw_rate | P1 |
| 5 | notification_log | event_type/success 컬럼 | severity/title/message/sent_at/delivered | P2 |

---

## 위반 사항

### [VIOLATION-V3-001] 심각도: P0 -- indicator_history SQL 쿼리가 존재하지 않는 created_at 컬럼 참조

- **발견 위치**: `src/optimization/ml/data_preparer.py:43-47, 62-65`
- **위반 유형**: ORM-SQL 스키마 불일치 (런타임 에러 발생)
- **위반 상세**:
  - ORM `IndicatorHistory` 모델(models.py:76-83)은 `id=Integer(autoincrement)`, `recorded_at` 필드를 사용하며, `created_at` 컬럼이 **없다**.
  - `data_preparer.py`의 `_fetch_indicators()` 함수는 raw SQL로 `indicator_history`를 조회하는데:
    ```python
    # data_preparer.py:43-47
    query = (
        "SELECT id, ticker, indicator_name, value, "
        "metadata, created_at "    # ← created_at는 ORM에 없음
        "FROM indicator_history "
        "WHERE created_at BETWEEN :start AND :end "  # ← WHERE 절도 created_at 참조
        "ORDER BY created_at"      # ← ORDER BY도 created_at 참조
    )
    ```
  - `_merge_and_clean()` 함수(62-65행)도 `ind.get("created_at")`, `trade.get("created_at")`로 시간 키를 매핑한다.
  - **fresh SQLite DB**(ORM `create_all`로 생성)에서는 `created_at` 컬럼이 존재하지 않으므로 `sqlite3.OperationalError: no such column: created_at` 에러가 발생한다.
- **영향**: ML 학습 데이터 조회 완전 실패. EOD 시퀀스에서 피드백 루프가 작동하지 않는다.
- **관련 파일**:
  - `src/optimization/ml/data_preparer.py:43-47, 62-65` (SQL 쿼리 + merge 로직)
  - `src/db/models.py:76-83` (ORM 정의)
- **수정 방안**:
  1. `data_preparer.py`의 SQL 쿼리에서 `created_at` → `recorded_at`로 변경
  2. `_merge_and_clean()`의 시간 키 참조도 `recorded_at`로 변경
  3. 또는 ORM 기반 쿼리(SQLAlchemy select)로 리팩토링하여 raw SQL 의존 제거
- **상태**: **OPEN**

---

### [VIOLATION-V3-002] 심각도: P0 -- indicator_persister가 recorded_at을 설정하지 않음

- **발견 위치**: `src/orchestration/phases/indicator_persister.py:67-72`
- **위반 유형**: 데이터 무결성 위반 (필수 필드 미입력)
- **위반 상세**:
  - ORM `IndicatorHistory`의 `recorded_at`은 `Column(DateTime(timezone=True))` -- **NOT NULL이 아니고 server_default도 없다**.
  - `indicator_persister.py`에서 IndicatorHistory 레코드를 생성할 때:
    ```python
    record = IndicatorHistory(
        ticker=ticker,
        indicator_name=name,
        value=value,
        metadata_=meta,
        # recorded_at이 설정되지 않음 → NULL로 저장됨
    )
    ```
  - `data_preparer.py`가 `recorded_at`으로 시간 필터링을 하면 NULL인 레코드는 절대 조회되지 않는다.
- **영향**: indicator_history에 저장된 모든 데이터의 `recorded_at`이 NULL. ML 학습 데이터로 사용 불가.
- **관련 파일**:
  - `src/orchestration/phases/indicator_persister.py:67-72`
  - `src/db/models.py:82` (recorded_at 정의)
- **수정 방안**: `indicator_persister.py`에서 `recorded_at=datetime.now(tz=timezone.utc)` 추가
- **상태**: **OPEN**

---

### [VIOLATION-V3-003] 심각도: P0 -- Alembic 마이그레이션이 ORM과 5개 테이블에서 불일치

- **발견 위치**: `alembic/versions/0001_v2_clean_initial_schema.py`
- **위반 유형**: 스키마 마이그레이션 미반영 (DB 무결성 위반)
- **위반 상세**:
  Alembic 0001 마이그레이션과 현재 ORM models.py 사이에 다음 불일치가 존재한다:

  | 테이블 | Alembic 0001 스키마 | ORM models.py 스키마 |
  |---|---|---|
  | indicator_history.id | `String()` (UUID) | `Integer(autoincrement=True)` |
  | indicator_history | `created_at` 존재 | `recorded_at` 존재, created_at 없음 |
  | feedback_reports | `summary` Text 컬럼 존재 | `report_date` Date 추가, summary 제거 |
  | crawl_checkpoints | source/last_url/last_published | checkpoint_at/total_articles/source_stats |
  | crawl_checkpoints.id | `String()` (UUID) | `Integer(autoincrement=True)` |
  | fx_rates.id | `String()` (UUID) | `Integer(autoincrement=True)` |
  | fx_rates | `usd_krw` 컬럼 | `timestamp` + `usd_krw_rate` 컬럼 |
  | notification_log | event_type/success | severity/title/message/sent_at/delivered |

  - 기존 PostgreSQL DB에서 마이그레이션된 SQLite DB는 Alembic 0001 스키마를 가진다.
  - `database_gateway.py:81`의 `create_all()`은 기존 테이블이 있으면 건너뛰므로, 기존 DB에서는 ORM 변경이 반영되지 않는다.
  - `db/init.sql`은 새 스키마를 반영하지만, Alembic이 실제 마이그레이션 도구이다.
- **영향**: 기존 DB를 사용하는 환경에서는 ORM과 실제 테이블 구조가 불일치하여 모든 INSERT/SELECT 연산이 실패할 수 있다.
- **수정 방안**:
  1. `0004_update_5_tables.py` 마이그레이션을 작성하여 5개 테이블을 ALTER 또는 DROP+CREATE
  2. 또는 SQLite 전환이 완료되었으므로 Alembic 대신 `create_all()` 기반으로 전환하고, 기존 DB는 별도 마이그레이션 스크립트로 처리
- **상태**: **OPEN**

---

### [VIOLATION-V3-004] 심각도: P0 -- Alembic env.py가 PostgreSQL 드라이버를 사용

- **발견 위치**: `alembic/env.py:39, 42`
- **위반 유형**: 인프라 전환 미완료 (Alembic 실행 불가)
- **위반 상세**:
  ```python
  # alembic/env.py:39
  url = f"postgresql+asyncpg://{user}:{pw}@{host}:{port}/{name}"
  # alembic/env.py:42
  return url.replace("+asyncpg", "+psycopg2").replace("postgresql://", "postgresql+psycopg2://")
  ```
  - SQLite로 전환되었으나 Alembic 환경은 여전히 PostgreSQL URL을 구성한다.
  - 마이그레이션 0001도 `postgresql.JSON` 타입을 사용한다 (line 106, 152, 444, 445, 511).
  - `alembic upgrade head`를 실행하면 PostgreSQL 연결을 시도하여 실패한다.
- **영향**: Alembic을 통한 마이그레이션 관리가 완전히 비활성화된 상태이다.
- **수정 방안**:
  1. `alembic/env.py`를 SQLite URL로 변경
  2. 기존 마이그레이션 파일의 `postgresql.JSON` → `sa.JSON`으로 변경
  3. 또는 Alembic을 제거하고 ORM `create_all()` + 수동 마이그레이션 스크립트로 전환
- **상태**: **OPEN**

---

### [VIOLATION-V3-005] 심각도: P1 -- FxManager/FxScheduler가 FxRate.usd_krw로 접근하나 DB 컬럼은 usd_krw_rate

- **발견 위치**:
  - `src/tax/fx_manager.py:60, 68, 76` -- `FxRate(usd_krw=rate)`, `fx.usd_krw`
  - `src/tax/models.py:20` -- `FxRate.usd_krw: float`
  - `src/monitoring/schedulers/fx_scheduler.py:180` -- `float(fx_rate.usd_krw)`
  - `src/monitoring/endpoints/fx.py:102` -- `float(fx_rate.usd_krw)`
  - DB ORM `src/db/models.py:144` -- `usd_krw_rate = Column(Float)`
- **위반 유형**: Pydantic 모델 ↔ ORM 모델 필드명 불일치
- **위반 상세**:
  - `FxRate` Pydantic 모델(tax/models.py)은 `usd_krw` 필드를 사용한다.
  - DB ORM `FxRateRecord`(db/models.py)은 `usd_krw_rate` 컬럼을 사용한다.
  - 캐시 키 `fx:current`의 JSON에는 `usd_krw_rate` 키가 사용된다 (fx_scheduler.py:120).
  - **현재 FxRateRecord는 DB에 직접 저장되지 않으므로** (코드에서 `session.add(FxRateRecord(...))` 호출 없음), 런타임 에러는 발생하지 않는다. 하지만 향후 DB 저장 로직이 추가되면 필드명 불일치로 인해 데이터 매핑 오류가 발생한다.
  - 캐시 경로에서는 `usd_krw_rate` 키를 사용하므로 프론트엔드(Flutter)와의 인터페이스는 정상이다.
- **영향**: 현재는 캐시 경로만 사용하므로 기능적 문제 없음. 단, DB 저장 시 불일치 발생 잠재적 위험.
- **수정 방안**: `FxRate` Pydantic 모델의 `usd_krw` → `usd_krw_rate`로 통일, 또는 DB 모델 사용 시 명시적 매핑 추가
- **상태**: **OPEN**

---

### [VIOLATION-V3-006] 심각도: P1 -- FeedbackReport Pydantic 모델(analysis/models.py)에 summary 필드가 여전히 존재

- **발견 위치**:
  - `src/analysis/models.py:98-103` -- `FeedbackReport.summary: dict`
  - `src/analysis/feedback/eod_feedback_report.py:51-58, 97-101, 105-108` -- `summary=...`
  - `src/optimization/feedback/rag_doc_updater.py:21` -- `result.summary`
  - `src/optimization/feedback/param_adjuster.py:133` -- `daily_result.summary`
  - DB ORM `src/db/models.py:98-104` -- summary 컬럼 없음, `report_date` 추가
- **위반 유형**: Pydantic 모델 ↔ ORM 모델 필드 불일치
- **위반 상세**:
  - `analysis/models.py`의 `FeedbackReport` Pydantic 모델은 `summary: dict` 필드를 가진다.
  - DB ORM `FeedbackReport`(db/models.py)에는 `summary` 컬럼이 삭제되고 `report_date: Date`가 추가되었다.
  - 둘은 같은 이름(`FeedbackReport`)이지만 **별개의 클래스**이다:
    - `src/analysis/models.py:98` = Pydantic BaseModel (매매 로직용)
    - `src/db/models.py:98` = SQLAlchemy ORM (DB 저장용)
  - 현재 `EODFeedbackReport`는 캐시에 저장하고(`feedback:latest`), DB에는 직접 저장하지 않으므로, 런타임 에러는 발생하지 않는다. 그러나 클래스명이 같아 import 혼동 위험이 크다.
- **영향**: 현재 캐시 경로만 사용하므로 기능적 문제 없음. import 혼동 및 향후 DB 저장 시 불일치 발생 잠재적 위험.
- **수정 방안**:
  - Pydantic 모델명을 `FeedbackReportResult`로 변경하여 DB 모델과 구분
  - 또는 DB 모델의 `content` JSON 컬럼에 Pydantic 모델 전체를 직렬화하여 저장하는 패턴 사용
- **상태**: **OPEN**

---

### [VIOLATION-V3-007] 심각도: P2 -- CrawlCheckpoint/NotificationLog/FxRateRecord가 DB에 기록되지 않음 (dead ORM)

- **발견 위치**:
  - `src/db/models.py:108-114` -- CrawlCheckpoint
  - `src/db/models.py:140-146` -- FxRateRecord
  - `src/db/models.py:190-199` -- NotificationLog
- **위반 유형**: 미사용 ORM 모델 (dead code)
- **위반 상세**:
  - 코드베이스 전체에서 `CrawlCheckpoint(`, `FxRateRecord(`, `NotificationLog(` 인스턴스 생성이 없다.
  - `session.add()` 호출에서도 이 3개 모델은 사용되지 않는다.
  - ORM 모델 스키마가 변경되었지만, 이를 사용하는 코드가 없어 변경의 실질적 영향이 없다.
  - 그러나 테이블은 `create_all()`로 생성되므로 불필요한 빈 테이블이 DB에 존재한다.
- **영향**: 기능적 문제 없음. 코드 위생 차원의 이슈.
- **수정 방안**:
  - 향후 사용 계획이 없으면 모델 제거 검토
  - 사용 계획이 있으면 기록 코드(writer) 추가 필요
- **상태**: **OPEN**

---

### [VIOLATION-V3-008] 심각도: P2 -- 스크립트/문서에 하드코딩된 포트 9501 잔존 (13곳)

- **발견 위치**: 아래 파일들
- **위반 유형**: 인프라 전환 미완료 (동적 포트 감지 미적용)
- **위반 상세**:
  서버는 동적 포트(9500-9505)를 사용하고 `data/server_port.txt`에 기록하지만, 다음 파일들은 9501을 하드코딩하고 있다:

  | 파일 | 하드코딩 수 |
  |---|---|
  | `scripts/monitor_5min.sh` | 3곳 |
  | `scripts/monitor_overnight.py` | 1곳 |
  | `scripts/auto_trading.sh` | 1곳 |
  | `scripts/start_dashboard.py` | 1곳 |
  | `scripts/start_server.sh` | 2곳 |
  | `scripts/monitor_trading.sh` | 1곳 |
  | `docs/api-specification.md` | 2곳 |
  | `CheckList/` 문서들 | 다수 |
  | `docs/superpowers/` 문서들 | 3곳 |

  - Flutter `server_launcher.dart`는 동적 포트 감지를 정상 구현하고 있다 (포트 파일 → 캐시 → 범위 스캔).
  - 백엔드 `api_server.py`도 동적 포트를 정상 구현하고 있다.
  - 문제는 **보조 스크립트와 문서**에 구 포트가 잔존한다는 것이다.
- **영향**: 서버가 9501이 아닌 다른 포트에서 시작되면 보조 스크립트가 연결 실패한다.
- **수정 방안**:
  - 스크립트들에 `data/server_port.txt` 읽기 로직 추가
  - 또는 `PORT=$(cat data/server_port.txt 2>/dev/null || echo 9501)` 패턴 사용
  - 문서의 포트 번호는 "동적 포트 (기본 9500-9505)" 설명으로 교체
- **상태**: **OPEN**

---

### [VIOLATION-V3-009] 심각도: P2 -- server_launcher.dart 독스트링에 "Docker(PostgreSQL+Redis) 별도 관리" 언급

- **발견 위치**: `dashboard/lib/services/server_launcher.dart:9`
- **위반 유형**: 문서 정합성 위반
- **위반 상세**:
  ```dart
  /// Docker(PostgreSQL+Redis)는 별도로 관리하며 이 클래스에서는 다루지 않는다.
  ```
  - SQLite+InMemoryCache로 전환되어 Docker가 더 이상 필요하지 않다.
  - 오해를 유발하는 오래된 독스트링이다.
- **영향**: 기능적 문제 없음. 코드 독스트링 정합성 이슈.
- **수정 방안**: 해당 독스트링을 "SQLite+인메모리 캐시 기반이므로 별도 인프라가 필요하지 않다"로 변경
- **상태**: **OPEN**

---

### [VIOLATION-V3-010] 심각도: P3 -- fx.py 독스트링에 "Redis 캐시" 언급

- **발견 위치**: `src/monitoring/endpoints/fx.py:1, 80, 85, 129`
- **위반 유형**: 독스트링 정합성 위반
- **위반 상세**: "FxManager 인스턴스가 있으면 실시간 데이터를, 없으면 Redis 캐시 또는 기본값을 반환한다" 등 Redis 관련 언급이 4곳에 잔존한다.
- **영향**: 없음. 독스트링 정합성 이슈.
- **수정 방안**: "Redis" → "캐시" 또는 "인메모리 캐시"로 교체
- **상태**: **OPEN**

---

### [VIOLATION-V3-011] 심각도: P3 -- fx_scheduler.py 독스트링에 "Redis에 캐싱" 언급

- **발견 위치**: `src/monitoring/schedulers/fx_scheduler.py:1, 7`
- **위반 유형**: 독스트링 정합성 위반
- **위반 상세**: "10분 주기로 USD/KRW 환율을 갱신하고 Redis에 캐싱한다" 등.
- **영향**: 없음.
- **수정 방안**: "Redis" → "인메모리 캐시"로 교체
- **상태**: **OPEN**

---

### [VIOLATION-V3-012] 심각도: P1 -- 이전 V2 감사 미해결 위반 (V2-001) 여전히 OPEN

- **발견 위치**: V2 보고서 참조
- **위반 유형**: PUT /api/strategy/ticker-params/{ticker} 요청 본문 구조 불일치
- **위반 상세**: Flutter `setTickerOverride()`가 다중 키 Map을 전송하지만, 백엔드 `TickerParamsUpdateRequest`는 단일 `{param_name, value}` 구조를 기대한다. 422 Validation Error 발생.
- **상태**: **OPEN** (V2-001에서 이관)

---

## 위반 사항 요약

| 심각도 | 건수 | 설명 |
|---|---|---|
| **P0** (시스템 장애) | 4 | V3-001 (SQL 쿼리 broken), V3-002 (recorded_at NULL), V3-003 (마이그레이션 불일치), V3-004 (Alembic PG 드라이버) |
| **P1** (런타임 오류/잠재적) | 3 | V3-005 (FxRate 필드명), V3-006 (FeedbackReport 동명 클래스), V3-012 (V2-001 미해결) |
| **P2** (코드 품질) | 3 | V3-007 (dead ORM), V3-008 (하드코딩 포트), V3-009 (독스트링) |
| **P3** (권장) | 2 | V3-010 (fx.py 독스트링), V3-011 (fx_scheduler 독스트링) |

---

## 즉시 수정 필요 사항 (리더에게 전달)

### [GUARDIAN CORRECTION - P0] #1
- **대상**: 백엔드 DB 담당
- **위반**: data_preparer.py의 SQL 쿼리가 indicator_history.created_at을 참조하나 ORM에는 recorded_at만 존재
- **수정 지시**: `src/optimization/ml/data_preparer.py`의 43-47행 SQL 쿼리와 62-65행 merge 키를 `created_at` → `recorded_at`로 변경
- **기한**: 즉시

### [GUARDIAN CORRECTION - P0] #2
- **대상**: 백엔드 DB 담당
- **위반**: indicator_persister가 IndicatorHistory 생성 시 recorded_at을 설정하지 않아 NULL로 저장됨
- **수정 지시**: `src/orchestration/phases/indicator_persister.py:67-72`에서 `recorded_at=datetime.now(tz=timezone.utc)` 추가
- **기한**: 즉시

### [GUARDIAN CORRECTION - P0] #3
- **대상**: 백엔드 DB 담당
- **위반**: Alembic 마이그레이션 0001이 5개 테이블의 ORM 변경을 반영하지 않으며, env.py가 PostgreSQL 드라이버를 사용
- **수정 지시**: (A) Alembic env.py를 SQLite URL로 변경 + 0004 마이그레이션으로 5개 테이블 스키마 갱신, 또는 (B) Alembic을 제거하고 ORM create_all() 기반으로 전환
- **기한**: Phase 완료 전

### [GUARDIAN CORRECTION - P1] #4
- **대상**: Flutter 프론트엔드 담당
- **위반**: PUT /api/strategy/ticker-params/{ticker} 요청 본문이 백엔드와 불일치 (V2-001 미해결)
- **수정 지시**: `api_service.dart`의 `setTickerOverride`를 개별 PUT 요청으로 분리
- **기한**: 즉시

---

## Flutter 프론트엔드 검증 결과

Flutter 모델들과 백엔드 응답 스키마의 정합성을 확인하였다:

| 모델 | 검증 결과 | 비고 |
|---|---|---|
| `FxStatus.fromJson` ↔ `FxStatusResponse` | **PASS** | `usd_krw_rate`, `change_pct`, `updated_at`, `source` 일치 |
| `FxHistoryPoint.fromJson` ↔ `FxHistoryEntry` | **PASS** | `date`, `rate`, `change_pct` 일치 |
| `EmergencyStatus.fromJson` ↔ 백엔드 응답 | **PASS** | 필드 매칭 완료 |
| `IndicatorHistory.fromJson` (Flutter) | **PASS** | 캐시 경로 사용, DB 직접 조회 없음 |
| `NewsArticle.fromJson` ↔ 백엔드 기사 응답 | **PASS** | 모든 필드 매칭 + 폴백 처리 |
| `DailyReport.fromJson` ↔ 백엔드 리포트 응답 | **PASS** | 중첩 구조 + 평탄 구조 모두 처리 |
| 포트 감지 (`server_launcher.dart`) | **PASS** | 동적 포트 감지 정상 구현 |

**결론**: Flutter 프론트엔드 모델은 백엔드 응답 스키마와 정상 매칭된다. 유일한 미해결 이슈는 V2-001 (ticker-params PUT 본문 구조 불일치)이다.

---

## 전체 준수 현황

| 규칙 | 상태 | 비고 |
|---|---|---|
| ORM ↔ 실제 DB 스키마 일치 | **FAIL** | 5개 테이블 불일치 (V3-003) |
| 백엔드 코드 ↔ ORM 필드명 | **FAIL** | data_preparer.py created_at 참조 (V3-001) |
| Flutter ↔ 백엔드 API 응답 | **PASS** | 1건 제외(V2-001) 모두 일치 |
| 캐시 인터페이스 호환 | **PASS** | InMemoryCache의 CacheClient 인터페이스 100% 호환 |
| 동적 포트 감지 | **PARTIAL** | 서버+Flutter는 정상, 보조 스크립트 미적용 |
| Docker 의존 제거 | **PASS** | 코드 레벨에서 Docker 의존 없음 |
| Redis 참조 제거 | **PARTIAL** | 코드는 정상, 독스트링 3곳 잔존 |
