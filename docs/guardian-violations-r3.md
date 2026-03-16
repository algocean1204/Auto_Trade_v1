# Guardian Violation Report -- Round 3 Audit

**감사일시**: 2026-03-15
**감사 범위**: 신규 6파일 + 수정 6파일 + 관련 엔드포인트 3파일 + Flutter 모델 3파일
**총 위반 건수**: 23건 (P0: 2, P1: 7, P2: 14)

---

## P0 -- 즉시 수정 필수 (운영 장애 가능)

### [V-R3-001] P0: tax_writer.py SQLite 함수를 PostgreSQL에서 사용
- **발견 위치**: `src/strategy/tax/tax_writer.py:218`
- **위반 유형**: DB 호환성 결함
- **위반 내용**: `datetime(s.created_at, '+30 days')` 는 SQLite 전용 함수이다. 프로젝트는 PostgreSQL 17을 사용하므로 이 SQL은 런타임에서 `ProgrammingError`를 발생시킨다.
- **원본 요구사항**: MEMORY.md에 "PostgreSQL 17 + pgvector" 명시
- **수정 지시**: `datetime(s.created_at, '+30 days')` 를 PostgreSQL 호환 `s.created_at + INTERVAL '30 days'` 로 변경해야 한다.
- **상태**: OPEN

### [V-R3-002] P0: EOD _TOTAL_STEPS 값과 실제 단계 수 불일치
- **발견 위치**: `src/orchestration/phases/eod_sequence.py:18`
- **위반 유형**: 데이터 정합성 결함
- **위반 내용**: `_TOTAL_STEPS = 25` 로 선언되어 있으나, 루프 내 25개 단계 + `_s11_telegram` 1개 = 총 26개 단계가 `r.steps_completed += 1`을 호출한다. 텔레그램 보고서에서 "완료: 26/25"로 표시되어 사용자에게 혼란을 줄 수 있으며, 정상 실행 시에도 단계 완료율이 100%를 초과한다.
- **원본 요구사항**: [CRITICAL] EOD step numbering must be consistent (25 steps)
- **수정 지시**: `_TOTAL_STEPS = 26` 으로 변경하거나, `_s11_telegram` 내부의 `r.steps_completed += 1` (line 899)을 제거하여 25단계로 통일해야 한다.
- **상태**: OPEN

---

## P1 -- Phase 완료 전 수정 필수

### [V-R3-003] P1: status_writer.py에서 cache 파라미터 타입이 object
- **발견 위치**: `src/agents/status_writer.py:19,43,83`
- **위반 유형**: 타입 안전성 위반 + type: ignore 남용
- **위반 내용**: 3개 함수 모두 `cache: object` 로 선언하고 `# type: ignore[union-attr]` 로 5개소에서 타입 체크를 우회한다. 프로젝트 규약 "No Workarounds"에 따르면 `type: ignore` 는 타입 에러 우회로 간주된다. `CacheClient` 타입을 직접 사용하거나 Protocol을 정의해야 한다.
- **원본 요구사항**: No Workarounds 규칙, `type: ignore` 사용 금지
- **수정 지시**: `cache: object` 를 `cache: CacheClient` 로 변경하고 import를 추가하여 `type: ignore` 5건을 제거해야 한다.
- **상태**: OPEN

### [V-R3-004] P1: slippage_aggregator.py에서 cache 파라미터 타입이 object
- **발견 위치**: `src/orchestration/phases/slippage_aggregator.py:170`
- **위반 유형**: 타입 안전성 위반 + type: ignore 남용
- **위반 내용**: `aggregate_and_write(cache: object)` 로 선언하고 `type: ignore[union-attr]` 3건으로 타입 체크를 우회한다.
- **수정 지시**: `cache: CacheClient` 로 변경하고 import 추가, `type: ignore` 3건 제거.
- **상태**: OPEN

### [V-R3-005] P1: dependency_injector.py에서 SlippageTracker 비공개 속성 직접 할당
- **발견 위치**: `src/orchestration/init/dependency_injector.py:409`
- **위반 유형**: No Workarounds 위반 (내부 구현 직접 접근)
- **위반 내용**: `om._slippage_tracker = tracker  # type: ignore[union-attr]` 로 비공개(_) 속성에 직접 할당한다. 이는 "Ignoring intended APIs/interfaces and directly accessing internal implementations" 워크어라운드 패턴이다.
- **원본 요구사항**: No Workarounds -- Proper Integration Required
- **수정 지시**: `OrderManager.__init__` 에 `slippage_tracker` 파라미터가 이미 있으므로 (line 82), `_inject_f5_executor` 에서 생성 시점에 주입하거나, F8 주입 순서를 F5 이전으로 변경하거나, 공개 setter 메서드를 추가해야 한다.
- **상태**: OPEN

