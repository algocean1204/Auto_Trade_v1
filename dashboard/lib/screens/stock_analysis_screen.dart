import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:fl_chart/fl_chart.dart';
import '../providers/stock_analysis_provider.dart';
import '../providers/locale_provider.dart';
import '../models/stock_analysis_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';

// ─────────────────────────────────────────────────────────
// 테마 인식 색상 헬퍼 함수
// ─────────────────────────────────────────────────────────

/// RSI 값에 따른 테마 인식 색상을 반환한다.
Color _rsiColor(BuildContext context, double rsi) {
  if (rsi > 70) return context.tc.loss;
  if (rsi < 30) return context.tc.profit;
  return context.tc.textTertiary;
}

/// MACD 신호에 따른 테마 인식 색상을 반환한다.
Color _macdSignalColor(BuildContext context, String signal) {
  switch (signal.toLowerCase()) {
    case 'bullish':
      return context.tc.profit;
    case 'bearish':
      return context.tc.loss;
    default:
      return context.tc.warning;
  }
}

/// 추세 값에 따른 테마 인식 색상을 반환한다.
Color _trendSignalColor(BuildContext context, String trend) {
  switch (trend.toLowerCase()) {
    case 'uptrend':
    case 'up':
      return context.tc.profit;
    case 'downtrend':
    case 'down':
      return context.tc.loss;
    default:
      return context.tc.warning;
  }
}

/// direction 값에 따른 테마 인식 색상을 반환한다.
Color _directionColor(BuildContext context, String direction) {
  switch (direction.toLowerCase()) {
    case 'bullish':
      return context.tc.profit;
    case 'bearish':
      return context.tc.loss;
    default:
      return context.tc.warning;
  }
}

/// action 값에 따른 테마 인식 색상을 반환한다.
Color _actionColor(BuildContext context, String action) {
  switch (action.toLowerCase()) {
    case 'buy':
      return context.tc.profit;
    case 'sell':
      return context.tc.loss;
    default:
      return context.tc.warning;
  }
}

/// impact 값에 따른 테마 인식 색상을 반환한다.
Color _impactColor(BuildContext context, String impact) {
  switch (impact.toLowerCase()) {
    case 'high':
      return context.tc.loss;
    case 'medium':
      return context.tc.warning;
    default:
      return context.tc.textTertiary;
  }
}

/// 종목 종합 분석 화면이다.
class StockAnalysisScreen extends StatefulWidget {
  const StockAnalysisScreen({super.key});

  @override
  State<StockAnalysisScreen> createState() => _StockAnalysisScreenState();
}

class _StockAnalysisScreenState extends State<StockAnalysisScreen> {
  // ── 테마 인식 색상 헬퍼 ──

  /// priceChangePct 값에 따른 테마 색상을 반환한다.
  Color _priceChangeColor(BuildContext context, double pct) =>
      pct >= 0 ? context.tc.profit : context.tc.loss;

