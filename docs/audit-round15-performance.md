# 전수조사 Round 15: 성능 최적화 보고서

**일시**: 2026-03-19
**범위**: Python 서버 + Flutter 대시보드 전반

---

## 수정 완료 (3건)

### P0-1. `trades:today` 캐시 중복 조회 (trading_loop.py)

**문제**: `_compute_position_multipliers()`에서 `trades:today`를 **3회 연속** 조회했다.
- 1289행: DailyLossLimit 재구축용
- 1311행: HouseMoney 실현 PnL 합산용
- 1333행: LosingStreak 업데이트용

추가로 `_run_entry_stage()`의 for 루프 안에서 Kelly Criterion 계산 시 **매 티커마다** `trades:today`를 재조회했다 (1730행). 유니버스 10종목 기준 반복 10회.

총합: 루프 1회 반복당 **최소 13회** → **1회**로 감소 (3 + 10 → 1).

**수정**: 함수 시작 시 1회만 조회하여 `_trades_today` 변수에 저장, 3개 모듈(DailyLossLimit, HouseMoney, LosingStreak)에서 재사용. Kelly Criterion도 루프 밖에서 `_kelly_sell_trades`를 사전 계산.

**파일**: `src/orchestration/loops/trading_loop.py`

### P0-2. 토큰 추적 파일 I/O 병목 (token_tracker.py)

**문제**: `record_usage()` / `record_error()` 호출마다 `_save_to_file()`이 실행되어 **매 AI API 호출마다 동기 디스크 쓰기**가 발생했다. 30분 연속 분석 사이클에서 Claude Opus + Sonnet 호출이 수십 회 발생하면 누적 I/O가 상당했다.

**수정**: 30초 간격 스로틀 (`_save_throttled()`) 도입. 인메모리 데이터 정합성은 유지하되, 파일 저장은 최소 30초 간격으로만 수행. `flush()` 함수를 추가하여 EOD 등 명시적 시점에서 강제 저장 가능.

**파일**: `src/common/token_tracker.py`

### P1-1. 차트 데이터 불필요한 캐시 재조회 (chart_data_writer.py)

**문제**: `write_chart_data()`에서 `charts:cumulative_returns`를 캐시에 쓴 직후 **동일 키를 다시 읽어** drawdown을 계산했다 (218~221행). 이미 인메모리에 `cumulative` 리스트가 있는 상태에서 불필요한 JSON 직렬화+역직렬화 왕복이 발생했다.

**수정**: 캐시 재조회를 제거하고 인메모리 `cumulative` 변수를 직접 `_compute_drawdown_detail()`에 전달.

**파일**: `src/optimization/feedback/chart_data_writer.py`

---

## 보고만 (수정 불필요 또는 미세 최적화)

### A. N+1 쿼리 패턴 (Python)

| 위치 | 패턴 | 영향도 | 비고 |
|---|---|---|---|
| `eod_sequence._s2_6` | for ticker: `builder.build()` + `persist_indicator_bundle()` | **낮음** | EOD 1회, 1~5종목. asyncio.gather 가능하나 DB 세션 분리 필요 |
| `eod_sequence._s9` | for key: `cache.delete()` (8~15회) | **낮음** | 인메모리 캐시이므로 실질적 비용 무시할 수준 |
| `trading_loop._accumulate_orderflow_history` | for item: `cache.atomic_list_append()` | **낮음** | 보유 포지션 수(1~5개) 만큼만 순회 |
| `trading_loop._update_ws_cache` orderflow | for ticker: `aggregator.aggregate()` + `cache.read_json()` | **낮음** | 보유 포지션 수(1~5개) |
| `trading_loop._update_ws_cache` indicators | for ticker: `builder.build()` | **낮음** | 보유 포지션 수(1~5개) |
| `eod_sequence._s7_0` | for change: `session.add()` | **낮음** | 단일 세션 내 add이므로 N+1이 아님 (올바른 패턴) |

