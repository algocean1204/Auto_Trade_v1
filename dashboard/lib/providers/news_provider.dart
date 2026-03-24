import 'package:flutter/material.dart';
import '../models/news_models.dart';
import '../services/api_service.dart';

/// 뉴스 화면 상태 관리 프로바이더이다.
class NewsProvider with ChangeNotifier {
  final ApiService _api;

  List<NewsDate>? _dates;
  NewsSummary? _summary;
  List<NewsArticle>? _articles;
  NewsArticle? _selectedArticle;
  String? _selectedDate;
  String? _filterCategory;

  /// 임팩트 필터이다. null이면 majorNewsOnly 모드에 따라 결정된다.
  String? _filterImpact;

  /// 중요도 필터이다. null이면 전체, "critical"이면 크리티컬만,
  /// "key"이면 크리티컬+핵심을 표시한다.
  String? _filterImportance;

  /// 주요 뉴스만 보기 모드이다 (high + medium impact).
  /// true이면 high/medium impact 기사만 표시하고, false이면 전체를 표시한다.
  bool _majorNewsOnly = true;

  bool _isLoading = false;
  bool _isLoadingDetail = false;
  bool _isLoadingMore = false;
  String? _error;
  int _total = 0;
  int _currentOffset = 0;
  static const int _pageSize = 50;

  /// 빠른 필터 전환 시 race condition 방지를 위한 세대 카운터이다.
  /// loadArticles 시작 시 증가하고, 완료 시 현재 세대와 비교하여
  /// stale 응답이면 결과를 무시한다.
  int _loadGeneration = 0;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  NewsProvider(this._api);

  // ── Getters ──

  List<NewsDate>? get dates => _dates;
  NewsSummary? get summary => _summary;
  List<NewsArticle>? get articles => _articles;
  NewsArticle? get selectedArticle => _selectedArticle;
  String? get selectedDate => _selectedDate;
  String? get filterCategory => _filterCategory;
  String? get filterImpact => _filterImpact;
  String? get filterImportance => _filterImportance;
  bool get majorNewsOnly => _majorNewsOnly;
  bool get isLoading => _isLoading;
  bool get isLoadingDetail => _isLoadingDetail;
  bool get isLoadingMore => _isLoadingMore;
  String? get error => _error;
  int get total => _total;
  bool get hasMore => _articles != null && (_articles?.length ?? 0) < _total;

  // ── Actions ──

  /// 뉴스 날짜 목록을 로드한다.
  Future<void> loadDates({int limit = 30}) async {
    _isLoading = true;
    _error = null;
    _safeNotify();

    try {
      _dates = await _api.getNewsDates(limit: limit);
      _error = null;

      // 날짜 목록이 있고 아직 날짜를 선택하지 않았으면 첫 번째 날짜를 자동 선택한다
      final dates = _dates;
      if (dates != null && dates.isNotEmpty && _selectedDate == null) {
        _isLoading = false;
        _safeNotify();
        await selectDate(dates.first.date);
        return;
      }
    } catch (e) {
      _error = _friendlyError(e);
    } finally {
      _isLoading = false;
      _safeNotify();
    }
  }

  /// 날짜를 선택하고 기사 목록과 요약을 로드한다.
  Future<void> selectDate(String date) async {
    if (_selectedDate == date) return;
    _selectedDate = date;
    _articles = null;
    _summary = null;
    _selectedArticle = null;
    _currentOffset = 0;
    _total = 0;
    _safeNotify();

    await Future.wait([
      loadArticles(),
      loadSummary(),
    ]);
  }

  /// 기사 목록을 로드한다.
  /// 주요 뉴스만 모드에서는 impact 파라미터 없이 로드하고 클라이언트에서 필터링한다.
  /// 단일 impact 필터가 설정되어 있으면 해당 값을 API에 전달한다.
  /// 세대 카운터 패턴으로 빠른 필터 전환 시 stale 응답을 무시한다.
  Future<void> loadArticles({int offset = 0}) async {
    if (_selectedDate == null) return;

    // 세대 증가: 이전 진행 중인 요청의 결과를 무효화한다
    final thisGeneration = ++_loadGeneration;

    if (offset == 0) {
      _isLoading = true;
      _error = null;
    } else {
      _isLoadingMore = true;
    }
    _safeNotify();

    try {
      // 주요 뉴스만 모드: API는 impact 필터 없이 호출하고 클라이언트에서 필터링한다.
      // 단일 impact 필터 모드: API에 해당 impact 값을 전달한다.
      final String? apiImpact = _majorNewsOnly ? null : _filterImpact;

      final result = await _api.getDailyNews(
        _selectedDate ?? '',
        category: _filterCategory,
        impact: apiImpact,
        limit: _pageSize,
        offset: offset,
      );

      // stale 응답 확인: 요청 시작 이후 새 요청이 발생했으면 결과를 버린다
      if (thisGeneration != _loadGeneration) return;

      _total = (result['total'] as num? ?? 0).toInt();
      final rawArticles = result['articles'] as List? ?? [];
      List<NewsArticle> newArticles = rawArticles
          .map((e) => NewsArticle.fromJson(e as Map<String, dynamic>))
          .toList();

      // 주요 뉴스만 모드이면 클라이언트에서 high/medium 기사만 필터링한다.
      if (_majorNewsOnly) {
        newArticles = newArticles.where((a) {
          final imp = a.impact.toLowerCase();
          return imp == 'high' || imp == 'medium';
        }).toList();
        // 클라이언트 필터링이므로 서버 total을 그대로 유지한다.
        // hasMore는 서버 total 기준으로 판단하여 누락 없이 로드한다.
      }

      // 중요도 필터를 클라이언트에서 적용한다.
      if (_filterImportance == 'critical') {
        newArticles = newArticles
            .where((a) => a.importance == 'critical')
            .toList();
      } else if (_filterImportance == 'key') {
        // 핵심 필터는 critical + key 모두 포함한다.
        newArticles = newArticles
            .where((a) =>
                a.importance == 'critical' || a.importance == 'key')
            .toList();
      }

      if (offset == 0) {
        _articles = newArticles;
        _currentOffset = newArticles.length;
      } else {
        _articles = [...(_articles ?? []), ...newArticles];
        _currentOffset = _articles?.length ?? 0;
      }
      _error = null;
    } catch (e) {
      // stale 에러도 무시한다
      if (thisGeneration != _loadGeneration) return;
      _error = _friendlyError(e);
      if (offset == 0) _articles = [];
    } finally {
      // stale 응답이면 UI 상태를 건드리지 않는다
      if (thisGeneration == _loadGeneration) {
        _isLoading = false;
        _isLoadingMore = false;
        _safeNotify();
      }
    }
  }

