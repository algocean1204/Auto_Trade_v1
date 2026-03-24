import 'dart:io';

import 'package:flutter/material.dart';
import '../models/setup_models.dart';
import '../services/server_launcher.dart';
import '../services/setup_service.dart';


/// 초기 설정 마법사의 전체 상태를 관리하는 프로바이더이다.
/// 8단계 위저드 진행, 서비스 검증 결과, 사용자 입력값을 통합 관리한다.
class SetupProvider with ChangeNotifier {
  final SetupService _service;

  SetupProvider(this._service);

  int _currentStep = 0;
  bool _isLoading = false;
  String? _error;
  SetupStatus? _status;
  ModelsStatus? _modelsStatus;
  final Map<String, SetupValidation> _validations = {};
  final Map<String, dynamic> _configData = {};

  /// 현재 검증 중인 서비스 키 집합이다.
  final Set<String> _validatingServices = {};

  /// 위저드 총 단계 수이다.
  static const int totalSteps = 8;

  int get currentStep => _currentStep;
  bool get isLoading => _isLoading;
  String? get error => _error;
  SetupStatus? get status => _status;
  ModelsStatus? get modelsStatus => _modelsStatus;
  Map<String, SetupValidation> get validations =>
      Map.unmodifiable(_validations);
  Map<String, dynamic> get configData => Map.unmodifiable(_configData);

  /// 특정 서비스가 검증 중인지 반환한다.
  bool isValidating(String key) => _validatingServices.contains(key);

  /// 모든 필수 설정이 완료되었는지 반환한다.
  bool get isSetupComplete => _status?.setupComplete ?? false;

  /// 전체 설정 상태를 서버에서 조회한다.
  Future<void> loadStatus() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _status = await _service.getStatus();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// MLX 모델 다운로드 상태를 서버에서 조회한다.
  Future<void> loadModelsStatus() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _modelsStatus = await _service.getModelsStatus();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 현재 저장된 설정값 (마스킹)이다.
  Map<String, String> _currentConfig = {};
  Map<String, String> get currentConfig => Map.unmodifiable(_currentConfig);

  /// .env 필드명 → 환경변수 키 매핑이다. 서버 없이 로컬에서 키를 읽을 때 사용한다.
  static const _envKeyMap = <String, String>{
    'kis_app_key': 'KIS_REAL_APP_KEY',
    'kis_app_secret': 'KIS_REAL_APP_SECRET',
    'kis_account_no': 'KIS_REAL_ACCOUNT',
    'kis_hts_id': 'KIS_HTS_ID',
    'kis_mock_app_key': 'KIS_VIRTUAL_APP_KEY',
    'kis_mock_app_secret': 'KIS_VIRTUAL_APP_SECRET',
    'kis_mock_account_no': 'KIS_VIRTUAL_ACCOUNT',
    'claude_mode': 'CLAUDE_MODE',
    'claude_api_key': 'ANTHROPIC_API_KEY',
    'telegram_bot_token': 'TELEGRAM_BOT_TOKEN',
    'telegram_chat_id': 'TELEGRAM_CHAT_ID',
    'telegram_bot_token_2': 'TELEGRAM_BOT_TOKEN_2',
    'telegram_chat_id_2': 'TELEGRAM_CHAT_ID_2',
    'telegram_bot_token_3': 'TELEGRAM_BOT_TOKEN_3',
    'telegram_chat_id_3': 'TELEGRAM_CHAT_ID_3',
    'telegram_bot_token_4': 'TELEGRAM_BOT_TOKEN_4',
    'telegram_chat_id_4': 'TELEGRAM_CHAT_ID_4',
    'telegram_bot_token_5': 'TELEGRAM_BOT_TOKEN_5',
    'telegram_chat_id_5': 'TELEGRAM_CHAT_ID_5',
    'fred_api_key': 'FRED_API_KEY',
    'finnhub_api_key': 'FINNHUB_API_KEY',
    'reddit_client_id': 'REDDIT_CLIENT_ID',
    'reddit_client_secret': 'REDDIT_CLIENT_SECRET',
  };

  /// 값의 앞 4자만 보여주고 나머지를 마스킹한다.
  static String _mask(String raw) {
    if (raw.length <= 4) return '****';
    return '${raw.substring(0, 4)}****';
  }

  /// 현재 저장된 API 키를 로드한다.
  /// 서버가 실행 중이면 API에서, 아니면 로컬 .env에서 읽는다.
  Future<void> loadCurrentConfig() async {
    try {
      _currentConfig = await _service.getCurrentConfig();
      notifyListeners();
      return;
    } catch (e) {
    }

    // 로컬 .env 파일에서 직접 읽어 마스킹하여 반환한다
    final envValues = _readEnvFileDirect();

    final local = <String, String>{};
    for (final entry in _envKeyMap.entries) {
      final raw = envValues[entry.value] ?? '';
      if (raw.isNotEmpty) {
        local[entry.key] = entry.key == 'claude_mode' ? raw : _mask(raw);
      }
    }
    // trading_mode도 읽는다
    final tradingMode = envValues['TRADING_MODE'] ?? '';
    if (tradingMode.isNotEmpty) {
      local['trading_mode'] = tradingMode;
    }
    _currentConfig = local;
    notifyListeners();
  }

