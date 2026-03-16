import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
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
import '../widgets/ticker_add_dialog.dart';
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
    _tabController = TabController(length: 6, vsync: this);
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
                    Tab(text: t('server_tab')),
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
                const _ServerTab(),
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

  Future<void> _runAction(
    Future<ServerLaunchResult> Function() action,
  ) async {
    setState(() {
      _isBusy = true;
      _message = null;
    });
    final result = await action();
    await _refreshAgentStatus();
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
                            onPressed: _isBusy || !isConnected
                                ? null
                                : () => _runAction(
                                    _launcher.stopViaLaunchAgent),
                          ),
                        ),
                        AppSpacing.hGapMd,
                        Expanded(
                          child: _buildActionButton(
                            icon: Icons.refresh_rounded,
                            label: t('server_restart'),
                            color: tc.primary,
                            onPressed: _isBusy
                                ? null
                                : () => _runAction(
                                    _launcher.restartViaLaunchAgent),
                          ),
                        ),
                      ],
                    ),
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
            AppSpacing.vGapXxl,
          ],
        );
      },
    );
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
