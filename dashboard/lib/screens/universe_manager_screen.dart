import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/trade_provider.dart';
import '../models/dashboard_models.dart';
import '../widgets/ticker_add_dialog.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../animations/animation_utils.dart';

class UniverseManagerScreen extends StatefulWidget {
  const UniverseManagerScreen({super.key});

  @override
  State<UniverseManagerScreen> createState() => _UniverseManagerScreenState();
}

class _UniverseManagerScreenState extends State<UniverseManagerScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<TradeProvider>().loadUniverse();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Universe', style: AppTypography.displaySmall),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded, size: 22),
            onPressed: () => context.read<TradeProvider>().loadUniverse(),
          ),
        ],
      ),
      body: Consumer<TradeProvider>(
        builder: (context, provider, child) {
          if (provider.isLoading && provider.universe.isEmpty) {
            return Padding(
              padding: AppSpacing.paddingScreen,
              child: Column(
                children: List.generate(3, (i) => Padding(
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

          if (provider.error != null && provider.universe.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.cloud_off_rounded, size: 48, color: context.tc.textTertiary),
                  AppSpacing.vGapLg,
                  Text('Error: ${provider.error}', style: AppTypography.bodyMedium),
                  AppSpacing.vGapLg,
                  ElevatedButton(
                    onPressed: () => provider.loadUniverse(),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            );
          }

          return RefreshIndicator(
            onRefresh: () => provider.loadUniverse(),
            color: context.tc.primary,
            backgroundColor: context.tc.surfaceElevated,
            child: ListView(
              padding: AppSpacing.paddingScreen,
              children: [
                _buildSection(
                  context,
                  'Bull 2X ETF',
                  provider.bullTickers,
                  provider,
                ),
                AppSpacing.vGapXxl,
                _buildSection(
                  context,
                  'Bear 2X ETF',
                  provider.bearTickers,
                  provider,
                ),
                AppSpacing.vGapXxl,
              ],
            ),
          );
        },
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _showAddDialog(context),
        child: const Icon(Icons.add_rounded),
      ),
    );
  }

  Widget _buildSection(
    BuildContext context,
    String title,
    List<UniverseTicker> tickers,
    TradeProvider provider,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(title, style: AppTypography.headlineMedium),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: context.tc.primary.withValues(alpha: 0.12),
                borderRadius: AppSpacing.borderRadiusSm,
              ),
              child: Text(
                '${tickers.where((t) => t.enabled).length}/${tickers.length}',
                style: AppTypography.numberSmall.copyWith(
                  color: context.tc.primary,
                ),
              ),
            ),
          ],
        ),
        AppSpacing.vGapMd,
        if (tickers.isEmpty)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(32),
            decoration: BoxDecoration(
              color: context.tc.surface,
              borderRadius: AppSpacing.borderRadiusLg,
              border: Border.all(
                color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                width: 1,
              ),
            ),
            child: Center(
              child: Text('No tickers registered', style: AppTypography.bodyMedium),
            ),
          )
        else
          ...tickers.asMap().entries.map((entry) => StaggeredFadeSlide(
                index: entry.key,
                child: _buildTickerCard(context, entry.value, provider),
              )),
      ],
    );
  }

  Widget _buildTickerCard(
    BuildContext context,
    UniverseTicker ticker,
    TradeProvider provider,
  ) {
    final hasLowVolume = ticker.avgDailyVolume != null && (ticker.avgDailyVolume ?? 0) < 100000;

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Dismissible(
        key: Key(ticker.ticker),
        direction: DismissDirection.endToStart,
        confirmDismiss: (direction) async {
          return await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
              title: const Text('Delete Ticker'),
              content: Text('Remove ${ticker.ticker}?'),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('Cancel'),
                ),
                ElevatedButton(
                  onPressed: () => Navigator.pop(context, true),
                  style: ElevatedButton.styleFrom(backgroundColor: context.tc.loss),
                  child: const Text('Delete'),
                ),
              ],
            ),
          );
        },
        onDismissed: (direction) {
          provider.deleteTicker(ticker.ticker);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('${ticker.ticker} removed')),
          );
        },
        background: Container(
          decoration: BoxDecoration(
            color: context.tc.loss,
            borderRadius: AppSpacing.borderRadiusLg,
          ),
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: 20),
          child: const Icon(Icons.delete_rounded, color: Colors.white),
        ),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: context.tc.surface,
            borderRadius: AppSpacing.borderRadiusLg,
            border: Border.all(
              color: context.tc.surfaceBorder.withValues(alpha: 0.3),
              width: 1,
            ),
          ),
          child: Row(
            children: [
              SizedBox(
                width: 24,
                child: Checkbox(
                  value: ticker.enabled,
                  onChanged: (value) {
                    provider.toggleTicker(ticker.ticker, value ?? false);
                  },
                  activeColor: context.tc.primary,
                  side: BorderSide(color: context.tc.surfaceBorder),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(4),
                  ),
                ),
              ),
              AppSpacing.hGapMd,
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          ticker.ticker,
                          style: AppTypography.labelLarge,
                        ),
                        if (hasLowVolume) ...[
                          AppSpacing.hGapSm,
                          Icon(
                            Icons.warning_rounded,
                            size: 14,
                            color: context.tc.warning,
                          ),
                        ],
                      ],
                    ),
                    AppSpacing.vGapXs,
                    Text(
                      ticker.name,
                      style: AppTypography.bodySmall,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    if (ticker.avgDailyVolume != null) ...[
                      AppSpacing.vGapXs,
                      Text(
                        'Vol: ${NumberFormat('#,###').format(ticker.avgDailyVolume)}'
                        '${ticker.expenseRatio != null ? '  ER: ${ticker.expenseRatio}%' : ''}',
                        style: AppTypography.bodySmall.copyWith(
                          color: hasLowVolume
                              ? context.tc.warning
                              : context.tc.textTertiary,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _showAddDialog(BuildContext context) async {
    final direction = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('Select Type'),
        children: [
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, 'bull'),
            child: const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Text('Bull 2X ETF'),
            ),
          ),
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, 'bear'),
            child: const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Text('Bear 2X ETF'),
            ),
          ),
        ],
      ),
    );

    if (direction == null || !context.mounted) return;

    final ticker = await showDialog<UniverseTicker>(
      context: context,
      builder: (context) => TickerAddDialogLegacy(direction: direction),
    );

    if (ticker != null && context.mounted) {
      try {
        await context.read<TradeProvider>().addTicker(ticker);
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('${ticker.ticker} added'),
              backgroundColor: context.tc.profit,
            ),
          );
        }
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Failed: $e'),
              backgroundColor: context.tc.loss,
            ),
          );
        }
      }
    }
  }
}
