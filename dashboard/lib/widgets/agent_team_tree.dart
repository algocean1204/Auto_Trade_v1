import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/agent_models.dart';
import '../providers/agent_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';

/// 에이전트 팀 파이프라인 트리 위젯이다.
/// 상단에 파이프라인 플로우 다이어그램을, 하단에 팀별 접을 수 있는 에이전트 목록을 표시한다.
class AgentTeamTree extends StatelessWidget {
  final void Function(AgentInfo agent, AgentTeam team) onAgentTap;

  const AgentTeamTree({
    super.key,
    required this.onAgentTap,
  });

  @override
  Widget build(BuildContext context) {
    return Consumer2<AgentProvider, LocaleProvider>(
      builder: (context, agentProvider, locale, _) {
        if (agentProvider.isLoading) {
          return Center(
            child: CircularProgressIndicator(color: context.tc.primary),
          );
        }

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 파이프라인 플로우 다이어그램
            _PipelineFlowRow(teams: agentProvider.teams, locale: locale),
            AppSpacing.vGapLg,
            // 팀별 트리 목록
            ...agentProvider.teams.map(
              (team) => _TeamExpansionTile(
                team: team,
                locale: locale,
                onAgentTap: onAgentTap,
              ),
            ),
          ],
        );
      },
    );
  }
}

/// 파이프라인 흐름을 가로 행으로 표시하는 위젯이다.
class _PipelineFlowRow extends StatelessWidget {
  final List<AgentTeam> teams;
  final LocaleProvider locale;

  const _PipelineFlowRow({required this.teams, required this.locale});

