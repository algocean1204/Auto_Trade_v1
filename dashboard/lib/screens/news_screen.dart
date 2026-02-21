import 'dart:io';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/news_provider.dart';
import '../providers/locale_provider.dart';
import '../models/news_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../animations/animation_utils.dart';

/// 미국 주식 뉴스 화면이다.
class NewsScreen extends StatefulWidget {
  const NewsScreen({super.key});

  @override
  State<NewsScreen> createState() => _NewsScreenState();
}

class _NewsScreenState extends State<NewsScreen> {
  final ScrollController _articleScrollController = ScrollController();
  bool _summaryExpanded = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<NewsProvider>().loadDates();
    });
    _articleScrollController.addListener(_onScroll);
  }

  @override
  void dispose() {
    _articleScrollController.removeListener(_onScroll);
    _articleScrollController.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (_articleScrollController.position.pixels >=
        _articleScrollController.position.maxScrollExtent - 200) {
      context.read<NewsProvider>().loadMore();
    }
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
                _DateSidePanel(),
                // 구분선
                Container(
                  width: 1,
                  color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                ),
                // 오른쪽: 메인 컨텐츠
                Expanded(
                  child: _MainContent(
                    articleScrollController: _articleScrollController,
                    summaryExpanded: _summaryExpanded,
                    onToggleSummary: () {
                      setState(() {
                        _summaryExpanded = !_summaryExpanded;
                      });
                    },
                  ),
                ),
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
                Text(t('news_title'), style: AppTypography.displayMedium),
                AppSpacing.vGapXs,
                Text(
                  '크롤링된 뉴스 기사 분석 및 감성 데이터',
                  style: AppTypography.bodySmall,
                ),
              ],
            ),
          ),
          IconButton(
            icon: Icon(Icons.refresh_rounded,
                size: 20, color: context.tc.textTertiary),
            onPressed: () => context.read<NewsProvider>().refresh(),
            tooltip: t('refresh'),
          ),
        ],
      ),
    );
  }
}

// ── 날짜 사이드 패널 ──

class _DateSidePanel extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 240,
      child: Consumer<NewsProvider>(
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
                  padding: const EdgeInsets.symmetric(
                      horizontal: 10, vertical: 4),
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
  final NewsDate dateObj;
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
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
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
                        '${dateObj.articleCount}건',
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
                if (dateObj.articleCount > 0)
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
                      '${dateObj.articleCount}',
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
  final ScrollController articleScrollController;
  final bool summaryExpanded;
  final VoidCallback onToggleSummary;

  const _MainContent({
    required this.articleScrollController,
    required this.summaryExpanded,
    required this.onToggleSummary,
  });

  @override
  Widget build(BuildContext context) {
    return Consumer<NewsProvider>(
      builder: (context, provider, _) {
        if (provider.selectedDate == null) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.newspaper_rounded,
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
            // 상단 바: 날짜 타이틀 + 필터
            _TopBar(
              summaryExpanded: summaryExpanded,
              onToggleSummary: onToggleSummary,
            ),
            // 요약 섹션 (접이식)
            if (summaryExpanded) const _SummarySection(),
            // 기사 목록
            Expanded(
              child: _ArticleList(
                  scrollController: articleScrollController),
            ),
          ],
        );
      },
    );
  }
}

// ── 상단 바 ──

class _TopBar extends StatelessWidget {
  final bool summaryExpanded;
  final VoidCallback onToggleSummary;

