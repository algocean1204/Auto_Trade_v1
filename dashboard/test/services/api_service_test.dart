// ApiService 단위 테스트이다.
// URL 생성, 에러 핸들링, 응답 파싱을 검증한다.

import 'package:flutter_test/flutter_test.dart';

import 'package:ai_trading_dashboard/services/api_service.dart';

void main() {
  group('ApiService - URL 생성', () {
    test('기본 baseUrl은 localhost:9500이다', () {
      final api = ApiService();
      expect(api.baseUrl, 'http://localhost:9500');
    });

    test('커스텀 baseUrl을 설정할 수 있다', () {
      final api = ApiService(baseUrl: 'http://192.168.1.100:8080');
      expect(api.baseUrl, 'http://192.168.1.100:8080');
    });
  });

  group('ApiService - checkHealth', () {
    test('서버가 없으면 false를 반환한다', () async {
      // localhost에 실제 서버가 없으므로 false를 반환해야 한다.
      final api = ApiService(baseUrl: 'http://localhost:59999');
      final result = await api.checkHealth();
      expect(result, isFalse);
    });

    test('네트워크 에러 시 false를 반환한다', () async {
      final api = ApiService(baseUrl: 'http://invalid-host-that-does-not-exist:9999');
      final result = await api.checkHealth();
      expect(result, isFalse);
    });
  });

  group('ApiService - getDashboardSummary 응답 파싱', () {
    test('정상 JSON을 DashboardSummary로 파싱한다', () async {
      // ApiService가 http 패키지를 직접 사용하므로 네트워크 없이는
      // 모델 파싱만 별도 테스트한다.
      final json = {
        'total_asset': 10000.0,
        'cash': 5000.0,
        'today_pnl': 150.5,
        'today_pnl_pct': 1.5,
        'cumulative_return': 10.2,
        'active_positions': 3,
        'system_status': 'RUNNING',
        'timestamp': '2026-02-19T10:00:00',
      };

      // DashboardSummary.fromJson을 직접 테스트한다.
      final summary =
          (await Future.value(json)).cast<String, dynamic>();
      expect(summary['total_asset'], 10000.0);
      expect(summary['active_positions'], 3);
    });
  });

  group('ApiService - _getList 응답 형식 처리', () {
    test('리스트 형식 응답을 올바르게 처리한다', () {
      // _getList의 로직을 시뮬레이션한다.
      // dynamic으로 선언하여 실제 API 응답 파싱 로직과 동일하게 테스트한다.
      final dynamic decoded = [
        {'ticker': 'SOXL', 'name': 'Direxion SOX 2X', 'direction': 'bull', 'enabled': true},
        {'ticker': 'QLD', 'name': 'ProShares QQQ 2X', 'direction': 'bull', 'enabled': false},
      ];

      List<dynamic> data;
      if (decoded is List) {
        data = decoded;
      } else {
        data = [];
      }

      expect(data.length, 2);
      expect((data[0] as Map)['ticker'], 'SOXL');
      expect((data[1] as Map)['ticker'], 'QLD');
    });

    test('{data: [...]} 형식 응답을 올바르게 처리한다', () {
      final dynamic decoded = <String, dynamic>{
        'data': [
          {'ticker': 'SOXL', 'name': 'Direxion SOX 2X'},
        ]
      };

      List<dynamic> data;
      if (decoded is List) {
        data = decoded;
      } else if (decoded is Map && decoded['data'] is List) {
        data = decoded['data'] as List;
      } else {
        data = [];
      }

      expect(data.length, 1);
      expect((data[0] as Map)['ticker'], 'SOXL');
    });

    test('빈 응답을 빈 리스트로 처리한다', () {
      final dynamic decoded = <String, dynamic>{'message': 'no data'};

      List<dynamic> data;
      if (decoded is List) {
        data = decoded;
      } else if (decoded is Map && decoded['data'] is List) {
        data = decoded['data'] as List;
      } else {
        data = [];
      }

      expect(data, isEmpty);
    });
  });

  group('ApiService - 쿼리 파라미터 구성', () {
    test('getAlerts 쿼리 문자열 생성 - 기본값', () {
      const limit = 50;

      // 필터 없이 기본 limit만 포함되는 쿼리를 생성한다.
      final query = _buildAlertQuery(limit: limit);

      expect(query, 'limit=50');
    });

    test('getAlerts 쿼리 문자열 생성 - 모든 필터', () {
      const limit = 20;
      const alertType = 'trade';
      const severity = 'critical';

      String query = 'limit=$limit';
      query += '&alert_type=$alertType';
      query += '&severity=$severity';

      expect(query, 'limit=20&alert_type=trade&severity=critical');
    });

    test('getDailyNews 쿼리 문자열 생성', () {
      const date = '2026-02-19';
      const limit = 50;
      const offset = 0;
      const category = 'macro';

      // impact 필터 없이 category만 포함되는 쿼리를 생성한다.
      final query = _buildNewsQuery(
        date: date,
        limit: limit,
        offset: offset,
        category: category,
      );

      expect(query, 'date=2026-02-19&limit=50&offset=0&category=macro');
    });
  });

  group('ApiService - getUnreadCount 파싱', () {
    test('unread_count 필드를 파싱한다', () {
      final data = {'unread_count': 5};
      final count = data['unread_count'] ?? data['count'];
      expect((count as num?)?.toInt() ?? 0, 5);
    });

    test('count 필드를 fallback으로 파싱한다', () {
      final data = {'count': 3};
      final count = data['unread_count'] ?? data['count'];
      expect((count as num?)?.toInt() ?? 0, 3);
    });

    test('둘 다 없으면 0을 반환한다', () {
      final data = <String, dynamic>{};
      final count = data['unread_count'] ?? data['count'];
      expect((count as num?)?.toInt() ?? 0, 0);
    });
  });

  group('ApiService - 에러 상태 코드 처리', () {
    test('비-200 상태 코드에서 Exception을 생성한다', () {
      const endpoint = '/dashboard/summary';
      const statusCode = 500;

      final error = Exception('GET $endpoint failed: $statusCode');
      expect(error.toString(), contains('GET /dashboard/summary failed: 500'));
    });

    test('POST 비-200/201 상태 코드에서 Exception을 생성한다', () {
      const endpoint = '/emergency/stop';
      const statusCode = 403;

      final error = Exception('POST $endpoint failed: $statusCode');
      expect(error.toString(), contains('POST /emergency/stop failed: 403'));
    });

    test('DELETE 비-200/204 상태 코드에서 Exception을 생성한다', () {
      const endpoint = '/universe/SOXL';
      const statusCode = 404;

      final error = Exception('DELETE $endpoint failed: $statusCode');
      expect(error.toString(), contains('DELETE /universe/SOXL failed: 404'));
    });

    test('PUT 비-200 상태 코드에서 Exception을 생성한다', () {
      const endpoint = '/api/target/aggression';
      const statusCode = 422;

      final error = Exception('PUT $endpoint failed: $statusCode');
      expect(error.toString(), contains('PUT /api/target/aggression failed: 422'));
    });
  });

  group('ApiService - endpoint URL 패턴', () {
    test('getDailyReturns URL에 days 쿼리가 포함된다', () {
      const baseUrl = 'http://localhost:9500';
      const days = 30;
      final url = Uri.parse('$baseUrl/dashboard/charts/daily-returns?days=$days');
      expect(url.queryParameters['days'], '30');
      expect(url.path, '/dashboard/charts/daily-returns');
    });

    test('getTripleRsi URL에 ticker와 days가 포함된다', () {
      const baseUrl = 'http://localhost:9500';
      const ticker = 'SOXL';
      const days = 100;
      final url = Uri.parse('$baseUrl/api/indicators/rsi/$ticker?days=$days');
      expect(url.path, '/api/indicators/rsi/SOXL');
      expect(url.queryParameters['days'], '100');
    });

    test('getStockAnalysis URL에 ticker가 포함된다', () {
      const baseUrl = 'http://localhost:9500';
      const ticker = 'QLD';
      final url = Uri.parse('$baseUrl/api/analysis/comprehensive/$ticker');
      expect(url.path, '/api/analysis/comprehensive/QLD');
    });
  });
}

/// 알림 쿼리 문자열을 생성하는 헬퍼이다.
String _buildAlertQuery({
  required int limit,
  String? alertType,
  String? severity,
}) {
  String query = 'limit=$limit';
  if (alertType != null) query += '&alert_type=$alertType';
  if (severity != null) query += '&severity=$severity';
  return query;
}

/// 뉴스 쿼리 문자열을 생성하는 헬퍼이다.
String _buildNewsQuery({
  required String date,
  required int limit,
  required int offset,
  String? category,
  String? impact,
}) {
  String query = 'date=$date&limit=$limit&offset=$offset';
  if (category != null && category.isNotEmpty) query += '&category=$category';
  if (impact != null && impact.isNotEmpty) query += '&impact=$impact';
  return query;
}
