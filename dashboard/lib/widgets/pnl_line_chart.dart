import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:intl/intl.dart';
import '../models/chart_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';

class PnlLineChart extends StatelessWidget {
  final List<DailyReturn> data;

  const PnlLineChart({super.key, required this.data});

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
                return FlSpot(entry.key.toDouble(), entry.value.pnlPct);
              }).toList(),
              isCurved: true,
              color: context.tc.chart1,
              barWidth: 2.5,
              dotData: FlDotData(
                show: true,
                getDotPainter: (spot, percent, barData, index) {
                  final pnl = data[index].pnlPct;
                  return FlDotCirclePainter(
                    radius: 3.5,
                    color: context.tc.pnlColor(pnl),
                    strokeWidth: 1.5,
                    strokeColor: context.tc.surface,
                  );
                },
              ),
              belowBarData: BarAreaData(
                show: true,
                gradient: LinearGradient(
                  colors: [
                    context.tc.chart1.withValues(alpha: 0.2),
                    context.tc.chart1.withValues(alpha: 0.0),
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
                      '${point.pnlPct >= 0 ? '+' : ''}${point.pnlPct.toStringAsFixed(2)}%\n'
                      '${NumberFormat.currency(symbol: '\$', decimalDigits: 0).format(point.pnlAmount)}',
                      AppTypography.numberSmall.copyWith(
                        color: context.tc.pnlColor(point.pnlPct),
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
