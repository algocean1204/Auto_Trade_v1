import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/trade_provider.dart';
import '../providers/trading_control_provider.dart';
import '../providers/indicator_provider.dart';
import '../providers/locale_provider.dart';
import '../models/dashboard_models.dart';
import '../models/indicator_models.dart';
import '../services/server_launcher.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/section_header.dart';
import '../widgets/empty_state.dart';
import '../widgets/weight_slider.dart';
import '../widgets/confirmation_dialog.dart';
import '../animations/animation_utils.dart';
import '../services/setup_service.dart';
import '../models/setup_models.dart';
import 'ticker_params_screen.dart';
import 'api_keys_tab.dart';

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
    _tabController = TabController(length: 8, vsync: this);
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
                    const Tab(text: 'AI 모델'),
                    Tab(text: t('server_tab')),
                    const Tab(text: 'API 키'),
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
                const _ModelsTab(),
                const _ServerTab(),
                const ApiKeysTab(),
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

  /// V2 수치 파라미터 정의 (key, 한국어 이름, 설명, 기본값)이다.
  static const _paramDefs = <(String, String, String, String)>[
    ('beast_min_confidence', '최소 신뢰도', '매매 신호 최소 신뢰도 임계값 (0-1)', '0.7'),
    ('default_position_size_pct', '기본 포지션 %', '기본 포지션 배분 비율', '10.0'),
    ('max_position_pct', '최대 포지션 %', '단일 포지션 최대 비율', '23.75'),
    ('beast_min_obi', '최소 OBI', 'Order Book Imbalance 최소 임계값', '0.2'),
    ('obi_threshold', 'OBI 게이트 임계값', 'OBI 게이트 통과 기준', '0.1'),
    ('ml_threshold', 'ML 임계값', 'ML 모델 예측 신뢰도 임계값', '0.3'),
    ('friction_hurdle', '거래비용 허들', '거래비용 대비 최소 기대수익 비율', '0.7'),
    ('beast_max_daily', '일일 최대 거래', '하루 최대 거래 횟수', '10'),
    ('beast_cooldown_seconds', '쿨다운 (초)', '연속 거래 간 최소 대기 시간', '180'),
    ('pyramid_level1_pct', '피라미딩 1단계 %', '1차 추가 매수 진입 수익률', '1.5'),
    ('pyramid_level2_pct', '피라미딩 2단계 %', '2차 추가 매수 진입 수익률', '3.0'),
    ('pyramid_level3_pct', '피라미딩 3단계 %', '3차 추가 매수 진입 수익률', '5.0'),
  ];

  /// 토글 스위치 파라미터 정의이다.
  static const _toggleDefs = <(String, String, String)>[
    ('beast_mode_enabled', 'Beast Mode', '고빈도 단타 전략 활성화'),
    ('pyramiding_enabled', 'Pyramiding', '수익 구간 추가 매수 활성화'),
    ('stat_arb_enabled', 'Stat Arb', '통계적 차익거래 전략 활성화'),
    ('news_fading_enabled', 'News Fading', '뉴스 기반 역추세 전략 활성화'),
    ('wick_catcher_enabled', 'Wick Catcher', '급락 꼬리 잡기 전략 활성화'),
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
          return SingleChildScrollView(
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
                  // 전략 모듈 토글 스위치
                  _buildTogglesCard(params.params, provider),
                  AppSpacing.vGapLg,
                  // 수치 파라미터
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

  Widget _buildTogglesCard(Map<String, dynamic> params, TradeProvider provider) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('전략 모듈', style: AppTypography.headlineMedium),
          AppSpacing.vGapSm,
          Text('활성화할 전략 모듈을 선택한다', style: AppTypography.bodySmall),
          AppSpacing.vGapLg,
          ..._toggleDefs.map((def) {
            final (key, label, description) = def;
            final enabled = params[key] == true;
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(label, style: AppTypography.labelLarge),
                        Text(description, style: AppTypography.bodySmall),
                      ],
                    ),
                  ),
                  Switch(
                    value: enabled,
                    onChanged: (value) {
                      final updated = Map<String, dynamic>.from(params);
                      updated[key] = value;
                      provider.updateStrategyParams(updated);
                    },
                  ),
                ],
              ),
            );
          }),
        ],
      ),
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
        final (key, label, desc, defaultVal) = _paramDefs[i];
        final value = params.params[key]?.toString() ?? defaultVal;
        return _buildParamCard(key, label, desc, value, provider, t);
      },
    );
  }

  Widget _buildNarrowList(TradeProvider provider, dynamic params,
      String Function(String) t) {
    return Column(
      children: _paramDefs.map((def) {
        final (key, label, desc, defaultVal) = def;
        final value = params.params[key]?.toString() ?? defaultVal;
        return Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: _buildParamCard(key, label, desc, value, provider, t),
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
          if (params.regimes.isEmpty)
            Text(
              '레짐 설정이 없다',
              style: AppTypography.bodySmall,
            )
          else
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

/// 페어 그룹: bull+bear 티커를 하나의 그룹으로 묶는다.
class _PairGroup {
  UniverseTicker? bull;
  UniverseTicker? bear;

  String get sector => bull?.sector ?? bear?.sector ?? '';

  String get displayKey {
    if (bull != null && bear != null) return '${bull!.ticker}/${bear!.ticker}';
    return bull?.ticker ?? bear?.ticker ?? '';
  }
}

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

        final pairs = _buildPairGroups(provider.universe);
        final enabledCount =
            provider.universe.where((t) => t.enabled).length;

        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            // 헤더: 페어 ETF + 활성 카운트
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(t('etf_pairs'), style: AppTypography.headlineMedium),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: context.tc.primary.withValues(alpha: 0.12),
                    borderRadius: AppSpacing.borderRadiusSm,
                  ),
                  child: Text(
                    '$enabledCount/${provider.universe.length}',
                    style: AppTypography.numberSmall
                        .copyWith(color: context.tc.primary),
                  ),
                ),
              ],
            ),
            AppSpacing.vGapMd,
            if (pairs.isEmpty)
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
                  child:
                      Text(t('no_tickers'), style: AppTypography.bodyMedium),
                ),
              )
            else
              ...pairs.map((pair) => Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: _buildPairCard(context, pair, provider, t),
                  )),
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

  /// universe 목록에서 bull/bear 페어 그룹을 빌드한다.
  List<_PairGroup> _buildPairGroups(List<UniverseTicker> universe) {
    final Map<String, _PairGroup> groups = {};
    for (final t in universe) {
      final key = _pairKey(t);
      groups.putIfAbsent(key, () => _PairGroup());
      if (t.direction == 'bull') {
        groups[key]!.bull = t;
      } else {
        groups[key]!.bear = t;
      }
    }
    final result = groups.values.toList();
    result.sort((a, b) {
      final s = a.sector.compareTo(b.sector);
      if (s != 0) return s;
      return a.displayKey.compareTo(b.displayKey);
    });
    return result;
  }

  /// 페어 그룹핑 키를 생성한다. 동일 페어는 같은 키를 갖는다.
  String _pairKey(UniverseTicker t) {
    if (t.pairTicker != null && t.pairTicker!.isNotEmpty) {
      final a = t.ticker;
      final b = t.pairTicker!;
      return a.compareTo(b) < 0 ? a : b;
    }
    return t.ticker;
  }

  /// 페어 카드를 빌드한다. bull과 bear를 한 카드 안에 표시한다.
  Widget _buildPairCard(BuildContext context, _PairGroup pair,
      TradeProvider provider, String Function(String) t) {
    final tc = context.tc;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: tc.surface,
        borderRadius: AppSpacing.borderRadiusLg,
        border:
            Border.all(color: tc.surfaceBorder.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 섹터 배지
          if (pair.sector.isNotEmpty)
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              margin: const EdgeInsets.only(bottom: 8),
              decoration: BoxDecoration(
                color: tc.primary.withValues(alpha: 0.08),
                borderRadius: AppSpacing.borderRadiusSm,
              ),
              child: Text(
                pair.sector.toUpperCase(),
                style: AppTypography.bodySmall
                    .copyWith(fontSize: 10, color: tc.primary),
              ),
            ),
          // Bull 행
          if (pair.bull != null)
            _buildTickerRow(context, pair.bull!, provider, t, isBull: true),
          if (pair.bull != null && pair.bear != null) AppSpacing.vGapSm,
          // Bear 행
          if (pair.bear != null)
            _buildTickerRow(context, pair.bear!, provider, t, isBull: false),
        ],
      ),
    );
  }

  Widget _buildTickerRow(BuildContext context, UniverseTicker ticker,
      TradeProvider provider, String Function(String) t,
      {required bool isBull}) {
    final tc = context.tc;
    final dirColor = isBull ? tc.profit : tc.loss;
    final dirIcon = isBull ? '▲' : '▼';
    return Row(
      children: [
        Checkbox(
          value: ticker.enabled,
          onChanged: (value) {
            provider.toggleTicker(ticker.ticker, value ?? false);
          },
          fillColor: WidgetStateProperty.resolveWith((states) =>
              states.contains(WidgetState.selected) ? tc.primary : null),
          side: BorderSide(color: tc.surfaceBorder),
          shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(4)),
          visualDensity: VisualDensity.compact,
        ),
        AppSpacing.hGapXs,
        // 방향 배지
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
          decoration: BoxDecoration(
            color: dirColor.withValues(alpha: 0.10),
            borderRadius: AppSpacing.borderRadiusSm,
          ),
          child: Text(
            '$dirIcon ${ticker.ticker}',
            style: AppTypography.labelMedium.copyWith(
              color: dirColor,
              fontWeight: FontWeight.w700,
              fontSize: 12,
            ),
          ),
        ),
        AppSpacing.hGapSm,
        Expanded(
          child: Text(
            ticker.name,
            style: AppTypography.bodySmall,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ),
        IconButton(
          icon: Icon(Icons.delete_rounded, size: 16, color: tc.textTertiary),
          onPressed: () => _handleDelete(context, ticker, provider, t),
          padding: EdgeInsets.zero,
          constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
        ),
      ],
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

  /// 간소화된 종목 추가 다이얼로그이다. 티커 코드만 입력하면 페어도 자동 추가된다.
  Future<void> _showAddDialog(BuildContext context, TradeProvider provider,
      String Function(String) t) async {
    final controller = TextEditingController();
    var isLoading = false;
    String? errorMsg;

    final added = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (ctx, setState) {
            final tc = ctx.tc;
            return AlertDialog(
              backgroundColor: tc.surfaceElevated,
              shape: RoundedRectangleBorder(
                borderRadius: AppSpacing.borderRadiusLg,
                side: BorderSide(
                  color: tc.surfaceBorder.withValues(alpha: 0.4),
                  width: 1,
                ),
              ),
              title: Row(
                children: [
                  Icon(Icons.add_circle_outline_rounded,
                      color: tc.primary, size: 22),
                  AppSpacing.hGapSm,
                  Text(t('add_ticker'), style: AppTypography.headlineMedium),
                ],
              ),
              content: SizedBox(
                width: 360,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      t('enter_ticker_code'),
                      style: AppTypography.labelMedium
                          .copyWith(color: tc.textSecondary),
                    ),
                    AppSpacing.vGapSm,
                    TextField(
                      controller: controller,
                      autofocus: true,
                      textCapitalization: TextCapitalization.characters,
                      enabled: !isLoading,
                      style: AppTypography.displaySmall.copyWith(
                        color: tc.textPrimary,
                        letterSpacing: 2,
                      ),
                      decoration: InputDecoration(
                        hintText: 'SOXL',
                        hintStyle: AppTypography.displaySmall.copyWith(
                          color: tc.textDisabled,
                          letterSpacing: 2,
                        ),
                        filled: true,
                        fillColor: tc.surface,
                        border: OutlineInputBorder(
                          borderRadius: AppSpacing.borderRadiusMd,
                          borderSide: BorderSide(
                              color: tc.surfaceBorder.withValues(alpha: 0.3)),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: AppSpacing.borderRadiusMd,
                          borderSide: BorderSide(
                              color: tc.surfaceBorder.withValues(alpha: 0.3)),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: AppSpacing.borderRadiusMd,
                          borderSide: BorderSide(
                              color: tc.primary.withValues(alpha: 0.6),
                              width: 1.5),
                        ),
                        contentPadding: const EdgeInsets.symmetric(
                            horizontal: 14, vertical: 12),
                      ),
                      onSubmitted: (_) {
                        if (!isLoading) {
                          _submitAdd(ctx, controller, provider, t,
                              setState, (v) => isLoading = v, (v) => errorMsg = v);
                        }
                      },
                    ),
                    if (isLoading) ...[
                      AppSpacing.vGapMd,
                      Row(
                        children: [
                          SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                                strokeWidth: 2, color: tc.primary),
                          ),
                          AppSpacing.hGapSm,
                          Text(
                            t('adding_ticker'),
                            style: AppTypography.bodySmall
                                .copyWith(color: tc.primary),
                          ),
                        ],
                      ),
                    ],
                    if (errorMsg != null) ...[
                      AppSpacing.vGapMd,
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 8),
                        decoration: BoxDecoration(
                          color: tc.loss.withValues(alpha: 0.08),
                          borderRadius: AppSpacing.borderRadiusMd,
                          border: Border.all(
                              color: tc.loss.withValues(alpha: 0.25)),
                        ),
                        child: Row(
                          children: [
                            Icon(Icons.error_outline_rounded,
                                size: 16, color: tc.loss),
                            AppSpacing.hGapSm,
                            Expanded(
                              child: Text(
                                errorMsg!,
                                style: AppTypography.bodySmall
                                    .copyWith(color: tc.loss),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed:
                      isLoading ? null : () => Navigator.pop(dialogContext),
                  child: Text(
                    t('cancel'),
                    style: AppTypography.labelLarge
                        .copyWith(color: tc.textSecondary),
                  ),
                ),
                ElevatedButton(
                  onPressed: isLoading
                      ? null
                      : () => _submitAdd(ctx, controller, provider, t,
                          setState, (v) => isLoading = v, (v) => errorMsg = v),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: tc.primary,
                    foregroundColor: Colors.white,
                    disabledBackgroundColor:
                        tc.primary.withValues(alpha: 0.4),
                    shape: RoundedRectangleBorder(
                        borderRadius: AppSpacing.borderRadiusSm),
                  ),
                  child: isLoading
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white),
                        )
                      : Text(t('add_ticker'),
                          style: AppTypography.labelLarge
                              .copyWith(color: Colors.white)),
                ),
              ],
            );
          },
        );
      },
    );

    if (added == true && context.mounted) {
      provider.loadUniverse();
    }
  }

  Future<void> _submitAdd(
    BuildContext context,
    TextEditingController controller,
    TradeProvider provider,
    String Function(String) t,
    void Function(void Function()) setState,
    void Function(bool) setLoading,
    void Function(String?) setError,
  ) async {
    final ticker = controller.text.trim().toUpperCase();
    if (ticker.isEmpty) return;

    setState(() {
      setLoading(true);
      setError(null);
    });

    try {
      final result = await provider.autoAddTicker(ticker);
      final pairAdded = result['pair_ticker'] as String?;
      if (context.mounted) {
        Navigator.pop(context, true);
        final msg = pairAdded != null
            ? '$ticker ${t('added')} (${t('pair_auto_added').replaceAll('{pair}', pairAdded)})'
            : '$ticker ${t('added')}';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(msg), backgroundColor: context.tc.profit),
        );
      }
    } catch (e) {
      setState(() {
        setLoading(false);
        setError(e.toString().replaceFirst('Exception: ', ''));
      });
    }
  }
}

