import 'dart:async';
import 'package:flutter/material.dart';
import '../models/dashboard_models.dart';
import '../services/api_service.dart';
import 'trading_mode_provider.dart';

/// 서버 연결 상태를 나타낸다.
enum ServerConnectionState {
  /// 아직 연결을 시도하지 않은 초기 상태이다.
  unknown,

  /// 서버와 정상 통신 중이다.
  connected,

  /// 서버에 물리적으로 연결할 수 없다 (프로세스 다운 등).
  disconnected,

  /// 재연결을 시도 중이다.
  reconnecting,
}

class DashboardProvider with ChangeNotifier {
  final ApiService _apiService;

  DashboardProvider(this._apiService);

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  DashboardSummary? _summary;
  SystemStatus? _systemStatus;
  bool _isLoading = false;
  String? _error;

  /// 현재 적용 중인 투자 모드이다 (null이면 기본값 사용).
  TradingMode? _currentMode;

  /// 두 계좌의 요약 데이터이다 (모의 + 실전).
  Map<String, dynamic> _accountsSummary = {};

  /// 현재 모드의 보유 포지션 목록이다.
  List<Map<String, dynamic>> _positions = [];

  /// 서버 물리 연결 상태이다.
  ServerConnectionState _connectionState = ServerConnectionState.unknown;

  /// 자동 재연결 타이머이다.
  Timer? _reconnectTimer;

  /// 1초 주기 자동 새로고침 타이머이다.
  Timer? _autoRefreshTimer;

  /// 자동 새로고침 중 중복 호출 방지 플래그이다.
  bool _isAutoRefreshing = false;

  /// 다음 재연결까지 남은 초이다.
  int _retryCountdown = 0;

  /// 재연결 주기 (초 단위)이다.
  static const _reconnectIntervalSec = 30;

  DashboardSummary? get summary => _summary;
  SystemStatus? get systemStatus => _systemStatus;
  bool get isLoading => _isLoading;
  String? get error => _error;
  ServerConnectionState get connectionState => _connectionState;
  int get retryCountdown => _retryCountdown;

  /// 두 계좌의 요약 데이터를 반환한다.
  Map<String, dynamic> get accountsSummary => _accountsSummary;

  /// 현재 모드의 보유 포지션 목록을 반환한다.
  List<Map<String, dynamic>> get positions => _positions;

  /// 서버에 연결할 수 없는 상태인지 반환한다.
  bool get isServerDisconnected =>
      _connectionState == ServerConnectionState.disconnected ||
      _connectionState == ServerConnectionState.reconnecting;

  @override
  void dispose() {
    _disposed = true;
    stopAutoRefresh();
    _cancelReconnectTimer();
    super.dispose();
  }

  /// dispose 이후 안전하게 notifyListeners를 호출한다.
  void _safeNotify() {
    if (!_disposed) notifyListeners();
  }

  /// 1초 주기 자동 새로고침을 시작한다.
  /// 이전 요청이 완료되지 않았으면 해당 틱은 건너뛴다.
  void startAutoRefresh() {
    stopAutoRefresh();
    _autoRefreshTimer = Timer.periodic(const Duration(seconds: 3), (_) {
      if (!_isAutoRefreshing) {
        _autoRefreshSilent();
      }
    });
  }

  /// 자동 새로고침을 중지한다.
  void stopAutoRefresh() {
    _autoRefreshTimer?.cancel();
    _autoRefreshTimer = null;
  }

