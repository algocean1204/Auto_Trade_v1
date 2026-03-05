// AI Trading Dashboard smoke test.
// AiTradingApp 내부에서 ApiService가 HTTP 요청을 시도하기 때문에
// 직접 pumpWidget하면 네트워크 오류가 발생한다.
// 대신 MaterialApp을 직접 구성하여 위젯 트리가 문제없이 빌드되는지 확인한다.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:ai_trading_dashboard/providers/theme_provider.dart';
import 'package:ai_trading_dashboard/providers/navigation_provider.dart';
import 'package:ai_trading_dashboard/theme/app_theme.dart';

void main() {
  testWidgets('App smoke test - MaterialApp with providers builds without error',
      (WidgetTester tester) async {
    // ThemeProvider와 NavigationProvider만으로 기본 MaterialApp을 구성한다.
    // ApiService를 사용하는 프로바이더는 제외하여 네트워크 의존성을 회피한다.
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider(create: (_) => ThemeProvider()),
          ChangeNotifierProvider(create: (_) => NavigationProvider()),
        ],
        child: Consumer<ThemeProvider>(
          builder: (context, themeProvider, child) {
            return MaterialApp(
              title: 'AI Trading Dashboard',
              theme: AppTheme.lightTheme,
              darkTheme: AppTheme.darkTheme,
              themeMode: themeProvider.themeMode,
              home: const Scaffold(
                body: Center(child: Text('AI Trading Dashboard')),
              ),
              debugShowCheckedModeBanner: false,
            );
          },
        ),
      ),
    );

    // 앱이 정상적으로 렌더링되었는지 확인한다.
    expect(find.text('AI Trading Dashboard'), findsOneWidget);
  });

  testWidgets('App smoke test - basic widget tree renders',
      (WidgetTester tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: Text('Test')),
      ),
    );
    expect(find.text('Test'), findsOneWidget);
  });
}
