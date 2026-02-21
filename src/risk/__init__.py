"""
리스크 관리 모듈 (Addendum 26)

RiskFirst 엔진을 구성하는 4개 리스크 게이트와 관련 유틸리티를 제공한다.

Gate 1: DailyLossLimiter - 일일 손실 한도 (3단계)
Gate 2: ConcentrationLimiter - 집중도 한도
Gate 3: LosingStreakDetector - 연패 감지
Gate 4: SimpleVaR - Value at Risk

추가: RiskBudget, TrailingStopLoss, RiskBacktester
"""

from src.risk.concentration import ConcentrationLimiter
from src.risk.daily_loss_limit import DailyLossLimiter
from src.risk.losing_streak import LosingStreakDetector
from src.risk.risk_backtester import RiskBacktester
from src.risk.risk_budget import RiskBudget
from src.risk.risk_gate import GateResult, RiskGatePipeline
from src.risk.simple_var import SimpleVaR
from src.risk.stop_loss import TrailingStopLoss

__all__ = [
    "GateResult",
    "RiskGatePipeline",
    "DailyLossLimiter",
    "ConcentrationLimiter",
    "LosingStreakDetector",
    "SimpleVaR",
    "RiskBudget",
    "TrailingStopLoss",
    "RiskBacktester",
]
