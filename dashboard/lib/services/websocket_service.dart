import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../models/trade_models.dart';
import '../models/dashboard_models.dart';
import '../models/scalper_tape_models.dart';
import '../constants/api_constants.dart';
import 'server_launcher.dart';
import '../utils/env_loader.dart';

// WebSocket 연결 상태를 나타낸다.
enum WsConnectionState { disconnected, connecting, connected, error }

/// V2 WebSocket 서비스이다.
/// V2 백엔드의 채널 형식: ws://host:8000/ws/{channel}
/// 지원 채널: dashboard, positions, trades, alerts, orderflow
class WebSocketService {
  String baseUrl;

  // 엔드포인트별 독립 채널 맵 (공유 채널 버그 수정)
  final Map<String, WebSocketChannel?> _channels = {};
  final Map<String, StreamController> _controllers = {};
  final Map<String, int> _reconnectAttempts = {};
  final Map<String, WsConnectionState> _connectionStates = {};

  /// 채널별 StreamSubscription을 관리하여 재연결 시 이전 listener를 cancel한다.
  /// 이를 통해 listener 오버랩(중복 구독)을 방지한다.
  final Map<String, StreamSubscription> _subscriptions = {};

  WebSocketService({String? baseUrl})
      : baseUrl = baseUrl ?? ServerLauncher.instance.wsBaseUrl;

  /// ServerLauncher가 감지한 포트로 baseUrl을 갱신한다.
  void refreshBaseUrl() {
    final detected = ServerLauncher.instance.wsBaseUrl;
    if (detected != baseUrl) {
      baseUrl = detected;
    }
  }

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

    // 기존 subscription이 있으면 cancel하여 listener 중복을 방지한다
    _subscriptions[endpoint]?.cancel();
    _subscriptions.remove(endpoint);

    _connectionStates[endpoint] = WsConnectionState.connecting;

    try {
      // 엔드포인트마다 독립 채널을 생성한다
      final apiKey = EnvLoader.get('API_SECRET_KEY');
      final sep = endpoint.contains('?') ? '&' : '?';
      final wsUrl = apiKey.isNotEmpty
          ? '$baseUrl$endpoint${sep}token=$apiKey'
          : '$baseUrl$endpoint';
      final channel = WebSocketChannel.connect(Uri.parse(wsUrl));
      _channels[endpoint] = channel;
      _connectionStates[endpoint] = WsConnectionState.connected;
      _reconnectAttempts[endpoint] = 0;

      final subscription = channel.stream.listen(
        (message) {
          try {
            final decoded = json.decode(message as String);

            // 백엔드가 에러 메시지를 전송한 경우 무시한다
            // {"error": "시스템 초기화 중"} 또는 {"channel": "...", "error": "..."} 형식
            if (decoded is Map && decoded.containsKey('error') && !decoded.containsKey('data')) {
              return;
            }

            // 백엔드 응답 래퍼 처리: {channel: "xxx", data: [...], count: N} 형식인 경우
            // data 필드를 추출하고, 래퍼가 없으면 원본을 그대로 사용한다
            final payload = (decoded is Map && decoded.containsKey('data'))
                ? decoded['data']  // 래핑된 응답: data 필드 추출
                : decoded;         // 래핑 없는 응답: 직접 사용

            // data가 null이면 아직 데이터가 없는 상태이므로 무시한다
            if (payload == null) return;

            if (!controller.isClosed) {
              if (payload is List) {
                // 리스트 페이로드: 각 항목을 개별 모델로 변환하여 emit 한다
                for (final item in payload) {
                  if (item is Map<String, dynamic>) {
                    controller.add(fromJson(item));
                  }
                }
              } else if (payload is Map<String, dynamic>) {
                // 단일 객체 페이로드: 그대로 변환한다
                controller.add(fromJson(payload));
              }
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
      // subscription을 맵에 저장하여 재연결 시 cancel할 수 있게 한다
      _subscriptions[endpoint] = subscription;
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
    // 기존 subscription을 먼저 cancel하여 listener 중복을 방지한다
    _subscriptions[endpoint]?.cancel();
    _subscriptions.remove(endpoint);

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
    // 모든 subscription을 cancel하여 listener 누수를 방지한다
    for (final sub in _subscriptions.values) {
      sub.cancel();
    }
    _subscriptions.clear();

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
