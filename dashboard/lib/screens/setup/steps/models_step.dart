import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../providers/setup_provider.dart';
import '../../../theme/app_spacing.dart';
import '../../../theme/trading_colors.dart';
import '../../../widgets/setup/model_download_card.dart';

/// 셋업 위저드 7단계: GGUF 모델 다운로드이다.
/// 로컬 분류/번역에 필요한 MLX 모델 4개의 다운로드를 관리한다.
class ModelsStep extends StatefulWidget {
  const ModelsStep({super.key});

  @override
  State<ModelsStep> createState() => _ModelsStepState();
}

class _ModelsStepState extends State<ModelsStep> {
  Timer? _pollTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<SetupProvider>().loadModelsStatus();
    });
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }

  /// 3초 간격 폴링을 시작한다.
  void _startPolling() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 3), (_) {
      if (!mounted) return;
      context.read<SetupProvider>().loadModelsStatus();
    });
  }

  void _stopPolling() { _pollTimer?.cancel(); _pollTimer = null; }

  /// 전체 다운로드를 시작하고 폴링을 활성화한다.
  Future<void> _startDownload() async {
    await context.read<SetupProvider>().startDownload();
    _startPolling();
  }

  /// 다운로드를 취소하고 폴링을 중단한다.
  Future<void> _cancelDownload() async {
    final p = context.read<SetupProvider>();
    await p.cancelDownload();
    _stopPolling();
    await p.loadModelsStatus();
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final theme = Theme.of(context);
    final provider = context.watch<SetupProvider>();
    final models = provider.modelsStatus?.models ?? [];
    final totalGb = provider.modelsStatus?.totalSizeGb ?? 23;

    // 다운로드 진행 중 여부
    final downloading = models.any((m) => !m.downloaded && m.downloadProgress != null);
    // 전체 진행률
    final progress = _overallProgress(models);

    return SingleChildScrollView(
      padding: AppSpacing.paddingScreen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('AI 모델 다운로드', style: theme.textTheme.titleLarge?.copyWith(
            color: tc.textPrimary, fontWeight: FontWeight.bold)),
          AppSpacing.vGapSm,
          Text('로컬 분류/번역 모델 4개를 다운로드합니다. 총 약 ${totalGb.toStringAsFixed(0)}GB입니다.',
            style: theme.textTheme.bodyMedium?.copyWith(color: tc.textSecondary)),
          AppSpacing.vGapLg,
          // 안내 카드
          Card(
            margin: EdgeInsets.zero, color: tc.infoBg,
            shape: RoundedRectangleBorder(
              borderRadius: AppSpacing.borderRadiusMd,
              side: BorderSide(color: tc.info.withValues(alpha: 0.3))),
            child: Padding(
              padding: AppSpacing.paddingCard,
              child: Row(children: [
                Icon(Icons.info_outline, color: tc.info, size: 20),
                AppSpacing.hGapMd,
                Expanded(child: Text(
                  '모델은 나중에 다운로드할 수도 있습니다. 인터넷 연결이 필요합니다.',
                  style: TextStyle(color: tc.info, fontSize: 13))),
              ]),
            ),
          ),
          AppSpacing.vGapXl,
          // 전체 진행률 바
          if (downloading) ...[
            Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              Text('전체 진행률', style: theme.textTheme.titleSmall?.copyWith(
                color: tc.textPrimary)),
              Text('${(progress * 100).toStringAsFixed(0)}%',
                style: TextStyle(color: tc.info, fontWeight: FontWeight.w600)),
            ]),
            AppSpacing.vGapSm,
            ClipRRect(
              borderRadius: AppSpacing.borderRadiusSm,
              child: LinearProgressIndicator(value: progress, minHeight: 6,
                backgroundColor: tc.surfaceBorder,
                valueColor: AlwaysStoppedAnimation<Color>(tc.info))),
            AppSpacing.vGapXl,
          ],
          // 모델 목록
          if (models.isEmpty && provider.isLoading)
            const Center(child: CircularProgressIndicator())
          else
            ...models.map((m) => Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: ModelDownloadCard(
                name: m.name, sizeGb: m.sizeGb,
                downloaded: m.downloaded, progress: m.downloadProgress))),
          AppSpacing.vGapXl,
          // 액션 버튼
          Row(children: [
            Expanded(child: downloading
              ? OutlinedButton.icon(
                  onPressed: provider.isLoading ? null : _cancelDownload,
                  icon: Icon(Icons.cancel, size: 18, color: tc.loss),
                  label: Text('취소', style: TextStyle(color: tc.loss)))
              : FilledButton.icon(
                  onPressed: provider.isLoading ? null : _startDownload,
                  icon: const Icon(Icons.download, size: 18),
                  label: const Text('전체 다운로드'))),
            AppSpacing.hGapMd,
            Expanded(child: OutlinedButton(
              onPressed: () { _stopPolling(); provider.nextStep(); },
              child: const Text('나중에 다운로드'))),
          ]),
          AppSpacing.vGapXl,
        ],
      ),
    );
  }

  /// 전체 모델의 평균 진행률을 계산한다.
  double _overallProgress(List models) {
    if (models.isEmpty) return 0.0;
    var total = 0.0;
    for (final m in models) {
      total += m.downloaded ? 1.0 : (m.downloadProgress as double? ?? 0.0);
    }
    return total / models.length;
  }
}
