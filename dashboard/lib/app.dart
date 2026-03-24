import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'theme/app_theme.dart';
import 'services/api_service.dart';
import 'services/setup_service.dart';
import 'services/server_launcher.dart';
import 'services/websocket_service.dart';
import 'providers/dashboard_provider.dart';
import 'providers/chart_provider.dart';
import 'providers/indicator_provider.dart';
import 'providers/trade_provider.dart';
import 'providers/settings_provider.dart';
import 'providers/profit_target_provider.dart';
import 'providers/risk_provider.dart';
import 'providers/navigation_provider.dart';
import 'providers/emergency_provider.dart';
import 'providers/tax_fx_provider.dart';
import 'providers/benchmark_provider.dart';
import 'providers/locale_provider.dart';
import 'providers/agent_provider.dart';
import 'providers/macro_provider.dart';
import 'providers/report_provider.dart';
import 'providers/universe_provider.dart';
import 'providers/news_provider.dart';
import 'providers/principles_provider.dart';
import 'providers/trade_reasoning_provider.dart';
import 'providers/stock_analysis_provider.dart';
import 'providers/theme_provider.dart';
import 'providers/crawl_progress_provider.dart';
import 'providers/trading_mode_provider.dart';
import 'providers/trading_control_provider.dart';
import 'providers/scalper_tape_provider.dart';
import 'providers/manual_trade_provider.dart';
import 'providers/token_provider.dart';
import 'providers/setup_provider.dart';
import 'screens/shell_screen.dart';
import 'screens/setup/setup_wizard_screen.dart';
import 'screens/setup/gatekeeper_guide_screen.dart';

class AiTradingApp extends StatelessWidget {
  const AiTradingApp({super.key});

  @override
  Widget build(BuildContext context) {
    final apiService = ApiService();
    final wsService = WebSocketService();

    return MultiProvider(
      providers: [
        // 테마 상태
        ChangeNotifierProvider(create: (_) => ThemeProvider()),
        // 로케일 (언어) 상태
        ChangeNotifierProvider(create: (_) => LocaleProvider()),
        // 투자 모드 (모의/실전) 상태
        ChangeNotifierProvider(create: (_) => TradingModeProvider()),
        // 네비게이션 상태
        ChangeNotifierProvider(create: (_) => NavigationProvider()),
        // 긴급 상태 (전역)
        ChangeNotifierProvider(create: (_) => EmergencyProvider(apiService)),
        // 대시보드 / 시스템
        ChangeNotifierProvider(create: (_) => DashboardProvider(apiService)),
        // 차트
        ChangeNotifierProvider(create: (_) => ChartProvider(apiService)),
        // 인디케이터
        ChangeNotifierProvider(create: (_) => IndicatorProvider(apiService)),
        // 트레이딩 / 전략 / 피드백 / 유니버스
        ChangeNotifierProvider(create: (_) => TradeProvider(apiService)),
        // 알림 (Settings/Alerts)
        ChangeNotifierProvider(create: (_) => SettingsProvider(apiService)),
        // 수익 목표
        ChangeNotifierProvider(
            create: (_) => ProfitTargetProvider(apiService)),
        // 리스크
        ChangeNotifierProvider(create: (_) => RiskProvider(apiService)),
        // Tax / FX
        ChangeNotifierProvider(create: (_) => TaxFxProvider(apiService)),
        // 벤치마크
        ChangeNotifierProvider(
            create: (_) => BenchmarkProvider(apiService)),
        // 에이전트 팀
        ChangeNotifierProvider(create: (_) => AgentProvider(apiService)),
        // 거시경제 지표
        ChangeNotifierProvider(create: (_) => MacroProvider(apiService)),
        // 일간 리포트
        ChangeNotifierProvider(create: (_) => ReportProvider(apiService)),
        // 유니버스 관리
        ChangeNotifierProvider(create: (_) => UniverseProvider(apiService)),
        // 뉴스
        ChangeNotifierProvider(create: (_) => NewsProvider(apiService)),
        // 매매 원칙
        ChangeNotifierProvider(create: (_) => PrinciplesProvider(apiService)),
        // 매매 근거
        ChangeNotifierProvider(
            create: (_) => TradeReasoningProvider(apiService)),
        // 종목 종합 분석
        ChangeNotifierProvider(
            create: (_) => StockAnalysisProvider(apiService)),
        // 크롤링 진행 상태
        ChangeNotifierProvider(
            create: (_) => CrawlProgressProvider(apiService, wsService)),
        // 자동매매 제어 상태
        ChangeNotifierProvider(
            create: (_) => TradingControlProvider(apiService)),
        // 스캘퍼 테이프 실시간 데이터
        ChangeNotifierProvider(
            create: (_) => ScalperTapeProvider(wsService)),
        // 수동 매매 상태
        ChangeNotifierProvider(
            create: (_) => ManualTradeProvider(apiService)),
        // KIS 토큰 발급 및 유효성 상태
        ChangeNotifierProvider(create: (_) => TokenProvider()..initialize()),
        // WebSocket 서비스 (Provider로 노출)
        Provider<WebSocketService>(create: (_) => wsService),
        Provider<ApiService>(create: (_) => apiService),
        // 초기 설정 위저드 상태
        ChangeNotifierProvider(
            create: (_) => SetupProvider(SetupService())),
      ],
      child: Consumer<ThemeProvider>(
        builder: (context, themeProvider, child) {
          return MaterialApp(
            title: 'AI Trading Dashboard',
            theme: AppTheme.lightTheme,
            darkTheme: AppTheme.darkTheme,
            themeMode: themeProvider.themeMode,
            home: const _SetupGate(),
            debugShowCheckedModeBanner: false,
          );
        },
      ),
    );
  }
}

