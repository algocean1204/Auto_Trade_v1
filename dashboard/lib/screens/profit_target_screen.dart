import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/profit_target_provider.dart';
import '../providers/locale_provider.dart';
import '../models/profit_target_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../animations/animation_utils.dart';

class ProfitTargetScreen extends StatefulWidget {
  const ProfitTargetScreen({super.key});

  @override
  State<ProfitTargetScreen> createState() => _ProfitTargetScreenState();
}

class _ProfitTargetScreenState extends State<ProfitTargetScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final provider = context.read<ProfitTargetProvider>();
      provider.loadStatus();
      provider.loadHistory();
    });
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Scaffold(
      appBar: AppBar(
        title: Text(t('profit_target'), style: AppTypography.displaySmall),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded, size: 22),
            tooltip: t('refresh'),
            onPressed: () {
              context.read<ProfitTargetProvider>().refresh();
            },
          ),
        ],
      ),
      body: Consumer<ProfitTargetProvider>(
        builder: (context, provider, child) {
          if (provider.isLoading && provider.status == null) {
            return _buildLoadingSkeleton();
          }

          if (provider.error != null && provider.status == null) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.cloud_off_rounded, size: 48, color: context.tc.textTertiary),
                  AppSpacing.vGapLg,
                  Text('${t('connection_error')}: ${provider.error}',
                      style: AppTypography.bodyMedium),
                  AppSpacing.vGapLg,
                  ElevatedButton(
                    onPressed: () => provider.refresh(),
                    child: Text(t('retry')),
                  ),
                ],
              ),
            );
          }

          final status = provider.status;
          if (status == null) {
            return Center(
              child: Text(t('no_data_available'), style: AppTypography.bodyLarge),
            );
          }

          return RefreshIndicator(
            onRefresh: () => provider.refresh(),
            color: context.tc.primary,
            backgroundColor: context.tc.surfaceElevated,
            child: ListView(
              padding: AppSpacing.paddingScreen,
              children: [
                StaggeredFadeSlide(
                  index: 0,
                  child: _buildProgressRing(status, t),
                ),
                AppSpacing.vGapLg,
                StaggeredFadeSlide(
                  index: 1,
                  child: _buildDailyTargetCard(status, t),
                ),
                AppSpacing.vGapLg,
                StaggeredFadeSlide(
                  index: 2,
                  child: _buildAggressionSelector(provider, t),
                ),
                AppSpacing.vGapLg,
                StaggeredFadeSlide(
                  index: 3,
                  child: _buildMonthlyHistory(provider.history, t),
                ),
                AppSpacing.vGapXxl,
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildLoadingSkeleton() {
    return Padding(
      padding: AppSpacing.paddingScreen,
      child: Column(
        children: [
          ShimmerLoading(
            width: double.infinity,
            height: 260,
            borderRadius: AppSpacing.borderRadiusLg,
          ),
          AppSpacing.vGapLg,
          ShimmerLoading(
            width: double.infinity,
            height: 120,
            borderRadius: AppSpacing.borderRadiusLg,
          ),
        ],
      ),
    );
  }

  Widget _buildProgressRing(ProfitTargetStatus status, String Function(String) t) {
    // achievementPct는 백엔드에서 직접 제공하는 달성률 (%)이다.
    final progress = (status.achievementPct / 100).clamp(0.0, 1.0);
    final onTrack = status.achievementPct >=
        (status.timeProgress.timeRatio * 100).clamp(0.0, 100.0);
    final ringColor = onTrack ? context.tc.profit : context.tc.warning;

    return GlassCard(
      child: Column(
        children: [
          SizedBox(
            width: 180,
            height: 180,
            child: TweenAnimationBuilder<double>(
              tween: Tween(begin: 0, end: progress),
              duration: AnimDuration.chart,
              curve: AnimCurve.easeOut,
              builder: (context, value, child) {
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
                          ),
                        ),
                        Text(
                          t('of_target'),
                          style: AppTypography.bodySmall,
                        ),
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
              _buildStatColumn(
                t('monthly_target_label'),
                '\$${status.monthlyTargetUsd.toStringAsFixed(0)}',
                context.tc.textPrimary,
              ),
              _buildStatColumn(
                t('current'),
                '${status.monthPnlUsd >= 0 ? '+\$' : '-\$'}${status.monthPnlUsd.abs().toStringAsFixed(1)}',
                context.tc.pnlColor(status.monthPnlUsd),
              ),
              _buildStatColumn(
                t('days_left'),
                '${status.timeProgress.remainingTradingDays}',
                context.tc.textPrimary,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStatColumn(String label, String value, Color valueColor) {
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

  Widget _buildDailyTargetCard(ProfitTargetStatus status, String Function(String) t) {
    // 백엔드는 remainingDailyTargetUsd (USD 금액)를 반환한다.
    // todayPct는 백엔드가 제공하지 않으므로 achievementPct로 진행률을 표시한다.
    final dailyTargetUsd = status.remainingDailyTargetUsd;
    final progressValue = (status.achievementPct / 100).clamp(0.0, 1.5);
    final onTrack = status.achievementPct >=
        (status.timeProgress.timeRatio * 100).clamp(0.0, 100.0);

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('daily_target'), style: AppTypography.headlineMedium),
          AppSpacing.vGapLg,
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(t('target'), style: AppTypography.bodySmall),
                    AppSpacing.vGapXs,
                    Text(
                      // 남은 일일 목표를 USD로 표시한다
                      '\$${dailyTargetUsd.toStringAsFixed(2)}',
                      style: AppTypography.numberMedium,
                    ),
                  ],
                ),
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(t('achievement'), style: AppTypography.bodySmall),
                    AppSpacing.vGapXs,
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
          AppSpacing.vGapLg,
          ClipRRect(
            borderRadius: AppSpacing.borderRadiusFull,
            child: TweenAnimationBuilder<double>(
              tween: Tween(
                begin: 0,
                end: progressValue,
              ),
              duration: AnimDuration.chart,
              curve: AnimCurve.easeOut,
              builder: (context, value, child) {
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
                onTrack ? Icons.check_circle_rounded : Icons.schedule_rounded,
                size: 14,
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

  Widget _buildAggressionSelector(ProfitTargetProvider provider, String Function(String) t) {
    final currentLevel = provider.status?.aggressionLevel ?? 'moderate';
    const levels = ['conservative', 'moderate', 'aggressive'];

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('aggression_level'), style: AppTypography.headlineMedium),
          AppSpacing.vGapLg,
          Wrap(
            spacing: 8,
            children: levels.map((level) {
              final isSelected = level == currentLevel;
              return ChoiceChip(
                label: Text(t(level)),
                selected: isSelected,
                selectedColor: context.tc.primary.withValues(alpha: 0.2),
                labelStyle: AppTypography.labelMedium.copyWith(
                  color: isSelected ? context.tc.primary : context.tc.textSecondary,
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

  Widget _buildMonthlyHistory(List<MonthlyHistory> history, String Function(String) t) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('monthly_history'), style: AppTypography.headlineMedium),
          AppSpacing.vGapLg,
          if (history.isEmpty)
            Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  t('no_history'),
                  style: AppTypography.bodyMedium,
                ),
              ),
            )
          else
            ...history.map((h) => _buildHistoryRow(h)),
        ],
      ),
    );
  }

  Widget _buildHistoryRow(MonthlyHistory h) {
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ];
    final monthLabel = h.month >= 1 && h.month <= 12 ? months[h.month - 1] : '?';

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        children: [
          SizedBox(
            width: 60,
            child: Text(
              '$monthLabel ${h.year}',
              style: AppTypography.bodySmall,
            ),
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
            width: 70,
            child: Text(
              // USD 금액으로 표시한다
              '${h.actualPnlUsd >= 0 ? '+\$' : '-\$'}${h.actualPnlUsd.abs().toStringAsFixed(0)}',
              style: AppTypography.numberSmall.copyWith(
                color: context.tc.pnlColor(h.actualPnlUsd),
              ),
              textAlign: TextAlign.right,
            ),
          ),
          AppSpacing.hGapSm,
          Icon(
            h.achieved ? Icons.check_circle_rounded : Icons.cancel_rounded,
            size: 16,
            color: h.achieved ? context.tc.profit : context.tc.loss,
          ),
        ],
      ),
    );
  }
}

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
    final radius = size.width / 2 - 12;
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
