import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../models/macro_models.dart';
import '../theme/trading_colors.dart';
import '../theme/chart_colors.dart';
import '../theme/app_typography.dart';
/// CPI (소비자물가지수) 추세 라인 차트 위젯이다.
/// Fed 목표치 2.0%에 점선을 표시한다.
class CpiChart extends StatelessWidget {
  final FredHistoryData? cpiHistory;

  const CpiChart({super.key, this.cpiHistory});

  @override
  Widget build(BuildContext context) {
    final history = cpiHistory;
    if (history == null || history.data.isEmpty) {
      return SizedBox(
        height: 160,
        child: Center(
          child: Text('CPI 데이터 없음', style: AppTypography.bodySmall),
        ),
      );
    }

    final points = history.data;
    final spots = <FlSpot>[];
    for (int i = 0; i < points.length; i++) {
      spots.add(FlSpot(i.toDouble(), points[i].value));
    }

    final rawValues = spots.map((s) => s.y).toList();
    final minY =
        (rawValues.reduce((a, b) => a < b ? a : b) - 0.3).clamp(0.0, double.infinity);
    final maxY = rawValues.reduce((a, b) => a > b ? a : b) + 0.3;
    const fedTarget = 2.0;

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
                      "${date.month.toString().padLeft(2, '0')}/${date.year.toString().substring(2)}",
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
                y: fedTarget,
                color: ChartColors.cpiFedTarget.withValues(alpha: 0.7),
                strokeWidth: 1,
                dashArray: [6, 4],
                label: HorizontalLineLabel(
                  show: true,
                  alignment: Alignment.topRight,
                  labelResolver: (_) => ' Fed 목표 2.0%',
                  style: AppTypography.bodySmall.copyWith(
                    color: ChartColors.cpiFedTarget,
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
              color: ChartColors.cpiLine,
              barWidth: 2.5,
              isStrokeCapRound: true,
              dotData: const FlDotData(show: false),
              belowBarData: BarAreaData(
                show: true,
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [
                    ChartColors.cpiLine.withValues(alpha: 0.15),
                    ChartColors.cpiLine.withValues(alpha: 0.02),
                  ],
                ),
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
}
