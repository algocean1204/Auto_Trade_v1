import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../models/trade_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

class PositionCard extends StatelessWidget {
  final Position position;

  const PositionCard({super.key, required this.position});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final pnlColor = tc.pnlColor(position.unrealizedPnl);
    final pnlBg = tc.pnlBg(position.unrealizedPnl);

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: tc.surface,
        borderRadius: AppSpacing.borderRadiusLg,
        border: Border.all(
          color: tc.surfaceBorder.withValues(alpha: 0.3),
          width: 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header: Ticker + PnL badge
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(position.ticker, style: AppTypography.headlineMedium),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: pnlBg,
                  borderRadius: AppSpacing.borderRadiusSm,
                  border: Border.all(color: pnlColor.withValues(alpha: 0.4)),
                ),
                child: Text(
                  '${position.unrealizedPnlPct >= 0 ? '+' : ''}${position.unrealizedPnlPct.toStringAsFixed(2)}%',
                  style: AppTypography.numberSmall.copyWith(
                    color: pnlColor,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          AppSpacing.vGapMd,
          // Qty + PnL amount
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Qty: ${position.quantity}',
                style: AppTypography.bodyMedium,
              ),
              Text(
                NumberFormat.currency(symbol: '\$', decimalDigits: 0)
                    .format(position.unrealizedPnl),
                style: AppTypography.numberMedium.copyWith(
                  color: pnlColor,
                  fontSize: 16,
                ),
              ),
            ],
          ),
          AppSpacing.vGapSm,
          // Avg price + current price
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Avg: ${NumberFormat.currency(symbol: '\$', decimalDigits: 2).format(position.avgPrice)}',
                style: AppTypography.bodySmall,
              ),
              Text(
                'Now: ${NumberFormat.currency(symbol: '\$', decimalDigits: 2).format(position.currentPrice)}',
                style: AppTypography.bodySmall,
              ),
            ],
          ),
          AppSpacing.vGapMd,
          // Progress bar
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: position.unrealizedPnlPct.abs() / 100,
              backgroundColor: tc.surfaceBorder.withValues(alpha: 0.3),
              valueColor: AlwaysStoppedAnimation<Color>(pnlColor),
              minHeight: 4,
            ),
          ),
          AppSpacing.vGapSm,
          // Hold days + strategy
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Hold: ${position.holdDays}d',
                style: AppTypography.bodySmall,
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: tc.primary.withValues(alpha: 0.12),
                  borderRadius: AppSpacing.borderRadiusSm,
                ),
                child: Text(
                  position.strategy,
                  style: AppTypography.bodySmall.copyWith(
                    color: tc.primary,
                    fontSize: 11,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
