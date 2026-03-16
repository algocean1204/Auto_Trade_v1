# Guardian Violation Report — Round 4 Audit

**감사 일시**: 2026-03-16
**감사 범위**: DB↔Backend↔Frontend 연결 전수검사, 최근 수정사항 최종 검증
**감사자**: requirements-guardian

---

## 감사 결과 요약

| 검사 항목 | 결과 | 상세 |
|---|---|---|
| Redis → CachePublisher 리네임 (Python) | PASS | `RedisPublisher`, `redis_publisher` 참조 0건 |
| `cache_publisher.py` import 체인 | PASS | `storage/__init__.py`, `manager.py` 정상 참조 |
| `_ServerControlButton` 잔여 참조 | PASS | 0건, `_ServerStartButton`+`_ServerStopButton` 정상 분리 |
| EmergencyButton STOP→SOS | PASS | `emergency_button.dart:58` 에서 'SOS' 확인 |
| AppBar overflow 방지 | PASS | `shell_screen.dart:188` Flexible + SingleChildScrollView 적용 확인 |
| Flutter `dart analyze` | PASS | 62 info (error 0, warning 0) — 모두 `prefer_const_constructors` 등 스타일 권고 |
| Python `py_compile` (12개 핵심 파일) | PASS | 전부 컴파일 성공 |
| Python return type hints | PASS | public 함수 전체 return type annotation 존재 |
| Workaround 패턴 (`@ts-ignore` 등) | PASS | Python/Dart 소스에서 0건 |
| `redis_publisher`/`RedisPublisher` 전역 검색 | PASS | src/, dashboard/ 소스에서 0건 (htmlcov 제외) |

---

## 위반 사항

### [VIOLATION-R4-001] Severity: P2
- **발견 위치**: Flutter UI 표시 레이블
- **위반 유형**: 불완전 리네임 (Redis → Cache)
- **위반 상세**: 백엔드는 `cache` 필드로 전환 완료되었으나, Flutter UI에서 사용자에게 보여지는 레이블이 여전히 "Redis"/"RDB"로 표시됨
- **관련 파일**:
  - `dashboard/lib/widgets/status_bar.dart:78` — `_StatusDot(label: 'RDB', online: status.redis)`
  - `dashboard/lib/screens/overview_screen.dart:1361` — `final services = ['Claude AI', 'KIS API', 'Database', 'Redis']`
  - `dashboard/lib/screens/overview_screen.dart:1507` — `_buildStatusRow('Redis', status.redis, ...)`
  - `dashboard/lib/models/dashboard_models.dart:105` — `final bool redis;` (필드명)
- **원본 요구사항**: Redis 참조 완전 제거
- **수정 지시**: 표시 레이블을 'Cache'로 변경하고, 모델 필드명도 `redis` → `cache`로 일관성 있게 변경. `fromJson`의 fallback 로직 `json['cache'] ?? json['redis']`은 하위 호환을 위해 유지 가능.
- **기한**: 다음 Phase 진입 전
- **상태**: OPEN

### [VIOLATION-R4-002] Severity: P3
- **발견 위치**: `src/strategy/models.py:124`
- **위반 유형**: 한국어 주석 규칙 미준수
- **위반 상세**: `# Pyramiding` — 순수 영어 주석 (한국어 설명 없음)
- **관련 파일**: `src/strategy/models.py:124`
- **원본 요구사항**: 모든 코드 주석/독스트링은 한국어로 작성
- **수정 지시**: `# 피라미딩 설정이다` 등 한국어로 변경
- **기한**: 다음 Phase 진입 전 일괄 처리
- **상태**: OPEN

### [VIOLATION-R4-003] Severity: P3
- **발견 위치**: `src/common/__init__.py` (lines 41, 45, 50, 54, 61, 63, 72)
- **위반 유형**: 한국어 주석 규칙 미준수 (경미)
- **위반 상세**: `# C0.1 SecretVault`, `# C0.2 DatabaseGateway` 등 — 모듈 식별자이므로 영어가 불가피하나, 한국어 설명을 추가하면 더 좋음
- **수정 지시**: `# C0.1 시크릿 볼트` 또는 `# C0.1 SecretVault — 비밀 저장소` 등으로 한국어 병기 권장 (선택적)
- **기한**: 일괄 정리 시
- **상태**: OPEN (P3 — 권고사항)

