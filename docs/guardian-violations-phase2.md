# Guardian Violation Report -- Session 6, Phase 2 (Flutter -- Setup Wizard UI)

## Monitoring Timestamp: 2026-03-17
## Phase: 2 (Flutter -- Setup Wizard UI)
## Active Agents: Flutter sub-agents (setup_service, setup_provider, wizard widgets/steps, app routing, server_launcher)
## Guardian Status: INITIAL SCAN COMPLETE, AWAITING IMPLEMENTATION

---

## Phase 1 Backend Status (선행 작업 검증)

Phase 1 Backend 구현물이 존재함을 확인했다. Phase 2 Flutter 코드는 아래 6개 엔드포인트에 정확히 매칭해야 한다:

| 엔드포인트 | 메서드 | 인증 | 비고 |
|---|---|---|---|
| `/api/setup/status` | GET | 불필요 | → `SetupStatusResponse` (setup_complete, services, models) |
| `/api/setup/config` | POST | 필요 | → `SetupConfigResponse` (success, message, env_path) |
| `/api/setup/validate/{service}` | POST | 필요 | → `SetupValidateResponse` (service, valid, message) |
| `/api/setup/models` | GET | 불필요 | → `ModelsStatusResponse` (models, total_size_gb, downloaded/total count) |
| `/api/setup/models/download` | POST | 필요 | → `ModelDownloadResponse` (status, message) |
| `/api/setup/models/cancel` | POST | 필요 | → `ModelDownloadResponse` (status, message) |

### SetupConfigRequest 필드 (Flutter 입력 폼이 반드시 매칭해야 하는 필드):
- KIS 실거래: `kis_app_key`, `kis_app_secret`, `kis_account_no`, `kis_hts_id`
- KIS 모의투자: `kis_mock_app_key`, `kis_mock_app_secret`, `kis_mock_account_no`
- Claude AI: `claude_mode` ("oauth" | "api_key"), `claude_api_key`
- 텔레그램: `telegram_bot_token`, `telegram_chat_id`
- 외부 데이터: `fred_api_key`, `finnhub_api_key`
- Reddit: `reddit_client_id`, `reddit_client_secret`

### Validate 서비스 목록 (Flutter에서 호출 가능해야 하는 서비스):
- `kis` (credentials: app_key, app_secret)
- `telegram` (credentials: bot_token, chat_id)
- `claude` (credentials: mode, api_key)
- `fred`, `finnhub`, `reddit` (단순 포맷 검증)

---

## Pre-Implementation Checklist (Phase 2 구현 시 반드시 확인할 항목)

### [CRITICAL] 기존 대시보드 기능 보존

**현재 상태**: 앱 시작 시 `MaterialApp.home`이 `ShellScreen()`으로 하드코딩되어 있다 (app.dart:118).

**요구사항**: setup_complete가 false일 때만 위저드를 표시하고, true이면 기존 ShellScreen으로 진입해야 한다.

**구현 시 주의 사항**:
1. `app.dart`의 `home:` 프로퍼티를 조건부로 변경하거나, FutureBuilder/Consumer로 감싸야 한다
2. ShellScreen 내부의 initState 로직(startAutoRefresh, startPolling 등)이 위저드 화면에서 실행되어서는 안 된다
3. app.dart의 MultiProvider 목록에 SetupProvider가 추가되어야 한다
4. 기존 27개 Provider 등록 순서/구조를 변경하지 않아야 한다

### [CRITICAL] 8개 위저드 스텝 구현 완전성

사용자 요구사항에 명시된 8개 스텝:
1. **Welcome** -- 앱 소개, 설정 과정 안내
2. **KIS API Key** -- 한국투자증권 API 키 입력 (발급 가이드 포함) [CRITICAL: 상세 가이드 필수]
3. **Claude AI** -- OAuth / API Key 듀얼 모드 선택
4. **Telegram** -- 봇 토큰 + 채팅 ID 입력
5. **Trading Mode** -- 모의/실전 투자 선택
6. **Optional Keys** -- FRED, Finnhub, Reddit (선택사항)
7. **Models** -- GGUF 모델 다운로드 상태 및 제어
8. **Review** -- 설정 요약 및 최종 확인

---

## 기존 코드베이스 컨벤션 분석 (Phase 2 구현 시 반드시 따라야 하는 패턴)

### 디렉토리 구조 패턴
```
dashboard/lib/
├── services/         ← API 통신 서비스 (api_service.dart, server_launcher.dart, websocket_service.dart)
├── providers/        ← ChangeNotifier 기반 상태관리 (27개 Provider)
├── models/           ← 데이터 모델 클래스 (22개 모델 파일)
├── screens/          ← 전체 화면 위젯 (28개 Screen)
├── widgets/          ← 재사용 가능 UI 컴포넌트 (29개 Widget)
├── theme/            ← 테마/색상/타이포그래피
├── constants/        ← 상수 (api_constants.dart)
├── l10n/             ← 다국어 문자열 (app_strings.dart)
├── animations/       ← 애니메이션 유틸
└── utils/            ← 유틸리티 (env_loader.dart)
```

### Phase 2에서 생성해야 하는 파일 위치 (예상):
- `dashboard/lib/services/setup_service.dart` -- Setup API 통신
- `dashboard/lib/providers/setup_provider.dart` -- 위저드 상태관리
- `dashboard/lib/models/setup_models.dart` -- Setup 관련 데이터 모델
- `dashboard/lib/screens/setup_wizard_screen.dart` -- 위저드 메인 화면
- `dashboard/lib/widgets/setup/` -- 위저드 스텝 위젯들 (steps 하위 폴더 생성 가능)

