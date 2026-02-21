import 'package:flutter/foundation.dart';
import '../services/api_service.dart';
import '../models/macro_models.dart';

/// 거시경제 지표 상태를 관리하는 Provider이다.
class MacroProvider extends ChangeNotifier {
  final ApiService _api;

  MacroIndicators? _indicators;
  FredHistoryData? _rateHistory;
  FredHistoryData? _cpiHistory;
  FredHistoryData? _vixHistory;
  List<EconomicEvent>? _calendar;
  RateOutlook? _rateOutlook;
  bool _isLoading = false;
  String? _errorMessage;

  /// 서버에 물리적으로 연결할 수 없는 상태인지 나타낸다.
  bool _isServerUnreachable = false;

  MacroProvider(this._api);

  MacroIndicators? get indicators => _indicators;
  FredHistoryData? get rateHistory => _rateHistory;
  FredHistoryData? get cpiHistory => _cpiHistory;
  FredHistoryData? get vixHistory => _vixHistory;
  List<EconomicEvent>? get calendar => _calendar;
  RateOutlook? get rateOutlook => _rateOutlook;
  bool get isLoading => _isLoading;

  /// 에러 메시지를 반환한다. 에러가 없으면 null이다.
  String? get errorMessage => _errorMessage;

  /// 서버에 연결할 수 없는 상태인지 반환한다.
  /// true이면 UI에서 "서버 미연결" 배너를 표시해야 한다.
  bool get isServerUnreachable => _isServerUnreachable;

  /// 에러가 있는지 반환한다 (서버 미연결 포함).
  bool get hasError => _errorMessage != null;

  /// 모든 거시경제 데이터를 병렬로 로드한다.
  Future<void> loadAll() async {
    _isLoading = true;
    _errorMessage = null;
    _isServerUnreachable = false;
    notifyListeners();

    try {
      final futures = await Future.wait<dynamic>([
        _safeFetch(() => _api.getMacroIndicators()),
        _safeFetch(() => _api.getFredHistory('DFF', days: 365)),
        _safeFetch(() => _api.getFredHistory('CPIAUCSL', days: 365)),
        _safeFetch(() => _api.getEconomicCalendar()),
        _safeFetch(() => _api.getRateOutlook()),
      ]);

      _indicators = futures[0] as MacroIndicators? ?? MacroIndicators.empty();
      _rateHistory = futures[1] as FredHistoryData?;
      _cpiHistory = futures[2] as FredHistoryData?;
      _calendar = futures[3] as List<EconomicEvent>?;
      _rateOutlook = futures[4] as RateOutlook?;
    } on ServerUnreachableException catch (e) {
      debugPrint('MacroProvider: server unreachable - $e');
      _errorMessage = e.toString();
      _isServerUnreachable = true;
      _indicators = MacroIndicators.empty();
    } catch (e) {
      debugPrint('MacroProvider.loadAll error: $e');
      _errorMessage = e.toString();
      _isServerUnreachable = false;
      _indicators = MacroIndicators.empty();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 특정 FRED 시리즈의 히스토리를 로드한다.
  Future<FredHistoryData?> loadHistory(String seriesId,
      {int days = 90}) async {
    try {
      return await _api.getFredHistory(seriesId, days: days);
    } catch (e) {
      debugPrint('MacroProvider.loadHistory error: $e');
      return null;
    }
  }

  /// 데이터를 강제 갱신한다.
  Future<void> refresh() => loadAll();

  /// API 호출을 안전하게 감싸서 예외를 null로 변환한다.
  /// ServerUnreachableException은 상위로 전파하여 구분 처리한다.
  Future<T?> _safeFetch<T>(Future<T> Function() fn) async {
    try {
      return await fn();
    } on ServerUnreachableException {
      rethrow;
    } catch (e) {
      debugPrint('MacroProvider._safeFetch error: $e');
      return null;
    }
  }
}