  @override
  void initState() {
    super.initState();
    // 화면 진입 시 티커 목록을 로드하고, 첫 번째 종목의 분석 결과를 즉시 로드한다.
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final provider = context.read<StockAnalysisProvider>();
      await provider.loadTickers();
      if (!provider.isLoading && provider.data == null) {
        provider.loadAnalysis(provider.selectedTicker);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    final provider = context.watch<StockAnalysisProvider>();

    return Scaffold(
      backgroundColor: context.tc.background,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildHeader(context, t, provider),
          Expanded(
            child: _buildBody(context, t, provider),
          ),
        ],
      ),
    );
  }

  /// lastUpdated DateTime을 수동 포맷 문자열로 반환한다.
  String _formatLastUpdated(
    BuildContext context,
    DateTime dt,
    String Function(String) t,
  ) {
    final local = dt.toLocal();
    final y = local.year.toString();
    final mo = local.month.toString().padLeft(2, '0');
    final d = local.day.toString().padLeft(2, '0');
    final h = local.hour.toString().padLeft(2, '0');
    final min = local.minute.toString().padLeft(2, '0');
    final s = local.second.toString().padLeft(2, '0');
    return '${t('last_updated')}: $y-$mo-$d $h:$min:$s';
  }

  Widget _buildHeader(
    BuildContext context,
    String Function(String) t,
    StockAnalysisProvider provider,
  ) {
    return Container(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.xl,
        AppSpacing.lg,
        AppSpacing.xl,
        AppSpacing.lg,
      ),
      decoration: BoxDecoration(
        color: context.tc.surface,
        border: Border(
          bottom: BorderSide(
            color: context.tc.surfaceBorder.withValues(alpha: 0.3),
            width: 1,
          ),
        ),
      ),
      child: Row(
        children: [
          Icon(Icons.query_stats_rounded, size: 22, color: context.tc.primary),
          AppSpacing.hGapMd,
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  t('stock_analysis_title'),
                  style: AppTypography.displaySmall,
                ),
                // 마지막 업데이트 시각 또는 설명 텍스트를 표시한다.
                if (provider.isLoading)
                  Text(
                    t('refreshing'),
                    style: AppTypography.bodySmall.copyWith(
                      color: context.tc.primary,
                    ),
                  )
                else if (provider.lastUpdated != null)
                  Text(
                    _formatLastUpdated(context, provider.lastUpdated!, t),
                    style: AppTypography.bodySmall.copyWith(
                      color: context.tc.textTertiary,
                    ),
                  )
                else
                  Text(
                    t('stock_analysis_desc'),
                    style: AppTypography.bodySmall,
                  ),
              ],
            ),
          ),
          // 티커 선택 드롭다운
          _TickerDropdown(
            selectedTicker: provider.selectedTicker,
            onChanged: (ticker) {
              if (ticker != null) {
                context.read<StockAnalysisProvider>().changeTicker(ticker);
              }
            },
          ),
          AppSpacing.hGapMd,
          // 새로고침 버튼
          IconButton(
            onPressed: provider.isLoading ? null : provider.refresh,
            icon: provider.isLoading
                ? SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: context.tc.primary,
                    ),
                  )
                : Icon(Icons.refresh_rounded,
                    size: 20, color: context.tc.textSecondary),
            tooltip: t('refresh'),
          ),
        ],
      ),
    );
  }

  Widget _buildBody(
    BuildContext context,
    String Function(String) t,
    StockAnalysisProvider provider,
  ) {
    if (provider.isLoading) {
      return _LoadingView(ticker: provider.selectedTicker, t: t);
    }

    if (provider.error != null) {
      return _ErrorView(
        error: provider.error ?? '',
        onRetry: provider.refresh,
        t: t,
      );
    }

    if (provider.data == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.search_off_rounded,
              size: 56,
              color: context.tc.textTertiary,
            ),
            AppSpacing.vGapLg,
            Text(
              t('no_analysis_data'),
              style: AppTypography.headlineMedium,
            ),
            AppSpacing.vGapSm,
            Text(
              provider.selectedTicker,
              style: AppTypography.labelLarge.copyWith(
                color: context.tc.primary,
              ),
            ),
            AppSpacing.vGapLg,
            ElevatedButton.icon(
              onPressed: provider.isLoading ? null : provider.refresh,
              icon: const Icon(Icons.refresh_rounded),
              label: Text(t('refresh')),
              style: ElevatedButton.styleFrom(
                backgroundColor: context.tc.primary,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.xl, vertical: AppSpacing.md),
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                ),
              ),
            ),
          ],
        ),
      );
    }

    final analysisData = provider.data;
    if (analysisData == null) {
      return Center(
        child: Text(
          t('no_analysis_data'),
          style: AppTypography.bodyMedium,
        ),
      );
    }

    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 가격 정보 + 기술적 지표 패널
          _buildPriceAndTechRow(context, t, analysisData),
          AppSpacing.vGapLg,
          // 현재 상황 분석
          _buildCurrentSituationCard(context, t, analysisData),
          AppSpacing.vGapLg,
          // 기간별 예측
          _buildPredictionsRow(context, t, analysisData),
          AppSpacing.vGapLg,
          // 리스크 + 매매 추천
          _buildRiskAndRecommendRow(context, t, analysisData),
          AppSpacing.vGapLg,
          // 관련 뉴스
          _buildRelatedNews(context, t, analysisData),
          AppSpacing.vGapXxl,
        ],
      ),
    );
  }

  Widget _buildPriceAndTechRow(
    BuildContext context,
    String Function(String) t,
    StockAnalysisData data,
  ) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 왼쪽: 가격 차트
        Expanded(
          flex: 3,
          child: GlassCard(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 현재가 정보
                Row(
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          data.ticker,
                          style: AppTypography.labelLarge.copyWith(
                            color: context.tc.primary,
                            fontSize: 16,
                          ),
                        ),
                        Row(
                          children: [
                            Text(
                              '\$${data.currentPrice.toStringAsFixed(2)}',
                              style: AppTypography.numberLarge,
                            ),
                            AppSpacing.hGapMd,
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 8, vertical: 3),
                              decoration: BoxDecoration(
                                color: _priceChangeColor(context, data.priceChangePct).withValues(alpha: 0.15),
                                borderRadius: AppSpacing.borderRadiusSm,
                              ),
                              child: Text(
                                data.priceChangeLabel,
                                style: AppTypography.labelMedium.copyWith(
                                  color: _priceChangeColor(context, data.priceChangePct),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                    const Spacer(),
                    Text(
                      t('price_chart'),
                      style: AppTypography.labelMedium,
                    ),
                  ],
                ),
                AppSpacing.vGapMd,
                // 가격 차트
                SizedBox(
                  height: 220,
                  child: _PriceChart(data: data, t: t),
                ),
              ],
            ),
          ),
        ),
        AppSpacing.hGapLg,
        // 오른쪽: 기술적 지표 패널
        SizedBox(
          width: 220,
          child: _TechnicalPanel(data: data, t: t),
        ),
      ],
    );
  }

  Widget _buildCurrentSituationCard(
    BuildContext context,
    String Function(String) t,
    StockAnalysisData data,
  ) {
    final ai = data.aiAnalysis;
    return GlassCard(
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.analytics_rounded, size: 18, color: context.tc.primary),
              AppSpacing.hGapSm,
              Text(t('current_situation'), style: AppTypography.labelLarge),
              const Spacer(),
              if (!data.aiAvailable)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: context.tc.warning.withValues(alpha: 0.15),
                    borderRadius: AppSpacing.borderRadiusSm,
                    border: Border.all(
                      color: context.tc.warning.withValues(alpha: 0.3),
                      width: 1,
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.info_outline_rounded,
                          size: 12, color: context.tc.warning),
                      AppSpacing.hGapXs,
                      Text(
                        t('ai_unavailable'),
                        style: AppTypography.bodySmall.copyWith(
                          color: context.tc.warning,
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),
          AppSpacing.vGapMd,
          Text(
            ai.currentSituation.isNotEmpty
                ? ai.currentSituation
                : ai.reasoning,
            style: AppTypography.bodyMedium.copyWith(
              color: context.tc.textSecondary,
              height: 1.7,
            ),
          ),
          if (ai.keyFactors.isNotEmpty) ...[
            AppSpacing.vGapMd,
            Text(t('key_factors'), style: AppTypography.labelMedium),
            AppSpacing.vGapSm,
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: ai.keyFactors
                  .map((factor) => _FactorChip(text: factor))
                  .toList(),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildPredictionsRow(
    BuildContext context,
    String Function(String) t,
    StockAnalysisData data,
  ) {
    final predictions = data.aiAnalysis.predictions;
    if (predictions.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(Icons.timeline_rounded, size: 18, color: context.tc.primary),
            AppSpacing.hGapSm,
            Text(t('predictions'), style: AppTypography.labelLarge),
          ],
        ),
        AppSpacing.vGapMd,
        SizedBox(
          height: 180,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: predictions.length,
            separatorBuilder: (_, __) => AppSpacing.hGapMd,
            itemBuilder: (context, index) {
              return _PredictionCard(
                prediction: predictions[index],
                currentPrice: data.currentPrice,
              );
            },
          ),
        ),
      ],
    );
  }

  Widget _buildRiskAndRecommendRow(
    BuildContext context,
    String Function(String) t,
    StockAnalysisData data,
  ) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 리스크 요인
        Expanded(
          child: GlassCard(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.warning_amber_rounded,
                        size: 18, color: context.tc.warning),
                    AppSpacing.hGapSm,
                    Text(t('risk_factors'), style: AppTypography.labelLarge),
                  ],
                ),
                AppSpacing.vGapMd,
                if (data.aiAnalysis.riskFactors.isEmpty)
                  Text(t('no_analysis_data'), style: AppTypography.bodySmall)
                else
                  ...data.aiAnalysis.riskFactors.map(
                    (risk) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Icon(
                              Icons.circle,
                              size: 6,
                              color: context.tc.warning,
                            ),
                          ),
                          AppSpacing.hGapSm,
                          Expanded(
                            child: Text(
                              risk,
                              style: AppTypography.bodySmall.copyWith(
                                color: context.tc.textSecondary,
                                height: 1.5,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
        AppSpacing.hGapLg,
        // 매매 추천
        Expanded(
          child: GlassCard(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.recommend_rounded,
                        size: 18, color: context.tc.primary),
                    AppSpacing.hGapSm,
                    Text(t('recommendation'), style: AppTypography.labelLarge),
                  ],
                ),
                AppSpacing.vGapMd,
                _RecommendationBadge(
                  recommendation: data.aiAnalysis.recommendation,
                ),
                AppSpacing.vGapMd,
                Text(
                  data.aiAnalysis.recommendation.reasoning,
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.textSecondary,
                    height: 1.6,
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildRelatedNews(
    BuildContext context,
    String Function(String) t,
    StockAnalysisData data,
  ) {
    final news = data.relatedNews;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(Icons.newspaper_rounded, size: 18, color: context.tc.primary),
            AppSpacing.hGapSm,
            Text(t('related_news'), style: AppTypography.labelLarge),
            AppSpacing.hGapMd,
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: context.tc.primary.withValues(alpha: 0.15),
                borderRadius: AppSpacing.borderRadiusFull,
              ),
              child: Text(
                '${news.length}',
                style: AppTypography.bodySmall.copyWith(
                  color: context.tc.primary,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
        AppSpacing.vGapMd,
        if (news.isEmpty)
          GlassCard(
            child: Center(
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: AppSpacing.xl),
                child: Text(t('no_news'), style: AppTypography.bodyMedium),
              ),
            ),
          )
        else
          _GroupedNewsList(news: news, t: t),
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────
// 티커 드롭다운
// ─────────────────────────────────────────────────────────

class _TickerDropdown extends StatelessWidget {
  final String selectedTicker;
  final ValueChanged<String?> onChanged;

  const _TickerDropdown({
    required this.selectedTicker,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<StockAnalysisProvider>();
    final tickers = provider.tickers.isNotEmpty
        ? provider.tickers
        : [selectedTicker];

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(
        color: context.tc.surfaceElevated,
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: context.tc.surfaceBorder.withValues(alpha: 0.6),
          width: 1,
        ),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: tickers.contains(selectedTicker) ? selectedTicker : tickers.first,
          onChanged: onChanged,
          dropdownColor: context.tc.surfaceElevated,
          icon: Icon(Icons.expand_more_rounded,
              size: 18, color: context.tc.textTertiary),
          style: AppTypography.labelLarge.copyWith(fontSize: 13),
          items: tickers.map((ticker) {
            return DropdownMenuItem<String>(
              value: ticker,
              child: Text(
                ticker,
                style: AppTypography.bodySmall.copyWith(
                  color: ticker == selectedTicker
                      ? context.tc.primary
                      : context.tc.textSecondary,
                ),
              ),
            );
          }).toList(),
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────
// 가격 차트
// ─────────────────────────────────────────────────────────

class _PriceChart extends StatefulWidget {
  final StockAnalysisData data;
  final String Function(String) t;

  const _PriceChart({required this.data, required this.t});

  @override
  State<_PriceChart> createState() => _PriceChartState();
}

class _PriceChartState extends State<_PriceChart> {
  @override
  Widget build(BuildContext context) {
    final history = widget.data.priceHistory;
    if (history.isEmpty) {
      return Center(
        child: Text(widget.t('no_chart_data'),
            style: AppTypography.bodySmall),
      );
    }

    final prices = history.map((p) => p.close).toList();
    final minPrice = prices.reduce(math.min);
    final maxPrice = prices.reduce(math.max);
    final priceRange = maxPrice - minPrice;
    // 가격 범위가 0일 때 division-by-zero를 방지한다.
    final safeRange = priceRange > 0
        ? priceRange
        : (maxPrice * 0.01).clamp(0.01, double.infinity);
    final paddedMin = minPrice - safeRange * 0.05;
    final paddedMax = maxPrice + safeRange * 0.05;

    final support = widget.data.technicalSummary.support;
    final resistance = widget.data.technicalSummary.resistance;

    final spots = history.asMap().entries.map((e) {
      return FlSpot(e.key.toDouble(), e.value.close);
    }).toList();

    return LineChart(
      LineChartData(
        minY: paddedMin,
        maxY: paddedMax,
        gridData: FlGridData(
          show: true,
          drawVerticalLine: false,
          horizontalInterval: safeRange / 4,
          getDrawingHorizontalLine: (value) => FlLine(
            color: context.tc.chartGrid,
            strokeWidth: 1,
          ),
        ),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          leftTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 60,
              interval: safeRange / 4,
              getTitlesWidget: (value, meta) {
                return Text(
                  '\$${value.toStringAsFixed(0)}',
                  style: AppTypography.bodySmall.copyWith(fontSize: 10),
                );
              },
            ),
          ),
          rightTitles: const AxisTitles(
            sideTitles: SideTitles(showTitles: false),
          ),
          topTitles: const AxisTitles(
            sideTitles: SideTitles(showTitles: false),
          ),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              interval: (history.length / 6).ceilToDouble(),
              reservedSize: 24,
              getTitlesWidget: (value, meta) {
                final idx = value.toInt();
                if (idx < 0 || idx >= history.length) {
                  return const SizedBox.shrink();
                }
                final date = history[idx].date;
                // MM-DD 형식으로 표시한다.
                final parts = date.split('-');
                final label = parts.length >= 3
                    ? '${parts[1]}/${parts[2]}'
                    : date;
                return Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    label,
                    style:
                        AppTypography.bodySmall.copyWith(fontSize: 9),
                  ),
                );
              },
            ),
          ),
        ),
        lineTouchData: LineTouchData(
          touchTooltipData: LineTouchTooltipData(
            getTooltipColor: (_) => context.tc.surfaceElevated,
            getTooltipItems: (touchedSpots) {
              return touchedSpots.map((spot) {
                final idx = spot.x.toInt();
                final date = idx < history.length
                    ? history[idx].date
                    : '';
                return LineTooltipItem(
                  '$date\n\$${spot.y.toStringAsFixed(2)}',
                  AppTypography.bodySmall.copyWith(
                    color: context.tc.primary,
                    fontWeight: FontWeight.w600,
                  ),
                );
              }).toList();
            },
          ),
        ),
        extraLinesData: ExtraLinesData(
          horizontalLines: [
            // 지지선
            if (support > paddedMin && support < paddedMax)
              HorizontalLine(
                y: support,
                color: context.tc.profit.withValues(alpha: 0.6),
                strokeWidth: 1,
                dashArray: [6, 4],
                label: HorizontalLineLabel(
                  show: true,
                  alignment: Alignment.topRight,
                  labelResolver: (_) =>
                      '${widget.t('support')} \$${support.toStringAsFixed(0)}',
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.profit,
                    fontSize: 9,
                  ),
                ),
              ),
            // 저항선
            if (resistance > paddedMin && resistance < paddedMax)
              HorizontalLine(
                y: resistance,
                color: context.tc.loss.withValues(alpha: 0.6),
                strokeWidth: 1,
                dashArray: [6, 4],
                label: HorizontalLineLabel(
                  show: true,
                  alignment: Alignment.topRight,
                  labelResolver: (_) =>
                      '${widget.t('resistance')} \$${resistance.toStringAsFixed(0)}',
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.loss,
                    fontSize: 9,
                  ),
                ),
              ),
          ],
        ),
        lineBarsData: [
          LineChartBarData(
            spots: spots,
            isCurved: true,
            curveSmoothness: 0.3,
            color: context.tc.primary,
            barWidth: 2,
            isStrokeCapRound: true,
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(
              show: true,
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [
                  context.tc.primary.withValues(alpha: 0.2),
                  context.tc.primary.withValues(alpha: 0.0),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────
// 기술적 지표 패널
// ─────────────────────────────────────────────────────────

class _TechnicalPanel extends StatelessWidget {
  final StockAnalysisData data;
  final String Function(String) t;

  const _TechnicalPanel({required this.data, required this.t});

  @override
  Widget build(BuildContext context) {
    final tech = data.technicalSummary;
    return GlassCard(
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('technical_indicators'), style: AppTypography.labelLarge),
          AppSpacing.vGapMd,
          // 종합 점수 게이지
          _CompositeScoreGauge(score: tech.compositeScore, t: t),
          AppSpacing.vGapMd,
          Divider(color: context.tc.surfaceBorder, height: 1),
          AppSpacing.vGapMd,
          // RSI
          _TechRow(
            label: 'RSI(14)',
            value: tech.rsi14.toStringAsFixed(1),
            valueColor: _rsiColor(context, tech.rsi14),
            badge: tech.rsiLabel,
            badgeColor: _rsiColor(context, tech.rsi14),
          ),
          AppSpacing.vGapSm,
          // MACD
          _TechRow(
            label: 'MACD',
            value: tech.macdSignal,
            valueColor: _macdSignalColor(context, tech.macdSignal),
          ),
          AppSpacing.vGapSm,
          // 추세
          _TechRow(
            label: t('trend'),
            value: _trendLabel(tech.trend),
            valueColor: _trendSignalColor(context, tech.trend),
          ),
          AppSpacing.vGapMd,
          Divider(color: context.tc.surfaceBorder, height: 1),
          AppSpacing.vGapMd,
          // 지지
          _PriceLevelRow(
            label: t('support'),
            price: tech.support,
            color: context.tc.profit,
          ),
          AppSpacing.vGapSm,
          // 저항
          _PriceLevelRow(
            label: t('resistance'),
            price: tech.resistance,
            color: context.tc.loss,
          ),
        ],
      ),
    );
  }

  String _trendLabel(String trend) {
    switch (trend.toLowerCase()) {
      case 'uptrend':
      case 'up':
        return t('trend_up');
      case 'downtrend':
      case 'down':
        return t('trend_down');
      default:
        return t('trend_sideways');
    }
  }
}

class _CompositeScoreGauge extends StatelessWidget {
  final double score;
  final String Function(String) t;

  const _CompositeScoreGauge({required this.score, required this.t});

  @override
  Widget build(BuildContext context) {
    final color = score > 0.3
        ? context.tc.profit
        : score < -0.3
            ? context.tc.loss
            : context.tc.warning;
    final normalizedScore = ((score + 1) / 2).clamp(0.0, 1.0);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(t('composite_score'), style: AppTypography.bodySmall),
            Text(
              score.toStringAsFixed(2),
              style: AppTypography.numberSmall.copyWith(color: color),
            ),
          ],
        ),
        AppSpacing.vGapSm,
        ClipRRect(
          borderRadius: AppSpacing.borderRadiusFull,
          child: LinearProgressIndicator(
            value: normalizedScore,
            backgroundColor: context.tc.surfaceBorder.withValues(alpha: 0.5),
            valueColor: AlwaysStoppedAnimation<Color>(color),
            minHeight: 8,
          ),
        ),
      ],
    );
  }
}

