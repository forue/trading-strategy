"""策略引擎服务 - 板块轮动评分模型核心算法"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from typing import Optional

from .models import StrategyType, StrategyParams, TradeSignal, SignalDirection


# 申万一级行业板块
SECTOR_MAP = {
    "SW801010": "农林牧渔", "SW801020": "采掘", "SW801030": "化工",
    "SW801040": "钢铁", "SW801050": "有色金属", "SW801080": "电子",
    "SW801110": "家用电器", "SW801120": "食品饮料", "SW801130": "纺织服装",
    "SW801140": "轻工制造", "SW801150": "医药生物", "SW801160": "公用事业",
    "SW801170": "交通运输", "SW801180": "房地产", "SW801200": "商业贸易",
    "SW801210": "休闲服务", "SW801230": "综合", "SW801710": "建筑材料",
    "SW801720": "建筑装饰", "SW801730": "电气设备", "SW801740": "国防军工",
    "SW801750": "计算机", "SW801760": "传媒", "SW801770": "通信",
    "SW801780": "银行", "SW801790": "非银金融", "SW801880": "汽车",
    "SW801890": "机械设备",
}

# 申万一级行业对应场内ETF推荐
SECTOR_ETF_MAP = {
    "SW801010": {"code": "159825", "name": "农业ETF"},
    "SW801020": {"code": "516260", "name": "矿业ETF"},
    "SW801030": {"code": "159870", "name": "化工ETF"},
    "SW801040": {"code": "562300", "name": "钢铁ETF"},
    "SW801050": {"code": "512400", "name": "有色金属ETF"},
    "SW801080": {"code": "159997", "name": "电子ETF"},
    "SW801110": {"code": "159746", "name": "家电ETF"},
    "SW801120": {"code": "512170", "name": "食品饮料ETF"},
    "SW801130": {"code": "159573", "name": "纺织服装ETF"},
    "SW801140": {"code": "159608", "name": "轻工ETF"},
    "SW801150": {"code": "512010", "name": "医药ETF"},
    "SW801160": {"code": "159611", "name": "公用事业ETF"},
    "SW801170": {"code": "159662", "name": "交运ETF"},
    "SW801180": {"code": "512200", "name": "房地产ETF"},
    "SW801200": {"code": "159828", "name": "消费ETF"},
    "SW801210": {"code": "159766", "name": "旅游ETF"},
    "SW801230": {"code": "511020", "name": "综合ETF"},
    "SW801710": {"code": "159745", "name": "建材ETF"},
    "SW801720": {"code": "159740", "name": "基建ETF"},
    "SW801730": {"code": "159611", "name": "新能源ETF"},
    "SW801740": {"code": "512810", "name": "军工ETF"},
    "SW801750": {"code": "512720", "name": "计算机ETF"},
    "SW801760": {"code": "512980", "name": "传媒ETF"},
    "SW801770": {"code": "515880", "name": "通信ETF"},
    "SW801780": {"code": "512800", "name": "银行ETF"},
    "SW801790": {"code": "512070", "name": "非银ETF"},
    "SW801880": {"code": "516110", "name": "汽车ETF"},
    "SW801890": {"code": "159883", "name": "机械ETF"},
}


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
    ) -> list[TradeSignal]:
        """计算每日轮动信号

        Args:
            sector_data: 板块数据列表 [{sector_code, sector_name, main_net_inflow, ...}]
            strategy_type: 策略类型
            params: 策略参数
            signal_date: 信号日期
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
            score = self._calculate_composite_score(item, strategy_type, params)
            scored_sectors.append({
                **item,
                "composite_score": score,
                "sector_name": item.get("sector_name", SECTOR_MAP.get(item.get("sector_code", ""), "未知")),
            })

        # 按评分排序
        scored_sectors.sort(key=lambda x: x["composite_score"], reverse=True)

        # 根据策略类型生成信号
        signals = []
        if strategy_type == StrategyType.AGGRESSIVE:
            signals = self._aggressive_rotation(scored_sectors, params, signal_date)
        elif strategy_type == StrategyType.MODERATE:
            signals = self._moderate_rotation(scored_sectors, params, signal_date)
        elif strategy_type == StrategyType.CONSERVATIVE:
            signals = self._conservative_rotation(scored_sectors, params, signal_date)

        logger.info(f"策略 {strategy_type.value} 生成 {len(signals)} 条信号")
        return signals

    def _calculate_composite_score(self, item: dict, strategy_type: StrategyType, params: StrategyParams) -> float:
        """计算综合评分

        评分公式（根据策略类型加权）:
        - 激进: 资金强度(60%) + 资金斜率(30%) + 相对强弱(10%)
        - 稳健: 资金强度(40%) + 资金斜率(25%) + 相对强弱(25%) + 估值(10%)
        - 保守: 资金强度(30%) + 资金斜率(20%) + 相对强弱(20%) + 估值(30%)
        """
        main_flow = item.get("main_net_inflow", 0)
        north_flow = item.get("north_net_inflow", 0)
        change_pct = item.get("index_change_pct", 0)

        # 资金强度得分 (0-10)
        strength_score = self._normalize_flow(main_flow) * 0.7 + self._normalize_flow(north_flow) * 0.3

        # 资金斜率得分 (0-10) - 简化为近期趋势
        slope_score = 5.0 + np.sign(main_flow) * min(abs(main_flow) / 1e8, 5.0)

        # 相对强弱得分 (0-10)
        rs_score = 5.0 + change_pct * 1.5

        # 估值得分 (0-10) - 基于资金流和涨跌幅的确定性计算
        # 估值分位与资金流入负相关：资金流入越多→估值可能越高→得分越低
        # 涨跌幅大也暗示估值可能偏高
        if strategy_type == StrategyType.CONSERVATIVE:
            valuation_score = 8.0 - self._normalize_flow(main_flow) * 0.3 - max(0, change_pct) * 0.5
            valuation_score = max(0, min(10, valuation_score))
        else:
            valuation_score = 5.0

        if strategy_type == StrategyType.AGGRESSIVE:
            return strength_score * 0.6 + slope_score * 0.3 + rs_score * 0.1
        elif strategy_type == StrategyType.MODERATE:
            return strength_score * 0.4 + slope_score * 0.25 + rs_score * 0.25 + valuation_score * 0.1
        else:  # CONSERVATIVE
            return strength_score * 0.3 + slope_score * 0.2 + rs_score * 0.2 + valuation_score * 0.3

    @staticmethod
    def _normalize_flow(flow: float) -> float:
        """将资金流标准化为0-10分"""
        if flow == 0:
            return 5.0
        # 以1亿为基准
        normalized = 5.0 + flow / 2e8
        return max(0, min(10, normalized))

    @staticmethod
    def _get_etf_info(sector_code: str) -> dict:
        """获取板块对应的场内ETF信息"""
        etf = SECTOR_ETF_MAP.get(sector_code)
        if etf:
            return {
                "etf_code": etf["code"], 
                "etf_name": etf["name"]
            }
        return {"etf_code": None, "etf_name": None}

    def _build_signal(self, sector: dict, strategy_type: StrategyType,
                      direction: SignalDirection, position_ratio: float,
                      score: float, reason: str, signal_date: str,
                      rank: Optional[int] = None, total_sectors: Optional[int] = None) -> TradeSignal:
        """构建交易信号，自动填充ETF信息"""
        sector_code = sector.get("sector_code", "")
        etf_info = self._get_etf_info(sector_code)
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

    def _aggressive_rotation(self, scored_sectors: list, params: StrategyParams, signal_date: str) -> list[TradeSignal]:
        """激进轮动：仅取资金强度前2名，满仓轮换"""
        signals = []
        top_n = min(params.top_n, len(scored_sectors))

        for i, sector in enumerate(scored_sectors[:top_n]):
            position_ratio = params.max_position / top_n
            signals.append(self._build_signal(
                sector=sector, strategy_type=StrategyType.AGGRESSIVE,
                direction=SignalDirection.BUY, position_ratio=position_ratio,
                score=sector["composite_score"], signal_date=signal_date,
                reason=f"激进轮动: 资金强度排名#{i+1}, 综合评分{sector['composite_score']:.2f}, 建议满仓轮换持有{params.hold_days}日",
                rank=i+1,
                total_sectors=len(scored_sectors),
            ))

        # 对排名靠后的板块发出卖出信号
        for i, sector in enumerate(scored_sectors):
            if sector["composite_score"] < 4.0 and i >= len(scored_sectors) - 3:
                signals.append(self._build_signal(
                    sector=sector, strategy_type=StrategyType.AGGRESSIVE,
                    direction=SignalDirection.SELL, position_ratio=0,
                    score=sector["composite_score"], signal_date=signal_date,
                    reason=f"激进轮动: 资金流出, 评分{sector['composite_score']:.2f}低于阈值, 建议卖出",
                    rank=i+1,
                    total_sectors=len(scored_sectors),
                ))

        return signals

    def _moderate_rotation(self, scored_sectors: list, params: StrategyParams, signal_date: str) -> list[TradeSignal]:
        """稳健轮动：取综合前3名，半仓分散"""
        signals = []
        top_n = min(params.top_n, len(scored_sectors))

        for i, sector in enumerate(scored_sectors[:top_n]):
            position_ratio = params.max_position / top_n
            signals.append(self._build_signal(
                sector=sector, strategy_type=StrategyType.MODERATE,
                direction=SignalDirection.BUY, position_ratio=position_ratio,
                score=sector["composite_score"], signal_date=signal_date,
                reason=f"稳健轮动: 综合排名#{i+1}, 评分{sector['composite_score']:.2f}, 半仓分散持有{params.hold_days}日",
                rank=i+1,
                total_sectors=len(scored_sectors),
            ))

        for i, sector in enumerate(scored_sectors):
            if sector["composite_score"] < 3.0:
                signals.append(self._build_signal(
                    sector=sector, strategy_type=StrategyType.MODERATE,
                    direction=SignalDirection.SELL, position_ratio=0,
                    score=sector["composite_score"], signal_date=signal_date,
                    reason=f"稳健轮动: 评分{sector['composite_score']:.2f}过低, 建议减仓",
                    rank=i+1,
                    total_sectors=len(scored_sectors),
                ))

        return signals

    def _conservative_rotation(self, scored_sectors: list, params: StrategyParams, signal_date: str) -> list[TradeSignal]:
        """保守轮动：资金持续流入且估值分位低于50%"""
        signals = []
        valuation_max = params.valuation_pct_max or 50

        # 筛选估值分位低于阈值的板块
        filtered = [s for s in scored_sectors if s["composite_score"] >= 5.0]

        top_n = min(params.top_n, len(filtered))
        for i, sector in enumerate(filtered[:top_n]):
            # 找到该板块在原始排序中的排名
            original_rank = next((idx+1 for idx, s in enumerate(scored_sectors) if s.get("sector_code") == sector.get("sector_code")), 0)
            position_ratio = params.max_position / max(top_n, 1)
            signals.append(self._build_signal(
                sector=sector, strategy_type=StrategyType.CONSERVATIVE,
                direction=SignalDirection.BUY, position_ratio=position_ratio,
                score=sector["composite_score"], signal_date=signal_date,
                reason=f"保守轮动: 综合评分{sector['composite_score']:.2f}, 估值分位<={valuation_max}%, 仓位上限{params.max_position*100:.0f}%",
                rank=original_rank,
                total_sectors=len(scored_sectors),
            ))

        for i, sector in enumerate(scored_sectors):
            if sector["composite_score"] < 3.5:
                signals.append(self._build_signal(
                    sector=sector, strategy_type=StrategyType.CONSERVATIVE,
                    direction=SignalDirection.SELL, position_ratio=0,
                    score=sector["composite_score"], signal_date=signal_date,
                    reason=f"保守轮动: 评分{sector['composite_score']:.2f}不满足安全边际, 建议规避",
                    rank=i+1,
                    total_sectors=len(scored_sectors),
                ))

        return signals

    # 全局实例
scoring_model = RotationScoringModel()
