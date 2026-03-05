import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:intl/intl.dart';
import '../models/chart_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';

class CumulativeChart extends StatelessWidget {
  final List<CumulativeReturn> data;

  const CumulativeChart({super.key, required this.data});

  @override
  Widget build(BuildContext context) {
    if (data.isEmpty) {
      return Center(
        child: Text('No data', style: AppTypography.bodyMedium),
      );
    }

    return Padding(
      padding: const EdgeInsets.all(8),
      child: LineChart(
        LineChartData(
          gridData: FlGridData(
            show: true,
            drawVerticalLine: false,
            horizontalInterval: 1,
            getDrawingHorizontalLine: (value) {
              return FlLine(
                color: context.tc.chartGrid,
                strokeWidth: 1,
              );
            },
          ),
          titlesData: FlTitlesData(
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 44,
                getTitlesWidget: (value, meta) {
                  return Text(
                    '${value.toStringAsFixed(1)}%',
                    style: AppTypography.bodySmall.copyWith(
                      color: context.tc.chartAxis,
                      fontSize: 10,
                    ),
                  );
                },
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 30,
                interval: (data.length / 5).ceil().toDouble(),
                getTitlesWidget: (value, meta) {
                  if (value.toInt() >= 0 && value.toInt() < data.length) {
                    final date = data[value.toInt()].date;
                    return Text(
                      DateFormat('MM/dd').format(date),
                      style: AppTypography.bodySmall.copyWith(
                        color: context.tc.chartAxis,
                        fontSize: 10,
                      ),
                    );
                  }
                  return const SizedBox();
                },
              ),
            ),
            topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
            rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          ),
          borderData: FlBorderData(show: false),
          lineBarsData: [
            LineChartBarData(
              spots: data.asMap().entries.map((entry) {
                return FlSpot(entry.key.toDouble(), entry.value.cumulativePct);
              }).toList(),
              isCurved: true,
              color: context.tc.profit,
              barWidth: 2.5,
              dotData: const FlDotData(show: false),
              belowBarData: BarAreaData(
                show: true,
                gradient: LinearGradient(
                  colors: [
                    context.tc.profit.withValues(alpha: 0.25),
                    context.tc.profit.withValues(alpha: 0.0),
                  ],
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                ),
              ),
            ),
          ],
          lineTouchData: LineTouchData(
            touchTooltipData: LineTouchTooltipData(
              getTooltipColor: (touchedSpot) => context.tc.surfaceElevated,
              tooltipRoundedRadius: 12,
              tooltipBorder: BorderSide(
                color: context.tc.surfaceBorder,
                width: 1,
              ),
              getTooltipItems: (touchedSpots) {
                return touchedSpots.map((spot) {
                  final index = spot.x.toInt();
                  if (index >= 0 && index < data.length) {
                    final point = data[index];
                    return LineTooltipItem(
                      '${DateFormat('MM/dd').format(point.date)}\n'
                      '${point.cumulativePct >= 0 ? '+' : ''}${point.cumulativePct.toStringAsFixed(2)}%\n'
                      '${NumberFormat.currency(symbol: '\$', decimalDigits: 0).format(point.cumulativePnl)}',
                      AppTypography.numberSmall.copyWith(
                        color: context.tc.textPrimary,
                        fontSize: 12,
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
