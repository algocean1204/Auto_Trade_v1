import 'package:flutter/material.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

/// 섹션 헤더 위젯 - 제목과 선택적 액션 버튼을 표시한다.
class SectionHeader extends StatelessWidget {
  final String title;
  final Widget? action;
  final EdgeInsetsGeometry? padding;

  const SectionHeader({
    super.key,
    required this.title,
    this.action,
    this.padding,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: padding ?? const EdgeInsets.only(bottom: 12),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Text(title, style: AppTypography.headlineMedium),
          if (action != null) action ?? const SizedBox.shrink(),
        ],
      ),
    );
  }
}

/// 작은 섹션 라벨이다.
class SectionLabel extends StatelessWidget {
  final String text;
  final Color? color;

  const SectionLabel({
    super.key,
    required this.text,
    this.color,
  });

  @override
  Widget build(BuildContext context) {
    final labelColor = color ?? context.tc.primary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: labelColor.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusSm,
      ),
      child: Text(
        text.toUpperCase(),
        style: AppTypography.labelMedium.copyWith(
          color: labelColor,
          fontSize: 11,
        ),
      ),
    );
  }
}
