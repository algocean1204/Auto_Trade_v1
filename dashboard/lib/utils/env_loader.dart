import 'dart:io';

/// 프로젝트 루트의 .env 파일에서 환경변수를 런타임에 로드하는 유틸리티이다.
///
/// 우선순위:
///   1. Dart compile-time define (--dart-define=KEY=VALUE)
///   2. .env 파일 (런타임, 동일 머신)
///   3. defaultValue
///
/// 사용 예시:
///   final key = EnvLoader.get('API_SECRET_KEY');
class EnvLoader {
  EnvLoader._();

  static final Map<String, String> _cache = {};
  static bool _loaded = false;

  /// .env 파일을 탐색하여 파싱한다. 이미 로드된 경우 재실행하지 않는다.
  static void load() {
    if (_loaded) return;
    _loaded = true;

    final file = _findEnvFile();
    if (file != null) {
      _parseEnvFile(file);
    }
  }

  /// 환경변수 값을 반환한다.
  ///
  /// [key] : 환경변수 키 이름
  /// [defaultValue] : 키가 없을 때 반환할 기본값 (기본 빈 문자열)
  static String get(String key, {String defaultValue = ''}) {
    load();

    // 1. Dart compile-time define이 최우선이다.
    // ignore: do_not_use_environment
    final dartDefine = String.fromEnvironment(key);
    if (dartDefine.isNotEmpty) return dartDefine;

    // 2. .env 파일에서 읽은 값을 반환한다.
    return _cache[key] ?? defaultValue;
  }

  /// .env 캐시를 초기화하고 다시 로드한다.
  ///
  /// 셋업 위저드에서 .env를 새로 생성한 후 호출하여
  /// ApiService/SetupService가 최신 API_SECRET_KEY를 사용하도록 한다.
  static void reload() {
    _cache.clear();
    _loaded = false;
    load();
  }

  // ── Private helpers ──

  /// .env 파일을 찾아 File 객체를 반환한다. 찾지 못하면 null을 반환한다.
  static File? _findEnvFile() {
    // 후보 경로 목록을 순서대로 탐색한다.
    final candidates = _buildCandidates();
    for (final path in candidates) {
      final file = File(path);
      if (file.existsSync()) return file;
    }
    return null;
  }

  /// 탐색할 후보 경로 목록을 생성한다.
  ///
  /// 번들 모드(.app)에서는 ~/Library/Application Support/com.stocktrader.ai/.env를
  /// 최우선으로 탐색한다. 서버가 해당 경로를 작업 디렉토리로 사용하므로
  /// .env도 이 위치에 저장된다.
  static List<String> _buildCandidates() {
    final paths = <String>[];

    // 번들 모드: Application Support 경로를 최우선으로 추가한다.
    try {
      final exePath = Platform.resolvedExecutable;
      if (exePath.contains('.app/Contents/MacOS/')) {
        final home = Platform.environment['HOME'] ?? '';
        if (home.isNotEmpty) {
          paths.add(
            '$home/Library/Application Support/com.stocktrader.ai/.env',
          );
        }
      }
    } catch (_) {}

    // 실행 파일 기준으로 상위 디렉터리를 최대 12단계까지 탐색한다.
    // macOS 앱 패키지 구조가 깊다:
    // dashboard/build/macos/Build/Products/Debug/App.app/Contents/MacOS/App
    // → 프로젝트 루트까지 10단계 필요
    try {
      var dir = File(Platform.resolvedExecutable).parent;
      for (var i = 0; i < 12; i++) {
        paths.add('${dir.path}/.env');
        dir = dir.parent;
      }
    } catch (_) {}

    // 현재 작업 디렉터리 기준으로도 탐색한다 (flutter run 시 유용).
    try {
      var dir = Directory.current;
      for (var i = 0; i < 8; i++) {
        paths.add('${dir.path}/.env');
        dir = dir.parent;
      }
    } catch (_) {}

    return paths;
  }

  /// .env 파일을 한 줄씩 읽어 KEY=VALUE 형태를 파싱한다.
  static void _parseEnvFile(File file) {
    try {
      for (final line in file.readAsLinesSync()) {
        final trimmed = line.trim();
        // 빈 줄과 주석(#)은 건너뛴다.
        if (trimmed.isEmpty || trimmed.startsWith('#')) continue;
        final idx = trimmed.indexOf('=');
        if (idx <= 0) continue;
        final key = trimmed.substring(0, idx).trim();
        var value = trimmed.substring(idx + 1).trim();
        // 따옴표로 감싸진 값의 따옴표를 제거한다.
        if (value.length >= 2 &&
            ((value.startsWith('"') && value.endsWith('"')) ||
                (value.startsWith("'") && value.endsWith("'")))) {
          value = value.substring(1, value.length - 1);
        }
        _cache[key] = value;
      }
    } catch (_) {
      // 파일 읽기 실패 시 조용히 무시한다.
    }
  }
}
