import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../models/trade_models.dart';
import '../models/dashboard_models.dart';
import '../models/scalper_tape_models.dart';
import '../constants/api_constants.dart';

// WebSocket 연결 상태를 나타낸다.
enum WsConnectionState { disconnected, connecting, connected, error }

/// V2 WebSocket 서비스이다.
/// V2 백엔드의 채널 형식: ws://host:8000/ws/{channel}
/// 지원 채널: dashboard, positions, trades, alerts, orderflow
class WebSocketService {
  final String baseUrl;

  // 엔드포인트별 독립 채널 맵 (공유 채널 버그 수정)
  final Map<String, WebSocketChannel?> _channels = {};
  final Map<String, StreamController> _controllers = {};
  final Map<String, int> _reconnectAttempts = {};
  final Map<String, WsConnectionState> _connectionStates = {};

  WebSocketService({this.baseUrl = 'ws://localhost:9501'});

  // 지수 백오프 딜레이를 계산한다 (1s, 2s, 4s, 8s, 16s, max 30s)
  Duration _backoffDelay(String endpoint) {
    final attempts = _reconnectAttempts[endpoint] ?? 0;
    final seconds = (1 << attempts).clamp(1, 30);
    return Duration(seconds: seconds);
  }

  Stream<T> _getStream<T>(
    String endpoint,
    T Function(Map<String, dynamic>) fromJson,
  ) {
    final existingController = _controllers[endpoint];
    if (existingController != null && !existingController.isClosed) {
      return existingController.stream as Stream<T>;
    }

    late final StreamController<T> controller;
    controller = StreamController<T>.broadcast(
      onListen: () {
        _reconnectAttempts[endpoint] = 0;
        _connect(endpoint, fromJson, controller);
      },
      onCancel: () => _disconnect(endpoint),
    );

    _controllers[endpoint] = controller;
    return controller.stream;
  }

  void _connect<T>(
    String endpoint,
    T Function(Map<String, dynamic>) fromJson,
    StreamController<T> controller,
  ) {
    if (controller.isClosed) return;

    _connectionStates[endpoint] = WsConnectionState.connecting;

    try {
      // 엔드포인트마다 독립 채널을 생성한다
      final channel = WebSocketChannel.connect(Uri.parse('$baseUrl$endpoint'));
      _channels[endpoint] = channel;
      _connectionStates[endpoint] = WsConnectionState.connected;
      _reconnectAttempts[endpoint] = 0;

      channel.stream.listen(
        (message) {
          try {
            final data = json.decode(message as String) as Map<String, dynamic>;
            if (!controller.isClosed) {
              controller.add(fromJson(data));
            }
          } catch (e) {
            if (!controller.isClosed) {
              controller.addError('Failed to parse WebSocket message: $e');
            }
          }
        },
        onError: (error) {
          _connectionStates[endpoint] = WsConnectionState.error;
          if (!controller.isClosed) {
            controller.addError(error);
          }
          _scheduleReconnect(endpoint, fromJson, controller);
        },
        onDone: () {
          _connectionStates[endpoint] = WsConnectionState.disconnected;
          _scheduleReconnect(endpoint, fromJson, controller);
        },
        cancelOnError: false,
      );
    } catch (e) {
      _connectionStates[endpoint] = WsConnectionState.error;
      if (!controller.isClosed) {
        controller.addError('Failed to connect WebSocket: $e');
      }
      _scheduleReconnect(endpoint, fromJson, controller);
    }
  }

  void _scheduleReconnect<T>(
    String endpoint,
    T Function(Map<String, dynamic>) fromJson,
    StreamController<T> controller,
  ) {
    if (controller.isClosed) return;

    final attempts = _reconnectAttempts[endpoint] ?? 0;
    _reconnectAttempts[endpoint] = attempts + 1;
    final delay = _backoffDelay(endpoint);

    Future.delayed(delay, () {
      if (!controller.isClosed) {
        _connect(endpoint, fromJson, controller);
      }
    });
  }

