# Guardian Violation Report V5 -- DB-Backend-Frontend 전수 연결 감사 (2차)

**감사일**: 2026-03-15
**감사 범위**: 캐시 Writer↔Reader 체인, Alembic↔ORM 정합성, Flutter↔Backend 모델 필드 매칭, CLAUDE.md 규칙 준수
**Phase**: DB↔Backend↔Frontend 2차 전수 연결 감사

---

## 요약

| 심각도 | 건수 | 설명 |
|--------|------|------|
| **P0** | 1건 | Alembic 체인 실행 불가 (0001~0003 PostgreSQL 종속, 0004 fresh 실행 불가) |
| **P1** | 1건 | EOD step 5 캐시 키 불일치 (pnl:monthly 작성자 없음) |
| **P2** | 3건 | Redis 언급 독스트링 20+곳, article/universe_persister PostgreSQL 독스트링, 파일 크기 초과 |
| **P3** | 1건 | benchmark_writer.py 독스트링 "Redis" 참조 |
| **합계** | **6건** | |

---

## V4 수정 사항 재검증 결과

### RESOLVED (코드에 정상 반영 확인)

| V4 위반 ID | 설명 | 검증 위치 | 상태 |
|-----------|------|----------|------|
| V4-P0-001 | Alembic env.py PostgreSQL 드라이버 | alembic/env.py:23-37 → SQLite+aiosqlite URL, render_as_batch=True | **RESOLVED** |
| V4-P0-002 | postgresql.JSON 5개소 | 0004_sqlite_initial.py → sa.JSON() 사용 (0001은 DEPRECATED 마킹) | **PARTIALLY** (아래 참조) |
| V4-P0-003 | now() server_default 29개소 | 0004_sqlite_initial.py → datetime('now') 사용 (0001~0003은 DEPRECATED) | **PARTIALLY** (아래 참조) |
| V4-P0-004 | 5테이블 스키마 ORM 불일치 | 0004_sqlite_initial.py: 27테이블 ORM과 1:1 매칭 확인 | **RESOLVED** |
| V4-P1-001 | secret_vault Redis 사잔코드 | secret_vault.py: REDIS_* 키 완전 제거, "Redis 사용하지 않는다" 코멘트 | **RESOLVED** |
| V4-P1-002 | system.py "PostgreSQL" 참조 | system.py:80 "Database(SQLite)", 115 "Database(SQLite)" | **RESOLVED** |
| V4-P1-003 | benchmark.py JSONResponse | benchmark.py: BenchmarkChartResponse(BaseModel) Pydantic 모델 반환 | **RESOLVED** |
| V4-P2-005 | data_preparer.py __import__ | data_preparer.py:7 `from sqlalchemy import text` 정상 import | **RESOLVED** |
| V3-P0-001 | data_preparer SQL created_at | data_preparer.py:49-52 → recorded_at 사용 확인 | **RESOLVED** |
| V3-P0-002 | indicator_persister recorded_at | indicator_persister.py:73 → `recorded_at=datetime.now(tz=timezone.utc)` | **RESOLVED** |
| V2-001 | ticker-params PUT 본문 불일치 | api_service.dart:1582-1587 → 개별 PUT 반복 확인 | **RESOLVED** |
| V1-001~010 | Session 1 수정 10건 | 전체 재검증 완료, 리그레션 없음 | **VERIFIED** |

### 추가 검증 (V5 신규 확인)

