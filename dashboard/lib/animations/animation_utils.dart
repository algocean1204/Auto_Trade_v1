import 'package:flutter/material.dart';
import '../theme/trading_colors.dart';

/// 애니메이션 타이밍 토큰을 정의한다.
class AnimDuration {
  AnimDuration._();
  static const Duration instant = Duration(milliseconds: 100);
  static const Duration fast = Duration(milliseconds: 200);
  static const Duration normal = Duration(milliseconds: 300);
  static const Duration slow = Duration(milliseconds: 500);
  static const Duration chart = Duration(milliseconds: 800);
  static const Duration number = Duration(milliseconds: 600);
}

/// 이징 커브 토큰을 정의한다.
class AnimCurve {
  AnimCurve._();
  static const Curve easeOut = Curves.easeOutCubic;
  static const Curve easeIn = Curves.easeInCubic;
  static const Curve easeInOut = Curves.easeInOutCubic;
  static const Curve spring = Curves.elasticOut;
  static const Curve linear = Curves.linear;
}

/// 리스트 아이템의 stagger fade-in + slide-up 애니메이션 위젯이다.
class StaggeredFadeSlide extends StatefulWidget {
  final int index;
  final Widget child;
  final Duration delay;

  const StaggeredFadeSlide({
    super.key,
    required this.index,
    required this.child,
    this.delay = const Duration(milliseconds: 50),
  });

  @override
  State<StaggeredFadeSlide> createState() => _StaggeredFadeSlideState();
}

class _StaggeredFadeSlideState extends State<StaggeredFadeSlide>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _fadeAnimation;
  late final Animation<Offset> _slideAnimation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: AnimDuration.normal,
    );
    _fadeAnimation = CurvedAnimation(
      parent: _controller,
      curve: AnimCurve.easeOut,
    );
    _slideAnimation = Tween<Offset>(
      begin: const Offset(0, 0.08),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _controller,
      curve: AnimCurve.easeOut,
    ));

    final staggerDelay = widget.delay * widget.index.clamp(0, 5);
    Future.delayed(staggerDelay, () {
      if (mounted) _controller.forward();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _fadeAnimation,
      child: SlideTransition(
        position: _slideAnimation,
        child: widget.child,
      ),
    );
  }
}

/// 숫자가 카운팅되며 변하는 애니메이션 위젯이다.
class AnimatedNumber extends StatelessWidget {
  final double value;
  final TextStyle? style;
  final String Function(double) formatter;
  final Duration duration;

  const AnimatedNumber({
    super.key,
    required this.value,
    this.style,
    required this.formatter,
    this.duration = const Duration(milliseconds: 600),
  });

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: value),
      duration: duration,
      curve: AnimCurve.easeOut,
      builder: (context, animatedValue, child) {
        return Text(
          formatter(animatedValue),
          style: style,
        );
      },
    );
  }
}

/// 맥박 효과 애니메이션 위젯이다 (온라인 상태 표시기용).
class PulsingDot extends StatefulWidget {
  final Color color;
  final double size;

  const PulsingDot({
    super.key,
    required this.color,
    this.size = 10,
  });

  @override
  State<PulsingDot> createState() => _PulsingDotState();
}

class _PulsingDotState extends State<PulsingDot>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2000),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        final pulse = 1.0 + 0.3 * (_controller.value < 0.5
            ? _controller.value * 2
            : (1 - _controller.value) * 2);
        return Stack(
          alignment: Alignment.center,
          children: [
            Transform.scale(
              scale: pulse,
              child: Container(
                width: widget.size,
                height: widget.size,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: widget.color.withValues(alpha: 0.3),
                ),
              ),
            ),
            Container(
              width: widget.size * 0.6,
              height: widget.size * 0.6,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: widget.color,
              ),
            ),
          ],
        );
      },
    );
  }
}

/// 시머(스켈레톤) 로딩 효과 위젯이다.
class ShimmerLoading extends StatefulWidget {
  final double width;
  final double height;
  final BorderRadius? borderRadius;

  const ShimmerLoading({
    super.key,
    required this.width,
    required this.height,
    this.borderRadius,
  });

  @override
  State<ShimmerLoading> createState() => _ShimmerLoadingState();
}

class _ShimmerLoadingState extends State<ShimmerLoading>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final baseColor = tc.surfaceBorder;
    final highlightColor = tc.surfaceElevated;

    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return Container(
          width: widget.width,
          height: widget.height,
          decoration: BoxDecoration(
            borderRadius: widget.borderRadius ?? BorderRadius.circular(8),
            gradient: LinearGradient(
              begin: Alignment(-1.0 + 2.0 * _controller.value, 0),
              end: Alignment(-1.0 + 2.0 * _controller.value + 1.0, 0),
              colors: [
                baseColor,
                highlightColor,
                baseColor,
              ],
            ),
          ),
        );
      },
    );
  }
}

/// 페이지 전환 애니메이션 (fade + slide)을 생성한다.
class FadeSlideTransition extends StatelessWidget {
  final Animation<double> animation;
  final Widget child;

  const FadeSlideTransition({
    super.key,
    required this.animation,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: animation,
      child: SlideTransition(
        position: Tween<Offset>(
          begin: const Offset(0, 0.03),
          end: Offset.zero,
        ).animate(CurvedAnimation(
          parent: animation as AnimationController,
          curve: AnimCurve.easeOut,
        )),
        child: child,
      ),
    );
  }
}
