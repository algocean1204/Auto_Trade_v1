// DashboardProvider 단위 테스트이다.
// 상태 초기화, 로딩, 에러 처리를 검증한다.

import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import 'package:ai_trading_dashboard/models/dashboard_models.dart';
import 'package:ai_trading_dashboard/providers/dashboard_provider.dart';
import 'package:ai_trading_dashboard/services/api_service.dart';

class MockApiService extends Mock implements ApiService {}

void main() {
  late MockApiService mockApi;
  late DashboardProvider provider;

  setUp(() {
    mockApi = MockApiService();
    provider = DashboardProvider(mockApi);
  });

  group('DashboardProvider - 초기 상태', () {
    test('summary는 null이다', () {
      expect(provider.summary, isNull);
    });

    test('systemStatus는 null이다', () {
      expect(provider.systemStatus, isNull);
    });

    test('isLoading은 false이다', () {
      expect(provider.isLoading, isFalse);
    });

    test('error는 null이다', () {
      expect(provider.error, isNull);
    });
  });

  group('DashboardProvider - loadDashboardData 성공', () {
    test('로딩 후 summary와 systemStatus가 설정된다', () async {
      final mockSummary = DashboardSummary(
        totalAsset: 10000.0,
        cash: 5000.0,
        todayPnl: 150.0,
        todayPnlPct: 1.5,
        cumulativeReturn: 10.0,
        activePositions: 2,
        systemStatus: 'RUNNING',
        timestamp: DateTime(2026, 2, 19),
      );

      final mockStatus = SystemStatus(
        claude: true,
        kis: true,
        database: true,
        redis: true,
        fallback: false,
        quota: QuotaInfo(
          claudeCallsToday: 10,
          claudeLimit: 100,
          kisCallsToday: 50,
          kisLimit: 1000,
        ),
        safety: SafetyInfo(
          stopLossEnabled: true,
          takeProfitEnabled: true,
          maxDrawdownCheck: true,
        ),
        timestamp: DateTime(2026, 2, 19),
      );

      when(() => mockApi.getDashboardSummary())
          .thenAnswer((_) async => mockSummary);
      when(() => mockApi.getSystemStatus())
          .thenAnswer((_) async => mockStatus);

      await provider.loadDashboardData();

      expect(provider.summary, isNotNull);
      expect(provider.summary!.totalAsset, 10000.0);
      expect(provider.summary!.activePositions, 2);
      expect(provider.systemStatus, isNotNull);
      expect(provider.systemStatus!.claude, isTrue);
      expect(provider.isLoading, isFalse);
      expect(provider.error, isNull);
    });

    test('로딩 중 isLoading이 true였다가 완료 후 false가 된다', () async {
      final mockSummary = DashboardSummary(
        totalAsset: 0,
        cash: 0,
        todayPnl: 0,
        todayPnlPct: 0,
        cumulativeReturn: 0,
        activePositions: 0,
        systemStatus: 'IDLE',
        timestamp: DateTime.now(),
      );

      final mockStatus = SystemStatus(
        claude: false,
        kis: false,
        database: true,
        redis: true,
        fallback: false,
        quota: QuotaInfo(
          claudeCallsToday: 0,
          claudeLimit: 100,
          kisCallsToday: 0,
          kisLimit: 1000,
        ),
        safety: SafetyInfo(
          stopLossEnabled: true,
          takeProfitEnabled: true,
          maxDrawdownCheck: true,
        ),
        timestamp: DateTime.now(),
      );

      bool wasLoading = false;
      provider.addListener(() {
        if (provider.isLoading) wasLoading = true;
      });

      when(() => mockApi.getDashboardSummary())
          .thenAnswer((_) async => mockSummary);
      when(() => mockApi.getSystemStatus())
          .thenAnswer((_) async => mockStatus);

      await provider.loadDashboardData();

      expect(wasLoading, isTrue);
      expect(provider.isLoading, isFalse);
    });
  });

  group('DashboardProvider - loadDashboardData 실패', () {
    test('에러 발생 시 error 필드가 설정된다', () async {
      when(() => mockApi.getDashboardSummary())
          .thenThrow(Exception('Network error'));

      await provider.loadDashboardData();

      expect(provider.error, isNotNull);
      expect(provider.error, contains('Network error'));
      expect(provider.isLoading, isFalse);
    });

    test('에러 발생 시 summary는 null을 유지한다', () async {
      when(() => mockApi.getDashboardSummary())
          .thenThrow(Exception('Timeout'));

      await provider.loadDashboardData();

      expect(provider.summary, isNull);
      expect(provider.error, isNotNull);
    });

    test('getSystemStatus만 실패해도 error가 설정된다', () async {
      final mockSummary = DashboardSummary(
        totalAsset: 5000.0,
        cash: 2000.0,
        todayPnl: -50.0,
        todayPnlPct: -1.0,
        cumulativeReturn: 5.0,
        activePositions: 1,
        systemStatus: 'RUNNING',
        timestamp: DateTime.now(),
      );

      when(() => mockApi.getDashboardSummary())
          .thenAnswer((_) async => mockSummary);
      when(() => mockApi.getSystemStatus())
          .thenThrow(Exception('System status unavailable'));

      await provider.loadDashboardData();

      expect(provider.error, isNotNull);
      expect(provider.error, contains('System status unavailable'));
    });
  });

  group('DashboardProvider - refresh', () {
    test('refresh는 loadDashboardData를 호출한다', () async {
      when(() => mockApi.getDashboardSummary())
          .thenThrow(Exception('test'));

      await provider.refresh();

      verify(() => mockApi.getDashboardSummary()).called(1);
    });
  });

  group('DashboardProvider - notifyListeners', () {
    test('loadDashboardData 호출 시 리스너가 최소 2회 호출된다', () async {
      int notifyCount = 0;
      provider.addListener(() => notifyCount++);

      when(() => mockApi.getDashboardSummary())
          .thenThrow(Exception('fail'));

      await provider.loadDashboardData();

      // 1번: isLoading = true, 2번: finally에서 isLoading = false
      expect(notifyCount, greaterThanOrEqualTo(2));
    });

    test('성공 시 error가 null로 초기화된다', () async {
      // 먼저 에러를 발생시킨다.
      when(() => mockApi.getDashboardSummary())
          .thenThrow(Exception('first error'));
      await provider.loadDashboardData();
      expect(provider.error, isNotNull);

      // 이제 성공시킨다.
      final mockSummary = DashboardSummary(
        totalAsset: 1000.0,
        cash: 500.0,
        todayPnl: 0,
        todayPnlPct: 0,
        cumulativeReturn: 0,
        activePositions: 0,
        systemStatus: 'OK',
        timestamp: DateTime.now(),
      );
      final mockStatus = SystemStatus(
        claude: true,
        kis: true,
        database: true,
        redis: true,
        fallback: false,
        quota: QuotaInfo(
          claudeCallsToday: 0,
          claudeLimit: 100,
          kisCallsToday: 0,
          kisLimit: 1000,
        ),
        safety: SafetyInfo(
          stopLossEnabled: true,
          takeProfitEnabled: true,
          maxDrawdownCheck: true,
        ),
        timestamp: DateTime.now(),
      );

      when(() => mockApi.getDashboardSummary())
          .thenAnswer((_) async => mockSummary);
      when(() => mockApi.getSystemStatus())
          .thenAnswer((_) async => mockStatus);

      await provider.loadDashboardData();
      expect(provider.error, isNull);
    });
  });
}