| 체인 | 검증 내용 | 상태 |
|------|----------|------|
| noqa/eslint-disable | src/ 전체에서 0건 | **PASS** |
| JSONResponse 사용 | endpoints/ 전체에서 0건 | **PASS** |
| Benchmark Pydantic → Flutter | BenchmarkChartResponse{items} → _getList(items 키 추출) → BenchmarkChartPoint.fromJson | **PASS** |
| AlertItem → Flutter AlertNotification | alert_type/title/created_at 중복 필드 + fromJson type/timestamp 폴백 | **PASS** |
| WebSocket 5채널 envelope | ws:positions/dashboard/trades/alerts/orderflow → {channel, data, count} → Flutter unwrap | **PASS** |
| Orderflow → ScalperTapeData | _update_ws_cache → obi/cvd/vpin/execution_strength/spread_bps/last_price/last_volume → fromJson | **PASS** |
| QuotaInfo KIS 필드 | system.py:170-179 → kis_calls_today/kis_limit → QuotaInfo.fromJson | **PASS** |
| SafetyInfo 전체 필드 | system.py:182-206 → 8개 필드 → SafetyInfo.fromJson | **PASS** |
| DashboardSummary 필드 | DashboardSummaryResponse → DashboardSummary.fromJson (18개 필드 매칭) | **PASS** |
| profit_target:history 체인 | EOD _s5_5 → write {month, target, actual} → endpoint 파싱 (year/month 분리) → Flutter MonthlyHistory | **PASS** |
| performance:monthly_pnl 체인 | EOD _s5_5 → write {pnl, updated_at} → profit_target.py:146 read "pnl" 키 | **PASS** |
| benchmark:spy_daily/sso_daily | benchmark_writer → write [{date, return_pct}] → benchmark.py → _build_period_items | **PASS** |
| alerts:list 체인 | trading_loop _record_alert → write → alerts.py/trading_loop _update_ws_cache read | **PASS** |

---

## 신규 위반 사항

### [V5-P0-001] Alembic 마이그레이션 체인이 SQLite 환경에서 실행 불가

- **발견 지점**: alembic/versions/0001, 0002, 0003
- **위반 유형**: 인프라 전환 미완료 (Alembic 실행 불가)
- **위반 상세**:
  - 마이그레이션 체인: `0001 → 0002 → 0003 → 0004`
  - `alembic upgrade head` 실행 시 0001부터 순차 실행되며:
    - 0001: `from sqlalchemy.dialects import postgresql` (import 자체는 성공하나), `postgresql.JSON()` 5개소 사용 → SQLite 연결에서 실행 시 실패
    - 0001: `sa.text("now()")` 26개소 → SQLite에 `now()` 함수 없음
    - 0002: `sa.text("now()")` 2개소, `sa.text("true")`/`sa.text("false")` → SQLite 비호환
    - 0003: `sa.text("now()")` 1개소
  - 0001~0003에 `[DEPRECATED]` 코멘트가 있으나, Alembic은 체인 의존성에 따라 모든 파일을 실행한다
  - 현재 시스템은 `Base.metadata.create_all()`로 테이블을 생성하므로 **런타임에는 영향 없다**
  - 그러나 `alembic upgrade head`, `alembic revision --autogenerate` 등 Alembic 명령이 완전히 비활성화된 상태이다
- **관련 파일**:
  - `alembic/versions/0001_v2_clean_initial_schema.py`
  - `alembic/versions/0002_add_universe_config.py`
  - `alembic/versions/0003_rebuild_articles_v2.py`
  - `alembic/versions/0004_sqlite_initial.py`
- **수정 방안**:
  - **(A)** 0004의 `down_revision`을 `None`으로 변경하고 0001~0003을 삭제하여 0004를 새로운 initial migration으로 만든다. 기존 DB가 있다면 `alembic stamp 0004`로 현재 상태를 마킹한다.
  - **(B)** 0001~0003을 SQLite 호환으로 전면 재작성한다 (비효율적이므로 A 권장).
- **상태**: OPEN
- **비고**: V4-P0-002/003에서 이관됨. 0004 생성으로 ORM↔마이그레이션 스키마 불일치는 해결되었으나, 체인 실행 문제는 여전히 존재한다.

---

### [V5-P1-001] EOD step 5가 존재하지 않는 캐시 키 `pnl:monthly`를 읽는다

