import 'package:flutter/material.dart';
import '../models/report_models.dart';
import '../services/api_service.dart';

/// 일간 리포트 상태 관리 프로바이더이다.
class ReportProvider with ChangeNotifier {
  final ApiService _api;

  List<ReportDate>? _availableDates;
  DailyReport? _currentReport;
  String? _selectedDate;
  bool _isLoading = false;
  String? _error;

  ReportProvider(this._api);

  List<ReportDate>? get availableDates => _availableDates;
  DailyReport? get currentReport => _currentReport;
  String? get selectedDate => _selectedDate;
  bool get isLoading => _isLoading;
  String? get error => _error;

  /// 사용 가능한 날짜 목록을 로드한다.
  Future<void> loadDates({int limit = 30}) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _availableDates = await _api.getReportDates(limit: limit);
      _error = null;

      // 날짜가 있고 선택된 날짜가 없으면 첫 번째 날짜를 선택한다
      final dates = _availableDates;
      if (dates != null &&
          dates.isNotEmpty &&
          _selectedDate == null) {
        await loadReport(dates.first.date);
        _selectedDate = dates.first.date;
      }
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 특정 날짜의 리포트를 로드한다.
  Future<void> loadReport(String date) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _currentReport = await _api.getDailyTradingReport(date);
      _selectedDate = date;
      _error = null;
    } catch (e) {
      _error = e.toString();
      _currentReport = null;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 날짜를 선택하고 리포트를 로드한다.
  void selectDate(String date) {
    if (_selectedDate == date) return;
    loadReport(date);
  }

  /// 데이터를 새로고침한다.
  Future<void> refresh() async {
    _currentReport = null;
    _availableDates = null;
    _selectedDate = null;
    await loadDates();
  }
}
