import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/report_provider.dart';
import '../providers/locale_provider.dart';
import '../models/report_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/section_header.dart';
import '../widgets/empty_state.dart';
import '../animations/animation_utils.dart';

/// 일간 리포트 화면이다.
class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key});

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ReportProvider>().loadDates();
    });
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Scaffold(
      backgroundColor: context.tc.background,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 헤더
          Container(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 16),
            decoration: BoxDecoration(
              color: context.tc.background,
              border: Border(
                bottom: BorderSide(
                  color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                  width: 1,
                ),
              ),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(t('daily_reports'),
                          style: AppTypography.displayMedium),
                      AppSpacing.vGapXs,
                      Text(
                        '거래 성과 일간 분석 리포트',
                        style: AppTypography.bodySmall,
                      ),
                    ],
                  ),
                ),
                IconButton(
                  icon: Icon(Icons.refresh_rounded,
                      size: 20, color: context.tc.textTertiary),
                  onPressed: () => context.read<ReportProvider>().refresh(),
                  tooltip: t('refresh'),
                ),
              ],
            ),
          ),
          // 날짜 선택기
          _DateSelector(),
          // 리포트 컨텐츠
          Expanded(
            child: _ReportContent(),
          ),
        ],
      ),
    );
  }
}

/// 날짜 선택 가로 스크롤 위젯이다.
class _DateSelector extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    context.watch<LocaleProvider>().t;
    return Consumer<ReportProvider>(
      builder: (context, provider, _) {
        if (provider.availableDates == null && provider.isLoading) {
          return Container(
            height: 56,
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 20),
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: 5,
              separatorBuilder: (_, __) => AppSpacing.hGapSm,
              itemBuilder: (_, __) => ShimmerLoading(
                width: 80,
                height: 36,
                borderRadius: AppSpacing.borderRadiusFull,
              ),
            ),
          );
        }

        final dates = provider.availableDates ?? [];
        if (dates.isEmpty && !provider.isLoading) {
          return Container(
            height: 56,
            alignment: Alignment.centerLeft,
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: Text(
              '날짜 정보 없음',
              style: AppTypography.bodySmall,
            ),
          );
        }

        return Container(
          height: 56,
          padding: const EdgeInsets.symmetric(vertical: 8),
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(
                color: context.tc.surfaceBorder.withValues(alpha: 0.2),
                width: 1,
              ),
            ),
          ),
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 20),
            itemCount: dates.length,
            separatorBuilder: (_, __) => AppSpacing.hGapSm,
            itemBuilder: (context, index) {
              final dateObj = dates[index];
              final isSelected = provider.selectedDate == dateObj.date;
              return GestureDetector(
                onTap: () => provider.selectDate(dateObj.date),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  padding: const EdgeInsets.symmetric(
                      horizontal: 14, vertical: 4),
                  decoration: BoxDecoration(
                    color: isSelected
                        ? context.tc.primary.withValues(alpha: 0.15)
                        : context.tc.surface,
                    borderRadius: AppSpacing.borderRadiusFull,
                    border: Border.all(
                      color: isSelected
                          ? context.tc.primary.withValues(alpha: 0.4)
                          : context.tc.surfaceBorder.withValues(alpha: 0.3),
                      width: 1,
                    ),
                  ),
                  child: Text(
                    _formatDate(dateObj.date),
                    style: AppTypography.labelMedium.copyWith(
                      color: isSelected
                          ? context.tc.primary
                          : context.tc.textSecondary,
                      fontSize: 12,
                    ),
                  ),
                ),
              );
            },
          ),
        );
      },
    );
  }

  String _formatDate(String date) {
    final parts = date.split('-');
    if (parts.length >= 3) {
      return '${parts[1]}/${parts[2]}';
    }
    return date;
  }
}

