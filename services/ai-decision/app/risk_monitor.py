"""AI 决策服务 - 风险监控器

实时监控持仓和市场状态，触发风险预警。
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel
from loguru import logger


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RiskAlert(BaseModel):
    """风险预警"""
    alert_type: str        # 预警类型
    level: AlertLevel      # 预警级别
    title: str             # 预警标题
    description: str       # 详细描述
    suggestion: str        # 建议操作
    metrics: dict = {}     # 相关指标


class PortfolioState(BaseModel):
    """投资组合状态"""
    positions: dict = {}           # {sector_code: weight}
    total_assets: float = 0.0      # 总资产
    daily_pnl: float = 0.0         # 当日盈亏
    cum_return: float = 0.0        # 累计收益
    max_drawdown: float = 0.0      # 最大回撤
    market_change: float = 0.0     # 大盘涨跌幅
    market_sentiment: str = "中性"  # 市场情绪


class RiskMonitor:
    """风险监控器"""

    # 风险阈值配置（百分比单位，如 2.0 = 2%）
    THRESHOLDS = {
        "concentration_warn": 0.35,      # 单板块仓位预警线（权重0-1）
        "concentration_critical": 0.50,   # 单板块仓位警戒线
        "daily_loss_warn": 1.5,           # 当日亏损预警线（%）
        "daily_loss_critical": 3.0,       # 当日亏损警戒线（%）
        "drawdown_warn": 5.0,             # 回撤预警线（%）
        "drawdown_critical": 10.0,        # 回撤警戒线（%）
        "market_drop_warn": 1.0,          # 大盘跌幅预警（%）
        "market_drop_critical": 2.5,      # 大盘跌幅警戒（%）
    }

    def check_portfolio(self, state: PortfolioState) -> list[RiskAlert]:
        """检查投资组合风险"""
        alerts = []

        alerts.extend(self._check_concentration(state))
        alerts.extend(self._check_daily_loss(state))
        alerts.extend(self._check_drawdown(state))
        alerts.extend(self._check_market_risk(state))

        return alerts

    def _check_concentration(self, state: PortfolioState) -> list[RiskAlert]:
        """检查仓位集中度"""
        alerts = []
        for sector, weight in state.positions.items():
            if weight >= self.THRESHOLDS["concentration_critical"]:
                alerts.append(RiskAlert(
                    alert_type="concentration",
                    level=AlertLevel.CRITICAL,
                    title=f"仓位严重集中: {sector}",
                    description=f"板块 {sector} 仓位占比 {weight*100:.0f}%，超过 {self.THRESHOLDS['concentration_critical']*100:.0f}% 警戒线",
                    suggestion="建议立即分散仓位，单板块不超过 40%",
                    metrics={"sector": sector, "weight": weight, "threshold": self.THRESHOLDS["concentration_critical"]},
                ))
            elif weight >= self.THRESHOLDS["concentration_warn"]:
                alerts.append(RiskAlert(
                    alert_type="concentration",
                    level=AlertLevel.WARNING,
                    title=f"仓位集中度偏高: {sector}",
                    description=f"板块 {sector} 仓位占比 {weight*100:.0f}%，超过 {self.THRESHOLDS['concentration_warn']*100:.0f}% 预警线",
                    suggestion="建议适当分散仓位",
                    metrics={"sector": sector, "weight": weight, "threshold": self.THRESHOLDS["concentration_warn"]},
                ))
        return alerts

    def _check_daily_loss(self, state: PortfolioState) -> list[RiskAlert]:
        """检查当日亏损"""
        alerts = []
        if state.daily_pnl <= -self.THRESHOLDS["daily_loss_critical"]:
            alerts.append(RiskAlert(
                alert_type="daily_loss",
                level=AlertLevel.CRITICAL,
                title="当日亏损超警戒线",
                description=f"当日亏损 {abs(state.daily_pnl):.2f}%，超过 {self.THRESHOLDS['daily_loss_critical']:.0f}% 警戒线",
                suggestion="建议暂停交易，评估市场状况",
                metrics={"daily_pnl": state.daily_pnl, "threshold": self.THRESHOLDS["daily_loss_critical"]},
            ))
        elif state.daily_pnl <= -self.THRESHOLDS["daily_loss_warn"]:
            alerts.append(RiskAlert(
                alert_type="daily_loss",
                level=AlertLevel.WARNING,
                title="当日亏损预警",
                description=f"当日亏损 {abs(state.daily_pnl):.2f}%，接近止损线",
                suggestion="建议密切关注持仓，做好止损准备",
                metrics={"daily_pnl": state.daily_pnl, "threshold": self.THRESHOLDS["daily_loss_warn"]},
            ))
        return alerts

    def _check_drawdown(self, state: PortfolioState) -> list[RiskAlert]:
        """检查回撤"""
        alerts = []
        if state.max_drawdown >= self.THRESHOLDS["drawdown_critical"]:
            alerts.append(RiskAlert(
                alert_type="drawdown",
                level=AlertLevel.CRITICAL,
                title="最大回撤超警戒线",
                description=f"最大回撤 {state.max_drawdown:.2f}%，超过 {self.THRESHOLDS['drawdown_critical']:.0f}% 警戒线",
                suggestion="建议暂停策略，全面评估风险",
                metrics={"max_drawdown": state.max_drawdown, "threshold": self.THRESHOLDS["drawdown_critical"]},
            ))
        elif state.max_drawdown >= self.THRESHOLDS["drawdown_warn"]:
            alerts.append(RiskAlert(
                alert_type="drawdown",
                level=AlertLevel.WARNING,
                title="回撤预警",
                description=f"最大回撤 {state.max_drawdown:.2f}%，接近警戒水平",
                suggestion="建议降低仓位，收紧止损",
                metrics={"max_drawdown": state.max_drawdown, "threshold": self.THRESHOLDS["drawdown_warn"]},
            ))
        return alerts

    def _check_market_risk(self, state: PortfolioState) -> list[RiskAlert]:
        """检查市场风险"""
        alerts = []
        if state.market_change <= -self.THRESHOLDS["market_drop_critical"]:
            alerts.append(RiskAlert(
                alert_type="market_drop",
                level=AlertLevel.CRITICAL,
                title="市场大幅下跌",
                description=f"大盘跌幅 {abs(state.market_change):.2f}%，市场恐慌情绪蔓延",
                suggestion="建议减仓观望，等待企稳信号",
                metrics={"market_change": state.market_change, "threshold": self.THRESHOLDS["market_drop_critical"]},
            ))
        elif state.market_change <= -self.THRESHOLDS["market_drop_warn"]:
            alerts.append(RiskAlert(
                alert_type="market_drop",
                level=AlertLevel.WARNING,
                title="市场下跌预警",
                description=f"大盘跌幅 {abs(state.market_change):.2f}%，注意控制风险",
                suggestion="建议关注持仓板块资金流向",
                metrics={"market_change": state.market_change, "threshold": self.THRESHOLDS["market_drop_warn"]},
            ))
        return alerts


# 全局实例
risk_monitor = RiskMonitor()
