import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../providers/setup_provider.dart';
import '../../../theme/app_spacing.dart';
import '../../../theme/trading_colors.dart';
import '../../../widgets/setup/api_key_field.dart';
import '../../../widgets/setup/setup_guide_card.dart';
import '../../../widgets/setup/validation_indicator.dart';

/// 셋업 위저드 4단계: 텔레그램 알림 설정이다. 선택 단계이다.
/// 최대 5명의 수신자를 동적으로 추가/삭제할 수 있다.
class TelegramStep extends StatefulWidget {
  const TelegramStep({super.key});

  @override
  State<TelegramStep> createState() => _TelegramStepState();
}

class _TelegramStepState extends State<TelegramStep> {
  /// 현재 수신자 수이다. 최소 1, 최대 5이다.
  int _recipientCount = 1;

  /// 최대 수신자 수이다.
  static const int _maxRecipients = 5;

  /// 수신자 인덱스(0-based)에 대응하는 config 키를 반환한다.
  String _tokenKey(int index) =>
      index == 0 ? 'telegram_bot_token' : 'telegram_bot_token_${index + 1}';

  String _chatIdKey(int index) =>
      index == 0 ? 'telegram_chat_id' : 'telegram_chat_id_${index + 1}';

  /// 검증 결과 저장용 키이다. 수신자별 독립 검증을 위해 사용한다.
  String _validationKey(int index) =>
      index == 0 ? 'telegram' : 'telegram_${index + 1}';

  /// 특정 수신자의 테스트 메시지를 전송한다.
  Future<void> _sendTest(SetupProvider provider, int index) async {
    final config = provider.configData;
    final token = config[_tokenKey(index)] as String? ?? '';
    final chatId = config[_chatIdKey(index)] as String? ?? '';

    await provider.validateService(
      'telegram',
      {'bot_token': token, 'chat_id': chatId},
      storeAs: _validationKey(index),
    );
  }

  /// 수신자를 추가한다.
  void _addRecipient() {
    if (_recipientCount < _maxRecipients) {
      setState(() => _recipientCount++);
    }
  }

  /// 수신자를 삭제한다. 삭제된 수신자 이후의 데이터를 한 칸씩 앞으로 이동한다.
  void _removeRecipient(SetupProvider provider, int index) {
    if (_recipientCount <= 1) return;

    // 삭제된 인덱스 이후의 수신자 데이터를 한 칸씩 앞으로 이동한다
    for (int i = index; i < _recipientCount - 1; i++) {
      final nextToken = provider.configData[_tokenKey(i + 1)] as String? ?? '';
      final nextChatId = provider.configData[_chatIdKey(i + 1)] as String? ?? '';
      provider.updateConfig(_tokenKey(i), nextToken);
      provider.updateConfig(_chatIdKey(i), nextChatId);
    }

    // 마지막 수신자 데이터를 비운다
    final lastIdx = _recipientCount - 1;
    provider.updateConfig(_tokenKey(lastIdx), '');
    provider.updateConfig(_chatIdKey(lastIdx), '');

    setState(() => _recipientCount--);
  }