// ── 크롤링 탭 ──
//
// AppBar NEWS 버튼과 동일한 파이프라인(collect-and-send)을 사용한다.

class _CrawlTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Consumer<TradingControlProvider>(
      builder: (context, ctrl, _) {
        final tc = context.tc;
        final isBusy = ctrl.isBusyNews;
        final isConnected = ctrl.isConnected;

        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            // 설명 카드
            StaggeredFadeSlide(
              index: 0,
              child: GlassCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SectionHeader(title: t('last_crawl')),
                    AppSpacing.vGapSm,
                    Text(
                      '30개 뉴스 소스 크롤링 → AI 분류 → 텔레그램 전송',
                      style: AppTypography.bodySmall,
                    ),
                    AppSpacing.vGapMd,
                    // 서버 연결 상태
                    Row(
                      children: [
                        Container(
                          width: 8,
                          height: 8,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: isConnected ? tc.profit : tc.loss,
                          ),
                        ),
                        AppSpacing.hGapSm,
                        Text(
                          isConnected ? '서버 연결됨' : '서버 미연결',
                          style: AppTypography.bodySmall.copyWith(
                            color: isConnected ? tc.profit : tc.loss,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            AppSpacing.vGapLg,

            // 실행 버튼
            StaggeredFadeSlide(
              index: 1,
              child: SizedBox(
                width: double.infinity,
                height: 52,
                child: ElevatedButton.icon(
                  onPressed: isBusy
                      ? null
                      : () => _handleCollect(context, ctrl),
                  icon: isBusy
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            valueColor:
                                AlwaysStoppedAnimation<Color>(Colors.white),
                          ),
                        )
                      : const Icon(Icons.newspaper_rounded, size: 18),
                  label: Text(
                    isBusy
                        ? '뉴스 수집 중...'
                        : t('start_manual_crawl'),
                  ),
                ),
              ),
            ),

            // 에러 메시지
            if (ctrl.error != null) ...[
              AppSpacing.vGapMd,
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: tc.loss.withValues(alpha: 0.1),
                  borderRadius: AppSpacing.borderRadiusMd,
                  border: Border.all(color: tc.loss.withValues(alpha: 0.3)),
                ),
                child: Row(
                  children: [
                    Icon(Icons.error_outline_rounded,
                        color: tc.loss, size: 16),
                    AppSpacing.hGapSm,
                    Expanded(
                      child: Text(
                        ctrl.error ?? '',
                        style:
                            AppTypography.bodySmall.copyWith(color: tc.loss),
                      ),
                    ),
                  ],
                ),
              ),
            ],

            // 결과 메시지
            if (ctrl.newsResult != null) ...[
              AppSpacing.vGapMd,
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: tc.profit.withValues(alpha: 0.1),
                  borderRadius: AppSpacing.borderRadiusMd,
                  border: Border.all(color: tc.profit.withValues(alpha: 0.3)),
                ),
                child: Row(
                  children: [
                    Icon(Icons.check_circle_rounded,
                        color: tc.profit, size: 16),
                    AppSpacing.hGapSm,
                    Expanded(
                      child: Text(
                        ctrl.newsResult!,
                        style:
                            AppTypography.bodySmall.copyWith(color: tc.profit),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            AppSpacing.vGapXxl,
          ],
        );
      },
    );
  }

  Future<void> _handleCollect(
      BuildContext context, TradingControlProvider ctrl) async {
    await ctrl.collectAndSendNews();
    if (!context.mounted) return;

    final tc = context.tc;
    if (ctrl.error != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('뉴스 수집 실패: ${ctrl.error}'),
          backgroundColor: tc.loss,
        ),
      );
    } else if (ctrl.newsResult != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('뉴스 수집 완료'),
          backgroundColor: tc.profit,
        ),
      );
    }
  }
}

