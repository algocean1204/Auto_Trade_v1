# Guardian Violation Report -- Session 7 (환율 폴백 + 포트 변경)

## Summary -- 초기 현황 분석 (작업 시작 전 상태)

모든 요구사항은 **아직 미구현 상태**이다. 아래는 구현 시 반드시 수정해야 할 파일과 위반 사항 목록이다.

- Total violations: 14 (P0: 3, P1: 6, P2: 3, P3: 2)
- P0: 핵심 요구사항 미구현
- P1: 관련 파일 일관성 미확보
- P2: 코드 품질
- P3: 문서 업데이트

---

## [VIOLATION-S7-001] Severity: P0 -- 1350.0 폴백이 "조회불가"로 변경되지 않음

- **Discovery point**: 초기 스캔
- **Violating agent**: 미구현 (작업 전)
- **Violation type**: 핵심 요구사항 미구현
- **Violation details**:
  사용자가 명시적으로 "폴백은 '조회불가'로 하고"라고 요청했으나, 아래 6개 파일에서 `1350.0` 폴백이 그대로 사용 중이다:

  | # | 파일 | 라인 | 현재 값 | 변경 필요 |
  |---|---|---|---|---|
  | 1 | `src/monitoring/schedulers/fx_scheduler.py` | 30, 106, 167-169, 182, 184 | `_FALLBACK_RATE: float = 1350.0` | 폴백 시 `"조회불가"` 반환 |
  | 2 | `src/tax/fx_manager.py` | 19, 53-57, 65-70 | `_FALLBACK_RATE: float = 1350.0` | 폴백 시 `"조회불가"` 반환 또는 예외 |
  | 3 | `src/monitoring/endpoints/fx.py` | 26, 80, 104, 112-117, 144 | `_FALLBACK_RATE: float = 1350.0` | API 응답에 `"조회불가"` 소스 표시 |
  | 4 | `src/strategy/tax/tax_writer.py` | 24, 34, 37 | `_DEFAULT_FX_RATE: float = 1350.0` | 환율 조회 실패 시 계산 중단/경고 |
  | 5 | `src/monitoring/endpoints/tax.py` | 33, 200, 272, 333 | `_DEFAULT_FX_RATE = 1350.0` | 환율 조회 실패 시 "조회불가" 표시 |
  | 6 | `src/tax/tax_tracker.py` | 40 | `fx_rate: float = 1350.0` | 환율 주입 필수, 기본값 제거 |

- **Correction order**:
  1. 환율을 `float`에서 `float | None`으로 변경하여 조회 실패를 명시적으로 표현해야 한다
  2. FxScheduler 최종 폴백: `(None, "조회불가")` 반환
  3. FxManager 최종 폴백: `None` 반환 또는 예외 raise
  4. fx.py 엔드포인트: `source="조회불가"`, `usd_krw_rate=0.0` 또는 별도 상태 필드
  5. 세금 관련 파일: 환율=None이면 세금 계산을 건너뛰고 "환율 조회불가" 상태 표시
  6. **주의**: `float` 폴백 1350.0을 단순히 문자열 "조회불가"로 바꾸면 타입 에러 발생. 설계가 필요하다.
- **Deadline**: 구현 완료 전 필수
- **Status**: OPEN

---

## [VIOLATION-S7-002] Severity: P0 -- 환율 조회 소스가 3개뿐 (10개 필요)

- **Discovery point**: 초기 스캔
- **Violating agent**: 미구현 (작업 전)
- **Violation type**: 핵심 요구사항 미구현
- **Violation details**:
  사용자가 "10가지 안전장치"를 요청했으나 현재 환율 조회 소스가 3개뿐이다:
  1. KIS API (`fx_manager.py` → `broker_gateway.get_exchange_rate()`)
  2. 네이버 금융 크롤링 (`naver_fx.py` -- PC웹 + 모바일 API 2가지 시도 = 내부 2소스)
  3. 구글 Finance 크롤링 (`google_fx.py` -- Finance페이지 + 검색결과 2가지 시도 = 내부 2소스)

  **추가로 필요한 7개 소스 예시**:
  - Yahoo Finance API
  - ExchangeRate-API (무료 tier)
  - Open Exchange Rates API
  - Fixer.io / exchangeratesapi.io
  - FRED DEXKOUS (이미 macro에서 사용 중 -- 환율 폴백으로 활용 가능)
  - Wise (TransferWise) 환율 페이지 크롤링
  - 한국은행 ECOS API
  - XE.com 크롤링
  - Bloomberg/Reuters 크롤링

  현재 `fx_scheduler.py._fetch_rate_with_fallback()` 메서드는 3단계 체인만 구현되어 있다.

