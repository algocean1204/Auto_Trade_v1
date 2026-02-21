import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/locale_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

/// macOS 스타일 확인 다이얼로그이다.
class ConfirmationDialog extends StatelessWidget {
  final String title;
  final String message;
  final String confirmLabel;
  final String cancelLabel;
  final Color? confirmColor;
  final IconData? icon;

  const ConfirmationDialog({
    super.key,
    required this.title,
    required this.message,
    this.confirmLabel = 'Confirm',
    this.cancelLabel = 'Cancel',
    this.confirmColor,
    this.icon,
  });

  static Future<bool> show(
    BuildContext context, {
    required String title,
    required String message,
    String? confirmLabel,
    String? cancelLabel,
    Color? confirmColor,
    IconData? icon,
  }) async {
    final locale = context.read<LocaleProvider>();
    final result = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) => ConfirmationDialog(
        title: title,
        message: message,
        confirmLabel: confirmLabel ?? locale.t('confirm'),
        cancelLabel: cancelLabel ?? locale.t('cancel'),
        confirmColor: confirmColor,
        icon: icon,
      ),
    );
    return result ?? false;
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final color = confirmColor ?? tc.primary;

    return AlertDialog(
      backgroundColor: tc.surfaceElevated,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusXl,
        side: BorderSide(
          color: tc.surfaceBorder.withValues(alpha: 0.5),
          width: 1,
        ),
      ),
      contentPadding: const EdgeInsets.fromLTRB(24, 20, 24, 0),
      actionsPadding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.12),
                borderRadius: AppSpacing.borderRadiusFull,
              ),
              child: Icon(icon, color: color, size: 28),
            ),
            AppSpacing.vGapLg,
          ],
          Text(
            title,
            style: AppTypography.displaySmall,
            textAlign: TextAlign.center,
          ),
          AppSpacing.vGapMd,
          Text(
            message,
            style: AppTypography.bodyMedium,
            textAlign: TextAlign.center,
          ),
        ],
      ),
      actions: [
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: Text(cancelLabel),
              ),
            ),
            AppSpacing.hGapMd,
            Expanded(
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: color,
                ),
                onPressed: () => Navigator.of(context).pop(true),
                child: Text(confirmLabel),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// 긴급 정지용 텍스트 입력 확인 다이얼로그이다.
class TypeToConfirmDialog extends StatefulWidget {
  final String title;
  final String message;
  final String confirmWord;
  final String confirmLabel;
  final String cancelLabel;
  final Color? confirmColor;
  final IconData? icon;

  const TypeToConfirmDialog({
    super.key,
    required this.title,
    required this.message,
    required this.confirmWord,
    this.confirmLabel = 'Confirm',
    this.cancelLabel = 'Cancel',
    this.confirmColor,
    this.icon,
  });

  static Future<bool> show(
    BuildContext context, {
    required String title,
    required String message,
    required String confirmWord,
    String? confirmLabel,
    String? cancelLabel,
    Color? confirmColor,
    IconData? icon,
  }) async {
    final locale = context.read<LocaleProvider>();
    final result = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) => TypeToConfirmDialog(
        title: title,
        message: message,
        confirmWord: confirmWord,
        confirmLabel: confirmLabel ?? locale.t('confirm'),
        cancelLabel: cancelLabel ?? locale.t('cancel'),
        confirmColor: confirmColor,
        icon: icon,
      ),
    );
    return result ?? false;
  }

  @override
  State<TypeToConfirmDialog> createState() => _TypeToConfirmDialogState();
}

class _TypeToConfirmDialogState extends State<TypeToConfirmDialog> {
  final TextEditingController _controller = TextEditingController();
  bool _isMatch = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final color = widget.confirmColor ?? tc.loss;
    final t = context.read<LocaleProvider>().t;

    return AlertDialog(
      backgroundColor: tc.surfaceElevated,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusXl,
        side: BorderSide(color: color.withValues(alpha: 0.4), width: 1),
      ),
      contentPadding: const EdgeInsets.fromLTRB(24, 20, 24, 0),
      actionsPadding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (widget.icon != null) ...[
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.12),
                shape: BoxShape.circle,
              ),
              child: Icon(widget.icon, color: color, size: 28),
            ),
            AppSpacing.vGapLg,
          ],
          Text(
            widget.title,
            style: AppTypography.displaySmall,
            textAlign: TextAlign.center,
          ),
          AppSpacing.vGapMd,
          Text(
            widget.message,
            style: AppTypography.bodyMedium,
            textAlign: TextAlign.center,
          ),
          AppSpacing.vGapLg,
          Text(
            t('type_to_confirm').replaceAll('{word}', widget.confirmWord),
            style: AppTypography.bodySmall,
          ),
          AppSpacing.vGapSm,
          TextField(
            controller: _controller,
            autofocus: true,
            style: AppTypography.numberSmall,
            decoration: InputDecoration(
              hintText: widget.confirmWord,
              border: OutlineInputBorder(
                borderRadius: AppSpacing.borderRadiusMd,
                borderSide: BorderSide(color: tc.surfaceBorder),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: AppSpacing.borderRadiusMd,
                borderSide: BorderSide(color: color, width: 1.5),
              ),
            ),
            onChanged: (value) {
              setState(() {
                _isMatch = value == widget.confirmWord;
              });
            },
          ),
        ],
      ),
      actions: [
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: Text(widget.cancelLabel),
              ),
            ),
            AppSpacing.hGapMd,
            Expanded(
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: _isMatch ? color : tc.surfaceBorder,
                ),
                onPressed: _isMatch
                    ? () => Navigator.of(context).pop(true)
                    : null,
                child: Text(widget.confirmLabel),
              ),
            ),
          ],
        ),
      ],
    );
  }
}
