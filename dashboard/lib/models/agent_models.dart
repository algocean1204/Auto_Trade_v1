// 에이전트 팀 및 에이전트 정보 데이터 모델이다.

/// 에이전트 팀 유형을 정의한다.
enum AgentTeamType {
  crawling,
  analysis,
  decision,
  execution,
  safety,
  monitoring,
}

extension AgentTeamTypeExtension on AgentTeamType {
  String get teamId {
    switch (this) {
      case AgentTeamType.crawling:
        return 'crawling';
      case AgentTeamType.analysis:
        return 'analysis';
      case AgentTeamType.decision:
        return 'decision';
      case AgentTeamType.execution:
        return 'execution';
      case AgentTeamType.safety:
        return 'safety';
      case AgentTeamType.monitoring:
        return 'monitoring';
    }
  }

  String get labelKey {
    switch (this) {
      case AgentTeamType.crawling:
        return 'crawling_team';
      case AgentTeamType.analysis:
        return 'analysis_team';
      case AgentTeamType.decision:
        return 'decision_team';
      case AgentTeamType.execution:
        return 'execution_team';
      case AgentTeamType.safety:
        return 'safety_team';
      case AgentTeamType.monitoring:
        return 'monitoring_team';
    }
  }

  String get emoji {
    switch (this) {
      case AgentTeamType.crawling:
        return '\uD83D\uDD17';
      case AgentTeamType.analysis:
        return '\uD83E\uDDE0';
      case AgentTeamType.decision:
        return '\u26A1';
      case AgentTeamType.execution:
        return '\uD83C\uDFAF';
      case AgentTeamType.safety:
        return '\uD83D\uDEE1\uFE0F';
      case AgentTeamType.monitoring:
        return '\uD83D\uDCCA';
    }
  }
}

/// 개별 에이전트 정보를 담는 모델이다.
class AgentInfo {
  final String id;
  final String name;
  final String description;
  final String teamId;
  final bool isActive;
  final String? mdContent;

  const AgentInfo({
    required this.id,
    required this.name,
    required this.description,
    required this.teamId,
    this.isActive = true,
    this.mdContent,
  });

  AgentInfo copyWith({
    String? id,
    String? name,
    String? description,
    String? teamId,
    bool? isActive,
    String? mdContent,
  }) {
    return AgentInfo(
      id: id ?? this.id,
      name: name ?? this.name,
      description: description ?? this.description,
      teamId: teamId ?? this.teamId,
      isActive: isActive ?? this.isActive,
      mdContent: mdContent ?? this.mdContent,
    );
  }