  /// 다음 페이지 기사를 로드한다 (스크롤 페이지네이션).
  Future<void> loadMore() async {
    if (_isLoadingMore || !hasMore) return;
    await loadArticles(offset: _currentOffset);
  }

  /// 날짜 요약을 로드한다.
  Future<void> loadSummary() async {
    if (_selectedDate == null) return;

    try {
      _summary = await _api.getNewsSummary(date: _selectedDate);
      _safeNotify();
    } catch (e) {
      // 요약 로드 실패는 조용히 처리한다 (기사 목록은 계속 표시)
      _summary = null;
      _safeNotify();
    }
  }

  /// 기사 상세 내용을 로드한다.
  Future<void> loadArticleDetail(String id) async {
    _isLoadingDetail = true;
    _safeNotify();

    try {
      _selectedArticle = await _api.getArticleDetail(id);
      _safeNotify();
    } catch (e) {
      // 상세 로드 실패 시 기존 기사 정보를 유지한다
    } finally {
      _isLoadingDetail = false;
      _safeNotify();
    }
  }

  /// 선택된 기사를 설정한다 (로컬 데이터로 즉시 표시).
  void selectArticle(NewsArticle article) {
    _selectedArticle = article;
    _safeNotify();
  }

  /// 기사 선택을 해제한다.
  void clearSelectedArticle() {
    _selectedArticle = null;
    _safeNotify();
  }

  /// 카테고리 필터를 설정하고 기사 목록을 다시 로드한다.
  /// category가 null이면 전체 카테고리를 표시한다.
  void setCategory(String? category) {
    _filterCategory = category;
    _articles = null;
    _currentOffset = 0;
    _safeNotify();
    loadArticles();
  }

  /// impact 단일 필터를 설정하고 기사 목록을 다시 로드한다.
  /// majorNewsOnly 모드가 활성화된 경우 이 필터는 무시된다.
  void setImpact(String? impact) {
    _filterImpact = impact;
    _articles = null;
    _currentOffset = 0;
    _safeNotify();
    loadArticles();
  }

  /// 중요도 필터를 설정하고 기사 목록을 다시 로드한다.
  /// null이면 전체, "critical"이면 크리티컬만, "key"이면 크리티컬+핵심 표시한다.
  void setImportanceFilter(String? importance) {
    _filterImportance = importance;
    _articles = null;
    _currentOffset = 0;
    _safeNotify();
    loadArticles();
  }

  /// 주요 뉴스만 보기 모드를 토글한다.
  void toggleMajorNewsOnly() {
    _majorNewsOnly = !_majorNewsOnly;
    // 주요 뉴스 모드를 켜면 단일 impact 필터를 초기화한다.
    if (_majorNewsOnly) {
      _filterImpact = null;
    }
    _articles = null;
    _currentOffset = 0;
    _safeNotify();
    loadArticles();
  }

  /// 필터를 적용하고 기사 목록을 다시 로드한다.
  void setFilter({String? category, String? impact}) {
    _filterCategory = category;
    _filterImpact = impact;
    // impact 필터를 명시적으로 설정하면 주요 뉴스 모드를 해제한다.
    if (impact != null) {
      _majorNewsOnly = false;
    }
    _articles = null;
    _currentOffset = 0;
    _safeNotify();
    loadArticles();
  }

  /// 필터를 초기화하고 기사 목록을 다시 로드한다.
  void clearFilters() {
    _filterCategory = null;
    _filterImpact = null;
    _filterImportance = null;
    _majorNewsOnly = true;
    _articles = null;
    _currentOffset = 0;
    _safeNotify();
    loadArticles();
  }

  /// 에러 객체를 사용자 친화적 메시지로 변환한다.
  String _friendlyError(Object e) {
    final msg = e.toString();
    if (msg.contains('Future not completed') || msg.contains('TimeoutException')) {
      return '서버 응답 시간 초과. 잠시 후 다시 시도하세요.';
    }
    if (msg.contains('ServerUnreachable') || msg.contains('SocketException')) {
      return '서버에 연결할 수 없습니다.';
    }
    return msg;
  }

  /// 전체 데이터를 새로고침한다.
  Future<void> refresh() async {
    _dates = null;
    _summary = null;
    _articles = null;
    _selectedArticle = null;
    _selectedDate = null;
    _filterCategory = null;
    _filterImpact = null;
    _filterImportance = null;
    _majorNewsOnly = true;
    _currentOffset = 0;
    _total = 0;
    _error = null;
    await loadDates();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }

  /// dispose 이후 안전하게 notifyListeners를 호출한다.
  void _safeNotify() {
    if (!_disposed) notifyListeners();
  }
}
