import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/dashboard_provider.dart';
import '../providers/navigation_provider.dart';
import '../providers/settings_provider.dart';
import '../providers/emergency_provider.dart';
import '../providers/trading_control_provider.dart';
import '../providers/locale_provider.dart';
import '../providers/token_provider.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../theme/trading_colors.dart';
import '../widgets/sidebar_nav.dart';
import '../widgets/status_bar.dart';
import '../widgets/alert_panel.dart';
import '../widgets/emergency_button.dart';
import '../widgets/confirmation_dialog.dart';
import '../widgets/setup/update_banner.dart';
import 'overview_screen.dart';
import 'trading_screen.dart';
import 'risk_center_screen.dart';
import 'analytics_screen.dart';
import 'settings_screen.dart';
import 'agent_team_screen.dart';
import 'rsi_screen.dart';
import 'reports_screen.dart';
import 'news_screen.dart';
import 'universe_screen.dart';
import 'principles_screen.dart';
import 'trade_reasoning_screen.dart';
import 'stock_analysis_screen.dart';
import 'scalper_tape_screen.dart';
import 'manual_trade_screen.dart';

/// 메인 쉘 스크린: 사이드바 + 컨텐츠 영역 + 상태 바를 구성한다.
class ShellScreen extends StatefulWidget {
  const ShellScreen({super.key});

  @override
  State<ShellScreen> createState() => _ShellScreenState();
}

