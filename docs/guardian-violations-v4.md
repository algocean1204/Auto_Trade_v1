# Guardian Violation Report V4 -- DB-ORM-Backend-Frontend 전수 연결 감사

**감사일**: 2026-03-15
**감사 범위**: ORM ↔ Alembic ↔ Backend Endpoints ↔ Pydantic Schemas ↔ Flutter Models ↔ API Service
**Phase**: DB↔Backend↔Frontend 전수 연결 감사

---

## 요약

| 심각도 | 건수 | 설명 |
|--------|------|------|
| **P0** | 4건 | Alembic 인프라 PostgreSQL 종속, 스키마 5테이블 불일치 |
| **P1** | 3건 | secret_vault Redis 사잔코드, system.py PostgreSQL 참조, benchmark JSONResponse |
| **P2** | 5건 | 파일 크기 초과, type:ignore 238건, 레거시 코멘트 |
| **P3** | 2건 | agent 문서 PostgreSQL 참조, data_preparer 코멘트 |
| **합계** | **14건** | |

---

## P0 위반 (즉시 작업 중단 + 수정 필수)

### [V4-P0-001] Alembic env.py: PostgreSQL 드라이버 하드코딩
- **발견 지점**: alembic/env.py:23-42
- **위반 유형**: 인프라 미전환 (SQLite 마이그레이션 불가)
- **위반 상세**:
  - `get_url()` 함수가 `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD` 환경변수로 `postgresql+asyncpg://` URL을 구성한다
  - `asyncpg → psycopg2` 변환 로직이 하드코딩되어 있다
  - SQLite 환경에서 `alembic upgrade head` 실행 시 PostgreSQL 드라이버로 접속을 시도하여 실패한다
- **관련 파일**: `/Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading/alembic/env.py`
- **원래 요구사항**: [CRITICAL] Docker 의존성 완전 제거 (PostgreSQL 컨테이너 불필요)
- **수정 지시**: `get_url()`을 SQLite 호환으로 변경한다. DATABASE_URL 환경변수 또는 기본값 `sqlite:///data/trading.db`를 사용한다. asyncpg→psycopg2 변환 로직을 제거한다.
- **상태**: OPEN

### [V4-P0-002] Alembic 0001: postgresql.JSON 타입 사용 (5개소)
- **발견 지점**: alembic/versions/0001_v2_clean_initial_schema.py:16,106,152,444,445,511
- **위반 유형**: PostgreSQL 전용 방언 (SQLite 비호환)
- **위반 상세**:
  - `from sqlalchemy.dialects import postgresql` 임포트
  - `postgresql.JSON(astext_type=sa.Text())` 5개소 사용
  - SQLite에서 실행 시 `sqlalchemy.dialects.postgresql` 모듈은 PostgreSQL 방언을 요구하므로 실패한다
- **관련 파일**: `/Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading/alembic/versions/0001_v2_clean_initial_schema.py`
- **수정 지시**: `postgresql.JSON()` → `sa.JSON()`으로 변경한다. `from sqlalchemy.dialects import postgresql` 임포트를 제거한다.
- **상태**: OPEN

### [V4-P0-003] Alembic 0001/0002/0003: `now()` server_default (29개소)
- **발견 지점**: 3개 마이그레이션 파일 전체
- **위반 유형**: PostgreSQL 전용 SQL 함수 (SQLite 비호환)
- **위반 상세**:
  - `server_default=sa.text("now()")` 29개소 사용 (0001: 26개, 0002: 2개, 0003: 1개)
  - SQLite에서는 `now()` 함수가 존재하지 않는다
  - ORM models.py는 이미 `server_default=text("(datetime('now'))")` SQLite 호환 문법을 사용 중이다
  - 실제 DB는 `Base.metadata.create_all()`로 생성하므로 런타임에는 영향 없지만, Alembic 마이그레이션 실행 시 실패한다
- **관련 파일**:
  - `/Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading/alembic/versions/0001_v2_clean_initial_schema.py`
  - `/Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading/alembic/versions/0002_add_universe_config.py`
  - `/Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading/alembic/versions/0003_rebuild_articles_v2.py`
- **수정 지시**: 모든 `sa.text("now()")` → `sa.text("(datetime('now'))")` 로 변경한다.
- **상태**: OPEN

