import 'dart:async';
import 'package:flutter/foundation.dart';
import '../models/scalper_tape_models.dart';
import '../services/websocket_service.dart';

/// 스캘퍼 테이프 실시간 데이터 프로바이더이다.
/// WebSocket /ws/orderflow 엔드포인트를 통해 1초마다 데이터를 수신한다.
class ScalperTapeProvider extends ChangeNotifier {
  final WebSocketService _wsService;

  /// dispose 호출 여부를 추적하여 비동기 완료 후 notifyListeners 호출을 방지한다.
  bool _disposed = false;

  StreamSubscription<ScalperTapeData>? _subscription;

  ScalperTapeData? _currentData;
  String _selectedTicker = 'SOXL';
  bool _isConnected = false;
  String? _error;

  // 미니 차트용 히스토리 (최근 60개 = 60초 데이터)
  static const int _maxHistoryLength = 60;
  final List<double> _obiHistory = [];
  final List<double> _cvdHistory = [];
  final List<double> _vpinHistory = [];

  /// 지원 티커 목록이다.
  static const List<String> supportedTickers = [
    'SOXL',
    'QLD',
    'TQQQ',
    'UPRO',
    'LABU',
    'FNGU',
    'CURE',
    'NAIL',
    'DFEN',
    'FAS',
  ];

  ScalperTapeProvider(this._wsService);

  // ── Getters ──

  ScalperTapeData? get currentData => _currentData;
  String get selectedTicker => _selectedTicker;
  bool get isConnected => _isConnected;
  String? get error => _error;
  List<double> get obiHistory => List.unmodifiable(_obiHistory);
  List<double> get cvdHistory => List.unmodifiable(_cvdHistory);
  List<double> get vpinHistory => List.unmodifiable(_vpinHistory);

  // ── 티커 전환 ──

  /// 티커를 전환하고 WebSocket을 재연결한다.
  void selectTicker(String ticker) {
    if (_selectedTicker == ticker) return;

    // 기존 연결 해제
    _subscription?.cancel();
    _subscription = null;
    _wsService.disconnectEndpoint('/ws/orderflow');

    _selectedTicker = ticker;
    _clearHistory();
    _currentData = null;
    _isConnected = false;
    _error = null;

    _safeNotify();
    connect();
  }

  // ── WebSocket 연결 관리 ──

  /// WebSocket 연결을 시작한다.
  void connect() {
    if (_subscription != null) {
      _subscription?.cancel();
      _subscription = null;
    }
    _error = null;

    try {
      final stream = _wsService.getScalperTapeStream(_selectedTicker);

      _subscription = stream.listen(
        _onData,
        onError: (Object error) {
          _isConnected = false;
          _error = error.toString();
          _safeNotify();
        },
        onDone: () {
          _isConnected = false;
          _safeNotify();
        },
        cancelOnError: false,
      );

      // 연결 시작 직후에는 낙관적으로 connected 표시한다.
      // 실제 첫 데이터 수신 시 _onData에서 확정한다.
      _isConnected = true;
      _safeNotify();
    } catch (e) {
      _isConnected = false;
      _error = e.toString();
      _safeNotify();
    }
  }

  /// WebSocket 연결을 종료한다.
  void disconnect() {
    _subscription?.cancel();
    _subscription = null;
    _wsService.disconnectEndpoint('/ws/orderflow');
    _isConnected = false;
    _safeNotify();
  }

  // ── 데이터 처리 ──

  void _onData(ScalperTapeData data) {
    // 선택된 티커와 일치하지 않는 데이터는 무시한다
    if (data.ticker.isNotEmpty && data.ticker != _selectedTicker) {
      return;
    }

    _currentData = data;
    _isConnected = true;
    _error = null;

    // 히스토리 갱신
    if (data.obi != null) {
      _appendHistory(_obiHistory, data.obi!.smoothed);
    }
    if (data.cvd != null) {
      _appendHistory(_cvdHistory, data.cvd!.cumulative);
    }
    if (data.vpin != null) {
      _appendHistory(_vpinHistory, data.vpin!.value);
    }

    _safeNotify();
  }

  void _appendHistory(List<double> history, double value) {
    history.add(value);
    if (history.length > _maxHistoryLength) {
      history.removeAt(0);
    }
  }

  void _clearHistory() {
    _obiHistory.clear();
    _cvdHistory.clear();
    _vpinHistory.clear();
  }

  @override
  void dispose() {
    _disposed = true;
    _subscription?.cancel();
    _subscription = null;
    // WebSocket 채널도 함께 정리하여 리소스 누수를 방지한다.
    _wsService.disconnectEndpoint('/ws/orderflow');
    super.dispose();
  }

  /// dispose 이후 안전하게 notifyListeners를 호출한다.
  void _safeNotify() {
    if (!_disposed) notifyListeners();
  }
}
