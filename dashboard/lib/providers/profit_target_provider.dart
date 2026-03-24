import 'package:flutter/material.dart';
import '../models/profit_target_models.dart';
import '../services/api_service.dart';

class ProfitTargetProvider with ChangeNotifier {
  final ApiService _apiService;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  ProfitTargetProvider(this._apiService);

  ProfitTargetStatus? _status;
  List<MonthlyHistory> _history = [];
  bool _isLoading = false;
  String? _error;

  ProfitTargetStatus? get status => _status;
  List<MonthlyHistory> get history => _history;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadStatus() async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      _status = await _apiService.getProfitTargetStatus();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  Future<void> loadHistory({int months = 6}) async {
    try {
      _history = await _apiService.getProfitTargetHistory(months: months);
      _safeNotify();
    } catch (e) {
      _error = e.toString();
      _safeNotify();
    }
  }

  Future<void> setAggressionLevel(String level) async {
    try {
      await _apiService.setAggressionLevel(level);
      await loadStatus();
    } catch (e) {
      _error = e.toString();
      _safeNotify();
    }
  }

  Future<void> refresh() async {
    await Future.wait([
      loadStatus(),
      loadHistory(),
    ]);
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
