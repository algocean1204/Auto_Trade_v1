import 'package:flutter/material.dart';

import '../../theme/app_spacing.dart';
import '../../theme/trading_colors.dart';

/// AI 모델 다운로드 상태 및 진행률을 표시하는 카드 위젯이다.
/// 미시작, 다운로드 중, 완료 3가지 상태를 시각적으로 구분한다.
class ModelDownloadCard extends StatelessWidget {
  final String name;
  final double sizeGb;
  final bool downloaded;
  final double? progress; // 0.0~1.0, null이면 미시작

  const ModelDownloadCard({
    super.key,
    required this.name,
    required this.sizeGb,
    this.downloaded = false,
    this.progress,
  });

  /// 파일 크기를 읽기 좋은 문자열로 변환한다.
  String get _sizeText {
    if (sizeGb >= 1.0) return '${sizeGb.toStringAsFixed(1)} GB';
    return '${(sizeGb * 1024).toStringAsFixed(0)} MB';
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final bool isDownloading = !downloaded && progress != null;

    return Card(
      margin: EdgeInsets.zero,
      color: tc.surface,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusMd,
        side: BorderSide(color: tc.surfaceBorder),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                // 상태 아이콘
                Icon(
                  downloaded ? Icons.check_circle
                      : isDownloading ? Icons.downloading
                      : Icons.download,
                  color: downloaded ? tc.profit
                      : isDownloading ? tc.info
                      : tc.textTertiary,
                  size: 24,
                ),
                AppSpacing.hGapMd,
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(name,
                        style: Theme.of(context).textTheme.titleSmall,
                        overflow: TextOverflow.ellipsis,
                      ),
                      AppSpacing.vGapXs,
                      Text(
                        downloaded ? '$_sizeText · 완료' : _sizeText,
                        style: TextStyle(
                          color: downloaded ? tc.profit : tc.textSecondary,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
                // 진행률 퍼센트 텍스트
                if (isDownloading)
                  Text('${(progress! * 100).toStringAsFixed(0)}%',
                    style: TextStyle(color: tc.info, fontWeight: FontWeight.w600),
                  ),
              ],
            ),
            // 프로그레스 바
            if (isDownloading) ...[
              AppSpacing.vGapSm,
              ClipRRect(
                borderRadius: AppSpacing.borderRadiusSm,
                child: LinearProgressIndicator(
                  value: progress,
                  minHeight: 4,
                  backgroundColor: tc.surfaceBorder,
                  valueColor: AlwaysStoppedAnimation<Color>(tc.info),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