### B. Flutter 불필요 반복 API 호출

| Provider | 주기 | API 수 | 판정 |
|---|---|---|---|
| `DashboardProvider` | 3초 | 4개 병렬 | **적정** — 3초는 실시간 대시보드에 합리적, Future.wait으로 병렬화됨 |
| `TradingControlProvider` | 10초 | 1개 | **적정** |
| `TokenProvider` | 30초 | 1개 | **적정** |
| `EmergencyProvider` | 30초 | 1개 | **적정** |
| `CrawlProgressProvider` | 1.5초 | 1개 | **적정** — 크롤링 진행 중에만 활성 |

### C. 캐시 TTL 검토

| 캐시 키 | TTL | 판정 |
|---|---|---|
| `ws:*` | 30초 | **적정** — WS 채널 갱신 주기와 일치 |
| `trades:today` | 24시간 | **적정** — 일일 단위 리셋 |
| `charts:*` | 90일 | **적정** — 장기 차트 보관 |
| `pnl:history:{date}` | 30일 | **적정** — DB에도 영속 |
| `dashboard:buy_power` | 60초 | **적정** — 매수력 갱신 주기 |
| `orderflow:snapshot` | 30초 | **적정** |

### D. 비효율적 데이터 구조/알고리즘

- **O(n) 순회**: `_record_alert()`에서 `alerts:list` read → append → write 패턴. 100건 제한이므로 무해하나 `atomic_list_append(max_size=100)`으로 단순화 가능.
- **리스트 복사**: `eod_sequence._s2_7`에서 `existing_daily` 리스트를 90일로 슬라이싱. O(90)이므로 무해.
- **정렬**: `_s2_7`의 `existing_daily.sort()` — 최대 90개 원소이므로 무해.

### E. 비동기 처리 효율성

- **순차 실행 가능**: `_prepare_session_context()`에서 VIX 조회 → 레짐 감지 → 콘탱고 감지가 순차. VIX→레짐은 의존관계가 있으나 콘탱고는 독립적. 병렬화 가능하나 호출 1회씩이므로 효과 미미.
- **독립 EOD 단계 병렬화**: Phase 1(데이터 수집)의 _s2_1~_s2_8 중 일부는 독립적이나 ctx 딕셔너리 공유로 순차 강제. 아키텍처 변경이 필요하여 미수정.

### F. 메모리 사용

- **인메모리 캐시 크기 제한 없음**: `CacheClient._store`는 dict 크기에 제한이 없으나, 실행 중 캐시 키는 ~200개 수준이고 `_cleanup_expired()`가 60초 주기로 만료 키를 정리하므로 현실적으로 문제 없음.
- **`atomic_list_append` max_size**: 모든 호출에서 `max_size`가 설정되어 있어 무한 증가 방지됨 (360, 100, 50 등).
- **로그 메시지**: 대용량 데이터(trades 리스트 전체 등)를 로그에 포함하는 패턴은 발견되지 않음. `logger.debug` 수준에서만 세부 정보 출력.

---

## 요약

| 구분 | 건수 | 주요 내용 |
|---|---|---|
| **수정 완료** | 3건 | trades:today 중복 조회(13→1회), 토큰 파일 I/O 스로틀, 차트 캐시 재조회 제거 |
| **보고만 (미세최적화)** | 11건 | EOD 순차 실행, 소규모 N+1, 독립 작업 병렬화 가능 등 |
| **정상 확인** | 6건 | Flutter 폴링 주기, 캐시 TTL, 메모리 바운딩 등 |

**가장 큰 성능 개선**: `_compute_position_multipliers` + `_run_entry_stage`에서 `trades:today` 캐시 조회 횟수를 **루프 반복 1회당 13회 → 1회**로 감소. 매매 루프가 90~180초 간격으로 반복되고 반복마다 JSON 직렬화/역직렬화가 수반되므로 누적 효과가 상당하다.
