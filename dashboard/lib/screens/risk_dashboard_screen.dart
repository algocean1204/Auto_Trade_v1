import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/risk_provider.dart';
import '../providers/locale_provider.dart';
import '../models/risk_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../animations/animation_utils.dart';

class RiskDashboardScreen extends StatefulWidget {
  const RiskDashboardScreen({super.key});

  @override
  State<RiskDashboardScreen> createState() => _RiskDashboardScreenState();
}

class _RiskDashboardScreenState extends State<RiskDashboardScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<RiskProvider>().loadDashboard();
    });
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Scaffold(
      appBar: AppBar(
        title: Text(t('risk_safety'), style: AppTypography.displaySmall),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded, size: 22),
            tooltip: t('refresh'),
            onPressed: () {
              context.read<RiskProvider>().refresh();
            },
          ),
        ],
      ),
      body: Consumer<RiskProvider>(
        builder: (context, provider, child) {
          if (provider.isLoading && provider.dashboardData == null) {
            return _buildLoadingSkeleton();
          }

          if (provider.error != null && provider.dashboardData == null) {
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

          if (provider.dashboardData == null) {
            return Center(
              child: Text(t('no_data_available'), style: AppTypography.bodyLarge),
            );
          }

          final riskBudget = provider.riskBudget;
          final varIndicator = provider.varIndicator;
          final trailingStop = provider.trailingStop;
          final streakCounter = provider.streakCounter;

          return RefreshIndicator(
            onRefresh: () => provider.refresh(),
            color: context.tc.primary,
            backgroundColor: context.tc.surfaceElevated,
            child: ListView(
              padding: AppSpacing.paddingScreen,
              children: [
                StaggeredFadeSlide(
                  index: 0,
                  child: _buildGateStatusCards(provider.gates, t),
                ),
                AppSpacing.vGapLg,
                if (riskBudget != null) ...[
                  StaggeredFadeSlide(
                    index: 1,
                    child: _buildRiskBudgetGauge(riskBudget, t),
                  ),
                  AppSpacing.vGapLg,
                ],
                StaggeredFadeSlide(
                  index: 2,
                  child: _buildConcentrationChart(provider.concentrations, t),
                ),
                AppSpacing.vGapLg,
                if (varIndicator != null) ...[
                  StaggeredFadeSlide(
                    index: 3,
                    child: _buildVarIndicator(varIndicator),
                  ),
                  AppSpacing.vGapLg,
                ],
                if (trailingStop != null) ...[
                  StaggeredFadeSlide(
                    index: 4,
                    child: _buildTrailingStopCard(trailingStop, t),
                  ),
                  AppSpacing.vGapLg,
                ],
                if (streakCounter != null)
                  StaggeredFadeSlide(
                    index: 5,
                    child: _buildStreakCounter(streakCounter, t),
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
            height: 120,
            borderRadius: AppSpacing.borderRadiusLg,
          ),
          AppSpacing.vGapLg,
          ShimmerLoading(
            width: double.infinity,
            height: 160,
            borderRadius: AppSpacing.borderRadiusLg,
          ),
          AppSpacing.vGapLg,
          ShimmerLoading(
            width: double.infinity,
            height: 200,
            borderRadius: AppSpacing.borderRadiusLg,
          ),
        ],
      ),
    );
  }

  // ── 4 Gate Status Cards ──
  Widget _buildGateStatusCards(List<RiskGateStatus> gates, String Function(String) t) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(t('risk_gates'), style: AppTypography.headlineMedium),
        AppSpacing.vGapMd,
        LayoutBuilder(
          builder: (context, constraints) {
            final crossAxisCount = constraints.maxWidth >= 600 ? 2 : 1;
            return GridView.count(
              crossAxisCount: crossAxisCount,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 12,
              crossAxisSpacing: 12,
              childAspectRatio: crossAxisCount == 2 ? 1.5 : 3.0,
              children: gates.map((gate) => _buildGateCard(gate)).toList(),
            );
          },
        ),
      ],
    );
  }

  Widget _buildGateCard(RiskGateStatus gate) {
    final color = gate.passed ? context.tc.profit : context.tc.loss;
    final bgColor = gate.passed ? context.tc.profitBg : context.tc.lossBg;

    return Container(
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: AppSpacing.borderRadiusLg,
        border: Border.all(
          color: color.withValues(alpha: 0.2),
          width: 1,
        ),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            children: [
              Icon(
                gate.passed ? Icons.check_circle_rounded : Icons.error_rounded,
                color: color,
                size: 20,
              ),
              AppSpacing.hGapSm,
              Expanded(
                child: Text(
                  gate.displayName,
                  style: AppTypography.labelLarge.copyWith(
                    color: context.tc.textPrimary,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          Text(
            gate.description,
            style: AppTypography.bodySmall.copyWith(fontSize: 11),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }

  // ── Risk Budget Gauge ──
  Widget _buildRiskBudgetGauge(RiskBudget budget, String Function(String) t) {
    final usageRatio = budget.totalBudgetPct != 0
        ? (budget.usedPct / budget.totalBudgetPct).clamp(0.0, 1.0)
        : 0.0;
    final gaugeColor = usageRatio > 0.8
        ? context.tc.loss
        : usageRatio > 0.6
            ? context.tc.warning
            : context.tc.profit;

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('risk_budget'), style: AppTypography.headlineMedium),
          AppSpacing.vGapLg,
          ClipRect(
            child: SizedBox(
              width: double.infinity,
              height: 140,
              child: TweenAnimationBuilder<double>(
                tween: Tween(begin: 0, end: usageRatio),
                duration: AnimDuration.chart,
                curve: AnimCurve.easeOut,
                builder: (context, value, child) {
                  return CustomPaint(
                  painter: _GaugePainter(
                    progress: value,
                    color: gaugeColor,
                    backgroundColor: context.tc.surfaceBorder,
                  ),
                  child: Center(
                    child: Padding(
                      padding: const EdgeInsets.only(top: 30),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            '${budget.usedPct.toStringAsFixed(1)}%',
                            style: AppTypography.numberLarge.copyWith(
                              color: gaugeColor,
                            ),
                          ),
                          Text(
                            'of ${budget.totalBudgetPct.toStringAsFixed(1)}% budget',
                            style: AppTypography.bodySmall,
                          ),
                        ],
                      ),
                    ),
                  ),
                );
                },
              ),
            ),
          ),
          AppSpacing.vGapLg,
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _buildBudgetStat(
                t('remaining'),
                '${budget.remainingPct.toStringAsFixed(1)}%',
                context.tc.profit,
              ),
              _buildBudgetStat(
                t('daily_limit'),
                '${budget.dailyLimitPct.toStringAsFixed(1)}%',
                context.tc.textPrimary,
              ),
              _buildBudgetStat(
                t('daily_used'),
                '${budget.dailyUsedPct.toStringAsFixed(1)}%',
                context.tc.pnlColor(-budget.dailyUsedPct),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildBudgetStat(String label, String value, Color color) {
    return Column(
      children: [
        Text(label, style: AppTypography.bodySmall),
        AppSpacing.vGapXs,
        Text(
          value,
          style: AppTypography.numberSmall.copyWith(color: color),
        ),
      ],
    );
  }

  // ── Position Concentration Bar Chart ──
  Widget _buildConcentrationChart(List<PositionConcentration> concentrations, String Function(String) t) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('concentration'), style: AppTypography.headlineMedium),
          AppSpacing.vGapLg,
          if (concentrations.isEmpty)
            Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(t('no_active_positions'), style: AppTypography.bodyMedium),
              ),
            )
          else
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 300),
              child: SingleChildScrollView(
                physics: const ClampingScrollPhysics(),
                child: Column(
                  children: concentrations
                      .map((c) => _buildConcentrationBar(c))
                      .toList(),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildConcentrationBar(PositionConcentration c) {
    // 백엔드는 weight_pct (포트폴리오 비중 %)를 반환한다.
    // overLimit 기준: 단일 포지션이 30% 초과 시 경고로 간주한다.
    const maxAllowedPct = 30.0;
    final overLimit = c.weightPct > maxAllowedPct;
    final barColor = overLimit ? context.tc.loss : context.tc.primary;

    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Text(
                    c.ticker,
                    style: AppTypography.labelLarge,
                  ),
                  if (overLimit) ...[
                    AppSpacing.hGapSm,
                    Icon(Icons.warning_rounded, size: 14, color: context.tc.loss),
                  ],
                ],
              ),
              Text(
                '${c.weightPct.toStringAsFixed(1)}% / ${maxAllowedPct.toStringAsFixed(0)}%',
                style: AppTypography.numberSmall.copyWith(
                  color: overLimit ? context.tc.loss : context.tc.textSecondary,
                ),
              ),
            ],
          ),
          AppSpacing.vGapSm,
          Stack(
            children: [
              ClipRRect(
                borderRadius: AppSpacing.borderRadiusFull,
                child: TweenAnimationBuilder<double>(
                  tween: Tween(
                    begin: 0,
                    end: (c.weightPct / maxAllowedPct).clamp(0.0, 1.0),
                  ),
                  duration: AnimDuration.chart,
                  curve: AnimCurve.easeOut,
                  builder: (context, value, child) {
                    return LinearProgressIndicator(
                      value: value,
                      backgroundColor: context.tc.surfaceBorder,
                      valueColor: AlwaysStoppedAnimation<Color>(barColor),
                      minHeight: 8,
                    );
                  },
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  // ── VaR Indicator ──
  Widget _buildVarIndicator(VarIndicator var_) {
    final riskColor = switch (var_.riskLevel.toLowerCase()) {
      'low' => context.tc.profit,
      'medium' => context.tc.warning,
      'high' => context.tc.loss,
      _ => context.tc.textTertiary,
    };

    return GlassCard(
      child: Row(
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              color: riskColor.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusMd,
            ),
            child: Center(
              child: Text(
                'VaR',
                style: AppTypography.labelLarge.copyWith(color: riskColor),
              ),
            ),
          ),
          AppSpacing.hGapLg,
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Value at Risk (${var_.confidenceLevel.toStringAsFixed(0)}%)',
                  style: AppTypography.bodyMedium,
                ),
                AppSpacing.vGapXs,
                Text(
                  '${var_.varPct.toStringAsFixed(2)}%',
                  style: AppTypography.numberMedium.copyWith(color: riskColor),
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: riskColor.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusSm,
              border: Border.all(color: riskColor.withValues(alpha: 0.3)),
            ),
            child: Text(
              var_.riskLevel.toUpperCase(),
              style: AppTypography.labelMedium.copyWith(color: riskColor),
            ),
          ),
        ],
      ),
    );
  }

  // ── Trailing Stop ──
  Widget _buildTrailingStopCard(TrailingStopStatus stop, String Function(String) t) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('Trailing Stop', style: AppTypography.headlineMedium),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: stop.active ? context.tc.profitBg : context.tc.surfaceBorder,
                  borderRadius: AppSpacing.borderRadiusSm,
                ),
                child: Text(
                  stop.active ? 'ACTIVE' : 'INACTIVE',
                  style: AppTypography.labelMedium.copyWith(
                    color: stop.active ? context.tc.profit : context.tc.textTertiary,
                  ),
                ),
              ),
            ],
          ),
          AppSpacing.vGapLg,
          if (stop.positions.isEmpty)
            Center(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text(t('no_active_positions'), style: AppTypography.bodyMedium),
              ),
            )
          else
            ...stop.positions.map((p) => _buildTrailingStopRow(p)),
        ],
      ),
    );
  }

  Widget _buildTrailingStopRow(TrailingStopPosition p) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        children: [
          SizedBox(
            width: 56,
            child: Text(p.ticker, style: AppTypography.labelLarge),
          ),
          Expanded(
            child: Column(
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'High: \$${p.highPrice.toStringAsFixed(2)}',
                      style: AppTypography.bodySmall,
                    ),
                    Text(
                      'Stop: \$${p.stopPrice.toStringAsFixed(2)}',
                      style: AppTypography.bodySmall.copyWith(color: context.tc.loss),
                    ),
                  ],
                ),
                AppSpacing.vGapXs,
                ClipRRect(
                  borderRadius: AppSpacing.borderRadiusFull,
                  child: LinearProgressIndicator(
                    value: (p.drawdownPct.abs() / 10).clamp(0.0, 1.0),
                    backgroundColor: context.tc.surfaceBorder,
                    valueColor: AlwaysStoppedAnimation<Color>(
                      p.drawdownPct.abs() > 3 ? context.tc.loss : context.tc.warning,
                    ),
                    minHeight: 4,
                  ),
                ),
              ],
            ),
          ),
          AppSpacing.hGapMd,
          Text(
            '${p.drawdownPct.toStringAsFixed(1)}%',
            style: AppTypography.numberSmall.copyWith(
              color: context.tc.loss,
            ),
          ),
        ],
      ),
    );
  }

  // ── Streak Counter ──
  Widget _buildStreakCounter(StreakCounter streak, String Function(String) t) {
    final isWinning = streak.currentStreak == 'win';
    final currentCount = isWinning ? streak.winStreak : streak.lossStreak;

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('win_loss_streak'), style: AppTypography.headlineMedium),
          AppSpacing.vGapLg,
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _buildStreakStat(
                t('current_streak'),
                '${isWinning ? '+' : '-'}$currentCount',
                isWinning ? context.tc.profit : context.tc.loss,
                isWinning ? Icons.trending_up_rounded : Icons.trending_down_rounded,
              ),
              Container(
                width: 1,
                height: 50,
                color: context.tc.surfaceBorder,
              ),
              _buildStreakStat(
                t('best_win'),
                '+${streak.maxWinStreak}',
                context.tc.profit,
                Icons.emoji_events_rounded,
              ),
              Container(
                width: 1,
                height: 50,
                color: context.tc.surfaceBorder,
              ),
              _buildStreakStat(
                t('worst_loss'),
                '-${streak.maxLossStreak}',
                context.tc.loss,
                Icons.warning_rounded,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStreakStat(String label, String value, Color color, IconData icon) {
    return Column(
      children: [
        Icon(icon, color: color, size: 24),
        AppSpacing.vGapSm,
        Text(
          value,
          style: AppTypography.numberMedium.copyWith(color: color),
        ),
        AppSpacing.vGapXs,
        Text(label, style: AppTypography.bodySmall),
      ],
    );
  }
}

class _GaugePainter extends CustomPainter {
  final double progress;
  final Color color;
  final Color backgroundColor;

  _GaugePainter({
    required this.progress,
    required this.color,
    required this.backgroundColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    const strokeWidth = 14.0;
    // radius를 width와 height 모두 고려하여 컨테이너 안에 맞춘다
    final maxRadiusFromWidth = size.width / 2 - 20;
    final maxRadiusFromHeight = size.height - 20;
    final radius = math.min(maxRadiusFromWidth, maxRadiusFromHeight);
    final center = Offset(size.width / 2, size.height - 10);
    const startAngle = math.pi;
    const sweepAngle = math.pi;

    final bgPaint = Paint()
      ..color = backgroundColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;

    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      startAngle,
      sweepAngle,
      false,
      bgPaint,
    );

    final progressPaint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;

    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      startAngle,
      sweepAngle * progress,
      false,
      progressPaint,
    );
  }

  @override
  bool shouldRepaint(covariant _GaugePainter oldDelegate) {
    return oldDelegate.progress != progress || oldDelegate.color != color;
  }
}
