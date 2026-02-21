import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/trade_reasoning_provider.dart';
import '../providers/locale_provider.dart';
import '../models/trade_reasoning_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../animations/animation_utils.dart';

/// 매매 근거(Trade Reasoning) 화면이다.
class TradeReasoningScreen extends StatefulWidget {
  const TradeReasoningScreen({super.key});

  @override
  State<TradeReasoningScreen> createState() => _TradeReasoningScreenState();
}

class _TradeReasoningScreenState extends State<TradeReasoningScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<TradeReasoningProvider>().loadDates();
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
          _buildHeader(context, t),
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 왼쪽: 날짜 선택 패널
                const _DateSidePanel(),
                // 구분선
                Container(
                  width: 1,
                  color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                ),
                // 오른쪽: 메인 컨텐츠
                const Expanded(child: _MainContent()),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context, String Function(String) t) {
    return Container(
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
                Text(t('tradeReasoning'), style: AppTypography.displayMedium),
                AppSpacing.vGapXs,
                Text(
                  'AI 매매 결정 근거 및 분석 기록',
                  style: AppTypography.bodySmall,
                ),
              ],
            ),
          ),
          IconButton(
            icon: Icon(Icons.refresh_rounded,
                size: 20, color: context.tc.textTertiary),
            onPressed: () =>
                context.read<TradeReasoningProvider>().refresh(),
            tooltip: t('refresh'),
          ),
        ],
      ),
    );
  }
}

// ── 날짜 사이드 패널 ──

