import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/trade_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../animations/animation_utils.dart';

class StrategySettings extends StatefulWidget {
  const StrategySettings({super.key});

  @override
  State<StrategySettings> createState() => _StrategySettingsState();
}

class _StrategySettingsState extends State<StrategySettings> {
  final Map<String, TextEditingController> _controllers = {};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<TradeProvider>().loadStrategyParams();
    });
  }

  @override
  void dispose() {
    for (var controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Strategy', style: AppTypography.displaySmall),
      ),
      body: Consumer<TradeProvider>(
        builder: (context, provider, child) {
          if (provider.isLoading && provider.strategyParams == null) {
            return Padding(
              padding: AppSpacing.paddingScreen,
              child: Column(
                children: List.generate(4, (i) => Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: ShimmerLoading(
                    width: double.infinity,
                    height: 120,
                    borderRadius: AppSpacing.borderRadiusLg,
                  ),
                )),
              ),
            );
          }

          if (provider.error != null && provider.strategyParams == null) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.cloud_off_rounded, size: 48, color: context.tc.textTertiary),
                  AppSpacing.vGapLg,
                  Text('Error: ${provider.error}', style: AppTypography.bodyMedium),
                  AppSpacing.vGapLg,
                  ElevatedButton(
                    onPressed: () => provider.loadStrategyParams(),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            );
          }

          final params = provider.strategyParams;
          if (params == null) {
            return Center(child: Text('No data', style: AppTypography.bodyLarge));
          }

          return ListView(
            padding: AppSpacing.paddingScreen,
            children: [
              StaggeredFadeSlide(
                index: 0,
                child: _buildParamCard(
                  'Min Confidence', 'min_confidence',
                  params.params['min_confidence']?.toString() ?? '0.7',
                  'Minimum confidence threshold for trade signals (0-1)',
                ),
              ),
              AppSpacing.vGapLg,
              StaggeredFadeSlide(
                index: 1,
                child: _buildParamCard(
                  'Take Profit %', 'take_profit_pct',
                  params.params['take_profit_pct']?.toString() ?? '5.0',
                  'Target profit percentage',
                ),
              ),
              AppSpacing.vGapLg,
              StaggeredFadeSlide(
                index: 2,
                child: _buildParamCard(
                  'Stop Loss %', 'stop_loss_pct',
                  params.params['stop_loss_pct']?.toString() ?? '3.0',
                  'Maximum loss tolerance percentage',
                ),
              ),
              AppSpacing.vGapLg,
              StaggeredFadeSlide(
                index: 3,
                child: _buildParamCard(
                  'Trailing Stop %', 'trailing_stop_pct',
                  params.params['trailing_stop_pct']?.toString() ?? '2.0',
                  'Trailing stop from high watermark',
                ),
              ),
              AppSpacing.vGapLg,
              StaggeredFadeSlide(
                index: 4,
                child: _buildParamCard(
                  'Max Position %', 'max_position_pct',
                  params.params['max_position_pct']?.toString() ?? '30.0',
                  'Maximum single position allocation',
                ),
              ),
              AppSpacing.vGapXxl,
              StaggeredFadeSlide(
                index: 5,
                child: _buildRegimesCard(params),
              ),
              AppSpacing.vGapXxl,
            ],
          );
        },
      ),
    );
  }

  Widget _buildParamCard(
    String title,
    String paramKey,
    String defaultValue,
    String description,
  ) {
    if (!_controllers.containsKey(paramKey)) {
      _controllers[paramKey] = TextEditingController(text: defaultValue);
    }

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: AppTypography.headlineMedium),
          AppSpacing.vGapSm,
          Text(description, style: AppTypography.bodySmall),
          AppSpacing.vGapLg,
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _controllers[paramKey],
                  keyboardType: TextInputType.number,
                  style: AppTypography.numberSmall,
                ),
              ),
              AppSpacing.hGapMd,
              ElevatedButton(
                onPressed: () => _saveParam(paramKey),
                child: const Text('Save'),
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

  Widget _buildRegimesCard(dynamic params) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('시장 레짐', style: AppTypography.headlineMedium),
          AppSpacing.vGapSm,
          Text(
            '시장 상황별 전략 파라미터',
            style: AppTypography.bodySmall,
          ),
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

  void _saveParam(String paramKey) async {
    final value = _controllers[paramKey]?.text;
    if (value == null || value.isEmpty) return;

    final numValue = double.tryParse(value);
    if (numValue == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: const Text('Please enter a valid number'),
          backgroundColor: context.tc.loss,
        ),
      );
      return;
    }

    try {
      final provider = context.read<TradeProvider>();
      final currentParams = Map<String, dynamic>.from(
        provider.strategyParams?.params ?? {},
      );
      currentParams[paramKey] = numValue;
      await provider.updateStrategyParams(currentParams);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Parameter saved'),
            backgroundColor: context.tc.profit,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Save failed: $e'),
            backgroundColor: context.tc.loss,
          ),
        );
      }
    }
  }
}
