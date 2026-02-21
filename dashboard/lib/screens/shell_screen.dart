import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/navigation_provider.dart';
import '../providers/settings_provider.dart';
import '../providers/emergency_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../theme/trading_colors.dart';
import '../widgets/sidebar_nav.dart';
import '../widgets/status_bar.dart';
import '../widgets/alert_panel.dart';
import '../widgets/emergency_button.dart';
import 'overview_screen.dart';
import 'trading_screen.dart';
import 'risk_center_screen.dart';
import 'analytics_screen.dart';
import 'settings_screen.dart';
import 'agent_team_screen.dart';
import 'rsi_screen.dart';
import 'reports_screen.dart';
import 'news_screen.dart';
import 'universe_screen.dart';
import 'principles_screen.dart';
import 'trade_reasoning_screen.dart';
import 'stock_analysis_screen.dart';

/// 메인 쉘 스크린: 사이드바 + 컨텐츠 영역 + 상태 바를 구성한다.
class ShellScreen extends StatefulWidget {
  const ShellScreen({super.key});

  @override
  State<ShellScreen> createState() => _ShellScreenState();
}

class _ShellScreenState extends State<ShellScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<SettingsProvider>().refreshUnreadCount();
    });
  }

  Widget _buildScreenForSection(NavSection section) {
    switch (section) {
      case NavSection.overview:
        return const OverviewScreen();
      case NavSection.trading:
        return const TradingScreen();
      case NavSection.risk:
        return const RiskCenterScreen();
      case NavSection.analytics:
        return const AnalyticsScreen();
      case NavSection.rsi:
        return const RsiScreen();
      case NavSection.stockAnalysis:
        return const StockAnalysisScreen();
      case NavSection.reports:
        return const ReportsScreen();
      case NavSection.tradeReasoning:
        return const TradeReasoningScreen();
      case NavSection.news:
        return const NewsScreen();
      case NavSection.universe:
        return const UniverseScreen();
      case NavSection.agents:
        return const AgentTeamScreen();
      case NavSection.principles:
        return const PrinciplesScreen();
      case NavSection.settings:
        return const SettingsScreen();
    }
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Consumer<EmergencyProvider>(
      builder: (context, emergencyProvider, _) {
        final isEmergency = emergencyProvider.isEmergencyStopped;

        return Stack(
          children: [
            // 메인 레이아웃
            Container(
              decoration: isEmergency
                  ? BoxDecoration(
                      border: Border.all(
                        color: tc.loss.withValues(alpha: 0.5),
                        width: 2,
                      ),
                    )
                  : null,
              child: Scaffold(
                backgroundColor: tc.background,
                appBar: _buildAppBar(context),
                body: Column(
                  children: [
                    // 긴급 정지 배너
                    if (isEmergency) const _EmergencyBanner(),
                    // 메인 컨텐츠
                    Expanded(
                      child: Row(
                        children: [
                          // 사이드바
                          const SidebarNav(),
                          // 컨텐츠 + 알림 패널
                          Expanded(
                            child: Consumer<NavigationProvider>(
                              builder: (context, navProvider, _) {
                                return Row(
                                  children: [
                                    Expanded(
                                      child: AnimatedSwitcher(
                                        duration: const Duration(milliseconds: 250),
                                        switchInCurve: Curves.easeOutCubic,
                                        child: KeyedSubtree(
                                          key: ValueKey(navProvider.currentSection),
                                          child: _buildScreenForSection(
                                              navProvider.currentSection),
                                        ),
                                      ),
                                    ),
                                    // 알림 패널 (슬라이드 아웃)
                                    if (navProvider.alertPanelOpen)
                                      const AlertPanel(),
                                  ],
                                );
                              },
                            ),
                          ),
                        ],
                      ),
                    ),
                    // 하단 상태 바
                    const StatusBar(),
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  PreferredSizeWidget _buildAppBar(BuildContext context) {
    final tc = context.tc;
    return AppBar(
      backgroundColor: tc.surface,
      elevation: 0,
      toolbarHeight: 52,
      title: Consumer<LocaleProvider>(
        builder: (context, locale, _) {
          return Row(
            children: [
              Icon(Icons.auto_graph_rounded, size: 20, color: tc.primary),
              AppSpacing.hGapSm,
              Text(locale.t('app_title'), style: AppTypography.displaySmall),
            ],
          );
        },
      ),
      actions: [
        // 언어 토글 버튼
        Consumer<LocaleProvider>(
          builder: (context, locale, _) {
            return IconButton(
              icon: Text(
                locale.isKorean ? 'EN' : 'KR',
                style: AppTypography.labelMedium.copyWith(
                  color: tc.textSecondary,
                  fontSize: 12,
                ),
              ),
              tooltip:
                  locale.isKorean ? 'Switch to English' : '한국어로 전환',
              onPressed: () => locale.toggleLocale(),
            );
          },
        ),
        // 알림 벨 아이콘
        Consumer2<SettingsProvider, NavigationProvider>(
          builder: (context, settingsProvider, navProvider, _) {
            return Stack(
              children: [
                IconButton(
                  icon: Icon(
                    navProvider.alertPanelOpen
                        ? Icons.notifications_rounded
                        : Icons.notifications_none_rounded,
                    size: 22,
                    color: navProvider.alertPanelOpen
                        ? tc.primary
                        : tc.textSecondary,
                  ),
                  tooltip: context.read<LocaleProvider>().t('alerts'),
                  onPressed: () {
                    navProvider.toggleAlertPanel();
                  },
                ),
                if (settingsProvider.unreadCount > 0)
                  Positioned(
                    right: 8,
                    top: 8,
                    child: Container(
                      padding: const EdgeInsets.all(3),
                      decoration: BoxDecoration(
                        color: tc.loss,
                        shape: BoxShape.circle,
                      ),
                      child: Text(
                        settingsProvider.unreadCount > 9
                            ? '9+'
                            : '${settingsProvider.unreadCount}',
                        style: const TextStyle(
                          fontSize: 9,
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ),
              ],
            );
          },
        ),
        const SizedBox(width: 4),
        // 긴급 정지 버튼 (항상 표시)
        const EmergencyButton(),
        const SizedBox(width: 8),
      ],
      bottom: PreferredSize(
        preferredSize: const Size.fromHeight(1),
        child: Container(
          height: 1,
          color: tc.surfaceBorder.withValues(alpha: 0.2),
        ),
      ),
    );
  }
}

/// 긴급 정지 활성 시 상단 배너이다.
class _EmergencyBanner extends StatelessWidget {
  const _EmergencyBanner();

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final t = context.watch<LocaleProvider>().t;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      color: tc.loss.withValues(alpha: 0.15),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.warning_rounded, size: 16, color: tc.loss),
          AppSpacing.hGapSm,
          Text(
            t('emergency_stop_banner'),
            style: AppTypography.labelLarge.copyWith(
              color: tc.loss,
              fontSize: 13,
            ),
          ),
          AppSpacing.hGapSm,
          Icon(Icons.warning_rounded, size: 16, color: tc.loss),
        ],
      ),
    );
  }
}
