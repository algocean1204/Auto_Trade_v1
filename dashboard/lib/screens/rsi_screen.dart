import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/locale_provider.dart';
import '../services/api_service.dart';
import '../models/rsi_models.dart';
import '../models/dashboard_models.dart';
import '../providers/trade_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/chart_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/rsi_chart.dart';
import '../widgets/section_header.dart';
import '../animations/animation_utils.dart';

// ──────────────────────────────────────────
// 종목 카테고리 데이터 정의
// ──────────────────────────────────────────

/// 단일 종목 그룹 (기저종목 + 2x 레버리지 쌍)이다.
class _StockGroup {
  final String underlying;
  final String? bull2x;
  final String? bear2x;

  const _StockGroup({
    required this.underlying,
    this.bull2x,
    this.bear2x,
  });
}

/// 종목 카테고리 (이름 + 그룹 목록)이다.
class _StockCategory {
  final String name;
  final String icon;
  final Color accentColor;
  final List<_StockGroup> groups;

  const _StockCategory({
    required this.name,
    required this.icon,
    required this.accentColor,
    required this.groups,
  });
}

// ──────────────────────────────────────────
// RSI 화면
// ──────────────────────────────────────────

/// RSI 분석 화면이다. 카테고리별 종목 선택 + TripleRsiChart 표시한다.
class RsiScreen extends StatefulWidget {
  const RsiScreen({super.key});

  @override
  State<RsiScreen> createState() => _RsiScreenState();
}

class _RsiScreenState extends State<RsiScreen> {
  // ── 하드코딩 카테고리 정의 ──

  static const List<_StockCategory> _hardcodedCategories = [
    _StockCategory(
      name: '빅테크',
      icon: 'B',
      accentColor: ChartColors.categoryBigTech,
      groups: [
        _StockGroup(underlying: 'AAPL', bull2x: 'AAPB', bear2x: 'AAPD'),
        _StockGroup(underlying: 'TSLA', bull2x: 'TSLL', bear2x: 'TSLS'),
        _StockGroup(underlying: 'NVDA', bull2x: 'NVDL', bear2x: 'NVDS'),
        _StockGroup(underlying: 'GOOGL', bull2x: 'GGLL', bear2x: null),
        _StockGroup(underlying: 'AMZN', bull2x: 'AMZU', bear2x: 'AMZD'),
        _StockGroup(underlying: 'META', bull2x: 'METU', bear2x: null),
        _StockGroup(underlying: 'MSFT', bull2x: 'MSFL', bear2x: null),
        _StockGroup(underlying: 'AMD', bull2x: 'AMDU', bear2x: null),
        _StockGroup(underlying: 'COIN', bull2x: 'CONL', bear2x: null),
      ],
    ),
    _StockCategory(
      name: '지수 ETF',
      icon: 'I',
      accentColor: ChartColors.categoryIndex,
      groups: [
        _StockGroup(underlying: 'SPY', bull2x: 'SSO', bear2x: 'SDS'),
        _StockGroup(underlying: 'QQQ', bull2x: 'QLD', bear2x: 'QID'),
        _StockGroup(underlying: 'SOXX', bull2x: 'SOXL', bear2x: 'SOXS'),
        _StockGroup(underlying: 'IWM', bull2x: 'UWM', bear2x: 'TWM'),
        _StockGroup(underlying: 'DIA', bull2x: 'DDM', bear2x: 'DXD'),
      ],
    ),
    _StockCategory(
      name: '섹터 ETF',
      icon: 'S',
      accentColor: ChartColors.categorySector,
      groups: [
        _StockGroup(underlying: 'XLK', bull2x: 'ROM', bear2x: 'REW'),
        _StockGroup(underlying: 'XLF', bull2x: 'UYG', bear2x: 'SKF'),
        _StockGroup(underlying: 'XLE', bull2x: 'DIG', bear2x: 'DUG'),
      ],
    ),
  ];

  // ── 상태 ──
  String? _selectedTicker;
  TripleRsiData? _rsiData;
  bool _isLoading = false;
  String? _error;
  int _days = 100;

