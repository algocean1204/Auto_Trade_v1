import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/universe_provider.dart';
import '../providers/locale_provider.dart';
import '../models/universe_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/empty_state.dart';
import '../widgets/ticker_add_dialog.dart';
import '../animations/animation_utils.dart';

/// 종목 관리 화면이다.
class UniverseScreen extends StatefulWidget {
  const UniverseScreen({super.key});

  @override
  State<UniverseScreen> createState() => _UniverseScreenState();
}

class _UniverseScreenState extends State<UniverseScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 4, vsync: this);
    _tabController.addListener(_onTabChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<UniverseProvider>().loadAll();
      // 첫 번째 탭이 섹터별이므로 초기에 섹터 데이터도 로드한다.
      context.read<UniverseProvider>().loadSectors();
    });
  }

  void _onTabChanged() {
    // 섹터별 탭(index 0) 또는 활성 종목 탭(index 1)으로 전환 시 섹터 데이터를 로드한다.
    if (_tabController.index == 0 || _tabController.index == 1) {
      final provider = context.read<UniverseProvider>();
      if (provider.sectors == null && !provider.isSectorsLoading) {
        provider.loadSectors();
      }
    }
  }

  @override
  void dispose() {
    _tabController.removeListener(_onTabChanged);
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
          // 헤더
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
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        t('universe_management'),
                        style: AppTypography.displayMedium,
                      ),
                    ),
                    // 새로고침 버튼
                    IconButton(
                      icon: Icon(Icons.refresh_rounded,
                          size: 20, color: context.tc.textTertiary),
                      onPressed: () =>
                          context.read<UniverseProvider>().refresh(),
                      tooltip: t('refresh'),
                    ),
                    // 종목 추가 버튼
                    ElevatedButton.icon(
                      onPressed: () => _showAddTickerDialog(context),
                      icon: const Icon(Icons.add_rounded, size: 16),
                      label: Text(t('add_ticker')),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: context.tc.primary,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(
                            horizontal: 14, vertical: 8),
                        textStyle: AppTypography.labelMedium,
                      ),
                    ),
                    AppSpacing.hGapSm,
                  ],
                ),
                AppSpacing.vGapMd,
                TabBar(
                  controller: _tabController,
                  isScrollable: true,
                  tabAlignment: TabAlignment.start,
                  tabs: [
                    Tab(text: t('sector_view')),
                    Tab(text: t('active_tickers')),
                    Tab(text: t('inactive_tickers')),
                    Tab(text: t('mapping_management')),
                  ],
                ),
              ],
            ),
          ),
          // 탭 컨텐츠
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                _SectorTab(),
                _ActiveTickersTab(),
                _InactiveTickersTab(),
                _MappingTab(),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _showAddTickerDialog(BuildContext context) async {
    // 새로운 단순화된 자동 추가 다이얼로그를 사용한다.
    await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => const TickerAddDialog(),
    );
  }
}

/// 섹터별 그룹 데이터 모델이다.
class _SectorGroup {
  final String key;
  final String nameKr;
  final String nameEn;
  final Color color;
  final IconData icon;
  final List<UniverseTickerEx> tickers;

  const _SectorGroup({
    required this.key,
    required this.nameKr,
    required this.nameEn,
    required this.color,
    required this.icon,
    required this.tickers,
  });
}

/// 활성 종목 탭 - 섹터별로 그룹핑하여 표시한다.
class _ActiveTickersTab extends StatelessWidget {
  /// 섹터 키에 대응하는 아이콘을 반환한다.
  static IconData _sectorIcon(String key) {
    switch (key) {
      case 'semiconductors':
        return Icons.memory;
      case 'big_tech':
        return Icons.computer;
      case 'ai_software':
        return Icons.smart_toy;
      case 'ev_energy':
        return Icons.electric_car;
      case 'crypto':
        return Icons.currency_bitcoin;
      case 'finance':
        return Icons.account_balance;
      case 'quantum':
        return Icons.science;
      case 'entertainment':
        return Icons.movie;
      case 'infrastructure':
        return Icons.domain;
      case 'consumer':
        return Icons.shopping_cart;
      case 'healthcare':
        return Icons.local_hospital;
      case 'other':
        return Icons.more_horiz_rounded;
      default:
        return Icons.category;
    }
  }

  /// 섹터 인덱스에 따른 색상을 반환한다.
  static Color _sectorColor(int index) {
    const colors = [
      Color(0xFF3B82F6),
      Color(0xFF8B5CF6),
      Color(0xFF10B981),
      Color(0xFFF59E0B),
      Color(0xFFEF4444),
      Color(0xFF06B6D4),
      Color(0xFFEC4899),
      Color(0xFF84CC16),
      Color(0xFFF97316),
      Color(0xFF6366F1),
      Color(0xFF14B8A6),
      Color(0xFFA855F7),
    ];
    return colors[index % colors.length];
  }

