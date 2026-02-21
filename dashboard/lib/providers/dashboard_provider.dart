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
    _cancelReconnectTimer();
    super.dispose();
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
    notifyListeners();

    try {
      final modeStr = _currentMode?.name; // 'virtual' 또는 'real', null이면 서버 기본값 사용
      _summary = await _apiService.getDashboardSummary(mode: modeStr);
      _systemStatus = await _apiService.getSystemStatus();
      // 두 계좌 요약을 비동기로 가져온다 (실패해도 메인 데이터에 영향 없음)
      _accountsSummary = await _apiService.getAccountsSummary();
      // 포지션 목록을 가져온다 (실패해도 메인 데이터에 영향 없음)
      _positions = await _apiService.getPositions(mode: modeStr);
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
      notifyListeners();
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
    notifyListeners();

    // 카운트다운 타이머: 1초마다 감소
    _reconnectTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      _retryCountdown--;
      if (_retryCountdown <= 0) {
        timer.cancel();
        _reconnectTimer = null;
        _retryCountdown = 0;
        _connectionState = ServerConnectionState.reconnecting;
        notifyListeners();
        // 재연결 시도
        loadDashboardData();
      } else {
        notifyListeners();
      }
    });
  }

  void _cancelReconnectTimer() {
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _retryCountdown = 0;
  }
}
