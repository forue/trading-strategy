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
    # 调仓优化参数
    min_score_threshold: float = 4.0      # 最低评分阈值，低于此评分不买入
    score_gap_threshold: float = 1.5        # 评分差异阈值，新信号评分需高于当前持仓此阈值才调仓
    cooldown_days: int = 2                  # 调仓冷却期额外的交易日间隔
    keep_overlap: bool = True               # 是否保留重叠持仓
    allow_empty: bool = True               # 市场不景气时是否允许空仓
    min_score_keep: float = 5.0            # 持仓保留阈值，评分高于此值可保留
    # 截面与合成
    cross_section_alpha: float = 0.35   # 综合分 = (1-α)*绝对分 + α*截面排名分；0 表示纯绝对分
    # 调仓阈值：相对缺口与绝对缺口取较大，抑制分数整体漂移时的噪声交易
    use_relative_score_gap: bool = True
    relative_score_gap_ratio: float = 0.06  # 相对基准：max(ε, |当前|, |新建议|) 的比例
    score_gap_epsilon: float = 1e-6
    # 仓位：在入选标的中按波动率倒数分配（无波动数据时回退等权）
    use_inverse_vol_weights: bool = True
    # 截面 Z-Score 归一化：将因子硬阈值评分替换为板块间相对排名得分
    use_zscore_normalization: bool = True
    # 动态市场状态参数
    market_bull_threshold: float = 0.5    # 上涨板块占比达到此值为牛市
    market_bear_threshold: float = 0.4    # 上涨板块占比低于此值为熊市
    favorable_confirm_days: int = 2       # 连续 N 天同向状态才确认
    max_empty_days: int = 10              # 最大空仓天数，超时强制试探建仓
    capital_pct_bull_boost: float = 0.3   # 牛市加仓比例
    emergency_exit_score: float = 1.0     # 持仓板块评分低于此值触发紧急退出


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


class FactorAnalyzeRequest(BaseModel):
    """因子分析请求"""
    sector_code: str
    strategy_type: str = "MODERATE"
    date: Optional[str] = None