- **발견 지점**: `src/orchestration/phases/eod_sequence.py:228`
- **위반 유형**: 캐시 키 불일치 (dead read → 항상 기본값 사용)
- **위반 상세**:
  - EOD `_s5()` (이익 목표 업데이트) 코드:
    ```python
    mp = await s.components.cache.read_json("pnl:monthly") or {"pnl": 0.0, "trades": 0}
    ts = pt.evaluate(mp)
    ```
  - `"pnl:monthly"` 키에 데이터를 쓰는 모듈이 코드베이스 전체에 존재하지 않는다
  - 실제 월간 PnL은 `_s5_5()`에서 `"performance:monthly_pnl"` 키에 `{"pnl": float, "updated_at": str}`로 기록한다
  - **결과**: `_s5()`의 `pt.evaluate()`는 항상 `{"pnl": 0.0, "trades": 0}`으로 평가한다. 로그에 `수익 목표: $0.00/$300.00`이 출력되며, 실제 달성률과 무관하게 항상 미달성으로 판정한다.
  - `_s5`가 `_s5_5`보다 먼저 실행되므로, `_s5_5`가 쓰는 `performance:monthly_pnl`을 읽어야 한다. 또는 `_s5`와 `_s5_5`의 실행 순서를 조정해야 한다.
- **관련 파일**:
  - `src/orchestration/phases/eod_sequence.py:228` (reader)
  - `src/orchestration/phases/eod_sequence.py:263-268` (writer: performance:monthly_pnl)
- **수정 지시**: `eod_sequence.py:228`의 `"pnl:monthly"`를 `"performance:monthly_pnl"`로 변경한다. 또는 `_s5`와 `_s5_5`의 순서를 바꿔 `_s5_5`가 먼저 실행되도록 한다. 후자가 더 올바른 수정이다 (데이터 기록 → 데이터 읽기 순서).
- **상태**: OPEN

---

### [V5-P2-001] 코드 파일 독스트링/코멘트에 "Redis" 참조 20+곳 잔존

- **발견 지점**: src/ 전체 (코드 실행에 영향 없는 독스트링/코멘트)
- **위반 유형**: 문서 정합성 위반 (신규 개발자 혼란 유발)
- **위반 상세**: 인메모리 캐시로 전환되었으나 다음 파일의 독스트링/코멘트에 "Redis" 언급이 잔존한다:
  - `src/safety/guards/quota_guard.py`: "Redis 기반 슬라이딩 윈도우", "_REDIS_KEY_PREFIX", "Redis 키를 생성한다" 등 (5곳+)
  - `src/strategy/exit/exit_strategy.py`: "Redis에 영속하여", "_REDIS_KEY_SCALES", "_REDIS_TTL" 등 (15곳+)
  - `src/risk/macro/net_liquidity.py`: "Redis 캐시 키" (1곳)
  - `src/strategy/stat_arb/stat_arb.py`: "Redis 캐시 클라이언트" (1곳)
  - `src/risk/gates/gap_risk.py`: "Redis에 영속하여", "_REDIS_KEY_PREFIX" 등 (3곳+)
  - `src/orchestration/phases/eod_sequence.py:202`: "Redis에 기록한다" (1곳)
  - `src/monitoring/endpoints/profit_target.py:386`: "Redis 캐시 키" (1곳)
  - `src/optimization/benchmark/benchmark_writer.py`: "Redis 키에 저장한다", "Redis에 기록한다" (3곳)
- **수정 지시**: 일괄 검색/치환으로 "Redis" → "캐시" 또는 "인메모리 캐시"로 변경. `_REDIS_KEY_PREFIX` → `_CACHE_KEY_PREFIX`, `_REDIS_TTL` → `_CACHE_TTL` 등 변수명도 함께 변경한다.
- **상태**: OPEN (이전 V3-010/011, V4-P3-002에서 이관 + 범위 확대)

---

### [V5-P2-002] article_persister.py / universe_persister.py 독스트링에 "PostgreSQL" 잔존

- **발견 지점**:
  - `src/orchestration/phases/article_persister.py:1`: "분류된 뉴스를 PostgreSQL articles 테이블에 영구 저장한다"
  - `src/common/universe_persister.py:23`: "유니버스 티커 설정을 PostgreSQL에 영속화한다"
