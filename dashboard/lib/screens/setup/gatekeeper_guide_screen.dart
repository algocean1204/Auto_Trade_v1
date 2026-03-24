import 'dart:io';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../theme/app_colors.dart';
import '../../theme/app_spacing.dart';
import '../../theme/app_typography.dart';

/// macOS Gatekeeper 경고 해제 방법을 안내하는 화면이다.
/// ad-hoc 서명된 앱을 처음 실행할 때 한 번만 표시한다.
class GatekeeperGuideScreen extends StatelessWidget {
  /// 안내를 확인한 후 호출되는 콜백이다.
  final VoidCallback onDismiss;

  const GatekeeperGuideScreen({super.key, required this.onDismiss});

  /// SharedPreferences 키
  static const _prefKey = 'gatekeeper_guide_shown';

  /// 안내 화면을 이미 표시했는지 확인한다.
  static Future<bool> hasBeenShown() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getBool(_prefKey) ?? false;
    } catch (_) {
      return true; // 확인 불가 시 표시하지 않는다
    }
  }

  /// 안내 화면을 표시했다고 기록한다.
  static Future<void> markAsShown() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(_prefKey, true);
    } catch (_) {
      // 저장 실패 무시
    }
  }

  /// .app 번들 내부에서 실행 중인지 판별한다.
  /// 개발 환경(flutter run)에서는 false를 반환한다.
  static bool isRunningFromAppBundle() {
    try {
      final exePath = Platform.resolvedExecutable;
      return exePath.contains('.app/Contents/');
    } catch (_) {
      return false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.xxxl),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 600),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 헤더
                const Center(
                  child: Icon(
                    Icons.security_rounded,
                    size: 56,
                    color: AppColors.warning,
                  ),
                ),
                AppSpacing.vGapLg,
                Center(
                  child: Text(
                    'macOS 보안 안내',
                    style: AppTypography.displayMedium.copyWith(
                      color: theme.colorScheme.onSurface,
                    ),
                  ),
                ),
                AppSpacing.vGapSm,
                Center(
                  child: Text(
                    '이 앱은 Apple 공증을 받지 않았으므로\n'
                    '처음 실행 시 macOS Gatekeeper가 차단할 수 있습니다.',
                    textAlign: TextAlign.center,
                    style: AppTypography.bodyMedium.copyWith(
                      color: isDark
                          ? AppColors.textSecondary
                          : theme.textTheme.bodyMedium?.color,
                    ),
                  ),
                ),
                const SizedBox(height: 32),

                // 방법 1
                _sectionTitle(theme, '방법 1: 우클릭으로 열기 (권장)'),
                AppSpacing.vGapMd,
                _stepTile(context, 1, 'Finder에서 StockTrader.app을 우클릭(또는 Control+클릭)한다'),
                _stepTile(context, 2, '메뉴에서 "열기"를 선택한다'),
                _stepTile(context, 3, '경고 대화상자에서 "열기" 버튼을 클릭한다'),
                _stepTile(context, 4, '이후부터는 정상적으로 실행된다'),

                const SizedBox(height: 28),

                // 방법 2
                _sectionTitle(theme, '방법 2: 시스템 설정에서 허용'),
                AppSpacing.vGapMd,
                _stepTile(context, 1, '시스템 설정 → 개인정보 보호 및 보안을 연다'),
                _stepTile(context, 2, '"확인 없이 열기" 버튼을 클릭한다'),

                const SizedBox(height: 36),

                // 확인 버튼
                Center(
                  child: SizedBox(
                    width: 240,
                    height: 48,
                    child: FilledButton(
                      onPressed: () async {
                        await markAsShown();
                        onDismiss();
                      },
                      child: const Text('확인'),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// 섹션 제목 위젯을 생성한다.
  Widget _sectionTitle(ThemeData theme, String text) {
    return Text(
      text,
      style: AppTypography.headlineMedium.copyWith(
        color: theme.colorScheme.onSurface,
      ),
    );
  }

  /// 단계별 안내 타일을 생성한다.
  Widget _stepTile(BuildContext context, int number, String text) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: AppColors.primary.withValues(alpha: isDark ? 0.2 : 0.12),
              borderRadius: BorderRadius.circular(14),
            ),
            alignment: Alignment.center,
            child: Text(
              '$number',
              style: AppTypography.labelLarge.copyWith(
                color: AppColors.primary,
              ),
            ),
          ),
          AppSpacing.hGapMd,
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Text(
                text,
                style: AppTypography.bodyMedium.copyWith(
                  color: isDark
                      ? AppColors.textPrimary
                      : theme.textTheme.bodyLarge?.color,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
