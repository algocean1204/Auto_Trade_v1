# Guardian Violations Report V2 -- 백엔드-프론트엔드 통합 2차 감사

> 작성일: 2026-03-13
> 감사 범위: FastAPI 백엔드 (30 라우터, 112+ 엔드포인트) ↔ Flutter 대시보드 (api_service.dart, WebSocket, 22 모델 파일)
> 목적: 1차 감사(27건 수정) 이후 실제 반영 여부 검증 + 신규 위반 탐지

---

## 1. 이전 수정 사항 검증 결과

### VERIFIED (확인 완료 -- 정상 반영됨)

| # | 이전 위반 | 검증 위치 | 상태 |
|---|---|---|---|
| V-001 | `_MIN_ORDER_DOLLAR_AMOUNT = 20.0` 최소 주문 금액 추가 | `trading_loop.py:31-54` | **VERIFIED** |
| V-002 | `updateIndicatorConfig` 에서 `{'config': config}` 래핑 | `api_service.dart:1114` | **VERIFIED** |
| V-003 | WebSocket 엔벨로프 언래핑 (`{channel, data, count}`) | `websocket_service.dart:76-96` | **VERIFIED** |
| V-004 | `DashboardSummaryResponse.system_status: str` 필드 | `response_models.py:35`, `dashboard_models.dart:73` | **VERIFIED** |
| V-005 | `setTickerOverride` 경로에서 `/override` 접미사 제거 | `api_service.dart:1593` | **VERIFIED** |
| V-006 | `clearTickerOverride`에 `param_name` 쿼리 파라미터 추가 | `api_service.dart:1598-1601`, `strategy.py:348` | **VERIFIED** |
| V-007 | `alerts.py`에서 `verify_api_key` 임포트 및 적용 | `alerts.py:16,173` | **VERIFIED** |
| V-008 | ProfitTarget 모델 필드 매칭 (`monthly_target_usd` 등) | `profit_target_models.dart` ↔ `profit_target.py` | **VERIFIED** |
| V-009 | Benchmark 모델 필드 매칭 (`periods`, `summary`) | `benchmark_models.dart` ↔ `benchmark.py` | **VERIFIED** |
| V-010 | `_enrich_analysis_data()`에서 기존 가격 덮어쓰기 방지 | `analysis.py:373` (`existing_price is None or existing_price <= 0`) | **VERIFIED** |

### 추가 검증 항목 (1차 감사 이후 확인)

| 항목 | 검증 내용 | 상태 |
|---|---|---|
| Risk 모델 | `RiskDashboardData.fromJson` ↔ `RiskDashboardResponse` 필드 매칭 | **VERIFIED** |
| VarIndicator | `confidence` 키 사용 + `confidence_level` 폴백 | **VERIFIED** |
| AlertNotification | `ws:alerts` 캐시 작성 형식 ↔ `AlertNotification.fromJson` | **VERIFIED** |
| News article | `ArticleDetailResponse(article=cached)` ↔ Flutter `map['article'] ?? map` | **VERIFIED** |
| StockAnalysis | `_enrich_analysis_data()` 출력 ↔ `StockAnalysisData.fromJson` | **VERIFIED** |
| WebSocket 5채널 | `_update_ws_cache()` 5개 키 (positions, trades, alerts, orderflow, dashboard) | **VERIFIED** |

**결론: 1차 감사에서 보고된 10건의 수정 사항 모두 코드에 정상 반영되어 있다. REGRESSION 없음.**

---

## 2. 신규 위반 사항

### [VIOLATION-V2-001] 심각도: P1 -- PUT /ticker-params 요청 본문 구조 불일치