- **위반 유형**: 문서 정합성 위반
- **위반 상세**: 실제 DB는 SQLite이다. 독스트링이 PostgreSQL을 언급하면 혼란을 유발한다.
- **수정 지시**: "PostgreSQL" → "SQLite" 또는 "DB"로 변경한다.
- **상태**: OPEN (V4-P3-001에서 이관 + 구체적 위치 특정)

---

### [V5-P2-003] 파일 크기 200줄 초과 (주요 파일)

- **발견 지점**: 프로젝트 전체
- **위반 유형**: CLAUDE.md SRP 규칙 위반
- **위반 상세**: V4-P2-001에서 이관. 주요 초과 파일:
  - `trading_loop.py`: 2055줄 (내부 함수 분해 완료됨, 외부 분리 필요)
  - `api_service.dart`: 1673줄
  - `eod_sequence.py`: 655줄
  - `analysis.py` (endpoint): 665줄
  - 기타 endpoint 파일 10+개가 400줄 이상
- **수정 지시**: 장기 리팩토링 과제. 현재 세션에서는 기록만 한다.
- **상태**: OPEN (V4-P2-001/003/004 이관)

---

### [V5-P3-001] benchmark_writer.py 독스트링/변수명에 "Redis" 참조

- **발견 지점**: `src/optimization/benchmark/benchmark_writer.py:1,4,15,49,55`
- **위반 유형**: 문서 정합성 위반 (기능적 영향 없음)
- **위반 상세**: 모듈 독스트링 "Redis 키에 저장한다", 코멘트 "Redis 키, 거래소 코드 매핑이다", 함수 독스트링 "Redis에 기록한다"
- **수정 지시**: "Redis" → "캐시"로 일괄 변경한다.
- **상태**: OPEN

---

## Flutter ↔ Backend 전수 연결 매칭 결과 (정상)

모든 주요 체인이 정합성을 유지하고 있다:

| 영역 | Flutter Model | Backend Response | 캐시 Writer | 상태 |
|------|--------------|------------------|------------|------|
| Dashboard Summary | DashboardSummary.fromJson (18필드) | DashboardSummaryResponse | trading_loop ws:dashboard | OK |
| System Status | SystemStatus.fromJson (quota+safety) | SystemStatusResponse | system.py 실시간 조회 | OK |
| Positions WS | Position.fromJson (unrealized_pnl_pct 변환) | ws:positions | trading_loop _update_ws_cache | OK |
| Trades WS | Trade.fromJson (action 변환) | ws:trades | trading_loop _update_ws_cache | OK |
| Alerts WS | AlertNotification.fromJson (type/timestamp 폴백) | ws:alerts | trading_loop _update_ws_cache | OK |
| Alerts REST | AlertNotification.fromJson | AlertListResponse {alerts} | _record_alert → alerts:list | OK |
| Orderflow WS | ScalperTapeData.fromJson (obi/cvd/vpin 중첩) | ws:orderflow | trading_loop OrderFlowAggregator | OK |
| Benchmark Comparison | BenchmarkComparison.fromJson {periods, summary} | BenchmarkComparisonResponse | benchmark_writer.py | OK |
| Benchmark Chart | BenchmarkChartPoint.fromJson | BenchmarkChartResponse {items} | benchmark_writer.py | OK |
| Profit Target Current | ProfitTargetStatus.fromJson (time_progress 중첩) | ProfitTargetCurrentResponse | profit_target:meta 캐시 | OK |
| Profit Target History | MonthlyHistory.fromJson (year/month 분리) | ProfitTargetHistoryEntry | EOD _s5_5 → profit_target:history | OK |
| Profit Target Projection | ProfitTargetProjection.fromJson (7필드) | ProfitTargetProjectionResponse | profit_target:meta + performance:monthly_pnl | OK |
| Risk Dashboard | RiskDashboardData.fromJson | RiskDashboardResponse | 실시간 gate 계산 | OK |
| Tax Status | TaxStatus.fromJson | TaxStatusResponse | 실시간 계산 | OK |
| FX Status | FxStatus.fromJson | FxStatusResponse (usd_krw_rate) | fx_scheduler → fx:current | OK |
| Slippage | SlippageStats.fromJson | SlippageStatsResponse | 실시간 DB 조회 | OK |
| Ticker Params PUT | setTickerOverride 개별 PUT | TickerParamsUpdateRequest {param_name, value} | N/A | OK |
| Port Sync | server_launcher.dart 동적 감지 | api_server.py 포트 파일 | data/server_port.txt | OK |