  // 카테고리 접힘/펼침 상태
  final Map<String, bool> _categoryExpanded = {
    '빅테크': true,
    '지수 ETF': true,
    '섹터 ETF': true,
    '사용자 추가': true,
  };

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _initLoad();
    });
  }

  Future<void> _initLoad() async {
    final tradeProvider = context.read<TradeProvider>();
    if (tradeProvider.universe.isEmpty) {
      await tradeProvider.loadUniverse();
    }
    if (!mounted) return;
    // 첫 종목 자동 선택: NVDA (빅테크 대표)
    if (_selectedTicker == null) {
      setState(() => _selectedTicker = 'NVDA');
      await _loadRsi('NVDA');
    }
  }

  Future<void> _loadRsi(String ticker) async {
    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      final api = context.read<ApiService>();
      final data = await api.getTripleRsi(ticker, days: _days);
      if (!mounted) return;
      setState(() {
        _rsiData = data;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  void _selectTicker(String ticker) {
    if (_selectedTicker == ticker) return;
    setState(() => _selectedTicker = ticker);
    _loadRsi(ticker);
  }

  /// 유니버스에서 하드코딩 카테고리에 없는 종목을 '사용자 추가'로 분류한다.
  List<String> _getCustomTickers(List<UniverseTicker> universe) {
    final hardcodedTickers = <String>{};
    for (final cat in _hardcodedCategories) {
      for (final g in cat.groups) {
        hardcodedTickers.add(g.underlying);
        if (g.bull2x != null) hardcodedTickers.add(g.bull2x ?? '');
        if (g.bear2x != null) hardcodedTickers.add(g.bear2x ?? '');
      }
    }
    return universe
        .where((t) => t.enabled && !hardcodedTickers.contains(t.ticker))
        .map((t) => t.ticker)
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Scaffold(
      backgroundColor: context.tc.background,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 헤더
          _buildHeader(t),
          // 바디: 좌측 사이드바 + 우측 차트
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 좌측 종목 선택 사이드바
                SizedBox(
                  width: 260,
                  child: _buildSidebar(t),
                ),
                // 구분선
                Container(
                  width: 1,
                  color: context.tc.surfaceBorder.withValues(alpha: 0.3),
                ),
                // 우측 차트 영역
                Expanded(
                  child: _buildChartArea(t),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ──────────────────────────────────────────
  // 헤더
  // ──────────────────────────────────────────

  Widget _buildHeader(String Function(String) t) {
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 16),
      decoration: BoxDecoration(
        color: context.tc.background,
        border: Border(
          bottom: BorderSide(
            color: context.tc.surfaceBorder.withValues(alpha: 0.3),
            width: 1,
          ),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(t('rsi_analysis'), style: AppTypography.displayMedium),
                AppSpacing.vGapXs,
                Text(t('rsi_desc'), style: AppTypography.bodySmall),
              ],
            ),
          ),
          // 기간 선택
          _buildDaySelector(t),
        ],
      ),
    );
  }

  // ──────────────────────────────────────────
  // 좌측 사이드바: 카테고리별 종목 목록
  // ──────────────────────────────────────────

  Widget _buildSidebar(String Function(String) t) {
    return Container(
      color: context.tc.surface.withValues(alpha: 0.4),
      child: Consumer<TradeProvider>(
        builder: (context, provider, _) {
          final customTickers = _getCustomTickers(provider.universe);
          return ListView(
            padding: const EdgeInsets.symmetric(vertical: 8),
            children: [
              // 하드코딩 카테고리
              ..._hardcodedCategories.map((cat) {
                return _CategorySection(
                  category: cat,
                  selectedTicker: _selectedTicker,
                  isExpanded: _categoryExpanded[cat.name] ?? true,
                  onToggle: () {
                    setState(() {
                      _categoryExpanded[cat.name] =
                          !(_categoryExpanded[cat.name] ?? true);
                    });
                  },
                  onTickerSelected: _selectTicker,
                );
              }),
              // 사용자 추가 카테고리 (유니버스에서 추출)
              if (customTickers.isNotEmpty)
                _CustomTickerSection(
                  tickers: customTickers,
                  selectedTicker: _selectedTicker,
                  isExpanded: _categoryExpanded['사용자 추가'] ?? true,
                  onToggle: () {
                    setState(() {
                      _categoryExpanded['사용자 추가'] =
                          !(_categoryExpanded['사용자 추가'] ?? true);
                    });
                  },
                  onTickerSelected: _selectTicker,
                ),
            ],
          );
        },
      ),
    );
  }

  // ──────────────────────────────────────────
  // 기간 선택
  // ──────────────────────────────────────────

  Widget _buildDaySelector(String Function(String) t) {
    final options = [30, 60, 100, 200];
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text('기간:', style: AppTypography.labelMedium),
        AppSpacing.hGapMd,
        ...options.map((d) {
          final isSelected = _days == d;
          return Padding(
            padding: const EdgeInsets.only(right: 6),
            child: GestureDetector(
              onTap: () {
                if (_days == d) return;
                setState(() => _days = d);
                if (_selectedTicker != null) _loadRsi(_selectedTicker ?? '');
              },
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 150),
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                decoration: BoxDecoration(
                  color: isSelected
                      ? context.tc.primary.withValues(alpha: 0.12)
                      : context.tc.surface,
                  borderRadius: AppSpacing.borderRadiusMd,
                  border: Border.all(
                    color: isSelected
                        ? context.tc.primary.withValues(alpha: 0.3)
                        : context.tc.surfaceBorder.withValues(alpha: 0.3),
                  ),
                ),
                child: Text(
                  '${d}d',
                  style: AppTypography.labelMedium.copyWith(
                    color: isSelected
                        ? context.tc.primary
                        : context.tc.textSecondary,
                  ),
                ),
              ),
            ),
          );
        }),
      ],
    );
  }

  // ──────────────────────────────────────────
  // 우측 차트 영역
  // ──────────────────────────────────────────

  Widget _buildChartArea(String Function(String) t) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 매핑 레이블 (기저종목 → 거래 종목)
          _buildMappingLabel(t),
          if (_rsiData != null) AppSpacing.vGapLg,
          // 차트 섹션
          _buildChartSection(t),
          // RSI 해석 텍스트
          if (_rsiData != null && !_isLoading) ...[
            AppSpacing.vGapLg,
            _buildRsiInterpretation(t),
          ],
        ],
      ),
    );
  }

  Widget _buildMappingLabel(String Function(String) t) {
    if (_rsiData == null) return const SizedBox.shrink();
    final rsiData = _rsiData;
    if (rsiData == null) return const SizedBox.shrink();
    final ticker = rsiData.ticker;
    final analysisTicker = rsiData.analysisTicker;
    if (analysisTicker.isEmpty && ticker.isEmpty) return const SizedBox.shrink();

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: context.tc.primary.withValues(alpha: 0.06),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: context.tc.primary.withValues(alpha: 0.15),
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.info_outline_rounded,
            size: 14,
            color: context.tc.primary.withValues(alpha: 0.7),
          ),
          AppSpacing.hGapXs,
          RichText(
            text: TextSpan(
              style: AppTypography.bodySmall.copyWith(
                color: context.tc.textSecondary,
              ),
              children: [
                TextSpan(text: '${t('analysis_target')}: '),
                TextSpan(
                  text: analysisTicker.isNotEmpty
                      ? analysisTicker
                      : _selectedTicker ?? '',
                  style: TextStyle(
                    color: context.tc.primary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const TextSpan(text: '  →  '),
                TextSpan(text: '${t('trade_target')}: '),
                TextSpan(
                  text: ticker.isNotEmpty ? ticker : _selectedTicker ?? '',
                  style: TextStyle(
                    color: context.tc.profit,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildChartSection(String Function(String) t) {
    if (_isLoading) {
      return Column(
        children: [
          ShimmerLoading(
            width: double.infinity,
            height: 60,
            borderRadius: AppSpacing.borderRadiusMd,
          ),
          AppSpacing.vGapLg,
          ShimmerLoading(
            width: double.infinity,
            height: 320,
            borderRadius: AppSpacing.borderRadiusLg,
          ),
        ],
      );
    }

    if (_error != null) {
      return GlassCard(
        child: Column(
          children: [
            Icon(
              Icons.cloud_off_rounded,
              size: 40,
              color: context.tc.textTertiary,
            ),
            AppSpacing.vGapMd,
            Text(
              'RSI 데이터 로드 실패',
              style: AppTypography.headlineMedium,
            ),
            AppSpacing.vGapSm,
            Text(
              _error ?? '',
              style: AppTypography.bodySmall,
              textAlign: TextAlign.center,
            ),
            AppSpacing.vGapLg,
            ElevatedButton.icon(
              onPressed: () {
                if (_selectedTicker != null) _loadRsi(_selectedTicker ?? '');
              },
              icon: const Icon(Icons.refresh_rounded, size: 16),
              label: Text(t('retry')),
            ),
          ],
        ),
      );
    }

    if (_rsiData == null) {
      return GlassCard(
        child: Column(
          children: [
            Icon(
              Icons.show_chart_rounded,
              size: 48,
              color: context.tc.textTertiary,
            ),
            AppSpacing.vGapLg,
            Text(
              _selectedTicker == null
                  ? '종목을 선택하세요'
                  : '$_selectedTicker RSI 데이터 없음',
              style: AppTypography.headlineMedium,
            ),
          ],
        ),
      );
    }

    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(
            title: t('rsi_analysis'),
            action: Row(
              children: [
                if ((_rsiData?.ticker ?? '').isNotEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: context.tc.primary.withValues(alpha: 0.1),
                      borderRadius: AppSpacing.borderRadiusSm,
                    ),
                    child: Text(
                      (_rsiData?.ticker ?? '').isNotEmpty
                          ? (_rsiData?.ticker ?? '')
                          : (_selectedTicker ?? ''),
                      style: AppTypography.labelMedium.copyWith(
                        color: context.tc.primary,
                      ),
                    ),
                  ),
                AppSpacing.hGapSm,
                IconButton(
                  icon: Icon(
                    Icons.refresh_rounded,
                    size: 16,
                    color: context.tc.textTertiary,
                  ),
                  onPressed: () {
                    if (_selectedTicker != null) _loadRsi(_selectedTicker ?? '');
                  },
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
                ),
              ],
            ),
          ),
          AppSpacing.vGapLg,
          if (_rsiData case final rsiData?) TripleRsiChart(data: rsiData, height: 300),
        ],
      ),
    );
  }

  // ──────────────────────────────────────────
  // RSI 해석 텍스트
  // ──────────────────────────────────────────

  Widget _buildRsiInterpretation(String Function(String) t) {
    final rsiData = _rsiData;
    if (rsiData == null) return const SizedBox.shrink();

    final rsi14 = rsiData.rsi14.rsi;
    final consensus = rsiData.consensus;
    final divergence = rsiData.divergence;

    // RSI 구간 판단
    final _RsiZone zone = _getRsiZone(rsi14);

    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.analytics_rounded,
                size: 16,
                color: context.tc.textTertiary,
              ),
              AppSpacing.hGapXs,
              Text('RSI 해석', style: AppTypography.labelLarge),
            ],
          ),
          AppSpacing.vGapMd,
          // 현재 RSI 값 + 구간 표시
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                decoration: BoxDecoration(
                  color: zone.color.withValues(alpha: 0.12),
                  borderRadius: AppSpacing.borderRadiusMd,
                  border: Border.all(
                    color: zone.color.withValues(alpha: 0.35),
                    width: 1,
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(zone.icon, size: 15, color: zone.color),
                    AppSpacing.hGapXs,
                    Text(
                      'RSI(14): ${rsi14.toStringAsFixed(1)}',
                      style: AppTypography.labelMedium.copyWith(
                        color: zone.color,
                      ),
                    ),
                    AppSpacing.hGapXs,
                    Text(
                      zone.label,
                      style: AppTypography.bodySmall.copyWith(
                        color: zone.color.withValues(alpha: 0.8),
                      ),
                    ),
                  ],
                ),
              ),
              // 컨센서스
              _buildConsensusBadge(consensus),
              // 다이버전스 경고
              if (divergence)
                _buildDivergenceWarning(),
            ],
          ),
          AppSpacing.vGapMd,
          // RSI 구간 설명 바
          _buildRsiZoneBar(rsi14),
          AppSpacing.vGapMd,
          // 해석 설명 텍스트
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: zone.color.withValues(alpha: 0.07),
              borderRadius: AppSpacing.borderRadiusMd,
              border: Border.all(
                color: zone.color.withValues(alpha: 0.2),
              ),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  Icons.lightbulb_outline_rounded,
                  size: 14,
                  color: zone.color.withValues(alpha: 0.8),
                ),
                AppSpacing.hGapXs,
                Expanded(
                  child: Text(
                    zone.description,
                    style: AppTypography.bodySmall.copyWith(
                      color: zone.color.withValues(alpha: 0.9),
                      height: 1.6,
                    ),
                  ),
                ),
              ],
            ),
          ),
          if (divergence) ...[
            AppSpacing.vGapMd,
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: context.tc.warning.withValues(alpha: 0.07),
                borderRadius: AppSpacing.borderRadiusMd,
                border: Border.all(
                  color: context.tc.warning.withValues(alpha: 0.2),
                ),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    Icons.warning_amber_rounded,
                    size: 14,
                    color: context.tc.warning,
                  ),
                  AppSpacing.hGapXs,
                  Expanded(
                    child: Text(
                      '다이버전스 감지 - RSI(7), RSI(14), RSI(21) 간 방향성 불일치. '
                      '추세 전환 가능성이 높으므로 포지션 진입 시 주의가 필요하다.',
                      style: AppTypography.bodySmall.copyWith(
                        color: context.tc.warning.withValues(alpha: 0.9),
                        height: 1.6,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildConsensusBadge(String consensus) {
    final tc = context.tc;
    Color color;
    IconData icon;
    String label;
    switch (consensus.toLowerCase()) {
      case 'bullish':
        color = tc.profit;
        icon = Icons.trending_up_rounded;
        label = '강세 (Bullish)';
        break;
      case 'bearish':
        color = tc.loss;
        icon = Icons.trending_down_rounded;
        label = '약세 (Bearish)';
        break;
      default:
        color = tc.textTertiary;
        icon = Icons.trending_flat_rounded;
        label = '중립 (Neutral)';
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: color),
          AppSpacing.hGapXs,
          Text(
            label,
            style: AppTypography.labelMedium.copyWith(color: color),
          ),
        ],
      ),
    );
  }

  Widget _buildDivergenceWarning() {
    final tc = context.tc;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: tc.warning.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(color: tc.warning.withValues(alpha: 0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.warning_amber_rounded, size: 14, color: tc.warning),
          AppSpacing.hGapXs,
          Text(
            '다이버전스 경고',
            style: AppTypography.labelMedium.copyWith(
              color: tc.warning,
            ),
          ),
        ],
      ),
    );
  }

  /// RSI 구간 시각화 바이다.
  Widget _buildRsiZoneBar(double rsi14) {
    // 5개 구간: <30 | 30-40 | 40-60 | 60-70 | >70
    const zones = [
      (label: '과매도', start: 0.0, end: 30.0, color: ChartColors.rsiOversold),
      (label: '약세', start: 30.0, end: 40.0, color: ChartColors.rsiBearish),
      (label: '중립', start: 40.0, end: 60.0, color: ChartColors.rsiNeutral),
      (label: '강세', start: 60.0, end: 70.0, color: ChartColors.rsiBullish),
      (label: '과매수', start: 70.0, end: 100.0, color: ChartColors.rsiOverbought),
    ];

    final currentZone = _getRsiZone(rsi14);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('RSI 구간', style: AppTypography.bodySmall),
        AppSpacing.vGapXs,
        // 바 영역
        LayoutBuilder(
          builder: (context, constraints) {
            final totalWidth = constraints.maxWidth;
            // RSI 포인터 위치 (0~100 → 0~totalWidth)
            final pointerX = (rsi14.clamp(0, 100) / 100) * totalWidth;
            return Stack(
              clipBehavior: Clip.none,
              children: [
                // 구간 컬러 바
                ClipRRect(
                  borderRadius: AppSpacing.borderRadiusFull,
                  child: Row(
                    children: zones.map((z) {
                      final width =
                          ((z.end - z.start) / 100) * totalWidth;
                      return Container(
                        width: width,
                        height: 8,
                        color: z.color.withValues(alpha: 0.45),
                      );
                    }).toList(),
                  ),
                ),
                // 현재 RSI 포인터
                Positioned(
                  left: pointerX - 6,
                  top: -3,
                  child: Container(
                    width: 14,
                    height: 14,
                    decoration: BoxDecoration(
                      color: currentZone.color,
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: context.tc.background,
                        width: 2,
                      ),
                      boxShadow: [
                        BoxShadow(
                          color: currentZone.color.withValues(alpha: 0.5),
                          blurRadius: 6,
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            );
          },
        ),
        AppSpacing.vGapXs,
        // 구간 레이블
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('0', style: AppTypography.bodySmall.copyWith(fontSize: 10)),
            Text('30', style: AppTypography.bodySmall.copyWith(fontSize: 10)),
            Text('40', style: AppTypography.bodySmall.copyWith(fontSize: 10)),
            Text('60', style: AppTypography.bodySmall.copyWith(fontSize: 10)),
            Text('70', style: AppTypography.bodySmall.copyWith(fontSize: 10)),
            Text('100', style: AppTypography.bodySmall.copyWith(fontSize: 10)),
          ],
        ),
      ],
    );
  }

  _RsiZone _getRsiZone(double rsi) {
    final tc = context.tc;
    if (rsi > 70) {
      return _RsiZone(
        label: '과매수 구간 - 매도 고려',
        color: tc.loss,
        icon: Icons.arrow_upward_rounded,
        description: '현재 RSI가 70을 초과하여 과매수 상태이다. '
            '단기 조정 또는 하락 전환 가능성이 있으므로 신규 매수는 자제하고 '
            '기존 포지션의 이익 실현을 고려하는 것이 좋다.',
      );
    } else if (rsi >= 60) {
      return _RsiZone(
        label: '강세 - 상승 추세',
        color: tc.profit,
        icon: Icons.trending_up_rounded,
        description: '현재 RSI가 60~70 구간으로 강세 추세를 나타낸다. '
            '상승 모멘텀이 유지되고 있으나 과매수 구간 진입 전 주의가 필요하다. '
            '추세 추종 전략이 유효한 구간이다.',
      );
    } else if (rsi >= 40) {
      return _RsiZone(
        label: '중립 - 관망',
        color: tc.textTertiary,
        icon: Icons.trending_flat_rounded,
        description: '현재 RSI가 40~60 중립 구간에 있다. '
            '뚜렷한 추세 방향성이 없으므로 관망을 권장한다. '
            '다른 지표(거래량, MACD 등)와 함께 복합적으로 판단하는 것이 좋다.',
      );
    } else if (rsi >= 30) {
      return _RsiZone(
        label: '약세 - 하락 추세',
        color: ChartColors.rsiBearish,
        icon: Icons.trending_down_rounded,
        description: '현재 RSI가 30~40 구간으로 약세 압력이 있다. '
            '하락 추세가 지속될 수 있으므로 신규 매수보다는 '
            '추가 하락을 대비한 리스크 관리가 필요하다.',
      );
    } else {
      return _RsiZone(
        label: '과매도 구간 - 매수 고려',
        color: tc.primary,
        icon: Icons.arrow_downward_rounded,
        description: '현재 RSI가 30 미만으로 과매도 상태이다. '
            '기술적 반등 가능성이 높아 분할 매수를 검토할 수 있다. '
            '단, 강한 하락 추세 중에는 과매도가 더 심화될 수 있으므로 신중하게 접근한다.',
      );
    }
  }
}

