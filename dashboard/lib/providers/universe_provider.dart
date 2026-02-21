import 'package:flutter/material.dart';
import '../models/universe_models.dart';
import '../services/api_service.dart';

/// 유니버스(종목) 관리 상태 관리 프로바이더이다.
class UniverseProvider with ChangeNotifier {
  final ApiService _api;

  List<UniverseTickerEx>? _tickers;
  List<TickerMapping>? _mappings;
  List<SectorData>? _sectors;
  bool _isLoading = false;
  bool _isSectorsLoading = false;
  String? _error;

  UniverseProvider(this._api);

  List<UniverseTickerEx>? get tickers => _tickers;
  List<TickerMapping>? get mappings => _mappings;
  List<SectorData>? get sectors => _sectors;
  bool get isLoading => _isLoading;
  bool get isSectorsLoading => _isSectorsLoading;
  String? get error => _error;

  List<UniverseTickerEx> get activeTickers =>
      _tickers?.where((t) => t.enabled).toList() ?? [];

  List<UniverseTickerEx> get inactiveTickers =>
      _tickers?.where((t) => !t.enabled).toList() ?? [];

  /// 종목 목록과 매핑을 모두 로드한다.
  Future<void> loadAll() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final results = await Future.wait([
        _api.getUniverseEx(),
        _api.getUniverseMappings(),
      ]);
      _tickers = results[0] as List<UniverseTickerEx>;
      _mappings = results[1] as List<TickerMapping>;
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 종목 활성/비활성 토글한다.
  Future<void> toggleTicker(String ticker, bool enabled) async {
    try {
      await _api.toggleUniverseTicker(ticker, enabled);
      await loadAll();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  /// 새 종목을 추가한다.
  Future<void> addTicker(Map<String, dynamic> data) async {
    try {
      await _api.addUniverseTicker(data);
      await loadAll();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  /// 종목을 삭제한다.
  Future<void> removeTicker(String ticker) async {
    try {
      await _api.removeUniverseTicker(ticker);
      await loadAll();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  /// 매핑을 추가한다.
  Future<void> addMapping(String underlying, String? bull, String? bear) async {
    try {
      await _api.addUniverseMapping(underlying, bull, bear);
      await loadAll();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  /// 매핑을 삭제한다.
  Future<void> removeMapping(String underlying) async {
    try {
      await _api.removeUniverseMapping(underlying);
      await loadAll();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  /// 섹터 데이터를 로드한다.
  Future<void> loadSectors() async {
    _isSectorsLoading = true;
    notifyListeners();

    try {
      final result = await _api.fetchSectors();
      final rawSectors = result['sectors'] as List? ?? [];
      _sectors = rawSectors
          .map((e) => SectorData.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      _sectors = [];
    } finally {
      _isSectorsLoading = false;
      notifyListeners();
    }
  }

  /// 종목 코드만 입력하면 Claude가 정보를 조회하여 자동으로 종목을 추가한다.
  Future<Map<String, dynamic>> autoAddTicker(String ticker) async {
    final result = await _api.autoAddTicker(ticker);
    // 추가 후 데이터를 새로고침한다.
    await loadAll();
    await loadSectors();
    return result;
  }

  /// 데이터를 새로고침한다.
  Future<void> refresh() async {
    _tickers = null;
    _mappings = null;
    _sectors = null;
    await loadAll();
  }
}
