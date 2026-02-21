import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/dashboard_provider.dart';
import '../providers/trade_provider.dart';
import '../providers/profit_target_provider.dart';
import '../providers/locale_provider.dart';
import '../providers/trading_mode_provider.dart';
import '../models/dashboard_models.dart';
import '../models/trade_models.dart';
import '../theme/app_typography.dart';
import '../theme/trading_colors.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/section_header.dart';
import '../widgets/empty_state.dart';
import '../widgets/confirmation_dialog.dart';
import '../animations/animation_utils.dart';

class OverviewScreen extends StatefulWidget {
  const OverviewScreen({super.key});

  @override
  State<OverviewScreen> createState() => _OverviewScreenState();
}

class _OverviewScreenState extends State<OverviewScreen> {
  // dispose()에서 context 없이 removeListener를 호출하기 위해
  // TradingModeProvider 참조를 저장한다.
  TradingModeProvider? _tradingModeProvider;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      // TradingModeProvider의 현재 모드를 DashboardProvider에 동기화하여
      // 포지션·계좌 데이터가 올바른 모드(virtual/real)로 로드되게 한다.
      // _currentMode가 같아도 강제로 loadDashboardData를 호출한다.
      final dashProvider = context.read<DashboardProvider>();
      _tradingModeProvider = context.read<TradingModeProvider>();
      final initialMode = _tradingModeProvider!.mode;
      dashProvider.syncModeAndLoad(initialMode);
      context.read<TradeProvider>().loadPendingAdjustments();
      context.read<ProfitTargetProvider>().loadStatus();

