import 'package:flutter/material.dart';
import '../models/chart_models.dart';
import '../services/api_service.dart';

class ChartProvider with ChangeNotifier {
  final ApiService _apiService;

  ChartProvider(this._apiService);

  List<DailyReturn> _dailyReturns = [];
  List<CumulativeReturn> _cumulativeReturns = [];
  List<HeatmapPoint> _tickerHeatmap = [];
  List<HeatmapPoint> _hourlyHeatmap = [];
  List<DrawdownPoint> _drawdown = [];

  bool _isLoading = false;
  String? _error;

  List<DailyReturn> get dailyReturns => _dailyReturns;
  List<CumulativeReturn> get cumulativeReturns => _cumulativeReturns;
  List<HeatmapPoint> get tickerHeatmap => _tickerHeatmap;
  List<HeatmapPoint> get hourlyHeatmap => _hourlyHeatmap;
  List<DrawdownPoint> get drawdown => _drawdown;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadAllCharts({int days = 30}) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final results = await Future.wait([
        _apiService.getDailyReturns(days: days),
        _apiService.getCumulativeReturns(),
        _apiService.getTickerHeatmap(days: days),
        _apiService.getHourlyHeatmap(),
        _apiService.getDrawdown(),
      ]);

      _dailyReturns = results[0] as List<DailyReturn>;
      _cumulativeReturns = results[1] as List<CumulativeReturn>;
      _tickerHeatmap = results[2] as List<HeatmapPoint>;
      _hourlyHeatmap = results[3] as List<HeatmapPoint>;
      _drawdown = results[4] as List<DrawdownPoint>;
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 홈 대시보드 미니 차트를 위한 누적 수익률 데이터만 로드한다.
  Future<void> loadCumulativeReturns() async {
    // 이미 데이터가 있으면 재요청하지 않는다.
    if (_cumulativeReturns.isNotEmpty) return;
    try {
      _cumulativeReturns = await _apiService.getCumulativeReturns();
      notifyListeners();
    } catch (e) {
      // 홈 화면에서는 차트 오류를 조용히 처리한다.
    }
  }

  Future<void> refresh() async {
    await loadAllCharts();
  }
}
