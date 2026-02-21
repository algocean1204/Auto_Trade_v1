import 'package:flutter/material.dart';
import '../models/benchmark_models.dart';
import '../services/api_service.dart';

class BenchmarkProvider with ChangeNotifier {
  final ApiService _apiService;

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
    notifyListeners();

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
      notifyListeners();
    }
  }

  Future<void> refresh() async {
    await loadAll();
  }
}
