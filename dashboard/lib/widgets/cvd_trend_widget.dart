import 'package:flutter/material.dart';
import '../theme/trading_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// CVD(Cumulative Volume Delta) 추세를 스파크라인 차트로 표시하는 위젯이다.
/// 최근 60초의 CVD 히스토리를 CustomPaint로 그린다.
/// 다이버전스 감지 시 알림 뱃지를 표시한다.
class CvdTrendWidget extends StatelessWidget {
  /// CVD 히스토리 데이터 (최근 60초)이다.
  final List<double> history;

  /// 현재 누적 CVD 값이다.
  final double currentCvd;

  /// 다이버전스 유형이다: "bullish_divergence", "bearish_divergence", null
  final String? divergence;

  const CvdTrendWidget({
    super.key,
    required this.history,
    required this.currentCvd,
    this.divergence,
  });

  String _divergenceLabel() {
    switch (divergence) {
      case 'bullish_divergence':
        return '강세 다이버전스';
      case 'bearish_divergence':
        return '약세 다이버전스';
      default:
        return '';
    }
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final isDivergence = divergence != null;
    final isBullish = divergence == 'bullish_divergence';

    // CVD 추세 방향을 결정한다 (마지막 5포인트 기준).
    bool isTrendingUp = true;
    if (history.length >= 2) {
      final recentEnd = history.last;
      final recentStart = history.length >= 5
          ? history[history.length - 5]
          : history.first;
      isTrendingUp = recentEnd >= recentStart;
    }

    final lineColor = isTrendingUp ? tc.profit : tc.loss;
    final divergenceColor = isBullish ? tc.profit : tc.loss;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 헤더 행
        Row(
          children: [
            Text(
              'CVD',
              style: AppTypography.labelLarge.copyWith(
                color: tc.textSecondary,
                fontSize: 13,
              ),
            ),
            AppSpacing.hGapXs,
            Text(
              '(누적 거래량 델타)',
              style: AppTypography.bodySmall.copyWith(
                color: tc.textTertiary,
                fontSize: 11,
              ),
            ),
            const Spacer(),
            // 다이버전스 뱃지
            if (isDivergence)
              AnimatedOpacity(
                opacity: isDivergence ? 1.0 : 0.0,
                duration: const Duration(milliseconds: 300),
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                  decoration: BoxDecoration(
                    color: divergenceColor.withValues(alpha: 0.15),
                    borderRadius: AppSpacing.borderRadiusFull,
                    border: Border.all(
                      color: divergenceColor.withValues(alpha: 0.5),
                      width: 1,
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        isBullish
                            ? Icons.arrow_upward_rounded
                            : Icons.arrow_downward_rounded,
                        size: 11,
                        color: divergenceColor,
                      ),
                      const SizedBox(width: 3),
                      Text(
                        _divergenceLabel(),
                        style: AppTypography.labelMedium.copyWith(
                          color: divergenceColor,
                          fontSize: 10,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
        AppSpacing.vGapXs,
        // 현재값 표시
        Row(
          children: [
            Icon(
              isTrendingUp
                  ? Icons.trending_up_rounded
                  : Icons.trending_down_rounded,
              size: 16,
              color: lineColor,
            ),
            AppSpacing.hGapXs,
            Text(
              currentCvd >= 0
                  ? '+${currentCvd.toStringAsFixed(0)}'
                  : currentCvd.toStringAsFixed(0),
              style: AppTypography.numberSmall.copyWith(
                color: lineColor,
                fontSize: 14,
                fontWeight: FontWeight.w600,
              ),
            ),
            AppSpacing.hGapSm,
            Text(
              '60초',
              style: AppTypography.bodySmall.copyWith(
                color: tc.textTertiary,
                fontSize: 10,
              ),
            ),
          ],
        ),
        AppSpacing.vGapSm,
        // 스파크라인 차트
        SizedBox(
          height: 64,
          child: history.isEmpty
              ? Center(
                  child: Text(
                    '데이터 수신 중...',
                    style: AppTypography.bodySmall.copyWith(
                      color: tc.textTertiary,
                      fontSize: 11,
                    ),
                  ),
                )
              : CustomPaint(
                  size: const Size(double.infinity, 64),
                  painter: _SparklinePainter(
                    data: history,
                    lineColor: lineColor,
                    fillColor: lineColor.withValues(alpha: 0.12),
                    gridColor: tc.chartGrid,
                  ),
                ),
        ),
      ],
    );
  }
}

/// 스파크라인을 그리는 CustomPainter이다.
class _SparklinePainter extends CustomPainter {
  final List<double> data;
  final Color lineColor;
  final Color fillColor;
  final Color gridColor;

  const _SparklinePainter({
    required this.data,
    required this.lineColor,
    required this.fillColor,
    required this.gridColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    if (data.length < 2) return;

    final minValue = data.reduce((a, b) => a < b ? a : b);
    final maxValue = data.reduce((a, b) => a > b ? a : b);
    final range = (maxValue - minValue).abs();

    // 범위가 0이면 수평선을 그린다.
    final effectiveRange = range < 1e-6 ? 1.0 : range;
    final padding = effectiveRange * 0.1;

    final adjustedMin = minValue - padding;
    final adjustedMax = maxValue + padding;
    final adjustedRange = adjustedMax - adjustedMin;

    // 중앙선 (시각적 기준선) 그리기
    final gridPaint = Paint()
      ..color = gridColor
      ..strokeWidth = 0.5;
    canvas.drawLine(
      Offset(0, size.height / 2),
      Offset(size.width, size.height / 2),
      gridPaint,
    );

    // 데이터 포인트를 픽셀 좌표로 변환한다.
    final points = <Offset>[];
    for (int i = 0; i < data.length; i++) {
      final x = i / (data.length - 1) * size.width;
      final normalizedY = (data[i] - adjustedMin) / adjustedRange;
      final y = size.height - normalizedY * size.height;
      points.add(Offset(x, y.clamp(0.0, size.height)));
    }

    // 채우기 영역 그리기
    final fillPath = Path();
    fillPath.moveTo(points.first.dx, size.height);
    for (final point in points) {
      fillPath.lineTo(point.dx, point.dy);
    }
    fillPath.lineTo(points.last.dx, size.height);
    fillPath.close();

    final fillPaint = Paint()
      ..color = fillColor
      ..style = PaintingStyle.fill;
    canvas.drawPath(fillPath, fillPaint);

    // 라인 그리기 (스무스 곡선)
    final linePath = Path();
    linePath.moveTo(points.first.dx, points.first.dy);

    for (int i = 1; i < points.length; i++) {
      final prev = points[i - 1];
      final curr = points[i];
      final controlX = (prev.dx + curr.dx) / 2;
      linePath.cubicTo(
        controlX, prev.dy,
        controlX, curr.dy,
        curr.dx, curr.dy,
      );
    }

    final linePaint = Paint()
      ..color = lineColor
      ..strokeWidth = 2.0
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    canvas.drawPath(linePath, linePaint);

    // 마지막 포인트에 점을 그린다.
    final dotPaint = Paint()
      ..color = lineColor
      ..style = PaintingStyle.fill;
    canvas.drawCircle(points.last, 3.5, dotPaint);
  }

  @override
  bool shouldRepaint(_SparklinePainter oldDelegate) {
    return oldDelegate.data != data || oldDelegate.lineColor != lineColor;
  }
}
