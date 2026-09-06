"""因子合成引擎"""
from .weighted import FactorCombiner, StrategyWeights, DEFAULT_WEIGHTS, get_dynamic_weights

__all__ = [
    "FactorCombiner",
    "StrategyWeights",
    "DEFAULT_WEIGHTS",
    "get_dynamic_weights",
]