- **Correction order**:
  1. 7개 추가 크롤러를 `src/monitoring/crawlers/` 아래에 각각 별도 파일로 생성 (SRP)
  2. `fx_scheduler.py._fetch_rate_with_fallback()`을 10단계 체인으로 확장
  3. 각 크롤러는 `fetch_*_usd_krw() -> float | None` 패턴 유지
  4. 파일당 200줄 이내, 한국어 주석
  5. 순서: KIS → Google → Naver → Yahoo → ExchangeRate-API → FRED → Open Exchange Rates → 한국은행 → Wise → XE (또는 사용자와 협의)
- **Deadline**: 구현 완료 전 필수
- **Status**: OPEN

---

## [VIOLATION-S7-003] Severity: P0 -- 서버 포트 범위에 9500이 포함되어 있음

- **Discovery point**: 초기 스캔
- **Violating agent**: 미구현 (작업 전)
- **Violation type**: 핵심 요구사항 미구현
- **Violation details**:
  사용자가 "9501~9505 포트를 사용"하라고 명시했으나, 현재 코드에 `9500`이 포함되어 있다:

  | # | 파일 | 위치 | 현재 값 | 변경 필요 |
  |---|---|---|---|---|
  | 1 | `src/monitoring/server/api_server.py` | L275 | `[9500, 9501, ..., 9505]` | `[9501, 9502, 9503, 9504, 9505]` |
  | 2 | `src/monitoring/server/api_server.py` | L290, 323, 326, 334, 340 | docstring/로그에 "9500-9505" | "9501-9505" |
  | 3 | `dashboard/lib/services/server_launcher.dart` | L49 | `[9500, 9501, ..., 9505]` | `[9501, 9502, 9503, 9504, 9505]` |
  | 4 | `dashboard/lib/services/server_launcher.dart` | L68-69, 72 | 기본 폴백 `9500` | 기본 폴백 `9501` |
  | 5 | `scripts/start_server.sh` | L21 | `DEFAULT_PORT=9500` | `DEFAULT_PORT=9501` |
  | 6 | `scripts/start_server.sh` | L28 | `9500` 범위 체크 | `9501` 범위 체크 |
  | 7 | `scripts/auto_trading.sh` | L21 | `DEFAULT_PORT=9500` | `DEFAULT_PORT=9501` |
  | 8 | `scripts/auto_trading.sh` | L30 | `9500` 범위 체크 | `9501` 범위 체크 |
  | 9 | `scripts/monitor_5min.sh` | L7 | `DEFAULT_PORT=9500` | `DEFAULT_PORT=9501` |
  | 10 | `scripts/monitor_5min.sh` | L14 | `9500` 범위 체크 | `9501` 범위 체크 |
  | 11 | `scripts/monitor_overnight.py` | L46 | `_DEFAULT_PORT = 9500` | `_DEFAULT_PORT = 9501` |
  | 12 | `scripts/monitor_overnight.py` | L54 | `9500 <= port` | `9501 <= port` |
  | 13 | `scripts/monitor_trading.sh` | L7, 12, 17 | `9500` 참조 | `9501` 참조 |
  | 14 | `scripts/start_dashboard.py` | L36 | `"9500"` | `"9501"` |
  | 15 | `.env.example` | L68 | `API_PORT=9500` | `API_PORT=9501` |
  | 16 | `Dockerfile` | L61, 63 | `9500` | `9501` |
  | 17 | `docker-compose.yml` | L69 | `9500:9500` (주석 처리됨) | `9501:9501` |

- **Correction order**:
  1. 모든 소스 코드 파일에서 `9500`을 `9501`로 변경 (기본 포트)
  2. 허용 포트 목록에서 `9500` 제거: `[9501, 9502, 9503, 9504, 9505]`
  3. 셸 스크립트의 범위 체크도 `9501`부터 시작
  4. Dockerfile EXPOSE도 `9501`로 변경
- **Deadline**: 구현 완료 전 필수
- **Status**: OPEN

---

## [VIOLATION-S7-004] Severity: P1 -- 문서 내 9500 포트 참조 다수 존재

- **Discovery point**: 초기 스캔
- **Violating agent**: 미구현 (작업 전)
- **Violation type**: 문서 일관성 위반
- **Violation details**:
  아래 문서들에 `localhost:9500` 참조가 다수 존재한다:
  - `docs/DASHBOARD_GUIDE.md` (3곳)
  - `docs/RUNNING.md` (5곳)
  - `docs/API_REFERENCE.md` (2곳)
  - `docs/TRADING_GUIDE.md` (16곳)
  - `docs/SETUP.md` (9곳)
  - `docs/README.md` (7곳)
  - `docs/DEPLOYMENT.md` (3곳)
  - `dashboard/README.md` (5곳)
  - `dashboard/SETUP_GUIDE.md` (6곳)
  - `dashboard/IMPLEMENTATION_SUMMARY.md` (4곳)
  - `dashboard/test/services/api_service_test.dart` (4곳)
