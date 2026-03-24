# Guardian Violation Report -- Phase 5

## 현재 Phase 5 상태 요약

Phase 5의 3개 태스크 (LaunchAgent 자동화, Sparkle 업데이트, 언인스톨)에 대해 초기 스캔을 수행했다.
아래는 발견된 위반 및 미구현 사항이다.

---

## [P0-PH5-001] Severity: P0 — 소비자용 LaunchAgent plist 미구현
- **Discovery point**: Phase 5, 초기 스캔
- **Violating agent**: 미할당 (아직 구현 시작 전)
- **Violation type**: 핵심 요구사항 미구현
- **Violation details**: 소비자용 LaunchAgent plist를 동적으로 생성하는 로직이 없다. 기존 plist 2개(com.trading.server.plist, com.trading.autotrader.plist)는 모두 개발자 절대경로 하드코딩이다. Phase 5의 핵심 요구사항인 ".app 내부 바이너리를 가리키는 plist 자동 생성"이 전혀 구현되지 않았다.
- **Related file**: scripts/com.trading.server.plist (하드코딩 경로), scripts/launchagent_setup.py (개발자용)
- **Original requirement**: [CRITICAL] LaunchAgent plist가 .app 내부 바이너리를 가리켜야 함
- **Correction order**: 
  1. ServerLauncher.dart 또는 별도 launchagent_service.dart에서 번들 모드일 때 plist를 동적 생성해야 한다
  2. ProgramArguments는 반드시 /Applications/StockTrader.app/Contents/Resources/python_backend/trading_server를 가리켜야 한다
  3. WorkingDirectory는 ~/Library/Application Support/com.stocktrader.ai/를 사용해야 한다
  4. plist를 ~/Library/LaunchAgents/com.stocktrader.ai.plist로 설치 후 launchctl load해야 한다
- **Status**: OPEN

## [P0-PH5-002] Severity: P0 — Sparkle 자동 업데이트 미구현
- **Discovery point**: Phase 5, 초기 스캔
- **Violating agent**: 미할당 (아직 구현 시작 전)
- **Violation type**: 핵심 요구사항 미구현
- **Violation details**: Sparkle 프레임워크 또는 자동 업데이트 관련 코드가 프로젝트에 전혀 존재하지 않는다. pubspec.yaml에 sparkle_flutter 패키지가 없고, macOS Runner 프로젝트에 Sparkle.framework이 없다. appcast.xml 설정도 없다.
- **Related file**: dashboard/pubspec.yaml, dashboard/macos/
- **Original requirement**: [CRITICAL] Sparkle은 Flutter macOS 앱에 통합
- **Correction order**: 
  1. sparkle_flutter 패키지를 pubspec.yaml에 추가하거나 네이티브 Swift 브릿지로 Sparkle.framework 통합
  2. Info.plist에 SUFeedURL(appcast.xml URL) 설정
  3. Settings UI에 "업데이트 확인" 버튼 및 "자동 업데이트" 토글 추가
  4. Ed25519 공개키 설정 (서명 없는 웹 배포라도 업데이트 자체는 서명 검증 필요)
- **Status**: OPEN

## [P0-PH5-003] Severity: P0 — 언인스톨 기능 미구현
- **Discovery point**: Phase 5, 초기 스캔
- **Violating agent**: 미할당 (아직 구현 시작 전)
- **Violation type**: 핵심 요구사항 미구현
- **Violation details**: 언인스톨(제거) 기능이 전혀 구현되지 않았다. "uninstall" 키워드로 dashboard/ 전체를 검색해도 0건이다. LaunchAgent 해제 + plist 삭제 + Application Support 삭제 3단계가 모두 필요하다.
- **Related file**: (미구현)
- **Original requirement**: [CRITICAL] 언인스톨: LaunchAgent 해제 + plist 삭제 + Application Support 삭제(확인 후)
- **Correction order**: 
  1. Settings UI에 "앱 제거" 또는 "데이터 초기화" 섹션 추가
  2. 3단계 언인스톨 로직 구현: (a) launchctl unload + plist 삭제, (b) ~/Library/Application Support/com.stocktrader.ai/ 삭제 확인 다이얼로그, (c) 삭제 실행
  3. 비전공자 대상이므로 확인 다이얼로그에 어떤 데이터가 삭제되는지 명확히 안내
  4. 언인스톨 완료 후 앱 종료 안내
