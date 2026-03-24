import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../models/setup_models.dart';
import '../utils/env_loader.dart';
import 'server_launcher.dart';
import 'api_service.dart';

/// 초기 설정 마법사에서 사용하는 6개 Setup API 엔드포인트 HTTP 클라이언트이다.
///
/// ApiService와 동일한 패턴으로 네트워크 오류를 ServerUnreachableException으로 변환한다.
class SetupService {
  final String baseUrl;

  /// 인증용 API 키이다. API_SECRET_KEY가 설정되어 있으면 Authorization 헤더에 포함한다.
  final String apiKey;

  /// 일반 HTTP 요청에 적용되는 타임아웃이다.
  static const _timeout = Duration(seconds: 15);

  /// 검증 요청은 외부 API 호출을 포함하므로 더 긴 타임아웃을 적용한다.
  static const _validateTimeout = Duration(seconds: 30);

  /// 설정 저장은 .env 쓰기 + vault 리로드 + 시스템 재초기화를 포함하므로 충분한 타임아웃이 필요하다.
  static const _saveTimeout = Duration(seconds: 45);

  SetupService({String? baseUrl, String? apiKey})
      : baseUrl = baseUrl ?? ServerLauncher.instance.baseUrl,
        apiKey = apiKey ?? EnvLoader.get('API_SECRET_KEY');

  /// 공통 요청 헤더를 생성한다. API 키가 설정되어 있으면 Bearer 토큰을 포함한다.
  Map<String, String> _headers({bool withJson = false}) {
    final h = <String, String>{};
    if (withJson) h['Content-Type'] = 'application/json';
    if (apiKey.isNotEmpty) h['Authorization'] = 'Bearer $apiKey';
    return h;
  }

  /// 네트워크 레벨 예외를 ServerUnreachableException으로 변환한다.
  Never _wrapNetworkError(Object e, StackTrace st) {
    if (e is SocketException || e is HandshakeException) {
      throw ServerUnreachableException(e.toString());
    }
    final msg = e.toString();
    if (msg.contains('TimeoutException') ||
        msg.contains('Connection refused')) {
      throw ServerUnreachableException(msg);
    }
    Error.throwWithStackTrace(e, st);
  }