class _DateSidePanel extends StatelessWidget {
  const _DateSidePanel();

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 200,
      child: Consumer<TradeReasoningProvider>(
        builder: (context, provider, _) {
          final dates = provider.dates;

          if (dates == null && provider.isLoading) {
            return _buildShimmerDates();
          }

          if (dates == null || dates.isEmpty) {
            return _buildEmptyDates();
          }

          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                child: Text(
                  '날짜 선택',
                  style: AppTypography.labelMedium.copyWith(
                    color: context.tc.textTertiary,
                    fontSize: 11,
                  ),
                ),
              ),
              Expanded(
                child: ListView.builder(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  itemCount: dates.length,
                  itemBuilder: (context, index) {
                    final dateObj = dates[index];
                    final isSelected =
                        provider.selectedDate == dateObj.date;
                    return _DateItem(
                      dateObj: dateObj,
                      isSelected: isSelected,
                      onTap: () => provider.selectDate(dateObj.date),
                    );
                  },
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildShimmerDates() {
    return Padding(
      padding: const EdgeInsets.all(10),
      child: Column(
        children: List.generate(
          8,
          (i) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: ShimmerLoading(
              width: double.infinity,
              height: 56,
              borderRadius: AppSpacing.borderRadiusMd,
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildEmptyDates() {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Text(
        '날짜 정보 없음',
        style: AppTypography.bodySmall,
      ),
    );
  }
}

class _DateItem extends StatelessWidget {
  final TradeReasoningDate dateObj;
  final bool isSelected;
  final VoidCallback onTap;

  const _DateItem({
    required this.dateObj,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final parts = dateObj.date.split('-');
    String dateLabel = dateObj.date;
    String dayLabel = '';

    if (parts.length >= 3) {
      final year = int.tryParse(parts[0]) ?? 2026;
      final month = int.tryParse(parts[1]) ?? 1;
      final day = int.tryParse(parts[2]) ?? 1;
      dateLabel = '${parts[1]}/${parts[2]}';

      try {
        final dt = DateTime(year, month, day);
        const weekdays = ['월', '화', '수', '목', '금', '토', '일'];
        dayLabel = weekdays[dt.weekday - 1];
      } catch (_) {}
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Material(
        color: Colors.transparent,
        borderRadius: AppSpacing.borderRadiusMd,
        child: InkWell(
          onTap: onTap,
          borderRadius: AppSpacing.borderRadiusMd,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            padding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: isSelected
                  ? context.tc.primary.withValues(alpha: 0.12)
                  : Colors.transparent,
              borderRadius: AppSpacing.borderRadiusMd,
              border: isSelected
                  ? Border.all(
                      color: context.tc.primary.withValues(alpha: 0.25),
                      width: 1,
                    )
                  : null,
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text(
                            dateLabel,
                            style: AppTypography.labelLarge.copyWith(
                              color: isSelected
                                  ? context.tc.primary
                                  : context.tc.textPrimary,
                              fontSize: 13,
                            ),
                          ),
                          if (dayLabel.isNotEmpty) ...[
                            AppSpacing.hGapXs,
                            Text(
                              dayLabel,
                              style: AppTypography.bodySmall.copyWith(
                                color: isSelected
                                    ? context.tc.primaryLight
                                    : context.tc.textTertiary,
                                fontSize: 11,
                              ),
                            ),
                          ],
                        ],
                      ),
                      AppSpacing.vGapXs,
                      Text(
                        '${dateObj.count}건',
                        style: AppTypography.bodySmall.copyWith(
                          color: isSelected
                              ? context.tc.primaryLight.withValues(alpha: 0.8)
                              : context.tc.textTertiary,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
                if (dateObj.count > 0)
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 7, vertical: 3),
                    decoration: BoxDecoration(
                      color: isSelected
                          ? context.tc.primary.withValues(alpha: 0.20)
                          : context.tc.surfaceBorder.withValues(alpha: 0.5),
                      borderRadius: AppSpacing.borderRadiusFull,
                    ),
                    child: Text(
                      '${dateObj.count}',
                      style: AppTypography.bodySmall.copyWith(
                        color: isSelected
                            ? context.tc.primary
                            : context.tc.textTertiary,
                        fontSize: 10,
                        fontWeight: FontWeight.w600,
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

// ── 메인 컨텐츠 패널 ──

class _MainContent extends StatelessWidget {
  const _MainContent();

  @override
  Widget build(BuildContext context) {
    return Consumer<TradeReasoningProvider>(
      builder: (context, provider, _) {
        if (provider.selectedDate == null) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.analytics_rounded,
                    size: 48, color: context.tc.textTertiary),
                AppSpacing.vGapLg,
                Text(
                  '왼쪽에서 날짜를 선택하세요',
                  style: AppTypography.bodyMedium,
                ),
              ],
            ),
          );
        }

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _DateTopBar(date: provider.selectedDate ?? ''),
            _StatsSection(),
            Expanded(child: _TradeList()),
          ],
        );
      },
    );
  }
}

// ── 날짜 상단 바 ──

class _DateTopBar extends StatelessWidget {
  final String date;

  const _DateTopBar({required this.date});

  @override
  Widget build(BuildContext context) {
    final parts = date.split('-');
    String dateTitle = date;
    if (parts.length >= 3) {
      final year = int.tryParse(parts[0]) ?? 2026;
      final month = int.tryParse(parts[1]) ?? 1;
      final day = int.tryParse(parts[2]) ?? 1;
      String dayLabel = '';
      try {
        final dt = DateTime(year, month, day);
        const weekdays = ['월', '화', '수', '목', '금', '토', '일'];
        dayLabel = weekdays[dt.weekday - 1];
      } catch (_) {}
      dateTitle =
          '$year년 $month월 $day일${dayLabel.isNotEmpty ? ' ($dayLabel)' : ''} 매매 근거';
    }

    return Consumer<TradeReasoningProvider>(
      builder: (context, provider, _) {
        final tradeCount = provider.trades?.length ?? 0;
        return Container(
          padding: const EdgeInsets.fromLTRB(20, 14, 16, 10),
          decoration: BoxDecoration(
            color: context.tc.background,
            border: Border(
              bottom: BorderSide(
                color: context.tc.surfaceBorder.withValues(alpha: 0.2),
                width: 1,
              ),
            ),
          ),
          child: Row(
            children: [
              Expanded(
                child: Row(
                  children: [
                    Text(
                      dateTitle,
                      style: AppTypography.headlineMedium,
                    ),
                    AppSpacing.hGapMd,
                    if (tradeCount > 0)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: context.tc.primary.withValues(alpha: 0.12),
                          borderRadius: AppSpacing.borderRadiusFull,
                          border: Border.all(
                            color: context.tc.primary.withValues(alpha: 0.25),
                          ),
                        ),
                        child: Text(
                          '$tradeCount건',
                          style: AppTypography.labelMedium.copyWith(
                            color: context.tc.primary,
                            fontSize: 12,
                          ),
                        ),
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
}

// ── 일일 통계 섹션 ──

class _StatsSection extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer<TradeReasoningProvider>(
      builder: (context, provider, _) {
        final stats = provider.stats;
        if (stats == null && provider.isLoading) {
          return Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: ShimmerLoading(
              width: double.infinity,
              height: 72,
              borderRadius: AppSpacing.borderRadiusMd,
            ),
          );
        }
        if (stats == null) return const SizedBox.shrink();

        return Container(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 8),
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(
                color: context.tc.surfaceBorder.withValues(alpha: 0.2),
                width: 1,
              ),
            ),
          ),
          child: Row(
            children: [
              _StatChip(
                label: '총 거래',
                value: '${stats.totalTrades}',
                icon: Icons.swap_horiz_rounded,
                color: context.tc.primary,
              ),
              AppSpacing.hGapSm,
              _StatChip(
                label: '승 / 패',
                value: '${stats.winCount} / ${stats.lossCount}',
                icon: Icons.balance_rounded,
                color: context.tc.profit,
              ),
              AppSpacing.hGapSm,
              _StatChip(
                label: '승률',
                value: stats.winRateLabel,
                icon: Icons.percent_rounded,
                color: stats.winRate >= 0.5 ? context.tc.profit : context.tc.loss,
              ),
              AppSpacing.hGapSm,
              _StatChip(
                label: '총 손익',
                value: stats.totalPnl >= 0
                    ? '+${stats.totalPnl.toStringAsFixed(2)}%'
                    : '${stats.totalPnl.toStringAsFixed(2)}%',
                icon: stats.totalPnl >= 0
                    ? Icons.trending_up_rounded
                    : Icons.trending_down_rounded,
                color: context.tc.pnlColor(stats.totalPnl),
              ),
              AppSpacing.hGapSm,
              _StatChip(
                label: '평균 신뢰도(승)',
                value:
                    '${(stats.avgWinConfidence * 100).toStringAsFixed(0)}%',
                icon: Icons.psychology_rounded,
                color: context.tc.chart4,
              ),
            ],
          ),
        );
      },
    );
  }
}

class _StatChip extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;
  final Color color;

  const _StatChip({
    required this.label,
    required this.value,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding:
            const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.07),
          borderRadius: AppSpacing.borderRadiusMd,
          border: Border.all(color: color.withValues(alpha: 0.15)),
        ),
        child: Row(
          children: [
            Icon(icon, size: 15, color: color),
            AppSpacing.hGapSm,
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    value,
                    style: AppTypography.labelLarge.copyWith(
                      color: color,
                      fontSize: 13,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                  Text(
                    label,
                    style: AppTypography.bodySmall.copyWith(fontSize: 10),
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── 매매 목록 ──

class _TradeList extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Consumer<TradeReasoningProvider>(
      builder: (context, provider, _) {
        // 로딩 스켈레톤
        if (provider.isLoading && provider.trades == null) {
          return ListView.builder(
            padding: const EdgeInsets.all(16),
            itemCount: 4,
            itemBuilder: (_, i) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: ShimmerLoading(
                width: double.infinity,
                height: 180,
                borderRadius: AppSpacing.borderRadiusMd,
              ),
            ),
          );
        }

        // 에러 상태
        if (provider.error != null && provider.trades == null) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.cloud_off_rounded,
                    size: 48, color: context.tc.textTertiary),
                AppSpacing.vGapLg,
                Text('데이터 로드 실패',
                    style: AppTypography.headlineMedium),
                AppSpacing.vGapSm,
                Text(provider.error ?? '', style: AppTypography.bodySmall),
                AppSpacing.vGapXxl,
                ElevatedButton.icon(
                  onPressed: () {
                    if (provider.selectedDate != null) {
                      provider.loadDaily(provider.selectedDate ?? '');
                    }
                  },
                  icon: const Icon(Icons.refresh_rounded, size: 18),
                  label: Text(t('retry')),
                ),
              ],
            ),
          );
        }

        final trades = provider.trades ?? [];

        // 빈 상태
        if (trades.isEmpty && !provider.isLoading) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.analytics_outlined,
                    size: 48, color: context.tc.textTertiary),
                AppSpacing.vGapLg,
                Text(t('noTradesForDate'),
                    style: AppTypography.bodyMedium),
              ],
            ),
          );
        }

        return ListView.builder(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          itemCount: trades.length,
          itemBuilder: (context, index) {
            return StaggeredFadeSlide(
              index: index,
              child: _TradeCard(trade: trades[index]),
            );
          },
        );
      },
    );
  }
}

