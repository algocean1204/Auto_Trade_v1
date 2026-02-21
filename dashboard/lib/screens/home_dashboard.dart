import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import 'package:fl_chart/fl_chart.dart';
import '../providers/dashboard_provider.dart';
import '../providers/chart_provider.dart';
import '../providers/locale_provider.dart';
import '../providers/trading_control_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../animations/animation_utils.dart';
import 'chart_dashboard.dart';
import 'indicator_settings.dart';
import 'ai_report.dart';
import 'alert_history.dart';
import 'strategy_settings.dart';
import 'manual_crawl_screen.dart';
import 'universe_manager_screen.dart';
import 'profit_target_screen.dart';
import 'risk_dashboard_screen.dart';

class HomeDashboard extends StatefulWidget {
  const HomeDashboard({super.key});

  @override
  State<HomeDashboard> createState() => _HomeDashboardState();
}

class _HomeDashboardState extends State<HomeDashboard> {
  int _currentIndex = 0;

  final List<Widget> _screens = const [
    _HomeScreen(),
    ChartDashboard(),
    ProfitTargetScreen(),
    RiskDashboardScreen(),
    AlertHistory(),
  ];

  @override
  Widget build(BuildContext context) {
    // locale 변경 시 하단 네비게이션 레이블도 재빌드된다.
    final t = context.watch<LocaleProvider>().t;

    return Scaffold(
      body: AnimatedSwitcher(
        duration: AnimDuration.normal,
        switchInCurve: AnimCurve.easeOut,
        switchOutCurve: AnimCurve.easeIn,
        child: _screens[_currentIndex],
      ),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          color: context.tc.surface,
          border: Border(
            top: BorderSide(
              color: context.tc.surfaceBorder.withValues(alpha: 0.3),
              width: 1,
            ),
          ),
        ),
        child: BottomNavigationBar(
          currentIndex: _currentIndex,
          onTap: (index) {
            setState(() {
              _currentIndex = index;
            });
          },
          items: [
            BottomNavigationBarItem(
              icon: const Icon(Icons.dashboard_rounded),
              label: t('nav_home'),
            ),
            BottomNavigationBarItem(
              icon: const Icon(Icons.candlestick_chart_rounded),
              label: t('nav_charts'),
            ),
            BottomNavigationBarItem(
              icon: const Icon(Icons.track_changes_rounded),
              label: t('nav_target'),
            ),
            BottomNavigationBarItem(
              icon: const Icon(Icons.shield_rounded),
              label: t('nav_risk'),
            ),
            BottomNavigationBarItem(
              icon: const Icon(Icons.notifications_rounded),
              label: t('nav_alerts'),
            ),
          ],
        ),
      ),
    );
  }
}

class _HomeScreen extends StatefulWidget {
  const _HomeScreen();

