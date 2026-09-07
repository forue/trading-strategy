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


# 三档策略默认权重（含新增 ma_trend/mfi/sector_dispersion）
DEFAULT_WEIGHTS = {
    "AGGRESSIVE": StrategyWeights(
        capital_flow=0.28, momentum=0.18, technical=0.17, sentiment=0.07, valuation=0.25, rotation=0.05,
    ),
    "MODERATE": StrategyWeights(
        capital_flow=0.30, momentum=0.20, technical=0.27, sentiment=0.13, valuation=0.05, rotation=0.05,
    ),
    "CONSERVATIVE": StrategyWeights(
        capital_flow=0.23, momentum=0.10, technical=0.23, sentiment=0.19, valuation=0.14, rotation=0.11,
    ),
}


def get_dynamic_weights(strategy_type: str, market_regime: str = "NEUTRAL") -> StrategyWeights:
    """根据市场环境动态调整因子权重

    - 牛市: 加大动量+技术权重，降低估值权重（追涨有效）
    - 熊市: 加大估值+情绪权重，降低动量权重（均值回归有效）
    - 震荡: 保持默认

    Args:
        strategy_type: AGGRESSIVE / MODERATE / CONSERVATIVE
        market_regime: BULL / NEUTRAL / BEAR
    """
    base = DEFAULT_WEIGHTS.get(strategy_type, DEFAULT_WEIGHTS["MODERATE"])

    if market_regime == "BULL":
        # 牛市: 动量+10%, 技术+5%, 估值-10%, 资金流-5%
        return StrategyWeights(
            capital_flow=max(0, base.capital_flow - 0.05),
            momentum=min(1.0, base.momentum + 0.10),
            technical=min(1.0, base.technical + 0.05),
            sentiment=base.sentiment,
            valuation=max(0, base.valuation - 0.10),
            rotation=base.rotation,
        )
    elif market_regime == "BEAR":
        # 熊市: 估值+10%, 情绪+5%, 动量-10%, 资金流-5%
        return StrategyWeights(
            capital_flow=max(0, base.capital_flow - 0.05),
            momentum=max(0, base.momentum - 0.10),
            technical=base.technical,
            sentiment=min(1.0, base.sentiment + 0.05),
            valuation=min(1.0, base.valuation + 0.10),
            rotation=min(1.0, base.rotation + 0.05),
        )
    else:
        return base


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

        # 类别内加权合成（因子置信度参与权重，全为 0 的类别不参与类间合成）
        category_avg: dict[str, float] = {}
        category_detail: dict[str, dict] = {}
        for cat, factors in category_scores.items():
            eff_denom = sum(f.weight * max(f.confidence, 0.0) for f in factors)
            if eff_denom > 1e-12:
                avg_score = sum(
                    f.score * f.weight * max(f.confidence, 0.0) for f in factors
                ) / eff_denom
            else:
                continue
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

        # 归一化（全部因子置信度为 0 时无可用类别）
        if total_category_weight > 0:
            composite_score /= total_category_weight
        else:
            composite_score = 5.0

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

        # 构建因子权重映射 (使用类别权重 × 因子权重；合并多板块样本避免仅用首板块)
        factor_weight_map: dict[str, float] = {}
        for results in all_sector_results.values():
            for r in results:
                cat_weight = getattr(weights, r.category.value, 0)
                w = r.weight * cat_weight
                prev = factor_weight_map.get(r.name, 0.0)
                if w > prev:
                    factor_weight_map[r.name] = w

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