  /// 자동 새로고침용 조용한 데이터 로드이다.
  /// _isLoading 플래그를 건드리지 않아 UI 깜빡임이 없다.
  /// 4개 API를 병렬로 호출하여 응답 대기 시간을 최소화한다.
  Future<void> _autoRefreshSilent() async {
    _isAutoRefreshing = true;
    try {
      final modeStr = _currentMode?.name;
      final results = await Future.wait([
        _apiService.getDashboardSummary(mode: modeStr),
        _apiService.getSystemStatus(),
        _apiService.getAccountsSummary(),
        _apiService.getPositions(mode: modeStr),
      ]);

      _summary = results[0] as DashboardSummary;
      _systemStatus = results[1] as SystemStatus;
      _accountsSummary = results[2] as Map<String, dynamic>;
      _positions = results[3] as List<Map<String, dynamic>>;
      _error = null;
      _setConnectionState(ServerConnectionState.connected);
      _cancelReconnectTimer();
      _safeNotify();
    } on ServerUnreachableException {
      _setConnectionState(ServerConnectionState.disconnected);
      _safeNotify();
    } catch (e) {
      // 자동 새로고침 실패 시 기존 데이터 유지, 에러만 갱신
      _error = e.toString();
      _safeNotify();
    } finally {
      _isAutoRefreshing = false;
    }
  }

  /// 투자 모드를 설정하고 데이터를 재로드한다.
  /// 이미 같은 모드라면 재로드하지 않는다.
  Future<void> setMode(TradingMode mode) async {
    if (_currentMode == mode) return;
    _currentMode = mode;
    await loadDashboardData();
  }

  /// 투자 모드를 강제로 동기화하고 데이터를 재로드한다.
  /// 모드가 같더라도 항상 loadDashboardData를 호출한다.
  /// 화면 진입 시 최신 포지션·계좌 데이터를 보장하기 위해 사용한다.
  Future<void> syncModeAndLoad(TradingMode mode) async {
    _currentMode = mode;
    await loadDashboardData();
  }

  Future<void> loadDashboardData() async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      final modeStr = _currentMode?.name; // 'virtual' 또는 'real', null이면 서버 기본값 사용
      // 4개 API를 병렬로 호출하여 응답 대기 시간을 최소화한다.
      final results = await Future.wait([
        _apiService.getDashboardSummary(mode: modeStr),
        _apiService.getSystemStatus(),
        _apiService.getAccountsSummary(),
        _apiService.getPositions(mode: modeStr),
      ]);
      _summary = results[0] as DashboardSummary;
      _systemStatus = results[1] as SystemStatus;
      _accountsSummary = results[2] as Map<String, dynamic>;
      _positions = results[3] as List<Map<String, dynamic>>;
      _error = null;
      _setConnectionState(ServerConnectionState.connected);
      // 성공하면 재연결 타이머를 취소한다
      _cancelReconnectTimer();
    } on ServerUnreachableException catch (e) {
      debugPrint('DashboardProvider: server unreachable - $e');
      _error = e.toString();
      _setConnectionState(ServerConnectionState.disconnected);
      _scheduleReconnect();
    } catch (e) {
      debugPrint('DashboardProvider: load error - $e');
      _error = e.toString();
      // 일반 오류는 연결 상태를 변경하지 않는다
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  Future<void> refresh() async {
    _cancelReconnectTimer();
    await loadDashboardData();
  }

  /// 서버 연결 상태를 변경하고 리스너에 알린다.
  void _setConnectionState(ServerConnectionState state) {
    if (_connectionState == state) return;
    _connectionState = state;
    // notifyListeners는 loadDashboardData의 finally에서 호출된다
  }

  /// 30초 주기 자동 재연결 타이머를 예약한다.
  void _scheduleReconnect() {
    _cancelReconnectTimer();
    _retryCountdown = _reconnectIntervalSec;
    _safeNotify();

    // 카운트다운 타이머: 1초마다 감소
    _reconnectTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      _retryCountdown--;
      if (_retryCountdown <= 0) {
        timer.cancel();
        _reconnectTimer = null;
        _retryCountdown = 0;
        _connectionState = ServerConnectionState.reconnecting;
        _safeNotify();
        // 재연결 시도
        loadDashboardData();
      } else {
        _safeNotify();
      }
    });
  }

  void _cancelReconnectTimer() {
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _retryCountdown = 0;
  }
}
