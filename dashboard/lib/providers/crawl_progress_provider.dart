import 'dart:async';
import 'package:flutter/material.dart';
import '../models/dashboard_models.dart';
import '../services/api_service.dart';
import '../services/websocket_service.dart';

/// 크롤링 진행 상태를 관리하는 프로바이더이다.
/// 폴링(1초 간격)을 기본으로 사용하고, WebSocket을 보조로 활용한다.
class CrawlProgressProvider with ChangeNotifier {
  final ApiService _api;
  final WebSocketService _ws;

  // ── 상태 ──

  bool _isCrawling = false;
  String? _taskId;
  List<CrawlProgress> _crawlerStatuses = [];
  CrawlSummary? _summary;
  double _progress = 0.0;
  String? _error;
  DateTime? _lastCrawlTime;
  int _lastArticleCount = 0;

  // ── 내부 타이머 / 구독 ──

  Timer? _pollingTimer;
  StreamSubscription<CrawlProgress>? _wsSub;

  CrawlProgressProvider(this._api, this._ws);

  // ── Getters ──

  bool get isCrawling => _isCrawling;
  String? get taskId => _taskId;
  List<CrawlProgress> get crawlerStatuses =>
      List.unmodifiable(_crawlerStatuses);
  CrawlSummary? get summary => _summary;
  double get progress => _progress;
  String? get error => _error;
  DateTime? get lastCrawlTime => _lastCrawlTime;
  int get lastArticleCount => _lastArticleCount;

  // ── Actions ──

  /// 수동 크롤링을 시작한다.
  /// POST /crawl/manual 호출 후 폴링과 WebSocket을 병행한다.
  Future<void> startCrawl() async {
    if (_isCrawling) return;

    _isCrawling = true;
    _crawlerStatuses = [];
    _summary = null;
    _progress = 0.0;
    _error = null;
    notifyListeners();

    try {
      final result = await _api.startManualCrawl();
      _taskId = result.taskId;

      // WebSocket 연결을 시도한다 (실패해도 폴링으로 대체된다)
      _startWebSocket();

      // 폴링을 시작한다 (1.5초 간격)
      _startPolling();
    } catch (e) {
      _isCrawling = false;
      _error = e.toString();
      notifyListeners();
    }
  }

  /// 크롤링을 강제 중단하고 상태를 초기화한다.
  void reset() {
    _stopPolling();
    _stopWebSocket();
    _isCrawling = false;
    _taskId = null;
    _crawlerStatuses = [];
    _summary = null;
    _progress = 0.0;
    _error = null;
    notifyListeners();
  }

  // ── 폴링 ──

  void _startPolling() {
    _stopPolling();
    _pollingTimer =
        Timer.periodic(const Duration(milliseconds: 1500), (_) async {
      await _pollStatus();
    });
  }

  void _stopPolling() {
    _pollingTimer?.cancel();
    _pollingTimer = null;
  }

  Future<void> _pollStatus() async {
    final taskId = _taskId;
    if (taskId == null || !_isCrawling) return;

    try {
      final status = await _api.getCrawlStatus(taskId);
      _applyStatusUpdate(status);
    } catch (_) {
      // 폴링 실패는 조용히 무시한다
    }
  }

  /// GET /crawl/status/{taskId} 응답을 파싱하여 상태를 갱신한다.
  /// 백엔드 CrawlDetailedStatusResponse 형식을 처리한다.
  void _applyStatusUpdate(CrawlStatus status) {
    // 크롤러 상태 목록을 갱신한다 (CrawlStatus에 이미 파싱되어 있음)
    for (final crawlerStatus in status.crawlerStatuses) {
      _upsertCrawler(crawlerStatus);
    }

    // 진행률을 백엔드 progress_pct로 업데이트한다 (0.0~1.0 범위로 변환)
    if (status.progressPct > 0 || status.totalCrawlers > 0) {
      _progress = (status.progressPct / 100.0).clamp(0.0, 1.0);
    } else {
      _recalcProgress(
        status.totalCrawlers > 0 ? status.totalCrawlers : null,
      );
    }

    // 완료 처리 (completed 상태)
    if (status.status == 'completed') {
      final data = status.data;
      if (data != null && data.containsKey('total_articles')) {
        _summary = CrawlSummary.fromJson(data);
      }
      _finishCrawling();
      return;
    }

    // 실패 처리
    if (status.status == 'failed') {
      _isCrawling = false;
      _error = status.data?['error'] as String? ?? 'Crawl failed';
      _stopPolling();
      _stopWebSocket();
      notifyListeners();
      return;
    }

    notifyListeners();
  }

