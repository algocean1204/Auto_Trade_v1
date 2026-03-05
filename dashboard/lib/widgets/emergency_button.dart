import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/emergency_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import 'confirmation_dialog.dart';

/// 앱바에 항상 표시되는 긴급 정지 버튼이다.
class EmergencyButton extends StatelessWidget {
  const EmergencyButton({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<EmergencyProvider>(
      builder: (context, provider, _) {
        final isStopped = provider.isEmergencyStopped;

        if (isStopped) {
          return _ResumeButton(provider: provider);
        } else {
          return _StopButton(provider: provider);
        }
      },
    );
  }
}

class _StopButton extends StatelessWidget {
  final EmergencyProvider provider;
  const _StopButton({required this.provider});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
      child: ElevatedButton.icon(
        style: ElevatedButton.styleFrom(
          backgroundColor: tc.loss.withValues(alpha: 0.15),
          foregroundColor: tc.loss,
          side: BorderSide(color: tc.loss.withValues(alpha: 0.4), width: 1),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
          ),
          textStyle: AppTypography.labelLarge.copyWith(
            color: tc.loss,
            fontSize: 12,
          ),
        ),
        onPressed: provider.isLoading
            ? null
            : () => _handleEmergencyStop(context),
        icon: const Icon(Icons.stop_circle_rounded, size: 16),
        label: const Text('STOP'),
      ),
    );
  }

  Future<void> _handleEmergencyStop(BuildContext context) async {
    final locale = context.read<LocaleProvider>();
    final confirmed = await ConfirmationDialog.show(
      context,
      title: locale.t('emergency_stop_title'),
      message: locale.t('emergency_stop_msg'),
      confirmLabel: locale.t('stop_trading'),
      cancelLabel: locale.t('cancel'),
      confirmColor: context.tc.loss,
      icon: Icons.stop_circle_rounded,
    );

    if (confirmed && context.mounted) {
      final t = context.read<LocaleProvider>().t;
      final success = await provider.triggerEmergencyStop(
        reason: 'Manual emergency stop',
      );
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              success
                  ? t('trading_stopped')
                  : '${t('failed')}: ${provider.error}',
            ),
            backgroundColor: success ? context.tc.loss : context.tc.warning,
          ),
        );
      }
    }
  }
}

class _ResumeButton extends StatelessWidget {
  final EmergencyProvider provider;
  const _ResumeButton({required this.provider});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
      child: ElevatedButton.icon(
        style: ElevatedButton.styleFrom(
          backgroundColor: tc.profit.withValues(alpha: 0.15),
          foregroundColor: tc.profit,
          side: BorderSide(color: tc.profit.withValues(alpha: 0.5), width: 1),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
          ),
          textStyle: AppTypography.labelLarge.copyWith(
            color: tc.profit,
            fontSize: 12,
          ),
        ),
        onPressed: provider.isLoading
            ? null
            : () => _handleResume(context),
        icon: const Icon(Icons.play_circle_rounded, size: 16),
        label: const Text('RESUME'),
      ),
    );
  }

  Future<void> _handleResume(BuildContext context) async {
    final locale = context.read<LocaleProvider>();
    final confirmed = await TypeToConfirmDialog.show(
      context,
      title: locale.t('resume_trading'),
      message: locale.t('resume_trading_msg'),
      confirmWord: 'RESUME',
      confirmLabel: locale.t('resume_trading'),
      confirmColor: context.tc.profit,
      icon: Icons.play_circle_rounded,
    );

    if (confirmed && context.mounted) {
      final t = context.read<LocaleProvider>().t;
      final success = await provider.resumeTrading();
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              success
                  ? t('trading_resumed')
                  : '${t('failed')}: ${provider.error}',
            ),
            backgroundColor: success ? context.tc.profit : context.tc.loss,
          ),
        );
      }
    }
  }
}
