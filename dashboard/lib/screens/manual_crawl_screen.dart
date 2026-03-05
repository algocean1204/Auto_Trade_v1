import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../providers/crawl_progress_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/crawl_progress_widget.dart';
import '../animations/animation_utils.dart';

class ManualCrawlScreen extends StatefulWidget {
  const ManualCrawlScreen({super.key});

  @override
  State<ManualCrawlScreen> createState() => _ManualCrawlScreenState();
}

class _ManualCrawlScreenState extends State<ManualCrawlScreen> {
  bool _wasCrawling = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // 크롤링 완료 시 스낵바를 표시한다
    final provider = context.watch<CrawlProgressProvider>();
    if (_wasCrawling && !provider.isCrawling) {
      _wasCrawling = false;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        if (provider.error != null) {
          _showSnackBar(
            'Crawl failed: ${provider.error}',
            isError: true,
          );
        } else {
          _showSnackBar(
            'Crawling complete: ${provider.lastArticleCount} articles',
            isError: false,
          );
        }
      });
    }
    if (provider.isCrawling) {
      _wasCrawling = true;
    }
  }

  void _showSnackBar(String message, {required bool isError}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? context.tc.loss : context.tc.profit,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<CrawlProgressProvider>();

    return Scaffold(
      appBar: AppBar(
        title: Text('Manual Crawling', style: AppTypography.displaySmall),
      ),
      body: ListView(
        padding: AppSpacing.paddingScreen,
        children: [
          StaggeredFadeSlide(
            index: 0,
            child: _buildInfoCard(context, provider),
          ),
          AppSpacing.vGapLg,
          StaggeredFadeSlide(
            index: 1,
            child: _buildCrawlButton(context, provider),
          ),
          if (provider.error != null && !provider.isCrawling) ...[
            AppSpacing.vGapMd,
            StaggeredFadeSlide(
              index: 2,
              child: _buildErrorCard(context, provider.error!),
            ),
          ],
          AppSpacing.vGapXxl,
          if (provider.isCrawling || provider.crawlerStatuses.isNotEmpty) ...[
            StaggeredFadeSlide(
              index: 3,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Crawl Progress',
                      style: AppTypography.headlineMedium),
                  AppSpacing.vGapLg,
                  // Provider 기반 CrawlProgressWidget (progressList 미전달)
                  const CrawlProgressWidget(),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildInfoCard(BuildContext context, CrawlProgressProvider provider) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Last Crawl', style: AppTypography.headlineMedium),
          AppSpacing.vGapLg,
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Time', style: AppTypography.bodySmall),
                  AppSpacing.vGapXs,
                  Text(
                    provider.lastCrawlTime != null
                        ? DateFormat('yyyy-MM-dd HH:mm')
                            .format(provider.lastCrawlTime!)
                        : 'N/A',
                    style: AppTypography.numberSmall.copyWith(
                      color: context.tc.primary,
                    ),
                  ),
                ],
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text('Articles', style: AppTypography.bodySmall),
                  AppSpacing.vGapXs,
                  Text(
                    NumberFormat('#,###').format(provider.lastArticleCount),
                    style: AppTypography.numberSmall.copyWith(
                      color: context.tc.primary,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildCrawlButton(
      BuildContext context, CrawlProgressProvider provider) {
    return SizedBox(
      width: double.infinity,
      height: 56,
      child: ElevatedButton.icon(
        onPressed: provider.isCrawling ? null : _startCrawling,
        icon: provider.isCrawling
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                ),
              )
            : const Icon(Icons.download_rounded),
        label: Text(
          provider.isCrawling ? 'Crawling...' : 'Start Crawling',
          style: AppTypography.labelLarge.copyWith(color: Colors.white),
        ),
        style: ElevatedButton.styleFrom(
          backgroundColor: provider.isCrawling
              ? context.tc.surfaceBorder
              : context.tc.primary,
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
          ),
        ),
      ),
    );
  }

  Widget _buildErrorCard(BuildContext context, String error) {
    final tc = context.tc;
    return GlassCard(
      child: Row(
        children: [
          Icon(Icons.error_rounded, color: tc.loss, size: 20),
          AppSpacing.hGapMd,
          Expanded(
            child: Text(
              error,
              style: AppTypography.bodyMedium.copyWith(color: tc.loss),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _startCrawling() async {
    final provider = context.read<CrawlProgressProvider>();
    await provider.startCrawl();
  }
}
