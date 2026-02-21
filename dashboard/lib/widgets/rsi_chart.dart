import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../models/rsi_models.dart';
import '../theme/trading_colors.dart';
import '../theme/chart_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

/// 트리플 RSI 차트 위젯이다.
/// RSI(7), RSI(14), RSI(21) 지표를 탭으로 전환하거나 모두 표시한다.
class TripleRsiChart extends StatefulWidget {
  final TripleRsiData data;
  final double height;

  const TripleRsiChart({
    super.key,
    required this.data,
    this.height = 300,
  });

  @override
  State<TripleRsiChart> createState() => _TripleRsiChartState();
}

class _TripleRsiChartState extends State<TripleRsiChart> {
  // 0=All, 7=RSI7, 14=RSI14, 21=RSI21
  int _selectedPeriod = 14;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildPeriodSelector(),
        AppSpacing.vGapMd,
        _buildConsensusBar(),
        AppSpacing.vGapMd,
        SizedBox(
          height: widget.height,
          child: _buildChart(),
        ),
        AppSpacing.vGapMd,
        _buildCurrentValueBadges(),
      ],
    );
  }

  Widget _buildPeriodSelector() {
    final periods = [
      (7, 'RSI(7)'),
      (14, 'RSI(14)'),
      (21, 'RSI(21)'),
      (0, 'All'),
    ];

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: periods.map((p) {
          final isSelected = _selectedPeriod == p.$1;
          final color = _colorForPeriod(p.$1);
          return Padding(
            padding: const EdgeInsets.only(right: 8),
            child: GestureDetector(
              onTap: () => setState(() => _selectedPeriod = p.$1),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                padding:
                    const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
                decoration: BoxDecoration(
                  color: isSelected
                      ? color.withValues(alpha: 0.15)
                      : context.tc.surface,
                  borderRadius: AppSpacing.borderRadiusMd,
                  border: Border.all(
                    color: isSelected
                        ? color.withValues(alpha: 0.5)
                        : context.tc.surfaceBorder.withValues(alpha: 0.3),
                    width: 1,
                  ),
                ),
                child: Text(
                  p.$2,
                  style: AppTypography.labelMedium.copyWith(
                    color: isSelected ? color : context.tc.textSecondary,
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildConsensusBar() {
    final consensus = widget.data.consensus;
    final divergence = widget.data.divergence;

    Color consensusColor;
    IconData consensusIcon;
    String consensusLabel;

    switch (consensus.toLowerCase()) {
      case 'bullish':
        consensusColor = context.tc.profit;
        consensusIcon = Icons.trending_up_rounded;
        consensusLabel = 'Bullish';
        break;
      case 'bearish':
        consensusColor = context.tc.loss;
        consensusIcon = Icons.trending_down_rounded;
        consensusLabel = 'Bearish';
        break;
      default:
        consensusColor = context.tc.textTertiary;
        consensusIcon = Icons.trending_flat_rounded;
        consensusLabel = 'Neutral';
    }

    return Row(
      children: [
        // 컨센서스 뱃지
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            color: consensusColor.withValues(alpha: 0.12),
            borderRadius: AppSpacing.borderRadiusMd,
            border: Border.all(
              color: consensusColor.withValues(alpha: 0.3),
              width: 1,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(consensusIcon, size: 14, color: consensusColor),
              AppSpacing.hGapXs,
              Text(
                consensusLabel,
                style: AppTypography.labelMedium.copyWith(
                  color: consensusColor,
                ),
              ),
            ],
          ),
        ),
        // 다이버전스 경고
        if (divergence) ...[
          AppSpacing.hGapMd,
          Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: context.tc.warning.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusMd,
              border: Border.all(
                color: context.tc.warning.withValues(alpha: 0.3),
                width: 1,
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.warning_amber_rounded,
                    size: 14, color: context.tc.warning),
                AppSpacing.hGapXs,
                Text(
                  'Divergence',
                  style: AppTypography.labelMedium.copyWith(
                    color: context.tc.warning,
                  ),
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildChart() {
    if (_selectedPeriod == 0) {
      return _buildAllChart();
    }
    return _buildSingleChart(_selectedPeriod);
  }

  Widget _buildSingleChart(int period) {
    final indicator = widget.data.indicatorFor(period);
    final color = _colorForPeriod(period);
    final dates = widget.data.dates;

    if (indicator.rsiSeries.isEmpty) {
      return Center(
        child: Text(
          'No RSI data available',
          style: AppTypography.bodyMedium,
        ),
      );
    }

    final rsiSpots = _buildSpots(indicator.rsiSeries);
    final signalSpots = _buildSpots(indicator.signalSeries);

    return Padding(
      padding: const EdgeInsets.only(right: 16),
      child: LineChart(
        LineChartData(
          minY: 0,
          maxY: 100,
          clipData: const FlClipData.all(),
          gridData: FlGridData(
            show: true,
            drawVerticalLine: false,
            horizontalInterval: 10,
            getDrawingHorizontalLine: (value) {
              if (value == 70) {
                return FlLine(
                  color: context.tc.loss.withValues(alpha: 0.4),
                  strokeWidth: 1,
                  dashArray: [5, 4],
                );
              }
              if (value == 30) {
                return FlLine(
                  color: context.tc.profit.withValues(alpha: 0.4),
                  strokeWidth: 1,
                  dashArray: [5, 4],
                );
              }
              return FlLine(
                color: context.tc.chartGrid,
                strokeWidth: 0.5,
              );
            },
          ),
          borderData: FlBorderData(show: false),
          titlesData: FlTitlesData(
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                interval: 10,
                reservedSize: 36,
                getTitlesWidget: (value, meta) {
                  if (value % 10 == 0) {
                    return Text(
                      value.toInt().toString(),
                      style: AppTypography.bodySmall
                          .copyWith(fontSize: 10),
                      textAlign: TextAlign.right,
                    );
                  }
                  return const SizedBox.shrink();
                },
              ),
            ),
            rightTitles: const AxisTitles(
                sideTitles: SideTitles(showTitles: false)),
            topTitles: const AxisTitles(
                sideTitles: SideTitles(showTitles: false)),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 24,
                interval: (rsiSpots.length / 5).ceilToDouble(),
                getTitlesWidget: (value, meta) {
                  final idx = value.toInt();
                  if (idx >= 0 &&
                      idx < dates.length &&
                      idx % (rsiSpots.length ~/ 5).clamp(1, 999) == 0) {
                    final d = dates[idx];
                    final parts = d.split('-');
                    final label =
                        parts.length >= 3 ? '${parts[1]}/${parts[2]}' : d;
                    return Transform.rotate(
                      angle: -0.4,
                      child: Text(
                        label,
                        style: AppTypography.bodySmall
                            .copyWith(fontSize: 9),
                      ),
                    );
                  }
                  return const SizedBox.shrink();
                },
              ),
            ),
          ),
          // 과매수/과매도 영역 fill
          betweenBarsData: [
            BetweenBarsData(
              fromIndex: 0,
              toIndex: 0,
              color: Colors.transparent,
            ),
          ],
          lineBarsData: [
            // RSI 라인
            LineChartBarData(
              spots: rsiSpots,
              isCurved: true,
              curveSmoothness: 0.3,
              color: color,
              barWidth: 2,
              isStrokeCapRound: true,
              dotData: const FlDotData(show: false),
              belowBarData: BarAreaData(
                show: true,
                color: Colors.transparent,
                // 과매수 영역 상단 fill
                cutOffY: 70,
                applyCutOffY: true,
              ),
            ),
            // Signal 라인 (점선 효과로 얇게)
            if (signalSpots.isNotEmpty)
              LineChartBarData(
                spots: signalSpots,
                isCurved: true,
                curveSmoothness: 0.3,
                color: color.withValues(alpha: 0.45),
                barWidth: 1.5,
                isStrokeCapRound: true,
                dotData: const FlDotData(show: false),
                dashArray: [5, 4],
              ),
          ],
          lineTouchData: LineTouchData(
            enabled: true,
            touchCallback: (event, response) {
              if (response == null ||
                  response.lineBarSpots == null ||
                  (response.lineBarSpots?.isEmpty ?? true)) {
                return;
              }
            },
            touchTooltipData: LineTouchTooltipData(
              getTooltipColor: (_) =>
                  context.tc.surfaceElevated.withValues(alpha: 0.95),
              getTooltipItems: (touchedSpots) {
                return touchedSpots.map((spot) {
                  final idx = spot.spotIndex;
                  final dateLabel =
                      idx < dates.length ? dates[idx] : '';
                  final isRsiLine = spot.barIndex == 0;
                  return LineTooltipItem(
                    isRsiLine
                        ? '$dateLabel\nRSI: ${spot.y.toStringAsFixed(1)}'
                        : 'Sig: ${spot.y.toStringAsFixed(1)}',
                    AppTypography.bodySmall.copyWith(
                      color: isRsiLine ? color : color.withValues(alpha: 0.6),
                      height: 1.6,
                    ),
                  );
                }).toList();
              },
            ),
          ),
          // 과매수/과매도 수평선
          extraLinesData: ExtraLinesData(
            horizontalLines: [
              HorizontalLine(
                y: 70,
                color: context.tc.loss.withValues(alpha: 0.6),
                strokeWidth: 1,
                dashArray: [5, 4],
                label: HorizontalLineLabel(
                  show: true,
                  alignment: Alignment.topRight,
                  labelResolver: (_) => '70',
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.loss.withValues(alpha: 0.7),
                    fontSize: 10,
                  ),
                ),
              ),
              HorizontalLine(
                y: 30,
                color: context.tc.profit.withValues(alpha: 0.6),
                strokeWidth: 1,
                dashArray: [5, 4],
                label: HorizontalLineLabel(
                  show: true,
                  alignment: Alignment.topRight,
                  labelResolver: (_) => '30',
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.profit.withValues(alpha: 0.7),
                    fontSize: 10,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildAllChart() {
    final dates = widget.data.dates;
    final rsi7Spots = _buildSpots(widget.data.rsi7.rsiSeries);
    final rsi14Spots = _buildSpots(widget.data.rsi14.rsiSeries);
    final rsi21Spots = _buildSpots(widget.data.rsi21.rsiSeries);

    if (rsi14Spots.isEmpty) {
      return Center(
        child: Text('No RSI data available', style: AppTypography.bodyMedium),
      );
    }

    return Padding(
      padding: const EdgeInsets.only(right: 16),
      child: LineChart(
        LineChartData(
          minY: 0,
          maxY: 100,
          clipData: const FlClipData.all(),
          gridData: FlGridData(
            show: true,
            drawVerticalLine: false,
            horizontalInterval: 10,
            getDrawingHorizontalLine: (value) {
              if (value == 70) {
                return FlLine(
                  color: context.tc.loss.withValues(alpha: 0.4),
                  strokeWidth: 1,
                  dashArray: [5, 4],
                );
              }
              if (value == 30) {
                return FlLine(
                  color: context.tc.profit.withValues(alpha: 0.4),
                  strokeWidth: 1,
                  dashArray: [5, 4],
                );
              }
              return FlLine(
                color: context.tc.chartGrid,
                strokeWidth: 0.5,
              );
            },
          ),
          borderData: FlBorderData(show: false),
          titlesData: FlTitlesData(
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                interval: 10,
                reservedSize: 36,
                getTitlesWidget: (value, meta) {
                  if (value % 10 == 0) {
                    return Text(
                      value.toInt().toString(),
                      style: AppTypography.bodySmall
                          .copyWith(fontSize: 10),
                      textAlign: TextAlign.right,
                    );
                  }
                  return const SizedBox.shrink();
                },
              ),
            ),
            rightTitles: const AxisTitles(
                sideTitles: SideTitles(showTitles: false)),
            topTitles: const AxisTitles(
                sideTitles: SideTitles(showTitles: false)),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 24,
                interval:
                    (rsi14Spots.length / 5).ceilToDouble(),
                getTitlesWidget: (value, meta) {
                  final idx = value.toInt();
                  if (idx >= 0 &&
                      idx < dates.length &&
                      idx % (rsi14Spots.length ~/ 5).clamp(1, 999) ==
                          0) {
                    final d = dates[idx];
                    final parts = d.split('-');
                    final label = parts.length >= 3
                        ? '${parts[1]}/${parts[2]}'
                        : d;
                    return Transform.rotate(
                      angle: -0.4,
                      child: Text(
                        label,
                        style: AppTypography.bodySmall
                            .copyWith(fontSize: 9),
                      ),
                    );
                  }
                  return const SizedBox.shrink();
                },
              ),
            ),
          ),
          lineBarsData: [
            if (rsi7Spots.isNotEmpty)
              LineChartBarData(
                spots: rsi7Spots,
                isCurved: true,
                curveSmoothness: 0.3,
                color: ChartColors.rsi7,
                barWidth: 1.5,
                isStrokeCapRound: true,
                dotData: const FlDotData(show: false),
              ),
            if (rsi14Spots.isNotEmpty)
              LineChartBarData(
                spots: rsi14Spots,
                isCurved: true,
                curveSmoothness: 0.3,
                color: ChartColors.rsi14,
                barWidth: 2,
                isStrokeCapRound: true,
                dotData: const FlDotData(show: false),
              ),
            if (rsi21Spots.isNotEmpty)
              LineChartBarData(
                spots: rsi21Spots,
                isCurved: true,
                curveSmoothness: 0.3,
                color: ChartColors.rsi21,
                barWidth: 1.5,
                isStrokeCapRound: true,
                dotData: const FlDotData(show: false),
              ),
          ],
          lineTouchData: LineTouchData(
            enabled: true,
            touchTooltipData: LineTouchTooltipData(
              getTooltipColor: (_) =>
                  context.tc.surfaceElevated.withValues(alpha: 0.95),
              getTooltipItems: (touchedSpots) {
                final labels = ['RSI(7)', 'RSI(14)', 'RSI(21)'];
                final colors = [
                  ChartColors.rsi7,
                  ChartColors.rsi14,
                  ChartColors.rsi21
                ];
                return touchedSpots.map((spot) {
                  final bar = spot.barIndex.clamp(0, 2);
                  return LineTooltipItem(
                    '${labels[bar]}: ${spot.y.toStringAsFixed(1)}',
                    AppTypography.bodySmall
                        .copyWith(color: colors[bar], height: 1.6),
                  );
                }).toList();
              },
            ),
          ),
          extraLinesData: ExtraLinesData(
            horizontalLines: [
              HorizontalLine(
                y: 70,
                color: context.tc.loss.withValues(alpha: 0.6),
                strokeWidth: 1,
                dashArray: [5, 4],
              ),
              HorizontalLine(
                y: 30,
                color: context.tc.profit.withValues(alpha: 0.6),
                strokeWidth: 1,
                dashArray: [5, 4],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCurrentValueBadges() {
    final periods = _selectedPeriod == 0
        ? [7, 14, 21]
        : [_selectedPeriod];

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: periods.map((period) {
        final indicator = widget.data.indicatorFor(period);
        final color = _colorForPeriod(period);
        return _RsiValueBadge(
          period: period,
          rsi: indicator.rsi,
          signal: indicator.signal,
          color: color,
          status: indicator.status,
        );
      }).toList(),
    );
  }

  List<FlSpot> _buildSpots(List<double> series) {
    return series.asMap().entries
        .map((e) => FlSpot(e.key.toDouble(), e.value.clamp(0, 100)))
        .toList();
  }

  Color _colorForPeriod(int period) {
    switch (period) {
      case 7:
        return ChartColors.rsi7;
      case 21:
        return ChartColors.rsi21;
      default:
        return ChartColors.rsi14;
    }
  }
}

/// RSI 현재값 뱃지 위젯이다.
class _RsiValueBadge extends StatelessWidget {
  final int period;
  final double rsi;
  final double signal;
  final Color color;
  final String status; // "overbought", "oversold", "neutral"

  const _RsiValueBadge({
    required this.period,
    required this.rsi,
    required this.signal,
    required this.color,
    required this.status,
  });

  @override
  Widget build(BuildContext context) {
    Color statusColor;
    String statusLabel;
    switch (status) {
      case 'overbought':
        statusColor = context.tc.loss;
        statusLabel = 'OB';
        break;
      case 'oversold':
        statusColor = context.tc.profit;
        statusLabel = 'OS';
        break;
      default:
        statusColor = context.tc.textTertiary;
        statusLabel = '—';
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: color.withValues(alpha: 0.25),
          width: 1,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: color,
              shape: BoxShape.circle,
            ),
          ),
          AppSpacing.hGapXs,
          Text(
            'RSI($period)',
            style: AppTypography.labelMedium.copyWith(color: color),
          ),
          AppSpacing.hGapMd,
          Text(
            rsi.toStringAsFixed(1),
            style: AppTypography.numberSmall.copyWith(
              color: color,
              fontSize: 13,
            ),
          ),
          AppSpacing.hGapXs,
          Text(
            '/ ${signal.toStringAsFixed(1)}',
            style: AppTypography.bodySmall.copyWith(
              color: color.withValues(alpha: 0.55),
            ),
          ),
          AppSpacing.hGapMd,
          Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
            decoration: BoxDecoration(
              color: statusColor.withValues(alpha: 0.15),
              borderRadius: AppSpacing.borderRadiusSm,
            ),
            child: Text(
              statusLabel,
              style: AppTypography.bodySmall.copyWith(
                color: statusColor,
                fontSize: 10,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
