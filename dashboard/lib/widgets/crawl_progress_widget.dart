import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../models/dashboard_models.dart';
import '../providers/crawl_progress_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/section_header.dart';

/// 크롤링 진행 상황을 실시간으로 표시하는 위젯이다.
/// [CrawlProgressProvider]를 구독하여 상태 변화에 반응한다.
class CrawlProgressWidget extends StatelessWidget {
  /// 레거시 호환용 생성자이다. progressList를 직접 받아 표시한다.
  final List<CrawlProgress>? progressList;

  const CrawlProgressWidget({super.key, this.progressList});

  @override
  Widget build(BuildContext context) {
    // progressList가 제공되면 레거시 표시 방식을 사용한다
    final list = progressList;
    if (list != null) {
      return _LegacyProgressView(progressList: list);
    }

    // Provider 기반 표시 방식을 사용한다
    return Consumer<CrawlProgressProvider>(
      builder: (context, provider, _) {
        if (!provider.isCrawling && provider.crawlerStatuses.isEmpty) {
          return const SizedBox.shrink();
        }

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 전체 진행률 바
            _OverallProgressBar(provider: provider),
            AppSpacing.vGapLg,

            // 크롤러 목록
            if (provider.crawlerStatuses.isNotEmpty)
              _CrawlerList(statuses: provider.crawlerStatuses),

            // 완료 요약 카드
            if (!provider.isCrawling && provider.summary != null) ...[
              AppSpacing.vGapLg,
              if (provider.summary case final summary?) _SummaryCard(summary: summary),
            ],
          ],
        );
      },
    );
  }
}

// ── 전체 진행률 바 ──

class _OverallProgressBar extends StatelessWidget {
  final CrawlProgressProvider provider;

  const _OverallProgressBar({required this.provider});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final t = context.read<LocaleProvider>().t;

    final statuses = provider.crawlerStatuses;
    final done = statuses
        .where((c) =>
            c.status.toLowerCase() == 'completed' ||
            c.status.toLowerCase() == 'failed' ||
            c.status.toLowerCase() == 'done')
        .length;

    // 전체 크롤러 수: statuses.first.totalCrawlers 또는 statuses.length 중 큰 값을 사용한다
    final totalFromMeta = statuses.isNotEmpty
        ? (statuses.first.totalCrawlers ?? 0)
        : 0;
    final displayTotal = totalFromMeta > statuses.length
        ? totalFromMeta
        : statuses.isNotEmpty
            ? statuses.length
            : 0;
    final progressValue = provider.progress.clamp(0.0, 1.0);

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              // 상태 표시 아이콘
              if (provider.isCrawling)
                SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor: AlwaysStoppedAnimation<Color>(tc.primary),
                  ),
                )
              else
                Icon(
                  Icons.check_circle_rounded,
                  size: 16,
                  color: tc.profit,
                ),
              AppSpacing.hGapSm,
              Expanded(
                child: Text(
                  provider.isCrawling
                      ? t('crawling_in_progress')
                      : t('crawling_done'),
                  style: AppTypography.headlineMedium,
                ),
              ),
              // 진행 카운터
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: tc.primary.withValues(alpha: 0.12),
                  borderRadius: AppSpacing.borderRadiusSm,
                ),
                child: Text(
                  displayTotal > 0
                      ? '$done / $displayTotal'
                      : '${statuses.length}',
                  style: AppTypography.numberSmall.copyWith(
                    color: tc.primary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          AppSpacing.vGapMd,
          // 진행률 바
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: TweenAnimationBuilder<double>(
              tween: Tween(begin: 0, end: progressValue),
              duration: const Duration(milliseconds: 400),
              builder: (context, value, _) {
                return LinearProgressIndicator(
                  value: value,
                  backgroundColor: tc.surfaceBorder.withValues(alpha: 0.3),
                  valueColor: AlwaysStoppedAnimation<Color>(tc.primary),
                  minHeight: 6,
                );
              },
            ),
          ),
          AppSpacing.vGapXs,
          Text(
            '${(progressValue * 100).toStringAsFixed(0)}%',
            style: AppTypography.bodySmall.copyWith(
              color: tc.textTertiary,
            ),
          ),
        ],
      ),
    );
  }
}

// ── 크롤러 목록 ──

class _CrawlerList extends StatelessWidget {
  final List<CrawlProgress> statuses;

  const _CrawlerList({required this.statuses});

  @override
  Widget build(BuildContext context) {
    final t = context.read<LocaleProvider>().t;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: t('crawler_list')),
        GlassCard(
          padding: EdgeInsets.zero,
          child: ListView.separated(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: statuses.length,
            separatorBuilder: (_, __) => Divider(
              height: 1,
              indent: 56,
              color: context.tc.surfaceBorder.withValues(alpha: 0.2),
            ),
            itemBuilder: (context, index) {
              return _CrawlerItem(item: statuses[index]);
            },
          ),
        ),
      ],
    );
  }
}

