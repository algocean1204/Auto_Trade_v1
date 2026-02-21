import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/crawl_progress_provider.dart';
import '../providers/trade_provider.dart';
import '../providers/indicator_provider.dart';
import '../providers/locale_provider.dart';
import '../models/dashboard_models.dart';
import '../models/indicator_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/section_header.dart';
import '../widgets/empty_state.dart';
import '../widgets/ticker_add_dialog.dart';
import '../widgets/crawl_progress_widget.dart';
import '../widgets/weight_slider.dart';
import '../widgets/confirmation_dialog.dart';
import '../animations/animation_utils.dart';
import 'ticker_params_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 5, vsync: this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<TradeProvider>().loadStrategyParams();
      context.read<TradeProvider>().loadUniverse();
      context.read<IndicatorProvider>().loadWeights();
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
      backgroundColor: context.tc.background,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
            decoration: BoxDecoration(
              color: context.tc.background,
              border: Border(
                bottom: BorderSide(
                  color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                  width: 1,
                ),
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(t('settings'), style: AppTypography.displayMedium),
                AppSpacing.vGapMd,
                TabBar(
                  controller: _tabController,
                  isScrollable: true,
                  tabAlignment: TabAlignment.start,
                  tabs: [
                    Tab(text: t('strategy')),
                    Tab(text: t('indicators')),
                    Tab(text: t('universe')),
                    Tab(text: t('crawl')),
                    Tab(text: t('tp_tab_title')),
                  ],
                ),
              ],
            ),
          ),
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                _StrategyTab(),
                _IndicatorsTab(),
                _UniverseTab(),
                _CrawlTab(),
                const TickerParamsTab(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── 전략 설정 탭 ──

class _StrategyTab extends StatefulWidget {
  @override
  State<_StrategyTab> createState() => _StrategyTabState();
}

class _StrategyTabState extends State<_StrategyTab> {
  final Map<String, TextEditingController> _controllers = {};

  // (paramKey, titleKey, descKey)
  static const _paramDefs = [
    ('min_confidence', 'min_confidence_title', 'min_confidence_desc'),
    ('take_profit_pct', 'take_profit_title', 'take_profit_desc'),
    ('stop_loss_pct', 'stop_loss_title', 'stop_loss_desc'),
    ('trailing_stop_pct', 'trailing_stop_title', 'trailing_stop_desc'),
    ('max_position_pct', 'max_position_title', 'max_position_desc'),
  ];

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Consumer<TradeProvider>(
      builder: (context, provider, _) {
        if (provider.isLoading && provider.strategyParams == null) {
          return Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: List.generate(
                4,
                (i) => Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: ShimmerLoading(
                    width: double.infinity,
                    height: 100,
                    borderRadius: AppSpacing.borderRadiusLg,
                  ),
                ),
              ),
            ),
          );
        }
        if (provider.error != null && provider.strategyParams == null) {
          return ErrorState(
            message: provider.error ?? '',
            onRetry: () => provider.loadStrategyParams(),
          );
        }

        final params = provider.strategyParams;
        if (params == null) {
          return EmptyState(
            icon: Icons.settings_rounded,
            title: t('no_strategy_params'),
          );
        }

        return SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final isWide = constraints.maxWidth >= 800;
              return Column(
                children: [
                  if (isWide)
                    _buildWideGrid(provider, params, t)
                  else
                    _buildNarrowList(provider, params, t),
                  AppSpacing.vGapLg,
                  _buildRegimesCard(params, t),
                  AppSpacing.vGapXxl,
                ],
              );
            },
          ),
        );
      },
    );
  }

  Widget _buildWideGrid(TradeProvider provider, dynamic params,
      String Function(String) t) {
    return GridView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: 400,
        mainAxisSpacing: 16,
        crossAxisSpacing: 16,
        mainAxisExtent: 140,
      ),
      itemCount: _paramDefs.length,
      itemBuilder: (context, i) {
        final (key, titleKey, descKey) = _paramDefs[i];
        final defaultValue = params.params[key]?.toString() ?? '';
        return _buildParamCard(
            key, t(titleKey), t(descKey), defaultValue, provider, t);
      },
    );
  }

  Widget _buildNarrowList(TradeProvider provider, dynamic params,
      String Function(String) t) {
    return Column(
      children: _paramDefs.map((def) {
        final (key, titleKey, descKey) = def;
        final defaultValue = params.params[key]?.toString() ?? '';
        return Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: _buildParamCard(
              key, t(titleKey), t(descKey), defaultValue, provider, t),
        );
      }).toList(),
    );
  }

  /// TextField + Save 버튼 Row: Flexible/Expanded로 오버플로우 방지
  Widget _buildParamCard(String paramKey, String title, String description,
      String defaultValue, TradeProvider provider,
      String Function(String) t) {
    if (!_controllers.containsKey(paramKey)) {
      _controllers[paramKey] = TextEditingController(text: defaultValue);
    }

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(title, style: AppTypography.headlineMedium),
          AppSpacing.vGapXs,
          Text(description, style: AppTypography.bodySmall),
          AppSpacing.vGapMd,
          Row(
            children: [
              Expanded(
                child: SizedBox(
                  height: 36,
                  child: TextField(
                    controller: _controllers[paramKey],
                    keyboardType: TextInputType.number,
                    style: AppTypography.numberSmall,
                    decoration: const InputDecoration(
                      isDense: true,
                      contentPadding:
                          EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    ),
                  ),
                ),
              ),
              AppSpacing.hGapMd,
              SizedBox(
                height: 36,
                child: ElevatedButton(
                  onPressed: () => _saveParam(paramKey, provider, t),
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 0),
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: Text(t('save'),
                      style: const TextStyle(fontSize: 13)),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  /// 레짐 키를 한국어 이름으로 변환한다.
  static String _regimeLabel(String key) {
    const labels = {
      'strong_bull': '강한 상승장',
      'mild_bull': '완만한 상승장',
      'sideways': '횡보장',
      'mild_bear': '완만한 하락장',
      'crash': '폭락장',
    };
    return labels[key] ?? key;
  }

  /// 레짐 값 Map을 사람이 읽을 수 있는 문자열로 포맷팅한다.
  static String _formatRegimeValue(dynamic value) {
    if (value is! Map) return value.toString();
    final parts = <String>[];

    final vixRange = value['vix_range'];
    if (vixRange is List && vixRange.length == 2) {
      parts.add('VIX ${vixRange[0]}~${vixRange[1]}');
    }

    final takeProfit = value['take_profit'];
    if (takeProfit != null) {
      parts.add('익절 ${takeProfit.toStringAsFixed(1)}%');
    }

    final maxHoldDays = value['max_hold_days'];
    if (maxHoldDays != null) {
      final days = maxHoldDays is num ? maxHoldDays.toInt() : 0;
      parts.add(days == 0 ? '당일청산' : '최대 $days일');
    }

    final strategy = value['strategy'] as String?;
    if (strategy != null) {
      const strategyLabels = {
        'inverse_2x': '인버스 2X',
        'no_new_buy': '신규매수 금지',
      };
      parts.add(strategyLabels[strategy] ?? strategy);
    }

    return parts.join(' | ');
  }

  Widget _buildRegimesCard(dynamic params, String Function(String) t) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('market_regimes')),
          Text(t('params_by_condition'),
              style: AppTypography.bodySmall),
          AppSpacing.vGapLg,
          ...params.regimes.entries.map<Widget>((entry) {
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    _regimeLabel(entry.key as String),
                    style: AppTypography.bodyMedium,
                  ),
                  Flexible(
                    child: Text(
                      _formatRegimeValue(entry.value),
                      style: AppTypography.numberSmall.copyWith(
                        color: context.tc.primary,
                      ),
                      textAlign: TextAlign.end,
                    ),
                  ),
                ],
              ),
            );
          }),
        ],
      ),
    );
  }

  Future<void> _saveParam(String paramKey, TradeProvider provider,
      String Function(String) t) async {
    final value = _controllers[paramKey]?.text;
    if (value == null || value.isEmpty) return;

    final numValue = double.tryParse(value);
    if (numValue == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(t('enter_valid_number')),
          backgroundColor: context.tc.loss,
        ),
      );
      return;
    }

    // 변경 확인 다이얼로그
    final oldValue = provider.strategyParams?.params[paramKey];
    final confirmed = await ConfirmationDialog.show(
      context,
      title: t('update_parameter'),
      message: '$paramKey:\n$oldValue → $numValue',
      confirmLabel: t('save'),
      confirmColor: context.tc.primary,
      icon: Icons.edit_rounded,
    );

    if (!confirmed || !mounted) return;

    try {
      final currentParams = Map<String, dynamic>.from(
        provider.strategyParams?.params ?? {},
      );
      currentParams[paramKey] = numValue;
      await provider.updateStrategyParams(currentParams);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(t('parameter_saved')),
            backgroundColor: context.tc.profit,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${t('save_failed')}: $e'),
            backgroundColor: context.tc.loss,
          ),
        );
      }
    }
  }
}

