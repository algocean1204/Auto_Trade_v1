import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/agent_models.dart';
import '../providers/agent_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/agent_team_tree.dart';
import 'agent_detail_screen.dart';

/// 에이전트 팀 전체 화면이다.
/// 상단 헤더, 파이프라인 플로우, 팀별 에이전트 트리를 표시한다.
class AgentTeamScreen extends StatefulWidget {
  const AgentTeamScreen({super.key});

  @override
  State<AgentTeamScreen> createState() => _AgentTeamScreenState();
}

class _AgentTeamScreenState extends State<AgentTeamScreen> {
  @override
  void initState() {
    super.initState();
    // 화면 진입 시 항상 에이전트 목록을 로드한다.
    // teams.isEmpty 조건 없이 매번 로드하여 최신 데이터를 보장한다.
    // ApiService.getAgentList()가 오류 시 빈 목록을 반환하므로
    // 조건부 검사만으로는 폴백이 작동하지 않을 수 있기 때문이다.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<AgentProvider>().loadTeams();
    });
  }

  void _openAgentDetail(AgentInfo agent, AgentTeam team) {
    // 에이전트 상세 화면을 슬라이드로 열어 MD 내용을 표시한다.
    Navigator.of(context).push(
      PageRouteBuilder(
        pageBuilder: (context, animation, secondaryAnimation) {
          return AgentDetailScreen(agent: agent, team: team);
        },
        transitionsBuilder: (context, animation, secondaryAnimation, child) {
          const begin = Offset(1.0, 0.0);
          const end = Offset.zero;
          final tween = Tween(begin: begin, end: end).chain(
            CurveTween(curve: Curves.easeOutCubic),
          );
          return SlideTransition(
            position: animation.drive(tween),
            child: child,
          );
        },
        transitionDuration: const Duration(milliseconds: 280),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final locale = context.watch<LocaleProvider>();

    return Scaffold(
      backgroundColor: context.tc.background,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 화면 헤더
          _AgentTeamHeader(locale: locale),
          // 에이전트 트리 스크롤 영역
          Expanded(
            child: Consumer<AgentProvider>(
              builder: (context, agentProvider, _) {
                if (agentProvider.isLoading) {
                  return Center(
                    child: CircularProgressIndicator(
                      color: context.tc.primary,
                    ),
                  );
                }

                return RefreshIndicator(
                  color: context.tc.primary,
                  backgroundColor: context.tc.surfaceElevated,
                  onRefresh: () => agentProvider.refresh(),
                  child: ListView(
                    padding: const EdgeInsets.all(AppSpacing.lg),
                    children: [
                      AgentTeamTree(
                        onAgentTap: _openAgentDetail,
                      ),
                      const SizedBox(height: AppSpacing.xxl),
                    ],
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

/// 에이전트 팀 화면 헤더 위젯이다.
class _AgentTeamHeader extends StatelessWidget {
  final LocaleProvider locale;

  const _AgentTeamHeader({required this.locale});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.xl,
        AppSpacing.xl,
        AppSpacing.xl,
        AppSpacing.lg,
      ),
      decoration: BoxDecoration(
        color: context.tc.surface,
        border: Border(
          bottom: BorderSide(
            color: context.tc.surfaceBorder.withValues(alpha: 0.3),
            width: 1,
          ),
        ),
      ),
      child: Row(
        children: [
          // 아이콘
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: context.tc.primary.withValues(alpha: 0.12),
              borderRadius: AppSpacing.borderRadiusMd,
            ),
            child: Icon(
              Icons.account_tree_rounded,
              size: 20,
              color: context.tc.primary,
            ),
          ),
          AppSpacing.hGapLg,
          // 제목 + 부제목
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  locale.t('agent_teams'),
                  style: AppTypography.headlineMedium,
                ),
                Text(
                  locale.t('agent_teams_subtitle'),
                  style: AppTypography.bodySmall,
                ),
              ],
            ),
          ),
          // 새로고침 버튼
          Consumer<AgentProvider>(
            builder: (context, provider, _) {
              return IconButton(
                icon: Icon(
                  Icons.refresh_rounded,
                  size: 20,
                  color: context.tc.textSecondary,
                ),
                tooltip: locale.t('refresh'),
                onPressed: provider.isLoading ? null : () => provider.refresh(),
              );
            },
          ),
        ],
      ),
    );
  }
}
