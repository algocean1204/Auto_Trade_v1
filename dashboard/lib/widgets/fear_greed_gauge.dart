import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../models/macro_models.dart';
import '../theme/trading_colors.dart';
import '../theme/chart_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../animations/animation_utils.dart';

/// Fear & Greed 지수를 반원형 게이지로 표시하는 위젯이다.
/// 0 (극도의 공포) ~ 100 (극도의 탐욕) 범위를 색상 그라디언트로 시각화한다.
class FearGreedGauge extends StatelessWidget {
  final FearGreedIndex fearGreed;
  final VixStatus vix;

  const FearGreedGauge({
    super.key,
    required this.fearGreed,
    required this.vix,
  });

  static Color _colorForScore(double score) {
    return ChartColors.colorForFearGreedScore(score);
  }

  String _levelLabel(String locale, String level) {
    const labels = {
      'extreme_fear': '극도의 공포',
      'fear': '공포',
      'neutral': '중립',
      'greed': '탐욕',
      'extreme_greed': '극도의 탐욕',
    };
    return labels[level] ?? level;
  }

  /// 점수에 따른 해석 텍스트를 반환한다.
  String _scoreInterpretation(double score) {
    if (score <= 20) return '시장이 극도로 두려워하고 있습니다. 역발상 매수 기회일 수 있습니다.';
    if (score <= 40) return '투자자들이 불안해하고 있습니다. 저가 매수를 고려해볼 시점입니다.';
    if (score <= 60) return '시장 심리가 균형 잡혀 있습니다. 현재 포지션 유지를 권장합니다.';
    if (score <= 80) return '투자자들이 낙관적입니다. 과열 징후에 주의하세요.';
    return '시장이 극도로 과열되어 있습니다. 차익 실현을 고려하세요.';
  }

  /// VIX 값에 따른 해석 텍스트를 반환한다.
  String _vixInterpretation(double vixValue) {
    if (vixValue < 15) return '시장 안정 - 낮은 변동성';
    if (vixValue < 20) return '정상 범위 - 보통 변동성';
    if (vixValue < 25) return '경계 - 높아지는 변동성';
    if (vixValue < 30) return '높은 불안 - 급격한 변동 가능';
    return '극도의 공포 - 시장 패닉';
  }

  /// VIX 값에 따른 해석 색상을 반환한다.
  Color _vixInterpretationColor(double vixValue, BuildContext context) {
    if (vixValue < 15) return context.tc.profit;
    if (vixValue < 20) return context.tc.textTertiary;
    if (vixValue < 25) return context.tc.warning;
    if (vixValue < 30) return ChartColors.vixHighAnxiety;
    return context.tc.loss;
  }

