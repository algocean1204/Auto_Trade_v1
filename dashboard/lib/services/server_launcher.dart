import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

/// Python 트레이딩 서버 프로세스를 관리하는 서비스이다.
///
/// Flutter 데스크탑 앱에서 버튼 클릭 시 백엔드 서버를 자동으로 시작/종료한다.
/// SQLite+인메모리 캐시 기반이므로 별도 인프라가 필요하지 않다.
///
/// 사용 흐름:
///   1. ensureRunning() → 서버가 꺼져 있으면 자동 시작, 이미 실행 중이면 즉시 반환
///   2. stop() → 서버 프로세스를 SIGTERM으로 안전 종료
class ServerLauncher {
  ServerLauncher._();

  static final ServerLauncher instance = ServerLauncher._();

  /// 서버 프로세스 핸들이다. 이 앱이 시작한 프로세스만 추적한다.
  Process? _serverProcess;

  /// 이 앱이 서버를 시작했는지 여부이다.
  bool _launchedByUs = false;

  /// ensureRunning() 동시 호출 방지 Completer이다.
  /// null이면 현재 실행 중인 ensureRunning이 없다.
  Completer<ServerLaunchResult>? _ensureRunningCompleter;

  /// 캐시된 프로젝트 루트 경로이다.
  String? _projectRoot;

  /// 서버 stdout/stderr 출력을 저장한다 (디버깅용, 최근 100줄).
  final List<String> _serverLogs = [];

  /// 현재 서버가 실행 중인 포트이다. 감지 전에는 null이다.
  int? _activePort;

  // ── 상수 ──

  /// 헬스 체크 최대 대기 시간(초)이다.
  static const _healthCheckTimeoutSec = 45;

  /// 헬스 체크 간격(밀리초)이다.
  static const _healthCheckIntervalMs = 1000;

  /// 서버 로그 최대 보관 줄 수이다.
  static const _maxLogLines = 100;

  /// 서버 SIGTERM 후 최대 대기(초)이다.
  static const _stopTimeoutSec = 20;

  /// 허용 포트 범위이다.
  static const _allowedPorts = [9501, 9502, 9503, 9504, 9505];

  /// 서버가 기록하는 포트 파일 경로이다.
  static const _portFileName = 'data/server_port.txt';

  // ── Public getters ──

  /// 이 앱이 서버를 시작했는지 여부이다.
  bool get launchedByUs => _launchedByUs;

  /// 프로젝트 루트 경로이다. 아직 탐색하지 않았으면 자동으로 탐색한다.
  String? get projectRoot {
    _projectRoot ??= _findProjectRoot();
    return _projectRoot;
  }

  /// 서버 프로세스의 최근 로그이다.
  List<String> get serverLogs => List.unmodifiable(_serverLogs);

  /// 현재 서버가 실행 중인 포트이다. 감지 전에는 null이다.
  int? get activePort => _activePort;

  /// 현재 서버의 base URL이다. 포트가 감지되지 않으면 허용 범위의 첫 번째 포트(9501)를 사용한다.
  String get baseUrl => 'http://localhost:${_activePort ?? 9501}';

  /// 현재 서버의 WebSocket base URL이다.
  String get wsBaseUrl => 'ws://localhost:${_activePort ?? 9501}';

  /// 번들 모드인지 여부를 외부에 공개한다.
  bool get isBundledApp => _isBundledApp;

  /// 현재 모드에 맞는 데이터 디렉토리 경로를 반환한다.
  ///
  /// 번들 모드: ~/Library/Application Support/com.stocktrader.ai/data/
  /// 개발 모드: {projectRoot}/data/
  String? get dataDirectory {
    if (_isBundledApp) {
      return '$_bundledWorkingDirectory/data';
    }
    // projectRoot가 아직 초기화되지 않았으면 탐색을 시도한다.
    _projectRoot ??= _findProjectRoot();
    final root = _projectRoot;
    if (root == null) return null;
    return '$root/data';
  }

