import 'package:flutter/material.dart';
import '../models/trade_reasoning_models.dart';
import '../services/api_service.dart';

/// 매매 근거 화면 상태 관리 프로바이더이다.
class TradeReasoningProvider with ChangeNotifier {
  final ApiService _api;

  List<TradeReasoningDate>? _dates;
  List<TradeReasoning>? _trades;
  TradeReasoningStats? _stats;
  String? _selectedDate;
  bool _isLoading = false;
  bool _isSubmittingFeedback = false;
  String? _error;

  TradeReasoningProvider(this._api);

  // ── Getters ──

  List<TradeReasoningDate>? get dates => _dates;
  List<TradeReasoning>? get trades => _trades;
  TradeReasoningStats? get stats => _stats;
  String? get selectedDate => _selectedDate;
  bool get isLoading => _isLoading;
  bool get isSubmittingFeedback => _isSubmittingFeedback;
  String? get error => _error;

  // ── Actions ──

  /// 매매 근거 날짜 목록을 로드한다.
  Future<void> loadDates() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final raw = await _api.getTradeReasoningDates();
      _dates = raw
          .map((e) =>
              TradeReasoningDate.fromJson(e as Map<String, dynamic>))
          .toList();
      _error = null;

      // 날짜 목록이 있고 아직 날짜를 선택하지 않았으면 첫 번째 날짜를 자동 선택한다
      final dates = _dates;
      if (dates != null && dates.isNotEmpty && _selectedDate == null) {
        _isLoading = false;
        notifyListeners();
        await selectDate(dates.first.date);
        return;
      }
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 특정 날짜의 매매 목록을 로드한다.
  Future<void> loadDaily(String date) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final raw = await _api.getTradeReasoningDaily(date);
      _trades = raw
          .map((e) =>
              TradeReasoning.fromJson(e as Map<String, dynamic>))
          .toList();
      _error = null;
    } catch (e) {
      _error = e.toString();
      _trades = [];
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 특정 날짜의 통계 요약을 로드한다.
  Future<void> loadStats(String date) async {
    try {
      final raw = await _api.getTradeReasoningStats(date);
      _stats = TradeReasoningStats.fromJson(raw);
      notifyListeners();
    } catch (e) {
      // 통계 로드 실패는 조용히 처리한다 (매매 목록은 계속 표시)
      _stats = null;
      notifyListeners();
    }
  }

  /// 날짜를 선택하고 매매 목록과 통계를 동시에 로드한다.
  Future<void> selectDate(String date) async {
    if (_selectedDate == date) return;
    _selectedDate = date;
    _trades = null;
    _stats = null;
    notifyListeners();

    await Future.wait([
      loadDaily(date),
      loadStats(date),
    ]);
  }

  /// 매매 근거에 피드백을 제출한다.
  Future<bool> submitFeedback(
    String tradeId, {
    required String feedback,
    required int rating,
    String? notes,
  }) async {
    _isSubmittingFeedback = true;
    notifyListeners();

    try {
      await _api.submitTradeReasoningFeedback(tradeId, {
        'feedback': feedback,
        'rating': rating,
        'notes': notes ?? '',
      });

      // 피드백 제출 후 현재 날짜의 데이터를 새로고침한다
      final selectedDate = _selectedDate;
      if (selectedDate != null) {
        await Future.wait([
          loadDaily(selectedDate),
          loadStats(selectedDate),
        ]);
      }
      return true;
    } catch (e) {
      return false;
    } finally {
      _isSubmittingFeedback = false;
      notifyListeners();
    }
  }

  /// 전체 데이터를 새로고침한다.
  Future<void> refresh() async {
    _dates = null;
    _trades = null;
    _stats = null;
    _selectedDate = null;
    _error = null;
    await loadDates();
  }
}
