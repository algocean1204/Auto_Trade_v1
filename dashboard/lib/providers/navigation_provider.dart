import 'package:flutter/material.dart';

// 사이드바 섹션 열거형이다.
enum NavSection {
  overview,
  trading,
  risk,
  analytics,
  rsi,
  stockAnalysis,
  reports,
  tradeReasoning,
  news,
  universe,
  agents,
  principles,
  settings,
}

extension NavSectionExtension on NavSection {
  String get label {
    switch (this) {
      case NavSection.overview:
        return 'Overview';
      case NavSection.trading:
        return 'Trading';
      case NavSection.risk:
        return 'Risk & Safety';
      case NavSection.analytics:
        return 'Analytics';
      case NavSection.rsi:
        return 'RSI Analysis';
      case NavSection.stockAnalysis:
        return 'Stock Analysis';
      case NavSection.reports:
        return 'Daily Reports';
      case NavSection.tradeReasoning:
        return 'Trade Reasoning';
      case NavSection.news:
        return 'News';
      case NavSection.universe:
        return 'Universe';
      case NavSection.agents:
        return 'Agent Teams';
      case NavSection.principles:
        return 'Trading Principles';
      case NavSection.settings:
        return 'Settings';
    }
  }

  IconData get icon {
    switch (this) {
      case NavSection.overview:
        return Icons.dashboard_rounded;
      case NavSection.trading:
        return Icons.show_chart_rounded;
      case NavSection.risk:
        return Icons.shield_rounded;
      case NavSection.analytics:
        return Icons.analytics_rounded;
      case NavSection.rsi:
        return Icons.stacked_line_chart_rounded;
      case NavSection.stockAnalysis:
        return Icons.query_stats_rounded;
      case NavSection.reports:
        return Icons.article_outlined;
      case NavSection.tradeReasoning:
        return Icons.psychology_outlined;
      case NavSection.news:
        return Icons.newspaper_outlined;
      case NavSection.universe:
        return Icons.list_alt_rounded;
      case NavSection.agents:
        return Icons.account_tree_rounded;
      case NavSection.principles:
        return Icons.gavel_rounded;
      case NavSection.settings:
        return Icons.settings_rounded;
    }
  }

  IconData get activeIcon {
    switch (this) {
      case NavSection.overview:
        return Icons.dashboard_rounded;
      case NavSection.trading:
        return Icons.show_chart_rounded;
      case NavSection.risk:
        return Icons.shield_rounded;
      case NavSection.analytics:
        return Icons.analytics_rounded;
      case NavSection.rsi:
        return Icons.stacked_line_chart_rounded;
      case NavSection.stockAnalysis:
        return Icons.query_stats_rounded;
      case NavSection.reports:
        return Icons.article_rounded;
      case NavSection.tradeReasoning:
        return Icons.psychology_rounded;
      case NavSection.news:
        return Icons.newspaper_rounded;
      case NavSection.universe:
        return Icons.list_alt_rounded;
      case NavSection.agents:
        return Icons.account_tree_rounded;
      case NavSection.principles:
        return Icons.gavel_rounded;
      case NavSection.settings:
        return Icons.settings_rounded;
    }
  }
}

class NavigationProvider with ChangeNotifier {
  NavSection _currentSection = NavSection.overview;
  bool _alertPanelOpen = false;

  NavSection get currentSection => _currentSection;
  bool get alertPanelOpen => _alertPanelOpen;

  void navigateTo(NavSection section) {
    if (_currentSection != section) {
      _currentSection = section;
      _alertPanelOpen = false;
      notifyListeners();
    }
  }

  void toggleAlertPanel() {
    _alertPanelOpen = !_alertPanelOpen;
    notifyListeners();
  }

  void closeAlertPanel() {
    _alertPanelOpen = false;
    notifyListeners();
  }
}