  const _TopBar({
    required this.summaryExpanded,
    required this.onToggleSummary,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Consumer<NewsProvider>(
      builder: (context, provider, _) {
        final date = provider.selectedDate ?? '';
        final dateTitle = _formatFullDate(date);
        final articleCount = provider.total;

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
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Row(
                      children: [
                        Text(
                          dateTitle,
                          style: AppTypography.headlineMedium,
                        ),
                        AppSpacing.hGapMd,
                        if (articleCount > 0)
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color:
                                  context.tc.primary.withValues(alpha: 0.12),
                              borderRadius: AppSpacing.borderRadiusFull,
                              border: Border.all(
                                color: context.tc.primary.withValues(alpha: 0.25),
                              ),
                            ),
                            child: Text(
                              '$articleCount${t('article_count_suffix')}',
                              style: AppTypography.labelMedium.copyWith(
                                color: context.tc.primary,
                                fontSize: 12,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                  // 요약 토글 버튼
                  IconButton(
                    onPressed: onToggleSummary,
                    icon: Icon(
                      summaryExpanded
                          ? Icons.keyboard_arrow_up_rounded
                          : Icons.keyboard_arrow_down_rounded,
                      size: 22,
                      color: context.tc.textTertiary,
                    ),
                    tooltip: summaryExpanded ? '요약 숨기기' : '요약 보기',
                  ),
                ],
              ),
              AppSpacing.vGapSm,
              // 필터 영역 (카테고리 칩 + 주요뉴스 토글)
              _FilterRow(),
            ],
          ),
        );
      },
    );
  }

  String _formatFullDate(String date) {
    final parts = date.split('-');
    if (parts.length < 3) return date;
    final year = int.tryParse(parts[0]) ?? 2026;
    final month = int.tryParse(parts[1]) ?? 1;
    final day = int.tryParse(parts[2]) ?? 1;

    String dayLabel = '';
    try {
      final dt = DateTime(year, month, day);
      const weekdays = ['월', '화', '수', '목', '금', '토', '일'];
      dayLabel = weekdays[dt.weekday - 1];
    } catch (_) {}

    return '$year년 $month월 $day일${dayLabel.isNotEmpty ? ' ($dayLabel)' : ''} 뉴스';
  }
}

// ── 필터 행 (카테고리 칩 + 중요도 칩 + 주요 뉴스 토글) ──

class _FilterRow extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer<NewsProvider>(
      builder: (context, provider, _) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 카테고리 필터 칩 행
            Row(
              children: [
                Expanded(
                  child: _CategoryChipRow(),
                ),
                // 구분선
                Container(
                  width: 1,
                  height: 24,
                  color: context.tc.surfaceBorder.withValues(alpha: 0.4),
                  margin: const EdgeInsets.symmetric(horizontal: 10),
                ),
                // 주요 뉴스만 토글
                _MajorNewsToggle(),
              ],
            ),
            const SizedBox(height: 6),
            // 중요도 필터 칩 행
            _ImportanceChipRow(),
          ],
        );
      },
    );
  }
}

// ── 카테고리 필터 칩 행 ──

class _CategoryChipRow extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Consumer<NewsProvider>(
      builder: (context, provider, _) {
        final categories = [
          null,
          'macro',
          'earnings',
          'company',
          'sector',
          'policy',
          'geopolitics',
          'other',
        ];
        final categoryLabels = {
          null: t('all_categories'),
          'macro': t('macro_news'),
          'earnings': t('earnings_news'),
          'company': t('company_news'),
          'sector': t('sector_news'),
          'policy': t('policy_news'),
          'geopolitics': t('geopolitics_news'),
          'other': t('other_news'),
        };

        return SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: categories.map((cat) {
              // null(전체)은 filterCategory가 null일 때 선택 상태로 표시한다.
              final isSelected = cat == null
                  ? provider.filterCategory == null
                  : provider.filterCategory == cat;

              return Padding(
                padding: const EdgeInsets.only(right: 6),
                child: _FilterChip(
                  label: categoryLabels[cat] ?? '',
                  isSelected: isSelected,
                  onTap: () {
                    if (cat == null) {
                      // 전체 선택: 카테고리 필터 해제
                      provider.setCategory(null);
                    } else if (isSelected) {
                      // 이미 선택된 카테고리를 다시 탭하면 전체로 돌아간다
                      provider.setCategory(null);
                    } else {
                      // 새 카테고리 선택
                      provider.setCategory(cat);
                    }
                  },
                ),
              );
            }).toList(),
          ),
        );
      },
    );
  }
}

// ── 중요도 필터 칩 행 ──

