import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../providers/locale_provider.dart';
import '../../../theme/app_spacing.dart';
import '../../../theme/trading_colors.dart';

/// 셋업 위저드 1단계: 환영 및 언어 선택이다.
class WelcomeStep extends StatelessWidget {
  const WelcomeStep({super.key});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final theme = Theme.of(context);
    final locale = context.watch<LocaleProvider>();

    return SingleChildScrollView(
      padding: AppSpacing.paddingScreen,
      child: Column(
        children: [
          AppSpacing.vGapXxl,
          // 아이콘
          Icon(
            Icons.auto_graph_rounded,
            size: 72,
            color: tc.primary,
          ),
          AppSpacing.vGapXl,
          // 제목
          Text(
            'AI 주식 자동매매 시스템',
            style: theme.textTheme.headlineMedium?.copyWith(
              color: tc.textPrimary,
              fontWeight: FontWeight.bold,
            ),
            textAlign: TextAlign.center,
          ),
          AppSpacing.vGapMd,
          // 부제
          Text(
            '설정을 시작합니다. 몇 가지 API 키를 입력하면\n바로 사용할 수 있습니다.',
            style: theme.textTheme.bodyLarge?.copyWith(
              color: tc.textSecondary,
            ),
            textAlign: TextAlign.center,
          ),
          AppSpacing.vGapXxl,
          // 언어 토글
          Card(
            color: tc.surface,
            shape: RoundedRectangleBorder(
              borderRadius: AppSpacing.borderRadiusMd,
              side: BorderSide(color: tc.surfaceBorder),
            ),
            child: Padding(
              padding: AppSpacing.paddingCard,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    locale.isKorean ? '언어 설정' : 'Language',
                    style: theme.textTheme.titleSmall?.copyWith(
                      color: tc.textPrimary,
                    ),
                  ),
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'ko', label: Text('한국어')),
                      ButtonSegment(value: 'en', label: Text('English')),
                    ],
                    selected: {locale.locale},
                    onSelectionChanged: (selected) {
                      locale.setLocale(selected.first);
                    },
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
