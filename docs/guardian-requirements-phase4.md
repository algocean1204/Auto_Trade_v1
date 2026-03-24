# Guardian Requirements Log -- Phase 4 (.dmg 빌드 파이프라인)

## User Original Requirements (전문)

비전공자가 웹사이트에서 .dmg 다운로드 → 설치 → 위저드로 API 키 설정 → 바로 사용.
macOS Apple Silicon 전용, .dmg 인스톨러, 바이너리 배포, Apple Developer 미가입 (ad-hoc 서명).

## Current Phase: 4 (.dmg 빌드 파이프라인)

## Phase Goal:
`scripts/build_dmg.sh` 빌드 스크립트를 작성하여 PyInstaller 빌드 결과물과 Flutter .app을 조립하고,
ad-hoc 코드 서명 + create-dmg로 최종 .dmg 인스톨러를 생성한다.
Gatekeeper 우회 안내 화면을 Flutter 앱에 포함한다.

## Active Agents: build script developer (general-purpose)

## Critical Requirements (즉시 개입 필요)
- [CRITICAL] ad-hoc 서명만 사용 (Apple Developer 미가입, codesign -s "-")
- [CRITICAL] Gatekeeper 우회 안내 필수 (우클릭 → 열기 가이드 화면)
- [CRITICAL] .app 내부에 python_backend 디렉토리 배치 필수 (.app/Contents/Resources/python_backend/)
- [CRITICAL] Flutter macOS 앱이 python_backend를 subprocess로 실행
- [CRITICAL] build_dmg.sh가 전체 파이프라인 수행: PyInstaller → Flutter → .app 조립 → .dmg

## Phase 4 구체적 산출물:
1. `scripts/build_dmg.sh` -- 전체 빌드 파이프라인 스크립트
2. Gatekeeper 안내 화면 -- Flutter UI (설치 후 첫 실행 안내)
3. .dmg 파일 -- 최종 배포 아티팩트

## Phase 4 빌드 스크립트 필수 단계:
- Step 1: PyInstaller 빌드 → `dist/trading_server/` 생성
- Step 2: Cython 컴파일 (5개 민감 모듈 → .so 교체)
- Step 3: Flutter build macos --release → `.app` 생성
- Step 4: `dist/trading_server/` → `.app/Contents/Resources/python_backend/` 복사
- Step 5: Ad-hoc 코드 서명 (`codesign --force --deep -s "-"`)
- Step 6: create-dmg 로 .dmg 생성

## Phase 3 미해결 사항 (Phase 4에서 고려 필요):
- P3-V001 (P1): Path(__file__) 하드코딩 12개 파일 -- PyInstaller 호환성 위반 (OPEN)
- P3-V002 (P0): llama-cpp-python Metal GPU .dylib/.metal 번들 누락 위험 (OPEN)
- P3-V003 (P1): Cython 대상 파일 async/await + annotations 호환성 미검증 (OPEN)
- P3-V004 (P1): src/telegram/ 과 python-telegram-bot 이름 충돌 (OPEN)
- P3-V005 (P2): sentence-transformers/torch 대용량 번들 (5GB+) 경고 (OPEN)
- P3-V006 (P1): api_server.py _PORT_FILE 상대 경로 하드코딩 (OPEN)

## 현재 프로젝트 상태 (Phase 4 시작 시점):
- PyInstaller spec 파일: 존재 (trading_server.spec, ad-hoc 서명 포함)
- PyInstaller 빌드 결과: dist/trading_server/ 존재 (80MB 바이너리)
- Flutter 앱: dashboard/ 디렉토리, Release 빌드 존재 (ai_trading_dashboard.app)
- Setup Wizard: 8단계 위저드 구현 완료
- server_launcher.dart: 번들 모드 감지 + python_backend 경로 탐색 로직 구현 완료
- create-dmg: 미설치 (brew install create-dmg 필요)
- Gatekeeper 안내 화면: 미구현
- build_dmg.sh: 미작성

## Monitored Files/Directories:
- scripts/build_dmg.sh (신규 생성 예정)
- dashboard/lib/ (Gatekeeper 가이드 화면 추가 예정)
- dist/ (빌드 산출물)
