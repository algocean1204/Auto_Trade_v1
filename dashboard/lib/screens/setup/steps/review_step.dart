import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../providers/setup_provider.dart';
import '../../../screens/shell_screen.dart';
import '../../../services/api_service.dart';
import '../../../theme/app_spacing.dart';
import '../../../theme/trading_colors.dart';
import '../../../utils/env_loader.dart';

/// 셋업 위저드 8단계: 설정 검토 및 시작이다.
/// 모든 설정값을 한눈에 확인하고 최종 저장 후 메인 대시보드로 이동한다.
class ReviewStep extends StatelessWidget {
  const ReviewStep({super.key});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final theme = Theme.of(context);
    final provider = context.watch<SetupProvider>();
    final c = provider.configData;
    final ms = provider.modelsStatus;
    final isReal = c['trading_mode'] == 'real';

    return SingleChildScrollView(
      padding: AppSpacing.paddingScreen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('설정 검토', style: theme.textTheme.titleLarge?.copyWith(
            color: tc.textPrimary, fontWeight: FontWeight.bold,
          )),
          AppSpacing.vGapSm,
          Text('입력한 설정을 확인하고 시작합니다.',
            style: theme.textTheme.bodyMedium?.copyWith(color: tc.textSecondary)),
          AppSpacing.vGapXl,
          // 설정 요약 카드
          Card(
            margin: EdgeInsets.zero, color: tc.surface,
            shape: RoundedRectangleBorder(
              borderRadius: AppSpacing.borderRadiusMd,
              side: BorderSide(color: tc.surfaceBorder),
            ),
            child: Padding(
              padding: AppSpacing.paddingCard,
              child: Column(children: [
                _row(tc, theme, Icons.account_balance_wallet, 'KIS OpenAPI',
                  _val(c, 'kis_mock_app_key') ? '설정됨' : '미설정',
                  _val(c, 'kis_mock_app_key'),
                  detail: _mask(c['kis_mock_app_key'] as String?)),
                Divider(color: tc.surfaceBorder, height: 24),
                _row(tc, theme, Icons.psychology, 'Claude AI',
                  c['claude_mode'] == 'oauth' ? 'OAuth'
                    : _val(c, 'claude_api_key') ? 'API Key' : '미설정',
                  _val(c, 'claude_api_key') || c['claude_mode'] == 'oauth'),
                Divider(color: tc.surfaceBorder, height: 24),
                _row(tc, theme, Icons.send, 'Telegram',
                  _val(c, 'telegram_bot_token') ? '설정됨' : '건너뜀',
                  _val(c, 'telegram_bot_token')),
                Divider(color: tc.surfaceBorder, height: 24),
                _row(tc, theme, isReal ? Icons.account_balance : Icons.school,
                  '매매 모드', isReal ? '실전투자' : '모의투자', true),
                Divider(color: tc.surfaceBorder, height: 24),
                _row(tc, theme, Icons.vpn_key, '추가 API',
                  _optionalSummary(c), _hasAnyOptional(c)),
                Divider(color: tc.surfaceBorder, height: 24),
                _row(tc, theme, Icons.smart_toy, 'AI 모델',
                  ms != null
                    ? '${ms.downloadedCount}/${ms.totalCount} 다운로드 완료'
                    : '확인 불가',
                  (ms?.downloadedCount ?? 0) > 0),
              ]),
            ),
          ),
          AppSpacing.vGapXxl,
          // 저장 및 시작
          SizedBox(width: double.infinity, height: 48, child: FilledButton(
            onPressed: provider.isLoading
              ? null : () => _saveAndStart(context, provider),
            child: provider.isLoading
              ? const SizedBox(width: 20, height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Text('설정 저장 및 시작'),
          )),
          AppSpacing.vGapMd,
          // 이전으로
          SizedBox(width: double.infinity, height: 48, child: OutlinedButton(
            onPressed: provider.isLoading ? null : provider.previousStep,
            child: const Text('이전으로'),
          )),
          AppSpacing.vGapXl,
        ],
      ),
    );
  }

  /// 설정을 저장하고 성공 시 메인 대시보드로 이동한다.
  Future<void> _saveAndStart(BuildContext context, SetupProvider provider) async {
    final success = await provider.saveAllConfig();
    if (!context.mounted) return;
    if (success) {
      // .env가 새로 생성되었으므로 EnvLoader 캐시를 초기화하여
      // ApiService가 최신 API_SECRET_KEY를 사용하도록 한다.
      EnvLoader.reload();

      // ServerLauncher의 baseUrl도 갱신한다.
      final api = context.read<ApiService>();
      api.refreshBaseUrl();

      await showDialog<void>(
        context: context, barrierDismissible: false,
        builder: (ctx) => AlertDialog(
          icon: const Icon(Icons.check_circle, color: Colors.green, size: 48),
          title: const Text('설정 완료'),
          content: const Text('모든 설정이 저장되었습니다. 대시보드로 이동합니다.'),
          actions: [FilledButton(
            onPressed: () {
              Navigator.of(ctx).pop();
              // 명시적 MaterialPageRoute로 대시보드 전환 (named route 미등록)
              Navigator.of(context).pushReplacement(
                MaterialPageRoute(builder: (_) => const ShellScreen()),
              );
            },
            child: const Text('시작하기'),
          )],
        ),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(provider.error ?? '설정 저장에 실패했습니다.'),
        backgroundColor: Theme.of(context).colorScheme.error,
      ));
    }
  }

  /// 검토 항목 한 줄을 빌드한다.
  Widget _row(TradingColors tc, ThemeData theme, IconData icon,
      String label, String value, bool ok, {String? detail}) {
    return Row(children: [
      Icon(ok ? Icons.check_circle : Icons.cancel,
        color: ok ? tc.profit : tc.textTertiary, size: 20),
      AppSpacing.hGapMd,
      Icon(icon, color: tc.textSecondary, size: 20),
      AppSpacing.hGapSm,
      Expanded(child: Text(label,
        style: theme.textTheme.bodyMedium?.copyWith(color: tc.textPrimary))),
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(value, style: TextStyle(
          color: ok ? tc.profit : tc.textTertiary,
          fontWeight: FontWeight.w500, fontSize: 13)),
        if (detail != null)
          Text(detail, style: TextStyle(color: tc.textTertiary, fontSize: 11)),
      ]),
    ]);
  }

  /// 값이 비어있지 않은지 확인한다.
  bool _val(Map<String, dynamic> c, String k) {
    final v = c[k];
    return v != null && v.toString().isNotEmpty;
  }

  /// API 키를 앞 4자리만 보이도록 마스킹한다.
  String? _mask(String? v) {
    if (v == null || v.length < 5) return null;
    return '${v.substring(0, 4)}****';
  }

  /// 선택 API 요약 텍스트를 반환한다.
  String _optionalSummary(Map<String, dynamic> c) {
    final list = <String>[
      if (_val(c, 'fred_api_key')) 'FRED',
      if (_val(c, 'finnhub_api_key')) 'Finnhub',
      if (_val(c, 'reddit_client_id')) 'Reddit',
    ];
    return list.isEmpty ? '없음' : list.join(', ');
  }

  /// 선택 API 중 하나라도 설정되었는지 확인한다.
  bool _hasAnyOptional(Map<String, dynamic> c) =>
    _val(c, 'fred_api_key') || _val(c, 'finnhub_api_key') || _val(c, 'reddit_client_id');
}
