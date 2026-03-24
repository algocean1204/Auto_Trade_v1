// 초기 설정 마법사 관련 데이터 모델이다.

/// 개별 서비스(KIS, Claude, Telegram 등)의 설정 상태를 나타낸다.
class ServiceStatus {
  /// API 키 등 인증 정보가 설정되었는지 여부이다.
  final bool configured;

  /// 서비스 연결 테스트를 통과했는지 여부이다.
  final bool validated;

  /// 시스템 작동에 필수인 서비스인지 여부이다.
  final bool required;

  const ServiceStatus({
    required this.configured,
    required this.validated,
    required this.required,
  });

  factory ServiceStatus.fromJson(Map<String, dynamic> json) {
    return ServiceStatus(
      configured: json['configured'] as bool? ?? false,
      validated: json['validated'] as bool? ?? false,
      required: json['required'] as bool? ?? false,
    );
  }
}

/// MLX 모델 전체 다운로드 상태 요약이다.
class ModelSetupInfo {
  /// 모든 필수 모델이 다운로드 완료되었는지 여부이다.
  final bool allDownloaded;

  /// 다운로드 완료된 모델 수이다.
  final int downloadedCount;

  /// 전체 모델 수이다.
  final int totalCount;

  const ModelSetupInfo({
    required this.allDownloaded,
    required this.downloadedCount,
    required this.totalCount,
  });

  factory ModelSetupInfo.fromJson(Map<String, dynamic> json) {
    return ModelSetupInfo(
      allDownloaded: json['all_downloaded'] as bool? ?? false,
      downloadedCount: json['downloaded_count'] as int? ?? 0,
      totalCount: json['total_count'] as int? ?? 0,
    );
  }
}

/// 전체 초기 설정 진행 상태이다.
class SetupStatus {
  /// 모든 필수 서비스 설정 + 모델 다운로드가 완료되었는지이다.
  final bool setupComplete;

  /// 서비스별 설정 상태 맵 (예: "kis", "claude", "telegram").
  final Map<String, ServiceStatus> services;

  /// MLX 모델 설정 상태 요약이다.
  final ModelSetupInfo models;

  const SetupStatus({
    required this.setupComplete,
    required this.services,
    required this.models,
  });

  factory SetupStatus.fromJson(Map<String, dynamic> json) {
    final rawServices = json['services'] as Map<String, dynamic>? ?? {};
    final services = rawServices.map(
      (key, value) => MapEntry(
        key,
        ServiceStatus.fromJson(value as Map<String, dynamic>),
      ),
    );

    return SetupStatus(
      setupComplete: json['setup_complete'] as bool? ?? false,
      services: services,
      models: ModelSetupInfo.fromJson(
        json['models'] as Map<String, dynamic>? ?? {},
      ),
    );
  }
}

/// 설정 저장 결과이다.
class SetupConfigResult {
  /// 저장 성공 여부이다.
  final bool success;

  /// 결과 메시지이다.
  final String message;

  /// .env 파일이 저장된 경로이다.
  final String envPath;

  const SetupConfigResult({
    required this.success,
    required this.message,
    required this.envPath,
  });

  factory SetupConfigResult.fromJson(Map<String, dynamic> json) {
    return SetupConfigResult(
      success: json['success'] as bool? ?? false,
      message: json['message'] as String? ?? '',
      envPath: json['env_path'] as String? ?? '',
    );
  }
}

/// 서비스 연결 검증 결과이다.
class SetupValidation {
  /// 검증한 서비스 이름이다.
  final String service;

  /// 연결 테스트 통과 여부이다.
  final bool valid;

  /// 검증 결과 메시지이다.
  final String message;

  const SetupValidation({
    required this.service,
    required this.valid,
    required this.message,
  });

  factory SetupValidation.fromJson(Map<String, dynamic> json) {
    return SetupValidation(
      service: json['service'] as String? ?? '',
      valid: json['valid'] as bool? ?? false,
      message: json['message'] as String? ?? '',
    );
  }
}

