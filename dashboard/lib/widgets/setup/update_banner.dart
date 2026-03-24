import 'dart:io';

import 'package:flutter/material.dart';
import '../../models/setup_models.dart';
import '../../services/setup_service.dart';
import '../../theme/trading_colors.dart';
import '../../theme/app_typography.dart';
import '../../theme/app_spacing.dart';

/// 새 버전이 있을 때 상단에 표시되는 업데이트 배너 위젯이다.
///
/// SetupService를 통해 서버에 업데이트를 확인하고,
/// 새 버전이 존재하면 다운로드 링크를 포함한 배너를 표시한다.
class UpdateBanner extends StatefulWidget {
  const UpdateBanner({super.key});

  @override
  State<UpdateBanner> createState() => _UpdateBannerState();
}

class _UpdateBannerState extends State<UpdateBanner> {
  UpdateCheckResult? _updateInfo;
  bool _dismissed = false;
  bool _checking = false;

  @override
  void initState() {
    super.initState();
    _checkForUpdates();
  }

  /// 서버에 업데이트를 확인한다.
  Future<void> _checkForUpdates() async {
    if (_checking) return;
    setState(() => _checking = true);

    try {
      final service = SetupService();
      final result = await service.checkForUpdates();
      if (mounted && result.updateAvailable) {
        setState(() => _updateInfo = result);
      }
    } catch (_) {
      // 업데이트 확인 실패는 무시한다 (네트워크 오류 등)
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  /// 다운로드 URL을 macOS 기본 브라우저로 연다.
  Future<void> _openDownloadUrl(String url) async {
    if (url.isEmpty) return;
    try {
      await Process.run('open', [url]);
    } catch (_) {
      // URL 열기 실패 시 무시한다
    }
  }

  @override
  Widget build(BuildContext context) {
    // 업데이트가 없거나 사용자가 닫았으면 빈 위젯을 반환한다
    if (_updateInfo == null || _dismissed || !_updateInfo!.updateAvailable) {
      return const SizedBox.shrink();
    }

    final tc = context.tc;
    final info = _updateInfo!;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: BoxDecoration(
        color: tc.primary.withValues(alpha: 0.12),
        border: Border(
          bottom: BorderSide(
            color: tc.primary.withValues(alpha: 0.3),
            width: 1,
          ),
        ),
      ),
      child: Row(
        children: [
          Icon(
            Icons.system_update_rounded,
            color: tc.primary,
            size: 20,
          ),
          AppSpacing.hGapMd,
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  '새 버전이 있습니다: v${info.latestVersion}',
                  style: AppTypography.bodyMedium.copyWith(
                    color: tc.primary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                if (info.releaseNotes.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    info.releaseNotes,
                    style: AppTypography.bodySmall.copyWith(
                      color: tc.textSecondary,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ],
            ),
          ),
          AppSpacing.hGapMd,
          if (info.downloadUrl.isNotEmpty)
            TextButton.icon(
              onPressed: () => _openDownloadUrl(info.downloadUrl),
              icon: const Icon(Icons.download_rounded, size: 16),
              label: const Text('다운로드'),
              style: TextButton.styleFrom(
                foregroundColor: tc.primary,
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 6,
                ),
              ),
            ),
          IconButton(
            onPressed: () => setState(() => _dismissed = true),
            icon: Icon(
              Icons.close_rounded,
              size: 16,
              color: tc.textTertiary,
            ),
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(
              minWidth: 28,
              minHeight: 28,
            ),
          ),
        ],
      ),
    );
  }
}