  /// 현재 모드에 맞는 .env 파일 경로를 반환한다.
  ///
  /// 번들 모드: ~/Library/Application Support/com.stocktrader.ai/.env
  /// 개발 모드: {projectRoot}/.env
  String? get envFilePath {
    if (_isBundledApp) {
      return '$_bundledWorkingDirectory/.env';
    }
    _projectRoot ??= _findProjectRoot();
    final root = _projectRoot;
    if (root == null) return null;
    return '$root/.env';
  }

  /// 번들 모드에서의 작업 디렉토리를 외부에 공개한다.
  String get bundledWorkingDir => _bundledWorkingDirectory;

  // ── Public methods ──

  /// 서버가 실행 중인지 헬스 체크로 확인한다.
  ///
  /// /health 엔드포인트에 GET 요청을 보내 200 응답 여부를 확인한다.
  /// 프로세스 존재 여부와 무관하게 네트워크 레벨로 확인한다
  /// (수동으로 시작한 서버도 감지할 수 있다).
  Future<bool> isServerRunning() async {
    return _healthCheck();
  }

  /// 서버가 실행 중이지 않으면 시작하고, 이미 실행 중이면 즉시 반환한다.
  ///
  /// [onLog] 콜백을 제공하면 서버 시작 과정의 단계별 로그를 수신한다.
  /// 반환값의 [success]가 true이면 서버가 정상 가동 중이다.
  /// 동시 호출 시 첫 번째 호출의 결과를 공유한다 (서버 2개 시작 방지).
  Future<ServerLaunchResult> ensureRunning({
    void Function(String)? onLog,
  }) async {
    // 이미 ensureRunning이 진행 중이면 해당 결과를 대기하여 반환한다.
    if (_ensureRunningCompleter != null) {
      onLog?.call('서버 시작이 이미 진행 중입니다. 대기합니다...');
      return _ensureRunningCompleter!.future;
    }
    _ensureRunningCompleter = Completer<ServerLaunchResult>();
    try {
      final result = await _doEnsureRunning(onLog: onLog);
      _ensureRunningCompleter!.complete(result);
      return result;
    } catch (e) {
      final errorResult = ServerLaunchResult(
        success: false,
        message: '서버 시작 중 오류: $e',
      );
      _ensureRunningCompleter!.complete(errorResult);
      return errorResult;
    } finally {
      _ensureRunningCompleter = null;
    }
  }

