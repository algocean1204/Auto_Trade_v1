import 'package:flutter/material.dart';
import '../theme/domain_colors.dart';

/// 뉴스 날짜 및 기사 수 모델이다.
class NewsDate {
  final String date;
  final int articleCount;

  const NewsDate({
    required this.date,
    required this.articleCount,
  });

  factory NewsDate.fromJson(Map<String, dynamic> json) {
    return NewsDate(
      date: json['date'] as String? ?? '',
      articleCount: (json['article_count'] as num? ?? 0).toInt(),
    );
  }
}

/// 뉴스 기사 모델이다.
class NewsArticle {
  final String id;
  final String headline;
  final String content;
  final String? summaryKo;
  /// 한국어 헤드라인이다. 백엔드 headline_kr 필드에서 파싱된다.
  final String? headlineKr;
  final String? url;
  final String source;
  final DateTime? publishedAt;
  final List<String> tickers;
  final double? sentimentScore;
  final String impact;
  final String direction;
  final String category;
  /// 기업별 영향 분석이다. 키는 티커 심볼, 값은 영향 설명이다.
  /// 백엔드 companies_impact 필드에서 파싱된다.
  final Map<String, String>? companiesImpact;
  /// 기사 중요도이다. "critical", "key", "normal" 중 하나이다.
  final String importance;

  const NewsArticle({
    required this.id,
    required this.headline,
    required this.content,
    this.summaryKo,
    this.headlineKr,
    this.url,
    required this.source,
    this.publishedAt,
    required this.tickers,
    this.sentimentScore,
    required this.impact,
    required this.direction,
    required this.category,
    this.companiesImpact,
    this.importance = 'normal',
  });

  factory NewsArticle.fromJson(Map<String, dynamic> json) {
    DateTime? parsedDate;
    final rawDate = json['published_at'];
    if (rawDate is String && rawDate.isNotEmpty) {
      try {
        parsedDate = DateTime.parse(rawDate);
      } catch (_) {
        parsedDate = null;
      }
    }

    final rawTickers = json['tickers'];
    final List<String> tickerList;
    if (rawTickers is List) {
      tickerList = rawTickers.map((e) => e.toString()).toList();
    } else {
      tickerList = [];
    }

    // summary_ko 필드를 파싱한다. 백엔드에서 제공하지 않을 경우 null을 반환한다.
    final rawSummaryKo = json['summary_ko'];
    final String? summaryKo =
        (rawSummaryKo is String && rawSummaryKo.isNotEmpty)
            ? rawSummaryKo
            : null;

    // headline_kr 필드를 파싱한다.
    final rawHeadlineKr = json['headline_kr'];
    final String? headlineKr =
        (rawHeadlineKr is String && rawHeadlineKr.isNotEmpty)
            ? rawHeadlineKr
            : null;

    // companies_impact 필드를 파싱한다. Map<String, String> 형태이다.
    final rawCompaniesImpact = json['companies_impact'];
    Map<String, String>? companiesImpact;
    if (rawCompaniesImpact is Map && rawCompaniesImpact.isNotEmpty) {
      companiesImpact = rawCompaniesImpact.map(
        (k, v) => MapEntry(k.toString(), v?.toString() ?? ''),
      );
    }

    // importance 필드를 파싱한다. 기본값은 'normal'이다.
    final rawImportance = json['importance'];
    final String importance =
        (rawImportance is String && rawImportance.isNotEmpty)
            ? rawImportance
            : 'normal';

    return NewsArticle(
      id: json['id'] as String? ?? '',
      headline: json['headline'] as String? ?? '',
      content: json['content'] as String? ?? '',
      summaryKo: summaryKo,
      headlineKr: headlineKr,
      url: json['url'] as String?,
      source: json['source'] as String? ?? '',
      publishedAt: parsedDate,
      tickers: tickerList,
      sentimentScore: (json['sentiment_score'] as num?)?.toDouble(),
      impact: json['impact'] as String? ?? 'low',
      direction: json['direction'] as String? ?? 'neutral',
      category: json['category'] as String? ?? 'other',
      companiesImpact: companiesImpact,
      importance: importance,
    );
  }