### [V4-P0-004] Alembic 0001 vs ORM: 5개 테이블 스키마 불일치
- **발견 지점**: alembic/versions/0001_v2_clean_initial_schema.py vs src/db/models.py
- **위반 유형**: 마이그레이션 스키마 ≠ 현재 ORM 모델 (구조적 불일치)
- **위반 상세**:

  | 테이블 | Alembic 0001 | ORM (models.py) | 불일치 |
  |--------|-------------|-----------------|--------|
  | **indicator_history** | id=String, created_at | id=Integer(autoincrement), recorded_at | PK 타입 + 타임스탬프 컬럼명 변경 |
  | **fx_rates** | id=String, usd_krw, source | id=Integer(autoincrement), usd_krw_rate, timestamp, source | PK 타입 + 컬럼명 변경 + 컬럼 추가 |
  | **notification_log** | event_type, success | severity, title, message, sent_at, delivered | 완전히 다른 컬럼 구조 |
  | **feedback_reports** | summary(Text), content(JSON), (report_date 없음) | report_date(Date), content(JSON), (summary 없음) | 컬럼 추가/삭제 |
  | **crawl_checkpoints** | id=String, source, last_url, last_published | id=Integer(autoincrement), checkpoint_at, total_articles, source_stats(JSON) | PK 타입 + 완전히 다른 컬럼 |

  - 런타임 DB는 `Base.metadata.create_all()`로 ORM 기반 생성되므로 실제 동작에는 문제 없다
  - 그러나 Alembic 마이그레이션 히스토리가 현재 스키마를 정확히 반영하지 않으므로, 향후 `alembic revision --autogenerate` 실행 시 잘못된 diff를 생성한다
- **관련 파일**:
  - `/Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading/alembic/versions/0001_v2_clean_initial_schema.py`
  - `/Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading/src/db/models.py`
- **수정 지시**: 기존 0001/0002/0003 마이그레이션을 SQLite 호환으로 전면 재작성하거나, ORM과 완전히 동기화된 새로운 단일 initial 마이그레이션(0004)을 생성한다. `alembic revision --autogenerate` 후 diff가 0인지 확인한다.
- **상태**: OPEN

---

## P1 위반 (즉시 수정 지시, Phase 완료 전 해결 필수)

### [V4-P1-001] secret_vault.py: Redis URL 구성 사잔코드
- **발견 지점**: src/common/secret_vault.py:34, 51-70
- **위반 유형**: 인프라 미전환 잔존 코드 (Redis 제거 후)
- **위반 상세**:
  - `_MANAGED_KEYS`에 `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` 4개 키가 잔존한다 (라인 34)
  - `_build_composite_secrets()` 함수(라인 61-69)가 `REDIS_HOST/PORT/PASSWORD`로부터 `redis://...` URL을 조합한다
  - Redis가 인메모리 dict로 대체된 후 이 코드는 완전히 사잔(dead code)이다
  - `.env` 파일에 `REDIS_*` 키가 없으면 불필요한 기본 `redis://localhost:6379/0`을 생성한다
- **관련 파일**: `/Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading/src/common/secret_vault.py`
- **원래 요구사항**: [CRITICAL] Redis 대체: Python dict + asyncio.Lock
- **수정 지시**: `_MANAGED_KEYS`에서 `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` 4개 키를 제거한다. `_build_composite_secrets()`에서 REDIS_URL 조합 로직(라인 62-69)을 삭제한다.
- **상태**: OPEN

### [V4-P1-002] system.py: "Database(PostgreSQL)" 참조
- **발견 지점**: src/monitoring/endpoints/system.py:80, 115
- **위반 유형**: 레거시 참조 (사용자 혼란 유발)
- **위반 상세**:
  - 라인 80: 함수 docstring에 `Database(PostgreSQL)` 텍스트 잔존
  - 라인 115: 코드 코멘트에 `Database(PostgreSQL)` 텍스트 잔존
  - 현재 시스템은 SQLite를 사용하므로 "Database(SQLite)"로 수정해야 한다
- **관련 파일**: `/Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading/src/monitoring/endpoints/system.py`
- **수정 지시**: `PostgreSQL` → `SQLite`로 변경한다.
- **상태**: OPEN

