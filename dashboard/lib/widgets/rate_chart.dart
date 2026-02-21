import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../models/macro_models.dart';
import '../theme/trading_colors.dart';
import '../theme/chart_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

/// 연방기금금리 히스토리 라인 차트와 금리 전망 바를 표시한다.
class RateChart extends StatelessWidget {
  final FredHistoryData? rateHistory;
  final RateOutlook? rateOutlook;

  const RateChart({
    super.key,
    this.rateHistory,
    this.rateOutlook,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (rateHistory != null && (rateHistory?.data.isNotEmpty ?? false))
          _buildLineChart(rateHistory!, context)
        else
          SizedBox(
            height: 160,
            child: Center(
              child: Text('금리 데이터 없음', style: AppTypography.bodySmall),
            ),
          ),
        if (rateOutlook != null) ...[
          AppSpacing.vGapMd,
          _buildRateOutlookBar(rateOutlook!, context),
        ],
      ],
    );
  }

  Widget _buildLineChart(FredHistoryData history, BuildContext context) {
    final points = history.data;
    if (points.isEmpty) return const SizedBox.shrink();

    // Step-line 스타일 구현: 각 포인트를 X축 기준 인덱스로 매핑한다.
    final spots = <FlSpot>[];
    for (int i = 0; i < points.length; i++) {
      spots.add(FlSpot(i.toDouble(), points[i].value));
    }

    final minY = (spots.map((s) => s.y).reduce((a, b) => a < b ? a : b) - 0.25)
        .clamp(0.0, double.infinity);
    final maxY = spots.map((s) => s.y).reduce((a, b) => a > b ? a : b) + 0.25;
    final currentRate = points.last.value;

    return SizedBox(
      height: 160,
      child: LineChart(
        LineChartData(
          gridData: FlGridData(
            show: true,
            drawVerticalLine: false,
            getDrawingHorizontalLine: (value) => FlLine(
              color: context.tc.chartGrid,
              strokeWidth: 1,
            ),
          ),
          titlesData: FlTitlesData(
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 40,
                getTitlesWidget: (value, meta) {
                  if (value == meta.min || value == meta.max) {
                    return const SizedBox.shrink();
                  }
                  return Padding(
                    padding: const EdgeInsets.only(right: 4),
                    child: Text(
                      '${value.toStringAsFixed(1)}%',
                      style: AppTypography.bodySmall.copyWith(fontSize: 9),
                      textAlign: TextAlign.right,
                    ),
                  );
                },
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 20,
                interval: (points.length / 4).ceilToDouble(),
                getTitlesWidget: (value, meta) {
                  final idx = value.toInt();
                  if (idx < 0 || idx >= points.length) {
                    return const SizedBox.shrink();
                  }
                  final date = points[idx].date;
                  return Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(
                      "${date.month}/${date.year.toString().substring(2)}",
                      style: AppTypography.bodySmall.copyWith(fontSize: 9),
                    ),
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
          ),
          borderData: FlBorderData(show: false),
          minY: minY,
          maxY: maxY,
          extraLinesData: ExtraLinesData(
            horizontalLines: [
              HorizontalLine(
                y: currentRate,
                color: ChartColors.rateCurrentLine.withValues(alpha: 0.7),
                strokeWidth: 1,
                dashArray: [6, 4],
                label: HorizontalLineLabel(
                  show: true,
                  alignment: Alignment.topRight,
                  labelResolver: (line) =>
                      ' ${currentRate.toStringAsFixed(2)}%',
                  style: AppTypography.bodySmall.copyWith(
                    color: ChartColors.rateCurrentLine,
                    fontSize: 9,
                  ),
                ),
              ),
            ],
          ),
          lineBarsData: [
            LineChartBarData(
              spots: spots,
              isCurved: false, // Step-line 스타일: 곡선 없이 직선으로 연결한다.
              color: ChartColors.rateLine,
              barWidth: 2.5,
              isStrokeCapRound: true,
              dotData: const FlDotData(show: false),
              belowBarData: BarAreaData(
                show: true,
                color: ChartColors.rateLine.withValues(alpha: 0.08),
              ),
            ),
          ],
          lineTouchData: LineTouchData(
            touchTooltipData: LineTouchTooltipData(
              getTooltipItems: (touchedSpots) {
                return touchedSpots.map((spot) {
                  final idx = spot.spotIndex;
                  if (idx >= 0 && idx < points.length) {
                    final d = points[idx].date;
                    return LineTooltipItem(
                      '${d.year}-${d.month.toString().padLeft(2, '0')}\n${spot.y.toStringAsFixed(2)}%',
                      AppTypography.bodySmall.copyWith(
                        color: context.tc.textPrimary,
                        fontSize: 10,
                      ),
                    );
                  }
                  return null;
                }).toList();
              },
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildRateOutlookBar(RateOutlook outlook, BuildContext context) {
    final probs = outlook.probabilities;
    // cut 확률 합산 (cut_25bp, cut_50bp 등)
    final cutPct =
        probs.entries.where((e) => e.key.contains('cut')).fold(0, (a, b) => a + b.value);
    final holdPct =
        probs.entries.where((e) => e.key.contains('hold')).fold(0, (a, b) => a + b.value);
    final hikePct =
        probs.entries.where((e) => e.key.contains('hike')).fold(0, (a, b) => a + b.value);
    final total = (cutPct + holdPct + hikePct).clamp(1, 999);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '금리 전망',
          style: AppTypography.bodySmall.copyWith(
            color: context.tc.textTertiary,
            fontWeight: FontWeight.w600,
          ),
        ),
        AppSpacing.vGapXs,
        ClipRRect(
          borderRadius: AppSpacing.borderRadiusFull,
          child: Row(
            children: [
              if (cutPct > 0)
                _buildOutlookSegment(cutPct / total, context.tc.profit, '인하 ${cutPct}%'),
              if (holdPct > 0)
                _buildOutlookSegment(holdPct / total, context.tc.surfaceBorder, '동결 ${holdPct}%'),
              if (hikePct > 0)
                _buildOutlookSegment(hikePct / total, context.tc.loss, '인상 ${hikePct}%'),
              // 나머지를 채운다
              if (cutPct + holdPct + hikePct < 100)
                Expanded(
                  child: Container(height: 16, color: context.tc.surfaceBorder),
                ),
            ],
          ),
        ),
        AppSpacing.vGapXs,
        Row(
          children: [
            _buildLegend(context.tc.profit, '인하 ${cutPct}%'),
            AppSpacing.hGapMd,
            _buildLegend(context.tc.textTertiary, '동결 ${holdPct}%'),
            AppSpacing.hGapMd,
            _buildLegend(context.tc.loss, '인상 ${hikePct}%'),
            if (outlook.nextMeeting != null) ...[
              const Spacer(),
              Text(
                '다음 FOMC: ${outlook.nextMeeting}',
                style: AppTypography.bodySmall.copyWith(fontSize: 10),
              ),
            ],
          ],
        ),
      ],
    );
  }

  Widget _buildOutlookSegment(double flex, Color color, String tooltip) {
    return Expanded(
      flex: (flex * 1000).round(),
      child: Tooltip(
        message: tooltip,
        child: Container(height: 16, color: color),
      ),
    );
  }

  Widget _buildLegend(Color color, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        AppSpacing.hGapXs,
        Text(label, style: AppTypography.bodySmall.copyWith(fontSize: 10)),
      ],
    );
  }
}
