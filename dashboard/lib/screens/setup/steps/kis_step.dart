import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../providers/setup_provider.dart';
import '../../../theme/app_spacing.dart';
import '../../../theme/trading_colors.dart';
import '../../../widgets/setup/api_key_field.dart';
import '../../../widgets/setup/setup_guide_card.dart';
import '../../../widgets/setup/validation_indicator.dart';

/// 셋업 위저드 2단계: KIS OpenAPI 설정이다. 필수 단계이다.
class KisStep extends StatefulWidget {
  const KisStep({super.key});

  @override
  State<KisStep> createState() => _KisStepState();
}

class _KisStepState extends State<KisStep> {
  bool _realExpanded = false;

  /// 모의투자 검증 결과를 별도 키로 관리한다.
  static const _mockValidationKey = 'kis_mock';
  static const _realValidationKey = 'kis_real';

  /// 모의투자 연결 테스트를 실행한다.
  Future<void> _validateMock(SetupProvider provider) async {
    final config = provider.configData;
    await provider.validateService('kis', {
      'app_key': config['kis_mock_app_key'] as String? ?? '',
      'app_secret': config['kis_mock_app_secret'] as String? ?? '',
      'account_no': config['kis_mock_account_no'] as String? ?? '',
      'mock': 'true',
    }, storeAs: _mockValidationKey);
  }

