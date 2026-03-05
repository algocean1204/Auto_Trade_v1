import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/chart_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/pnl_line_chart.dart';
import '../widgets/cumulative_chart.dart';
import '../widgets/ticker_heatmap.dart';
import '../widgets/hourly_heatmap.dart';
import '../widgets/drawdown_chart.dart';
import '../animations/animation_utils.dart';

class ChartDashboard extends StatefulWidget {
  const ChartDashboard({super.key});

  @override
  State<ChartDashboard> createState() => _ChartDashboardState();
}

class _ChartDashboardState extends State<ChartDashboard>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 4, vsync: this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ChartProvider>().loadAllCharts();
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Scaffold(
      appBar: AppBar(
        title: Text(t('charts'), style: AppTypography.displaySmall),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded, size: 22),
            tooltip: t('refresh'),
            onPressed: () {
              context.read<ChartProvider>().refresh();
            },
          ),
        ],
        bottom: TabBar(
          controller: _tabController,
          tabs: [
            Tab(text: t('daily_pnl')),
            Tab(text: t('cumulative_chart')),
            Tab(text: 'Heatmap'),
            Tab(text: t('drawdown')),
          ],
        ),
      ),
      body: Consumer<ChartProvider>(
        builder: (context, provider, child) {
          if (provider.isLoading && provider.dailyReturns.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  ShimmerLoading(
                    width: MediaQuery.of(context).size.width - 32,
                    height: 300,
                    borderRadius: AppSpacing.borderRadiusLg,
                  ),
                ],
              ),
            );
          }

          if (provider.error != null && provider.dailyReturns.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.cloud_off_rounded, size: 48, color: context.tc.textTertiary),
                  AppSpacing.vGapLg,
                  Text('${t('connection_error')}: ${provider.error}',
                      style: AppTypography.bodyMedium),
                  AppSpacing.vGapLg,
                  ElevatedButton(
                    onPressed: () => provider.refresh(),
                    child: Text(t('retry')),
                  ),
                ],
              ),
            );
          }

          return TabBarView(
            controller: _tabController,
            children: [
              _buildChartTab(
                provider,
                t('daily_returns'),
                SizedBox(
                  height: 300,
                  child: PnlLineChart(data: provider.dailyReturns),
                ),
              ),
              _buildChartTab(
                provider,
                t('cumulative_returns'),
                SizedBox(
                  height: 300,
                  child: CumulativeChart(data: provider.cumulativeReturns),
                ),
              ),
              _buildHeatmapTab(provider, t),
              _buildChartTab(
                provider,
                t('max_drawdown'),
                SizedBox(
                  height: 300,
                  child: DrawdownChart(data: provider.drawdown),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildChartTab(ChartProvider provider, String title, Widget chart) {
    return RefreshIndicator(
      onRefresh: () => provider.refresh(),
      color: context.tc.primary,
      backgroundColor: context.tc.surfaceElevated,
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        child: Padding(
          padding: AppSpacing.paddingScreen,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AppSpacing.vGapLg,
              Text(title, style: AppTypography.headlineMedium),
              AppSpacing.vGapLg,
              Container(
                decoration: BoxDecoration(
                  color: context.tc.surface,
                  borderRadius: AppSpacing.borderRadiusLg,
                  border: Border.all(
                    color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                    width: 1,
                  ),
                ),
                padding: const EdgeInsets.only(top: 16, right: 8, bottom: 8),
                child: chart,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeatmapTab(ChartProvider provider, String Function(String) t) {
    return DefaultTabController(
      length: 2,
      child: Column(
        children: [
          Container(
            margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: BoxDecoration(
              color: context.tc.surface,
              borderRadius: AppSpacing.borderRadiusSm,
            ),
            child: TabBar(
              tabs: [
                Tab(text: t('ticker_heatmap')),
                Tab(text: t('hourly_heatmap')),
              ],
            ),
          ),
          Expanded(
            child: TabBarView(
              children: [
                RefreshIndicator(
                  onRefresh: () => provider.refresh(),
                  color: context.tc.primary,
                  child: SingleChildScrollView(
                    child: TickerHeatmap(data: provider.tickerHeatmap),
                  ),
                ),
                RefreshIndicator(
                  onRefresh: () => provider.refresh(),
                  color: context.tc.primary,
                  child: SingleChildScrollView(
                    child: HourlyHeatmap(data: provider.hourlyHeatmap),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
