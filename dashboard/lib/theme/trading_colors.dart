import 'package:flutter/material.dart';

/// 트레이딩 대시보드 커스텀 컬러 ThemeExtension이다.
/// 다크/라이트 테마 전환 시 모든 컴포넌트가 올바른 색상을 참조한다.
class TradingColors extends ThemeExtension<TradingColors> {
  final Color background;
  final Color surface;
  final Color surfaceElevated;
  final Color surfaceBorder;
  final Color primary;
  final Color primaryLight;
  final Color primaryDark;
  final Color profit;
  final Color profitLight;
  final Color loss;
  final Color lossLight;
  final Color warning;
  final Color warningLight;
  final Color info;
  final Color textPrimary;
  final Color textSecondary;
  final Color textTertiary;
  final Color textDisabled;
  final Color glassBackground;
  final Color glassBorder;
  final Color chartGrid;
  final Color chartAxis;
  final Color chart1;
  final Color chart2;
  final Color chart3;
  final Color chart4;
  final Color chart5;

  const TradingColors({
    required this.background,
    required this.surface,
    required this.surfaceElevated,
    required this.surfaceBorder,
    required this.primary,
    required this.primaryLight,
    required this.primaryDark,
    required this.profit,
    required this.profitLight,
    required this.loss,
    required this.lossLight,
    required this.warning,
    required this.warningLight,
    required this.info,
    required this.textPrimary,
    required this.textSecondary,
    required this.textTertiary,
    required this.textDisabled,
    required this.glassBackground,
    required this.glassBorder,
    required this.chartGrid,
    required this.chartAxis,
    required this.chart1,
    required this.chart2,
    required this.chart3,
    required this.chart4,
    required this.chart5,
  });

  // ── 다크 테마 인스턴스 ──
  static const dark = TradingColors(
    background: Color(0xFF06080F),
    surface: Color(0xFF0F1420),
    surfaceElevated: Color(0xFF161C2E),
    surfaceBorder: Color(0xFF1E2740),
    primary: Color(0xFF3B82F6),
    primaryLight: Color(0xFF60A5FA),
    primaryDark: Color(0xFF2563EB),
    profit: Color(0xFF10B981),
    profitLight: Color(0xFF34D399),
    loss: Color(0xFFEF4444),
    lossLight: Color(0xFFF87171),
    warning: Color(0xFFF59E0B),
    warningLight: Color(0xFFFBBF24),
    info: Color(0xFF3B82F6),
    textPrimary: Color(0xF2FFFFFF),
    textSecondary: Color(0xB3FFFFFF),
    textTertiary: Color(0x73FFFFFF),
    textDisabled: Color(0x40FFFFFF),
    glassBackground: Color(0x990F1420),
    glassBorder: Color(0x661E2740),
    chartGrid: Color(0x0FFFFFFF),
    chartAxis: Color(0x4DFFFFFF),
    chart1: Color(0xFF3B82F6),
    chart2: Color(0xFF10B981),
    chart3: Color(0xFFF59E0B),
    chart4: Color(0xFF8B5CF6),
    chart5: Color(0xFFEC4899),
  );

  // ── 라이트 테마 인스턴스 (전문 금융 대시보드 스타일) ──
  static const light = TradingColors(
    background: Color(0xFFF5F7FA),
    surface: Color(0xFFFFFFFF),
    surfaceElevated: Color(0xFFF0F2F5),
    surfaceBorder: Color(0xFFE2E8F0),
    primary: Color(0xFF2563EB),
    primaryLight: Color(0xFF3B82F6),
    primaryDark: Color(0xFF1D4ED8),
    profit: Color(0xFF059669),
    profitLight: Color(0xFF10B981),
    loss: Color(0xFFDC2626),
    lossLight: Color(0xFFEF4444),
    warning: Color(0xFFD97706),
    warningLight: Color(0xFFF59E0B),
    info: Color(0xFF2563EB),
    textPrimary: Color(0xF20F172A),
    textSecondary: Color(0xB30F172A),
    textTertiary: Color(0x730F172A),
    textDisabled: Color(0x400F172A),
    glassBackground: Color(0xE6FFFFFF),
    glassBorder: Color(0x33E2E8F0),
    chartGrid: Color(0x0F000000),
    chartAxis: Color(0x4D000000),
    chart1: Color(0xFF2563EB),
    chart2: Color(0xFF059669),
    chart3: Color(0xFFD97706),
    chart4: Color(0xFF7C3AED),
    chart5: Color(0xFFDB2777),
  );

  // ── 헬퍼 getter들 ──

  Color get profitBg => profit.withValues(alpha: 0.12);
  Color get lossBg => loss.withValues(alpha: 0.12);
  Color get warningBg => warning.withValues(alpha: 0.12);
  Color get infoBg => info.withValues(alpha: 0.12);
  Color get primaryGlow => primary.withValues(alpha: 0.20);

  /// PnL 부호에 따른 색상을 반환한다.
  Color pnlColor(double value) => value >= 0 ? profit : loss;