  /// 활성 종목을 섹터별로 그룹핑하여 반환한다.
  /// sectors 데이터가 없으면 "기타" 하나의 그룹으로 묶는다.
  List<_SectorGroup> _buildSectorGroups(
    List<UniverseTickerEx> activeTickers,
    List<SectorData> sectors,
  ) {
    if (sectors.isEmpty) {
      return [
        _SectorGroup(
          key: 'other',
          nameKr: '기타',
          nameEn: 'Other',
          color: _sectorColor(0),
          icon: _sectorIcon('other'),
          tickers: activeTickers,
        ),
      ];
    }

    // 각 티커가 어느 섹터에 속하는지 매핑한다.
    final Map<String, _SectorGroup> groupMap = {};
    final Set<String> assignedTickers = {};
    int colorIndex = 0;

    for (final sector in sectors) {
      final matchedTickers = activeTickers
          .where((t) => sector.tickers.contains(t.ticker))
          .toList();

      if (matchedTickers.isNotEmpty) {
        groupMap[sector.key] = _SectorGroup(
          key: sector.key,
          nameKr: sector.nameKr.isNotEmpty ? sector.nameKr : sector.nameEn,
          nameEn: sector.nameEn,
          color: _sectorColor(colorIndex),
          icon: _sectorIcon(sector.key),
          tickers: matchedTickers,
        );
        for (final t in matchedTickers) {
          assignedTickers.add(t.ticker);
        }
        colorIndex++;
      }
    }

    // 어느 섹터에도 속하지 않는 종목은 "기타"로 묶는다.
    final unassigned =
        activeTickers.where((t) => !assignedTickers.contains(t.ticker)).toList();
    if (unassigned.isNotEmpty) {
      groupMap['other'] = _SectorGroup(
        key: 'other',
        nameKr: '기타',
        nameEn: 'Other',
        color: _sectorColor(colorIndex),
        icon: _sectorIcon('other'),
        tickers: unassigned,
      );
    }

    return groupMap.values.toList();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Consumer<UniverseProvider>(
      builder: (context, provider, _) {
        // 로딩 상태
        final isLoading =
            (provider.isLoading && provider.tickers == null) ||
            (provider.isSectorsLoading && provider.sectors == null);
        if (isLoading) {
          return _loadingList();
        }
        // 에러 상태
        if (provider.error != null && provider.tickers == null) {
          return _errorState(context, provider, t);
        }
        final activeTickers = provider.activeTickers;
        if (activeTickers.isEmpty) {
          return EmptyState(
            icon: Icons.list_alt_rounded,
            title: t('no_tickers'),
          );
        }

        final sectors = provider.sectors ?? [];
        final groups = _buildSectorGroups(activeTickers, sectors);

        // 상단 요약 카운터 + 섹터 그룹 리스트
        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            // 활성 종목 요약 헤더
            _ActiveSummaryHeader(
              totalCount: activeTickers.length,
              sectorCount: groups.length,
            ),
            const SizedBox(height: 16),
            // 섹터별 그룹 카드
            ...groups.asMap().entries.map((entry) {
              return StaggeredFadeSlide(
                index: entry.key,
                child: _ActiveSectorGroup(
                  group: entry.value,
                  onToggle: (ticker, enabled) =>
                      provider.toggleTicker(ticker, enabled),
                  onDelete: (ticker) => _confirmDelete(
                    context,
                    ticker,
                    provider,
                    t,
                  ),
                ),
              );
            }),
          ],
        );
      },
    );
  }

  Widget _loadingList() {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        children: List.generate(
          4,
          (i) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: ShimmerLoading(
                width: double.infinity,
                height: 90,
                borderRadius: AppSpacing.borderRadiusLg),
          ),
        ),
      ),
    );
  }

  Widget _errorState(BuildContext context, UniverseProvider provider,
      String Function(String) t) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.cloud_off_rounded, size: 48, color: context.tc.textTertiary),
          AppSpacing.vGapLg,
          Text('로드 실패', style: AppTypography.headlineMedium),
          AppSpacing.vGapSm,
          Text(provider.error ?? '', style: AppTypography.bodySmall),
          AppSpacing.vGapXxl,
          ElevatedButton.icon(
            onPressed: () => provider.loadAll(),
            icon: const Icon(Icons.refresh_rounded, size: 18),
            label: Text(t('retry')),
          ),
        ],
      ),
    );
  }

  Future<void> _confirmDelete(BuildContext context, UniverseTickerEx ticker,
      UniverseProvider provider, String Function(String) t) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: context.tc.surfaceElevated,
        title: Text(t('confirm_delete'), style: AppTypography.headlineMedium),
        content: Text(
          '${ticker.ticker} (${ticker.name})',
          style: AppTypography.bodyMedium,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(t('cancel')),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, true),
            style: ElevatedButton.styleFrom(backgroundColor: context.tc.loss),
            child: Text(t('delete')),
          ),
        ],
      ),
    );
    if (confirmed == true && context.mounted) {
      provider.removeTicker(ticker.ticker);
    }
  }
}

/// 활성 종목 요약 헤더 위젯이다.
class _ActiveSummaryHeader extends StatelessWidget {
  final int totalCount;
  final int sectorCount;

  const _ActiveSummaryHeader({
    required this.totalCount,
    required this.sectorCount,
  });

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        children: [
          // 활성 종목 수
          _StatItem(
            icon: Icons.check_circle_rounded,
            iconColor: context.tc.profit,
            label: '활성 종목',
            value: '$totalCount개',
            valueColor: context.tc.profit,
          ),
          Container(
            width: 1,
            height: 32,
            color: context.tc.surfaceBorder.withValues(alpha: 0.4),
            margin: const EdgeInsets.symmetric(horizontal: 16),
          ),
          // 섹터 수
          _StatItem(
            icon: Icons.category_rounded,
            iconColor: context.tc.primary,
            label: '섹터',
            value: '$sectorCount개',
            valueColor: context.tc.textPrimary,
          ),
        ],
      ),
    );
  }
}