/// 앱 시작 시 초기 설정 완료 여부를 확인하여 위저드 또는 대시보드를 표시한다.
class _SetupGate extends StatefulWidget {
  const _SetupGate();

  @override
  State<_SetupGate> createState() => _SetupGateState();
}

class _SetupGateState extends State<_SetupGate> with WidgetsBindingObserver {
  bool? _setupComplete;
  bool _showGatekeeperGuide = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _checkSetupStatus();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 앱이 종료(detached)될 때 이 앱이 시작한 서버 프로세스를 정리한다.
    // 외부에서 시작한 서버(LaunchAgent 등)는 건드리지 않는다.
    if (state == AppLifecycleState.detached) {
      final launcher = ServerLauncher.instance;
      if (launcher.launchedByUs) {
        launcher.stop();
      }
    }
  }

  Future<void> _checkSetupStatus() async {
    try {
      // .app 번들 실행 시 Gatekeeper 안내 표시 여부를 확인한다
      if (GatekeeperGuideScreen.isRunningFromAppBundle()) {
        final shown = await GatekeeperGuideScreen.hasBeenShown();
        if (!shown && mounted) {
          setState(() => _showGatekeeperGuide = true);
          return;
        }
      }

      await _loadSetupStatus();
    } catch (_) {
      // 서버 연결 실패 시 위저드를 표시한다
      if (!mounted) return;
      setState(() => _setupComplete = false);
    }
  }

  /// 셋업 위저드 완료 상태를 확인한다.
  ///
  /// 서버를 자동 시작하지 않는다. .env 파일 존재 여부로 로컬에서 판단한다.
  /// .env가 있으면 → 대시보드 표시 (서버는 꺼진 상태, 사용자가 수동 시작)
  /// .env가 없으면 → 서버 시작 → 위저드 표시
  Future<void> _loadSetupStatus() async {
    final launcher = ServerLauncher.instance;

    // 1) 프로젝트 루트에서 .env 존재 여부를 로컬로 확인한다
    final hasEnv = _checkEnvFileExists(launcher);

    if (hasEnv) {
      // .env가 있으면 셋업 완료로 간주하고 대시보드를 표시한다
      // 서버는 시작하지 않는다 — 사용자가 자동매매 버튼으로 시작한다
      if (!mounted) return;
      setState(() => _setupComplete = true);
      return;
    }

    // 2) .env가 없으면 서버를 시작하여 위저드를 진행한다
    try {
      final running = await launcher.isServerRunning();
      if (!running) {
        final result = await launcher.ensureRunning();
        if (!result.success) {
          if (!mounted) return;
          setState(() => _setupComplete = false);
          return;
        }
      }

      final provider = context.read<SetupProvider>();
      await provider.loadStatus();
      if (!mounted) return;
      setState(() => _setupComplete = provider.isSetupComplete);
    } catch (_) {
      if (!mounted) return;
      setState(() => _setupComplete = false);
    }
  }

  /// .env 파일이 존재하는지 확인한다.
  ///
  /// ServerLauncher.envFilePath를 사용하여 번들/개발 모드 모두 올바른 경로를 확인한다.
  /// 번들 모드: ~/Library/Application Support/com.stocktrader.ai/.env
  /// 개발 모드: {projectRoot}/.env
  bool _checkEnvFileExists(ServerLauncher launcher) {
    try {
      // ServerLauncher가 모드에 맞는 .env 경로를 반환한다.
      final envPath = launcher.envFilePath;
      if (envPath != null && File(envPath).existsSync()) return true;

      // 프로젝트 루트를 초기화하기 위해 ensureRunning 전에 projectRoot를 한 번 탐색한다.
      final root = launcher.projectRoot;
      if (root != null && File('$root/.env').existsSync()) return true;

      return false;
    } catch (_) {
      return false;
    }
  }

  @override
  Widget build(BuildContext context) {
    // Gatekeeper 안내 화면을 먼저 표시한다
    if (_showGatekeeperGuide) {
      return GatekeeperGuideScreen(
        onDismiss: () {
          setState(() => _showGatekeeperGuide = false);
          _loadSetupStatus();
        },
      );
    }

    if (_setupComplete == null) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }
    return _setupComplete! ? const ShellScreen() : const SetupWizardScreen();
  }
}