/// 리포트 컨텐츠 영역이다.
class _ReportContent extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Consumer<ReportProvider>(
      builder: (context, provider, _) {
        if (provider.isLoading && provider.currentReport == null) {
          return Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: [
                ShimmerLoading(
                    width: double.infinity,
                    height: 120,
                    borderRadius: AppSpacing.borderRadiusLg),
                AppSpacing.vGapLg,
                ShimmerLoading(
                    width: double.infinity,
                    height: 200,
                    borderRadius: AppSpacing.borderRadiusLg),
                AppSpacing.vGapLg,
                ShimmerLoading(
                    width: double.infinity,
                    height: 160,
                    borderRadius: AppSpacing.borderRadiusLg),
              ],
            ),
          );
        }

        if (provider.error != null && provider.currentReport == null) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.cloud_off_rounded,
                    size: 48, color: context.tc.textTertiary),
                AppSpacing.vGapLg,
                Text('데이터 로드 실패', style: AppTypography.headlineMedium),
                AppSpacing.vGapSm,
                Text(provider.error ?? '', style: AppTypography.bodySmall),
                AppSpacing.vGapXxl,
                ElevatedButton.icon(
                  onPressed: () => provider.refresh(),
                  icon: const Icon(Icons.refresh_rounded, size: 18),
                  label: Text(t('retry')),
                ),
              ],
            ),
          );
        }

        final report = provider.currentReport;
        if (report == null) {
          return EmptyState(
            icon: Icons.article_rounded,
            title: t('no_report_data'),
          );
        }

        // 거래 없는 날짜
        if (report.summary.totalTrades == 0) {
          return EmptyState(
            icon: Icons.bar_chart_rounded,
            title: t('no_report_data'),
            subtitle: report.date,
          );
        }

        return SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _SummaryCard(report: report),
              AppSpacing.vGapLg,
              _ByTickerCard(report: report),
              AppSpacing.vGapLg,
              _ByExitReasonCard(report: report),
              AppSpacing.vGapLg,
              _ByHourCard(report: report),
              AppSpacing.vGapLg,
              _RiskMetricsCard(report: report),
              if (report.indicatorFeedback case final feedback?) ...[
                AppSpacing.vGapLg,
                _IndicatorFeedbackCard(feedback: feedback),
              ],
              AppSpacing.vGapXxl,
            ],
          ),
        );
      },
    );
  }
}

/// 요약 카드이다.
class _SummaryCard extends StatelessWidget {
  final DailyReport report;