// ──────────────────────────────────────────
// RSI 구간 정보 데이터 클래스
// ──────────────────────────────────────────

class _RsiZone {
  final String label;
  final Color color;
  final IconData icon;
  final String description;

  const _RsiZone({
    required this.label,
    required this.color,
    required this.icon,
    required this.description,
  });
}

// ──────────────────────────────────────────
// 카테고리 섹션 위젯
// ──────────────────────────────────────────

/// 하드코딩 종목 카테고리 섹션 위젯이다.
class _CategorySection extends StatelessWidget {
  final _StockCategory category;
  final String? selectedTicker;
  final bool isExpanded;
  final VoidCallback onToggle;
  final void Function(String) onTickerSelected;

  const _CategorySection({
    required this.category,
    required this.selectedTicker,
    required this.isExpanded,
    required this.onToggle,
    required this.onTickerSelected,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 카테고리 헤더
        GestureDetector(
          onTap: onToggle,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            child: Row(
              children: [
                // 카테고리 아이콘 (이니셜)
                Container(
                  width: 22,
                  height: 22,
                  decoration: BoxDecoration(
                    color: category.accentColor.withValues(alpha: 0.15),
                    borderRadius: AppSpacing.borderRadiusSm,
                    border: Border.all(
                      color: category.accentColor.withValues(alpha: 0.3),
                    ),
                  ),
                  alignment: Alignment.center,
                  child: Text(
                    category.icon,
                    style: AppTypography.labelMedium.copyWith(
                      color: category.accentColor,
                      fontSize: 11,
                    ),
                  ),
                ),
                AppSpacing.hGapSm,
                Expanded(
                  child: Text(
                    category.name,
                    style: AppTypography.labelLarge.copyWith(fontSize: 13),
                  ),
                ),
                // 카운트 뱃지
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: context.tc.surfaceBorder.withValues(alpha: 0.4),
                    borderRadius: AppSpacing.borderRadiusFull,
                  ),
                  child: Text(
                    '${category.groups.length}',
                    style: AppTypography.bodySmall.copyWith(fontSize: 10),
                  ),
                ),
                AppSpacing.hGapXs,
                AnimatedRotation(
                  turns: isExpanded ? 0 : -0.25,
                  duration: const Duration(milliseconds: 200),
                  child: Icon(
                    Icons.expand_more_rounded,
                    size: 18,
                    color: context.tc.textTertiary,
                  ),
                ),
              ],
            ),
          ),
        ),
        // 종목 그룹 목록
        AnimatedCrossFade(
          duration: const Duration(milliseconds: 200),
          crossFadeState: isExpanded
              ? CrossFadeState.showFirst
              : CrossFadeState.showSecond,
          firstChild: Column(
            children: category.groups.map((group) {
              return _StockGroupCard(
                group: group,
                accentColor: category.accentColor,
                selectedTicker: selectedTicker,
                onTickerSelected: onTickerSelected,
              );
            }).toList(),
          ),
          secondChild: const SizedBox.shrink(),
        ),
        Divider(
          height: 1,
          color: context.tc.surfaceBorder.withValues(alpha: 0.2),
          indent: 12,
          endIndent: 12,
        ),
      ],
    );
  }
}

