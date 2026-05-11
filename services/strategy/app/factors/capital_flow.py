"""资金流因子 - 主力净流入 + 北向资金 + 资金流加速度"""
import numpy as np
from .base import BaseFactor, FactorResult, FactorCategory, FactorRegistry


class MainFlowFactor(BaseFactor):
    """主力资金净流入因子

    衡量板块主力资金的绝对强度和相对强度。
    数据来源: 板块当日 main_net_inflow 字段 (单位: 元)
    """

    name = "main_flow"
    category = FactorCategory.CAPITAL_FLOW
    default_weight = 0.25

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        main_flow = sector_data.get("main_net_inflow", 0)
        turnover = sector_data.get("turnover", 0)

        # 资金流强度 (亿元)
        flow_yi = main_flow / 1e8

        # 资金流入比率 = 主力净流入 / 成交额
        flow_ratio = main_flow / turnover if turnover > 0 else 0.0

        # 评分: 以1亿为基准单位
        # flow_yi = 0 → 5分, flow_yi = 2亿 → 10分, flow_yi = -2亿 → 0分
        score = self.clamp(5.0 + flow_yi * 2.5)

        # 置信度: 成交额越大越可靠
        confidence = min(1.0, turnover / 1e9) if turnover > 0 else 0.3

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=main_flow,
            score=round(score, 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={
                "flow_yi": round(flow_yi, 2),
                "flow_ratio": round(flow_ratio, 4),
                "turnover_yi": round(turnover / 1e8, 2) if turnover > 0 else 0,
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return "main_net_inflow" in sector_data


class NorthFlowFactor(BaseFactor):
    """北向资金净流入因子

    衡量外资对板块的偏好程度。
    数据来源: 板块当日 north_net_inflow 字段 (单位: 元)
    """

    name = "north_flow"
    category = FactorCategory.CAPITAL_FLOW
    default_weight = 0.10

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        north_flow = sector_data.get("north_net_inflow", 0)

        # 北向资金强度 (亿元)
        flow_yi = north_flow / 1e8

        # 评分: 以0.5亿为基准单位
        score = self.clamp(5.0 + flow_yi * 5.0)

        # 北向资金数据可能缺失，置信度较低
        confidence = 0.7 if north_flow != 0 else 0.3

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=north_flow,
            score=round(score, 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={
                "flow_yi": round(flow_yi, 2),
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return "north_net_inflow" in sector_data


class FlowAccelerationFactor(BaseFactor):
    """资金流加速度因子

    资金流变化的二阶导数，捕捉资金加速流入或流出拐点。
    计算: Δflow_t = flow_t - flow_{t-1}, Δ²flow_t = Δflow_t - Δflow_{t-1}
    正加速度 = 资金流入在加速 (看涨信号)
    负加速度 = 资金流入在减速 (看跌信号)

    需要至少 3 个交易日的历史资金流数据。
    """

    name = "flow_acceleration"
    category = FactorCategory.CAPITAL_FLOW
    default_weight = 0.03
    min_history_days = 3

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        today_flow = sector_data.get("main_net_inflow", 0)

        if not history or len(history) < 3:
            return FactorResult(
                name=self.name,
                category=self.category,
                raw_value=0,
                score=5.0,
                weight=self.default_weight,
                confidence=0.0,
                detail={"error": "历史资金流数据不足(需>=3天)"},
            )

        flows = [h.get("main_net_inflow", 0) for h in history[-3:]]
        flows.append(today_flow)
        d1 = flows[-1] - flows[-2]
        d2 = flows[-2] - flows[-3]
        acceleration = d1 - d2

        acc_yi = acceleration / 1e8

        # 评分: 加速度为正=资金加速流入, 每1亿加速度 +2分
        score = self.clamp(5.0 + acc_yi * 2.0)

        confidence = 0.65 if all(f != 0 for f in flows[-3:]) else 0.4

        direction = "accelerating_in" if acceleration > 0 else "decelerating" if acceleration < 0 else "steady"

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=acceleration,
            score=round(score, 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={
                "acceleration_yi": round(acc_yi, 2),
                "d1_yi": round(d1 / 1e8, 2),
                "d2_yi": round(d2 / 1e8, 2),
                "direction": direction,
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        if "main_net_inflow" not in sector_data:
            return False
        return history is not None and len(history) >= self.min_history_days


# 注册因子
FactorRegistry.register(MainFlowFactor())
FactorRegistry.register(NorthFlowFactor())
FactorRegistry.register(FlowAccelerationFactor())
