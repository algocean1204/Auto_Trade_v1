import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

/// Python 트레이딩 서버 프로세스를 관리하는 서비스이다.
///
/// Flutter 데스크탑 앱에서 버튼 클릭 시 백엔드 서버를 자동으로 시작/종료한다.
/// Docker(PostgreSQL+Redis) 상태도 함께 확인하여 필요 시 기동한다.
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

  /// 캐시된 프로젝트 루트 경로이다.
  String? _projectRoot;

  /// 서버 stdout/stderr 출력을 저장한다 (디버깅용, 최근 100줄).
  final List<String> _serverLogs = [];

  // ── 상수 ──

  /// 헬스 체크 최대 대기 시간(초)이다.
  static const _healthCheckTimeoutSec = 45;

  /// 헬스 체크 간격(밀리초)이다.
  static const _healthCheckIntervalMs = 1000;

  /// Docker 시작 후 대기 시간(초)이다.
  static const _dockerWaitSec = 4;

  /// 서버 로그 최대 보관 줄 수이다.
  static const _maxLogLines = 100;

  /// 서버 SIGTERM 후 최대 대기(초)이다.
  static const _stopTimeoutSec = 20;

  // ── Public getters ──

  /// 이 앱이 서버를 시작했는지 여부이다.
  bool get launchedByUs => _launchedByUs;

  /// 캐시된 프로젝트 루트 경로이다.
  String? get projectRoot => _projectRoot;

  /// 서버 프로세스의 최근 로그이다.
  List<String> get serverLogs => List.unmodifiable(_serverLogs);

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
  Future<ServerLaunchResult> ensureRunning({
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
            '.env와 src/main.py가 있는 디렉토리를 확인하세요.',
      );
    }
    onLog?.call('프로젝트 루트: $_projectRoot');

    // 3) Python 가상환경 존재 여부를 확인한다.
    final venvPython = '$_projectRoot/.venv/bin/python';
    if (!File(venvPython).existsSync()) {
      return const ServerLaunchResult(
        success: false,
        message: 'Python 가상환경을 찾을 수 없습니다.',
      );
    }

    // 4) Docker(PostgreSQL + Redis)를 확인/시작한다.
    onLog?.call('Docker 서비스 확인 중...');
    final dockerOk = await _ensureDocker(_projectRoot!);
    if (!dockerOk) {
      onLog?.call('Docker 시작 실패 — DB 없이 서버를 시작합니다.');
    } else {
      onLog?.call('Docker 서비스 준비 완료.');
    }

    // 5) Python 서버 프로세스를 시작한다.
    onLog?.call('Python 서버 시작 중...');
    try {
      // CLAUDECODE 환경변수를 제거하여 중첩 세션을 방지한다.
      final env = Map<String, String>.from(Platform.environment);
      env.remove('CLAUDECODE');
      env.remove('CLAUDE_CODE');

      _serverProcess = await Process.start(
        venvPython,
        ['-u', '-m', 'src.main'],
        workingDirectory: _projectRoot!,
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

    // 6) 헬스 체크를 반복하여 서버 준비 완료를 확인한다.
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

  /// /api/system/health 엔드포인트로 단일 헬스 체크를 수행한다.
  Future<bool> _healthCheck() async {
    try {
      final client = HttpClient();
      client.connectionTimeout = const Duration(seconds: 2);
      final request = await client
          .getUrl(Uri.parse('http://localhost:9501/api/system/health'));
      final response = await request.close().timeout(
            const Duration(seconds: 3),
          );
      client.close(force: true);
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
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

  /// Docker Compose 서비스(PostgreSQL + Redis)가 실행 중인지 확인하고,
  /// 실행 중이 아니면 시작한다.
  Future<bool> _ensureDocker(String projectRoot) async {
    try {
      // Docker 사용 가능 여부를 확인한다.
      final infoResult = await Process.run('docker', ['info'],
          workingDirectory: projectRoot);
      if (infoResult.exitCode != 0) return false;

      // 현재 실행 중인 서비스를 확인한다.
      final psResult = await Process.run(
        'docker',
        ['compose', 'ps', '--services', '--filter', 'status=running'],
        workingDirectory: projectRoot,
      );

      final running = psResult.stdout.toString();
      if (running.contains('postgres') && running.contains('redis')) {
        return true;
      }

      // Docker Compose를 시작한다.
      debugPrint('ServerLauncher: Docker Compose 시작 중...');
      final upResult = await Process.run(
        'docker',
        ['compose', 'up', '-d'],
        workingDirectory: projectRoot,
      );

      if (upResult.exitCode != 0) {
        debugPrint(
            'ServerLauncher: docker compose up 실패: ${upResult.stderr}');
        return false;
      }

      // DB 초기화 대기
      await Future.delayed(const Duration(seconds: _dockerWaitSec));
      return true;
    } catch (e) {
      debugPrint('ServerLauncher: Docker 확인 실패: $e');
      return false;
    }
  }

  /// 프로젝트 루트 경로를 탐색한다.
  ///
  /// 실행 파일 기준 상위 12단계, 현재 작업 디렉토리 기준 8단계를 탐색하여
  /// .env와 src/main.py가 모두 존재하는 디렉토리를 반환한다.
  String? _findProjectRoot() {
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
  bool _isProjectRoot(String path) {
    return File('$path/.env').existsSync() &&
        File('$path/src/main.py').existsSync();
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
