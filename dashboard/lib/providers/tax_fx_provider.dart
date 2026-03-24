import 'package:flutter/material.dart';
import '../models/tax_models.dart';
import '../models/fx_models.dart';
import '../services/api_service.dart';

class TaxFxProvider with ChangeNotifier {
  final ApiService _apiService;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

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
    _safeNotify();

    // 개별 실패가 전체를 막지 않도록 각각 시도한다
    await Future.wait([
      _loadTaxStatus(),
      _loadFxStatus(),
    ]);

    _isLoading = false;
    _safeNotify();
  }

  Future<void> _loadTaxStatus() async {
    try {
      _taxStatus = await _apiService.getTaxStatus();
      _harvestSuggestions = await _apiService.getTaxHarvestSuggestions();
    } catch (e) {
      // 세금 데이터 로드 실패는 기록만 하고 기존 데이터를 유지한다
      debugPrint('TaxFxProvider: tax load failed - $e');
    }
  }

  Future<void> _loadFxStatus() async {
    try {
      _fxStatus = await _apiService.getFxStatus();
      _fxHistory = await _apiService.getFxHistory();
    } catch (e) {
      // FX 데이터 로드 실패는 기록만 하고 기존 데이터를 유지한다
      debugPrint('TaxFxProvider: fx load failed - $e');
    }
  }

  Future<void> refresh() async {
    await loadAll();
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