- **발견 위치**: Flutter `api_service.dart:1593` ↔ 백엔드 `strategy.py:189-193,297-319`
- **위반 유형**: 데이터 모델 불일치 (런타임 422 에러 발생)
- **위반 상세**:
  - Flutter의 `setTickerOverride(ticker, overrides)` 메서드는 `overrides` (다중 키 Map)를 PUT 본문으로 직접 전송한다.
    ```dart
    // api_service.dart:1593
    await _putVoid('/api/strategy/ticker-params/$ticker', overrides);
    // 전송 예시: {"trailing_stop": 0.5, "hard_stop": -1.0}
    ```
  - 백엔드 `TickerParamsUpdateRequest`는 단일 파라미터 구조를 기대한다:
    ```python
    # strategy.py:189-193
    class TickerParamsUpdateRequest(BaseModel):
        param_name: str   # 오버라이드할 파라미터 이름
        value: Any        # 파라미터 값
    # 기대 예시: {"param_name": "trailing_stop", "value": 0.5}
    ```
  - Flutter UI (`ticker_params_screen.dart:183-204`)는 사용자가 활성화한 모든 오버라이드를 하나의 dict로 모아서 전송한다.
- **영향**: 사용자가 티커 파라미터 오버라이드를 저장하려 하면 Pydantic 422 Validation Error가 발생한다. 핵심 트레이딩 기능에 직접적 영향.
- **수정 방안**: 두 가지 중 택일:
  - **(A) Flutter 수정**: `setTickerOverride`에서 overrides map을 순회하며 각 param에 대해 개별 PUT 요청을 전송
    ```dart
    for (final entry in overrides.entries) {
      await _putVoid('/api/strategy/ticker-params/$ticker',
          {'param_name': entry.key, 'value': entry.value});
    }
    ```
  - **(B) 백엔드 수정**: `TickerParamsUpdateRequest`를 다중 파라미터 수용 구조로 변경 (`params: dict[str, Any]`)
  - **권장**: (A) Flutter 수정. 백엔드의 단일 파라미터 단위 갱신은 원자성과 로깅 측면에서 더 안전한 설계이다.
- **상태**: **OPEN**

---

### [VIOLATION-V2-002] 심각도: P2 -- noqa 린트 억제 2건 잔존

- **발견 위치**: 
  - `src/orchestration/loops/trading_loop.py:910` -- `# noqa: C901` (함수 복잡도 억제)
  - `src/common/cache_gateway.py:125` -- `# noqa: S307` (eval 보안 경고 억제)
- **위반 유형**: CLAUDE.md "No Workarounds" 규칙 위반 (린트 경고 억제는 워크어라운드에 해당)
- **위반 상세**:
  - `# noqa: C901`: `_run_regular_session()` 함수가 지나치게 복잡하여 C901 경고 발생. 함수 분리가 근본 해결책이나, 해당 파일이 1702줄로 이미 과대하여 구조 리팩토링 필요.
  - `# noqa: S307`: Redis `eval` 명령은 보안 위험이 있으나, Redis 스크립트 실행은 의도된 사용법이므로 이 경우는 예외적으로 허용 가능. 단, WORKAROUND 형식 주석(`// WORKAROUND: ...`)으로 명시해야 함.
- **수정 방안**:
  - C901: `_run_regular_session()`을 하위 함수로 분리하여 복잡도 감소 (장기 리팩토링 과제)
  - S307: `# WORKAROUND: Redis eval은 의도된 사용법이므로 S307 억제. Redis Lua 스크립트 실행에 필수.` 형태로 주석 보강
- **상태**: **OPEN**

---

### [VIOLATION-V2-003] 심각도: P3 -- 오래된 TODO(v2) 주석 7건 (백엔드에 이미 존재하는 엔드포인트)

- **발견 위치**: `dashboard/lib/services/api_service.dart`
- **위반 유형**: 코드 위생 (오래된 주석이 혼란을 유발)
- **위반 상세**: 아래 TODO(v2) 주석들은 "V2 백엔드에 해당 엔드포인트가 없다"고 기술하나, 실제로는 모두 존재한다.