/// 요약 헤더 내 개별 통계 항목 위젯이다.
class _StatItem extends StatelessWidget {
  final IconData icon;
  final Color iconColor;
  final String label;
  final String value;
  final Color valueColor;

  const _StatItem({
    required this.icon,
    required this.iconColor,
    required this.label,
    required this.value,
    required this.valueColor,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 16, color: iconColor),
        const SizedBox(width: 6),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              label,
              style: AppTypography.bodySmall.copyWith(
                fontSize: 10,
                color: context.tc.textTertiary,
              ),
            ),
            Text(
              value,
              style: AppTypography.labelMedium.copyWith(
                color: valueColor,
                fontSize: 13,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// 섹터별 활성 종목 그룹 카드 위젯이다.
class _ActiveSectorGroup extends StatefulWidget {
  final _SectorGroup group;
  final void Function(String ticker, bool enabled) onToggle;
  final void Function(UniverseTickerEx ticker) onDelete;

  const _ActiveSectorGroup({
    required this.group,
    required this.onToggle,
    required this.onDelete,
  });

  @override
  State<_ActiveSectorGroup> createState() => _ActiveSectorGroupState();
}

class _ActiveSectorGroupState extends State<_ActiveSectorGroup>
    with SingleTickerProviderStateMixin {
  bool _expanded = true;
  late final AnimationController _animController;
  late final Animation<double> _expandAnimation;

  @override
  void initState() {
    super.initState();
    _animController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 250),
      value: 1.0, // 초기에 펼쳐진 상태이다.
    );
    _expandAnimation = CurvedAnimation(
      parent: _animController,
      curve: Curves.easeInOutCubic,
    );
  }

  @override
  void dispose() {
    _animController.dispose();
    super.dispose();
  }

  void _toggleExpanded() {
    setState(() {
      _expanded = !_expanded;
      if (_expanded) {
        _animController.forward();
      } else {
        _animController.reverse();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final group = widget.group;
    final color = group.color;

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: GlassCard(
        padding: EdgeInsets.zero,
        child: Column(
          children: [
            // 섹터 헤더 (탭으로 펼치기/접기)
            InkWell(
              onTap: _toggleExpanded,
              borderRadius: _expanded
                  ? const BorderRadius.vertical(
                      top: Radius.circular(AppSpacing.radiusLg))
                  : AppSpacing.borderRadiusLg,
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.07),
                  borderRadius: _expanded
                      ? const BorderRadius.vertical(
                          top: Radius.circular(AppSpacing.radiusLg))
                      : AppSpacing.borderRadiusLg,
                ),
                child: Row(
                  children: [
                    // 섹터 아이콘
                    Container(
                      width: 38,
                      height: 38,
                      decoration: BoxDecoration(
                        color: color.withValues(alpha: 0.15),
                        borderRadius: AppSpacing.borderRadiusMd,
                      ),
                      child: Icon(group.icon, size: 20, color: color),
                    ),
                    AppSpacing.hGapMd,
                    // 섹터명 + 종목 수
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Text(
                                group.nameKr,
                                style: AppTypography.labelLarge.copyWith(
                                  fontSize: 14,
                                  color: context.tc.textPrimary,
                                ),
                              ),
                              if (group.nameEn.isNotEmpty) ...[
                                AppSpacing.hGapSm,
                                Text(
                                  group.nameEn,
                                  style: AppTypography.bodySmall.copyWith(
                                    fontSize: 11,
                                    color: context.tc.textTertiary,
                                  ),
                                ),
                              ],
                            ],
                          ),
                          AppSpacing.vGapXs,
                          // 활성 종목 수 뱃지
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 6, vertical: 2),
                            decoration: BoxDecoration(
                              color: color.withValues(alpha: 0.12),
                              borderRadius: AppSpacing.borderRadiusSm,
                            ),
                            child: Text(
                              '${group.tickers.length}종목 활성',
                              style: AppTypography.bodySmall.copyWith(
                                fontSize: 10,
                                color: color,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    // 펼치기/접기 화살표
                    AnimatedRotation(
                      turns: _expanded ? 0.0 : -0.25,
                      duration: const Duration(milliseconds: 250),
                      curve: Curves.easeInOutCubic,
                      child: Icon(
                        Icons.keyboard_arrow_down_rounded,
                        size: 20,
                        color: context.tc.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            // 종목 카드 목록 (애니메이션으로 펼침/접힘)
            SizeTransition(
              sizeFactor: _expandAnimation,
              axisAlignment: -1.0,
              child: Column(
                children: [
                  Divider(
                    height: 1,
                    color: color.withValues(alpha: 0.15),
                  ),
                  ...group.tickers.asMap().entries.map((entry) {
                    final ticker = entry.value;
                    final isLast = entry.key == group.tickers.length - 1;
                    return Column(
                      children: [
                        _TickerCard(
                          ticker: ticker,
                          inGroup: true,
                          onToggle: (enabled) =>
                              widget.onToggle(ticker.ticker, enabled),
                          onDelete: () => widget.onDelete(ticker),
                        ),
                        if (!isLast)
                          Divider(
                            height: 1,
                            indent: 14,
                            endIndent: 14,
                            color: context.tc.surfaceBorder
                                .withValues(alpha: 0.2),
                          ),
                      ],
                    );
                  }),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 비활성 종목 탭이다.
class _InactiveTickersTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    context.watch<LocaleProvider>().t;
    return Consumer<UniverseProvider>(
      builder: (context, provider, _) {
        if (provider.isLoading && provider.tickers == null) {
          return const Center(child: CircularProgressIndicator());
        }
        final tickers = provider.inactiveTickers;
        if (tickers.isEmpty) {
          return EmptyState(
            icon: Icons.list_alt_rounded,
            title: '비활성 종목 없음',
          );
        }
        return ListView.builder(
          padding: const EdgeInsets.all(20),
          itemCount: tickers.length,
          itemBuilder: (context, index) => StaggeredFadeSlide(
            index: index,
            child: _TickerCard(
              ticker: tickers[index],
              onToggle: (enabled) =>
                  provider.toggleTicker(tickers[index].ticker, enabled),
              onDelete: () {},
            ),
          ),
        );
      },
    );
  }
}

/// 매핑 관리 탭이다.
class _MappingTab extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Consumer<UniverseProvider>(
      builder: (context, provider, _) {
        if (provider.isLoading && provider.mappings == null) {
          return const Center(child: CircularProgressIndicator());
        }
        final mappings = provider.mappings ?? [];

        return Column(
          children: [
            // 매핑 추가 버튼
            Padding(
              padding:
                  const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              child: Row(
                children: [
                  Text('${mappings.length}개 매핑',
                      style: AppTypography.labelMedium),
                  const Spacer(),
                  TextButton.icon(
                    onPressed: () =>
                        _showAddMappingDialog(context, provider, t),
                    icon: const Icon(Icons.add_rounded, size: 16),
                    label: Text('매핑 추가'),
                  ),
                ],
              ),
            ),
            if (mappings.isEmpty)
              Expanded(
                child: EmptyState(
                  icon: Icons.compare_arrows_rounded,
                  title: '매핑 없음',
                  subtitle: '종목 매핑을 추가하세요',
                ),
              )
            else
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: GlassCard(
                    padding: EdgeInsets.zero,
                    child: Column(
                      children: [
                        // 헤더
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 16, vertical: 10),
                          decoration: BoxDecoration(
                            color:
                                context.tc.surfaceElevated.withValues(alpha: 0.5),
                            borderRadius: const BorderRadius.vertical(
                              top: Radius.circular(AppSpacing.radiusLg),
                            ),
                          ),
                          child: Row(
                            children: [
                              _headerCell(t('underlying'), context, flex: 2),
                              _headerCell('Bull 2X', context, flex: 2),
                              _headerCell('Bear 2X', context, flex: 2),
                              _headerCell('', context, flex: 1),
                            ],
                          ),
                        ),
                        // 데이터 행
                        ...mappings.asMap().entries.map((entry) {
                          final mapping = entry.value;
                          return Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 16, vertical: 10),
                            decoration: BoxDecoration(
                              border: Border(
                                top: BorderSide(
                                  color: context.tc.surfaceBorder
                                      .withValues(alpha: 0.2),
                                  width: 1,
                                ),
                              ),
                            ),
                            child: Row(
                              children: [
                                _dataCell(mapping.underlying,
                                    context.tc.textPrimary,
                                    flex: 2, bold: true),
                                _dataCell(
                                  mapping.bull2x ?? '—',
                                  mapping.bull2x != null
                                      ? context.tc.profit
                                      : context.tc.textTertiary,
                                  flex: 2,
                                ),
                                _dataCell(
                                  mapping.bear2x ?? '—',
                                  mapping.bear2x != null
                                      ? context.tc.loss
                                      : context.tc.textTertiary,
                                  flex: 2,
                                ),
                                Expanded(
                                  flex: 1,
                                  child: Row(
                                    mainAxisAlignment: MainAxisAlignment.end,
                                    children: [
                                      InkWell(
                                        onTap: () => _confirmDeleteMapping(
                                          context,
                                          mapping.underlying,
                                          provider,
                                          t,
                                        ),
                                        child: Icon(
                                          Icons.delete_outline_rounded,
                                          size: 16,
                                          color: context.tc.loss
                                              .withValues(alpha: 0.7),
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          );
                        }),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        );
      },
    );
  }

  Widget _headerCell(String label, BuildContext context, {int flex = 1}) {
    return Expanded(
      flex: flex,
      child: Text(
        label,
        style: AppTypography.bodySmall.copyWith(
          color: context.tc.textTertiary,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  Widget _dataCell(String value, Color color,
      {int flex = 1, bool bold = false}) {
    return Expanded(
      flex: flex,
      child: Text(
        value,
        style: AppTypography.labelMedium.copyWith(
          color: color,
          fontWeight: bold ? FontWeight.w700 : FontWeight.w500,
        ),
      ),
    );
  }

  Future<void> _showAddMappingDialog(BuildContext context,
      UniverseProvider provider, String Function(String) t) async {
    final result = await showDialog<Map<String, String?>>(
      context: context,
      builder: (context) => const _AddMappingDialog(),
    );
    if (result != null && context.mounted) {
      final underlying = result['underlying'] ?? '';
      if (underlying.isEmpty) return;
      try {
        await provider.addMapping(
          underlying,
          result['bull2x'],
          result['bear2x'],
        );
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(
                '${result['underlying']} 매핑 ${t('added')}'),
            backgroundColor: context.tc.profit,
          ));
        }
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('${t('failed')}: $e'),
            backgroundColor: context.tc.loss,
          ));
        }
      }
    }
  }

  Future<void> _confirmDeleteMapping(BuildContext context, String underlying,
      UniverseProvider provider, String Function(String) t) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: context.tc.surfaceElevated,
        title: Text(t('confirm_delete'),
            style: AppTypography.headlineMedium),
        content: Text('$underlying 매핑을 삭제하시겠습니까?',
            style: AppTypography.bodyMedium),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(t('cancel')),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, true),
            style:
                ElevatedButton.styleFrom(backgroundColor: context.tc.loss),
            child: Text(t('delete')),
          ),
        ],
      ),
    );
    if (confirmed == true && context.mounted) {
      provider.removeMapping(underlying);
    }
  }
}

/// 섹터별 탭이다.
class _SectorTab extends StatelessWidget {
  /// 섹터 키에 대응하는 아이콘을 반환한다.
  static IconData _sectorIcon(String key) {
    switch (key) {
      case 'semiconductors':
        return Icons.memory;
      case 'big_tech':
        return Icons.computer;
      case 'ai_software':
        return Icons.smart_toy;
      case 'ev_energy':
        return Icons.electric_car;
      case 'crypto':
        return Icons.currency_bitcoin;
      case 'finance':
        return Icons.account_balance;
      case 'quantum':
        return Icons.science;
      case 'entertainment':
        return Icons.movie;
      case 'infrastructure':
        return Icons.domain;
      case 'consumer':
        return Icons.shopping_cart;
      case 'healthcare':
        return Icons.local_hospital;
      default:
        return Icons.category;
    }
  }

  /// 섹터별 배경 색상을 반환한다.
  static Color _sectorBgColor(int index) {
    const colors = [
      Color(0xFF3B82F6), // blue
      Color(0xFF8B5CF6), // violet
      Color(0xFF10B981), // emerald
      Color(0xFFF59E0B), // amber
      Color(0xFFEF4444), // red
      Color(0xFF06B6D4), // cyan
      Color(0xFFEC4899), // pink
      Color(0xFF84CC16), // lime
      Color(0xFFF97316), // orange
      Color(0xFF6366F1), // indigo
      Color(0xFF14B8A6), // teal
      Color(0xFFA855F7), // purple
    ];
    return colors[index % colors.length];
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return Consumer<UniverseProvider>(
      builder: (context, provider, _) {
        if (provider.isSectorsLoading && provider.sectors == null) {
          return _buildLoading();
        }
        final sectors = provider.sectors ?? [];
        if (sectors.isEmpty) {
          return EmptyState(
            icon: Icons.category_rounded,
            title: t('sector_empty'),
          );
        }
        return ListView.builder(
          padding: const EdgeInsets.all(20),
          itemCount: sectors.length,
          itemBuilder: (context, index) => StaggeredFadeSlide(
            index: index,
            child: _SectorCard(
              sector: sectors[index],
              colorSeed: _sectorBgColor(index),
              icon: _sectorIcon(sectors[index].key),
            ),
          ),
        );
      },
    );
  }

  Widget _buildLoading() {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        children: List.generate(
          5,
          (i) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: ShimmerLoading(
              width: double.infinity,
              height: 80,
              borderRadius: AppSpacing.borderRadiusLg,
            ),
          ),
        ),
      ),
    );
  }
}

/// 개별 섹터 카드 위젯이다.
class _SectorCard extends StatefulWidget {
  final SectorData sector;
  final Color colorSeed;
  final IconData icon;

  const _SectorCard({
    required this.sector,
    required this.colorSeed,
    required this.icon,
  });

  @override
  State<_SectorCard> createState() => _SectorCardState();
}

class _SectorCardState extends State<_SectorCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final sector = widget.sector;
    final color = widget.colorSeed;

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: GlassCard(
        padding: EdgeInsets.zero,
        onTap: () => setState(() => _expanded = !_expanded),
        child: Column(
          children: [
            // 섹터 헤더
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.06),
                borderRadius: _expanded
                    ? const BorderRadius.vertical(
                        top: Radius.circular(AppSpacing.radiusLg))
                    : AppSpacing.borderRadiusLg,
              ),
              child: Row(
                children: [
                  // 섹터 아이콘
                  Container(
                    width: 38,
                    height: 38,
                    decoration: BoxDecoration(
                      color: color.withValues(alpha: 0.15),
                      borderRadius: AppSpacing.borderRadiusMd,
                    ),
                    child: Icon(widget.icon, size: 20, color: color),
                  ),
                  AppSpacing.hGapMd,
                  // 섹터 이름 및 정보
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Text(
                              sector.nameKr.isNotEmpty
                                  ? sector.nameKr
                                  : sector.nameEn,
                              style: AppTypography.labelLarge.copyWith(
                                fontSize: 14,
                                color: context.tc.textPrimary,
                              ),
                            ),
                            AppSpacing.hGapSm,
                            if (sector.nameKr.isNotEmpty &&
                                sector.nameEn.isNotEmpty)
                              Text(
                                sector.nameEn,
                                style: AppTypography.bodySmall.copyWith(
                                  fontSize: 11,
                                  color: context.tc.textTertiary,
                                ),
                              ),
                          ],
                        ),
                        AppSpacing.vGapXs,
                        Row(
                          children: [
                            // 종목 수 뱃지
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                color: color.withValues(alpha: 0.12),
                                borderRadius: AppSpacing.borderRadiusSm,
                              ),
                              child: Text(
                                '${sector.totalCount}종목',
                                style: AppTypography.bodySmall.copyWith(
                                  fontSize: 10,
                                  color: color,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                            AppSpacing.hGapSm,
                            // 활성 종목 수
                            if (sector.enabledCount > 0)
                              Text(
                                '${sector.enabledCount}개 활성',
                                style: AppTypography.bodySmall.copyWith(
                                  fontSize: 10,
                                  color: context.tc.profit,
                                ),
                              ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  // 레버리지 ETF 정보
                  if (sector.sectorLeveraged != null) ...[
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        if (sector.sectorLeveraged?.bull != null)
                          _EtfBadge(
                            label: sector.sectorLeveraged?.bull ?? '',
                            color: context.tc.profit,
                            prefix: '▲',
                          ),
                        if (sector.sectorLeveraged?.bear != null) ...[
                          const SizedBox(height: 3),
                          _EtfBadge(
                            label: sector.sectorLeveraged?.bear ?? '',
                            color: context.tc.loss,
                            prefix: '▼',
                          ),
                        ],
                      ],
                    ),
                    AppSpacing.hGapSm,
                  ],
                  // 확장/축소 화살표
                  Icon(
                    _expanded
                        ? Icons.keyboard_arrow_up_rounded
                        : Icons.keyboard_arrow_down_rounded,
                    size: 20,
                    color: context.tc.textTertiary,
                  ),
                ],
              ),
            ),
            // 종목 목록 (확장 시)
            if (_expanded) ...[
              Divider(
                height: 1,
                color: color.withValues(alpha: 0.15),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
                child: Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: sector.tickers
                      .map((ticker) => _TickerChip(
                            ticker: ticker,
                            color: color,
                          ))
                      .toList(),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// ETF 뱃지 위젯이다.
class _EtfBadge extends StatelessWidget {
  final String label;
  final Color color;
  final String prefix;

  const _EtfBadge({
    required this.label,
    required this.color,
    required this.prefix,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: AppSpacing.borderRadiusSm,
        border: Border.all(
          color: color.withValues(alpha: 0.25),
          width: 1,
        ),
      ),
      child: Text(
        '$prefix $label',
        style: AppTypography.bodySmall.copyWith(
          fontSize: 10,
          color: color,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

/// 종목 칩 위젯이다.
class _TickerChip extends StatelessWidget {
  final String ticker;
  final Color color;

  const _TickerChip({
    required this.ticker,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.07),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: color.withValues(alpha: 0.20),
          width: 1,
        ),
      ),
      child: Text(
        ticker,
        style: AppTypography.labelMedium.copyWith(
          fontSize: 11,
          color: context.tc.textPrimary,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

/// 종목 카드 위젯이다.
/// [inGroup]이 true이면 섹터 그룹 내부에서 사용되며, GlassCard 없이 padding만 적용한다.
class _TickerCard extends StatelessWidget {
  final UniverseTickerEx ticker;
  final ValueChanged<bool> onToggle;
  final VoidCallback onDelete;
  final bool inGroup;

  const _TickerCard({
    required this.ticker,
    required this.onToggle,
    required this.onDelete,
    this.inGroup = false,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    final isBull = ticker.direction.toLowerCase() == 'bull';

    final content = Row(
          children: [
            // 방향 인디케이터
            Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(
                color: isBull
                    ? context.tc.profit.withValues(alpha: 0.12)
                    : context.tc.loss.withValues(alpha: 0.12),
                borderRadius: AppSpacing.borderRadiusMd,
              ),
              child: Icon(
                isBull
                    ? Icons.trending_up_rounded
                    : Icons.trending_down_rounded,
                size: 18,
                color: isBull ? context.tc.profit : context.tc.loss,
              ),
            ),
            AppSpacing.hGapMd,
            // 종목 정보
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        ticker.ticker,
                        style: AppTypography.labelLarge.copyWith(fontSize: 15),
                      ),
                      AppSpacing.hGapSm,
                      // 레버리지 뱃지
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 5, vertical: 2),
                        decoration: BoxDecoration(
                          color: context.tc.primary.withValues(alpha: 0.1),
                          borderRadius: AppSpacing.borderRadiusSm,
                        ),
                        child: Text(
                          '${ticker.leverage}x',
                          style: AppTypography.bodySmall.copyWith(
                            color: context.tc.primary,
                            fontSize: 10,
                          ),
                        ),
                      ),
                      if (ticker.underlying != null) ...[
                        AppSpacing.hGapSm,
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: isBull
                                ? context.tc.profit.withValues(alpha: 0.1)
                                : context.tc.loss.withValues(alpha: 0.1),
                            borderRadius: AppSpacing.borderRadiusSm,
                          ),
                          child: Text(
                            ticker.underlying ?? '',
                            style: AppTypography.bodySmall.copyWith(
                              color: isBull ? context.tc.profit : context.tc.loss,
                              fontSize: 10,
                            ),
                          ),
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
                  if (ticker.avgDailyVolume != null ||
                      ticker.expenseRatio != null) ...[
                    AppSpacing.vGapXs,
                    Row(
                      children: [
                        if (ticker.avgDailyVolume != null)
                          Text(
                            'Vol: ${_formatVolume(ticker.avgDailyVolume ?? 0)}',
                            style: AppTypography.bodySmall.copyWith(
                              fontSize: 10,
                              color: (ticker.avgDailyVolume ?? 0) < 100000
                                  ? context.tc.warning
                                  : context.tc.textTertiary,
                            ),
                          ),
                        if (ticker.expenseRatio != null) ...[
                          AppSpacing.hGapMd,
                          Text(
                            'ER: ${ticker.expenseRatio}%',
                            style: AppTypography.bodySmall.copyWith(
                                fontSize: 10),
                          ),
                        ],
                      ],
                    ),
                  ],
                ],
              ),
            ),
            // 토글 + 삭제
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Switch(
                  value: ticker.enabled,
                  onChanged: onToggle,
                  activeColor: context.tc.primary,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                AppSpacing.hGapSm,
                IconButton(
                  onPressed: onDelete,
                  icon: Icon(
                    Icons.delete_outline_rounded,
                    size: 18,
                    color: context.tc.loss.withValues(alpha: 0.7),
                  ),
                  padding: EdgeInsets.zero,
                  constraints:
                      const BoxConstraints(minWidth: 28, minHeight: 28),
                  tooltip: t('remove_ticker'),
                ),
              ],
            ),
          ],
        );

    // 섹터 그룹 내에서는 GlassCard 없이 padding만 적용한다.
    if (inGroup) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        child: content,
      );
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: GlassCard(
        padding: const EdgeInsets.all(14),
        child: content,
      ),
    );
  }

  String _formatVolume(int volume) {
    if (volume >= 1000000) {
      return '${(volume / 1000000).toStringAsFixed(1)}M';
    } else if (volume >= 1000) {
      return '${(volume / 1000).toStringAsFixed(0)}K';
    }
    return '$volume';
  }
}

/// 종목 추가 다이얼로그이다.
class _AddTickerDialog extends StatefulWidget {
  const _AddTickerDialog();

  @override
  State<_AddTickerDialog> createState() => _AddTickerDialogState();
}

class _AddTickerDialogState extends State<_AddTickerDialog> {
  final _formKey = GlobalKey<FormState>();
  final _tickerCtrl = TextEditingController();
  final _nameCtrl = TextEditingController();
  final _underlyingCtrl = TextEditingController();
  final _bull2xCtrl = TextEditingController();
  final _bear2xCtrl = TextEditingController();
  String _direction = 'bull';

  @override
  void dispose() {
    _tickerCtrl.dispose();
    _nameCtrl.dispose();
    _underlyingCtrl.dispose();
    _bull2xCtrl.dispose();
    _bear2xCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return AlertDialog(
      backgroundColor: context.tc.surfaceElevated,
      title: Text(t('add_ticker'), style: AppTypography.headlineMedium),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _field(
                  controller: _tickerCtrl,
                  label: t('ticker'),
                  hint: 'e.g. TSLL',
                  required: true,
                ),
                AppSpacing.vGapMd,
                _field(
                  controller: _nameCtrl,
                  label: '이름',
                  hint: 'e.g. Direxion Daily TSLA Bull 2X',
                  required: true,
                ),
                AppSpacing.vGapMd,
                _field(
                  controller: _underlyingCtrl,
                  label: t('underlying'),
                  hint: 'e.g. TSLA',
                ),
                AppSpacing.vGapMd,
                Text('방향', style: AppTypography.labelMedium),
                AppSpacing.vGapXs,
                Row(
                  children: ['bull', 'bear'].map((d) {
                    final isSelected = _direction == d;
                    return Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: GestureDetector(
                        onTap: () => setState(() => _direction = d),
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 150),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 14, vertical: 8),
                          decoration: BoxDecoration(
                            color: isSelected
                                ? (d == 'bull'
                                    ? context.tc.profit.withValues(alpha: 0.15)
                                    : context.tc.loss.withValues(alpha: 0.15))
                                : context.tc.surface,
                            borderRadius: AppSpacing.borderRadiusMd,
                            border: Border.all(
                              color: isSelected
                                  ? (d == 'bull'
                                      ? context.tc.profit.withValues(alpha: 0.4)
                                      : context.tc.loss.withValues(alpha: 0.4))
                                  : context.tc.surfaceBorder
                                      .withValues(alpha: 0.3),
                            ),
                          ),
                          child: Text(
                            d == 'bull'
                                ? t('leveraged_bull')
                                : t('leveraged_bear'),
                            style: AppTypography.labelMedium.copyWith(
                              color: isSelected
                                  ? (d == 'bull'
                                      ? context.tc.profit
                                      : context.tc.loss)
                                  : context.tc.textSecondary,
                            ),
                          ),
                        ),
                      ),
                    );
                  }).toList(),
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(t('cancel')),
        ),
        ElevatedButton(
          onPressed: _submit,
          style: ElevatedButton.styleFrom(
            backgroundColor: context.tc.primary,
            foregroundColor: Colors.white,
          ),
          child: Text(t('save')),
        ),
      ],
    );
  }