  /// 표시할 요약/본문을 반환한다.
  /// summary_ko가 있으면 한국어 요약을, 없으면 영어 원문을 반환한다.
  String get displaySummary => summaryKo ?? content;

  /// 표시할 헤드라인을 반환한다.
  /// headlineKr이 있으면 한국어 헤드라인을, 없으면 영어 헤드라인을 반환한다.
  String get displayHeadline => headlineKr ?? headline;

  /// 한국어 헤드라인 여부를 반환한다.
  bool get hasKoreanHeadline => headlineKr != null && (headlineKr?.isNotEmpty ?? false);

  /// 한국어 요약 여부를 반환한다.
  bool get hasKoreanSummary => summaryKo != null && (summaryKo?.isNotEmpty ?? false);

  /// 기업 영향 분석 존재 여부를 반환한다.
  bool get hasCompaniesImpact =>
      companiesImpact != null && (companiesImpact?.isNotEmpty ?? false);

  /// impact 값에 따른 색상을 반환한다.
  Color get impactColor {
    switch (impact.toLowerCase()) {
      case 'high':
        return DomainColors.impactHigh;
      case 'medium':
        return DomainColors.impactMedium;
      default:
        return DomainColors.impactLow;
    }
  }

  /// direction 값에 따른 색상을 반환한다.
  Color get directionColor {
    switch (direction.toLowerCase()) {
      case 'bullish':
        return DomainColors.bullish;
      case 'bearish':
        return DomainColors.bearish;
      default:
        return DomainColors.neutral;
    }
  }

  /// direction 한국어 레이블을 반환한다.
  String get directionLabel {
    switch (direction.toLowerCase()) {
      case 'bullish':
        return '강세';
      case 'bearish':
        return '약세';
      default:
        return '중립';
    }
  }

  /// category 한국어 레이블을 반환한다.
  String get categoryLabel {
    switch (category.toLowerCase()) {
      case 'macro':
        return '매크로';
      case 'earnings':
        return '실적';
      case 'company':
        return '기업';
      case 'sector':
        return '섹터';
      case 'policy':
        return '정책';
      case 'geopolitics':
        return '지정학';
      default:
        return '기타';
    }
  }

  /// category 색상을 반환한다.
  Color get categoryColor {
    switch (category.toLowerCase()) {
      case 'macro':
        return DomainColors.categoryMacro;
      case 'earnings':
        return DomainColors.categoryEarnings;
      case 'company':
        return DomainColors.categoryCompany;
      case 'sector':
        return DomainColors.categorySector;
      case 'policy':
        return DomainColors.categoryPolicy;
      case 'geopolitics':
        return DomainColors.categoryGeopolitics;
      default:
        return DomainColors.categoryOther;
    }
  }

  /// importance 한국어 레이블을 반환한다.
  String get importanceLabel {
    switch (importance) {
      case 'critical':
        return '크리티컬';
      case 'key':
        return '핵심';
      default:
        return '일반';
    }
  }

  /// importance 색상을 반환한다.
  Color get importanceColor {
    switch (importance) {
      case 'critical':
        return const Color(0xFFDC2626); // red-600
      case 'key':
        return const Color(0xFFF59E0B); // amber-500
      default:
        return const Color(0xFF6B7280); // gray-500
    }
  }

