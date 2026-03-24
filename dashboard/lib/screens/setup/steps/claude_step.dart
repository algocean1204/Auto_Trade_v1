import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../providers/setup_provider.dart';
import '../../../theme/app_spacing.dart';
import '../../../theme/trading_colors.dart';
import '../../../widgets/setup/api_key_field.dart';
import '../../../widgets/setup/validation_indicator.dart';

/// 셋업 위저드 3단계: Claude AI 모드 선택이다. 필수 단계이다.
class ClaudeStep extends StatelessWidget {
  const ClaudeStep({super.key});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final theme = Theme.of(context);
    final provider = context.watch<SetupProvider>();
    final selectedMode = provider.configData['claude_mode'] as String? ?? 'oauth';
    final validation = provider.validations['claude'];

    return SingleChildScrollView(
      padding: AppSpacing.paddingScreen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 단계 제목
          Text(
            'Claude AI 설정',
            style: theme.textTheme.titleLarge?.copyWith(
              color: tc.textPrimary,
              fontWeight: FontWeight.bold,
            ),
          ),
          AppSpacing.vGapSm,
          Text(
            'AI 분석에 사용할 Claude 연동 방식을 선택합니다.',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: tc.textSecondary,
            ),
          ),
          AppSpacing.vGapXl,

          // OAuth 모드 카드
          _ModeCard(
            icon: Icons.key,
            title: 'OAuth 모드 (Claude Code 사용자)',
            description:
                'Claude Code가 설치된 경우 자동으로 연동됩니다.\n추가 설정이 필요 없습니다.',
            isSelected: selectedMode == 'oauth',
            onTap: () => provider.updateConfig('claude_mode', 'oauth'),
          ),
          AppSpacing.vGapMd,

          // OAuth 검증 버튼 (OAuth 모드 선택 시)
          if (selectedMode == 'oauth') ...[
            Padding(
              padding: const EdgeInsets.only(left: AppSpacing.lg),
              child: Row(
                children: [
                  ElevatedButton.icon(
                    onPressed: provider.isValidating('claude')
                        ? null
                        : () => provider.validateService('claude', {
                              'mode': 'oauth',
                            }),
                    icon: const Icon(Icons.verified_user, size: 18),
                    label: const Text('Claude Code 확인'),
                  ),
                  AppSpacing.hGapMd,
                  if (validation != null ||
                      provider.isValidating('claude'))
                    ValidationIndicator(
                      isValid: validation?.valid,
                      isLoading: provider.isValidating('claude'),
                      message: validation?.message ?? '확인 중...',
                    ),
                ],
              ),
            ),
            AppSpacing.vGapMd,
          ],

          // API Key 모드 카드
          _ModeCard(
            icon: Icons.vpn_key,
            title: 'API Key 모드',
            description: 'Anthropic API 키를 직접 입력합니다.',
            isSelected: selectedMode == 'api_key',
            onTap: () => provider.updateConfig('claude_mode', 'api_key'),
          ),
          AppSpacing.vGapMd,

          // API Key 입력 필드 (API Key 모드 선택 시)
          if (selectedMode == 'api_key') ...[
            Padding(
              padding: const EdgeInsets.only(left: AppSpacing.lg),
              child: ApiKeyField(
                label: 'Claude API Key',
                hintText: 'sk-ant-로 시작하는 API 키',
                value: provider.configData['claude_api_key'] as String?,
                onChanged: (v) => provider.updateConfig('claude_api_key', v),
                onValidate: () => provider.validateService('claude', {
                  'mode': 'api_key',
                  'api_key':
                      provider.configData['claude_api_key'] as String? ?? '',
                }),
                isValidating: provider.isValidating('claude'),
                isValid: validation?.valid,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// 모드 선택 카드 위젯이다. 라디오 선택 스타일을 제공한다.
class _ModeCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String description;
  final bool isSelected;
  final VoidCallback onTap;

  const _ModeCard({
    required this.icon,
    required this.title,
    required this.description,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final theme = Theme.of(context);

    return Card(
      margin: EdgeInsets.zero,
      color: isSelected ? tc.primary.withValues(alpha: 0.08) : tc.surface,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusMd,
        side: BorderSide(
          color: isSelected ? tc.primary : tc.surfaceBorder,
          width: isSelected ? 1.5 : 1.0,
        ),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: AppSpacing.borderRadiusMd,
        child: Padding(
          padding: AppSpacing.paddingCard,
          child: Row(
            children: [
              Icon(icon, color: isSelected ? tc.primary : tc.textTertiary),
              AppSpacing.hGapLg,
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: theme.textTheme.titleSmall?.copyWith(
                        color: tc.textPrimary,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    AppSpacing.vGapXs,
                    Text(
                      description,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: tc.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              Radio<bool>(
                value: true,
                groupValue: isSelected,
                onChanged: (_) => onTap(),
                activeColor: tc.primary,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