// ── 서버 관리 탭 ──
// ── AI 모델 관리 탭 ──
//
// 모델 다운로드 상태 확인, 개별/전체 다운로드, 기존 데이터 감지를 제공한다.

class _ModelsTab extends StatefulWidget {
  const _ModelsTab();

  @override
  State<_ModelsTab> createState() => _ModelsTabState();
}

class _ModelsTabState extends State<_ModelsTab> {
  Timer? _pollTimer;
  DataStatus? _dataStatus;
  ModelsStatus? _modelsStatus;
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadAll());
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }

  /// 모델 + 데이터 상태를 동시 조회한다.
  Future<void> _loadAll() async {
    setState(() { _isLoading = true; _error = null; });
    final service = SetupService();
    try {
      final results = await Future.wait([
        service.getModelsStatus(),
        service.getDataStatus(),
      ]);
      if (!mounted) return;
      setState(() {
        _modelsStatus = results[0] as ModelsStatus;
        _dataStatus = results[1] as DataStatus;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() { _error = '서버 연결 실패'; _isLoading = false; });
    }
  }

  /// 3초 폴링을 시작한다 (다운로드 진행 중 상태 갱신용).
  void _startPolling() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 3), (_) {
      if (!mounted) return;
      _refreshModels();
    });
  }

  void _stopPolling() { _pollTimer?.cancel(); _pollTimer = null; }

  int _pollFailCount = 0;

  /// 모델 상태만 갱신한다 (폴링용).
  Future<void> _refreshModels() async {
    try {
      final service = SetupService();
      final status = await service.getModelsStatus();
      if (!mounted) return;
      _pollFailCount = 0;
      final downloading = status.models.any(
        (m) => !m.downloaded && m.downloadProgress != null,
      );
      setState(() { _modelsStatus = status; _error = null; });
      // 다운로드가 모두 끝나면 폴링을 중단하고 전체 갱신한다
      if (!downloading && _pollTimer != null) {
        _stopPolling();
        _loadAll();
      }
    } catch (_) {
      _pollFailCount++;
      // 연속 5회 실패 시 폴링을 중단하고 에러를 표시한다
      if (_pollFailCount >= 5 && mounted) {
        _stopPolling();
        setState(() { _error = '서버 연결이 끊어졌습니다. 새로고침하세요.'; });
      }
    }
  }

  /// 특정 모델 또는 전체를 다운로드한다.
  Future<void> _startDownload({List<String>? modelIds}) async {
    try {
      final service = SetupService();
      await service.startModelDownload(modelIds: modelIds);
      if (!mounted) return;
      _startPolling();
      await _refreshModels();
    } catch (e) {
      if (!mounted) return;
      setState(() { _error = '다운로드 시작 실패: $e'; });
    }
  }

  /// 다운로드를 취소한다.
  Future<void> _cancelDownload() async {
    try {
      final service = SetupService();
      await service.cancelModelDownload();
      if (!mounted) return;
      _stopPolling();
      await _refreshModels();
    } catch (e) {
      if (!mounted) return;
      _stopPolling();
      setState(() { _error = '취소 요청 실패 — 서버 연결을 확인하세요'; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final theme = Theme.of(context);

    if (_isLoading && _modelsStatus == null) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null && _modelsStatus == null) {
      return Center(child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.cloud_off, size: 48, color: tc.textTertiary),
          AppSpacing.vGapMd,
          Text(_error!, style: TextStyle(color: tc.textSecondary)),
          AppSpacing.vGapMd,
          FilledButton.icon(
            onPressed: _loadAll,
            icon: const Icon(Icons.refresh, size: 18),
            label: const Text('재시도'),
          ),
        ],
      ));
    }

    final models = _modelsStatus?.models ?? [];
    final downloading = models.any(
      (m) => !m.downloaded && m.downloadProgress != null,
    );
    final allDownloaded = models.isNotEmpty && models.every((m) => m.downloaded);
    final progress = _overallProgress(models);
    final dataFiles = _dataStatus?.files ?? [];

    return RefreshIndicator(
      onRefresh: _loadAll,
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: AppSpacing.paddingScreen,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ── 기존 데이터 감지 섹션 ──
            if (_dataStatus != null) ...[
              _buildDataDetectionSection(tc, theme, dataFiles),
              AppSpacing.vGapXl,
            ],
            // ── 모델 다운로드 섹션 ──
            Text('AI 모델 관리', style: theme.textTheme.titleLarge?.copyWith(
              color: tc.textPrimary, fontWeight: FontWeight.bold)),
            AppSpacing.vGapSm,
            Text(
              '로컬 분류/번역에 필요한 GGUF 모델입니다. 총 약 ${_modelsStatus?.totalSizeGb.toStringAsFixed(0) ?? "23"}GB',
              style: theme.textTheme.bodyMedium?.copyWith(color: tc.textSecondary),
            ),
            AppSpacing.vGapMd,
            // 전체 상태 요약 카드
            _buildSummaryCard(tc, theme, allDownloaded),
            AppSpacing.vGapLg,
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
              AppSpacing.vGapLg,
            ],
            // 개별 모델 카드 (개별 다운로드 버튼 포함)
            ...models.map((m) => Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: _buildModelCard(tc, theme, m, downloading),
            )),
            AppSpacing.vGapLg,
            // 전체 다운로드/취소 버튼
            if (!allDownloaded) ...[
              Row(children: [
                Expanded(child: downloading
                  ? OutlinedButton.icon(
                      onPressed: _cancelDownload,
                      icon: Icon(Icons.cancel, size: 18, color: tc.loss),
                      label: Text('취소', style: TextStyle(color: tc.loss)))
                  : FilledButton.icon(
                      onPressed: () => _startDownload(),
                      icon: const Icon(Icons.download, size: 18),
                      label: const Text('전체 다운로드'))),
              ]),
              AppSpacing.vGapMd,
            ],
            // 경로 정보
            if (_dataStatus != null) ...[
              AppSpacing.vGapMd,
              _buildPathInfo(tc, theme),
            ],
            AppSpacing.vGapXl,
          ],
        ),
      ),
    );
  }

  /// 기존 데이터 감지 섹션을 빌드한다.
  Widget _buildDataDetectionSection(
    TradingColors tc, ThemeData theme, List<DataFileInfo> files,
  ) {
    final hasData = _dataStatus!.hasPreviousInstall;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(children: [
          Icon(hasData ? Icons.history : Icons.new_releases,
            color: hasData ? tc.info : tc.textTertiary, size: 22),
          AppSpacing.hGapSm,
          Text(hasData ? '기존 설치 데이터 감지됨' : '새로운 설치',
            style: theme.textTheme.titleMedium?.copyWith(
              color: tc.textPrimary, fontWeight: FontWeight.w600)),
        ]),
        AppSpacing.vGapMd,
        // 데이터 파일 목록
        ...files.map((f) => Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(children: [
            Icon(f.exists ? Icons.check_circle : Icons.radio_button_unchecked,
              color: f.exists ? tc.profit : tc.textTertiary, size: 16),
            AppSpacing.hGapSm,
            Expanded(child: Text(f.description,
              style: theme.textTheme.bodySmall?.copyWith(
                color: f.exists ? tc.textPrimary : tc.textTertiary))),
            Text(f.exists ? _formatSize(f.sizeBytes) : '없음',
              style: theme.textTheme.bodySmall?.copyWith(
                color: f.exists ? tc.textSecondary : tc.textTertiary)),
          ]),
        )),
      ],
    );
  }

  /// 모델 상태 요약 카드를 빌드한다.
  Widget _buildSummaryCard(TradingColors tc, ThemeData theme, bool allDone) {
    final st = _modelsStatus;
    return Card(
      margin: EdgeInsets.zero,
      color: allDone ? tc.profit.withValues(alpha: 0.08) : tc.infoBg,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusMd,
        side: BorderSide(color: allDone
          ? tc.profit.withValues(alpha: 0.3) : tc.info.withValues(alpha: 0.3)),
      ),
      child: Padding(
        padding: AppSpacing.paddingCard,
        child: Row(children: [
          Icon(allDone ? Icons.check_circle : Icons.info_outline,
            color: allDone ? tc.profit : tc.info, size: 20),
          AppSpacing.hGapMd,
          Expanded(child: Text(
            allDone
              ? '모든 모델 준비 완료 (${st?.downloadedCount ?? 0}/${st?.totalCount ?? 0})'
              : '${st?.downloadedCount ?? 0}/${st?.totalCount ?? 0}개 다운로드됨 — 미완료 모델은 개별 또는 전체 다운로드 가능',
            style: TextStyle(
              color: allDone ? tc.profit : tc.info, fontSize: 13),
          )),
        ]),
      ),
    );
  }

  /// 개별 모델 카드 (개별 다운로드 버튼 포함).
  Widget _buildModelCard(
    TradingColors tc, ThemeData theme, ModelInfo m, bool anyDownloading,
  ) {
    final isDownloading = !m.downloaded && m.downloadProgress != null;
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
            Row(children: [
              Icon(
                m.downloaded ? Icons.check_circle
                  : isDownloading ? Icons.downloading : Icons.download,
                color: m.downloaded ? tc.profit
                  : isDownloading ? tc.info : tc.textTertiary,
                size: 24,
              ),
              AppSpacing.hGapMd,
              Expanded(child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(m.name, style: theme.textTheme.titleSmall,
                    overflow: TextOverflow.ellipsis),
                  AppSpacing.vGapXs,
                  Text(
                    m.downloaded
                      ? '${m.sizeGb.toStringAsFixed(1)} GB · 완료'
                      : '${m.sizeGb.toStringAsFixed(1)} GB',
                    style: TextStyle(
                      color: m.downloaded ? tc.profit : tc.textSecondary,
                      fontSize: 12),
                  ),
                ],
              )),
              if (isDownloading)
                Text('${(m.downloadProgress! * 100).toStringAsFixed(0)}%',
                  style: TextStyle(color: tc.info, fontWeight: FontWeight.w600))
              else if (!m.downloaded && !anyDownloading)
                SizedBox(
                  height: 32,
                  child: OutlinedButton(
                    onPressed: () => _startDownload(modelIds: [m.modelId]),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      textStyle: const TextStyle(fontSize: 12),
                    ),
                    child: const Text('다운로드'),
                  ),
                ),
            ]),
            if (isDownloading) ...[
              AppSpacing.vGapSm,
              ClipRRect(
                borderRadius: AppSpacing.borderRadiusSm,
                child: LinearProgressIndicator(
                  value: m.downloadProgress,
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

  /// 저장 경로 정보를 표시한다.
  Widget _buildPathInfo(TradingColors tc, ThemeData theme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('저장 경로', style: theme.textTheme.titleSmall?.copyWith(
          color: tc.textSecondary)),
        AppSpacing.vGapSm,
        _pathRow(tc, theme, '모델', _dataStatus!.modelsDir),
        AppSpacing.vGapXs,
        _pathRow(tc, theme, '데이터', _dataStatus!.dataDir),
      ],
    );
  }

  Widget _pathRow(TradingColors tc, ThemeData theme, String label, String path) {
    return Row(children: [
      SizedBox(width: 50, child: Text(label,
        style: theme.textTheme.bodySmall?.copyWith(color: tc.textTertiary))),
      Expanded(child: Text(path,
        style: theme.textTheme.bodySmall?.copyWith(
          color: tc.textSecondary, fontFamily: 'monospace', fontSize: 11),
        overflow: TextOverflow.ellipsis)),
    ]);
  }

  double _overallProgress(List<ModelInfo> models) {
    if (models.isEmpty) return 0.0;
    var total = 0.0;
    for (final m in models) {
      total += m.downloaded ? 1.0 : (m.downloadProgress ?? 0.0);
    }
    return total / models.length;
  }

  String _formatSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1048576) return '${(bytes / 1024).toStringAsFixed(0)} KB';
    if (bytes < 1073741824) return '${(bytes / 1048576).toStringAsFixed(1)} MB';
    return '${(bytes / 1073741824).toStringAsFixed(1)} GB';
  }
}


