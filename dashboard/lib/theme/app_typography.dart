import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// 앱 전체 타이포그래피를 정의한다.
/// UI 텍스트는 Inter, 숫자/코드는 JetBrains Mono를 사용한다.
/// 색상은 포함하지 않으며, 테마의 TextTheme 또는 TradingColors에서 색상을 지정한다.
class AppTypography {
  AppTypography._();

  // ── Display ──
  static TextStyle get displayLarge => GoogleFonts.inter(
        fontSize: 34,
        fontWeight: FontWeight.w700,
        height: 1.2,
      );

  static TextStyle get displayMedium => GoogleFonts.inter(
        fontSize: 26,
        fontWeight: FontWeight.w600,
        height: 1.3,
      );

  static TextStyle get displaySmall => GoogleFonts.inter(
        fontSize: 22,
        fontWeight: FontWeight.w600,
        height: 1.3,
      );

  // ── Headline ──
  static TextStyle get headlineMedium => GoogleFonts.inter(
        fontSize: 20,
        fontWeight: FontWeight.w600,
        height: 1.4,
      );

  // ── Body ──
  static TextStyle get bodyLarge => GoogleFonts.inter(
        fontSize: 17,
        fontWeight: FontWeight.w400,
        height: 1.5,
      );

  static TextStyle get bodyMedium => GoogleFonts.inter(
        fontSize: 15,
        fontWeight: FontWeight.w400,
        height: 1.5,
      );

  static TextStyle get bodySmall => GoogleFonts.inter(
        fontSize: 13,
        fontWeight: FontWeight.w400,
        height: 1.5,
      );

  // ── Label ──
  static TextStyle get labelLarge => GoogleFonts.inter(
        fontSize: 14,
        fontWeight: FontWeight.w600,
        height: 1.4,
      );

  static TextStyle get labelMedium => GoogleFonts.inter(
        fontSize: 12,
        fontWeight: FontWeight.w600,
        height: 1.4,
      );

  // ── Monospace Numbers ──
  static TextStyle get numberLarge => GoogleFonts.jetBrainsMono(
        fontSize: 30,
        fontWeight: FontWeight.w700,
        height: 1.2,
      );

  static TextStyle get numberMedium => GoogleFonts.jetBrainsMono(
        fontSize: 20,
        fontWeight: FontWeight.w600,
        height: 1.3,
      );

  static TextStyle get numberSmall => GoogleFonts.jetBrainsMono(
        fontSize: 16,
        fontWeight: FontWeight.w500,
        height: 1.4,
      );

  /// Flutter TextTheme을 생성한다. 색상은 포함하지 않으므로 테마에서 지정한다.
  static TextTheme get textTheme => TextTheme(
        displayLarge: displayLarge,
        displayMedium: displayMedium,
        displaySmall: displaySmall,
        headlineMedium: headlineMedium,
        bodyLarge: bodyLarge,
        bodyMedium: bodyMedium,
        bodySmall: bodySmall,
        labelLarge: labelLarge,
        labelMedium: labelMedium,
      );
}