class _TechRow extends StatelessWidget {
  final String label;
  final String value;
  final Color valueColor;
  final String? badge;
  final Color? badgeColor;

  const _TechRow({
    required this.label,
    required this.value,
    required this.valueColor,
    this.badge,
    this.badgeColor,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: AppTypography.bodySmall),
        Row(
          children: [
            Text(
              value,
              style: AppTypography.bodySmall.copyWith(
                color: valueColor,
                fontWeight: FontWeight.w600,
              ),
            ),
            if (badge != null) ...[
              AppSpacing.hGapXs,
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                decoration: BoxDecoration(
                  color: (badgeColor ?? context.tc.textTertiary).withValues(alpha: 0.15),
                  borderRadius: AppSpacing.borderRadiusSm,
                ),
                child: Text(
                  badge ?? '',
                  style: AppTypography.bodySmall.copyWith(
                    color: badgeColor ?? context.tc.textTertiary,
                    fontSize: 9,
                  ),
                ),
              ),
            ],
          ],
        ),
      ],
    );
  }
}

class _PriceLevelRow extends StatelessWidget {
  final String label;
  final double price;
  final Color color;

  const _PriceLevelRow({
    required this.label,
    required this.price,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Row(
          children: [
            Container(
              width: 8,
              height: 1,
              color: color,
              margin: const EdgeInsets.only(right: 6),
            ),
            Text(label,
                style: AppTypography.bodySmall.copyWith(color: color)),
          ],
        ),
        Text(
          price > 0 ? '\$${price.toStringAsFixed(2)}' : '-',
          style: AppTypography.numberSmall.copyWith(color: color),
        ),
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────
// 핵심 요인 칩
// ─────────────────────────────────────────────────────────

class _FactorChip extends StatelessWidget {
  final String text;

  const _FactorChip({required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: context.tc.primary.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusFull,
        border: Border.all(
          color: context.tc.primary.withValues(alpha: 0.25),
          width: 1,
        ),
      ),
      child: Text(
        text,
        style: AppTypography.bodySmall.copyWith(
          color: context.tc.primary,
          fontWeight: FontWeight.w500,
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────
// 기간별 예측 카드
// ─────────────────────────────────────────────────────────

class _PredictionCard extends StatefulWidget {
  final Prediction prediction;
  final double currentPrice;

  const _PredictionCard({
    required this.prediction,
    required this.currentPrice,
  });

  @override
  State<_PredictionCard> createState() => _PredictionCardState();
}

class _PredictionCardState extends State<_PredictionCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final p = widget.prediction;
    final color = _directionColor(context, p.direction);
    final confidence = p.confidence / 100.0;

    return GestureDetector(
      onTap: () => setState(() => _expanded = !_expanded),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        width: _expanded ? 200 : 140,
        decoration: BoxDecoration(
          color: context.tc.surfaceElevated,
          borderRadius: AppSpacing.borderRadiusLg,
          border: Border.all(
            color: color.withValues(alpha: 0.3),
            width: 1,
          ),
        ),
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            // 기간 레이블
            Text(
              p.timeframe,
              style: AppTypography.labelMedium.copyWith(
                color: context.tc.textTertiary,
                fontSize: 11,
              ),
            ),
            AppSpacing.vGapSm,
            // 방향 아이콘 + 신뢰도
            Row(
              children: [
                Icon(p.directionIcon, size: 22, color: color),
                AppSpacing.hGapSm,
                Text(
                  '${p.confidence}%',
                  style: AppTypography.numberSmall.copyWith(color: color),
                ),
              ],
            ),
            AppSpacing.vGapSm,
            // 신뢰도 바
            ClipRRect(
              borderRadius: AppSpacing.borderRadiusFull,
              child: LinearProgressIndicator(
                value: confidence,
                backgroundColor: context.tc.surfaceBorder.withValues(alpha: 0.5),
                valueColor: AlwaysStoppedAnimation<Color>(color),
                minHeight: 4,
              ),
            ),
            AppSpacing.vGapSm,
            // 목표가
            if (p.targetPrice > 0)
              Text(
                '\$${p.targetPrice.toStringAsFixed(2)}',
                style: AppTypography.numberSmall.copyWith(
                  color: context.tc.textSecondary,
                  fontSize: 12,
                ),
              ),
            // 확장 시 이유 표시
            if (_expanded && p.reasoning.isNotEmpty) ...[
              AppSpacing.vGapSm,
              Divider(color: context.tc.surfaceBorder, height: 1),
              AppSpacing.vGapSm,
              Text(
                p.reasoning,
                style: AppTypography.bodySmall.copyWith(
                  color: context.tc.textTertiary,
                  fontSize: 10,
                  height: 1.5,
                ),
                maxLines: 4,
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────
// 매매 추천 뱃지
// ─────────────────────────────────────────────────────────

class _RecommendationBadge extends StatelessWidget {
  final Recommendation recommendation;

  const _RecommendationBadge({required this.recommendation});

  @override
  Widget build(BuildContext context) {
    final color = _actionColor(context, recommendation.action);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(color: color.withValues(alpha: 0.4), width: 1),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            recommendation.action.toLowerCase() == 'buy'
                ? Icons.arrow_upward_rounded
                : recommendation.action.toLowerCase() == 'sell'
                    ? Icons.arrow_downward_rounded
                    : Icons.remove_rounded,
            size: 18,
            color: color,
          ),
          AppSpacing.hGapSm,
          Text(
            recommendation.actionLabel,
            style: AppTypography.labelLarge.copyWith(
              color: color,
              fontSize: 18,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────
// 날짜별 그룹핑된 뉴스 목록
// ─────────────────────────────────────────────────────────

class _GroupedNewsList extends StatelessWidget {
  final List<AnalysisNews> news;
  final String Function(String) t;

  const _GroupedNewsList({required this.news, required this.t});

  @override
  Widget build(BuildContext context) {
    // 날짜별 그룹핑한다.
    final grouped = <String, List<AnalysisNews>>{};
    for (final article in news) {
      final key = article.dateKey;
      grouped.putIfAbsent(key, () => []).add(article);
    }

    final sortedDates = grouped.keys.toList()..sort((a, b) => b.compareTo(a));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: sortedDates.map((date) {
        final articles = grouped[date] ?? [];
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 날짜 구분선
            Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
              child: Row(
                children: [
                  Text(
                    date.isEmpty ? t('date_unknown') : date,
                    style: AppTypography.labelMedium.copyWith(
                      color: context.tc.textTertiary,
                      fontSize: 11,
                    ),
                  ),
                  AppSpacing.hGapMd,
                  Expanded(
                    child: Container(
                      height: 1,
                      color: context.tc.surfaceBorder.withValues(alpha: 0.4),
                    ),
                  ),
                ],
              ),
            ),
            ...articles.map((article) => _NewsItemCard(article: article, t: t)),
          ],
        );
      }).toList(),
    );
  }
}

class _NewsItemCard extends StatefulWidget {
  final AnalysisNews article;
  final String Function(String) t;

  const _NewsItemCard({required this.article, required this.t});

  @override
  State<_NewsItemCard> createState() => _NewsItemCardState();
}

class _NewsItemCardState extends State<_NewsItemCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final article = widget.article;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: GlassCard(
        padding: const EdgeInsets.all(AppSpacing.md),
        onTap: () => setState(() => _expanded = !_expanded),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 헤더 행: 임팩트 뱃지 + 헤드라인 + 소스 + 시간
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 임팩트 뱃지
                Builder(
                  builder: (context) {
                    final impactClr = _impactColor(context, article.impact);
                    return Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: impactClr.withValues(alpha: 0.15),
                        borderRadius: AppSpacing.borderRadiusSm,
                        border: Border.all(
                          color: impactClr.withValues(alpha: 0.3),
                          width: 1,
                        ),
                      ),
                      child: Text(
                        article.impactLabel,
                        style: AppTypography.bodySmall.copyWith(
                          color: impactClr,
                          fontSize: 9,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    );
                  },
                ),
                AppSpacing.hGapSm,
                // 헤드라인
                Expanded(
                  child: Text(
                    article.headline,
                    style: AppTypography.bodySmall.copyWith(
                      color: context.tc.textSecondary,
                      height: 1.5,
                    ),
                    maxLines: _expanded ? null : 2,
                    overflow: _expanded ? null : TextOverflow.ellipsis,
                  ),
                ),
                AppSpacing.hGapSm,
                // 소스 + 시간
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      article.sourceLabel,
                      style: AppTypography.bodySmall.copyWith(
                        color: context.tc.primary,
                        fontSize: 10,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (article.timeLabel.isNotEmpty)
                      Text(
                        article.timeLabel,
                        style: AppTypography.bodySmall.copyWith(
                          color: context.tc.textTertiary,
                          fontSize: 9,
                        ),
                      ),
                  ],
                ),
                // 확장 아이콘
                Icon(
                  _expanded
                      ? Icons.expand_less_rounded
                      : Icons.expand_more_rounded,
                  size: 16,
                  color: context.tc.textTertiary,
                ),
              ],
            ),
            // 확장 내용
            AnimatedCrossFade(
              firstChild: const SizedBox.shrink(),
              secondChild: _buildExpandedContent(article),
              crossFadeState: _expanded
                  ? CrossFadeState.showSecond
                  : CrossFadeState.showFirst,
              duration: const Duration(milliseconds: 200),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildExpandedContent(AnalysisNews article) {
    final t = widget.t;
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Divider(color: context.tc.surfaceBorder, height: 1),
          AppSpacing.vGapMd,
          // 영어 원문 헤드라인
          if (article.headlineOriginal != null &&
              article.headlineOriginal != article.headline) ...[
            Text(
              t('original_text'),
              style: AppTypography.bodySmall.copyWith(
                color: context.tc.textTertiary,
                fontSize: 10,
              ),
            ),
            AppSpacing.vGapXs,
            Text(
              article.headlineOriginal ?? '',
              style: AppTypography.bodySmall.copyWith(
                color: context.tc.textTertiary,
                fontStyle: FontStyle.italic,
                fontSize: 11,
              ),
            ),
            AppSpacing.vGapMd,
          ],
          // 한국어 요약
          if (article.summaryKo != null && (article.summaryKo ?? '').isNotEmpty) ...[
            Text(
              t('summary_text'),
              style: AppTypography.bodySmall.copyWith(
                color: context.tc.textTertiary,
                fontSize: 10,
              ),
            ),
            AppSpacing.vGapXs,
            Text(
              article.summaryKo ?? '',
              style: AppTypography.bodySmall.copyWith(
                color: context.tc.textSecondary,
                height: 1.6,
              ),
            ),
            AppSpacing.vGapMd,
          ],
          // 감성 점수
          if (article.sentimentScore != null)
            Row(
              children: [
                Text(
                  '${t('sentiment_score')}: ',
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.textTertiary,
                    fontSize: 10,
                  ),
                ),
                Text(
                  (article.sentimentScore ?? 0.0).toStringAsFixed(2),
                  style: AppTypography.bodySmall.copyWith(
                    color: (article.sentimentScore ?? 0.0) >= 0
                        ? context.tc.profit
                        : context.tc.loss,
                    fontWeight: FontWeight.w600,
                    fontSize: 10,
                  ),
                ),
              ],
            ),
          // 기업별 영향
          if (article.companiesImpact != null &&
              (article.companiesImpact ?? {}).isNotEmpty) ...[
            if (article.sentimentScore != null) AppSpacing.vGapMd,
            Text(
              t('company_impact'),
              style: AppTypography.bodySmall.copyWith(
                color: context.tc.textTertiary,
                fontSize: 10,
              ),
            ),
            AppSpacing.vGapSm,
            ...(article.companiesImpact ?? {}).entries.map(
              (entry) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 5, vertical: 1),
                      decoration: BoxDecoration(
                        color: context.tc.primary.withValues(alpha: 0.15),
                        borderRadius: AppSpacing.borderRadiusSm,
                      ),
                      child: Text(
                        entry.key,
                        style: AppTypography.bodySmall.copyWith(
                          color: context.tc.primary,
                          fontSize: 9,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    AppSpacing.hGapSm,
                    Expanded(
                      child: Text(
                        entry.value,
                        style: AppTypography.bodySmall.copyWith(
                          color: context.tc.textTertiary,
                          fontSize: 10,
                          height: 1.5,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────
// 로딩 뷰
// ─────────────────────────────────────────────────────────

class _LoadingView extends StatelessWidget {
  final String ticker;
  final String Function(String) t;

  const _LoadingView({required this.ticker, required this.t});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          SizedBox(
            width: 56,
            height: 56,
            child: CircularProgressIndicator(
              strokeWidth: 3,
              color: context.tc.primary,
            ),
          ),
          AppSpacing.vGapXl,
          Text(
            ticker,
            style: AppTypography.displaySmall.copyWith(
              color: context.tc.primary,
            ),
          ),
          AppSpacing.vGapSm,
          Text(
            t('analyzing'),
            style: AppTypography.bodyMedium,
          ),
          AppSpacing.vGapSm,
          Text(
            t('analyzing_detail'),
            style: AppTypography.bodySmall,
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────
// 에러 뷰
// ─────────────────────────────────────────────────────────

class _ErrorView extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;
  final String Function(String) t;

  const _ErrorView({
    required this.error,
    required this.onRetry,
    required this.t,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.error_outline_rounded,
              size: 48, color: context.tc.loss),
          AppSpacing.vGapLg,
          Text(t('connection_error'), style: AppTypography.headlineMedium),
          AppSpacing.vGapSm,
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
            child: Text(
              error,
              style: AppTypography.bodySmall,
              textAlign: TextAlign.center,
            ),
          ),
          AppSpacing.vGapLg,
          ElevatedButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh_rounded),
            label: Text(t('retry')),
            style: ElevatedButton.styleFrom(
              backgroundColor: context.tc.primary,
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.xl, vertical: AppSpacing.md),
              shape: RoundedRectangleBorder(
                borderRadius: AppSpacing.borderRadiusMd,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