| 줄 | TODO 내용 | 실제 백엔드 엔드포인트 |
|---|---|---|
| 482 | "V2 백엔드에 주간 리포트 엔드포인트가 없다" | `feedback.py:136` -- `GET /api/feedback/weekly/{week}` 존재 |
| 495 | "V2 백엔드에 /api/feedback/pending-adjustments 없다" | `feedback.py:179` -- `GET /api/feedback/pending-adjustments` 존재 |
| 506 | "V2 백엔드에 해당 엔드포인트가 추가되면 경로 업데이트" | `feedback.py:201` -- `POST /api/feedback/approve-adjustment/{id}` 존재 |
| 511 | "V2 백엔드에 해당 엔드포인트가 추가되면 경로 업데이트" | `feedback.py:251` -- `POST /api/feedback/reject-adjustment/{id}` 존재 |
| 561 | "V2 백엔드에 크롤 전용 엔드포인트가 없다" | `crawl_control.py:154,190` -- `POST /api/crawl/manual`, `GET /api/crawl/status/{task_id}` 존재 |
| 574 | "V2 백엔드의 알림 전용 REST 엔드포인트 경로 미확정" | `alerts.py:115,150,170` -- `GET /api/alerts/`, `GET /api/alerts/unread-count`, `POST /api/alerts/{id}/read` 존재 |
| 843 | "V2 스펙에 해당 엔드포인트가 명시되어 있지 않다" | `dashboard.py:406` -- `GET /api/dashboard/trades/recent` 존재 |

  나머지 2건은 정당한 TODO이다:
  - 줄 517: `/reports/daily/list`는 존재하나 Flutter가 호출하는 경로 구조가 다를 수 있어 확인 필요
  - 줄 961: `/reports/daily/*`는 존재하나 Flutter의 호출 패턴이 다를 수 있어 확인 필요

- **수정 방안**: 7건의 TODO(v2) 주석을 제거하고, 해당 코드 블록이 정상 연결되는 백엔드 경로를 확인한 후 주석 갱신.
- **상태**: **OPEN**

---

### [VIOLATION-V2-004] 심각도: P3 -- 파일 크기 초과 (300줄 기준)

- **발견 위치**: 다수 파일
- **위반 유형**: CLAUDE.md SRP 규칙 위반 ("파일 200줄, 컴포넌트 150줄 max")
- **위반 상세**:

| 파일 | 줄 수 | 초과량 |
|---|---|---|
| `src/orchestration/loops/trading_loop.py` | 1702 | +1502 (8.5배 초과) |
| `dashboard/lib/services/api_service.dart` | 1681 | +1481 (8.4배 초과) |
| `src/monitoring/endpoints/analysis.py` | 691 | +491 (3.5배 초과) |
| `src/monitoring/endpoints/risk.py` | 628 | +428 (3.1배 초과) |
| `src/monitoring/endpoints/indicators.py` | 587 | +387 (2.9배 초과) |
| `src/monitoring/endpoints/profit_target.py` | 585 | +385 (2.9배 초과) |
| `src/monitoring/endpoints/universe.py` | 498 | +298 (2.5배 초과) |
| `src/monitoring/endpoints/macro.py` | 487 | +287 (2.4배 초과) |
| `src/monitoring/endpoints/strategy.py` | 456 | +256 (2.3배 초과) |
| `src/monitoring/endpoints/reports.py` | 443 | +243 (2.2배 초과) |
| `src/monitoring/endpoints/dashboard.py` | 422 | +222 (2.1배 초과) |
| `src/monitoring/endpoints/feedback.py` | 397 | +197 (2.0배 초과) |
| `src/monitoring/endpoints/agents.py` | 365 | +165 (1.8배 초과) |
| `src/monitoring/endpoints/news.py` | 350 | +150 (1.8배 초과) |

- **참고**: 엔드포인트 파일들은 Pydantic 모델 정의 + 헬퍼 함수 + 엔드포인트 핸들러를 모두 포함하므로 구조적으로 길어지는 경향이 있다. 모델을 별도 파일로 분리하면 줄 수를 크게 줄일 수 있다.
- **수정 방안**: 장기 리팩토링 과제. 우선순위가 낮으므로 기록만 하고 다음 대규모 리팩토링 시 처리.
- **상태**: **OPEN** (장기 과제)

