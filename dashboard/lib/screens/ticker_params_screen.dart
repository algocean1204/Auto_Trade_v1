import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/ticker_params_models.dart';
import '../providers/locale_provider.dart';
import '../services/api_service.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/section_header.dart';
import '../widgets/empty_state.dart';
import '../widgets/confirmation_dialog.dart';
import '../animations/animation_utils.dart';

/// 설정 탭에 삽입되는 AI 종목별 전략 파라미터 탭 위젯이다.
class TickerParamsTab extends StatefulWidget {
  const TickerParamsTab({super.key});

  @override
  State<TickerParamsTab> createState() => _TickerParamsTabState();
}

class _TickerParamsTabState extends State<TickerParamsTab> {
  List<TickerParamsSummary> _summaries = [];
  bool _isLoading = false;
  bool _isOptimizing = false;
  String? _error;
  String? _selectedTicker;
  TickerParamsDetail? _detail;
  bool _isLoadingDetail = false;
  String? _detailError;

  // 유저 오버라이드 편집 상태
  final Map<String, TextEditingController> _overrideControllers = {};
  final Map<String, bool> _overrideEnabled = {};
  bool _hasUnsavedChanges = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadSummaries());
  }

  @override
  void dispose() {
    for (final c in _overrideControllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _loadSummaries() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final api = context.read<ApiService>();
      final data = await api.getTickerParams();
      if (mounted) {
        setState(() {
          _summaries = data;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _loadDetail(String ticker) async {
    setState(() {
      _selectedTicker = ticker;
      _isLoadingDetail = true;
      _detailError = null;
      _hasUnsavedChanges = false;
    });

    // 이전 컨트롤러 정리
    for (final c in _overrideControllers.values) {
      c.dispose();
    }
    _overrideControllers.clear();
    _overrideEnabled.clear();

    try {
      final api = context.read<ApiService>();
      final data = await api.getTickerParamsDetail(ticker);
      if (mounted) {
        setState(() {
          _detail = data;
          _isLoadingDetail = false;
          _initOverrideControllers(data);
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _detailError = e.toString();
          _isLoadingDetail = false;
        });
      }
    }
  }

  void _initOverrideControllers(TickerParamsDetail detail) {
    const paramKeys = [
      'take_profit_pct',
      'stop_loss_pct',
      'trailing_stop_pct',
      'min_confidence',
      'max_position_pct',
      'max_hold_days',
    ];

    for (final key in paramKeys) {
      final hasOverride = detail.userOverride.containsKey(key);
      final overrideValue = detail.userOverride[key];
      _overrideEnabled[key] = hasOverride;
      _overrideControllers[key] = TextEditingController(
        text: hasOverride ? overrideValue.toString() : '',
      );
    }
  }

  Future<void> _triggerOptimization() async {
    final t = context.read<LocaleProvider>().t;
    setState(() => _isOptimizing = true);

    try {
      final api = context.read<ApiService>();
      await api.triggerAiOptimization();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(t('ai_optimization_started')),
            backgroundColor: context.tc.profit,
          ),
        );
        // 재분석 후 목록 새로고침
        await _loadSummaries();
      }
    } catch (e) {
      if (mounted) {
        final errMsg = e.toString();
        String userMsg;
        if (errMsg.contains('404')) {
          userMsg = 'AI 재분석 엔드포인트를 찾을 수 없습니다 (404). 서버 버전을 확인하세요.';
        } else if (errMsg.contains('503')) {
          userMsg = '시스템이 초기화 중입니다 (503). 잠시 후 다시 시도하세요.';
        } else if (errMsg.contains('401') || errMsg.contains('403')) {
          userMsg = '인증 오류입니다 (${errMsg.contains('401') ? '401' : '403'}). API 키를 확인하세요.';
        } else if (errMsg.contains('ServerUnreachable') ||
            errMsg.contains('Connection refused') ||
            errMsg.contains('SocketException')) {
          userMsg = '서버에 연결할 수 없습니다. 서버 실행 상태를 확인하세요.';
        } else {
          userMsg = 'AI 재분석 실패: $errMsg';
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(userMsg),
            backgroundColor: context.tc.loss,
            duration: const Duration(seconds: 5),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isOptimizing = false);
    }
  }

  Future<void> _saveOverrides() async {
    if (_detail == null || _selectedTicker == null) return;
    final t = context.read<LocaleProvider>().t;

    final overrides = <String, dynamic>{};
    for (final entry in _overrideEnabled.entries) {
      if (entry.value) {
        final text = _overrideControllers[entry.key]?.text ?? '';
        if (text.isEmpty) continue;
        final numValue = double.tryParse(text);
        if (numValue == null) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(t('enter_valid_number')),
              backgroundColor: context.tc.loss,
            ),
          );
          return;
        }
        overrides[entry.key] = numValue;
      }
    }

    try {
      final api = context.read<ApiService>();
      await api.setTickerOverride(_selectedTicker!, overrides);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(t('parameter_saved')),
            backgroundColor: context.tc.profit,
          ),
        );
        setState(() => _hasUnsavedChanges = false);
        // 상세/목록 새로고침
        await _loadDetail(_selectedTicker!);
        await _loadSummaries();
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

  Future<void> _clearAllOverrides() async {
    if (_selectedTicker == null) return;
    final t = context.read<LocaleProvider>().t;

    final confirmed = await ConfirmationDialog.show(
      context,
      title: t('tp_reset_overrides'),
      message: t('tp_reset_overrides_msg')
          .replaceAll('{ticker}', _selectedTicker!),
      confirmLabel: t('confirm'),
      confirmColor: context.tc.loss,
      icon: Icons.restore_rounded,
    );

    if (!confirmed || !mounted) return;

    try {
      final api = context.read<ApiService>();
      await api.clearTickerOverride(_selectedTicker!);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(t('tp_overrides_cleared')),
            backgroundColor: context.tc.profit,
          ),
        );
        await _loadDetail(_selectedTicker!);
        await _loadSummaries();
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

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    if (_isLoading && _summaries.isEmpty) {
      return Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: List.generate(
            4,
            (i) => Padding(
              padding: const EdgeInsets.only(bottom: 16),
              child: ShimmerLoading(
                width: double.infinity,
                height: 60,
                borderRadius: AppSpacing.borderRadiusLg,
              ),
            ),
          ),
        ),
      );
    }

    if (_error != null && _summaries.isEmpty) {
      return ErrorState(
        message: _error ?? '',
        onRetry: _loadSummaries,
      );
    }

    if (_summaries.isEmpty) {
      return EmptyState(
        icon: Icons.auto_awesome_rounded,
        title: t('tp_no_data'),
        subtitle: t('tp_no_data_hint'),
        actionLabel: t('tp_trigger_ai'),
        onAction: _triggerOptimization,
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 900;
        if (isWide) {
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                flex: 5,
                child: _buildSummaryList(t),
              ),
              if (_selectedTicker != null) ...[
                const VerticalDivider(width: 1),
                Expanded(
                  flex: 5,
                  child: _buildDetailPanel(t),
                ),
              ],
            ],
          );
        } else {
          return _selectedTicker != null
              ? _buildDetailPanel(t, showBack: true)
              : _buildSummaryList(t);
        }
      },
    );
  }

  Widget _buildSummaryList(String Function(String) t) {
    final tc = context.tc;
    final lastUpdated = _summaries.isNotEmpty
        ? _summaries.first.aiUpdatedAt ?? '-'
        : '-';

    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        // 헤더: AI 재분석 버튼 + 마지막 분석 시간
        StaggeredFadeSlide(
          index: 0,
          child: GlassCard(
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        t('tp_title'),
                        style: AppTypography.headlineMedium,
                      ),
                      AppSpacing.vGapXs,
                      Text(
                        '${t('tp_last_analysis')}: $lastUpdated',
                        style: AppTypography.bodySmall.copyWith(
                          color: tc.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
                SizedBox(
                  height: 40,
                  child: ElevatedButton.icon(
                    onPressed: _isOptimizing ? null : _triggerOptimization,
                    icon: _isOptimizing
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              valueColor:
                                  AlwaysStoppedAnimation<Color>(Colors.white),
                            ),
                          )
                        : const Icon(Icons.auto_awesome_rounded, size: 18),
                    label: Text(t('tp_trigger_ai')),
                  ),
                ),
              ],
            ),
          ),
        ),
        AppSpacing.vGapLg,

        // 종목 리스트
        StaggeredFadeSlide(
          index: 1,
          child: GlassCard(
            padding: const EdgeInsets.all(0),
            child: Column(
              children: [
                // 테이블 헤더
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  decoration: BoxDecoration(
                    color: tc.surface.withValues(alpha: 0.5),
                    borderRadius: const BorderRadius.only(
                      topLeft: Radius.circular(16),
                      topRight: Radius.circular(16),
                    ),
                  ),
                  child: Row(
                    children: [
                      _headerCell(t('ticker'), flex: 2),
                      _headerCell(t('tp_sector'), flex: 2),
                      _headerCell(t('tp_risk'), flex: 2),
                      _headerCell('TP%', flex: 1),
                      _headerCell('SL%', flex: 1),
                      _headerCell('TS%', flex: 1),
                      _headerCell(t('tp_override'), flex: 2),
                    ],
                  ),
                ),
                Divider(
                  height: 1,
                  color: tc.surfaceBorder.withValues(alpha: 0.3),
                ),
                // 종목 행들
                ..._summaries.asMap().entries.map((entry) {
                  final i = entry.key;
                  final s = entry.value;
                  final isSelected = s.ticker == _selectedTicker;
                  return _buildTickerRow(s, isSelected, i);
                }),
              ],
            ),
          ),
        ),
        AppSpacing.vGapXxl,
      ],
    );
  }

  Widget _headerCell(String text, {int flex = 1}) {
    return Expanded(
      flex: flex,
      child: Text(
        text,
        style: AppTypography.labelMedium.copyWith(
          color: context.tc.textTertiary,
        ),
      ),
    );
  }

  Widget _buildTickerRow(
      TickerParamsSummary s, bool isSelected, int index) {
    final tc = context.tc;
    return InkWell(
      onTap: () => _loadDetail(s.ticker),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: isSelected
              ? tc.primary.withValues(alpha: 0.08)
              : Colors.transparent,
          border: Border(
            bottom: BorderSide(
              color: tc.surfaceBorder.withValues(alpha: 0.15),
            ),
          ),
        ),
        child: Row(
          children: [
            // 종목 코드
            Expanded(
              flex: 2,
              child: Text(
                s.ticker,
                style: AppTypography.labelLarge.copyWith(
                  color: isSelected ? tc.primary : null,
                ),
              ),
            ),
            // 섹터
            Expanded(
              flex: 2,
              child: Text(
                s.sector,
                style: AppTypography.bodySmall,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            // 리스크 등급 뱃지
            Expanded(
              flex: 2,
              child: Align(
                alignment: Alignment.centerLeft,
                child: _riskBadge(s.riskGrade),
              ),
            ),
            // TP%
            Expanded(
              flex: 1,
              child: Text(
                s.takeProfitPct.toStringAsFixed(1),
                style: AppTypography.numberSmall.copyWith(fontSize: 13),
              ),
            ),
            // SL%
            Expanded(
              flex: 1,
              child: Text(
                s.stopLossPct.toStringAsFixed(1),
                style: AppTypography.numberSmall.copyWith(
                  fontSize: 13,
                  color: tc.loss,
                ),
              ),
            ),
            // TS%
            Expanded(
              flex: 1,
              child: Text(
                s.trailingStopPct.toStringAsFixed(1),
                style: AppTypography.numberSmall.copyWith(fontSize: 13),
              ),
            ),
            // 오버라이드 표시
            Expanded(
              flex: 2,
              child: s.hasUserOverride
                  ? Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.edit_rounded,
                            size: 14, color: tc.primary),
                        AppSpacing.hGapXs,
                        Text(
                          '${s.overrideCount}',
                          style: AppTypography.bodySmall.copyWith(
                            color: tc.primary,
                          ),
                        ),
                      ],
                    )
                  : Text(
                      '-',
                      style: AppTypography.bodySmall.copyWith(
                        color: tc.textTertiary,
                      ),
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _riskBadge(String grade) {
    final tc = context.tc;
    Color color;
    String label;
    switch (grade.toUpperCase()) {
      case 'HIGH':
        color = tc.loss;
        label = 'HIGH';
        break;
      case 'LOW':
        color = tc.profit;
        label = 'LOW';
        break;
      default:
        color = tc.warning;
        label = 'MED';
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusSm,
      ),
      child: Text(
        label,
        style: AppTypography.labelMedium.copyWith(
          color: color,
          fontSize: 11,
        ),
      ),
    );
  }

  Widget _buildDetailPanel(String Function(String) t,
      {bool showBack = false}) {
    final tc = context.tc;

    if (_isLoadingDetail) {
      return Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            ShimmerLoading(
              width: double.infinity,
              height: 100,
              borderRadius: AppSpacing.borderRadiusLg,
            ),
            AppSpacing.vGapLg,
            ShimmerLoading(
              width: double.infinity,
              height: 200,
              borderRadius: AppSpacing.borderRadiusLg,
            ),
          ],
        ),
      );
    }

    if (_detailError != null) {
      return ErrorState(
        message: _detailError ?? '',
        onRetry: () => _loadDetail(_selectedTicker!),
      );
    }

    if (_detail == null) {
      return const SizedBox.shrink();
    }

    final detail = _detail!;
    final analysis = detail.aiAnalysis;
    final rsi7 = (analysis['rsi_7'] as num?)?.toDouble();
    final rsi14 = (analysis['rsi_14'] as num?)?.toDouble();
    final rsi21 = (analysis['rsi_21'] as num?)?.toDouble();
    final dailyVol = (analysis['daily_volatility'] as num?)?.toDouble();
    final riskGrade = analysis['risk_grade'] as String? ?? 'MEDIUM';

    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        // 상단: 뒤로가기 + 종목명 + 원복 버튼
        Row(
          children: [
            if (showBack)
              IconButton(
                icon: const Icon(Icons.arrow_back_rounded),
                onPressed: () => setState(() {
                  _selectedTicker = null;
                  _detail = null;
                }),
              ),
            Expanded(
              child: Text(
                '${detail.ticker} - ${t('tp_ai_detail')}',
                style: AppTypography.headlineMedium,
              ),
            ),
            if (detail.userOverride.isNotEmpty)
              TextButton.icon(
                onPressed: _clearAllOverrides,
                icon: Icon(Icons.restore_rounded,
                    size: 16, color: tc.loss),
                label: Text(
                  t('tp_reset'),
                  style: AppTypography.bodySmall.copyWith(color: tc.loss),
                ),
              ),
          ],
        ),
        AppSpacing.vGapLg,

        // 기술 지표 카드
        GlassCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SectionHeader(title: t('tp_technical_indicators')),
              Wrap(
                spacing: 16,
                runSpacing: 8,
                children: [
                  if (rsi7 != null)
                    _indicatorChip('RSI(7)', rsi7, tc),
                  if (rsi14 != null)
                    _indicatorChip('RSI(14)', rsi14, tc),
                  if (rsi21 != null)
                    _indicatorChip('RSI(21)', rsi21, tc),
                  if (dailyVol != null)
                    _indicatorChip(
                      t('tp_daily_volatility'),
                      dailyVol,
                      tc,
                      suffix: '%',
                    ),
                ],
              ),
              AppSpacing.vGapSm,
              Row(
                children: [
                  Text(
                    '${t('tp_risk_grade')}: ',
                    style: AppTypography.bodySmall,
                  ),
                  _riskBadge(riskGrade),
                ],
              ),
            ],
          ),
        ),
        AppSpacing.vGapLg,

        // 파라미터 편집 테이블
        GlassCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SectionHeader(title: t('tp_ai_recommended_params')),
              _buildParamTable(detail, t),
            ],
          ),
        ),
        AppSpacing.vGapLg,

        // AI 분석 근거
        if (detail.aiReasoning.isNotEmpty) ...[
          GlassCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SectionHeader(title: t('tp_ai_reasoning')),
                Text(
                  detail.aiReasoning,
                  style: AppTypography.bodyMedium.copyWith(
                    height: 1.6,
                    color: tc.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          AppSpacing.vGapLg,
        ],

        // 저장/취소 버튼
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: () {
                  setState(() {
                    _selectedTicker = null;
                    _detail = null;
                    _hasUnsavedChanges = false;
                  });
                },
                child: Text(t('cancel')),
              ),
            ),
            AppSpacing.hGapMd,
            Expanded(
              child: ElevatedButton.icon(
                onPressed: _hasUnsavedChanges ? _saveOverrides : null,
                icon: const Icon(Icons.save_rounded, size: 18),
                label: Text(t('save')),
              ),
            ),
          ],
        ),
        AppSpacing.vGapXxl,
      ],
    );
  }

  Widget _indicatorChip(
      String label, double value, TradingColors tc,
      {String suffix = ''}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: tc.surface,
        borderRadius: AppSpacing.borderRadiusSm,
        border: Border.all(
          color: tc.surfaceBorder.withValues(alpha: 0.3),
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '$label: ',
            style: AppTypography.bodySmall.copyWith(
              color: tc.textTertiary,
            ),
          ),
          Text(
            '${value.toStringAsFixed(1)}$suffix',
            style: AppTypography.numberSmall.copyWith(
              fontSize: 14,
              color: tc.primary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildParamTable(
      TickerParamsDetail detail, String Function(String) t) {
    final tc = context.tc;

    // 파라미터 정의: (key, displayName)
    final paramDefs = [
      ('take_profit_pct', t('tp_take_profit')),
      ('stop_loss_pct', t('tp_stop_loss')),
      ('trailing_stop_pct', t('tp_trailing_stop')),
      ('min_confidence', t('tp_min_confidence')),
      ('max_position_pct', t('tp_max_position')),
      ('max_hold_days', t('tp_max_hold_days')),
    ];

    return Column(
      children: [
        // 테이블 헤더
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(
            children: [
              Expanded(
                flex: 3,
                child: Text(
                  t('tp_param_name'),
                  style: AppTypography.labelMedium.copyWith(
                    color: tc.textTertiary,
                  ),
                ),
              ),
              Expanded(
                flex: 2,
                child: Text(
                  t('tp_ai_value'),
                  style: AppTypography.labelMedium.copyWith(
                    color: tc.textTertiary,
                  ),
                ),
              ),
              Expanded(
                flex: 3,
                child: Text(
                  t('tp_my_value'),
                  style: AppTypography.labelMedium.copyWith(
                    color: tc.textTertiary,
                  ),
                ),
              ),
              Expanded(
                flex: 2,
                child: Text(
                  t('tp_effective_value'),
                  style: AppTypography.labelMedium.copyWith(
                    color: tc.textTertiary,
                  ),
                ),
              ),
            ],
          ),
        ),
        Divider(
          height: 1,
          color: tc.surfaceBorder.withValues(alpha: 0.3),
        ),
        // 파라미터 행들
        ...paramDefs.map((def) {
          final (key, displayName) = def;
          final aiValue = detail.aiRecommended[key];
          final effectiveValue = detail.effective[key];
          final hasOverride = _overrideEnabled[key] ?? false;

          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              children: [
                // 파라미터 이름
                Expanded(
                  flex: 3,
                  child: Text(
                    displayName,
                    style: AppTypography.bodySmall,
                  ),
                ),
                // AI 추천 값
                Expanded(
                  flex: 2,
                  child: Text(
                    aiValue != null
                        ? _formatParamValue(aiValue)
                        : '-',
                    style: AppTypography.numberSmall.copyWith(
                      fontSize: 13,
                      color: tc.textSecondary,
                    ),
                  ),
                ),
                // 내 설정 (편집 가능)
                Expanded(
                  flex: 3,
                  child: Row(
                    children: [
                      SizedBox(
                        width: 20,
                        height: 20,
                        child: Checkbox(
                          value: hasOverride,
                          onChanged: (val) {
                            setState(() {
                              _overrideEnabled[key] = val ?? false;
                              _hasUnsavedChanges = true;
                              if (val == true &&
                                  (_overrideControllers[key]?.text.isEmpty ??
                                      true)) {
                                // AI 값을 기본값으로 채운다
                                _overrideControllers[key]?.text =
                                    aiValue != null
                                        ? _formatParamValue(aiValue)
                                        : '';
                              }
                            });
                          },
                          activeColor: tc.primary,
                          side: BorderSide(color: tc.surfaceBorder),
                          materialTapTargetSize:
                              MaterialTapTargetSize.shrinkWrap,
                        ),
                      ),
                      AppSpacing.hGapSm,
                      Expanded(
                        child: SizedBox(
                          height: 30,
                          child: TextField(
                            controller: _overrideControllers[key],
                            enabled: hasOverride,
                            keyboardType: TextInputType.number,
                            style: AppTypography.numberSmall.copyWith(
                              fontSize: 13,
                              color: hasOverride
                                  ? tc.primary
                                  : tc.textDisabled,
                            ),
                            decoration: InputDecoration(
                              isDense: true,
                              contentPadding: const EdgeInsets.symmetric(
                                horizontal: 8,
                                vertical: 6,
                              ),
                              hintText: aiValue != null
                                  ? _formatParamValue(aiValue)
                                  : '',
                              hintStyle: AppTypography.bodySmall.copyWith(
                                color: tc.textDisabled,
                                fontSize: 13,
                              ),
                              border: OutlineInputBorder(
                                borderRadius: AppSpacing.borderRadiusSm,
                                borderSide: BorderSide(
                                  color: tc.surfaceBorder
                                      .withValues(alpha: 0.3),
                                ),
                              ),
                              enabledBorder: OutlineInputBorder(
                                borderRadius: AppSpacing.borderRadiusSm,
                                borderSide: BorderSide(
                                  color: tc.primary
                                      .withValues(alpha: 0.3),
                                ),
                              ),
                              disabledBorder: OutlineInputBorder(
                                borderRadius: AppSpacing.borderRadiusSm,
                                borderSide: BorderSide(
                                  color: tc.surfaceBorder
                                      .withValues(alpha: 0.15),
                                ),
                              ),
                            ),
                            onChanged: (_) {
                              if (!_hasUnsavedChanges) {
                                setState(() => _hasUnsavedChanges = true);
                              }
                            },
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                // 적용 값
                Expanded(
                  flex: 2,
                  child: Text(
                    effectiveValue != null
                        ? _formatParamValue(effectiveValue)
                        : '-',
                    style: AppTypography.numberSmall.copyWith(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          );
        }),
      ],
    );
  }

  String _formatParamValue(dynamic value) {
    if (value is double) {
      return value.toStringAsFixed(
          value == value.truncateToDouble() ? 1 : 2);
    }
    if (value is int) return value.toString();
    if (value is num) return value.toDouble().toStringAsFixed(1);
    return value.toString();
  }
}
