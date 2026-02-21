import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/navigation_provider.dart';
import '../providers/settings_provider.dart';
import '../providers/locale_provider.dart';
import '../providers/theme_provider.dart';
import '../providers/dashboard_provider.dart';
import '../providers/trading_mode_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../theme/trading_colors.dart';

/// 로케일에 맞는 네비게이션 섹션 레이블을 반환한다.
String _getNavLabel(NavSection section, LocaleProvider locale) {
  switch (section) {
    case NavSection.overview:
      return locale.t('nav_overview');
    case NavSection.trading:
      return locale.t('nav_trading');
    case NavSection.risk:
      return locale.t('nav_risk');
    case NavSection.analytics:
      return locale.t('nav_analytics');
    case NavSection.rsi:
      return locale.t('nav_rsi');
    case NavSection.stockAnalysis:
      return locale.t('nav_stock_analysis');
    case NavSection.reports:
      return locale.t('nav_reports');
    case NavSection.tradeReasoning:
      return locale.t('nav_trade_reasoning');
    case NavSection.news:
      return locale.t('nav_news');
    case NavSection.universe:
      return locale.t('nav_universe');
    case NavSection.agents:
      return locale.t('nav_agents');
    case NavSection.principles:
      return locale.t('nav_principles');
    case NavSection.settings:
      return locale.t('nav_settings');
  }
}

