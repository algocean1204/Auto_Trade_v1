// SidebarNav 위젯 테스트이다.
// 렌더링, 네비게이션 탭, 테마 토글을 검증한다.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ai_trading_dashboard/widgets/sidebar_nav.dart';
import 'package:ai_trading_dashboard/providers/navigation_provider.dart';
import 'package:ai_trading_dashboard/providers/settings_provider.dart';
import 'package:ai_trading_dashboard/providers/locale_provider.dart';
import 'package:ai_trading_dashboard/providers/theme_provider.dart';
import 'package:ai_trading_dashboard/services/api_service.dart';
import 'package:ai_trading_dashboard/theme/app_theme.dart';

Widget _buildTestWidget({
  NavigationProvider? navProvider,
  SettingsProvider? settingsProvider,
  LocaleProvider? localeProvider,
  ThemeProvider? themeProvider,
}) {
  final apiService = ApiService();
  return MultiProvider(
    providers: [
      ChangeNotifierProvider<NavigationProvider>(
        create: (_) => navProvider ?? NavigationProvider(),
      ),
      ChangeNotifierProvider<SettingsProvider>(
        create: (_) => settingsProvider ?? SettingsProvider(apiService),
      ),
      ChangeNotifierProvider<LocaleProvider>(
        create: (_) => localeProvider ?? LocaleProvider(),
      ),
      ChangeNotifierProvider<ThemeProvider>(
        create: (_) => themeProvider ?? ThemeProvider(),
      ),
    ],
    child: MaterialApp(
      theme: AppTheme.darkTheme,
      home: const Scaffold(
        body: Row(
          children: [
            SidebarNav(),
            Expanded(child: SizedBox()),
          ],
        ),
      ),
    ),
  );
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('SidebarNav - 렌더링', () {
    testWidgets('사이드바가 올바르게 렌더링된다', (tester) async {
      await tester.pumpWidget(_buildTestWidget());
      await tester.pumpAndSettle();

      // 헤더의 타이틀이 보여야 한다 (한국어 기본값).
      expect(find.text('AI 트레이더'), findsOneWidget);
      expect(find.text('V2 시스템'), findsOneWidget);
    });

    testWidgets('상단 네비게이션 항목들이 표시된다', (tester) async {
      await tester.pumpWidget(_buildTestWidget());
      await tester.pumpAndSettle();

      // 한국어 기본값으로 상단 항목들이 보여야 한다 (하단 항목은 스크롤 필요).
      expect(find.text('개요'), findsOneWidget);
      expect(find.text('트레이딩'), findsOneWidget);
      expect(find.text('리스크 & 안전'), findsOneWidget);
      expect(find.text('분석'), findsOneWidget);
    });

    testWidgets('스크롤 오프스테이지 포함 시 모든 항목이 존재한다', (tester) async {
      await tester.pumpWidget(_buildTestWidget());
      await tester.pumpAndSettle();

      // 오프스테이지 위젯도 포함하여 설정 항목이 위젯 트리에 존재하는지 확인한다.
      expect(find.text('설정', skipOffstage: false), findsOneWidget);
      expect(find.text('종목 관리', skipOffstage: false), findsOneWidget);
      expect(find.text('에이전트팀', skipOffstage: false), findsOneWidget);
    });

    testWidgets('footer에 버전 텍스트가 표시된다', (tester) async {
      await tester.pumpWidget(_buildTestWidget());
      await tester.pumpAndSettle();

      expect(find.text('Stock Trading AI V2'), findsOneWidget);
    });

    testWidgets('auto_graph 아이콘이 헤더에 표시된다', (tester) async {
      await tester.pumpWidget(_buildTestWidget());
      await tester.pumpAndSettle();

      expect(find.byIcon(Icons.auto_graph_rounded), findsOneWidget);
    });
  });

  group('SidebarNav - 네비게이션', () {
    testWidgets('항목 탭 시 NavigationProvider의 섹션이 변경된다', (tester) async {
      final navProvider = NavigationProvider();
      await tester.pumpWidget(_buildTestWidget(navProvider: navProvider));
      await tester.pumpAndSettle();

      // 초기 상태는 overview이다.
      expect(navProvider.currentSection, NavSection.overview);

      // '트레이딩'을 탭한다.
      await tester.tap(find.text('트레이딩'));
      await tester.pumpAndSettle();

      expect(navProvider.currentSection, NavSection.trading);
    });

    testWidgets('다른 항목을 탭하면 섹션이 업데이트된다', (tester) async {
      final navProvider = NavigationProvider();
      await tester.pumpWidget(_buildTestWidget(navProvider: navProvider));
      await tester.pumpAndSettle();

      // '분석'을 탭한다.
      await tester.tap(find.text('분석'));
      await tester.pumpAndSettle();

      expect(navProvider.currentSection, NavSection.analytics);
    });

    testWidgets('리스크 항목을 탭할 수 있다', (tester) async {
      final navProvider = NavigationProvider();
      await tester.pumpWidget(_buildTestWidget(navProvider: navProvider));
      await tester.pumpAndSettle();

      // '리스크 & 안전'을 탭한다 (화면에 보이는 항목).
      await tester.tap(find.text('리스크 & 안전'));
      await tester.pumpAndSettle();

      expect(navProvider.currentSection, NavSection.risk);
    });
  });

  group('SidebarNav - 테마 토글', () {
    testWidgets('다크 모드에서 테마 토글 버튼이 표시된다', (tester) async {
      await tester.pumpWidget(_buildTestWidget());
      await tester.pumpAndSettle();

      // 다크 모드일 때 '라이트 모드' 텍스트가 표시되어야 한다.
      expect(find.text('라이트 모드'), findsOneWidget);
    });
  });

  group('SidebarNav - 로케일', () {
    testWidgets('영어 로케일에서 올바른 레이블이 표시된다', (tester) async {
      final locale = LocaleProvider();
      locale.setLocale('en');

      await tester.pumpWidget(_buildTestWidget(localeProvider: locale));
      await tester.pumpAndSettle();

      expect(find.text('AI Trader'), findsOneWidget);
      expect(find.text('V2 System'), findsOneWidget);
      expect(find.text('Overview'), findsOneWidget);
      expect(find.text('Trading'), findsOneWidget);
    });

    testWidgets('한국어 로케일에서 올바른 레이블이 표시된다', (tester) async {
      final locale = LocaleProvider();
      locale.setLocale('ko');

      await tester.pumpWidget(_buildTestWidget(localeProvider: locale));
      await tester.pumpAndSettle();

      expect(find.text('AI 트레이더'), findsOneWidget);
      expect(find.text('V2 시스템'), findsOneWidget);
      expect(find.text('개요'), findsOneWidget);
    });
  });
}
