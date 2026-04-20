"""策略引擎服务 - 数据模型"""
from pydantic import BaseModel
from typing import Optional
from enum import Enum


class StrategyType(str, Enum):
    AGGRESSIVE = "AGGRESSIVE"
    MODERATE = "MODERATE"
    CONSERVATIVE = "CONSERVATIVE"


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class StrategyParams(BaseModel):
    top_n: int = 3
    max_position: float = 0.5
    hold_days: int = 5
    capital_pct: float = 0.3
    stop_loss: float = 0.03
    valuation_pct_max: Optional[float] = None
    # 交易成本参数
    commission_rate: float = 0.0003    # 佣金费率，默认万三
    stamp_tax_rate: float = 0.001     # 印花税率，默认千一（仅卖出）
    slippage_rate: float = 0.001      # 滑点费率，默认千一


class TradeSignal(BaseModel):
    id: Optional[int] = None
    signal_date: str
    strategy_type: StrategyType
    sector_code: str
    sector_name: str
    etf_code: Optional[str] = None
    etf_name: Optional[str] = None
    direction: SignalDirection
    position_ratio: float
    score: float
    reason: str
    rank: Optional[int] = None
    total_sectors: Optional[int] = None
    created_at: Optional[str] = None


class StrategyConfig(BaseModel):
    id: Optional[int] = None
    strategy_type: StrategyType
    name: str
    params: StrategyParams
    is_active: bool = True


class BacktestRequest(BaseModel):
    strategy_type: StrategyType
    start_date: str
    end_date: str
    initial_capital: float = 1000000.0
    # 可选的策略参数覆盖，不传则使用默认配置
    params: Optional[StrategyParams] = None


class BacktestResult(BaseModel):
    id: Optional[str] = None
    strategy_type: StrategyType = StrategyType.MODERATE
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 1000000.0
    total_return: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0
    # 交易成本统计
    total_commission: float = 0.0
    total_stamp_tax: float = 0.0
    total_slippage_cost: float = 0.0
    total_trade_cost: float = 0.0
    trade_count_actual: int = 0
    nav_curve: list = []
    created_at: Optional[str] = None