### Raw SQL vs ORM 정합성

| 파일 | SQL 쿼리 | ORM 모델 | 상태 |
|------|----------|---------|------|
| data_preparer._fetch_trades | `SELECT ... created_at FROM trades WHERE created_at ...` | Trade.created_at | OK |
| data_preparer._fetch_indicators | `SELECT ... recorded_at FROM indicator_history WHERE recorded_at ...` | IndicatorHistory.recorded_at | OK |
| indicator_persister | `recorded_at=datetime.now(tz=timezone.utc)` | IndicatorHistory.recorded_at | OK |

---

## 캐시 Writer ↔ Reader 체인 전수 검증

| 캐시 키 | Writer | Reader | 일치 여부 |
|--------|--------|--------|----------|
| `alerts:list` | trading_loop._record_alert + trading_control._record_alert | alerts.py, trading_loop ws:alerts | OK |
| `alerts:read` | alerts.py mark_alert_read | alerts.py _get_read_ids, trading_loop ws:alerts | OK |
| `benchmark:spy_daily` | benchmark_writer.write_benchmark_data | benchmark.py _build_period_items | OK |
| `benchmark:sso_daily` | benchmark_writer.write_benchmark_data | benchmark.py _build_period_items | OK |
| `charts:daily_returns` | chart_data_writer EOD | benchmark.py _build_period_items (AI 수익률) | OK |
| `profit_target:history` | EOD _s5_5 _upsert_history_entry | profit_target.py get_target_history | OK |
| `profit_target:meta` | profit_target.py set_monthly_target/set_aggression | profit_target.py get_current, EOD _s5_5 | OK |
| `performance:monthly_pnl` | EOD _s5_5 _write_monthly_pnl_cache | profit_target.py _read_monthly_pnl | OK |
| **`pnl:monthly`** | **작성자 없음** | **EOD _s5 (eod_sequence.py:228)** | **FAIL** → V5-P1-001 |
| `pnl:daily` | trading_loop | EOD _s2 | OK |
| `pnl:history:{date}` | EOD _s2 | N/A (보관용) | OK |
| `trades:today` | trading_loop | EOD _s2, _s5_5, profit_target.py fallback | OK |
| `feedback:latest` | EOD _s4 | feedback endpoint | OK |
| `ws:positions` | trading_loop _update_ws_cache | WebSocketManager → Flutter | OK |
| `ws:dashboard` | trading_loop _update_ws_cache | WebSocketManager → Flutter | OK |
| `ws:trades` | trading_loop _update_ws_cache | WebSocketManager → Flutter | OK |
| `ws:alerts` | trading_loop _update_ws_cache | WebSocketManager → Flutter | OK |
| `ws:orderflow` | trading_loop _update_ws_cache | WebSocketManager → Flutter | OK |
| `fx:current` | fx_scheduler | fx.py endpoints | OK |
| `exit:scales` | exit_strategy | exit_strategy (복원) | OK |
| `exit:peak_pnl` | exit_strategy | exit_strategy (복원) | OK |
| `gap_block:*` | gap_risk | gap_risk (복원) | OK |

---

## CLAUDE.md 규칙 준수 상태

