import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/server_launcher.dart';

/// 자동매매 시작/중지 제어 상태를 관리한다.
///
/// 서버 연결 상태(_isConnected)를 추적하여 "서버가 중지라고 응답"과
/// "서버에 연결 불가"를 구분한다.
/// 매매 시간 윈도우 관련 정보(_isTradingWindow, _isTradingDay 등)도 함께 관리한다.
///
/// 서버가 꺼져 있으면 ServerLauncher를 통해 자동으로 시작한 뒤 API를 호출한다.
///
/// 매매 세션 보호: 자동매매가 실행된 적이 있으면 07:00 KST까지 서버를
/// 보호한다 (EOD 보고서 생성 시간 확보).
class TradingControlProvider with ChangeNotifier {
  final ApiService _apiService;
  final ServerLauncher _serverLauncher;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  TradingControlProvider(this._apiService, {ServerLauncher? serverLauncher})
      : _serverLauncher = serverLauncher ?? ServerLauncher.instance;

  /// 자동매매 실행 여부이다 (마지막 성공 응답 기준).
  bool _isRunning = false;

  /// 서버 연결 가능 여부이다. 첫 폴링 전까지는 미연결 상태로 시작한다.
  bool _isConnected = false;

  /// 상태 조회/시작/중지 요청 처리 중 여부이다.
  bool _isBusy = false;

  /// 마지막 에러 메시지이다 (null이면 정상 상태).
  String? _error;

  /// 뉴스 수집 중 여부이다.
  bool _isBusyNews = false;

  /// 뉴스 수집 결과 메시지이다.
  String? _newsResult;

  /// 10초 주기 자동 상태 갱신 타이머이다.
  Timer? _pollingTimer;

  /// 서버 시작 진행 중 여부이다.
  bool _isStartingServer = false;

  /// 서버 시작 진행 상황 메시지이다.
  String? _serverStartLog;

  // ── 매매 시간 윈도우 필드 ──

  /// 현재 매매 가능 시간대인지 여부이다 (23:00~06:30 KST, DST 시 22:00~06:30).
  bool _isTradingWindow = false;

  /// 오늘이 매매일인지 여부이다 (주말/공휴일 제외).
  bool _isTradingDay = true;

  /// 다음 매매 시작 시각이다 (서버 응답의 ISO datetime 문자열을 파싱).
  DateTime? _nextWindowStart;

  /// 현재 세션 유형이다 (예: "pre_market", "trading", "post_market" 등).
  String? _sessionType;

  /// 서버 기준 현재 KST 시각 문자열이다.
  String? _currentKst;

  // ── 매매 세션 보호 필드 ──

  /// 이번 세션에서 자동매매가 실행된 적이 있는지 여부이다.
  /// true이면 07:00 KST까지 서버 중지를 차단한다.
  bool _tradingSessionActive = false;

  /// 서버 보호 만료 시각이다 (자동매매 시작 시 당일/익일 07:00 KST로 설정).
  DateTime? _serverProtectedUntil;

  /// 보호 만료 후 자동 종료를 위한 타이머이다.
  Timer? _autoShutdownTimer;

  bool get isRunning => _isRunning;
  bool get isConnected => _isConnected;
  bool get isBusy => _isBusy;
  bool get isBusyNews => _isBusyNews;
  String? get error => _error;
  String? get newsResult => _newsResult;
  bool get isStartingServer => _isStartingServer;
  String? get serverStartLog => _serverStartLog;

  bool get isTradingWindow => _isTradingWindow;
  bool get isTradingDay => _isTradingDay;
  DateTime? get nextWindowStart => _nextWindowStart;
  String? get sessionType => _sessionType;
  String? get currentKst => _currentKst;

  /// 이 앱이 서버를 시작했는지 여부이다.
  bool get serverLaunchedByUs => _serverLauncher.launchedByUs;

  /// 매매 세션 보호 중인지 여부이다.
  bool get isServerProtected => _isServerProtectedNow();

  /// 보호 만료 시각이다 (UI 표시용).
  DateTime? get serverProtectedUntil => _serverProtectedUntil;

  /// 폴링을 시작한다. 화면 진입 시 1회 호출한다.
  void startPolling() {
    // 서버 포트를 감지한다 (외부에서 시작된 서버도 포트를 인식하기 위함).
    _serverLauncher.isServerRunning();
    _fetchStatus();
    _pollingTimer?.cancel();
    _pollingTimer = Timer.periodic(const Duration(seconds: 10), (_) {
      if (!_isBusy) _fetchStatus();
    });
  }

