import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/chart_provider.dart';
import '../providers/profit_target_provider.dart';
import '../providers/benchmark_provider.dart';
import '../providers/trade_provider.dart';
import '../providers/locale_provider.dart';
import '../models/profit_target_models.dart';
import '../theme/app_typography.dart';
import '../theme/trading_colors.dart';
import '../theme/chart_colors.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/section_header.dart';
import '../widgets/empty_state.dart';
import '../widgets/pnl_line_chart.dart';
import '../widgets/cumulative_chart.dart';
import '../widgets/drawdown_chart.dart';
import '../widgets/ticker_heatmap.dart';
import '../widgets/hourly_heatmap.dart';
import '../animations/animation_utils.dart';

class AnalyticsScreen extends StatefulWidget {
  const AnalyticsScreen({super.key});

  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 4, vsync: this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ChartProvider>().loadAllCharts();
      context.read<ProfitTargetProvider>().loadStatus();
      context.read<ProfitTargetProvider>().loadHistory();
      context.read<BenchmarkProvider>().loadAll();
      context.read<TradeProvider>().loadDailyReport(
        _todayString(),
      );
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  String _todayString() {
    final now = DateTime.now();
    return '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Scaffold(
      backgroundColor: context.tc.background,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 헤더 + 탭
          Container(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
            decoration: BoxDecoration(
              color: context.tc.background,
              border: Border(
                bottom: BorderSide(
                  color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                  width: 1,
                ),
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(t('analytics'), style: AppTypography.displayMedium),
                AppSpacing.vGapMd,
                TabBar(
                  controller: _tabController,
                  isScrollable: true,
                  tabAlignment: TabAlignment.start,
                  tabs: [
                    Tab(text: t('charts')),
                    Tab(text: t('profit_target')),
                    Tab(text: t('ai_reports')),
                    Tab(text: t('benchmark')),
                  ],
                ),
              ],
            ),
          ),
          // 탭 컨텐츠
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                _ChartsTab(),
                _ProfitTargetTab(),
                _AiReportsTab(),
                _BenchmarkTab(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── 차트 탭 ──

class _ChartsTab extends StatefulWidget {
  @override
  State<_ChartsTab> createState() => _ChartsTabState();
}

class _ChartsTabState extends State<_ChartsTab> {
  String _selectedChart = 'pnl';

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Consumer<ChartProvider>(
      builder: (context, provider, _) {
        return Column(
          children: [
            // 차트 선택 버튼
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: [
                    _chartButton('pnl', t('daily_pnl')),
                    AppSpacing.hGapSm,
                    _chartButton('cumulative', t('cumulative_chart')),
                    AppSpacing.hGapSm,
                    _chartButton('drawdown', t('drawdown')),
                    AppSpacing.hGapSm,
                    _chartButton('heatmap_ticker', t('ticker_heatmap')),
                    AppSpacing.hGapSm,
                    _chartButton('heatmap_hourly', t('hourly_heatmap')),
                  ],
                ),
              ),
            ),
            // 차트 영역
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                child: _buildSelectedChart(provider),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _chartButton(String id, String label) {
    final isSelected = _selectedChart == id;
    return InkWell(
      onTap: () => setState(() => _selectedChart = id),
      borderRadius: AppSpacing.borderRadiusMd,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: isSelected
              ? context.tc.primary.withValues(alpha: 0.12)
              : context.tc.surface,
          borderRadius: AppSpacing.borderRadiusMd,
          border: Border.all(
            color: isSelected
                ? context.tc.primary.withValues(alpha: 0.3)
                : context.tc.surfaceBorder.withValues(alpha: 0.3),
          ),
        ),
        child: Text(
          label,
          style: AppTypography.labelMedium.copyWith(
            color: isSelected ? context.tc.primary : context.tc.textSecondary,
          ),
        ),
      ),
    );
  }

  Widget _buildSelectedChart(ChartProvider provider) {
    final t = context.watch<LocaleProvider>().t;
    if (provider.isLoading) {
      return Column(
        children: [
          AppSpacing.vGapLg,
          ShimmerLoading(
            width: double.infinity,
            height: 300,
            borderRadius: AppSpacing.borderRadiusLg,
          ),
        ],
      );
    }
    if (provider.error != null) {
      return ErrorState(
        message: provider.error ?? '',
        onRetry: () => provider.refresh(),
      );
    }

    Widget chart;
    String title;

    switch (_selectedChart) {
      case 'pnl':
        title = t('daily_returns');
        chart = provider.dailyReturns.isEmpty
            ? EmptyState(
                icon: Icons.bar_chart_rounded,
                title: t('no_return_data'),
              )
            : PnlLineChart(data: provider.dailyReturns);
        break;
      case 'cumulative':
        title = t('cumulative_returns');
        chart = provider.cumulativeReturns.isEmpty
            ? EmptyState(
                icon: Icons.show_chart_rounded,
                title: t('no_cumulative_data'),
              )
            : CumulativeChart(data: provider.cumulativeReturns);
        break;
      case 'drawdown':
        title = t('max_drawdown');
        chart = provider.drawdown.isEmpty
            ? EmptyState(
                icon: Icons.trending_down_rounded,
                title: t('no_drawdown_data'),
              )
            : DrawdownChart(data: provider.drawdown);
        break;
      case 'heatmap_ticker':
        title = t('ticker_pnl_heatmap');
        chart = provider.tickerHeatmap.isEmpty
            ? EmptyState(
                icon: Icons.grid_view_rounded,
                title: t('no_heatmap_data'),
              )
            : TickerHeatmap(data: provider.tickerHeatmap);
        break;
      case 'heatmap_hourly':
        title = t('hourly_pnl_heatmap');
        chart = provider.hourlyHeatmap.isEmpty
            ? EmptyState(
                icon: Icons.access_time_rounded,
                title: t('no_hourly_data'),
              )
            : HourlyHeatmap(data: provider.hourlyHeatmap);
        break;
      default:
        title = t('charts');
        chart = const SizedBox.shrink();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AppSpacing.vGapLg,
        SectionHeader(
          title: title,
          action: IconButton(
            icon: Icon(Icons.refresh_rounded,
                size: 18, color: context.tc.textTertiary),
            onPressed: () => provider.refresh(),
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
          ),
        ),
        GlassCard(
          padding: const EdgeInsets.fromLTRB(16, 16, 8, 8),
          child: SizedBox(
            height: 300,
            child: chart,
          ),
        ),
      ],
    );
  }
}

// ── 수익 목표 탭 ──

class _ProfitTargetTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer2<ProfitTargetProvider, LocaleProvider>(
      builder: (context, provider, locale, _) {
        final t = locale.t;
        if (provider.isLoading && provider.status == null) {
          return Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: [
                ShimmerLoading(
                    width: double.infinity,
                    height: 260,
                    borderRadius: AppSpacing.borderRadiusLg),
                AppSpacing.vGapLg,
                ShimmerLoading(
                    width: double.infinity,
                    height: 120,
                    borderRadius: AppSpacing.borderRadiusLg),
              ],
            ),
          );
        }
        if (provider.error != null && provider.status == null) {
          return ErrorState(
            message: provider.error ?? '',
            onRetry: () => provider.refresh(),
          );
        }

