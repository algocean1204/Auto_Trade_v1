import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import '../services/server_launcher.dart';

/// KIS 토큰 발급 및 상태 관리 Provider이다.
///
/// 토큰 정책:
///   - 재발급: 상시 가능 (버튼 항상 활성)
///   - 서버 시작 조건: 토큰이 유효하면 OK (만료 전이기만 하면 됨)
///   - 필수 갱신: 발급 후 16시간 경과 시 갱신 권고
///   - 자동 갱신: 서버 실행 중 + 만료 1시간 전 → 자동 재발급
class TokenProvider with ChangeNotifier {
  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;
  /// 토큰 발급 중 여부이다.
  bool _isIssuing = false;

  /// 마지막 에러 메시지이다.
  String? _error;

  /// 가상 토큰 만료 시각이다.
  DateTime? _virtualExpires;

  /// 실전 토큰 만료 시각이다.
  DateTime? _realExpires;

  /// 토큰 발급 시각이다.
  DateTime? _issuedAt;

  /// 상태 갱신 타이머이다.
  Timer? _pollingTimer;

  /// 서버 연결 상태이다. 외부에서 주입받는다.
  bool _serverConnected = false;

  /// 자동 갱신 진행 중 플래그이다 (중복 방지용).
  bool _autoRenewing = false;

  // ── 상수 ──

  /// 필수 갱신 기준 시간 (16시간)이다.
  static const _mandatoryRenewalHours = 16;

  /// 자동 갱신 기준: 만료 N분 전이다.
  static const _autoRenewBeforeMinutes = 60;

  // ── Getters ──

  /// 토큰 발급 중 여부이다.
  bool get isIssuing => _isIssuing;

  /// 마지막 에러 메시지이다.
  String? get error => _error;

  /// 가상 계좌 토큰 만료 시각이다.
  DateTime? get virtualExpires => _virtualExpires;

  /// 실전 계좌 토큰 만료 시각이다.
  DateTime? get realExpires => _realExpires;

  /// 토큰 발급 시각이다.
  DateTime? get issuedAt => _issuedAt;

  /// 토큰이 유효한지 여부이다.
  ///
  /// 가상/실전 중 하나만 설정되어 있어도 해당 토큰이 유효하면 true를 반환한다.
  /// 두 종류 모두 null이면 (아직 발급 전) false를 반환한다.
  bool get isTokenValid {
    if (_virtualExpires == null && _realExpires == null) return false;
    final now = DateTime.now();
    final virtualOk = _virtualExpires != null && now.isBefore(_virtualExpires!);
    final realOk = _realExpires != null && now.isBefore(_realExpires!);
    return virtualOk || realOk;
  }

  /// 토큰 필수 갱신이 필요한지 여부이다 (발급 후 16시간 경과).
  bool get needsMandatoryRenewal {
    if (_issuedAt == null) return true;
    return DateTime.now().difference(_issuedAt!).inHours >= _mandatoryRenewalHours;
  }

  /// 토큰이 곧 만료되는지 여부이다 (만료 1시간 이내).
  bool get isExpiringSoon {
    if (!isTokenValid) return false;
    final earliest = _earliestExpiry;
    if (earliest == null) return false;
    return earliest.difference(DateTime.now()).inMinutes <= _autoRenewBeforeMinutes;
  }

  /// 가상/실전 중 더 빨리 만료되는 시각이다.
  DateTime? get _earliestExpiry {
    if (_virtualExpires == null) return _realExpires;
    if (_realExpires == null) return _virtualExpires;
    return _virtualExpires!.isBefore(_realExpires!)
        ? _virtualExpires
        : _realExpires;
  }

  /// 만료까지 남은 시간 텍스트이다.
  String get _remainingText {
    final earliest = _earliestExpiry;
    if (earliest == null) return '';
    final diff = earliest.difference(DateTime.now());
    if (diff.isNegative) return '만료됨';
    if (diff.inHours > 0) return '${diff.inHours}시간 ${diff.inMinutes % 60}분';
    return '${diff.inMinutes}분';
  }

