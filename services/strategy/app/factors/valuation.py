"""估值因子 - PE/PB 分位"""
from .base import BaseFactor, FactorResult, FactorCategory, FactorRegistry


class PEPercentileFactor(BaseFactor):
    """PE分位因子

    衡量板块当前估值在历史中的位置。
    低分位 = 便宜 = 买入机会
    """

    name = "pe_percentile"
    category = FactorCategory.VALUATION
    default_weight = 0.05

    def calculate(self, sector_data: dict, history: list = None) -> FactorResult:
        pe_percentile = sector_data.get("pe_percentile")

        if pe_percentile is None:
            return FactorResult(
                name=self.name,
                category=self.category,
                raw_value=0,
                score=5.0,
                weight=self.default_weight,
                confidence=0.0,
                detail={"error": "PE分位数据缺失"},
            )

        # 评分: 低分位 = 高分 (价值投资逻辑)
        # PE分位 0% → 10分, 50% → 5分, 100% → 0分
        score = 10.0 - pe_percentile / 10.0 * 10.0

        confidence = 0.8

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=pe_percentile,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={"pe_percentile": round(pe_percentile, 2)},
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return "pe_percentile" in sector_data and sector_data["pe_percentile"] is not None


class PBPercentileFactor(BaseFactor):
    """PB分位因子

    衡量板块当前市净率在历史中的位置。
    """

    name = "pb_percentile"
    category = FactorCategory.VALUATION
    default_weight = 0.05

    def calculate(self, sector_data: dict, history: list = None) -> FactorResult:
        pb_percentile = sector_data.get("pb_percentile")

        if pb_percentile is None:
            return FactorResult(
                name=self.name,
                category=self.category,
                raw_value=0,
                score=5.0,
                weight=self.default_weight,
                confidence=0.0,
                detail={"error": "PB分位数据缺失"},
            )

        # 评分: 低分位 = 高分
        score = 10.0 - pb_percentile / 10.0 * 10.0

        confidence = 0.8

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=pb_percentile,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={"pb_percentile": round(pb_percentile, 2)},
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return "pb_percentile" in sector_data and sector_data["pb_percentile"] is not None


# 注册因子
FactorRegistry.register(PEPercentileFactor())
FactorRegistry.register(PBPercentileFactor())
