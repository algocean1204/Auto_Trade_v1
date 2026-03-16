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

  /// V2 전략 파라미터 정의 (key, 표시 이름, 설명, 기본값)이다.
  static const _paramDefs = <_ParamDef>[
    _ParamDef('beast_min_confidence', '최소 신뢰도', '매매 신호 최소 신뢰도 임계값 (0-1)', '0.7'),
    _ParamDef('default_position_size_pct', '기본 포지션 %', '기본 포지션 배분 비율', '10.0'),
    _ParamDef('max_position_pct', '최대 포지션 %', '단일 포지션 최대 비율', '23.75'),
    _ParamDef('beast_min_obi', '최소 OBI', 'Order Book Imbalance 최소 임계값', '0.2'),
    _ParamDef('obi_threshold', 'OBI 게이트 임계값', 'OBI 게이트 통과 기준', '0.1'),
    _ParamDef('ml_threshold', 'ML 임계값', 'ML 모델 예측 신뢰도 임계값', '0.3'),
    _ParamDef('friction_hurdle', '거래비용 허들', '거래비용 대비 최소 기대수익 비율', '0.7'),
    _ParamDef('beast_max_daily', '일일 최대 거래', '하루 최대 거래 횟수', '10'),
    _ParamDef('beast_cooldown_seconds', '쿨다운 (초)', '연속 거래 간 최소 대기 시간', '180'),
    _ParamDef('pyramid_level1_pct', '피라미딩 1단계 %', '1차 추가 매수 진입 수익률', '1.5'),
    _ParamDef('pyramid_level2_pct', '피라미딩 2단계 %', '2차 추가 매수 진입 수익률', '3.0'),
    _ParamDef('pyramid_level3_pct', '피라미딩 3단계 %', '3차 추가 매수 진입 수익률', '5.0'),
  ];

  /// 토글 스위치 파라미터 정의이다.
  static const _toggleDefs = <_ToggleDef>[
    _ToggleDef('beast_mode_enabled', 'Beast Mode', '고빈도 단타 전략 활성화'),
    _ToggleDef('pyramiding_enabled', 'Pyramiding', '수익 구간 추가 매수 활성화'),
    _ToggleDef('stat_arb_enabled', 'Stat Arb', '통계적 차익거래 전략 활성화'),
    _ToggleDef('news_fading_enabled', 'News Fading', '뉴스 기반 역추세 전략 활성화'),
    _ToggleDef('wick_catcher_enabled', 'Wick Catcher', '급락 꼬리 잡기 전략 활성화'),
  ];

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
              // 토글 스위치 섹션
              StaggeredFadeSlide(
                index: 0,
                child: _buildTogglesCard(params.params, provider),
              ),
              AppSpacing.vGapXxl,
              // 수치 파라미터 섹션
              ..._paramDefs.asMap().entries.map((entry) {
                final idx = entry.key;
                final def = entry.value;
                return Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: StaggeredFadeSlide(
                    index: idx + 1,
                    child: _buildParamCard(
                      def.label,
                      def.key,
                      params.params[def.key]?.toString() ?? def.defaultValue,
                      def.description,
                    ),
                  ),
                );
              }),
              AppSpacing.vGapXxl,
              // 레짐 섹션
              StaggeredFadeSlide(
                index: _paramDefs.length + 1,
                child: _buildRegimesCard(params),
              ),
              AppSpacing.vGapXxl,
            ],
          );
        },
      ),
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
            final enabled = params[def.key] == true;
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(def.label, style: AppTypography.labelLarge),
                        Text(def.description, style: AppTypography.bodySmall),
                      ],
                    ),
                  ),
                  Switch(
                    value: enabled,
                    onChanged: (value) {
                      final updated = Map<String, dynamic>.from(params);
                      updated[def.key] = value;
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

  Widget _buildParamCard(
    String title,
    String paramKey,
    String defaultValue,
    String description,
  ) {
    if (!_controllers.containsKey(paramKey)) {
      _controllers[paramKey] = TextEditingController(text: defaultValue);
    } else if (_controllers[paramKey]!.text.isEmpty ||
        _controllers[paramKey]!.text == '0' ||
        _controllers[paramKey]!.text == '0.0') {
      _controllers[paramKey]!.text = defaultValue;
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
                child: const Text('저장'),
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
          if (params.regimes.isEmpty)
            Text(
              '레짐 설정이 없다 (data/strategy_params.json에 regimes 키 추가 필요)',
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

  void _saveParam(String paramKey) async {
    final value = _controllers[paramKey]?.text;
    if (value == null || value.isEmpty) return;

    final numValue = double.tryParse(value);
    if (numValue == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: const Text('유효한 숫자를 입력해주세요'),
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
            content: const Text('저장 완료'),
            backgroundColor: context.tc.profit,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('저장 실패: $e'),
            backgroundColor: context.tc.loss,
          ),
        );
      }
    }
  }
}

/// 수치 파라미터 정의이다.
class _ParamDef {
  final String key;
  final String label;
  final String description;
  final String defaultValue;

  const _ParamDef(this.key, this.label, this.description, this.defaultValue);
}

/// 토글 파라미터 정의이다.
class _ToggleDef {
  final String key;
  final String label;
  final String description;

  const _ToggleDef(this.key, this.label, this.description);
}