### [VIOLATION-R4-004] Severity: P2
- **발견 위치**: Python 소스 전체
- **위반 유형**: 파일 크기 / 함수 크기 제한 초과
- **위반 상세**: 50줄 초과 함수 96개 발견. 특히 심각한 위반:
  - `trading_loop.py:1478` `_run_entry_stage()` — **310줄** (제한의 6.2배)
  - `trading_loop.py:1877` `_update_ws_cache()` — **241줄** (제한의 4.8배)
  - `risk.py:143` `get_risk_dashboard()` — **211줄** (제한의 4.2배)
  - `trading_loop.py:511` `_run_beast_entry()` — **166줄** (제한의 3.3배)
  - `trading_loop.py:1223` `_compute_position_multipliers()` — **147줄** (제한의 2.9배)
  - `system.py:77` `system_status()` — **141줄** (제한의 2.8배)
- **관련 파일**: `src/orchestration/loops/trading_loop.py` (2,226줄, 300줄 제한의 7.4배)
- **원본 요구사항**: Atomic 30줄, Manager 50줄, 파일 200줄 제한. 300줄 이상 단일 파일 금지.
- **수정 지시**: 이 규칙은 프로젝트 초기 설계 시 적용된 규칙이며, 현재 프로덕션 코드의 대규모 리팩토링은 운영 안정성에 영향을 줄 수 있음. 리더에게 리팩토링 범위를 보고하고 사용자 판단을 요청할 것.
- **기한**: 사용자 결정 후
- **상태**: OPEN (기존 부채 — 이번 라운드에서 신규 도입된 위반 아님)

### [VIOLATION-R4-005] Severity: P2
- **발견 위치**: Flutter Dart 파일 전체
- **위반 유형**: 파일 크기 제한 초과
- **위반 상세**: 300줄 초과 Dart 파일 다수:
  - `news_screen.dart` — 1,963줄
  - `overview_screen.dart` — 1,920줄
  - `universe_screen.dart` — 1,827줄
  - `home_dashboard.dart` — 1,754줄
  - `api_service.dart` — 1,692줄
  - 외 15+ 파일
- **수정 지시**: R4-004와 동일. 기존 부채이며, 리팩토링은 사용자 판단 후 별도 Phase에서 수행 권장.
- **기한**: 사용자 결정 후
- **상태**: OPEN (기존 부채)

---

## 검증 완료 (이번 Round 수정사항)

| # | 수정 항목 | 검증 결과 |
|---|---|---|
| 1 | EmergencyButton STOP→SOS | PASS — `emergency_button.dart:58` 'SOS' 확인 |
| 2 | SERVER 버튼 분리 (_ServerStartButton + _ServerStopButton) | PASS — `shell_screen.dart` 두 클래스 확인, 구 클래스 참조 0건 |
| 3 | AppBar overflow 방지 | PASS — Flexible + SingleChildScrollView 적용 확인 |
| 4 | cache_publisher 리네임 | PASS — import 체인 정상, 구 이름 참조 0건 |
| 5 | Python compile check | PASS — 12개 핵심 파일 전체 컴파일 성공 |
| 6 | Flutter dart analyze | PASS — error 0, warning 0 (info 62건은 스타일 권고) |
| 7 | Backend cache 필드명 | PASS — `SystemStatusResponse.cache`, endpoint `cache=cache_item` |
| 8 | Flutter JSON 파싱 하위 호환 | PASS — `json['cache'] ?? json['redis']` fallback 유지 |

---

## P0/P1 위반: 없음

이번 Round 4 감사에서 P0/P1 위반은 발견되지 않았다.

## 최종 판정

**다음 Phase 진입 가능** — P0/P1 위반 없음.
P2 2건(R4-001 UI 레이블, R4-004/R4-005 파일크기)은 리더 보고 후 사용자 결정에 따라 처리.
P3 2건(R4-002, R4-003 한국어 주석)은 일괄 정리 시 처리 가능.
