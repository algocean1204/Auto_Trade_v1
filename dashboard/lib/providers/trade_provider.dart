import 'package:flutter/material.dart';
import '../models/trade_models.dart';
import '../models/dashboard_models.dart';
import '../services/api_service.dart';

class TradeProvider with ChangeNotifier {
  final ApiService _apiService;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  TradeProvider(this._apiService);

  StrategyParams? _strategyParams;
  List<FeedbackReport> _reports = [];
  List<PendingAdjustment> _pendingAdjustments = [];
  List<UniverseTicker> _universe = [];
  bool _isLoading = false;
  String? _error;

  StrategyParams? get strategyParams => _strategyParams;
  List<FeedbackReport> get reports => _reports;
  List<PendingAdjustment> get pendingAdjustments => _pendingAdjustments;
  List<UniverseTicker> get universe => _universe;
  bool get isLoading => _isLoading;
  String? get error => _error;

  List<UniverseTicker> get bullTickers =>
      _universe.where((t) => t.direction == 'bull').toList();

  List<UniverseTicker> get bearTickers =>
      _universe.where((t) => t.direction == 'bear').toList();

  Future<void> loadStrategyParams() async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      _strategyParams = await _apiService.getStrategyParams();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  Future<void> updateStrategyParams(Map<String, dynamic> params) async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      await _apiService.updateStrategyParams(params);
      await loadStrategyParams();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  Future<void> loadDailyReport(String date) async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      final report = await _apiService.getDailyReport(date);
      _reports = [report];
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  Future<void> loadWeeklyReport(String week) async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      final report = await _apiService.getWeeklyReport(week);
      _reports = [report];
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  Future<void> loadPendingAdjustments() async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      _pendingAdjustments = await _apiService.getPendingAdjustments();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  // 백엔드 PendingAdjustment.id는 UUID String이다.
  Future<void> approveAdjustment(String id) async {
    try {
      await _apiService.approveAdjustment(id);
      await loadPendingAdjustments();
    } catch (e) {
      _error = e.toString();
      _safeNotify();
    }
  }

  Future<void> rejectAdjustment(String id) async {
    try {
      await _apiService.rejectAdjustment(id);
      await loadPendingAdjustments();
    } catch (e) {
      _error = e.toString();
      _safeNotify();
    }
  }

  Future<void> loadUniverse() async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      _universe = await _apiService.getUniverse();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  Future<void> addTicker(UniverseTicker ticker) async {
    try {
      await _apiService.addTicker(ticker);
      await loadUniverse();
    } catch (e) {
      _error = e.toString();
      _safeNotify();
    }
  }

  /// 티커 코드만으로 유니버스에 추가한다. 페어 티커도 자동으로 함께 추가된다.
  Future<Map<String, dynamic>> autoAddTicker(String ticker) async {
    try {
      final result = await _apiService.autoAddTicker(ticker);
      await loadUniverse();
      return result;
    } catch (e) {
      _error = e.toString();
      _safeNotify();
      rethrow;
    }
  }

  Future<void> toggleTicker(String ticker, bool enabled) async {
    try {
      await _apiService.toggleTicker(ticker, enabled);
      await loadUniverse();
    } catch (e) {
      _error = e.toString();
      _safeNotify();
    }
  }

  Future<void> deleteTicker(String ticker) async {
    try {
      await _apiService.deleteTicker(ticker);
      await loadUniverse();
    } catch (e) {
      _error = e.toString();
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
