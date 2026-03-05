# Flutter Dashboard Setup Guide

## 빠른 시작

### 1. Flutter 설치 확인
```bash
flutter doctor
```

Flutter SDK가 설치되어 있지 않다면 [Flutter 공식 문서](https://flutter.dev/docs/get-started/install)를 참고하세요.

### 2. 프로젝트 초기화
```bash
cd dashboard

# 의존성 설치
flutter pub get

# Flutter 프로젝트가 정상인지 확인
flutter doctor -v
```

### 3. iOS/Android 플랫폼 파일 생성
현재 Dart 코드만 생성되어 있으므로, iOS와 Android 플랫폼 파일을 생성해야 합니다.

```bash
# 현재 디렉토리에서 Flutter 프로젝트 초기화
cd dashboard

# iOS 및 Android 플랫폼 파일 생성
flutter create --platforms=ios,android .
```

이 명령어는 다음 폴더를 생성합니다:
- `ios/` - iOS 프로젝트 파일
- `android/` - Android 프로젝트 파일

### 4. 백엔드 API 실행
```bash
# 새 터미널에서 (프로젝트 루트에서 실행)
python src/main.py
```

백엔드가 `http://localhost:9500`에서 실행되는지 확인하세요.

### 5. 앱 실행

#### iOS 시뮬레이터 (macOS만 가능)
```bash
# iOS 시뮬레이터 열기
open -a Simulator

# 앱 실행
flutter run -d ios
```

#### Android 에뮬레이터
```bash
# Android Studio에서 에뮬레이터 실행 후
flutter run -d android
```

#### Chrome 웹 브라우저 (테스트용)
```bash
flutter run -d chrome
```

## API URL 설정

### 로컬 개발 (기본값)
현재 설정: `http://localhost:9500`

### 실제 기기에서 테스트
Mac의 IP 주소로 변경해야 합니다.

1. Mac의 IP 주소 확인:
```bash
ipconfig getifaddr en0
# 예: 192.168.1.100
```

2. API 서비스 파일 수정:

`lib/services/api_service.dart`:
```dart
ApiService({this.baseUrl = 'http://192.168.1.100:9500'});
```

`lib/services/websocket_service.dart`:
```dart
WebSocketService({this.baseUrl = 'ws://192.168.1.100:9500'});
```

### Android 에뮬레이터 특수 주소
Android 에뮬레이터에서는 `10.0.2.2`가 호스트 머신의 `localhost`입니다.

```dart
ApiService({this.baseUrl = 'http://10.0.2.2:9500'});
WebSocketService({this.baseUrl = 'ws://10.0.2.2:9500'});
```

## 문제 해결

### 1. Flutter SDK not found
```bash
# Flutter 설치
# macOS: Homebrew 사용
brew install flutter

# 또는 직접 다운로드
# https://flutter.dev/docs/get-started/install
```

### 2. iOS pod install 에러
```bash
cd ios
pod install
cd ..
```

### 3. Android Gradle 에러
```bash
cd android
./gradlew clean
cd ..
```

### 4. 의존성 충돌
```bash
flutter clean
flutter pub get
```

### 5. 연결 에러 (Connection refused)
- 백엔드 API가 실행 중인지 확인
- 방화벽 설정 확인
- API URL이 올바른지 확인

### 6. WebSocket 연결 실패
- WebSocket이 `ws://` 프로토콜을 사용하는지 확인
- HTTPS를 사용하는 경우 `wss://` 사용

## 개발 팁

### Hot Reload
앱 실행 중 코드 수정 후:
- **r** - Hot reload
- **R** - Hot restart
- **q** - 종료

### 디버그 모드
```bash
flutter run --debug
```

### 릴리스 빌드
```bash
# iOS
flutter build ios --release

# Android APK
flutter build apk --release

# Android App Bundle (권장)
flutter build appbundle --release
```

### 로그 확인
```bash
flutter logs
```

### 성능 프로파일링
```bash
flutter run --profile
```

## VS Code 설정 (권장)

### 확장 프로그램 설치
1. Flutter
2. Dart
3. Flutter Widget Snippets

### launch.json 생성
`.vscode/launch.json`:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Flutter: Run",
      "type": "dart",
      "request": "launch",
      "program": "lib/main.dart"
    },
    {
      "name": "Flutter: Debug",
      "type": "dart",
      "request": "launch",
      "program": "lib/main.dart",
      "flutterMode": "debug"
    }
  ]
}
```

## 프로덕션 체크리스트

### 배포 전 확인사항
- [ ] API URL을 프로덕션 서버로 변경
- [ ] 디버그 로그 제거
- [ ] 앱 아이콘 설정
- [ ] 스플래시 스크린 설정
- [ ] iOS: Info.plist 권한 설정
- [ ] Android: AndroidManifest.xml 권한 설정
- [ ] 버전 번호 업데이트 (pubspec.yaml)
- [ ] 릴리스 빌드 테스트
- [ ] 성능 테스트
- [ ] 보안 검토

### iOS 배포
1. Apple Developer 계정 필요
2. Xcode에서 서명 설정
3. App Store Connect에 앱 등록
4. TestFlight로 베타 테스트
5. App Store 제출

### Android 배포
1. Google Play Console 계정 필요
2. 서명 키 생성
3. Google Play Console에 앱 등록
4. 내부 테스트 트랙 업로드
5. 프로덕션 트랙에 배포

## 유용한 명령어

```bash
# Flutter 버전 확인
flutter --version

# 연결된 기기 목록
flutter devices

# 앱 분석
flutter analyze

# 테스트 실행
flutter test

# 빌드 사이즈 분석
flutter build apk --analyze-size

# 의존성 업그레이드
flutter pub upgrade

# 캐시 정리
flutter clean
```

## 다음 단계

1. 앱 실행 및 기능 테스트
2. UI/UX 개선 (필요시)
3. 성능 최적화
4. 추가 기능 구현
5. 테스트 코드 작성
6. 프로덕션 배포

## 지원

문제가 발생하면:
1. `flutter doctor -v` 실행하여 환경 확인
2. 에러 메시지 확인
3. Flutter 공식 문서 참고
4. GitHub Issues 검색
