"""策略优化：合成置信度、截面上下文、ETF 映射、轮动参数。"""
from collections import defaultdict

import pytest

from services.strategy.app.combiner.weighted import FactorCombiner, DEFAULT_WEIGHTS, StrategyWeights
from services.strategy.app.factors.base import FactorCategory, FactorResult, FactorRegistry
from services.strategy.app.models import StrategyParams, StrategyType
from services.strategy.app.scoring import SECTOR_ETF_MAP, RotationScoringModel, scoring_model


def test_combine_weighted_uses_confidence():
    """置信度为 0 的因子不参与类内加权。"""
    combiner = FactorCombiner()
    results = [
        FactorResult(
            name="a", category=FactorCategory.MOMENTUM,
            raw_value=1, score=9.0, weight=1.0, confidence=1.0, detail={},
        ),
        FactorResult(
            name="b", category=FactorCategory.MOMENTUM,
            raw_value=0, score=2.0, weight=1.0, confidence=0.0, detail={"error": "x"},
        ),
    ]
    w = StrategyWeights(momentum=1.0, capital_flow=0, technical=0, sentiment=0, valuation=0, rotation=0)
    score, _ = combiner.combine_weighted(results, w)
    assert score == 9.0


def test_cross_section_context_merge():
    d1 = [
        {
            "sector_code": "A",
            "_history": [
                {"date": "2026-01-01", "index_change_pct": 2.0},
                {"date": "2026-01-02", "index_change_pct": -1.0},
            ],
        },
        {
            "sector_code": "B",
            "_history": [
                {"date": "2026-01-01", "index_change_pct": 1.0},
                {"date": "2026-01-02", "index_change_pct": 3.0},
            ],
        },
    ]
    ctx = RotationScoringModel._build_cross_section_context(d1)
    peers = ctx["changes_by_date"]["2026-01-01"]
    assert peers["A"] == 2.0 and peers["B"] == 1.0


def test_effective_score_gap_relative():
    p = StrategyParams(score_gap_threshold=1.0, use_relative_score_gap=True, relative_score_gap_ratio=0.1)
    thr = RotationScoringModel._effective_score_gap_threshold(8.0, 6.0, p, 1.5)
    assert thr >= 1.0
    assert thr >= 0.1 * max(8.0, 6.0, 1.0)


def test_market_filter_aggressive_vs_moderate():
    sectors = [{"composite_score": 1.0, "index_change_pct": -1.0} for _ in range(15)]
    for i in range(3):
        sectors[i]["composite_score"] = 2.5
    p = StrategyParams(min_score_threshold=2.0)
    assert scoring_model._market_is_favorable(sectors, StrategyType.AGGRESSIVE, p) is True
    p2 = StrategyParams(min_score_threshold=4.0)
    assert scoring_model._market_is_favorable(sectors, StrategyType.MODERATE, p2) is False


def test_sector_etf_map_entries():
    for k, v in SECTOR_ETF_MAP.items():
        assert "code" in v and "name" in v
        assert len(v["code"]) >= 4


def test_etf_fan_in_report():
    """同一 ETF 代码对应多板块时记录集中度（软断言，便于后续清理映射）。"""
    by_etf = defaultdict(list)
    for sector_key, v in SECTOR_ETF_MAP.items():
        by_etf[v["code"]].append(sector_key)
    fan = {c: ss for c, ss in by_etf.items() if len(ss) > 1}
    assert isinstance(fan, dict)
    # 已知存在共用 ETF，仅保证数量在合理上限内以便回归发现异常膨胀
    assert max(len(v) for v in fan.values()) <= 25


def test_default_weights_sum_to_one():
    for k, sw in DEFAULT_WEIGHTS.items():
        d = sw.model_dump()
        assert abs(sum(d.values()) - 1.0) < 1e-6, k
