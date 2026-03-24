import 'package:flutter/material.dart';

import '../../theme/app_spacing.dart';
import '../../theme/trading_colors.dart';

/// 접을 수 있는 단계별 설정 가이드 카드 위젯이다.
/// 번호가 매겨진 안내 목록과 선택적 외부 링크를 표시한다.
class SetupGuideCard extends StatelessWidget {
  /// 가이드 제목
  final String title;

  /// 단계별 안내 텍스트
  final List<String> steps;

  /// 외부 링크 URL (optional)
  final String? linkUrl;

  /// 링크 표시 텍스트
  final String? linkText;

  /// 기본 펼침 상태
  final bool initiallyExpanded;

  const SetupGuideCard({
    super.key,
    required this.title,
    required this.steps,
    this.linkUrl,
    this.linkText,
    this.initiallyExpanded = false,
  });

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final theme = Theme.of(context);

    return Card(
      margin: EdgeInsets.zero,
      color: tc.surface,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusMd,
        side: BorderSide(color: tc.surfaceBorder),
      ),
      clipBehavior: Clip.antiAlias,
      child: ExpansionTile(
        leading: Icon(Icons.help_outline, color: tc.info),
        title: Text(title, style: theme.textTheme.titleSmall),
        initiallyExpanded: initiallyExpanded,
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 번호 매긴 단계 목록
          for (int i = 0; i < steps.length; i++)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${i + 1}. ',
                    style: TextStyle(
                      color: tc.textSecondary,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  Expanded(
                    child: Text(
                      steps[i],
                      style: TextStyle(color: tc.textSecondary),
                    ),
                  ),
                ],
              ),
            ),
          // 선택적 링크 버튼
          if (linkUrl != null) ...[
            AppSpacing.vGapSm,
            TextButton.icon(
              onPressed: () {
                // url_launcher 없이 URL 텍스트만 표시 (의존성 최소화)
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text(linkUrl!)),
                );
              },
              icon: Icon(Icons.open_in_new, size: 16, color: tc.info),
              label: Text(
                linkText ?? linkUrl!,
                style: TextStyle(color: tc.info),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
