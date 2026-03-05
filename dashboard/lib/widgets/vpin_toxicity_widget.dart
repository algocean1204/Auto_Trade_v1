import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../theme/trading_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// VPIN 독성 레벨을 원형 아크 게이지로 표시하는 위젯이다.
/// 레벨에 따라 색상이 변하며, Critical 레벨에서는 맥박 애니메이션이 추가된다.
/// 거래 잠금 상태에서는 자물쇠 아이콘과 카운트다운 타이머를 표시한다.
class VpinToxicityWidget extends StatefulWidget {
  /// VPIN 값이다 (0.0 ~ 1.0).
  final double vpinValue;

  /// VPIN 레벨이다: "safe", "warning", "danger", "critical"
  final String vpinLevel;

  /// 복합 독성 지수이다 (0.0 ~ 1.0).
  final double toxicityComposite;

  /// 독성 레벨이다: "safe", "warning", "danger", "blocked"
  final String toxicityLevel;

  /// 거래 잠금 여부이다.
  final bool isLocked;

  /// 잠금 해제까지 남은 시간(초)이다.
  final double? lockRemaining;

  const VpinToxicityWidget({
    super.key,
    required this.vpinValue,
    required this.vpinLevel,
    required this.toxicityComposite,
    required this.toxicityLevel,
    this.isLocked = false,
    this.lockRemaining,
  });

  @override
  State<VpinToxicityWidget> createState() => _VpinToxicityWidgetState();
}

class _VpinToxicityWidgetState extends State<VpinToxicityWidget>
    with SingleTickerProviderStateMixin {
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );
    _pulseAnimation = Tween<double>(begin: 0.85, end: 1.0).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );

    _updatePulse();
  }

  @override
  void didUpdateWidget(VpinToxicityWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.vpinLevel != widget.vpinLevel) {
      _updatePulse();
    }
  }

  void _updatePulse() {
    if (widget.vpinLevel == 'critical' || widget.isLocked) {
      if (!_pulseController.isAnimating) {
        _pulseController.repeat(reverse: true);
      }
    } else {
      _pulseController.stop();
      _pulseController.reset();
    }
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  Color _levelColor(BuildContext context) {
    final tc = context.tc;
    switch (widget.vpinLevel) {
      case 'warning':
        return tc.warning;
      case 'danger':
        return const Color(0xFFFF6B35); // 주황색
      case 'critical':
        return tc.loss;
      default:
        return tc.profit; // safe
    }
  }

  String _levelLabel() {
    switch (widget.vpinLevel) {
      case 'warning':
        return '경고';
      case 'danger':
        return '위험';
      case 'critical':
        return '위험!';
      default:
        return '안전';
    }
  }

  String _toxicityLevelLabel() {
    switch (widget.toxicityLevel) {
      case 'warning':
        return '경고';
      case 'danger':
        return '위험';
      case 'blocked':
        return '차단';
      default:
        return '안전';
    }
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final gaugeColor = _levelColor(context);
    final isCritical = widget.vpinLevel == 'critical';

    return Column(
      children: [
        // 헤더
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              'VPIN',
              style: AppTypography.labelLarge.copyWith(
                color: tc.textSecondary,
                fontSize: 13,
              ),
            ),
            AppSpacing.hGapXs,
            Text(
              '독성',
              style: AppTypography.bodySmall.copyWith(
                color: tc.textTertiary,
                fontSize: 11,
              ),
            ),
          ],
        ),
        AppSpacing.vGapSm,
        // 원형 게이지
        AnimatedBuilder(
          animation: _pulseAnimation,
          builder: (context, child) {
            final scale = isCritical || widget.isLocked ? _pulseAnimation.value : 1.0;
            return Transform.scale(
              scale: scale,
              child: SizedBox(
                width: 110,
                height: 110,
                child: CustomPaint(
                  painter: _ArcGaugePainter(
                    value: widget.vpinValue.clamp(0.0, 1.0),
                    color: gaugeColor,
                    backgroundColor:
                        tc.surfaceBorder.withValues(alpha: 0.5),
                  ),
                  child: Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (widget.isLocked)
                          Icon(Icons.lock_rounded, color: tc.loss, size: 20)
                        else
                          Text(
                            (widget.vpinValue * 100).toStringAsFixed(0),
                            style: AppTypography.numberSmall.copyWith(
                              color: gaugeColor,
                              fontSize: 20,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        Text(
                          widget.isLocked ? '잠금' : _levelLabel(),
                          style: AppTypography.labelMedium.copyWith(
                            color: gaugeColor,
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          },
        ),
        AppSpacing.vGapSm,
        // 잠금 상태 표시 또는 독성 레벨 뱃지
        if (widget.isLocked && widget.lockRemaining != null) ...[
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: tc.loss.withValues(alpha: 0.15),
              borderRadius: AppSpacing.borderRadiusMd,
              border: Border.all(
                color: tc.loss.withValues(alpha: 0.4),
                width: 1,
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.lock_clock_rounded, size: 14, color: tc.loss),
                AppSpacing.hGapXs,
                Text(
                  '${widget.lockRemaining!.toInt()}초 후 해제',
                  style: AppTypography.labelMedium.copyWith(
                    color: tc.loss,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
        ] else ...[
          // 독성 레벨 배지
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: gaugeColor.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusFull,
              border: Border.all(
                color: gaugeColor.withValues(alpha: 0.35),
                width: 1,
              ),
            ),
            child: Text(
              '독성: ${_toxicityLevelLabel()} (${(widget.toxicityComposite * 100).toStringAsFixed(0)}%)',
              style: AppTypography.labelMedium.copyWith(
                color: gaugeColor,
                fontSize: 11,
              ),
            ),
          ),
        ],
      ],
    );
  }
}

/// 원형 아크 게이지를 그리는 CustomPainter이다.
class _ArcGaugePainter extends CustomPainter {
  final double value; // 0.0 ~ 1.0
  final Color color;
  final Color backgroundColor;

  const _ArcGaugePainter({
    required this.value,
    required this.color,
    required this.backgroundColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = (size.width / 2) - 8;
    const strokeWidth = 10.0;

    // 시작각: 135도 (좌측 하단), 끝각: 45도 (우측 하단)
    // 총 호의 각도: 270도
    const startAngle = 135.0 * math.pi / 180.0;
    const sweepAngle = 270.0 * math.pi / 180.0;

    final bgPaint = Paint()
      ..color = backgroundColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;

    final fgPaint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;

    // 배경 아크
    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      startAngle,
      sweepAngle,
      false,
      bgPaint,
    );

    // 채워진 아크 (값에 비례)
    if (value > 0) {
      canvas.drawArc(
        Rect.fromCircle(center: center, radius: radius),
        startAngle,
        sweepAngle * value,
        false,
        fgPaint,
      );
    }

    // Critical 레벨에서 글로우 효과를 추가한다.
    if (value > 0.7) {
      final glowPaint = Paint()
        ..color = color.withValues(alpha: 0.25)
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth + 8
        ..strokeCap = StrokeCap.round
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 6);

      canvas.drawArc(
        Rect.fromCircle(center: center, radius: radius),
        startAngle,
        sweepAngle * value,
        false,
        glowPaint,
      );
    }
  }

  @override
  bool shouldRepaint(_ArcGaugePainter oldDelegate) {
    return oldDelegate.value != value ||
        oldDelegate.color != color ||
        oldDelegate.backgroundColor != backgroundColor;
  }
}