  @override
  Widget build(BuildContext context) {
    // 주 파이프라인: Crawling → Analysis → Decision → Execution → Monitoring
    final mainFlow = [
      AgentTeamType.crawling,
      AgentTeamType.analysis,
      AgentTeamType.decision,
      AgentTeamType.execution,
      AgentTeamType.monitoring,
    ];

    return GlassCard(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            locale.t('pipeline_flow'),
            style: AppTypography.labelMedium.copyWith(
              color: context.tc.textTertiary,
              fontSize: 11,
              letterSpacing: 0.8,
            ),
          ),
          AppSpacing.vGapMd,
          // 메인 플로우 행
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                for (int i = 0; i < mainFlow.length; i++) ...[
                  _PipelineNode(teamType: mainFlow[i], locale: locale),
                  if (i < mainFlow.length - 1)
                    _FlowArrow(),
                ],
              ],
            ),
          ),
          AppSpacing.vGapMd,
          // 안전팀 브랜치 표시
          Row(
            children: [
              const SizedBox(width: 16),
              Container(
                width: 1,
                height: 20,
                color: context.tc.warning.withValues(alpha: 0.4),
              ),
              const SizedBox(width: 8),
              Icon(
                Icons.security_rounded,
                size: 12,
                color: context.tc.warning.withValues(alpha: 0.7),
              ),
              const SizedBox(width: 4),
              Text(
                locale.t('safety_team'),
                style: AppTypography.bodySmall.copyWith(
                  color: context.tc.warning.withValues(alpha: 0.8),
                  fontSize: 11,
                ),
              ),
              const SizedBox(width: 4),
              Text(
                '\u2192 Execution',
                style: AppTypography.bodySmall.copyWith(
                  color: context.tc.textTertiary,
                  fontSize: 10,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// 파이프라인의 단일 노드 위젯이다.
class _PipelineNode extends StatelessWidget {
  final AgentTeamType teamType;
  final LocaleProvider locale;

  const _PipelineNode({required this.teamType, required this.locale});

  Color _nodeColor(BuildContext context) {
    switch (teamType) {
      case AgentTeamType.crawling:
        return context.tc.chart1;
      case AgentTeamType.analysis:
        return context.tc.chart4;
      case AgentTeamType.decision:
        return context.tc.chart3;
      case AgentTeamType.execution:
        return context.tc.profit;
      case AgentTeamType.safety:
        return context.tc.warning;
      case AgentTeamType.monitoring:
        return context.tc.chart2;
    }
  }

  @override
  Widget build(BuildContext context) {
    final nodeColor = _nodeColor(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: nodeColor.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(
          color: nodeColor.withValues(alpha: 0.35),
          width: 1,
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            teamType.emoji,
            style: const TextStyle(fontSize: 16),
          ),
          const SizedBox(height: 2),
          Text(
            locale.t(teamType.labelKey),
            style: AppTypography.bodySmall.copyWith(
              fontSize: 10,
              color: nodeColor,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

/// 파이프라인 화살표 위젯이다.
class _FlowArrow extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: Icon(
        Icons.arrow_forward_rounded,
        size: 14,
        color: context.tc.textTertiary,
      ),
    );
  }
}

/// 팀별 접을 수 있는 에이전트 목록 타일이다.
class _TeamExpansionTile extends StatefulWidget {
  final AgentTeam team;
  final LocaleProvider locale;
  final void Function(AgentInfo agent, AgentTeam team) onAgentTap;

  const _TeamExpansionTile({
    required this.team,
    required this.locale,
    required this.onAgentTap,
  });

  @override
  State<_TeamExpansionTile> createState() => _TeamExpansionTileState();
}

class _TeamExpansionTileState extends State<_TeamExpansionTile>
    with SingleTickerProviderStateMixin {
  bool _expanded = true;
  late AnimationController _controller;
  late Animation<double> _expandAnim;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 220),
      value: 1.0,
    );
    _expandAnim = CurvedAnimation(
      parent: _controller,
      curve: Curves.easeOutCubic,
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _toggle() {
    setState(() {
      _expanded = !_expanded;
      if (_expanded) {
        _controller.forward();
      } else {
        _controller.reverse();
      }
    });
  }

  Color get _teamColor {
    final tc = context.tc;
    switch (widget.team.type) {
      case AgentTeamType.crawling:
        return tc.chart1;
      case AgentTeamType.analysis:
        return tc.chart4;
      case AgentTeamType.decision:
        return tc.chart3;
      case AgentTeamType.execution:
        return tc.profit;
      case AgentTeamType.safety:
        return tc.warning;
      case AgentTeamType.monitoring:
        return tc.chart2;
    }
  }

  @override
  Widget build(BuildContext context) {
    final locale = widget.locale;
    final agentsCountStr = locale
        .t('agents_count')
        .replaceAll('{n}', '${widget.team.totalCount}');

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        decoration: BoxDecoration(
          color: context.tc.surfaceElevated.withValues(alpha: 0.6),
          borderRadius: AppSpacing.borderRadiusMd,
          border: Border.all(
            color: _teamColor.withValues(alpha: 0.2),
            width: 1,
          ),
        ),
        child: Column(
          children: [
            // 팀 헤더
            InkWell(
              onTap: _toggle,
              borderRadius: _expanded
                  ? BorderRadius.vertical(
                      top: Radius.circular(AppSpacing.radiusMd))
                  : AppSpacing.borderRadiusMd,
              child: Padding(
                padding: const EdgeInsets.symmetric(
                    horizontal: 14, vertical: 12),
                child: Row(
                  children: [
                    // 팀 이콘 배지
                    Container(
                      width: 32,
                      height: 32,
                      decoration: BoxDecoration(
                        color: _teamColor.withValues(alpha: 0.15),
                        borderRadius: AppSpacing.borderRadiusSm,
                      ),
                      child: Center(
                        child: Text(
                          widget.team.type.emoji,
                          style: const TextStyle(fontSize: 16),
                        ),
                      ),
                    ),
                    AppSpacing.hGapMd,
                    // 팀 이름 + 카운트
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            locale.t(widget.team.type.labelKey),
                            style: AppTypography.labelLarge.copyWith(
                              color: _teamColor,
                              fontSize: 13,
                            ),
                          ),
                          Text(
                            agentsCountStr,
                            style: AppTypography.bodySmall.copyWith(
                              fontSize: 11,
                            ),
                          ),
                        ],
                      ),
                    ),
                    // 활성 에이전트 카운트 배지
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: _teamColor.withValues(alpha: 0.15),
                        borderRadius: AppSpacing.borderRadiusFull,
                      ),
                      child: Text(
                        '${widget.team.activeCount}/${widget.team.totalCount}',
                        style: AppTypography.bodySmall.copyWith(
                          fontSize: 10,
                          color: _teamColor,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    AppSpacing.hGapSm,
                    // 펼치기/접기 아이콘
                    AnimatedRotation(
                      turns: _expanded ? 0.0 : -0.25,
                      duration: const Duration(milliseconds: 220),
                      child: Icon(
                        Icons.keyboard_arrow_down_rounded,
                        size: 18,
                        color: context.tc.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            // 에이전트 목록 (접을 수 있음)
            SizeTransition(
              sizeFactor: _expandAnim,
              child: Column(
                children: [
                  Container(
                    height: 1,
                    margin: const EdgeInsets.symmetric(horizontal: 14),
                    color: _teamColor.withValues(alpha: 0.15),
                  ),
                  ...widget.team.agents.asMap().entries.map((entry) {
                    final idx = entry.key;
                    final agent = entry.value;
                    final isLast = idx == widget.team.agents.length - 1;
                    return _AgentRow(
                      agent: agent,
                      isLast: isLast,
                      teamColor: _teamColor,
                      onTap: () => widget.onAgentTap(agent, widget.team),
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

/// 개별 에이전트 행 위젯이다.
class _AgentRow extends StatelessWidget {
  final AgentInfo agent;
  final bool isLast;
  final Color teamColor;
  final VoidCallback onTap;

  const _AgentRow({
    required this.agent,
    required this.isLast,
    required this.teamColor,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: isLast
            ? const BorderRadius.vertical(
                bottom: Radius.circular(AppSpacing.radiusMd))
            : BorderRadius.zero,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          child: Row(
            children: [
              // 트리 라인 표시
              SizedBox(
                width: 20,
                child: Column(
                  children: [
                    Container(
                      width: 1,
                      height: isLast ? 10 : 20,
                      color: teamColor.withValues(alpha: 0.3),
                    ),
                    if (!isLast)
                      Expanded(
                        child: Container(
                          width: 1,
                          color: teamColor.withValues(alpha: 0.3),
                        ),
                      ),
                  ],
                ),
              ),
              // 가로 연결선
              Container(
                width: 10,
                height: 1,
                color: teamColor.withValues(alpha: 0.3),
              ),
              AppSpacing.hGapSm,
              // 상태 인디케이터 (녹색 점)
              Container(
                width: 6,
                height: 6,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: agent.isActive
                      ? context.tc.profit
                      : context.tc.textDisabled,
                  boxShadow: agent.isActive
                      ? [
                          BoxShadow(
                            color: context.tc.profit.withValues(alpha: 0.4),
                            blurRadius: 4,
                          ),
                        ]
                      : null,
                ),
              ),
              AppSpacing.hGapSm,
              // 에이전트 정보
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      agent.name,
                      style: AppTypography.labelLarge.copyWith(
                        fontSize: 12,
                        color: context.tc.textPrimary,
                      ),
                    ),
                    Text(
                      agent.description,
                      style: AppTypography.bodySmall.copyWith(
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
              // 상세 보기 화살표
              Icon(
                Icons.chevron_right_rounded,
                size: 16,
                color: context.tc.textDisabled,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
