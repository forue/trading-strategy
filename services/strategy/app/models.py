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
    # 回撤控制 - 多重止损
    trailing_stop_loss: float = 0.08       # 移动止损：从最高点回撤超过此比例触发
    max_drawdown_stop: float = 0.15        # 最大回撤止损：累计回撤超过此比例清仓
    benchmark_stop_loss: float = 0.10      # 基准相对止损：落后大盘超过此比例触发
    ma_stop_days: int = 20                 # 均线止损：跌破N日均线超过阈值触发
    ma_stop_loss: float = 0.05             # 均线止损阈值
    # 阶梯式均线止盈（可选，设为空列表不启用）
    ma_take_profit_days: int = 20          # 均线止盈窗口天数
    ma_take_profit_thresholds: list = [0.05, 0.03, 0.01]  # 各级触发阈值：NAV回落至均线上方X%以内时减仓（递减序列）
    ma_take_profit_ratios: list = [0.3, 0.4, 0.3]         # 各级减仓比例（按原始仓位计算）
    # 趋势确认与宽松止损（治本：减少牛市低点踏空与无效止盈）
    stop_loss_mode: str = "fixed"         # 止损模式: "fixed"=沿用多重固定止损; "trend_break"=仅在趋势破位时止损
    trend_confirm: bool = False            # 强趋势中跳过阶梯止盈，让利润奔跑（减少逆势干预）
    trend_ma_days: int = 60                # 趋势破位判定的长均线窗口（仅 stop_loss_mode="trend_break" 生效）
    drawdown_ma_window: int = 20           # 回撤控制用的均线窗口
    valuation_pct_max: Optional[float] = None
    # 交易成本参数
    commission_rate: float = 0.0003    # 佣金费率，默认万三
    stamp_tax_rate: float = 0.001     # 印花税率，默认千一（仅卖出）
    slippage_rate: float = 0.001      # 滑点费率，默认千一
    # 无风险利率（年化）：用于夏普比率与空仓资金计息
    risk_free_rate: float = 0.02
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
    # BEAR空仓恢复回补门控：0=关闭(出厂行为,当日不再确认BEAR即回补)；
    # N>0=BEAR清仓后需连续N日非BEAR(当日BULL也不放行)才允许重新建仓，压制"弱反弹首日追高、
    # 下跌中继二次套牢"型回撤；代价是牺牲BEAR后大概率反弹的快速回补收益，默认保持0
    bear_reentry_days: int = 0


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
    position_changes: list = []  # 仓位调整明细：加仓/减仓/清仓
    created_at: Optional[str] = None


class FactorAnalyzeRequest(BaseModel):
    """因子分析请求"""
    sector_code: str
    strategy_type: str = "MODERATE"
    date: Optional[str] = None