  /// 실전투자 연결 테스트를 실행한다.
  Future<void> _validateReal(SetupProvider provider) async {
    final config = provider.configData;
    await provider.validateService('kis', {
      'app_key': config['kis_app_key'] as String? ?? '',
      'app_secret': config['kis_app_secret'] as String? ?? '',
      'account_no': config['kis_account_no'] as String? ?? '',
      'mock': 'false',
    }, storeAs: _realValidationKey);
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final theme = Theme.of(context);
    final provider = context.watch<SetupProvider>();
    final mockValidation = provider.validations[_mockValidationKey]
        ?? provider.validations['kis'];
    final realValidation = provider.validations[_realValidationKey];

    return SingleChildScrollView(
      padding: AppSpacing.paddingScreen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'KIS OpenAPI 설정',
            style: theme.textTheme.titleLarge?.copyWith(
              color: tc.textPrimary, fontWeight: FontWeight.bold,
            ),
          ),
          AppSpacing.vGapSm,
          Text(
            '한국투자증권 API를 연동합니다. 모의투자 설정은 필수입니다.',
            style: theme.textTheme.bodyMedium?.copyWith(color: tc.textSecondary),
          ),
          AppSpacing.vGapLg,
          const SetupGuideCard(
            title: 'KIS OpenAPI 키 발급 방법',
            steps: [
              '한국투자증권 계좌를 개설합니다 (증권사 앱 또는 지점 방문)',
              'KIS Developers(apiportal.koreainvestment.com)에 가입합니다',
              "'앱 등록' 메뉴에서 새 앱을 생성합니다",
              '발급된 App Key와 App Secret을 아래에 입력합니다',
              '계좌번호와 HTS ID도 함께 입력합니다',
            ],
            linkUrl: 'https://apiportal.koreainvestment.com',
            linkText: 'KIS Developers 바로가기',
          ),
          AppSpacing.vGapXl,
          _buildSectionHeader(theme, tc, '모의투자 설정 (필수)'),
          AppSpacing.vGapMd,
          ApiKeyField(
            label: '모의투자 App Key',
            hintText: 'PSxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
            value: provider.configData['kis_mock_app_key'] as String?,
            onChanged: (v) => provider.updateConfig('kis_mock_app_key', v),
          ),
          AppSpacing.vGapMd,
          ApiKeyField(
            label: '모의투자 App Secret',
            value: provider.configData['kis_mock_app_secret'] as String?,
            onChanged: (v) => provider.updateConfig('kis_mock_app_secret', v),
          ),
          AppSpacing.vGapMd,
          _buildTextField(
            context,
            label: '모의투자 계좌번호',
            hintText: '00000000-00',
            value: provider.configData['kis_mock_account_no'] as String?,
            onChanged: (v) => provider.updateConfig('kis_mock_account_no', v),
          ),
          AppSpacing.vGapLg,
          Row(
            children: [
              ElevatedButton.icon(
                onPressed: provider.isValidating(_mockValidationKey)
                    ? null
                    : () => _validateMock(provider),
                icon: const Icon(Icons.wifi_tethering, size: 18),
                label: const Text('연결 테스트'),
              ),
              AppSpacing.hGapMd,
              if (mockValidation != null ||
                  provider.isValidating(_mockValidationKey))
                Expanded(
                  child: ValidationIndicator(
                    isValid: mockValidation?.valid,
                    isLoading: provider.isValidating(_mockValidationKey),
                    message: mockValidation?.message ?? '검증 중...',
                  ),
                ),
            ],
          ),
          AppSpacing.vGapXl,
          Card(
            color: tc.surface,
            shape: RoundedRectangleBorder(
              borderRadius: AppSpacing.borderRadiusMd,
              side: BorderSide(color: tc.surfaceBorder),
            ),
            clipBehavior: Clip.antiAlias,
            child: ExpansionTile(
              title: Text('실전투자 설정 (선택사항)',
                style: theme.textTheme.titleSmall?.copyWith(color: tc.textPrimary)),
              leading: Icon(Icons.shield_outlined, color: tc.warning),
              initiallyExpanded: _realExpanded,
              onExpansionChanged: (v) => setState(() => _realExpanded = v),
              childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ApiKeyField(
                  label: '실전 App Key',
                  value: provider.configData['kis_app_key'] as String?,
                  onChanged: (v) => provider.updateConfig('kis_app_key', v),
                ),
                AppSpacing.vGapMd,
                ApiKeyField(
                  label: '실전 App Secret',
                  value: provider.configData['kis_app_secret'] as String?,
                  onChanged: (v) => provider.updateConfig('kis_app_secret', v),
                ),
                AppSpacing.vGapMd,
                _buildTextField(
                  context,
                  label: '실전 계좌번호',
                  hintText: '00000000-00',
                  value: provider.configData['kis_account_no'] as String?,
                  onChanged: (v) => provider.updateConfig('kis_account_no', v),
                ),
                AppSpacing.vGapLg,
                Row(
                  children: [
                    ElevatedButton.icon(
                      onPressed: provider.isValidating(_realValidationKey)
                          ? null
                          : () => _validateReal(provider),
                      icon: const Icon(Icons.verified_user, size: 18),
                      label: const Text('실전 연결 테스트'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: tc.warning.withValues(alpha: 0.15),
                        foregroundColor: tc.warning,
                      ),
                    ),
                    AppSpacing.hGapMd,
                    if (realValidation != null ||
                        provider.isValidating(_realValidationKey))
                      Expanded(
                        child: ValidationIndicator(
                          isValid: realValidation?.valid,
                          isLoading:
                              provider.isValidating(_realValidationKey),
                          message:
                              realValidation?.message ?? '검증 중...',
                        ),
                      ),
                  ],
                ),
              ],
            ),
          ),
          AppSpacing.vGapXl,
          _buildSectionHeader(theme, tc, 'HTS ID (공통)'),
          AppSpacing.vGapMd,
          _buildTextField(
            context,
            label: 'HTS ID',
            hintText: '영문으로 입력 (예: myid123)',
            value: provider.configData['kis_hts_id'] as String?,
            onChanged: (v) => provider.updateConfig('kis_hts_id', v),
          ),
          AppSpacing.vGapXxl,
        ],
      ),
    );
  }

  /// 섹션 헤더를 빌드한다.
  Widget _buildSectionHeader(ThemeData theme, TradingColors tc, String title) {
    return Text(
      title,
      style: theme.textTheme.titleSmall?.copyWith(
        color: tc.textPrimary,
        fontWeight: FontWeight.w600,
      ),
    );
  }

  /// 일반 텍스트 입력 필드를 빌드한다.
  Widget _buildTextField(
    BuildContext context, {
    required String label,
    String? hintText,
    String? value,
    required ValueChanged<String> onChanged,
  }) {
    return TextFormField(
      initialValue: value,
      onChanged: onChanged,
      decoration: InputDecoration(
        labelText: label,
        hintText: hintText,
      ),
    );
  }
}
