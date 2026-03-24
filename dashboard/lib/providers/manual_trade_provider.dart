import 'package:flutter/material.dart';
import '../services/api_service.dart';

/// 수동 매매 요청의 상태를 관리하는 Provider이다.
///
/// 분석 요청 → AI 의견 표시 → 사용자 확인 → 실행의 흐름을 제어한다.
class ManualTradeProvider with ChangeNotifier {
  final ApiService _api;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  ManualTradeProvider(this._api);

  // ── 입력 상태 ──
  String _ticker = '';
  String _side = 'buy';
  int _quantity = 1;

  // ── 분석 결과 ──
  Map<String, dynamic>? _analysisResult;
  bool _isAnalyzing = false;
  String? _analyzeError;

  // ── 실행 결과 ──
  Map<String, dynamic>? _executeResult;
  bool _isExecuting = false;
  String? _executeError;

  // ── Getters ──
  String get ticker => _ticker;
  String get side => _side;
  int get quantity => _quantity;
  Map<String, dynamic>? get analysisResult => _analysisResult;
  bool get isAnalyzing => _isAnalyzing;
  String? get analyzeError => _analyzeError;
  Map<String, dynamic>? get executeResult => _executeResult;
  bool get isExecuting => _isExecuting;
  String? get executeError => _executeError;

  /// 분석 결과가 있고 아직 실행되지 않은 상태인지 확인한다.
  bool get canExecute =>
      _analysisResult != null && _executeResult == null && !_isExecuting;

  // ── 입력 업데이트 ──

  void setTicker(String value) {
    _ticker = value.toUpperCase().trim();
    // 입력이 변경되면 이전 분석/실행 결과를 초기화한다.
    _resetResults();
    _safeNotify();
  }

  void setSide(String value) {
    _side = value;
    _resetResults();
    _safeNotify();
  }

  void setQuantity(int value) {
    _quantity = value > 0 ? value : 1;
    _resetResults();
    _safeNotify();
  }

  /// 모든 상태를 초기화한다.
  void reset() {
    _ticker = '';
    _side = 'buy';
    _quantity = 1;
    _resetResults();
    _safeNotify();
  }

  void _resetResults() {
    _analysisResult = null;
    _analyzeError = null;
    _executeResult = null;
    _executeError = null;
  }

  // ── AI 분석 요청 ──

  /// 입력된 종목/방향/수량에 대해 AI 분석을 요청한다.
  Future<void> analyzeRequest() async {
    if (_ticker.isEmpty) {
      _analyzeError = '종목 코드를 입력하세요';
      _safeNotify();
      return;
    }

    _isAnalyzing = true;
    _analyzeError = null;
    _analysisResult = null;
    _executeResult = null;
    _executeError = null;
    _safeNotify();

    try {
      final result = await _api.manualTradeAnalyze(
        ticker: _ticker,
        side: _side,
        quantity: _quantity,
      );
      _analysisResult = result;
    } catch (e) {
      _analyzeError = e.toString();
    } finally {
      _isAnalyzing = false;
      _safeNotify();
    }
  }

  // ── 매매 실행 ──

  /// 분석 확인 후 실제 매매를 실행한다.
  Future<void> executeTrade() async {
    _isExecuting = true;
    _executeError = null;
    _safeNotify();

    try {
      final result = await _api.manualTradeExecute(
        ticker: _ticker,
        side: _side,
        quantity: _quantity,
      );
      _executeResult = result;
    } catch (e) {
      _executeError = e.toString();
    } finally {
      _isExecuting = false;
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
