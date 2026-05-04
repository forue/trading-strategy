"""因子引擎 - 基类与注册中心"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel
from loguru import logger


class FactorCategory(str, Enum):
    """因子类别"""
    CAPITAL_FLOW = "capital_flow"
    MOMENTUM = "momentum"
    TECHNICAL = "technical"
    SENTIMENT = "sentiment"
    VALUATION = "valuation"
    ROTATION = "rotation"


class FactorResult(BaseModel):
    """单因子计算结果"""
    name: str
    category: FactorCategory
    raw_value: float
    score: float
    weight: float
    confidence: float = 1.0
    detail: dict = {}


class BaseFactor(ABC):
    """因子基类"""

    name: str = "base_factor"
    category: FactorCategory = FactorCategory.MOMENTUM
    default_weight: float = 0.0
    min_history_days: int = 0

    @abstractmethod
    def calculate(
        self,
        sector_data: dict,
        history: list[dict] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> FactorResult:
        """计算因子得分

        Args:
            sector_data: 当日板块数据
            history: 历史K线数据序列 (按日期升序)
            context: 可选截面上下文，如 {"changes_by_date": {date: {sector_code: change_pct}}}

        Returns:
            FactorResult
        """
        pass

    def validate_data(self, sector_data: dict, history: list[dict] = None) -> bool:
        """验证数据完整性"""
        if not sector_data:
            logger.warning(f"因子 {self.name}: sector_data 为空")
            return False
        if self.min_history_days > 0:
            if not history or len(history) < self.min_history_days:
                logger.warning(f"因子 {self.name}: 历史数据不足 {self.min_history_days} 天")
                return False
        return True

    @staticmethod
    def clamp(value: float, min_val: float = 0.0, max_val: float = 10.0) -> float:
        """钳位到指定范围"""
        return max(min_val, min(max_val, value))

    @staticmethod
    def normalize_min_max(value: float, min_val: float, max_val: float, 
                          target_min: float = 0.0, target_max: float = 10.0) -> float:
        """Min-Max 标准化"""
        if max_val == min_val:
            return (target_min + target_max) / 2
        normalized = (value - min_val) / (max_val - min_val)
        return target_min + normalized * (target_max - target_min)


class FactorRegistry:
    """因子注册中心"""

    _factors: dict[str, BaseFactor] = {}

    @classmethod
    def register(cls, factor: BaseFactor):
        """注册因子"""
        cls._factors[factor.name] = factor
        logger.debug(f"因子已注册: {factor.name} ({factor.category.value})")

    @classmethod
    def get(cls, name: str) -> Optional[BaseFactor]:
        """获取因子"""
        return cls._factors.get(name)

    @classmethod
    def get_all(cls) -> dict[str, BaseFactor]:
        """获取所有因子"""
        return cls._factors.copy()

    @classmethod
    def get_by_category(cls, category: FactorCategory) -> list[BaseFactor]:
        """按类别获取因子"""
        return [f for f in cls._factors.values() if f.category == category]

    @classmethod
    def calculate_all(
        cls,
        sector_data: dict,
        history: list[dict] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> list[FactorResult]:
        """计算所有已注册因子"""
        results = []
        for factor in cls._factors.values():
            try:
                if factor.validate_data(sector_data, history):
                    result = factor.calculate(sector_data, history, context)
                    results.append(result)
                else:
                    results.append(FactorResult(
                        name=factor.name,
                        category=factor.category,
                        raw_value=0.0,
                        score=5.0,
                        weight=factor.default_weight,
                        confidence=0.0,
                        detail={"error": "数据不足"},
                    ))
            except Exception as e:
                logger.error(f"因子 {factor.name} 计算失败: {e}")
                results.append(FactorResult(
                    name=factor.name,
                    category=factor.category,
                    raw_value=0.0,
                    score=5.0,
                    weight=factor.default_weight,
                    confidence=0.0,
                    detail={"error": str(e)},
                ))
        return results

    @classmethod
    def clear(cls):
        """清空所有因子（测试用）"""
        cls._factors.clear()