  // ── WebSocket ──

  void _startWebSocket() {
    if (_taskId == null) return;
    _stopWebSocket();

    try {
      _wsSub = _ws.getCrawlProgress(_taskId ?? '').listen(
        (event) => _handleWsEvent(event),
        onDone: () {
          // WebSocket이 닫히면 폴링으로 계속한다
        },
        onError: (_) {
          // WebSocket 오류는 무시한다 (폴링이 대체한다)
        },
      );
    } catch (_) {
      // WebSocket 연결 실패는 무시한다
    }
  }

  void _stopWebSocket() {
    _wsSub?.cancel();
    _wsSub = null;
  }

  void _handleWsEvent(CrawlProgress event) {
    if (!_isCrawling) return;

    switch (event.type) {
      case 'crawler_start':
        _upsertCrawler(event.copyWith(status: 'running'));
        break;
      case 'crawler_done':
        _upsertCrawler(event.copyWith(
          status: event.status.isEmpty ? 'completed' : event.status,
        ));
        break;
      case 'crawl_summary':
        // summary 이벤트가 오면 완료 처리한다.
        // rawJson에 total_articles, unique_articles 등 전체 필드가 포함되어 있다.
        final summaryData = event.rawJson ?? <String, dynamic>{
          'total_articles': event.articleCount,
          'unique_articles': 0,
          'saved_articles': 0,
          'duplicates_removed': 0,
          'duration_seconds': 0,
          'crawler_results': _crawlerStatuses.map(_crawlerToJson).toList(),
        };
        _summary = CrawlSummary.fromJson(summaryData);
        _finishCrawling();
        return;
      default:
        _upsertCrawler(event);
    }

    _recalcProgress(event.totalCrawlers);
    notifyListeners();
  }

  // ── 헬퍼 ──

  /// 크롤러 목록에서 동일 이름을 찾아 갱신하거나, 없으면 추가한다.
  void _upsertCrawler(CrawlProgress updated) {
    final idx = _crawlerStatuses.indexWhere(
      (c) => c.source == updated.source,
    );
    if (idx >= 0) {
      _crawlerStatuses[idx] = updated;
    } else {
      _crawlerStatuses.add(updated);
    }
  }

  /// 완료된 크롤러 수 / 전체 크롤러 수로 진행률을 재계산한다.
  void _recalcProgress(int? totalCrawlers) {
    final total = totalCrawlers ?? _crawlerStatuses.length;
    if (total == 0) return;

    final done = _crawlerStatuses
        .where((c) =>
            c.status.toLowerCase() == 'completed' ||
            c.status.toLowerCase() == 'failed' ||
            c.status.toLowerCase() == 'done')
        .length;
    _progress = done / total;
  }

  /// 크롤링 완료 처리를 수행한다.
  void _finishCrawling() {
    _stopPolling();
    _stopWebSocket();

    _isCrawling = false;
    _lastCrawlTime = DateTime.now();

    // 최종 기사 수를 계산한다
    final summary = _summary;
    if (summary != null) {
      _lastArticleCount = summary.totalArticles;
    } else {
      _lastArticleCount =
          _crawlerStatuses.fold(0, (sum, c) => sum + c.articleCount);
    }

    // 진행률을 100%로 설정한다
    _progress = 1.0;

    notifyListeners();
  }

  /// CrawlProgress를 요약용 JSON으로 변환한다.
  Map<String, dynamic> _crawlerToJson(CrawlProgress c) {
    return {
      'name': c.source,
      'count': c.articleCount,
      'status': c.status,
    };
  }

  @override
  void dispose() {
    _stopPolling();
    _stopWebSocket();
    super.dispose();
  }
}