  /// 수신자 카드 위젯을 빌드한다.
  Widget _buildRecipientCard(
    BuildContext context,
    SetupProvider provider,
    TradingColors tc,
    ThemeData theme,
    int index,
  ) {
    final validation = provider.validations[_validationKey(index)];
    final isFirst = index == 0;
    final label = isFirst ? '기본 수신자' : '수신자 ${index + 1}';

    return Card(
      color: tc.surface,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusMd,
        side: BorderSide(color: tc.surfaceBorder),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 수신자 헤더 + 삭제 버튼
            Row(
              children: [
                Icon(Icons.person, size: 18, color: tc.primary),
                const SizedBox(width: 8),
                Text(
                  label,
                  style: theme.textTheme.titleSmall?.copyWith(
                    color: tc.textPrimary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const Spacer(),
                if (!isFirst)
                  IconButton(
                    onPressed: () => _removeRecipient(provider, index),
                    icon: Icon(Icons.close, size: 18, color: tc.loss),
                    tooltip: '수신자 삭제',
                    constraints: const BoxConstraints(
                      minWidth: 32,
                      minHeight: 32,
                    ),
                    padding: EdgeInsets.zero,
                  ),
              ],
            ),
            AppSpacing.vGapMd,

            // 봇 토큰 입력
            ApiKeyField(
              label: '봇 토큰',
              hintText: '0123456789:ABCdefGHIjklMNOpqrSTUvwxYZ',
              value: provider.configData[_tokenKey(index)] as String?,
              onChanged: (v) => provider.updateConfig(_tokenKey(index), v),
            ),
            AppSpacing.vGapMd,

            // 채팅 ID 입력
            TextFormField(
              initialValue: provider.configData[_chatIdKey(index)] as String?,
              onChanged: (v) => provider.updateConfig(_chatIdKey(index), v),
              decoration: const InputDecoration(
                labelText: '채팅 ID',
                hintText: '숫자로 된 Chat ID (예: 123456789)',
              ),
              keyboardType: TextInputType.number,
            ),
            AppSpacing.vGapMd,

            // 테스트 메시지 전송 버튼 + 결과
            Row(
              children: [
                ElevatedButton.icon(
                  onPressed: provider.isValidating(_validationKey(index))
                      ? null
                      : () => _sendTest(provider, index),
                  icon: const Icon(Icons.send, size: 16),
                  label: const Text('테스트 전송'),
                ),
                AppSpacing.hGapMd,
                if (validation != null ||
                    provider.isValidating(_validationKey(index)))
                  Expanded(
                    child: ValidationIndicator(
                      isValid: validation?.valid,
                      isLoading:
                          provider.isValidating(_validationKey(index)),
                      message: validation?.message ?? '전송 중...',
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final theme = Theme.of(context);
    final provider = context.watch<SetupProvider>();
    final skipped = provider.configData['telegram_skip'] as bool? ?? false;

    return SingleChildScrollView(
      padding: AppSpacing.paddingScreen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 단계 제목
          Text(
            '텔레그램 알림 설정 (선택)',
            style: theme.textTheme.titleLarge?.copyWith(
              color: tc.textPrimary,
              fontWeight: FontWeight.bold,
            ),
          ),
          AppSpacing.vGapSm,
          Text(
            '매매 알림을 텔레그램으로 받을 수 있습니다. 최대 $_maxRecipients명까지 수신자를 추가할 수 있습니다.',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: tc.textSecondary,
            ),
          ),
          AppSpacing.vGapLg,

          // 스킵 토글
          Card(
            color: tc.surface,
            shape: RoundedRectangleBorder(
              borderRadius: AppSpacing.borderRadiusMd,
              side: BorderSide(color: tc.surfaceBorder),
            ),
            child: CheckboxListTile(
              title: Text(
                '텔레그램 알림을 사용하지 않습니다',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: tc.textPrimary,
                ),
              ),
              value: skipped,
              onChanged: (v) =>
                  provider.updateConfig('telegram_skip', v ?? false),
              activeColor: tc.primary,
              shape: RoundedRectangleBorder(
                borderRadius: AppSpacing.borderRadiusMd,
              ),
            ),
          ),
          AppSpacing.vGapLg,

          // 텔레그램 설정 영역 (스킵하지 않을 때만 표시)
          if (!skipped) ...[
            // 봇 생성 가이드
            const SetupGuideCard(
              title: '텔레그램 봇 생성 방법',
              steps: [
                '텔레그램에서 @BotFather를 검색합니다',
                '/newbot 명령으로 봇을 생성합니다',
                '발급된 봇 토큰을 아래에 입력합니다',
                '봇과 대화를 시작한 후 Chat ID를 확인합니다',
              ],
              initiallyExpanded: true,
            ),
            AppSpacing.vGapXl,

            // 수신자 카드 목록
            for (int i = 0; i < _recipientCount; i++) ...[
              _buildRecipientCard(context, provider, tc, theme, i),
              AppSpacing.vGapMd,
            ],

            // 수신자 추가 버튼
            if (_recipientCount < _maxRecipients)
              OutlinedButton.icon(
                onPressed: _addRecipient,
                icon: const Icon(Icons.add, size: 18),
                label: Text('수신자 추가 ($_recipientCount/$_maxRecipients)'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: tc.primary,
                  side: BorderSide(color: tc.primary.withValues(alpha: 0.5)),
                  minimumSize: const Size(double.infinity, 44),
                ),
              ),
          ],
          AppSpacing.vGapXxl,
        ],
      ),
    );
  }
}