  /// ensureRunning의 실제 구현이다.
  Future<ServerLaunchResult> _doEnsureRunning({
    void Function(String)? onLog,
  }) async {
    // 1) 이미 실행 중인 서버가 있는지 확인한다 (수동 기동 포함).
    onLog?.call('서버 상태 확인 중...');
    if (await _healthCheck()) {
      onLog?.call('서버가 이미 실행 중입니다.');
      return const ServerLaunchResult(
        success: true,
        message: '서버가 이미 실행 중입니다.',
      );
    }

    // 2) 프로젝트 루트를 탐색한다.
    onLog?.call('프로젝트 경로 탐색 중...');
    _projectRoot ??= _findProjectRoot();
    if (_projectRoot == null) {
      return const ServerLaunchResult(
        success: false,
        message: '프로젝트 루트를 찾을 수 없습니다. '
            'src/main.py가 있는 디렉토리를 확인하세요.',
      );
    }
    onLog?.call('프로젝트 루트: $_projectRoot');

    // 3) 번들 모드 또는 개발 모드에 따라 실행 경로를 결정한다.
    final String executable;
    final List<String> arguments;
    final String workingDir;

    // 번들 모드: 내장 바이너리가 실제로 존재할 때만 사용한다.
    // flutter run 디버그 빌드도 .app 구조를 사용하므로 바이너리 존재 여부로 확인한다.
    final bundledExe = '$_projectRoot/trading_server';
    if (_isBundledApp && File(bundledExe).existsSync()) {
      executable = bundledExe;
      arguments = [];
      workingDir = _bundledWorkingDirectory;
      final workDir = Directory(workingDir);
      if (!workDir.existsSync()) {
        workDir.createSync(recursive: true);
      }
    } else {
      // 개발 모드: Python 가상환경을 사용한다.
      final venvPython = '$_projectRoot/.venv/bin/python';
      if (!File(venvPython).existsSync()) {
        return const ServerLaunchResult(
          success: false,
          message: 'Python 가상환경을 찾을 수 없습니다.',
        );
      }
      executable = venvPython;
      arguments = ['-u', '-m', 'src.main'];
      workingDir = _projectRoot!;
    }

    // 4) Python 서버 프로세스를 시작한다. (Docker 단계는 별도 관리)
    onLog?.call('Python 서버 시작 중...');
    try {
      // CLAUDECODE 환경변수를 제거하여 중첩 세션을 방지한다.
      final env = Map<String, String>.from(Platform.environment);
      env.remove('CLAUDECODE');
      env.remove('CLAUDE_CODE');

      _serverProcess = await Process.start(
        executable,
        arguments,
        workingDirectory: workingDir,
        environment: env,
      );

      // stdout/stderr를 로그 버퍼에 기록한다.
      _serverProcess!.stdout
          .transform(const SystemEncoding().decoder)
          .listen((data) {
        _appendLog('[stdout] $data');
      });
      _serverProcess!.stderr
          .transform(const SystemEncoding().decoder)
          .listen((data) {
        _appendLog('[stderr] $data');
      });

      // 프로세스 종료를 감지한다.
      _serverProcess!.exitCode.then((code) {
        debugPrint('ServerLauncher: 서버 프로세스 종료 (exit code: $code)');
        _launchedByUs = false;
        _serverProcess = null;
      });
    } catch (e) {
      return ServerLaunchResult(
        success: false,
        message: '서버 프로세스 시작 실패: $e',
      );
    }

    // 5) 헬스 체크를 반복하여 서버 준비 완료를 확인한다.
    onLog?.call('서버 헬스 체크 대기 중 (최대 $_healthCheckTimeoutSec초)...');
    final healthy = await _waitForHealth(onLog: onLog);
    if (healthy) {
      _launchedByUs = true;
      onLog?.call('서버 시작 완료!');
      return const ServerLaunchResult(
        success: true,
        message: '서버가 정상 시작되었습니다.',
      );
    } else {
      // 헬스 체크 실패 — 프로세스를 정리한다.
      onLog?.call('헬스 체크 실패. 서버 프로세스를 종료합니다.');
      await stop();
      return const ServerLaunchResult(
        success: false,
        message: '서버 헬스 체크 시간 초과. '
            '로그를 확인하세요.',
      );
    }
  }

  /// 서버 프로세스를 안전하게 종료한다.
  ///
  /// 이 앱이 시작한 프로세스만 종료한다. 수동으로 시작한 서버는 종료하지 않는다.
  Future<void> stop() async {
    if (_serverProcess == null) return;

    debugPrint('ServerLauncher: SIGTERM 전송...');
    _serverProcess!.kill(ProcessSignal.sigterm);

    try {
      await _serverProcess!.exitCode
          .timeout(const Duration(seconds: _stopTimeoutSec));
    } on TimeoutException {
      debugPrint('ServerLauncher: SIGTERM 타임아웃, SIGKILL 전송...');
      _serverProcess!.kill(ProcessSignal.sigkill);
    }

    _serverProcess = null;
    _launchedByUs = false;
  }

  // ── Private helpers ──