  @override
  Widget build(BuildContext context) {
    final score = fearGreed.score.toDouble();
    final progress = score / 100.0;
    final gaugeColor = _colorForScore(score);
    final vixChange = vix.change1d;
    final vixChangeColor = vixChange > 0
        ? context.tc.loss
        : vixChange < 0
            ? context.tc.profit
            : context.tc.textTertiary;
    final vixChangeIcon = vixChange > 0
        ? Icons.arrow_upward_rounded
        : vixChange < 0
            ? Icons.arrow_downward_rounded
            : Icons.remove_rounded;
    final interpretation = _scoreInterpretation(score);
    final vixInterpText = _vixInterpretation(vix.value);
    final vixInterpColor = _vixInterpretationColor(vix.value, context);

    return Column(
      children: [
        SizedBox(
          width: 300,
          height: 180,
          child: TweenAnimationBuilder<double>(
            tween: Tween(begin: 0, end: progress),
            duration: AnimDuration.chart,
            curve: AnimCurve.easeOut,
            builder: (context, animatedProgress, _) {
              return CustomPaint(
                painter: _FearGreedPainter(
                  progress: animatedProgress,
                  gaugeColor: gaugeColor,
                  backgroundColor: context.tc.surfaceBorder,
                  pointerInnerColor: context.tc.surface,
                ),
                child: Center(
                  child: Padding(
                    padding: const EdgeInsets.only(top: 30),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          '${fearGreed.score}',
                          style: AppTypography.numberLarge.copyWith(
                            color: gaugeColor,
                            fontSize: 42,
                          ),
                        ),
                        Text(
                          _levelLabel('ko', _scoreToLevel(score)),
                          style: AppTypography.labelMedium.copyWith(
                            color: gaugeColor,
                            fontSize: 14,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),
        AppSpacing.vGapSm,
        // VIX 값과 변화율 표시
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              'VIX ',
              style: AppTypography.bodySmall.copyWith(
                color: context.tc.textTertiary,
                fontSize: 14,
              ),
            ),
            Text(
              vix.value.toStringAsFixed(2),
              style: AppTypography.numberSmall.copyWith(
                color: context.tc.textSecondary,
                fontSize: 14,
              ),
            ),
            AppSpacing.hGapXs,
            Icon(vixChangeIcon, size: 14, color: vixChangeColor),
            Text(
              '${vixChange.abs().toStringAsFixed(2)}%',
              style: AppTypography.numberSmall.copyWith(
                color: vixChangeColor,
                fontSize: 14,
              ),
            ),
          ],
        ),
        AppSpacing.vGapXs,
        // VIX 해석 텍스트
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Text(
            vixInterpText,
            style: AppTypography.bodySmall.copyWith(
              color: vixInterpColor,
              fontSize: 13,
            ),
            textAlign: TextAlign.center,
          ),
        ),
        AppSpacing.vGapSm,
        // Fear & Greed 해석 텍스트 (인용 블록 스타일)
        Container(
          margin: const EdgeInsets.symmetric(horizontal: 2),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            color: gaugeColor.withValues(alpha: 0.06),
            borderRadius: AppSpacing.borderRadiusSm,
            border: Border(
              left: BorderSide(color: gaugeColor.withValues(alpha: 0.6), width: 3),
            ),
          ),
          child: Text(
            interpretation,
            style: AppTypography.bodySmall.copyWith(
              color: gaugeColor.withValues(alpha: 0.9),
              fontSize: 13,
              height: 1.4,
            ),
          ),
        ),
      ],
    );
  }

  static String _scoreToLevel(double score) {
    if (score <= 20) return 'extreme_fear';
    if (score <= 40) return 'fear';
    if (score <= 60) return 'neutral';
    if (score <= 80) return 'greed';
    return 'extreme_greed';
  }
}

class _FearGreedPainter extends CustomPainter {
  final double progress;
  final Color gaugeColor;
  final Color backgroundColor;
  final Color pointerInnerColor;

  const _FearGreedPainter({
    required this.progress,
    required this.gaugeColor,
    required this.backgroundColor,
    required this.pointerInnerColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    const strokeWidth = 14.0;
    // radius를 width와 height 모두 고려하여 컨테이너 안에 맞춘다
    final maxRadiusFromWidth = size.width / 2 - 18;
    final maxRadiusFromHeight = size.height - 16;
    final radius = math.min(maxRadiusFromWidth, maxRadiusFromHeight);
    final center = Offset(size.width / 2, size.height - 8);
    const startAngle = math.pi;
    const sweepAngle = math.pi;

    // 배경 아크
    final bgPaint = Paint()
      ..color = backgroundColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;

    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      startAngle,
      sweepAngle,
      false,
      bgPaint,
    );

    if (progress <= 0) return;

    // 그라디언트 색상으로 진행 아크를 그린다.
    // 단순화: 현재 점수 색상을 단색으로 사용한다.
    final progressPaint = Paint()
      ..color = gaugeColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;

    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      startAngle,
      sweepAngle * progress,
      false,
      progressPaint,
    );

    // 현재 위치 포인터 원
    final angle = startAngle + sweepAngle * progress;
    final pointerX = center.dx + radius * math.cos(angle);
    final pointerY = center.dy + radius * math.sin(angle);
    final pointerPaint = Paint()
      ..color = gaugeColor
      ..style = PaintingStyle.fill;
    canvas.drawCircle(Offset(pointerX, pointerY), 7, pointerPaint);
    canvas.drawCircle(
      Offset(pointerX, pointerY),
      4,
      Paint()..color = pointerInnerColor,
    );
  }

  @override
  bool shouldRepaint(covariant _FearGreedPainter oldDelegate) {
    return oldDelegate.progress != progress ||
        oldDelegate.gaugeColor != gaugeColor ||
        oldDelegate.backgroundColor != backgroundColor ||
        oldDelegate.pointerInnerColor != pointerInnerColor;
  }
}
