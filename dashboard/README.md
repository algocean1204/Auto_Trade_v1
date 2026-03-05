# AI Trading Dashboard - Flutter Mobile App

AI Trading System V2를 모니터링하기 위한 Flutter 모바일 대시보드 애플리케이션입니다.

## 기능

### 1. 홈 대시보드
- 총 자산, 현금, 오늘 수익 실시간 표시
- 누적 수익률 및 활성 포지션 수
- 시스템 상태 모니터링 (Claude AI, KIS API, Database, Fallback)

### 2. 차트 대시보드
- 일일 수익률 추이 라인 차트
- 누적 수익률 영역 차트
- 종목별/시간대별 수익 히트맵
- Maximum Drawdown 차트

### 3. 기술적 지표 설정
- 모멘텀 지표: RSI, MACD, Stochastic
- 추세 지표: MA Cross, ADX
- 변동성 지표: Bollinger Bands, ATR
- 지표별 가중치 조정 슬라이더
- 프리셋 (기본, 모멘텀 중심, 추세 중심, 균형)

### 4. AI 리포트
- 일일 리포트: 당일 거래 분석 및 개선사항
- 주간 리포트: 심층 분석, 패턴 발견, 전략 제안
- 조정 대기: AI가 제안한 파라미터 변경 승인/거부

### 5. 알림 내역
- 거래, 손절, 시스템, 피드백 알림
- 심각도별 필터링 (정보, 경고, 치명적)
- 읽음/안읽음 상태 관리

### 6. 추가 기능
- 전략 파라미터 설정
- 수동 뉴스 크롤링
- ETF 유니버스 관리 (Bull/Bear 2X)

## 설치 및 실행

### 1. Flutter 설치
```bash
# Flutter SDK 설치 확인
flutter --version

# Flutter 3.3.0 이상 필요
```

### 2. 의존성 설치
```bash
cd dashboard
flutter pub get
```

### 3. 백엔드 API 실행
백엔드 FastAPI 서버가 `localhost:9500`에서 실행 중이어야 합니다.

```bash
# 프로젝트 루트에서
cd src
python main.py
```

### 4. 앱 실행

#### iOS 시뮬레이터
```bash
flutter run -d ios
```

#### Android 에뮬레이터
```bash
flutter run -d android
```

#### 실제 기기
```bash
# 연결된 기기 확인
flutter devices

# 특정 기기에서 실행
flutter run -d <device_id>
```

## API 엔드포인트 설정

기본 API URL은 `http://localhost:9500`입니다. 다른 URL을 사용하려면 `lib/services/api_service.dart`와 `lib/services/websocket_service.dart`에서 `baseUrl`을 수정하세요.

```dart
// lib/services/api_service.dart
ApiService({this.baseUrl = 'http://YOUR_SERVER_IP:9500'});

// lib/services/websocket_service.dart
WebSocketService({this.baseUrl = 'ws://YOUR_SERVER_IP:9500'});
```

## 프로젝트 구조

```
dashboard/
├── lib/
│   ├── main.dart                   # 앱 진입점
│   ├── app.dart                    # 앱 설정 및 Provider 등록
│   ├── theme.dart                  # 다크 테마 정의
│   ├── models/                     # 데이터 모델
│   ├── services/                   # API 및 WebSocket 서비스
│   ├── providers/                  # 상태 관리 (Provider)
│   ├── screens/                    # 화면
│   └── widgets/                    # 재사용 가능한 위젯
├── pubspec.yaml                    # 의존성 정의
└── analysis_options.yaml           # 코드 린트 설정
```

## 주요 기술 스택

- **Flutter**: 3.3.0+
- **상태 관리**: Provider 6.1.0
- **차트**: fl_chart 0.69.0
- **HTTP 통신**: http 1.2.0
- **WebSocket**: web_socket_channel 3.0.0
- **폰트**: Google Fonts (Noto Sans)
- **국제화**: intl 0.19.0

## 디자인 가이드

### 색상 팔레트
- Primary: Deep Blue (#1A237E)
- Accent: Electric Blue (#448AFF)
- Background: Dark Navy (#0A0E27)
- Surface: Dark Blue (#1A1F3A)
- Profit: Green (#4CAF50)
- Loss: Red (#F44336)

### 타이포그래피
- 한글: Noto Sans
- 숫자/영문: Noto Sans

### UI/UX 원칙
- Material 3 디자인 시스템
- 다크 테마 (트레이딩 앱 스타일)
- 둥근 모서리 카드 (16px radius)
- 일관된 패딩 (16px)
- 수익/손실 색상 구분 (Green/Red)

## 실시간 업데이트

WebSocket을 통해 다음 데이터가 실시간으로 업데이트됩니다:
- 포지션 변경
- 거래 체결
- 알림 수신
- 크롤링 진행 상태

자동 재연결 기능이 구현되어 있어 연결이 끊어져도 5초 후 재시도합니다.

## 문제 해결

### 1. 연결 오류
- 백엔드 API가 실행 중인지 확인
- 방화벽 설정 확인
- API URL이 올바른지 확인

### 2. 빌드 오류
```bash
# 캐시 정리
flutter clean
flutter pub get

# 재빌드
flutter run
```

### 3. iOS 시뮬레이터에서 localhost 연결 불가
- `localhost` 대신 `127.0.0.1` 사용
- 또는 맥의 실제 IP 주소 사용

### 4. Android 에뮬레이터에서 localhost 연결 불가
- `10.0.2.2` 사용 (에뮬레이터의 호스트 머신 주소)

## 라이선스

이 프로젝트는 AI Trading System V2의 일부입니다.