// ──────────────────────────────────────────
// 사용자 추가 카테고리 섹션
// ──────────────────────────────────────────

class _CustomTickerSection extends StatelessWidget {
  final List<String> tickers;
  final String? selectedTicker;
  final bool isExpanded;
  final VoidCallback onToggle;
  final void Function(String) onTickerSelected;

  const _CustomTickerSection({
    required this.tickers,
    required this.selectedTicker,
    required this.isExpanded,
    required this.onToggle,
    required this.onTickerSelected,
  });

  @override
  Widget build(BuildContext context) {
    const accentColor = ChartColors.categoryWatchlist;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        GestureDetector(
          onTap: onToggle,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            child: Row(
              children: [
                Container(
                  width: 22,
                  height: 22,
                  decoration: BoxDecoration(
                    color: accentColor.withValues(alpha: 0.15),
                    borderRadius: AppSpacing.borderRadiusSm,
                    border: Border.all(color: accentColor.withValues(alpha: 0.3)),
                  ),
                  alignment: Alignment.center,
                  child: Text(
                    'C',
                    style: AppTypography.labelMedium.copyWith(
                      color: accentColor,
                      fontSize: 11,
                    ),
                  ),
                ),
                AppSpacing.hGapSm,
                Expanded(
                  child: Text(
                    '사용자 추가',
                    style: AppTypography.labelLarge.copyWith(fontSize: 13),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: context.tc.surfaceBorder.withValues(alpha: 0.4),
                    borderRadius: AppSpacing.borderRadiusFull,
                  ),
                  child: Text(
                    '${tickers.length}',
                    style: AppTypography.bodySmall.copyWith(fontSize: 10),
                  ),
                ),
                AppSpacing.hGapXs,
                AnimatedRotation(
                  turns: isExpanded ? 0 : -0.25,
                  duration: const Duration(milliseconds: 200),
                  child: Icon(
                    Icons.expand_more_rounded,
                    size: 18,
                    color: context.tc.textTertiary,
                  ),
                ),
              ],
            ),
          ),
        ),
        AnimatedCrossFade(
          duration: const Duration(milliseconds: 200),
          crossFadeState: isExpanded
              ? CrossFadeState.showFirst
              : CrossFadeState.showSecond,
          firstChild: Column(
            children: tickers.map((ticker) {
              final isSelected = selectedTicker == ticker;
              return GestureDetector(
                onTap: () => onTickerSelected(ticker),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  padding: const EdgeInsets.symmetric(
                      horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: isSelected
                        ? accentColor.withValues(alpha: 0.1)
                        : Colors.transparent,
                    borderRadius: AppSpacing.borderRadiusMd,
                    border: Border.all(
                      color: isSelected
                          ? accentColor.withValues(alpha: 0.35)
                          : Colors.transparent,
                    ),
                  ),
                  child: Row(
                    children: [
                      Icon(
                        Icons.add_circle_outline_rounded,
                        size: 13,
                        color: accentColor.withValues(alpha: 0.7),
                      ),
                      AppSpacing.hGapXs,
                      Text(
                        ticker,
                        style: AppTypography.labelMedium.copyWith(
                          color: isSelected
                              ? accentColor
                              : context.tc.textSecondary,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ),
                ),
              );
            }).toList(),
          ),
          secondChild: const SizedBox.shrink(),
        ),
        Divider(
          height: 1,
          color: context.tc.surfaceBorder.withValues(alpha: 0.2),
          indent: 12,
          endIndent: 12,
        ),
      ],
    );
  }
}