        final status = provider.status;
        if (status == null) {
          return EmptyState(
            icon: Icons.track_changes_rounded,
            title: t('no_data_available'),
          );
        }

        return SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: LayoutBuilder(
            builder: (context, constraints) {
              if (constraints.maxWidth >= 800) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Column(
                        children: [
                          _buildProgressRing(context, status, t),
                          AppSpacing.vGapLg,
                          _buildDailyCard(context, status, t),
                        ],
                      ),
                    ),
                    AppSpacing.hGapLg,
                    Expanded(
                      child: Column(
                        children: [
                          _buildAggressionSelector(context, provider, t),
                          AppSpacing.vGapLg,
                          _buildMonthlyHistory(context, provider.history, t),
                        ],
                      ),
                    ),
                  ],
                );
              }
              return Column(
                children: [
                  _buildProgressRing(context, status, t),
                  AppSpacing.vGapLg,
                  _buildDailyCard(context, status, t),
                  AppSpacing.vGapLg,
                  _buildAggressionSelector(context, provider, t),
                  AppSpacing.vGapLg,
                  _buildMonthlyHistory(context, provider.history, t),
                ],
              );
            },
          ),
        );
      },
    );
  }

  Widget _buildProgressRing(BuildContext context, ProfitTargetStatus status,
      String Function(String) t) {
    // achievementPct는 백엔드에서 직접 제공되는 달성률 (%)이다.
    final progress = (status.achievementPct / 100).clamp(0.0, 1.0);
    final onTrack = status.achievementPct >=
        (status.timeProgress.timeRatio * 100).clamp(0.0, 100.0);
    final ringColor = onTrack ? context.tc.profit : context.tc.warning;

    return GlassCard(
      child: Column(
        children: [
          SizedBox(
            width: 160,
            height: 160,
            child: TweenAnimationBuilder<double>(
              tween: Tween(begin: 0, end: progress),
              duration: AnimDuration.chart,
              curve: AnimCurve.easeOut,
              builder: (context, value, _) {
                return CustomPaint(
                  painter: _ProgressRingPainter(
                    progress: value,
                    color: ringColor,
                    backgroundColor: context.tc.surfaceBorder,
                  ),
                  child: Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          '${(value * 100).toStringAsFixed(1)}%',
                          style: AppTypography.numberLarge.copyWith(
                            color: ringColor,
                            fontSize: 24,
                          ),
                        ),
                        Text(t('of_target'), style: AppTypography.bodySmall),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
          AppSpacing.vGapLg,
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              // 백엔드는 USD 금액을 반환한다. '$' 기호로 표시한다.
              _statCol(t('monthly_target_label'),
                  '\$${status.monthlyTargetUsd.toStringAsFixed(0)}',
                  context.tc.textPrimary),
              _statCol(
                  t('current'),
                  '${status.monthPnlUsd >= 0 ? '+\$' : '-\$'}${status.monthPnlUsd.abs().toStringAsFixed(1)}',
                  context.tc.pnlColor(status.monthPnlUsd)),
              _statCol(t('days_left'),
                  '${status.timeProgress.remainingTradingDays}',
                  context.tc.textPrimary),
            ],
          ),
        ],
      ),
    );
  }

  Widget _statCol(String label, String value, Color valueColor) {
    return Column(
      children: [
        Text(label, style: AppTypography.bodySmall),
        AppSpacing.vGapXs,
        Text(value,
            style: AppTypography.numberSmall.copyWith(color: valueColor)),
      ],
    );
  }

  Widget _buildDailyCard(BuildContext context, ProfitTargetStatus status,
      String Function(String) t) {
    // 백엔드는 remainingDailyTargetUsd (USD 금액)를 반환한다.
    // todayPct는 백엔드가 제공하지 않으므로 achievementPct로 진행률을 표시한다.
    final dailyTargetUsd = status.remainingDailyTargetUsd;
    final progressValue =
        (status.achievementPct / 100).clamp(0.0, 1.5);
    final onTrack = status.achievementPct >=
        (status.timeProgress.timeRatio * 100).clamp(0.0, 100.0);
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('daily_target')),
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(t('target'), style: AppTypography.bodySmall),
                    Text('\$${dailyTargetUsd.toStringAsFixed(2)}',
                        style: AppTypography.numberMedium),
                  ],
                ),
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(t('achievement'), style: AppTypography.bodySmall),
                    Text(
                      '${status.achievementPct.toStringAsFixed(1)}%',
                      style: AppTypography.numberMedium.copyWith(
                        color: onTrack ? context.tc.profit : context.tc.warning,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          AppSpacing.vGapMd,
          ClipRRect(
            borderRadius: AppSpacing.borderRadiusFull,
            child: TweenAnimationBuilder<double>(
              tween: Tween(
                begin: 0,
                end: progressValue,
              ),
              duration: AnimDuration.chart,
              curve: AnimCurve.easeOut,
              builder: (context, value, _) {
                return LinearProgressIndicator(
                  value: value.clamp(0.0, 1.0),
                  backgroundColor: context.tc.surfaceBorder,
                  valueColor: AlwaysStoppedAnimation<Color>(
                    onTrack ? context.tc.profit : context.tc.warning,
                  ),
                  minHeight: 8,
                );
              },
            ),
          ),
          AppSpacing.vGapSm,
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              Icon(
                onTrack
                    ? Icons.check_circle_rounded
                    : Icons.schedule_rounded,
                size: 13,
                color: onTrack ? context.tc.profit : context.tc.warning,
              ),
              AppSpacing.hGapXs,
              Text(
                onTrack ? t('on_track') : t('behind_target'),
                style: AppTypography.bodySmall.copyWith(
                  color: onTrack ? context.tc.profit : context.tc.warning,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildAggressionSelector(BuildContext context,
      ProfitTargetProvider provider, String Function(String) t) {
    final currentLevel = provider.status?.aggressionLevel ?? 'moderate';
    const levels = ['conservative', 'moderate', 'aggressive'];

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('aggression_level')),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: levels.map((level) {
              final isSelected = level == currentLevel;
              final displayLabel = t(level);
              return ChoiceChip(
                label: Text(displayLabel),
                selected: isSelected,
                selectedColor: context.tc.primary.withValues(alpha: 0.2),
                labelStyle: AppTypography.labelMedium.copyWith(
                  color: isSelected
                      ? context.tc.primary
                      : context.tc.textSecondary,
                ),
                onSelected: (selected) {
                  if (selected) provider.setAggressionLevel(level);
                },
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  Widget _buildMonthlyHistory(BuildContext context, List<MonthlyHistory> history,
      String Function(String) t) {
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ];

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('monthly_history')),
          if (history.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 16),
              child: Text(t('no_history'),
                  style: AppTypography.bodyMedium),
            )
          else
            ...history.map((h) {
              final monthLabel = h.month >= 1 && h.month <= 12
                  ? months[h.month - 1]
                  : '?';
              return Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Row(
                  children: [
                    SizedBox(
                      width: 56,
                      child: Text('$monthLabel ${h.year}',
                          style: AppTypography.bodySmall),
                    ),
                    Expanded(
                      child: ClipRRect(
                        borderRadius: AppSpacing.borderRadiusFull,
                        child: LinearProgressIndicator(
                          // 백엔드: targetUsd, actualPnlUsd (USD 금액)
                          value: h.targetUsd != 0
                              ? (h.actualPnlUsd / h.targetUsd).clamp(0.0, 1.0)
                              : 0,
                          backgroundColor: context.tc.surfaceBorder,
                          valueColor: AlwaysStoppedAnimation<Color>(
                            h.achieved ? context.tc.profit : context.tc.loss,
                          ),
                          minHeight: 6,
                        ),
                      ),
                    ),
                    AppSpacing.hGapMd,
                    SizedBox(
                      width: 60,
                      child: Text(
                        // USD 금액으로 표시한다
                        '${h.actualPnlUsd >= 0 ? '+\$' : '-\$'}${h.actualPnlUsd.abs().toStringAsFixed(0)}',
                        style: AppTypography.numberSmall.copyWith(
                          color: context.tc.pnlColor(h.actualPnlUsd),
                          fontSize: 11,
                        ),
                        textAlign: TextAlign.right,
                      ),
                    ),
                    AppSpacing.hGapSm,
                    Icon(
                      h.achieved
                          ? Icons.check_circle_rounded
                          : Icons.cancel_rounded,
                      size: 14,
                      color: h.achieved ? context.tc.profit : context.tc.loss,
                    ),
                  ],
                ),
              );
            }),
        ],
      ),
    );
  }
}

