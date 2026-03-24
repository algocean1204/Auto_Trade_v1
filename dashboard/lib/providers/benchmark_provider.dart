import 'package:flutter/material.dart';
import '../models/benchmark_models.dart';
import '../services/api_service.dart';

class BenchmarkProvider with ChangeNotifier {
  final ApiService _apiService;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  BenchmarkProvider(this._apiService);

  BenchmarkComparison? _comparison;
  List<BenchmarkChartPoint> _chartData = [];
  bool _isLoading = false;
  String? _error;

  BenchmarkComparison? get comparison => _comparison;
  List<BenchmarkChartPoint> get chartData => _chartData;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadAll() async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      final results = await Future.wait([
        _apiService.getBenchmarkComparison(),
        _apiService.getBenchmarkChart(),
      ]);
      _comparison = results[0] as BenchmarkComparison;
      _chartData = results[1] as List<BenchmarkChartPoint>;
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      _safeNotify();
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
