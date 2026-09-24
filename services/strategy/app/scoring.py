"""策略引擎服务 - 板块轮动评分模型核心算法"""
from collections import defaultdict
import json
import math
import time
import numpy as np
from datetime import datetime
from loguru import logger
from typing import Any, Optional

import os
import sys

# 引入共享库（services/shared）：板块→ETF 映射的唯一来源
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.sector_etf_map import SECTOR_MAP, SECTOR_ETF_MAP, SECTOR_ETF_CANDIDATES

from .models import StrategyType, StrategyParams, TradeSignal, SignalDirection

# 导入因子引擎
from .factors import FactorRegistry, FactorResult, FactorCategory
from .combiner import FactorCombiner, DEFAULT_WEIGHTS


# 板块→ETF 映射已抽到 services/shared/sector_etf_map.py（全系统单一映射源）
# ETF表现缓存 {code: (score, timestamp)}
_etf_score_cache: dict[str, tuple[float, float]] = {}
_ETF_SCORE_TTL = 1800  # 30分钟


def _score_etf(code: str) -> float:
    """计算ETF综合评分（基于30天数据）

    评分公式: 0.4 * 流动性 + 0.3 * 收益动量 + 0.3 * 回撤控制
    - 流动性: log10(日均成交额)，归一化到0-10
    - 收益动量: 30日累计收益率，归一化到0-10
    - 回撤控制: 30日最大回撤(负值)，越小越好，归一化到0-10
    """
    now = time.time()
    if code in _etf_score_cache:
        score, ts = _etf_score_cache[code]
        if now - ts < _ETF_SCORE_TTL:
            return score

    try:
        import akshare as ak
        from datetime import datetime, timedelta
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=45)).strftime("%Y%m%d")
        df = ak.fund_etf_hist_em(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")

        if df is None or df.empty or len(df) < 5:
            _etf_score_cache[code] = (5.0, now)
            return 5.0

        closes = df["收盘"].astype(float).tolist()
        volumes = df["成交额"].astype(float).tolist()

        # 收益动量 (30日累计)
        ret = (closes[-1] / closes[0] - 1) * 100 if closes[0] > 0 else 0
        ret_score = max(0, min(10, 5 + ret * 0.5))

        # 最大回撤
        peak = closes[0]
        max_dd = 0
        for c in closes:
            if c > peak:
                peak = c
            dd = (peak - c) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)
        dd_score = max(0, min(10, 10 - max_dd * 0.5))

        # 流动性 (日均成交额)
        avg_vol = sum(volumes) / max(len(volumes), 1)
        liq_score = max(0, min(10, 3 + (avg_vol / 1e8) * 2))

        total = ret_score * 0.3 + dd_score * 0.3 + liq_score * 0.4

        # NaN/Infinity 防护
        if math.isnan(total) or math.isinf(total):
            logger.warning(f"ETF {code} 评分产生异常值: {total}, ret={ret}, max_dd={max_dd}, avg_vol={avg_vol}, 回退到默认值5.0")
            _etf_score_cache[code] = (5.0, now)
            return 5.0

        _etf_score_cache[code] = (round(total, 2), now)
        return round(total, 2)
    except Exception as e:
        logger.warning(f"ETF {code} 评分异常: {e}")
        _etf_score_cache[code] = (5.0, now)
        return 5.0


def _rank_etf_candidates(sector_name: str) -> list[dict]:
    """获取板块的ETF候选列表，按评分排序"""
    candidates = SECTOR_ETF_CANDIDATES.get(sector_name, [])
    if not candidates:
        return []
    scored = []
    for etf in candidates:
        s = _score_etf(etf["code"])
        scored.append({**etf, "score": s})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


