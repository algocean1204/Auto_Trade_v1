import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/setup_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../theme/trading_colors.dart';
import '../widgets/glass_card.dart';
import '../widgets/section_header.dart';
import '../widgets/setup/api_key_field.dart';
import '../widgets/setup/validation_indicator.dart';
import '../animations/animation_utils.dart';

/// 설정 화면 7번째 탭: API 키 관리이다.
/// 위저드에서 입력한 API 키를 편집 모드로 재설정할 수 있다.
/// 텔레그램 수신자를 동적으로 추가/삭제할 수 있다.
class ApiKeysTab extends StatefulWidget {
  const ApiKeysTab({super.key});

  @override
  State<ApiKeysTab> createState() => _ApiKeysTabState();
}

class _ApiKeysTabState extends State<ApiKeysTab> {
  final Map<String, String> _values = {};
  bool _isSaving = false;
  String? _message;

  /// 텔레그램 수신자 수이다. 최소 1, 최대 5이다.
  int _telegramRecipientCount = 1;
  static const int _maxTelegramRecipients = 5;

  /// Claude 모드 선택값이다. 'oauth', 'api_key', 'local' 중 하나이다.
  /// 위저드에서는 'oauth'/'api_key', 레거시는 'local'/'api' 형식이다.
  String _claudeMode = 'local';

  /// KIS 필드 정의이다. (key, 라벨, 힌트)
  static const _kisFields = <(String, String, String)>[
    ('kis_mock_app_key', 'App Key (모의)', 'App Key를 입력하세요'),
    ('kis_mock_app_secret', 'App Secret (모의)', 'App Secret을 입력하세요'),
    ('kis_mock_account_no', '계좌번호 (모의)', '12345678-01'),
    ('kis_app_key', 'App Key (실전)', 'App Key를 입력하세요'),
    ('kis_app_secret', 'App Secret (실전)', 'App Secret을 입력하세요'),
    ('kis_account_no', '계좌번호 (실전)', '12345678-01'),
    ('kis_hts_id', 'HTS ID', 'HTS 사용자 ID'),
  ];