// ── AI 리포트 탭 ──

class _AiReportsTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer2<TradeProvider, LocaleProvider>(
      builder: (context, provider, locale, _) {
        final t = locale.t;
        if (provider.isLoading && provider.reports.isEmpty) {
          return Padding(
            padding: const EdgeInsets.all(20),
            child: ShimmerLoading(
              width: double.infinity,
              height: 300,
              borderRadius: AppSpacing.borderRadiusLg,
            ),
          );
        }

        if (provider.error != null && provider.reports.isEmpty) {
          return ErrorState(
            message: provider.error ?? '',
            onRetry: () {
              final now = DateTime.now();
              final dateStr = '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';
              provider.loadDailyReport(dateStr);
            },
          );
        }

        if (provider.reports.isEmpty) {
          return EmptyState(
            icon: Icons.assessment_rounded,
            title: t('no_ai_reports'),
            subtitle: t('reports_generated_during'),
          );
        }

        final report = provider.reports.first;
        // reportType과 reportDate가 비어 있으면 빈 리포트로 판정한다.
        if (report.reportType.isEmpty && report.reportDate.isEmpty) {
          return EmptyState(
            icon: Icons.assessment_rounded,
            title: t('no_ai_reports'),
            subtitle: t('reports_generated_during'),
          );
        }

        return SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: GlassCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SectionHeader(
                  title: '${t('daily_report')} - ${report.reportDate}',
                  action: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        report.reportType.toUpperCase(),
                        style: AppTypography.labelMedium.copyWith(
                          color: context.tc.primary,
                        ),
                      ),
                      AppSpacing.hGapMd,
                      SizedBox(
                        height: 28,
                        child: IconButton(
                          icon: Icon(Icons.refresh_rounded,
                              size: 16, color: context.tc.textTertiary),
                          onPressed: () {
                            provider.loadDailyReport(report.reportDate);
                          },
                          padding: EdgeInsets.zero,
                        ),
                      ),
                    ],
                  ),
                ),
                AppSpacing.vGapMd,
                Text(
                  report.contentString,
                  style: AppTypography.bodyMedium.copyWith(height: 1.7),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

// ── 벤치마크 탭 ──

class _BenchmarkTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer2<BenchmarkProvider, LocaleProvider>(
      builder: (context, provider, locale, _) {
        final t = locale.t;
        if (provider.isLoading && provider.comparison == null) {
          return Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: [
                ShimmerLoading(
                    width: double.infinity,
                    height: 160,
                    borderRadius: AppSpacing.borderRadiusLg),
                AppSpacing.vGapLg,
                ShimmerLoading(
                    width: double.infinity,
                    height: 240,
                    borderRadius: AppSpacing.borderRadiusLg),
              ],
            ),
          );
        }

        if (provider.error != null && provider.comparison == null) {
          return ErrorState(
            message: provider.error ?? '',
            onRetry: () => provider.refresh(),
          );
        }

        if (provider.comparison == null) {
          return EmptyState(
            icon: Icons.compare_arrows_rounded,
            title: t('no_benchmark_data'),
          );
        }

        final comp = provider.comparison;
        if (comp == null) return const SizedBox.shrink();
        // summary에서 누적 수익률을 읽는다.
        // 백엔드: ai_total, spy_total, sso_total, ai_win_rate_vs_spy, ai_win_rate_vs_sso
        final summary = comp.summary;
        final aiTotal = summary.aiTotal;
        final spyTotal = summary.spyTotal;
        final ssoTotal = summary.ssoTotal;
        final aiVsSpyDiff = aiTotal - spyTotal;
        final aiVsSsoDiff = aiTotal - ssoTotal;

        return SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Column(
            children: [
              GlassCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SectionHeader(
                      title: t('performance_vs_benchmark'),
                      action: SizedBox(
                        height: 28,
                        child: IconButton(
                          icon: Icon(Icons.refresh_rounded,
                              size: 16, color: context.tc.textTertiary),
                          onPressed: () => provider.refresh(),
                          padding: EdgeInsets.zero,
                        ),
                      ),
                    ),
                    // 수익률 비교 행 (누적 수익률)
                    Row(
                      children: [
                        Expanded(
                          child: _benchmarkStat(
                            t('portfolio'),
                            '${aiTotal >= 0 ? '+' : ''}${aiTotal.toStringAsFixed(2)}%',
                            context.tc.pnlColor(aiTotal),
                          ),
                        ),
                        Expanded(
                          child: _benchmarkStat(
                            'SPY',
                            '${spyTotal >= 0 ? '+' : ''}${spyTotal.toStringAsFixed(2)}%',
                            context.tc.primary,
                          ),
                        ),
                        Expanded(
                          child: _benchmarkStat(
                            'SSO',
                            '${ssoTotal >= 0 ? '+' : ''}${ssoTotal.toStringAsFixed(2)}%',
                            ChartColors.purple,
                          ),
                        ),
                      ],
                    ),
                    Divider(
                        height: 24,
                        color: context.tc.surfaceBorder.withValues(alpha: 0.3)),
                    // AI vs 벤치마크 초과수익 및 승률
                    Row(
                      children: [
                        Expanded(
                          child: _benchmarkStat(
                            'AI vs SPY',
                            '${aiVsSpyDiff >= 0 ? '+' : ''}${aiVsSpyDiff.toStringAsFixed(2)}%',
                            context.tc.pnlColor(aiVsSpyDiff),
                          ),
                        ),
                        Expanded(
                          child: _benchmarkStat(
                            'AI vs SSO',
                            '${aiVsSsoDiff >= 0 ? '+' : ''}${aiVsSsoDiff.toStringAsFixed(2)}%',
                            context.tc.pnlColor(aiVsSsoDiff),
                          ),
                        ),
                        Expanded(
                          child: _benchmarkStat(
                            t('win_rate'),
                            '${summary.aiWinRateVsSpy.toStringAsFixed(1)}%',
                            summary.aiWinRateVsSpy > 50
                                ? context.tc.profit
                                : context.tc.warning,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _benchmarkStat(String label, String value, Color valueColor) {
    return Column(
      children: [
        Text(label, style: AppTypography.bodySmall),
        AppSpacing.vGapXs,
        Text(
          value,
          style: AppTypography.numberSmall.copyWith(color: valueColor),
        ),
      ],
    );
  }
}

// ── 진행 링 페인터 ──

class _ProgressRingPainter extends CustomPainter {
  final double progress;
  final Color color;
  final Color backgroundColor;

  _ProgressRingPainter({
    required this.progress,
    required this.color,
    required this.backgroundColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = size.width / 2 - 10;
    const strokeWidth = 10.0;

    final bgPaint = Paint()
      ..color = backgroundColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;

    canvas.drawCircle(center, radius, bgPaint);

    final progressPaint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;

    final sweepAngle = 2 * math.pi * progress;
    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      -math.pi / 2,
      sweepAngle,
      false,
      progressPaint,
    );
  }

  @override
  bool shouldRepaint(covariant _ProgressRingPainter oldDelegate) {
    return oldDelegate.progress != progress || oldDelegate.color != color;
  }
}