class _ImportanceChipRow extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer<NewsProvider>(
      builder: (context, provider, _) {
        final importanceFilters = [null, 'critical', 'key'];
        final labels = {
          null: '전체',
          'critical': '크리티컬',
          'key': '핵심',
        };
        final colors = {
          null: context.tc.primary,
          'critical': const Color(0xFFDC2626),
          'key': const Color(0xFFF59E0B),
        };

        return Row(
          children: [
            Text(
              '중요도',
              style: AppTypography.bodySmall.copyWith(
                fontSize: 11,
                color: context.tc.textTertiary,
              ),
            ),
            const SizedBox(width: 6),
            ...importanceFilters.map((imp) {
              final isSelected = imp == provider.filterImportance;
              final color = colors[imp] ?? context.tc.primary;
              return Padding(
                padding: const EdgeInsets.only(right: 6),
                child: GestureDetector(
                  onTap: () {
                    if (isSelected && imp != null) {
                      provider.setImportanceFilter(null);
                    } else {
                      provider.setImportanceFilter(imp);
                    }
                  },
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 150),
                    padding: const EdgeInsets.symmetric(
                        horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: isSelected
                          ? color.withValues(alpha: 0.15)
                          : context.tc.surface,
                      borderRadius: AppSpacing.borderRadiusFull,
                      border: Border.all(
                        color: isSelected
                            ? color.withValues(alpha: 0.45)
                            : context.tc.surfaceBorder.withValues(alpha: 0.35),
                        width: 1,
                      ),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (imp != null)
                          Container(
                            width: 6,
                            height: 6,
                            margin: const EdgeInsets.only(right: 4),
                            decoration: BoxDecoration(
                              color: isSelected ? color : color.withValues(alpha: 0.5),
                              shape: BoxShape.circle,
                            ),
                          ),
                        Text(
                          labels[imp] ?? '전체',
                          style: AppTypography.labelMedium.copyWith(
                            color: isSelected
                                ? color
                                : context.tc.textSecondary,
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            }),
          ],
        );
      },
    );
  }
}

// ── 주요 뉴스만 토글 ──

class _MajorNewsToggle extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer<NewsProvider>(
      builder: (context, provider, _) {
        final isOn = provider.majorNewsOnly;

        return GestureDetector(
          onTap: () => provider.toggleMajorNewsOnly(),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: isOn
                  ? context.tc.warning.withValues(alpha: 0.15)
                  : context.tc.surface,
              borderRadius: AppSpacing.borderRadiusFull,
              border: Border.all(
                color: isOn
                    ? context.tc.warning.withValues(alpha: 0.40)
                    : context.tc.surfaceBorder.withValues(alpha: 0.35),
                width: 1,
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 7,
                  height: 7,
                  decoration: BoxDecoration(
                    color: isOn
                        ? context.tc.warning
                        : context.tc.textTertiary,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 5),
                Text(
                  isOn ? '주요 뉴스만' : '전체 뉴스',
                  style: AppTypography.labelMedium.copyWith(
                    color: isOn
                        ? context.tc.warning
                        : context.tc.textSecondary,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _FilterChip extends StatelessWidget {
  final String label;
  final bool isSelected;
  final VoidCallback onTap;

  const _FilterChip({
    required this.label,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: isSelected
              ? context.tc.primary.withValues(alpha: 0.15)
              : context.tc.surface,
          borderRadius: AppSpacing.borderRadiusFull,
          border: Border.all(
            color: isSelected
                ? context.tc.primary.withValues(alpha: 0.35)
                : context.tc.surfaceBorder.withValues(alpha: 0.35),
            width: 1,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              label,
              style: AppTypography.labelMedium.copyWith(
                color: isSelected
                    ? context.tc.primary
                    : context.tc.textSecondary,
                fontSize: 12,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── 요약 섹션 ──

class _SummarySection extends StatelessWidget {
  const _SummarySection();

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Consumer<NewsProvider>(
      builder: (context, provider, _) {
        final summary = provider.summary;
        if (summary == null && provider.isLoading) {
          return Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: ShimmerLoading(
              width: double.infinity,
              height: 80,
              borderRadius: AppSpacing.borderRadiusMd,
            ),
          );
        }
        if (summary == null) return const SizedBox.shrink();

        return Container(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(
                color: context.tc.surfaceBorder.withValues(alpha: 0.2),
                width: 1,
              ),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 통계 카드 행
              Row(
                children: [
                  _StatCard(
                    label: '총 기사',
                    value: '${summary.totalArticles}',
                    icon: Icons.article_rounded,
                    color: context.tc.primary,
                  ),
                  AppSpacing.hGapSm,
                  _StatCard(
                    label: t('bullish'),
                    value: '${summary.bullishCount}',
                    icon: Icons.trending_up_rounded,
                    color: context.tc.profit,
                  ),
                  AppSpacing.hGapSm,
                  _StatCard(
                    label: t('bearish'),
                    value: '${summary.bearishCount}',
                    icon: Icons.trending_down_rounded,
                    color: context.tc.loss,
                  ),
                  AppSpacing.hGapSm,
                  _StatCard(
                    label: t('neutral_direction'),
                    value: '${summary.neutralCount}',
                    icon: Icons.remove_rounded,
                    color: context.tc.textTertiary,
                  ),
                  AppSpacing.hGapSm,
                  _StatCard(
                    label: '주요 뉴스',
                    value: '${summary.highImpactArticles.length}',
                    icon: Icons.priority_high_rounded,
                    color: context.tc.warning,
                  ),
                ],
              ),
              // 중요도 분포 행 (byImportance 데이터가 있을 때만 표시)
              if (summary.byImportance.isNotEmpty) ...[
                AppSpacing.vGapSm,
                _ImportanceDistRow(summary: summary),
              ],
              if (summary.byCategory.isNotEmpty) ...[
                AppSpacing.vGapSm,
                // 카테고리 분포 칩
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: summary.byCategory.entries
                        .where((e) => e.value > 0)
                        .map((e) {
                      final article = NewsArticle(
                        id: '',
                        headline: '',
                        content: '',
                        source: '',
                        tickers: [],
                        impact: 'low',
                        direction: 'neutral',
                        category: e.key,
                      );
                      return Padding(
                        padding: const EdgeInsets.only(right: 6),
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 10, vertical: 4),
                          decoration: BoxDecoration(
                            color: article.categoryColor.withValues(alpha: 0.12),
                            borderRadius: AppSpacing.borderRadiusFull,
                            border: Border.all(
                              color:
                                  article.categoryColor.withValues(alpha: 0.3),
                            ),
                          ),
                          child: Text(
                            '${article.categoryLabel} ${e.value}',
                            style: AppTypography.bodySmall.copyWith(
                              color: article.categoryColor,
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      );
                    }).toList(),
                  ),
                ),
              ],
            ],
          ),
        );
      },
    );
  }
}

/// 중요도 분포 행 위젯이다.
class _ImportanceDistRow extends StatelessWidget {
  final NewsSummary summary;

  const _ImportanceDistRow({required this.summary});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(
          '중요도',
          style: AppTypography.bodySmall.copyWith(
            fontSize: 11,
            color: context.tc.textTertiary,
          ),
        ),
        const SizedBox(width: 8),
        if (summary.criticalCount > 0)
          _ImportanceBadge(
            label: '크리티컬 ${summary.criticalCount}',
            color: const Color(0xFFDC2626),
          ),
        if (summary.criticalCount > 0 && summary.keyCount > 0)
          const SizedBox(width: 6),
        if (summary.keyCount > 0)
          _ImportanceBadge(
            label: '핵심 ${summary.keyCount}',
            color: const Color(0xFFF59E0B),
          ),
        if (summary.normalCount > 0) ...[
          const SizedBox(width: 6),
          _ImportanceBadge(
            label: '일반 ${summary.normalCount}',
            color: const Color(0xFF6B7280),
          ),
        ],
      ],
    );
  }
}

/// 중요도 뱃지 위젯이다.
class _ImportanceBadge extends StatelessWidget {
  final String label;
  final Color color;

  const _ImportanceBadge({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusFull,
        border: Border.all(color: color.withValues(alpha: 0.30)),
      ),
      child: Text(
        label,
        style: AppTypography.bodySmall.copyWith(
          fontSize: 10,
          color: color,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;
  final Color color;

  const _StatCard({
    required this.label,
    required this.value,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.07),
          borderRadius: AppSpacing.borderRadiusMd,
          border: Border.all(color: color.withValues(alpha: 0.15)),
        ),
        child: Row(
          children: [
            Icon(icon, size: 16, color: color),
            AppSpacing.hGapSm,
            Flexible(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    value,
                    style: AppTypography.labelLarge.copyWith(
                      color: color,
                      fontSize: 15,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  Text(
                    label,
                    style: AppTypography.bodySmall.copyWith(fontSize: 10),
                    maxLines: 1,
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

// ── 기사 목록 ──

class _ArticleList extends StatelessWidget {
  final ScrollController scrollController;

  const _ArticleList({required this.scrollController});

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Consumer<NewsProvider>(
      builder: (context, provider, _) {
        // 로딩 상태: 기사 없을 때 스켈레톤 표시
        if (provider.isLoading && (provider.articles == null)) {
          return ListView.builder(
            padding: const EdgeInsets.all(16),
            itemCount: 6,
            itemBuilder: (_, i) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: ShimmerLoading(
                width: double.infinity,
                height: 100,
                borderRadius: AppSpacing.borderRadiusMd,
              ),
            ),
          );
        }

        // 에러 상태
        if (provider.error != null && provider.articles == null) {
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
                  onPressed: () => provider.loadArticles(),
                  icon: const Icon(Icons.refresh_rounded, size: 18),
                  label: Text(t('retry')),
                ),
              ],
            ),
          );
        }

        final articles = provider.articles ?? [];

        // 빈 상태
        if (articles.isEmpty && !provider.isLoading) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.newspaper_rounded,
                    size: 48, color: context.tc.textTertiary),
                AppSpacing.vGapLg,
                Text(
                  provider.majorNewsOnly
                      ? '해당 날짜의 주요 뉴스가 없습니다'
                      : t('no_news'),
                  style: AppTypography.bodyMedium,
                ),
                if (provider.majorNewsOnly) ...[
                  AppSpacing.vGapSm,
                  GestureDetector(
                    onTap: () => provider.toggleMajorNewsOnly(),
                    child: Text(
                      '전체 뉴스 보기',
                      style: AppTypography.labelMedium.copyWith(
                        color: context.tc.primary,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          );
        }

        return ListView.builder(
          controller: scrollController,
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          itemCount: articles.length + (provider.isLoadingMore ? 1 : 0),
          itemBuilder: (context, index) {
            if (index >= articles.length) {
              // 하단 로딩 인디케이터
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Center(
                  child: SizedBox(
                    width: 24,
                    height: 24,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: context.tc.primary,
                    ),
                  ),
                ),
              );
            }

            final article = articles[index];
            return _ArticleCard(
              article: article,
              index: index,
            );
          },
        );
      },
    );
  }
}

// ── 기사 카드 ──

class _ArticleCard extends StatefulWidget {
  final NewsArticle article;
  final int index;

  const _ArticleCard({
    required this.article,
    required this.index,
  });

  @override
  State<_ArticleCard> createState() => _ArticleCardState();
}

class _ArticleCardState extends State<_ArticleCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final article = widget.article;
    final t = context.watch<LocaleProvider>().t;

    final timeLabel = _formatTime(article.publishedAt);

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: GlassCard(
        padding: EdgeInsets.zero,
        onTap: () {
          setState(() {
            _expanded = !_expanded;
          });
          if (!_expanded) {
            context.read<NewsProvider>().clearSelectedArticle();
          }
        },
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ── 카드 헤더 행 ──
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 12, 10, 10),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Impact dot + 중요도 표시
                  Padding(
                    padding: const EdgeInsets.only(top: 4, right: 10),
                    child: article.importance == 'critical'
                        ? _PulsingImportanceDot(color: article.importanceColor)
                        : Container(
                            width: 9,
                            height: 9,
                            decoration: BoxDecoration(
                              color: article.importance == 'key'
                                  ? article.importanceColor
                                  : article.impactColor,
                              shape: BoxShape.circle,
                              boxShadow: [
                                BoxShadow(
                                  color: (article.importance == 'key'
                                          ? article.importanceColor
                                          : article.impactColor)
                                      .withValues(alpha: 0.4),
                                  blurRadius: 4,
                                ),
                              ],
                            ),
                          ),
                  ),
                  // 헤드라인 + 메타
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        // 한국어 헤드라인이 있으면 한국어로, 없으면 영어로 표시한다
                        Text(
                          article.displayHeadline,
                          style: AppTypography.labelLarge.copyWith(
                            fontSize: 13,
                            height: 1.45,
                          ),
                          maxLines: _expanded ? null : 2,
                          overflow: _expanded
                              ? TextOverflow.visible
                              : TextOverflow.ellipsis,
                        ),
                        // 한국어 헤드라인이 표시될 때 원문 헤드라인도 보조로 표시한다
                        if (_expanded && article.hasKoreanHeadline) ...[
                          AppSpacing.vGapXs,
                          Text(
                            article.headline,
                            style: AppTypography.bodySmall.copyWith(
                              fontSize: 10,
                              color: context.tc.textTertiary,
                              height: 1.4,
                              fontStyle: FontStyle.italic,
                            ),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                        AppSpacing.vGapXs,
                        // 소스 + 시간 + 중요도 뱃지
                        Row(
                          children: [
                            Flexible(
                              child: Text(
                                '${article.sourceLabel}${timeLabel.isNotEmpty ? ' · $timeLabel' : ''}',
                                style: AppTypography.bodySmall.copyWith(
                                  fontSize: 11,
                                  color: context.tc.textTertiary,
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            // 중요도 뱃지 (critical, key만 표시)
                            if (article.importance == 'critical' ||
                                article.importance == 'key') ...[
                              AppSpacing.hGapXs,
                              Container(
                                padding: const EdgeInsets.symmetric(
                                    horizontal: 5, vertical: 1),
                                decoration: BoxDecoration(
                                  color: article.importanceColor
                                      .withValues(alpha: 0.14),
                                  borderRadius: BorderRadius.circular(3),
                                  border: Border.all(
                                    color: article.importanceColor
                                        .withValues(alpha: 0.35),
                                    width: 1,
                                  ),
                                ),
                                child: Text(
                                  article.importanceLabel,
                                  style: AppTypography.bodySmall.copyWith(
                                    fontSize: 8,
                                    color: article.importanceColor,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ],
                            if (article.hasKoreanHeadline) ...[
                              AppSpacing.hGapXs,
                              Container(
                                padding: const EdgeInsets.symmetric(
                                    horizontal: 4, vertical: 1),
                                decoration: BoxDecoration(
                                  color: context.tc.primary.withValues(alpha: 0.12),
                                  borderRadius: BorderRadius.circular(3),
                                ),
                                child: Text(
                                  'KO',
                                  style: AppTypography.bodySmall.copyWith(
                                    fontSize: 8,
                                    color: context.tc.primary,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ],
                          ],
                        ),
                      ],
                    ),
                  ),
                  // 원문 링크 아이콘 버튼 (URL이 있을 때만 표시)
                  if (article.url != null && (article.url ?? '').isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(left: 4),
                      child: Tooltip(
                        message: '원문 보기',
                        child: GestureDetector(
                          onTap: () => _launchUrl(article.url ?? ''),
                          behavior: HitTestBehavior.opaque,
                          child: Container(
                            width: 30,
                            height: 30,
                            decoration: BoxDecoration(
                              color: context.tc.primary.withValues(alpha: 0.10),
                              borderRadius: AppSpacing.borderRadiusSm,
                              border: Border.all(
                                color: context.tc.primary.withValues(alpha: 0.20),
                                width: 1,
                              ),
                            ),
                            child: Icon(
                              Icons.open_in_new_rounded,
                              size: 14,
                              color: context.tc.primary,
                            ),
                          ),
                        ),
                      ),
                    ),
                  // 확장 토글 화살표
                  Padding(
                    padding: const EdgeInsets.only(left: 4),
                    child: Icon(
                      _expanded
                          ? Icons.keyboard_arrow_up_rounded
                          : Icons.keyboard_arrow_down_rounded,
                      size: 18,
                      color: context.tc.textTertiary,
                    ),
                  ),
                ],
              ),
            ),
            // ── 요약/본문 미리보기 (접힌 상태에서도 한 줄 표시) ──
            if (!_expanded && article.displaySummary.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(33, 0, 14, 8),
                child: _ContentPreview(article: article),
              ),
            // ── 태그 행 ──
            Padding(
              padding: const EdgeInsets.fromLTRB(33, 0, 14, 10),
              child: _buildTagRow(article, t),
            ),
            // ── 감성 바 ──
            if (article.sentimentScore != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 0, 14, 10),
                child: _SentimentBar(score: article.sentimentScore ?? 0.0),
              ),
            // ── 확장 영역: 전문 + 원문 버튼 ──
            if (_expanded) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 0, 14, 4),
                child: Divider(
                  height: 1,
                  color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 10, 14, 14),
                child: _ArticleDetail(article: article, t: t),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildTagRow(NewsArticle article, String Function(String) t) {
    return Wrap(
      spacing: 6,
      runSpacing: 4,
      children: [
        // 카테고리 칩
        _TagChip(
          label: article.categoryLabel,
          color: article.categoryColor,
        ),
        // 방향 칩
        _TagChip(
          label: article.directionLabel,
          color: article.directionColor,
        ),
        // 티커 칩들
        ...article.tickers.take(4).map((ticker) => _TagChip(
              label: ticker,
              color: context.tc.primary,
              outlined: true,
            )),
        if (article.tickers.length > 4)
          _TagChip(
            label: '+${article.tickers.length - 4}',
            color: context.tc.textTertiary,
            outlined: true,
          ),
      ],
    );
  }

  String _formatTime(DateTime? dt) {
    if (dt == null) return '';
    final local = dt.toLocal();
    final h = local.hour.toString().padLeft(2, '0');
    final m = local.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }

  Future<void> _launchUrl(String url) async {
    try {
      final uri = Uri.tryParse(url);
      if (uri == null || (!uri.isScheme('http') && !uri.isScheme('https'))) {
        return;
      }
      if (Platform.isMacOS) {
        await Process.run('open', [url]);
      } else if (Platform.isLinux) {
        await Process.run('xdg-open', [url]);
      } else if (Platform.isWindows) {
        await Process.run('cmd', ['/c', 'start', '', url]);
      }
    } catch (_) {}
  }
}

// ── 콘텐츠 미리보기 (접힌 상태) ──

class _ContentPreview extends StatelessWidget {
  final NewsArticle article;

  const _ContentPreview({required this.article});

  @override
  Widget build(BuildContext context) {
    final displayText = article.displaySummary;
    final isKo = article.hasKoreanSummary;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!isKo)
          Container(
            margin: const EdgeInsets.only(right: 5, top: 1),
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
            decoration: BoxDecoration(
              color: context.tc.surfaceBorder.withValues(alpha: 0.6),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              'EN',
              style: AppTypography.bodySmall.copyWith(
                fontSize: 9,
                color: context.tc.textTertiary,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        Expanded(
          child: Text(
            displayText,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: AppTypography.bodySmall.copyWith(
              fontSize: 11,
              color: context.tc.textTertiary,
              height: 1.5,
            ),
          ),
        ),
      ],
    );
  }
}

class _TagChip extends StatelessWidget {
  final String label;
  final Color color;
  final bool outlined;

  const _TagChip({
    required this.label,
    required this.color,
    this.outlined = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: outlined ? Colors.transparent : color.withValues(alpha: 0.14),
        borderRadius: AppSpacing.borderRadiusFull,
        border: Border.all(
          color: color.withValues(alpha: outlined ? 0.35 : 0.25),
          width: 1,
        ),
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

class _SentimentBar extends StatelessWidget {
  final double score; // -1.0 ~ 1.0

  const _SentimentBar({required this.score});

  @override
  Widget build(BuildContext context) {
    // -1~1 범위를 0~1로 정규화한다
    final normalizedScore = ((score + 1) / 2).clamp(0.0, 1.0);
    final barColor = score > 0.1
        ? context.tc.profit
        : score < -0.1
            ? context.tc.loss
            : context.tc.textTertiary;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              '감성',
              style: AppTypography.bodySmall.copyWith(fontSize: 10),
            ),
            const Spacer(),
            Text(
              score >= 0
                  ? '+${score.toStringAsFixed(2)}'
                  : score.toStringAsFixed(2),
              style: AppTypography.bodySmall.copyWith(
                fontSize: 10,
                color: barColor,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
        const SizedBox(height: 3),
        ClipRRect(
          borderRadius: AppSpacing.borderRadiusFull,
          child: Stack(
            children: [
              // 배경 바
              Container(
                height: 3,
                decoration: BoxDecoration(
                  color: context.tc.surfaceBorder.withValues(alpha: 0.5),
                ),
              ),
              // 값 바
              FractionallySizedBox(
                widthFactor: normalizedScore,
                child: Container(
                  height: 3,
                  decoration: BoxDecoration(
                    color: barColor,
                    borderRadius: AppSpacing.borderRadiusFull,
                  ),
                ),
              ),
              // 중앙 기준선
              Positioned(
                left: 0,
                right: 0,
                child: Center(
                  child: Container(
                    width: 1,
                    height: 3,
                    color: context.tc.textTertiary.withValues(alpha: 0.5),
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// ── 기사 상세 ──

class _ArticleDetail extends StatelessWidget {
  final NewsArticle article;
  final String Function(String) t;

  const _ArticleDetail({required this.article, required this.t});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 한국어 요약 여부 레이블
        if (!article.hasKoreanSummary)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 7, vertical: 3),
                  decoration: BoxDecoration(
                    color: context.tc.surfaceBorder.withValues(alpha: 0.6),
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(
                      color: context.tc.surfaceBorder,
                      width: 1,
                    ),
                  ),
                  child: Text(
                    '원문 (영어)',
                    style: AppTypography.bodySmall.copyWith(
                      fontSize: 10,
                      color: context.tc.textTertiary,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),
        Text(
          article.displaySummary,
          style: AppTypography.bodyMedium.copyWith(
            height: 1.65,
            color: context.tc.textSecondary,
          ),
        ),
        // 관련 기업 영향 섹션
        if (article.hasCompaniesImpact) ...[
          AppSpacing.vGapMd,
          _CompaniesImpactSection(companiesImpact: article.companiesImpact ?? {}),
        ],
        if (article.url != null && (article.url ?? '').isNotEmpty) ...[
          AppSpacing.vGapMd,
          GestureDetector(
            onTap: () => _launchUrl(article.url ?? ''),
            child: Container(
              padding: const EdgeInsets.symmetric(
                  horizontal: 14, vertical: 8),
              decoration: BoxDecoration(
                color: context.tc.primary.withValues(alpha: 0.1),
                borderRadius: AppSpacing.borderRadiusMd,
                border: Border.all(
                  color: context.tc.primary.withValues(alpha: 0.25),
                  width: 1,
                ),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.open_in_new_rounded,
                    size: 14,
                    color: context.tc.primary,
                  ),
                  AppSpacing.hGapSm,
                  Text(
                    t('view_original'),
                    style: AppTypography.labelMedium.copyWith(
                      color: context.tc.primary,
                    ),
                  ),
                  AppSpacing.hGapSm,
                  Flexible(
                    child: Text(
                      article.url ?? '',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTypography.bodySmall.copyWith(
                        fontSize: 10,
                        color: context.tc.textTertiary,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
        // 전체 ticker 목록
        if (article.tickers.length > 4) ...[
          AppSpacing.vGapSm,
          Wrap(
            spacing: 5,
            runSpacing: 4,
            children: article.tickers
                .map((ticker) => _TagChip(
                      label: ticker,
                      color: context.tc.primary,
                      outlined: true,
                    ))
                .toList(),
          ),
        ],
      ],
    );
  }

  Future<void> _launchUrl(String url) async {
    try {
      // URL 스킴을 검증하여 커맨드 인젝션을 방지한다
      final uri = Uri.tryParse(url);
      if (uri == null || (!uri.isScheme('http') && !uri.isScheme('https'))) {
        return;
      }
      if (Platform.isMacOS) {
        await Process.run('open', [url]);
      } else if (Platform.isLinux) {
        await Process.run('xdg-open', [url]);
      } else if (Platform.isWindows) {
        await Process.run('cmd', ['/c', 'start', '', url]);
      }
    } catch (_) {}
  }
}

// ── 관련 기업 영향 섹션 ──

/// 기업별 영향 분석 섹션 위젯이다.
/// companies_impact 맵의 각 항목을 티커 + 영향 설명으로 표시한다.
class _CompaniesImpactSection extends StatelessWidget {
  final Map<String, String> companiesImpact;

  const _CompaniesImpactSection({required this.companiesImpact});

  @override
  Widget build(BuildContext context) {
    final entries = companiesImpact.entries.toList();
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: context.tc.surfaceBorder.withValues(alpha: 0.25),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: context.tc.surfaceBorder.withValues(alpha: 0.5),
          width: 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.business_center_rounded,
                size: 13,
                color: context.tc.textTertiary,
              ),
              AppSpacing.hGapXs,
              Text(
                '관련 기업 영향',
                style: AppTypography.labelMedium.copyWith(
                  fontSize: 11,
                  color: context.tc.textTertiary,
                ),
              ),
            ],
          ),
          AppSpacing.vGapSm,
          ...entries.map((entry) => _CompanyImpactRow(
                ticker: entry.key,
                impact: entry.value,
              )),
        ],
      ),
    );
  }
}

/// 크리티컬 중요도 펄싱 도트 위젯이다.
class _PulsingImportanceDot extends StatefulWidget {
  final Color color;

  const _PulsingImportanceDot({required this.color});

  @override
  State<_PulsingImportanceDot> createState() => _PulsingImportanceDotState();
}

class _PulsingImportanceDotState extends State<_PulsingImportanceDot>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);
    _animation = Tween<double>(begin: 0.4, end: 1.0).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animation,
      builder: (context, child) {
        return Container(
          width: 9,
          height: 9,
          decoration: BoxDecoration(
            color: widget.color.withValues(alpha: _animation.value),
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: widget.color.withValues(alpha: _animation.value * 0.6),
                blurRadius: 6,
                spreadRadius: 1,
              ),
            ],
          ),
        );
      },
    );
  }
}

/// 개별 기업 영향 행 위젯이다.
class _CompanyImpactRow extends StatelessWidget {
  final String ticker;
  final String impact;

  const _CompanyImpactRow({required this.ticker, required this.impact});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 티커 뱃지
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
            decoration: BoxDecoration(
              color: context.tc.primary.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusSm,
              border: Border.all(
                color: context.tc.primary.withValues(alpha: 0.25),
                width: 1,
              ),
            ),
            child: Text(
              ticker,
              style: AppTypography.labelMedium.copyWith(
                fontSize: 10,
                color: context.tc.primary,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          AppSpacing.hGapSm,
          // 영향 설명
          Expanded(
            child: Text(
              impact,
              style: AppTypography.bodySmall.copyWith(
                fontSize: 11,
                color: context.tc.textSecondary,
                height: 1.5,
              ),
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}