// ── 매매 카드 ──

class _TradeCard extends StatefulWidget {
  final TradeReasoning trade;

  const _TradeCard({required this.trade});

  @override
  State<_TradeCard> createState() => _TradeCardState();
}

class _TradeCardState extends State<_TradeCard> {
  bool _detailExpanded = false;

  @override
  Widget build(BuildContext context) {
    final trade = widget.trade;
    final t = context.watch<LocaleProvider>().t;

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Container(
        decoration: BoxDecoration(
          color: context.tc.glassBackground,
          borderRadius: AppSpacing.borderRadiusLg,
          border: Border(
            left: BorderSide(
              color: trade.cardBorderColor,
              width: 3,
            ),
            top: BorderSide(color: context.tc.glassBorder, width: 1),
            right: BorderSide(color: context.tc.glassBorder, width: 1),
            bottom: BorderSide(color: context.tc.glassBorder, width: 1),
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.25),
              blurRadius: 16,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ── 카드 헤더 ──
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
              child: _buildHeader(trade, t),
            ),

            // ── AI 분석 근거 섹션 ──
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              child: _buildAiReasoningSection(trade, t),
            ),

            // ── 거래 세부 정보 (접이식) ──
            _buildDetailToggle(trade, t),

            // ── 피드백 섹션 ──
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
              child: _buildFeedbackSection(trade, t),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader(TradeReasoning trade, String Function(String) t) {
    final pnlColor = trade.pnlPct != null
        ? context.tc.pnlColor(trade.pnlPct ?? 0.0)
        : context.tc.textTertiary;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        // 티커 배지
        Container(
          padding:
              const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            color: trade.directionColor.withValues(alpha: 0.15),
            borderRadius: AppSpacing.borderRadiusMd,
            border: Border.all(
              color: trade.directionColor.withValues(alpha: 0.35),
              width: 1,
            ),
          ),
          child: Text(
            trade.ticker,
            style: AppTypography.labelLarge.copyWith(
              color: trade.directionColor,
              fontSize: 14,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        AppSpacing.hGapSm,
        // 방향 아이콘
        Icon(trade.directionIcon, size: 18, color: trade.directionColor),
        AppSpacing.hGapSm,
        // 가격 정보
        Expanded(
          child: Row(
            children: [
              Text(
                '\$${trade.entryPrice.toStringAsFixed(2)}',
                style: AppTypography.labelLarge.copyWith(fontSize: 13),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 6),
                child: Icon(Icons.arrow_forward_rounded,
                    size: 14, color: context.tc.textTertiary),
              ),
              Text(
                trade.exitPrice != null
                    ? '\$${(trade.exitPrice ?? 0.0).toStringAsFixed(2)}'
                    : t('tradeOpen'),
                style: AppTypography.labelLarge.copyWith(
                  fontSize: 13,
                  color: trade.exitPrice != null
                      ? context.tc.textPrimary
                      : context.tc.info,
                ),
              ),
            ],
          ),
        ),
        // PnL
        if (trade.pnlPct != null)
          Text(
            (trade.pnlPct ?? 0.0) >= 0
                ? '+${(trade.pnlPct ?? 0.0).toStringAsFixed(2)}%'
                : '${(trade.pnlPct ?? 0.0).toStringAsFixed(2)}%',
            style: AppTypography.labelLarge.copyWith(
              color: pnlColor,
              fontSize: 14,
            ),
          ),
        AppSpacing.hGapSm,
        // 상태 배지
        _StatusBadge(status: trade.status, t: t),
      ],
    );
  }

