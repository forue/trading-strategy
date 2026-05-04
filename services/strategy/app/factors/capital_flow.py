"""资金流因子 - 主力净流入 + 北向资金"""
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


# 注册因子
FactorRegistry.register(MainFlowFactor())
FactorRegistry.register(NorthFlowFactor())