### [V-R3-006] P1: Flutter slippage_models.dart 필드명 불일치
- **발견 위치**: `dashboard/lib/models/slippage_models.dart:49,61`
- **위반 유형**: 프론트엔드-백엔드 스키마 불일치
- **위반 내용**: Flutter `OptimalHour.fromJson`은 `avg_slippage_pct` 키를 읽지만 (line 61), 백엔드 `SlippageHourEntry` 응답 모델은 `avg_slippage` 필드를 반환한다 (slippage.py:62). 또한 `slippage_aggregator.py:83`에서도 `avg_slippage` 키로 기록한다. Flutter에서 항상 기본값 0이 표시될 것이다.
- **원본 요구사항**: [CRITICAL] Flutter providers must match API response schemas
- **수정 지시**: Flutter의 `OptimalHour.fromJson`에서 `json['avg_slippage_pct']` 를 `json['avg_slippage']` 로 변경하거나, 백엔드 `SlippageHourEntry.avg_slippage` 필드명을 `avg_slippage_pct`로 통일해야 한다.
- **상태**: OPEN

### [V-R3-007] P1: Redis 명칭이 코드에 잔존
- **발견 위치**: 
  - `src/strategy/exit/exit_strategy.py:232-234` (`_REDIS_KEY_SCALES`, `_REDIS_KEY_PEAK_PNL`, `_REDIS_TTL`)
  - `src/risk/gates/gap_risk.py:23` (`_REDIS_KEY_PREFIX`)
  - `src/safety/guards/quota_guard.py:20,87` (`_REDIS_KEY_PREFIX`)
  - `src/websocket/storage/redis_publisher.py:76` (`RedisPublisher` 클래스명)
  - `src/websocket/manager.py:26,46` (`RedisPublisher` 임포트)
  - `src/websocket/storage/__init__.py:3,6` (`RedisPublisher` 공개 API)
- **위반 유형**: 네이밍 불일치 / 아키텍처 혼란
- **위반 내용**: 프로젝트가 Redis에서 인메모리 캐시로 전환되었지만 변수명/클래스명에 "Redis"가 11개소 잔존한다. 코드 기능은 정상이나 유지보수성을 해친다.
- **원본 요구사항**: [CRITICAL] No Redis references should remain anywhere
- **수정 지시**: `_REDIS_KEY_*` → `_CACHE_KEY_*`, `_REDIS_TTL` → `_CACHE_TTL`, `RedisPublisher` → `CachePublisher` 등으로 리네이밍해야 한다.
- **상태**: OPEN

### [V-R3-008] P1: registry.py 모듈 에이전트 수 주석과 실제 불일치
- **발견 위치**: `src/agents/registry.py:1,41`
- **위반 유형**: 문서 정합성
- **위반 내용**: docstring에 "시스템 모듈(23개)"라 명시되어 있으나, `_MODULE_AGENTS` 튜플에는 실제 25개 AgentMeta가 정의되어 있다 (crawling 3 + analysis 7 + decision 3 + execution 3 + safety 4 + monitoring 5 = 25). 전체 합산도 "28개"가 아닌 30개이다.
- **수정 지시**: docstring의 숫자를 실제 등록 수와 일치하도록 "시스템 모듈(25개)" 및 전체 "30개"로 수정해야 한다.
- **상태**: OPEN

### [V-R3-009] P1: Flutter agent_models.dart 폴백 데이터와 registry.py 실제 데이터 불일치
- **발견 위치**: `dashboard/lib/models/agent_models.dart:169-370`
- **위반 유형**: 프론트엔드-백엔드 데이터 불일치
- **위반 내용**: Flutter의 `AgentData.defaultTeams` 폴백에는 analysis 팀이 5명(news_classifier, mlx_classifier, regime_detector, claude_client, knowledge_manager)이지만 백엔드 registry.py의 analysis 팀은 8명(+news_analyst, key_news_filter, situation_tracker)이다. decision 팀도 Flutter는 3명, 백엔드는 7명이다. 백엔드 API가 정상 응답하면 문제없지만, API 오류 시 폴백 데이터가 부정확하다.
- **수정 지시**: `AgentData.defaultTeams`를 백엔드 registry와 동기화하거나, 폴백 데이터 사용 시 경고를 표시해야 한다.
- **상태**: OPEN