  factory AgentInfo.fromJson(Map<String, dynamic> json) {
    return AgentInfo(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      description: json['description'] as String? ?? '',
      teamId: json['team_id'] as String? ?? '',
      isActive: json['is_active'] as bool? ?? true,
      mdContent: json['md_content'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'description': description,
        'team_id': teamId,
        'is_active': isActive,
        if (mdContent != null) 'md_content': mdContent,
      };
}

/// 에이전트 팀 정보를 담는 모델이다.
class AgentTeam {
  final String id;
  final AgentTeamType type;
  final List<AgentInfo> agents;

  const AgentTeam({
    required this.id,
    required this.type,
    required this.agents,
  });

  int get activeCount => agents.where((a) => a.isActive).length;
  int get totalCount => agents.length;

  factory AgentTeam.fromJson(Map<String, dynamic> json) {
    final typeStr = json['id'] as String? ?? '';
    final type = AgentTeamType.values.firstWhere(
      (t) => t.teamId == typeStr,
      orElse: () => AgentTeamType.crawling,
    );
    final agentsList = (json['agents'] as List<dynamic>? ?? [])
        .map((a) => AgentInfo.fromJson(a as Map<String, dynamic>))
        .toList();
    return AgentTeam(
      id: typeStr,
      type: type,
      agents: agentsList,
    );
  }
}

/// 파이프라인 플로우 단계를 정의한다.
/// Crawling -> Analysis -> Decision -> Execution -> Monitoring
/// Safety는 Execution에 연결된 별도 브랜치이다.
class PipelineStep {
  final AgentTeamType teamType;
  final List<AgentTeamType> connectsTo;

  const PipelineStep({
    required this.teamType,
    this.connectsTo = const [],
  });
}

/// 기본 에이전트 팀 데이터 (API 응답 없을 시 폴백)이다.
class AgentData {
  AgentData._();

  static List<AgentTeam> get defaultTeams => [
        AgentTeam(
          id: 'crawling',
          type: AgentTeamType.crawling,
          agents: [
            const AgentInfo(
              id: 'crawl_engine',
              name: 'CrawlEngine',
              description: '30소스 병렬 크롤링',
              teamId: 'crawling',
              isActive: true,
            ),
            const AgentInfo(
              id: 'crawl_scheduler',
              name: 'CrawlScheduler',
              description: '야간/주간 스케줄링',
              teamId: 'crawling',
              isActive: true,
            ),
            const AgentInfo(
              id: 'crawl_verifier',
              name: 'CrawlVerifier',
              description: '품질 검증',
              teamId: 'crawling',
              isActive: true,
            ),
          ],
        ),
        AgentTeam(
          id: 'analysis',
          type: AgentTeamType.analysis,
          agents: [
            const AgentInfo(
              id: 'news_classifier',
              name: 'NewsClassifier',
              description: '뉴스 분류',
              teamId: 'analysis',
              isActive: true,
            ),
            const AgentInfo(
              id: 'mlx_classifier',
              name: 'MLXClassifier',
              description: '로컬 AI 분류',
              teamId: 'analysis',
              isActive: true,
            ),
            const AgentInfo(
              id: 'regime_detector',
              name: 'RegimeDetector',
              description: '시장 레짐 감지',
              teamId: 'analysis',
              isActive: true,
            ),
            const AgentInfo(
              id: 'claude_client',
              name: 'ClaudeClient',
              description: 'Claude API 연동',
              teamId: 'analysis',
              isActive: true,
            ),
            const AgentInfo(
              id: 'knowledge_manager',
              name: 'KnowledgeManager',
              description: 'RAG 지식 관리',
              teamId: 'analysis',
              isActive: true,
            ),
          ],
        ),
        AgentTeam(
          id: 'decision',
          type: AgentTeamType.decision,
          agents: [
            const AgentInfo(
              id: 'decision_maker',
              name: 'DecisionMaker',
              description: '매매 결정',
              teamId: 'decision',
              isActive: true,
            ),
            const AgentInfo(
              id: 'entry_strategy',
              name: 'EntryStrategy',
              description: '진입 전략',
              teamId: 'decision',
              isActive: true,
            ),
            const AgentInfo(
              id: 'exit_strategy',
              name: 'ExitStrategy',
              description: '청산 전략',
              teamId: 'decision',
              isActive: true,
            ),
          ],
        ),
        AgentTeam(
          id: 'execution',
          type: AgentTeamType.execution,
          agents: [
            const AgentInfo(
              id: 'order_manager',
              name: 'OrderManager',
              description: '주문 관리',
              teamId: 'execution',
              isActive: true,
            ),
            const AgentInfo(
              id: 'kis_client',
              name: 'KISClient',
              description: '증권사 API 연동',
              teamId: 'execution',
              isActive: true,
            ),
            const AgentInfo(
              id: 'position_monitor',
              name: 'PositionMonitor',
              description: '포지션 감시',
              teamId: 'execution',
              isActive: true,
            ),
          ],
        ),
        AgentTeam(
          id: 'safety',
          type: AgentTeamType.safety,
          agents: [
            const AgentInfo(
              id: 'hard_safety',
              name: 'HardSafety',
              description: '하드 리밋',
              teamId: 'safety',
              isActive: true,
            ),
            const AgentInfo(
              id: 'safety_checker',
              name: 'SafetyChecker',
              description: '안전 체인',
              teamId: 'safety',
              isActive: true,
            ),
            const AgentInfo(
              id: 'emergency_protocol',
              name: 'EmergencyProtocol',
              description: '비상 대응',
              teamId: 'safety',
              isActive: true,
            ),
            const AgentInfo(
              id: 'capital_guard',
              name: 'CapitalGuard',
              description: '자본 보호',
              teamId: 'safety',
              isActive: true,
            ),
          ],
        ),
        AgentTeam(
          id: 'monitoring',
          type: AgentTeamType.monitoring,
          agents: [
            const AgentInfo(
              id: 'alert_manager',
              name: 'AlertManager',
              description: '알림 관리',
              teamId: 'monitoring',
              isActive: true,
            ),
            const AgentInfo(
              id: 'telegram_notifier',
              name: 'TelegramNotifier',
              description: '텔레그램 알림',
              teamId: 'monitoring',
              isActive: true,
            ),
            const AgentInfo(
              id: 'benchmark_comparison',
              name: 'BenchmarkComparison',
              description: '벤치마크 비교',
              teamId: 'monitoring',
              isActive: true,
            ),
            const AgentInfo(
              id: 'daily_feedback',
              name: 'DailyFeedback',
              description: '일일 피드백 분석',
              teamId: 'monitoring',
              isActive: true,
            ),
            const AgentInfo(
              id: 'weekly_analysis',
              name: 'WeeklyAnalysis',
              description: '주간 종합 분석',
              teamId: 'monitoring',
              isActive: true,
            ),
          ],
        ),
      ];

  static const List<PipelineStep> pipelineFlow = [
    PipelineStep(
      teamType: AgentTeamType.crawling,
      connectsTo: [AgentTeamType.analysis],
    ),
    PipelineStep(
      teamType: AgentTeamType.analysis,
      connectsTo: [AgentTeamType.decision],
    ),
    PipelineStep(
      teamType: AgentTeamType.decision,
      connectsTo: [AgentTeamType.execution],
    ),
    PipelineStep(
      teamType: AgentTeamType.execution,
      connectsTo: [AgentTeamType.monitoring],
    ),
    PipelineStep(
      teamType: AgentTeamType.safety,
      connectsTo: [AgentTeamType.execution],
    ),
    PipelineStep(
      teamType: AgentTeamType.monitoring,
      connectsTo: [],
    ),
  ];
}