### [V4-P1-003] benchmark.py: get_benchmark_chart가 JSONResponse 반환
- **발견 지점**: src/monitoring/endpoints/benchmark.py:207-230
- **위반 유형**: CLAUDE.md 규칙 위반 (모든 엔드포인트는 Pydantic BaseModel 반환)
- **위반 상세**:
  - `get_benchmark_chart()` 엔드포인트가 `JSONResponse(content=chart_data)`를 직접 반환한다
  - CLAUDE.md/MEMORY: "Every endpoint returns exactly 1 Pydantic BaseModel (no dict, no JSONResponse)"
  - `from fastapi.responses import JSONResponse` 임포트가 존재한다
- **관련 파일**: `/Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading/src/monitoring/endpoints/benchmark.py`
- **수정 지시**: `BenchmarkChartResponse(BaseModel)` Pydantic 모델(items: list[BenchmarkPeriodItem])을 생성하고, JSONResponse 대신 해당 모델을 반환한다. Flutter `_getList`가 배열을 기대하므로 `{"items": [...]}` 또는 리스트 직접 반환 구조를 검토한다.
- **상태**: OPEN

---

## P2 위반 (수정 지시, 다음 Phase 진입 전 해결)

### [V4-P2-001] Python 파일 크기 초과 (200줄 제한 위반, 15+개 파일)
- **발견 지점**: 프로젝트 전체
- **위반 유형**: CLAUDE.md SRP 규칙 위반 (파일 200줄 제한)
- **위반 상세**:
  - trading_loop.py: 2055줄 (10x 초과)
  - analysis.py (endpoint): 665줄
  - eod_sequence.py: 655줄
  - news_pipeline.py: 637줄
  - risk.py (endpoint): 520줄
  - indicators.py (endpoint): 503줄
  - exit_strategy.py: 489줄
  - macro.py (endpoint): 487줄
  - profit_target.py (endpoint): 478줄
  - dashboard.py (endpoint): 474줄
  - dependency_injector.py: 461줄
  - strategy.py (endpoint): 456줄
  - situation_tracker.py: 449줄
  - reports.py: 443줄
  - kis_api.py: 443줄
  - 이외 다수
- **수정 지시**: 200줄 초과 파일을 기능별로 분리한다. 특히 trading_loop.py(2055줄)은 최우선 분할 대상이다. 엔드포인트 파일들은 헬퍼 함수를 별도 모듈로 추출한다.
- **상태**: OPEN (이전 세션에서도 지적됨, V2-004 이관)

### [V4-P2-002] `# type: ignore` 238건 사용
- **발견 지점**: src/ 전체 (238건)
- **위반 유형**: CLAUDE.md 워크어라운드 금지 규칙 위반
- **위반 상세**:
  - `# type: ignore[union-attr]`: DI 패턴에서 Optional 피처 접근 시 사용 (대다수)
  - `# type: ignore[attr-defined]`: 비공개 속성 접근 시 사용
  - `# type: ignore[misc]`: 기타
  - DI 패턴 특성상 `features.get()` 반환값이 `Any | None`이므로 구조적으로 발생하는 측면이 있다
  - 그러나 238건은 과도한 수치이며, 타입 안전성을 위한 래퍼 함수나 TypedDict 도입이 필요하다
- **수정 지시**: DI 피처 접근을 위한 타입 안전 래퍼 함수를 도입하여 `type: ignore` 사용을 최소화한다. 당장 전부 제거가 어렵다면, 최소한 DI 접근 이외의 `type: ignore`를 먼저 해결한다.
- **상태**: OPEN (이전 세션 P2-007 이관)

### [V4-P2-003] Flutter api_service.dart 1673줄
- **발견 지점**: dashboard/lib/services/api_service.dart
- **위반 유형**: SRP 위반 (파일 200줄, 컴포넌트 150줄 제한)
- **위반 상세**:
  - 단일 파일에 40+개 API 메서드가 집약되어 있다
  - 도메인별로 분리하는 것이 유지보수에 적합하다 (예: RiskApiService, TaxApiService 등)
- **수정 지시**: 도메인별 partial 파일 또는 mixin으로 분리한다.
- **상태**: OPEN

### [V4-P2-004] Flutter risk_models.dart 495줄, news_models.dart 461줄
- **발견 지점**: dashboard/lib/models/
- **위반 유형**: SRP 위반 (파일 크기 초과)
- **위반 상세**:
  - risk_models.dart: 8개 클래스가 단일 파일에 포함 (495줄)
  - news_models.dart: 3개 클래스 + 다수 getter (461줄)