  /// 포트 파일에서 서버 포트를 읽는다. 파일이 없거나 유효하지 않으면 null이다.
  ///
  /// 번들 모드에서는 Application Support 하위에서도 탐색한다.
  /// 서버가 작업 디렉토리를 Application Support로 사용하므로
  /// 포트 파일도 해당 경로에 생성된다.
  int? _readPortFile() {
    // 번들 모드: Application Support 경로를 우선 탐색한다.
    if (_isBundledApp) {
      final port = _tryReadPort('$_bundledWorkingDirectory/$_portFileName');
      if (port != null) return port;
    }
    // 프로젝트 루트 경로에서 탐색한다.
    if (_projectRoot == null) return null;
    return _tryReadPort('$_projectRoot/$_portFileName');
  }

  /// 지정 경로에서 포트 번호를 읽는 헬퍼이다.
  ///
  /// 비숫자, 범위 초과(1~65535 밖), 빈 파일 등 무효한 값은 null을 반환한다.
  int? _tryReadPort(String path) {
    try {
      final file = File(path);
      if (!file.existsSync()) return null;
      final content = file.readAsStringSync().trim();
      if (content.isEmpty) return null;
      final port = int.tryParse(content);
      if (port == null || port < 1 || port > 65535) return null;
      return port;
    } catch (_) {
      return null;
    }
  }

  /// 특정 포트에 대해 헬스 체크를 수행한다.
  Future<bool> _healthCheckPort(int port) async {
    final client = HttpClient();
    client.connectionTimeout = const Duration(seconds: 2);
    try {
      final request = await client
          .getUrl(Uri.parse('http://localhost:$port/api/system/health'));
      final response = await request.close().timeout(
            const Duration(seconds: 3),
          );
      return response.statusCode == 200;
    } catch (_) {
      return false;
    } finally {
      client.close(force: true);
    }
  }

  /// 서버 헬스 체크를 수행한다. 포트 파일 → 캐시 포트 → 범위 스캔 순으로 시도한다.
  Future<bool> _healthCheck() async {
    // 1) 포트 파일에서 읽는다
    final filePort = _readPortFile();
    if (filePort != null && await _healthCheckPort(filePort)) {
      _activePort = filePort;
      return true;
    }

    // 2) 이전에 감지된 포트를 시도한다
    if (_activePort != null && await _healthCheckPort(_activePort!)) {
      return true;
    }

    // 3) 허용 범위 전체를 스캔한다
    for (final port in _allowedPorts) {
      if (await _healthCheckPort(port)) {
        _activePort = port;
        return true;
      }
    }

    _activePort = null;
    return false;
  }

  /// 서버가 준비될 때까지 헬스 체크를 반복한다.
  Future<bool> _waitForHealth({void Function(String)? onLog}) async {
    for (var i = 0; i < _healthCheckTimeoutSec; i++) {
      await Future.delayed(
        const Duration(milliseconds: _healthCheckIntervalMs),
      );
      if (await _healthCheck()) return true;

      // 5초마다 진행 상황을 로그에 출력한다.
      if ((i + 1) % 5 == 0) {
        onLog?.call('  헬스 체크 대기 중... (${i + 1}초)');
      }

      // 프로세스가 이미 종료되었으면 즉시 실패 처리한다.
      if (_serverProcess == null) return false;
    }
    return false;
  }

  /// .app 번들 내에서 실행 중인지 감지한다.
  bool get _isBundledApp {
    try {
      final exePath = Platform.resolvedExecutable;
      return exePath.contains('.app/Contents/MacOS/');
    } catch (_) {
      return false;
    }
  }

  /// 번들 모드에서 사용할 작업 디렉토리를 반환한다.
  /// ~/Library/Application Support/com.stocktrader.ai/ 하위에 생성한다.
  String get _bundledWorkingDirectory {
    final home = Platform.environment['HOME'] ?? '';
    return '$home/Library/Application Support/com.stocktrader.ai';
  }

  /// 번들 모드에서 내장된 Python 백엔드 경로를 반환한다.
  /// .app/Contents/Resources/python_backend/ 에 위치한다.
  String? _findBundledBackend() {
    try {
      final exeDir = File(Platform.resolvedExecutable).parent;
      // MacOS/ → Contents/ → Resources/python_backend/
      final resourcesDir = exeDir.parent;
      final backendPath = '${resourcesDir.path}/Resources/python_backend';
      if (Directory(backendPath).existsSync()) return backendPath;
    } catch (_) {}
    return null;
  }