  /// 폴링을 중지한다. dispose 또는 화면 이탈 시 호출한다.
  void stopPolling() {
    _pollingTimer?.cancel();
    _pollingTimer = null;
  }

  @override
  void dispose() {
    _disposed = true;
    stopPolling();
    _autoShutdownTimer?.cancel();
    super.dispose();
  }

  /// dispose 이후 안전하게 notifyListeners를 호출한다.
  void _safeNotify() {
    if (!_disposed) notifyListeners();
  }

  // ── 서버 자동 시작 ──

  /// 서버가 실행 중이지 않으면 ServerLauncher를 통해 자동 시작한다.
  ///
  /// 이미 실행 중이면 즉시 true를 반환한다.
  /// 시작 실패 시 false를 반환하고 _error에 메시지를 저장한다.
  Future<bool> _ensureServer() async {
    // 서버가 이미 연결되어 있으면 바로 통과한다.
    if (_isConnected) return true;

    // 다른 작업이 이미 서버를 시작하고 있으면 대기한다.
    if (_isStartingServer) {
      // 최대 50초 대기 (500ms * 100)
      for (var i = 0; i < 100; i++) {
        await Future.delayed(const Duration(milliseconds: 500));
        if (!_isStartingServer) break;
      }
      return _isConnected;
    }

    _isStartingServer = true;
    _serverStartLog = null;
    _safeNotify();

    final result = await _serverLauncher.ensureRunning(
      onLog: (msg) {
        _serverStartLog = msg;
        _safeNotify();
      },
    );

    _isStartingServer = false;
    _serverStartLog = null;

    if (result.success) {
      _isConnected = true;
      _error = null;
      // 서버가 바인드한 포트로 API/WS 연결을 갱신한다.
      _apiService.refreshBaseUrl();
      _safeNotify();
      // 서버가 막 시작됐으므로 상태를 한 번 갱신한다.
      await _fetchStatus();
      return true;
    } else {
      _error = result.message;
      _safeNotify();
      return false;
    }
  }

  /// 서버를 안전하게 중지할 수 있는지 확인한다.
  ///
  /// 자동매매 실행 중, 뉴스 수집 중, 또는 매매 세션 보호 중이면 중지할 수 없다.
  bool get canStopServer =>
      !_isRunning && !_isBusyNews && !_isBusy && !_isServerProtectedNow();

  /// 매매 세션 보호 중인지 확인한다.
  ///
  /// 자동매매가 실행된 적이 있고 현재 시각이 보호 만료 시각 이전이면 true이다.
  bool _isServerProtectedNow() {
    if (!_tradingSessionActive || _serverProtectedUntil == null) return false;
    return DateTime.now().isBefore(_serverProtectedUntil!);
  }

  /// 매매 세션 보호를 활성화한다.
  ///
  /// 당일/익일 07:00 KST를 보호 만료 시각으로 설정하고,
  /// 만료 시 자동으로 서버를 종료하는 타이머를 등록한다.
  void _activateSessionProtection() {
    if (_tradingSessionActive) return; // 이미 활성화됨
    _tradingSessionActive = true;

    // 보호 만료 시각: 다음 07:00 KST (현재 07시 이후면 내일 07시)
    final now = DateTime.now();
    var shutdownTime = DateTime(now.year, now.month, now.day, 7, 0);
    if (now.isAfter(shutdownTime)) {
      shutdownTime = shutdownTime.add(const Duration(days: 1));
    }
    _serverProtectedUntil = shutdownTime;

    // 만료 시 자동 종료 타이머를 설정한다.
    _autoShutdownTimer?.cancel();
    final delay = shutdownTime.difference(now);
    _autoShutdownTimer = Timer(delay, _autoShutdownServer);

    debugPrint(
      'TradingControlProvider: 서버 보호 활성화 '
      '(만료: $shutdownTime, ${delay.inMinutes}분 후)',
    );
    _safeNotify();
  }