  void _disconnect(String endpoint) {
    _channels[endpoint]?.sink.close();
    _channels.remove(endpoint);
    _connectionStates[endpoint] = WsConnectionState.disconnected;
    _reconnectAttempts.remove(endpoint);

    final controller = _controllers[endpoint];
    if (controller != null && !controller.isClosed) {
      controller.close();
    }
    _controllers.remove(endpoint);
  }

  // 연결 상태를 조회한다
  WsConnectionState getConnectionState(String endpoint) {
    return _connectionStates[endpoint] ?? WsConnectionState.disconnected;
  }

  // ── 스트림 공개 API ──

  /// 포지션 실시간 업데이트 스트림을 반환한다.
  /// V2 채널: ws://host:8000/ws/positions
  Stream<Position> getPositionUpdates() {
    return _getStream(
      '/ws/${ApiConstants.wsPositions}',
      (data) => Position.fromJson(data),
    );
  }

  /// 체결 내역 실시간 업데이트 스트림을 반환한다.
  /// V2 채널: ws://host:8000/ws/trades
  Stream<Trade> getTradeUpdates() {
    return _getStream(
      '/ws/${ApiConstants.wsTrades}',
      (data) => Trade.fromJson(data),
    );
  }

  /// 크롤 진행 상황 스트림을 반환한다.
  /// TODO(v2): V2 백엔드에 /ws/crawl/{taskId} 채널이 없다.
  /// 뉴스 수집 진행 상황은 POST /api/news/collect-and-send 응답으로 처리한다.
  /// 하위 호환성을 위해 메서드를 유지하며, 연결 시도는 그대로 수행한다.
  Stream<CrawlProgress> getCrawlProgress(String taskId) {
    // 백엔드 WebSocket은 {"type": "crawl_progress", "data": {...이벤트...}} 형식으로 전송한다.
    // 실제 이벤트 데이터가 'data' 키 안에 있으므로 언래핑한다.
    return _getStream('/ws/crawl/$taskId', (raw) {
      final inner = raw['data'] as Map<String, dynamic>? ?? raw;
      return CrawlProgress.fromJson(inner);
    });
  }

  /// 알림 실시간 스트림을 반환한다.
  /// V2 채널: ws://host:8000/ws/alerts
  Stream<AlertNotification> getAlertUpdates() {
    return _getStream(
      '/ws/${ApiConstants.wsAlerts}',
      (data) => AlertNotification.fromJson(data),
    );
  }

  /// 오더플로우(스캘퍼 테이프) 실시간 데이터 스트림을 반환한다.
  /// V2 채널: ws://host:8000/ws/orderflow
  /// [ticker] 파라미터는 orderflow 채널 연결 후 메시지 필터링에 사용된다.
  /// V1의 /ws/realtime-tape/{ticker} 가 V2의 /ws/orderflow 로 통합되었다.
  Stream<ScalperTapeData> getScalperTapeStream(String ticker) {
    // V2는 단일 orderflow 채널에서 모든 티커 데이터를 스트리밍한다.
    // ticker 파라미터는 채널 경로에 포함되지 않으므로 클라이언트에서 필터링이 필요하다.
    return _getStream(
      '/ws/${ApiConstants.wsOrderflow}',
      (data) => ScalperTapeData.fromJson(data),
    );
  }

  /// 특정 엔드포인트의 WebSocket 연결을 명시적으로 해제한다.
  /// ScalperTapeProvider에서 티커 전환 시 이전 연결을 닫기 위해 사용한다.
  void disconnectEndpoint(String endpoint) {
    _disconnect(endpoint);
  }

  void dispose() {
    for (final endpoint in _channels.keys.toList()) {
      _channels[endpoint]?.sink.close();
    }
    _channels.clear();

    for (final controller in _controllers.values) {
      if (!controller.isClosed) controller.close();
    }
    _controllers.clear();
    _reconnectAttempts.clear();
    _connectionStates.clear();
  }
}