  const _SummaryCard({required this.report});

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    final s = report.summary;

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(
            title: '${t('daily_report')}  ${_fullDate(report.date)}',
          ),
          AppSpacing.vGapMd,
          Row(
            children: [
              _statBox('총 거래', '${s.totalTrades}', context.tc.textPrimary),
              _statBox(t('win_rate'), '${s.winRate.toStringAsFixed(1)}%',
                  s.winRate >= 50 ? context.tc.profit : context.tc.warning),
              _statBox(
                t('total_pnl'),
                '${s.totalPnl >= 0 ? '+\$' : '-\$'}${s.totalPnl.abs().toStringAsFixed(2)}',
                context.tc.pnlColor(s.totalPnl),
              ),
              _statBox(
                t('avg_hold_time'),
                '${s.avgHoldMinutes}m',
                context.tc.textSecondary,
              ),
            ],
          ),
          AppSpacing.vGapMd,
          Divider(
              height: 1, color: context.tc.surfaceBorder.withValues(alpha: 0.3)),
          AppSpacing.vGapMd,
          Row(
            children: [
              _statBox(
                '승리',
                '${s.winningTrades}',
                context.tc.profit,
              ),
              _statBox(
                '패배',
                '${s.losingTrades}',
                context.tc.loss,
              ),
              _statBox(
                '최대 수익',
                '+${s.maxWinPct.toStringAsFixed(2)}%',
                context.tc.profit,
              ),
              _statBox(
                '최대 손실',
                '${s.maxLossPct.toStringAsFixed(2)}%',
                context.tc.loss,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _statBox(String label, String value, Color valueColor) {
    return Expanded(
      child: Column(
        children: [
          Text(
            value,
            style: AppTypography.numberSmall.copyWith(
              color: valueColor,
              fontSize: 15,
            ),
            textAlign: TextAlign.center,
          ),
          AppSpacing.vGapXs,
          Text(
            label,
            style: AppTypography.bodySmall.copyWith(fontSize: 11),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }

  String _fullDate(String date) {
    return date;
  }
}

/// 종목별 실적 카드이다.
class _ByTickerCard extends StatelessWidget {
  final DailyReport report;

  const _ByTickerCard({required this.report});

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    final tickers = report.byTicker.entries.toList();
    tickers.sort((a, b) => b.value.totalPnl.compareTo(a.value.totalPnl));

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('by_ticker')),
          AppSpacing.vGapMd,
          if (tickers.isEmpty)
            Text('데이터 없음', style: AppTypography.bodySmall)
          else
            Table(
              columnWidths: const {
                0: FlexColumnWidth(2),
                1: FlexColumnWidth(1),
                2: FlexColumnWidth(1.5),
                3: FlexColumnWidth(1.5),
              },
              children: [
                TableRow(
                  children: [
                    _th('종목', context),
                    _th('거래수', context),
                    _th('총 손익', context),
                    _th('평균 수익%', context),
                  ],
                ),
                ...tickers.map((e) => TableRow(
                      children: [
                        _td(e.key, context.tc.textPrimary, bold: true),
                        _td('${e.value.trades}', context.tc.textSecondary),
                        _td(
                          '${e.value.totalPnl >= 0 ? '+\$' : '-\$'}${e.value.totalPnl.abs().toStringAsFixed(2)}',
                          context.tc.pnlColor(e.value.totalPnl),
                        ),
                        _td(
                          '${e.value.avgPnlPct >= 0 ? '+' : ''}${e.value.avgPnlPct.toStringAsFixed(2)}%',
                          context.tc.pnlColor(e.value.avgPnlPct),
                        ),
                      ],
                    )),
              ],
            ),
        ],
      ),
    );
  }

  Widget _th(String label, BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(
          label,
          style: AppTypography.bodySmall.copyWith(
            color: context.tc.textTertiary,
            fontWeight: FontWeight.w600,
          ),
        ),
      );

  Widget _td(String value, Color color, {bool bold = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Text(
          value,
          style: AppTypography.numberSmall.copyWith(
            color: color,
            fontSize: 12,
            fontWeight: bold ? FontWeight.w700 : FontWeight.w500,
          ),
        ),
      );
}

/// 청산 사유별 카드이다.
class _ByExitReasonCard extends StatelessWidget {
  final DailyReport report;

  const _ByExitReasonCard({required this.report});

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    final reasons = report.byExitReason.entries.toList();
    reasons.sort((a, b) => b.value.compareTo(a.value));
    final total = reasons.fold<int>(0, (sum, e) => sum + e.value);

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('by_exit_reason')),
          AppSpacing.vGapMd,
          if (reasons.isEmpty)
            Text('데이터 없음', style: AppTypography.bodySmall)
          else
            ...reasons.map((e) {
              final pct = total > 0 ? e.value / total : 0.0;
              final color = _exitColor(e.key, context);
              return Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          width: 8,
                          height: 8,
                          decoration: BoxDecoration(
                            color: color,
                            shape: BoxShape.circle,
                          ),
                        ),
                        AppSpacing.hGapSm,
                        Expanded(
                          child: Text(
                            _exitLabel(e.key),
                            style: AppTypography.labelMedium,
                          ),
                        ),
                        Text(
                          '${e.value}건 (${(pct * 100).toStringAsFixed(0)}%)',
                          style: AppTypography.numberSmall.copyWith(
                            color: color,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                    AppSpacing.vGapXs,
                    ClipRRect(
                      borderRadius: AppSpacing.borderRadiusFull,
                      child: LinearProgressIndicator(
                        value: pct.toDouble(),
                        backgroundColor: context.tc.surfaceBorder,
                        valueColor:
                            AlwaysStoppedAnimation<Color>(color),
                        minHeight: 4,
                      ),
                    ),
                  ],
                ),
              );
            }),
        ],
      ),
    );
  }

  Color _exitColor(String reason, BuildContext context) {
    switch (reason.toLowerCase()) {
      case 'take_profit':
        return context.tc.profit;
      case 'stop_loss':
        return context.tc.loss;
      case 'trailing_stop':
        return context.tc.warning;
      default:
        return context.tc.chart4;
    }
  }

  String _exitLabel(String reason) {
    switch (reason.toLowerCase()) {
      case 'take_profit':
        return '익절';
      case 'stop_loss':
        return '손절';
      case 'trailing_stop':
        return '추적 손절';
      case 'manual':
        return '수동';
      case 'time_exit':
        return '시간 만료';
      default:
        return reason;
    }
  }
}

/// 시간대별 거래 카드이다.
class _ByHourCard extends StatelessWidget {
  final DailyReport report;

  const _ByHourCard({required this.report});