class _ShellScreenState extends State<ShellScreen> {
  // dispose 시 context.read가 안전하지 않으므로 참조를 캐시한다
  DashboardProvider? _dashboardProvider;
  TradingControlProvider? _tradingControlProvider;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _dashboardProvider = context.read<DashboardProvider>();
      _tradingControlProvider = context.read<TradingControlProvider>();
      context.read<SettingsProvider>().refreshUnreadCount();
      // AppBar 버튼에서 매매 상태를 표시하기 위해 폴링을 시작한다.
      _tradingControlProvider?.startPolling();
      // 대시보드 데이터를 1초마다 자동 새로고침한다.
      _dashboardProvider?.startAutoRefresh();
    });
  }

  @override
  void dispose() {
    // ShellScreen이 파괴될 때 initState에서 시작한 타이머를 정리한다.
    // SetupWizard로 돌아가는 경우 등 재빌드 시 타이머 누수를 방지한다.
    // 캐시된 참조를 사용하여 dispose 후 context.read 호출을 방지한다.
    _dashboardProvider?.stopAutoRefresh();
    _tradingControlProvider?.stopPolling();
    super.dispose();
  }

  Widget _buildScreenForSection(NavSection section) {
    switch (section) {
      case NavSection.overview:
        return const OverviewScreen();
      case NavSection.trading:
        return const TradingScreen();
      case NavSection.scalperTape:
        return const ScalperTapeScreen();
      case NavSection.risk:
        return const RiskCenterScreen();
      case NavSection.analytics:
        return const AnalyticsScreen();
      case NavSection.rsi:
        return const RsiScreen();
      case NavSection.stockAnalysis:
        return const StockAnalysisScreen();
      case NavSection.reports:
        return const ReportsScreen();
      case NavSection.tradeReasoning:
        return const TradeReasoningScreen();
      case NavSection.news:
        return const NewsScreen();
      case NavSection.universe:
        return const UniverseScreen();
      case NavSection.agents:
        return const AgentTeamScreen();
      case NavSection.principles:
        return const PrinciplesScreen();
      case NavSection.manualTrade:
        return const ManualTradeScreen();
      case NavSection.settings:
        return const SettingsScreen();
    }
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Consumer<EmergencyProvider>(
      builder: (context, emergencyProvider, _) {
        final isEmergency = emergencyProvider.isEmergencyStopped;

        return Stack(
          children: [
            // 메인 레이아웃
            Container(
              decoration: isEmergency
                  ? BoxDecoration(
                      border: Border.all(
                        color: tc.loss.withValues(alpha: 0.5),
                        width: 2,
                      ),
                    )
                  : null,
              child: Scaffold(
                backgroundColor: tc.background,
                appBar: _buildAppBar(context),
                body: Column(
                  children: [
                    // 업데이트 알림 배너
                    const UpdateBanner(),
                    // 긴급 정지 배너
                    if (isEmergency) const _EmergencyBanner(),
                    // 메인 컨텐츠
                    Expanded(
                      child: Row(
                        children: [
                          // 사이드바
                          const SidebarNav(),
                          // 컨텐츠 + 알림 패널
                          Expanded(
                            child: Consumer<NavigationProvider>(
                              builder: (context, navProvider, _) {
                                return Row(
                                  children: [
                                    Expanded(
                                      child: AnimatedSwitcher(
                                        duration: const Duration(milliseconds: 250),
                                        switchInCurve: Curves.easeOutCubic,
                                        child: KeyedSubtree(
                                          key: ValueKey(navProvider.currentSection),
                                          child: _buildScreenForSection(
                                              navProvider.currentSection),
                                        ),
                                      ),
                                    ),
                                    // 알림 패널 (슬라이드 아웃)
                                    if (navProvider.alertPanelOpen)
                                      const AlertPanel(),
                                  ],
                                );
                              },
                            ),
                          ),
                        ],
                      ),
                    ),
                    // 하단 상태 바
                    const StatusBar(),
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  PreferredSizeWidget _buildAppBar(BuildContext context) {
    final tc = context.tc;
    return AppBar(
      backgroundColor: tc.surface,
      elevation: 0,
      toolbarHeight: 52,
      titleSpacing: 12,
      title: Consumer<LocaleProvider>(
        builder: (context, locale, _) {
          return Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.auto_graph_rounded, size: 20, color: tc.primary),
              AppSpacing.hGapSm,
              Flexible(
                child: Text(
                  locale.t('app_title'),
                  style: AppTypography.displaySmall,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          );
        },
      ),
      actions: [
        // 창 축소 시 overflow 방지를 위해 SingleChildScrollView로 감싼다.
        Flexible(
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                // 언어 토글 버튼
                Consumer<LocaleProvider>(
                  builder: (context, locale, _) {
                    return IconButton(
                      icon: Text(
                        locale.isKorean ? 'EN' : 'KR',
                        style: AppTypography.labelMedium.copyWith(
                          color: tc.textSecondary,
                          fontSize: 12,
                        ),
                      ),
                      tooltip:
                          locale.isKorean ? 'Switch to English' : '한국어로 전환',
                      onPressed: () => locale.toggleLocale(),
                    );
                  },
                ),
                // 알림 벨 아이콘
                Consumer2<SettingsProvider, NavigationProvider>(
                  builder: (context, settingsProvider, navProvider, _) {
                    return Stack(
                      children: [
                        IconButton(
                          icon: Icon(
                            navProvider.alertPanelOpen
                                ? Icons.notifications_rounded
                                : Icons.notifications_none_rounded,
                            size: 22,
                            color: navProvider.alertPanelOpen
                                ? tc.primary
                                : tc.textSecondary,
                          ),
                          tooltip: context.read<LocaleProvider>().t('alerts'),
                          onPressed: () {
                            navProvider.toggleAlertPanel();
                          },
                        ),
                        if (settingsProvider.unreadCount > 0)
                          Positioned(
                            right: 8,
                            top: 8,
                            child: Container(
                              padding: const EdgeInsets.all(3),
                              decoration: BoxDecoration(
                                color: tc.loss,
                                shape: BoxShape.circle,
                              ),
                              child: Text(
                                settingsProvider.unreadCount > 9
                                    ? '9+'
                                    : '${settingsProvider.unreadCount}',
                                style: const TextStyle(
                                  fontSize: 9,
                                  color: Colors.white,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ),
                          ),
                      ],
                    );
                  },
                ),
                const SizedBox(width: 4),
                // ═══ 체인 버튼 시작 ═══
                // 1) 토큰 발급 버튼 (항상 활성)
                const _TokenButton(),
                const SizedBox(width: 4),
                // 2) 서버 시작 버튼 (토큰 1시간 이내 시 활성)
                const _ServerStartButton(),
                const SizedBox(width: 2),
                // 2b) 서버 중지 버튼 (서버 connected 시에만 표시)
                const _ServerStopButton(),
                const SizedBox(width: 4),
                // 3) 자동매매 시작/중지 버튼 (서버 connected 시 활성)
                const _TradingControlButton(),
                const SizedBox(width: 4),
                // 4) 뉴스 수집 버튼 (서버 connected 시 활성)
                const _NewsCollectButton(),
                // ═══ 체인 버튼 끝 ═══
                const SizedBox(width: 4),
                // 긴급 정지 버튼 (항상 표시)
                const EmergencyButton(),
                const SizedBox(width: 8),
              ],
            ),
          ),
        ),
      ],
      bottom: PreferredSize(
        preferredSize: const Size.fromHeight(1),
        child: Container(
          height: 1,
          color: tc.surfaceBorder.withValues(alpha: 0.2),
        ),
      ),
    );
  }
}

/// KIS 토큰 발급 AppBar 버튼이다.
///
/// 항상 활성이며, 클릭 시 TokenProvider.issueToken()을 호출한다.
/// 토큰 상태에 따라 색상이 변한다:
/// - 유효+갱신 불필요: profit 색상 (초록)
/// - 유효+갱신 필요 (16시간 경과 또는 만료 임박): warning 색상 (주황)
/// - 무효: textSecondary 색상 (회색)
class _TokenButton extends StatelessWidget {
  const _TokenButton();

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Consumer<TokenProvider>(
      builder: (context, token, _) {
        final isValid = token.isTokenValid;
        final isIssuing = token.isIssuing;

        // 토큰 상태에 따라 버튼 색상을 결정한다.
        final Color buttonColor;
        if (isValid && !token.needsMandatoryRenewal && !token.isExpiringSoon) {
          buttonColor = tc.profit; // 초록: 유효 + 갱신 불필요
        } else if (isValid) {
          buttonColor = tc.warning; // 주황: 유효하지만 갱신 필요 (16시간 경과 또는 만료 임박)
        } else {
          buttonColor = tc.textSecondary; // 회색: 토큰 없음 또는 만료
        }

        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
          child: Tooltip(
            message: token.statusText,
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: buttonColor.withValues(alpha: 0.12),
                foregroundColor: buttonColor,
                side: BorderSide(
                  color: buttonColor.withValues(alpha: 0.3),
                  width: 1,
                ),
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                ),
                textStyle: AppTypography.labelLarge.copyWith(fontSize: 12),
              ),
              onPressed: isIssuing ? null : () => token.issueToken(),
              icon: isIssuing
                  ? SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: buttonColor,
                      ),
                    )
                  : const Icon(Icons.key_rounded, size: 16),
              label: Text(isIssuing ? '...' : 'TOKEN'),
            ),
          ),
        );
      },
    );
  }
}

