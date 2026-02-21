import 'package:flutter/material.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

class WeightSlider extends StatelessWidget {
  final String label;
  final double value;
  final ValueChanged<double> onChanged;
  final bool enabled;

  const WeightSlider({
    super.key,
    required this.label,
    required this.value,
    required this.onChanged,
    this.enabled = true,
  });

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final activeColor = enabled ? tc.primary : tc.textDisabled;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: AppTypography.bodyLarge),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              decoration: BoxDecoration(
                color: activeColor.withValues(alpha: 0.12),
                borderRadius: AppSpacing.borderRadiusSm,
              ),
              child: Text(
                '${value.toStringAsFixed(0)}%',
                style: AppTypography.numberSmall.copyWith(
                  color: activeColor,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
        ),
        AppSpacing.vGapSm,
        SliderTheme(
          data: SliderThemeData(
            activeTrackColor: activeColor,
            inactiveTrackColor: tc.surfaceBorder,
            thumbColor: activeColor,
            overlayColor: activeColor.withValues(alpha: 0.12),
            trackHeight: 4,
            thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 8),
            overlayShape: const RoundSliderOverlayShape(overlayRadius: 16),
          ),
          child: Slider(
            value: value,
            min: 0,
            max: 100,
            divisions: 20,
            onChanged: enabled ? onChanged : null,
          ),
        ),
      ],
    );
  }
}
