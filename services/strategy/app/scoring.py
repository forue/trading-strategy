"""策略引擎服务 - 板块轮动评分模型核心算法"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from typing import Optional

from .models import StrategyType, StrategyParams, TradeSignal, SignalDirection

# 导入因子引擎
from .factors import FactorRegistry, FactorResult, FactorCategory
from .combiner import FactorCombiner, StrategyWeights, DEFAULT_WEIGHTS


# 同花顺行业板块代码（动态获取，此处为备用映射）
# 数据源统一使用同花顺板块代码，格式: THS{code} 或 THS_{板块名}
SECTOR_MAP = {
    "THS801010": "农林牧渔", "THS801020": "采掘", "THS801030": "化工",
    "THS801040": "钢铁", "THS801050": "有色金属", "THS801080": "电子",
    "THS801110": "家用电器", "THS801120": "食品饮料", "THS801130": "纺织服装",
    "THS801140": "轻工制造", "THS801150": "医药生物", "THS801160": "公用事业",
    "THS801170": "交通运输", "THS801180": "房地产", "THS801200": "商业贸易",
    "THS801210": "休闲服务", "THS801230": "综合", "THS801710": "建筑材料",
    "THS801720": "建筑装饰", "THS801730": "电气设备", "THS801740": "国防军工",
    "THS801750": "计算机", "THS801760": "传媒", "THS801770": "通信",
    "THS801780": "银行", "THS801790": "非银金融", "THS801880": "汽车",
    "THS801890": "机械设备",
    "THS银行": "银行", "THS证券": "证券", "THS保险": "保险",
    "THS房地产": "房地产", "THS医药": "医药", "THS食品饮料": "食品饮料",
    "THS电子": "电子", "THS计算机": "计算机", "THS传媒": "传媒",
    "THS通信": "通信", "THS电气设备": "电气设备", "THS机械设备": "机械设备",
    "THS汽车": "汽车", "THS有色金属": "有色金属", "THS化工": "化工",
    "THS钢铁": "钢铁", "THS建筑材料": "建筑材料", "THS建筑装饰": "建筑装饰",
    "THS公用事业": "公用事业", "THS交通运输": "交通运输", "THS农林牧渔": "农林牧渔",
    "THS采掘": "采掘", "THS纺织服装": "纺织服装", "THS轻工制造": "轻工制造",
    "THS商业贸易": "商业贸易", "THS休闲服务": "休闲服务", "THS国防军工": "国防军工",
    "THS综合": "综合", "THS家用电器": "家用电器",
}

# 同花顺行业板块对应场内ETF推荐
SECTOR_ETF_MAP = {
    "THS801010": {"code": "159825", "name": "农业ETF"}, "THS801020": {"code": "516260", "name": "矿业ETF"},
    "THS801030": {"code": "159870", "name": "化工ETF"}, "THS801040": {"code": "562300", "name": "钢铁ETF"},
    "THS801050": {"code": "512400", "name": "有色金属ETF"}, "THS801080": {"code": "159997", "name": "电子ETF"},
    "THS801110": {"code": "159746", "name": "家电ETF"}, "THS801120": {"code": "512170", "name": "食品饮料ETF"},
    "THS801130": {"code": "159573", "name": "纺织服装ETF"}, "THS801140": {"code": "159608", "name": "轻工ETF"},
    "THS801150": {"code": "512010", "name": "医药ETF"}, "THS801160": {"code": "159611", "name": "公用事业ETF"},
    "THS801170": {"code": "159662", "name": "交运ETF"}, "THS801180": {"code": "512200", "name": "房地产ETF"},
    "THS801200": {"code": "159828", "name": "消费ETF"}, "THS801210": {"code": "159766", "name": "旅游ETF"},
    "THS801230": {"code": "511020", "name": "综合ETF"}, "THS801710": {"code": "159745", "name": "建材ETF"},
    "THS801720": {"code": "159740", "name": "基建ETF"}, "THS801730": {"code": "159611", "name": "新能源ETF"},
    "THS801740": {"code": "512810", "name": "军工ETF"}, "THS801750": {"code": "512720", "name": "计算机ETF"},
    "THS801760": {"code": "512980", "name": "传媒ETF"}, "THS801770": {"code": "515880", "name": "通信ETF"},
    "THS801780": {"code": "512800", "name": "银行ETF"}, "THS801790": {"code": "512070", "name": "非银ETF"},
    "THS801880": {"code": "516110", "name": "汽车ETF"}, "THS801890": {"code": "159883", "name": "机械ETF"},
    "THS银行": {"code": "512800", "name": "银行ETF"}, "THS证券": {"code": "512070", "name": "非银ETF"},
    "THS保险": {"code": "512070", "name": "非银ETF"}, "THS医药": {"code": "512010", "name": "医药ETF"},
    "THS食品饮料": {"code": "512170", "name": "食品饮料ETF"}, "THS电子": {"code": "159997", "name": "电子ETF"},
    "THS计算机": {"code": "512720", "name": "计算机ETF"}, "THS传媒": {"code": "512980", "name": "传媒ETF"},
    "THS通信": {"code": "515880", "name": "通信ETF"}, "THS房地产": {"code": "512200", "name": "房地产ETF"},
    "THS汽车": {"code": "516110", "name": "汽车ETF"}, "THS机械设备": {"code": "159883", "name": "机械ETF"},
    "THS有色金属": {"code": "512400", "name": "有色金属ETF"}, "THS化工": {"code": "159870", "name": "化工ETF"},
    "THS钢铁": {"code": "562300", "name": "钢铁ETF"}, "THS建筑材料": {"code": "159745", "name": "建材ETF"},
    "THS建筑装饰": {"code": "159740", "name": "基建ETF"}, "THS公用事业": {"code": "159611", "name": "公用事业ETF"},
    "THS交通运输": {"code": "159662", "name": "交运ETF"}, "THS农林牧渔": {"code": "159825", "name": "农业ETF"},
    "THS采掘": {"code": "516260", "name": "矿业ETF"}, "THS电气设备": {"code": "159611", "name": "新能源ETF"},
    "THS国防军工": {"code": "512810", "name": "军工ETF"}, "THS纺织服装": {"code": "159573", "name": "纺织服装ETF"},
    "THS轻工制造": {"code": "159608", "name": "轻工ETF"}, "THS商业贸易": {"code": "159828", "name": "消费ETF"},
    "THS休闲服务": {"code": "159766", "name": "旅游ETF"}, "THS综合": {"code": "511020", "name": "综合ETF"},
    "THS家用电器": {"code": "159746", "name": "家电ETF"},
}

# 扩充：SW申万行业代码 → 场内ETF（SW + THS双key）
SECTOR_ETF_MAP.update({
    "SW801010": {"code": "159825", "name": "农业ETF"}, "SW801020": {"code": "516260", "name": "矿业ETF"},
    "SW801030": {"code": "159870", "name": "化工ETF"}, "SW801040": {"code": "562300", "name": "钢铁ETF"},
    "SW801050": {"code": "512400", "name": "有色金属ETF"}, "SW801080": {"code": "159997", "name": "电子ETF"},
    "SW801110": {"code": "159746", "name": "家电ETF"}, "SW801120": {"code": "512170", "name": "食品饮料ETF"},
    "SW801130": {"code": "159573", "name": "纺织服装ETF"}, "SW801140": {"code": "159608", "name": "轻工ETF"},
    "SW801150": {"code": "512010", "name": "医药ETF"}, "SW801160": {"code": "159611", "name": "公用事业ETF"},
    "SW801170": {"code": "159662", "name": "交运ETF"}, "SW801180": {"code": "512200", "name": "房地产ETF"},
    "SW801200": {"code": "159828", "name": "消费ETF"}, "SW801210": {"code": "159766", "name": "旅游ETF"},
    "SW801230": {"code": "511020", "name": "综合ETF"}, "SW801710": {"code": "159745", "name": "建材ETF"},
    "SW801720": {"code": "159740", "name": "基建ETF"}, "SW801730": {"code": "159611", "name": "新能源ETF"},
    "SW801740": {"code": "512810", "name": "军工ETF"}, "SW801750": {"code": "512720", "name": "计算机ETF"},
    "SW801760": {"code": "512980", "name": "传媒ETF"}, "SW801770": {"code": "515880", "name": "通信ETF"},
    "SW801780": {"code": "512800", "name": "银行ETF"}, "SW801790": {"code": "512070", "name": "非银ETF"},
    "SW801880": {"code": "516110", "name": "汽车ETF"}, "SW801890": {"code": "159883", "name": "机械ETF"},
})


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

    def calculate_daily_signals(
        self,
        sector_data: list[dict],
        strategy_type: StrategyType,
        params: StrategyParams,
        signal_date: Optional[str] = None,
        current_positions: Optional[dict] = None,
    ) -> list[TradeSignal]:
        """计算每日轮动信号

        Args:
            sector_data: 板块数据列表 [{sector_code, sector_name, main_net_inflow, ...}]
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

        # 计算综合评分
        scored_sectors = []
        for item in sector_data:
            # 获取该板块的历史数据（如果有）
            history = item.get("_history", None)
            score, valuation_score = self._calculate_composite_score(item, strategy_type, params, history)
            main_flow = item.get("main_net_inflow", 0)
            display_flow = main_flow if main_flow != 0 else self._simulate_flow_from_kline(item)
            scored_sectors.append({
                **item,
                "composite_score": score,
                "valuation_score": valuation_score,
                "display_flow": display_flow,
                "strength_score": self._normalize_flow(main_flow) * 0.7 + self._normalize_flow(item.get("north_net_inflow", 0)) * 0.3,
                "slope_score": 5.0 + np.sign(main_flow) * min(abs(main_flow) / 1e8, 5.0),
                "rs_score": 5.0 + item.get("index_change_pct", 0) * 1.5,
                "sector_name": item.get("sector_name", SECTOR_MAP.get(item.get("sector_code", ""), "未知")),
            })

        # 按评分排序
        scored_sectors.sort(key=lambda x: x["composite_score"], reverse=True)

        # 调试：打印前5名评分
        logger.info(f"信号日期 {signal_date} 前5名板块:")
        for i, s in enumerate(scored_sectors[:5]):
            display_flow = s.get("display_flow", s.get("main_net_inflow", 0))
            source = "真实" if s.get("main_net_inflow", 0) != 0 else "模拟"
            logger.info(f"  {i+1}. {s.get('sector_name')}: 综合={s['composite_score']:.2f} (强度={s.get('strength_score', 0):.2f}, 斜率={s.get('slope_score', 0):.2f}, 涨跌={s.get('rs_score', 0):.2f}, 净流入={display_flow/1e8:.2f}亿[{source}])")

        # 根据策略类型生成信号
        signals = []
        if strategy_type == StrategyType.AGGRESSIVE:
            signals = self._aggressive_rotation(scored_sectors, params, signal_date, current_positions)
        elif strategy_type == StrategyType.MODERATE:
            signals = self._moderate_rotation(scored_sectors, params, signal_date, current_positions)
        elif strategy_type == StrategyType.CONSERVATIVE:
            signals = self._conservative_rotation(scored_sectors, params, signal_date, current_positions)

        logger.info(f"策略 {strategy_type.value} 生成 {len(signals)} 条信号")
        return signals

    def _calculate_composite_score(self, item: dict, strategy_type: StrategyType, params: StrategyParams, history: list = None) -> tuple[float, float]:
        """计算综合评分 - 使用因子引擎

        评分流程:
        1. 计算所有已注册因子
        2. 按策略类型选择权重
        3. 加权合成综合评分
        """
        try:
            # 计算所有因子
            factor_results = FactorRegistry.calculate_all(item, history)

            if not factor_results:
                # 回退到简化计算
                return self._calculate_composite_score_fallback(item, strategy_type, params)

            # 获取策略权重
            weights = DEFAULT_WEIGHTS.get(strategy_type.value, DEFAULT_WEIGHTS["MODERATE"])

            # 加权合成
            combiner = FactorCombiner()
            composite_score, detail = combiner.combine_weighted(factor_results, weights)

            # 估值因子单独提取（兼容保守策略）
            valuation_score = 5.0
            for r in factor_results:
                if r.category == FactorCategory.VALUATION:
                    valuation_score = r.score
                    break

            return composite_score, valuation_score

        except Exception as e:
            logger.warning(f"因子引擎计算失败，回退到简化计算: {e}")
            return self._calculate_composite_score_fallback(item, strategy_type, params)

    def _calculate_composite_score_fallback(self, item: dict, strategy_type: StrategyType, params: StrategyParams) -> tuple[float, float]:
        """简化评分（因子引擎不可用时的回退方案）"""
        main_flow = item.get("main_net_inflow", 0)
        north_flow = item.get("north_net_inflow", 0)
        change_pct = item.get("index_change_pct", 0)

        # 如果资金流为0，用K线模拟
        if main_flow == 0:
            main_flow = self._simulate_flow_from_kline(item)
        
        # 动量得分：涨跌幅 1% = 2分，上限10分
        rs_score = 5.0 + change_pct * 2.0
        
        # 资金强度得分
        strength_score = 5.0 + main_flow / 2e8

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
                valuation_score = 10.0 - avg_percentile / 10.0 * 10.0
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
    def _normalize_flow(flow: float) -> float:
        """将资金流标准化为0-10分
        
        如果flow为0（历史数据无资金流），用涨跌幅+成交额模拟资金强度
        """
        if flow == 0:
            return 5.0
        normalized = 5.0 + flow / 2e8
        return max(0, min(10, normalized))
    
    @staticmethod
    def _simulate_flow_from_kline(item: dict) -> float:
        """从K线数据模拟资金流
        
        使用成交额和涨跌幅模拟主力资金流向：
        - 成交额大 + 涨幅大 = 资金大幅流入
        - 成交额大 + 跌幅大 = 资金大幅流出
        - 模拟值按成交额比例估算（假设主力占比30%）
        
        注意：turnover单位是元，转换为亿元
        """
        turnover = item.get("turnover", 0)  # 元
        change_pct = item.get("index_change_pct", 0)
        
        if turnover == 0 or change_pct == 0:
            return 0.0
        
        # 成交额的30%作为主力资金估算，再乘以涨跌幅方向
        main_ratio = 0.3
        # turnover是元，转换为亿元
        turnover_yi = turnover / 1e8
        simulated = turnover_yi * main_ratio * (change_pct / 100) * 1e8
        
        return simulated

    @staticmethod
    def _get_etf_info(sector_code: str, sector_name: str = None, sector_data: dict = None) -> dict:
        """获取板块对应的场内ETF信息

        优先级：
        1. 直接从传入的sector_data获取 etf_code/etf_name
        2. 用sector_code精确匹配（SECTOR_ETF_MAP同时支持THS/SW前缀）
        3. 用sector_name精确匹配中文名称
        4. 用sector_name模糊匹配（去除"THS"/"SW"前缀后对比）
        """
        if sector_data and (sector_data.get("etf_code") or sector_data.get("etf_name")):
            return {
                "etf_code": sector_data.get("etf_code", ""),
                "etf_name": sector_data.get("etf_name", ""),
            }

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

    def _aggressive_rotation(self, scored_sectors: list, params: StrategyParams, signal_date: str, current_positions: Optional[dict] = None) -> list[TradeSignal]:
        """激进轮动：仅取资金强度前2名，满仓轮换（带持仓优化）
        
        市场景气判断因素：
        1. 前10名板块中是否存在评分>=min_score的板块
        2. 整体市场涨跌幅（平均涨跌幅是否>0）
        3. 是否有资金流入的板块数量
        """
        signals = []
        current_positions = current_positions or {}
        min_score = params.min_score_threshold or 2.0
        score_gap = params.score_gap_threshold or 1.0
        keep_overlap = params.keep_overlap if params.keep_overlap is not None else True
        allow_empty = params.allow_empty if params.allow_empty is not None else True
        keep_score_min = params.min_score_keep or 3.0

        # 构建当前持仓评分映射
        current_scores = {}
        for s in scored_sectors:
            if current_positions and s.get("sector_code") in current_positions:
                current_scores[s.get("sector_code")] = s.get("composite_score", 0)

        # 市场景气判断：需要同时满足多个条件（AND关系更严格）
        top10_with_score = [s for s in scored_sectors[:10] if s.get("composite_score", 0) >= min_score]
        avg_change = sum(s.get("index_change_pct", 0) for s in scored_sectors) / max(len(scored_sectors), 1)
        
        market_good = (len(top10_with_score) >= 3) or (avg_change > 0 and len(top10_with_score) >= 1)
        
        # 调试日志
        logger.info(f"市场景气判断: 前10评分达标={len(top10_with_score)}, 平均涨跌幅={avg_change:.2f}%")

        # 如果市场不景气且允许空仓，返回空信号
        if not market_good and allow_empty:
            logger.info(f"市场不景气，进入空仓模式")
            return signals

        top_n = min(params.top_n, len(scored_sectors))
        top_sectors = scored_sectors[:top_n]

        # 筛选合格的目标板块
        buy_targets = []
        for s in top_sectors:
            score = s.get("composite_score", 0)
            if score >= min_score:
                buy_targets.append(s)

        if not buy_targets:
            return signals

        # 构建新的买入板块集合
        new_codes = set(s.get("sector_code") for s in buy_targets)
        current_codes = set(current_positions.keys()) if current_positions else set()

        # 调仓决策：检查是否需要调仓
        should_rebalance = False

        # 情况1：新信号包含当前持仓的板块 → 保留
        if keep_overlap and current_codes:
            overlap = current_codes & new_codes
            if overlap:
                # 保留重叠持仓，只处理其他
                should_rebalance = True

        # 情况2：评分差异显著高于当前持仓才调仓
        if current_positions:
            max_current_score = max(current_scores.values()) if current_scores else 0
            max_new_score = max(s.get("composite_score", 0) for s in buy_targets)
            if max_new_score - max_current_score < score_gap:
                # 差异不足，保持当前持仓
                buy_targets = [s for s in buy_targets if s.get("sector_code") in current_codes]
                if not buy_targets:
                    # 当前持仓评分尚可，保留
                    for code in current_codes:
                        s = next((sec for sec in scored_sectors if sec.get("sector_code") == code), None)
                        if s and s.get("composite_score", 0) >= keep_score_min:
                            signals.append(self._build_signal(
                                sector=s, strategy_type=StrategyType.AGGRESSIVE,
                                direction=SignalDirection.BUY, position_ratio=params.max_position,
                                score=s["composite_score"], signal_date=signal_date,
                                reason=f"激进轮动: 持仓保留, 评分{s['composite_score']:.2f}>=保留阈值{keep_score_min:.2f}, 继续持有",
                                rank=next((i+1 for i, x in enumerate(scored_sectors) if x.get("sector_code") == code), 0),
                                total_sectors=len(scored_sectors),
                            ))
                    return signals
        else:
            should_rebalance = True

        # 生成买入信号
        if buy_targets:
            total_weight = min(params.max_position * params.capital_pct, 1.0)
            position_ratio = total_weight / len(buy_targets)
            replace_all = current_codes and new_codes and len(new_codes - current_codes) == len(new_codes)
            for s in buy_targets:
                rank = next((i+1 for i, x in enumerate(scored_sectors) if x.get("sector_code") == s.get("sector_code")), 0)
                reason_prefix = "满仓轮换" if replace_all else "部分调仓"
                signals.append(self._build_signal(
                    sector=s, strategy_type=StrategyType.AGGRESSIVE,
                    direction=SignalDirection.BUY, position_ratio=position_ratio,
                    score=s["composite_score"], signal_date=signal_date,
                    reason=f"激进轮动: {reason_prefix}, 评分{s['composite_score']:.2f}, 持有{params.hold_days}日",
                    rank=rank,
                    total_sectors=len(scored_sectors),
                ))

        # 卖出不再持有的板块
        if current_positions and should_rebalance:
            for code in current_codes - new_codes:
                s = next((sec for sec in scored_sectors if sec.get("sector_code") == code), None)
                if s:
                    old_score = current_scores.get(code, 0)
                    top_buy_score = buy_targets[0].get('composite_score', 0) if buy_targets else 0
                    signals.append(self._build_signal(
                        sector=s, strategy_type=StrategyType.AGGRESSIVE,
                        direction=SignalDirection.SELL, position_ratio=0,
                        score=s["composite_score"], signal_date=signal_date,
                        reason=f"激进轮动: 调出, 原评分{old_score:.2f}, 新建议评分{top_buy_score:.2f}",
                        rank=0,
                        total_sectors=len(scored_sectors),
                    ))

        return signals

    def _moderate_rotation(self, scored_sectors: list, params: StrategyParams, signal_date: str, current_positions: Optional[dict] = None) -> list[TradeSignal]:
        """稳健轮动：取综合前3名，半仓分散（带持仓优化）"""
        signals = []
        current_positions = current_positions or {}
        min_score = params.min_score_threshold or 4.0
        score_gap = params.score_gap_threshold or 1.5
        keep_overlap = params.keep_overlap if params.keep_overlap is not None else True
        allow_empty = params.allow_empty if params.allow_empty is not None else True
        keep_score_min = params.min_score_keep or 5.0

        current_scores = {}
        for s in scored_sectors:
            if current_positions and s.get("sector_code") in current_positions:
                current_scores[s.get("sector_code")] = s.get("composite_score", 0)

        market_good = any(s.get("composite_score", 0) >= min_score for s in scored_sectors[:10])

        if not market_good and allow_empty:
            return signals

        top_n = min(params.top_n, len(scored_sectors))
        top_sectors = scored_sectors[:top_n]

        buy_targets = []
        for s in top_sectors:
            score = s.get("composite_score", 0)
            if score >= min_score:
                buy_targets.append(s)

        if not buy_targets:
            return signals

        new_codes = set(s.get("sector_code") for s in buy_targets)
        current_codes = set(current_positions.keys()) if current_positions else set()

        should_rebalance = False

        if keep_overlap and current_codes:
            overlap = current_codes & new_codes
            if overlap:
                should_rebalance = True

        if current_positions:
            max_current_score = max(current_scores.values()) if current_scores else 0
            max_new_score = max(s.get("composite_score", 0) for s in buy_targets)
            if max_new_score - max_current_score < score_gap:
                buy_targets = [s for s in buy_targets if s.get("sector_code") in current_codes]
                if not buy_targets:
                    for code in current_codes:
                        s = next((sec for sec in scored_sectors if sec.get("sector_code") == code), None)
                        if s and s.get("composite_score", 0) >= keep_score_min:
                            signals.append(self._build_signal(
                                sector=s, strategy_type=StrategyType.MODERATE,
                                direction=SignalDirection.BUY, position_ratio=params.max_position / max(len(current_positions), 1),
                                score=s["composite_score"], signal_date=signal_date,
                                reason=f"稳健轮动: 持仓保留, 评分{s['composite_score']:.2f}>=保留阈值{keep_score_min:.2f}",
                                rank=next((i+1 for i, x in enumerate(scored_sectors) if x.get("sector_code") == code), 0),
                                total_sectors=len(scored_sectors),
                            ))
                    return signals
        else:
            should_rebalance = True

        if buy_targets:
            total_weight = min(params.max_position * params.capital_pct, 1.0)
            position_ratio = total_weight / len(buy_targets)
            replace_all = current_codes and new_codes and len(new_codes - current_codes) == len(new_codes)
            for s in buy_targets:
                rank = next((i+1 for i, x in enumerate(scored_sectors) if x.get("sector_code") == s.get("sector_code")), 0)
                reason_prefix = "半仓轮换" if replace_all else "部分调仓"
                signals.append(self._build_signal(
                    sector=s, strategy_type=StrategyType.MODERATE,
                    direction=SignalDirection.BUY, position_ratio=position_ratio,
                    score=s["composite_score"], signal_date=signal_date,
                    reason=f"稳健轮动: {reason_prefix}, 评分{s['composite_score']:.2f}, 持有{params.hold_days}日",
                    rank=rank,
                    total_sectors=len(scored_sectors),
                ))

        if current_positions and should_rebalance:
            for code in current_codes - new_codes:
                s = next((sec for sec in scored_sectors if sec.get("sector_code") == code), None)
                if s:
                    old_score = current_scores.get(code, 0)
                    signals.append(self._build_signal(
                        sector=s, strategy_type=StrategyType.MODERATE,
                        direction=SignalDirection.SELL, position_ratio=0,
                        score=s["composite_score"], signal_date=signal_date,
                        reason=f"稳健轮动: 调出, 原评分{old_score:.2f}",
                        rank=0,
                        total_sectors=len(scored_sectors),
                    ))

        return signals

    def _conservative_rotation(self, scored_sectors: list, params: StrategyParams, signal_date: str, current_positions: Optional[dict] = None) -> list[TradeSignal]:
        """保守轮动：资金持续流入且估值分位低于50%（带持仓优化）"""
        signals = []
        current_positions = current_positions or {}
        valuation_max = params.valuation_pct_max or 50
        min_score = params.min_score_threshold or 4.0
        score_gap = params.score_gap_threshold or 1.5
        keep_overlap = params.keep_overlap if params.keep_overlap is not None else True
        allow_empty = params.allow_empty if params.allow_empty is not None else True
        keep_score_min = params.min_score_keep or 5.0

        current_scores = {}
        for s in scored_sectors:
            if current_positions and s.get("sector_code") in current_positions:
                current_scores[s.get("sector_code")] = s.get("composite_score", 0)

        market_good = any(s.get("composite_score", 0) >= min_score for s in scored_sectors[:10])

        if not market_good and allow_empty:
            return signals

        # 筛选估值分位低于阈值的板块（必须使用真实估值数据）
        filtered = []
        has_valuation_data = False
        for s in scored_sectors:
            if s["composite_score"] < min_score:
                continue
            pe_percentile = s.get("pe_percentile")
            pb_percentile = s.get("pb_percentile")
            if pe_percentile is None and pb_percentile is None:
                continue
            has_valuation_data = True
            valuation_score = s.get("valuation_score", 5.0)
            valuation_pct = (10 - valuation_score) / 10 * 100
            if valuation_pct <= valuation_max:
                filtered.append(s)

        if not has_valuation_data:
            return signals

        top_n = min(params.top_n, len(filtered))
        buy_targets = filtered[:top_n]

        if not buy_targets:
            return signals

        new_codes = set(s.get("sector_code") for s in buy_targets)
        current_codes = set(current_positions.keys()) if current_positions else set()

        should_rebalance = False

        if keep_overlap and current_codes:
            overlap = current_codes & new_codes
            if overlap:
                should_rebalance = True

        if current_positions:
            max_current_score = max(current_scores.values()) if current_scores else 0
            max_new_score = max(s.get("composite_score", 0) for s in buy_targets)
            if max_new_score - max_current_score < score_gap:
                buy_targets = [s for s in buy_targets if s.get("sector_code") in current_codes]
                if not buy_targets:
                    for code in current_codes:
                        s = next((sec for sec in filtered if sec.get("sector_code") == code), None)
                        if s and s.get("composite_score", 0) >= keep_score_min:
                            pe_percentile = s.get("pe_percentile")
                            pb_percentile = s.get("pb_percentile")
                            if pe_percentile is None and pb_percentile is None:
                                continue
                            valuation_score = s.get("valuation_score", 5.0)
                            valuation_pct = (10 - valuation_score) / 10 * 100
                            signals.append(self._build_signal(
                                sector=s, strategy_type=StrategyType.CONSERVATIVE,
                                direction=SignalDirection.BUY, position_ratio=params.max_position / max(len(current_positions), 1),
                                score=s["composite_score"], signal_date=signal_date,
                                reason=f"保守轮动: 持仓保留, 评分{s['composite_score']:.2f}>=保留阈值{keep_score_min:.2f}, 估值分位{valuation_pct:.1f}%<={valuation_max}%",
                                rank=next((i+1 for i, x in enumerate(scored_sectors) if x.get("sector_code") == code), 0),
                                total_sectors=len(scored_sectors),
                            ))
                    return signals
        else:
            should_rebalance = True

        if buy_targets:
            total_weight = min(params.max_position * params.capital_pct, 1.0)
            position_ratio = total_weight / max(len(buy_targets), 1)
            replace_all = current_codes and new_codes and len(new_codes - current_codes) == len(new_codes)
            for s in buy_targets:
                pe_percentile = s.get("pe_percentile")
                pb_percentile = s.get("pb_percentile")
                if pe_percentile is None and pb_percentile is None:
                    continue
                original_rank = next((idx+1 for idx, x in enumerate(scored_sectors) if x.get("sector_code") == s.get("sector_code")), 0)
                valuation_score = s.get("valuation_score", 5.0)
                valuation_pct = (10 - valuation_score) / 10 * 100
                reason_prefix = "保守轮换" if replace_all else "部分调仓"
                signals.append(self._build_signal(
                    sector=s, strategy_type=StrategyType.CONSERVATIVE,
                    direction=SignalDirection.BUY, position_ratio=position_ratio,
                    score=s["composite_score"], signal_date=signal_date,
                    reason=f"保守轮动: {reason_prefix}, 评分{s['composite_score']:.2f}, 估值分位{valuation_pct:.1f}%<={valuation_max}%",
                    rank=original_rank,
                    total_sectors=len(scored_sectors),
                ))

        if current_positions and should_rebalance:
            for code in current_codes - new_codes:
                s = next((sec for sec in scored_sectors if sec.get("sector_code") == code), None)
                if s:
                    signals.append(self._build_signal(
                        sector=s, strategy_type=StrategyType.CONSERVATIVE,
                        direction=SignalDirection.SELL, position_ratio=0,
                        score=s["composite_score"], signal_date=signal_date,
                        reason=f"保守轮动: 调出, 原评分{current_scores.get(code, 0):.2f}",
                        rank=0,
                        total_sectors=len(scored_sectors),
                    ))

        return signals

    # 全局实例
scoring_model = RotationScoringModel()