/// 서버 시작 AppBar 버튼이다.
///
/// 활성 조건: 토큰이 유효함 (isTokenValid).
/// 서버 실행 중이면 SERVER(초록) 상태 표시, 미실행이면 SERVER(회색) + 클릭으로 시작.
class _ServerStartButton extends StatelessWidget {
  const _ServerStartButton();

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Consumer2<TokenProvider, TradingControlProvider>(
      builder: (context, token, ctrl, _) {
        final canActivate = token.isTokenValid;
        final isConnected = ctrl.isConnected;
        final isStarting = ctrl.isStartingServer;

        // 서버 연결 상태를 TokenProvider에 전달한다 (자동 갱신 트리거용).
        WidgetsBinding.instance.addPostFrameCallback((_) {
          token.setServerConnected(isConnected);
        });

        // 서버 실행 중이면 초록 상태 표시 (클릭 불가)
        if (isConnected) {
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
            child: Tooltip(
              message: '서버 실행 중',
              child: ElevatedButton.icon(
                style: ElevatedButton.styleFrom(
                  backgroundColor: tc.profit.withValues(alpha: 0.15),
                  foregroundColor: tc.profit,
                  side: BorderSide(
                      color: tc.profit.withValues(alpha: 0.4), width: 1),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  elevation: 0,
                  shape: RoundedRectangleBorder(
                    borderRadius: AppSpacing.borderRadiusMd,
                  ),
                  textStyle: AppTypography.labelLarge.copyWith(fontSize: 12),
                ),
                onPressed: null,
                icon: const Icon(Icons.dns_rounded, size: 16),
                label: const Text('SERVER'),
              ),
            ),
          );
        }

        // 서버 미실행 — 토큰 조건 충족 시에만 시작 활성화
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
          child: Tooltip(
            message:
                !canActivate ? '유효한 토큰이 필요합니다' : '서버 시작',
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: canActivate
                    ? tc.primary.withValues(alpha: 0.15)
                    : tc.surface,
                foregroundColor: canActivate
                    ? tc.primary
                    : tc.textSecondary.withValues(alpha: 0.5),
                side: BorderSide(
                  color: canActivate
                      ? tc.primary.withValues(alpha: 0.4)
                      : tc.surfaceBorder.withValues(alpha: 0.3),
                  width: 1,
                ),
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                ),
                textStyle: AppTypography.labelLarge.copyWith(fontSize: 12),
              ),
              onPressed: (canActivate && !isStarting)
                  ? () => _handleStart(context, ctrl)
                  : null,
              icon: isStarting
                  ? SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: tc.primary,
                      ),
                    )
                  : const Icon(Icons.dns_outlined, size: 16),
              label: Text(isStarting ? '...' : 'SERVER'),
            ),
          ),
        );
      },
    );
  }

  Future<void> _handleStart(
      BuildContext context, TradingControlProvider ctrl) async {
    final success = await ctrl.startServer();
    if (context.mounted && !success && ctrl.error != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('서버 시작 실패: ${ctrl.error}'),
          backgroundColor: context.tc.loss,
        ),
      );
    }
  }
}

