import 'package:flutter/material.dart';
import '../theme/domain_colors.dart';

/// 매매 원칙 전체 응답 모델이다.
class TradingPrinciples {
  final String corePrinciple;
  final List<TradingPrinciple> principles;

  TradingPrinciples({
    required this.corePrinciple,
    required this.principles,
  });

  factory TradingPrinciples.fromJson(Map<String, dynamic> json) {
    final rawList = json['principles'] as List<dynamic>? ?? [];
    return TradingPrinciples(
      corePrinciple: json['core_principle'] as String? ?? '',
      principles: rawList
          .map((e) => TradingPrinciple.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

/// 개별 매매 원칙 모델이다.
class TradingPrinciple {
  final String id;
  final String category; // survival, risk, strategy, execution, mindset, custom
  final String title;
  final String content;
  final int priority;
  final bool isSystem; // 시스템 원칙은 삭제할 수 없다
  final bool enabled;
  final DateTime? createdAt;

  TradingPrinciple({
    required this.id,
    required this.category,
    required this.title,
    required this.content,
    required this.priority,
    required this.isSystem,
    required this.enabled,
    this.createdAt,
  });

  factory TradingPrinciple.fromJson(Map<String, dynamic> json) {
    DateTime? parsedDate;
    final rawDate = json['created_at'];
    if (rawDate != null && rawDate is String) {
      parsedDate = DateTime.tryParse(rawDate);
    }
    return TradingPrinciple(
      id: json['id'] as String? ?? '',
      category: json['category'] as String? ?? 'custom',
      title: json['title'] as String? ?? '',
      content: json['content'] as String? ?? '',
      priority: (json['priority'] as num? ?? 0).toInt(),
      isSystem: json['is_system'] as bool? ?? false,
      enabled: json['enabled'] as bool? ?? true,
      createdAt: parsedDate,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'category': category,
      'title': title,
      'content': content,
      'priority': priority,
      'is_system': isSystem,
      'enabled': enabled,
      if (createdAt != null) 'created_at': createdAt?.toIso8601String(),
    };
  }

  TradingPrinciple copyWith({
    String? category,
    String? title,
    String? content,
    int? priority,
    bool? isSystem,
    bool? enabled,
  }) {
    return TradingPrinciple(
      id: id,
      category: category ?? this.category,
      title: title ?? this.title,
      content: content ?? this.content,
      priority: priority ?? this.priority,
      isSystem: isSystem ?? this.isSystem,
      enabled: enabled ?? this.enabled,
      createdAt: createdAt,
    );
  }

  /// 카테고리별 색상을 반환한다.
  Color get categoryColor {
    switch (category) {
      case 'survival':
        return DomainColors.principleSurvival;
      case 'risk':
        return DomainColors.principleRisk;
      case 'strategy':
        return DomainColors.principleStrategy;
      case 'execution':
        return DomainColors.principleExecution;
      case 'mindset':
        return DomainColors.principleMindset;
      case 'custom':
        return DomainColors.principleCustom;
      default:
        return DomainColors.principleCustom;
    }
  }

  /// 카테고리별 한국어 레이블을 반환한다.
  String get categoryLabel {
    switch (category) {
      case 'survival':
        return '생존';
      case 'risk':
        return '리스크';
      case 'strategy':
        return '전략';
      case 'execution':
        return '실행';
      case 'mindset':
        return '마인드셋';
      case 'custom':
        return '사용자 정의';
      default:
        return '사용자 정의';
    }
  }

  /// 카테고리별 아이콘을 반환한다.
  IconData get categoryIcon {
    switch (category) {
      case 'survival':
        return Icons.shield_rounded;
      case 'risk':
        return Icons.warning_rounded;
      case 'strategy':
        return Icons.auto_graph_rounded;
      case 'execution':
        return Icons.trending_up_rounded;
      case 'mindset':
        return Icons.psychology_rounded;
      case 'custom':
        return Icons.edit_note_rounded;
      default:
        return Icons.edit_note_rounded;
    }
  }
}