      // 투자 모드 변경 시 대시보드 데이터를 재로드한다
      _tradingModeProvider!.addListener(_onModeChanged);
    });
  }

  @override
  void dispose() {
    // 위젯이 파괴될 때 리스너를 해제한다.
    // dispose() 시점에는 mounted == false이므로 context를 사용하지 않고
    // initState에서 저장한 참조로 removeListener를 호출한다.
    _tradingModeProvider?.removeListener(_onModeChanged);
    super.dispose();
  }

  void _onModeChanged() {
    if (!mounted) return;
    final mode = context.read<TradingModeProvider>().mode;
    context.read<DashboardProvider>().setMode(mode);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.tc.background,
      body: Consumer<DashboardProvider>(
        builder: (context, provider, _) {
          if (provider.isLoading && provider.summary == null) {
            return _buildLoadingSkeleton();
          }

          // 서버 미연결 상태이고 데이터가 전혀 없으면 전용 화면을 표시한다
          if (provider.isServerDisconnected && provider.summary == null) {
            return _buildServerDisconnectedScreen(provider);
          }

          // 일반 에러이고 데이터가 없으면 에러 화면을 표시한다
          if (provider.error != null &&
              !provider.isServerDisconnected &&
              provider.summary == null) {
            return ErrorState(
              message: provider.error ?? '',
              onRetry: () => provider.refresh(),
            );
          }

          return Column(
            children: [
              // 서버 미연결 배너: 이전에 로드한 데이터는 계속 표시하면서 배너를 함께 보여준다
              if (provider.isServerDisconnected)
                _buildDisconnectedBanner(provider),
              Expanded(
                child: RefreshIndicator(
                  onRefresh: () async {
                    final tradeProvider = context.read<TradeProvider>();
                    await provider.refresh();
                    if (mounted) {
                      tradeProvider.loadPendingAdjustments();
                    }
                  },
                  color: context.tc.primary,
                  backgroundColor: context.tc.surfaceElevated,
                  child: SingleChildScrollView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.all(20),
                    child: _buildContent(provider),
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  /// 서버 미연결 상태를 나타내는 상단 배너이다.
  /// 데이터가 있을 때는 이 배너만 표시하고 기존 데이터를 계속 보여준다.
  Widget _buildDisconnectedBanner(DashboardProvider provider) {
    final t = context.watch<LocaleProvider>().t;
    final isReconnecting =
        provider.connectionState == ServerConnectionState.reconnecting;
    final countdown = provider.retryCountdown;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      width: double.infinity,
      color: context.tc.warning.withValues(alpha: 0.15),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      child: Row(
        children: [
          Icon(
            isReconnecting
                ? Icons.sync_rounded
                : Icons.cloud_off_rounded,
            size: 16,
            color: context.tc.warning,
          ),
          AppSpacing.hGapSm,
          Expanded(
            child: Text(
              isReconnecting
                  ? t('server_reconnecting')
                  : countdown > 0
                      ? t('retry_in').replaceAll('{n}', '$countdown')
                      : t('server_disconnected'),
              style: AppTypography.bodySmall.copyWith(
                color: context.tc.warning,
              ),
            ),
          ),
          // 즉시 재연결 버튼
          if (!isReconnecting)
            GestureDetector(
              onTap: () => provider.refresh(),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: context.tc.warning.withValues(alpha: 0.20),
                  borderRadius: AppSpacing.borderRadiusSm,
                  border: Border.all(
                    color: context.tc.warning.withValues(alpha: 0.40),
                  ),
                ),
                child: Text(
                  t('retry'),
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.warning,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// 서버 미연결 상태이고 데이터도 없을 때 표시하는 전용 화면이다.
  Widget _buildServerDisconnectedScreen(DashboardProvider provider) {
    final t = context.watch<LocaleProvider>().t;
    final isReconnecting =
        provider.connectionState == ServerConnectionState.reconnecting;
    final countdown = provider.retryCountdown;

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(40),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // 아이콘
            Container(
              width: 80,
              height: 80,
              decoration: BoxDecoration(
                color: context.tc.warning.withValues(alpha: 0.10),
                shape: BoxShape.circle,
                border: Border.all(
                  color: context.tc.warning.withValues(alpha: 0.30),
                  width: 1.5,
                ),
              ),
              child: Icon(
                Icons.cloud_off_rounded,
                size: 36,
                color: context.tc.warning,
              ),
            ),
            AppSpacing.vGapLg,
            // 제목
            Text(
              t('server_disconnected'),
              style: AppTypography.displaySmall.copyWith(
                color: context.tc.textPrimary,
              ),
              textAlign: TextAlign.center,
            ),
            AppSpacing.vGapSm,
            // 안내 문구
            Text(
              t('server_disconnected_hint'),
              style: AppTypography.bodyMedium.copyWith(
                color: context.tc.textTertiary,
              ),
              textAlign: TextAlign.center,
            ),
            AppSpacing.vGapXl,
            // 재연결 중 표시 또는 카운트다운
            if (isReconnecting)
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      valueColor: AlwaysStoppedAnimation<Color>(
                          context.tc.warning),
                    ),
                  ),
                  AppSpacing.hGapSm,
                  Text(
                    t('server_reconnecting'),
                    style: AppTypography.bodySmall.copyWith(
                      color: context.tc.textTertiary,
                    ),
                  ),
                ],
              )
            else if (countdown > 0)
              Text(
                t('retry_in').replaceAll('{n}', '$countdown'),
                style: AppTypography.bodySmall.copyWith(
                  color: context.tc.textTertiary,
                ),
              ),
            AppSpacing.vGapLg,
            // 즉시 재시도 버튼
            if (!isReconnecting)
              FilledButton.icon(
                onPressed: () => provider.refresh(),
                icon: const Icon(Icons.refresh_rounded, size: 18),
                label: Text(t('retry')),
                style: FilledButton.styleFrom(
                  backgroundColor: context.tc.warning,
                  foregroundColor: Colors.black87,
                  padding: const EdgeInsets.symmetric(
                      horizontal: 24, vertical: 12),
                  shape: RoundedRectangleBorder(
                    borderRadius: AppSpacing.borderRadiusMd,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildContent(DashboardProvider provider) {
    final t = context.watch<LocaleProvider>().t;
    final summary = provider.summary;
    final systemStatus = provider.systemStatus;

    if (summary == null) {
      return EmptyState(
        icon: Icons.dashboard_rounded,
        title: t('no_data_available'),
        subtitle: t('connect_to_system'),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 투자 모드 전환 토글 + 듀얼 계좌 요약
        StaggeredFadeSlide(
          index: 0,
          child: _buildTradingModeSection(),
        ),
        AppSpacing.vGapLg,
        // 포트폴리오 히어로 섹션
        StaggeredFadeSlide(
          index: 1,
          child: _buildHeroCard(summary),
        ),
        AppSpacing.vGapLg,
        // 메인 2열 레이아웃
        LayoutBuilder(
          builder: (context, constraints) {
            if (constraints.maxWidth >= 900) {
              return _buildTwoColumnLayout(summary, systemStatus);
            }
            return _buildSingleColumnLayout(summary, systemStatus);
          },
        ),
      ],
    );
  }

  // ── 투자 모드 전환 섹션 ──

  /// 모드 전환 토글과 듀얼 계좌 요약 카드를 포함한 섹션이다.
  Widget _buildTradingModeSection() {
    final t = context.watch<LocaleProvider>().t;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildModeToggle(t),
        AppSpacing.vGapMd,
        _buildDualAccountCards(t),
        AppSpacing.vGapMd,
        _buildPositionCards(t),
      ],
    );
  }

  /// 보유 포지션 카드 리스트를 빌드한다.
  Widget _buildPositionCards(String Function(String) t) {
    return Consumer<DashboardProvider>(
      builder: (context, provider, _) {
        final positions = provider.positions;

        if (positions.isEmpty) {
          return Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 16),
            decoration: BoxDecoration(
              color: context.tc.surfaceElevated.withValues(alpha: 0.5),
              borderRadius: AppSpacing.borderRadiusMd,
              border: Border.all(
                color: context.tc.surfaceBorder.withValues(alpha: 0.25),
                width: 1,
              ),
            ),
            child: Row(
              children: [
                Icon(
                  Icons.inventory_2_outlined,
                  size: 14,
                  color: context.tc.textTertiary,
                ),
                AppSpacing.hGapSm,
                Text(
                  t('no_holdings'),
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.textTertiary,
                  ),
                ),
              ],
            ),
          );
        }

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 섹션 레이블
            Row(
              children: [
                Icon(
                  Icons.pie_chart_outline_rounded,
                  size: 13,
                  color: context.tc.textTertiary,
                ),
                AppSpacing.hGapXs,
                Text(
                  t('holding_positions'),
                  style: AppTypography.bodySmall.copyWith(
                    fontSize: 11,
                    color: context.tc.textTertiary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                AppSpacing.hGapXs,
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                  decoration: BoxDecoration(
                    color: context.tc.primary.withValues(alpha: 0.12),
                    borderRadius: AppSpacing.borderRadiusFull,
                  ),
                  child: Text(
                    '${positions.length}',
                    style: AppTypography.bodySmall.copyWith(
                      fontSize: 10,
                      color: context.tc.primary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            AppSpacing.vGapSm,
            // 포지션 카드 목록
            ...positions.map((pos) => _buildSinglePositionCard(pos, t)),
          ],
        );
      },
    );
  }

  /// 개별 포지션 카드를 빌드한다.
  Widget _buildSinglePositionCard(
    Map<String, dynamic> pos,
    String Function(String) t,
  ) {
    final ticker = pos['ticker'] as String? ?? '';
    final name = pos['name'] as String? ?? '';
    final quantity = (pos['quantity'] as num?)?.toInt() ?? 0;
    final avgPrice = (pos['avg_price'] as num?)?.toDouble() ?? 0.0;
    final currentPrice = (pos['current_price'] as num?)?.toDouble() ?? 0.0;
    final pnlPct = (pos['pnl_pct'] as num?)?.toDouble() ?? 0.0;
    final pnlAmount = (pos['pnl_amount'] as num?)?.toDouble() ?? 0.0;
    final currentValue = (pos['current_value'] as num?)?.toDouble() ?? 0.0;

    final isProfit = pnlPct >= 0;
    final pnlColor = context.tc.pnlColor(pnlPct);

    final fmtPrice = NumberFormat.currency(symbol: '\$', decimalDigits: 2);
    final fmtValue = NumberFormat.currency(symbol: '\$', decimalDigits: 0);

    // 티커 심볼 배경 색상 (ticker 첫 글자로 결정)
    final tickerColors = [
      context.tc.primary,
      context.tc.chart2,
      context.tc.chart3,
      context.tc.chart4,
      context.tc.chart5,
    ];
    final colorIndex = ticker.isNotEmpty ? ticker.codeUnitAt(0) % tickerColors.length : 0;
    final symbolColor = tickerColors[colorIndex];

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: context.tc.surfaceElevated.withValues(alpha: 0.6),
          borderRadius: AppSpacing.borderRadiusMd,
          border: Border.all(
            color: pnlColor.withValues(alpha: 0.15),
            width: 1,
          ),
        ),
        child: Row(
          children: [
            // 왼쪽: 티커 심볼 배경 박스
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: symbolColor.withValues(alpha: 0.12),
                borderRadius: AppSpacing.borderRadiusMd,
                border: Border.all(
                  color: symbolColor.withValues(alpha: 0.25),
                  width: 1,
                ),
              ),
              child: Center(
                child: Text(
                  ticker.length > 4 ? ticker.substring(0, 4) : ticker,
                  style: AppTypography.labelLarge.copyWith(
                    color: symbolColor,
                    fontSize: ticker.length > 3 ? 9 : 11,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ),
            AppSpacing.hGapMd,
            // 중앙: 종목명 + 수량/단가 정보
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // 티커 + 종목명
                  Text(
                    ticker,
                    style: AppTypography.labelLarge.copyWith(
                      fontWeight: FontWeight.w700,
                      fontSize: 13,
                    ),
                  ),
                  if (name.isNotEmpty)
                    Text(
                      name,
                      style: AppTypography.bodySmall.copyWith(
                        color: context.tc.textTertiary,
                        fontSize: 10,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  AppSpacing.vGapXs,
                  // 수량 / 평균단가 / 현재가 인라인
                  Row(
                    children: [
                      _buildPositionMeta(
                        '$quantity${t('shares')}',
                        Icons.format_list_numbered_rounded,
                      ),
                      _buildPositionMetaDivider(),
                      _buildPositionMeta(
                        '${t('avg_price')} ${fmtPrice.format(avgPrice)}',
                        Icons.price_change_outlined,
                      ),
                      _buildPositionMetaDivider(),
                      _buildPositionMeta(
                        fmtPrice.format(currentPrice),
                        Icons.show_chart_rounded,
                      ),
                    ],
                  ),
                ],
              ),
            ),
            AppSpacing.hGapSm,
            // 오른쪽: 수익률 + 수익금액 + 평가금액
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                // 수익률
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                  decoration: BoxDecoration(
                    color: pnlColor.withValues(alpha: 0.12),
                    borderRadius: AppSpacing.borderRadiusSm,
                  ),
                  child: Text(
                    '${isProfit ? '+' : ''}${pnlPct.toStringAsFixed(2)}%',
                    style: AppTypography.numberSmall.copyWith(
                      color: pnlColor,
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                AppSpacing.vGapXs,
                // 수익금액
                Text(
                  '${isProfit ? '+' : ''}${fmtPrice.format(pnlAmount)}',
                  style: AppTypography.numberSmall.copyWith(
                    color: pnlColor,
                    fontSize: 11,
                  ),
                ),
                AppSpacing.vGapXs,
                // 평가금액
                Text(
                  fmtValue.format(currentValue),
                  style: AppTypography.numberSmall.copyWith(
                    color: context.tc.textSecondary,
                    fontSize: 10,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// 포지션 메타 정보 아이콘+텍스트 조합이다.
  Widget _buildPositionMeta(String text, IconData icon) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 10, color: context.tc.textTertiary),
        const SizedBox(width: 2),
        Text(
          text,
          style: AppTypography.bodySmall.copyWith(
            fontSize: 10,
            color: context.tc.textTertiary,
          ),
        ),
      ],
    );
  }

  /// 포지션 메타 정보 사이 구분자이다.
  Widget _buildPositionMetaDivider() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: Text(
        '·',
        style: AppTypography.bodySmall.copyWith(
          fontSize: 10,
          color: context.tc.textDisabled,
        ),
      ),
    );
  }

  /// 모의투자 / 실전투자 세그먼트 토글 버튼이다.
  Widget _buildModeToggle(String Function(String) t) {
    return Consumer<TradingModeProvider>(
      builder: (context, modeProvider, _) {
        final isVirtual = modeProvider.isVirtual;
        final virtualColor = context.tc.primary;
        final realColor = context.tc.warning;

        return Container(
          padding: const EdgeInsets.all(4),
          decoration: BoxDecoration(
            color: context.tc.surfaceElevated,
            borderRadius: AppSpacing.borderRadiusLg,
            border: Border.all(
              color: context.tc.surfaceBorder.withValues(alpha: 0.5),
              width: 1,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              // 모의투자 버튼
              _buildModeTab(
                label: t('virtual_trading'),
                icon: Icons.science_rounded,
                isActive: isVirtual,
                activeColor: virtualColor,
                onTap: () => modeProvider.switchMode(TradingMode.virtual),
              ),
              const SizedBox(width: 4),
              // 실전투자 버튼
              _buildModeTab(
                label: t('real_trading'),
                icon: Icons.attach_money_rounded,
                isActive: !isVirtual,
                activeColor: realColor,
                onTap: () => modeProvider.switchMode(TradingMode.real),
              ),
            ],
          ),
        );
      },
    );
  }

  /// 단일 모드 탭 버튼이다.
  Widget _buildModeTab({
    required String label,
    required IconData icon,
    required bool isActive,
    required Color activeColor,
    required VoidCallback onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeInOut,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        decoration: BoxDecoration(
          color: isActive
              ? activeColor.withValues(alpha: 0.15)
              : Colors.transparent,
          borderRadius: AppSpacing.borderRadiusMd,
          border: isActive
              ? Border.all(
                  color: activeColor.withValues(alpha: 0.35),
                  width: 1,
                )
              : null,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              size: 14,
              color: isActive ? activeColor : context.tc.textTertiary,
            ),
            AppSpacing.hGapXs,
            Text(
              label,
              style: AppTypography.labelLarge.copyWith(
                fontSize: 13,
                color: isActive ? activeColor : context.tc.textTertiary,
                fontWeight:
                    isActive ? FontWeight.w700 : FontWeight.w400,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 모의투자 / 실전투자 계좌 잔액을 나란히 표시하는 카드이다.
  Widget _buildDualAccountCards(String Function(String) t) {
    return Consumer2<DashboardProvider, TradingModeProvider>(
      builder: (context, dashProvider, modeProvider, _) {
        final accounts = dashProvider.accountsSummary;
        final virtualData =
            accounts['virtual'] as Map<String, dynamic>? ?? {};
        final realData =
            accounts['real'] as Map<String, dynamic>? ?? {};
        final isVirtual = modeProvider.isVirtual;

        return Row(
          children: [
            // 모의투자 카드
            Expanded(
              child: _buildAccountMiniCard(
                t: t,
                label: t('virtual_account'),
                icon: Icons.science_rounded,
                accountNumber: virtualData['account_number'] as String? ?? '****7255-01',
                totalAsset: (virtualData['total_asset'] as num?)?.toDouble() ?? 0,
                cash: (virtualData['cash'] as num?)?.toDouble() ?? 0,
                positionCount: (virtualData['positions_count'] as int?) ?? 0,
                isActive: isVirtual,
                activeColor: context.tc.primary,
                onTap: () => modeProvider.switchMode(TradingMode.virtual),
              ),
            ),
            AppSpacing.hGapMd,
            // 실전투자 카드
            Expanded(
              child: _buildAccountMiniCard(
                t: t,
                label: t('real_account'),
                icon: Icons.attach_money_rounded,
                accountNumber: realData['account_number'] as String? ?? '****2903-01',
                totalAsset: (realData['total_asset'] as num?)?.toDouble() ?? 0,
                cash: (realData['cash'] as num?)?.toDouble() ?? 0,
                positionCount: (realData['positions_count'] as int?) ?? 0,
                isActive: !isVirtual,
                activeColor: context.tc.warning,
                onTap: () => modeProvider.switchMode(TradingMode.real),
              ),
            ),
          ],
        );
      },
    );
  }

  /// 개별 계좌 미니 카드이다.
  Widget _buildAccountMiniCard({
    required String Function(String) t,
    required String label,
    required IconData icon,
    required String accountNumber,
    required double totalAsset,
    required double cash,
    required int positionCount,
    required bool isActive,
    required Color activeColor,
    required VoidCallback onTap,
  }) {
    final fmt = NumberFormat.currency(symbol: '\$', decimalDigits: 0);
    final fmtCash = NumberFormat.currency(symbol: '\$', decimalDigits: 2);
    final hasData = totalAsset > 0;

    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeInOut,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: isActive
              ? activeColor.withValues(alpha: 0.08)
              : context.tc.surfaceElevated.withValues(alpha: 0.5),
          borderRadius: AppSpacing.borderRadiusMd,
          border: Border.all(
            color: isActive
                ? activeColor.withValues(alpha: 0.30)
                : context.tc.surfaceBorder.withValues(alpha: 0.25),
            width: isActive ? 1.5 : 1,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 라벨 + 아이콘
            Row(
              children: [
                Icon(
                  icon,
                  size: 13,
                  color: isActive ? activeColor : context.tc.textTertiary,
                ),
                AppSpacing.hGapXs,
                Text(
                  label,
                  style: AppTypography.bodySmall.copyWith(
                    fontSize: 11,
                    color: isActive ? activeColor : context.tc.textTertiary,
                    fontWeight: isActive ? FontWeight.w600 : FontWeight.w400,
                  ),
                ),
                if (isActive) ...[
                  const Spacer(),
                  Container(
                    width: 6,
                    height: 6,
                    decoration: BoxDecoration(
                      color: activeColor,
                      shape: BoxShape.circle,
                    ),
                  ),
                ],
              ],
            ),
            AppSpacing.vGapSm,
            // 총 자산
            Opacity(
              opacity: isActive ? 1.0 : 0.55,
              child: Text(
                hasData ? fmt.format(totalAsset) : '--',
                style: AppTypography.numberMedium.copyWith(
                  fontSize: 16,
                  color: isActive ? context.tc.textPrimary : context.tc.textSecondary,
                  fontWeight: FontWeight.w700,
                ),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            AppSpacing.vGapXs,
            // 현금 잔액
            Opacity(
              opacity: isActive ? 0.85 : 0.45,
              child: Row(
                children: [
                  Icon(
                    Icons.account_balance_wallet_rounded,
                    size: 10,
                    color: isActive ? context.tc.textSecondary : context.tc.textTertiary,
                  ),
                  const SizedBox(width: 3),
                  Text(
                    '${t('cash')} ${fmtCash.format(cash)}',
                    style: AppTypography.bodySmall.copyWith(
                      fontSize: 10,
                      color: isActive ? context.tc.textSecondary : context.tc.textTertiary,
                    ),
                  ),
                ],
              ),
            ),
            AppSpacing.vGapXs,
            // 계좌번호
            Opacity(
              opacity: isActive ? 0.7 : 0.4,
              child: Text(
                accountNumber,
                style: AppTypography.bodySmall.copyWith(
                  fontSize: 10,
                  color: context.tc.textTertiary,
                ),
              ),
            ),
            AppSpacing.vGapXs,
            // 포지션 수
            Opacity(
              opacity: isActive ? 0.85 : 0.45,
              child: Text(
                '${t('positions')} $positionCount',
                style: AppTypography.bodySmall.copyWith(
                  fontSize: 10,
                  color: isActive ? activeColor : context.tc.textTertiary,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── 히어로 카드 ──

  Widget _buildHeroCard(DashboardSummary summary) {
    final t = context.watch<LocaleProvider>().t;
    final isProfit = summary.todayPnl >= 0;
    final pnlColor = context.tc.pnlColor(summary.todayPnl);
    // 백엔드는 achievement_pct를 반환한다 (달성률 %)
    final monthlyPct =
        context.watch<ProfitTargetProvider>().status?.achievementPct ?? 0;

    return GlassCard(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // 계좌번호를 총 자산 레이블 옆에 작게 표시한다
                    Row(
                      children: [
                        Text(
                          t('total_portfolio'),
                          style: AppTypography.bodyMedium,
                        ),
                        AppSpacing.hGapSm,
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: context.tc.surfaceElevated,
                            borderRadius: AppSpacing.borderRadiusSm,
                            border: Border.all(
                              color: context.tc.surfaceBorder
                                  .withValues(alpha: 0.5),
                            ),
                          ),
                          child: Text(
                            summary.accountNumber,
                            style: AppTypography.bodySmall.copyWith(
                              fontSize: 10,
                              color: context.tc.textTertiary,
                            ),
                          ),
                        ),
                      ],
                    ),
                    AppSpacing.vGapXs,
                    AnimatedNumber(
                      value: summary.totalAsset,
                      style: AppTypography.numberLarge.copyWith(fontSize: 36),
                      formatter: (v) => NumberFormat.currency(
                              symbol: '\$', decimalDigits: 0)
                          .format(v),
                    ),
                  ],
                ),
              ),
              // 오늘 P&L
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                decoration: BoxDecoration(
                  color: context.tc.pnlBg(summary.todayPnl),
                  borderRadius: AppSpacing.borderRadiusMd,
                  border: Border.all(
                    color: pnlColor.withValues(alpha: 0.25),
                    width: 1,
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          isProfit
                              ? Icons.trending_up_rounded
                              : Icons.trending_down_rounded,
                          color: pnlColor,
                          size: 16,
                        ),
                        AppSpacing.hGapXs,
                        Text(t('today_pnl'), style: AppTypography.bodySmall),
                      ],
                    ),
                    AppSpacing.vGapXs,
                    Text(
                      '${isProfit ? '+' : ''}${NumberFormat.currency(symbol: '\$', decimalDigits: 0).format(summary.todayPnl)}',
                      style:
                          AppTypography.numberMedium.copyWith(color: pnlColor),
                    ),
                    Text(
                      '${isProfit ? '+' : ''}${summary.todayPnlPct.toStringAsFixed(2)}%',
                      style:
                          AppTypography.numberSmall.copyWith(color: pnlColor),
                    ),
                  ],
                ),
              ),
            ],
          ),
          AppSpacing.vGapLg,
          // 계좌 잔액 상세 4-grid 카드
          _buildAccountBreakdownGrid(summary),
          AppSpacing.vGapLg,
          // 월간 목표 프로그레스 바
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(t('monthly_target'), style: AppTypography.bodySmall),
                  Text(
                    '${monthlyPct.toStringAsFixed(1)}%',
                    style: AppTypography.numberSmall.copyWith(
                      color: monthlyPct >= 100
                          ? context.tc.profit
                          : context.tc.primary,
                    ),
                  ),
                ],
              ),
              AppSpacing.vGapXs,
              TweenAnimationBuilder<double>(
                tween: Tween(
                    begin: 0, end: (monthlyPct / 100).clamp(0.0, 1.0)),
                duration: const Duration(milliseconds: 800),
                curve: Curves.easeOutCubic,
                builder: (context, value, _) {
                  return ClipRRect(
                    borderRadius: AppSpacing.borderRadiusFull,
                    child: LinearProgressIndicator(
                      value: value,
                      backgroundColor: context.tc.surfaceBorder,
                      valueColor: AlwaysStoppedAnimation<Color>(
                        monthlyPct >= 100
                            ? context.tc.profit
                            : context.tc.primary,
                      ),
                      minHeight: 6,
                    ),
                  );
                },
              ),
            ],
          ),
          AppSpacing.vGapLg,
          // 하단 미니 통계 3개
          Row(
            children: [
              Expanded(
                child: _buildMiniStat(
                  t('cumulative'),
                  '${summary.cumulativeReturn >= 0 ? '+' : ''}${summary.cumulativeReturn.toStringAsFixed(2)}%',
                  context.tc.pnlColor(summary.cumulativeReturn),
                  Icons.auto_graph_rounded,
                ),
              ),
              _buildVerticalDivider(),
              Expanded(
                child: _buildMiniStat(
                  t('positions'),
                  '${summary.activePositions}',
                  null,
                  Icons.pie_chart_rounded,
                ),
              ),
              _buildVerticalDivider(),
              Expanded(
                child: _buildMiniStat(
                  t('currency'),
                  summary.currency,
                  context.tc.primary,
                  Icons.currency_exchange_rounded,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  /// 총 자산 / 보유 평가액 / 현금 잔액 / 매수 가능액을 2x2 그리드로 표시한다.
  Widget _buildAccountBreakdownGrid(DashboardSummary summary) {
    final t = context.watch<LocaleProvider>().t;
    final fmt = NumberFormat.currency(symbol: '\$', decimalDigits: 0);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: context.tc.surfaceElevated,
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: context.tc.surfaceBorder.withValues(alpha: 0.4),
          width: 1,
        ),
      ),
      child: Column(
        children: [
          // 상단 행: 총 자산 | 보유 평가액
          Row(
            children: [
              Expanded(
                child: _buildAccountCell(
                  label: t('total_asset'),
                  value: fmt.format(summary.totalAsset),
                  icon: Icons.account_balance_rounded,
                  iconColor: context.tc.primary,
                  isHighlighted: true,
                ),
              ),
              Container(
                width: 1,
                height: 48,
                color: context.tc.surfaceBorder.withValues(alpha: 0.4),
              ),
              Expanded(
                child: _buildAccountCell(
                  label: t('positions_value'),
                  value: fmt.format(summary.positionsValue),
                  icon: Icons.pie_chart_outline_rounded,
                  iconColor: context.tc.pnlColor(summary.positionsValue),
                ),
              ),
            ],
          ),
          Divider(
            height: 16,
            color: context.tc.surfaceBorder.withValues(alpha: 0.4),
          ),
          // 하단 행: 현금 잔액 | 매수 가능액
          Row(
            children: [
              Expanded(
                child: _buildAccountCell(
                  label: t('cash_balance'),
                  value: fmt.format(summary.cash),
                  icon: Icons.account_balance_wallet_rounded,
                  iconColor: context.tc.textSecondary,
                ),
              ),
              Container(
                width: 1,
                height: 48,
                color: context.tc.surfaceBorder.withValues(alpha: 0.4),
              ),
              Expanded(
                child: _buildAccountCell(
                  label: t('buying_power'),
                  value: fmt.format(summary.buyingPower),
                  icon: Icons.bolt_rounded,
                  iconColor: context.tc.warning,
                  isHighlighted: false,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  /// 계좌 정보 그리드 셀 하나를 빌드한다.
  Widget _buildAccountCell({
    required String label,
    required String value,
    required IconData icon,
    required Color iconColor,
    bool isHighlighted = false,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: iconColor.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusSm,
            ),
            child: Icon(icon, size: 14, color: iconColor),
          ),
          AppSpacing.hGapSm,
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
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
                  style: AppTypography.numberSmall.copyWith(
                    color: isHighlighted
                        ? context.tc.primary
                        : context.tc.textPrimary,
                    fontWeight:
                        isHighlighted ? FontWeight.w700 : FontWeight.w500,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildVerticalDivider() {
    return Container(
      width: 1,
      height: 40,
      color: context.tc.surfaceBorder.withValues(alpha: 0.5),
    );
  }

  Widget _buildMiniStat(
      String label, String value, Color? valueColor, IconData icon) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(
        children: [
          Icon(icon, size: 16, color: context.tc.textTertiary),
          AppSpacing.hGapSm,
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: AppTypography.bodySmall),
                Text(
                  value,
                  style: AppTypography.numberSmall.copyWith(
                    color: valueColor ?? context.tc.textPrimary,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ── 2열 레이아웃 ──

  Widget _buildTwoColumnLayout(
      DashboardSummary summary, SystemStatus? systemStatus) {
    final isServerDisconnected =
        context.watch<DashboardProvider>().isServerDisconnected;

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 왼쪽 2/3
          Expanded(
            flex: 2,
            child: Column(
              children: [
                StaggeredFadeSlide(
                  index: 2,
                  child: _buildActivePositionsCard(),
                ),
                AppSpacing.vGapLg,
                StaggeredFadeSlide(
                  index: 4,
                  child: _buildRecentTradesCard(),
                ),
              ],
            ),
          ),
          AppSpacing.hGapLg,
          // 오른쪽 1/3
          Expanded(
            flex: 1,
            child: Column(
              children: [
                // systemStatus가 있으면 정상 카드, 서버 미연결이면 미연결 카드를 표시한다
                if (systemStatus != null) ...[
                  StaggeredFadeSlide(
                    index: 3,
                    child: _buildSystemStatusCard(systemStatus),
                  ),
                  AppSpacing.vGapLg,
                ] else if (isServerDisconnected) ...[
                  StaggeredFadeSlide(
                    index: 3,
                    child: _buildSystemStatusDisconnectedCard(),
                  ),
                  AppSpacing.vGapLg,
                ],
                StaggeredFadeSlide(
                  index: 5,
                  child: _buildPendingActionsCard(),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSingleColumnLayout(
      DashboardSummary summary, SystemStatus? systemStatus) {
    final isServerDisconnected =
        context.watch<DashboardProvider>().isServerDisconnected;

    return Column(
      children: [
        StaggeredFadeSlide(
          index: 2,
          child: _buildActivePositionsCard(),
        ),
        AppSpacing.vGapLg,
        if (systemStatus != null) ...[
          StaggeredFadeSlide(
            index: 3,
            child: _buildSystemStatusCard(systemStatus),
          ),
          AppSpacing.vGapLg,
        ] else if (isServerDisconnected) ...[
          StaggeredFadeSlide(
            index: 3,
            child: _buildSystemStatusDisconnectedCard(),
          ),
          AppSpacing.vGapLg,
        ],
        StaggeredFadeSlide(
          index: 4,
          child: _buildRecentTradesCard(),
        ),
        AppSpacing.vGapLg,
        StaggeredFadeSlide(
          index: 5,
          child: _buildPendingActionsCard(),
        ),
      ],
    );
  }

  /// 서버 미연결 시 시스템 상태 카드 대신 표시하는 플레이스홀더 카드이다.
  Widget _buildSystemStatusDisconnectedCard() {
    final t = context.watch<LocaleProvider>().t;
    final services = ['Claude AI', 'KIS API', 'Database', 'Redis'];

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('system_status')),
          ...services.map(
            (name) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(name, style: AppTypography.bodyMedium),
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(
                          color: context.tc.warning,
                          shape: BoxShape.circle,
                        ),
                      ),
                      AppSpacing.hGapSm,
                      Text(
                        t('server_disconnected'),
                        style: AppTypography.labelMedium.copyWith(
                          color: context.tc.warning,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ── 포지션 카드 ──

  Widget _buildActivePositionsCard() {
    final t = context.watch<LocaleProvider>().t;
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('active_positions')),
          Consumer<DashboardProvider>(
            builder: (context, provider, _) {
              final positionCount = provider.summary?.activePositions ?? 0;
              if (positionCount == 0) {
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Center(
                    child: Text(t('no_active_positions'),
                        style: AppTypography.bodyMedium),
                  ),
                );
              }
              return Column(
                children: [
                  _buildPositionRow('Portfolio', positionCount, null, 0),
                ],
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _buildPositionRow(
      String ticker, dynamic value, double? pnlPct, double posValue) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: context.tc.primary.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusMd,
            ),
            child: Center(
              child: Text(
                ticker.length > 4 ? ticker.substring(0, 4) : ticker,
                style: AppTypography.labelLarge.copyWith(
                  color: context.tc.primary,
                  fontSize: 11,
                ),
              ),
            ),
          ),
          AppSpacing.hGapMd,
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(ticker, style: AppTypography.labelLarge),
                if (pnlPct != null)
                  Text(
                    '${pnlPct >= 0 ? '+' : ''}${pnlPct.toStringAsFixed(2)}%',
                    style: AppTypography.bodySmall.copyWith(
                      color: context.tc.pnlColor(pnlPct),
                    ),
                  ),
              ],
            ),
          ),
          Text(
            '$value active',
            style: AppTypography.numberSmall,
          ),
        ],
      ),
    );
  }

  // ── 시스템 상태 카드 ──

  Widget _buildSystemStatusCard(SystemStatus status) {
    final t = context.watch<LocaleProvider>().t;
    // 서버 미연결 여부를 Provider에서 가져온다
    final isServerDisconnected =
        context.watch<DashboardProvider>().isServerDisconnected;

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('system_status')),
          _buildStatusRow('Claude AI', status.claude,
              serverDisconnected: isServerDisconnected),
          AppSpacing.vGapMd,
          _buildStatusRow('KIS API', status.kis,
              serverDisconnected: isServerDisconnected),
          AppSpacing.vGapMd,
          _buildStatusRow('Database', status.database,
              serverDisconnected: isServerDisconnected),
          AppSpacing.vGapMd,
          _buildStatusRow('Redis', status.redis,
              serverDisconnected: isServerDisconnected),
          AppSpacing.vGapLg,
          // 쿼터 정보 (서버 미연결 시 희미하게 표시한다)
          Opacity(
            opacity: isServerDisconnected ? 0.45 : 1.0,
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: context.tc.surfaceElevated,
                borderRadius: AppSpacing.borderRadiusMd,
              ),
              child: Column(
                children: [
                  _buildQuotaBar(
                    t('claude_calls'),
                    status.quota.claudeCallsToday,
                    status.quota.claudeLimit,
                  ),
                  AppSpacing.vGapSm,
                  _buildQuotaBar(
                    t('kis_calls'),
                    status.quota.kisCallsToday,
                    status.quota.kisLimit,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// 시스템 서비스 상태 행을 빌드한다.
  ///
  /// [isOnline] 서버가 해당 서비스를 정상으로 보고했는지 여부이다.
  /// [serverDisconnected] API 서버 자체에 연결할 수 없는 상태이면 true이다.
  /// - serverDisconnected == true: 주황색 "서버 미연결" 표시 (isOnline 무관)
  /// - serverDisconnected == false && isOnline == true: 초록색 "온라인"
  /// - serverDisconnected == false && isOnline == false: 빨간색 "오프라인"
  Widget _buildStatusRow(String label, bool isOnline,
      {bool serverDisconnected = false}) {
    final t = context.watch<LocaleProvider>().t;

    final Color dotColor;
    final Color textColor;
    final String statusText;
    final Widget dot;

    if (serverDisconnected) {
      dotColor = context.tc.warning;
      textColor = context.tc.warning;
      statusText = t('server_disconnected');
      dot = Container(
        width: 8,
        height: 8,
        decoration: BoxDecoration(
          color: dotColor,
          shape: BoxShape.circle,
        ),
      );
    } else if (isOnline) {
      dotColor = context.tc.profit;
      textColor = context.tc.profit;
      statusText = t('online');
      dot = PulsingDot(color: dotColor, size: 8);
    } else {
      dotColor = context.tc.loss;
      textColor = context.tc.loss;
      statusText = t('offline');
      dot = Container(
        width: 8,
        height: 8,
        decoration: BoxDecoration(
          color: dotColor,
          shape: BoxShape.circle,
        ),
      );
    }

    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: AppTypography.bodyMedium),
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            dot,
            AppSpacing.hGapSm,
            Text(
              statusText,
              style: AppTypography.labelMedium.copyWith(color: textColor),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildQuotaBar(String label, int used, int limit) {
    final ratio = limit > 0 ? (used / limit).clamp(0.0, 1.0) : 0.0;
    final barColor = ratio > 0.8
        ? context.tc.loss
        : ratio > 0.6
            ? context.tc.warning
            : context.tc.primary;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: AppTypography.bodySmall),
            Text(
              '$used / $limit',
              style: AppTypography.numberSmall.copyWith(fontSize: 11),
            ),
          ],
        ),
        AppSpacing.vGapXs,
        ClipRRect(
          borderRadius: AppSpacing.borderRadiusFull,
          child: LinearProgressIndicator(
            value: ratio,
            backgroundColor: context.tc.surfaceBorder,
            valueColor: AlwaysStoppedAnimation<Color>(barColor),
            minHeight: 4,
          ),
        ),
      ],
    );
  }

  // ── 최근 거래 카드 ──

  Widget _buildRecentTradesCard() {
    final t = context.watch<LocaleProvider>().t;
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: t('recent_trades')),
          Consumer<DashboardProvider>(
            builder: (context, provider, _) {
              if (provider.summary == null) {
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Center(
                    child: Text(t('no_trades_yet'),
                        style: AppTypography.bodyMedium),
                  ),
                );
              }
              // 실제 데이터 없이 요약 정보 표시
              final summary = provider.summary;
              return Column(
                children: [
                  _buildTradeRow(
                    'System',
                    'Active',
                    summary?.systemStatus ?? '-',
                    null,
                    DateTime.now(),
                  ),
                ],
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _buildTradeRow(
    String ticker,
    String action,
    String status,
    double? pnl,
    DateTime time,
  ) {
    final timeStr = DateFormat('HH:mm').format(time);
    final isBuy = action.toLowerCase() == 'buy';
    final actionColor = isBuy ? context.tc.profit : context.tc.loss;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: actionColor.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusSm,
            ),
            child: Text(
              action.toUpperCase(),
              style: AppTypography.bodySmall.copyWith(
                color: actionColor,
                fontSize: 10,
              ),
            ),
          ),
          AppSpacing.hGapMd,
          Expanded(
            child: Text(ticker, style: AppTypography.labelLarge),
          ),
          if (pnl != null)
            Text(
              '${pnl >= 0 ? '+' : ''}${NumberFormat.currency(symbol: '\$', decimalDigits: 0).format(pnl)}',
              style: AppTypography.numberSmall.copyWith(
                color: context.tc.pnlColor(pnl),
              ),
            ),
          AppSpacing.hGapMd,
          Text(timeStr, style: AppTypography.bodySmall),
        ],
      ),
    );
  }

  // ── 보류 중인 AI 조정 카드 ──

  Widget _buildPendingActionsCard() {
    final t = context.watch<LocaleProvider>().t;
    return Consumer<TradeProvider>(
      builder: (context, provider, _) {
        final pending = provider.pendingAdjustments;

        return GlassCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SectionHeader(
                title: t('pending_ai_actions'),
                action: pending.isNotEmpty
                    ? SectionLabel(
                        text: '${pending.length}',
                        color: context.tc.warning,
                      )
                    : null,
              ),
              if (pending.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Text(
                    t('no_pending_adjustments'),
                    style: AppTypography.bodyMedium,
                  ),
                )
              else
                ...pending
                    .take(3)
                    .map((adj) => _buildAdjustmentRow(adj, provider)),
              if (pending.length > 3) ...[
                AppSpacing.vGapSm,
                Text(
                  t('more_count')
                      .replaceAll('{n}', '${pending.length - 3}'),
                  style: AppTypography.bodySmall,
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _buildAdjustmentRow(
      PendingAdjustment adj, TradeProvider provider) {
    final t = context.watch<LocaleProvider>().t;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(adj.paramName, style: AppTypography.labelLarge),
          AppSpacing.vGapXs,
          Row(
            children: [
              Text(
                '${adj.currentValue}',
                style: AppTypography.numberSmall.copyWith(
                  color: context.tc.textTertiary,
                  decoration: TextDecoration.lineThrough,
                ),
              ),
              Icon(Icons.arrow_forward_rounded,
                  size: 12, color: context.tc.textTertiary),
              Text(
                '${adj.proposedValue}',
                style: AppTypography.numberSmall.copyWith(
                  color: context.tc.primary,
                ),
              ),
              const Spacer(),
              // 승인 버튼
              InkWell(
                onTap: () => _handleApprove(adj, provider),
                borderRadius: AppSpacing.borderRadiusSm,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: context.tc.profitBg,
                    borderRadius: AppSpacing.borderRadiusSm,
                    border: Border.all(
                        color: context.tc.profit.withValues(alpha: 0.3)),
                  ),
                  child: Text(
                    t('approve'),
                    style: AppTypography.bodySmall
                        .copyWith(color: context.tc.profit),
                  ),
                ),
              ),
              AppSpacing.hGapSm,
              // 거부 버튼
              InkWell(
                onTap: () => provider.rejectAdjustment(adj.id),
                borderRadius: AppSpacing.borderRadiusSm,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: context.tc.lossBg,
                    borderRadius: AppSpacing.borderRadiusSm,
                    border: Border.all(
                        color: context.tc.loss.withValues(alpha: 0.3)),
                  ),
                  child: Text(
                    t('reject'),
                    style: AppTypography.bodySmall
                        .copyWith(color: context.tc.loss),
                  ),
                ),
              ),
            ],
          ),
          AppSpacing.vGapSm,
          Text(adj.reason,
              style: AppTypography.bodySmall,
              maxLines: 2,
              overflow: TextOverflow.ellipsis),
          Divider(
            height: 16,
            color: context.tc.surfaceBorder.withValues(alpha: 0.3),
          ),
        ],
      ),
    );
  }

  Future<void> _handleApprove(
      PendingAdjustment adj, TradeProvider provider) async {
    final t = context.read<LocaleProvider>().t;
    final confirmed = await ConfirmationDialog.show(
      context,
      title: t('approve_adjustment'),
      message:
          '${adj.paramName}: ${adj.currentValue} -> ${adj.proposedValue}\n\n${adj.reason}',
      confirmLabel: t('approve'),
      confirmColor: context.tc.profit,
      icon: Icons.check_circle_rounded,
    );
    if (confirmed && mounted) {
      await provider.approveAdjustment(adj.id);
    }
  }

  Widget _buildLoadingSkeleton() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        children: [
          ShimmerLoading(
              width: double.infinity,
              height: 200,
              borderRadius: AppSpacing.borderRadiusLg),
          AppSpacing.vGapLg,
          Row(
            children: [
              Expanded(
                flex: 2,
                child: ShimmerLoading(
                    width: double.infinity,
                    height: 300,
                    borderRadius: AppSpacing.borderRadiusLg),
              ),
              AppSpacing.hGapLg,
              Expanded(
                child: Column(
                  children: [
                    ShimmerLoading(
                        width: double.infinity,
                        height: 200,
                        borderRadius: AppSpacing.borderRadiusLg),
                    AppSpacing.vGapLg,
                    ShimmerLoading(
                        width: double.infinity,
                        height: 120,
                        borderRadius: AppSpacing.borderRadiusLg),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