// ── 인디케이터 설정 탭 ──

class _IndicatorsTab extends StatefulWidget {
  @override
  State<_IndicatorsTab> createState() => _IndicatorsTabState();
}

class _IndicatorsTabState extends State<_IndicatorsTab> {
  Map<String, double> _editedWeights = {};
  Map<String, bool> _enabledIndicators = {};

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Consumer<IndicatorProvider>(
      builder: (context, provider, _) {
        if (provider.isLoading && provider.weights == null) {
          return Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: [
                ShimmerLoading(
                    width: double.infinity,
                    height: 80,
                    borderRadius: AppSpacing.borderRadiusLg),
                AppSpacing.vGapLg,
                ShimmerLoading(
                    width: double.infinity,
                    height: 200,
                    borderRadius: AppSpacing.borderRadiusLg),
              ],
            ),
          );
        }
        if (provider.error != null && provider.weights == null) {
          return ErrorState(
            message: provider.error ?? '',
            onRetry: () => provider.loadWeights(),
          );
        }

        final weights = provider.weights;
        if (weights == null) {
          return EmptyState(
            icon: Icons.tune_rounded,
            title: t('no_indicator_data'),
          );
        }

        if (_editedWeights.isEmpty) {
          _editedWeights = Map.from(weights.weights);
          _enabledIndicators = weights.weights.map(
            (key, value) => MapEntry(key, value > 0),
          );
        }

        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            if (weights.presets.isNotEmpty) ...[
              _buildPresetSection(weights.presets, provider, t),
              AppSpacing.vGapLg,
            ],
            _buildCategorySection(
                t('momentum'), IndicatorCategory.momentum, t),
            AppSpacing.vGapLg,
            _buildCategorySection(t('trend'), IndicatorCategory.trend, t),
            AppSpacing.vGapLg,
            _buildCategorySection(
                t('volatility'), IndicatorCategory.volatility, t),
            AppSpacing.vGapXxl,
            // 저장 버튼
            ElevatedButton.icon(
              onPressed: () => _saveWeights(provider, t),
              icon: const Icon(Icons.save_rounded, size: 18),
              label: Text(t('save_all_weights')),
              style: ElevatedButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
              ),
            ),
            AppSpacing.vGapXxl,
          ],
        );
      },
    );
  }

  Widget _buildPresetSection(List<WeightPreset> presets,
      IndicatorProvider provider, String Function(String) t) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('presets')),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: presets.map((preset) {
              return ActionChip(
                label: Text(preset.name),
                onPressed: () => _applyPreset(preset, t),
                side: BorderSide(
                    color: context.tc.primary.withValues(alpha: 0.3)),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  Widget _buildCategorySection(String title, IndicatorCategory category,
      String Function(String) t) {
    final indicators =
        IndicatorInfo.all.where((i) => i.category == category).toList();

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: title),
          ...indicators.map((info) => _buildIndicatorItem(info, t)),
        ],
      ),
    );
  }

  Widget _buildIndicatorItem(IndicatorInfo info, String Function(String) t) {
    final enabled = _enabledIndicators[info.id] ?? false;
    final weight = _editedWeights[info.id] ?? 0.0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(info.displayName,
                      style: AppTypography.labelLarge),
                  AppSpacing.vGapXs,
                  Text(info.description,
                      style: AppTypography.bodySmall),
                ],
              ),
            ),
            Switch(
              value: enabled,
              onChanged: (value) {
                setState(() {
                  _enabledIndicators[info.id] = value;
                  if (!value) {
                    _editedWeights[info.id] = 0.0;
                  } else if (_editedWeights[info.id] == 0.0) {
                    _editedWeights[info.id] = 20.0;
                  }
                });
              },
            ),
          ],
        ),
        AppSpacing.vGapSm,
        WeightSlider(
          label: t('weight'),
          value: weight,
          enabled: enabled,
          onChanged: (value) {
            setState(() => _editedWeights[info.id] = value);
          },
        ),
        Divider(
          height: 24,
          color: context.tc.surfaceBorder.withValues(alpha: 0.3),
        ),
      ],
    );
  }

  void _applyPreset(WeightPreset preset, String Function(String) t) {
    setState(() {
      _editedWeights = Map.from(preset.weights.isNotEmpty
          ? preset.weights
          : _editedWeights);
      _enabledIndicators = _editedWeights.map(
        (key, value) => MapEntry(key, value > 0),
      );
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('${t('applied')}: ${preset.name}'),
        backgroundColor: context.tc.primary,
      ),
    );
  }

  Future<void> _saveWeights(IndicatorProvider provider,
      String Function(String) t) async {
    try {
      await provider.updateWeights(_editedWeights);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(t('weights_saved')),
            backgroundColor: context.tc.profit,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${t('save_failed')}: $e'),
            backgroundColor: context.tc.loss,
          ),
        );
      }
    }
  }
}