// ──────────────────────────────────────────
// 종목 그룹 카드 위젯
// ──────────────────────────────────────────

/// 기저종목 + 2x 레버리지 쌍을 표시하는 카드이다.
class _StockGroupCard extends StatelessWidget {
  final _StockGroup group;
  final Color accentColor;
  final String? selectedTicker;
  final void Function(String) onTickerSelected;

  const _StockGroupCard({
    required this.group,
    required this.accentColor,
    required this.selectedTicker,
    required this.onTickerSelected,
  });

  bool get _isAnySelected =>
      selectedTicker == group.underlying ||
      (group.bull2x != null && selectedTicker == group.bull2x) ||
      (group.bear2x != null && selectedTicker == group.bear2x);

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: _isAnySelected
            ? accentColor.withValues(alpha: 0.06)
            : Colors.transparent,
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: _isAnySelected
              ? accentColor.withValues(alpha: 0.2)
              : Colors.transparent,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 기저 종목 행
          _TickerRow(
            ticker: group.underlying,
            type: _TickerType.underlying,
            isSelected: selectedTicker == group.underlying,
            accentColor: accentColor,
            onTap: () => onTickerSelected(group.underlying),
          ),
          // 레버리지 ETF 행 (존재하는 경우만)
          if (group.bull2x != null || group.bear2x != null)
            Padding(
              padding: const EdgeInsets.only(left: 16, bottom: 4),
              child: Row(
                children: [
                  if (group.bull2x != null)
                    _LeverageChip(
                      ticker: group.bull2x ?? '',
                      type: _TickerType.bull2x,
                      isSelected: selectedTicker == group.bull2x,
                      onTap: () => onTickerSelected(group.bull2x ?? ''),
                    ),
                  if (group.bull2x != null && group.bear2x != null)
                    AppSpacing.hGapXs,
                  if (group.bear2x != null)
                    _LeverageChip(
                      ticker: group.bear2x ?? '',
                      type: _TickerType.bear2x,
                      isSelected: selectedTicker == group.bear2x,
                      onTap: () => onTickerSelected(group.bear2x ?? ''),
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

// ──────────────────────────────────────────
// 티커 타입
// ──────────────────────────────────────────

enum _TickerType { underlying, bull2x, bear2x }

// ──────────────────────────────────────────
// 기저 종목 행 위젯
// ──────────────────────────────────────────

class _TickerRow extends StatelessWidget {
  final String ticker;
  final _TickerType type;
  final bool isSelected;
  final Color accentColor;
  final VoidCallback onTap;

  const _TickerRow({
    required this.ticker,
    required this.type,
    required this.isSelected,
    required this.accentColor,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        decoration: BoxDecoration(
          color: isSelected
              ? accentColor.withValues(alpha: 0.12)
              : Colors.transparent,
          borderRadius: AppSpacing.borderRadiusMd,
        ),
        child: Row(
          children: [
            // 선택 표시 점
            Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: isSelected
                    ? accentColor
                    : context.tc.textTertiary.withValues(alpha: 0.4),
              ),
            ),
            AppSpacing.hGapSm,
            Text(
              ticker,
              style: AppTypography.labelMedium.copyWith(
                color: isSelected ? accentColor : context.tc.textSecondary,
                fontSize: 13,
                fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
              ),
            ),
            const Spacer(),
            if (isSelected)
              Icon(
                Icons.chevron_right_rounded,
                size: 14,
                color: accentColor.withValues(alpha: 0.7),
              ),
          ],
        ),
      ),
    );
  }
}

// ──────────────────────────────────────────
// 레버리지 ETF 칩 위젯
// ──────────────────────────────────────────

class _LeverageChip extends StatelessWidget {
  final String ticker;
  final _TickerType type;
  final bool isSelected;
  final VoidCallback onTap;

  const _LeverageChip({
    required this.ticker,
    required this.type,
    required this.isSelected,
    required this.onTap,
  });

  Color _typeColor(BuildContext context) {
    final tc = context.tc;
    switch (type) {
      case _TickerType.bull2x:
        return tc.profit;
      case _TickerType.bear2x:
        return tc.loss;
      default:
        return tc.primary;
    }
  }

  String get _typeLabel {
    switch (type) {
      case _TickerType.bull2x:
        return '2x↑';
      case _TickerType.bear2x:
        return '2x↓';
      default:
        return '';
    }
  }

  @override
  Widget build(BuildContext context) {
    final color = _typeColor(context);
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
        decoration: BoxDecoration(
          color: isSelected
              ? color.withValues(alpha: 0.18)
              : color.withValues(alpha: 0.07),
          borderRadius: AppSpacing.borderRadiusSm,
          border: Border.all(
            color: isSelected
                ? color.withValues(alpha: 0.5)
                : color.withValues(alpha: 0.2),
            width: 1,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              _typeLabel,
              style: AppTypography.bodySmall.copyWith(
                color: color.withValues(alpha: 0.7),
                fontSize: 9,
              ),
            ),
            AppSpacing.hGapXs,
            Text(
              ticker,
              style: AppTypography.labelMedium.copyWith(
                color: isSelected ? color : color.withValues(alpha: 0.75),
                fontSize: 11,
                fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