/// 서버 수동 중지 AppBar 버튼이다.
///
/// 서버가 connected 상태일 때만 표시된다.
/// 클릭 시 확인 다이얼로그 후 서버를 종료한다.
class _ServerStopButton extends StatelessWidget {
  const _ServerStopButton();

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Consumer<TradingControlProvider>(
      builder: (context, ctrl, _) {
        // 서버 미연결 시 빈 위젯 (숨김)
        if (!ctrl.isConnected) return const SizedBox.shrink();

        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 6),
          child: Tooltip(
            message: '서버 수동 종료',
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: tc.warning.withValues(alpha: 0.12),
                foregroundColor: tc.warning,
                side: BorderSide(
                    color: tc.warning.withValues(alpha: 0.3), width: 1),
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                ),
                textStyle: AppTypography.labelLarge.copyWith(fontSize: 11),
              ),
              onPressed:
                  ctrl.canStopServer ? () => _handleStop(context, ctrl) : null,
              icon: const Icon(Icons.power_settings_new_rounded, size: 15),
              label: const Text('OFF'),
            ),
          ),
        );
      },
    );
  }

  Future<void> _handleStop(
      BuildContext context, TradingControlProvider ctrl) async {
    final t = context.read<LocaleProvider>().t;
    final confirmed = await ConfirmationDialog.show(
      context,
      title: '서버 중지',
      message: '서버를 중지하시겠습니까?\n자동매매가 실행 중이면 함께 종료됩니다.',
      confirmLabel: '중지',
      cancelLabel: t('cancel'),
      confirmColor: context.tc.warning,
      icon: Icons.power_settings_new_rounded,
    );
    if (confirmed && context.mounted) {
      final success = await ctrl.stopServer();
      if (context.mounted && !success && ctrl.error != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(ctrl.error!),
            backgroundColor: context.tc.loss,
          ),
        );
      }
    }
  }
}