  /// PnL 부호에 따른 밝은 색상을 반환한다.
  Color pnlColorLight(double value) => value >= 0 ? profitLight : lossLight;

  /// PnL 부호에 따른 배경 색상을 반환한다.
  Color pnlBg(double value) => value >= 0 ? profitBg : lossBg;

  /// 심각도에 따른 색상을 반환한다.
  Color severityColor(String severity) {
    switch (severity.toLowerCase()) {
      case 'critical':
        return loss;
      case 'warning':
        return warning;
      case 'info':
        return info;
      default:
        return textTertiary;
    }
  }

  @override
  TradingColors copyWith({
    Color? background,
    Color? surface,
    Color? surfaceElevated,
    Color? surfaceBorder,
    Color? primary,
    Color? primaryLight,
    Color? primaryDark,
    Color? profit,
    Color? profitLight,
    Color? loss,
    Color? lossLight,
    Color? warning,
    Color? warningLight,
    Color? info,
    Color? textPrimary,
    Color? textSecondary,
    Color? textTertiary,
    Color? textDisabled,
    Color? glassBackground,
    Color? glassBorder,
    Color? chartGrid,
    Color? chartAxis,
    Color? chart1,
    Color? chart2,
    Color? chart3,
    Color? chart4,
    Color? chart5,
  }) {
    return TradingColors(
      background: background ?? this.background,
      surface: surface ?? this.surface,
      surfaceElevated: surfaceElevated ?? this.surfaceElevated,
      surfaceBorder: surfaceBorder ?? this.surfaceBorder,
      primary: primary ?? this.primary,
      primaryLight: primaryLight ?? this.primaryLight,
      primaryDark: primaryDark ?? this.primaryDark,
      profit: profit ?? this.profit,
      profitLight: profitLight ?? this.profitLight,
      loss: loss ?? this.loss,
      lossLight: lossLight ?? this.lossLight,
      warning: warning ?? this.warning,
      warningLight: warningLight ?? this.warningLight,
      info: info ?? this.info,
      textPrimary: textPrimary ?? this.textPrimary,
      textSecondary: textSecondary ?? this.textSecondary,
      textTertiary: textTertiary ?? this.textTertiary,
      textDisabled: textDisabled ?? this.textDisabled,
      glassBackground: glassBackground ?? this.glassBackground,
      glassBorder: glassBorder ?? this.glassBorder,
      chartGrid: chartGrid ?? this.chartGrid,
      chartAxis: chartAxis ?? this.chartAxis,
      chart1: chart1 ?? this.chart1,
      chart2: chart2 ?? this.chart2,
      chart3: chart3 ?? this.chart3,
      chart4: chart4 ?? this.chart4,
      chart5: chart5 ?? this.chart5,
    );
  }

  @override
  TradingColors lerp(TradingColors? other, double t) {
    if (other == null) return this;
    return TradingColors(
      background: Color.lerp(background, other.background, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceElevated: Color.lerp(surfaceElevated, other.surfaceElevated, t)!,
      surfaceBorder: Color.lerp(surfaceBorder, other.surfaceBorder, t)!,
      primary: Color.lerp(primary, other.primary, t)!,
      primaryLight: Color.lerp(primaryLight, other.primaryLight, t)!,
      primaryDark: Color.lerp(primaryDark, other.primaryDark, t)!,
      profit: Color.lerp(profit, other.profit, t)!,
      profitLight: Color.lerp(profitLight, other.profitLight, t)!,
      loss: Color.lerp(loss, other.loss, t)!,
      lossLight: Color.lerp(lossLight, other.lossLight, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      warningLight: Color.lerp(warningLight, other.warningLight, t)!,
      info: Color.lerp(info, other.info, t)!,
      textPrimary: Color.lerp(textPrimary, other.textPrimary, t)!,
      textSecondary: Color.lerp(textSecondary, other.textSecondary, t)!,
      textTertiary: Color.lerp(textTertiary, other.textTertiary, t)!,
      textDisabled: Color.lerp(textDisabled, other.textDisabled, t)!,
      glassBackground: Color.lerp(glassBackground, other.glassBackground, t)!,
      glassBorder: Color.lerp(glassBorder, other.glassBorder, t)!,
      chartGrid: Color.lerp(chartGrid, other.chartGrid, t)!,
      chartAxis: Color.lerp(chartAxis, other.chartAxis, t)!,
      chart1: Color.lerp(chart1, other.chart1, t)!,
      chart2: Color.lerp(chart2, other.chart2, t)!,
      chart3: Color.lerp(chart3, other.chart3, t)!,
      chart4: Color.lerp(chart4, other.chart4, t)!,
      chart5: Color.lerp(chart5, other.chart5, t)!,
    );
  }
}

/// BuildContext 확장 - 간결한 테마 색상 접근을 제공한다.
extension TradingColorsExtension on BuildContext {
  /// 현재 테마의 TradingColors를 반환한다. 테마 확장이 없으면 다크를 기본으로 사용한다.
  TradingColors get tc =>
      Theme.of(this).extension<TradingColors>() ?? TradingColors.dark;
}
