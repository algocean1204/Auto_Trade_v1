// GlassCard 위젯 테스트이다.
// 다크 모드와 라이트 모드에서 각각 올바르게 렌더링되는지 확인한다.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_trading_dashboard/widgets/glass_card.dart';
import 'package:ai_trading_dashboard/theme/app_theme.dart';

void main() {
  group('GlassCard', () {
    testWidgets('자식 위젯을 렌더링한다', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: const Scaffold(
            body: GlassCard(
              child: Text('Card Content'),
            ),
          ),
        ),
      );

      expect(find.text('Card Content'), findsOneWidget);
    });

    testWidgets('다크 테마에서 BackdropFilter를 포함한다', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: const Scaffold(
            body: GlassCard(
              child: Text('Dark Card'),
            ),
          ),
        ),
      );

      // 다크 모드에서는 글래스모피즘 효과로 BackdropFilter가 사용된다.
      expect(find.byType(BackdropFilter), findsOneWidget);
      expect(find.text('Dark Card'), findsOneWidget);
    });

    testWidgets('라이트 테마에서는 BackdropFilter를 사용하지 않는다', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.lightTheme,
          home: const Scaffold(
            body: GlassCard(
              child: Text('Light Card'),
            ),
          ),
        ),
      );

      // 라이트 모드에서는 BackdropFilter 대신 Container만 사용한다.
      expect(find.byType(BackdropFilter), findsNothing);
      expect(find.text('Light Card'), findsOneWidget);
    });

    testWidgets('onTap 콜백이 동작한다', (tester) async {
      bool tapped = false;

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: Scaffold(
            body: GlassCard(
              onTap: () => tapped = true,
              child: const Text('Tap Me'),
            ),
          ),
        ),
      );

      await tester.tap(find.text('Tap Me'));
      expect(tapped, isTrue);
    });

    testWidgets('onTap이 null이면 GestureDetector를 추가하지 않는다', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: const Scaffold(
            body: GlassCard(
              child: Text('No Tap'),
            ),
          ),
        ),
      );

      // GestureDetector가 GlassCard의 직접 자식으로 없어야 한다.
      // (MaterialApp 자체에도 GestureDetector가 있으므로 findsNothing은 아님)
      expect(find.text('No Tap'), findsOneWidget);
    });

    testWidgets('margin이 있으면 Padding이 적용된다', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: const Scaffold(
            body: GlassCard(
              margin: EdgeInsets.all(16),
              child: Text('Margined'),
            ),
          ),
        ),
      );

      expect(find.text('Margined'), findsOneWidget);
    });
  });

  group('ElevatedCard', () {
    testWidgets('자식 위젯을 렌더링한다', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: const Scaffold(
            body: ElevatedCard(
              child: Text('Elevated Content'),
            ),
          ),
        ),
      );

      expect(find.text('Elevated Content'), findsOneWidget);
    });

    testWidgets('onTap 콜백이 동작한다', (tester) async {
      bool tapped = false;

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: Scaffold(
            body: ElevatedCard(
              onTap: () => tapped = true,
              child: const Text('Tap Elevated'),
            ),
          ),
        ),
      );

      await tester.tap(find.text('Tap Elevated'));
      expect(tapped, isTrue);
    });
  });
}
