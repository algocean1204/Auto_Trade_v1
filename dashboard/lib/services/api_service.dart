import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../models/dashboard_models.dart';
import '../models/chart_models.dart';
import '../models/indicator_models.dart';
import '../models/trade_models.dart';
import '../models/profit_target_models.dart';
import '../models/risk_models.dart';
import '../models/tax_models.dart';
import '../models/fx_models.dart';
import '../models/emergency_models.dart';
import '../models/benchmark_models.dart';
import '../models/slippage_models.dart';
import '../models/agent_models.dart';
import '../models/macro_models.dart';
import '../models/rsi_models.dart';
import '../models/report_models.dart';
import '../models/universe_models.dart';
import '../models/news_models.dart';
import '../models/principles_models.dart';
import '../models/stock_analysis_models.dart';
import '../models/ticker_params_models.dart';
import '../constants/api_constants.dart';
import '../utils/env_loader.dart';

/// 서버에 물리적으로 연결할 수 없을 때 발생하는 예외이다.
/// SocketException, TimeoutException 등 네트워크 레벨 실패를 나타낸다.
class ServerUnreachableException implements Exception {
  final String message;
  const ServerUnreachableException([this.message = 'Server is unreachable']);

  @override
  String toString() => 'ServerUnreachableException: $message';
}

class ApiService {
  final String baseUrl;

  /// 자동매매 제어 엔드포인트(POST /api/trading/start, /stop) 인증에 사용하는 API 키이다.
  /// 백엔드 .env의 API_SECRET_KEY와 일치해야 한다.
  /// EnvLoader가 프로젝트 루트 .env 파일에서 API_SECRET_KEY를 자동으로 읽는다.
  /// --dart-define=API_SECRET_KEY=VALUE 빌드 파라미터로 오버라이드할 수 있다.
  /// 빈 문자열로 설정하면 Authorization 헤더를 전송하지 않는다.
  final String apiKey;

  /// 모든 HTTP 요청에 적용되는 타임아웃이다.
  static const _timeout = Duration(seconds: 15);

  ApiService({String? baseUrl, String? apiKey})
      : baseUrl = baseUrl ??
            EnvLoader.get(
              'API_BASE_URL',
              defaultValue: 'http://localhost:8000',
            ),
        apiKey = apiKey ?? EnvLoader.get('API_SECRET_KEY');

  /// 예외가 서버 미연결(네트워크 레벨) 오류인지 판별한다.
  static bool isConnectionError(Object e) {
    if (e is ServerUnreachableException) return true;
    final msg = e.toString().toLowerCase();
    return msg.contains('socketexception') ||
        msg.contains('connection refused') ||
        msg.contains('network is unreachable') ||
        msg.contains('timeoutexception') ||
        msg.contains('handshakeexception') ||
        msg.contains('failed host lookup');
  }

  // ── HTTP 헬퍼 메서드 ──

  /// 모든 요청에 공통 헤더를 생성한다.
  /// API 키가 설정된 경우 Authorization: Bearer 헤더를 포함한다.
  Map<String, String> _headers({bool withJson = false}) {
    final h = <String, String>{};
    if (withJson) h['Content-Type'] = 'application/json';
    if (apiKey.isNotEmpty) h['Authorization'] = 'Bearer $apiKey';
    return h;
  }

  /// SocketException / TimeoutException을 ServerUnreachableException으로 변환한다.
  T _wrapNetworkError<T>(Object e, StackTrace st) {
    if (e is SocketException || e is HandshakeException) {
      throw ServerUnreachableException(e.toString());
    }
    // TimeoutException은 dart:async에 있으나 toString으로 판별한다
    final msg = e.toString();
    if (msg.contains('TimeoutException') || msg.contains('Connection refused')) {
      throw ServerUnreachableException(msg);
    }
    Error.throwWithStackTrace(e, st);
  }