/// 데스크탑 사이드바 네비게이션 위젯이다.
class SidebarNav extends StatelessWidget {
  const SidebarNav({super.key});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Container(
      width: 220,
      decoration: BoxDecoration(
        color: tc.surface,
        border: Border(
          right: BorderSide(
            color: tc.surfaceBorder.withValues(alpha: 0.3),
            width: 1,
          ),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _buildHeader(context),
          const SizedBox(height: 8),
          Expanded(
            child: _buildNavItems(context),
          ),
          _buildFooter(context),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    final tc = context.tc;
    final locale = context.watch<LocaleProvider>();
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 16),
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(
            color: tc.surfaceBorder.withValues(alpha: 0.2),
            width: 1,
          ),
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: tc.primary.withValues(alpha: 0.15),
              borderRadius: AppSpacing.borderRadiusMd,
            ),
            child: Icon(
              Icons.auto_graph_rounded,
              size: 18,
              color: tc.primary,
            ),
          ),
          AppSpacing.hGapMd,
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  locale.t('sidebar_title'),
                  style: AppTypography.labelLarge.copyWith(
                    color: tc.textPrimary,
                  ),
                ),
                Text(
                  locale.t('sidebar_subtitle'),
                  style: AppTypography.bodySmall.copyWith(
                    fontSize: 11,
                    color: tc.textTertiary,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildNavItems(BuildContext context) {
    return Consumer3<NavigationProvider, SettingsProvider, LocaleProvider>(
      builder: (context, navProvider, settingsProvider, locale, _) {
        return ListView(
          padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 10),
          children: NavSection.values.map((section) {
            final isSelected = navProvider.currentSection == section;
            return _NavItem(
              section: section,
              isSelected: isSelected,
              label: _getNavLabel(section, locale),
              badge: section == NavSection.overview &&
                      settingsProvider.unreadCount > 0
                  ? settingsProvider.unreadCount
                  : null,
              onTap: () => navProvider.navigateTo(section),
            );
          }).toList(),
        );
      },
    );
  }

  Widget _buildFooter(BuildContext context) {
    final tc = context.tc;
    final locale = context.watch<LocaleProvider>();
    final themeProvider = context.watch<ThemeProvider>();
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      decoration: BoxDecoration(
        border: Border(
          top: BorderSide(
            color: tc.surfaceBorder.withValues(alpha: 0.2),
            width: 1,
          ),
        ),
      ),
      child: Column(
        children: [
          // 투자 모드 표시 배지
          _buildModeBadge(context, locale),
          const SizedBox(height: 6),
          // 포트폴리오 스냅샷 (항상 보이는 잔액 요약)
          _buildPortfolioSnapshot(context),
          const SizedBox(height: 8),
          // 테마 토글 버튼
          Row(
            children: [
              Expanded(
                child: InkWell(
                  onTap: () => themeProvider.toggleTheme(),
                  borderRadius: AppSpacing.borderRadiusMd,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 10, vertical: 7),
                    decoration: BoxDecoration(
                      color: tc.surfaceElevated,
                      borderRadius: AppSpacing.borderRadiusMd,
                      border: Border.all(
                        color: tc.surfaceBorder.withValues(alpha: 0.4),
                        width: 1,
                      ),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          themeProvider.isDark
                              ? Icons.light_mode_rounded
                              : Icons.dark_mode_rounded,
                          size: 14,
                          color: tc.textSecondary,
                        ),
                        const SizedBox(width: 6),
                        Text(
                          themeProvider.isDark
                              ? locale.t('theme_light')
                              : locale.t('theme_dark'),
                          style: AppTypography.bodySmall.copyWith(
                            fontSize: 11,
                            color: tc.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            locale.t('sidebar_footer'),
            style: AppTypography.bodySmall.copyWith(
              fontSize: 10,
              color: tc.textTertiary,
            ),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }

  /// 현재 투자 모드(모의/실전)를 사이드바에 표시하는 배지이다.
  Widget _buildModeBadge(BuildContext context, LocaleProvider locale) {
    final tc = context.tc;
    return Consumer<TradingModeProvider>(
      builder: (context, modeProvider, _) {
        final isVirtual = modeProvider.isVirtual;
        final modeColor = isVirtual ? tc.primary : tc.warning;
        final modeLabel = isVirtual
            ? locale.t('virtual_trading')
            : locale.t('real_trading');
        final modeIcon =
            isVirtual ? Icons.science_rounded : Icons.attach_money_rounded;

        return GestureDetector(
          onTap: () => modeProvider.toggle(),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 220),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: modeColor.withValues(alpha: 0.10),
              borderRadius: AppSpacing.borderRadiusMd,
              border: Border.all(
                color: modeColor.withValues(alpha: 0.30),
                width: 1,
              ),
            ),
            child: Row(
              children: [
                Icon(modeIcon, size: 12, color: modeColor),
                const SizedBox(width: 5),
                Expanded(
                  child: Text(
                    modeLabel,
                    style: AppTypography.bodySmall.copyWith(
                      fontSize: 11,
                      color: modeColor,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                // 탭하면 모드 전환 힌트 아이콘
                Icon(
                  Icons.swap_horiz_rounded,
                  size: 12,
                  color: modeColor.withValues(alpha: 0.60),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  /// 사이드바 하단에 항상 표시되는 포트폴리오 간략 요약이다.
  Widget _buildPortfolioSnapshot(BuildContext context) {
    final tc = context.tc;
    return Consumer<DashboardProvider>(
      builder: (context, provider, _) {
        final summary = provider.summary;
        final fmt = NumberFormat.currency(symbol: '\$', decimalDigits: 0);

        if (summary == null) {
          return Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            decoration: BoxDecoration(
              color: tc.surfaceElevated,
              borderRadius: AppSpacing.borderRadiusMd,
              border: Border.all(
                color: tc.surfaceBorder.withValues(alpha: 0.3),
              ),
            ),
            child: Row(
              children: [
                Icon(
                  Icons.account_balance_wallet_rounded,
                  size: 14,
                  color: tc.textTertiary,
                ),
                const SizedBox(width: 6),
                Text(
                  '--',
                  style: AppTypography.bodySmall.copyWith(
                    fontSize: 11,
                    color: tc.textTertiary,
                  ),
                ),
              ],
            ),
          );
        }

        final isProfit = summary.todayPnl >= 0;
        final pnlColor = tc.pnlColor(summary.todayPnl);
        final pnlSign = isProfit ? '+' : '';

        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            color: tc.primary.withValues(alpha: 0.06),
            borderRadius: AppSpacing.borderRadiusMd,
            border: Border.all(
              color: tc.primary.withValues(alpha: 0.15),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 총 자산 행
              Row(
                children: [
                  Icon(
                    Icons.account_balance_rounded,
                    size: 12,
                    color: tc.primary,
                  ),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      fmt.format(summary.totalAsset),
                      style: AppTypography.numberSmall.copyWith(
                        fontSize: 12,
                        color: tc.textPrimary,
                        fontWeight: FontWeight.w700,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              // 수익률 + 현금 행
              Row(
                children: [
                  // 오늘 수익률
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 5, vertical: 1),
                    decoration: BoxDecoration(
                      color: pnlColor.withValues(alpha: 0.12),
                      borderRadius: AppSpacing.borderRadiusSm,
                    ),
                    child: Text(
                      '$pnlSign${summary.todayPnlPct.toStringAsFixed(1)}%',
                      style: AppTypography.bodySmall.copyWith(
                        fontSize: 10,
                        color: pnlColor,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  const SizedBox(width: 6),
                  // 현금 잔액
                  Expanded(
                    child: Row(
                      children: [
                        Icon(
                          Icons.account_balance_wallet_rounded,
                          size: 10,
                          color: tc.textTertiary,
                        ),
                        const SizedBox(width: 3),
                        Expanded(
                          child: Text(
                            fmt.format(summary.cash),
                            style: AppTypography.bodySmall.copyWith(
                              fontSize: 10,
                              color: tc.textTertiary,
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}

class _NavItem extends StatelessWidget {
  final NavSection section;
  final bool isSelected;
  final String label;
  final int? badge;
  final VoidCallback onTap;

  const _NavItem({
    required this.section,
    required this.isSelected,
    required this.label,
    this.badge,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Material(
        color: Colors.transparent,
        borderRadius: AppSpacing.borderRadiusMd,
        child: InkWell(
          onTap: onTap,
          borderRadius: AppSpacing.borderRadiusMd,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: isSelected
                  ? tc.primary.withValues(alpha: 0.12)
                  : Colors.transparent,
              borderRadius: AppSpacing.borderRadiusMd,
              border: isSelected
                  ? Border.all(
                      color: tc.primary.withValues(alpha: 0.2),
                      width: 1,
                    )
                  : null,
            ),
            child: Row(
              children: [
                Icon(
                  isSelected ? section.activeIcon : section.icon,
                  size: 18,
                  color: isSelected ? tc.primary : tc.textTertiary,
                ),
                AppSpacing.hGapMd,
                Expanded(
                  child: Text(
                    label,
                    style: AppTypography.labelLarge.copyWith(
                      color: isSelected ? tc.primary : tc.textSecondary,
                      fontSize: 13,
                    ),
                  ),
                ),
                if (badge != null && (badge ?? 0) > 0)
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: tc.loss,
                      borderRadius: AppSpacing.borderRadiusFull,
                    ),
                    child: Text(
                      (badge ?? 0) > 99 ? '99+' : '$badge',
                      style: AppTypography.bodySmall.copyWith(
                        fontSize: 10,
                        color: Colors.white,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