---

## P2 -- 다음 Phase 전 수정 권장

### [V-R3-010] P2: eod_sequence.py 파일 크기 918줄
- **발견 위치**: `src/orchestration/phases/eod_sequence.py`
- **위반 유형**: SRP / 파일 크기 위반 (한도: 300줄)
- **위반 내용**: 918줄로 한도의 3배를 초과한다. 25개 EOD 단계가 단일 파일에 밀집되어 있다.
- **수정 지시**: 관련 단계를 그룹별로 분리해야 한다 (예: eod_pnl_steps.py, eod_indicator_steps.py, eod_macro_steps.py, eod_cleanup_steps.py).
- **상태**: OPEN

### [V-R3-011] P2: trading_loop.py 파일 크기 2227줄
- **발견 위치**: `src/orchestration/loops/trading_loop.py`
- **위반 유형**: SRP / 파일 크기 위반 (한도: 300줄)
- **위반 내용**: 2227줄로 한도의 7.4배를 초과한다. `_run_beast_entry` (166줄), `_run_entry_stage` (310줄), `_update_ws_cache` (241줄), `_compute_position_multipliers` (147줄) 등 거대 함수가 다수 존재한다.
- **수정 지시**: 각 매매 전략(beast, pyramid, wick_catcher)과 WS 캐시 갱신을 별도 모듈로 분리해야 한다.
- **상태**: OPEN

### [V-R3-012] P2: order_manager.py 파일 크기 456줄
- **발견 위치**: `src/executor/order/order_manager.py`
- **위반 유형**: SRP / 파일 크기 위반 (한도: 300줄)
- **위반 내용**: 456줄. `_sniper_execute` (82줄), `execute_buy` (53줄), `execute_sell` (51줄), `_record_slippage` (53줄) 등이 50줄 한도를 초과한다.
- **수정 지시**: 스나이퍼 실행 로직과 슬리피지 기록 로직을 별도 atomic 모듈로 분리해야 한다.
- **상태**: OPEN

### [V-R3-013] P2: tax.py 엔드포인트 파일 크기 418줄
- **발견 위치**: `src/monitoring/endpoints/tax.py`
- **위반 유형**: SRP / 파일 크기 위반 (한도: 300줄)
- **위반 내용**: 418줄. `_build_tax_status_from_cache` (67줄), `get_tax_status` (65줄), `get_tax_report` (55줄) 등이 50줄 한도를 초과한다.
- **수정 지시**: 레거시 변환 로직을 별도 헬퍼 파일로 분리하거나, 레거시 지원을 제거해야 한다.
- **상태**: OPEN

### [V-R3-014] P2: agents.py 엔드포인트 파일 크기 315줄
- **발견 위치**: `src/monitoring/endpoints/agents.py`
- **위반 유형**: 파일 크기 위반 (한도: 300줄)
- **위반 내용**: 315줄로 한도를 소폭 초과한다.
- **수정 지시**: Pydantic 응답 모델을 schemas/ 하위로 분리하면 한도 이내가 된다.
- **상태**: OPEN

### [V-R3-015] P2: tax_writer.py 파일 크기 317줄
- **발견 위치**: `src/strategy/tax/tax_writer.py`
- **위반 유형**: 파일 크기 위반 (한도: 300줄)
- **위반 내용**: 317줄로 한도를 소폭 초과한다. compute_tax_status, compute_tax_report, compute_tax_harvest 3개 공개 함수가 하나의 파일에 있다.
- **수정 지시**: harvest 관련 로직을 별도 파일로 분리하면 한도 이내가 된다.
- **상태**: OPEN

### [V-R3-016] P2: econ_calendar.py generate_calendar 함수 38줄
- **발견 위치**: `src/indicators/misc/econ_calendar.py:131`
- **위반 유형**: SRP Atomic 함수 크기 위반 (한도: 30줄)
- **위반 내용**: `generate_calendar` 함수가 38줄이다. 여러 이벤트 타입의 extend 호출이 나열되어 있다.
- **수정 지시**: 이벤트 수집 루프를 별도 _collect_all_events 함수로 추출해야 한다.
- **상태**: OPEN

