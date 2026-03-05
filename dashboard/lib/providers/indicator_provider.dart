import 'package:flutter/material.dart';
import '../models/indicator_models.dart';
import '../services/api_service.dart';

class IndicatorProvider with ChangeNotifier {
  final ApiService _apiService;

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
    notifyListeners();

    try {
      _weights = await _apiService.getIndicatorWeights();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> updateWeights(Map<String, double> newWeights) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _apiService.updateIndicatorWeights(newWeights);
      await loadWeights();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> loadRealtimeIndicator(String ticker) async {
    try {
      final data = await _apiService.getRealtimeIndicator(ticker);
      _realtimeData[ticker] = data;
      notifyListeners();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  void applyPreset(WeightPreset preset) {
    final currentWeights = _weights;
    if (currentWeights != null) {
      _weights = IndicatorWeights(
        weights: Map.from(preset.weights),
        presets: currentWeights.presets,
      );
      notifyListeners();
    }
  }
}
