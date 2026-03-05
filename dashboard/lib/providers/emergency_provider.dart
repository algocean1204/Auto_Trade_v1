import 'dart:async';
import 'package:flutter/material.dart';
import '../models/emergency_models.dart';
import '../services/api_service.dart';

class EmergencyProvider with ChangeNotifier {
  final ApiService _apiService;
  Timer? _refreshTimer;

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

  // 30초마다 긴급 상태를 갱신한다
  void _startPeriodicRefresh() {
    _refreshTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => loadStatus(),
    );
    loadStatus();
  }

  Future<void> loadStatus() async {
    try {
      _status = await _apiService.getEmergencyStatus();
      _error = null;
      notifyListeners();
    } catch (e) {
      // 연결 실패 시 기존 상태 유지
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<bool> triggerEmergencyStop({String reason = 'Manual stop by user'}) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _apiService.triggerEmergencyStop(reason: reason);
      await loadStatus();
      return true;
    } catch (e) {
      _error = e.toString();
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> resumeTrading() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _apiService.resumeTrading();
      await loadStatus();
      return true;
    } catch (e) {
      _error = e.toString();
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    super.dispose();
  }
}
