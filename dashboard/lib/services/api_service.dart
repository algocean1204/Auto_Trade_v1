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
import 'server_launcher.dart';

/// 서버에 물리적으로 연결할 수 없을 때 발생하는 예외이다.
/// SocketException, TimeoutException 등 네트워크 레벨 실패를 나타낸다.
class ServerUnreachableException implements Exception {
  final String message;
  const ServerUnreachableException([this.message = 'Server is unreachable']);

  @override
  String toString() => 'ServerUnreachableException: $message';
}

class ApiService {
  String baseUrl;

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
              defaultValue: ServerLauncher.instance.baseUrl,
            ),
        apiKey = apiKey ?? EnvLoader.get('API_SECRET_KEY');

  /// ServerLauncher가 감지한 포트로 baseUrl을 갱신한다.
  void refreshBaseUrl() {
    final detected = ServerLauncher.instance.baseUrl;
    if (detected != baseUrl) {
      baseUrl = detected;
    }
  }

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
        // 응답이 리스트, {data: [...]}, {positions: [...]} 등 다양한 형식을 처리한다
        List<dynamic> data;
        if (decoded is List) {
          data = decoded;
        } else if (decoded is Map) {
          // 맵 응답에서 리스트 값을 찾는다 (data, positions, trades, items 등)
          if (decoded['data'] is List) {
            data = decoded['data'] as List;
          } else if (decoded['positions'] is List) {
            data = decoded['positions'] as List;
          } else if (decoded['trades'] is List) {
            data = decoded['trades'] as List;
          } else if (decoded['items'] is List) {
            data = decoded['items'] as List;
          } else if (decoded['entries'] is List) {
            data = decoded['entries'] as List;
          } else if (decoded['suggestions'] is List) {
            data = decoded['suggestions'] as List;
          } else if (decoded['adjustments'] is List) {
            data = decoded['adjustments'] as List;
          } else if (decoded['universe'] is List) {
            data = decoded['universe'] as List;
          } else if (decoded['alerts'] is List) {
            data = decoded['alerts'] as List;
          } else {
            // 알려진 키가 없으면 첫 번째 List 타입 값을 사용한다
            data = decoded.values
                .whereType<List>()
                .firstOrNull ?? [];
          }
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

  Future<T> _put<T>(
    String endpoint,
    Map<String, dynamic> body,
    T Function(dynamic) fromJson,
  ) async {
    try {
      final response = await http
          .put(
            Uri.parse('$baseUrl$endpoint'),
            headers: _headers(withJson: true),
            body: json.encode(body),
          )
          .timeout(_timeout);

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        return fromJson(data);
      } else {
        throw Exception('PUT $endpoint failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<T>(e, st);
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
      // V2: /api/dashboard/summary
      return await _get('${ApiConstants.dashboardSummary}$query',
          (data) => DashboardSummary.fromJson(data));
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
      // V2: /api/dashboard/accounts
      return await _get(ApiConstants.dashboardAccounts,
          (data) => data as Map<String, dynamic>);
    } catch (e) {
      debugPrint('getAccountsSummary error: $e');
      return {};
    }
  }

  Future<SystemStatus> getSystemStatus() async {
    try {
      // V2: /api/system/status (종합 서비스 상태 -- claude/kis/database/redis)
      return await _get(ApiConstants.systemStatus,
          (data) => SystemStatus.fromJson(data));
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
      // V2: /api/system/info (V1의 /system/usage → V2의 /api/system/info)
      return await _get(ApiConstants.systemInfo,
          (data) => data as Map<String, dynamic>);
    } catch (e) {
      debugPrint('getSystemUsage error: $e');
      return {};
    }
  }

  // ── Chart endpoints ──

  Future<List<DailyReturn>> getDailyReturns({int days = 30}) async {
    try {
      // V2: /api/dashboard/charts/daily-returns
      return await _getList(
        '${ApiConstants.dashboardChartsDaily}?days=$days',
        DailyReturn.fromJson,
      );
    } catch (e) {
      debugPrint('getDailyReturns error: $e');
      return [];
    }
  }

  Future<List<CumulativeReturn>> getCumulativeReturns() async {
    try {
      // V2: /api/dashboard/charts/cumulative
      return await _getList(
        ApiConstants.dashboardChartsCumulative,
        CumulativeReturn.fromJson,
      );
    } catch (e) {
      debugPrint('getCumulativeReturns error: $e');
      return [];
    }
  }

  Future<List<HeatmapPoint>> getTickerHeatmap({int days = 30}) async {
    try {
      // V2: /api/dashboard/charts/heatmap/ticker
      return await _getList(
        '${ApiConstants.dashboardChartsHeatmapTicker}?days=$days',
        HeatmapPoint.fromJson,
      );
    } catch (e) {
      debugPrint('getTickerHeatmap error: $e');
      return [];
    }
  }

  Future<List<HeatmapPoint>> getHourlyHeatmap() async {
    try {
      // V2: /api/dashboard/charts/heatmap/hourly
      return await _getList(
        ApiConstants.dashboardChartsHeatmapHourly,
        HeatmapPoint.fromJson,
      );
    } catch (e) {
      debugPrint('getHourlyHeatmap error: $e');
      return [];
    }
  }

  Future<List<DrawdownPoint>> getDrawdown() async {
    try {
      // V2: /api/dashboard/charts/drawdown
      return await _getList(
        ApiConstants.dashboardChartsDrawdown,
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
      // V2: GET /api/indicators/weights
      return await _get(ApiConstants.indicatorWeights,
          (data) => IndicatorWeights.fromJson(data));
    } catch (e) {
      debugPrint('getIndicatorWeights error: $e');
      return IndicatorWeights.fromJson({});
    }
  }

  /// 인디케이터 가중치를 업데이트한다.
  /// V2: PUT /api/indicators/weights (V1은 POST였으나 V2는 PUT을 사용한다)
  Future<void> updateIndicatorWeights(Map<String, double> weights) async {
    await _putVoid(ApiConstants.indicatorWeights, {'weights': weights});
  }

  Future<RealtimeIndicator> getRealtimeIndicator(String ticker) async {
    try {
      return await _get(
        '/api/indicators/realtime/$ticker',
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
      // V2: GET /api/strategy/params
      return await _get(ApiConstants.strategyParams,
          (data) => StrategyParams.fromJson(data));
    } on ServerUnreachableException {
      rethrow;
    } catch (e) {
      debugPrint('getStrategyParams error: $e');
      return StrategyParams.fromJson({});
    }
  }

  /// 전략 파라미터를 업데이트한다.
  /// V2: PUT /api/strategy/params (V1은 POST였으나 V2는 PUT을 사용한다)
  Future<void> updateStrategyParams(Map<String, dynamic> params) async {
    await _putVoid(ApiConstants.strategyParams, {'params': params});
  }

  // ── Feedback / Report endpoints ──

  Future<FeedbackReport> getDailyReport(String date) async {
    try {
      // V2: /api/feedback/daily/{date}
      return await _get('/api/feedback/daily/$date',
          (data) => FeedbackReport.fromJson(data));
    } catch (e) {
      debugPrint('getDailyReport error: $e');
      return FeedbackReport.fromJson({});
    }
  }

  /// 최신 피드백 리포트를 가져온다.
  /// V2: GET /api/feedback/latest
  Future<FeedbackReport> getLatestFeedback() async {
    try {
      return await _get(ApiConstants.feedbackLatest,
          (data) => FeedbackReport.fromJson(data));
    } catch (e) {
      debugPrint('getLatestFeedback error: $e');
      return FeedbackReport.fromJson({});
    }
  }

  Future<FeedbackReport> getWeeklyReport(String week) async {
    try {
      return await _get('/api/feedback/weekly/$week',
          (data) => FeedbackReport.fromJson(data));
    } catch (e) {
      debugPrint('getWeeklyReport error: $e');
      return FeedbackReport.fromJson({});
    }
  }

  Future<List<PendingAdjustment>> getPendingAdjustments() async {
    try {
      return await _getList(
          '/api/feedback/pending-adjustments', PendingAdjustment.fromJson);
    } catch (e) {
      debugPrint('getPendingAdjustments error: $e');
      return [];
    }
  }

  Future<void> approveAdjustment(String id) async {
    await _postVoid('/api/feedback/approve-adjustment/$id', {});
  }

  Future<void> rejectAdjustment(String id) async {
    await _postVoid('/api/feedback/reject-adjustment/$id', {});
  }

  Future<List<Map<String, dynamic>>> getReportsList() async {
    try {
      return await _get('/api/reports/daily/list', (data) {
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
      // V2: /api/universe
      return await _getList(ApiConstants.universe, UniverseTicker.fromJson);
    } on ServerUnreachableException {
      rethrow;
    } catch (e) {
      debugPrint('getUniverse error: $e');
      return [];
    }
  }

  Future<void> addTicker(UniverseTicker ticker) async {
    // V2: /api/universe/add
    await _postVoid(ApiConstants.universeAdd, ticker.toJson());
  }

  Future<void> toggleTicker(String ticker, bool enabled) async {
    // V2: /api/universe/toggle
    await _postVoid(
        ApiConstants.universeToggle, {'ticker': ticker, 'enabled': enabled});
  }

  Future<void> deleteTicker(String ticker) async {
    // V2: /api/universe/{ticker}
    await _delete('${ApiConstants.universe}/$ticker');
  }

  // ── Crawl endpoints ──

  Future<CrawlStatus> startManualCrawl() async {
    return _post('/api/crawl/manual', {}, (data) => CrawlStatus.fromJson(data));
  }

  Future<CrawlStatus> getCrawlStatus(String taskId) async {
    return _get('/api/crawl/status/$taskId', (data) => CrawlStatus.fromJson(data));
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

      return await _getList('/api/alerts?$query', AlertNotification.fromJson);
    } catch (e) {
      debugPrint('getAlerts error: $e');
      return [];
    }
  }

  Future<int> getUnreadCount() async {
    try {
      return await _get('/api/alerts/unread-count', (data) {
        // 백엔드가 'count' 키로 반환하므로 우선 시도하고, 폴백으로 'unread_count'를 사용한다
        final count = data['count'] ?? data['unread_count'];
        return (count as num? ?? 0).toInt();
      });
    } catch (e) {
      debugPrint('getUnreadCount error: $e');
      return 0;
    }
  }

  Future<void> markAlertAsRead(String id) async {
    await _postVoid('/api/alerts/$id/read', {});
  }

  // ── Profit Target endpoints ──

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
    await _putVoid(
        '/api/target/monthly', {'monthly_target_usd': monthlyTargetUsd});
  }

  // ── Risk Dashboard endpoints ──

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
      return await _get('/api/tax/status', (data) => TaxStatus.fromJson(data));
    } catch (e) {
      debugPrint('getTaxStatus error: $e');
      return TaxStatus.fromJson({});
    }
  }

  Future<Map<String, dynamic>> getTaxReport(int year) async {
    try {
      return await _get(
          '/api/tax/report?year=$year', (data) => data as Map<String, dynamic>);
    } catch (e) {
      debugPrint('getTaxReport error: $e');
      return {};
    }
  }

  Future<List<TaxHarvestSuggestion>> getTaxHarvestSuggestions() async {
    try {
      return await _getList(
          '/api/tax/harvest-suggestions', TaxHarvestSuggestion.fromJson);
    } catch (e) {
      debugPrint('getTaxHarvestSuggestions error: $e');
      return [];
    }
  }

  // ── FX endpoints ──

  Future<FxStatus> getFxStatus() async {
    try {
      return await _get(
          ApiConstants.fxStatus, (data) => FxStatus.fromJson(data));
    } catch (e) {
      debugPrint('getFxStatus error: $e');
      return FxStatus.fromJson({});
    }
  }

  Future<List<FxHistoryPoint>> getFxHistory() async {
    try {
      // 백엔드는 {"entries": [...]} 형식으로 반환한다
      return await _get(ApiConstants.fxHistory, (data) {
        final entries = data['entries'] as List<dynamic>? ?? [];
        return entries
            .map((e) => FxHistoryPoint.fromJson(e as Map<String, dynamic>))
            .toList();
      });
    } catch (e) {
      debugPrint('getFxHistory error: $e');
      return [];
    }
  }

  // ── Emergency endpoints ──

  Future<EmergencyStatus> getEmergencyStatus() async {
    try {
      // V2: /api/emergency/status
      return await _get(ApiConstants.emergencyStatus,
          (data) => EmergencyStatus.fromJson(data));
    } catch (e) {
      debugPrint('getEmergencyStatus error: $e');
      return EmergencyStatus.fromJson({});
    }
  }

  Future<void> triggerEmergencyStop({String reason = 'Manual'}) async {
    // V2: /api/emergency/stop — reason은 쿼리 파라미터로 전달한다
    await _postVoid(
        '${ApiConstants.emergencyStop}?reason=${Uri.encodeComponent(reason)}',
        {});
  }

  Future<void> resumeTrading() async {
    // V2: /api/emergency/resume
    await _postVoid(ApiConstants.emergencyResume, {});
  }

  // ── Slippage endpoints ──

  Future<SlippageStats> getSlippageStats() async {
    try {
      return await _get(
          '/api/slippage/stats', (data) => SlippageStats.fromJson(data));
    } catch (e) {
      debugPrint('getSlippageStats error: $e');
      return SlippageStats.fromJson({});
    }
  }

  Future<List<OptimalHour>> getOptimalHours(String ticker) async {
    try {
      // 백엔드는 {"ticker": ..., "hours": [...], "data_points": N} 형태로 반환한다.
      // 'hours' 키를 우선 시도하고, 폴백으로 'optimal_hours'를 사용한다.
      return await _get(
        '/api/slippage/optimal-hours?ticker=$ticker',
        (data) {
          List<dynamic> hours;
          if (data is List) {
            hours = data;
          } else if (data is Map) {
            hours = (data['hours'] as List?) ?? (data['optimal_hours'] as List?) ?? [];
          } else {
            hours = [];
          }
          return hours
              .map((item) =>
                  OptimalHour.fromJson(item as Map<String, dynamic>))
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
      // V2: /api/benchmark/comparison
      return await _get(ApiConstants.benchmarkComparison,
          (data) => BenchmarkComparison.fromJson(data));
    } catch (e) {
      debugPrint('getBenchmarkComparison error: $e');
      return BenchmarkComparison.fromJson({});
    }
  }

  Future<List<BenchmarkChartPoint>> getBenchmarkChart() async {
    try {
      // V2: /api/benchmark/chart
      return await _getList(
          ApiConstants.benchmarkChart, BenchmarkChartPoint.fromJson);
    } catch (e) {
      debugPrint('getBenchmarkChart error: $e');
      return [];
    }
  }

  // ── Positions endpoints ──

  /// 현재 모드(virtual/real)의 보유 포지션 목록을 반환한다.
  /// 백엔드 응답: [{"ticker": ..., "quantity": ..., "avg_price": ...,
  ///   "current_price": ..., "unrealized_pnl_pct": ..., "unrealized_pnl": ...,
  ///   "current_value": ..., "name": ..., "exchange": ...}, ...]
  Future<List<Map<String, dynamic>>> getPositions({String? mode}) async {
    try {
      final query = mode != null ? '?mode=$mode' : '';
      // V2: /api/dashboard/positions
      return await _getList(
        '${ApiConstants.dashboardPositions}$query',
        (data) => Map<String, dynamic>.from(data),
      );
    } catch (e) {
      debugPrint('getPositions error: $e');
      return [];
    }
  }

  Future<List<dynamic>> getRecentTrades({int limit = 10, String? mode}) async {
    try {
      // mode 파라미터는 백엔드가 지원하지 않으므로 limit만 전송한다.
      final query = 'limit=$limit';
      return await _getList(
          '${ApiConstants.dashboardTradesRecent}?$query', (data) => data);
    } catch (e) {
      debugPrint('getRecentTrades error: $e');
      return [];
    }
  }

  // ── Macro / Economic indicator endpoints ──

  Future<MacroIndicators> getMacroIndicators() async {
    try {
      return await _get(ApiConstants.macroRichIndicators,
          (data) => MacroIndicators.fromJson(data as Map<String, dynamic>));
    } catch (e) {
      debugPrint('getMacroIndicators error: $e');
      return MacroIndicators.fromJson({});
    }
  }

  Future<FredHistoryData> getFredHistory(String seriesId,
      {int days = 90}) async {
    try {
      return await _get('/api/macro/history/$seriesId?limit=$days',
          (data) => FredHistoryData.fromJson(data as Map<String, dynamic>));
    } catch (e) {
      debugPrint('getFredHistory error: $e');
      return FredHistoryData.fromJson({});
    }
  }

  Future<List<EconomicEvent>> getEconomicCalendar() async {
    try {
      return await _get(ApiConstants.macroCalendar, (data) {
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
      return await _get(ApiConstants.macroRateOutlook,
          (data) => RateOutlook.fromJson(data as Map<String, dynamic>));
    } catch (e) {
      debugPrint('getRateOutlook error: $e');
      return RateOutlook.fromJson({});
    }
  }

  /// 캐시된 거시 지표 데이터를 가져온다.
  Future<Map<String, dynamic>> getCachedIndicators() async {
    try {
      return await _get(
        '/api/macro/cached-indicators',
        (data) => data as Map<String, dynamic>,
      );
    } catch (e) {
      debugPrint('getCachedIndicators error: $e');
      return {};
    }
  }

  /// 캐시된 거시 지표 원시 데이터를 가져온다.
  Future<Map<String, dynamic>> getMacroAnalysis() async {
    try {
      return await _get(
        ApiConstants.macroCachedIndicators,
        (data) => data as Map<String, dynamic>,
      );
    } catch (e) {
      debugPrint('getMacroAnalysis error: $e');
      return {};
    }
  }

  /// 핵심 원칙(슬로건) 텍스트만 가져온다.
  Future<Map<String, dynamic>> getCorePrinciple() async {
    try {
      final data = await _get(
        '/api/principles',
        (d) => d as Map<String, dynamic>,
      );
      return {'core_principle': data['core_principle'] ?? ''};
    } catch (e) {
      debugPrint('getCorePrinciple error: $e');
      return {'core_principle': ''};
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
      return await _get('/api/reports/daily/list?limit=$limit', (data) {
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
        '/api/reports/daily?date=$date',
        (data) => DailyReport.fromJson(data as Map<String, dynamic>),
      );
    } catch (e) {
      debugPrint('getDailyTradingReport error: $e');
      rethrow;
    }
  }

  // ── Universe (Extended) endpoints ──

  /// 유니버스 종목 목록을 UniverseTickerEx 형태로 가져온다.
  /// 백엔드 UniverseResponse는 {"universe": [...], "total": N, "enabled": N} 구조이다.
  Future<List<UniverseTickerEx>> getUniverseEx() async {
    try {
      // V2: /api/universe
      return await _get(ApiConstants.universe, (decoded) {
        List<dynamic> data;
        if (decoded is List) {
          data = decoded;
        } else if (decoded is Map) {
          // 백엔드 래핑 키: universe, data 순서로 탐색한다
          data = (decoded['data'] as List?) ??
              (decoded['universe'] as List?) ??
              [];
        } else {
          data = [];
        }
        return data
            .map((item) =>
                UniverseTickerEx.fromJson(item as Map<String, dynamic>))
            .toList();
      });
    } catch (e) {
      debugPrint('getUniverseEx error: $e');
      return [];
    }
  }

  /// 유니버스 매핑 목록을 가져온다.
  Future<List<TickerMapping>> getUniverseMappings() async {
    try {
      // V2: /api/universe/mappings
      return await _get(ApiConstants.universeMappings, (data) {
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
    // V2: /api/universe/toggle
    await _postVoid(
        ApiConstants.universeToggle, {'ticker': ticker, 'enabled': enabled});
  }

  /// 새 종목을 유니버스에 추가한다.
  Future<void> addUniverseTicker(Map<String, dynamic> data) async {
    // V2: /api/universe/add
    await _postVoid(ApiConstants.universeAdd, data);
  }

  /// 종목을 유니버스에서 삭제한다.
  Future<void> removeUniverseTicker(String ticker) async {
    // V2: /api/universe/{ticker}
    await _delete('${ApiConstants.universe}/$ticker');
  }

  /// 유니버스 매핑을 추가한다.
  Future<void> addUniverseMapping(
      String underlying, String? bull2x, String? bear2x) async {
    // V2: /api/universe/mappings/add
    await _postVoid(ApiConstants.universeMappingsAdd, {
      'underlying': underlying,
      'bull_2x': bull2x,
      'bear_2x': bear2x,
    });
  }

  /// 유니버스 매핑을 삭제한다.
  Future<void> removeUniverseMapping(String underlying) async {
    // V2: /api/universe/mappings/{underlying}
    await _delete('${ApiConstants.universeMappings}/$underlying');
  }

  /// 종목 코드만 입력하면 Claude가 종목 정보를 자동으로 조회하여 추가한다.
  /// AI 호출로 최대 60초가 소요될 수 있으므로 longTimeout을 적용한다.
  Future<Map<String, dynamic>> autoAddTicker(String ticker) async {
    try {
      // V2: /api/universe/auto-add
      return await _post(
        ApiConstants.universeAutoAdd,
        {'ticker': ticker},
        (data) {
          if (data is Map<String, dynamic>) return data;
          return <String, dynamic>{};
        },
      );
    } catch (e) {
      debugPrint('autoAddTicker error: $e');
      rethrow;
    }
  }

  /// 유니버스 섹터 목록을 가져온다.
  /// V2: GET /api/universe/sectors
  Future<Map<String, dynamic>> fetchSectors() async {
    try {
      return await _get(ApiConstants.universeSectors, (decoded) {
        if (decoded is Map<String, dynamic>) return decoded;
        return <String, dynamic>{};
      });
    } catch (e) {
      debugPrint('fetchSectors error: $e');
      return {};
    }
  }

  /// 인디케이터 설정을 업데이트한다.
  Future<void> updateIndicatorConfig(Map<String, dynamic> config) async {
    await _putVoid('/api/indicators/config', {'config': config});
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
      return await _get('/api/news/$id', (data) {
        final map = data as Map<String, dynamic>;
        final article = map['article'] ?? map;  // 백엔드 래퍼 처리, 폴백으로 직접 데이터 사용
        return NewsArticle.fromJson(article as Map<String, dynamic>);
      });
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
    return _put(
      '/api/principles/$id',
      updates,
      (data) => TradingPrinciple.fromJson(data as Map<String, dynamic>),
    );
  }

  /// 매매 원칙을 삭제한다.
  Future<void> deletePrinciple(String id) async {
    await _delete('/api/principles/$id');
  }

  /// 핵심 원칙(슬로건)을 수정한다.
  Future<void> updateCorePrinciple(String text) async {
    await _putVoid('/api/principles/core', {'text': text});
  }

  // ── Trade Reasoning endpoints ──

  /// 매매 근거 날짜 목록을 가져온다.
  /// 백엔드는 {"dates": [...], "total_days": N} 형태로 반환한다.
  Future<List<dynamic>> getTradeReasoningDates() async {
    try {
      return await _get('/api/trade-reasoning/dates', (decoded) {
        if (decoded is Map) {
          return (decoded['dates'] as List?) ?? [];
        }
        if (decoded is List) return decoded;
        return <dynamic>[];
      });
    } catch (e) {
      debugPrint('getTradeReasoningDates error: $e');
      return [];
    }
  }

  /// 특정 날짜의 매매 근거 목록을 가져온다.
  /// 백엔드는 {"date": "...", "trades": [...], "total_count": N} 형태로 반환한다.
  Future<List<dynamic>> getTradeReasoningDaily(String date) async {
    try {
      return await _get('/api/trade-reasoning/daily?date=$date', (decoded) {
        if (decoded is Map) {
          return (decoded['trades'] as List?) ?? [];
        }
        if (decoded is List) return decoded;
        return <dynamic>[];
      });
    } catch (e) {
      debugPrint('getTradeReasoningDaily error: $e');
      return [];
    }
  }

  /// 특정 날짜의 매매 통계 요약을 가져온다.
  Future<Map<String, dynamic>> getTradeReasoningStats(String date) async {
    try {
      return await _get('/api/trade-reasoning/stats?date=$date', (decoded) {
        if (decoded is Map<String, dynamic>) return decoded;
        return <String, dynamic>{};
      });
    } catch (e) {
      debugPrint('getTradeReasoningStats error: $e');
      return {};
    }
  }

  /// 매매 근거에 피드백을 제출한다.
  Future<Map<String, dynamic>> submitTradeReasoningFeedback(
      String tradeId, Map<String, dynamic> body) async {
    try {
      return await _put(
        '/api/trade-reasoning/$tradeId/feedback',
        body,
        (decoded) {
          if (decoded is Map<String, dynamic>) return decoded;
          return <String, dynamic>{};
        },
      );
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
        return list?.map((e) {
          if (e is Map<String, dynamic>) return e['ticker'] as String? ?? '';
          return e.toString();
        }).toList() ?? <String>[];
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
        final body = json.decode(response.body) as Map<String, dynamic>;
        // 서버 응답은 {ticker, analysis: {...}, source, message} 형태이다.
        // analysis 내부 dict를 꺼내서 fromJson에 전달한다.
        final rawAnalysis = body['analysis'];
        if (rawAnalysis == null || rawAnalysis is! Map<String, dynamic>) {
          // analysis가 null이면 서버가 분석 데이터를 생성하지 못한 것이다.
          final msg = body['message'] as String? ?? '분석 데이터 없음';
          throw Exception('분석 데이터를 가져올 수 없습니다 ($ticker): $msg');
        }
        final analysisData = rawAnalysis;
        // 서버 source 필드를 analysis dict에 포함하여 디버깅을 지원한다.
        if (!analysisData.containsKey('source') && body.containsKey('source')) {
          analysisData['source'] = body['source'];
        }
        return StockAnalysisData.fromJson(analysisData);
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
      } else if (response.statusCode == 409) {
        // 409: 대시보드 전용 모드, 매매 시간 외, 비거래일
        final body = json.decode(response.body) as Map<String, dynamic>;
        final detail = body['detail'] as String? ?? '자동매매를 시작할 수 없습니다';
        throw Exception(detail);
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
  /// 크롤링 30개 소스 + AI 분류 + 번역에 최대 1시간 소요될 수 있으므로 타임아웃을 3600초로 설정한다.
  /// 백엔드 응답: {"status": "sent" | "sent_no_key_news", "news_count": N,
  ///              "key_news_count": M, "crawl_saved": K, "telegram_sent": bool}
  Future<Map<String, dynamic>> collectAndSendNews() async {
    try {
      // 크롤링 30개 소스 + AI 분류에 최대 1시간 소요될 수 있으므로 3600초 타임아웃을 적용한다
      final response = await http
          .post(
            Uri.parse('$baseUrl/api/news/collect-and-send'),
            headers: _headers(withJson: true),
            body: json.encode({}),
          )
          .timeout(const Duration(seconds: 3600));
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
          .get(Uri.parse('$baseUrl${ApiConstants.health}'))
          .timeout(_timeout);
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  // ── Agent endpoints ──

  /// 에이전트 팀 목록을 가져온다.
  /// V2: GET /api/agents
  /// 백엔드는 {"agents": [...], "teams": [...]} 형태로 반환한다.
  /// teams 키를 우선 참조하고, 없으면 agents 키를 fallback으로 사용한다.
  Future<List<AgentTeam>> getAgentList() async {
    try {
      return await _get(ApiConstants.agents, (decoded) {
        List<dynamic> data;
        if (decoded is List) {
          // 혹시 리스트로 직접 반환되는 경우도 처리한다
          data = decoded;
        } else if (decoded is Map && decoded['teams'] is List) {
          // 백엔드 실제 응답: {"teams": [...]}
          data = decoded['teams'] as List;
        } else if (decoded is Map && decoded['agents'] is List) {
          // fallback: agents 키에서 읽는다
          data = decoded['agents'] as List;
        } else if (decoded is Map && decoded['data'] is List) {
          data = decoded['data'] as List;
        } else {
          data = [];
        }
        return data
            .map((item) => AgentTeam.fromJson(item as Map<String, dynamic>))
            .toList();
      });
    } catch (e) {
      debugPrint('getAgentList error: $e');
      return [];
    }
  }

  /// 특정 에이전트의 MD 콘텐츠를 가져온다.
  /// V2: GET /api/agents/{agent_id}
  Future<String> getAgentMd(String agentId) async {
    try {
      return await _get('${ApiConstants.agents}/$agentId', (decoded) {
        if (decoded is Map) {
          return decoded['content'] as String? ??
              decoded['md_content'] as String? ??
              '';
        }
        return decoded.toString();
      });
    } catch (e) {
      debugPrint('getAgentMd error: $e');
      return '';
    }
  }

  /// 특정 에이전트의 MD 콘텐츠를 저장한다.
  /// V2: PUT /api/agents/{agent_id}
  Future<void> saveAgentMd(String agentId, String content) async {
    try {
      await _putVoid('${ApiConstants.agents}/$agentId', {'content': content});
    } catch (e) {
      debugPrint('saveAgentMd error: $e');
      rethrow;
    }
  }

  // ── Ticker Params (AI 종목별 전략 파라미터) endpoints ──

  /// 전체 종목 파라미터 요약 목록을 가져온다.
  /// 백엔드 TickerParamsAllResponse는 {"ticker_params": {"SOXL": {...}, "QLD": {...}}}
  /// dict of dict 구조이므로 _getList 대신 커스텀 파서를 사용한다.
  Future<List<TickerParamsSummary>> getTickerParams() async {
    try {
      return await _get('/api/strategy/ticker-params', (decoded) {
        if (decoded is Map) {
          final tickerParams = decoded['ticker_params'];
          if (tickerParams is Map) {
            // dict of dict → List로 변환: 각 entry에 ticker 키를 삽입한다
            return tickerParams.entries.map((e) {
              final value =
                  e.value is Map ? Map<String, dynamic>.from(e.value as Map) : <String, dynamic>{};
              value['ticker'] = e.key;
              return TickerParamsSummary.fromJson(value);
            }).toList();
          }
        }
        return <TickerParamsSummary>[];
      });
    } catch (e) {
      debugPrint('getTickerParams error: $e');
      return [];
    }
  }

  /// 단일 종목 상세 파라미터를 가져온다.
  Future<TickerParamsDetail> getTickerParamsDetail(String ticker) async {
    try {
      return await _get(
        '/api/strategy/ticker-params/$ticker',
        (data) => TickerParamsDetail.fromJson(data as Map<String, dynamic>),
      );
    } catch (e) {
      debugPrint('getTickerParamsDetail error: $e');
      rethrow;
    }
  }

  /// 유저 오버라이드를 설정한다.
  /// 백엔드는 {param_name, value} 단일 파라미터 구조를 기대하므로
  /// overrides map을 순회하며 개별 PUT 요청으로 분리 전송한다.
  Future<void> setTickerOverride(
      String ticker, Map<String, dynamic> overrides) async {
    for (final entry in overrides.entries) {
      await _putVoid('/api/strategy/ticker-params/$ticker', {
        'param_name': entry.key,
        'value': entry.value,
      });
    }
  }

  /// 유저 오버라이드를 제거한다.
  /// [paramName]이 주어지면 해당 파라미터만, 없으면 전체를 제거한다.
  Future<void> clearTickerOverride(String ticker, {String? paramName}) async {
    // 백엔드는 쿼리 파라미터 이름으로 param_name을 기대한다.
    final query = paramName != null ? '?param_name=$paramName' : '';
    await _delete('/api/strategy/ticker-params/$ticker$query');
  }

  /// AI 재분석을 트리거한다.
  Future<void> triggerAiOptimization() async {
    await _postVoid('/api/strategy/ticker-params/ai-optimize', {});
  }

  // ── Manual Trade (수동 매매) endpoints ──

  /// 수동 매매 분석을 요청한다.
  /// AI 의견 + 현재가 + 기술적 지표를 반환한다.
  /// V2: POST /api/manual/analyze (V1의 /api/manual-trade/analyze → V2의 /api/manual/analyze)
  Future<Map<String, dynamic>> manualTradeAnalyze({
    required String ticker,
    required String side,
    required int quantity,
  }) async {
    refreshBaseUrl();
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl${ApiConstants.manualAnalyze}'),
            headers: _headers(withJson: true),
            body: json.encode({
              'ticker': ticker,
              'side': side,
              'quantity': quantity,
            }),
          )
          .timeout(ApiConstants.longTimeout);
      if (response.statusCode == 200) {
        return Map<String, dynamic>.from(json.decode(response.body) as Map);
      } else {
        final dynamic body = json.decode(response.body);
        final String detail =
            (body is Map ? body['detail'] ?? '' : '') as String;
        throw Exception('분석 실패: ${response.statusCode} $detail');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<Map<String, dynamic>>(e, st);
      }
      rethrow;
    }
  }

  /// 수동 매매를 실행한다.
  /// V2: POST /api/manual/execute (V1의 /api/manual-trade/execute → V2의 /api/manual/execute)
  Future<Map<String, dynamic>> manualTradeExecute({
    required String ticker,
    required String side,
    required int quantity,
  }) async {
    refreshBaseUrl();
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl${ApiConstants.manualExecute}'),
            headers: _headers(withJson: true),
            body: json.encode({
              'ticker': ticker,
              'side': side,
              'quantity': quantity,
            }),
          )
          .timeout(ApiConstants.longTimeout);
      if (response.statusCode == 200) {
        return Map<String, dynamic>.from(json.decode(response.body) as Map);
      } else {
        final dynamic body = json.decode(response.body);
        final String detail =
            (body is Map ? body['detail'] ?? '' : '') as String;
        throw Exception('매매 실행 실패: ${response.statusCode} $detail');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError<Map<String, dynamic>>(e, st);
      }
      rethrow;
    }
  }
}