- **수정 지시**: 연관 클래스 그룹별로 파일을 분리한다.
- **상태**: OPEN

### [V4-P2-005] data_preparer.py: `__import__("sqlalchemy")` 인라인 임포트
- **발견 지점**: src/optimization/ml/data_preparer.py:30, 49
- **위반 유형**: 코드 품질 위반 (비정상 임포트 패턴)
- **위반 상세**:
  - `__import__("sqlalchemy").text(query)` 패턴으로 인라인 임포트 사용
  - 파일 상단에 `from sqlalchemy import text`로 정상 임포트해야 한다
- **관련 파일**: `/Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading/src/optimization/ml/data_preparer.py`
- **수정 지시**: 파일 상단에 `from sqlalchemy import text`를 추가하고, 인라인 `__import__` 호출을 제거한다.
- **상태**: OPEN

---

## P3 위반 (기록, 일괄 처리)

### [V4-P3-001] 에이전트/문서에 PostgreSQL 참조 잔존
- **발견 지점**: src/agents/ 및 docs/ 내 일부 파일
- **위반 유형**: 문서 정합성 (비기능적, 혼란 유발 가능)
- **위반 상세**:
  - 에이전트 문서 및 일부 docs 파일에서 "PostgreSQL" 텍스트가 잔존한다
  - 실제 기능에 영향은 없으나, 신규 개발자에게 혼란을 줄 수 있다
- **수정 지시**: 검색/치환으로 "PostgreSQL" → "SQLite" 업데이트한다 (docs, agents 디렉토리).
- **상태**: OPEN

### [V4-P3-002] data_preparer.py 코멘트: "Redis 캐시 키"
- **발견 지점**: src/optimization/ml/data_preparer.py:14
- **위반 유형**: 레거시 코멘트 (혼란 유발)
- **위반 상세**:
  - `_CACHE_PREFIX` 변수 위 코멘트가 "Redis 캐시 키 접두사이다"로 되어 있다
  - 현재 캐시는 인메모리 dict이므로 "인메모리 캐시 키 접두사이다"로 수정해야 한다
- **수정 지시**: "Redis" → "인메모리" 또는 "캐시"로 변경한다.
- **상태**: OPEN

---

## Flutter ↔ Backend 연결 검증 결과 (정상 확인)

아래 연결 체인은 모두 **정합성 확인 완료**이다:

### 정상 확인 항목
| 영역 | Flutter Model | Backend Response | 상태 |
|------|--------------|------------------|------|
| Dashboard Summary | DashboardSummary.fromJson | DashboardSummaryResponse | OK -- 모든 필드 일치 |
| System Status | SystemStatus.fromJson (quota, safety) | SystemStatusResponse | OK -- kis_calls_today, kis_limit, max_hold_days 포함 |
| Positions | Position.fromJson | PositionItem (pnl_pct→unrealized_pnl_pct) | OK -- 변환 로직 정상 |
| Trades | Trade.fromJson | RecentTradesResponse (side→action) | OK -- 변환 로직 정상 |
| Risk Dashboard | RiskDashboardData.fromJson | RiskDashboardResponse | OK -- gates, risk_budget, var_indicator, streak_counter, concentrations, trailing_stop 모두 일치 |
| Tax Status | TaxStatus.fromJson | TaxStatusResponse | OK -- summary + remaining_exemption 구조 일치 |
| Tax Harvest | TaxHarvestSuggestion.fromJson | HarvestSuggestion | OK -- unrealized_loss_usd, potential_tax_saving_krw, recommendation 일치 |
| FX Status | FxStatus.fromJson | FxStatusResponse | OK -- usd_krw_rate, change_pct, updated_at, source |
| Slippage | SlippageStats.fromJson | SlippageStatsResponse | OK -- avg/max/median + by_hour 포함 |
| Benchmark Comparison | BenchmarkComparison.fromJson | BenchmarkComparisonResponse | OK -- periods + summary 구조 일치 |
| Benchmark Chart | BenchmarkChartPoint.fromJson | BenchmarkPeriodItem (JSONResponse) | OK (필드 일치, 단 JSONResponse 사용은 P1 위반) |
| Profit Target Current | ProfitTargetStatus.fromJson | ProfitTargetCurrentResponse | OK -- time_progress 중첩 구조 포함 |
| Profit Target History | MonthlyHistory.fromJson | ProfitTargetHistoryEntry | OK -- year, month, target_usd, actual_pnl_usd, achievement_pct |
| Profit Target Projection | ProfitTargetProjection.fromJson | ProfitTargetProjectionResponse | OK -- 7개 필드 모두 일치 |
| Indicator Weights | IndicatorWeights.fromJson | /indicators/weights 응답 | OK -- weights + presets 구조 |
| News Articles | NewsArticle.fromJson | /news/articles 응답 | OK -- importance, time_sensitivity, actionability, leveraged_etf_impact 포함 |
| News Summary | NewsSummary.fromJson | /news/summary 응답 | OK -- importance_distribution 포함 |
| Feedback Reports | FeedbackReport.fromJson (trade_models.dart) | feedback_reports 테이블 | OK -- report_type, report_date, content, created_at |
| WebSocket | 5 channels (dashboard, positions, trades, alerts, orderflow) | ws_manager.py + cache `ws:*` keys | OK -- envelope unwrapping 포함 |
| Port Sync | server_launcher.dart (port file → scan) | api_server.py (port file write) | OK -- data/server_port.txt 동기화 |
| Ticker Params | setTickerOverride (개별 PUT) | /strategy/ticker-params/{ticker} PUT | OK -- V2-001 해결 확인 |

