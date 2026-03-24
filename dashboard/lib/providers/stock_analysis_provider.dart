import 'package:flutter/material.dart';
import '../models/stock_analysis_models.dart';
import '../services/api_service.dart';

/// 종목 종합 분석 화면의 상태 관리 프로바이더이다.
class StockAnalysisProvider with ChangeNotifier {
  final ApiService _api;

  StockAnalysisData? _data;
  bool _isLoading = false;
  String? _error;
  String _selectedTicker = '';

  /// 마지막으로 데이터를 성공적으로 불러온 시각이다.
  DateTime? _lastUpdated;

  /// 서버에서 가져온 분석 가능 종목 목록이다.
  List<String> _tickers = [];
  bool _tickersLoaded = false;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  StockAnalysisProvider(this._api);

  // ── Getters ──

  StockAnalysisData? get data => _data;
  bool get isLoading => _isLoading;
  String? get error => _error;
  String get selectedTicker => _selectedTicker;
  List<String> get tickers => _tickers;
  bool get tickersLoaded => _tickersLoaded;

  /// 마지막 업데이트 시각을 반환한다. 아직 로드되지 않은 경우 null이다.
  DateTime? get lastUpdated => _lastUpdated;

  /// 하드코딩 폴백 목록 (서버 응답 실패 시 사용)
  static const List<String> _fallbackTickers = [
    'NVDA', 'GOOGL', 'TSLA', 'SOXL',
    'AAPL', 'AMD', 'AMZN', 'COIN', 'META', 'MSFT',
    'DIA', 'IWM', 'QQQ', 'SOXX', 'SPY',
    'XLE', 'XLF', 'XLK',
  ];

  // ── Actions ──

  /// 서버에서 분석 가능 종목 목록을 로드한다.
  /// 최초 로드 시 첫 번째 티커를 기본 선택한다.
  Future<void> loadTickers() async {
    if (_tickersLoaded) return;
    try {
      final result = await _api.getAnalysisTickers();
      _tickers = result.isNotEmpty ? result : List.from(_fallbackTickers);
    } catch (_) {
      _tickers = List.from(_fallbackTickers);
    }
    _tickersLoaded = true;
    // 티커가 아직 선택되지 않았으면 첫 번째 티커를 기본값으로 설정한다
    if (_selectedTicker.isEmpty && _tickers.isNotEmpty) {
      _selectedTicker = _tickers.first;
    }
    _safeNotify();
  }

  /// 티커를 선택하고 분석 데이터를 로드한다.
  /// AI 분석 실패 시 기술 지표 기반 분석(ai=false)으로 자동 재시도한다.
  Future<void> loadAnalysis(String ticker) async {
    if (_isLoading) return;
    _selectedTicker = ticker;
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      _data = await _api.getStockAnalysis(ticker);
      _error = null;
      _lastUpdated = DateTime.now();
    } catch (e) {
      // AI 분석 실패 시 기술 지표 기반으로 재시도한다
      try {
        _data = await _api.getStockAnalysis(ticker, ai: false);
        _error = null;
        _lastUpdated = DateTime.now();
      } catch (e2) {
        _error = e2.toString();
      }
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  /// 분석 데이터를 새로고침한다.
  Future<void> refresh() async {
    await loadAnalysis(_selectedTicker);
  }

  /// 티커를 변경하고 새로운 분석 데이터를 로드한다.
  Future<void> changeTicker(String ticker) async {
    if (ticker == _selectedTicker && _data != null) return;
    _data = null;
    await loadAnalysis(ticker);
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
