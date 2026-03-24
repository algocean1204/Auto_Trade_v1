# Guardian Requirements Log -- Phase 5 (LaunchAgent + 자동 업데이트 + 언인스톨)

## User Original Requirements (전문)

비전공자가 웹사이트에서 .dmg 다운로드 → 설치 → 위저드로 API 키 설정 → 바로 사용. macOS Apple Silicon 전용.

## Current Phase: 5 (LaunchAgent + 자동 업데이트 + 언인스톨)
## Phase Goal: LaunchAgent plist 생성/설치 자동화, Sparkle 자동 업데이트 통합, 언인스톨 기능 구현
## Active Agents: general-purpose implementation agents

## Critical Requirements (즉시 개입 필요)
- [CRITICAL] LaunchAgent plist가 .app 내부 바이너리를 가리켜야 함 (StockTrader.app/Contents/Resources/python_backend/trading_server)
- [CRITICAL] WorkingDirectory는 ~/Library/Application Support/com.stocktrader.ai/
- [CRITICAL] Sparkle은 Flutter macOS 앱에 통합 (sparkle_flutter 패키지 or 네이티브 Swift 브릿지)
- [CRITICAL] 언인스톨: LaunchAgent 해제 + plist 삭제 + Application Support 삭제(확인 후)
- [CRITICAL] 비전공자 대상이므로 모든 자동화가 UI에서 제어 가능해야 함
- [CRITICAL] Korean comments only (Dart/Python 코드)
- [CRITICAL] 파일 200줄 한도 준수 (새 파일 기준)

## Phase 5 Tasks
### 5-1. LaunchAgent plist 생성/설치 자동화
- 앱 최초 실행 시 또는 설정에서 LaunchAgent plist를 자동 생성/설치
- ProgramArguments가 .app 번들 내부 trading_server 바이너리를 가리켜야 함
- WorkingDirectory = ~/Library/Application Support/com.stocktrader.ai/
- UI에서 LaunchAgent 설치/해제/상태확인 제어 가능

### 5-2. Sparkle 자동 업데이트 통합
- Sparkle 프레임워크를 Flutter macOS 앱에 통합
- appcast.xml URL 설정
- UI에서 업데이트 확인/자동 업데이트 토글 가능

### 5-3. 언인스톨 기능
- LaunchAgent 해제 + plist 삭제
- ~/Library/Application Support/com.stocktrader.ai/ 삭제 (사용자 확인 후)
- UI에서 언인스톨 버튼 → 확인 다이얼로그 → 실행

## 기존 구현 현황 (Phase 5 시작 시점)
### 이미 구현됨:
- ServerLauncher.dart: LaunchAgent 제어 (start/stop/restart via launchctl) — 562줄
- settings_screen.dart 서버 관리 탭: LaunchAgent 상태 표시 + 시작/종료/재시작 버튼 — 1683줄
- launchagent_setup.py: Python CLI 기반 LaunchAgent 설치/제거 — 202줄
- scripts/com.trading.server.plist: 개발자용 하드코딩 plist (절대경로 사용)
- scripts/com.trading.autotrader.plist: 개발자용 하드코딩 plist (절대경로 사용)
- src/common/paths.py: 번들/개발 환경 분기 경로 모듈 — 119줄
- build_dmg.sh: .dmg 패키징 파이프라인 — 679줄

### 아직 구현되지 않음:
- 소비자용 LaunchAgent plist 자동 생성 (번들 내부 바이너리 경로, 동적 생성)
- Sparkle 자동 업데이트 프레임워크 통합 (전혀 없음)
- 언인스톨 기능 (전혀 없음)
- UI에서의 LaunchAgent 설치/등록 자동화 (기존은 CLI 스크립트)

## Monitored Directories
- dashboard/lib/
- scripts/
- src/common/
- src/setup/

## 이전 Phase 미해결 사항 (리그레션 금지)
- settings_screen.dart: 1683줄 (200줄 한도 초과 — 기존 부채, Phase 5에서 악화 금지)
- server_launcher.dart: 562줄 (200줄 한도 초과 — 기존 부채, Phase 5에서 악화 금지)
- 영어 코멘트 일부 존재 (position_card.dart, ticker_heatmap.dart 등 — 기존 부채)