  /// 보호 만료 후 서버를 자동 종료한다.
  ///
  /// shutdown API를 호출하여 서버가 어떻게 시작되었든 안전하게 종료한다.
  /// 서버 측에도 08:00 KST 워치독이 있으므로 이중 안전장치이다.
  Future<void> _autoShutdownServer() async {
    // 아직 매매 실행 중이면 종료하지 않는다 (안전장치).
    if (_isRunning || _isBusyNews) {
      debugPrint(
        'TradingControlProvider: 자동 종료 시점이지만 '
        '작업 진행 중이므로 5분 후 재시도',
      );
      _autoShutdownTimer = Timer(
        const Duration(minutes: 5),
        _autoShutdownServer,
      );
      return;
    }

    debugPrint('TradingControlProvider: 07:00 KST 도달, 서버 자동 종료');
    _tradingSessionActive = false;
    _serverProtectedUntil = null;
    _autoShutdownTimer = null;

    // shutdown API로 서버를 안전하게 종료한다 (시작 방법과 무관)
    try {
      await _apiService.shutdownServer();
      debugPrint('TradingControlProvider: 자동 종료 — shutdown API 성공');
    } catch (e) {
      debugPrint('TradingControlProvider: 자동 종료 — shutdown API 실패: $e');
    }
    // 앱이 시작한 프로세스가 있으면 추가로 종료한다 (안전장치)
    await _serverLauncher.stop();

    stopPolling();
    _isConnected = false;
    _isRunning = false;
    _safeNotify();
  }

  /// 서버가 외부에서 시작된 후 상태를 동기화한다.
  ///
  /// Settings의 LaunchAgent 시작/재시작 후 호출한다.
  /// 헬스체크로 서버 상태를 확인하고, AppBar 버튼에 즉시 반영한다.
  Future<void> syncAfterServerStart() async {
    final alive = await _serverLauncher.isServerRunning();
    if (alive && !_isConnected) {
      _isConnected = true;
      _error = null;
      _apiService.refreshBaseUrl();
      _safeNotify();
      // 전체 상태(매매 상태, 시간 윈도우 등)를 갱신한다
      await _fetchStatus();
    }
  }

  /// 서버가 외부에서 중지되었음을 즉시 반영한다.
  ///
  /// Settings의 LaunchAgent 중지 후 호출한다.
  /// 헬스체크 없이 즉시 disconnected 상태로 전환하여
  /// graceful shutdown 중 레이스 컨디션을 방지한다.
  void markServerStopped() {
    if (!_isConnected && !_isRunning) return;
    _isConnected = false;
    _isRunning = false;
    _error = null;
    _safeNotify();
  }

  /// 서버를 수동으로 시작한다.
  ///
  /// 체인 구조에서 서버 시작 버튼이 직접 호출한다.
  /// 이미 연결되어 있으면 즉시 true를 반환한다.
  /// 시작 실패 시 false를 반환하고 _error에 메시지를 저장한다.
  Future<bool> startServer() async {
    if (_isConnected) return true;
    return _ensureServer();
  }

  /// 서버 프로세스를 중지한다.
  ///
  /// /api/system/shutdown API를 호출하여 서버를 안전하게 종료한다.
  /// API 호출 실패 시 프로세스 직접 종료를 시도한다.
  /// 자동매매 실행 중, 뉴스 수집 중, 또는 매매 세션 보호 중이면 중지를 거부한다.
  Future<bool> stopServer() async {
    if (_isRunning) {
      _error = '자동매매 실행 중에는 서버를 중지할 수 없습니다. 먼저 자동매매를 중지하세요.';
      _safeNotify();
      return false;
    }
    if (_isBusyNews) {
      _error = '뉴스 수집 중에는 서버를 중지할 수 없습니다. 완료를 기다려주세요.';
      _safeNotify();
      return false;
    }
    if (_isBusy) {
      _error = '작업 처리 중에는 서버를 중지할 수 없습니다.';
      _safeNotify();
      return false;
    }
    if (_isServerProtectedNow()) {
      final until = _serverProtectedUntil!;
      final h = until.hour.toString().padLeft(2, '0');
      final m = until.minute.toString().padLeft(2, '0');
      _error = '매매 세션 보호 중입니다 ($h:$m까지). EOD 보고서 생성이 완료될 때까지 서버를 유지합니다.';
      _safeNotify();
      return false;
    }

    stopPolling();
    _autoShutdownTimer?.cancel();
    _autoShutdownTimer = null;
    _tradingSessionActive = false;
    _serverProtectedUntil = null;

    // 1) shutdown API로 서버를 안전하게 종료한다
    try {
      await _apiService.shutdownServer();
      debugPrint('TradingControlProvider: shutdown API 호출 성공');
    } catch (e) {
      debugPrint('TradingControlProvider: shutdown API 실패, 프로세스 직접 종료: $e');
    }
    // 2) 앱이 직접 시작한 프로세스가 있으면 추가로 종료한다 (안전장치)
    await _serverLauncher.stop();

    _isConnected = false;
    _isRunning = false;
    _error = null;
    _safeNotify();
    return true;
  }

