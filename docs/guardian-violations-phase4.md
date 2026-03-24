# Guardian Violation Report -- Phase 4 (.dmg 빌드 파이프라인)

## Phase 정보
- **Phase**: 4 (.dmg 빌드 파이프라인)
- **Phase 목표**: build_dmg.sh 작성, ad-hoc 서명, create-dmg로 .dmg 생성, Gatekeeper 안내 화면
- **모니터링 일시**: 2026-03-17
- **모니터링 에이전트**: requirements-guardian

---

## 1. Phase 4 산출물 현황 (초기 스캔)

| 산출물 | 상태 | 비고 |
|---|---|---|
| `scripts/build_dmg.sh` | 미작성 | Phase 4-1 핵심 산출물 |
| Gatekeeper 안내 화면 (Flutter) | 미구현 | Phase 4-3 산출물 |
| .dmg 파일 | 미생성 | 최종 배포 아티팩트 |
| `create-dmg` 도구 | 미설치 | `brew install create-dmg` 필요 |
| PyInstaller 빌드 결과 (`dist/trading_server/`) | 존재 | 80MB 바이너리, arm64 |
| Flutter Release 빌드 (`ai_trading_dashboard.app`) | 존재 | 3/16 빌드, Release 모드 |
| `server_launcher.dart` 번들 모드 로직 | 구현 완료 | `_findBundledBackend()` + `_isBundledApp` |
| `trading_server.spec` (PyInstaller) | 존재 | ad-hoc 서명 설정 포함 |

---

## 2. VIOLATIONS (발견된 위반/주의 사항)

### [P4-V001] Severity: P1 -- server_launcher.dart 번들 경로와 빌드 스크립트 간 경로 불일치 위험

- **위반 유형**: 요구사항 정합성 -- 빌드 스크립트가 server_launcher.dart의 기대 경로에 맞게 조립해야 한다
- **상세**: `server_launcher.dart`의 `_findBundledBackend()` (329-337행)는 `.app/Contents/Resources/python_backend/` 경로를 기대한다. 또한 121행에서 `$_projectRoot/trading_server` 바이너리를 실행한다. 이는 다음을 의미한다:
  - `_projectRoot` = `.app/Contents/Resources/python_backend/`
  - 실행 파일 = `.app/Contents/Resources/python_backend/trading_server`
  - build_dmg.sh는 `dist/trading_server/` 전체 디렉토리를 `.app/Contents/Resources/python_backend/`로 복사해야 한다
- **검증 필요 항목**:
  1. `dist/trading_server/trading_server` (바이너리)가 복사 후 `.app/Contents/Resources/python_backend/trading_server`에 존재하는지
  2. `dist/trading_server/_internal/` (의존성)도 함께 복사되는지
  3. _internal/ 내부의 .so/.dylib 심볼릭 링크가 복사 시 깨지지 않는지
- **수정 지시**: build_dmg.sh에서 반드시 `cp -a` (아카이브 모드, 심볼릭 링크 보존)로 복사해야 한다. `cp -r`은 심볼릭 링크를 실제 파일로 변환하므로 부적절하다.
- **상태**: PENDING (빌드 스크립트 미작성)

### [P4-V002] Severity: P1 -- Flutter 앱 이름 불일치

- **위반 유형**: 요구사항 정합성
- **상세**: Phase 4 요구사항에서 `StockTrader.app`으로 언급하지만, 실제 Flutter 프로젝트의 PRODUCT_NAME은 `ai_trading_dashboard`이다 (AppInfo.xcconfig:8). Flutter build macos --release 결과물은 `ai_trading_dashboard.app`이 된다.
  - `dashboard/macos/Runner/Configs/AppInfo.xcconfig`: `PRODUCT_NAME = ai_trading_dashboard`
  - `dashboard/pubspec.yaml`: `name: ai_trading_dashboard`
- **수정 지시**: 빌드 스크립트에서 `.app` 이름을 `StockTrader.app`으로 변경하려면:
  - AppInfo.xcconfig의 `PRODUCT_NAME`을 변경하거나
  - 빌드 후 .app 디렉토리를 rename하거나
  - 또는 현재 이름(`ai_trading_dashboard.app`) 그대로 사용
  - 사용자의 확인이 필요하다
- **상태**: PENDING

### [P4-V003] Severity: P0 -- Gatekeeper 우회 안내 화면 미구현 [CRITICAL]

