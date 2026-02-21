import 'package:flutter/material.dart';
import '../models/macro_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

/// 다가오는 경제 이벤트 캘린더를 리스트 형식으로 표시하는 위젯이다.
class EconomicCalendarCard extends StatelessWidget {
  final List<EconomicEvent> events;

  const EconomicCalendarCard({super.key, required this.events});

  Color _impactColor(String impact, BuildContext context) {
    switch (impact.toLowerCase()) {
      case 'high':
        return context.tc.loss;
      case 'medium':
        return context.tc.warning;
      default:
        return context.tc.textTertiary;
    }
  }

  Color _impactBg(String impact, BuildContext context) {
    switch (impact.toLowerCase()) {
      case 'high':
        return context.tc.loss.withValues(alpha: 0.08);
      case 'medium':
        return context.tc.warning.withValues(alpha: 0.06);
      default:
        return Colors.transparent;
    }
  }

  /// 이벤트명에서 태그를 추출한다 (CPI, FOMC, NFP 등).
  String? _extractTag(String event) {
    const tags = ['CPI', 'FOMC', 'NFP', 'GDP', 'PPI', 'PCE', 'PMI', 'ISM', 'JOLTS'];
    for (final tag in tags) {
      if (event.toUpperCase().contains(tag)) return tag;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final displayEvents = events.take(10).toList();

    if (displayEvents.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Text('예정된 경제 이벤트 없음', style: AppTypography.bodySmall),
        ),
      );
    }

    return Column(
      children: displayEvents.map((event) => _buildEventRow(event, context)).toList(),
    );
  }

  Widget _buildEventRow(EconomicEvent event, BuildContext context) {
    final impactColor = _impactColor(event.impact, context);
    final impactBg = _impactBg(event.impact, context);
    final tag = _extractTag(event.event);
    final isHigh = event.impact.toLowerCase() == 'high';

    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: impactBg,
        borderRadius: AppSpacing.borderRadiusSm,
        border: isHigh
            ? Border.all(color: context.tc.loss.withValues(alpha: 0.15), width: 1)
            : null,
      ),
      child: Row(
        children: [
          // 충격도 표시 점
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: impactColor,
              shape: BoxShape.circle,
            ),
          ),
          AppSpacing.hGapSm,
          // 날짜와 시간
          SizedBox(
            width: 58,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  event.date,
                  style: AppTypography.bodySmall.copyWith(
                    fontSize: 10,
                    color: context.tc.textTertiary,
                  ),
                ),
                if (event.time != null)
                  Text(
                    event.time ?? '',
                    style: AppTypography.bodySmall.copyWith(
                      fontSize: 9,
                      color: context.tc.textDisabled,
                    ),
                  ),
              ],
            ),
          ),
          AppSpacing.hGapSm,
          // 이벤트명과 태그
          Expanded(
            child: Row(
              children: [
                if (tag != null) ...[
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 5, vertical: 1),
                    decoration: BoxDecoration(
                      color: context.tc.primary.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      tag,
                      style: AppTypography.labelMedium.copyWith(
                        color: context.tc.primaryLight,
                        fontSize: 9,
                      ),
                    ),
                  ),
                  AppSpacing.hGapXs,
                ],
                Expanded(
                  child: Text(
                    event.event,
                    style: AppTypography.bodySmall.copyWith(
                      fontSize: 11,
                      color: isHigh
                          ? context.tc.textPrimary
                          : context.tc.textSecondary,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
          ),
          AppSpacing.hGapSm,
          // 전기/예측/실제 값
          SizedBox(
            width: 100,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (event.previous != null)
                  _buildValueChip('이전', event.previous ?? '', context.tc.textTertiary, context),
                if (event.forecast != null) ...[
                  AppSpacing.hGapXs,
                  _buildValueChip('예측', event.forecast ?? '', context.tc.warning, context),
                ],
                if (event.actual != null) ...[
                  AppSpacing.hGapXs,
                  _buildValueChip('실제', event.actual ?? '', context.tc.profit, context),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildValueChip(String label, String value, Color color, BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text(
          label,
          style: AppTypography.bodySmall.copyWith(
            fontSize: 8,
            color: context.tc.textDisabled,
          ),
        ),
        Text(
          value,
          style: AppTypography.numberSmall.copyWith(
            fontSize: 10,
            color: color,
          ),
        ),
      ],
    );
  }
}