  /// .env 파일을 직접 찾아서 파싱한다. EnvLoader 캐시와 무관하게 항상 최신 파일을 읽는다.
  ///
  /// 번들 모드에서는 ~/Library/Application Support/com.stocktrader.ai/.env를
  /// 최우선으로 탐색한다.
  static Map<String, String> _readEnvFileDirect() {
    final result = <String, String>{};
    File? envFile;

    // 0) ServerLauncher가 제공하는 경로를 최우선으로 확인한다.
    try {
      final launcherEnv = ServerLauncher.instance.envFilePath;
      if (launcherEnv != null) {
        final f = File(launcherEnv);
        if (f.existsSync()) envFile = f;
      }
    } catch (_) {}

    // 1) 번들 모드: Application Support 경로를 직접 확인한다.
    if (envFile == null) {
      try {
        final exePath = Platform.resolvedExecutable;
        if (exePath.contains('.app/Contents/MacOS/')) {
          final home = Platform.environment['HOME'] ?? '';
          if (home.isNotEmpty) {
            final f = File(
              '$home/Library/Application Support/com.stocktrader.ai/.env',
            );
            if (f.existsSync()) envFile = f;
          }
        }
      } catch (_) {}
    }

    // 2) 실행 파일 기준으로 상위 탐색
    if (envFile == null) {
      try {
        var dir = File(Platform.resolvedExecutable).parent;
        for (var i = 0; i < 12; i++) {
          final f = File('${dir.path}/.env');
          if (f.existsSync()) { envFile = f; break; }
          dir = dir.parent;
        }
      } catch (_) {}
    }

    // 3) CWD 기준으로 상위 탐색
    if (envFile == null) {
      try {
        var dir = Directory.current;
        for (var i = 0; i < 8; i++) {
          final f = File('${dir.path}/.env');
          if (f.existsSync()) { envFile = f; break; }
          dir = dir.parent;
        }
      } catch (_) {}
    }

    if (envFile == null) {
      return result;
    }

    try {
      for (final line in envFile.readAsLinesSync()) {
        final trimmed = line.trim();
        if (trimmed.isEmpty || trimmed.startsWith('#')) continue;
        final idx = trimmed.indexOf('=');
        if (idx <= 0) continue;
        final key = trimmed.substring(0, idx).trim();
        var value = trimmed.substring(idx + 1).trim();
        if (value.length >= 2 &&
            ((value.startsWith('"') && value.endsWith('"')) ||
                (value.startsWith("'") && value.endsWith("'")))) {
          value = value.substring(1, value.length - 1);
        }
        result[key] = value;
      }
    } catch (e) {
      // .env 파일 파싱 실패 시 디버그 출력한다 — UI에서 키가 '미설정'으로 표시된다
      debugPrint('[SetupProvider] .env 파싱 실패: $e');
    }
    return result;
  }

  /// 설정값을 누적 저장한다. 위저드 단계를 넘어가도 유지된다.
  void updateConfig(String key, dynamic value) {
    _configData[key] = value;
    notifyListeners();
  }

  /// 특정 서비스의 연결을 검증하고 결과를 캐시한다.
  ///
  /// [storeAs]를 지정하면 검증 결과를 해당 키로 저장한다.
  /// 같은 서비스(예: KIS)를 모의/실전 구분하여 저장할 때 사용한다.
  /// 검증 로딩 상태는 서비스별로 독립 관리한다 (글로벌 _isLoading 사용하지 않음).
  Future<bool> validateService(
    String service,
    Map<String, String> credentials, {
    String? storeAs,
  }) async {
    final key = storeAs ?? service;
    _validatingServices.add(key);
    _error = null;
    notifyListeners();

    try {
      final result = await _service.validateService(service, credentials);
      _validations[key] = result;
      _error = null;
      return result.valid;
    } catch (e) {
      _error = e.toString();
      _validations[key] = SetupValidation(
        service: service,
        valid: false,
        message: '서버 연결 실패: ${e.toString()}',
      );
      return false;
    } finally {
      _validatingServices.remove(key);
      notifyListeners();
    }
  }

  /// 누적된 모든 설정값을 서버에 저장한다.
  Future<bool> saveAllConfig() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final result = await _service.saveConfig(_configData);
      _error = null;
      return result.success;
    } catch (e) {
      _error = e.toString();
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 모델 다운로드를 시작한다. modelIds 미지정 시 전체 다운로드한다.
  Future<void> startDownload({List<String>? modelIds}) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _service.startModelDownload(modelIds: modelIds);
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 진행 중인 모델 다운로드를 취소한다.
  Future<void> cancelDownload() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _service.cancelModelDownload();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 다음 단계로 이동한다. 마지막 단계에서는 동작하지 않는다.
  void nextStep() {
    if (_currentStep < totalSteps - 1) {
      _currentStep++;
      notifyListeners();
    }
  }

  /// 이전 단계로 이동한다. 첫 단계에서는 동작하지 않는다.
  void previousStep() {
    if (_currentStep > 0) {
      _currentStep--;
      notifyListeners();
    }
  }

  /// 특정 단계로 직접 이동한다.
  void goToStep(int step) {
    if (step >= 0 && step < totalSteps) {
      _currentStep = step;
      notifyListeners();
    }
  }
}
