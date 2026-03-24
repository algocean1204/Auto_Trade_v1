import 'package:flutter/material.dart';

import '../../theme/app_spacing.dart';
import '../../theme/trading_colors.dart';

/// 검증 상태 표시 인디케이터 위젯이다.
/// 로딩, 성공, 실패, 미검증 4가지 상태를 시각적으로 표현한다.
class ValidationIndicator extends StatelessWidget {
  /// 검증 결과 (null=미검증, true=성공, false=실패)
  final bool? isValid;

  /// 검증 진행 중 여부
  final bool isLoading;

  /// 결과 메시지
  final String? message;

  const ValidationIndicator({
    super.key,
    this.isValid,
    this.isLoading = false,
    this.message,
  });

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;

    // 로딩 상태
    if (isLoading) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          if (message != null) ...[
            AppSpacing.hGapSm,
            Text(message!, style: TextStyle(color: tc.textSecondary)),
          ],
        ],
      );
    }

    // 미검증 상태
    if (isValid == null) return const SizedBox.shrink();

    // 성공 또는 실패 상태
    final color = isValid! ? tc.profit : tc.loss;
    final icon = isValid! ? Icons.check_circle : Icons.error;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 18, color: color),
        if (message != null) ...[
          AppSpacing.hGapSm,
          Flexible(
            child: Text(
              message!,
              style: TextStyle(color: color, fontSize: 13),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ],
    );
  }
}
