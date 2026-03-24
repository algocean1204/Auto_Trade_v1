import 'package:flutter/material.dart';
import '../models/dashboard_models.dart';
import '../services/api_service.dart';

class SettingsProvider with ChangeNotifier {
  final ApiService _apiService;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  SettingsProvider(this._apiService);

  List<AlertNotification> _alerts = [];
  int _unreadCount = 0;
  bool _isLoading = false;
  String? _error;

  List<AlertNotification> get alerts => _alerts;
  int get unreadCount => _unreadCount;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadAlerts({
    int limit = 50,
    String? alertType,
    String? severity,
  }) async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      _alerts = await _apiService.getAlerts(
        limit: limit,
        alertType: alertType,
        severity: severity,
      );
      _unreadCount = await _apiService.getUnreadCount();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  Future<void> markAsRead(String id) async {
    try {
      await _apiService.markAlertAsRead(id);
      await loadAlerts();
    } catch (e) {
      _error = e.toString();
      _safeNotify();
    }
  }

  Future<void> refreshUnreadCount() async {
    try {
      _unreadCount = await _apiService.getUnreadCount();
      _safeNotify();
    } catch (e) {
      _error = e.toString();
      _safeNotify();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }

  /// dispose 이후 안전하게 notifyListeners를 호출한다.
  void _safeNotify() {
    if (!_disposed) notifyListeners();
  }
}
