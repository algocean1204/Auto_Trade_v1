import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/settings_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../animations/animation_utils.dart';

class AlertHistory extends StatefulWidget {
  const AlertHistory({super.key});

  @override
  State<AlertHistory> createState() => _AlertHistoryState();
}

class _AlertHistoryState extends State<AlertHistory> {
  String? _selectedType;
  String? _selectedSeverity;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<SettingsProvider>().loadAlerts();
    });
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Scaffold(
      appBar: AppBar(
        title: Text(t('alerts'), style: AppTypography.displaySmall),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded, size: 22),
            tooltip: t('refresh'),
            onPressed: () => _applyFilters(),
          ),
        ],
      ),
      body: Consumer<SettingsProvider>(
        builder: (context, provider, child) {
          return Column(
            children: [
              _buildFilterSection(t),
              Expanded(child: _buildAlertList(provider, t)),
            ],
          );
        },
      ),
    );
  }

  Widget _buildFilterSection(String Function(String) t) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Type', style: AppTypography.labelMedium),
          AppSpacing.vGapSm,
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                _buildFilterChip('All', _selectedType == null, () {
                  setState(() => _selectedType = null);
                  _applyFilters();
                }),
                AppSpacing.hGapSm,
                _buildFilterChip('Trade', _selectedType == 'trade', () {
                  setState(() => _selectedType = _selectedType == 'trade' ? null : 'trade');
                  _applyFilters();
                }),
                AppSpacing.hGapSm,
                _buildFilterChip('Stop Loss', _selectedType == 'stop_loss', () {
                  setState(() => _selectedType = _selectedType == 'stop_loss' ? null : 'stop_loss');
                  _applyFilters();
                }),
                AppSpacing.hGapSm,
                _buildFilterChip('System', _selectedType == 'system', () {
                  setState(() => _selectedType = _selectedType == 'system' ? null : 'system');
                  _applyFilters();
                }),
                AppSpacing.hGapSm,
                _buildFilterChip('Feedback', _selectedType == 'feedback', () {
                  setState(() => _selectedType = _selectedType == 'feedback' ? null : 'feedback');
                  _applyFilters();
                }),
              ],
            ),
          ),
          AppSpacing.vGapMd,
          Text('Severity', style: AppTypography.labelMedium),
          AppSpacing.vGapSm,
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                _buildFilterChip('All', _selectedSeverity == null, () {
                  setState(() => _selectedSeverity = null);
                  _applyFilters();
                }),
                AppSpacing.hGapSm,
                _buildSeverityChip('Info', 'info', context.tc.info),
                AppSpacing.hGapSm,
                _buildSeverityChip('Warning', 'warning', context.tc.warning),
                AppSpacing.hGapSm,
                _buildSeverityChip('Critical', 'critical', context.tc.loss),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFilterChip(String label, bool selected, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: AnimDuration.fast,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? context.tc.primary.withValues(alpha: 0.15) : context.tc.surface,
          borderRadius: AppSpacing.borderRadiusSm,
          border: Border.all(
            color: selected ? context.tc.primary.withValues(alpha: 0.4) : context.tc.surfaceBorder,
            width: 1,
          ),
        ),
        child: Text(
          label,
          style: AppTypography.labelMedium.copyWith(
            color: selected ? context.tc.primary : context.tc.textSecondary,
          ),
        ),
      ),
    );
  }

  Widget _buildSeverityChip(String label, String value, Color color) {
    final selected = _selectedSeverity == value;
    return GestureDetector(
      onTap: () {
        setState(() => _selectedSeverity = selected ? null : value);
        _applyFilters();
      },
      child: AnimatedContainer(
        duration: AnimDuration.fast,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? color.withValues(alpha: 0.15) : context.tc.surface,
          borderRadius: AppSpacing.borderRadiusSm,
          border: Border.all(
            color: selected ? color.withValues(alpha: 0.4) : context.tc.surfaceBorder,
            width: 1,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(
                color: color,
                shape: BoxShape.circle,
              ),
            ),
            AppSpacing.hGapSm,
            Text(
              label,
              style: AppTypography.labelMedium.copyWith(
                color: selected ? color : context.tc.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAlertList(SettingsProvider provider, String Function(String) t) {
    if (provider.isLoading) {
      return Padding(
        padding: AppSpacing.paddingScreen,
        child: Column(
          children: List.generate(4, (i) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: ShimmerLoading(
              width: double.infinity,
              height: 80,
              borderRadius: AppSpacing.borderRadiusLg,
            ),
          )),
        ),
      );
    }

    if (provider.error != null) {
      return Center(
        child: Text('${t('connection_error')}: ${provider.error}',
            style: AppTypography.bodyMedium),
      );
    }

    if (provider.alerts.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.notifications_off_rounded, size: 48, color: context.tc.textTertiary),
            AppSpacing.vGapLg,
            Text(t('no_alerts'), style: AppTypography.bodyMedium),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () => provider.loadAlerts(
        alertType: _selectedType,
        severity: _selectedSeverity,
      ),
      color: context.tc.primary,
      backgroundColor: context.tc.surfaceElevated,
      child: ListView.builder(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        itemCount: provider.alerts.length,
        itemBuilder: (context, index) {
          final alert = provider.alerts[index];
          final severityColor = context.tc.severityColor(alert.severity);

          return StaggeredFadeSlide(
            index: index,
            child: Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Material(
                color: context.tc.surface,
                borderRadius: AppSpacing.borderRadiusLg,
                child: InkWell(
                  onTap: () {
                    if (!alert.read) {
                      provider.markAsRead(alert.id);
                    }
                  },
                  borderRadius: AppSpacing.borderRadiusLg,
                  child: Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      borderRadius: AppSpacing.borderRadiusLg,
                      border: Border.all(
                        color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                        width: 1,
                      ),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Container(
                          width: 36,
                          height: 36,
                          decoration: BoxDecoration(
                            color: severityColor.withValues(alpha: 0.12),
                            borderRadius: AppSpacing.borderRadiusSm,
                          ),
                          child: Icon(
                            _getAlertIcon(alert.alertType),
                            color: severityColor,
                            size: 18,
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
                                      style: AppTypography.labelLarge,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                  if (!alert.read)
                                    Container(
                                      width: 8,
                                      height: 8,
                                      decoration: BoxDecoration(
                                        color: context.tc.primary,
                                        shape: BoxShape.circle,
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
                                DateFormat('MM/dd HH:mm').format(alert.createdAt),
                                style: AppTypography.bodySmall.copyWith(
                                  color: context.tc.textDisabled,
                                  fontSize: 11,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  IconData _getAlertIcon(String type) {
    switch (type.toLowerCase()) {
      case 'trade':
        return Icons.swap_horiz_rounded;
      case 'stop_loss':
        return Icons.trending_down_rounded;
      case 'system':
        return Icons.settings_rounded;
      case 'feedback':
        return Icons.feedback_rounded;
      default:
        return Icons.notifications_rounded;
    }
  }

  void _applyFilters() {
    context.read<SettingsProvider>().loadAlerts(
      alertType: _selectedType,
      severity: _selectedSeverity,
    );
  }
}
