import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/settings_provider.dart';
import '../providers/navigation_provider.dart';
import '../providers/locale_provider.dart';
import '../models/dashboard_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

/// 슬라이드 아웃 알림 패널이다.
class AlertPanel extends StatefulWidget {
  const AlertPanel({super.key});

  @override
  State<AlertPanel> createState() => _AlertPanelState();
}

class _AlertPanelState extends State<AlertPanel>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<Offset> _slideAnimation;
  late final Animation<double> _fadeAnimation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _slideAnimation = Tween<Offset>(
      begin: const Offset(1, 0),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _controller,
      curve: Curves.easeOutCubic,
    ));
    _fadeAnimation =
        CurvedAnimation(parent: _controller, curve: Curves.easeOut);

    // 초기 열기
    _controller.forward();
    // 알림 목록 로드
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<SettingsProvider>().loadAlerts();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return FadeTransition(
      opacity: _fadeAnimation,
      child: SlideTransition(
        position: _slideAnimation,
        child: Container(
          width: 360,
          decoration: BoxDecoration(
            color: tc.surfaceElevated,
            border: Border(
              left: BorderSide(
                color: tc.surfaceBorder.withValues(alpha: 0.4),
                width: 1,
              ),
            ),
          ),
          child: Column(
            children: [
              _buildHeader(context),
              Expanded(
                child: Consumer2<SettingsProvider, LocaleProvider>(
                  builder: (context, provider, locale, _) {
                    if (provider.isLoading) {
                      return const Center(child: CircularProgressIndicator());
                    }
                    if (provider.alerts.isEmpty) {
                      return Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(Icons.notifications_none_rounded,
                                size: 40, color: context.tc.textTertiary),
                            AppSpacing.vGapMd,
                            Text(locale.t('no_alerts'),
                                style: AppTypography.bodyMedium),
                          ],
                        ),
                      );
                    }
                    return ListView.separated(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      itemCount: provider.alerts.length,
                      separatorBuilder: (_, __) => Divider(
                        height: 1,
                        color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                      ),
                      itemBuilder: (context, index) {
                        return _AlertItem(
                          alert: provider.alerts[index],
                          onRead: (id) => provider.markAsRead(id),
                        );
                      },
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    final locale = context.watch<LocaleProvider>();
    final tc = context.tc;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(
            color: tc.surfaceBorder.withValues(alpha: 0.3),
            width: 1,
          ),
        ),
      ),
      child: Row(
        children: [
          Icon(Icons.notifications_rounded,
              size: 18, color: tc.primary),
          AppSpacing.hGapSm,
          Text(locale.t('alerts'), style: AppTypography.headlineMedium),
          const Spacer(),
          IconButton(
            icon: Icon(Icons.close_rounded,
                size: 18, color: tc.textTertiary),
            onPressed: () {
              context.read<NavigationProvider>().closeAlertPanel();
            },
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
          ),
        ],
      ),
    );
  }
}

class _AlertItem extends StatelessWidget {
  final AlertNotification alert;
  final Function(String) onRead;

  const _AlertItem({required this.alert, required this.onRead});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final severityColor = tc.severityColor(alert.severity);
    final timeStr = DateFormat('MM/dd HH:mm').format(alert.createdAt);

    return InkWell(
      onTap: () {
        if (!alert.read) onRead(alert.id);
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        color: alert.read
            ? Colors.transparent
            : tc.primary.withValues(alpha: 0.04),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 4,
              height: 4,
              margin: const EdgeInsets.only(top: 6),
              decoration: BoxDecoration(
                color: alert.read ? Colors.transparent : severityColor,
                shape: BoxShape.circle,
              ),
            ),
            AppSpacing.hGapMd,
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          alert.title,
                          style: AppTypography.labelLarge.copyWith(
                            color: alert.read
                                ? tc.textSecondary
                                : tc.textPrimary,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: severityColor.withValues(alpha: 0.12),
                          borderRadius: AppSpacing.borderRadiusSm,
                        ),
                        child: Text(
                          alert.severity.toUpperCase(),
                          style: AppTypography.bodySmall.copyWith(
                            color: severityColor,
                            fontSize: 10,
                          ),
                        ),
                      ),
                    ],
                  ),
                  AppSpacing.vGapXs,
                  Text(
                    alert.message,
                    style: AppTypography.bodySmall,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  AppSpacing.vGapXs,
                  Text(
                    timeStr,
                    style: AppTypography.bodySmall.copyWith(fontSize: 10),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