  /// GET 요청 공통 헬퍼이다.
  Future<T> _get<T>(
    String endpoint,
    T Function(dynamic) fromJson,
  ) async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl$endpoint'), headers: _headers())
          .timeout(_timeout);

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        return fromJson(data);
      } else {
        throw Exception('GET $endpoint failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError(e, st);
      }
      rethrow;
    }
  }

  /// POST 요청 공통 헬퍼이다.
  Future<T> _post<T>(
    String endpoint,
    Map<String, dynamic> body,
    T Function(dynamic) fromJson,
  ) async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl$endpoint'),
            headers: _headers(withJson: true),
            body: json.encode(body),
          )
          .timeout(_timeout);

      if (response.statusCode == 200 || response.statusCode == 201) {
        final data = json.decode(response.body);
        return fromJson(data);
      } else {
        throw Exception('POST $endpoint failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError(e, st);
      }
      rethrow;
    }
  }

  // ── Setup API 엔드포인트 ──

  /// 전체 초기 설정 진행 상태를 조회한다.
  Future<SetupStatus> getStatus() {
    return _get(
      '/api/setup/status',
      (data) => SetupStatus.fromJson(data as Map<String, dynamic>),
    );
  }

  /// 현재 저장된 API 키를 마스킹하여 조회한다.
  Future<Map<String, String>> getCurrentConfig() {
    return _get(
      '/api/setup/config/current',
      (data) {
        final raw = (data as Map<String, dynamic>)['keys'] as Map<String, dynamic>? ?? {};
        return raw.map((k, v) => MapEntry(k, v as String? ?? ''));
      },
    );
  }

  /// 모든 API 키와 설정값을 서버에 저장한다.
  /// 시스템 재초기화를 포함하므로 _saveTimeout을 사용한다.
  Future<SetupConfigResult> saveConfig(Map<String, dynamic> config) async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl/api/setup/config'),
            headers: _headers(withJson: true),
            body: json.encode(config),
          )
          .timeout(_saveTimeout);

      if (response.statusCode == 200 || response.statusCode == 201) {
        final data = json.decode(response.body);
        return SetupConfigResult.fromJson(data as Map<String, dynamic>);
      } else {
        throw Exception('POST /api/setup/config failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError(e, st);
      }
      rethrow;
    }
  }

  /// 특정 서비스의 연결을 검증한다.
  /// 외부 API 호출을 포함하므로 _validateTimeout을 사용한다.
  Future<SetupValidation> validateService(
    String service,
    Map<String, String> credentials,
  ) async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl/api/setup/validate/$service'),
            headers: _headers(withJson: true),
            body: json.encode(credentials),
          )
          .timeout(_validateTimeout);

      if (response.statusCode == 200 || response.statusCode == 201) {
        final data = json.decode(response.body);
        return SetupValidation.fromJson(data as Map<String, dynamic>);
      } else {
        throw Exception(
            'POST /api/setup/validate/$service failed: ${response.statusCode}');
      }
    } catch (e, st) {
      if (e is Exception && e is! ServerUnreachableException) {
        _wrapNetworkError(e, st);
      }
      rethrow;
    }
  }

  /// MLX 모델 다운로드 상태 목록을 조회한다.
  Future<ModelsStatus> getModelsStatus() {
    return _get(
      '/api/setup/models',
      (data) => ModelsStatus.fromJson(data as Map<String, dynamic>),
    );
  }

  /// 모델 다운로드를 시작한다. modelIds를 지정하면 해당 모델만 다운로드한다.
  Future<ModelDownloadResult> startModelDownload({List<String>? modelIds}) {
    final body = <String, dynamic>{};
    if (modelIds != null) body['model_ids'] = modelIds;
    return _post(
      '/api/setup/models/download',
      body,
      (data) => ModelDownloadResult.fromJson(data as Map<String, dynamic>),
    );
  }

  /// 진행 중인 모델 다운로드를 취소한다.
  Future<ModelDownloadResult> cancelModelDownload() {
    return _post(
      '/api/setup/models/cancel',
      {},
      (data) => ModelDownloadResult.fromJson(data as Map<String, dynamic>),
    );
  }

  // ── LaunchAgent API 엔드포인트 ──

  /// LaunchAgent를 설치한다.
  Future<LaunchAgentInstallResult> installLaunchAgents({String? appPath}) {
    final body = <String, dynamic>{};
    if (appPath != null) body['app_path'] = appPath;
    return _post(
      '/api/setup/launchagent/install',
      body,
      (data) =>
          LaunchAgentInstallResult.fromJson(data as Map<String, dynamic>),
    );
  }

  /// LaunchAgent를 삭제한다.
  Future<LaunchAgentInstallResult> uninstallLaunchAgents() {
    return _post(
      '/api/setup/launchagent/uninstall',
      {},
      (data) =>
          LaunchAgentInstallResult.fromJson(data as Map<String, dynamic>),
    );
  }

  /// LaunchAgent 상태를 조회한다.
  Future<LaunchAgentFullStatus> getLaunchAgentStatus() {
    return _get(
      '/api/setup/launchagent/status',
      (data) =>
          LaunchAgentFullStatus.fromJson(data as Map<String, dynamic>),
    );
  }

  // ── 업데이트 확인 API ──

  /// 새 버전이 있는지 확인한다.
  Future<UpdateCheckResult> checkForUpdates() {
    return _get(
      '/api/setup/update/check',
      (data) => UpdateCheckResult.fromJson(data as Map<String, dynamic>),
    );
  }

  // ── 언인스톨 API ──

  /// 삭제될 항목 미리보기를 조회한다.
  Future<UninstallPreview> getUninstallPreview() {
    return _get(
      '/api/setup/uninstall/preview',
      (data) => UninstallPreview.fromJson(data as Map<String, dynamic>),
    );
  }

  /// 완전 삭제를 실행한다.
  Future<UninstallResult> runUninstall({bool keepData = false}) {
    return _post(
      '/api/setup/uninstall',
      {'keep_data': keepData},
      (data) => UninstallResult.fromJson(data as Map<String, dynamic>),
    );
  }
}