| 규칙 | 상태 | 비고 |
|------|------|------|
| 한국어 주석/독스트링 | **PASS** | 전체 Python/Dart 코드 확인, 영어 코멘트 없음 |
| Python 타입 힌트 | **PASS** | 모든 함수 파라미터/반환 타입 명시 |
| No Workarounds (noqa/ts-ignore 등) | **PASS** | src/ 전체 noqa 0건 확인 |
| Pydantic BaseModel 반환 | **PASS** | 모든 endpoint에서 BaseModel 반환, JSONResponse 0건 |
| try/except + logging | **PASS** | 모든 public 메서드에 예외 처리 + 로깅 |
| get_logger(__name__) | **PASS** | 전체 모듈 확인 |
| from __future__ import annotations | **PASS** | 전체 모듈 확인 |
| SRP / 파일 크기 | **FAIL** | 15+개 파일 200줄 초과 (V5-P2-003) |
| Docker 의존 제거 | **PASS** | 코드 레벨에서 Docker 의존 없음 |
| Redis → 인메모리 전환 | **PARTIAL** | 코드 정상, 독스트링 20+곳 Redis 잔존 (V5-P2-001) |
| PostgreSQL → SQLite 전환 | **PARTIAL** | 코드 정상, 독스트링 2곳 + 에이전트 문서에 PostgreSQL 잔존 |

---

## 리더에게 전달할 수정 사항

### 최우선 (P0)
1. **Alembic 체인 정리**: 0004의 `down_revision`을 `None`으로 변경하고, 0001~0003을 삭제(또는 별도 archive 디렉토리로 이동). 기존 DB는 `alembic stamp 0004`로 마킹한다.

### 즉시 수정 (P1)
2. **EOD step 5 캐시 키 수정**: `eod_sequence.py:228`의 `"pnl:monthly"` → `"performance:monthly_pnl"`로 변경. 그리고 `_s5_5`를 `_s5`보다 먼저 실행하도록 순서 조정 (또는 _s5에서 직접 trades 합산).

### 품질 개선 (P2)
3. **Redis 독스트링 일괄 변경**: 20+곳의 "Redis" → "캐시" / "인메모리 캐시" 변경
4. **PostgreSQL 독스트링 수정**: article_persister.py, universe_persister.py "PostgreSQL" → "SQLite" 또는 "DB"
5. **파일 크기 초과**: 장기 리팩토링 과제로 기록

### 기록 (P3)
6. **benchmark_writer.py 독스트링**: "Redis" → "캐시" 변경

---

## Phase 완료 체크리스트

- [x] V4 수정사항 정합성 재검증 완료 — **10건 RESOLVED, 리그레션 없음**
- [x] 캐시 Writer↔Reader 체인 전수 검증 — **18개 키 중 17개 정상, 1개 P1 위반**
- [x] Flutter↔Backend 모델 필드 매칭 — **20+ 영역 모두 정합성 확인**
- [x] WebSocket 5채널 메시지 구조 — **정상 (envelope unwrap + 데이터 변환 확인)**
- [x] Raw SQL↔ORM 정합성 — **3개 쿼리 모두 정상**
- [x] Alembic↔ORM 스키마 정합성 — **0004는 27테이블 ORM과 일치, 체인 문제 잔존**
- [x] CLAUDE.md 규칙 준수 — **핵심 규칙 모두 PASS, 파일 크기/독스트링 잔존**
- [ ] 미해결 P0/P1 위반 0건 — **P0 1건, P1 1건 OPEN**

---

## 이전 세션 대비 전체 진행 현황

| 세션 | P0 | P1 | P2 | P3 | 합계 | 상태 |
|------|----|----|----|----|------|------|
| Session 3 (V1) | 3→0 | 2→0 | 3→1 | 3→0 | 11→1 | 10 해결 |
| Session 4 (V2) | 1→0 | 2→0 | 0 | 2→0 | 5→0 | 5 해결 |
| Session 4b (refactoring) | 0 | 0 | -4 | -2 | -6 | 리팩토링 |
| V3 감사 | 4→2 | 3→1 | 3 | 2 | 12→8 | 4 해결, V4 이관 |
| V4 감사 | 4→1 | 3→0 | 5→3 | 2→1 | 14→5 | 9 해결 |
| **V5 감사** | **1** | **1** | **3** | **1** | **6** | **신규 1건 발견 (P1-001)** |

**총 누적**: P0 1건 + P1 1건 + P2 3건 + P3 1건 = **6건 OPEN**
(이 중 P0은 Alembic 체인 문제로 런타임 영향 없음, P1은 EOD 로직 정확성 문제로 수정 필요)