- **Correction order**: 모든 문서에서 `9500` → `9501` 변경 또는 "동적 포트 (9501-9505)" 설명으로 교체
- **Deadline**: 구현 완료 전
- **Status**: OPEN

---

## [VIOLATION-S7-005] Severity: P1 -- FxManager가 1350.0 폴백을 반환하면 FxScheduler가 잘못 판단

- **Discovery point**: 코드 로직 분석
- **Violating agent**: fx_scheduler.py
- **Violation type**: 로직 결함 (폴백 변경 시 영향)
- **Violation details**:
  `fx_scheduler.py:182-185`에서 `rate_value == _FALLBACK_RATE` (1350.0)을 비교하여 KIS 폴백을 감지한다.
  폴백 로직이 변경되면 이 비교 로직도 반드시 함께 수정해야 한다.
  FxManager가 `None`을 반환하는 방식으로 변경하면 이 비교가 불필요해진다.
- **Correction order**: FxManager 폴백 변경과 동시에 FxScheduler의 폴백 감지 로직 수정
- **Deadline**: VIOLATION-S7-001과 동시 해결
- **Status**: OPEN

---

## [VIOLATION-S7-006] Severity: P1 -- 세금 계산 모듈들이 환율 "조회불가" 시 동작이 정의되지 않음

- **Discovery point**: 코드 로직 분석
- **Violating agent**: tax_writer.py, tax.py, tax_tracker.py
- **Violation type**: 요구사항 변경에 따른 영향 범위 미대응
- **Violation details**:
  현재 세금 관련 3개 파일이 환율 1350.0을 기본값으로 하드코딩하고 있다:
  - `tax_writer.py:24` -- `_DEFAULT_FX_RATE: float = 1350.0` (FRED 캐시 미스 시 폴백)
  - `tax.py:33` -- `_DEFAULT_FX_RATE = 1350.0` (레거시 캐시 변환 시 사용)
  - `tax.py:333` -- `float(t.get("fx_rate", 1350.0))` (거래 데이터 파싱 시 기본값)
  - `tax_tracker.py:40` -- `fx_rate: float = 1350.0` (생성자 기본값)

  환율 폴백이 "조회불가"로 변경되면 이 모듈들에서 환율=None일 때의 동작을 정의해야 한다.
  현재는 1350.0으로 계산이 진행되므로, 변경 후 잘못된 세금 계산이 이루어지지 않도록 해야 한다.
- **Correction order**:
  1. 세금 계산 시 환율이 None/"조회불가"면 세금 계산을 건너뛰거나 경고 표시
  2. 또는 가장 최근 성공적으로 조회된 환율을 캐시에서 읽어 사용
  3. 어느 경우든 1350.0 하드코딩 제거 필수
- **Deadline**: VIOLATION-S7-001과 동시 해결
- **Status**: OPEN

---

## [VIOLATION-S7-007] Severity: P1 -- FxStatusResponse 모델이 "조회불가" 상태를 표현할 수 없음

- **Discovery point**: 코드 구조 분석
- **Violating agent**: fx.py
- **Violation type**: 데이터 모델 부족
- **Violation details**:
  `fx.py:40-50`의 `FxStatusResponse` 모델은 `usd_krw_rate: float` 필드를 가지고 있다.
  폴백이 "조회불가"가 되면 이 필드를 `float | None`으로 변경하거나,
  별도의 `available: bool` 필드를 추가해야 한다.
  Flutter 대시보드의 `TaxFxProvider`가 이 응답을 파싱하므로, Dart 모델도 함께 수정 필요.
- **Correction order**:
  1. `FxStatusResponse`에 `available: bool` 필드 추가 또는 `usd_krw_rate: float | None` 변경
  2. `source` 필드가 `"조회불가"`일 때의 프론트엔드 처리 추가
  3. Flutter `TaxFxProvider` / `tax_fx_models.dart` 연동 확인
- **Deadline**: VIOLATION-S7-001과 동시 해결
- **Status**: OPEN

---

## [VIOLATION-S7-008] Severity: P1 -- api_service_test.dart에 9500 하드코딩

- **Discovery point**: 초기 스캔
- **Violating agent**: Flutter 테스트 코드
- **Violation type**: 포트 변경 미반영
- **Violation details**:
  `dashboard/test/services/api_service_test.dart`의 4곳에서 `localhost:9500` 하드코딩:
  - L10: `'http://localhost:9500'`
  - L212, 220, 229: `const baseUrl = 'http://localhost:9500'`
- **Correction order**: `9500` → `9501` 변경
- **Deadline**: 포트 변경과 동시
- **Status**: OPEN

---

