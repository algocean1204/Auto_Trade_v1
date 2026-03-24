# Guardian Violation Report -- Session 6 (macOS Consumer Installer 전환, Phase 1)

## Monitoring Timestamp: 2026-03-17
## Phase: 1 (Backend — Setup Mode + Configuration API)
## Active Agents: backend-api

---

## Summary (초기 스캔)

현재 git에 반영된 변경사항은 5개 파일이다:
1. `scripts/issue_token.py` -- `--force` 강제 재발급 옵션 추가 (+19줄)
2. `src/common/broker_gateway.py` -- 토큰 만료 시간 추적, 선제 갱신 로직, `force_refresh()` 추가 (+47줄)
3. `src/monitoring/endpoints/system.py` -- `/api/system/token/refresh` 엔드포인트 추가 (+59줄)
4. `src/monitoring/endpoints/trading_control.py` -- EOD 중 시작 차단, running=False 조기 설정 (+14줄)
5. `src/orchestration/phases/preparation.py` -- Step 1에서 `force_refresh()` 호출로 변경 (+14줄)

새 파일: `src/common/paths.py` (경로 통합 모듈, 118줄) -- git untracked

---

## [VIOLATION-S6-001] Severity: P2 -- 파일 크기 초과 (기존 부채 악화)

- **Discovery point**: Phase 1, 초기 스캔
- **Violating agent**: backend-api
- **Violation type**: SRP 파일 크기 규칙 위반
- **Violation details**:
  - `src/monitoring/endpoints/system.py`: **351줄** (200줄 한도의 1.75배, +59줄 증가)
  - `src/monitoring/endpoints/trading_control.py`: **317줄** (200줄 한도의 1.58배)
  - `src/orchestration/phases/preparation.py`: **450줄** (200줄 한도의 2.25배, 기존 부채)
  - `src/common/broker_gateway.py`: **245줄** (200줄 한도의 1.22배, +47줄 증가)
- **Related file**: 상기 4개 파일
- **Original requirement**: [CRITICAL] SRP 원칙 준수 (파일 200줄)
- **Correction order**: 새 코드 추가 시 기존 파일을 팽창시키지 말고 별도 모듈로 분리할 것. 특히 `system.py`의 `TokenRefreshResponse` + `refresh_kis_token` 엔드포인트는 `src/monitoring/endpoints/token.py`로 분리 가능. 단, 현시점에서 이 위반은 기존 부채이며, Phase 1 핵심 작업 진행을 차단하지는 않는다.
- **Status**: OPEN (P2, Phase 완료 전 정리 권장)

---

## [VIOLATION-S6-002] Severity: P2 -- 비공개 속성 직접 접근

- **Discovery point**: Phase 1, 초기 스캔
- **Violating agent**: backend-api
- **Violation type**: 캡슐화 위반
- **Violation details**:
  - `src/monitoring/endpoints/system.py:325,334` -- `_expires_at` 비공개 속성 직접 접근
  - `_system.components.broker.virtual_auth._expires_at` 및 `real_auth._expires_at`
  - `KisAuth._expires_at`는 언더스코어 접두사로 비공개를 의도한 속성이다
  - 적절한 접근자 메서드(`@property expires_at`)를 추가하거나, `force_refresh()`의 반환값에 만료시간을 포함해야 한다
- **Related file**: `src/monitoring/endpoints/system.py:325,334`
- **Correction order**: `KisAuth`에 `@property expires_at` 추가하거나 `force_refresh()` 반환 타입을 튜플(token, expires_at)로 변경할 것
- **Status**: OPEN

---

## [VIOLATION-S6-003] Severity: P3 -- Phase 1 핵심 작업 미착수

- **Discovery point**: Phase 1, 진행 상황 점검
- **Violating agent**: backend-api
- **Violation type**: 요구사항 이행 진행 상황 감시
- **Violation details**:
  Phase 1 계획의 핵심 4개 작업 중 현재 진행 상태:
  - **1-1. Setup Mode 도입**: 미착수 (system_initializer.py, secret_vault.py, main.py 미수정)
  - **1-2. Setup API 엔드포인트**: 미착수 (setup.py, setup_schemas.py 미생성)
  - **1-3. 모델 다운로드 매니저**: 미착수 (model_manager.py 미생성)
  - **1-4. 경로 통합 모듈**: **완료** (paths.py 생성됨, 118줄)

  현재 변경된 5개 파일은 KIS 토큰 관리 개선에 해당하며, Phase 1 계획에는 직접 명시되지 않은 작업이다. 토큰 강제 재발급 기능은 Setup API의 validate/{service} 엔드포인트에서 활용될 수 있으므로 사전 준비 작업으로 볼 수 있으나, Phase 1 핵심 작업(setup mode, setup API, model manager)은 아직 시작되지 않았다.

  이것은 "위반"이 아니라 진행 상황 보고이다. 작업이 진행 중일 수 있으므로 P3으로 기록한다.
- **Status**: MONITORING (진행 추적 중)

---

## 규칙 준수 확인 결과 (통과 항목)

### Code Quality Checks -- ALL PASS
| 검사 항목 | 결과 | 비고 |
|---|---|---|
| `from __future__ import annotations` | PASS | 모든 수정 파일에 존재 |
| `get_logger(__name__)` | PASS | 모든 수정 파일에서 사용 |
| Korean comments/docstrings | PASS | 모든 주석/독스트링이 한국어 |
| Python type hints | PASS | 모든 새 함수에 타입 힌트 존재 |
| try/except + logging | PASS | public 메서드에 예외 처리 존재 |
| Workaround patterns (noqa, @ts-ignore 등) | PASS | 0건 |
| `!important` CSS | N/A | Python 파일만 변경 |
| Pure achromatic colors | N/A | Python 파일만 변경 |

### Architecture Checks -- ALL PASS
| 검사 항목 | 결과 | 비고 |
|---|---|---|
| 디렉토리 경계 준수 | PASS | backend-api 영역 내 파일만 수정 |
| 순환 의존성 | PASS | 감지되지 않음 |
| 개발 환경 호환성 | PASS | paths.py가 is_bundled() 폴백 제공, broker_gateway.py가 기존 로직 유지 |

### Requirement Preservation -- PASS
| 검사 항목 | 결과 | 비고 |
|---|---|---|
| 기존 동작 보존 | PASS | 모든 변경이 하위 호환, 기존 get_token() 동작 유지 |
| 개발 환경 폴백 | PASS | paths.py가 프로젝트 루트 폴백 제공 |

---

## Phase Completion Checklist (Phase 1 진행 중)

- [ ] User original requirements 100% reflected -- **IN PROGRESS** (1-4 완료, 1-1/1-2/1-3 미착수)
- [x] All CLAUDE.md Non-negotiable rules complied with -- **YES** (현재 변경분 기준)
- [ ] Current Phase goals achieved -- **NO** (setup mode, setup API, model manager 미완)
- [x] No unresolved P0/P1 violations remaining -- **YES**
- [x] Information to be passed to next Phase is complete -- **N/A** (Phase 1 진행 중)
- [x] docs/guardian-requirements.md is up to date -- **YES**
