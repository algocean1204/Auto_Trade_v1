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

  /// 토큰이 유효한지 여부 (가상/실전 모두 만료 전이어야 한다).
  bool get isTokenValid {
    if (_virtualExpires == null || _realExpires == null) return false;
    final now = DateTime.now();
    return now.isBefore(_virtualExpires!) && now.isBefore(_realExpires!);
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
    _pollingTimer?.cancel();
    super.dispose();
  }

  /// 토큰을 발급한다.
  ///
  /// scripts/issue_token.py를 subprocess로 실행하여
  /// KIS API에서 가상/실전 토큰을 동시에 발급받는다.
  Future<void> issueToken() async {
    // 이미 발급 중이면 중복 실행을 방지한다.
    if (_isIssuing) return;
    _isIssuing = true;
    _error = null;
    notifyListeners();

    try {
      final projectRoot =
          ServerLauncher.instance.projectRoot ?? _findProjectRoot();
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

      if (result.exitCode != 0) {
        // 기본 에러 메시지를 설정한다.
        _error = '토큰 발급 실패 (exit: ${result.exitCode})';
        // stdout에 JSON 에러가 있을 경우 파싱하여 상세 메시지를 사용한다.
        try {
          final json = jsonDecode(result.stdout.toString());
          if (json['error'] != null) _error = json['error'].toString();
        } catch (_) {}
        return;
      }

      // 성공 시 stdout JSON을 파싱하여 만료 시각을 저장한다.
      final output = jsonDecode(result.stdout.toString());
      if (output['success'] == true) {
        _virtualExpires = _parseDateTime(output['virtual_expires']);
        _realExpires = _parseDateTime(output['real_expires']);
        _issuedAt = _parseDateTime(output['issued_at']) ?? DateTime.now();
        _error = null;
      } else {
        _error = output['error']?.toString() ?? '알 수 없는 오류';
      }
    } catch (e) {
      _error = '토큰 발급 실패: $e';
    } finally {
      _isIssuing = false;
      _autoRenewing = false;
      notifyListeners();
    }
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
  void _checkTokenFiles() {
    try {
      final projectRoot =
          ServerLauncher.instance.projectRoot ?? _findProjectRoot();
      if (projectRoot == null) return;

      final virtualToken =
          _readTokenFile('$projectRoot/data/kis_token.json');
      final realToken =
          _readTokenFile('$projectRoot/data/kis_real_token.json');

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
      if (_issuedAt == null && virtualToken != null) {
        try {
          final stat =
              File('$projectRoot/data/kis_token.json').statSync();
          _issuedAt = stat.modified;
          changed = true;
        } catch (_) {}
      }

      if (changed) notifyListeners();
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
  DateTime? _parseDateTime(dynamic value) {
    if (value == null) return null;
    try {
      return DateTime.parse(value.toString().replaceAll(' ', 'T'));
    } catch (_) {
      return null;
    }
  }

  /// ServerLauncher와 동일한 로직으로 프로젝트 루트를 탐색한다.
  ///
  /// 컴파일된 macOS 앱에서는 Directory.current가 프로젝트 경로가 아니므로
  /// 실행 파일 경로 기준으로도 탐색한다.
  String? _findProjectRoot() {
    // 1) 실행 파일 기준 상위 디렉토리를 탐색한다 (macOS .app 번들 대응).
    try {
      var dir = File(Platform.resolvedExecutable).parent;
      for (var i = 0; i < 12; i++) {
        if (File('${dir.path}/.env').existsSync() &&
            File('${dir.path}/src/main.py').existsSync()) {
          return dir.path;
        }
        dir = dir.parent;
      }
    } catch (_) {}

    // 2) 현재 작업 디렉토리 기준으로 탐색한다.
    try {
      var dir = Directory.current;
      for (var i = 0; i < 8; i++) {
        if (File('${dir.path}/.env').existsSync() &&
            File('${dir.path}/src/main.py').existsSync()) {
          return dir.path;
        }
        dir = dir.parent;
      }
    } catch (_) {}
    return null;
  }
}