  /// 소스 이름을 가독성 좋게 변환한다.
  String get sourceLabel {
    final lower = source.toLowerCase();
    if (lower.contains('reuters')) return 'Reuters';
    if (lower.contains('bloomberg')) return 'Bloomberg';
    if (lower.contains('cnbc')) return 'CNBC';
    if (lower.contains('wsj') || lower.contains('wall_street')) {
      return 'WSJ';
    }
    if (lower.contains('ft') || lower.contains('financial_times')) {
      return 'FT';
    }
    if (lower.contains('marketwatch')) return 'MarketWatch';
    if (lower.contains('seeking_alpha') || lower.contains('seekingalpha')) {
      return 'Seeking Alpha';
    }
    if (lower.contains('yahoo')) return 'Yahoo Finance';
    if (lower.contains('barrons') || lower.contains("barron")) {
      return "Barron's";
    }
    if (lower.contains('investing')) return 'Investing.com';
    if (lower.contains('motley_fool') || lower.contains('motleyfool')) {
      return 'Motley Fool';
    }
    // 언더스코어/하이픈을 공백으로 치환 후 첫 글자 대문자 처리한다
    return source
        .replaceAll('_', ' ')
        .replaceAll('-', ' ')
        .split(' ')
        .map((w) => w.isEmpty ? '' : '${w[0].toUpperCase()}${w.substring(1)}')
        .join(' ');
  }
}

/// 뉴스 요약 모델이다.
class NewsSummary {
  final String date;
  final int totalArticles;
  final Map<String, int> byCategory;
  final Map<String, int> bySource;
  final Map<String, int> sentimentDistribution;
  final List<NewsArticle> highImpactArticles;
  /// 중요도별 기사 수이다. {"critical": 2, "key": 5, "normal": 43} 형태이다.
  final Map<String, int> byImportance;

  const NewsSummary({
    required this.date,
    required this.totalArticles,
    required this.byCategory,
    required this.bySource,
    required this.sentimentDistribution,
    required this.highImpactArticles,
    this.byImportance = const {},
  });

  factory NewsSummary.fromJson(Map<String, dynamic> json) {
    // byCategory 파싱
    final byCategoryMap = <String, int>{};
    final rawByCategory = json['by_category'];
    if (rawByCategory is Map) {
      rawByCategory.forEach((key, value) {
        byCategoryMap[key.toString()] = (value as num? ?? 0).toInt();
      });
    }

    // bySource 파싱
    final bySourceMap = <String, int>{};
    final rawBySource = json['by_source'];
    if (rawBySource is Map) {
      rawBySource.forEach((key, value) {
        bySourceMap[key.toString()] = (value as num? ?? 0).toInt();
      });
    }

    // sentimentDistribution 파싱
    final sentimentMap = <String, int>{};
    final rawSentiment = json['sentiment_distribution'];
    if (rawSentiment is Map) {
      rawSentiment.forEach((key, value) {
        sentimentMap[key.toString()] = (value as num? ?? 0).toInt();
      });
    }

    // highImpactArticles 파싱
    final rawHighImpact = json['high_impact_articles'];
    final List<NewsArticle> highImpactList;
    if (rawHighImpact is List) {
      highImpactList = rawHighImpact
          .map((e) => NewsArticle.fromJson(e as Map<String, dynamic>))
          .toList();
    } else {
      highImpactList = [];
    }

    // byImportance 파싱
    final byImportanceMap = <String, int>{};
    final rawByImportance = json['importance_distribution'];
    if (rawByImportance is Map) {
      rawByImportance.forEach((key, value) {
        byImportanceMap[key.toString()] = (value as num? ?? 0).toInt();
      });
    }

    return NewsSummary(
      date: json['date'] as String? ?? '',
      totalArticles: (json['total_articles'] as num? ?? 0).toInt(),
      byCategory: byCategoryMap,
      bySource: bySourceMap,
      sentimentDistribution: sentimentMap,
      highImpactArticles: highImpactList,
      byImportance: byImportanceMap,
    );
  }

  /// bullish 기사 수를 반환한다.
  int get bullishCount => sentimentDistribution['bullish'] ?? 0;

  /// bearish 기사 수를 반환한다.
  int get bearishCount => sentimentDistribution['bearish'] ?? 0;

  /// neutral 기사 수를 반환한다.
  int get neutralCount => sentimentDistribution['neutral'] ?? 0;

  /// critical 중요도 기사 수를 반환한다.
  int get criticalCount => byImportance['critical'] ?? 0;

  /// key 중요도 기사 수를 반환한다.
  int get keyCount => byImportance['key'] ?? 0;

  /// normal 중요도 기사 수를 반환한다.
  int get normalCount => byImportance['normal'] ?? 0;
}