  @override
  State<_HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<_HomeScreen> {
  /// 현재 선택된 차트 기간 필터이다.
  String _selectedPeriod = '1M';

  /// 30초 주기 자동 새로고침 타이머이다.
  Timer? _refreshTimer;

  /// dispose()에서 context.read 사용을 피하기 위해 캐싱한다.
  late final TradingControlProvider _tradingCtrl;

  @override
  void initState() {
    super.initState();
    _tradingCtrl = context.read<TradingControlProvider>();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<DashboardProvider>().loadDashboardData();
      context.read<ChartProvider>().loadCumulativeReturns();
      _tradingCtrl.startPolling();
    });
    _refreshTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (!mounted) return;
      context.read<DashboardProvider>().refresh();
      context.read<ChartProvider>().loadCumulativeReturns();
    });
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    _tradingCtrl.stopPolling();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          t('home_title'),
          style: AppTypography.displaySmall,
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.tune_rounded, size: 22),
            tooltip: t('settings'),
            onPressed: () {
              _showMoreMenu(context);
            },
          ),
          IconButton(
            icon: const Icon(Icons.refresh_rounded, size: 22),
            tooltip: t('refresh'),
            onPressed: () {
              context.read<DashboardProvider>().refresh();
              context.read<ChartProvider>().refresh();
            },
          ),
        ],
      ),
      body: Consumer<DashboardProvider>(
        builder: (context, provider, child) {
          if (provider.isLoading && provider.summary == null) {
            return _buildLoadingSkeleton();
          }

          if (provider.error != null && provider.summary == null) {
            return _buildErrorState(provider, t);
          }

          final summary = provider.summary;
          final systemStatus = provider.systemStatus;

          if (summary == null || systemStatus == null) {
            return Center(
              child: Text(
                t('no_data'),
                style: AppTypography.bodyLarge,
              ),
            );
          }

          final chartProvider = context.read<ChartProvider>();
          return RefreshIndicator(
            onRefresh: () async {
              // 전체 새로고침: 대시보드 데이터 + 차트 데이터를 병렬로 로드한다.
              await Future.wait([
                provider.refresh(),
                chartProvider.refresh(),
              ]);
            },
            color: context.tc.primary,
            backgroundColor: context.tc.surfaceElevated,
            child: ListView(
              padding: AppSpacing.paddingScreen,
              children: [
                StaggeredFadeSlide(
                  index: 0,
                  child: _buildTradingControlCard(context, t),
                ),
                AppSpacing.vGapLg,
                StaggeredFadeSlide(
                  index: 1,
                  child: _buildPortfolioCard(context, summary, t),
                ),
                AppSpacing.vGapLg,
                StaggeredFadeSlide(
                  index: 2,
                  child: _buildPortfolioChart(context, summary, t),
                ),
                AppSpacing.vGapLg,
                StaggeredFadeSlide(
                  index: 3,
                  child: _buildTodayPnlCard(context, summary, t),
                ),
                AppSpacing.vGapLg,
                StaggeredFadeSlide(
                  index: 4,
                  child: _buildSystemStatusCard(context, systemStatus, t),
                ),
                AppSpacing.vGapLg,
                StaggeredFadeSlide(
                  index: 5,
                  child: _buildQuickActions(context, t),
                ),
                AppSpacing.vGapXxl,
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildLoadingSkeleton() {
    return Padding(
      padding: AppSpacing.paddingScreen,
      child: Column(
        children: [
          ShimmerLoading(
            width: double.infinity,
            height: 180,
            borderRadius: AppSpacing.borderRadiusLg,
          ),
          AppSpacing.vGapLg,
          ShimmerLoading(
            width: double.infinity,
            height: 220,
            borderRadius: AppSpacing.borderRadiusLg,
          ),
          AppSpacing.vGapLg,
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

  Widget _buildErrorState(DashboardProvider provider, String Function(String) t) {
    return Center(
      child: Padding(
        padding: AppSpacing.paddingScreen,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.cloud_off_rounded, size: 64, color: context.tc.textTertiary),
            AppSpacing.vGapLg,
            Text(
              t('connection_error'),
              style: AppTypography.displaySmall,
            ),
            AppSpacing.vGapSm,
            Text(
              provider.error ?? t('no_data'),
              style: AppTypography.bodyMedium,
              textAlign: TextAlign.center,
            ),
            AppSpacing.vGapXxl,
            ElevatedButton.icon(
              onPressed: () => provider.refresh(),
              icon: const Icon(Icons.refresh_rounded, size: 18),
              label: Text(t('retry')),
            ),
          ],
        ),
      ),
    );
  }

  /// 자동매매 제어 + 뉴스 수집 카드를 빌드한다.
  ///
  /// 공통: "뉴스 수집 & 전송" 버튼 (항상 활성).
  /// 평일: 자동매매 시작/중지 버튼 (23:00~07:00 KST 활성).
  /// 주말/공휴일: 자동매매 버튼 숨김 + "휴장일입니다" 안내.
  Widget _buildTradingControlCard(BuildContext context, String Function(String) t) {
    return Consumer<TradingControlProvider>(
      builder: (context, ctrl, _) {
        final isRunning = ctrl.isRunning;
        final isConnected = ctrl.isConnected;
        final isBusy = ctrl.isBusy;
        final isBusyNews = ctrl.isBusyNews;
        final isTradingWindow = ctrl.isTradingWindow;
        final isTradingDay = ctrl.isTradingDay;

        // 연결 끊김 시 회색/경고색, 연결 시 기존 로직 유지
        final Color statusColor;
        final Color statusBg;
        final IconData statusIcon;
        final String statusLabel;
        final String hintLabel;

        if (!isConnected) {
          statusColor = context.tc.warning;
          statusBg = context.tc.warning.withValues(alpha: 0.1);
          statusIcon = Icons.cloud_off_rounded;
          statusLabel = t('auto_trading_disconnected');
          hintLabel = t('auto_trading_disconnected_hint');
        } else if (isRunning) {
          statusColor = context.tc.profit;
          statusBg = context.tc.profitBg;
          statusIcon = Icons.play_circle_filled_rounded;
          statusLabel = t('auto_trading_running');
          hintLabel = t('system_running_normally');
        } else {
          statusColor = context.tc.loss;
          statusBg = context.tc.lossBg;
          statusIcon = Icons.stop_circle_rounded;
          statusLabel = t('auto_trading_stopped');
          hintLabel = t('server_disconnected_hint');
        }

        return GlassCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 상단 헤더 행: 섹션 제목 + 상태 배지
              Row(
                children: [
                  Text(
                    t('auto_trading'),
                    style: AppTypography.headlineMedium,
                  ),
                  const Spacer(),
                  // 상태 배지
                  AnimatedContainer(
                    duration: AnimDuration.normal,
                    padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.md, vertical: AppSpacing.xs),
                    decoration: BoxDecoration(
                      color: statusBg,
                      borderRadius: AppSpacing.borderRadiusFull,
                      border: Border.all(
                        color: statusColor.withValues(alpha: 0.4),
                        width: 1,
                      ),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        // 실행 중일 때 점멸 애니메이션, 연결 끊김 시 고정 점, 중지 시 고정 점
                        if (isConnected && isRunning)
                          PulsingDot(color: statusColor, size: 8)
                        else
                          Container(
                            width: 8,
                            height: 8,
                            decoration: BoxDecoration(
                              color: statusColor,
                              shape: BoxShape.circle,
                            ),
                          ),
                        AppSpacing.hGapXs,
                        Text(
                          statusLabel,
                          style: AppTypography.labelMedium.copyWith(
                            color: statusColor,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              AppSpacing.vGapLg,
              // 대형 상태 아이콘 + 설명 행
              Row(
                children: [
                  AnimatedContainer(
                    duration: AnimDuration.normal,
                    width: 56,
                    height: 56,
                    decoration: BoxDecoration(
                      color: statusBg,
                      borderRadius: AppSpacing.borderRadiusMd,
                    ),
                    child: Icon(
                      statusIcon,
                      color: statusColor,
                      size: 32,
                    ),
                  ),
                  AppSpacing.hGapLg,
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          hintLabel,
                          style: AppTypography.bodyMedium.copyWith(
                            color: context.tc.textSecondary,
                          ),
                        ),
                        if (ctrl.error != null) ...[
                          AppSpacing.vGapXs,
                          Text(
                            _sanitizeError(ctrl.error!),
                            style: AppTypography.bodySmall.copyWith(
                              color: context.tc.loss,
                            ),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ],
                    ),
                  ),
                ],
              ),
              AppSpacing.vGapMd,
              // 매매 시간 윈도우 상태 칩 - 서버에 연결된 경우에만 표시한다.
              if (isConnected)
                _buildTradingWindowChip(context, ctrl, t),
              AppSpacing.vGapMd,

              // ── 뉴스 수집 & 전송 버튼 (항상 표시, 항상 활성) ──
              _buildNewsCollectButton(context, ctrl, isBusyNews, t),
              AppSpacing.vGapSm,

              // ── 자동매매 시작/중지 버튼 (조건부 표시) ──
              if (!isTradingDay) ...[
                // 주말/공휴일: 휴장일 안내
                _buildHolidayNotice(context, t),
              ] else ...[
                // 평일: 자동매매 버튼
                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: AnimatedSwitcher(
                    duration: AnimDuration.normal,
                    layoutBuilder: (Widget? currentChild, List<Widget> previousChildren) {
                      return currentChild ?? const SizedBox.shrink();
                    },
                    child: isBusy
                        ? _buildLoadingButton(context, isRunning, t)
                        : isRunning
                            ? _buildStopButton(context, ctrl, t)
                            : _buildStartButton(context, ctrl, isTradingWindow, isTradingDay, t),
                  ),
                ),
                // 시간대 밖일 때 힌트 표시
                if (!isRunning && !isTradingWindow) ...[
                  AppSpacing.vGapXs,
                  Center(
                    child: Text(
                      t('trading_window_hint'),
                      style: AppTypography.bodySmall.copyWith(
                        color: context.tc.textTertiary,
                        fontSize: 11,
                      ),
                    ),
                  ),
                ],
              ],
            ],
          ),
        );
      },
    );
  }

  /// 뉴스 수집 & 전송 버튼을 빌드한다.
  ///
  /// 항상 활성화되며, 수집 중일 때는 CircularProgressIndicator를 표시한다.
  Widget _buildNewsCollectButton(
    BuildContext context,
    TradingControlProvider ctrl,
    bool isBusyNews,
    String Function(String) t,
  ) {
    return SizedBox(
      width: double.infinity,
      height: 48,
      child: ElevatedButton.icon(
        style: ElevatedButton.styleFrom(
          backgroundColor: context.tc.primary,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
          ),
          elevation: 0,
        ),
        icon: isBusyNews
            ? SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(
                  strokeWidth: 2.0,
                  color: Colors.white,
                ),
              )
            : const Icon(Icons.newspaper_rounded, size: 20),
        label: Text(
          isBusyNews ? t('news_collecting') : t('news_collect_send'),
          style: AppTypography.labelLarge.copyWith(
            color: Colors.white,
            fontWeight: FontWeight.w600,
          ),
        ),
        onPressed: isBusyNews
            ? null
            : () async {
                await ctrl.collectAndSendNews();
                if (context.mounted) {
                  if (ctrl.error != null) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text(t('news_sent_failed')),
                        backgroundColor: context.tc.loss,
                      ),
                    );
                  } else {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text(t('news_sent_success')),
                        backgroundColor: context.tc.profit,
                        duration: const Duration(seconds: 2),
                      ),
                    );
                  }
                }
              },
      ),
    );
  }

  /// 휴장일 안내 위젯을 빌드한다.
  Widget _buildHolidayNotice(BuildContext context, String Function(String) t) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: context.tc.textTertiary.withValues(alpha: 0.08),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: context.tc.textTertiary.withValues(alpha: 0.2),
          width: 1,
        ),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.event_busy_rounded,
            size: 18,
            color: context.tc.textTertiary,
          ),
          const SizedBox(width: 8),
          Text(
            t('trading_holiday'),
            style: AppTypography.bodyMedium.copyWith(
              color: context.tc.textTertiary,
            ),
          ),
        ],
      ),
    );
  }

  /// 매매 시간 윈도우 상태 정보 칩을 빌드한다.
  ///
  /// 매매 가능 시간, 매매일 여부, 다음 윈도우 시작 시각을 표시한다.
  Widget _buildTradingWindowChip(
    BuildContext context,
    TradingControlProvider ctrl,
    String Function(String) t,
  ) {
    final isTradingWindow = ctrl.isTradingWindow;
    final isTradingDay = ctrl.isTradingDay;
    final nextWindowStart = ctrl.nextWindowStart;
    final sessionType = ctrl.sessionType;

    final Color chipColor;
    final Color chipBg;
    final IconData chipIcon;
    final String chipText;

    if (!isTradingDay) {
      // 오늘이 매매일이 아닌 경우이다.
      chipColor = context.tc.textTertiary;
      chipBg = context.tc.textTertiary.withValues(alpha: 0.08);
      chipIcon = Icons.calendar_today_rounded;
      chipText = t('trading_not_trading_day');
    } else if (isTradingWindow) {
      // 현재 매매 가능 시간대이다.
      chipColor = context.tc.profit;
      chipBg = context.tc.profitBg;
      chipIcon = Icons.access_time_rounded;
      final sessionLabel = sessionType != null && sessionType.isNotEmpty
          ? ' ($sessionType)'
          : '';
      chipText = '${t('trading_window_available')}$sessionLabel';
    } else {
      // 매매 가능 시간대가 아닌 경우이다.
      chipColor = context.tc.textTertiary;
      chipBg = context.tc.textTertiary.withValues(alpha: 0.08);
      chipIcon = Icons.schedule_rounded;
      chipText = t('trading_outside_hours');
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 상태 칩
        Container(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.sm,
            vertical: AppSpacing.xs,
          ),
          decoration: BoxDecoration(
            color: chipBg,
            borderRadius: AppSpacing.borderRadiusSm,
            border: Border.all(
              color: chipColor.withValues(alpha: 0.3),
              width: 1,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(chipIcon, size: 13, color: chipColor),
              const SizedBox(width: 5),
              Text(
                chipText,
                style: AppTypography.bodySmall.copyWith(
                  color: chipColor,
                  fontSize: 11,
                ),
              ),
            ],
          ),
        ),
        // 다음 윈도우 시작 시각이 있고 현재 윈도우가 아닐 때 표시한다.
        if (!isTradingWindow && nextWindowStart != null) ...[
          const SizedBox(height: 4),
          Text(
            _formatNextWindowStart(nextWindowStart, t),
            style: AppTypography.bodySmall.copyWith(
              color: context.tc.textTertiary,
              fontSize: 11,
            ),
          ),
        ],
      ],
    );
  }

  /// 다음 매매 시작 시각을 "다음 매매 시작: MM/DD HH:mm KST" 형식으로 포맷한다.
  String _formatNextWindowStart(DateTime dt, String Function(String) t) {
    // DateTime은 서버에서 ISO 문자열로 수신되며 UTC 또는 로컬 오프셋이 포함될 수 있다.
    // UI에서는 날짜+시간만 표시한다.
    final mm = dt.month.toString().padLeft(2, '0');
    final dd = dt.day.toString().padLeft(2, '0');
    final hh = dt.hour.toString().padLeft(2, '0');
    final min = dt.minute.toString().padLeft(2, '0');
    return '${t('trading_next_window_start')}: $mm/$dd $hh:$min KST';
  }

  Widget _buildStartButton(
    BuildContext context,
    TradingControlProvider ctrl,
    bool isTradingWindow,
    bool isTradingDay,
    String Function(String) t,
  ) {
    // 매매 시간대가 아니거나 매매일이 아닌 경우 버튼을 비활성화한다.
    final bool canStart = isTradingWindow && isTradingDay;

    final Color buttonBg = canStart ? context.tc.profit : context.tc.textDisabled.withValues(alpha: 0.15);
    final Color buttonFg = canStart ? Colors.white : context.tc.textDisabled;

    return ElevatedButton.icon(
      key: const ValueKey('start'),
      style: ElevatedButton.styleFrom(
        backgroundColor: buttonBg,
        foregroundColor: buttonFg,
        disabledBackgroundColor: context.tc.textDisabled.withValues(alpha: 0.12),
        disabledForegroundColor: context.tc.textDisabled,
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusMd,
          side: canStart
              ? BorderSide.none
              : BorderSide(
                  color: context.tc.textDisabled.withValues(alpha: 0.25),
                  width: 1,
                ),
        ),
        elevation: 0,
      ),
      icon: Icon(
        Icons.play_arrow_rounded,
        size: 22,
        color: buttonFg,
      ),
      label: Text(
        t('auto_trading_start'),
        style: AppTypography.labelLarge.copyWith(
          color: buttonFg,
          fontWeight: FontWeight.w600,
        ),
      ),
      // 매매 가능 시간대가 아닌 경우 onPressed를 null로 설정하여 버튼을 비활성화한다.
      onPressed: canStart
          ? () async {
              await ctrl.startTrading();
              if (context.mounted) {
                if (ctrl.error != null) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(t('auto_trading_start_failed')),
                      backgroundColor: context.tc.loss,
                    ),
                  );
                } else {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(t('auto_trading_running')),
                      backgroundColor: context.tc.profit,
                      duration: const Duration(seconds: 2),
                    ),
                  );
                }
              }
            }
          : null,
    );
  }

  Widget _buildStopButton(
    BuildContext context,
    TradingControlProvider ctrl,
    String Function(String) t,
  ) {
    return ElevatedButton.icon(
      key: const ValueKey('stop'),
      style: ElevatedButton.styleFrom(
        backgroundColor: context.tc.loss,
        foregroundColor: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusMd,
        ),
        elevation: 0,
      ),
      icon: const Icon(Icons.stop_rounded, size: 22),
      label: Text(
        t('auto_trading_stop'),
        style: AppTypography.labelLarge.copyWith(
          color: Colors.white,
          fontWeight: FontWeight.w600,
        ),
      ),
      onPressed: () => _showStopConfirmDialog(context, ctrl, t),
    );
  }

  Widget _buildLoadingButton(
    BuildContext context,
    bool wasRunning,
    String Function(String) t,
  ) {
    final color = wasRunning ? context.tc.loss : context.tc.profit;
    return Container(
      key: const ValueKey('loading'),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Center(
        child: SizedBox(
          width: 22,
          height: 22,
          child: CircularProgressIndicator(
            strokeWidth: 2.5,
            color: color,
          ),
        ),
      ),
    );
  }

  /// 자동매매 중지 확인 다이얼로그를 표시한다.
  Future<void> _showStopConfirmDialog(
    BuildContext context,
    TradingControlProvider ctrl,
    String Function(String) t,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: context.tc.surfaceElevated,
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusLg,
        ),
        title: Row(
          children: [
            Icon(Icons.warning_amber_rounded,
                color: context.tc.warning, size: 22),
            AppSpacing.hGapSm,
            Flexible(
              child: Text(
                t('auto_trading_stop_confirm_title'),
                style: AppTypography.headlineMedium,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
        content: Text(
          t('auto_trading_stop_confirm_msg'),
          style: AppTypography.bodyMedium,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: Text(
              t('cancel'),
              style: AppTypography.labelLarge.copyWith(
                color: context.tc.textSecondary,
              ),
            ),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: context.tc.loss,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(
                borderRadius: AppSpacing.borderRadiusMd,
              ),
              elevation: 0,
            ),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: Text(
              t('auto_trading_stop'),
              style: AppTypography.labelLarge.copyWith(
                color: Colors.white,
              ),
            ),
          ),
        ],
      ),
    );

    if (confirmed == true && context.mounted) {
      await ctrl.stopTrading();
      if (context.mounted) {
        if (ctrl.error != null) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(t('auto_trading_stop_failed')),
              backgroundColor: context.tc.loss,
            ),
          );
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(t('auto_trading_stopped')),
              backgroundColor: context.tc.profit,
              duration: const Duration(seconds: 2),
            ),
          );
        }
      }
    }
  }

  /// 에러 메시지에서 예외 클래스명 접두사를 제거하여 사용자 친화적으로 표시한다.
  String _sanitizeError(String raw) {
    // "Exception: ...", "ServerUnreachableException: ..." 등의 접두사를 제거한다.
    final colonIdx = raw.indexOf(': ');
    if (colonIdx > 0 && colonIdx < 40) {
      return raw.substring(colonIdx + 2);
    }
    return raw;
  }

  Widget _buildPortfolioCard(BuildContext context, dynamic summary, String Function(String) t) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            t('total_assets'),
            style: AppTypography.bodyMedium,
          ),
          AppSpacing.vGapSm,
          AnimatedNumber(
            value: summary.totalAsset,
            style: AppTypography.numberLarge,
            formatter: (v) => NumberFormat.currency(symbol: '\$', decimalDigits: 0).format(v),
          ),
          AppSpacing.vGapXl,
          Row(
            children: [
              Expanded(
                child: _buildMiniStat(
                  t('cash'),
                  NumberFormat.currency(symbol: '\$', decimalDigits: 0)
                      .format(summary.cash),
                  null,
                ),
              ),
              Container(
                width: 1,
                height: 40,
                color: context.tc.surfaceBorder,
              ),
              Expanded(
                child: _buildMiniStat(
                  t('cumulative'),
                  '${summary.cumulativeReturn >= 0 ? '+' : ''}${summary.cumulativeReturn.toStringAsFixed(2)}%',
                  context.tc.pnlColor(summary.cumulativeReturn),
                ),
              ),
              Container(
                width: 1,
                height: 40,
                color: context.tc.surfaceBorder,
              ),
              Expanded(
                child: _buildMiniStat(
                  t('positions'),
                  '${summary.activePositions}',
                  null,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildMiniStat(String label, String value, Color? valueColor) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Column(
        children: [
          Text(
            label,
            style: AppTypography.bodySmall,
            textAlign: TextAlign.center,
          ),
          AppSpacing.vGapXs,
          Text(
            value,
            style: AppTypography.numberSmall.copyWith(
              color: valueColor ?? context.tc.textPrimary,
            ),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }

  /// Upbit 스타일의 포트폴리오 미니 차트를 빌드한다.
  /// 누적 수익률을 기간별로 필터링하여 라인 차트로 표시한다.
  Widget _buildPortfolioChart(BuildContext context, dynamic summary, String Function(String) t) {
    return Consumer<ChartProvider>(
      builder: (context, chartProvider, child) {
        final allData = chartProvider.cumulativeReturns;
        final filteredData = _filterByPeriod(allData, _selectedPeriod);
        final isPositive = filteredData.isEmpty
            ? true
            : (filteredData.last.cumulativePct >= 0);
        final lineColor = isPositive ? context.tc.profit : context.tc.loss;

        return GlassCard(
          padding: const EdgeInsets.fromLTRB(16, 16, 8, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 상단: Upbit 스타일 자산 분석 행
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: _buildUpbitAccountRow(summary, t),
              ),
              AppSpacing.vGapLg,
              // 기간 선택 버튼 행
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: _buildPeriodSelector(t),
              ),
              AppSpacing.vGapMd,
              // 차트 영역
              SizedBox(
                height: 180,
                child: filteredData.isEmpty
                    ? Center(
                        child: Text(
                          t('no_data'),
                          style: AppTypography.bodySmall,
                        ),
                      )
                    : _buildLineChart(filteredData, lineColor),
              ),
            ],
          ),
        );
      },
    );
  }

  /// Upbit 스타일의 계좌 잔액 요약 행을 빌드한다.
  Widget _buildUpbitAccountRow(dynamic summary, String Function(String) t) {
    final totalAsset = (summary.totalAsset as num).toDouble();
    final cash = (summary.cash as num).toDouble();
    final todayPnl = (summary.todayPnl as num).toDouble();
    // 총 매입금액 = 총 자산 - 현금 - 오늘 손익 (근사값)
    final totalInvested = totalAsset - cash - todayPnl;
    final unrealizedPnl = todayPnl;
    final pnlColor = context.tc.pnlColor(unrealizedPnl);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 총 평가금액 (대형)
        Text(t('total_evaluated'), style: AppTypography.bodySmall),
        AppSpacing.vGapXs,
        AnimatedNumber(
          value: totalAsset,
          style: AppTypography.numberMedium,
          formatter: (v) => NumberFormat.currency(symbol: '\$', decimalDigits: 0).format(v),
        ),
        AppSpacing.vGapMd,
        // 하단 3개 항목 행
        Row(
          children: [
            Expanded(
              child: _buildUpbitStatCell(
                label: t('available_cash'),
                value: NumberFormat.currency(symbol: '\$', decimalDigits: 0).format(cash),
                valueColor: context.tc.textPrimary,
              ),
            ),
            Container(
              width: 1,
              height: 32,
              color: context.tc.surfaceBorder,
            ),
            Expanded(
              child: _buildUpbitStatCell(
                label: t('total_invested'),
                value: NumberFormat.currency(symbol: '\$', decimalDigits: 0).format(totalInvested),
                valueColor: context.tc.textPrimary,
              ),
            ),
            Container(
              width: 1,
              height: 32,
              color: context.tc.surfaceBorder,
            ),
            Expanded(
              child: _buildUpbitStatCell(
                label: t('unrealized_pnl'),
                value:
                    '${unrealizedPnl >= 0 ? '+' : ''}${NumberFormat.currency(symbol: '\$', decimalDigits: 0).format(unrealizedPnl)}',
                valueColor: pnlColor,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildUpbitStatCell({
    required String label,
    required String value,
    required Color valueColor,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: AppTypography.bodySmall, overflow: TextOverflow.ellipsis),
          AppSpacing.vGapXs,
          Text(
            value,
            style: AppTypography.numberSmall.copyWith(color: valueColor),
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }

  /// 기간 선택 버튼 행을 빌드한다 (1W, 1M, 3M, 6M, 1Y).
  Widget _buildPeriodSelector(String Function(String) t) {
    final periods = [
      ('1W', t('period_1w')),
      ('1M', t('period_1m')),
      ('3M', t('period_3m')),
      ('6M', t('period_6m')),
      ('1Y', t('period_1y')),
    ];

    return Row(
      mainAxisAlignment: MainAxisAlignment.start,
      children: periods.map((entry) {
        final key = entry.$1;
        final label = entry.$2;
        final isSelected = _selectedPeriod == key;

        return Padding(
          padding: const EdgeInsets.only(right: 6),
          child: GestureDetector(
            onTap: () {
              setState(() {
                _selectedPeriod = key;
              });
            },
            child: AnimatedContainer(
              duration: AnimDuration.fast,
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                color: isSelected
                    ? context.tc.primary.withValues(alpha: 0.15)
                    : Colors.transparent,
                borderRadius: AppSpacing.borderRadiusSm,
                border: Border.all(
                  color: isSelected
                      ? context.tc.primary.withValues(alpha: 0.5)
                      : context.tc.surfaceBorder.withValues(alpha: 0.4),
                  width: 1,
                ),
              ),
              child: Text(
                label,
                style: AppTypography.labelMedium.copyWith(
                  color: isSelected ? context.tc.primary : context.tc.textTertiary,
                  fontSize: 11,
                ),
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  /// 선택된 기간에 따라 누적 수익률 데이터를 필터링한다.
  List<dynamic> _filterByPeriod(List<dynamic> data, String period) {
    if (data.isEmpty) return data;
    final now = DateTime.now();
    final DateTime cutoff;
    switch (period) {
      case '1W':
        cutoff = now.subtract(const Duration(days: 7));
        break;
      case '3M':
        cutoff = DateTime(now.year, now.month - 3, now.day);
        break;
      case '6M':
        cutoff = DateTime(now.year, now.month - 6, now.day);
        break;
      case '1Y':
        cutoff = DateTime(now.year - 1, now.month, now.day);
        break;
      case '1M':
      default:
        cutoff = DateTime(now.year, now.month - 1, now.day);
        break;
    }
    return data.where((d) => d.date.isAfter(cutoff)).toList();
  }

  /// fl_chart 기반의 누적 수익률 라인 차트를 빌드한다.
  /// 양수이면 초록색, 음수이면 빨간색 영역 채우기를 적용한다.
  Widget _buildLineChart(List<dynamic> data, Color lineColor) {
    final spots = <FlSpot>[];
    for (int i = 0; i < data.length; i++) {
      spots.add(FlSpot(i.toDouble(), data[i].cumulativePct));
    }

    final minY = spots.map((s) => s.y).reduce((a, b) => a < b ? a : b);
    final maxY = spots.map((s) => s.y).reduce((a, b) => a > b ? a : b);
    final yPadding = ((maxY - minY) * 0.15).abs().clamp(0.5, double.infinity);

    // 날짜 레이블 간격 계산
    final labelInterval = (data.length / 4).ceil().toDouble();

    return LineChart(
      LineChartData(
        minX: 0,
        maxX: (data.length - 1).toDouble(),
        minY: minY - yPadding,
        maxY: maxY + yPadding,
        gridData: FlGridData(
          show: true,
          drawVerticalLine: false,
          horizontalInterval: yPadding * 2,
          getDrawingHorizontalLine: (value) => FlLine(
            color: context.tc.chartGrid,
            strokeWidth: 1,
          ),
        ),
        titlesData: FlTitlesData(
          leftTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 44,
              getTitlesWidget: (value, meta) {
                if (value == meta.min || value == meta.max) {
                  return const SizedBox.shrink();
                }
                return Text(
                  '${value.toStringAsFixed(1)}%',
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.chartAxis,
                    fontSize: 9,
                  ),
                );
              },
            ),
          ),
          topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 24,
              interval: labelInterval,
              getTitlesWidget: (value, meta) {
                final idx = value.toInt();
                if (idx < 0 || idx >= data.length) return const SizedBox.shrink();
                return Text(
                  DateFormat('MM/dd').format(data[idx].date),
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.chartAxis,
                    fontSize: 9,
                  ),
                );
              },
            ),
          ),
        ),
        borderData: FlBorderData(show: false),
        lineBarsData: [
          LineChartBarData(
            spots: spots,
            isCurved: true,
            curveSmoothness: 0.35,
            color: lineColor,
            barWidth: 2.0,
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(
              show: true,
              gradient: LinearGradient(
                colors: [
                  lineColor.withValues(alpha: 0.25),
                  lineColor.withValues(alpha: 0.0),
                ],
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
              ),
            ),
          ),
        ],
        lineTouchData: LineTouchData(
          touchTooltipData: LineTouchTooltipData(
            getTooltipColor: (_) => context.tc.surfaceElevated,
            tooltipRoundedRadius: 10,
            tooltipBorder: BorderSide(color: context.tc.surfaceBorder, width: 1),
            getTooltipItems: (spots) {
              return spots.map((spot) {
                final idx = spot.x.toInt();
                if (idx < 0 || idx >= data.length) return null;
                final point = data[idx];
                return LineTooltipItem(
                  '${DateFormat('MM/dd').format(point.date)}\n'
                  '${point.cumulativePct >= 0 ? '+' : ''}${point.cumulativePct.toStringAsFixed(2)}%',
                  AppTypography.numberSmall.copyWith(
                    color: context.tc.textPrimary,
                    fontSize: 11,
                  ),
                );
              }).toList();
            },
          ),
        ),
      ),
    );
  }

  Widget _buildTodayPnlCard(BuildContext context, dynamic summary, String Function(String) t) {
    final isProfit = summary.todayPnl >= 0;
    final pnlColor = context.tc.pnlColor(summary.todayPnl);

    return GlassCard(
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: context.tc.pnlBg(summary.todayPnl),
              borderRadius: AppSpacing.borderRadiusMd,
            ),
            child: Icon(
              isProfit ? Icons.trending_up_rounded : Icons.trending_down_rounded,
              color: pnlColor,
              size: 24,
            ),
          ),
          AppSpacing.hGapLg,
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  t('today_pnl'),
                  style: AppTypography.bodyMedium,
                ),
                AppSpacing.vGapXs,
                Text(
                  '${isProfit ? '+' : ''}${NumberFormat.currency(symbol: '\$', decimalDigits: 0).format(summary.todayPnl)}',
                  style: AppTypography.numberMedium.copyWith(color: pnlColor),
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: context.tc.pnlBg(summary.todayPnlPct),
              borderRadius: AppSpacing.borderRadiusSm,
              border: Border.all(
                color: pnlColor.withValues(alpha: 0.3),
                width: 1,
              ),
            ),
            child: Text(
              '${isProfit ? '+' : ''}${summary.todayPnlPct.toStringAsFixed(2)}%',
              style: AppTypography.numberSmall.copyWith(color: pnlColor),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSystemStatusCard(BuildContext context, dynamic systemStatus, String Function(String) t) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            t('system_status'),
            style: AppTypography.headlineMedium,
          ),
          AppSpacing.vGapLg,
          _buildStatusRow('Claude AI', systemStatus.claude, t),
          AppSpacing.vGapMd,
          _buildStatusRow('KIS API', systemStatus.kis, t),
          AppSpacing.vGapMd,
          _buildStatusRow(t('database'), systemStatus.database, t),
          AppSpacing.vGapMd,
          _buildStatusRow(t('fallback'), systemStatus.fallback, t),
        ],
      ),
    );
  }

  Widget _buildStatusRow(String label, bool status, String Function(String) t) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: AppTypography.bodyMedium),
        Row(
          children: [
            if (status)
              PulsingDot(color: context.tc.profit, size: 10)
            else
              Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                  color: context.tc.loss,
                  shape: BoxShape.circle,
                ),
              ),
            AppSpacing.hGapSm,
            Text(
              status ? t('online') : t('offline'),
              style: AppTypography.labelMedium.copyWith(
                color: status ? context.tc.profit : context.tc.loss,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildQuickActions(BuildContext context, String Function(String) t) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          t('quick_actions'),
          style: AppTypography.headlineMedium,
        ),
        AppSpacing.vGapMd,
        Row(
          children: [
            Expanded(
              child: _buildActionButton(
                context,
                Icons.tune_rounded,
                t('indicators'),
                () => Navigator.push(context,
                    MaterialPageRoute(builder: (_) => const IndicatorSettings())),
              ),
            ),
            AppSpacing.hGapMd,
            Expanded(
              child: _buildActionButton(
                context,
                Icons.assessment_rounded,
                t('ai_report'),
                () => Navigator.push(context,
                    MaterialPageRoute(builder: (_) => const AiReport())),
              ),
            ),
          ],
        ),
        AppSpacing.vGapMd,
        Row(
          children: [
            Expanded(
              child: _buildActionButton(
                context,
                Icons.settings_rounded,
                t('strategy'),
                () => Navigator.push(context,
                    MaterialPageRoute(builder: (_) => const StrategySettings())),
              ),
            ),
            AppSpacing.hGapMd,
            Expanded(
              child: _buildActionButton(
                context,
                Icons.language_rounded,
                t('crawling'),
                () => Navigator.push(context,
                    MaterialPageRoute(builder: (_) => const ManualCrawlScreen())),
              ),
            ),
          ],
        ),
        AppSpacing.vGapMd,
        _buildActionButton(
          context,
          Icons.list_alt_rounded,
          t('universe_manager'),
          () => Navigator.push(context,
              MaterialPageRoute(builder: (_) => const UniverseManagerScreen())),
        ),
      ],
    );
  }

  Widget _buildActionButton(
    BuildContext context,
    IconData icon,
    String label,
    VoidCallback onTap,
  ) {
    return Material(
      color: context.tc.surface,
      borderRadius: AppSpacing.borderRadiusLg,
      child: InkWell(
        onTap: onTap,
        borderRadius: AppSpacing.borderRadiusLg,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          decoration: BoxDecoration(
            borderRadius: AppSpacing.borderRadiusLg,
            border: Border.all(
              color: context.tc.surfaceBorder.withValues(alpha: 0.3),
              width: 1,
            ),
          ),
          child: Row(
            children: [
              Icon(icon, size: 20, color: context.tc.primary),
              AppSpacing.hGapMd,
              Text(label, style: AppTypography.labelLarge),
              const Spacer(),
              Icon(
                Icons.chevron_right_rounded,
                size: 20,
                color: context.tc.textTertiary,
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _showMoreMenu(BuildContext context) {
    final t = context.read<LocaleProvider>().t;
    showModalBottomSheet(
      context: context,
      backgroundColor: context.tc.surfaceElevated,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: context.tc.surfaceBorder,
                    borderRadius: AppSpacing.borderRadiusFull,
                  ),
                ),
                AppSpacing.vGapLg,
                ListTile(
                  leading: const Icon(Icons.tune_rounded),
                  title: Text(t('indicators')),
                  onTap: () {
                    Navigator.pop(context);
                    Navigator.push(context,
                        MaterialPageRoute(builder: (_) => const IndicatorSettings()));
                  },
                ),
                ListTile(
                  leading: const Icon(Icons.settings_rounded),
                  title: Text(t('strategy')),
                  onTap: () {
                    Navigator.pop(context);
                    Navigator.push(context,
                        MaterialPageRoute(builder: (_) => const StrategySettings()));
                  },
                ),
                ListTile(
                  leading: const Icon(Icons.language_rounded),
                  title: Text(t('crawling')),
                  onTap: () {
                    Navigator.pop(context);
                    Navigator.push(context,
                        MaterialPageRoute(builder: (_) => const ManualCrawlScreen()));
                  },
                ),
                ListTile(
                  leading: const Icon(Icons.list_alt_rounded),
                  title: Text(t('universe_manager')),
                  onTap: () {
                    Navigator.pop(context);
                    Navigator.push(context,
                        MaterialPageRoute(builder: (_) => const UniverseManagerScreen()));
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
