import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../providers/setup_provider.dart';
import '../../../theme/app_spacing.dart';
import '../../../theme/trading_colors.dart';

/// 셋업 위저드 5단계: 매매 모드 선택이다.
/// 모의투자(기본 권장)와 실전투자 중 하나를 선택한다.
class TradingModeStep extends StatelessWidget {
  const TradingModeStep({super.key});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final theme = Theme.of(context);
    final provider = context.watch<SetupProvider>();
    final mode = provider.configData['trading_mode'] as String? ?? 'virtual';
    final hasRealKey =
        (provider.configData['kis_app_key'] as String?)?.isNotEmpty ?? false;

    return SingleChildScrollView(
      padding: AppSpacing.paddingScreen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('매매 모드 선택', style: theme.textTheme.titleLarge?.copyWith(
            color: tc.textPrimary, fontWeight: FontWeight.bold)),
          AppSpacing.vGapSm,
          Text('시스템이 사용할 매매 모드를 선택합니다.',
            style: theme.textTheme.bodyMedium?.copyWith(color: tc.textSecondary)),
          AppSpacing.vGapXl,
          // 모의투자 카드
          _modeCard(tc, theme,
            icon: Icons.school, title: '모의투자', chip: '권장',
            desc: '가상 자금으로 매매를 연습합니다. 실제 돈이 움직이지 않습니다.',
            selected: mode == 'virtual', enabled: true,
            onTap: () => provider.updateConfig('trading_mode', 'virtual')),
          AppSpacing.vGapMd,
          // 실전투자 카드
          _modeCard(tc, theme,
            icon: Icons.account_balance, title: '실전투자',
            desc: '실제 계좌로 매매합니다. 실제 손익이 발생합니다.',
            selected: mode == 'real', enabled: hasRealKey,
            onTap: () => _confirmReal(context, provider)),
          // 실전 키 미설정 안내
          if (!hasRealKey) ...[
            AppSpacing.vGapSm,
            Padding(
              padding: const EdgeInsets.only(left: AppSpacing.lg),
              child: Text('실전투자를 사용하려면 KIS 실전 App Key를 먼저 설정하세요.',
                style: TextStyle(color: tc.textTertiary, fontSize: 12)),
            ),
          ],
        ],
      ),
    );
  }

  /// 실전투자 선택 시 확인 다이얼로그를 표시한다.
  Future<void> _confirmReal(BuildContext context, SetupProvider provider) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('실전투자 모드'),
        content: const Text(
          '실전투자 모드를 선택하면 실제 자금으로 매매가 실행됩니다. 계속하시겠습니까?'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('취소')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('확인')),
        ],
      ),
    );
    if (ok == true) provider.updateConfig('trading_mode', 'real');
  }

  /// 모드 선택 카드를 빌드한다.
  Widget _modeCard(TradingColors tc, ThemeData theme, {
    required IconData icon, required String title, String? chip,
    required String desc, required bool selected, required bool enabled,
    required VoidCallback onTap,
  }) {
    final border = selected ? tc.primary : tc.surfaceBorder;
    final bg = selected ? tc.primary.withValues(alpha: 0.08) : tc.surface;
    return Opacity(
      opacity: enabled ? 1.0 : 0.5,
      child: InkWell(
        onTap: enabled ? onTap : null,
        borderRadius: AppSpacing.borderRadiusMd,
        child: Card(
          margin: EdgeInsets.zero, color: bg,
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
            side: BorderSide(color: border, width: selected ? 2 : 1)),
          child: Padding(
            padding: AppSpacing.paddingCard,
            child: Row(children: [
              Icon(selected ? Icons.radio_button_checked : Icons.radio_button_unchecked,
                color: selected ? tc.primary : tc.textTertiary),
              AppSpacing.hGapMd,
              Icon(icon, color: selected ? tc.primary : tc.textSecondary),
              AppSpacing.hGapMd,
              Expanded(child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    Text(title, style: theme.textTheme.titleSmall?.copyWith(
                      color: tc.textPrimary, fontWeight: FontWeight.w600)),
                    if (chip != null) ...[
                      AppSpacing.hGapSm,
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: tc.primary.withValues(alpha: 0.15),
                          borderRadius: AppSpacing.borderRadiusSm),
                        child: Text(chip, style: TextStyle(
                          color: tc.primary, fontSize: 11, fontWeight: FontWeight.w600)),
                      ),
                    ],
                  ]),
                  AppSpacing.vGapXs,
                  Text(desc, style: TextStyle(color: tc.textSecondary, fontSize: 13)),
                ],
              )),
            ]),
          ),
        ),
      ),
    );
  }
}