/// 개별 MLX 모델 정보이다.
class ModelInfo {
  /// 모델 고유 식별자이다.
  final String modelId;

  /// 사용자에게 표시할 모델 이름이다.
  final String name;

  /// HuggingFace 레포지토리 ID이다.
  final String repoId;

  /// 모델 파일명이다.
  final String filename;

  /// 모델 파일 크기(GB)이다.
  final double sizeGb;

  /// 다운로드 완료 여부이다.
  final bool downloaded;

  /// 다운로드 진행률(0.0~1.0)이다. 다운로드 중이 아니면 null이다.
  final double? downloadProgress;

  const ModelInfo({
    required this.modelId,
    required this.name,
    required this.repoId,
    required this.filename,
    required this.sizeGb,
    required this.downloaded,
    this.downloadProgress,
  });

  factory ModelInfo.fromJson(Map<String, dynamic> json) {
    return ModelInfo(
      modelId: json['model_id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      repoId: json['repo_id'] as String? ?? '',
      filename: json['filename'] as String? ?? '',
      sizeGb: (json['size_gb'] as num? ?? 0).toDouble(),
      downloaded: json['downloaded'] as bool? ?? false,
      downloadProgress: (json['download_progress'] as num?)?.toDouble(),
    );
  }
}

/// 전체 모델 목록 및 상태이다.
class ModelsStatus {
  /// 개별 모델 정보 리스트이다.
  final List<ModelInfo> models;

  /// 전체 모델 합계 용량(GB)이다.
  final double totalSizeGb;

  /// 다운로드 완료된 모델 수이다.
  final int downloadedCount;

  /// 전체 모델 수이다.
  final int totalCount;

  const ModelsStatus({
    required this.models,
    required this.totalSizeGb,
    required this.downloadedCount,
    required this.totalCount,
  });

  factory ModelsStatus.fromJson(Map<String, dynamic> json) {
    final rawModels = json['models'] as List<dynamic>? ?? [];
    return ModelsStatus(
      models: rawModels
          .map((e) => ModelInfo.fromJson(e as Map<String, dynamic>))
          .toList(),
      totalSizeGb: (json['total_size_gb'] as num? ?? 0).toDouble(),
      downloadedCount: json['downloaded_count'] as int? ?? 0,
      totalCount: json['total_count'] as int? ?? 0,
    );
  }
}

/// 모델 다운로드 요청 결과이다.
class ModelDownloadResult {
  /// 작업 상태이다 (예: "started", "cancelled").
  final String status;

  /// 결과 메시지이다.
  final String message;

  const ModelDownloadResult({
    required this.status,
    required this.message,
  });

  factory ModelDownloadResult.fromJson(Map<String, dynamic> json) {
    return ModelDownloadResult(
      status: json['status'] as String? ?? '',
      message: json['message'] as String? ?? '',
    );
  }
}

// ── LaunchAgent 관련 모델 ──

/// 개별 LaunchAgent 상태 정보이다.
class LaunchAgentInfo {
  final String label;
  final bool installed;
  final bool loaded;
  final bool running;
  final int? pid;
  final int? lastExitCode;

  const LaunchAgentInfo({
    required this.label,
    required this.installed,
    required this.loaded,
    required this.running,
    this.pid,
    this.lastExitCode,
  });

  factory LaunchAgentInfo.fromJson(Map<String, dynamic> json) {
    return LaunchAgentInfo(
      label: json['label'] as String? ?? '',
      installed: json['installed'] as bool? ?? false,
      loaded: json['loaded'] as bool? ?? false,
      running: json['running'] as bool? ?? false,
      pid: json['pid'] as int?,
      lastExitCode: json['last_exit_code'] as int?,
    );
  }
}

/// LaunchAgent 전체 상태 응답이다.
class LaunchAgentFullStatus {
  final LaunchAgentInfo server;
  final LaunchAgentInfo autotrader;

  const LaunchAgentFullStatus({
    required this.server,
    required this.autotrader,
  });