  /// 프로젝트 루트 경로를 탐색한다.
  ///
  /// 번들 모드에서는 내장 백엔드 경로를 사용하고,
  /// 개발 모드에서는 실행 파일 기준 상위 12단계, 작업 디렉토리 기준 8단계를 탐색한다.
  String? _findProjectRoot() {
    // 번들 모드: 내장 백엔드 경로를 사용한다.
    if (_isBundledApp) {
      final bundled = _findBundledBackend();
      if (bundled != null) return bundled;
    }

    // 실행 파일 기준 상위 디렉토리를 탐색한다.
    try {
      var dir = File(Platform.resolvedExecutable).parent;
      for (var i = 0; i < 12; i++) {
        if (_isProjectRoot(dir.path)) return dir.path;
        dir = dir.parent;
      }
    } catch (_) {}

    // 현재 작업 디렉토리 기준으로 탐색한다.
    try {
      var dir = Directory.current;
      for (var i = 0; i < 8; i++) {
        if (_isProjectRoot(dir.path)) return dir.path;
        dir = dir.parent;
      }
    } catch (_) {}

    return null;
  }

  /// 주어진 경로가 프로젝트 루트인지 확인한다.
  /// .env 없이도 src/main.py만 있으면 프로젝트 루트로 인정한다 (setup_mode 지원).
  bool _isProjectRoot(String path) {
    return File('$path/src/main.py').existsSync();
  }

  // ── LaunchAgent 제어 (launchctl) ──

  /// LaunchAgent 서비스 이름이다.
  static const _serviceLabel = 'com.trading.server';

  /// LaunchAgent plist 경로이다.
  static String get _plistPath {
    final home = Platform.environment['HOME'] ?? '';
    return '$home/Library/LaunchAgents/$_serviceLabel.plist';
  }

  /// LaunchAgent의 현재 상태를 조회한다.
  ///
  /// launchctl list에서 PID와 마지막 exit code를 파싱한다.
  Future<LaunchAgentStatus> getLaunchAgentStatus() async {
    try {
      final result = await Process.run('launchctl', ['list', _serviceLabel]);
      if (result.exitCode != 0) {
        return const LaunchAgentStatus(loaded: false);
      }
      // 출력 형식: "{PID}\t{lastExitCode}\t{label}"
      final line = result.stdout.toString().trim();
      final parts = line.split('\t');
      final pidStr = parts.isNotEmpty ? parts[0] : '-';
      final pid = pidStr == '-' ? null : int.tryParse(pidStr);
      final lastExit =
          parts.length > 1 ? int.tryParse(parts[1]) : null;
      return LaunchAgentStatus(
        loaded: true,
        pid: pid,
        lastExitCode: lastExit,
      );
    } catch (e) {
      debugPrint('ServerLauncher: launchctl list 실패: $e');
      return const LaunchAgentStatus(loaded: false);
    }
  }