### Provider 패턴 (필수 준수)
```dart
// 기존 패턴: ChangeNotifier + ApiService DI
class XxxProvider with ChangeNotifier {
  final ApiService _apiService;
  XxxProvider(this._apiService);
  // ...
}
```
- 모든 Provider는 `ChangeNotifier`를 사용한다
- API 호출은 ApiService를 주입받아 사용한다
- `notifyListeners()` 호출로 UI 갱신을 트리거한다

### 한국어 주석 패턴 (필수 준수)
기존 코드의 주석은 모두 `/// 한국어 설명이다.` 또는 `// 한국어 설명` 형식이다.
독스트링은 `~이다/~한다` 체로 작성한다.

### 테마 사용 패턴
```dart
final tc = context.tc;  // TradingColors extension
tc.primary, tc.profit, tc.loss, tc.warning, tc.info
tc.background, tc.surface, tc.surfaceBorder
tc.textPrimary, tc.textSecondary
```
절대 하드코딩 색상 사용 금지. 반드시 `context.tc` 또는 `Theme.of(context)` 사용.

### 타이포그래피 패턴
```dart
AppTypography.displaySmall, AppTypography.labelMedium, AppTypography.labelLarge
```

### 스페이싱 패턴
```dart
AppSpacing.hGapSm, AppSpacing.borderRadiusMd
```

---

## PRE-EXISTING VIOLATIONS (기존 부채, Phase 2에서 악화시키지 않을 것)

### [PRE-001] 파일 크기 초과 (기존)
기존 대시보드 파일 중 200줄 초과 파일이 다수 존재한다:
- `shell_screen.dart`: 808줄
- `api_service.dart`: 1708줄
- `news_screen.dart`: 1963줄
- `overview_screen.dart`: 1920줄
- 기타 다수

이것은 기존 부채이며 Phase 2의 위반은 아니다. 다만 Phase 2에서 **새로 생성하는 파일**은 200줄 한도를 준수해야 한다.

### [PRE-002] 영문 주석 (기존)
`dashboard/lib/widgets/position_card.dart` 등 일부 위젯에 영문 주석 존재.
- `// Header: Ticker + PnL badge`
- `// Qty + PnL amount`
- 기타

Phase 2에서 새로 작성하는 코드에는 영문 주석 사용 금지.

---

## ACTIVE VIOLATIONS (Phase 2 진행 중 발견)

### 현재 상태: Phase 2 구현물 미감지

Phase 2 관련 Flutter 파일이 아직 생성되지 않았다. 다음 파일들이 생성되는 시점에 실시간 모니터링을 수행한다:

- [ ] `setup_service.dart` (또는 유사한 이름의 Setup API 서비스)
- [ ] `setup_provider.dart` (또는 유사한 이름의 위저드 상태 Provider)
- [ ] `setup_models.dart` (Setup 응답 모델)
- [ ] 위저드 화면 / 스텝 위젯 파일들
- [ ] `app.dart` 수정 (조건부 라우팅)
- [ ] `api_constants.dart` 수정 (Setup 엔드포인트 상수 추가)

---

## Phase 2 구현 시 감시할 위반 항목 체크리스트

### Code-Level Checks
- [ ] Dart 파일 200줄 초과 여부
- [ ] 영문 주석 사용 여부
- [ ] 하드코딩 색상 사용 여부 (tc 미사용)
- [ ] `!important` CSS 사용 여부 (해당 없음)
- [ ] 정확한 API 엔드포인트 경로 일치 여부
- [ ] SetupConfigRequest 필드명 정확 일치 여부
- [ ] validate 서비스명 정확 일치 여부

### Architecture-Level Checks
- [ ] 파일이 dashboard/lib/ 내에만 생성되는지
- [ ] Provider 패턴(ChangeNotifier + ApiService DI) 준수 여부
- [ ] 기존 Provider 등록 순서 파괴 여부 (app.dart)
- [ ] ShellScreen 기존 기능 손상 여부
- [ ] 새 서비스가 ApiService에 직접 메서드를 추가하는 대신 별도 서비스 파일로 분리하는지

### Requirement-Level Checks
- [ ] 8개 위저드 스텝 모두 구현되었는지
- [ ] KIS 스텝에 API 키 발급 상세 가이드가 포함되는지
- [ ] Claude OAuth + API Key 듀얼 모드가 구현되는지
- [ ] setup_complete=false일 때만 위저드 표시되는지
- [ ] setup_complete=true이면 기존 ShellScreen으로 직행하는지
- [ ] 모델 다운로드 진행률 UI가 있는지
- [ ] Review 스텝에서 설정 요약이 표시되는지

---

## Phase Completion Checklist (Phase 2)

- [ ] User original requirements 100% reflected -- **PENDING** (구현 미착수)
- [ ] All CLAUDE.md Non-negotiable rules complied with -- **PENDING**
- [ ] Current Phase goals achieved -- **PENDING**
- [ ] No unresolved P0/P1 violations remaining -- **YES** (현시점)
- [ ] Information to be passed to next Phase is complete -- **N/A**
- [ ] docs/guardian-requirements.md is up to date -- **YES**
