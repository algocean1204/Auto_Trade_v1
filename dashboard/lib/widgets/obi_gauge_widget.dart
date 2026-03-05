import 'package:flutter/material.dart';
import '../theme/trading_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// OBI(Order Book Imbalance) 게이지 위젯이다.
/// 좌측(매도 압력, 빨간색) ← 중앙(중립) → 우측(매수 압력, 초록색) 구조의
/// 수평 게이지 바로 OBI 값을 시각화한다.
class ObiGaugeWidget extends StatefulWidget {
  /// OBI 값이다 (-1.0 ~ +1.0).
  final double value;

  /// 평활화된 OBI 값이다 (-1.0 ~ +1.0).
  final double smoothed;

  /// 매매 신호이다: "strong_buy", "buy", "neutral", "sell", "strong_sell"
  final String signal;

  const ObiGaugeWidget({
    super.key,
    required this.value,
    required this.smoothed,
    required this.signal,
  });

  @override
  State<ObiGaugeWidget> createState() => _ObiGaugeWidgetState();
}

class _ObiGaugeWidgetState extends State<ObiGaugeWidget>
    with SingleTickerProviderStateMixin {
  late AnimationController _wobbleController;
  late Animation<double> _wobbleAnimation;
  double _prevValue = 0;

  @override
  void initState() {
    super.initState();
    _prevValue = widget.value;
    _wobbleController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );
    _wobbleAnimation = Tween<double>(begin: 0, end: 1).animate(
      CurvedAnimation(parent: _wobbleController, curve: Curves.elasticOut),
    );
  }

  @override
  void didUpdateWidget(ObiGaugeWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 값이 급격히 변할 때 꿀렁이는 애니메이션을 트리거한다.
    final delta = (widget.value - _prevValue).abs();
    if (delta > 0.05) {
      _wobbleController.forward(from: 0);
    }
    _prevValue = widget.value;
  }

  @override
  void dispose() {
    _wobbleController.dispose();
    super.dispose();
  }

  String _signalLabel(String signal) {
    switch (signal) {
      case 'strong_buy':
        return '강한 매수';
      case 'buy':
        return '매수';
      case 'sell':
        return '매도';
      case 'strong_sell':
        return '강한 매도';
      default:
        return '중립';
    }
  }

  Color _signalColor(BuildContext context, String signal) {
    final tc = context.tc;
    switch (signal) {
      case 'strong_buy':
        return tc.profit;
      case 'buy':
        return tc.profitLight;
      case 'sell':
        return tc.lossLight;
      case 'strong_sell':
        return tc.loss;
      default:
        return tc.textTertiary;
    }
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    // value는 -1.0 ~ +1.0, 게이지 위치는 0.0 ~ 1.0으로 변환한다.
    final clampedValue = widget.smoothed.clamp(-1.0, 1.0);
    final gaugePosition = (clampedValue + 1.0) / 2.0; // 0=좌측, 0.5=중앙, 1=우측
    final signalColor = _signalColor(context, widget.signal);
    final isPositive = clampedValue >= 0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 헤더 행: 레이블 + 신호 배지
        Row(
          children: [
            Text(
              'OBI',
              style: AppTypography.labelLarge.copyWith(
                color: tc.textSecondary,
                fontSize: 13,
              ),
            ),
            AppSpacing.hGapSm,
            Text(
              '(오더북 불균형)',
              style: AppTypography.bodySmall.copyWith(
                color: tc.textTertiary,
                fontSize: 11,
              ),
            ),
            const Spacer(),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: signalColor.withValues(alpha: 0.15),
                borderRadius: AppSpacing.borderRadiusFull,
                border: Border.all(
                  color: signalColor.withValues(alpha: 0.4),
                  width: 1,
                ),
              ),
              child: Text(
                _signalLabel(widget.signal),
                style: AppTypography.labelMedium.copyWith(
                  color: signalColor,
                  fontSize: 11,
                ),
              ),
            ),
          ],
        ),
        AppSpacing.vGapSm,
        // 수치 표시 행
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              '매도 압력',
              style: AppTypography.bodySmall.copyWith(
                color: tc.loss.withValues(alpha: 0.7),
                fontSize: 10,
              ),
            ),
            AnimatedBuilder(
              animation: _wobbleAnimation,
              builder: (context, child) {
                return Transform.scale(
                  scale: 1.0 + _wobbleAnimation.value * 0.05,
                  child: Text(
                    widget.smoothed >= 0
                        ? '+${widget.smoothed.toStringAsFixed(3)}'
                        : widget.smoothed.toStringAsFixed(3),
                    style: AppTypography.numberSmall.copyWith(
                      color: isPositive ? tc.profit : tc.loss,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                );
              },
            ),
            Text(
              '매수 압력',
              style: AppTypography.bodySmall.copyWith(
                color: tc.profit.withValues(alpha: 0.7),
                fontSize: 10,
              ),
            ),
          ],
        ),
        AppSpacing.vGapXs,
        // 게이지 바
        AnimatedBuilder(
          animation: _wobbleAnimation,
          builder: (context, child) {
            final wobble = _wobbleAnimation.value * 0.015;
            final adjustedPosition = (gaugePosition + wobble).clamp(0.0, 1.0);
            return _buildGaugeBar(context, adjustedPosition, clampedValue, tc);
          },
        ),
        AppSpacing.vGapXs,
        // 중앙 기준선 레이블
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              '0',
              style: AppTypography.bodySmall.copyWith(
                color: tc.textTertiary,
                fontSize: 10,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildGaugeBar(
    BuildContext context,
    double position,
    double value,
    TradingColors tc,
  ) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final totalWidth = constraints.maxWidth;
        final thumbPosition = (position * totalWidth).clamp(6.0, totalWidth - 6);

        return SizedBox(
          height: 28,
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              // 베이스 트랙 (배경)
              Positioned.fill(
                child: ClipRRect(
                  borderRadius: AppSpacing.borderRadiusFull,
                  child: Container(
                    decoration: BoxDecoration(
                      color: tc.surfaceBorder,
                      borderRadius: AppSpacing.borderRadiusFull,
                    ),
                  ),
                ),
              ),
              // 채워진 영역 (중앙 기준으로 좌우 확장)
              Positioned(
                left: value >= 0 ? totalWidth / 2 : thumbPosition,
                right: value >= 0
                    ? totalWidth - thumbPosition
                    : totalWidth / 2 - (totalWidth - thumbPosition),
                top: 0,
                bottom: 0,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: value >= 0
                          ? [
                              tc.profit.withValues(alpha: 0.5),
                              tc.profit,
                            ]
                          : [
                              tc.loss,
                              tc.loss.withValues(alpha: 0.5),
                            ],
                    ),
                    borderRadius: AppSpacing.borderRadiusFull,
                  ),
                ),
              ),
              // 중앙 기준선
              Positioned(
                left: totalWidth / 2 - 1,
                top: 0,
                bottom: 0,
                width: 2,
                child: Container(
                  color: tc.textTertiary.withValues(alpha: 0.5),
                ),
              ),
              // 썸 인디케이터
              AnimatedPositioned(
                duration: const Duration(milliseconds: 200),
                curve: Curves.easeOutCubic,
                left: thumbPosition - 6,
                top: 4,
                child: Container(
                  width: 12,
                  height: 20,
                  decoration: BoxDecoration(
                    color: value >= 0 ? tc.profit : tc.loss,
                    borderRadius: AppSpacing.borderRadiusSm,
                    boxShadow: [
                      BoxShadow(
                        color: (value >= 0 ? tc.profit : tc.loss)
                            .withValues(alpha: 0.6),
                        blurRadius: 8,
                        spreadRadius: 1,
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