### [V-R3-017] P2: status_writer.py record_agent_complete 함수 38줄
- **발견 위치**: `src/agents/status_writer.py:43`
- **위반 유형**: SRP Atomic 함수 크기 위반 (한도: 30줄)
- **위반 내용**: `record_agent_complete` (38줄), `record_agent_error` (34줄) 모두 30줄 한도를 초과한다.
- **수정 지시**: status dict와 history_entry dict 구성을 별도 헬퍼 함수로 추출해야 한다.
- **상태**: OPEN

### [V-R3-018] P2: eod_sequence.py 다수 함수 50줄 한도 초과
- **발견 위치**: `src/orchestration/phases/eod_sequence.py` 내 `_s2_7` (70줄), `_s7_2` (75줄), `_s7_3b` (57줄), `_s9` (53줄)
- **위반 유형**: SRP Manager 함수 크기 위반 (한도: 50줄)
- **위반 내용**: 4개 EOD 단계 함수가 50줄 매니저 한도를 초과한다.
- **수정 지시**: 각 단계의 데이터 구성/계산 로직을 atomic 헬퍼 함수로 추출해야 한다.
- **상태**: OPEN

### [V-R3-019] P2: slippage.py get_slippage_stats 함수 58줄
- **발견 위치**: `src/monitoring/endpoints/slippage.py:100`
- **위반 유형**: SRP Manager 함수 크기 위반 (한도: 50줄)
- **위반 내용**: tracker 직접 조회 경로와 캐시 조회 경로가 하나의 함수에 혼재되어 58줄이다.
- **수정 지시**: tracker 조회와 캐시 조회를 각각 별도 헬퍼로 분리해야 한다.
- **상태**: OPEN

### [V-R3-020] P2: SlippageStats by_hour 필드 타입 불일치
- **발견 위치**: `dashboard/lib/models/slippage_models.dart:12` vs `src/monitoring/endpoints/slippage.py:52`
- **위반 유형**: 프론트엔드-백엔드 스키마 불일치
- **위반 내용**: Flutter `SlippageStats.byHour`는 `Map<String, double>` 이지만, 백엔드 `slippage:stats`의 `by_hour` 값은 `{"avg_bps": float, "count": int}` dict이다 (slippage_aggregator.py:63). Flutter에서 파싱 시 타입 캐스트 에러가 발생할 수 있다.
- **수정 지시**: Flutter 모델을 중첩 Map으로 변경하거나, 백엔드에서 by_hour를 float 값으로 단순화해야 한다.
- **상태**: OPEN

### [V-R3-021] P2: slippage:hours 백엔드에서 best_execution_hour가 캐시에서만 조회됨
- **발견 위치**: `src/monitoring/endpoints/slippage.py:130`
- **위반 유형**: 기능 불완전
- **위반 내용**: SlippageTracker 직접 조회 경로에서 `best_execution_hour`가 항상 하드코딩 10으로 반환된다. 캐시 경로에서만 `slippage:stats`의 `best_execution_hour` 값을 사용한다. SlippageTracker에 시간대별 분석 기능이 없어 인메모리 경로에서는 정확한 최적 시간대가 반환되지 않는다.
- **수정 지시**: SlippageTracker에 시간대별 분석 메서드를 추가하거나, 캐시 데이터를 항상 우선 참조하도록 조회 순서를 변경해야 한다.
- **상태**: OPEN

### [V-R3-022] P2: Flutter agent_models.dart monitoring 팀 benchmark 에이전트 ID 불일치
- **발견 위치**: `dashboard/lib/models/agent_models.dart:348`
- **위반 유형**: 프론트엔드-백엔드 ID 불일치
- **위반 내용**: Flutter 폴백에서 monitoring 팀의 벤치마크 에이전트 ID가 `benchmark_comparison` 이지만 백엔드 registry.py에서는 `benchmark`이다 (registry.py:163). API 정상 응답 시에는 문제없지만, 폴백 시 ID 불일치로 상세 조회가 실패한다.
- **수정 지시**: Flutter 폴백의 `benchmark_comparison` 을 `benchmark` 으로 수정해야 한다.
- **상태**: OPEN