---

## 3. 전체 준수 현황 평가

### CLAUDE.md 규칙 준수 상태

| 규칙 | 상태 | 비고 |
|---|---|---|
| 한국어 주석/독스트링 | **PASS** | 전체 엔드포인트 파일 검사 완료. 영어 주석 없음 |
| Python 타입 힌트 | **PASS** | 모든 엔드포인트 함수에 파라미터/반환 타입 명시됨 |
| No Workarounds | **PARTIAL** | 2건 noqa 잔존 (V2-002 참조) |
| SRP / 파일 크기 | **PARTIAL** | 14개 파일 200줄 초과 (V2-004 참조) |
| Pydantic 응답 모델 | **PASS** | 모든 엔드포인트가 BaseModel 반환 (dict/JSONResponse 미사용) |
| try/except + logging | **PASS** | 모든 public 메서드에 예외 처리 + 로깅 적용 |
| get_logger(__name__) | **PASS** | 전체 엔드포인트 파일에서 확인 |

### 백엔드-프론트엔드 연결 상태

| 영역 | 상태 | 비고 |
|---|---|---|
| REST API 경로 매칭 | **PASS** | 29개 엔드포인트 그룹 모두 경로 정확 |
| Pydantic ↔ Dart fromJson 필드 | **PASS** | 주요 10개 모델 교차 검증 완료 |
| WebSocket 데이터 흐름 | **PASS** | 5채널 엔벨로프 형식 + 데이터 구조 일치 |
| PUT/POST 요청 본문 | **FAIL** | 1건 불일치 (V2-001: ticker-params) |
| DELETE 쿼리 파라미터 | **PASS** | clearTickerOverride param_name 쿼리 정상 |

### 위반 사항 요약

| 심각도 | 건수 | 상태 |
|---|---|---|
| P0 (핵심 기능 누락/보안) | 0 | -- |
| P1 (런타임 오류 가능) | 1 | OPEN (V2-001) |
| P2 (코드 품질) | 1 | OPEN (V2-002) |
| P3 (권장 사항) | 2 | OPEN (V2-003, V2-004) |

---

## 4. 즉시 수정 필요 사항 (리더에게 전달)

### [GUARDIAN CORRECTION - P1]
- **대상 에이전트**: Flutter 프론트엔드 담당
- **위반**: PUT /api/strategy/ticker-params/{ticker} 요청 본문이 백엔드 Pydantic 모델과 불일치하여 422 에러 발생
- **원래 요구사항**: "백앤드랑 프론트앤드 위치 연결 전부 세세하게 모두 조사해봐"
- **수정 지시**: `api_service.dart:1591-1593`의 `setTickerOverride` 메서드를 수정하여, overrides map의 각 항목에 대해 개별 PUT 요청(`{param_name: key, value: val}`)을 전송하도록 변경할 것
- **기한**: 즉시

---

## 5. 참고: 정당한 TODO 및 예외 사항

1. **`api_service.dart:517,961`의 `/reports/daily/*` TODO**: 백엔드에 `GET /api/reports/daily/list`와 `GET /api/reports/daily`가 존재하나, Flutter의 호출 패턴과 응답 파싱이 일치하는지 별도 확인 필요.
2. **`cache_gateway.py:125`의 `# noqa: S307`**: Redis `eval` 명령은 Lua 스크립트 실행을 위한 의도된 사용이므로 보안 위험이 제한적이다. WORKAROUND 형식으로 주석을 보강하면 규칙 준수로 간주 가능.
3. **파일 크기 초과**: 엔드포인트 파일은 라우터 + 모델 + 헬퍼가 한 파일에 있는 구조적 특성상 200줄을 초과하기 쉽다. 모델을 별도 `schemas/` 디렉토리로 분리하는 것이 장기적 해결책이다.
