import 'package:flutter/material.dart';
import '../models/dashboard_models.dart';
import '../services/api_service.dart';

class SettingsProvider with ChangeNotifier {
  final ApiService _apiService;

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
    notifyListeners();

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
      notifyListeners();
    }
  }

  Future<void> markAsRead(String id) async {
    try {
      await _apiService.markAlertAsRead(id);
      await loadAlerts();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> refreshUnreadCount() async {
    try {
      _unreadCount = await _apiService.getUnreadCount();
      notifyListeners();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }
}