  @override
  Widget build(BuildContext context) {
    context.watch<LocaleProvider>().t;
    final byHour = report.byHour;
    if (byHour.isEmpty) return const SizedBox.shrink();

    final maxCount = byHour.values.isEmpty
        ? 1
        : byHour.values.reduce((a, b) => a > b ? a : b);

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: '시간대별 거래'),
          AppSpacing.vGapMd,
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: List.generate(24, (hour) {
                final count =
                    byHour[hour.toString()] ?? byHour['$hour'] ?? 0;
                final pct = maxCount > 0 ? count / maxCount : 0.0;
                final barHeight = (pct * 60).clamp(2.0, 60.0);
                final hasData = count > 0;
                return Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 3),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      if (hasData)
                        Text(
                          '$count',
                          style:
                              AppTypography.bodySmall.copyWith(fontSize: 9),
                        ),
                      AppSpacing.vGapXs,
                      AnimatedContainer(
                        duration: const Duration(milliseconds: 600),
                        width: 18,
                        height: barHeight.toDouble(),
                        decoration: BoxDecoration(
                          color: hasData
                              ? context.tc.primary.withValues(alpha: 0.7)
                              : context.tc.surface,
                          borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(3),
                          ),
                        ),
                      ),
                      AppSpacing.vGapXs,
                      Text(
                        '$hour',
                        style:
                            AppTypography.bodySmall.copyWith(fontSize: 9),
                      ),
                    ],
                  ),
                );
              }),
            ),
          ),
        ],
      ),
    );
  }
}

/// 리스크 지표 카드이다.
class _RiskMetricsCard extends StatelessWidget {
  final DailyReport report;

  const _RiskMetricsCard({required this.report});

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    final rm = report.riskMetrics;

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: '리스크 지표'),
          AppSpacing.vGapMd,
          Row(
            children: [
              _metric(
                t('max_drawdown'),
                '${rm.maxDrawdownPct.toStringAsFixed(2)}%',
                rm.maxDrawdownPct > 5
                    ? context.tc.loss
                    : context.tc.textPrimary,
              ),
              _metric(
                t('sharpe'),
                rm.sharpeEstimate.toStringAsFixed(2),
                rm.sharpeEstimate >= 1
                    ? context.tc.profit
                    : rm.sharpeEstimate >= 0
                        ? context.tc.warning
                        : context.tc.loss,
              ),
              _metric(
                '평균 신뢰도',
                '${(rm.avgConfidence * 100).toStringAsFixed(1)}%',
                rm.avgConfidence >= 0.7
                    ? context.tc.profit
                    : context.tc.warning,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _metric(String label, String value, Color color) {
    return Expanded(
      child: Column(
        children: [
          Text(
            value,
            style: AppTypography.numberMedium.copyWith(color: color),
            textAlign: TextAlign.center,
          ),
          AppSpacing.vGapXs,
          Text(
            label,
            style: AppTypography.bodySmall,
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}

/// 지표 피드백 카드이다.
class _IndicatorFeedbackCard extends StatelessWidget {
  final IndicatorFeedback feedback;

  const _IndicatorFeedbackCard({required this.feedback});

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    final indicators = feedback.indicators.entries.toList();

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('indicator_feedback')),
          if (feedback.recommendation != null) ...[
            AppSpacing.vGapMd,
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: context.tc.primary.withValues(alpha: 0.07),
                borderRadius: AppSpacing.borderRadiusMd,
                border: Border.all(
                  color: context.tc.primary.withValues(alpha: 0.2),
                ),
              ),
              child: Text(
                feedback.recommendation ?? '',
                style: AppTypography.bodyMedium.copyWith(height: 1.6),
              ),
            ),
          ],
          AppSpacing.vGapMd,
          ...indicators.map((e) {
            final perf = e.value;
            return Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        e.key.toUpperCase(),
                        style: AppTypography.labelLarge,
                      ),
                      AppSpacing.hGapMd,
                      Text(
                        '${perf.winRate.toStringAsFixed(0)}% 승률',
                        style: AppTypography.labelMedium.copyWith(
                          color: perf.winRate >= 50
                              ? context.tc.profit
                              : context.tc.loss,
                        ),
                      ),
                    ],
                  ),
                  AppSpacing.vGapXs,
                  Row(
                    children: [
                      Text(
                        '진입 수: ${perf.totalEntries}',
                        style: AppTypography.bodySmall,
                      ),
                      AppSpacing.hGapMd,
                      Text(
                        '평균 진입값: ${perf.avgEntryValue.toStringAsFixed(2)}',
                        style: AppTypography.bodySmall,
                      ),
                      AppSpacing.hGapMd,
                      Text(
                        '강세 시 평균 수익: ${perf.avgPnlWhenBullish >= 0 ? '+' : ''}${perf.avgPnlWhenBullish.toStringAsFixed(2)}%',
                        style: AppTypography.bodySmall.copyWith(
                          color: context.tc.pnlColor(perf.avgPnlWhenBullish),
                        ),
                      ),
                    ],
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