  factory LaunchAgentFullStatus.fromJson(Map<String, dynamic> json) {
    return LaunchAgentFullStatus(
      server: LaunchAgentInfo.fromJson(
        json['server'] as Map<String, dynamic>? ?? {},
      ),
      autotrader: LaunchAgentInfo.fromJson(
        json['autotrader'] as Map<String, dynamic>? ?? {},
      ),
    );
  }
}

/// LaunchAgent 설치/제거 결과이다.
class LaunchAgentInstallResult {
  final bool success;
  final String message;
  final bool serverInstalled;
  final bool autotraderInstalled;

  const LaunchAgentInstallResult({
    required this.success,
    required this.message,
    required this.serverInstalled,
    required this.autotraderInstalled,
  });

  factory LaunchAgentInstallResult.fromJson(Map<String, dynamic> json) {
    return LaunchAgentInstallResult(
      success: json['success'] as bool? ?? false,
      message: json['message'] as String? ?? '',
      serverInstalled: json['server_installed'] as bool? ?? false,
      autotraderInstalled: json['autotrader_installed'] as bool? ?? false,
    );
  }
}

// ── 업데이트 확인 관련 모델 ──

/// 업데이트 확인 결과이다.
class UpdateCheckResult {
  final bool updateAvailable;
  final String currentVersion;
  final String latestVersion;
  final String downloadUrl;
  final String releaseNotes;

  const UpdateCheckResult({
    required this.updateAvailable,
    required this.currentVersion,
    required this.latestVersion,
    required this.downloadUrl,
    required this.releaseNotes,
  });

  factory UpdateCheckResult.fromJson(Map<String, dynamic> json) {
    return UpdateCheckResult(
      updateAvailable: json['update_available'] as bool? ?? false,
      currentVersion: json['current_version'] as String? ?? '',
      latestVersion: json['latest_version'] as String? ?? '',
      downloadUrl: json['download_url'] as String? ?? '',
      releaseNotes: json['release_notes'] as String? ?? '',
    );
  }
}

// ── 언인스톨 관련 모델 ──

/// 삭제 대상 항목 정보이다.
class UninstallItem {
  final String path;
  final String type;
  final String description;
  final bool exists;
  final int sizeBytes;
  final bool deletable;

  const UninstallItem({
    required this.path,
    required this.type,
    required this.description,
    required this.exists,
    required this.sizeBytes,
    required this.deletable,
  });

  factory UninstallItem.fromJson(Map<String, dynamic> json) {
    return UninstallItem(
      path: json['path'] as String? ?? '',
      type: json['type'] as String? ?? '',
      description: json['description'] as String? ?? '',
      exists: json['exists'] as bool? ?? false,
      sizeBytes: json['size_bytes'] as int? ?? 0,
      deletable: json['deletable'] as bool? ?? true,
    );
  }
}

/// 삭제 미리보기 응답이다.
class UninstallPreview {
  final List<UninstallItem> items;
  final int totalSizeBytes;
  final int existingCount;

  const UninstallPreview({
    required this.items,
    required this.totalSizeBytes,
    required this.existingCount,
  });

  factory UninstallPreview.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'] as List<dynamic>? ?? [];
    return UninstallPreview(
      items: rawItems
          .map((e) => UninstallItem.fromJson(e as Map<String, dynamic>))
          .toList(),
      totalSizeBytes: json['total_size_bytes'] as int? ?? 0,
      existingCount: json['existing_count'] as int? ?? 0,
    );
  }
}

/// 삭제 실행 결과이다.
class UninstallResult {
  final bool success;
  final String message;
  final bool keepData;
  final int deletedCount;

  const UninstallResult({
    required this.success,
    required this.message,
    required this.keepData,
    required this.deletedCount,
  });

  factory UninstallResult.fromJson(Map<String, dynamic> json) {
    return UninstallResult(
      success: json['success'] as bool? ?? false,
      message: json['message'] as String? ?? '',
      keepData: json['keep_data'] as bool? ?? false,
      deletedCount: json['deleted_count'] as int? ?? 0,
    );
  }
}