class RotationScoringModel:
    """板块资金轮动评分模型

    评分维度：
    1. 资金强度：主力资金净流入的绝对值和相对强度
    2. 资金斜率：过去N日资金净流入的趋势斜率
    3. 相对强弱：指数涨幅相对大盘的超额收益
    4. 估值分位：当前估值在历史中的分位数（仅保守策略）
    """

    def __init__(self):
        self.sector_codes = list(SECTOR_MAP.keys())

    @staticmethod
    def _norm_hist_date(d: Any) -> str:
        if d is None:
            return ""
        return str(d)[:10]

    @staticmethod
    def _build_cross_section_context(sector_data_list: list[dict]) -> dict[str, Any]:
        """按交易日聚合全板块涨跌幅，供截面类因子使用。

        同时包含今日截面（从 sector_data_list 自身的 index_change_pct 提取），
        以及历史截面（从各板块的 _history 中提取）。
        """
        by_date: dict[str, dict[str, float]] = defaultdict(dict)

        # 今日截面：从 sector_data_list 中直接提取
        today_candidates: set[str] = set()
        for item in sector_data_list:
            code = item.get("sector_code")
            if not code:
                continue
            pct = item.get("index_change_pct")
            if pct is None:
                continue
            d = RotationScoringModel._norm_hist_date(item.get("date"))
            today_candidates.add(d)
            by_date[d][str(code)] = float(pct)

        # 历史截面：从各板块 _history 中提取（避免覆盖今日已写入的值）
        for item in sector_data_list:
            code = item.get("sector_code")
            if not code:
                continue
            for h in item.get("_history") or []:
                d = RotationScoringModel._norm_hist_date(h.get("date"))
                if not d or d in today_candidates:
                    continue
                pct = h.get("index_change_pct")
                if pct is None:
                    continue
                by_date[d][str(code)] = float(pct)

        # 计算每个日期的截面均值，注入 market_avg_change 供回退使用
        market_avg_by_date: dict[str, float] = {}
        for d, peers in by_date.items():
            if len(peers) >= 3:
                market_avg_by_date[d] = float(np.mean(list(peers.values())))

        return {
            "changes_by_date": dict(by_date),
            "market_avg_by_date": market_avg_by_date,
        }

    def _infer_volatility(self, sector: dict) -> Optional[float]:
        v = sector.get("realized_vol_20d")
        if v is not None and float(v) > 0:
            return float(v)
        hist = sector.get("_history") or []
        changes = [float(h.get("index_change_pct", 0) or 0) for h in hist[-20:]]
        if len(changes) < 5:
            return None
        return float(np.std(changes)) + 1e-8

    @staticmethod
    def _effective_score_gap_threshold(
        max_new: float,
        max_current: float,
        params: StrategyParams,
        default_floor: float,
    ) -> float:
        base = params.score_gap_threshold if params.score_gap_threshold is not None else default_floor
        if base <= 0:
            base = default_floor
        if not params.use_relative_score_gap:
            return base
        denom = max(params.score_gap_epsilon, abs(max_current), abs(max_new), 1.0)
        return max(base, params.relative_score_gap_ratio * denom)

    def _evaluate_market_regime(
        self, scored_sectors: list, strategy_type: StrategyType, params: StrategyParams
    ) -> str:
        """评估市场状态，返回 "BULL" / "NEUTRAL" / "BEAR"

        判定维度：
        1. top10 板块中有多少评分达标
        2. 全市场上涨板块占比（市场宽度）
        3. 平均涨跌幅方向
        """
        if not scored_sectors:
            return "BEAR"

        min_score = params.min_score_threshold if params.min_score_threshold is not None else (
            2.0 if strategy_type == StrategyType.AGGRESSIVE else 4.0
        )
        top10 = scored_sectors[:10]
        top10_ok = sum(1 for s in top10 if s.get("composite_score", 0) >= min_score)

        # 市场宽度：上涨板块占比
        total = len(scored_sectors)
        up_count = sum(1 for s in scored_sectors if s.get("index_change_pct", 0) > 0)
        up_ratio = up_count / max(total, 1)

        avg_change = sum(s.get("index_change_pct", 0) for s in scored_sectors) / max(total, 1)

        # 市场宽度绝对下限：全市场普跌时，头部板块的高分只是截面意义上的"相对抗跌"，
        # 并非绝对强势。此时即使 top10 有达标标的也不建仓，避免相对动量陷阱。
        breadth_floor = params.market_breadth_floor
        if breadth_floor is not None and breadth_floor > 0 and up_ratio < breadth_floor:
            logger.info(
                f"市场宽度绝对过滤: 上涨占比={up_ratio:.2%} < 下限{breadth_floor:.2%}, 判定 BEAR"
            )
            return "BEAR"

        bull_threshold = params.market_bull_threshold if params.market_bull_threshold is not None else 0.5
        bear_threshold = params.market_bear_threshold if params.market_bear_threshold is not None else 0.4

        if strategy_type == StrategyType.AGGRESSIVE:
            # BULL: top10 至少 2 个达标 且 上涨占比 >= 50%
            if top10_ok >= 2 and up_ratio >= bull_threshold:
                return "BULL"
            # BEAR: top10 无达标 且 上涨占比 < 40%
            if top10_ok == 0 and up_ratio < bear_threshold:
                return "BEAR"
            return "NEUTRAL"
        elif strategy_type == StrategyType.MODERATE:
            if top10_ok >= 2 and up_ratio >= bull_threshold:
                return "BULL"
            if top10_ok == 0 and up_ratio < bear_threshold:
                return "BEAR"
            return "NEUTRAL"
        else:  # CONSERVATIVE
            if top10_ok >= 1 and up_ratio >= bull_threshold:
                return "BULL"
            if top10_ok == 0 and up_ratio < bear_threshold:
                return "BEAR"
            return "NEUTRAL"

    def _market_is_favorable(
        self, scored_sectors: list, strategy_type: StrategyType, params: StrategyParams
    ) -> bool:
        """向后兼容：市场非 BEAR 即视为景气"""
        return self._evaluate_market_regime(scored_sectors, strategy_type, params) != "BEAR"

    def _allocate_buy_position_ratios(
        self, buy_targets: list[dict], params: StrategyParams, total_weight: float
    ) -> dict[str, float]:
        """在入选标的中分配目标仓位

        total_weight 为组合总仓位上限（capital_pct），max_position 为单一板块上限。
        分配后总权重不超过 total_weight，且任一标的不超过 max_position。
        """
        rows = [(s.get("sector_code"), s) for s in buy_targets if s.get("sector_code")]
        if not rows:
            return {}
        codes = [c for c, _ in rows]
        if not params.use_inverse_vol_weights:
            raw = {c: 1.0 / len(codes) for c in codes}
        else:
            invw = []
            for code, s in rows:
                v = self._infer_volatility(s)
                invw.append((code, 1.0 / v if v and v > 0 else 1.0))
            ssum = sum(w for _, w in invw)
            raw = ({c: w / ssum for c, w in invw} if ssum > 0
                   else {c: 1.0 / len(invw) for c, _ in invw})

        weights = {c: total_weight * p for c, p in raw.items()}
        # 单一板块上限：等比例压缩，保证 max(weights) <= max_position
        cap = params.max_position if params.max_position and params.max_position > 0 else 1.0
        if weights:
            peak = max(weights.values())
            if peak > cap:
                scale = cap / peak
                weights = {c: w * scale for c, w in weights.items()}
        return weights

    def calculate_daily_signals(
        self,
        sector_data: list[dict],
        strategy_type: StrategyType,
        params: StrategyParams,
        signal_date: Optional[str] = None,
        current_positions: Optional[dict] = None,
        regime_history: Optional[list[str]] = None,
        diagnostics: Optional[dict] = None,
    ) -> list[TradeSignal]:
        """计算每日轮动信号

        Args:
            sector_data: 板块数据列表 [{sector_code, sector_name, main_net_inflow, ...}]
            regime_history: 该日之前的历史市场状态序列（升序，元素为 BULL/NEUTRAL/BEAR）。
                提供时用于按 favorable_confirm_days 连续确认 BEAR，确认后对持仓生成清仓信号；
                不传（回测路径）则只"不买入"、不主动卖出，由回测自身的 BEAR_EXIT 流程处理。
            diagnostics: 可选输出字典，回填市场状态与空仓原因（供接口层展示）
            strategy_type: 策略类型
            params: 策略参数
            signal_date: 信号日期
            current_positions: 当前持仓 dict {sector_code: weight}
        Returns:
            交易信号列表
        """
        if signal_date is None:
            signal_date = datetime.now().strftime("%Y-%m-%d")

        if not sector_data:
            logger.warning(f"无板块数据，无法计算信号 (信号日期: {signal_date})")
            logger.warning(f"传入的sector_data类型: {type(sector_data)}, 长度: {len(sector_data) if isinstance(sector_data, list) else 'N/A'}")
            return []

        context = self._build_cross_section_context(sector_data)

        # 将今日截面均值注入每个板块数据，供 relative_strength 因子回退使用
        market_avg_by_date = context.get("market_avg_by_date") or {}
        for item in sector_data:
            d = self._norm_hist_date(item.get("date"))
            if d and d in market_avg_by_date:
                item["market_avg_change"] = market_avg_by_date[d]

        # 基于近期市场宽度判断 regime，动态调整因子权重
        changes_by_date = context.get("changes_by_date", {})
        recent_dates = sorted(changes_by_date.keys())[-5:]
        if len(recent_dates) >= 3:
            recent_breadth = []
            for d in recent_dates:
                changes = changes_by_date[d]
                if changes:
                    up = sum(1 for v in changes.values() if v > 0)
                    recent_breadth.append(up / len(changes))
            avg_breadth = sum(recent_breadth) / len(recent_breadth) if recent_breadth else 0.5
            if avg_breadth >= 0.55:
                preliminary_regime = "BULL"
            elif avg_breadth <= 0.40:
                preliminary_regime = "BEAR"
            else:
                preliminary_regime = "NEUTRAL"
        else:
            preliminary_regime = "NEUTRAL"

        from .combiner import get_dynamic_weights
        weights = get_dynamic_weights(strategy_type.value, preliminary_regime)
        combiner = FactorCombiner()

        # 第一阶段：计算所有板块的因子原始结果
        raw_rows: list[dict[str, Any]] = []
        for item in sector_data:
            history = item.get("_history", None)
            abs_score, val_score, cat_detail, engine_fb, factor_results = self._calculate_composite_score(
                item, strategy_type, params, history, context, weights=weights
            )
            raw_rows.append({
                "item": item,
                "abs_composite": abs_score,
                "valuation_score": val_score,
                "category_scores": cat_detail,
                "engine_fallback": engine_fb,
                "factor_results": factor_results,
            })

        # 第二阶段：截面 Z-Score 归一化（可选）
        if params.use_zscore_normalization:
            all_factor_results = [r["factor_results"] for r in raw_rows if r["factor_results"]]
            if all_factor_results and len(all_factor_results) >= 3:
                FactorRegistry.apply_zscore_normalization(all_factor_results)
                # 用归一化后的因子得分重新计算综合分
                for i, row in enumerate(raw_rows):
                    fr = row["factor_results"]
                    if not fr:
                        continue
                    new_abs, new_cat = combiner.combine_weighted(fr, weights)
                    row["abs_composite"] = new_abs
                    row["category_scores"] = new_cat
                    # 更新估值得分
                    for r in fr:
                        if r.category == FactorCategory.VALUATION:
                            row["valuation_score"] = r.score
                            break

        rows = raw_rows

        alpha = max(0.0, min(1.0, params.cross_section_alpha))
        if alpha > 0 and len(rows) >= 3:
            all_results: dict[str, list[FactorResult]] = {}
            for r in rows:
                fr = r.get("factor_results")
                if fr:
                    code = r["item"].get("sector_code")
                    if code:
                        all_results[str(code)] = fr
            if len(all_results) >= 3:
                rank_scores = combiner.combine_ranking(all_results, weights)
                for r in rows:
                    code = r["item"].get("sector_code")
                    rs = rank_scores.get(str(code), r["abs_composite"])
                    r["composite_score"] = round((1 - alpha) * r["abs_composite"] + alpha * rs, 2)
                    r["rank_composite_score"] = round(rs, 2)
            else:
                for r in rows:
                    r["composite_score"] = r["abs_composite"]
                    r["rank_composite_score"] = None
        else:
            for r in rows:
                r["composite_score"] = r["abs_composite"]
                r["rank_composite_score"] = None

        scored_sectors = []
        for r in rows:
            item = r["item"]
            main_flow = item.get("main_net_inflow", 0)
            cat_summary = {k: v.get("score") for k, v in (r.get("category_scores") or {}).items()}
            scored_sectors.append({
                **item,
                "composite_score": r["composite_score"],
                "abs_composite_score": r["abs_composite"],
                "rank_composite_score": r.get("rank_composite_score"),
                "valuation_score": r["valuation_score"],
                "category_scores": r.get("category_scores") or {},
                "engine_fallback": r["engine_fallback"],
                "display_flow": main_flow,
                "sector_name": item.get("sector_name", SECTOR_MAP.get(item.get("sector_code", ""), "未知")),
                "_category_score_summary": cat_summary,
            })

        scored_sectors.sort(key=lambda x: x["composite_score"], reverse=True)

        logger.info(f"信号日期 {signal_date} 前5名板块 (截面α={params.cross_section_alpha}):")
        for i, s in enumerate(scored_sectors[:5]):
            display_flow = s.get("display_flow", 0)
            fb = s.get("engine_fallback", False)
            cat_s = s.get("_category_score_summary") or {}
            logger.info(
                f"  {i+1}. {s.get('sector_name')}: 综合={s['composite_score']:.2f} "
                f"(绝对={s.get('abs_composite_score', 0):.2f}, 截面分={s.get('rank_composite_score')}, "
                f"类内={json.dumps(cat_s, ensure_ascii=False)}, fallback={fb}, 净流入={display_flow/1e8:.2f}亿)"
            )

        # 市场状态判定：既要"不买入"，也要能输出明确的空仓/清仓信号
        regime = self._evaluate_market_regime(scored_sectors, strategy_type, params)
        total_sectors = max(len(scored_sectors), 1)
        up_ratio = sum(1 for s in scored_sectors if s.get("index_change_pct", 0) > 0) / total_sectors
        avg_change = sum(s.get("index_change_pct", 0) for s in scored_sectors) / total_sectors
        breadth_detail = f"上涨板块占比{up_ratio:.0%}, 平均涨跌{avg_change:.2f}%"

        # 连续确认：与回测的 favorable_confirm_days 语义保持一致
        confirm_days = params.favorable_confirm_days if params.favorable_confirm_days is not None else 2
        prior = list(regime_history or [])
        confirmed_bear = False
        if regime == "BEAR":
            seq = prior[-(confirm_days - 1):] + [regime] if confirm_days > 1 else [regime]
            confirmed_bear = len(seq) >= confirm_days and all(r == "BEAR" for r in seq)

        if diagnostics is not None:
            diagnostics.update({
                "market_regime": regime,
                "up_ratio": round(up_ratio, 4),
                "avg_change": round(avg_change, 4),
                "confirmed_bear": confirmed_bear,
                "breadth_detail": breadth_detail,
                "top_sectors": [
                    {"sector_name": s.get("sector_name"), "score": s.get("composite_score")}
                    for s in scored_sectors[:3]
                ],
            })

        # 根据策略类型生成信号
        signals = []
        if strategy_type == StrategyType.AGGRESSIVE:
            signals = self._aggressive_rotation(scored_sectors, params, signal_date, current_positions, confirmed_bear, breadth_detail)
        elif strategy_type == StrategyType.MODERATE:
            signals = self._moderate_rotation(scored_sectors, params, signal_date, current_positions, confirmed_bear, breadth_detail)
        elif strategy_type == StrategyType.CONSERVATIVE:
            signals = self._conservative_rotation(scored_sectors, params, signal_date, current_positions, confirmed_bear, breadth_detail)

        if regime == "BEAR":
            logger.info(
                f"策略 {strategy_type.value} 市场判定 BEAR（{breadth_detail}），"
                f"连续确认={confirmed_bear}，生成 {len(signals)} 条信号"
            )
        else:
            logger.info(f"策略 {strategy_type.value} 生成 {len(signals)} 条信号")
        return signals

    def _calculate_composite_score(
        self,
        item: dict,
        strategy_type: StrategyType,
        params: StrategyParams,
        history: list = None,
        context: Optional[dict[str, Any]] = None,
        weights=None,
    ) -> tuple[float, float, dict, bool, Optional[list[FactorResult]]]:
        """计算综合评分。返回 (绝对综合分, 估值得分, 分类明细, 是否回退, 因子列表)。"""
        try:
            factor_results = FactorRegistry.calculate_all(item, history, context)

            if not factor_results:
                c, v = self._calculate_composite_score_fallback(item, strategy_type, params)
                return c, v, {}, True, None

            if weights is None:
                weights = DEFAULT_WEIGHTS.get(strategy_type.value, DEFAULT_WEIGHTS["MODERATE"])
            combiner = FactorCombiner()
            composite_score, detail = combiner.combine_weighted(factor_results, weights)

            valuation_score = 5.0
            for r in factor_results:
                if r.category == FactorCategory.VALUATION:
                    valuation_score = r.score
                    break

            return composite_score, valuation_score, detail, False, factor_results

        except Exception as e:
            logger.warning(f"因子引擎计算失败，回退到简化计算: {e}")
            c, v = self._calculate_composite_score_fallback(item, strategy_type, params)
            return c, v, {}, True, None

    def _calculate_composite_score_fallback(self, item: dict, strategy_type: StrategyType, params: StrategyParams) -> tuple[float, float]:
        """简化评分（因子引擎不可用时的回退方案）"""
        main_flow = item.get("main_net_inflow", 0)
        north_flow = item.get("north_net_inflow", 0)
        change_pct = item.get("index_change_pct", 0)
        
        # 动量得分：涨跌幅 1% = 2分，上限10分
        rs_score = 5.0 + change_pct * 2.0
        
        # 资金强度得分：无数据时返回 0
        strength_score = 0.0 if main_flow == 0 else 5.0 + main_flow / 2e8

        # 估值得分 (0-10) - 仅使用真实PE/PB分位数据
        if strategy_type == StrategyType.CONSERVATIVE:
            pe_percentile = item.get("pe_percentile")
            pb_percentile = item.get("pb_percentile")
            
            if pe_percentile is not None or pb_percentile is not None:
                avg_percentile = 0
                count = 0
                if pe_percentile is not None:
                    avg_percentile += pe_percentile
                    count += 1
                if pb_percentile is not None:
                    avg_percentile += pb_percentile
                    count += 1
                if count > 0:
                    avg_percentile /= count
                # 分位为 0~100 的百分数：0% → 10 分，50% → 5 分，100% → 0 分
                valuation_score = 10.0 - avg_percentile / 100.0 * 10.0
                valuation_score = max(0, min(10, valuation_score))
            else:
                valuation_score = 0
        else:
            valuation_score = 5.0

        if strategy_type == StrategyType.AGGRESSIVE:
            # 激进：纯动量策略，只看涨跌幅排名
            composite_score = rs_score * 0.9 + strength_score * 0.1
        elif strategy_type == StrategyType.MODERATE:
            # 稳健：动量 + 估值
            composite_score = rs_score * 0.6 + strength_score * 0.2 + valuation_score * 0.2
        else:  # CONSERVATIVE
            # 保守：估值优先
            composite_score = rs_score * 0.3 + valuation_score * 0.5 + strength_score * 0.2
        
        return composite_score, valuation_score

    @staticmethod
    def _get_etf_info(sector_code: str, sector_name: str = None, sector_data: dict = None) -> dict:
        """获取板块对应的最优场内ETF

        优先级：
        1. 直接从传入的sector_data获取 etf_code/etf_name
        2. 从SECTOR_ETF_CANDIDATES获取候选列表，按表现排序选最优
        3. 用sector_code精确匹配SECTOR_ETF_MAP
        4. 用sector_name模糊匹配
        """
        if sector_data and (sector_data.get("etf_code") or sector_data.get("etf_name")):
            return {
                "etf_code": sector_data.get("etf_code", ""),
                "etf_name": sector_data.get("etf_name", ""),
            }

        # 候选ETF列表：取静态首个（避免回测/信号路径实时请求akshare，
        # 实时行情评分既慢又会在历史回测中引入未来函数）
        if sector_name:
            cands = SECTOR_ETF_CANDIDATES.get(sector_name, [])
            if cands:
                best = cands[0]
                return {"etf_code": best["code"], "etf_name": best["name"]}

        etf = SECTOR_ETF_MAP.get(sector_code)
        if etf:
            return {"etf_code": etf["code"], "etf_name": etf["name"]}

        if sector_name:
            # 精确匹配中文名
            for key, val in SECTOR_ETF_MAP.items():
                name_part = key.replace("THS", "").replace("SW", "")
                if name_part == sector_name:
                    return {"etf_code": val["code"], "etf_name": val["name"]}

            # 名称模糊匹配（取前4个字符）
            for key, val in SECTOR_ETF_MAP.items():
                name_part = key.replace("THS", "").replace("SW", "")
                if sector_name.startswith(name_part[:4]) or name_part.startswith(sector_name[:4]):
                    return {"etf_code": val["code"], "etf_name": val["name"]}

            # 从SECTOR_MAP反查THS/SW前缀代码再匹配ETF
            for ths_code, ths_name in SECTOR_MAP.items():
                if ths_name == sector_name:
                    etf = SECTOR_ETF_MAP.get(ths_code)
                    if etf:
                        return {"etf_code": etf["code"], "etf_name": etf["name"]}

        return {"etf_code": None, "etf_name": None}

    def _build_signal(self, sector: dict, strategy_type: StrategyType,
                      direction: SignalDirection, position_ratio: float,
                      score: float, reason: str, signal_date: str,
                      rank: Optional[int] = None, total_sectors: Optional[int] = None) -> TradeSignal:
        """构建交易信号，自动填充ETF信息"""
        sector_code = sector.get("sector_code", "")
        etf_info = self._get_etf_info(sector_code, sector.get("sector_name"), sector)
        return TradeSignal(
            signal_date=signal_date,
            strategy_type=strategy_type,
            sector_code=sector_code,
            sector_name=sector.get("sector_name", ""),
            etf_code=etf_info["etf_code"],
            etf_name=etf_info["etf_name"],
            direction=direction,
            position_ratio=round(position_ratio, 4),
            score=round(score, 4),
            reason=reason,
            rank=rank,
            total_sectors=total_sectors,
        )

    # ---- 轮动策略参数配置 ----
    _ROTATION_PROFILES = {
        StrategyType.AGGRESSIVE: {
            "default_min_score": 2.0,
            "default_keep_score_min": 3.0,
            "score_gap_default_floor": 1.0,
            "label": "激进轮动",
            "reason_full": "满仓轮换",
            "divide_keep_position": False,
            "use_valuation_filter": False,
        },
        StrategyType.MODERATE: {
            "default_min_score": 4.0,
            "default_keep_score_min": 5.0,
            "score_gap_default_floor": 1.5,
            "label": "稳健轮动",
            "reason_full": "半仓轮换",
            "divide_keep_position": True,
            "use_valuation_filter": False,
        },
        StrategyType.CONSERVATIVE: {
            "default_min_score": 4.0,
            "default_keep_score_min": 5.0,
            "score_gap_default_floor": 1.5,
            "label": "保守轮动",
            "reason_full": "保守轮换",
            "divide_keep_position": True,
            "use_valuation_filter": True,
        },
    }

    def _rotation_core(
        self, scored_sectors: list, params: StrategyParams,
        strategy_type: StrategyType, signal_date: str,
        current_positions: Optional[dict] = None,
        bear_exit: bool = False,
        breadth_detail: str = "",
    ) -> list[TradeSignal]:
        """统一轮动策略核心逻辑。

        通过 _ROTATION_PROFILES 中的策略差异化参数，将激进/稳健/保守三档策略
        合并为一个方法。保守策略额外包含估值分位预筛选。

        Args:
            bear_exit: 市场已确认 BEAR 时，对现有持仓生成清仓卖出信号。
                为 False 时仅"不买入"，不主动卖出（回测路径保持该行为，
                其熊市清仓由回测自身的 BEAR_EXIT 流程处理）。
            breadth_detail: 市场宽度描述，用于写入空仓原因
        """
        signals: list[TradeSignal] = []
        current_positions = current_positions or {}
        profile = self._ROTATION_PROFILES.get(strategy_type, self._ROTATION_PROFILES[StrategyType.MODERATE])

        min_score = params.min_score_threshold or profile["default_min_score"]
        keep_overlap = params.keep_overlap if params.keep_overlap is not None else True
        allow_empty = params.allow_empty if params.allow_empty is not None else True
        keep_score_min = params.min_score_keep or profile["default_keep_score_min"]
        valuation_max = params.valuation_pct_max or 50
        divide_keep = profile["divide_keep_position"]
        label = profile["label"]
        reason_full = profile["reason_full"]
        gap_floor = profile["score_gap_default_floor"]

        # 构建当前持仓评分映射
        current_scores: dict[str, float] = {}
        for s in scored_sectors:
            if current_positions and s.get("sector_code") in current_positions:
                current_scores[s.get("sector_code")] = s.get("composite_score", 0)

        # 市场景气判断
        market_good = self._market_is_favorable(scored_sectors, strategy_type, params)
        if not market_good and allow_empty:
            logger.info(f"{label}: 市场不景气，进入空仓模式")
            # 空仓不是"什么都不做"：已确认 BEAR 且当前有持仓时，
            # 必须输出清仓卖出信号，否则持仓会无限期滞留、市场转差也无法离场。
            if bear_exit and current_positions:
                reason = f"{label}: 市场不景气，空仓清仓"
                if breadth_detail:
                    reason += f"（{breadth_detail}）"
                for code in current_positions:
                    sec = next(
                        (s for s in scored_sectors if s.get("sector_code") == code), None
                    )
                    if sec is None:
                        # 持仓板块未出现在当日截面（数据缺失）时，用最小信息兜底，
                        # 保证清仓信号不丢失
                        sec = {
                            "sector_code": code,
                            "sector_name": SECTOR_MAP.get(code, code),
                            "composite_score": 0,
                        }
                    signals.append(self._build_signal(
                        sector=sec, strategy_type=strategy_type,
                        direction=SignalDirection.SELL, position_ratio=0,
                        score=sec.get("composite_score", 0), signal_date=signal_date,
                        reason=reason, rank=0, total_sectors=len(scored_sectors),
                    ))
                logger.info(f"{label}: 已生成 {len(signals)} 条空仓清仓信号")
            return signals

        # 保守策略特有的估值预筛（仅当当日确实存在估值分位数据时启用）
        # 注意：若整日无任何估值数据（如数据源未覆盖的历史回测区间），
        # 保守策略须退化为纯评分选股，否则将长期空仓跑输大盘。
        valuation_active = False
        keep_search_pool = scored_sectors
        if profile["use_valuation_filter"]:
            filtered = []
            has_data = False
            for s in scored_sectors:
                if s["composite_score"] < min_score:
                    continue
                pe_pct = s.get("pe_percentile")
                pb_pct = s.get("pb_percentile")
                if pe_pct is None and pb_pct is None:
                    continue
                has_data = True
                vs = s.get("valuation_score", 5.0)
                vpct = (10 - vs) / 10 * 100
                if vpct <= valuation_max:
                    filtered.append(s)
            valuation_active = has_data

        if valuation_active:
            # 有估值数据：仅买入低估值且评分达标标的
            if not filtered:
                logger.info(f"{label}: 无满足低估值条件的板块，暂不买入")
                return signals
            top_n = min(params.top_n, len(filtered))
            buy_targets = filtered[:top_n]
            # 后续 keep 查找使用 filtered 列表
            keep_search_pool = filtered
        else:
            # 无估值数据（或非保守策略）：按综合评分动态选股
            # 动态 top_n：牛市多选 1 个
            total = len(scored_sectors)
            up_count = sum(1 for s in scored_sectors if s.get("index_change_pct", 0) > 0)
            up_ratio = up_count / max(total, 1)
            avg_change = sum(s.get("index_change_pct", 0) for s in scored_sectors) / max(total, 1)
            dynamic_top_n = params.top_n
            if up_ratio >= 0.5 and avg_change > 0:
                dynamic_top_n = min(params.top_n + 1, 5)  # 牛市上限 5
            top_n = min(dynamic_top_n, len(scored_sectors))
            top_sectors = scored_sectors[:top_n]
            buy_targets = [s for s in top_sectors if s.get("composite_score", 0) >= min_score]
            keep_search_pool = scored_sectors

        if not buy_targets:
            return signals

        new_codes = set(s.get("sector_code") for s in buy_targets)
        current_codes = set(current_positions.keys()) if current_positions else set()

        # 调仓决策
        should_rebalance = False
        if keep_overlap and current_codes:
            if current_codes & new_codes:
                should_rebalance = True

        if current_positions:
            max_cur = max(current_scores.values()) if current_scores else 0
            max_new = max(s.get("composite_score", 0) for s in buy_targets)
            # 动态 score_gap：根据市场宽度调整
            total = len(scored_sectors)
            up_count = sum(1 for s in scored_sectors if s.get("index_change_pct", 0) > 0)
            up_ratio = up_count / max(total, 1)
            avg_change = sum(s.get("index_change_pct", 0) for s in scored_sectors) / max(total, 1)
            dynamic_gap_floor = gap_floor
            if up_ratio >= 0.5 and avg_change > 0 and not params.trend_confirm:
                dynamic_gap_floor = gap_floor * 0.7  # 牛市降低换仓门槛（趋势确认模式不降低，减少无效调仓）
            elif up_ratio < 0.4 and avg_change < 0:
                dynamic_gap_floor = gap_floor * 1.5  # 熊市提高门槛
            gap_thr = self._effective_score_gap_threshold(max_new, max_cur, params, dynamic_gap_floor)
            if max_new - max_cur < gap_thr:
                buy_targets = [s for s in buy_targets if s.get("sector_code") in current_codes]
                if not buy_targets:
                    # 评分差距不足，保留现有持仓 → 返回空信号，回测自然保持仓位
                    return []
        else:
            should_rebalance = True

        # 生成买入信号
        if buy_targets:
            # capital_pct = 组合总仓位上限；max_position = 单一板块上限（在分配时约束）
            total_weight = min(params.capital_pct, 1.0)
            pos_map = self._allocate_buy_position_ratios(buy_targets, params, total_weight)
            replace_all = current_codes and new_codes and len(new_codes - current_codes) == len(new_codes)
            for s in buy_targets:
                # 估值预筛仅当当日存在估值数据时启用；数据缺失时按评分选股不跳过
                if valuation_active:
                    if s.get("pe_percentile") is None and s.get("pb_percentile") is None:
                        continue
                rank = next((i+1 for i, x in enumerate(scored_sectors) if x.get("sector_code") == s.get("sector_code")), 0)
                prefix = reason_full if replace_all else "部分调仓"
                pr = pos_map.get(s.get("sector_code"), total_weight / max(len(buy_targets), 1))
                reason = f"{label}: {prefix}, 评分{s['composite_score']:.2f}"
                if valuation_active:
                    vs = s.get("valuation_score", 5.0)
                    vpct = (10 - vs) / 10 * 100
                    reason += f", 估值分位{vpct:.1f}%<={valuation_max}%"
                else:
                    reason += f", 持有{params.hold_days}日"
                signals.append(self._build_signal(
                    sector=s, strategy_type=strategy_type,
                    direction=SignalDirection.BUY, position_ratio=pr,
                    score=s["composite_score"], signal_date=signal_date,
                    reason=reason, rank=rank, total_sectors=len(scored_sectors),
                ))

        # 卖出不再持有的板块
        if current_positions and should_rebalance:
            for code in current_codes - new_codes:
                s = next((sec for sec in scored_sectors if sec.get("sector_code") == code), None)
                if s:
                    old_score = current_scores.get(code, 0)
                    signals.append(self._build_signal(
                        sector=s, strategy_type=strategy_type,
                        direction=SignalDirection.SELL, position_ratio=0,
                        score=s["composite_score"], signal_date=signal_date,
                        reason=f"{label}: 调出, 原评分{old_score:.2f}",
                        rank=0, total_sectors=len(scored_sectors),
                    ))

        return signals

    def _aggressive_rotation(self, scored_sectors: list, params: StrategyParams, signal_date: str, current_positions: Optional[dict] = None, bear_exit: bool = False, breadth_detail: str = "") -> list[TradeSignal]:
        """激进轮动：仅取资金强度前2名，满仓轮换"""
        return self._rotation_core(scored_sectors, params, StrategyType.AGGRESSIVE, signal_date, current_positions, bear_exit, breadth_detail)

    def _moderate_rotation(self, scored_sectors: list, params: StrategyParams, signal_date: str, current_positions: Optional[dict] = None, bear_exit: bool = False, breadth_detail: str = "") -> list[TradeSignal]:
        """稳健轮动：取综合前3名，半仓分散"""
        return self._rotation_core(scored_sectors, params, StrategyType.MODERATE, signal_date, current_positions, bear_exit, breadth_detail)

    def _conservative_rotation(self, scored_sectors: list, params: StrategyParams, signal_date: str, current_positions: Optional[dict] = None, bear_exit: bool = False, breadth_detail: str = "") -> list[TradeSignal]:
        """保守轮动：资金持续流入且估值分位低于阈值"""
        return self._rotation_core(scored_sectors, params, StrategyType.CONSERVATIVE, signal_date, current_positions, bear_exit, breadth_detail)

    # 全局实例
scoring_model = RotationScoringModel()
