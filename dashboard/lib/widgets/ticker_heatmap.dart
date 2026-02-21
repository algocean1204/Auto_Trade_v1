import 'package:flutter/material.dart';
import '../models/chart_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

class TickerHeatmap extends StatelessWidget {
  final List<HeatmapPoint> data;

  const TickerHeatmap({super.key, required this.data});

  Color _getColor(double value, BuildContext context) {
    if (value > 0) {
      final opacity = (value / 10).clamp(0.2, 1.0);
      return context.tc.profit.withValues(alpha: opacity);
    } else if (value < 0) {
      final opacity = (value.abs() / 10).clamp(0.2, 1.0);
      return context.tc.loss.withValues(alpha: opacity);
    }
    return context.tc.surfaceBorder.withValues(alpha: 0.3);
  }

  @override
  Widget build(BuildContext context) {
    if (data.isEmpty) {
      return Center(
        child: Text('No data', style: AppTypography.bodyMedium),
      );
    }

    final tickers = data.map((p) => p.x).toSet().toList();
    final dates = data.map((p) => p.y).toSet().toList();

    return ClipRect(
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        physics: const ClampingScrollPhysics(),
        child: SingleChildScrollView(
          physics: const ClampingScrollPhysics(),
          child: Padding(
            padding: AppSpacing.paddingCard,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Header row with date labels
                Row(
                  children: [
                    const SizedBox(width: 64),
                    ...dates.map((date) => Container(
                          width: 64,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 4,
                            vertical: 6,
                          ),
                          child: Text(
                            date,
                            textAlign: TextAlign.center,
                            style: AppTypography.bodySmall.copyWith(
                              fontSize: 10,
                              color: context.tc.textTertiary,
                            ),
                          ),
                        )),
                  ],
                ),
                AppSpacing.vGapXs,
                // Data rows
                ...tickers.map((ticker) {
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 3),
                    child: Row(
                      children: [
                        SizedBox(
                          width: 64,
                          child: Text(
                            ticker,
                            style:
                                AppTypography.labelLarge.copyWith(fontSize: 12),
                          ),
                        ),
                        ...dates.map((date) {
                          final point = data.firstWhere(
                            (p) => p.x == ticker && p.y == date,
                            orElse: () =>
                                HeatmapPoint(x: ticker, y: date, value: 0),
                          );
                          return Container(
                            width: 64,
                            height: 40,
                            margin: const EdgeInsets.all(1.5),
                            decoration: BoxDecoration(
                              color: _getColor(point.value, context),
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Center(
                              child: Text(
                                '${point.value >= 0 ? '+' : ''}${point.value.toStringAsFixed(1)}%',
                                style: AppTypography.numberSmall.copyWith(
                                  fontSize: 10,
                                  color: context.tc.textPrimary,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          );
                        }),
                      ],
                    ),
                  );
                }),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