  Widget _field({
    required TextEditingController controller,
    required String label,
    String? hint,
    bool required = false,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: AppTypography.labelMedium),
        AppSpacing.vGapXs,
        TextFormField(
          controller: controller,
          style: AppTypography.bodyMedium.copyWith(
              color: context.tc.textPrimary),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: AppTypography.bodySmall,
            filled: true,
            fillColor: context.tc.surface,
            border: OutlineInputBorder(
              borderRadius: AppSpacing.borderRadiusMd,
              borderSide:
                  BorderSide(color: context.tc.surfaceBorder.withValues(alpha: 0.3)),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: AppSpacing.borderRadiusMd,
              borderSide:
                  BorderSide(color: context.tc.surfaceBorder.withValues(alpha: 0.3)),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: AppSpacing.borderRadiusMd,
              borderSide: BorderSide(
                  color: context.tc.primary.withValues(alpha: 0.5), width: 1.5),
            ),
            contentPadding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            isDense: true,
          ),
          validator: required
              ? (v) => (v == null || v.trim().isEmpty) ? '필수 입력' : null
              : null,
        ),
      ],
    );
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final data = <String, dynamic>{
      'ticker': _tickerCtrl.text.trim().toUpperCase(),
      'name': _nameCtrl.text.trim(),
      'direction': _direction,
      'enabled': true,
      'leverage': 2.0,
    };
    if (_underlyingCtrl.text.trim().isNotEmpty) {
      data['underlying'] = _underlyingCtrl.text.trim().toUpperCase();
    }
    Navigator.pop(context, data);
  }
}