  /// 자동매매 상태를 서버에서 조회한다.
  ///
  /// 서버 응답 성공 시 _isConnected=true로 설정하고 _isRunning 및 매매 윈도우
  /// 관련 필드들을 업데이트한다.
  /// ServerUnreachableException 발생 시 _isConnected=false로 설정하고
  /// _isRunning은 마지막 알려진 값을 유지한다.
  Future<void> _fetchStatus() async {
    try {
      final result = await _apiService.getTradingStatus();
      final running = result['is_trading'] as bool? ??
          result['running'] as bool? ??
          false;

      // 매매 시간 윈도우 필드를 파싱한다.
      final isTradingWindow = result['is_trading_window'] as bool? ?? false;
      final isTradingDay = result['is_trading_day'] as bool? ?? true;
      final sessionType = result['session_type'] as String?;
      final currentKst = result['current_kst'] as String?;

      // next_window_start ISO 문자열을 DateTime으로 파싱한다.
      DateTime? nextWindowStart;
      final nextWindowStartStr = result['next_window_start'] as String?;
      if (nextWindowStartStr != null && nextWindowStartStr.isNotEmpty) {
        try {
          nextWindowStart = DateTime.parse(nextWindowStartStr);
        } catch (_) {
          nextWindowStart = null;
        }
      }

      bool changed = false;

      if (!_isConnected) {
        _isConnected = true;
        // 서버 연결 성공 시 포트를 감지하고 갱신한다.
        await _serverLauncher.isServerRunning();
        _apiService.refreshBaseUrl();
        changed = true;
      }
      if (_isRunning != running) {
        _isRunning = running;
        changed = true;
        // 매매가 시작된 것을 감지하면 세션 보호를 활성화한다.
        if (running) _activateSessionProtection();
      }
      if (_isTradingWindow != isTradingWindow) {
        _isTradingWindow = isTradingWindow;
        changed = true;
      }
      if (_isTradingDay != isTradingDay) {
        _isTradingDay = isTradingDay;
        changed = true;
      }
      if (_sessionType != sessionType) {
        _sessionType = sessionType;
        changed = true;
      }
      if (_currentKst != currentKst) {
        _currentKst = currentKst;
        changed = true;
      }
      // nextWindowStart 비교는 DateTime? equality로 처리한다.
      if (_nextWindowStart != nextWindowStart) {
        _nextWindowStart = nextWindowStart;
        changed = true;
      }
      // 서버 응답 성공 시 이전 에러를 지운다.
      if (_error != null) {
        _error = null;
        changed = true;
      }
      if (changed) _safeNotify();
    } on ServerUnreachableException {
      // 서버 미연결: _isRunning은 마지막 알려진 값을 유지한다.
      bool changed = false;
      if (_isConnected) {
        _isConnected = false;
        changed = true;
      }
      if (_error != null) {
        _error = null;
        changed = true;
      }
      if (changed) _safeNotify();
      debugPrint('TradingControlProvider._fetchStatus: server unreachable');
    } catch (e) {
      // 503 등 서버 에러 시 안전하게 상태를 리셋한다.
      bool changed = false;
      if (_isRunning) {
        _isRunning = false;
        changed = true;
      }
      if (_isTradingWindow) {
        _isTradingWindow = false;
        changed = true;
      }
      if (_error != null) {
        _error = null;
        changed = true;
      }
      if (changed) _safeNotify();
      debugPrint('TradingControlProvider._fetchStatus error: $e');
    }
  }