- **Status**: OPEN

---

## 기존 부채 (Phase 5 이전부터 존재, 악화 금지)

## [P2-PH5-004] Severity: P2 — settings_screen.dart 파일 크기 초과
- **Discovery point**: Phase 5, 초기 스캔
- **Violating agent**: N/A (기존 부채)
- **Violation type**: 파일 크기 규칙 위반
- **Violation details**: settings_screen.dart가 1683줄로 200줄 한도를 크게 초과한다. Phase 5에서 이 파일에 코드를 추가하면 더 악화된다.
- **Related file**: dashboard/lib/screens/settings_screen.dart:1683줄
- **Original requirement**: 파일 200줄 한도
- **Correction order**: Phase 5에서 LaunchAgent 설치 UI나 언인스톨 UI를 추가할 때 settings_screen.dart에 직접 추가하지 말고 별도 위젯 파일로 분리해야 한다.
- **Status**: OPEN (기존 부채 — 악화 금지)

## [P2-PH5-005] Severity: P2 — server_launcher.dart 파일 크기 초과
- **Discovery point**: Phase 5, 초기 스캔
- **Violating agent**: N/A (기존 부채)
- **Violation type**: 파일 크기 규칙 위반
- **Violation details**: server_launcher.dart가 562줄로 200줄 한도를 크게 초과한다. Phase 5에서 LaunchAgent plist 생성 로직을 추가하면 더 악화된다.
- **Related file**: dashboard/lib/services/server_launcher.dart:562줄
- **Original requirement**: 파일 200줄 한도
- **Correction order**: 새로운 LaunchAgent 관련 로직은 별도 launchagent_service.dart 또는 유사한 파일로 분리해야 한다.
- **Status**: OPEN (기존 부채 — 악화 금지)

## [P3-PH5-006] Severity: P3 — 일부 영어 코멘트 존재
- **Discovery point**: Phase 5, 초기 스캔
- **Violating agent**: N/A (기존 부채)
- **Violation type**: Korean comments 규칙 위반
- **Violation details**: position_card.dart, ticker_heatmap.dart, app_strings.dart 등에서 영어 코멘트가 발견된다 (예: "// Header: Ticker + PnL badge", "// Header row with date labels"). Phase 5 신규 코드에서는 절대 영어 코멘트를 사용하면 안 된다.
- **Related file**: dashboard/lib/widgets/position_card.dart, dashboard/lib/widgets/ticker_heatmap.dart 등
- **Original requirement**: Korean comments only
- **Correction order**: Phase 5 신규 코드에서 영어 코멘트 사용 금지. 기존 부채는 Phase 5.5 File Cleanup에서 일괄 처리.
- **Status**: OPEN (기존 부채)

---

## 구조적 관찰 (위반은 아니나 Phase 5 구현 시 주의 필요)

### 기존 LaunchAgent 체계와 소비자 모드의 충돌
- 기존 plist 2개(com.trading.server, com.trading.autotrader)는 개발자 환경 전용이다.
- 소비자 모드에서는 com.stocktrader.ai (또는 유사) 레이블의 새 plist를 동적으로 생성해야 한다.
- ServerLauncher.dart의 _serviceLabel이 현재 'com.trading.server'로 하드코딩되어 있다. 번들 모드에서는 다른 레이블을 사용해야 할 수 있다.

### Sparkle 통합 시 Apple Developer 미가입 제약
- 사용자가 Apple Developer에 미가입 상태이므로 공증(notarization)이 불가능하다.
- Sparkle 업데이트 시 Ed25519 서명만으로 검증해야 한다 (Apple 서명 없이).
- 이 제약을 Sparkle 설정에 반영해야 한다.
