import 'dart:async';
import 'package:flutter/material.dart';
import '../models/emergency_models.dart';
import '../services/api_service.dart';

class EmergencyProvider with ChangeNotifier {
  final ApiService _apiService;
  Timer? _refreshTimer;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  EmergencyProvider(this._apiService) {
    _startPeriodicRefresh();
  }

  EmergencyStatus _status = EmergencyStatus.defaultSafe();
  bool _isLoading = false;
  String? _error;

  EmergencyStatus get status => _status;
  // 서킷 브레이커 또는 runaway loss 중 하나라도 활성이면 긴급 상태로 간주한다
  bool get isEmergencyStopped => _status.isAnyEmergencyActive;
  bool get isLoading => _isLoading;
  String? get error => _error;

  // 30초마다 긴급 상태를 갱신한다.
  // 초기 로드는 scheduleMicrotask로 지연하여 위젯 트리 연결 전 notifyListeners 호출을 방지한다.
  void _startPeriodicRefresh() {
    _refreshTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => loadStatus(),
    );
    Future.microtask(() => loadStatus());
  }

  Future<void> loadStatus() async {
    try {
      _status = await _apiService.getEmergencyStatus();
      _error = null;
      _safeNotify();
    } catch (e) {
      // 연결 실패 시 기존 상태 유지
      _error = e.toString();
      _safeNotify();
    }
  }

  Future<bool> triggerEmergencyStop({String reason = 'Manual stop by user'}) async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      await _apiService.triggerEmergencyStop(reason: reason);
      await loadStatus();
      return true;
    } catch (e) {
      _error = e.toString();
      return false;
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  Future<bool> resumeTrading() async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      await _apiService.resumeTrading();
      await loadStatus();
      return true;
    } catch (e) {
      _error = e.toString();
      return false;
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _refreshTimer?.cancel();
    super.dispose();
  }

  /// dispose 이후 안전하게 notifyListeners를 호출한다.
  void _safeNotify() {
    if (!_disposed) notifyListeners();
  }
}
