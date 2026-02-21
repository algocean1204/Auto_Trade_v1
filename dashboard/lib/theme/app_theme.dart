import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'app_colors.dart';
import 'app_typography.dart';
import 'app_spacing.dart';
import 'trading_colors.dart';

/// 앱 전체 테마를 정의한다.
/// Material3 기반의 다크/라이트 테마에 "Precision Noir" 디자인 시스템을 적용한다.
class AppTheme {
  AppTheme._();

  // ── 다크 테마 ──

  static ThemeData get darkTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      primaryColor: AppColors.primary,
      scaffoldBackgroundColor: AppColors.background,
      extensions: const [TradingColors.dark],
      colorScheme: const ColorScheme.dark(
        primary: AppColors.primary,
        secondary: AppColors.primaryLight,
        surface: AppColors.surface,
        error: AppColors.loss,
        onPrimary: Colors.white,
        onSecondary: Colors.white,
        onSurface: AppColors.textPrimary,
        onError: Colors.white,
      ),
      cardTheme: CardThemeData(
        color: AppColors.surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusLg,
          side: BorderSide(
            color: AppColors.surfaceBorder.withValues(alpha: 0.3),
            width: 1,
          ),
        ),
        margin: EdgeInsets.zero,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.background,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        systemOverlayStyle: SystemUiOverlayStyle.light,
        titleTextStyle: AppTypography.displaySmall.copyWith(color: AppColors.textPrimary),
        iconTheme: const IconThemeData(color: AppColors.textSecondary),
      ),
      textTheme: TextTheme(
        displayLarge: AppTypography.displayLarge.copyWith(color: AppColors.textPrimary),
        displayMedium: AppTypography.displayMedium.copyWith(color: AppColors.textPrimary),
        displaySmall: AppTypography.displaySmall.copyWith(color: AppColors.textPrimary),
        headlineMedium: AppTypography.headlineMedium.copyWith(color: AppColors.textPrimary),
        bodyLarge: AppTypography.bodyLarge.copyWith(color: AppColors.textSecondary),
        bodyMedium: AppTypography.bodyMedium.copyWith(color: AppColors.textSecondary),
        bodySmall: AppTypography.bodySmall.copyWith(color: AppColors.textTertiary),
        labelLarge: AppTypography.labelLarge.copyWith(color: AppColors.textPrimary),
        labelMedium: AppTypography.labelMedium.copyWith(color: AppColors.textSecondary),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.primary,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
          ),
          elevation: 0,
          textStyle: AppTypography.labelLarge,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: AppColors.primary,
          textStyle: AppTypography.labelLarge,
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.textPrimary,
          side: BorderSide(color: AppColors.surfaceBorder),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
          ),
          textStyle: AppTypography.labelLarge,
        ),
      ),
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        elevation: 4,
      ),
      chipTheme: ChipThemeData(
        backgroundColor: AppColors.surface,
        selectedColor: AppColors.primary.withValues(alpha: 0.2),
        labelStyle: AppTypography.labelMedium.copyWith(color: AppColors.textSecondary),
        side: BorderSide(color: AppColors.surfaceBorder),
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusSm,
        ),
        showCheckmark: false,
      ),
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) return AppColors.primary;
          return AppColors.textTertiary;
        }),
        trackColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return AppColors.primary.withValues(alpha: 0.4);
          }
          return AppColors.surfaceBorder;
        }),
        trackOutlineColor: WidgetStateProperty.all(Colors.transparent),
      ),
      sliderTheme: SliderThemeData(
        activeTrackColor: AppColors.primary,
        inactiveTrackColor: AppColors.surfaceBorder,
        thumbColor: AppColors.primary,
        overlayColor: AppColors.primary.withValues(alpha: 0.12),
        thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 8),
        trackHeight: 4,
      ),
      bottomNavigationBarTheme: BottomNavigationBarThemeData(
        backgroundColor: AppColors.surface,
        selectedItemColor: AppColors.primary,
        unselectedItemColor: AppColors.textTertiary,
        type: BottomNavigationBarType.fixed,
        elevation: 0,
        selectedLabelStyle: AppTypography.labelMedium.copyWith(
          color: AppColors.primary,
        ),
        unselectedLabelStyle: AppTypography.labelMedium.copyWith(
          color: AppColors.textTertiary,
        ),
      ),
      tabBarTheme: TabBarThemeData(
        labelColor: AppColors.primary,
        unselectedLabelColor: AppColors.textTertiary,
        labelStyle: AppTypography.labelLarge,
        unselectedLabelStyle: AppTypography.labelLarge,
        indicatorColor: AppColors.primary,
        indicatorSize: TabBarIndicatorSize.label,
        dividerColor: Colors.transparent,
      ),
      dividerTheme: DividerThemeData(
        color: AppColors.surfaceBorder.withValues(alpha: 0.5),
        thickness: 1,
        space: 1,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.surfaceElevated,
        border: OutlineInputBorder(
          borderRadius: AppSpacing.borderRadiusMd,
          borderSide: BorderSide(color: AppColors.surfaceBorder),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: AppSpacing.borderRadiusMd,
          borderSide: BorderSide(color: AppColors.surfaceBorder),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: AppSpacing.borderRadiusMd,
          borderSide: const BorderSide(color: AppColors.primary, width: 1.5),
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        hintStyle: AppTypography.bodyMedium.copyWith(
          color: AppColors.textDisabled,
        ),
        labelStyle: AppTypography.bodyMedium.copyWith(color: AppColors.textSecondary),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: AppColors.surfaceElevated,
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusXl,
        ),
        titleTextStyle: AppTypography.displaySmall.copyWith(color: AppColors.textPrimary),
        contentTextStyle: AppTypography.bodyLarge.copyWith(color: AppColors.textSecondary),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: AppColors.surfaceElevated,
        contentTextStyle: AppTypography.bodyMedium.copyWith(
          color: AppColors.textPrimary,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusMd,
        ),
        behavior: SnackBarBehavior.floating,
      ),
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: AppColors.primary,
        linearTrackColor: AppColors.surfaceBorder,
      ),
      // 데스크탑 NavigationRail 테마
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: AppColors.surface,
        selectedIconTheme: const IconThemeData(color: AppColors.primary),
        unselectedIconTheme: const IconThemeData(color: AppColors.textTertiary),
        selectedLabelTextStyle: AppTypography.labelMedium.copyWith(
          color: AppColors.primary,
        ),
        unselectedLabelTextStyle: AppTypography.labelMedium.copyWith(
          color: AppColors.textTertiary,
        ),
        indicatorColor: AppColors.primary,
        elevation: 0,
        labelType: NavigationRailLabelType.none,
      ),
      // 체크박스 테마
      checkboxTheme: CheckboxThemeData(
        fillColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) return AppColors.primary;
          return Colors.transparent;
        }),
        checkColor: WidgetStateProperty.all(Colors.white),
        side: BorderSide(color: AppColors.surfaceBorder),
      ),
    );
  }

  // ── 라이트 테마 ──

  static const _lightPrimary = Color(0xFF2563EB);
  static const _lightSurface = Color(0xFFFFFFFF);
  static const _lightBackground = Color(0xFFF5F7FA);
  static const _lightSurfaceElevated = Color(0xFFF0F2F5);
  static const _lightSurfaceBorder = Color(0xFFE2E8F0);
  static const _lightTextPrimary = Color(0xF20F172A);
  static const _lightTextSecondary = Color(0xB30F172A);
  static const _lightTextTertiary = Color(0x730F172A);
  static const _lightTextDisabled = Color(0x400F172A);
  static const _lightLoss = Color(0xFFDC2626);

  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      primaryColor: _lightPrimary,
      scaffoldBackgroundColor: _lightBackground,
      extensions: const [TradingColors.light],
      colorScheme: const ColorScheme.light(
        primary: _lightPrimary,
        secondary: Color(0xFF3B82F6),
        surface: _lightSurface,
        error: _lightLoss,
        onPrimary: Colors.white,
        onSecondary: Colors.white,
        onSurface: _lightTextPrimary,
        onError: Colors.white,
      ),
      cardTheme: CardThemeData(
        color: _lightSurface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusLg,
          side: BorderSide(
            color: _lightSurfaceBorder.withValues(alpha: 0.6),
            width: 1,
          ),
        ),
        margin: EdgeInsets.zero,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: _lightSurface,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        systemOverlayStyle: SystemUiOverlayStyle.dark,
        titleTextStyle: _lightDisplaySmall,
        iconTheme: const IconThemeData(color: _lightTextSecondary),
      ),
      textTheme: _lightTextTheme,
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: _lightPrimary,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
          ),
          elevation: 0,
          textStyle: _lightLabelLarge,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: _lightPrimary,
          textStyle: _lightLabelLarge,
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: _lightTextPrimary,
          side: BorderSide(color: _lightSurfaceBorder),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
          ),
          textStyle: _lightLabelLarge,
        ),
      ),
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: _lightPrimary,
        foregroundColor: Colors.white,
        elevation: 4,
      ),
      chipTheme: ChipThemeData(
        backgroundColor: _lightSurface,
        selectedColor: _lightPrimary.withValues(alpha: 0.15),
        labelStyle: _lightLabelMedium,
        side: BorderSide(color: _lightSurfaceBorder),
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusSm,
        ),
        showCheckmark: false,
      ),
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) return _lightPrimary;
          return _lightTextTertiary;
        }),
        trackColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return _lightPrimary.withValues(alpha: 0.4);
          }
          return _lightSurfaceBorder;
        }),
        trackOutlineColor: WidgetStateProperty.all(Colors.transparent),
      ),
      sliderTheme: SliderThemeData(
        activeTrackColor: _lightPrimary,
        inactiveTrackColor: _lightSurfaceBorder,
        thumbColor: _lightPrimary,
        overlayColor: _lightPrimary.withValues(alpha: 0.12),
        thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 8),
        trackHeight: 4,
      ),
      bottomNavigationBarTheme: BottomNavigationBarThemeData(
        backgroundColor: _lightSurface,
        selectedItemColor: _lightPrimary,
        unselectedItemColor: _lightTextTertiary,
        type: BottomNavigationBarType.fixed,
        elevation: 1,
        selectedLabelStyle: _lightLabelMedium.copyWith(color: _lightPrimary),
        unselectedLabelStyle:
            _lightLabelMedium.copyWith(color: _lightTextTertiary),
      ),
      tabBarTheme: TabBarThemeData(
        labelColor: _lightPrimary,
        unselectedLabelColor: _lightTextTertiary,
        labelStyle: _lightLabelLarge,
        unselectedLabelStyle: _lightLabelLarge,
        indicatorColor: _lightPrimary,
        indicatorSize: TabBarIndicatorSize.label,
        dividerColor: Colors.transparent,
      ),
      dividerTheme: DividerThemeData(
        color: _lightSurfaceBorder.withValues(alpha: 0.8),
        thickness: 1,
        space: 1,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: _lightSurfaceElevated,
        border: OutlineInputBorder(
          borderRadius: AppSpacing.borderRadiusMd,
          borderSide: BorderSide(color: _lightSurfaceBorder),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: AppSpacing.borderRadiusMd,
          borderSide: BorderSide(color: _lightSurfaceBorder),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: AppSpacing.borderRadiusMd,
          borderSide: const BorderSide(color: _lightPrimary, width: 1.5),
        ),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        hintStyle: _lightBodyMedium.copyWith(color: _lightTextDisabled),
        labelStyle: _lightBodyMedium,
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: _lightSurface,
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusXl,
        ),
        titleTextStyle: _lightDisplaySmall,
        contentTextStyle: _lightBodyLarge,
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: const Color(0xFF1E293B),
        contentTextStyle: _lightBodyMedium.copyWith(color: Colors.white),
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusMd,
        ),
        behavior: SnackBarBehavior.floating,
      ),
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: _lightPrimary,
        linearTrackColor: _lightSurfaceBorder,
      ),
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: _lightSurface,
        selectedIconTheme: const IconThemeData(color: _lightPrimary),
        unselectedIconTheme: const IconThemeData(color: _lightTextTertiary),
        selectedLabelTextStyle:
            _lightLabelMedium.copyWith(color: _lightPrimary),
        unselectedLabelTextStyle:
            _lightLabelMedium.copyWith(color: _lightTextTertiary),
        indicatorColor: _lightPrimary.withValues(alpha: 0.15),
        elevation: 0,
        labelType: NavigationRailLabelType.none,
      ),
      checkboxTheme: CheckboxThemeData(
        fillColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) return _lightPrimary;
          return Colors.transparent;
        }),
        checkColor: WidgetStateProperty.all(Colors.white),
        side: BorderSide(color: _lightSurfaceBorder),
      ),
    );
  }

  // ── 라이트 테마용 TextStyle 헬퍼 ──
  // AppTypography는 색상을 포함하지 않으므로 라이트 테마 전용 색상을 적용한다.

  static TextStyle get _lightDisplaySmall => AppTypography.displaySmall
      .copyWith(color: _lightTextPrimary);

  static TextStyle get _lightBodyMedium =>
      AppTypography.bodyMedium.copyWith(color: _lightTextSecondary);

  static TextStyle get _lightBodyLarge =>
      AppTypography.bodyLarge.copyWith(color: _lightTextSecondary);

  static TextStyle get _lightLabelLarge =>
      AppTypography.labelLarge.copyWith(color: _lightTextPrimary);

  static TextStyle get _lightLabelMedium =>
      AppTypography.labelMedium.copyWith(color: _lightTextSecondary);

  static TextTheme get _lightTextTheme => TextTheme(
        displayLarge: AppTypography.displayLarge.copyWith(color: _lightTextPrimary),
        displayMedium: AppTypography.displayMedium.copyWith(color: _lightTextPrimary),
        displaySmall: AppTypography.displaySmall.copyWith(color: _lightTextPrimary),
        headlineMedium: AppTypography.headlineMedium.copyWith(color: _lightTextPrimary),
        bodyLarge: AppTypography.bodyLarge.copyWith(color: _lightTextSecondary),
        bodyMedium: AppTypography.bodyMedium.copyWith(color: _lightTextSecondary),
        bodySmall: AppTypography.bodySmall.copyWith(color: _lightTextTertiary),
        labelLarge: AppTypography.labelLarge.copyWith(color: _lightTextPrimary),
        labelMedium: AppTypography.labelMedium.copyWith(color: _lightTextSecondary),
      );
}