- **위반 유형**: [CRITICAL] 요구사항 누락
- **상세**: ad-hoc 서명은 Apple Developer ID로 서명하지 않으므로, macOS Gatekeeper가 앱 실행을 차단한다. 비전공자 사용자가 앱을 열 수 없는 상황이 발생한다. 따라서 다음이 필수이다:
  1. **Flutter 앱 내부**: 첫 실행 전 설치 안내 화면 (위저드 Step 0 또는 별도 화면)
  2. **DMG 내부 또는 README**: "우클릭 → 열기" 또는 "시스템 설정 → 개인정보 보호 및 보안 → 확인 없이 열기" 안내
  3. **xattr -cr 명령어 안내**: 터미널에서 `xattr -cr /Applications/StockTrader.app` 실행 안내
- **현재 상태**: Gatekeeper 관련 코드/화면이 전혀 없다 (grep 결과 0건)
- **수정 지시**: 
  - Flutter 앱에 Gatekeeper 안내 화면/다이얼로그를 추가해야 한다
  - DMG 볼륨에 README.txt 또는 배경 이미지에 안내 문구를 포함해야 한다
- **상태**: OPEN

### [P4-V004] Severity: P2 -- create-dmg 미설치

- **위반 유형**: 빌드 환경 미준비
- **상세**: `create-dmg` 유틸리티가 시스템에 설치되어 있지 않다. 빌드 스크립트가 이를 사용하려면 사전 설치가 필요하다.
- **수정 지시**: 
  - `brew install create-dmg` 실행
  - 또는 빌드 스크립트 내에서 자동 설치 확인 (존재 체크 → brew install 안내)
  - 또는 `hdiutil` 직접 사용 (macOS 기본 내장)으로 대체
- **상태**: OPEN

### [P4-V005] Severity: P2 -- Release.entitlements에 server 권한 누락

- **위반 유형**: 네트워크 권한 불일치
- **상세**: `DebugProfile.entitlements`에는 `network.server`와 `network.client` 모두 있지만, `Release.entitlements`에는 `network.client`만 있다. 앱이 localhost에서 서버 프로세스를 subprocess로 실행하고 localhost 포트를 사용하므로, Release 빌드에서도 `network.server` 권한이 필요할 수 있다.
  - 단, sandbox=false이므로 실질적 영향은 없을 수 있다
  - 하지만 향후 sandbox를 활성화하면 문제가 발생한다
- **수정 지시**: Release.entitlements에 `com.apple.security.network.server` = true를 추가 권장
- **상태**: OPEN

### [P4-V006] Severity: P1 -- server_launcher.dart _isProjectRoot() 검증 로직이 번들 모드에서 부적절

- **위반 유형**: 번들 모드 호환성
- **상세**: `_isProjectRoot()` (374-376행)는 `src/main.py` 파일 존재 여부로 프로젝트 루트를 판단한다. PyInstaller onedir 번들에서는 `src/main.py`가 `_internal/src/main.py`로 패키징되므로, `python_backend/src/main.py`는 존재하지 않을 수 있다. 
  - `_findBundledBackend()`이 먼저 호출되므로 번들 모드에서는 `_isProjectRoot()`를 거치지 않을 수 있지만, `_findBundledBackend()`이 실패할 경우 폴백으로 `_isProjectRoot()`가 호출되며 이때 번들 환경에서 실패한다.
  - 또한 `_findBundledBackend()`는 `Resources/python_backend` 디렉토리 존재만 확인하지, 내부에 `trading_server` 실행 파일이 있는지는 확인하지 않는다.
- **수정 지시**: 
  1. `_findBundledBackend()` 내에서 `trading_server` 바이너리 존재도 확인해야 한다
  2. 또는 `_isProjectRoot()`에 `trading_server` 바이너리 존재 체크를 대안 조건으로 추가해야 한다
- **상태**: OPEN

### [P4-V007] Severity: P2 -- server_launcher.dart 파일 크기 562줄 (200줄 제한 초과)

- **위반 유형**: SRP/파일 크기 제한 위반
- **상세**: `server_launcher.dart`는 562줄로, 200줄 제한을 크게 초과한다. ServerLauncher + LaunchAgentStatus + ServerLaunchResult 3개 클래스가 한 파일에 있다. 하지만 이 파일은 Phase 2에서 생성된 기존 파일이므로, Phase 4에서 추가 수정하지 않는 한 기존 부채로 분류한다.
- **상태**: 기존 부채 (Phase 4 무관)

