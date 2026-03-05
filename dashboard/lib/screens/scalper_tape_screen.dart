import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/scalper_tape_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../widgets/glass_card.dart';
import '../widgets/obi_gauge_widget.dart';
import '../widgets/vpin_toxicity_widget.dart';
import '../widgets/cvd_trend_widget.dart';
import '../animations/animation_utils.dart';

/// 스캘퍼 테이프 실시간 대시보드 화면이다.
/// WebSocket을 통해 1초마다 갱신되는 시장 미시구조 지표를 표시한다.
class ScalperTapeScreen extends StatefulWidget {
  const ScalperTapeScreen({super.key});

  @override
  State<ScalperTapeScreen> createState() => _ScalperTapeScreenState();
}

class _ScalperTapeScreenState extends State<ScalperTapeScreen> {
  late ScalperTapeProvider _provider;
  Timer? _lockTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _provider = context.read<ScalperTapeProvider>();
      _provider.connect();
    });
  }

  @override
  void dispose() {
    _lockTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;

    return Scaffold(
      backgroundColor: tc.background,
      appBar: _buildAppBar(context, tc),
      body: Consumer<ScalperTapeProvider>(
        builder: (context, provider, _) {
          return RefreshIndicator(
            onRefresh: () async {
              provider.disconnect();
              await Future.delayed(const Duration(milliseconds: 300));
              provider.connect();
            },
            color: tc.primary,
            backgroundColor: tc.surfaceElevated,
            child: ListView(
              padding: AppSpacing.paddingScreen,
              children: [
                // 1. 가격 & 스프레드 정보 카드
                StaggeredFadeSlide(
                  index: 0,
                  child: _buildPriceInfoCard(context, provider, tc),
                ),
                AppSpacing.vGapLg,
                // 2. OBI 게이지 + VPIN 독성 (2열 레이아웃)
                StaggeredFadeSlide(
                  index: 1,
                  child: _buildObiVpinRow(context, provider, tc),
                ),
                AppSpacing.vGapLg,
                // 3. CVD 추세 차트
                StaggeredFadeSlide(
                  index: 2,
                  child: _buildCvdCard(context, provider, tc),
                ),
                AppSpacing.vGapLg,
                // 4. 체결 강도
                StaggeredFadeSlide(
                  index: 3,
                  child: _buildExecutionStrengthCard(context, provider, tc),
                ),
                AppSpacing.vGapLg,
                // 5. 타임 스탑
                StaggeredFadeSlide(
                  index: 4,
                  child: _buildTimeStopCard(context, provider, tc),
                ),
                AppSpacing.vGapLg,
                // 6. 독성 요약 바
                StaggeredFadeSlide(
                  index: 5,
                  child: _buildToxicitySummaryCard(context, provider, tc),
                ),
                AppSpacing.vGapXxl,
              ],
            ),
          );
        },
      ),
    );
  }

  PreferredSizeWidget _buildAppBar(BuildContext context, TradingColors tc) {
    return AppBar(
      backgroundColor: tc.surface,
      elevation: 0,
      toolbarHeight: 56,
      title: Consumer<ScalperTapeProvider>(
        builder: (context, provider, _) {
          return Row(
            children: [
              Icon(Icons.speed_rounded, size: 20, color: tc.primary),
              AppSpacing.hGapSm,
              Text(
                "Scalper's Tape",
                style: AppTypography.displaySmall.copyWith(fontSize: 18),
              ),
              AppSpacing.hGapMd,
              // 티커 드롭다운
              _buildTickerDropdown(context, provider, tc),
              const Spacer(),
              // 연결 상태 인디케이터
              _buildConnectionBadge(context, provider, tc),
            ],
          );
        },
      ),
      bottom: PreferredSize(
        preferredSize: const Size.fromHeight(1),
        child: Container(
          height: 1,
          color: tc.surfaceBorder.withValues(alpha: 0.2),
        ),
      ),
    );
  }

  Widget _buildTickerDropdown(
    BuildContext context,
    ScalperTapeProvider provider,
    TradingColors tc,
  ) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: tc.primary.withValues(alpha: 0.1),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: tc.primary.withValues(alpha: 0.3),
          width: 1,
        ),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: provider.selectedTicker,
          isDense: true,
          dropdownColor: tc.surfaceElevated,
          style: AppTypography.labelLarge.copyWith(
            color: tc.primary,
            fontSize: 13,
          ),
          icon: Icon(
            Icons.arrow_drop_down_rounded,
            size: 18,
            color: tc.primary,
          ),
          items: ScalperTapeProvider.supportedTickers.map((ticker) {
            return DropdownMenuItem<String>(
              value: ticker,
              child: Text(ticker),
            );
          }).toList(),
          onChanged: (value) {
            if (value != null) {
              provider.selectTicker(value);
            }
          },
        ),
      ),
    );
  }

  Widget _buildConnectionBadge(
    BuildContext context,
    ScalperTapeProvider provider,
    TradingColors tc,
  ) {
    final isConnected = provider.isConnected;
    final color = isConnected ? tc.profit : tc.warning;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (isConnected)
          PulsingDot(color: color, size: 8)
        else
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
        AppSpacing.hGapXs,
        Text(
          isConnected ? '실시간' : '연결 중',
          style: AppTypography.labelMedium.copyWith(
            color: color,
            fontSize: 11,
          ),
        ),
      ],
    );
  }

  // ── 가격 & 스프레드 카드 ──

  Widget _buildPriceInfoCard(
    BuildContext context,
    ScalperTapeProvider provider,
    TradingColors tc,
  ) {
    final data = provider.currentData;
    final fmt = NumberFormat('#,###.##');
    final volFmt = NumberFormat('#,###');

    return GlassCard(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.lg,
        vertical: AppSpacing.md,
      ),
      child: Row(
        children: [
          // 마지막 체결가
          Expanded(
            flex: 3,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '체결가',
                  style: AppTypography.bodySmall.copyWith(
                    color: tc.textTertiary,
                    fontSize: 11,
                  ),
                ),
                AppSpacing.vGapXs,
                Text(
                  data != null ? '\$${fmt.format(data.lastPrice)}' : '--',
                  style: AppTypography.numberSmall.copyWith(
                    color: tc.textPrimary,
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
          // 구분선
          Container(
            width: 1,
            height: 36,
            color: tc.surfaceBorder,
          ),
          // 체결 수량
          Expanded(
            flex: 2,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '체결수량',
                    style: AppTypography.bodySmall.copyWith(
                      color: tc.textTertiary,
                      fontSize: 11,
                    ),
                  ),
                  AppSpacing.vGapXs,
                  Text(
                    data != null ? volFmt.format(data.lastVolume) : '--',
                    style: AppTypography.numberSmall.copyWith(
                      color: tc.textSecondary,
                      fontSize: 15,
                    ),
                  ),
                ],
              ),
            ),
          ),
          // 구분선
          Container(
            width: 1,
            height: 36,
            color: tc.surfaceBorder,
          ),
          // 스프레드
          Expanded(
            flex: 2,
            child: Padding(
              padding: const EdgeInsets.only(left: AppSpacing.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '스프레드',
                    style: AppTypography.bodySmall.copyWith(
                      color: tc.textTertiary,
                      fontSize: 11,
                    ),
                  ),
                  AppSpacing.vGapXs,
                  Text(
                    data != null
                        ? '${data.spreadBps.toStringAsFixed(1)} bps'
                        : '--',
                    style: AppTypography.numberSmall.copyWith(
                      color: _spreadColor(
                          context, data?.spreadBps ?? 0, tc),
                      fontSize: 14,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Color _spreadColor(
      BuildContext context, double spreadBps, TradingColors tc) {
    if (spreadBps < 10) return tc.profit;
    if (spreadBps < 20) return tc.warning;
    return tc.loss;
  }

  // ── OBI + VPIN 2열 레이아웃 ──

  Widget _buildObiVpinRow(
    BuildContext context,
    ScalperTapeProvider provider,
    TradingColors tc,
  ) {
    final data = provider.currentData;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // OBI 게이지 (더 넓게)
        Expanded(
          flex: 6,
          child: GlassCard(
            child: data?.obi != null
                ? ObiGaugeWidget(
                    value: data!.obi!.value,
                    smoothed: data.obi!.smoothed,
                    signal: data.obi!.signal,
                  )
                : _buildSkeletonObi(context, tc),
          ),
        ),
        AppSpacing.hGapMd,
        // VPIN 독성 게이지 (원형)
        Expanded(
          flex: 4,
          child: GlassCard(
            child: data?.vpin != null
                ? VpinToxicityWidget(
                    vpinValue: data!.vpin!.value,
                    vpinLevel: data.vpin!.level,
                    toxicityComposite: data.toxicity?.composite ?? 0,
                    toxicityLevel: data.toxicity?.level ?? 'safe',
                    isLocked: data.toxicity?.isLocked ?? false,
                    lockRemaining: data.toxicity?.lockRemaining,
                  )
                : _buildSkeletonVpin(context, tc),
          ),
        ),
      ],
    );
  }

  Widget _buildSkeletonObi(BuildContext context, TradingColors tc) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ShimmerLoading(
          width: 80,
          height: 16,
          borderRadius: AppSpacing.borderRadiusSm,
        ),
        AppSpacing.vGapMd,
        ShimmerLoading(
          width: double.infinity,
          height: 28,
          borderRadius: AppSpacing.borderRadiusFull,
        ),
      ],
    );
  }

  Widget _buildSkeletonVpin(BuildContext context, TradingColors tc) {
    return Column(
      children: [
        ShimmerLoading(
          width: 100,
          height: 100,
          borderRadius: BorderRadius.circular(50),
        ),
      ],
    );
  }

  // ── CVD 추세 카드 ──

  Widget _buildCvdCard(
    BuildContext context,
    ScalperTapeProvider provider,
    TradingColors tc,
  ) {
    final data = provider.currentData;

    return GlassCard(
      child: CvdTrendWidget(
        history: provider.cvdHistory,
        currentCvd: data?.cvd?.cumulative ?? 0,
        divergence: data?.cvd?.divergence,
      ),
    );
  }

  // ── 체결 강도 카드 ──

  Widget _buildExecutionStrengthCard(
    BuildContext context,
    ScalperTapeProvider provider,
    TradingColors tc,
  ) {
    final data = provider.currentData;
    final es = data?.executionStrength;

    final Color trendColor;
    final IconData trendIcon;
    final String trendLabel;

    if (es == null) {
      trendColor = tc.textTertiary;
      trendIcon = Icons.remove_rounded;
      trendLabel = '--';
    } else {
      switch (es.trend) {
        case 'strengthening':
          trendColor = tc.profit;
          trendIcon = Icons.trending_up_rounded;
          trendLabel = '강화';
          break;
        case 'weakening':
          trendColor = tc.loss;
          trendIcon = Icons.trending_down_rounded;
          trendLabel = '약화';
          break;
        default:
          trendColor = tc.textSecondary;
          trendIcon = Icons.trending_flat_rounded;
          trendLabel = '안정';
      }
    }

    return GlassCard(
      child: Row(
        children: [
          // 아이콘
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: trendColor.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusMd,
            ),
            child: Icon(Icons.bolt_rounded, color: trendColor, size: 24),
          ),
          AppSpacing.hGapLg,
          // 정보
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '체결 강도',
                  style: AppTypography.bodySmall.copyWith(
                    color: tc.textTertiary,
                    fontSize: 11,
                  ),
                ),
                AppSpacing.vGapXs,
                Row(
                  children: [
                    Text(
                      es != null
                          ? es.current.toStringAsFixed(1)
                          : '--',
                      style: AppTypography.numberSmall.copyWith(
                        color: trendColor,
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    AppSpacing.hGapSm,
                    Icon(trendIcon, size: 16, color: trendColor),
                    AppSpacing.hGapXs,
                    Text(
                      trendLabel,
                      style: AppTypography.labelMedium.copyWith(
                        color: trendColor,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          // 서지 배지
          if (es?.isSurge == true)
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: tc.warning.withValues(alpha: 0.15),
                borderRadius: AppSpacing.borderRadiusMd,
                border: Border.all(
                  color: tc.warning.withValues(alpha: 0.5),
                  width: 1,
                ),
              ),
              child: Text(
                'SURGE',
                style: AppTypography.labelMedium.copyWith(
                  color: tc.warning,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.5,
                ),
              ),
            ),
        ],
      ),
    );
  }

  // ── 타임 스탑 카드 ──

  Widget _buildTimeStopCard(
    BuildContext context,
    ScalperTapeProvider provider,
    TradingColors tc,
  ) {
    final data = provider.currentData;
    final ts = data?.timeStop;

    if (ts == null) {
      return GlassCard(
        child: Row(
          children: [
            Icon(
              Icons.timer_off_rounded,
              color: tc.textTertiary,
              size: 20,
            ),
            AppSpacing.hGapMd,
            Text(
              '타임 스탑',
              style: AppTypography.bodyMedium.copyWith(
                color: tc.textTertiary,
              ),
            ),
            const Spacer(),
            Text(
              '포지션 없음',
              style: AppTypography.labelMedium.copyWith(
                color: tc.textTertiary,
                fontSize: 12,
              ),
            ),
          ],
        ),
      );
    }

    final Color actionColor;
    final String actionLabel;
    final IconData actionIcon;

    switch (ts.action) {
      case 'force_exit':
        actionColor = tc.loss;
        actionLabel = '강제 청산';
        actionIcon = Icons.exit_to_app_rounded;
        break;
      case 'breakeven':
        actionColor = tc.warning;
        actionLabel = '손익분기';
        actionIcon = Icons.balance_rounded;
        break;
      default:
        actionColor = tc.profit;
        actionLabel = '보유';
        actionIcon = Icons.lock_rounded;
    }

    final totalTime = ts.elapsed + ts.remaining;
    final progress = totalTime > 0 ? ts.elapsed / totalTime : 0.0;

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.timer_rounded, color: actionColor, size: 18),
              AppSpacing.hGapSm,
              Text(
                '타임 스탑',
                style: AppTypography.labelLarge.copyWith(
                  color: tc.textSecondary,
                  fontSize: 13,
                ),
              ),
              const Spacer(),
              // 액션 배지
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 8,
                  vertical: 3,
                ),
                decoration: BoxDecoration(
                  color: actionColor.withValues(alpha: 0.15),
                  borderRadius: AppSpacing.borderRadiusMd,
                  border: Border.all(
                    color: actionColor.withValues(alpha: 0.4),
                    width: 1,
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(actionIcon, size: 12, color: actionColor),
                    AppSpacing.hGapXs,
                    Text(
                      actionLabel,
                      style: AppTypography.labelMedium.copyWith(
                        color: actionColor,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          AppSpacing.vGapSm,
          // 진행 바 + 시간 표시
          Row(
            children: [
              Expanded(
                child: ClipRRect(
                  borderRadius: AppSpacing.borderRadiusFull,
                  child: LinearProgressIndicator(
                    value: progress.clamp(0.0, 1.0),
                    backgroundColor:
                        tc.surfaceBorder.withValues(alpha: 0.5),
                    color: actionColor,
                    minHeight: 6,
                  ),
                ),
              ),
              AppSpacing.hGapMd,
              Text(
                '${ts.remaining.toInt()}초 남음',
                style: AppTypography.numberSmall.copyWith(
                  color: actionColor,
                  fontSize: 13,
                ),
              ),
            ],
          ),
          AppSpacing.vGapXs,
          Text(
            '경과: ${ts.elapsed.toInt()}초 / 전체: ${totalTime.toInt()}초',
            style: AppTypography.bodySmall.copyWith(
              color: tc.textTertiary,
              fontSize: 11,
            ),
          ),
        ],
      ),
    );
  }

  // ── 독성 요약 카드 ──

  Widget _buildToxicitySummaryCard(
    BuildContext context,
    ScalperTapeProvider provider,
    TradingColors tc,
  ) {
    final data = provider.currentData;
    final toxicity = data?.toxicity;

    final Color statusColor;
    final String statusText;
    final IconData statusIcon;

    if (toxicity == null) {
      statusColor = tc.textTertiary;
      statusText = '--';
      statusIcon = Icons.help_outline_rounded;
    } else if (toxicity.isLocked) {
      statusColor = tc.loss;
      statusText = '차단됨';
      statusIcon = Icons.lock_rounded;
    } else {
      switch (toxicity.level) {
        case 'warning':
          statusColor = tc.warning;
          statusText = '경고';
          statusIcon = Icons.warning_amber_rounded;
          break;
        case 'danger':
          statusColor = const Color(0xFFFF6B35);
          statusText = '위험';
          statusIcon = Icons.dangerous_rounded;
          break;
        case 'blocked':
          statusColor = tc.loss;
          statusText = '차단';
          statusIcon = Icons.block_rounded;
          break;
        default:
          statusColor = tc.profit;
          statusText = '안전';
          statusIcon = Icons.check_circle_outline_rounded;
      }
    }

    return GlassCard(
      child: Row(
        children: [
          // 상태 아이콘
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: statusColor.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusMd,
            ),
            child: Icon(statusIcon, color: statusColor, size: 22),
          ),
          AppSpacing.hGapLg,
          // 레이블 + 값
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '독성 지수',
                  style: AppTypography.bodySmall.copyWith(
                    color: tc.textTertiary,
                    fontSize: 11,
                  ),
                ),
                AppSpacing.vGapXs,
                Row(
                  children: [
                    Text(
                      toxicity != null
                          ? toxicity.composite.toStringAsFixed(2)
                          : '--',
                      style: AppTypography.numberSmall.copyWith(
                        color: statusColor,
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    AppSpacing.hGapSm,
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 7,
                        vertical: 2,
                      ),
                      decoration: BoxDecoration(
                        color: statusColor.withValues(alpha: 0.12),
                        borderRadius: AppSpacing.borderRadiusFull,
                      ),
                      child: Text(
                        statusText,
                        style: AppTypography.labelMedium.copyWith(
                          color: statusColor,
                          fontSize: 11,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          // 잠금 상태 표시
          if (toxicity?.isLocked == true) ...[
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Icon(Icons.lock_rounded, color: tc.loss, size: 18),
                if (toxicity!.lockRemaining != null) ...[
                  AppSpacing.vGapXs,
                  Text(
                    '${toxicity.lockRemaining!.toInt()}초',
                    style: AppTypography.labelMedium.copyWith(
                      color: tc.loss,
                      fontSize: 11,
                    ),
                  ),
                ],
              ],
            ),
          ] else ...[
            // 비잠금 상태 도트
            Container(
              width: 10,
              height: 10,
              decoration: BoxDecoration(
                color: statusColor,
                shape: BoxShape.circle,
              ),
            ),
          ],
        ],
      ),
    );
  }
}