  Widget _buildAiReasoningSection(
      TradeReasoning trade, String Function(String) t) {
    final confidence = trade.aiConfidence ?? 0.0;
    final confidenceColor = trade.confidenceColor(confidence);

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: context.tc.primary.withValues(alpha: 0.05),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: context.tc.primary.withValues(alpha: 0.12),
          width: 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 섹션 헤더
          Row(
            children: [
              Icon(Icons.psychology_rounded,
                  size: 15, color: context.tc.primary),
              AppSpacing.hGapXs,
              Text(
                t('aiReasoning'),
                style: AppTypography.labelMedium.copyWith(
                  color: context.tc.primary,
                  fontSize: 12,
                ),
              ),
            ],
          ),
          AppSpacing.vGapSm,

          // 신뢰도 미터
          if (trade.aiConfidence != null) ...[
            Row(
              children: [
                Text(
                  t('confidence'),
                  style: AppTypography.bodySmall.copyWith(fontSize: 11),
                ),
                AppSpacing.hGapSm,
                Expanded(
                  child: ClipRRect(
                    borderRadius: AppSpacing.borderRadiusFull,
                    child: Stack(
                      children: [
                        Container(
                          height: 5,
                          decoration: BoxDecoration(
                            color: context.tc.surfaceBorder.withValues(alpha: 0.5),
                          ),
                        ),
                        FractionallySizedBox(
                          widthFactor: confidence.clamp(0.0, 1.0),
                          child: Container(
                            height: 5,
                            decoration: BoxDecoration(
                              color: confidenceColor,
                              borderRadius: AppSpacing.borderRadiusFull,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                AppSpacing.hGapSm,
                Text(
                  '${(confidence * 100).toStringAsFixed(0)}%',
                  style: AppTypography.labelMedium.copyWith(
                    color: confidenceColor,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
            AppSpacing.vGapSm,
          ],

          // 시장 국면 배지
          if (trade.marketRegime != null) ...[
            Row(
              children: [
                Text(
                  '${t('marketRegime')}: ',
                  style: AppTypography.bodySmall.copyWith(fontSize: 11),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: context.tc.chart4.withValues(alpha: 0.12),
                    borderRadius: AppSpacing.borderRadiusFull,
                    border: Border.all(
                        color: context.tc.chart4.withValues(alpha: 0.3)),
                  ),
                  child: Text(
                    trade.marketRegime ?? 'unknown',
                    style: AppTypography.bodySmall.copyWith(
                      color: context.tc.chart4,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
            AppSpacing.vGapSm,
          ],

          // 요약 텍스트 (주요 표시)
          if (trade.reasoning.summary.isNotEmpty) ...[
            Text(
              trade.reasoning.summary,
              style: AppTypography.bodyMedium.copyWith(
                height: 1.6,
                color: context.tc.textSecondary,
                fontSize: 13,
              ),
            ),
            AppSpacing.vGapSm,
          ],

          // 인디케이터 방향 + 신뢰도
          if (trade.reasoning.indicatorDirection != null) ...[
            Row(
              children: [
                Text(
                  '인디케이터: ',
                  style: AppTypography.bodySmall.copyWith(fontSize: 11),
                ),
                _buildDirectionBadge(trade.reasoning.indicatorDirection ?? '-'),
                if (trade.reasoning.indicatorConfidence != null) ...[
                  AppSpacing.hGapXs,
                  Text(
                    '(${((trade.reasoning.indicatorConfidence ?? 0.0) * 100).toStringAsFixed(0)}%)',
                    style: AppTypography.bodySmall.copyWith(
                      fontSize: 11,
                      color: context.tc.textTertiary,
                    ),
                  ),
                ],
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildDirectionBadge(String direction) {
    Color color;
    String label;
    switch (direction.toLowerCase()) {
      case 'bullish':
      case 'long':
      case 'buy':
        color = context.tc.profit;
        label = '강세';
        break;
      case 'bearish':
      case 'short':
      case 'sell':
        color = context.tc.loss;
        label = '약세';
        break;
      default:
        color = context.tc.textTertiary;
        label = direction;
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusFull,
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Text(
        label,
        style: AppTypography.bodySmall.copyWith(
          color: color,
          fontSize: 10,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  Widget _buildDetailToggle(
      TradeReasoning trade, String Function(String) t) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 세부 정보 토글 버튼
        InkWell(
          onTap: () => setState(() => _detailExpanded = !_detailExpanded),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Row(
              children: [
                Expanded(
                  child: Divider(
                    color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                    height: 1,
                  ),
                ),
                AppSpacing.hGapSm,
                Text(
                  _detailExpanded ? '세부 정보 접기' : '세부 정보 보기',
                  style: AppTypography.bodySmall.copyWith(
                    fontSize: 11,
                    color: context.tc.textTertiary,
                  ),
                ),
                AppSpacing.hGapXs,
                Icon(
                  _detailExpanded
                      ? Icons.keyboard_arrow_up_rounded
                      : Icons.keyboard_arrow_down_rounded,
                  size: 16,
                  color: context.tc.textTertiary,
                ),
                AppSpacing.hGapSm,
                Expanded(
                  child: Divider(
                    color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                    height: 1,
                  ),
                ),
              ],
            ),
          ),
        ),

        // 세부 내용
        if (_detailExpanded)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
            child: _buildDetailContent(trade, t),
          ),
      ],
    );
  }

  Widget _buildDetailContent(
      TradeReasoning trade, String Function(String) t) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: context.tc.surface.withValues(alpha: 0.5),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: context.tc.surfaceBorder.withValues(alpha: 0.3),
          width: 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 진입 시간
          _DetailRow(
            label: '진입 시간',
            value: _formatDateTime(trade.entryAt),
          ),
          // 청산 시간
          if (trade.exitAt != null) ...[
            AppSpacing.vGapXs,
            _DetailRow(
              label: '청산 시간',
              value: _formatDateTime(trade.exitAt ?? DateTime.now()),
            ),
          ],
          // 보유 시간
          if (trade.holdMinutes != null) ...[
            AppSpacing.vGapXs,
            _DetailRow(
              label: t('holdDuration'),
              value: trade.holdDurationLabel,
            ),
          ],
          // 청산 사유
          if (trade.exitReason != null && (trade.exitReason ?? '').isNotEmpty) ...[
            AppSpacing.vGapSm,
            Row(
              children: [
                Text(
                  '${t('exitReason')}: ',
                  style: AppTypography.bodySmall.copyWith(fontSize: 11),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: context.tc.warning.withValues(alpha: 0.12),
                    borderRadius: AppSpacing.borderRadiusFull,
                    border: Border.all(
                        color: context.tc.warning.withValues(alpha: 0.3)),
                  ),
                  child: Text(
                    trade.exitReason ?? '',
                    style: AppTypography.bodySmall.copyWith(
                      color: context.tc.warning,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ],
          // 신호 데이터
          if (trade.reasoning.signals.isNotEmpty) ...[
            AppSpacing.vGapSm,
            Text(
              '시그널 데이터',
              style: AppTypography.bodySmall.copyWith(
                fontSize: 11,
                color: context.tc.textTertiary,
              ),
            ),
            AppSpacing.vGapXs,
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: trade.reasoning.signals.take(8).map((signal) {
                final label = signal is Map
                    ? '${signal['name'] ?? signal.toString()}'
                    : signal.toString();
                return Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 7, vertical: 3),
                  decoration: BoxDecoration(
                    color: context.tc.surfaceBorder.withValues(alpha: 0.4),
                    borderRadius: AppSpacing.borderRadiusFull,
                    border: Border.all(
                      color: context.tc.surfaceBorder.withValues(alpha: 0.6),
                    ),
                  ),
                  child: Text(
                    label,
                    style: AppTypography.bodySmall.copyWith(
                      fontSize: 10,
                      color: context.tc.textSecondary,
                    ),
                  ),
                );
              }).toList(),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildFeedbackSection(
      TradeReasoning trade, String Function(String) t) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        // 기존 피드백 표시
        if (trade.hasFeedback) ...[
          Expanded(
            child: Row(
              children: [
                // 별점
                if (trade.feedbackRating != null)
                  Row(
                    children: List.generate(5, (i) {
                      final rating = trade.feedbackRating ?? 0;
                      return Icon(
                        i < rating
                            ? Icons.star_rounded
                            : Icons.star_outline_rounded,
                        size: 14,
                        color: i < rating
                            ? context.tc.warning
                            : context.tc.textTertiary,
                      );
                    }),
                  ),
                if (trade.feedbackRating != null && trade.feedbackText != null)
                  AppSpacing.hGapSm,
                // 피드백 텍스트
                if (trade.feedbackText != null &&
                    (trade.feedbackText ?? '').isNotEmpty)
                  Expanded(
                    child: Text(
                      trade.feedbackText ?? '',
                      style: AppTypography.bodySmall.copyWith(
                        fontSize: 11,
                        color: context.tc.textTertiary,
                        fontStyle: FontStyle.italic,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
            ),
          ),
        ] else
          const Spacer(),

        // 피드백 추가 버튼
        GestureDetector(
          onTap: () => _showFeedbackDialog(context, trade, t),
          child: Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: context.tc.primary.withValues(alpha: 0.08),
              borderRadius: AppSpacing.borderRadiusMd,
              border: Border.all(
                color: context.tc.primary.withValues(alpha: 0.2),
                width: 1,
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  trade.hasFeedback
                      ? Icons.edit_rounded
                      : Icons.rate_review_rounded,
                  size: 13,
                  color: context.tc.primary,
                ),
                AppSpacing.hGapXs,
                Text(
                  trade.hasFeedback ? '피드백 수정' : t('addFeedback'),
                  style: AppTypography.labelMedium.copyWith(
                    color: context.tc.primary,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  String _formatDateTime(DateTime dt) {
    final local = dt.toLocal();
    final y = local.year;
    final mo = local.month.toString().padLeft(2, '0');
    final d = local.day.toString().padLeft(2, '0');
    final h = local.hour.toString().padLeft(2, '0');
    final mi = local.minute.toString().padLeft(2, '0');
    return '$y-$mo-$d $h:$mi';
  }

  Future<void> _showFeedbackDialog(
    BuildContext context,
    TradeReasoning trade,
    String Function(String) t,
  ) async {
    await showDialog(
      context: context,
      builder: (ctx) => _FeedbackDialog(trade: trade, t: t),
    );
  }
}

class _DetailRow extends StatelessWidget {
  final String label;
  final String value;

  const _DetailRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(
          '$label: ',
          style: AppTypography.bodySmall.copyWith(
            fontSize: 11,
            color: context.tc.textTertiary,
          ),
        ),
        Text(
          value,
          style: AppTypography.bodySmall.copyWith(
            fontSize: 11,
            color: context.tc.textSecondary,
            fontWeight: FontWeight.w500,
          ),
        ),
      ],
    );
  }
}

// ── 상태 배지 ──

class _StatusBadge extends StatelessWidget {
  final String status;
  final String Function(String) t;

  const _StatusBadge({required this.status, required this.t});

  @override
  Widget build(BuildContext context) {
    final isOpen = status == 'open';
    final color = isOpen ? context.tc.info : context.tc.textTertiary;
    final label = isOpen ? t('tradeOpen') : t('tradeClosed');

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusFull,
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Text(
        label,
        style: AppTypography.bodySmall.copyWith(
          color: color,
          fontSize: 10,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

// ── 피드백 다이얼로그 ──

class _FeedbackDialog extends StatefulWidget {
  final TradeReasoning trade;
  final String Function(String) t;

  const _FeedbackDialog({required this.trade, required this.t});

  @override
  State<_FeedbackDialog> createState() => _FeedbackDialogState();
}

class _FeedbackDialogState extends State<_FeedbackDialog> {
  int _rating = 3;
  final TextEditingController _feedbackController = TextEditingController();
  final TextEditingController _notesController = TextEditingController();
  bool _isSubmitting = false;

  @override
  void initState() {
    super.initState();
    // 기존 피드백이 있으면 불러온다
    if (widget.trade.feedbackRating != null) {
      _rating = widget.trade.feedbackRating ?? 3;
    }
    if (widget.trade.feedbackText != null) {
      _notesController.text = widget.trade.feedbackText ?? '';
    }
  }

  @override
  void dispose() {
    _feedbackController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = widget.t;

    return Dialog(
      backgroundColor: context.tc.surfaceElevated,
      shape: RoundedRectangleBorder(borderRadius: AppSpacing.borderRadiusLg),
      child: SizedBox(
        width: 440,
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 헤더
              Row(
                children: [
                  Icon(Icons.rate_review_rounded,
                      size: 20, color: context.tc.primary),
                  AppSpacing.hGapSm,
                  Text(t('addFeedback'),
                      style: AppTypography.headlineMedium),
                  const Spacer(),
                  IconButton(
                    icon: Icon(Icons.close_rounded,
                        size: 20, color: context.tc.textTertiary),
                    onPressed: () => Navigator.of(context).pop(),
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(),
                  ),
                ],
              ),
              AppSpacing.vGapSm,
              // 거래 정보 요약
              Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: widget.trade.directionColor.withValues(alpha: 0.08),
                  borderRadius: AppSpacing.borderRadiusMd,
                  border: Border.all(
                    color: widget.trade.directionColor.withValues(alpha: 0.2),
                  ),
                ),
                child: Row(
                  children: [
                    Text(
                      widget.trade.ticker,
                      style: AppTypography.labelLarge.copyWith(
                        color: widget.trade.directionColor,
                      ),
                    ),
                    AppSpacing.hGapSm,
                    Icon(widget.trade.directionIcon,
                        size: 16, color: widget.trade.directionColor),
                    const Spacer(),
                    if (widget.trade.pnlPct != null)
                      Text(
                        (widget.trade.pnlPct ?? 0.0) >= 0
                            ? '+${(widget.trade.pnlPct ?? 0.0).toStringAsFixed(2)}%'
                            : '${(widget.trade.pnlPct ?? 0.0).toStringAsFixed(2)}%',
                        style: AppTypography.labelLarge.copyWith(
                          color: context.tc.pnlColor(widget.trade.pnlPct ?? 0.0),
                        ),
                      ),
                  ],
                ),
              ),
              AppSpacing.vGapLg,

              // 별점 평가
              Text(
                t('feedbackRating'),
                style: AppTypography.labelMedium,
              ),
              AppSpacing.vGapSm,
              Row(
                children: List.generate(5, (i) {
                  return GestureDetector(
                    onTap: () => setState(() => _rating = i + 1),
                    child: Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: Icon(
                        i < _rating
                            ? Icons.star_rounded
                            : Icons.star_outline_rounded,
                        size: 32,
                        color: i < _rating
                            ? context.tc.warning
                            : context.tc.textTertiary,
                      ),
                    ),
                  );
                }),
              ),
              AppSpacing.vGapLg,

              // 피드백 텍스트
              Text(
                t('feedbackNotes'),
                style: AppTypography.labelMedium,
              ),
              AppSpacing.vGapSm,
              TextField(
                controller: _notesController,
                maxLines: 4,
                style: AppTypography.bodyMedium.copyWith(fontSize: 13),
                decoration: InputDecoration(
                  hintText: '이 매매에 대한 의견이나 개선점을 입력하세요...',
                  hintStyle: AppTypography.bodySmall,
                  filled: true,
                  fillColor: context.tc.surface,
                  border: OutlineInputBorder(
                    borderRadius: AppSpacing.borderRadiusMd,
                    borderSide: BorderSide(
                      color: context.tc.surfaceBorder.withValues(alpha: 0.4),
                    ),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: AppSpacing.borderRadiusMd,
                    borderSide: BorderSide(
                      color: context.tc.surfaceBorder.withValues(alpha: 0.4),
                    ),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: AppSpacing.borderRadiusMd,
                    borderSide: BorderSide(
                      color: context.tc.primary.withValues(alpha: 0.5),
                    ),
                  ),
                  contentPadding: const EdgeInsets.all(12),
                ),
              ),
              AppSpacing.vGapLg,

              // 버튼 행
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: Text(
                      t('cancel'),
                      style: AppTypography.labelMedium.copyWith(
                        color: context.tc.textTertiary,
                      ),
                    ),
                  ),
                  AppSpacing.hGapSm,
                  ElevatedButton(
                    onPressed: _isSubmitting ? null : _submit,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: context.tc.primary,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 20, vertical: 10),
                      shape: RoundedRectangleBorder(
                          borderRadius: AppSpacing.borderRadiusMd),
                    ),
                    child: _isSubmitting
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : Text(t('save')),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _submit() async {
    setState(() => _isSubmitting = true);

    final provider =
        context.read<TradeReasoningProvider>();
    final success = await provider.submitFeedback(
      widget.trade.id,
      feedback: _feedbackController.text.isEmpty
          ? _notesController.text
          : _feedbackController.text,
      rating: _rating,
      notes: _notesController.text,
    );

    if (mounted) {
      setState(() => _isSubmitting = false);
      if (success) {
        Navigator.of(context).pop();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('피드백이 저장되었습니다'),
            backgroundColor: context.tc.profit,
            behavior: SnackBarBehavior.floating,
            duration: const Duration(seconds: 2),
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('피드백 저장에 실패했습니다'),
            backgroundColor: context.tc.loss,
            behavior: SnackBarBehavior.floating,
            duration: const Duration(seconds: 2),
          ),
        );
      }
    }
  }
}
