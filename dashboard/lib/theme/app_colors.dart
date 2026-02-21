import 'package:flutter/material.dart';

/// 앱 전체 색상 팔레트를 정의한다.
/// "Precision Noir" 디자인 컨셉 기반의 어두운 금융 대시보드 색상이다.
class AppColors {
  AppColors._();

  // ── Base Colors ──
  static const Color background = Color(0xFF06080F);
  static const Color surface = Color(0xFF0F1420);
  static const Color surfaceElevated = Color(0xFF161C2E);
  static const Color surfaceBorder = Color(0xFF1E2740);

  // ── Primary ──
  static const Color primary = Color(0xFF3B82F6);
  static const Color primaryLight = Color(0xFF60A5FA);
  static const Color primaryDark = Color(0xFF2563EB);

  // ── Semantic: Profit / Loss ──
  static const Color profit = Color(0xFF10B981);
  static const Color profitLight = Color(0xFF34D399);
  static const Color loss = Color(0xFFEF4444);
  static const Color lossLight = Color(0xFFF87171);
  static const Color warning = Color(0xFFF59E0B);
  static const Color warningLight = Color(0xFFFBBF24);
  static const Color info = Color(0xFF3B82F6);

  // ── Text ──
  static const Color textPrimary = Color(0xF2FFFFFF); // 95%
  static const Color textSecondary = Color(0xB3FFFFFF); // 70%
  static const Color textTertiary = Color(0x73FFFFFF); // 45%
  static const Color textDisabled = Color(0x40FFFFFF); // 25%

  // ── Chart Colors ──
  static const Color chart1 = Color(0xFF3B82F6);
  static const Color chart2 = Color(0xFF10B981);
  static const Color chart3 = Color(0xFFF59E0B);
  static const Color chart4 = Color(0xFF8B5CF6);
  static const Color chart5 = Color(0xFFEC4899);

  static const List<Color> chartPalette = [chart1, chart2, chart3, chart4, chart5];

  // ── Helpers ──
  static Color profitBg = profit.withValues(alpha: 0.12);
  static Color lossBg = loss.withValues(alpha: 0.12);
  static Color warningBg = warning.withValues(alpha: 0.12);
  static Color infoBg = info.withValues(alpha: 0.12);
  static Color primaryGlow = primary.withValues(alpha: 0.20);
  static Color chartGrid = Colors.white.withValues(alpha: 0.06);
  static Color chartAxis = Colors.white.withValues(alpha: 0.30);

  /// PnL 부호에 따른 색상을 반환한다.
  static Color pnlColor(double value) => value >= 0 ? profit : loss;

  /// PnL 부호에 따른 밝은 색상을 반환한다.
  static Color pnlColorLight(double value) => value >= 0 ? profitLight : lossLight;

  /// PnL 부호에 따른 배경 색상을 반환한다.
  static Color pnlBg(double value) => value >= 0 ? profitBg : lossBg;

  /// 심각도에 따른 색상을 반환한다.
  static Color severityColor(String severity) {
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

  /// 글래스 카드 배경 색상을 반환한다.
  static Color get glassBackground => surface.withValues(alpha: 0.60);
  static Color get glassBorder => surfaceBorder.withValues(alpha: 0.40);
}
