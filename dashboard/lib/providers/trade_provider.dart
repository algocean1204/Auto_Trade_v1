import 'package:flutter/material.dart';
import '../models/trade_models.dart';
import '../models/dashboard_models.dart';
import '../services/api_service.dart';

class TradeProvider with ChangeNotifier {
  final ApiService _apiService;

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
    notifyListeners();

    try {
      _strategyParams = await _apiService.getStrategyParams();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> updateStrategyParams(Map<String, dynamic> params) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _apiService.updateStrategyParams(params);
      await loadStrategyParams();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> loadDailyReport(String date) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final report = await _apiService.getDailyReport(date);
      _reports = [report];
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> loadWeeklyReport(String week) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final report = await _apiService.getWeeklyReport(week);
      _reports = [report];
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> loadPendingAdjustments() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _pendingAdjustments = await _apiService.getPendingAdjustments();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  // 백엔드 PendingAdjustment.id는 UUID String이다.
  Future<void> approveAdjustment(String id) async {
    try {
      await _apiService.approveAdjustment(id);
      await loadPendingAdjustments();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> rejectAdjustment(String id) async {
    try {
      await _apiService.rejectAdjustment(id);
      await loadPendingAdjustments();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> loadUniverse() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _universe = await _apiService.getUniverse();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> addTicker(UniverseTicker ticker) async {
    try {
      await _apiService.addTicker(ticker);
      await loadUniverse();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> toggleTicker(String ticker, bool enabled) async {
    try {
      await _apiService.toggleTicker(ticker, enabled);
      await loadUniverse();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> deleteTicker(String ticker) async {
    try {
      await _apiService.deleteTicker(ticker);
      await loadUniverse();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }
}
