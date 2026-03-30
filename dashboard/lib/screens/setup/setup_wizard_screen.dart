import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/setup_provider.dart';
import '../../screens/shell_screen.dart';
import '../../services/api_service.dart';
import '../../services/server_launcher.dart';
import '../../theme/app_spacing.dart';
import '../../theme/trading_colors.dart';
import '../../utils/env_loader.dart';
import 'steps/welcome_step.dart';
import 'steps/kis_step.dart';
import 'steps/claude_step.dart';
import 'steps/telegram_step.dart';
import 'steps/trading_mode_step.dart';
import 'steps/optional_keys_step.dart';
import 'steps/models_step.dart';
import 'steps/review_step.dart';

/// 셋업 위저드 메인 화면이다. 8단계 설정을 순서대로 안내한다.
class SetupWizardScreen extends StatefulWidget {
  const SetupWizardScreen({super.key});
  @override
  State<SetupWizardScreen> createState() => _SetupWizardScreenState();
}

class _SetupWizardScreenState extends State<SetupWizardScreen> {
  static const _titles = [
    '환영', 'KIS API', 'Claude AI', '텔레그램',
    '매매 모드', '추가 API', 'AI 모델', '검토',
  ];
  /// 건너뛰기 가능 단계 (텔레그램, 추가 API, AI 모델)
  static const _skippable = {3, 5, 6};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<SetupProvider>().loadStatus();
    });
  }

  Widget _stepContent(int s) => switch (s) {
    0 => const WelcomeStep(),     1 => const KisStep(),
    2 => const ClaudeStep(),      3 => const TelegramStep(),
    4 => const TradingModeStep(), 5 => const OptionalKeysStep(),
    6 => const ModelsStep(),      7 => const ReviewStep(),
    _ => const SizedBox.shrink(),
  };

  @override
  Widget build(BuildContext context) {
    final prov = context.watch<SetupProvider>();
    final cur = prov.currentStep;
    final theme = Theme.of(context);
    final tc = context.tc;
    return Scaffold(
      body: Column(children: [
        _indicator(cur, theme, tc),
        const Divider(height: 1),
        Expanded(child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Center(child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: _stepContent(cur),
          )),
        )),
        const Divider(height: 1),
        _navBar(prov, cur),
      ]),
    );
  }

  /// 상단 수평 스텝 인디케이터
  Widget _indicator(int cur, ThemeData theme, TradingColors tc) {
    return Padding(
      padding: const EdgeInsets.symmetric(
        vertical: AppSpacing.md, horizontal: AppSpacing.lg),
      child: Row(children: List.generate(_titles.length, (i) {
        final done = i < cur;
        final active = i == cur;
        // 활성 단계는 primary, 완료 단계는 profit, 미완료는 반투명 onSurface
        final c = active ? tc.primary
            : done ? tc.profit
            : theme.colorScheme.onSurface.withValues(alpha: 0.3);
        return Expanded(child: Row(children: [
          CircleAvatar(radius: 14, backgroundColor: c, child: done
              ? const Icon(Icons.check, size: 16, color: Colors.white)
              : Text('${i + 1}', style: const TextStyle(
                  fontSize: 12, color: Colors.white,
                  fontWeight: FontWeight.bold))),
          const SizedBox(width: 4),
          Flexible(child: Text(_titles[i],
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.bodySmall?.copyWith(color: c,
              fontWeight: active ? FontWeight.bold : FontWeight.normal))),
          if (i < _titles.length - 1) Expanded(child: Container(
            height: 1, margin: const EdgeInsets.symmetric(horizontal: 4),
            color: done ? tc.profit
                : theme.colorScheme.onSurface.withValues(alpha: 0.15))),
        ]));
      })),
    );
  }

  /// 하단 네비게이션 바 (이전/건너뛰기/다음)
  Widget _navBar(SetupProvider prov, int cur) {
    final first = cur == 0;
    final last = cur == SetupProvider.totalSteps - 1;
    final skip = _skippable.contains(cur) && !last;
    return Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.lg, vertical: AppSpacing.md),
      child: Row(children: [
        if (!first) OutlinedButton.icon(
          onPressed: prov.previousStep,
          icon: const Icon(Icons.arrow_back, size: 18),
          label: const Text('이전')),
        const Spacer(),
        if (skip) ...[
          TextButton(onPressed: prov.nextStep,
            child: const Text('건너뛰기')),
          const SizedBox(width: AppSpacing.sm),
        ],
        FilledButton.icon(
          onPressed: last ? () => _complete(prov) : prov.nextStep,
          icon: Icon(last ? Icons.check : Icons.arrow_forward, size: 18),
          label: Text(last ? '완료' : '다음')),
      ]),
    );
  }

  /// 설정 저장 후 셋업용 서버를 종료하고 대시보드로 전환한다.
  ///
  /// 셋업 위저드에서 시작한 서버는 위저드 전용이다.
  /// 완료 후 서버를 종료하여 대시보드에서 사용자가 토큰 발급 → 서버 시작
  /// 순서로 직접 시작하도록 한다.
  Future<void> _complete(SetupProvider prov) async {
    final ok = await prov.saveAllConfig();
    if (!mounted) return;
    if (ok) {
      // .env가 새로 생성되었으므로 EnvLoader 캐시를 초기화한다
      EnvLoader.reload();
      // ServerLauncher의 baseUrl도 갱신한다
      context.read<ApiService>().refreshBaseUrl();

      // 셋업용으로 시작한 서버를 종료한다 — 대시보드에서 수동으로 시작한다
      final launcher = ServerLauncher.instance;
      if (launcher.launchedByUs) {
        await launcher.stop();
      }

      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const ShellScreen()),
      );
    }
  }
}
