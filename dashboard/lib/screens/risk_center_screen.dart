import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/risk_provider.dart';
import '../providers/emergency_provider.dart';
import '../providers/locale_provider.dart';
import '../providers/macro_provider.dart';
import '../models/risk_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/section_header.dart';
import '../widgets/empty_state.dart';
import '../widgets/confirmation_dialog.dart';
import '../widgets/fear_greed_gauge.dart';
import '../widgets/fear_greed_chart.dart';
import '../widgets/rate_chart.dart';
import '../widgets/cpi_chart.dart';
import '../widgets/economic_calendar_card.dart';
import '../widgets/macro_stats_row.dart';
import '../animations/animation_utils.dart';

class RiskCenterScreen extends StatefulWidget {
  const RiskCenterScreen({super.key});

  @override
  State<RiskCenterScreen> createState() => _RiskCenterScreenState();
}

class _RiskCenterScreenState extends State<RiskCenterScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<RiskProvider>().loadDashboard();
      context.read<MacroProvider>().loadAll();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.tc.background,
      body: Consumer<RiskProvider>(
        builder: (context, provider, _) {
          if (provider.isLoading && provider.dashboardData == null) {
            return _buildLoadingSkeleton();
          }
          if (provider.error != null && provider.dashboardData == null) {
            return ErrorState(
              message: provider.error ?? '',
              onRetry: () => provider.refresh(),
            );
          }

          return RefreshIndicator(
            onRefresh: () => provider.refresh(),
            color: context.tc.primary,
            backgroundColor: context.tc.surfaceElevated,
            child: SingleChildScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(20),
              child: _buildContent(provider),
            ),
          );
        },
      ),
    );
  }

  Widget _buildContent(RiskProvider provider) {
    final t = context.watch<LocaleProvider>().t;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(t('risk_safety'), style: AppTypography.displayMedium),
        AppSpacing.vGapLg,
        // 긴급 제어 카드
        StaggeredFadeSlide(
          index: 0,
          child: _buildEmergencyControlCard(),
        ),
        AppSpacing.vGapLg,
        // 리스크 게이트 그리드
        if (provider.dashboardData != null) ...[
          StaggeredFadeSlide(
            index: 1,
            child: _buildRiskGatesGrid(provider.gates),
          ),
          AppSpacing.vGapLg,
          // 2열 레이아웃
          LayoutBuilder(
            builder: (context, constraints) {
              if (constraints.maxWidth >= 800) {
                return _buildWideLayout(provider);
              }
              return _buildNarrowLayout(provider);
            },
          ),
        ] else
          EmptyState(
            icon: Icons.shield_rounded,
            title: t('risk_data_unavailable'),
            subtitle: t('connect_for_risk'),
          ),
        AppSpacing.vGapXxl,
        // 거시경제 지표 섹션
        StaggeredFadeSlide(
          index: 6,
          child: _buildMacroSection(),
        ),
      ],
    );
  }

  // ── 긴급 제어 카드 ──

  Widget _buildEmergencyControlCard() {
    return Consumer2<EmergencyProvider, LocaleProvider>(
      builder: (context, provider, locale, _) {
        final t = locale.t;
        final isStopped = provider.isEmergencyStopped;
        final tc = context.tc;
        final borderColor =
            isStopped ? tc.loss : tc.profit;
        final bgColor = isStopped
            ? tc.loss.withValues(alpha: 0.06)
            : tc.profit.withValues(alpha: 0.04);

        return Container(
          decoration: BoxDecoration(
            color: bgColor,
            borderRadius: AppSpacing.borderRadiusLg,
            border: Border.all(color: borderColor.withValues(alpha: 0.3), width: 1),
          ),
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: borderColor.withValues(alpha: 0.12),
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  isStopped
                      ? Icons.stop_circle_rounded
                      : Icons.check_circle_rounded,
                  color: borderColor,
                  size: 24,
                ),
              ),
              AppSpacing.hGapLg,
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      isStopped
                          ? t('emergency_stop_active')
                          : t('trading_active'),
                      style: AppTypography.headlineMedium.copyWith(
                        color: borderColor,
                      ),
                    ),
                    Text(
                      isStopped
                          ? t('all_trading_halted')
                          : t('system_running_normally'),
                      style: AppTypography.bodySmall,
                    ),
                  ],
                ),
              ),
              if (isStopped)
                ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: context.tc.profit.withValues(alpha: 0.15),
                    foregroundColor: context.tc.profit,
                    side: BorderSide(color: context.tc.profit.withValues(alpha: 0.4)),
                    elevation: 0,
                  ),
                  onPressed: () => _handleResume(context, provider),
                  icon: const Icon(Icons.play_arrow_rounded, size: 18),
                  label: Text(t('resume')),
                )
              else
                ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: context.tc.loss.withValues(alpha: 0.15),
                    foregroundColor: context.tc.loss,
                    side: BorderSide(color: context.tc.loss.withValues(alpha: 0.4)),
                    elevation: 0,
                  ),
                  onPressed: () => _handleEmergencyStop(context, provider),
                  icon: const Icon(Icons.stop_rounded, size: 18),
                  label: Text(t('emergency_stop')),
                ),
            ],
          ),
        );
      },
    );
  }

  Future<void> _handleEmergencyStop(
      BuildContext context, EmergencyProvider provider) async {
    final t = context.read<LocaleProvider>().t;
    final confirmed = await ConfirmationDialog.show(
      context,
      title: t('emergency_stop_title'),
      message: t('emergency_stop_msg'),
      confirmLabel: t('stop_trading'),
      cancelLabel: t('cancel'),
      confirmColor: context.tc.loss,
      icon: Icons.stop_circle_rounded,
    );
    if (confirmed && context.mounted) {
      await provider.triggerEmergencyStop();
    }
  }

  Future<void> _handleResume(
      BuildContext context, EmergencyProvider provider) async {
    final t = context.read<LocaleProvider>().t;
    final confirmed = await TypeToConfirmDialog.show(
      context,
      title: t('resume_trading'),
      message: t('resume_trading_msg'),
      confirmWord: 'RESUME',
      confirmLabel: t('resume_trading'),
      confirmColor: context.tc.profit,
      icon: Icons.play_circle_rounded,
    );
    if (confirmed && context.mounted) {
      await provider.resumeTrading();
    }
  }

  // ── 리스크 게이트 그리드 ──

  Widget _buildRiskGatesGrid(List<RiskGateStatus> gates) {
    final t = context.watch<LocaleProvider>().t;
    if (gates.isEmpty) {
      return GlassCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(title: t('risk_gates')),
            Text(t('no_gate_data'), style: AppTypography.bodyMedium),
          ],
        ),
      );
    }

    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('risk_gates')),
          GridView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
              maxCrossAxisExtent: 240,
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: 2.2,
            ),
            itemCount: gates.length,
            itemBuilder: (context, i) => _buildGateCard(gates[i]),
          ),
        ],
      ),
    );
  }

  Widget _buildGateCard(RiskGateStatus gate) {
    final color = gate.passed ? context.tc.profit : context.tc.loss;
    final bgColor = gate.passed ? context.tc.profitBg : context.tc.lossBg;

    return Container(
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(color: color.withValues(alpha: 0.2), width: 1),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      child: Row(
        children: [
          Icon(
            gate.passed ? Icons.check_circle_rounded : Icons.error_rounded,
            color: color,
            size: 18,
          ),
          AppSpacing.hGapSm,
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  gate.displayName,
                  style: AppTypography.labelLarge.copyWith(fontSize: 12),
                  overflow: TextOverflow.ellipsis,
                ),
                if (gate.currentValue != null)
                  Text(
                    '${(gate.currentValue ?? 0.0).toStringAsFixed(1)}%',
                    style: AppTypography.numberSmall.copyWith(
                      color: color,
                      fontSize: 11,
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ── 2열 레이아웃 ──

  Widget _buildWideLayout(RiskProvider provider) {
    final riskBudget = provider.riskBudget;
    final varIndicator = provider.varIndicator;
    final streakCounter = provider.streakCounter;

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              children: [
                if (riskBudget != null) ...[
                  StaggeredFadeSlide(
                    index: 2,
                    child: _buildRiskBudgetGauge(riskBudget),
                  ),
                  AppSpacing.vGapLg,
                ],
                if (varIndicator != null)
                  StaggeredFadeSlide(
                    index: 4,
                    child: _buildVarCard(varIndicator),
                  ),
              ],
            ),
          ),
          AppSpacing.hGapLg,
          Expanded(
            child: Column(
              children: [
                StaggeredFadeSlide(
                  index: 3,
                  child: _buildConcentrationCard(provider.concentrations),
                ),
                AppSpacing.vGapLg,
                if (streakCounter != null)
                  StaggeredFadeSlide(
                    index: 5,
                    child: _buildStreakCard(streakCounter),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildNarrowLayout(RiskProvider provider) {
    final riskBudget = provider.riskBudget;
    final varIndicator = provider.varIndicator;
    final streakCounter = provider.streakCounter;

    return Column(
      children: [
        if (riskBudget != null) ...[
          StaggeredFadeSlide(
            index: 2,
            child: _buildRiskBudgetGauge(riskBudget),
          ),
          AppSpacing.vGapLg,
        ],
        StaggeredFadeSlide(
          index: 3,
          child: _buildConcentrationCard(provider.concentrations),
        ),
        AppSpacing.vGapLg,
        if (varIndicator != null) ...[
          StaggeredFadeSlide(
            index: 4,
            child: _buildVarCard(varIndicator),
          ),
          AppSpacing.vGapLg,
        ],
        if (streakCounter != null)
          StaggeredFadeSlide(
            index: 5,
            child: _buildStreakCard(streakCounter),
          ),
      ],
    );
  }

  // ── 리스크 예산 게이지 ──

  Widget _buildRiskBudgetGauge(RiskBudget budget) {
    final t = context.watch<LocaleProvider>().t;
    final usageRatio = budget.totalBudgetPct != 0
        ? (budget.usedPct / budget.totalBudgetPct).clamp(0.0, 1.0)
        : 0.0;
    final tc = context.tc;
    final gaugeColor = usageRatio > 0.8
        ? tc.loss
        : usageRatio > 0.6
            ? tc.warning
            : tc.profit;

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('risk_budget')),
          ClipRect(
            child: SizedBox(
              width: double.infinity,
              height: 130,
              child: TweenAnimationBuilder<double>(
                tween: Tween(begin: 0, end: usageRatio),
                duration: AnimDuration.chart,
                curve: AnimCurve.easeOut,
                builder: (context, value, _) {
                  return CustomPaint(
                  painter: _GaugePainter(
                    progress: value,
                    color: gaugeColor,
                    backgroundColor: context.tc.surfaceBorder,
                  ),
                  child: Center(
                    child: Padding(
                      padding: const EdgeInsets.only(top: 20),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            '${budget.usedPct.toStringAsFixed(1)}%',
                            style: AppTypography.numberMedium.copyWith(
                              color: gaugeColor,
                            ),
                          ),
                          Text(
                            'of ${budget.totalBudgetPct.toStringAsFixed(1)}%',
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
          AppSpacing.vGapMd,
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _buildBudgetStat(t('remaining'),
                  '${budget.remainingPct.toStringAsFixed(1)}%', context.tc.profit),
              _buildBudgetStat(t('daily_limit'),
                  '${budget.dailyLimitPct.toStringAsFixed(1)}%', context.tc.textPrimary),
              _buildBudgetStat(t('daily_used'),
                  '${budget.dailyUsedPct.toStringAsFixed(1)}%',
                  context.tc.pnlColor(-budget.dailyUsedPct)),
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
        Text(value, style: AppTypography.numberSmall.copyWith(color: color)),
      ],
    );
  }

  // ── 포지션 집중도 ──

  Widget _buildConcentrationCard(List<PositionConcentration> concentrations) {
    final t = context.watch<LocaleProvider>().t;
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('concentration')),
          if (concentrations.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 16),
              child: Text(t('no_active_positions'),
                  style: AppTypography.bodyMedium),
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
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Text(c.ticker, style: AppTypography.labelLarge),
                  if (overLimit) ...[
                    AppSpacing.hGapXs,
                    Icon(Icons.warning_rounded,
                        size: 12, color: context.tc.loss),
                  ],
                ],
              ),
              Text(
                '${c.weightPct.toStringAsFixed(1)}% / ${maxAllowedPct.toStringAsFixed(0)}%',
                style: AppTypography.numberSmall.copyWith(
                  color: overLimit ? context.tc.loss : context.tc.textSecondary,
                  fontSize: 11,
                ),
              ),
            ],
          ),
          AppSpacing.vGapXs,
          TweenAnimationBuilder<double>(
            tween: Tween(
                begin: 0,
                end: (c.weightPct / maxAllowedPct).clamp(0.0, 1.0)),
            duration: AnimDuration.chart,
            curve: AnimCurve.easeOut,
            builder: (context, value, _) {
              return ClipRRect(
                borderRadius: AppSpacing.borderRadiusFull,
                child: LinearProgressIndicator(
                  value: value,
                  backgroundColor: context.tc.surfaceBorder,
                  valueColor: AlwaysStoppedAnimation<Color>(barColor),
                  minHeight: 7,
                ),
              );
            },
          ),
        ],
      ),
    );
  }

  // ── VaR 카드 ──

  Widget _buildVarCard(VarIndicator varData) {
    final t = context.watch<LocaleProvider>().t;
    final tc = context.tc;
    final riskColor = switch (varData.riskLevel.toLowerCase()) {
      'low' => tc.profit,
      'medium' => tc.warning,
      'high' => tc.loss,
      _ => tc.textTertiary,
    };

    return GlassCard(
      child: Row(
        children: [
          Container(
            width: 52,
            height: 52,
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
                  '${t('var_title')} (${varData.confidenceLevel.toStringAsFixed(0)}%)',
                  style: AppTypography.bodyMedium,
                ),
                AppSpacing.vGapXs,
                Text(
                  '${varData.varPct.toStringAsFixed(2)}%',
                  style: AppTypography.numberMedium.copyWith(color: riskColor),
                ),
                Text(
                  '${t('max')}: ${varData.maxAcceptablePct.toStringAsFixed(2)}%',
                  style: AppTypography.bodySmall,
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: riskColor.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusSm,
              border: Border.all(color: riskColor.withValues(alpha: 0.3)),
            ),
            child: Text(
              varData.riskLevel.toUpperCase(),
              style: AppTypography.labelMedium.copyWith(color: riskColor),
            ),
          ),
        ],
      ),
    );
  }

  // ── 연속 승/패 카드 ──

  Widget _buildStreakCard(StreakCounter streak) {
    final t = context.watch<LocaleProvider>().t;
    final isWinning = streak.currentStreak == 'win';
    final currentCount = isWinning ? streak.winStreak : streak.lossStreak;
    final tc = context.tc;
    final streakColor = isWinning ? tc.profit : tc.loss;

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('win_loss_streak')),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _buildStreakStat(
                t('current_streak'),
                '${isWinning ? '+' : '-'}$currentCount',
                streakColor,
                isWinning
                    ? Icons.trending_up_rounded
                    : Icons.trending_down_rounded,
              ),
              Container(
                  width: 1, height: 48, color: tc.surfaceBorder),
              _buildStreakStat(
                t('best_win'),
                '+${streak.maxWinStreak}',
                tc.profit,
                Icons.emoji_events_rounded,
              ),
              Container(
                  width: 1, height: 48, color: tc.surfaceBorder),
              _buildStreakStat(
                t('worst_loss'),
                '-${streak.maxLossStreak}',
                tc.loss,
                Icons.warning_rounded,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStreakStat(
      String label, String value, Color color, IconData icon) {
    return Column(
      children: [
        Icon(icon, color: color, size: 22),
        AppSpacing.vGapSm,
        Text(value, style: AppTypography.numberMedium.copyWith(color: color)),
        AppSpacing.vGapXs,
        Text(label, style: AppTypography.bodySmall),
      ],
    );
  }

  // ── 거시경제 지표 섹션 ──

  Widget _buildMacroSection() {
    final t = context.watch<LocaleProvider>().t;
    final macroProvider = context.watch<MacroProvider>();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Container(
              width: 4,
              height: 20,
              decoration: BoxDecoration(
                color: context.tc.primary,
                borderRadius: AppSpacing.borderRadiusFull,
              ),
            ),
            AppSpacing.hGapSm,
            Text(t('macro_section_title'), style: AppTypography.displayMedium),
          ],
        ),
        AppSpacing.vGapLg,
        if (macroProvider.isLoading)
          Column(
            children: [
              ShimmerLoading(
                width: double.infinity,
                height: 280,
                borderRadius: AppSpacing.borderRadiusLg,
              ),
              AppSpacing.vGapLg,
              ShimmerLoading(
                width: double.infinity,
                height: 260,
                borderRadius: AppSpacing.borderRadiusLg,
              ),
            ],
          )
        else if (macroProvider.errorMessage != null && macroProvider.indicators == null)
          GlassCard(
            child: Column(
              children: [
                Icon(Icons.cloud_off_rounded,
                    size: 36, color: context.tc.textTertiary),
                AppSpacing.vGapMd,
                Text(t('macro_error'), style: AppTypography.bodyMedium),
                AppSpacing.vGapMd,
                ElevatedButton(
                  onPressed: () => macroProvider.refresh(),
                  child: Text(t('macro_retry')),
                ),
              ],
            ),
          )
        else if (macroProvider.indicators != null)
          _buildMacroContent(macroProvider),
      ],
    );
  }

  Widget _buildMacroContent(MacroProvider macroProvider) {
    final indicators = macroProvider.indicators;
    if (indicators == null) return const SizedBox.shrink();
    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 800;
        return Column(
          children: [
            // 행 1: Fear & Greed 게이지 + 매크로 스탯 행
            if (isWide)
              _buildMacroRow1Wide(indicators)
            else
              _buildMacroRow1Narrow(indicators),
            AppSpacing.vGapLg,
            // 행 2: 기준금리 차트 + 금리 전망
            GlassCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SectionHeader(title: context.read<LocaleProvider>().t('fed_rate')),
                  RateChart(
                    rateHistory: macroProvider.rateHistory,
                    rateOutlook: macroProvider.rateOutlook,
                  ),
                ],
              ),
            ),
            AppSpacing.vGapLg,
            // 행 3: CPI 추세 차트
            GlassCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SectionHeader(title: context.read<LocaleProvider>().t('cpi')),
                  CpiChart(cpiHistory: macroProvider.cpiHistory),
                ],
              ),
            ),
            AppSpacing.vGapLg,
            // 행 4: 경제 캘린더
            if (macroProvider.calendar != null &&
                (macroProvider.calendar ?? []).isNotEmpty)
              GlassCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SectionHeader(
                        title: context.read<LocaleProvider>().t('economic_calendar')),
                    EconomicCalendarCard(
                        events: macroProvider.calendar ?? []),
                  ],
                ),
              ),
          ],
        );
      },
    );
  }

  Widget _buildMacroRow1Wide(dynamic indicators) {
    final t = context.read<LocaleProvider>().t;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 왼쪽: Fear & Greed 게이지 + 임계값 차트
        Expanded(
          child: GlassCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SectionHeader(title: t('fear_greed_index')),
                Center(
                  child: FearGreedGauge(
                    fearGreed: indicators.fearGreed,
                    vix: indicators.vix,
                  ),
                ),
                AppSpacing.vGapLg,
                Divider(
                  height: 1,
                  color: context.tc.surfaceBorder.withValues(alpha: 0.4),
                ),
                AppSpacing.vGapMd,
                Text(
                  '구간 기준선',
                  style: AppTypography.labelMedium.copyWith(
                    fontSize: 11,
                    color: context.tc.textTertiary,
                  ),
                ),
                AppSpacing.vGapSm,
                FearGreedChart(fearGreed: indicators.fearGreed),
              ],
            ),
          ),
        ),
        AppSpacing.hGapLg,
        // 오른쪽: 매크로 스탯 카드들
        Expanded(
          child: GlassCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SectionHeader(title: t('macro_section_title')),
                MacroStatsRow(indicators: indicators),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildMacroRow1Narrow(dynamic indicators) {
    final t = context.read<LocaleProvider>().t;
    return Column(
      children: [
        GlassCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SectionHeader(title: t('fear_greed_index')),
              Center(
                child: FearGreedGauge(
                  fearGreed: indicators.fearGreed,
                  vix: indicators.vix,
                ),
              ),
              AppSpacing.vGapLg,
              Divider(
                height: 1,
                color: context.tc.surfaceBorder.withValues(alpha: 0.4),
              ),
              AppSpacing.vGapMd,
              Text(
                '구간 기준선',
                style: AppTypography.labelMedium.copyWith(
                  fontSize: 11,
                  color: context.tc.textTertiary,
                ),
              ),
              AppSpacing.vGapSm,
              FearGreedChart(fearGreed: indicators.fearGreed),
            ],
          ),
        ),
        AppSpacing.vGapLg,
        GlassCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SectionHeader(title: t('macro_section_title')),
              MacroStatsRow(indicators: indicators),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildLoadingSkeleton() {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        children: [
          ShimmerLoading(
              width: double.infinity,
              height: 80,
              borderRadius: AppSpacing.borderRadiusLg),
          AppSpacing.vGapLg,
          ShimmerLoading(
              width: double.infinity,
              height: 140,
              borderRadius: AppSpacing.borderRadiusLg),
          AppSpacing.vGapLg,
          Row(
            children: [
              Expanded(
                child: ShimmerLoading(
                    width: double.infinity,
                    height: 200,
                    borderRadius: AppSpacing.borderRadiusLg),
              ),
              AppSpacing.hGapLg,
              Expanded(
                child: ShimmerLoading(
                    width: double.infinity,
                    height: 200,
                    borderRadius: AppSpacing.borderRadiusLg),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// 게이지 페인터
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
    const strokeWidth = 12.0;
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