/// 매핑 추가 다이얼로그이다.
class _AddMappingDialog extends StatefulWidget {
  const _AddMappingDialog();

  @override
  State<_AddMappingDialog> createState() => _AddMappingDialogState();
}

class _AddMappingDialogState extends State<_AddMappingDialog> {
  final _formKey = GlobalKey<FormState>();
  final _underlyingCtrl = TextEditingController();
  final _bull2xCtrl = TextEditingController();
  final _bear2xCtrl = TextEditingController();

  @override
  void dispose() {
    _underlyingCtrl.dispose();
    _bull2xCtrl.dispose();
    _bear2xCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    return AlertDialog(
      backgroundColor: context.tc.surfaceElevated,
      title: Text('매핑 추가', style: AppTypography.headlineMedium),
      content: SizedBox(
        width: 380,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _inputField(
                controller: _underlyingCtrl,
                label: t('underlying'),
                hint: 'e.g. SPY',
                required: true,
              ),
              AppSpacing.vGapMd,
              _inputField(
                controller: _bull2xCtrl,
                label: 'Bull 2X',
                hint: 'e.g. SSO',
              ),
              AppSpacing.vGapMd,
              _inputField(
                controller: _bear2xCtrl,
                label: 'Bear 2X',
                hint: 'e.g. SDS',
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(t('cancel')),
        ),
        ElevatedButton(
          onPressed: () {
            if (!(_formKey.currentState?.validate() ?? false)) return;
            Navigator.pop(context, {
              'underlying': _underlyingCtrl.text.trim().toUpperCase(),
              'bull2x': _bull2xCtrl.text.trim().isNotEmpty
                  ? _bull2xCtrl.text.trim().toUpperCase()
                  : null,
              'bear2x': _bear2xCtrl.text.trim().isNotEmpty
                  ? _bear2xCtrl.text.trim().toUpperCase()
                  : null,
            });
          },
          style: ElevatedButton.styleFrom(
            backgroundColor: context.tc.primary,
            foregroundColor: Colors.white,
          ),
          child: Text(t('save')),
        ),
      ],
    );
  }

  Widget _inputField({
    required TextEditingController controller,
    required String label,
    String? hint,
    bool required = false,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: AppTypography.labelMedium),
        AppSpacing.vGapXs,
        TextFormField(
          controller: controller,
          style: AppTypography.bodyMedium.copyWith(
              color: context.tc.textPrimary),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: AppTypography.bodySmall,
            filled: true,
            fillColor: context.tc.surface,
            border: OutlineInputBorder(
              borderRadius: AppSpacing.borderRadiusMd,
              borderSide:
                  BorderSide(color: context.tc.surfaceBorder.withValues(alpha: 0.3)),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: AppSpacing.borderRadiusMd,
              borderSide:
                  BorderSide(color: context.tc.surfaceBorder.withValues(alpha: 0.3)),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: AppSpacing.borderRadiusMd,
              borderSide: BorderSide(
                  color: context.tc.primary.withValues(alpha: 0.5), width: 1.5),
            ),
            contentPadding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            isDense: true,
          ),
          validator: required
              ? (v) => (v == null || v.trim().isEmpty) ? '필수 입력' : null
              : null,
        ),
      ],
    );
  }
}
