import 'package:flutter/material.dart';
import '../models/profit_target_models.dart';
import '../services/api_service.dart';

class ProfitTargetProvider with ChangeNotifier {
  final ApiService _apiService;

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
    notifyListeners();

    try {
      _status = await _apiService.getProfitTargetStatus();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> loadHistory({int months = 6}) async {
    try {
      _history = await _apiService.getProfitTargetHistory(months: months);
      notifyListeners();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> setAggressionLevel(String level) async {
    try {
      await _apiService.setAggressionLevel(level);
      await loadStatus();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> refresh() async {
    await Future.wait([
      loadStatus(),
      loadHistory(),
    ]);
  }
}