  /// LaunchAgent를 로드하여 서버를 시작한다.
  ///
  /// plist가 이미 로드되어 있으면 start만 호출한다.
  /// KeepAlive=true이므로 로드 즉시 서버가 시작된다.
  Future<ServerLaunchResult> startViaLaunchAgent() async {
    // 이미 실행 중이면 바로 반환한다.
    if (await _healthCheck()) {
      return const ServerLaunchResult(
        success: true,
        message: '서버가 이미 실행 중입니다.',
      );
    }

    final status = await getLaunchAgentStatus();
    if (!status.loaded) {
      // plist 파일 존재 여부를 확인한다.
      if (!File(_plistPath).existsSync()) {
        return const ServerLaunchResult(
          success: false,
          message: 'LaunchAgent plist를 찾을 수 없습니다.',
        );
      }
      final loadResult =
          await Process.run('launchctl', ['load', _plistPath]);
      if (loadResult.exitCode != 0) {
        return ServerLaunchResult(
          success: false,
          message: 'LaunchAgent 로드 실패: ${loadResult.stderr}',
        );
      }
      _appendLog('[launchctl] LaunchAgent 로드 완료');
    } else {
      // 로드되어 있지만 프로세스가 없으면 start를 호출한다.
      await Process.run('launchctl', ['start', _serviceLabel]);
      _appendLog('[launchctl] 서버 시작 요청');
    }

    // 헬스 체크를 대기한다.
    final healthy = await _waitForHealth();
    if (healthy) {
      return const ServerLaunchResult(
        success: true,
        message: '서버가 LaunchAgent를 통해 시작되었습니다.',
      );
    }
    return const ServerLaunchResult(
      success: false,
      message: '서버 시작 후 헬스 체크 실패. 로그를 확인하세요.',
    );
  }

  /// LaunchAgent를 언로드하여 서버를 완전히 중지한다.
  ///
  /// unload를 사용하여 KeepAlive 자동 재시작을 방지한다.
  Future<ServerLaunchResult> stopViaLaunchAgent() async {
    final status = await getLaunchAgentStatus();
    if (!status.loaded) {
      return const ServerLaunchResult(
        success: true,
        message: '서버가 이미 중지되어 있습니다.',
      );
    }

    final result =
        await Process.run('launchctl', ['unload', _plistPath]);
    _appendLog('[launchctl] LaunchAgent 언로드: exit=${result.exitCode}');

    if (result.exitCode != 0) {
      return ServerLaunchResult(
        success: false,
        message: 'LaunchAgent 언로드 실패: ${result.stderr}',
      );
    }

    return const ServerLaunchResult(
      success: true,
      message: '서버가 중지되었습니다.',
    );
  }

  /// LaunchAgent를 통해 서버를 재시작한다.
  ///
  /// KeepAlive=true이므로 stop 명령이 자동 재시작을 트리거한다.
  Future<ServerLaunchResult> restartViaLaunchAgent() async {
    final status = await getLaunchAgentStatus();
    if (!status.loaded) {
      // 로드되어 있지 않으면 시작으로 처리한다.
      return startViaLaunchAgent();
    }

    // stop → KeepAlive가 자동 재시작한다.
    await Process.run('launchctl', ['stop', _serviceLabel]);
    _appendLog('[launchctl] 서버 재시작 요청 (stop → KeepAlive 자동 재시작)');

    // 재시작 완료를 대기한다.
    await Future.delayed(const Duration(seconds: 3));
    final healthy = await _waitForHealth();
    if (healthy) {
      return const ServerLaunchResult(
        success: true,
        message: '서버가 재시작되었습니다.',
      );
    }
    return const ServerLaunchResult(
      success: false,
      message: '서버 재시작 후 헬스 체크 실패. 로그를 확인하세요.',
    );
  }

  /// 서버 로그를 버퍼에 추가한다 (최대 _maxLogLines 줄 유지).
  void _appendLog(String line) {
    _serverLogs.add(line.trimRight());
    if (_serverLogs.length > _maxLogLines) {
      _serverLogs.removeAt(0);
    }
  }
}

/// LaunchAgent 상태 정보이다.
class LaunchAgentStatus {
  final bool loaded;
  final int? pid;
  final int? lastExitCode;

  const LaunchAgentStatus({
    required this.loaded,
    this.pid,
    this.lastExitCode,
  });

  /// 서버 프로세스가 실행 중인지 여부이다.
  bool get isRunning => loaded && pid != null;
}

/// 서버 시작 결과를 담는 데이터 클래스이다.
class ServerLaunchResult {
  final bool success;
  final String message;

  const ServerLaunchResult({
    required this.success,
    required this.message,
  });

  @override
  String toString() => 'ServerLaunchResult(success=$success, message=$message)';
}
