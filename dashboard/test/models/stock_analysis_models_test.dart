// stock_analysis_models.dart 모델의 fromJson 및 파생 속성 테스트이다.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_trading_dashboard/models/stock_analysis_models.dart';
import 'package:ai_trading_dashboard/theme/domain_colors.dart';

void main() {
  group('PricePoint', () {
    test('fromJson - 정상 JSON 파싱한다', () {
      final json = {'date': '2024-01-15', 'close': 123.45, 'volume': 1000000};
      final pp = PricePoint.fromJson(json);

      expect(pp.date, '2024-01-15');
      expect(pp.close, 123.45);
      expect(pp.volume, 1000000);
    });

    test('fromJson - 누락된 필드에 대해 기본값을 사용한다', () {
      final pp = PricePoint.fromJson({});

      expect(pp.date, '');
      expect(pp.close, 0.0);
      expect(pp.volume, 0);
    });

    test('fromJson - null 필드에 대해 기본값을 사용한다', () {
      final json = {'date': null, 'close': null, 'volume': null};
      final pp = PricePoint.fromJson(json);

      expect(pp.date, '');
      expect(pp.close, 0.0);
      expect(pp.volume, 0);
    });
  });

  group('TechnicalSummary', () {
    test('fromJson - 정상 JSON 파싱한다', () {
      final json = {
        'composite_score': 0.75,
        'rsi_14': 65.3,
        'macd_signal': 'bullish',
        'trend': 'uptrend',
        'support': 100.0,
        'resistance': 150.0,
      };
      final ts = TechnicalSummary.fromJson(json);

      expect(ts.compositeScore, 0.75);
      expect(ts.rsi14, 65.3);
      expect(ts.macdSignal, 'bullish');
      expect(ts.trend, 'uptrend');
      expect(ts.support, 100.0);
      expect(ts.resistance, 150.0);
    });

    test('fromJson - 누락된 필드에 대해 기본값을 사용한다', () {
      final ts = TechnicalSummary.fromJson({});

      expect(ts.compositeScore, 0.0);
      expect(ts.rsi14, 50.0);
      expect(ts.macdSignal, 'neutral');
      expect(ts.trend, 'sideways');
      expect(ts.support, 0.0);
      expect(ts.resistance, 0.0);
    });

    test('scoreColor - compositeScore > 0.3이면 profit 색상을 반환한다', () {
      final ts = TechnicalSummary.fromJson({'composite_score': 0.5});
      expect(ts.scoreColor, DomainColors.scorePositive);
    });

    test('scoreColor - compositeScore < -0.3이면 loss 색상을 반환한다', () {
      final ts = TechnicalSummary.fromJson({'composite_score': -0.5});
      expect(ts.scoreColor, DomainColors.scoreNegative);
    });

    test('scoreColor - compositeScore이 중립 범위이면 warning 색상을 반환한다', () {
      final ts = TechnicalSummary.fromJson({'composite_score': 0.1});
      expect(ts.scoreColor, DomainColors.scoreNeutral);
    });

    test('rsiColor - RSI > 70이면 loss 색상(과매수)을 반환한다', () {
      final ts = TechnicalSummary.fromJson({'rsi_14': 75});
      expect(ts.rsiColor, DomainColors.rsiOverbought);
    });

    test('rsiColor - RSI < 30이면 profit 색상(과매도)을 반환한다', () {
      final ts = TechnicalSummary.fromJson({'rsi_14': 25});
      expect(ts.rsiColor, DomainColors.rsiOversold);
    });

    test('rsiLabel - RSI 상태 레이블을 올바르게 반환한다', () {
      expect(TechnicalSummary.fromJson({'rsi_14': 75}).rsiLabel, '과매수');
      expect(TechnicalSummary.fromJson({'rsi_14': 25}).rsiLabel, '과매도');
      expect(TechnicalSummary.fromJson({'rsi_14': 50}).rsiLabel, '중립');
    });

    test('macdColor - MACD 신호에 따른 색상을 반환한다', () {
      expect(
        TechnicalSummary.fromJson({'macd_signal': 'bullish'}).macdColor,
        DomainColors.bullish,
      );
      expect(
        TechnicalSummary.fromJson({'macd_signal': 'bearish'}).macdColor,
        DomainColors.bearish,
      );
      expect(
        TechnicalSummary.fromJson({'macd_signal': 'neutral'}).macdColor,
        DomainColors.neutral,
      );
    });

    test('trendColor - 추세에 따른 색상을 반환한다', () {
      expect(
        TechnicalSummary.fromJson({'trend': 'uptrend'}).trendColor,
        DomainColors.bullish,
      );
      expect(
        TechnicalSummary.fromJson({'trend': 'up'}).trendColor,
        DomainColors.bullish,
      );
      expect(
        TechnicalSummary.fromJson({'trend': 'downtrend'}).trendColor,
        DomainColors.bearish,
      );
      expect(
        TechnicalSummary.fromJson({'trend': 'sideways'}).trendColor,
        DomainColors.neutral,
      );
    });
  });

  group('Prediction', () {
    test('fromJson - 정상 JSON 파싱한다', () {
      final json = {
        'timeframe': '1d',
        'direction': 'bullish',
        'confidence': 85,
        'target_price': 155.50,
        'reasoning': 'Strong momentum',
      };
      final p = Prediction.fromJson(json);

      expect(p.timeframe, '1d');
      expect(p.direction, 'bullish');
      expect(p.confidence, 85);
      expect(p.targetPrice, 155.50);
      expect(p.reasoning, 'Strong momentum');
    });

    test('fromJson - 누락된 필드에 대해 기본값을 사용한다', () {
      final p = Prediction.fromJson({});

      expect(p.timeframe, '');
      expect(p.direction, 'neutral');
      expect(p.confidence, 50);
      expect(p.targetPrice, 0.0);
      expect(p.reasoning, '');
    });

    test('directionColor - direction에 따른 색상을 반환한다', () {
      expect(
        Prediction.fromJson({'direction': 'bullish'}).directionColor,
        DomainColors.bullish,
      );
      expect(
        Prediction.fromJson({'direction': 'bearish'}).directionColor,
        DomainColors.bearish,
      );
      expect(
        Prediction.fromJson({'direction': 'neutral'}).directionColor,
        DomainColors.neutral,
      );
    });

    test('directionIcon - direction에 따른 아이콘을 반환한다', () {
      expect(
        Prediction.fromJson({'direction': 'bullish'}).directionIcon,
        Icons.trending_up_rounded,
      );
      expect(
        Prediction.fromJson({'direction': 'bearish'}).directionIcon,
        Icons.trending_down_rounded,
      );
      expect(
        Prediction.fromJson({'direction': 'neutral'}).directionIcon,
        Icons.trending_flat_rounded,
      );
    });

    test('directionLabel - direction에 따른 한국어 레이블을 반환한다', () {
      expect(Prediction.fromJson({'direction': 'bullish'}).directionLabel, '상승');
      expect(Prediction.fromJson({'direction': 'bearish'}).directionLabel, '하락');
      expect(Prediction.fromJson({'direction': 'neutral'}).directionLabel, '중립');
    });
  });

  group('Recommendation', () {
    test('fromJson - 정상 JSON 파싱한다', () {
      final json = {
        'action': 'buy',
        'reasoning': 'Oversold condition',
      };
      final r = Recommendation.fromJson(json);

      expect(r.action, 'buy');
      expect(r.reasoning, 'Oversold condition');
    });

    test('fromJson - 누락된 필드에 대해 기본값을 사용한다', () {
      final r = Recommendation.fromJson({});
      expect(r.action, 'hold');
      expect(r.reasoning, '');
    });

    test('actionColor - action에 따른 색상을 반환한다', () {
      expect(Recommendation.fromJson({'action': 'buy'}).actionColor, DomainColors.signalBuy);
      expect(Recommendation.fromJson({'action': 'sell'}).actionColor, DomainColors.signalSell);
      expect(Recommendation.fromJson({'action': 'hold'}).actionColor, DomainColors.signalHold);
    });

    test('actionLabel - action에 따른 한국어 레이블을 반환한다', () {
      expect(Recommendation.fromJson({'action': 'buy'}).actionLabel, '매수');
      expect(Recommendation.fromJson({'action': 'sell'}).actionLabel, '매도');
      expect(Recommendation.fromJson({'action': 'hold'}).actionLabel, '보유');
    });
  });

  group('AnalysisNews', () {
    test('fromJson - 정상 JSON 파싱한다', () {
      final json = {
        'id': 'news-001',
        'headline': 'Tech stocks rally',
        'headline_kr': '기술주 상승세',
        'summary_ko': '기술주가 강하게 반등했다.',
        'companies_impact': {'AAPL': 'positive', 'MSFT': 'neutral'},
        'published_at': '2024-01-15T10:30:00Z',
        'sentiment_score': 0.8,
        'impact': 'high',
        'source': 'reuters_api',
      };
      final news = AnalysisNews.fromJson(json);

      expect(news.id, 'news-001');
      // headline_kr이 있으면 한국어 헤드라인을 우선 사용한다.
      expect(news.headline, '기술주 상승세');
      expect(news.headlineOriginal, 'Tech stocks rally');
      expect(news.summaryKo, '기술주가 강하게 반등했다.');
      expect(news.companiesImpact, isNotNull);
      expect(news.companiesImpact!['AAPL'], 'positive');
      expect(news.sentimentScore, 0.8);
      expect(news.impact, 'high');
      expect(news.source, 'reuters_api');
    });

    test('fromJson - headline_kr이 없으면 영문 headline을 사용한다', () {
      final json = {
        'id': 'news-002',
        'headline': 'Markets close higher',
        'impact': 'low',
        'source': 'cnbc',
      };
      final news = AnalysisNews.fromJson(json);
      expect(news.headline, 'Markets close higher');
    });

    test('fromJson - 누락된 필드에 대해 기본값을 사용한다', () {
      final news = AnalysisNews.fromJson({});

      expect(news.id, '');
      expect(news.headline, '');
      expect(news.impact, 'low');
      expect(news.source, '');
      expect(news.companiesImpact, isNull);
      expect(news.sentimentScore, isNull);
    });

    test('impactColor - impact에 따른 색상을 반환한다', () {
      expect(AnalysisNews.fromJson({'impact': 'high'}).impactColor, DomainColors.analysisImpactHigh);
      expect(AnalysisNews.fromJson({'impact': 'medium'}).impactColor, DomainColors.analysisImpactMedium);
      expect(AnalysisNews.fromJson({'impact': 'low'}).impactColor, DomainColors.analysisImpactLow);
    });

    test('impactLabel - impact에 따른 한국어 레이블을 반환한다', () {
      expect(AnalysisNews.fromJson({'impact': 'high'}).impactLabel, '높음');
      expect(AnalysisNews.fromJson({'impact': 'medium'}).impactLabel, '보통');
      expect(AnalysisNews.fromJson({'impact': 'low'}).impactLabel, '낮음');
    });

    test('dateKey - published_at에서 날짜를 추출한다', () {
      final news = AnalysisNews.fromJson({
        'published_at': '2024-01-15T10:30:00Z',
      });
      expect(news.dateKey, '2024-01-15');
    });

    test('dateKey - published_at이 없으면 빈 문자열을 반환한다', () {
      final news = AnalysisNews.fromJson({});
      expect(news.dateKey, '');
    });

    test('sourceLabel - 알려진 소스를 가독성 좋게 변환한다', () {
      expect(AnalysisNews.fromJson({'source': 'reuters_api'}).sourceLabel, 'Reuters');
      expect(AnalysisNews.fromJson({'source': 'bloomberg'}).sourceLabel, 'Bloomberg');
      expect(AnalysisNews.fromJson({'source': 'cnbc'}).sourceLabel, 'CNBC');
      expect(AnalysisNews.fromJson({'source': 'wsj'}).sourceLabel, 'WSJ');
      expect(AnalysisNews.fromJson({'source': 'financial_times'}).sourceLabel, 'FT');
      expect(AnalysisNews.fromJson({'source': 'marketwatch'}).sourceLabel, 'MarketWatch');
      expect(AnalysisNews.fromJson({'source': 'seeking_alpha'}).sourceLabel, 'SeekingAlpha');
      expect(AnalysisNews.fromJson({'source': 'yahoo_finance'}).sourceLabel, 'Yahoo Finance');
    });

    test('sourceLabel - 알 수 없는 소스도 포맷팅한다', () {
      final news = AnalysisNews.fromJson({'source': 'custom_news_source'});
      expect(news.sourceLabel, 'Custom News Source');
    });
  });

  group('AiAnalysis', () {
    test('fromJson - 정상 JSON 파싱한다', () {
      final json = {
        'current_situation': 'Market is bullish',
        'reasoning': 'Strong earnings',
        'key_factors': ['Earnings beat', 'GDP growth'],
        'risk_factors': ['Inflation', 'Rate hikes'],
        'predictions': [
          {
            'timeframe': '1d',
            'direction': 'bullish',
            'confidence': 80,
            'target_price': 150.0,
            'reasoning': 'Momentum',
          },
        ],
        'recommendation': {
          'action': 'buy',
          'reasoning': 'Good entry point',
        },
      };
      final ai = AiAnalysis.fromJson(json);

      expect(ai.currentSituation, 'Market is bullish');
      expect(ai.reasoning, 'Strong earnings');
      expect(ai.keyFactors, hasLength(2));
      expect(ai.riskFactors, hasLength(2));
      expect(ai.predictions, hasLength(1));
      expect(ai.predictions.first.direction, 'bullish');
      expect(ai.recommendation.action, 'buy');
    });

    test('fromJson - 누락된 필드에 대해 기본값을 사용한다', () {
      final ai = AiAnalysis.fromJson({});

      expect(ai.currentSituation, '');
      expect(ai.reasoning, '');
      expect(ai.keyFactors, isEmpty);
      expect(ai.riskFactors, isEmpty);
      expect(ai.predictions, isEmpty);
      expect(ai.recommendation.action, 'hold');
    });
  });

  group('StockAnalysisData', () {
    test('fromJson - 전체 JSON 파싱한다', () {
      final json = {
        'ticker': 'SOXL',
        'current_price': 35.50,
        'price_change_pct': 2.35,
        'analysis_timestamp': '2024-01-15T10:00:00Z',
        'technical_summary': {
          'composite_score': 0.6,
          'rsi_14': 55.0,
          'macd_signal': 'bullish',
          'trend': 'uptrend',
          'support': 30.0,
          'resistance': 40.0,
        },
        'ai_analysis': {
          'current_situation': 'Bullish',
          'reasoning': 'Strong',
          'key_factors': ['A'],
          'risk_factors': ['B'],
          'predictions': [],
          'recommendation': {'action': 'buy', 'reasoning': 'Good'},
        },
        'related_news': [
          {
            'id': 'n1',
            'headline': 'News',
            'impact': 'high',
            'source': 'reuters',
          },
        ],
        'price_history': [
          {'date': '2024-01-15', 'close': 35.0, 'volume': 500000},
        ],
      };
      final data = StockAnalysisData.fromJson(json);

      expect(data.ticker, 'SOXL');
      expect(data.currentPrice, 35.50);
      expect(data.priceChangePct, 2.35);
      expect(data.technicalSummary.compositeScore, 0.6);
      expect(data.aiAnalysis.recommendation.action, 'buy');
      expect(data.relatedNews, hasLength(1));
      expect(data.priceHistory, hasLength(1));
    });

    test('fromJson - 누락된 중첩 객체에 대해 기본값을 사용한다', () {
      final data = StockAnalysisData.fromJson({});

      expect(data.ticker, '');
      expect(data.currentPrice, 0.0);
      expect(data.technicalSummary.macdSignal, 'neutral');
      expect(data.aiAnalysis.recommendation.action, 'hold');
      expect(data.relatedNews, isEmpty);
      expect(data.priceHistory, isEmpty);
    });

    test('priceChangeColor - 양수이면 profit, 음수이면 loss 색상을 반환한다', () {
      expect(
        StockAnalysisData.fromJson({'price_change_pct': 1.5}).priceChangeColor,
        DomainColors.priceUp,
      );
      expect(
        StockAnalysisData.fromJson({'price_change_pct': -1.5}).priceChangeColor,
        DomainColors.priceDown,
      );
    });

    test('priceChangeLabel - 부호 포함 문자열을 반환한다', () {
      expect(
        StockAnalysisData.fromJson({'price_change_pct': 2.35}).priceChangeLabel,
        '+2.35%',
      );
      expect(
        StockAnalysisData.fromJson({'price_change_pct': -1.50}).priceChangeLabel,
        '-1.50%',
      );
      expect(
        StockAnalysisData.fromJson({'price_change_pct': 0.0}).priceChangeLabel,
        '+0.00%',
      );
    });
  });
}