// ── 유니버스 탭 ──

class _UniverseTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Consumer<TradeProvider>(
      builder: (context, provider, _) {
        if (provider.isLoading && provider.universe.isEmpty) {
          return Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: List.generate(
                3,
                (i) => Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: ShimmerLoading(
                    width: double.infinity,
                    height: 72,
                    borderRadius: AppSpacing.borderRadiusLg,
                  ),
                ),
              ),
            ),
          );
        }
        if (provider.error != null && provider.universe.isEmpty) {
          return ErrorState(
            message: provider.error ?? '',
            onRetry: () => provider.loadUniverse(),
          );
        }

        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            _buildUniverseSection(
              context,
              t('bull_2x_etf'),
              provider.bullTickers,
              provider,
              t,
            ),
            AppSpacing.vGapXxl,
            _buildUniverseSection(
              context,
              t('bear_2x_etf'),
              provider.bearTickers,
              provider,
              t,
            ),
            AppSpacing.vGapXl,
            ElevatedButton.icon(
              onPressed: () => _showAddDialog(context, provider, t),
              icon: const Icon(Icons.add_rounded, size: 18),
              label: Text(t('add_ticker')),
              style: ElevatedButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
              ),
            ),
            AppSpacing.vGapXxl,
          ],
        );
      },
    );
  }

  Widget _buildUniverseSection(BuildContext context, String title,
      List<UniverseTicker> tickers, TradeProvider provider,
      String Function(String) t) {
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
                    color: context.tc.primary),
              ),
            ),
          ],
        ),
        AppSpacing.vGapMd,
        if (tickers.isEmpty)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: context.tc.surface,
              borderRadius: AppSpacing.borderRadiusLg,
              border: Border.all(
                  color: context.tc.surfaceBorder.withValues(alpha: 0.3)),
            ),
            child: Center(
              child: Text(t('no_tickers'),
                  style: AppTypography.bodyMedium),
            ),
          )
        else
          ...tickers.asMap().entries.map((e) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: _buildTickerRow(context, e.value, provider, t),
              )),
      ],
    );
  }

  Widget _buildTickerRow(BuildContext context, UniverseTicker ticker,
      TradeProvider provider, String Function(String) t) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: context.tc.surface,
        borderRadius: AppSpacing.borderRadiusLg,
        border: Border.all(
            color: context.tc.surfaceBorder.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          Checkbox(
            value: ticker.enabled,
            onChanged: (value) {
              provider.toggleTicker(ticker.ticker, value ?? false);
            },
            activeColor: context.tc.primary,
            side: BorderSide(color: context.tc.surfaceBorder),
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(4)),
          ),
          AppSpacing.hGapMd,
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(ticker.ticker, style: AppTypography.labelLarge),
                Text(ticker.name,
                    style: AppTypography.bodySmall,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis),
                if (ticker.avgDailyVolume != null)
                  Text(
                    'Vol: ${NumberFormat('#,###').format(ticker.avgDailyVolume)}',
                    style: AppTypography.bodySmall
                        .copyWith(fontSize: 11),
                  ),
              ],
            ),
          ),
          IconButton(
            icon: Icon(Icons.delete_rounded,
                size: 18, color: context.tc.textTertiary),
            onPressed: () => _handleDelete(context, ticker, provider, t),
            padding: EdgeInsets.zero,
            constraints:
                const BoxConstraints(minWidth: 32, minHeight: 32),
          ),
        ],
      ),
    );
  }

  Future<void> _handleDelete(BuildContext context, UniverseTicker ticker,
      TradeProvider provider, String Function(String) t) async {
    final confirmed = await ConfirmationDialog.show(
      context,
      title: t('delete_ticker_title'),
      message: t('delete_ticker_msg')
          .replaceAll('{ticker}', ticker.ticker)
          .replaceAll('{name}', ticker.name),
      confirmLabel: t('delete'),
      confirmColor: context.tc.loss,
      icon: Icons.delete_rounded,
    );
    if (confirmed && context.mounted) {
      await provider.deleteTicker(ticker.ticker);
    }
  }

  Future<void> _showAddDialog(BuildContext context, TradeProvider provider,
      String Function(String) t) async {
    final direction = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        backgroundColor: context.tc.surfaceElevated,
        title: Text(t('select_type')),
        children: [
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, 'bull'),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text(t('bull_2x_etf')),
            ),
          ),
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, 'bear'),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text(t('bear_2x_etf')),
            ),
          ),
        ],
      ),
    );

    if (direction == null || !context.mounted) return;

    final ticker = await showDialog<UniverseTicker>(
      context: context,
      builder: (_) => TickerAddDialogLegacy(direction: direction),
    );

    if (ticker != null && context.mounted) {
      try {
        await provider.addTicker(ticker);
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('${ticker.ticker} ${t('added')}'),
              backgroundColor: context.tc.profit,
            ),
          );
        }
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('${t('save_failed')}: $e'),
              backgroundColor: context.tc.loss,
            ),
          );
        }
      }
    }
  }
}