---

## 3. Phase 3에서 이월된 미해결 사항 (Phase 4 빌드 스크립트에서 고려 필수)

| Phase 3 ID | Severity | 내용 | Phase 4 영향 |
|---|---|---|---|
| P3-V001 | P1 | Path(__file__) 하드코딩 12개 파일 | 빌드 후 런타임에서 경로 오류 발생 가능. paths.py로 교체 필요 |
| P3-V002 | P0 | llama-cpp-python Metal GPU .dylib/.metal 누락 | 빌드 결과물에 Metal 지원 누락 시 AI 기능 불가 |
| P3-V003 | P1 | Cython async/await 호환성 미검증 | build_dmg.sh에 Cython 컴파일 + 테스트 단계 포함 필요 |
| P3-V004 | P1 | telegram 패키지 이름 충돌 | 번들 실행 시 import 실패 가능 |
| P3-V005 | P2 | torch 대용량 번들 | .dmg 크기 5GB+ 경고 |
| P3-V006 | P1 | _PORT_FILE 상대 경로 | 번들 모드에서 포트 파일 위치 오류 |

---

## 4. build_dmg.sh 작성 시 필수 포함 항목 체크리스트

build_dmg.sh가 생성되면 다음 항목을 순차적으로 검증한다:

- [ ] 4-1. shebang (`#!/bin/bash`) + `set -euo pipefail` (에러 시 즉시 중단)
- [ ] 4-2. 환경 사전 체크 (Python, PyInstaller, Flutter, create-dmg 존재 확인)
- [ ] 4-3. PyInstaller 빌드 (`pyinstaller trading_server.spec`)
- [ ] 4-4. Cython 컴파일 + .so 교체 (`python setup_cython.py build_ext --inplace` → dist/ 내 .pyc를 .so로 교체)
- [ ] 4-5. Flutter build macos --release
- [ ] 4-6. .app 복사 + python_backend 디렉토리 삽입
  - `cp -a dist/trading_server/ .app/Contents/Resources/python_backend/`
  - 심볼릭 링크 보존 필수
- [ ] 4-7. ad-hoc 코드 서명
  - `codesign --force --deep -s "-" StockTrader.app`
  - 또는 각 framework/dylib 개별 서명 후 전체 서명
- [ ] 4-8. create-dmg로 .dmg 생성
  - 앱 이름, 볼륨 이름, 아이콘 위치, Applications 심볼릭 링크
- [ ] 4-9. 결과물 크기 및 경로 출력

## 5. Gatekeeper 안내 화면 체크리스트

Gatekeeper 안내가 구현되면 다음을 검증한다:

- [ ] 5-1. 안내 화면이 앱 최초 실행 시 표시되는지 (또는 설치 가이드 별도 제공)
- [ ] 5-2. 3가지 방법 중 최소 1가지 안내:
  - "우클릭 → 열기" 방법
  - "시스템 설정 → 개인정보 보호 및 보안" 방법
  - `xattr -cr` 터미널 명령어
- [ ] 5-3. 스크린샷 또는 단계별 그림 포함 (비전공자 대상)
- [ ] 5-4. 한국어 안내 텍스트
- [ ] 5-5. DMG 볼륨 내에도 README 또는 안내 이미지 포함

---

## Violation Summary

| ID | Severity | 내용 | 상태 |
|---|---|---|---|
| P4-V001 | P1 | server_launcher.dart 경로와 빌드 스크립트 간 정합성 확보 필요 | PENDING |
| P4-V002 | P1 | Flutter 앱 이름 불일치 (ai_trading_dashboard vs StockTrader) | PENDING |
| P4-V003 | P0 | Gatekeeper 우회 안내 화면 미구현 [CRITICAL] | OPEN |
| P4-V004 | P2 | create-dmg 미설치 | OPEN |
| P4-V005 | P2 | Release.entitlements에 network.server 권한 누락 | OPEN |
| P4-V006 | P1 | server_launcher.dart _isProjectRoot() 번들 모드 부적절 | OPEN |
| P4-V007 | P2 | server_launcher.dart 562줄 (기존 부채) | 기존 부채 |

**P0 위반 1건 -- Phase 4 완료 전 반드시 해결 필요 (Gatekeeper 안내).**
**P1 위반 3건 -- Phase 4 완료 전 해결 필요.**
**Phase 3 이월 P0 1건 -- llama-cpp-python Metal GPU 번들 확인 필요.**
