import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/trade_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../animations/animation_utils.dart';

class AiReport extends StatefulWidget {
  const AiReport({super.key});

  @override
  State<AiReport> createState() => _AiReportState();
}

class _AiReportState extends State<AiReport> with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadDailyReport();
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  void _loadDailyReport() {
    final now = DateTime.now();
    final today =
        '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';
    context.read<TradeProvider>().loadDailyReport(today);
  }

  void _loadWeeklyReport() {
    final now = DateTime.now();
    final weekStart = now.subtract(Duration(days: now.weekday - 1));
    final weekStr =
        '${weekStart.year}-${weekStart.month.toString().padLeft(2, '0')}-${weekStart.day.toString().padLeft(2, '0')}';
    context.read<TradeProvider>().loadWeeklyReport(weekStr);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('AI Report', style: AppTypography.displaySmall),
        bottom: TabBar(
          controller: _tabController,
          onTap: (index) {
            if (index == 0) {
              _loadDailyReport();
            } else if (index == 1) {
              _loadWeeklyReport();
            } else {
              context.read<TradeProvider>().loadPendingAdjustments();
            }
          },
          tabs: const [
            Tab(text: 'Daily'),
            Tab(text: 'Weekly'),
            Tab(text: 'Pending'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          _buildReportTab('Daily Report'),
          _buildReportTab('Weekly Report'),
          _buildPendingAdjustmentsTab(),
        ],
      ),
    );
  }

  Widget _buildReportTab(String title) {
    return Consumer<TradeProvider>(
      builder: (context, provider, child) {
        if (provider.isLoading) {
          return Padding(
            padding: AppSpacing.paddingScreen,
            child: ShimmerLoading(
              width: double.infinity,
              height: 300,
              borderRadius: AppSpacing.borderRadiusLg,
            ),
          );
        }

        if (provider.error != null) {
          return Center(
            child: Text('Error: ${provider.error}', style: AppTypography.bodyMedium),
          );
        }

        if (provider.reports.isEmpty) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.article_rounded, size: 48, color: context.tc.textTertiary),
                AppSpacing.vGapLg,
                Text('No reports available', style: AppTypography.bodyMedium),
              ],
            ),
          );
        }

        final report = provider.reports.first;

        return ListView(
          padding: AppSpacing.paddingScreen,
          children: [
            StaggeredFadeSlide(
              index: 0,
              child: GlassCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(title, style: AppTypography.headlineMedium),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                          decoration: BoxDecoration(
                            color: context.tc.infoBg,
                            borderRadius: AppSpacing.borderRadiusSm,
                          ),
                          child: Text(
                            report.reportDate,
                            style: AppTypography.labelMedium.copyWith(
                              color: context.tc.info,
                            ),
                          ),
                        ),
                      ],
                    ),
                    Divider(height: 24, color: context.tc.surfaceBorder.withValues(alpha: 0.3)),
                    Text(
                      report.contentString,
                      style: AppTypography.bodyLarge.copyWith(height: 1.8),
                    ),
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildPendingAdjustmentsTab() {
    return Consumer<TradeProvider>(
      builder: (context, provider, child) {
        if (provider.isLoading) {
          return Padding(
            padding: AppSpacing.paddingScreen,
            child: Column(
              children: List.generate(3, (i) => Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: ShimmerLoading(
                  width: double.infinity,
                  height: 140,
                  borderRadius: AppSpacing.borderRadiusLg,
                ),
              )),
            ),
          );
        }

        if (provider.error != null) {
          return Center(
            child: Text('Error: ${provider.error}', style: AppTypography.bodyMedium),
          );
        }

        if (provider.pendingAdjustments.isEmpty) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.check_circle_outline_rounded, size: 48, color: context.tc.profit),
                AppSpacing.vGapLg,
                Text('No pending adjustments', style: AppTypography.bodyMedium),
              ],
            ),
          );
        }

        return ListView.builder(
          padding: AppSpacing.paddingScreen,
          itemCount: provider.pendingAdjustments.length,
          itemBuilder: (context, index) {
            final adjustment = provider.pendingAdjustments[index];
            return StaggeredFadeSlide(
              index: index,
              child: Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: GlassCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            adjustment.paramName,
                            style: AppTypography.headlineMedium,
                          ),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                            decoration: BoxDecoration(
                              color: context.tc.primary.withValues(alpha: 0.12),
                              borderRadius: AppSpacing.borderRadiusSm,
                            ),
                            child: Text(
                              '${adjustment.changePct >= 0 ? '+' : ''}${adjustment.changePct.toStringAsFixed(1)}%',
                              style: AppTypography.numberSmall.copyWith(
                                color: context.tc.primary,
                              ),
                            ),
                          ),
                        ],
                      ),
                      AppSpacing.vGapMd,
                      Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('Current', style: AppTypography.bodySmall),
                                Text(
                                  '${adjustment.currentValue}',
                                  style: AppTypography.numberSmall,
                                ),
                              ],
                            ),
                          ),
                          Icon(
                            Icons.arrow_forward_rounded,
                            size: 18,
                            color: context.tc.primary,
                          ),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                Text('Proposed', style: AppTypography.bodySmall),
                                Text(
                                  '${adjustment.proposedValue}',
                                  style: AppTypography.numberSmall.copyWith(
                                    color: context.tc.primary,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                      AppSpacing.vGapMd,
                      Text(
                        adjustment.reason,
                        style: AppTypography.bodyMedium,
                      ),
                      AppSpacing.vGapLg,
                      Row(
                        mainAxisAlignment: MainAxisAlignment.end,
                        children: [
                          OutlinedButton(
                            onPressed: () => provider.rejectAdjustment(adjustment.id),
                            child: const Text('Reject'),
                          ),
                          AppSpacing.hGapMd,
                          ElevatedButton(
                            onPressed: () => provider.approveAdjustment(adjustment.id),
                            child: const Text('Approve'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        );
      },
    );
  }
}