  /// 토큰 상태 텍스트 (UI 표시용)이다.
  String get statusText {
    if (_isIssuing) return '발급 중...';
    if (_error != null) return '오류: $_error';
    if (!isTokenValid) return '토큰 없음 (발급 필요)';
    if (needsMandatoryRenewal) return '갱신 필요 (남은 시간: $_remainingText)';
    if (isExpiringSoon) return '만료 임박 ($_remainingText)';
    return '유효 (남은 시간: $_remainingText)';
  }

  // ── Public methods ──

  /// 초기화 시 토큰 파일을 읽어 상태를 복원하고, 30초 주기 폴링을 시작한다.
  void initialize() {
    _checkTokenFiles();
    _pollingTimer?.cancel();
    _pollingTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      _checkTokenFiles();
      _tryAutoRenew();
    });
  }

  /// 서버 연결 상태를 업데이트한다.
  ///
  /// 서버가 켜진 상태에서만 자동 갱신이 작동한다.
  void setServerConnected(bool connected) {
    if (_serverConnected == connected) return;
    _serverConnected = connected;
    // 서버가 연결된 직후 자동 갱신 조건을 즉시 확인한다.
    if (connected) _tryAutoRenew();
  }

  @override
  void dispose() {
    _disposed = true;
    _pollingTimer?.cancel();
    super.dispose();
  }

  /// dispose 이후 안전하게 notifyListeners를 호출한다.
  void _safeNotify() {
    if (!_disposed) notifyListeners();
  }

  /// 토큰을 발급한다.
  ///
  /// 개발 모드: scripts/issue_token.py를 subprocess로 실행한다.
  /// 번들 모드: 서버가 실행 중이면 API로 요청하고,
  ///           서버가 꺼져 있으면 내장 trading_server 바이너리로 실행한다.
  Future<void> issueToken() async {
    // 이미 발급 중이면 중복 실행을 방지한다.
    if (_isIssuing) return;
    _isIssuing = true;
    _error = null;
    _safeNotify();

    try {
      final launcher = ServerLauncher.instance;

      if (launcher.isBundledApp) {
        await _issueTokenBundled(launcher);
      } else {
        await _issueTokenDev(launcher);
      }
    } catch (e) {
      _error = '토큰 발급 실패: $e';
    } finally {
      _isIssuing = false;
      _autoRenewing = false;
      _safeNotify();
    }
  }

  /// 개발 모드에서 .venv/bin/python으로 토큰을 발급한다.
  Future<void> _issueTokenDev(ServerLauncher launcher) async {
    final projectRoot = launcher.projectRoot;
    if (projectRoot == null) {
      _error = '프로젝트 경로를 찾을 수 없습니다.';
      return;
    }

    final venvPython = '$projectRoot/.venv/bin/python';
    if (!File(venvPython).existsSync()) {
      _error = 'Python 가상환경을 찾을 수 없습니다.';
      return;
    }

    final result = await Process.run(
      venvPython,
      ['-u', 'scripts/issue_token.py'],
      workingDirectory: projectRoot,
    );

    _handleIssueTokenResult(result);
  }

  /// 번들 모드에서 토큰을 발급한다.
  ///
  /// 1순위: 서버가 실행 중이면 POST /api/setup/token API를 사용한다.
  /// 2순위: 내장 issue_token.py를 시스템 Python으로 실행한다.
  ///        --env-file, --data-dir 인자로 올바른 경로를 전달한다.
  ///
  /// trading_server 바이너리의 --issue-token CLI 모드는 지원하지 않는다.
  /// (main.py에 argparse가 없어 전체 서버가 시작되므로 사용 불가)
  Future<void> _issueTokenBundled(ServerLauncher launcher) async {
    // 1) 서버가 실행 중이면 API로 토큰 발급을 요청한다.
    if (await launcher.isServerRunning()) {
      final client = HttpClient();
      client.connectionTimeout = const Duration(seconds: 5);
      try {
        final request = await client.postUrl(
          Uri.parse('${launcher.baseUrl}/api/setup/token'),
        );
        request.headers.contentType = ContentType.json;
        request.write('{}');
        final response = await request.close().timeout(
          const Duration(seconds: 30),
        );
        final body = await response.transform(utf8.decoder).join();

        if (response.statusCode == 200) {
          final output = jsonDecode(body);
          if (output['success'] == true) {
            _virtualExpires = _parseDateTime(output['virtual_expires']);
            _realExpires = _parseDateTime(output['real_expires']);
            _issuedAt = _parseDateTime(output['issued_at']) ?? DateTime.now();
            _error = null;
            return;
          }
          // success=false인 경우 에러 메시지를 설정한다
          _error = output['error']?.toString() ?? 'API 토큰 발급 실패';
          return;
        }
        // API 실패 시 fallback으로 이동한다.
        debugPrint(
          'TokenProvider: API 응답 ${response.statusCode}, fallback 시도',
        );
      } catch (e) {
        debugPrint('TokenProvider: API 토큰 발급 실패, fallback 시도: $e');
      } finally {
        client.close(force: true);
      }
    }

    // 2) 내장 issue_token.py를 시스템 Python으로 실행한다.
    //    번들 모드에서는 .env와 데이터 디렉토리가 Application Support에 있으므로
    //    --env-file과 --data-dir 인자로 올바른 경로를 전달한다.
    final projectRoot = launcher.projectRoot;
    if (projectRoot != null) {
      // 번들 내 scripts/issue_token.py 또는 _internal/scripts/issue_token.py를 탐색한다
      final scriptCandidates = [
        '$projectRoot/scripts/issue_token.py',
        '$projectRoot/_internal/scripts/issue_token.py',
      ];
      String? scriptPath;
      for (final candidate in scriptCandidates) {
        if (File(candidate).existsSync()) {
          scriptPath = candidate;
          break;
        }
      }

      if (scriptPath != null) {
        final envPath = launcher.envFilePath;
        final dataDir = launcher.dataDirectory;
        // 시스템 Python을 탐색한다 (번들에는 .venv가 없다)
        final pythonPaths = [
          '/usr/bin/python3',
          '/usr/local/bin/python3',
        ];
        for (final python in pythonPaths) {
          if (File(python).existsSync()) {
            // issue_token.py에 경로를 명시적으로 전달한다
            final args = ['-u', scriptPath];
            if (envPath != null) args.addAll(['--env-file', envPath]);
            if (dataDir != null) args.addAll(['--data-dir', dataDir]);

            final result = await Process.run(
              python,
              args,
              workingDirectory: launcher.bundledWorkingDir,
            );
            _handleIssueTokenResult(result);
            return;
          }
        }
        _error = '서버를 먼저 시작한 후 토큰을 발급하세요.';
        return;
      }
    }

    _error = '서버를 먼저 시작한 후 토큰을 발급하세요.';
  }

  /// subprocess 실행 결과를 파싱하여 토큰 상태를 업데이트한다.
  void _handleIssueTokenResult(ProcessResult result) {
    if (result.exitCode != 0) {
      _error = '토큰 발급 실패 (exit: ${result.exitCode})';
      try {
        final json = jsonDecode(result.stdout.toString());
        if (json['error'] != null) {
          _error = _humanizeTokenError(json['error'].toString());
        }
      } catch (_) {
        // stdout 파싱 실패 시 stderr에서 에러 힌트를 추출한다
        final stderr = result.stderr.toString().trim();
        if (stderr.isNotEmpty) {
          _error = '토큰 발급 실패: $stderr';
        }
      }
      return;
    }

    try {
      final output = jsonDecode(result.stdout.toString());
      if (output['success'] == true) {
        _virtualExpires = _parseDateTime(output['virtual_expires']);
        _realExpires = _parseDateTime(output['real_expires']);
        _issuedAt = _parseDateTime(output['issued_at']) ?? DateTime.now();
        _error = null;
      } else {
        _error = _humanizeTokenError(
          output['error']?.toString() ?? '알 수 없는 오류',
        );
      }
    } on FormatException {
      _error = '토큰 발급 스크립트 출력을 파싱할 수 없습니다.';
    }
  }

  /// KIS 토큰 발급 에러 메시지를 사용자 친화적으로 변환한다.
  String _humanizeTokenError(String raw) {
    if (raw.contains('환경변수 누락')) return raw;
    if (raw.contains('TimeoutError') || raw.contains('Timeout')) {
      return 'KIS 서버 연결 시간 초과. 네트워크 상태를 확인하세요.';
    }
    if (raw.contains('ClientConnectorError') || raw.contains('Cannot connect')) {
      return 'KIS 서버에 연결할 수 없습니다. 인터넷 연결을 확인하세요.';
    }
    if (raw.contains('HTTP 401') || raw.contains('HTTP 403')) {
      return 'KIS API 인증 실패. API 키와 시크릿을 확인하세요.';
    }
    if (raw.contains('HTTP 5')) {
      return 'KIS 서버 일시적 오류. 잠시 후 다시 시도하세요.';
    }
    return raw;
  }

  // ── Private helpers ──

  /// 서버 실행 중 + 만료 1시간 전이면 자동 갱신한다.
  void _tryAutoRenew() {
    if (!_serverConnected) return;
    if (_isIssuing || _autoRenewing) return;
    if (!isTokenValid) return;

    if (isExpiringSoon) {
      debugPrint('TokenProvider: 만료 임박 — 자동 갱신 시작');
      _autoRenewing = true;
      issueToken();
    }
  }

  /// 토큰 파일을 직접 읽어 상태를 확인한다.
  ///
  /// 앱 재시작 시 기존 토큰 상태를 복원하는 데 사용한다.
  /// ServerLauncher.dataDirectory를 사용하여 번들/개발 모드 모두 지원한다.
  /// 발급 진행 중에는 상태 덮어쓰기를 방지하기 위해 건너뛴다.
  void _checkTokenFiles() {
    // 발급 중에는 파일 폴링을 건너뛴다 — issueToken이 최종 상태를 설정한다.
    if (_isIssuing) return;
    try {
      final dataDir = ServerLauncher.instance.dataDirectory;
      if (dataDir == null) return;

      final virtualToken =
          _readTokenFile('$dataDir/kis_token.json');
      final realToken =
          _readTokenFile('$dataDir/kis_real_token.json');

      var changed = false;

      if (virtualToken != null) {
        final exp = _parseDateTime(virtualToken['token_expires_at']);
        if (exp != _virtualExpires) {
          _virtualExpires = exp;
          changed = true;
        }
      }

      if (realToken != null) {
        final exp = _parseDateTime(realToken['token_expires_at']);
        if (exp != _realExpires) {
          _realExpires = exp;
          changed = true;
        }
      }

      // issuedAt은 토큰 파일의 수정 시각으로 추정한다.
      // issue_token.py가 파일을 덮어쓰므로 수정 시각이 발급 시각에 해당한다.
      // 가상/실전 중 존재하는 파일에서 추정한다 (한쪽만 설정된 경우 대응).
      if (_issuedAt == null) {
        final tokenFileToCheck = virtualToken != null
            ? '$dataDir/kis_token.json'
            : (realToken != null ? '$dataDir/kis_real_token.json' : null);
        if (tokenFileToCheck != null) {
          try {
            final stat = File(tokenFileToCheck).statSync();
            _issuedAt = stat.modified;
            changed = true;
          } catch (_) {}
        }
      }

      if (changed) _safeNotify();
    } catch (_) {}
  }

  /// JSON 토큰 파일을 읽어 Map으로 반환한다.
  Map<String, dynamic>? _readTokenFile(String path) {
    try {
      final file = File(path);
      if (!file.existsSync()) return null;
      return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  /// 문자열을 DateTime으로 파싱한다.
  ///
  /// 공백이 포함된 형식(예: "2026-03-15 09:00:00")을 ISO 8601로 변환한다.
  /// KIS API가 반환하는 만료시각은 KST(+09:00)이므로 타임존이 없으면 KST를 추가한다.
  DateTime? _parseDateTime(dynamic value) {
    if (value == null) return null;
    try {
      var s = value.toString().replaceAll(' ', 'T');
      // KIS API 만료시각은 KST이다. 타임존 정보가 없으면 +09:00을 추가하여
      // 사용자가 KST 외 타임존에서도 올바른 비교가 가능하도록 한다.
      if (!s.contains('+') && !s.contains('Z') && !s.endsWith('z')) {
        s += '+09:00';
      }
      return DateTime.parse(s);
    } catch (_) {
      return null;
    }
  }

  // 프로젝트 루트 탐색은 ServerLauncher에 위임한다.
  // TokenProvider 고유의 _findProjectRoot는 제거하고 ServerLauncher.instance.projectRoot를 사용한다.
}
