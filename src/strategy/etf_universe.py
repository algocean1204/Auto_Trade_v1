"""미국 2X 레버리지 ETF 및 개별 주요 종목 유니버스 관리

Bull 2X (17종목) / Bear (Inverse) 2X (14종목) 레버리지 ETF 유니버스와
빅테크/반도체/클라우드/금융/헬스케어 주요 개별 주식 41종목을 정의하고,
종목 조회, 활성 필터, Bull-Bear 매칭, 섹터별 조회 등 유틸리티를 제공한다.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bull 2X Universe (17 종목)
# ---------------------------------------------------------------------------
BULL_2X_UNIVERSE: dict[str, dict] = {
    "SSO": {
        "name": "ProShares Ultra S&P500",
        "underlying": "S&P 500",
        "expense_ratio": 0.89,
        "avg_daily_volume": 3_500_000,
        "enabled": True,
    },
    "QLD": {
        "name": "ProShares Ultra QQQ",
        "underlying": "NASDAQ-100",
        "expense_ratio": 0.95,
        "avg_daily_volume": 4_200_000,
        "enabled": True,
    },
    "SPUU": {
        "name": "Direxion Daily S&P 500 Bull 2X",
        "underlying": "S&P 500",
        "expense_ratio": 0.63,
        "avg_daily_volume": 600_000,
        "enabled": True,
    },
    "UWM": {
        "name": "ProShares Ultra Russell 2000",
        "underlying": "Russell 2000",
        "expense_ratio": 0.95,
        "avg_daily_volume": 1_800_000,
        "enabled": True,
    },
    "MVV": {
        "name": "ProShares Ultra MidCap400",
        "underlying": "S&P MidCap 400",
        "expense_ratio": 0.95,
        "avg_daily_volume": 120_000,
        "enabled": False,
    },
    "DDM": {
        "name": "ProShares Ultra Dow30",
        "underlying": "Dow Jones 30",
        "expense_ratio": 0.95,
        "avg_daily_volume": 800_000,
        "enabled": True,
    },
    "ROM": {
        "name": "ProShares Ultra Technology",
        "underlying": "Dow Jones U.S. Technology",
        "expense_ratio": 0.95,
        "avg_daily_volume": 350_000,
        "enabled": True,
    },
    "USD": {
        "name": "ProShares Ultra Semiconductors",
        "underlying": "Dow Jones U.S. Semiconductors",
        "expense_ratio": 0.95,
        "avg_daily_volume": 500_000,
        "enabled": True,
    },
    "UYG": {
        "name": "ProShares Ultra Financials",
        "underlying": "Dow Jones U.S. Financials",
        "expense_ratio": 0.95,
        "avg_daily_volume": 700_000,
        "enabled": True,
    },
    "UGE": {
        "name": "ProShares Ultra Consumer Goods",
        "underlying": "Consumer Goods",
        "expense_ratio": 0.95,
        "avg_daily_volume": 30_000,
        "enabled": False,
    },
    "RXL": {
        "name": "ProShares Ultra Health Care",
        "underlying": "Health Care",
        "expense_ratio": 0.95,
        "avg_daily_volume": 50_000,
        "enabled": False,
    },
    "UPW": {
        "name": "ProShares Ultra Utilities",
        "underlying": "Utilities",
        "expense_ratio": 0.95,
        "avg_daily_volume": 40_000,
        "enabled": False,
    },
    "DIG": {
        "name": "ProShares Ultra Oil & Gas",
        "underlying": "Oil & Gas",
        "expense_ratio": 0.95,
        "avg_daily_volume": 1_200_000,
        "enabled": True,
    },
    "URE": {
        "name": "ProShares Ultra Real Estate",
        "underlying": "Real Estate",
        "expense_ratio": 0.95,
        "avg_daily_volume": 200_000,
        "enabled": False,
    },
    "UXI": {
        "name": "ProShares Ultra Industrials",
        "underlying": "Industrials",
        "expense_ratio": 0.95,
        "avg_daily_volume": 50_000,
        "enabled": False,
    },
    "UCC": {
        "name": "ProShares Ultra Consumer Services",
        "underlying": "Consumer Services",
        "expense_ratio": 0.95,
        "avg_daily_volume": 20_000,
        "enabled": False,
    },
    "UJB": {
        "name": "ProShares Ultra High Yield",
        "underlying": "HY Index",
        "expense_ratio": 0.95,
        "avg_daily_volume": 60_000,
        "enabled": False,
    },
}

# ---------------------------------------------------------------------------
# Bear (Inverse) 2X Universe (14 종목)
# ---------------------------------------------------------------------------
BEAR_2X_UNIVERSE: dict[str, dict] = {
    "SDS": {
        "name": "ProShares UltraShort S&P500",
        "underlying": "S&P 500 Inverse",
        "expense_ratio": 0.89,
        "avg_daily_volume": 5_000_000,
        "enabled": True,
    },
    "QID": {
        "name": "ProShares UltraShort QQQ",
        "underlying": "NASDAQ-100 Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 4_500_000,
        "enabled": True,
    },
    "TWM": {
        "name": "ProShares UltraShort Russell 2000",
        "underlying": "Russell 2000 Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 1_200_000,
        "enabled": True,
    },
    "DXD": {
        "name": "ProShares UltraShort Dow30",
        "underlying": "Dow Jones 30 Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 600_000,
        "enabled": True,
    },
    "MZZ": {
        "name": "ProShares UltraShort MidCap400",
        "underlying": "MidCap 400 Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 30_000,
        "enabled": False,
    },
    "REW": {
        "name": "ProShares UltraShort Technology",
        "underlying": "Technology Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 80_000,
        "enabled": True,
    },
    "SSG": {
        "name": "ProShares UltraShort Semiconductors",
        "underlying": "Semiconductors Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 150_000,
        "enabled": True,
    },
    "SKF": {
        "name": "ProShares UltraShort Financials",
        "underlying": "Financials Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 400_000,
        "enabled": True,
    },
    "DUG": {
        "name": "ProShares UltraShort Oil & Gas",
        "underlying": "Oil & Gas Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 800_000,
        "enabled": True,
    },
    "SRS": {
        "name": "ProShares UltraShort Real Estate",
        "underlying": "Real Estate Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 150_000,
        "enabled": False,
    },
    "RXD": {
        "name": "ProShares UltraShort Health Care",
        "underlying": "Health Care Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 20_000,
        "enabled": False,
    },
    "SIJ": {
        "name": "ProShares UltraShort Industrials",
        "underlying": "Industrials Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 15_000,
        "enabled": False,
    },
    "SCC": {
        "name": "ProShares UltraShort Consumer Services",
        "underlying": "Consumer Services Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 10_000,
        "enabled": False,
    },
    "SZK": {
        "name": "ProShares UltraShort Consumer Goods",
        "underlying": "Consumer Goods Inverse",
        "expense_ratio": 0.95,
        "avg_daily_volume": 10_000,
        "enabled": False,
    },
}

# ---------------------------------------------------------------------------
# 빅테크 / 주요 개별 주식 유니버스 (41 종목 + 기존 종목)
# expense_ratio=0.0 (개별 주식은 운용 보수 없음)
# sector: SECTOR_TICKERS 키와 일치
# ---------------------------------------------------------------------------
INDIVIDUAL_STOCK_UNIVERSE: dict[str, dict] = {
    # Big Tech / FAANG+
    "NVDA": {
        "name": "NVIDIA Corporation",
        "underlying": "Semiconductors / AI",
        "sector": "semiconductors",
        "expense_ratio": 0.0,
        "avg_daily_volume": 350_000_000,
        "enabled": True,
    },
    "AAPL": {
        "name": "Apple Inc.",
        "underlying": "Consumer Electronics / Tech",
        "sector": "big_tech",
        "expense_ratio": 0.0,
        "avg_daily_volume": 70_000_000,
        "enabled": True,
    },
    "MSFT": {
        "name": "Microsoft Corporation",
        "underlying": "Cloud / Software / AI",
        "sector": "big_tech",
        "expense_ratio": 0.0,
        "avg_daily_volume": 25_000_000,
        "enabled": True,
    },
    "GOOGL": {
        "name": "Alphabet Inc. (Google)",
        "underlying": "Internet / Advertising / AI",
        "sector": "big_tech",
        "expense_ratio": 0.0,
        "avg_daily_volume": 25_000_000,
        "enabled": True,
    },
    "GOOG": {
        "name": "Alphabet Inc. Class C (Google)",
        "underlying": "Internet / Advertising / AI",
        "sector": "big_tech",
        "expense_ratio": 0.0,
        "avg_daily_volume": 20_000_000,
        "enabled": True,
    },
    "AMZN": {
        "name": "Amazon.com Inc.",
        "underlying": "E-Commerce / Cloud (AWS)",
        "sector": "big_tech",
        "expense_ratio": 0.0,
        "avg_daily_volume": 45_000_000,
        "enabled": True,
    },
    "META": {
        "name": "Meta Platforms Inc.",
        "underlying": "Social Media / AI",
        "sector": "big_tech",
        "expense_ratio": 0.0,
        "avg_daily_volume": 20_000_000,
        "enabled": True,
    },
    "TSLA": {
        "name": "Tesla Inc.",
        "underlying": "Electric Vehicles / Energy",
        "sector": "ev_energy",
        "expense_ratio": 0.0,
        "avg_daily_volume": 120_000_000,
        "enabled": True,
    },
    # Semiconductor
    "AMD": {
        "name": "Advanced Micro Devices Inc.",
        "underlying": "Semiconductors / CPU / GPU",
        "sector": "semiconductors",
        "expense_ratio": 0.0,
        "avg_daily_volume": 60_000_000,
        "enabled": True,
    },
    "AVGO": {
        "name": "Broadcom Inc.",
        "underlying": "Semiconductors / Networking",
        "sector": "semiconductors",
        "expense_ratio": 0.0,
        "avg_daily_volume": 15_000_000,
        "enabled": True,
    },
    "TSM": {
        "name": "Taiwan Semiconductor Manufacturing (ADR)",
        "underlying": "Semiconductor Foundry",
        "sector": "semiconductors",
        "expense_ratio": 0.0,
        "avg_daily_volume": 20_000_000,
        "enabled": True,
    },
    "QCOM": {
        "name": "Qualcomm Inc.",
        "underlying": "Mobile Semiconductors / 5G",
        "sector": "semiconductors",
        "expense_ratio": 0.0,
        "avg_daily_volume": 12_000_000,
        "enabled": True,
    },
    "MU": {
        "name": "Micron Technology Inc.",
        "underlying": "Memory Semiconductors (DRAM/NAND)",
        "sector": "semiconductors",
        "expense_ratio": 0.0,
        "avg_daily_volume": 30_000_000,
        "enabled": True,
    },
    "ARM": {
        "name": "ARM Holdings plc (ADR)",
        "underlying": "CPU Architecture / IP Licensing",
        "sector": "semiconductors",
        "expense_ratio": 0.0,
        "avg_daily_volume": 15_000_000,
        "enabled": True,
    },
    "INTC": {
        "name": "Intel Corporation",
        "underlying": "Semiconductors / CPU / Foundry",
        "sector": "semiconductors",
        "expense_ratio": 0.0,
        "avg_daily_volume": 50_000_000,
        "enabled": True,
    },
    "MRVL": {
        "name": "Marvell Technology Inc.",
        "underlying": "Data Infrastructure Semiconductors",
        "sector": "semiconductors",
        "expense_ratio": 0.0,
        "avg_daily_volume": 25_000_000,
        "enabled": True,
    },
    # Cloud / Software / AI
    "CRM": {
        "name": "Salesforce Inc.",
        "underlying": "CRM / Enterprise Software / AI",
        "sector": "ai_software",
        "expense_ratio": 0.0,
        "avg_daily_volume": 8_000_000,
        "enabled": True,
    },
    "ORCL": {
        "name": "Oracle Corporation",
        "underlying": "Database / Cloud / Enterprise",
        "sector": "ai_software",
        "expense_ratio": 0.0,
        "avg_daily_volume": 12_000_000,
        "enabled": True,
    },
    "ADBE": {
        "name": "Adobe Inc.",
        "underlying": "Creative Software / Digital Media",
        "sector": "ai_software",
        "expense_ratio": 0.0,
        "avg_daily_volume": 5_000_000,
        "enabled": True,
    },
    "NOW": {
        "name": "ServiceNow Inc.",
        "underlying": "IT Workflow Automation / AI",
        "sector": "ai_software",
        "expense_ratio": 0.0,
        "avg_daily_volume": 3_000_000,
        "enabled": True,
    },
    "PLTR": {
        "name": "Palantir Technologies Inc.",
        "underlying": "Data Analytics / AI / Government",
        "sector": "ai_software",
        "expense_ratio": 0.0,
        "avg_daily_volume": 80_000_000,
        "enabled": True,
    },
    "DDOG": {
        "name": "Datadog Inc.",
        "underlying": "Cloud Monitoring / Observability",
        "sector": "ai_software",
        "expense_ratio": 0.0,
        "avg_daily_volume": 7_000_000,
        "enabled": True,
    },
    "MDB": {
        "name": "MongoDB Inc.",
        "underlying": "NoSQL Database / Cloud",
        "sector": "ai_software",
        "expense_ratio": 0.0,
        "avg_daily_volume": 5_000_000,
        "enabled": True,
    },
    "DELL": {
        "name": "Dell Technologies Inc.",
        "underlying": "Enterprise Hardware / AI Servers",
        "sector": "ai_software",
        "expense_ratio": 0.0,
        "avg_daily_volume": 10_000_000,
        "enabled": True,
    },
    "SNOW": {
        "name": "Snowflake Inc.",
        "underlying": "Cloud Data Platform",
        "sector": "ai_software",
        "expense_ratio": 0.0,
        "avg_daily_volume": 8_000_000,
        "enabled": True,
    },
    # Tech / Platform
    "NFLX": {
        "name": "Netflix Inc.",
        "underlying": "Streaming / Entertainment",
        "sector": "big_tech",
        "expense_ratio": 0.0,
        "avg_daily_volume": 7_000_000,
        "enabled": True,
    },
    "UBER": {
        "name": "Uber Technologies Inc.",
        "underlying": "Ride-Sharing / Delivery Platform",
        "sector": "other",
        "expense_ratio": 0.0,
        "avg_daily_volume": 25_000_000,
        "enabled": True,
    },
    "SHOP": {
        "name": "Shopify Inc.",
        "underlying": "E-Commerce Platform / SaaS",
        "sector": "other",
        "expense_ratio": 0.0,
        "avg_daily_volume": 10_000_000,
        "enabled": True,
    },
    "COIN": {
        "name": "Coinbase Global Inc.",
        "underlying": "Cryptocurrency Exchange",
        "sector": "crypto",
        "expense_ratio": 0.0,
        "avg_daily_volume": 20_000_000,
        "enabled": True,
    },
    "SQ": {
        "name": "Block Inc. (Square)",
        "underlying": "Fintech / Payments / Bitcoin",
        "sector": "finance",
        "expense_ratio": 0.0,
        "avg_daily_volume": 12_000_000,
        "enabled": True,
    },
    # Finance / Healthcare (diversification)
    "JPM": {
        "name": "JPMorgan Chase & Co.",
        "underlying": "Banking / Financial Services",
        "sector": "finance",
        "expense_ratio": 0.0,
        "avg_daily_volume": 12_000_000,
        "enabled": True,
    },
    "V": {
        "name": "Visa Inc.",
        "underlying": "Payment Networks",
        "sector": "finance",
        "expense_ratio": 0.0,
        "avg_daily_volume": 9_000_000,
        "enabled": True,
    },
    "MA": {
        "name": "Mastercard Inc.",
        "underlying": "Payment Networks",
        "sector": "finance",
        "expense_ratio": 0.0,
        "avg_daily_volume": 5_000_000,
        "enabled": True,
    },
    "UNH": {
        "name": "UnitedHealth Group Inc.",
        "underlying": "Healthcare Insurance / Services",
        "sector": "healthcare",
        "expense_ratio": 0.0,
        "avg_daily_volume": 4_000_000,
        "enabled": True,
    },
    "LLY": {
        "name": "Eli Lilly and Company",
        "underlying": "Pharmaceuticals / Diabetes / Oncology",
        "sector": "healthcare",
        "expense_ratio": 0.0,
        "avg_daily_volume": 5_000_000,
        "enabled": True,
    },
    # 신규 추가 종목 (41 유니버스)
    "MSTR": {
        "name": "MicroStrategy Inc.",
        "underlying": "Bitcoin Treasury / Business Intelligence",
        "sector": "crypto",
        "expense_ratio": 0.0,
        "avg_daily_volume": 15_000_000,
        "enabled": True,
    },
    "BLK": {
        "name": "BlackRock Inc.",
        "underlying": "Asset Management / Finance",
        "sector": "finance",
        "expense_ratio": 0.0,
        "avg_daily_volume": 3_000_000,
        "enabled": True,
    },
    "BAC": {
        "name": "Bank of America Corp.",
        "underlying": "Banking / Financial Services",
        "sector": "finance",
        "expense_ratio": 0.0,
        "avg_daily_volume": 40_000_000,
        "enabled": True,
    },
    "PYPL": {
        "name": "PayPal Holdings Inc.",
        "underlying": "Digital Payments / Fintech",
        "sector": "finance",
        "expense_ratio": 0.0,
        "avg_daily_volume": 12_000_000,
        "enabled": True,
    },
    "BRKB": {
        "name": "Berkshire Hathaway Inc. Class B",
        "underlying": "Diversified Conglomerate / Finance",
        "sector": "finance",
        "expense_ratio": 0.0,
        "avg_daily_volume": 5_000_000,
        "enabled": True,
    },
    "IONQ": {
        "name": "IonQ Inc.",
        "underlying": "Quantum Computing",
        "sector": "quantum",
        "expense_ratio": 0.0,
        "avg_daily_volume": 8_000_000,
        "enabled": True,
    },
    "RGTI": {
        "name": "Rigetti Computing Inc.",
        "underlying": "Quantum Computing",
        "sector": "quantum",
        "expense_ratio": 0.0,
        "avg_daily_volume": 20_000_000,
        "enabled": True,
    },
    "DIS": {
        "name": "The Walt Disney Company",
        "underlying": "Entertainment / Streaming / Theme Parks",
        "sector": "entertainment",
        "expense_ratio": 0.0,
        "avg_daily_volume": 15_000_000,
        "enabled": True,
    },
    "DKNG": {
        "name": "DraftKings Inc.",
        "underlying": "Online Sports Betting / Entertainment",
        "sector": "entertainment",
        "expense_ratio": 0.0,
        "avg_daily_volume": 10_000_000,
        "enabled": True,
    },
    "NSC": {
        "name": "Norfolk Southern Corporation",
        "underlying": "Railroad / Transportation",
        "sector": "infrastructure",
        "expense_ratio": 0.0,
        "avg_daily_volume": 2_000_000,
        "enabled": True,
    },
    "EQIX": {
        "name": "Equinix Inc.",
        "underlying": "Data Center REIT / Digital Infrastructure",
        "sector": "infrastructure",
        "expense_ratio": 0.0,
        "avg_daily_volume": 1_500_000,
        "enabled": True,
    },
    "KO": {
        "name": "The Coca-Cola Company",
        "underlying": "Beverages / Consumer Staples",
        "sector": "consumer",
        "expense_ratio": 0.0,
        "avg_daily_volume": 15_000_000,
        "enabled": True,
    },
    "NVO": {
        "name": "Novo Nordisk A/S (ADR)",
        "underlying": "Pharmaceuticals / Diabetes / Obesity",
        "sector": "healthcare",
        "expense_ratio": 0.0,
        "avg_daily_volume": 8_000_000,
        "enabled": True,
    },
    "FIG": {
        "name": "Simplify Macro Strategy ETF",
        "underlying": "Macro / Multi-Asset Strategy",
        "sector": "other",
        "expense_ratio": 0.50,
        "avg_daily_volume": 500_000,
        "enabled": True,
    },
    "CLSK": {
        "name": "CleanSpark Inc.",
        "underlying": "Bitcoin Mining / Clean Energy",
        "sector": "crypto",
        "expense_ratio": 0.0,
        "avg_daily_volume": 10_000_000,
        "enabled": True,
    },
}

# ---------------------------------------------------------------------------
# 섹터 레버리지 ETF (Sector-level leveraged ETFs tracked as individual universe items)
# ---------------------------------------------------------------------------
SECTOR_LEVERAGED_UNIVERSE: dict[str, dict] = {
    "SOXL": {
        "name": "Direxion Daily Semiconductor Bull 3X ETF",
        "underlying": "Semiconductor Sector",
        "sector": "semiconductors",
        "expense_ratio": 0.75,
        "avg_daily_volume": 60_000_000,
        "enabled": True,
    },
    "SOXS": {
        "name": "Direxion Daily Semiconductor Bear 3X ETF",
        "underlying": "Semiconductor Sector Inverse",
        "sector": "semiconductors",
        "expense_ratio": 0.75,
        "avg_daily_volume": 30_000_000,
        "enabled": True,
    },
}

# ---------------------------------------------------------------------------
# 크립토 레버리지 ETF (섹터 레버리지 - INDIVIDUAL_STOCK_UNIVERSE에 추가)
# ---------------------------------------------------------------------------
CRYPTO_LEVERAGED_UNIVERSE: dict[str, dict] = {
    "BITX": {
        "name": "2x Bitcoin Strategy ETF (Volatility Shares)",
        "underlying": "Bitcoin / Crypto",
        "sector": "crypto",
        "expense_ratio": 1.85,
        "avg_daily_volume": 5_000_000,
        "enabled": True,
    },
    "CONL": {
        "name": "GraniteShares 2x Long COIN Daily ETF",
        "underlying": "Coinbase",
        "sector": "crypto",
        "expense_ratio": 1.15,
        "avg_daily_volume": 3_000_000,
        "enabled": True,
    },
    "ETHU": {
        "name": "2x Ether ETF (Volatility Shares)",
        "underlying": "Ethereum / Crypto",
        "sector": "crypto",
        "expense_ratio": 1.85,
        "avg_daily_volume": 2_000_000,
        "enabled": True,
    },
    "SBIT": {
        "name": "ProShares Short Bitcoin ETF",
        "underlying": "Bitcoin Inverse",
        "sector": "crypto",
        "expense_ratio": 0.95,
        "avg_daily_volume": 2_000_000,
        "enabled": True,
    },
    "MSTU": {
        "name": "T-Rex 2x Long MSTR Daily Target ETF",
        "underlying": "MicroStrategy",
        "sector": "crypto",
        "expense_ratio": 1.05,
        "avg_daily_volume": 5_000_000,
        "enabled": True,
    },
    "MSTZ": {
        "name": "T-Rex 2x Inverse MSTR Daily Target ETF",
        "underlying": "MicroStrategy Inverse",
        "sector": "crypto",
        "expense_ratio": 1.05,
        "avg_daily_volume": 3_000_000,
        "enabled": True,
    },
}

# ---------------------------------------------------------------------------
# Bull <-> Bear 매칭 테이블 (같은 기초지수 기반)
# ---------------------------------------------------------------------------
_INVERSE_PAIRS: dict[str, str] = {
    "SSO": "SDS",
    "QLD": "QID",
    "UWM": "TWM",
    "DDM": "DXD",
    "MVV": "MZZ",
    "ROM": "REW",
    "USD": "SSG",
    "UYG": "SKF",
    "DIG": "DUG",
    "URE": "SRS",
    "RXL": "RXD",
    "UXI": "SIJ",
    "UCC": "SCC",
    "UGE": "SZK",
}

# 역방향 매핑 자동 생성
_INVERSE_PAIRS.update({v: k for k, v in list(_INVERSE_PAIRS.items())})


# ---------------------------------------------------------------------------
# 조회 함수
# ---------------------------------------------------------------------------
def get_all_tickers() -> list[str]:
    """전체 종목 티커 리스트 반환 (Bull ETF + Bear ETF + 개별 주식 + 섹터 레버리지 + 크립토 레버리지)."""
    return sorted(
        list(BULL_2X_UNIVERSE.keys())
        + list(BEAR_2X_UNIVERSE.keys())
        + list(INDIVIDUAL_STOCK_UNIVERSE.keys())
        + list(SECTOR_LEVERAGED_UNIVERSE.keys())
        + list(CRYPTO_LEVERAGED_UNIVERSE.keys())
    )


def get_individual_stock_tickers(enabled_only: bool = False) -> list[str]:
    """개별 주요 주식 티커 리스트 반환.

    Args:
        enabled_only: True이면 활성 종목만 반환.
    """
    if enabled_only:
        return sorted(
            t for t, info in INDIVIDUAL_STOCK_UNIVERSE.items() if info["enabled"]
        )
    return sorted(INDIVIDUAL_STOCK_UNIVERSE.keys())


def get_enabled_tickers() -> list[str]:
    """활성(enabled=True) 종목만 반환."""
    enabled: list[str] = []
    for ticker, info in BULL_2X_UNIVERSE.items():
        if info["enabled"]:
            enabled.append(ticker)
    for ticker, info in BEAR_2X_UNIVERSE.items():
        if info["enabled"]:
            enabled.append(ticker)
    return sorted(enabled)


def get_bull_tickers(enabled_only: bool = False) -> list[str]:
    """Bull 2X 종목 리스트 반환.

    Args:
        enabled_only: True이면 활성 종목만 반환.
    """
    if enabled_only:
        return sorted(
            t for t, info in BULL_2X_UNIVERSE.items() if info["enabled"]
        )
    return sorted(BULL_2X_UNIVERSE.keys())


def get_bear_tickers(enabled_only: bool = False) -> list[str]:
    """Bear (Inverse) 2X 종목 리스트 반환.

    Args:
        enabled_only: True이면 활성 종목만 반환.
    """
    if enabled_only:
        return sorted(
            t for t, info in BEAR_2X_UNIVERSE.items() if info["enabled"]
        )
    return sorted(BEAR_2X_UNIVERSE.keys())


def get_ticker_info(ticker: str) -> Optional[dict]:
    """종목 상세 정보 반환.

    Args:
        ticker: 티커 심볼 (ETF 또는 개별 주식).

    Returns:
        종목 정보 딕셔너리 또는 None (유효하지 않은 티커).
    """
    ticker = ticker.upper()
    if ticker in BULL_2X_UNIVERSE:
        return {"ticker": ticker, "direction": "bull", **BULL_2X_UNIVERSE[ticker]}
    if ticker in BEAR_2X_UNIVERSE:
        return {"ticker": ticker, "direction": "bear", **BEAR_2X_UNIVERSE[ticker]}
    if ticker in INDIVIDUAL_STOCK_UNIVERSE:
        return {"ticker": ticker, "direction": "bull", **INDIVIDUAL_STOCK_UNIVERSE[ticker]}
    if ticker in SECTOR_LEVERAGED_UNIVERSE:
        return {"ticker": ticker, "direction": "bull", **SECTOR_LEVERAGED_UNIVERSE[ticker]}
    if ticker in CRYPTO_LEVERAGED_UNIVERSE:
        return {"ticker": ticker, "direction": "bull", **CRYPTO_LEVERAGED_UNIVERSE[ticker]}
    logger.warning("Unknown ticker requested: %s", ticker)
    return None


def get_inverse_pair(ticker: str) -> Optional[str]:
    """Bull<->Bear 반대 방향 종목 반환.

    Args:
        ticker: ETF 티커 심볼 (예: SSO -> SDS, SDS -> SSO).

    Returns:
        반대 방향 티커 또는 None.
    """
    ticker = ticker.upper()
    pair = _INVERSE_PAIRS.get(ticker)
    if pair is None:
        logger.debug("No inverse pair found for: %s", ticker)
    return pair


def is_valid_ticker(ticker: str) -> bool:
    """유니버스에 포함된 유효한 티커인지 확인 (ETF + 개별 주식 + 섹터/크립토 레버리지 포함)."""
    ticker = ticker.upper()
    return (
        ticker in BULL_2X_UNIVERSE
        or ticker in BEAR_2X_UNIVERSE
        or ticker in INDIVIDUAL_STOCK_UNIVERSE
        or ticker in SECTOR_LEVERAGED_UNIVERSE
        or ticker in CRYPTO_LEVERAGED_UNIVERSE
    )
