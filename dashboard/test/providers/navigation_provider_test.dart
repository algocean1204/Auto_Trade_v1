// NavigationProvider 단위 테스트이다.

import 'package:flutter_test/flutter_test.dart';

import 'package:ai_trading_dashboard/providers/navigation_provider.dart';

void main() {
  group('NavigationProvider', () {
    test('초기 섹션은 overview이다', () {
      final provider = NavigationProvider();
      expect(provider.currentSection, NavSection.overview);
    });

    test('초기 alertPanelOpen은 false이다', () {
      final provider = NavigationProvider();
      expect(provider.alertPanelOpen, isFalse);
    });

    test('navigateTo - 섹션을 변경한다', () {
      final provider = NavigationProvider();

      provider.navigateTo(NavSection.trading);
      expect(provider.currentSection, NavSection.trading);

      provider.navigateTo(NavSection.risk);
      expect(provider.currentSection, NavSection.risk);
    });

    test('navigateTo - 동일한 섹션으로는 변경하지 않는다', () {
      final provider = NavigationProvider();

      int notifyCount = 0;
      provider.addListener(() => notifyCount++);

      provider.navigateTo(NavSection.overview);
      // 이미 overview이므로 notifyListeners가 호출되지 않아야 한다.
      expect(notifyCount, 0);
    });

    test('navigateTo - 섹션 변경 시 alertPanel을 닫는다', () {
      final provider = NavigationProvider();

      // alertPanel을 연다.
      provider.toggleAlertPanel();
      expect(provider.alertPanelOpen, isTrue);

      // 다른 섹션으로 이동하면 alertPanel이 닫힌다.
      provider.navigateTo(NavSection.analytics);
      expect(provider.alertPanelOpen, isFalse);
    });

    test('navigateTo 호출 시 notifyListeners가 호출된다', () {
      final provider = NavigationProvider();

      int notifyCount = 0;
      provider.addListener(() => notifyCount++);

      provider.navigateTo(NavSection.trading);
      expect(notifyCount, 1);

      provider.navigateTo(NavSection.risk);
      expect(notifyCount, 2);
    });

    test('toggleAlertPanel - 패널을 토글한다', () {
      final provider = NavigationProvider();

      expect(provider.alertPanelOpen, isFalse);

      provider.toggleAlertPanel();
      expect(provider.alertPanelOpen, isTrue);

      provider.toggleAlertPanel();
      expect(provider.alertPanelOpen, isFalse);
    });

    test('closeAlertPanel - 패널을 닫는다', () {
      final provider = NavigationProvider();

      provider.toggleAlertPanel();
      expect(provider.alertPanelOpen, isTrue);

      provider.closeAlertPanel();
      expect(provider.alertPanelOpen, isFalse);
    });

    test('모든 NavSection 값을 순회할 수 있다', () {
      final provider = NavigationProvider();

      for (final section in NavSection.values) {
        provider.navigateTo(section);
        expect(provider.currentSection, section);
      }
    });
  });

  group('NavSection extension', () {
    test('label - 각 섹션의 레이블을 반환한다', () {
      expect(NavSection.overview.label, 'Overview');
      expect(NavSection.trading.label, 'Trading');
      expect(NavSection.risk.label, 'Risk & Safety');
      expect(NavSection.analytics.label, 'Analytics');
      expect(NavSection.rsi.label, 'RSI Analysis');
      expect(NavSection.stockAnalysis.label, 'Stock Analysis');
      expect(NavSection.reports.label, 'Daily Reports');
      expect(NavSection.tradeReasoning.label, 'Trade Reasoning');
      expect(NavSection.news.label, 'News');
      expect(NavSection.universe.label, 'Universe');
      expect(NavSection.agents.label, 'Agent Teams');
      expect(NavSection.principles.label, 'Trading Principles');
      expect(NavSection.settings.label, 'Settings');
    });

    test('icon - 각 섹션에 아이콘이 할당되어 있다', () {
      for (final section in NavSection.values) {
        expect(section.icon, isNotNull);
      }
    });

    test('activeIcon - 각 섹션에 활성 아이콘이 할당되어 있다', () {
      for (final section in NavSection.values) {
        expect(section.activeIcon, isNotNull);
      }
    });
  });
}
