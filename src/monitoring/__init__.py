"""
Monitoring package for the AI Trading System V2.

Provides the FastAPI server, alert management, daily report generation,
benchmark comparison, and Telegram notifications.
"""

from src.monitoring.alert import AlertManager
from src.monitoring.api_server import app, set_dependencies
from src.monitoring.benchmark import BenchmarkComparison
from src.monitoring.daily_report import DailyReportGenerator
from src.monitoring.telegram_notifier import TelegramNotifier

__all__ = [
    "AlertManager",
    "BenchmarkComparison",
    "DailyReportGenerator",
    "TelegramNotifier",
    "app",
    "set_dependencies",
]