  /// 추가 API 필드 정의이다. (key, 라벨, 힌트)
  static const _extraFields = <(String, String, String)>[
    ('fred_api_key', 'FRED API Key', 'FRED에서 발급받은 키'),
    ('finnhub_api_key', 'Finnhub API Key', 'Finnhub에서 발급받은 키'),
    ('reddit_client_id', 'Reddit Client ID', 'Reddit 앱 ID'),
    ('reddit_client_secret', 'Reddit Client Secret', 'Reddit 앱 Secret'),
  ];

  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final provider = context.read<SetupProvider>();
      // 서버가 꺼져있어도 loadStatus 실패를 무시한다
      try { await provider.loadStatus(); } catch (_) {}
      await provider.loadCurrentConfig();
      if (!mounted) return;
      _applyCurrentConfig(provider.currentConfig);
    });
  }

  /// 서버에서 받은 마스킹된 현재 설정값을 필드에 반영한다.
  void _applyCurrentConfig(Map<String, String> config) {
    if (_loaded) return;
    _loaded = true;
    setState(() {
      for (final entry in config.entries) {
        if (entry.value.isNotEmpty) {
          _values[entry.key] = entry.value;
        }
      }
      // 텔레그램 수신자 수를 카운트한다
      for (int i = 1; i < _maxTelegramRecipients; i++) {
        final key = 'telegram_bot_token_${i + 1}';
        if (config[key]?.isNotEmpty == true) {
          _telegramRecipientCount = i + 1;
        }
      }
      // Claude 모드를 반영한다 — 레거시 'api'는 'api_key'로 정규화한다
      final mode = config['claude_mode'] ?? '';
      if (mode.isNotEmpty && mode != '****') {
        _claudeMode = mode == 'api' ? 'api_key' : mode;
      }
    });
  }

  /// 텔레그램 수신자 인덱스에 대응하는 config 키를 반환한다.
  String _telegramTokenKey(int index) =>
      index == 0 ? 'telegram_bot_token' : 'telegram_bot_token_${index + 1}';

  String _telegramChatIdKey(int index) =>
      index == 0 ? 'telegram_chat_id' : 'telegram_chat_id_${index + 1}';

  String _telegramValidationKey(int index) =>
      index == 0 ? 'telegram' : 'telegram_${index + 1}';

  /// 서비스별 설정 상태 배지를 반환한다.
  Widget _statusBadge(TradingColors tc, bool configured) {
    final color = configured ? tc.profit : tc.textTertiary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusSm,
      ),
      child: Text(
        configured ? '설정됨' : '미설정',
        style: AppTypography.labelMedium.copyWith(color: color, fontSize: 11),
      ),
    );
  }

  /// KIS API 섹션을 빌드한다.
  Widget _buildKisSection(TradingColors tc, SetupProvider setup) {
    final configured = setup.status?.services['kis']?.configured;
    final kisValidation = setup.validations['kis_mock'];
    final kisRealValidation = setup.validations['kis_real'];

    return StaggeredFadeSlide(
      index: 0,
      child: GlassCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Expanded(
                child: SectionHeader(title: 'KIS API', padding: EdgeInsets.zero),
              ),
              if (configured != null) _statusBadge(tc, configured),
            ]),
            AppSpacing.vGapMd,
            ..._kisFields.map((f) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: ApiKeyField(
                label: f.$2,
                hintText: f.$3,
                value: _values[f.$1],
                onChanged: (v) => setState(() => _values[f.$1] = v),
              ),
            )),
            AppSpacing.vGapSm,
            // KIS 검증 버튼 (모의/실전)
            Row(
              children: [
                ElevatedButton.icon(
                  onPressed: setup.isValidating('kis_mock')
                      ? null
                      : () => _validateKis(setup, mock: true),
                  icon: const Icon(Icons.verified_user, size: 16),
                  label: const Text('모의 검증'),
                ),
                AppSpacing.hGapMd,
                if (kisValidation != null ||
                    setup.isValidating('kis_mock'))
                  Expanded(
                    child: ValidationIndicator(
                      isValid: kisValidation?.valid,
                      isLoading: setup.isValidating('kis_mock'),
                      message: kisValidation?.message ?? '검증 중...',
                    ),
                  ),
              ],
            ),
            AppSpacing.vGapSm,
            Row(
              children: [
                ElevatedButton.icon(
                  onPressed: setup.isValidating('kis_real')
                      ? null
                      : () => _validateKis(setup, mock: false),
                  icon: const Icon(Icons.verified, size: 16),
                  label: const Text('실전 검증'),
                ),
                AppSpacing.hGapMd,
                if (kisRealValidation != null ||
                    setup.isValidating('kis_real'))
                  Expanded(
                    child: ValidationIndicator(
                      isValid: kisRealValidation?.valid,
                      isLoading: setup.isValidating('kis_real'),
                      message: kisRealValidation?.message ?? '검증 중...',
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// KIS API를 검증한다.
  Future<void> _validateKis(SetupProvider provider, {required bool mock}) async {
    final prefix = mock ? 'kis_mock_' : 'kis_';
    final appKey = _values['${prefix}app_key'] ?? '';
    final appSecret = _values['${prefix}app_secret'] ?? '';

    if (appKey.isEmpty || appSecret.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('App Key와 App Secret을 입력하세요')),
      );
      return;
    }

    // account_no 키 — 모의는 kis_mock_account_no, 실전은 kis_account_no이다
    final accountKey = mock ? 'kis_mock_account_no' : 'kis_account_no';
    final accountNo = _values[accountKey] ?? '';

    // config에 저장하여 서버에서 읽을 수 있게 한다
    provider.updateConfig('${prefix}app_key', appKey);
    provider.updateConfig('${prefix}app_secret', appSecret);

    final storeAs = mock ? 'kis_mock' : 'kis_real';
    await provider.validateService(
      'kis',
      {
        'app_key': appKey,
        'app_secret': appSecret,
        'account_no': accountNo,
        'mock': mock ? 'true' : 'false',
      },
      storeAs: storeAs,
    );
  }

  /// Claude AI 섹션을 빌드한다.
  Widget _buildClaudeSection(TradingColors tc, SetupProvider setup) {
    final configured = setup.status?.services['claude']?.configured;

    return StaggeredFadeSlide(
      index: 1,
      child: GlassCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Expanded(
                child: SectionHeader(
                  title: 'Claude AI',
                  padding: EdgeInsets.zero,
                ),
              ),
              if (configured != null) _statusBadge(tc, configured),
            ]),
            AppSpacing.vGapMd,
            // Claude 모드 선택 — 위저드와 동일한 값(oauth/api_key)을 사용한다
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(
                  value: 'oauth',
                  label: Text('OAuth (CLI)'),
                  icon: Icon(Icons.terminal, size: 16),
                ),
                ButtonSegment(
                  value: 'api_key',
                  label: Text('API Key'),
                  icon: Icon(Icons.cloud, size: 16),
                ),
              ],
              selected: {_claudeMode == 'local' ? 'oauth' : _claudeMode},
              onSelectionChanged: (v) {
                setState(() => _claudeMode = v.first);
                _values['claude_mode'] = v.first;
              },
            ),
            AppSpacing.vGapMd,
            if (_claudeMode == 'api_key')
              ApiKeyField(
                label: 'Claude API Key',
                hintText: 'sk-ant-...',
                value: _values['claude_api_key'],
                onChanged: (v) => setState(() => _values['claude_api_key'] = v),
              ),
          ],
        ),
      ),
    );
  }

  /// 텔레그램 섹션을 빌드한다. 동적 수신자 추가/삭제를 지원한다.
  Widget _buildTelegramSection(TradingColors tc, SetupProvider setup) {
    final configured = setup.status?.services['telegram']?.configured;

    return StaggeredFadeSlide(
      index: 2,
      child: GlassCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Expanded(
                child: SectionHeader(
                  title: '텔레그램',
                  padding: EdgeInsets.zero,
                ),
              ),
              if (configured != null) _statusBadge(tc, configured),
            ]),
            AppSpacing.vGapMd,

            // 수신자 목록
            for (int i = 0; i < _telegramRecipientCount; i++)
              _buildTelegramRecipient(tc, setup, i),

            // 수신자 추가 버튼
            if (_telegramRecipientCount < _maxTelegramRecipients) ...[
              AppSpacing.vGapSm,
              OutlinedButton.icon(
                onPressed: () =>
                    setState(() => _telegramRecipientCount++),
                icon: const Icon(Icons.add, size: 16),
                label: Text(
                  '수신자 추가 ($_telegramRecipientCount/$_maxTelegramRecipients)',
                ),
                style: OutlinedButton.styleFrom(
                  foregroundColor: tc.primary,
                  side: BorderSide(
                    color: tc.primary.withValues(alpha: 0.5),
                  ),
                  minimumSize: const Size(double.infinity, 40),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  /// 개별 텔레그램 수신자 위젯을 빌드한다.
  Widget _buildTelegramRecipient(
    TradingColors tc,
    SetupProvider setup,
    int index,
  ) {
    final tokenKey = _telegramTokenKey(index);
    final chatIdKey = _telegramChatIdKey(index);
    final validationKey = _telegramValidationKey(index);
    final validation = setup.validations[validationKey];
    final isFirst = index == 0;

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: tc.surfaceBorder),
        borderRadius: AppSpacing.borderRadiusMd,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 수신자 헤더
          Row(
            children: [
              Icon(Icons.person, size: 16, color: tc.primary),
              const SizedBox(width: 6),
              Text(
                isFirst ? '기본 수신자' : '수신자 ${index + 1}',
                style: AppTypography.labelMedium.copyWith(
                  color: tc.textPrimary,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const Spacer(),
              if (!isFirst)
                IconButton(
                  onPressed: () {
                    _values.remove(tokenKey);
                    _values.remove(chatIdKey);
                    setState(() => _telegramRecipientCount--);
                  },
                  icon: Icon(Icons.close, size: 16, color: tc.loss),
                  constraints: const BoxConstraints(
                    minWidth: 28,
                    minHeight: 28,
                  ),
                  padding: EdgeInsets.zero,
                  tooltip: '수신자 삭제',
                ),
            ],
          ),
          AppSpacing.vGapSm,
          ApiKeyField(
            label: '봇 토큰',
            hintText: '0123456789:ABCdefGHIjklMNOpqrSTUvwxYZ',
            value: _values[tokenKey],
            onChanged: (v) => setState(() => _values[tokenKey] = v),
          ),
          AppSpacing.vGapSm,
          ApiKeyField(
            label: '채팅 ID',
            hintText: '숫자로 된 Chat ID (예: 123456789)',
            value: _values[chatIdKey],
            onChanged: (v) => setState(() => _values[chatIdKey] = v),
            obscure: false,
          ),
          AppSpacing.vGapSm,
          // 개별 테스트 전송 + 검증 결과
          Row(
            children: [
              SizedBox(
                height: 34,
                child: ElevatedButton.icon(
                  onPressed: setup.isValidating(validationKey)
                      ? null
                      : () => _validateTelegram(setup, index),
                  icon: const Icon(Icons.send, size: 14),
                  label: const Text('테스트', style: TextStyle(fontSize: 12)),
                ),
              ),
              AppSpacing.hGapMd,
              if (validation != null || setup.isValidating(validationKey))
                Expanded(
                  child: ValidationIndicator(
                    isValid: validation?.valid,
                    isLoading: setup.isValidating(validationKey),
                    message: validation?.message ?? '전송 중...',
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }

  /// 텔레그램 수신자를 개별 검증한다.
  Future<void> _validateTelegram(SetupProvider provider, int index) async {
    final token = _values[_telegramTokenKey(index)] ?? '';
    final chatId = _values[_telegramChatIdKey(index)] ?? '';

    if (token.isEmpty || chatId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('봇 토큰과 채팅 ID를 입력하세요')),
      );
      return;
    }

    await provider.validateService(
      'telegram',
      {'bot_token': token, 'chat_id': chatId},
      storeAs: _telegramValidationKey(index),
    );
  }

  /// 추가 API 섹션을 빌드한다.
  Widget _buildExtraSection(TradingColors tc) {
    return StaggeredFadeSlide(
      index: 3,
      child: GlassCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SectionHeader(title: '추가 API', padding: EdgeInsets.zero),
            AppSpacing.vGapMd,
            ..._extraFields.map((f) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: ApiKeyField(
                label: f.$2,
                hintText: f.$3,
                value: _values[f.$1],
                onChanged: (v) => setState(() => _values[f.$1] = v),
              ),
            )),
          ],
        ),
      ),
    );
  }

  /// 모든 입력값을 서버에 저장한다.
  Future<void> _save() async {
    setState(() {
      _isSaving = true;
      _message = null;
    });

    // claude_mode도 포함한다
    if (_claudeMode.isNotEmpty) {
      _values['claude_mode'] = _claudeMode;
    }

    final payload = Map<String, String>.fromEntries(
      _values.entries.where((e) => e.value.trim().isNotEmpty),
    );
    if (payload.isEmpty) {
      setState(() {
        _isSaving = false;
        _message = '변경된 항목이 없습니다.';
      });
      return;
    }

    final provider = context.read<SetupProvider>();
    for (final entry in payload.entries) {
      provider.updateConfig(entry.key, entry.value);
    }
    final success = await provider.saveAllConfig();
    await provider.loadStatus();

    if (mounted) {
      setState(() {
        _isSaving = false;
        _message = success ? '저장 완료' : '저장 실패 — 서버 로그를 확인하세요.';
        if (success) _values.clear();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Consumer<SetupProvider>(
      builder: (context, setup, _) {
        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            _buildKisSection(tc, setup),
            AppSpacing.vGapMd,
            _buildClaudeSection(tc, setup),
            AppSpacing.vGapMd,
            _buildTelegramSection(tc, setup),
            AppSpacing.vGapMd,
            _buildExtraSection(tc),
            AppSpacing.vGapXl,
            // 저장 버튼
            StaggeredFadeSlide(
              index: 4,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SizedBox(
                    height: 48,
                    child: ElevatedButton.icon(
                      onPressed: _isSaving ? null : _save,
                      icon: _isSaving
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child:
                                  CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.save, size: 18),
                      label: Text(
                        _isSaving ? '저장 중...' : '설정 저장',
                        style: const TextStyle(fontSize: 14),
                      ),
                    ),
                  ),
                  if (_message != null) ...[
                    AppSpacing.vGapSm,
                    Text(
                      _message!,
                      textAlign: TextAlign.center,
                      style: AppTypography.bodySmall.copyWith(
                        color: _message!.contains('완료')
                            ? tc.profit
                            : tc.loss,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            AppSpacing.vGapXxl,
          ],
        );
      },
    );
  }
}