  /// 자동매매를 시작 요청한다.
  ///
  /// 서버가 꺼져 있으면 자동으로 시작한 뒤 매매를 시작한다.
  Future<void> startTrading() async {
    if (_isBusy) return;
    _isBusy = true;
    _error = null;
    _safeNotify();

    try {
      // 서버가 꺼져 있으면 먼저 시작한다.
      if (!_isConnected) {
        final serverOk = await _ensureServer();
        if (!serverOk) {
          _isBusy = false;
          _safeNotify();
          return;
        }
      }

      final result = await _apiService.startTrading();
      final status = result['status'] as String? ?? '';
      // "started" 또는 "already_running" 모두 실행 중으로 처리한다.
      _isRunning = true;
      _isConnected = true;
      // 매매 세션 보호를 활성화한다 (07:00 KST까지 서버 유지).
      _activateSessionProtection();
      debugPrint('TradingControlProvider.startTrading: $status');
    } on ServerUnreachableException catch (e) {
      debugPrint('TradingControlProvider.startTrading: server unreachable');
      _isConnected = false;
      _error = e.toString();
    } catch (e) {
      debugPrint('TradingControlProvider.startTrading error: $e');
      _error = e.toString();
    } finally {
      _isBusy = false;
      _safeNotify();
    }
  }

  /// 자동매매를 중지 요청한다.
  Future<void> stopTrading() async {
    if (_isBusy) return;
    _isBusy = true;
    _error = null;
    _safeNotify();

    try {
      final result = await _apiService.stopTrading();
      final status = result['status'] as String? ?? '';
      // "stopped" 또는 "not_running" 모두 중지로 처리한다.
      _isRunning = false;
      _isConnected = true;
      debugPrint('TradingControlProvider.stopTrading: $status');
    } on ServerUnreachableException catch (e) {
      debugPrint('TradingControlProvider.stopTrading: server unreachable');
      _isConnected = false;
      _error = e.toString();
    } catch (e) {
      debugPrint('TradingControlProvider.stopTrading error: $e');
      _error = e.toString();
    } finally {
      _isBusy = false;
      _safeNotify();
    }
  }

  /// 뉴스 수집 & 전송 파이프라인을 실행한다.
  ///
  /// 서버가 꺼져 있으면 자동으로 시작한 뒤 뉴스 수집을 실행한다.
  /// 크롤링 -> 분류 -> 번역 -> 텔레그램 전송을 순차 실행한다.
  /// 결과를 _newsResult에 저장하고, 에러 발생 시 _error에 기록한다.
  Future<void> collectAndSendNews() async {
    if (_isBusyNews) return;
    _isBusyNews = true;
    _error = null;
    _newsResult = null;
    _safeNotify();

    try {
      // 서버가 꺼져 있으면 먼저 시작한다.
      if (!_isConnected) {
        final serverOk = await _ensureServer();
        if (!serverOk) {
          _isBusyNews = false;
          _safeNotify();
          return;
        }
      }

      final result = await _apiService.collectAndSendNews();
      debugPrint('TradingControlProvider.collectAndSendNews: $result');
      final newsCount = result['news_count'] as int? ?? 0;
      final keyCount = result['key_news_count'] as int? ?? 0;
      final crawledCount = result['crawled_count'] as int? ?? 0;
      final translatedCount = result['translated_count'] as int? ?? 0;
      final telegramSent = result['telegram_sent'] as bool? ?? false;
      final telegramText = telegramSent ? '전송 완료' : '전송 안 함';
      _newsResult =
          '크롤링 ${crawledCount}건 → 분류 ${newsCount}건 → '
          '번역 ${translatedCount}건 → 고영향 ${keyCount}건 '
          '(텔레그램: $telegramText)';
    } on ServerUnreachableException catch (e) {
      // 타임아웃은 서버 연결 문제가 아니라 파이프라인이 오래 걸리는 것이다.
      // _isConnected를 false로 바꾸면 대시보드 전체가 끊긴 것으로 표시되므로,
      // 타임아웃인 경우에만 연결 상태를 유지한다.
      final msg = e.toString();
      final isTimeout = msg.contains('TimeoutException') ||
          msg.contains('Future not completed');
      if (!isTimeout) {
        _isConnected = false;
      }
      debugPrint(
          'TradingControlProvider.collectAndSendNews: $msg (isTimeout=$isTimeout)');
      _error = isTimeout
          ? '뉴스 수집 시간 초과 (크롤링+분류에 시간이 소요됩니다. 잠시 후 다시 시도하세요)'
          : '서버 연결 실패';
    } catch (e) {
      debugPrint('TradingControlProvider.collectAndSendNews error: $e');
      _error = e.toString();
    } finally {
      _isBusyNews = false;
      _safeNotify();
    }
  }
}
