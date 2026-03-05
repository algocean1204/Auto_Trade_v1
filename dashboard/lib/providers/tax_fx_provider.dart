import 'package:flutter/material.dart';
import '../models/tax_models.dart';
import '../models/fx_models.dart';
import '../services/api_service.dart';

class TaxFxProvider with ChangeNotifier {
  final ApiService _apiService;

  TaxFxProvider(this._apiService);

  TaxStatus? _taxStatus;
  List<TaxHarvestSuggestion> _harvestSuggestions = [];
  FxStatus? _fxStatus;
  List<FxHistoryPoint> _fxHistory = [];

  bool _isLoading = false;
  String? _error;

  TaxStatus? get taxStatus => _taxStatus;
  List<TaxHarvestSuggestion> get harvestSuggestions => _harvestSuggestions;
  FxStatus? get fxStatus => _fxStatus;
  List<FxHistoryPoint> get fxHistory => _fxHistory;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadAll() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    // 개별 실패가 전체를 막지 않도록 각각 시도한다
    await Future.wait([
      _loadTaxStatus(),
      _loadFxStatus(),
    ]);

    _isLoading = false;
    notifyListeners();
  }

  Future<void> _loadTaxStatus() async {
    try {
      _taxStatus = await _apiService.getTaxStatus();
      _harvestSuggestions = await _apiService.getTaxHarvestSuggestions();
    } catch (e) {
      // 세금 데이터 로드 실패는 기록만 한다
    }
  }

  Future<void> _loadFxStatus() async {
    try {
      _fxStatus = await _apiService.getFxStatus();
      _fxHistory = await _apiService.getFxHistory();
    } catch (e) {
      // FX 데이터 로드 실패는 기록만 한다
    }
  }

  Future<void> refresh() async {
    await loadAll();
  }
}
