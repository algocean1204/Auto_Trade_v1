import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../providers/setup_provider.dart';
import '../../../theme/app_spacing.dart';
import '../../../theme/trading_colors.dart';
import '../../../widgets/setup/api_key_field.dart';
import '../../../widgets/setup/validation_indicator.dart';

/// 셋업 위저드 6단계: 추가 API 키 입력이다. 모든 항목이 선택사항이다.
/// FRED, Finnhub, Reddit API 키를 선택적으로 입력받고 연결 테스트를 수행한다.
class OptionalKeysStep extends StatelessWidget {
  const OptionalKeysStep({super.key});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final theme = Theme.of(context);
    final provider = context.watch<SetupProvider>();

    return SingleChildScrollView(
      padding: AppSpacing.paddingScreen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 단계 제목
          Text(
            '추가 API 키 (선택)',
            style: theme.textTheme.titleLarge?.copyWith(
              color: tc.textPrimary,
              fontWeight: FontWeight.bold,
            ),
          ),
          AppSpacing.vGapSm,
          Text(
            '아래 서비스의 API 키가 없어도 기본 기능은 사용할 수 있습니다.',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: tc.textSecondary,
            ),
          ),
          AppSpacing.vGapXl,

          // FRED API 섹션
          _buildExpandableSection(
            context: context,
            tc: tc,
            theme: theme,
            icon: Icons.bar_chart,
            title: 'FRED API',
            subtitle: '경제 지표',
            validationKey: 'fred',
            provider: provider,
            children: [
              ApiKeyField(
                label: 'FRED API Key',
                hintText: 'FRED(fred.stlouisfed.org)에서 무료 발급',
                value: provider.configData['fred_api_key'] as String?,
                onChanged: (v) => provider.updateConfig('fred_api_key', v),
              ),
              AppSpacing.vGapMd,
              _buildValidateButton(
                context: context,
                provider: provider,
                service: 'fred',
                credentials: {
                  'api_key': provider.configData['fred_api_key'] as String? ?? '',
                },
                label: 'FRED 연결 테스트',
              ),
            ],
          ),
          AppSpacing.vGapMd,

          // Finnhub 섹션
          _buildExpandableSection(
            context: context,
            tc: tc,
            theme: theme,
            icon: Icons.candlestick_chart,
            title: 'Finnhub',
            subtitle: '주가 데이터',
            validationKey: 'finnhub',
            provider: provider,
            children: [
              ApiKeyField(
                label: 'Finnhub API Key',
                hintText: 'Finnhub(finnhub.io)에서 무료 발급',
                value: provider.configData['finnhub_api_key'] as String?,
                onChanged: (v) => provider.updateConfig('finnhub_api_key', v),
              ),
              AppSpacing.vGapMd,
              _buildValidateButton(
                context: context,
                provider: provider,
                service: 'finnhub',
                credentials: {
                  'api_key':
                      provider.configData['finnhub_api_key'] as String? ?? '',
                },
                label: 'Finnhub 연결 테스트',
              ),
            ],
          ),
          AppSpacing.vGapMd,

          // Reddit 섹션
          _buildExpandableSection(
            context: context,
            tc: tc,
            theme: theme,
            icon: Icons.forum,
            title: 'Reddit',
            subtitle: '시장 심리',
            validationKey: 'reddit',
            provider: provider,
            children: [
              ApiKeyField(
                label: 'Reddit Client ID',
                hintText: 'Reddit App(reddit.com/prefs/apps)에서 발급',
                value: provider.configData['reddit_client_id'] as String?,
                onChanged: (v) => provider.updateConfig('reddit_client_id', v),
              ),
              AppSpacing.vGapMd,
              ApiKeyField(
                label: 'Reddit Client Secret',
                value:
                    provider.configData['reddit_client_secret'] as String?,
                onChanged: (v) =>
                    provider.updateConfig('reddit_client_secret', v),
              ),
              AppSpacing.vGapMd,
              _buildValidateButton(
                context: context,
                provider: provider,
                service: 'reddit',
                credentials: {
                  'client_id':
                      provider.configData['reddit_client_id'] as String? ?? '',
                  'client_secret':
                      provider.configData['reddit_client_secret'] as String? ??
                          '',
                },
                label: 'Reddit 연결 테스트',
              ),
            ],
          ),
          AppSpacing.vGapXxl,

          // 모두 건너뛰기 버튼
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              onPressed: () => _skipAll(provider),
              child: const Text('모두 건너뛰기'),
            ),
          ),
          AppSpacing.vGapXl,
        ],
      ),
    );
  }

  /// 모든 선택 항목을 빈 값으로 설정하고 넘어간다.
  void _skipAll(SetupProvider provider) {
    provider.nextStep();
  }

  /// 연결 테스트 버튼 + 결과 인디케이터를 빌드한다.
  /// 각 서비스별로 독립된 로딩 상태를 사용한다.
  Widget _buildValidateButton({
    required BuildContext context,
    required SetupProvider provider,
    required String service,
    required Map<String, String> credentials,
    required String label,
  }) {
    final validation = provider.validations[service];
    final isValidating = provider.isValidating(service);

    return Row(
      children: [
        ElevatedButton.icon(
          onPressed: isValidating
              ? null
              : () => provider.validateService(service, credentials),
          icon: const Icon(Icons.wifi_tethering, size: 18),
          label: Text(label),
        ),
        AppSpacing.hGapMd,
        if (validation != null || isValidating)
          Expanded(
            child: ValidationIndicator(
              isValid: validation?.valid,
              isLoading: isValidating,
              message: validation?.message ?? '검증 중...',
            ),
          ),
      ],
    );
  }

  /// 접을 수 있는 API 키 입력 섹션을 빌드한다.
  Widget _buildExpandableSection({
    required BuildContext context,
    required TradingColors tc,
    required ThemeData theme,
    required IconData icon,
    required String title,
    required String subtitle,
    required String validationKey,
    required SetupProvider provider,
    required List<Widget> children,
  }) {
    final validation = provider.validations[validationKey];
    // 검증 성공 시 아이콘 색상을 변경한다
    final iconColor = validation?.valid == true ? tc.profit : tc.info;

    return Card(
      margin: EdgeInsets.zero,
      color: tc.surface,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusMd,
        side: BorderSide(color: tc.surfaceBorder),
      ),
      clipBehavior: Clip.antiAlias,
      child: ExpansionTile(
        leading: Icon(icon, color: iconColor),
        title: Row(
          children: [
            Text(title, style: theme.textTheme.titleSmall),
            AppSpacing.hGapSm,
            Text(
              subtitle,
              style: TextStyle(color: tc.textTertiary, fontSize: 12),
            ),
            if (validation?.valid == true) ...[
              AppSpacing.hGapSm,
              Icon(Icons.check_circle, size: 16, color: tc.profit),
            ],
          ],
        ),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: children,
      ),
    );
  }
}