// ── 크롤러 아이템 ──

class _CrawlerItem extends StatelessWidget {
  final CrawlProgress item;

  const _CrawlerItem({required this.item});

  IconData _statusIcon(String status) {
    switch (status.toLowerCase()) {
      case 'completed':
      case 'done':
        return Icons.check_circle_rounded;
      case 'running':
      case 'in_progress':
        return Icons.sync_rounded;
      case 'failed':
      case 'error':
        return Icons.error_rounded;
      case 'waiting':
      default:
        return Icons.schedule_rounded;
    }
  }

  Color _statusColor(String status, TradingColors tc) {
    switch (status.toLowerCase()) {
      case 'completed':
      case 'done':
        return tc.profit;
      case 'running':
      case 'in_progress':
        return tc.primary;
      case 'failed':
      case 'error':
        return tc.loss;
      case 'waiting':
      default:
        return tc.textTertiary;
    }
  }

  bool _isRunning(String status) {
    final s = status.toLowerCase();
    return s == 'running' || s == 'in_progress';
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final statusColor = _statusColor(item.status, tc);
    final running = _isRunning(item.status);

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        children: [
          // 상태 아이콘 (실행 중이면 회전)
          SizedBox(
            width: 24,
            height: 24,
            child: running
                ? _RotatingIcon(
                    icon: Icons.sync_rounded,
                    color: statusColor,
                  )
                : Icon(
                    _statusIcon(item.status),
                    color: statusColor,
                    size: 22,
                  ),
          ),
          AppSpacing.hGapMd,
          // 크롤러 이름 및 메시지
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(item.source, style: AppTypography.labelLarge),
                if (item.message != null && (item.message ?? '').isNotEmpty) ...[
                  AppSpacing.vGapXs,
                  Text(
                    item.message ?? '',
                    style: AppTypography.bodySmall,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ] else if (item.articleCount > 0) ...[
                  AppSpacing.vGapXs,
                  Text(
                    '${NumberFormat('#,###').format(item.articleCount)}건',
                    style: AppTypography.bodySmall,
                  ),
                ],
              ],
            ),
          ),
          // 기사 수 배지 (완료 시)
          if ((item.status.toLowerCase() == 'completed' ||
                  item.status.toLowerCase() == 'done') &&
              item.articleCount > 0)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: tc.profit.withValues(alpha: 0.12),
                borderRadius: AppSpacing.borderRadiusSm,
              ),
              child: Text(
                '${item.articleCount}건',
                style: AppTypography.bodySmall.copyWith(
                  color: tc.profit,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          // 실패 배지
          if (item.status.toLowerCase() == 'failed' ||
              item.status.toLowerCase() == 'error')
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: tc.loss.withValues(alpha: 0.12),
                borderRadius: AppSpacing.borderRadiusSm,
              ),
              child: Text(
                '실패',
                style: AppTypography.bodySmall.copyWith(
                  color: tc.loss,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

// ── 회전 아이콘 ──

class _RotatingIcon extends StatefulWidget {
  final IconData icon;
  final Color color;

  const _RotatingIcon({required this.icon, required this.color});

  @override
  State<_RotatingIcon> createState() => _RotatingIconState();
}

class _RotatingIconState extends State<_RotatingIcon>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return RotationTransition(
      turns: _controller,
      child: Icon(widget.icon, color: widget.color, size: 22),
    );
  }
}

// ── 완료 요약 카드 ──

class _SummaryCard extends StatelessWidget {
  final CrawlSummary summary;

  const _SummaryCard({required this.summary});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final t = context.read<LocaleProvider>().t;

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.summarize_rounded, color: tc.profit, size: 18),
              AppSpacing.hGapSm,
              Text(t('crawl_summary'), style: AppTypography.headlineMedium),
            ],
          ),
          AppSpacing.vGapLg,
          // 통계 그리드
          _StatsRow(
            items: [
              _StatItem(
                label: t('total_collected'),
                value: NumberFormat('#,###').format(summary.totalArticles),
                color: tc.primary,
              ),
              _StatItem(
                label: t('unique_articles'),
                value: NumberFormat('#,###').format(summary.uniqueArticles),
                color: tc.info,
              ),
            ],
          ),
          AppSpacing.vGapMd,
          _StatsRow(
            items: [
              _StatItem(
                label: t('saved_to_db'),
                value: NumberFormat('#,###').format(summary.savedArticles),
                color: tc.profit,
              ),
              _StatItem(
                label: t('duplicates_removed'),
                value:
                    NumberFormat('#,###').format(summary.duplicatesRemoved),
                color: tc.textTertiary,
              ),
            ],
          ),
          AppSpacing.vGapMd,
          Divider(
            height: 1,
            color: tc.surfaceBorder.withValues(alpha: 0.3),
          ),
          AppSpacing.vGapMd,
          // 성공/실패/시간 행
          Row(
            children: [
              Expanded(
                child: Row(
                  children: [
                    Icon(Icons.check_circle_outline_rounded,
                        size: 14, color: tc.profit),
                    AppSpacing.hGapXs,
                    Text(
                      '${summary.successCount}개 성공',
                      style: AppTypography.bodySmall
                          .copyWith(color: tc.profit),
                    ),
                  ],
                ),
              ),
              if (summary.failCount > 0)
                Row(
                  children: [
                    Icon(Icons.error_outline_rounded,
                        size: 14, color: tc.loss),
                    AppSpacing.hGapXs,
                    Text(
                      '${summary.failCount}개 실패',
                      style: AppTypography.bodySmall
                          .copyWith(color: tc.loss),
                    ),
                  ],
                ),
              const Spacer(),
              Row(
                children: [
                  Icon(Icons.timer_outlined,
                      size: 14, color: tc.textTertiary),
                  AppSpacing.hGapXs,
                  Text(
                    '${summary.durationSeconds.toStringAsFixed(1)}초',
                    style: AppTypography.bodySmall
                        .copyWith(color: tc.textTertiary),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _StatsRow extends StatelessWidget {
  final List<_StatItem> items;

  const _StatsRow({required this.items});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: items.map((item) {
        return Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(item.label, style: AppTypography.bodySmall),
              AppSpacing.vGapXs,
              Text(
                item.value,
                style: AppTypography.numberSmall.copyWith(
                  color: item.color,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }
}

class _StatItem {
  final String label;
  final String value;
  final Color color;

  const _StatItem({
    required this.label,
    required this.value,
    required this.color,
  });
}

// ── 레거시 표시 방식 (progressList 직접 전달용) ──

class _LegacyProgressView extends StatelessWidget {
  final List<CrawlProgress> progressList;

  const _LegacyProgressView({required this.progressList});

  IconData _getStatusIcon(String status) {
    switch (status.toLowerCase()) {
      case 'completed':
      case 'done':
        return Icons.check_circle_rounded;
      case 'in_progress':
      case 'running':
        return Icons.hourglass_bottom_rounded;
      case 'waiting':
        return Icons.schedule_rounded;
      case 'error':
      case 'failed':
        return Icons.error_rounded;
      default:
        return Icons.help_rounded;
    }
  }

  Color _getStatusColor(String status, BuildContext context) {
    final tc = context.tc;
    switch (status.toLowerCase()) {
      case 'completed':
      case 'done':
        return tc.profit;
      case 'in_progress':
      case 'running':
        return tc.primary;
      case 'waiting':
        return tc.textTertiary;
      case 'error':
      case 'failed':
        return tc.loss;
      default:
        return tc.textTertiary;
    }
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    if (progressList.isEmpty) {
      return Padding(
        padding: AppSpacing.paddingCard,
        child: Center(
          child: Text('진행 중인 크롤링 없음', style: AppTypography.bodyMedium),
        ),
      );
    }

    final total = progressList.length;
    final completed = progressList
        .where((p) =>
            p.status.toLowerCase() == 'completed' ||
            p.status.toLowerCase() == 'done')
        .length;
    final progress = total > 0 ? completed / total : 0.0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: AppSpacing.paddingCard,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('전체 진행률', style: AppTypography.headlineMedium),
              AppSpacing.vGapMd,
              Row(
                children: [
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(4),
                      child: LinearProgressIndicator(
                        value: progress,
                        backgroundColor:
                            tc.surfaceBorder.withValues(alpha: 0.3),
                        valueColor: AlwaysStoppedAnimation<Color>(tc.primary),
                        minHeight: 6,
                      ),
                    ),
                  ),
                  AppSpacing.hGapMd,
                  Text(
                    '$completed / $total',
                    style: AppTypography.numberSmall.copyWith(
                      color: tc.primary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        Divider(
          height: 1,
          color: tc.surfaceBorder.withValues(alpha: 0.3),
        ),
        ListView.separated(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: progressList.length,
          separatorBuilder: (context, index) => Divider(
            height: 1,
            indent: 56,
            color: context.tc.surfaceBorder.withValues(alpha: 0.2),
          ),
          itemBuilder: (context, index) {
            final item = progressList[index];
            final statusColor = _getStatusColor(item.status, context);

            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              child: Row(
                children: [
                  Icon(
                    _getStatusIcon(item.status),
                    color: statusColor,
                    size: 22,
                  ),
                  AppSpacing.hGapMd,
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(item.source, style: AppTypography.labelLarge),
                        AppSpacing.vGapXs,
                        Text(
                          '${item.articleCount}건'
                          '${item.timeElapsed != null ? '  |  ${(item.timeElapsed ?? 0.0).toStringAsFixed(1)}초' : ''}',
                          style: AppTypography.bodySmall,
                        ),
                      ],
                    ),
                  ),
                  if (item.status.toLowerCase() == 'in_progress' ||
                      item.status.toLowerCase() == 'running')
                    SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation<Color>(tc.primary),
                      ),
                    ),
                ],
              ),
            );
          },
        ),
      ],
    );
  }
}