### [V-R3-023] P2: news_pipeline.py 파일 크기 716줄
- **발견 위치**: `src/orchestration/phases/news_pipeline.py`
- **위반 유형**: SRP / 파일 크기 위반 (한도: 300줄)
- **위반 내용**: 716줄로 한도의 2.4배를 초과한다. 크롤링, 분류, 캐싱, 텔레그램 전송이 모두 단일 파일에 혼재되어 있다.
- **수정 지시**: `_cache_classified_results` (약 100줄), `_to_flutter_article`/`_build_summary` (약 100줄)를 별도 모듈로 분리해야 한다.
- **상태**: OPEN

---

## 캐시 키 정합성 검증 결과

아래 Writer→Reader 체인은 키명이 일치함을 확인하였다:

| Writer | 캐시 키 | Reader | 일치 여부 |
|---|---|---|---|
| whale_detector.py | `orderflow:whale` | trading_loop → ws cache | OK |
| whale_detector.py | `orderflow:history:{ticker}` | trading_loop | OK |
| econ_calendar.py | `macro:calendar` | indicators.py 엔드포인트 | OK |
| status_writer.py | `agent:status:{id}` | agents.py:206 | OK |
| status_writer.py | `agent:history:{id}` | agents.py:275 | OK |
| tax_writer.py | `tax:status` | tax.py:252 | OK |
| tax_writer.py | `tax:report:{year}` | tax.py:325 | OK |
| tax_writer.py | `tax:harvest` | tax.py:408 | OK |
| slippage_aggregator.py | `slippage:stats` | slippage.py:136 | OK |
| slippage_aggregator.py | `slippage:hours` | slippage.py:171 | OK |
| order_manager.py | `slippage:raw` | slippage_aggregator.py:176 | OK |
| trading_loop.py | `orderflow:history` | order_flow endpoint | OK |

## Flutter-Backend 필드 매핑 검증 결과

| API 응답 필드 | Flutter fromJson 키 | 일치 여부 | 비고 |
|---|---|---|---|
| tax:status.summary.* | TaxSummary.fromJson | OK | 8필드 전부 일치 |
| tax:status.remaining_exemption.* | RemainingExemption.fromJson | OK | 4필드 전부 일치 |
| tax:harvest[].unrealized_loss_usd | TaxHarvestSuggestion.fromJson | OK | 레거시 폴백 포함 |
| tax:harvest[].potential_tax_saving_krw | TaxHarvestSuggestion.fromJson | OK | 레거시 폴백 포함 |
| slippage:stats.avg_slippage_pct | SlippageStats.fromJson | OK | |
| slippage:hours[].avg_slippage | OptimalHour.fromJson (avg_slippage_pct) | **MISMATCH** | V-R3-006 |
| agents teams[].agents[].* | AgentInfo.fromJson | OK | |

## Korean Docstring 검증 결과

모든 신규 파일(6개)의 함수 docstring이 한국어로 작성되어 있음을 확인하였다. 영어 주석은 발견되지 않았다.

## DI Wiring 검증 결과

- `whale_detector.py`: DI 등록 없음 (trading_loop에서 직접 import 호출) -- 정상 (캐시만 사용하는 유틸리티)
- `econ_calendar.py`: DI 등록 없음 (eod_sequence에서 직접 import 호출) -- 정상
- `status_writer.py`: DI 등록 없음 (news_pipeline/continuous_analysis에서 직접 import) -- 정상
- `tax_writer.py`: DI 등록 없음 (eod_sequence에서 직접 import) -- 정상
- `slippage_aggregator.py`: DI 등록 없음 (eod_sequence에서 직접 import) -- 정상
- `SlippageTracker → OrderManager`: dependency_injector.py:407-409에서 F8에서 F5의 비공개 속성에 주입 -- **V-R3-005** 위반

---

## 요약

| 심각도 | 건수 | 상태 |
|---|---|---|
| P0 (즉시 수정) | 2 | 모두 OPEN |
| P1 (Phase 완료 전) | 7 | 모두 OPEN |
| P2 (다음 Phase 전) | 14 | 모두 OPEN |
| **합계** | **23** | |

**P0 우선 수정 필수 항목:**
1. `tax_writer.py:218` -- SQLite `datetime()` → PostgreSQL `INTERVAL` 문법 변경
2. `eod_sequence.py:18` -- `_TOTAL_STEPS` 값을 실제 단계 수와 일치시키기