// ── 크롤링 탭 ──

class _CrawlTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    final provider = context.watch<CrawlProgressProvider>();

    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        StaggeredFadeSlide(
          index: 0,
          child: _buildInfoCard(context, provider, t),
        ),
        AppSpacing.vGapLg,
        StaggeredFadeSlide(
          index: 1,
          child: _buildCrawlButton(context, provider, t),
        ),
        if (provider.error != null) ...[
          AppSpacing.vGapMd,
          _buildErrorBanner(context, provider, t),
        ],
        if (provider.isCrawling || provider.crawlerStatuses.isNotEmpty) ...[
          AppSpacing.vGapXxl,
          const StaggeredFadeSlide(
            index: 2,
            child: CrawlProgressWidget(),
          ),
        ],
        AppSpacing.vGapXxl,
      ],
    );
  }

  Widget _buildInfoCard(BuildContext context, CrawlProgressProvider provider,
      String Function(String) t) {
    final tc = context.tc;
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('last_crawl')),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(t('time'), style: AppTypography.bodySmall),
                  AppSpacing.vGapXs,
                  Text(
                    provider.lastCrawlTime != null
                        ? DateFormat('yyyy-MM-dd HH:mm')
                            .format(provider.lastCrawlTime ?? DateTime.now())
                        : 'N/A',
                    style: AppTypography.numberSmall
                        .copyWith(color: tc.primary),
                  ),
                ],
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(t('articles'), style: AppTypography.bodySmall),
                  AppSpacing.vGapXs,
                  Text(
                    NumberFormat('#,###')
                        .format(provider.lastArticleCount),
                    style: AppTypography.numberSmall
                        .copyWith(color: tc.primary),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildCrawlButton(BuildContext context, CrawlProgressProvider provider,
      String Function(String) t) {
    return SizedBox(
      width: double.infinity,
      height: 52,
      child: ElevatedButton.icon(
        onPressed: provider.isCrawling
            ? null
            : () => _startCrawling(context, provider, t),
        icon: provider.isCrawling
            ? const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                ),
              )
            : const Icon(Icons.download_rounded, size: 18),
        label: Text(
          provider.isCrawling
              ? t('crawling')
              : t('start_manual_crawl'),
        ),
      ),
    );
  }

  Widget _buildErrorBanner(BuildContext context, CrawlProgressProvider provider,
      String Function(String) t) {
    final tc = context.tc;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: tc.loss.withValues(alpha: 0.1),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(color: tc.loss.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          Icon(Icons.error_outline_rounded, color: tc.loss, size: 16),
          AppSpacing.hGapSm,
          Expanded(
            child: Text(
              provider.error ?? '',
              style: AppTypography.bodySmall.copyWith(color: tc.loss),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _startCrawling(BuildContext context,
      CrawlProgressProvider provider, String Function(String) t) async {
    await provider.startCrawl();

    if (!context.mounted) return;

    if (provider.error != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${t('save_failed')}: ${provider.error}'),
          backgroundColor: context.tc.loss,
        ),
      );
    }
  }
}
