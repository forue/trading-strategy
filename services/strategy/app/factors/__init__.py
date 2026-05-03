"""因子引擎 - 自动注册所有因子"""
from .base import BaseFactor, FactorResult, FactorCategory, FactorRegistry

# 导入各因子模块，触发自动注册
from . import capital_flow
from . import momentum
from . import technical
from . import sentiment
from . import valuation
from . import rotation

__all__ = [
    "BaseFactor",
    "FactorResult",
    "FactorCategory",
    "FactorRegistry",
]