  Future<T> _get<T>(
    String endpoint,
    T Function(dynamic) fromJson,
  ) async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl$endpoint'), headers: _headers())
          .timeout(_timeout);

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        return fromJson(data);
      } else {
        throw Exception('GET $endpoint failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<T>(e, st);
      }
      rethrow;
    }
  }

  Future<List<T>> _getList<T>(
    String endpoint,
    T Function(Map<String, dynamic>) fromJson,
  ) async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl$endpoint'), headers: _headers())
          .timeout(_timeout);

      if (response.statusCode == 200) {
        final dynamic decoded = json.decode(response.body);
        // 응답이 리스트인 경우와 {data: [...]} 형식 모두 처리한다
        List<dynamic> data;
        if (decoded is List) {
          data = decoded;
        } else if (decoded is Map && decoded['data'] is List) {
          data = decoded['data'] as List;
        } else {
          data = [];
        }
        return data.map((item) => fromJson(item as Map<String, dynamic>)).toList();
      } else {
        throw Exception('GET $endpoint failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<List<T>>(e, st);
      }
      rethrow;
    }
  }

  Future<T> _post<T>(
    String endpoint,
    Map<String, dynamic> body,
    T Function(dynamic) fromJson,
  ) async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl$endpoint'),
            headers: _headers(withJson: true),
            body: json.encode(body),
          )
          .timeout(_timeout);

      if (response.statusCode == 200 || response.statusCode == 201) {
        final data = json.decode(response.body);
        return fromJson(data);
      } else {
        throw Exception('POST $endpoint failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<T>(e, st);
      }
      rethrow;
    }
  }

  Future<void> _postVoid(
    String endpoint,
    Map<String, dynamic> body,
  ) async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl$endpoint'),
            headers: _headers(withJson: true),
            body: json.encode(body),
          )
          .timeout(_timeout);

      if (response.statusCode != 200 && response.statusCode != 201) {
        throw Exception('POST $endpoint failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<void>(e, st);
      }
      rethrow;
    }
  }

  Future<void> _putVoid(
    String endpoint,
    Map<String, dynamic> body,
  ) async {
    try {
      final response = await http
          .put(
            Uri.parse('$baseUrl$endpoint'),
            headers: _headers(withJson: true),
            body: json.encode(body),
          )
          .timeout(_timeout);

      if (response.statusCode != 200) {
        throw Exception('PUT $endpoint failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<void>(e, st);
      }
      rethrow;
    }
  }

  Future<void> _delete(String endpoint) async {
    try {
      final response = await http
          .delete(Uri.parse('$baseUrl$endpoint'), headers: _headers())
          .timeout(_timeout);

      if (response.statusCode != 200 && response.statusCode != 204) {
        throw Exception('DELETE $endpoint failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<void>(e, st);
      }
      rethrow;
    }
  }

  // ── Dashboard endpoints ──

  Future<DashboardSummary> getDashboardSummary({String? mode}) async {
    try {
      final query = mode != null ? '?mode=$mode' : '';
      return await _get('/dashboard/summary$query', (data) => DashboardSummary.fromJson(data));
    } on ServerUnreachableException {
      rethrow;
    } catch (e) {
      debugPrint('getDashboardSummary error: $e');
      return DashboardSummary.fromJson({});
    }
  }

  /// 모의투자와 실전투자 두 계좌의 요약 정보를 동시에 반환한다.
  Future<Map<String, dynamic>> getAccountsSummary() async {
    try {
      return await _get('/dashboard/accounts', (data) => data as Map<String, dynamic>);
    } catch (e) {
      debugPrint('getAccountsSummary error: $e');
      return {};
    }
  }

  Future<SystemStatus> getSystemStatus() async {
    try {
      return await _get('/system/status', (data) => SystemStatus.fromJson(data));
    } on ServerUnreachableException {
      // 서버 미연결은 상위로 전파하여 Provider가 연결 상태를 구분할 수 있게 한다
      rethrow;
    } catch (e) {
      debugPrint('getSystemStatus error: $e');
      return SystemStatus.fromJson({});
    }
  }

  Future<Map<String, dynamic>> getSystemUsage() async {
    try {
      return await _get('/system/usage', (data) => data as Map<String, dynamic>);
    } catch (e) {
      debugPrint('getSystemUsage error: $e');
      return {};
    }
  }

  // ── Chart endpoints ──

  Future<List<DailyReturn>> getDailyReturns({int days = 30}) async {
    try {
      return await _getList(
        '/dashboard/charts/daily-returns?days=$days',
        DailyReturn.fromJson,
      );
    } catch (e) {
      debugPrint('getDailyReturns error: $e');
      return [];
    }
  }

  Future<List<CumulativeReturn>> getCumulativeReturns() async {
    try {
      return await _getList(
        '/dashboard/charts/cumulative',
        CumulativeReturn.fromJson,
      );
    } catch (e) {
      debugPrint('getCumulativeReturns error: $e');
      return [];
    }
  }

  Future<List<HeatmapPoint>> getTickerHeatmap({int days = 30}) async {
    try {
      return await _getList(
        '/dashboard/charts/heatmap/ticker?days=$days',
        HeatmapPoint.fromJson,
      );
    } catch (e) {
      debugPrint('getTickerHeatmap error: $e');
      return [];
    }
  }

  Future<List<HeatmapPoint>> getHourlyHeatmap() async {
    try {
      return await _getList(
        '/dashboard/charts/heatmap/hourly',
        HeatmapPoint.fromJson,
      );
    } catch (e) {
      debugPrint('getHourlyHeatmap error: $e');
      return [];
    }
  }

  Future<List<DrawdownPoint>> getDrawdown() async {
    try {
      return await _getList(
        '/dashboard/charts/drawdown',
        DrawdownPoint.fromJson,
      );
    } catch (e) {
      debugPrint('getDrawdown error: $e');
      return [];
    }
  }

  // ── Indicator endpoints ──

  Future<IndicatorWeights> getIndicatorWeights() async {
    try {
      return await _get('/indicators/weights', (data) => IndicatorWeights.fromJson(data));
    } catch (e) {
      debugPrint('getIndicatorWeights error: $e');
      return IndicatorWeights.fromJson({});
    }
  }

  Future<void> updateIndicatorWeights(Map<String, double> weights) async {
    await _postVoid('/indicators/weights', {'weights': weights});
  }

  Future<RealtimeIndicator> getRealtimeIndicator(String ticker) async {
    try {
      return await _get(
        '/indicators/realtime/$ticker',
        (data) => RealtimeIndicator.fromJson(data),
      );
    } catch (e) {
      debugPrint('getRealtimeIndicator error: $e');
      rethrow;
    }
  }

  // ── Strategy endpoints ──

  Future<StrategyParams> getStrategyParams() async {
    try {
      return await _get('/strategy/params', (data) => StrategyParams.fromJson(data));
    } catch (e) {
      debugPrint('getStrategyParams error: $e');
      return StrategyParams.fromJson({});
    }
  }

  Future<void> updateStrategyParams(Map<String, dynamic> params) async {
    await _postVoid('/strategy/params', {'params': params});
  }

  // ── Feedback / Report endpoints ──

  Future<FeedbackReport> getDailyReport(String date) async {
    try {
      return await _get('/feedback/daily/$date', (data) => FeedbackReport.fromJson(data));
    } catch (e) {
      debugPrint('getDailyReport error: $e');
      return FeedbackReport.fromJson({});
    }
  }

  Future<FeedbackReport> getWeeklyReport(String week) async {
    try {
      return await _get('/feedback/weekly/$week', (data) => FeedbackReport.fromJson(data));
    } catch (e) {
      debugPrint('getWeeklyReport error: $e');
      return FeedbackReport.fromJson({});
    }
  }

  Future<List<PendingAdjustment>> getPendingAdjustments() async {
    try {
      return await _getList('/feedback/pending-adjustments', PendingAdjustment.fromJson);
    } catch (e) {
      debugPrint('getPendingAdjustments error: $e');
      return [];
    }
  }

  // 백엔드 PendingAdjustment.id는 UUID String이다.
  Future<void> approveAdjustment(String id) async {
    await _postVoid('/feedback/approve-adjustment/$id', {});
  }

  Future<void> rejectAdjustment(String id) async {
    await _postVoid('/feedback/reject-adjustment/$id', {});
  }

  // 일간 리포트 목록
  // 주의: /reports/daily 는 단건 dict를 반환하므로 목록 조회에는 /reports/daily/list를 사용한다.
  // getReportDates()가 이미 /reports/daily/list 를 호출하므로 이 메서드는 해당 경로를 사용한다.
  Future<List<Map<String, dynamic>>> getReportsList() async {
    try {
      return await _get('/reports/daily/list', (data) {
        final raw = data as Map<String, dynamic>;
        final dates = raw['dates'] as List? ?? [];
        return dates.map((e) => Map<String, dynamic>.from(e as Map)).toList();
      });
    } catch (e) {
      debugPrint('getReportsList error: $e');
      return [];
    }
  }

  // ── Universe endpoints ──

  Future<List<UniverseTicker>> getUniverse() async {
    try {
      return await _getList('/universe', UniverseTicker.fromJson);
    } catch (e) {
      debugPrint('getUniverse error: $e');
      return [];
    }
  }

  Future<void> addTicker(UniverseTicker ticker) async {
    await _postVoid('/universe/add', ticker.toJson());
  }

  Future<void> toggleTicker(String ticker, bool enabled) async {
    await _postVoid('/universe/toggle', {'ticker': ticker, 'enabled': enabled});
  }

  Future<void> deleteTicker(String ticker) async {
    await _delete('/universe/$ticker');
  }

  // ── Crawl endpoints ──

  Future<CrawlStatus> startManualCrawl() async {
    return _post('/crawl/manual', {}, (data) => CrawlStatus.fromJson(data));
  }

  Future<CrawlStatus> getCrawlStatus(String taskId) async {
    return _get('/crawl/status/$taskId', (data) => CrawlStatus.fromJson(data));
  }

  // ── Alert endpoints ──

  Future<List<AlertNotification>> getAlerts({
    int limit = 50,
    String? alertType,
    String? severity,
  }) async {
    try {
      String query = 'limit=$limit';
      if (alertType != null) query += '&alert_type=$alertType';
      if (severity != null) query += '&severity=$severity';

      return await _getList('/alerts?$query', AlertNotification.fromJson);
    } catch (e) {
      debugPrint('getAlerts error: $e');
      return [];
    }
  }

  Future<int> getUnreadCount() async {
    try {
      return await _get('/alerts/unread-count', (data) {
        // 'count' 또는 'unread_count' 필드 모두 허용한다
        final count = data['unread_count'] ?? data['count'];
        return (count as num? ?? 0).toInt();
      });
    } catch (e) {
      debugPrint('getUnreadCount error: $e');
      return 0;
    }
  }

  Future<void> markAlertAsRead(String id) async {
    await _postVoid('/alerts/$id/read', {});
  }

  // ── Profit Target endpoints (수정된 라우트) ──

  Future<ProfitTargetStatus> getProfitTargetStatus() async {
    try {
      return await _get(
        '/api/target/current',
        (data) => ProfitTargetStatus.fromJson(data),
      );
    } catch (e) {
      debugPrint('getProfitTargetStatus error: $e');
      return ProfitTargetStatus.fromJson({});
    }
  }

  Future<List<MonthlyHistory>> getProfitTargetHistory({int months = 6}) async {
    try {
      return await _getList(
        '/api/target/history?months=$months',
        MonthlyHistory.fromJson,
      );
    } catch (e) {
      debugPrint('getProfitTargetHistory error: $e');
      return [];
    }
  }

  Future<ProfitTargetProjection> getProfitTargetProjection() async {
    try {
      return await _get(
        '/api/target/projection',
        (data) => ProfitTargetProjection.fromJson(data),
      );
    } catch (e) {
      debugPrint('getProfitTargetProjection error: $e');
      return ProfitTargetProjection.fromJson({});
    }
  }

  Future<void> setAggressionLevel(String level) async {
    // 백엔드는 'aggression_level' 키를 기대한다
    await _putVoid('/api/target/aggression', {'aggression_level': level});
  }

  Future<void> setMonthlyTarget(double monthlyTargetUsd) async {
    // 백엔드는 'monthly_target_usd' 키를 기대한다 (USD 금액, 퍼센트 아님)
    await _putVoid('/api/target/monthly', {'monthly_target_usd': monthlyTargetUsd});
  }

  // ── Risk Dashboard endpoints (수정된 라우트) ──

  Future<RiskDashboardData> getRiskDashboard() async {
    try {
      return await _get(
        '/api/risk/dashboard',
        (data) => RiskDashboardData.fromJson(data),
      );
    } catch (e) {
      debugPrint('getRiskDashboard error: $e');
      return RiskDashboardData.fromJson({});
    }
  }

  // ── Tax endpoints ──

  Future<TaxStatus> getTaxStatus() async {
    try {
      return await _get('/tax/status', (data) => TaxStatus.fromJson(data));
    } catch (e) {
      debugPrint('getTaxStatus error: $e');
      return TaxStatus.fromJson({});
    }
  }

  Future<Map<String, dynamic>> getTaxReport(int year) async {
    try {
      return await _get('/tax/report/$year', (data) => data as Map<String, dynamic>);
    } catch (e) {
      debugPrint('getTaxReport error: $e');
      return {};
    }
  }

  Future<List<TaxHarvestSuggestion>> getTaxHarvestSuggestions() async {
    try {
      return await _getList('/tax/harvest-suggestions', TaxHarvestSuggestion.fromJson);
    } catch (e) {
      debugPrint('getTaxHarvestSuggestions error: $e');
      return [];
    }
  }

  // ── FX endpoints ──

  Future<FxStatus> getFxStatus() async {
    try {
      return await _get('/fx/status', (data) => FxStatus.fromJson(data));
    } catch (e) {
      debugPrint('getFxStatus error: $e');
      return FxStatus.fromJson({});
    }
  }

  Future<List<FxHistoryPoint>> getFxHistory() async {
    try {
      return await _getList('/fx/history', FxHistoryPoint.fromJson);
    } catch (e) {
      debugPrint('getFxHistory error: $e');
      return [];
    }
  }

  // ── Emergency endpoints ──

  Future<EmergencyStatus> getEmergencyStatus() async {
    try {
      return await _get('/emergency/status', (data) => EmergencyStatus.fromJson(data));
    } catch (e) {
      debugPrint('getEmergencyStatus error: $e');
      return EmergencyStatus.fromJson({});
    }
  }

  Future<void> triggerEmergencyStop({String reason = 'Manual'}) async {
    await _postVoid('/emergency/stop', {'reason': reason});
  }

  Future<void> resumeTrading() async {
    await _postVoid('/emergency/resume', {});
  }

  // ── Slippage endpoints ──

  Future<SlippageStats> getSlippageStats() async {
    try {
      return await _get('/slippage/stats', (data) => SlippageStats.fromJson(data));
    } catch (e) {
      debugPrint('getSlippageStats error: $e');
      return SlippageStats.fromJson({});
    }
  }

  Future<List<OptimalHour>> getOptimalHours(String ticker) async {
    try {
      // 백엔드는 {"ticker": ..., "optimal_hours": [...], "data_points": N} 형태로 반환한다.
      // _getList가 아닌 _get으로 호출하여 optimal_hours 배열을 추출한다.
      return await _get(
        '/slippage/optimal-hours?ticker=$ticker',
        (data) {
          List<dynamic> hours;
          if (data is List) {
            hours = data;
          } else if (data is Map) {
            hours = (data['optimal_hours'] as List?) ?? [];
          } else {
            hours = [];
          }
          return hours
              .map((item) => OptimalHour.fromJson(item as Map<String, dynamic>))
              .toList();
        },
      );
    } catch (e) {
      debugPrint('getOptimalHours error: $e');
      return [];
    }
  }

  // ── Benchmark endpoints ──

  Future<BenchmarkComparison> getBenchmarkComparison() async {
    try {
      return await _get('/benchmark/comparison', (data) => BenchmarkComparison.fromJson(data));
    } catch (e) {
      debugPrint('getBenchmarkComparison error: $e');
      return BenchmarkComparison.fromJson({});
    }
  }

  Future<List<BenchmarkChartPoint>> getBenchmarkChart() async {
    try {
      return await _getList('/benchmark/chart', BenchmarkChartPoint.fromJson);
    } catch (e) {
      debugPrint('getBenchmarkChart error: $e');
      return [];
    }
  }

  // ── Positions endpoints ──

  /// 현재 모드(virtual/real)의 보유 포지션 목록을 반환한다.
  /// 백엔드 응답: [{"ticker": ..., "quantity": ..., "avg_price": ...,
  ///   "current_price": ..., "pnl_pct": ..., "pnl_amount": ...,
  ///   "current_value": ..., "name": ..., "exchange": ...}, ...]
  Future<List<Map<String, dynamic>>> getPositions({String? mode}) async {
    try {
      final query = mode != null ? '?mode=$mode' : '';
      return await _getList(
        '/dashboard/positions$query',
        (data) => Map<String, dynamic>.from(data),
      );
    } catch (e) {
      debugPrint('getPositions error: $e');
      return [];
    }
  }

  // 주의: 백엔드 /dashboard/trades/recent는 mode 파라미터를 지원하지 않는다.
  // 현재 limit만 허용된다. mode는 무시된다.
  Future<List<dynamic>> getRecentTrades({int limit = 10, String? mode}) async {
    try {
      // mode 파라미터는 백엔드가 지원하지 않으므로 limit만 전송한다.
      final query = 'limit=$limit';
      return await _getList('/dashboard/trades/recent?$query', (data) => data);
    } catch (e) {
      debugPrint('getRecentTrades error: $e');
      return [];
    }
  }

  // ── Macro / Economic indicator endpoints ──

  Future<MacroIndicators> getMacroIndicators() async {
    try {
      return await _get('/api/macro/indicators',
          (data) => MacroIndicators.fromJson(data as Map<String, dynamic>));
    } catch (e) {
      debugPrint('getMacroIndicators error: $e');
      return MacroIndicators.fromJson({});
    }
  }

  Future<FredHistoryData> getFredHistory(String seriesId,
      {int days = 90}) async {
    try {
      return await _get('/api/macro/history/$seriesId?days=$days',
          (data) => FredHistoryData.fromJson(data as Map<String, dynamic>));
    } catch (e) {
      debugPrint('getFredHistory error: $e');
      return FredHistoryData.fromJson({});
    }
  }

  Future<List<EconomicEvent>> getEconomicCalendar() async {
    try {
      return await _get('/api/macro/calendar', (data) {
        final events =
            (data as Map<String, dynamic>)['events'] as List? ?? [];
        return events
            .map((e) => EconomicEvent.fromJson(e as Map<String, dynamic>))
            .toList();
      });
    } catch (e) {
      debugPrint('getEconomicCalendar error: $e');
      return [];
    }
  }

  Future<RateOutlook> getRateOutlook() async {
    try {
      return await _get('/api/macro/rate-outlook',
          (data) => RateOutlook.fromJson(data as Map<String, dynamic>));
    } catch (e) {
      debugPrint('getRateOutlook error: $e');
      return RateOutlook.fromJson({});
    }
  }

  // ── RSI endpoints ──

  /// Triple RSI 지표 데이터를 가져온다.
  Future<TripleRsiData> getTripleRsi(String ticker, {int days = 100}) async {
    try {
      return await _get(
        '/api/indicators/rsi/$ticker?days=$days',
        (data) => TripleRsiData.fromJson(data as Map<String, dynamic>),
      );
    } catch (e) {
      debugPrint('getTripleRsi error: $e');
      return TripleRsiData.fromJson({});
    }
  }

  // ── Daily Reports endpoints ──

  /// 사용 가능한 리포트 날짜 목록을 가져온다.
  Future<List<ReportDate>> getReportDates({int limit = 30}) async {
    try {
      return await _get('/reports/daily/list?limit=$limit', (data) {
        final raw = data as Map<String, dynamic>;
        final dates = raw['dates'] as List? ?? [];
        return dates
            .map((e) => ReportDate.fromJson(e as Map<String, dynamic>))
            .toList();
      });
    } catch (e) {
      debugPrint('getReportDates error: $e');
      return [];
    }
  }

  /// 특정 날짜의 일간 거래 리포트를 가져온다.
  Future<DailyReport> getDailyTradingReport(String date) async {
    try {
      return await _get(
        '/reports/daily?date=$date',
        (data) => DailyReport.fromJson(data as Map<String, dynamic>),
      );
    } catch (e) {
      debugPrint('getDailyTradingReport error: $e');
      rethrow;
    }
  }

  // ── Universe (Extended) endpoints ──

  /// 유니버스 종목 목록을 UniverseTickerEx 형태로 가져온다.
  Future<List<UniverseTickerEx>> getUniverseEx() async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/universe'), headers: _headers())
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final dynamic decoded = json.decode(response.body);
        List<dynamic> data;
        if (decoded is List) {
          data = decoded;
        } else if (decoded is Map && decoded['data'] is List) {
          data = decoded['data'] as List;
        } else {
          data = [];
        }
        return data
            .map((item) =>
                UniverseTickerEx.fromJson(item as Map<String, dynamic>))
            .toList();
      } else {
        debugPrint('getUniverseEx error: ${response.statusCode}');
        return [];
      }
    } catch (e) {
      debugPrint('getUniverseEx error: $e');
      return [];
    }
  }

  /// 유니버스 매핑 목록을 가져온다.
  Future<List<TickerMapping>> getUniverseMappings() async {
    try {
      return await _get('/universe/mappings', (data) {
        List<dynamic> mappings;
        if (data is List) {
          mappings = data;
        } else if (data is Map) {
          mappings = (data['mappings'] as List?) ?? [];
        } else {
          mappings = [];
        }
        return mappings
            .map((e) => TickerMapping.fromJson(e as Map<String, dynamic>))
            .toList();
      });
    } catch (e) {
      debugPrint('getUniverseMappings error: $e');
      return [];
    }
  }

  /// 종목 활성/비활성 상태를 토글한다.
  Future<void> toggleUniverseTicker(String ticker, bool enabled) async {
    await _postVoid('/universe/toggle', {'ticker': ticker, 'enabled': enabled});
  }

  /// 새 종목을 유니버스에 추가한다.
  Future<void> addUniverseTicker(Map<String, dynamic> data) async {
    await _postVoid('/universe/add', data);
  }

  /// 종목을 유니버스에서 삭제한다.
  Future<void> removeUniverseTicker(String ticker) async {
    await _delete('/universe/$ticker');
  }

  /// 유니버스 매핑을 추가한다.
  Future<void> addUniverseMapping(
      String underlying, String? bull2x, String? bear2x) async {
    await _postVoid('/universe/mappings/add', {
      'underlying': underlying,
      'bull_2x': bull2x,
      'bear_2x': bear2x,
    });
  }

  /// 유니버스 매핑을 삭제한다.
  Future<void> removeUniverseMapping(String underlying) async {
    await _delete('/universe/mappings/$underlying');
  }

  /// 종목 코드만 입력하면 Claude가 종목 정보를 자동으로 조회하여 추가한다.
  Future<Map<String, dynamic>> autoAddTicker(String ticker) async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl/universe/auto-add'),
            headers: _headers(withJson: true),
            body: json.encode({'ticker': ticker}),
          )
          .timeout(const Duration(seconds: 60));
      if (response.statusCode == 200 || response.statusCode == 201) {
        final dynamic data = json.decode(response.body);
        if (data is Map<String, dynamic>) return data;
        return {};
      } else {
        final dynamic body = json.decode(response.body);
        final String detail = (body is Map ? body['detail'] ?? body['message'] : null) ?? response.statusCode.toString();
        throw Exception(detail);
      }
    } catch (e) {
      debugPrint('autoAddTicker error: $e');
      rethrow;
    }
  }

  /// 유니버스 섹터 목록을 가져온다.
  /// 백엔드 GET /universe/sectors 엔드포인트를 호출한다.
  Future<Map<String, dynamic>> fetchSectors() async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/universe/sectors'), headers: _headers())
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final dynamic decoded = json.decode(response.body);
        if (decoded is Map<String, dynamic>) return decoded;
        return {};
      } else {
        debugPrint('fetchSectors error: ${response.statusCode}');
        return {};
      }
    } catch (e) {
      debugPrint('fetchSectors error: $e');
      return {};
    }
  }

  /// 인디케이터 설정을 업데이트한다.
  Future<void> updateIndicatorConfig(Map<String, dynamic> config) async {
    await _putVoid('/api/indicators/config', config);
  }

  // ── News endpoints ──

  /// 뉴스 날짜 목록을 가져온다.
  Future<List<NewsDate>> getNewsDates({int limit = 30}) async {
    try {
      return await _get('/api/news/dates?limit=$limit', (data) {
        final raw = data as Map<String, dynamic>;
        final dates = raw['dates'] as List? ?? [];
        return dates
            .map((e) => NewsDate.fromJson(e as Map<String, dynamic>))
            .toList();
      });
    } catch (e) {
      debugPrint('getNewsDates error: $e');
      return [];
    }
  }

  /// 특정 날짜의 뉴스 기사 목록을 가져온다.
  Future<Map<String, dynamic>> getDailyNews(
    String date, {
    String? category,
    String? impact,
    int limit = 50,
    int offset = 0,
  }) async {
    try {
      String query = 'date=$date&limit=$limit&offset=$offset';
      if (category != null && category.isNotEmpty) query += '&category=$category';
      if (impact != null && impact.isNotEmpty) query += '&impact=$impact';

      return await _get('/api/news/daily?$query', (data) => data as Map<String, dynamic>);
    } catch (e) {
      debugPrint('getDailyNews error: $e');
      return {};
    }
  }

  /// 뉴스 기사 상세 내용을 가져온다.
  Future<NewsArticle> getArticleDetail(String id) async {
    try {
      return await _get('/api/news/$id', (data) => NewsArticle.fromJson(data as Map<String, dynamic>));
    } catch (e) {
      debugPrint('getArticleDetail error: $e');
      rethrow;
    }
  }

  /// 뉴스 요약을 가져온다.
  Future<NewsSummary> getNewsSummary({String? date}) async {
    try {
      final query = date != null ? '?date=$date' : '';
      return await _get('/api/news/summary$query',
          (data) => NewsSummary.fromJson(data as Map<String, dynamic>));
    } catch (e) {
      debugPrint('getNewsSummary error: $e');
      return NewsSummary.fromJson({});
    }
  }

  // ── Principles endpoints ──

  /// 매매 원칙 전체 데이터를 가져온다.
  Future<TradingPrinciples> getPrinciples() async {
    try {
      return await _get(
        '/api/principles',
        (data) => TradingPrinciples.fromJson(data as Map<String, dynamic>),
      );
    } catch (e) {
      debugPrint('getPrinciples error: $e');
      return TradingPrinciples.fromJson({});
    }
  }

  /// 새 매매 원칙을 추가한다.
  Future<TradingPrinciple> addPrinciple(
      String category, String title, String content) async {
    return _post(
      '/api/principles',
      {'category': category, 'title': title, 'content': content},
      (data) => TradingPrinciple.fromJson(data as Map<String, dynamic>),
    );
  }

  /// 기존 매매 원칙을 수정한다.
  Future<TradingPrinciple> updatePrinciple(
      String id, Map<String, dynamic> updates) async {
    final response = await http.put(
      Uri.parse('$baseUrl/api/principles/$id'),
      headers: _headers(withJson: true),
      body: json.encode(updates),
    ).timeout(_timeout);
    if (response.statusCode != 200) {
      throw Exception('PUT /api/principles/$id failed: ${response.statusCode}');
    }
    return TradingPrinciple.fromJson(
        json.decode(response.body) as Map<String, dynamic>);
  }

  /// 매매 원칙을 삭제한다.
  Future<void> deletePrinciple(String id) async {
    await _delete('/api/principles/$id');
  }

  /// 핵심 원칙(슬로건)을 수정한다.
  Future<void> updateCorePrinciple(String text) async {
    await _putVoid('/api/principles/core', {'core_principle': text});
  }

  // ── Trade Reasoning endpoints ──

  /// 매매 근거 날짜 목록을 가져온다.
  /// 백엔드는 {"dates": [...], "total_days": N} 형태로 반환한다.
  Future<List<dynamic>> getTradeReasoningDates() async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/api/trade-reasoning/dates'),
              headers: _headers())
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final dynamic decoded = json.decode(response.body);
        if (decoded is Map) {
          // 백엔드 실제 응답: {"dates": [...], "total_days": N}
          return (decoded['dates'] as List?) ?? [];
        }
        if (decoded is List) return decoded;
        return [];
      } else if (response.statusCode == 404) {
        debugPrint('getTradeReasoningDates: 404 Not Found');
        return [];
      } else {
        debugPrint('getTradeReasoningDates error: ${response.statusCode}');
        return [];
      }
    } catch (e) {
      debugPrint('getTradeReasoningDates error: $e');
      return [];
    }
  }

  /// 특정 날짜의 매매 근거 목록을 가져온다.
  /// 백엔드는 {"date": "...", "trades": [...], "total_count": N} 형태로 반환한다.
  Future<List<dynamic>> getTradeReasoningDaily(String date) async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/api/trade-reasoning/daily?date=$date'),
              headers: _headers())
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final dynamic decoded = json.decode(response.body);
        if (decoded is Map) {
          // 백엔드 실제 응답: {"date": "...", "trades": [...], "total_count": N}
          return (decoded['trades'] as List?) ?? [];
        }
        if (decoded is List) return decoded;
        return [];
      } else if (response.statusCode == 404) {
        debugPrint('getTradeReasoningDaily: 404 Not Found for date=$date');
        return [];
      } else {
        debugPrint('getTradeReasoningDaily error: ${response.statusCode}');
        return [];
      }
    } catch (e) {
      debugPrint('getTradeReasoningDaily error: $e');
      return [];
    }
  }

  /// 특정 날짜의 매매 통계 요약을 가져온다.
  Future<Map<String, dynamic>> getTradeReasoningStats(String date) async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/api/trade-reasoning/stats?date=$date'),
              headers: _headers())
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final dynamic decoded = json.decode(response.body);
        if (decoded is Map<String, dynamic>) return decoded;
        return {};
      } else if (response.statusCode == 404) {
        debugPrint('getTradeReasoningStats: 404 Not Found for date=$date');
        return {};
      } else {
        debugPrint('getTradeReasoningStats error: ${response.statusCode}');
        return {};
      }
    } catch (e) {
      debugPrint('getTradeReasoningStats error: $e');
      return {};
    }
  }

  /// 매매 근거에 피드백을 제출한다.
  Future<Map<String, dynamic>> submitTradeReasoningFeedback(
      String tradeId, Map<String, dynamic> body) async {
    try {
      final response = await http
          .put(
            Uri.parse('$baseUrl/api/trade-reasoning/$tradeId/feedback'),
            headers: _headers(withJson: true),
            body: json.encode(body),
          )
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final dynamic decoded = json.decode(response.body);
        if (decoded is Map<String, dynamic>) return decoded;
        return {};
      } else {
        throw Exception(
            'PUT /api/trade-reasoning/$tradeId/feedback failed: ${response.statusCode}');
      }
    } catch (e) {
      debugPrint('submitTradeReasoningFeedback error: $e');
      rethrow;
    }
  }

  // ── Stock Analysis endpoints ──

  /// 분석 가능한 종목 목록을 정렬된 순서로 가져온다.
  Future<List<String>> getAnalysisTickers() async {
    try {
      return await _get('/api/analysis/tickers', (json) {
        final list = json['tickers'] as List<dynamic>?;
        return list?.map((e) => e.toString()).toList() ?? <String>[];
      });
    } catch (e) {
      debugPrint('getAnalysisTickers error: $e');
      return <String>[];
    }
  }

  /// 종합 종목 분석 데이터를 가져온다.
  /// Claude Opus 호출로 최대 120초가 소요될 수 있다.
  /// 504/404 등 에러 발생 시 예외를 그대로 전파하여 UI가 에러 상태를 표시하게 한다.
  Future<StockAnalysisData> getStockAnalysis(String ticker,
      {bool ai = true}) async {
    try {
      final query = ai ? '' : '?ai=false';
      final response = await http
          .get(Uri.parse('$baseUrl/api/analysis/comprehensive/$ticker$query'),
              headers: _headers())
          .timeout(ApiConstants.longTimeout);
      if (response.statusCode == 200) {
        return StockAnalysisData.fromJson(
            json.decode(response.body) as Map<String, dynamic>);
      } else if (response.statusCode == 404) {
        throw Exception('분석 데이터를 찾을 수 없습니다 ($ticker): 404 Not Found');
      } else if (response.statusCode == 504) {
        throw Exception('분석 서버 응답 시간 초과 ($ticker): 504 Gateway Timeout');
      } else {
        throw Exception(
            'GET /api/analysis/comprehensive/$ticker failed: ${response.statusCode}');
      }
    } on ServerUnreachableException {
      rethrow;
    } on Exception {
      rethrow;
    } catch (e, st) {
      _wrapNetworkError<StockAnalysisData>(e, st);
      throw Exception('getStockAnalysis ($ticker) error: $e');
    }
  }

  /// 종목 관련 뉴스를 가져온다.
  Future<List<AnalysisNews>> getTickerNews(String ticker,
      {int limit = 20}) async {
    try {
      return await _get('/api/analysis/ticker-news/$ticker?limit=$limit', (data) {
        final raw = data as Map<String, dynamic>;
        final articles = raw['articles'] as List? ?? [];
        return articles
            .map((e) => AnalysisNews.fromJson(e as Map<String, dynamic>))
            .toList();
      });
    } catch (e) {
      debugPrint('getTickerNews error: $e');
      return [];
    }
  }

  // ── Trading Control endpoints ──

  /// 자동매매 실행 상태를 조회한다.
  /// 백엔드 응답: {"is_trading": bool, "running": bool, "task_done": bool}
  /// 서버 미연결 시 ServerUnreachableException을 전파하여 Provider가 연결 상태를
  /// 구분할 수 있게 한다.
  Future<Map<String, dynamic>> getTradingStatus() async {
    try {
      return await _get(
        '/api/trading/status',
        (data) => Map<String, dynamic>.from(data as Map),
      );
    } on ServerUnreachableException {
      rethrow;
    } catch (e) {
      debugPrint('getTradingStatus error: $e');
      return {'is_trading': false, 'running': false};
    }
  }

  /// 자동매매를 시작한다.
  /// 백엔드 응답: {"status": "started" | "already_running"}
  /// apiKey가 설정된 경우 X-API-Key 헤더를 함께 전송하여 인증한다.
  Future<Map<String, dynamic>> startTrading() async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl/api/trading/start'),
            headers: _headers(withJson: true),
            body: json.encode({}),
          )
          .timeout(_timeout);
      if (response.statusCode == 200) {
        return Map<String, dynamic>.from(json.decode(response.body) as Map);
      } else if (response.statusCode == 401) {
        throw Exception('자동매매 시작 인증 실패: API 키가 올바르지 않습니다 (401)');
      } else {
        throw Exception('POST /api/trading/start failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<Map<String, dynamic>>(e, st);
      }
      rethrow;
    }
  }

  /// 자동매매를 중지한다.
  /// [runEod]가 true(기본값)이면 백엔드가 EOD 시퀀스를 실행한 뒤 종료한다.
  /// EOD 시퀀스에는 시간이 소요되므로 타임아웃을 120초로 설정한다.
  /// 백엔드 응답: {"status": "stopped" | "not_running"}
  /// apiKey가 설정된 경우 X-API-Key 헤더를 함께 전송하여 인증한다.
  Future<Map<String, dynamic>> stopTrading({bool runEod = true}) async {
    try {
      final query = runEod ? '' : '?run_eod=false';
      final response = await http
          .post(
            Uri.parse('$baseUrl/api/trading/stop$query'),
            headers: _headers(withJson: true),
            body: json.encode({}),
          )
          .timeout(ApiConstants.longTimeout);
      if (response.statusCode == 200) {
        return Map<String, dynamic>.from(json.decode(response.body) as Map);
      } else if (response.statusCode == 401) {
        throw Exception('자동매매 중지 인증 실패: API 키가 올바르지 않습니다 (401)');
      } else {
        throw Exception('POST /api/trading/stop failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<Map<String, dynamic>>(e, st);
      }
      rethrow;
    }
  }

  // ── News Collect & Send ──

  /// 뉴스 수집 -> 분류 -> 번역 -> 텔레그램 전송 파이프라인을 실행한다.
  /// 크롤링 + AI 분류에 시간이 소요되므로 타임아웃을 120초로 설정한다.
  /// 백엔드 응답: {"status": "sent" | "sent_no_key_news", "news_count": N,
  ///              "key_news_count": M, "crawl_saved": K, "telegram_sent": bool}
  Future<Map<String, dynamic>> collectAndSendNews() async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl/api/news/collect-and-send'),
            headers: _headers(withJson: true),
            body: json.encode({}),
          )
          .timeout(ApiConstants.longTimeout);
      if (response.statusCode == 200) {
        return Map<String, dynamic>.from(json.decode(response.body) as Map);
      } else if (response.statusCode == 401) {
        throw Exception('뉴스 수집 인증 실패: API 키가 올바르지 않습니다 (401)');
      } else {
        final dynamic body = json.decode(response.body);
        final String detail = (body is Map ? body['detail'] ?? '' : '') as String;
        throw Exception('뉴스 수집 실패: ${response.statusCode} $detail');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<Map<String, dynamic>>(e, st);
      }
      rethrow;
    }
  }

  // ── Health check ──

  Future<bool> checkHealth() async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/health'))
          .timeout(_timeout);
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  // ── Agent endpoints ──

  /// 에이전트 팀 목록을 가져온다.
  /// 백엔드는 {"teams": [...]} 형태로 반환한다.
  Future<List<AgentTeam>> getAgentList() async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/agents/list'), headers: _headers())
          .timeout(_timeout);

      if (response.statusCode == 200) {
        final dynamic decoded = json.decode(response.body);
        List<dynamic> data;
        if (decoded is List) {
          // 혹시 리스트로 직접 반환되는 경우도 처리한다
          data = decoded;
        } else if (decoded is Map && decoded['teams'] is List) {
          // 백엔드 실제 응답: {"teams": [...]}
          data = decoded['teams'] as List;
        } else if (decoded is Map && decoded['data'] is List) {
          data = decoded['data'] as List;
        } else {
          data = [];
        }
        return data
            .map((item) => AgentTeam.fromJson(item as Map<String, dynamic>))
            .toList();
      } else {
        debugPrint('getAgentList error: ${response.statusCode}');
        return [];
      }
    } catch (e) {
      debugPrint('getAgentList error: $e');
      return [];
    }
  }

  /// 특정 에이전트의 MD 콘텐츠를 가져온다.
  Future<String> getAgentMd(String agentId) async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/agents/$agentId'), headers: _headers())
          .timeout(_timeout);

      if (response.statusCode == 200) {
        final dynamic decoded = json.decode(response.body);
        if (decoded is Map) {
          return decoded['content'] as String? ??
              decoded['md_content'] as String? ??
              '';
        }
        return decoded.toString();
      } else {
        debugPrint('getAgentMd error: ${response.statusCode}');
        return '';
      }
    } catch (e) {
      debugPrint('getAgentMd error: $e');
      return '';
    }
  }

  /// 특정 에이전트의 MD 콘텐츠를 저장한다.
  Future<void> saveAgentMd(String agentId, String content) async {
    try {
      final response = await http
          .put(
            Uri.parse('$baseUrl/agents/$agentId'),
            headers: _headers(withJson: true),
            body: json.encode({'content': content}),
          )
          .timeout(_timeout);

      if (response.statusCode != 200) {
        throw Exception(
            'PUT /agents/$agentId failed: ${response.statusCode}');
      }
    } catch (e) {
      debugPrint('saveAgentMd error: $e');
      rethrow;
    }
  }

  // ── Ticker Params (AI 종목별 전략 파라미터) endpoints ──

  /// 전체 종목 파라미터 요약 목록을 가져온다.
  Future<List<TickerParamsSummary>> getTickerParams() async {
    try {
      return await _getList(
        '/strategy/ticker-params',
        TickerParamsSummary.fromJson,
      );
    } catch (e) {
      debugPrint('getTickerParams error: $e');
      return [];
    }
  }

  /// 단일 종목 상세 파라미터를 가져온다.
  Future<TickerParamsDetail> getTickerParamsDetail(String ticker) async {
    try {
      return await _get(
        '/strategy/ticker-params/$ticker',
        (data) => TickerParamsDetail.fromJson(data as Map<String, dynamic>),
      );
    } catch (e) {
      debugPrint('getTickerParamsDetail error: $e');
      rethrow;
    }
  }

  /// 유저 오버라이드를 설정한다.
  Future<void> setTickerOverride(
      String ticker, Map<String, dynamic> overrides) async {
    await _postVoid('/strategy/ticker-params/$ticker/override', overrides);
  }

  /// 유저 오버라이드를 제거한다.
  /// [paramName]이 주어지면 해당 파라미터만, 없으면 전체를 제거한다.
  Future<void> clearTickerOverride(String ticker, {String? paramName}) async {
    // 백엔드는 쿼리 파라미터 이름으로 param_name을 기대한다.
    final query = paramName != null ? '?param_name=$paramName' : '';
    await _delete('/strategy/ticker-params/$ticker/override$query');
  }

  /// AI 재분석을 트리거한다.
  Future<void> triggerAiOptimization() async {
    await _postVoid('/strategy/ticker-params/ai-optimize', {});
  }
}
