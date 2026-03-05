import 'package:flutter/material.dart';
import '../models/agent_models.dart';
import '../services/api_service.dart';

/// 에이전트 팀 목록과 에이전트 상세 내용을 관리하는 Provider이다.
class AgentProvider with ChangeNotifier {
  final ApiService _apiService;

  AgentProvider(this._apiService);

  List<AgentTeam> _teams = [];
  bool _isLoading = false;
  String? _error;

  // 에이전트 상세 MD 콘텐츠 캐시이다.
  final Map<String, String> _mdCache = {};
  bool _isMdLoading = false;
  String? _mdError;
  String? _currentAgentId;

  List<AgentTeam> get teams => _teams;
  bool get isLoading => _isLoading;
  String? get error => _error;
  bool get isMdLoading => _isMdLoading;
  String? get mdError => _mdError;
  String? get currentAgentId => _currentAgentId;

  /// 팀 목록을 로드한다. 실패하거나 빈 목록이면 기본 데이터로 폴백한다.
  Future<void> loadTeams() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final loaded = await _apiService.getAgentList();
      // API 호출은 성공했지만 빈 목록인 경우에도 기본 데이터로 폴백한다.
      // ApiService.getAgentList()는 내부에서 예외를 삼키고 []를 반환하므로
      // 이 체크로 네트워크 오류 시에도 기본 데이터가 표시되도록 보장한다.
      _teams = loaded.isNotEmpty ? loaded : AgentData.defaultTeams;
      _error = null;
    } catch (e) {
      // 예외가 전파된 경우에도 기본 데이터로 폴백한다.
      _teams = AgentData.defaultTeams;
      _error = null;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 특정 에이전트의 MD 콘텐츠를 로드한다.
  Future<String?> loadAgentMd(String agentId) async {
    if (_mdCache.containsKey(agentId)) {
      _currentAgentId = agentId;
      _isMdLoading = false;
      _mdError = null;
      notifyListeners();
      return _mdCache[agentId];
    }

    _currentAgentId = agentId;
    _isMdLoading = true;
    _mdError = null;
    notifyListeners();

    try {
      final content = await _apiService.getAgentMd(agentId);
      _mdCache[agentId] = content;
      _mdError = null;
      return content;
    } catch (e) {
      _mdError = e.toString();
      return null;
    } finally {
      _isMdLoading = false;
      notifyListeners();
    }
  }

  /// 특정 에이전트의 MD 콘텐츠를 저장한다.
  Future<bool> saveAgentMd(String agentId, String content) async {
    try {
      await _apiService.saveAgentMd(agentId, content);
      _mdCache[agentId] = content;
      notifyListeners();
      return true;
    } catch (e) {
      return false;
    }
  }

  /// 캐시된 MD 콘텐츠를 반환한다.
  String? getCachedMd(String agentId) => _mdCache[agentId];

  /// 특정 팀에서 에이전트를 찾는다.
  AgentInfo? findAgent(String agentId) {
    for (final team in _teams) {
      for (final agent in team.agents) {
        if (agent.id == agentId) return agent;
      }
    }
    return null;
  }

  /// 특정 에이전트가 속한 팀을 반환한다.
  AgentTeam? findTeamForAgent(String agentId) {
    for (final team in _teams) {
      for (final agent in team.agents) {
        if (agent.id == agentId) return team;
      }
    }
    return null;
  }

  /// 새로고침한다.
  Future<void> refresh() async {
    await loadTeams();
  }
}
