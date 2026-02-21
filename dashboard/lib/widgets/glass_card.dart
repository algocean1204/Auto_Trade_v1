import 'dart:ui';
import 'package:flutter/material.dart';
import '../theme/app_spacing.dart';
import '../theme/trading_colors.dart';

/// 글래스모피즘 효과가 적용된 카드 위젯이다.
/// 다크 모드: 반투명 배경, 블러 효과, 미세 테두리로 깊이감을 표현한다.
/// 라이트 모드: 흰색 배경, 미세 그림자, 테두리로 구분감을 표현한다.
class GlassCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final EdgeInsetsGeometry? margin;
  final double? blurAmount;
  final Color? backgroundColor;
  final BorderRadius? borderRadius;
  final VoidCallback? onTap;

  const GlassCard({
    super.key,
    required this.child,
    this.padding,
    this.margin,
    this.blurAmount,
    this.backgroundColor,
    this.borderRadius,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final radius = borderRadius ?? AppSpacing.borderRadiusLg;

    Widget card;

    if (isDark) {
      // 다크 모드: 글래스모피즘 효과 적용
      card = ClipRRect(
        borderRadius: radius,
        child: BackdropFilter(
          filter: ImageFilter.blur(
            sigmaX: blurAmount ?? 24,
            sigmaY: blurAmount ?? 24,
          ),
          child: Container(
            decoration: BoxDecoration(
              color: backgroundColor ?? tc.glassBackground,
              borderRadius: radius,
              border: Border.all(
                color: tc.glassBorder,
                width: 1,
              ),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.3),
                  blurRadius: 24,
                  offset: const Offset(0, 4),
                ),
              ],
            ),
            padding: padding ?? AppSpacing.paddingCard,
            child: child,
          ),
        ),
      );
    } else {
      // 라이트 모드: 깔끔한 카드 스타일 (그림자 + 테두리)
      card = Container(
        decoration: BoxDecoration(
          color: backgroundColor ?? tc.surface,
          borderRadius: radius,
          border: Border.all(
            color: tc.surfaceBorder.withValues(alpha: 0.6),
            width: 1,
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.06),
              blurRadius: 12,
              offset: const Offset(0, 2),
            ),
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.04),
              blurRadius: 4,
              offset: const Offset(0, 1),
            ),
          ],
        ),
        padding: padding ?? AppSpacing.paddingCard,
        child: child,
      );
    }

    if (onTap != null) {
      card = GestureDetector(
        onTap: onTap,
        child: card,
      );
    }

    if (margin != null) {
      card = Padding(padding: margin ?? EdgeInsets.zero, child: card);
    }

    return card;
  }
}

/// 승격(elevated) 카드 위젯이다. 글래스보다 불투명하고 강한 그림자를 가진다.
class ElevatedCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final EdgeInsetsGeometry? margin;
  final VoidCallback? onTap;

  const ElevatedCard({
    super.key,
    required this.child,
    this.padding,
    this.margin,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final isDark = Theme.of(context).brightness == Brightness.dark;

    Widget card = Container(
      decoration: BoxDecoration(
        color: tc.surfaceElevated,
        borderRadius: AppSpacing.borderRadiusLg,
        border: Border.all(
          color: tc.surfaceBorder.withValues(alpha: 0.6),
          width: 1,
        ),
        boxShadow: [
          BoxShadow(
            color: isDark
                ? Colors.black.withValues(alpha: 0.4)
                : Colors.black.withValues(alpha: 0.08),
            blurRadius: isDark ? 32 : 16,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      padding: padding ?? AppSpacing.paddingCard,
      child: child,
    );

    if (onTap != null) {
      card = InkWell(
        onTap: onTap,
        borderRadius: AppSpacing.borderRadiusLg,
        child: card,
      );
    }

    if (margin != null) {
      card = Padding(padding: margin ?? EdgeInsets.zero, child: card);
    }

    return card;
  }
}
