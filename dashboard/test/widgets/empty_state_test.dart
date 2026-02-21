// EmptyState, ErrorState 위젯 테스트이다.
// 다양한 파라미터 조합에서의 렌더링과 콜백을 검증한다.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:ai_trading_dashboard/widgets/empty_state.dart';
import 'package:ai_trading_dashboard/providers/locale_provider.dart';
import 'package:ai_trading_dashboard/theme/app_theme.dart';

Widget _buildTestWidget(Widget child, {String locale = 'ko'}) {
  final localeProvider = LocaleProvider();
  localeProvider.setLocale(locale);

  return ChangeNotifierProvider<LocaleProvider>.value(
    value: localeProvider,
    child: MaterialApp(
      theme: AppTheme.darkTheme,
      home: Scaffold(body: child),
    ),
  );
}

void main() {
  group('EmptyState - 렌더링', () {
    testWidgets('아이콘과 타이틀이 표시된다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          const EmptyState(
            icon: Icons.inbox_rounded,
            title: 'No data available',
          ),
        ),
      );

      expect(find.byIcon(Icons.inbox_rounded), findsOneWidget);
      expect(find.text('No data available'), findsOneWidget);
    });

    testWidgets('subtitle이 있으면 표시된다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          const EmptyState(
            icon: Icons.inbox_rounded,
            title: 'No data',
            subtitle: 'Connect to see data',
          ),
        ),
      );

      expect(find.text('No data'), findsOneWidget);
      expect(find.text('Connect to see data'), findsOneWidget);
    });

    testWidgets('subtitle이 null이면 표시되지 않는다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          const EmptyState(
            icon: Icons.inbox_rounded,
            title: 'Empty',
          ),
        ),
      );

      expect(find.text('Empty'), findsOneWidget);
      // subtitle Text 위젯이 하나만 있어야 한다 (title만).
      expect(find.byType(Text), findsOneWidget);
    });

    testWidgets('actionLabel과 onAction이 있으면 버튼이 표시된다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          EmptyState(
            icon: Icons.refresh,
            title: 'No data',
            actionLabel: 'Retry',
            onAction: () {},
          ),
        ),
      );

      expect(find.text('Retry'), findsOneWidget);
      expect(find.byType(ElevatedButton), findsOneWidget);
    });

    testWidgets('actionLabel이 null이면 버튼이 표시되지 않는다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          const EmptyState(
            icon: Icons.hourglass_empty,
            title: 'Loading...',
          ),
        ),
      );

      expect(find.byType(ElevatedButton), findsNothing);
    });

    testWidgets('onAction이 null이면 버튼이 표시되지 않는다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          const EmptyState(
            icon: Icons.hourglass_empty,
            title: 'Loading...',
            actionLabel: 'Retry',
            // onAction은 null
          ),
        ),
      );

      expect(find.byType(ElevatedButton), findsNothing);
    });

    testWidgets('액션 버튼 탭 시 콜백이 호출된다', (tester) async {
      bool actionCalled = false;

      await tester.pumpWidget(
        _buildTestWidget(
          EmptyState(
            icon: Icons.refresh,
            title: 'No data',
            actionLabel: 'Refresh',
            onAction: () => actionCalled = true,
          ),
        ),
      );

      await tester.tap(find.text('Refresh'));
      expect(actionCalled, isTrue);
    });

    testWidgets('Center 위젯으로 감싸져 있다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          const EmptyState(
            icon: Icons.inbox,
            title: 'Empty',
          ),
        ),
      );

      expect(find.byType(Center), findsWidgets);
    });
  });

  group('ErrorState - 렌더링', () {
    testWidgets('기본 에러 아이콘과 메시지가 표시된다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          const ErrorState(
            message: 'Failed to load data',
          ),
        ),
      );

      expect(find.byIcon(Icons.cloud_off_rounded), findsOneWidget);
      expect(find.text('Failed to load data'), findsOneWidget);
      // 기본 title은 locale의 'connection_error' 값이다.
      expect(find.text('연결 오류'), findsOneWidget);
    });

    testWidgets('커스텀 title이 있으면 기본값 대신 사용된다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          const ErrorState(
            message: 'Server unreachable',
            title: 'Custom Error Title',
          ),
        ),
      );

      expect(find.text('Custom Error Title'), findsOneWidget);
      expect(find.text('Server unreachable'), findsOneWidget);
    });

    testWidgets('영어 로케일에서 기본 title이 영어로 표시된다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          const ErrorState(
            message: 'Network timeout',
          ),
          locale: 'en',
        ),
      );

      expect(find.text('Connection Error'), findsOneWidget);
      expect(find.text('Network timeout'), findsOneWidget);
    });

    testWidgets('onRetry가 있으면 재시도 버튼이 표시된다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          ErrorState(
            message: 'Error occurred',
            onRetry: () {},
          ),
        ),
      );

      // 기본 retryLabel은 locale의 'retry' 값이다.
      expect(find.text('재시도'), findsOneWidget);
      expect(find.byIcon(Icons.refresh_rounded), findsOneWidget);
    });

    testWidgets('커스텀 retryLabel이 사용된다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          ErrorState(
            message: 'Error',
            retryLabel: 'Try Again',
            onRetry: () {},
          ),
        ),
      );

      expect(find.text('Try Again'), findsOneWidget);
    });

    testWidgets('onRetry가 null이면 버튼이 표시되지 않는다', (tester) async {
      await tester.pumpWidget(
        _buildTestWidget(
          const ErrorState(
            message: 'Permanent error',
          ),
        ),
      );

      expect(find.byType(ElevatedButton), findsNothing);
    });

    testWidgets('재시도 버튼 탭 시 콜백이 호출된다', (tester) async {
      bool retryCalled = false;

      await tester.pumpWidget(
        _buildTestWidget(
          ErrorState(
            message: 'Retryable error',
            onRetry: () => retryCalled = true,
          ),
        ),
      );

      await tester.tap(find.text('재시도'));
      expect(retryCalled, isTrue);
    });
  });
}
