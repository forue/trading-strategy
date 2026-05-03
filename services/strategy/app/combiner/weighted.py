"""因子合成引擎 - 加权合成 / 排名合成"""
from typing import Optional
from pydantic import BaseModel
from loguru import logger
from ..factors.base import FactorResult, FactorCategory


class StrategyWeights(BaseModel):
    """策略权重配置"""
    capital_flow: float = 0.35
    momentum: float = 0.25
    technical: float = 0.25
    sentiment: float = 0.10
    valuation: float = 0.05
    rotation: float = 0.0


# 三档策略默认权重
DEFAULT_WEIGHTS = {
    "AGGRESSIVE": StrategyWeights(
        capital_flow=0.50, momentum=0.35, technical=0.10, sentiment=0.05, valuation=0.0, rotation=0.0,
    ),
    "MODERATE": StrategyWeights(
        capital_flow=0.35, momentum=0.25, technical=0.25, sentiment=0.10, valuation=0.05, rotation=0.0,
    ),
    "CONSERVATIVE": StrategyWeights(
        capital_flow=0.25, momentum=0.15, technical=0.25, sentiment=0.15, valuation=0.15, rotation=0.05,
    ),
}


class FactorCombiner:
    """因子合成引擎"""

    def combine_weighted(self, results: list[FactorResult], weights: Optional[StrategyWeights] = None) -> tuple[float, dict]:
        """加权合成

        Args:
            results: 因子计算结果列表
            weights: 策略权重配置

        Returns:
            (综合评分, 分类得分详情)
        """
        if not results:
            return 0.0, {}

        if weights is None:
            weights = DEFAULT_WEIGHTS["MODERATE"]

        # 按类别分组
        category_scores: dict[str, list[FactorResult]] = {}
        for r in results:
            cat = r.category.value
            if cat not in category_scores:
                category_scores[cat] = []
            category_scores[cat].append(r)

        # 类别内加权合成
        category_avg: dict[str, float] = {}
        category_detail: dict[str, dict] = {}
        for cat, factors in category_scores.items():
            total_weight = sum(f.weight for f in factors)
            if total_weight > 0:
                avg_score = sum(f.score * f.weight for f in factors) / total_weight
            else:
                avg_score = sum(f.score for f in factors) / len(factors) if factors else 0
            category_avg[cat] = avg_score
            category_detail[cat] = {
                "score": round(avg_score, 2),
                "factors": [{"name": f.name, "score": f.score, "weight": f.weight, "confidence": f.confidence} for f in factors],
            }

        # 类别间加权合成
        weight_map = weights.model_dump()
        total_category_weight = 0
        composite_score = 0
        for cat, score in category_avg.items():
            w = weight_map.get(cat, 0)
            composite_score += score * w
            total_category_weight += w

        # 归一化
        if total_category_weight > 0:
            composite_score /= total_category_weight

        return round(composite_score, 2), category_detail

    def combine_ranking(self, all_sector_results: dict[str, list[FactorResult]], 
                        weights: Optional[StrategyWeights] = None) -> dict[str, float]:
        """排名合成

        对每个因子，将所有板块的得分转为百分位排名，再加权合成。
        适用于需要相对排名的场景。

        Args:
            all_sector_results: {sector_code: [FactorResult, ...]}

        Returns:
            {sector_code: composite_score}
        """
        if not all_sector_results:
            return {}

        # 收集所有因子名称
        factor_names = set()
        for results in all_sector_results.values():
            for r in results:
                factor_names.add(r.name)

        # 对每个因子计算排名
        sector_rank_scores: dict[str, dict[str, float]] = {s: {} for s in all_sector_results}

        for factor_name in factor_names:
            # 收集该因子的所有板块得分
            factor_scores = {}
            for sector, results in all_sector_results.items():
                for r in results:
                    if r.name == factor_name:
                        factor_scores[sector] = r.score
                        break

            if not factor_scores:
                continue

            # 计算百分位排名
            sorted_sectors = sorted(factor_scores.keys(), key=lambda s: factor_scores[s])
            n = len(sorted_sectors)
            for rank, sector in enumerate(sorted_sectors):
                percentile = rank / max(n - 1, 1) * 10
                sector_rank_scores[sector][factor_name] = percentile

        # 加权合成排名得分
        if weights is None:
            weights = DEFAULT_WEIGHTS["MODERATE"]

        # 构建因子权重映射 (使用类别权重)
        factor_weight_map = {}
        for results in list(all_sector_results.values()):
            for r in results:
                cat_weight = getattr(weights, r.category.value, 0)
                factor_weight_map[r.name] = r.weight * cat_weight
            break  # 只需遍历一次获取因子结构

        # 计算每个板块的综合排名得分
        final_scores = {}
        for sector, rank_scores in sector_rank_scores.items():
            total = 0
            total_weight = 0
            for factor_name, score in rank_scores.items():
                w = factor_weight_map.get(factor_name, 0.01)
                total += score * w
                total_weight += w
            final_scores[sector] = round(total / total_weight, 2) if total_weight > 0 else 5.0

        return final_scores
