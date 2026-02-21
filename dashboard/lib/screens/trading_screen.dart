import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/dashboard_provider.dart';
import '../providers/tax_fx_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/app_typography.dart';
import '../theme/trading_colors.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/section_header.dart';
import '../animations/animation_utils.dart';

class TradingScreen extends StatefulWidget {
  const TradingScreen({super.key});

  @override
  State<TradingScreen> createState() => _TradingScreenState();
}

class _TradingScreenState extends State<TradingScreen> {
  // 포지션 정렬 기준
  String _sortBy = 'pnl';
  bool _sortAsc = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<DashboardProvider>().loadDashboardData();
      context.read<TaxFxProvider>().loadAll();
    });
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Scaffold(
      backgroundColor: context.tc.background,
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 상단 섹션 타이틀
            Text(t('trading'), style: AppTypography.displayMedium),
            AppSpacing.vGapXxl,
            // 레이아웃
            LayoutBuilder(
              builder: (context, constraints) {
                if (constraints.maxWidth >= 900) {
                  return _buildWideLayout();
                }
                return _buildNarrowLayout();
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildWideLayout() {
    return Column(
      children: [
        StaggeredFadeSlide(
          index: 0,
          child: _buildPositionsCard(),
        ),
        AppSpacing.vGapLg,
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: StaggeredFadeSlide(
                index: 1,
                child: _buildFxCard(),
              ),
            ),
            AppSpacing.hGapLg,
            Expanded(
              child: StaggeredFadeSlide(
                index: 2,
                child: _buildTaxCard(),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildNarrowLayout() {
    return Column(
      children: [
        StaggeredFadeSlide(index: 0, child: _buildPositionsCard()),
        AppSpacing.vGapLg,
        StaggeredFadeSlide(index: 1, child: _buildFxCard()),
        AppSpacing.vGapLg,
        StaggeredFadeSlide(index: 2, child: _buildTaxCard()),
      ],
    );
  }

  // ── 포지션 테이블 ──

  Widget _buildPositionsCard() {
    final t = context.watch<LocaleProvider>().t;
    return Consumer<DashboardProvider>(
      builder: (context, provider, _) {
        if (provider.isLoading && provider.summary == null) {
          return ShimmerLoading(
            width: double.infinity,
            height: 200,
            borderRadius: AppSpacing.borderRadiusLg,
          );
        }

        final activeCount = provider.summary?.activePositions ?? 0;

        return GlassCard(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: SectionHeader(title: t('positions_title')),
                  ),
                  // 정렬 컨트롤
                  _buildSortChips(),
                  if (provider.isLoading)
                    Padding(
                      padding: const EdgeInsets.only(left: 8),
                      child: SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: context.tc.primary,
                        ),
                      ),
                    ),
                ],
              ),
              AppSpacing.vGapMd,
              if (activeCount == 0)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 24),
                  child: Center(
                    child: Column(
                      children: [
                        Icon(Icons.inbox_rounded,
                            size: 36, color: context.tc.textTertiary),
                        AppSpacing.vGapMd,
                        Text(t('no_active_positions'),
                            style: AppTypography.bodyMedium),
                      ],
                    ),
                  ),
                )
              else ...[
                // 테이블 헤더
                _buildTableHeader(),
                Divider(
                    height: 8,
                    color: context.tc.surfaceBorder.withValues(alpha: 0.3)),
                // 포지션 수 표시 (실제 데이터 없이 요약)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Row(
                    children: [
                      Icon(Icons.info_outline_rounded,
                          size: 14, color: context.tc.textTertiary),
                      AppSpacing.hGapSm,
                      Text(
                        t('connect_for_details')
                            .replaceAll('{n}', '$activeCount'),
                        style: AppTypography.bodySmall,
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _buildSortChips() {
    final t = context.watch<LocaleProvider>().t;
    final tc = context.tc;
    final options = [
      ('pnl', t('pnl')),
      ('ticker', t('ticker')),
      ('value', t('value')),
    ];
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: options.map((option) {
        final isSelected = _sortBy == option.$1;
        return Padding(
          padding: const EdgeInsets.only(left: 6),
          child: InkWell(
            onTap: () {
              setState(() {
                if (_sortBy == option.$1) {
                  _sortAsc = !_sortAsc;
                } else {
                  _sortBy = option.$1;
                  _sortAsc = false;
                }
              });
            },
            borderRadius: AppSpacing.borderRadiusSm,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: isSelected
                    ? tc.primary.withValues(alpha: 0.12)
                    : Colors.transparent,
                borderRadius: AppSpacing.borderRadiusSm,
                border: Border.all(
                  color: isSelected
                      ? tc.primary.withValues(alpha: 0.3)
                      : tc.surfaceBorder.withValues(alpha: 0.4),
                ),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    option.$2,
                    style: AppTypography.bodySmall.copyWith(
                      color: isSelected ? tc.primary : tc.textTertiary,
                      fontSize: 11,
                    ),
                  ),
                  if (isSelected) ...[
                    const SizedBox(width: 2),
                    Icon(
                      _sortAsc
                          ? Icons.arrow_upward_rounded
                          : Icons.arrow_downward_rounded,
                      size: 10,
                      color: tc.primary,
                    ),
                  ],
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildTableHeader() {
    final t = context.watch<LocaleProvider>().t;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(
            flex: 2,
            child: Text(t('ticker'), style: AppTypography.bodySmall),
          ),
          Expanded(
            flex: 2,
            child: Text(t('qty_avg'),
                style: AppTypography.bodySmall, textAlign: TextAlign.right),
          ),
          Expanded(
            flex: 2,
            child: Text(t('current'),
                style: AppTypography.bodySmall, textAlign: TextAlign.right),
          ),
          Expanded(
            flex: 2,
            child: Text(t('pnl'),
                style: AppTypography.bodySmall, textAlign: TextAlign.right),
          ),
          Expanded(
            flex: 2,
            child: Text(t('value'),
                style: AppTypography.bodySmall, textAlign: TextAlign.right),
          ),
        ],
      ),
    );
  }

  // ── FX 카드 ──

  Widget _buildFxCard() {
    return Consumer2<TaxFxProvider, LocaleProvider>(
      builder: (context, provider, locale, _) {
        final t = locale.t;
        final tc = context.tc;
        if (provider.isLoading && provider.fxStatus == null) {
          return ShimmerLoading(
            width: double.infinity,
            height: 160,
            borderRadius: AppSpacing.borderRadiusLg,
          );
        }

        final fx = provider.fxStatus;

        return GlassCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SectionHeader(title: t('fx_rate')),
              if (fx == null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Text(t('fx_unavailable'),
                      style: AppTypography.bodyMedium),
                )
              else ...[
                Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    AnimatedNumber(
                      value: fx.usdKrwRate,
                      style: AppTypography.numberMedium,
                      formatter: (v) => NumberFormat('#,##0.00').format(v),
                    ),
                    AppSpacing.hGapSm,
                    Text('USD/KRW', style: AppTypography.bodySmall),
                  ],
                ),
                AppSpacing.vGapSm,
                Row(
                  children: [
                    Icon(
                      fx.dailyChangePct >= 0
                          ? Icons.arrow_drop_up
                          : Icons.arrow_drop_down,
                      color: tc.pnlColor(fx.dailyChangePct),
                      size: 18,
                    ),
                    Text(
                      '${fx.dailyChangePct >= 0 ? '+' : ''}${fx.dailyChangePct.toStringAsFixed(2)}%',
                      style: AppTypography.numberSmall.copyWith(
                        color: tc.pnlColor(fx.dailyChangePct),
                      ),
                    ),
                    AppSpacing.hGapSm,
                    Text(t('today'), style: AppTypography.bodySmall),
                  ],
                ),
                AppSpacing.vGapMd,
                Text(
                  '${t('updated')}: ${DateFormat('HH:mm').format(fx.updatedAt)}',
                  style: AppTypography.bodySmall.copyWith(fontSize: 11),
                ),
              ],
              if (provider.error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Row(
                    children: [
                      Icon(Icons.warning_rounded,
                          size: 12, color: tc.warning),
                      AppSpacing.hGapXs,
                      Text(t('stale_data'),
                          style: AppTypography.bodySmall.copyWith(
                            color: tc.warning,
                            fontSize: 11,
                          )),
                    ],
                  ),
                ),
            ],
          ),
        );
      },
    );
  }

  // ── 세금 카드 ──

  Widget _buildTaxCard() {
    return Consumer2<TaxFxProvider, LocaleProvider>(
      builder: (context, provider, locale, _) {
        final t = locale.t;
        final tc = context.tc;
        if (provider.isLoading && provider.taxStatus == null) {
          return ShimmerLoading(
            width: double.infinity,
            height: 160,
            borderRadius: AppSpacing.borderRadiusLg,
          );
        }

        final tax = provider.taxStatus;

        return GlassCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SectionHeader(title: t('tax_status')),
              if (tax == null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Text(t('tax_unavailable'),
                      style: AppTypography.bodyMedium),
                )
              else ...[
                _buildTaxRow(
                  t('realized_gain'),
                  NumberFormat.currency(symbol: '\$', decimalDigits: 0)
                      .format(tax.realizedGainUsd),
                  tc.pnlColor(tax.realizedGainUsd),
                ),
                AppSpacing.vGapSm,
                _buildTaxRow(
                  t('est_tax'),
                  NumberFormat.currency(symbol: '\$', decimalDigits: 0)
                      .format(tax.estimatedTaxUsd),
                  tc.warning,
                ),
                AppSpacing.vGapSm,
                _buildTaxRow(
                  t('effective_rate'),
                  '${tax.effectiveTaxRate.toStringAsFixed(1)}%',
                  tc.textPrimary,
                ),
                AppSpacing.vGapSm,
                _buildTaxRow(
                  t('residency'),
                  tax.taxResidency,
                  tc.primary,
                ),
                // 손실 수확 제안
                if (provider.harvestSuggestions.isNotEmpty) ...[
                  Divider(
                    height: 20,
                    color: tc.surfaceBorder.withValues(alpha: 0.3),
                  ),
                  Row(
                    children: [
                      Icon(Icons.lightbulb_rounded,
                          size: 14, color: tc.warning),
                      AppSpacing.hGapXs,
                      Text(
                        t('harvest_suggestion').replaceAll(
                            '{n}', '${provider.harvestSuggestions.length}'),
                        style: AppTypography.bodySmall.copyWith(
                          color: tc.warning,
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _buildTaxRow(String label, String value, Color valueColor) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: AppTypography.bodyMedium),
        Text(
          value,
          style: AppTypography.numberSmall.copyWith(color: valueColor),
        ),
      ],
    );
  }
}
