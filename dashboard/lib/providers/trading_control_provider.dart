import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';

/// 자동매매 시작/중지 제어 상태를 관리한다.
///
/// 서버 연결 상태(_isConnected)를 추적하여 "서버가 중지라고 응답"과
/// "서버에 연결 불가"를 구분한다.
/// 매매 시간 윈도우 관련 정보(_isTradingWindow, _isTradingDay 등)도 함께 관리한다.
class TradingControlProvider with ChangeNotifier {
  final ApiService _apiService;

  TradingControlProvider(this._apiService);

  /// 자동매매 실행 여부이다 (마지막 성공 응답 기준).
  bool _isRunning = false;

  /// 서버 연결 가능 여부이다.
  bool _isConnected = true;

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

  bool get isRunning => _isRunning;
  bool get isConnected => _isConnected;
  bool get isBusy => _isBusy;
  bool get isBusyNews => _isBusyNews;
  String? get error => _error;
  String? get newsResult => _newsResult;

  bool get isTradingWindow => _isTradingWindow;
  bool get isTradingDay => _isTradingDay;
  DateTime? get nextWindowStart => _nextWindowStart;
  String? get sessionType => _sessionType;
  String? get currentKst => _currentKst;

  /// 폴링을 시작한다. 화면 진입 시 1회 호출한다.
  void startPolling() {
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
    stopPolling();
    super.dispose();
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
        changed = true;
      }
      if (_isRunning != running) {
        _isRunning = running;
        changed = true;
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
      if (changed) notifyListeners();
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
      if (changed) notifyListeners();
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
      if (changed) notifyListeners();
      debugPrint('TradingControlProvider._fetchStatus error: $e');
    }
  }

  /// 자동매매를 시작 요청한다.
  Future<void> startTrading() async {
    if (_isBusy) return;
    _isBusy = true;
    _error = null;
    notifyListeners();

    try {
      final result = await _apiService.startTrading();
      final status = result['status'] as String? ?? '';
      // "started" 또는 "already_running" 모두 실행 중으로 처리한다.
      _isRunning = true;
      _isConnected = true;
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
      notifyListeners();
    }
  }

  /// 자동매매를 중지 요청한다.
  Future<void> stopTrading() async {
    if (_isBusy) return;
    _isBusy = true;
    _error = null;
    notifyListeners();

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
      notifyListeners();
    }
  }

  /// 뉴스 수집 & 전송 파이프라인을 실행한다.
  ///
  /// 크롤링 -> 분류 -> 번역 -> 텔레그램 전송을 순차 실행한다.
  /// 결과를 _newsResult에 저장하고, 에러 발생 시 _error에 기록한다.
  Future<void> collectAndSendNews() async {
    if (_isBusyNews) return;
    _isBusyNews = true;
    _error = null;
    _newsResult = null;
    notifyListeners();

    try {
      final result = await _apiService.collectAndSendNews();
      final newsCount = result['news_count'] as int? ?? 0;
      final keyCount = result['key_news_count'] as int? ?? 0;
      final telegramSent = result['telegram_sent'] as bool? ?? false;
      _newsResult =
          'news:$newsCount,key:$keyCount,telegram:$telegramSent';
      debugPrint('TradingControlProvider.collectAndSendNews: $result');
    } on ServerUnreachableException catch (e) {
      debugPrint(
          'TradingControlProvider.collectAndSendNews: server unreachable');
      _isConnected = false;
      _error = e.toString();
    } catch (e) {
      debugPrint('TradingControlProvider.collectAndSendNews error: $e');
      _error = e.toString();
    } finally {
      _isBusyNews = false;
      notifyListeners();
    }
  }
}