### Raw SQL vs ORM 정합성
| 파일 | SQL 쿼리 | ORM 모델 | 상태 |
|------|----------|---------|------|
| data_preparer._fetch_trades | `SELECT * FROM trades WHERE created_at BETWEEN` | Trade.created_at | OK |
| data_preparer._fetch_indicators | `SELECT id, ticker, indicator_name, value, metadata, recorded_at` | IndicatorHistory (id, ticker, indicator_name, value, metadata_→metadata, recorded_at) | OK |
| indicator_persister | `recorded_at=datetime.now(tz=timezone.utc)` | IndicatorHistory.recorded_at | OK |

---

## 이전 세션 대비 변화

| 이전 위반 ID | 상태 | 비고 |
|-------------|------|------|
| V2-001 (ticker-params PUT) | **RESOLVED** | Flutter setTickerOverride 개별 PUT 확인 |
| V2-002 (noqa 사용) | **RESOLVED** | noqa 0건 확인 |
| V2-003 (stale TODOs) | 미검증 | 이번 감사 범위 외 |
| V2-004 (파일 크기) | **V4-P2-001로 이관** | 여전히 미해결 |
| V3-P0-001 (data_preparer SQL created_at) | **RESOLVED** | trades 테이블 created_at 컬럼 존재 확인 |
| V3-P0-002 (indicator_persister recorded_at) | **RESOLVED** | recorded_at 타임스탬프 설정 확인 |
| V3-P0-003 (Alembic SQLite 전환) | **V4-P0-001/002/003로 이관** | 여전히 미해결 |
| V3-P1-001 (Flutter ticker-params) | **RESOLVED** | V2-001과 동일, 해결 확인 |

---

## 리더에게 전달할 즉시 수정 사항

### 최우선 (P0) -- 작업 중단 수준
1. **Alembic 전면 재작성**: env.py SQLite 전환 + 마이그레이션 파일 `postgresql.JSON` → `sa.JSON`, `now()` → `datetime('now')`, 5테이블 스키마 ORM 동기화
2. **방법 제안**: 기존 0001/0002/0003을 개별 수정하기보다, ORM 기반 새 initial 마이그레이션 1개로 통합 재생성이 효율적이다

### 즉시 수정 (P1) -- Phase 완료 전 필수
3. secret_vault.py에서 REDIS_* 관련 코드 제거
4. system.py "PostgreSQL" → "SQLite" 텍스트 수정
5. benchmark.py `JSONResponse` → Pydantic 모델로 변경

### 품질 개선 (P2) -- 다음 Phase 진입 전
6. 200줄 초과 파일 분할 (trading_loop.py 2055줄 최우선)
7. `type: ignore` 238건 중 비DI 패턴 건 해결
8. data_preparer.py `__import__` → 정상 import
