import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/locale_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

/// 빈 상태 표시 위젯이다.
class EmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? subtitle;
  final String? actionLabel;
  final VoidCallback? onAction;

  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
    this.actionLabel,
    this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              size: 48,
              color: context.tc.textTertiary,
            ),
            AppSpacing.vGapLg,
            Text(
              title,
              style: AppTypography.headlineMedium,
              textAlign: TextAlign.center,
            ),
            if (subtitle != null) ...[
              AppSpacing.vGapSm,
              Text(
                subtitle ?? '',
                style: AppTypography.bodyMedium,
                textAlign: TextAlign.center,
              ),
            ],
            if (actionLabel != null && onAction != null) ...[
              AppSpacing.vGapXxl,
              ElevatedButton(
                onPressed: onAction,
                child: Text(actionLabel ?? ''),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// 에러 상태 표시 위젯이다.
class ErrorState extends StatelessWidget {
  final String message;
  final String? title;
  final String? retryLabel;
  final VoidCallback? onRetry;

  const ErrorState({
    super.key,
    required this.message,
    this.title,
    this.retryLabel,
    this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.read<LocaleProvider>().t;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.cloud_off_rounded,
              size: 48,
              color: context.tc.textTertiary,
            ),
            AppSpacing.vGapLg,
            Text(
              title ?? t('connection_error'),
              style: AppTypography.headlineMedium,
            ),
            AppSpacing.vGapSm,
            Text(
              message,
              style: AppTypography.bodyMedium,
              textAlign: TextAlign.center,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
            ),
            if (onRetry != null) ...[
              AppSpacing.vGapXxl,
              ElevatedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh_rounded, size: 18),
                label: Text(retryLabel ?? t('retry')),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
