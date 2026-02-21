import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'theme/app_theme.dart';
import 'services/api_service.dart';
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
import 'screens/shell_screen.dart';

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
        // WebSocket 서비스 (Provider로 노출)
        Provider<WebSocketService>(create: (_) => wsService),
        Provider<ApiService>(create: (_) => apiService),
      ],
      child: Consumer<ThemeProvider>(
        builder: (context, themeProvider, child) {
          return MaterialApp(
            title: 'AI Trading Dashboard',
            theme: AppTheme.lightTheme,
            darkTheme: AppTheme.darkTheme,
            themeMode: themeProvider.themeMode,
            home: const ShellScreen(),
            debugShowCheckedModeBanner: false,
          );
        },
      ),
    );
  }
}