/// 자동매매 시작/중지 AppBar 버튼이다.
///
/// 매매 시간대(23:00~06:30 KST) + 평일에만 시작 가능하다.
/// 실행 중이면 RUNNING 표시, 미실행이면 START 표시.
class _TradingControlButton extends StatelessWidget {
  const _TradingControlButton();

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Consumer<TradingControlProvider>(
      builder: (context, ctrl, _) {
        final isRunning = ctrl.isRunning;
        final isConnected = ctrl.isConnected;
        final isBusy = ctrl.isBusy;
        final canStart = ctrl.isTradingWindow && ctrl.isTradingDay;

        // 실행 중
        if (isRunning) {
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: tc.profit.withValues(alpha: 0.15),
                foregroundColor: tc.profit,
                side: BorderSide(
                    color: tc.profit.withValues(alpha: 0.4), width: 1),
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                ),
                textStyle: AppTypography.labelLarge.copyWith(fontSize: 12),
              ),
              onPressed: isBusy ? null : () => _handleStop(context, ctrl),
              icon: isBusy
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.stop_rounded, size: 16),
              label: Text(isBusy ? '...' : 'STOP'),
            ),
          );
        }

        // 미실행: 시작 가능 여부에 따라 활성/비활성
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
          child: Tooltip(
            message: !isConnected
                ? 'Server disconnected'
                : !ctrl.isTradingDay
                    ? '휴장일'
                    : !ctrl.isTradingWindow
                        ? '매매 시간대 아님 (20:00~06:30 KST)'
                        : '자동매매 시작',
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: canStart && isConnected
                    ? tc.primary.withValues(alpha: 0.15)
                    : tc.surface,
                foregroundColor: canStart && isConnected
                    ? tc.primary
                    : tc.textSecondary.withValues(alpha: 0.5),
                side: BorderSide(
                  color: canStart && isConnected
                      ? tc.primary.withValues(alpha: 0.4)
                      : tc.surfaceBorder.withValues(alpha: 0.3),
                  width: 1,
                ),
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                ),
                textStyle: AppTypography.labelLarge.copyWith(fontSize: 12),
              ),
              onPressed: (canStart && isConnected && !isBusy)
                  ? () => _handleStart(context, ctrl)
                  : null,
              icon: isBusy
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.play_arrow_rounded, size: 16),
              label: Text(isBusy ? '...' : 'START'),
            ),
          ),
        );
      },
    );
  }

  Future<void> _handleStart(
      BuildContext context, TradingControlProvider ctrl) async {
    final t = context.read<LocaleProvider>().t;
    final confirmed = await ConfirmationDialog.show(
      context,
      title: t('start_trading'),
      message: '자동매매를 시작하시겠습니까?',
      confirmLabel: t('start_trading'),
      cancelLabel: t('cancel'),
      confirmColor: context.tc.primary,
      icon: Icons.play_arrow_rounded,
    );
    if (confirmed && context.mounted) {
      await ctrl.startTrading();
      if (context.mounted && ctrl.error != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${t('failed')}: ${ctrl.error}'),
            backgroundColor: context.tc.loss,
          ),
        );
      }
    }
  }

  Future<void> _handleStop(
      BuildContext context, TradingControlProvider ctrl) async {
    final t = context.read<LocaleProvider>().t;
    final confirmed = await ConfirmationDialog.show(
      context,
      title: t('stop_trading'),
      message: '자동매매를 중지하시겠습니까? (EOD 시퀀스 실행)',
      confirmLabel: t('stop_trading'),
      cancelLabel: t('cancel'),
      confirmColor: context.tc.warning,
      icon: Icons.stop_rounded,
    );
    if (confirmed && context.mounted) {
      await ctrl.stopTrading();
      if (context.mounted && ctrl.error != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${t('failed')}: ${ctrl.error}'),
            backgroundColor: context.tc.loss,
          ),
        );
      }
    }
  }
}

/// 뉴스 수집 & 텔레그램 전송 AppBar 버튼이다.
///
/// 마지막 크롤링 시점부터 현재까지의 뉴스를 수집하고
/// AI 분류 후 텔레그램으로 전송한다.
class _NewsCollectButton extends StatelessWidget {
  const _NewsCollectButton();

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Consumer<TradingControlProvider>(
      builder: (context, ctrl, _) {
        final isBusy = ctrl.isBusyNews;
        final isConnected = ctrl.isConnected;

        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
          child: Tooltip(
            message: '뉴스 수집 → AI 분류 → 텔레그램 전송',
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: tc.info.withValues(alpha: 0.12),
                foregroundColor: tc.info,
                side: BorderSide(
                    color: tc.info.withValues(alpha: 0.3), width: 1),
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                ),
                textStyle: AppTypography.labelLarge.copyWith(fontSize: 12),
              ),
              onPressed: (isBusy || !isConnected)
                  ? null
                  : () => _handleCollect(context, ctrl),
              icon: isBusy
                  ? SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: tc.info,
                      ),
                    )
                  : const Icon(Icons.newspaper_rounded, size: 16),
              label: Text(isBusy ? 'Sending...' : 'NEWS'),
            ),
          ),
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
          content: Text('뉴스 전송 실패: ${ctrl.error}'),
          backgroundColor: tc.loss,
        ),
      );
    } else if (ctrl.newsResult != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('뉴스 전송 완료 (${ctrl.newsResult})'),
          backgroundColor: tc.profit,
        ),
      );
    }
  }
}

/// 긴급 정지 활성 시 상단 배너이다.
class _EmergencyBanner extends StatelessWidget {
  const _EmergencyBanner();

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final t = context.watch<LocaleProvider>().t;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      color: tc.loss.withValues(alpha: 0.15),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.warning_rounded, size: 16, color: tc.loss),
          AppSpacing.hGapSm,
          Text(
            t('emergency_stop_banner'),
            style: AppTypography.labelLarge.copyWith(
              color: tc.loss,
              fontSize: 13,
            ),
          ),
          AppSpacing.hGapSm,
          Icon(Icons.warning_rounded, size: 16, color: tc.loss),
        ],
      ),
    );
  }
}
