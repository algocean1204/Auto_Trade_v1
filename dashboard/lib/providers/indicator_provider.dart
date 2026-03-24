import 'package:flutter/material.dart';
import '../models/indicator_models.dart';
import '../services/api_service.dart';

class IndicatorProvider with ChangeNotifier {
  final ApiService _apiService;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  IndicatorProvider(this._apiService);

  IndicatorWeights? _weights;
  final Map<String, RealtimeIndicator> _realtimeData = {};
  bool _isLoading = false;
  String? _error;

  IndicatorWeights? get weights => _weights;
  Map<String, RealtimeIndicator> get realtimeData => _realtimeData;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadWeights() async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      _weights = await _apiService.getIndicatorWeights();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  Future<void> updateWeights(Map<String, double> newWeights) async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      await _apiService.updateIndicatorWeights(newWeights);
      await loadWeights();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  Future<void> loadRealtimeIndicator(String ticker) async {
    try {
      final data = await _apiService.getRealtimeIndicator(ticker);
      _realtimeData[ticker] = data;
      _safeNotify();
    } catch (e) {
      _error = e.toString();
      _safeNotify();
    }
  }

  void applyPreset(WeightPreset preset) {
    final currentWeights = _weights;
    if (currentWeights != null) {
      _weights = IndicatorWeights(
        weights: Map.from(preset.weights),
        presets: currentWeights.presets,
      );
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