## [VIOLATION-S7-009] Severity: P1 -- docker-compose.yml 주석 내 9500 참조

- **Discovery point**: 초기 스캔
- **Violating agent**: Docker 설정
- **Violation type**: 포트 변경 미반영
- **Violation details**:
  `docker-compose.yml:69` 주석 처리된 포트 매핑에 `9500:9500` 참조
- **Correction order**: `9501:9501`로 변경
- **Deadline**: 포트 변경과 동시
- **Status**: OPEN

---

## [VIOLATION-S7-010] Severity: P2 -- fx_scheduler.py가 향후 10단계 확장 시 파일 크기 초과 위험

- **Discovery point**: 코드 구조 분석
- **Violating agent**: fx_scheduler.py
- **Violation type**: SRP / 파일 크기 예방
- **Violation details**:
  현재 `fx_scheduler.py`는 264줄이다 (이미 200줄 초과).
  10개 소스로 확장하면 `_try_*` 메서드가 7개 추가되어 더욱 비대해진다.
  각 크롤러를 별도 파일로 분리하고 FxScheduler는 체인만 관리해야 한다.
- **Correction order**:
  1. 각 환율 소스 크롤러를 `src/monitoring/crawlers/` 아래 별도 파일로 분리
  2. fx_scheduler.py는 소스 목록을 순회하며 호출하는 체인 로직만 유지
  3. 최종 목표: fx_scheduler.py 200줄 이하
- **Deadline**: 10단계 구현과 동시
- **Status**: OPEN

---

## [VIOLATION-S7-011] Severity: P2 -- fx_scheduler.py 현재 264줄 (200줄 초과)

- **Discovery point**: 초기 파일 크기 스캔
- **Violating agent**: fx_scheduler.py (기존)
- **Violation type**: CLAUDE.md 파일 크기 규칙 위반
- **Violation details**:
  현재 상태에서 이미 264줄로 200줄 한도를 초과하고 있다.
  `_calc_change_pct()`, `_append_history()` 등의 유틸리티 메서드를 분리하면 해결 가능.
- **Status**: OPEN

---

## [VIOLATION-S7-012] Severity: P2 -- 환율 조회 소스 순서가 사용자 명시와 다름

- **Discovery point**: 코드 로직 분석
- **Violating agent**: fx_scheduler.py
- **Violation type**: 요구사항 미세 차이
- **Violation details**:
  사용자가 "KIS키 조회 -> 구글 -> 네이버 -> 등등 순서"를 명시했으나,
  현재 코드는 KIS → **네이버** → 구글 순서이다 (`fx_scheduler.py:150-163`).
  사용자 요청대로 KIS → 구글 → 네이버 순서로 변경해야 한다.
- **Correction order**: `_fetch_rate_with_fallback()`에서 네이버와 구글 순서 변경
- **Deadline**: 10단계 구현과 동시
- **Status**: OPEN

---

## [VIOLATION-S7-013] Severity: P3 -- .env.example의 API_PORT 기본값 변경 필요

- **Discovery point**: 초기 스캔
- **Violating agent**: 설정 파일
- **Violation type**: 설정 파일 일관성
- **Violation details**: `.env.example:68`의 `API_PORT=9500` → `API_PORT=9501`
- **Status**: OPEN

---

## [VIOLATION-S7-014] Severity: P3 -- guardian-violations-v3.md 내 포트 관련 기존 기록과 충돌 가능

- **Discovery point**: 문서 분석
- **Violating agent**: 이전 세션 문서
- **Violation type**: 문서 정합성
- **Violation details**:
  `docs/guardian-violations-v3.md:202-223`에서 "동적 포트 (기본 9500-9505)" 참조가 있다.
  이번 변경으로 9500이 제거되므로 해당 문서도 업데이트해야 한다.
- **Status**: OPEN

---

## Phase Completion Checklist (작업 시작 전 -- 모두 미완료)

- [ ] 환율 폴백 1350.0 → "조회불가" 변경 (6개 파일)
- [ ] 환율 조회 소스 10개 구현 (현재 3개, 7개 추가 필요)
- [ ] 환율 조회 순서: KIS → 구글 → 네이버 → ... (사용자 명시 순서)
- [ ] 서버 포트 9500 제거, 9501~9505만 허용 (17개+ 파일)
- [ ] 세금 모듈 "조회불가" 호환 처리
- [ ] FxStatusResponse 모델 "조회불가" 표현 가능
- [ ] Flutter 모델/테스트 연동 업데이트
- [ ] 문서 포트 참조 일괄 업데이트
- [ ] 모든 P0/P1 위반 해결 확인
- [ ] Korean comments 유지 확인
- [ ] 신규 파일 200줄 이내 확인
- [ ] 워크어라운드 패턴 없음 확인