// ── 서버 제어 탭 ──
//
// TradingControlProvider.isConnected를 기본 서버 상태로 사용한다.
// 서버는 AppBar SERVER 버튼(subprocess) 또는 LaunchAgent로 시작될 수 있다.

class _ServerTab extends StatefulWidget {
  const _ServerTab();

  @override
  State<_ServerTab> createState() => _ServerTabState();
}

class _ServerTabState extends State<_ServerTab> {
  final _launcher = ServerLauncher.instance;
  LaunchAgentStatus? _agentStatus;
  bool _isBusy = false;
  String? _message;
  Timer? _refreshTimer;

  @override
  void initState() {
    super.initState();
    _refreshAgentStatus();
    _refreshTimer = Timer.periodic(
      const Duration(seconds: 5),
      (_) => _refreshAgentStatus(),
    );
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    super.dispose();
  }

  Future<void> _refreshAgentStatus() async {
    final status = await _launcher.getLaunchAgentStatus();
    if (mounted) setState(() => _agentStatus = status);
  }

  /// LaunchAgent 액션을 실행하고 TradingControlProvider 상태를 즉시 동기화한다.
  ///
  /// [isStop]이 true이면 서버 중지로 판단하여 markServerStopped()를 호출하고,
  /// false이면 시작/재시작으로 판단하여 syncAfterServerStart()를 호출한다.
  Future<void> _runAction(
    Future<ServerLaunchResult> Function() action, {
    bool isStop = false,
  }) async {
    setState(() {
      _isBusy = true;
      _message = null;
    });
    final result = await action();
    await _refreshAgentStatus();
    // LaunchAgent 시작/중지 후 TradingControlProvider 상태를 즉시 동기화한다.
    // 이를 통해 AppBar의 SERVER/OFF/START/NEWS 버튼이 즉시 반영된다.
    if (mounted) {
      final ctrl = context.read<TradingControlProvider>();
      if (isStop) {
        ctrl.markServerStopped();
      } else {
        await ctrl.syncAfterServerStart();
      }
    }
    if (mounted) {
      setState(() {
        _isBusy = false;
        _message = result.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    final tc = context.tc;

    return Consumer<TradingControlProvider>(
      builder: (context, ctrl, _) {
        final isConnected = ctrl.isConnected;
        final agentStatus = _agentStatus;

        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            // 서버 상태 카드
            StaggeredFadeSlide(
              index: 0,
              child: GlassCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SectionHeader(title: t('server_status')),
                    AppSpacing.vGapMd,
                    // 실제 서버 연결 상태 (헬스체크 기반)
                    _buildStatusRow(
                      tc,
                      '서버 연결',
                      isConnected ? '연결됨 (포트 ${_launcher.activePort ?? "?"})'
                          : '미연결',
                      isConnected ? tc.profit : tc.loss,
                    ),
                    AppSpacing.vGapSm,
                    // 매매 상태
                    _buildStatusRow(
                      tc,
                      '매매 상태',
                      ctrl.isRunning ? '자동매매 실행 중' : '대기',
                      ctrl.isRunning ? tc.profit : tc.textTertiary,
                    ),
                    AppSpacing.vGapSm,
                    // LaunchAgent 상태
                    _buildStatusRow(
                      tc,
                      t('server_agent_status'),
                      agentStatus == null
                          ? t('server_checking')
                          : agentStatus.loaded
                              ? t('server_loaded')
                              : t('server_unloaded'),
                      agentStatus?.loaded == true
                          ? tc.textSecondary
                          : tc.textTertiary,
                    ),
                    if (agentStatus?.isRunning == true) ...[
                      AppSpacing.vGapSm,
                      _buildStatusRow(
                        tc,
                        'LaunchAgent PID',
                        '${agentStatus!.pid}',
                        tc.textSecondary,
                      ),
                    ],
                  ],
                ),
              ),
            ),
            AppSpacing.vGapLg,

            // 제어 버튼들
            StaggeredFadeSlide(
              index: 1,
              child: GlassCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SectionHeader(title: t('server_control')),
                    AppSpacing.vGapMd,
                    Row(
                      children: [
                        Expanded(
                          child: _buildActionButton(
                            icon: Icons.play_arrow_rounded,
                            label: t('server_start'),
                            color: tc.profit,
                            onPressed: _isBusy || isConnected
                                ? null
                                : () => _runAction(
                                    _launcher.startViaLaunchAgent),
                          ),
                        ),
                        AppSpacing.hGapMd,
                        Expanded(
                          child: _buildActionButton(
                            icon: Icons.stop_rounded,
                            label: t('server_stop'),
                            color: tc.loss,
                            onPressed: _isBusy || !isConnected || !ctrl.canStopServer
                                ? null
                                : () => _runAction(
                                    _launcher.stopViaLaunchAgent,
                                    isStop: true),
                          ),
                        ),
                        AppSpacing.hGapMd,
                        Expanded(
                          child: _buildActionButton(
                            icon: Icons.refresh_rounded,
                            label: t('server_restart'),
                            color: tc.primary,
                            onPressed: _isBusy || !ctrl.canStopServer
                                ? null
                                : () => _runAction(
                                    _launcher.restartViaLaunchAgent),
                          ),
                        ),
                      ],
                    ),
                    // 앱 이동 시 LaunchAgent 재설치 안내
                    if (agentStatus?.loaded == true) ...[
                      AppSpacing.vGapSm,
                      Text(
                        '앱을 다른 위치로 이동하면 LaunchAgent를 재설치해야 합니다.',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: tc.textTertiary,
                        ),
                      ),
                    ],
                    if (_isBusy) ...[
                      AppSpacing.vGapMd,
                      const LinearProgressIndicator(),
                    ],
                    if (_message != null) ...[
                      AppSpacing.vGapMd,
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: tc.surface,
                          borderRadius: AppSpacing.borderRadiusMd,
                          border: Border.all(
                            color: tc.surfaceBorder.withValues(alpha: 0.3),
                          ),
                        ),
                        child: Text(
                          _message!,
                          style: AppTypography.bodySmall,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            AppSpacing.vGapLg,

            // 서버 로그
            StaggeredFadeSlide(
              index: 2,
              child: GlassCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        SectionHeader(title: t('server_logs')),
                        IconButton(
                          icon: Icon(
                            Icons.refresh_rounded,
                            size: 18,
                            color: tc.textTertiary,
                          ),
                          onPressed: () => setState(() {}),
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(
                            minWidth: 32,
                            minHeight: 32,
                          ),
                        ),
                      ],
                    ),
                    AppSpacing.vGapSm,
                    Container(
                      width: double.infinity,
                      height: 200,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: tc.background,
                        borderRadius: AppSpacing.borderRadiusMd,
                        border: Border.all(
                          color: tc.surfaceBorder.withValues(alpha: 0.3),
                        ),
                      ),
                      child: SingleChildScrollView(
                        reverse: true,
                        child: Text(
                          _launcher.serverLogs.isEmpty
                              ? t('server_no_logs')
                              : _launcher.serverLogs.join('\n'),
                          style: AppTypography.bodySmall.copyWith(
                            fontFamily: 'monospace',
                            fontSize: 11,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            AppSpacing.vGapLg,

            // 앱 삭제 섹션
            StaggeredFadeSlide(
              index: 3,
              child: GlassCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SectionHeader(title: '앱 삭제'),
                    AppSpacing.vGapSm,
                    Text(
                      'LaunchAgent, 앱 데이터, 로그, 환경설정을 삭제합니다.',
                      style: AppTypography.bodySmall.copyWith(
                        color: tc.textSecondary,
                      ),
                    ),
                    AppSpacing.vGapLg,
                    Row(
                      children: [
                        Expanded(
                          child: _buildActionButton(
                            icon: Icons.delete_forever_rounded,
                            label: '완전 삭제',
                            color: tc.loss,
                            onPressed: _isBusy
                                ? null
                                : () => _showUninstallDialog(
                                      context, tc, keepData: false),
                          ),
                        ),
                        AppSpacing.hGapMd,
                        Expanded(
                          child: _buildActionButton(
                            icon: Icons.delete_outline_rounded,
                            label: '데이터 보존 삭제',
                            color: tc.warning,
                            onPressed: _isBusy
                                ? null
                                : () => _showUninstallDialog(
                                      context, tc, keepData: true),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            AppSpacing.vGapXxl,
          ],
        );
      },
    );
  }

  /// 삭제 확인 다이얼로그를 표시한다.
  Future<void> _showUninstallDialog(
    BuildContext context,
    TradingColors tc, {
    required bool keepData,
  }) async {
    // 미리보기를 가져온다
    UninstallPreview? preview;
    try {
      final service = SetupService();
      preview = await service.getUninstallPreview();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('삭제 항목 조회 실패'),
            backgroundColor: tc.loss,
          ),
        );
      }
      return;
    }

    if (!mounted) return;

    // 삭제 대상 목록을 다이얼로그로 보여준다
    final existingItems =
        preview.items.where((item) => item.exists).toList();

    final sizeStr = _formatBytes(preview.totalSizeBytes);

    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) {
        return AlertDialog(
          backgroundColor: tc.surfaceElevated,
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusXl,
            side: BorderSide(
              color: tc.loss.withValues(alpha: 0.4),
              width: 1,
            ),
          ),
          title: Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: tc.loss.withValues(alpha: 0.12),
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  Icons.warning_amber_rounded,
                  color: tc.loss,
                  size: 22,
                ),
              ),
              AppSpacing.hGapMd,
              Text(
                keepData ? '데이터 보존 삭제' : '완전 삭제',
                style: AppTypography.displaySmall,
              ),
            ],
          ),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  keepData
                      ? 'DB와 .env 파일을 보존하고 나머지를 삭제합니다.'
                      : '모든 앱 데이터가 삭제됩니다. 이 작업은 되돌릴 수 없습니다.',
                  style: AppTypography.bodyMedium,
                ),
                AppSpacing.vGapMd,
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: tc.surface,
                    borderRadius: AppSpacing.borderRadiusMd,
                    border: Border.all(
                      color: tc.surfaceBorder.withValues(alpha: 0.3),
                    ),
                  ),
                  constraints: const BoxConstraints(maxHeight: 200),
                  child: SingleChildScrollView(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        for (final item in existingItems)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 4),
                            child: Row(
                              children: [
                                Icon(
                                  _iconForType(item.type),
                                  size: 14,
                                  color: tc.textTertiary,
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    item.description,
                                    style: AppTypography.bodySmall.copyWith(
                                      fontFamily: 'monospace',
                                      fontSize: 11,
                                    ),
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                                if (item.sizeBytes > 0)
                                  Text(
                                    _formatBytes(item.sizeBytes),
                                    style: AppTypography.bodySmall.copyWith(
                                      color: tc.textTertiary,
                                      fontSize: 10,
                                    ),
                                  ),
                              ],
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
                AppSpacing.vGapMd,
                Text(
                  '총 크기: $sizeStr (${existingItems.length}개 항목)',
                  style: AppTypography.bodySmall.copyWith(
                    color: tc.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          actions: [
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(ctx).pop(false),
                    child: const Text('취소'),
                  ),
                ),
                AppSpacing.hGapMd,
                Expanded(
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: tc.loss,
                    ),
                    onPressed: () => Navigator.of(ctx).pop(true),
                    child: const Text('삭제 실행'),
                  ),
                ),
              ],
            ),
          ],
        );
      },
    );

    if (confirmed != true || !mounted) return;

    // 삭제를 실행한다
    setState(() {
      _isBusy = true;
      _message = '삭제 진행 중...';
    });

    try {
      final service = SetupService();
      final result = await service.runUninstall(keepData: keepData);
      if (mounted) {
        setState(() {
          _isBusy = false;
          _message = result.message;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(result.message),
            backgroundColor: result.success ? tc.profit : tc.loss,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isBusy = false;
          _message = '삭제 실패: $e';
        });
      }
    }
  }

  /// 파일 타입에 맞는 아이콘을 반환한다.
  IconData _iconForType(String type) {
    switch (type) {
      case 'launchagent':
        return Icons.schedule_rounded;
      case 'data':
      case 'data_sub':
        return Icons.folder_rounded;
      case 'logs':
        return Icons.article_rounded;
      case 'preferences':
        return Icons.settings_rounded;
      default:
        return Icons.insert_drive_file_rounded;
    }
  }

  /// 바이트를 사람이 읽기 좋은 형태로 변환한다.
  String _formatBytes(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    if (bytes < 1024 * 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
    }
    return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(1)} GB';
  }

  Widget _buildStatusRow(
    TradingColors tc,
    String label,
    String value,
    Color valueColor,
  ) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: AppTypography.bodyMedium),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: valueColor.withValues(alpha: 0.12),
            borderRadius: AppSpacing.borderRadiusSm,
          ),
          child: Text(
            value,
            style: AppTypography.numberSmall.copyWith(color: valueColor),
          ),
        ),
      ],
    );
  }

  Widget _buildActionButton({
    required IconData icon,
    required String label,
    required Color color,
    VoidCallback? onPressed,
  }) {
    return SizedBox(
      height: 48,
      child: ElevatedButton.icon(
        onPressed: onPressed,
        icon: Icon(icon, size: 18),
        label: Text(label, style: const TextStyle(fontSize: 13)),
        style: ElevatedButton.styleFrom(
          backgroundColor: color.withValues(alpha: 0.15),
          foregroundColor: color,
          disabledBackgroundColor:
              color.withValues(alpha: 0.05),
          disabledForegroundColor:
              color.withValues(alpha: 0.3),
          padding: const EdgeInsets.symmetric(horizontal: 8),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
        ),
      ),
    );
  }
}
