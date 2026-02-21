import 'package:flutter/material.dart';
import '../models/risk_models.dart';
import '../services/api_service.dart';

class RiskProvider with ChangeNotifier {
  final ApiService _apiService;

  RiskProvider(this._apiService);

  RiskDashboardData? _dashboardData;
  bool _isLoading = false;
  String? _error;

  RiskDashboardData? get dashboardData => _dashboardData;
  List<RiskGateStatus> get gates => _dashboardData?.gates ?? [];
  RiskBudget? get riskBudget => _dashboardData?.riskBudget;
  // 백엔드는 {"limits": {...}, "positions": [...]} 형태로 반환한다.
  // 화면에서는 positions 리스트를 사용한다.
  List<PositionConcentration> get concentrations =>
      _dashboardData?.concentrations.positions ?? [];
  ConcentrationStatus? get concentrationStatus =>
      _dashboardData?.concentrations;
  VarIndicator? get varIndicator => _dashboardData?.varIndicator;
  TrailingStopStatus? get trailingStop => _dashboardData?.trailingStop;
  StreakCounter? get streakCounter => _dashboardData?.streakCounter;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadDashboard() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      // /api/risk/dashboard 엔드포인트를 사용한다
      _dashboardData = await _apiService.getRiskDashboard();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> refresh() async {
    await loadDashboard();
  }
}
