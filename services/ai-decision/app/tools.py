"""AI 决策服务 - MCP Agent 工具定义

定义 AI 可调用的工具，用于获取实时交易数据。
支持非交易日自动回退：周末、节假日等无数据时，自动回退到最近有数据的交易日。
"""
import json
import math
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Any
from loguru import logger


MAX_FALLBACK_DAYS = 7  # 最多回退天数


def _safe_float(val, default=0.0) -> float:
    """安全取浮点值，None/非数字统一返回 default"""
    if val is None:
        return default
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default

def _clamp_days(val, default=10, maximum=60) -> int:
    """限制 days 参数在合理范围内"""
    try:
        d = int(val)
        return max(1, min(d, maximum))
    except (TypeError, ValueError):
        return default

# 交易日历缓存（模块级，跨请求复用）
_trade_dates_cache: list[str] = []
_trade_dates_cache_date: str = ""  # 缓存日期 YYYY-MM-DD


def _get_latest_trading_day() -> str:
    """获取最近交易日，优先用缓存的真实交易日历，回退到周末判断"""
    global _trade_dates_cache
    today = datetime.now()
    today_str = today.strftime("%Y%m%d")
    # 有缓存且包含今天
    if _trade_dates_cache and today_str in _trade_dates_cache:
        return today.strftime("%Y-%m-%d")
    # 有缓存但今天不在（非交易日），取最近一个
    if _trade_dates_cache:
        past = [d for d in _trade_dates_cache if d <= today_str]
        if past:
            return f"{past[-1][:4]}-{past[-1][4:6]}-{past[-1][6:]}"
    # 无缓存，回退到周末判断
    if today.weekday() == 5:
        target = today - timedelta(days=1)
    elif today.weekday() == 6:
        target = today - timedelta(days=2)
    else:
        target = today
    return target.strftime("%Y-%m-%d")


async def _refresh_trade_dates_cache(client: httpx.AsyncClient, data_collector_url: str):
    """异步刷新交易日历缓存"""
    global _trade_dates_cache, _trade_dates_cache_date
    today_str = datetime.now().strftime("%Y-%m-%d")
    if _trade_dates_cache_date == today_str and _trade_dates_cache:
        return
    try:
        resp = await client.get(f"{data_collector_url}/trade-dates?days=365", timeout=10)
        if resp.status_code == 200:
            dates = resp.json().get("data", [])
            if dates and len(dates) > 10:
                _trade_dates_cache = dates
                _trade_dates_cache_date = today_str
                logger.info(f"交易日历缓存已刷新: {len(dates)} 个交易日")
    except Exception as e:
        logger.warning(f"刷新交易日历缓存失败: {e}")


# 工具定义（OpenAI function calling 格式）
MCP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_market_overview",
            "description": "获取当日市场概览：涨跌家数、平均涨跌幅、市场情绪、北向资金等",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_ranking",
            "description": "获取板块涨跌排行，包括涨跌幅、主力净流入、北向资金",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"},
                    "metric": {"type": "string", "enum": ["change", "inflow"], "description": "排序指标：change=涨跌幅，inflow=资金流入"},
                    "limit": {"type": "integer", "description": "返回数量，默认10"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_sector",
            "description": "分析板块详情：资金流向、涨跌幅、主力净流入、北向资金、技术指标。支持批量分析多个板块（传 sector_codes 数组）",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_code": {"type": "string", "description": "单个板块代码，如 THS881121"},
                    "sector_codes": {"type": "array", "items": {"type": "string"}, "description": "批量板块代码列表，如 [\"THS881121\",\"THS881124\"]。与 sector_code 二选一"},
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_today_signals",
            "description": "获取今日交易信号：买入/卖出信号、评分、仓位建议",
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"], "description": "策略类型"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_north_bound",
            "description": "获取北向资金流入流出数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_history",
            "description": "获取板块历史数据序列（K线、资金流）",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_code": {"type": "string", "description": "板块代码"},
                    "days": {"type": "integer", "description": "天数，默认20"}
                },
                "required": ["sector_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_backtest",
            "description": "运行策略回测，获取历史收益、回撤等指标",
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]},
                    "start_date": {"type": "string", "description": "开始日期"},
                    "end_date": {"type": "string", "description": "结束日期"}
                },
                "required": ["start_date", "end_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_portfolio_risk",
            "description": "检查投资组合风险：仓位集中度、亏损、回撤、市场风险",
            "parameters": {
                "type": "object",
                "properties": {
                    "positions": {
                        "type": "object",
                        "description": "持仓权重 {sector_code: weight}，如 {\"SW801780\": 0.5}"
                    },
                    "total_assets": {
                        "type": "number",
                        "description": "总资产（元），默认 0"
                    },
                    "daily_pnl": {
                        "type": "number",
                        "description": "当日盈亏（元），默认 0"
                    },
                    "max_drawdown": {
                        "type": "number",
                        "description": "最大回撤（0-1），默认 0"
                    },
                    "market_change": {
                        "type": "number",
                        "description": "大盘涨跌幅（0-1），默认 0"
                    }
                },
                "required": ["positions"]
            }
        }
    },
    # --- 新增工具 ---
    {
        "type": "function",
        "function": {
            "name": "list_sectors",
            "description": "获取板块名称和代码列表，用于查找板块代码。支持多个关键词同时搜索（逗号分隔），一次查完所有需要的板块。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词，多个用逗号分隔，如'银行,医药,半导体'"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_trading_dates",
            "description": "获取交易日历，用于确认指定日期是否为交易日",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "返回最近N个交易日，默认20"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_sectors",
            "description": "对比多个板块的近期表现、资金流向、波动率等指标",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "板块代码列表，如 ['SW801780', 'SW801730']"
                    },
                    "days": {"type": "integer", "description": "对比天数，默认5"}
                },
                "required": ["sector_codes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_capital_flow_trend",
            "description": "分析板块的主力资金流向趋势，识别持续流入/流出的板块",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_code": {"type": "string", "description": "板块代码，不传则分析全部板块"},
                    "days": {"type": "integer", "description": "分析天数，默认10"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_signal_history",
            "description": "获取历史交易信号记录，分析信号命中率和策略表现",
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"], "description": "策略类型"},
                    "days": {"type": "integer", "description": "查询天数，默认30"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_technical_indicators",
            "description": "计算板块的技术指标（MA均线、MACD、RSI、布林带），用于技术分析",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_code": {"type": "string", "description": "板块代码"},
                    "indicators": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "指标列表，如 ['MA', 'MACD', 'RSI', 'BOLL']，默认全部"
                    },
                    "days": {"type": "integer", "description": "K线天数，默认60"}
                },
                "required": ["sector_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_valuation",
            "description": "获取板块估值分析：PE/PB及其历史百分位，判断高估/低估",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_code": {"type": "string", "description": "板块代码"},
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"}
                },
                "required": ["sector_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_breadth",
            "description": "获取市场宽度指标：涨跌家数比、涨跌停数、板块参与率、市场强弱判断",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_fund_flow_distribution",
            "description": "获取主力资金在各板块的分布情况，识别资金集中流入/流出的板块",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"},
                    "top_n": {"type": "integer", "description": "返回资金流入/流出最多的前N个板块，默认10"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_rotation",
            "description": "检测板块轮动信号：识别动量加速/减速、资金方向转变的板块",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "分析天数，默认10"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_factor_analysis",
            "description": "获取板块的多因子评分：动量、资金流、估值、波动率等因子的详细评分",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_code": {"type": "string", "description": "板块代码，不传则获取全部板块排名"},
                    "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"], "description": "策略类型，默认 MODERATE"},
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_heatmap",
            "description": "获取市场热力图数据：全部板块的涨跌幅、资金流向、成交额概览，用于全局感知",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"}
                },
                "required": []
            }
        }
    },
    # --- 外部数据工具（AkShare） ---
    {
        "type": "function",
        "function": {
            "name": "get_global_market",
            "description": "获取全球主要市场指数行情（道琼斯、纳斯达克、标普500、恒生、日经等），用于判断外围市场对A股的影响",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_china_macro",
            "description": "获取中国核心宏观经济指标最新值：PMI、CPI、PPI、GDP、M2、LPR、工业增加值等",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_us_macro",
            "description": "获取美国核心宏观经济数据：CPI、ISM PMI、非农就业、失业率、GDP、美联储利率",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_news",
            "description": "获取最新市场新闻资讯",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "enum": ["global", "ths", "sina", "cls"], "description": "新闻源：global=东方财富全球财经, ths=同花顺, sina=新浪, cls=财联社，默认 global"},
                    "limit": {"type": "integer", "description": "返回条数，默认15"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_bdi",
            "description": "获取BDI波罗的海干散货指数，大宗商品和航运的领先指标，反映全球贸易活跃度",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_bond_spread",
            "description": "获取中美国债收益率对比数据，分析中美利差变化对资金流动的影响",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "查询天数，默认30"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_margin_data",
            "description": "获取沪深两市融资融券数据，反映市场杠杆资金动向",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "查询天数，默认10"}
                },
                "required": []
            }
        }
    },
]


# ============================================================
# 技术指标计算（纯 Python，无需额外依赖）
# ============================================================

def _calc_ma(closes: list[float], period: int) -> list[float | None]:
    """移动平均线"""
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(round(sum(closes[i - period + 1:i + 1]) / period, 2))
    return result


def _calc_ema(closes: list[float], period: int) -> list[float]:
    """指数移动平均线"""
    if not closes:
        return []
    k = 2 / (period + 1)
    result = [closes[0]]
    for i in range(1, len(closes)):
        result.append(round(closes[i] * k + result[-1] * (1 - k), 2))
    return result


def _calc_macd(closes: list[float]) -> dict:
    """MACD 指标 (12, 26, 9)"""
    if len(closes) < 26:
        return {"dif": [], "dea": [], "macd": [], "signal": "数据不足"}
    ema12 = _calc_ema(closes, 12)
    ema26 = _calc_ema(closes, 26)
    dif = [round(a - b, 2) for a, b in zip(ema12, ema26)]
    dea = _calc_ema(dif, 9)
    macd_bar = [round((d - e) * 2, 2) for d, e in zip(dif, dea)]
    # 最新信号
    signal = "中性"
    if len(dif) >= 2 and len(dea) >= 2:
        if dif[-1] > dea[-1] and dif[-2] <= dea[-2]:
            signal = "金叉买入"
        elif dif[-1] < dea[-1] and dif[-2] >= dea[-2]:
            signal = "死叉卖出"
        elif dif[-1] > dea[-1]:
            signal = "多头"
        else:
            signal = "空头"
    return {
        "dif": dif[-5:],
        "dea": dea[-5:],
        "macd": macd_bar[-5:],
        "signal": signal,
    }


def _calc_rsi(closes: list[float], period: int = 14) -> dict:
    """RSI 相对强弱指标"""
    if len(closes) < period + 1:
        return {"values": [], "signal": "数据不足"}
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    rsi_values = []
    # 初始平均
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(round(100 - 100 / (1 + rs), 2))
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    latest = rsi_values[-1] if rsi_values else 50
    if latest > 70:
        signal = "超买"
    elif latest < 30:
        signal = "超卖"
    else:
        signal = "中性"
    return {"values": rsi_values[-5:], "latest": latest, "signal": signal}


def _calc_boll(closes: list[float], period: int = 20, num_std: float = 2.0) -> dict:
    """布林带"""
    if len(closes) < period:
        return {"upper": [], "middle": [], "lower": [], "signal": "数据不足"}
    middle = _calc_ma(closes, period)
    upper = []
    lower = []
    for i in range(len(closes)):
        if middle[i] is None:
            upper.append(None)
            lower.append(None)
        else:
            subset = closes[i - period + 1:i + 1]
            std = math.sqrt(sum((x - middle[i]) ** 2 for x in subset) / period)
            upper.append(round(middle[i] + num_std * std, 2))
            lower.append(round(middle[i] - num_std * std, 2))
    latest_close = closes[-1]
    latest_upper = upper[-1] or latest_close
    latest_lower = lower[-1] or latest_close
    if latest_close > latest_upper:
        signal = "突破上轨（超买）"
    elif latest_close < latest_lower:
        signal = "跌破下轨（超卖）"
    else:
        width_pct = round((latest_upper - latest_lower) / latest_close * 100, 2) if latest_close else 0
        signal = f"通道内（宽度{width_pct}%）"
    return {
        "upper": upper[-5:],
        "middle": middle[-5:],
        "lower": lower[-5:],
        "signal": signal,
    }


class MCPToolExecutor:
    """MCP 工具执行器"""

    def __init__(self, strategy_url: str, data_collector_url: str, signal_url: str):
        self.strategy_url = strategy_url.rstrip("/")
        self.data_collector_url = data_collector_url.rstrip("/")
        self.signal_url = signal_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30)

    async def close(self):
        """关闭 HTTP 客户端"""
        await self._client.aclose()

    async def _ensure_trade_dates(self):
        """确保交易日历缓存已加载"""
        await _refresh_trade_dates_cache(self._client, self.data_collector_url)

    async def _query_with_fallback(self, url: str, params: dict, date_key: str = "date") -> tuple[dict, str]:
        """带自动回退的数据查询

        如果指定日期无数据，自动往前推一天重试，最多回退 MAX_FALLBACK_DAYS 天。
        返回 (响应数据, 实际查询日期)。
        """
        await self._ensure_trade_dates()
        start_date = params.get("start_date", "")
        if not start_date:
            start_date = _get_latest_trading_day()
            params["start_date"] = start_date
            params["end_date"] = start_date

        current = datetime.strptime(start_date, "%Y-%m-%d")
        for i in range(MAX_FALLBACK_DAYS + 1):
            try_date = (current - timedelta(days=i)).strftime("%Y-%m-%d")
            params["start_date"] = try_date
            params["end_date"] = try_date

            try:
                resp = await self._client.get(url, params=params)
                data = resp.json()
                if data.get("code") == 200 and data.get("data"):
                    if i > 0:
                        logger.info(f"数据回退: {start_date} 无数据，使用 {try_date}")
                    return data, try_date
            except Exception:
                continue

        return None, start_date

    async def execute(self, tool_name: str, arguments: dict) -> dict:
        """执行工具调用"""
        try:
            # 先尝试带 _ 前缀（旧工具），再尝试不带前缀（新工具）
            handler = getattr(self, f"_{tool_name}", None) or getattr(self, tool_name, None)
            if handler and callable(handler):
                return await handler(arguments)
            return {"error": f"未知工具: {tool_name}"}
        except Exception as e:
            logger.error(f"工具 {tool_name} 执行失败: {e}")
            return {"error": str(e)}

    async def _get_market_overview(self, args: dict) -> dict:
        date = args.get("date") or _get_latest_trading_day()
        result = {"date": date}

        # 1. 大盘指数（akshare 实时）
        try:
            from .external_data import get_market_indices
            idx_data = await get_market_indices()
            if "indices" in idx_data:
                result["indices"] = idx_data["indices"]
        except Exception as e:
            logger.warning(f"获取大盘指数失败: {e}")

        # 2. 个股涨跌统计（akshare 实时）
        try:
            from .external_data import get_market_breadth_real
            breadth = await get_market_breadth_real()
            if "total_stocks" in breadth:
                result["breadth"] = {
                    "total_stocks": breadth["total_stocks"],
                    "up": breadth["up"],
                    "down": breadth["down"],
                    "flat": breadth["flat"],
                    "up_down_ratio": breadth["up_down_ratio"],
                    "limit_up": breadth["limit_up"],
                    "limit_down": breadth["limit_down"],
                    "up_pct": breadth["up_pct"],
                    "avg_change_pct": breadth["avg_change_pct"],
                }
        except Exception as e:
            logger.warning(f"获取涨跌统计失败: {e}")

        # 3. 板块级数据（data-collector）
        try:
            data, actual_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/all-sectors",
                {"start_date": date, "end_date": date},
            )
            if data and data.get("data"):
                sectors = data["data"]
                changes = [_safe_float(s.get("index_change_pct")) for s in sectors]
                up_s = sum(1 for c in changes if c > 0)
                down_s = sum(1 for c in changes if c < 0)
                avg = sum(changes) / max(len(sectors), 1)
                total_inflow = sum(_safe_float(s.get("main_net_inflow")) for s in sectors) / 1e8
                result["sectors"] = {
                    "total": len(sectors),
                    "up": up_s,
                    "down": down_s,
                    "avg_change_pct": round(avg, 2),
                    "total_main_inflow_yi": round(total_inflow, 2),
                }
                result["sentiment"] = "强势" if avg > 1 else "偏强" if avg > 0 else "偏弱" if avg > -1 else "弱势"
                if actual_date != date:
                    result["note"] = f"{date} 无数据，已回退到最近交易日 {actual_date}"
        except Exception as e:
            logger.warning(f"获取板块数据失败: {e}")

        return result if len(result) > 1 else {"error": "所有数据源均不可用"}

    async def _get_sector_ranking(self, args: dict) -> dict:
        date = args.get("date") or _get_latest_trading_day()
        metric = args.get("metric", "change")
        limit = args.get("limit", 10)
        try:
            data, actual_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/all-sectors",
                {"start_date": date, "end_date": date},
            )
            if data and data.get("data"):
                sectors = data["data"]
                if metric == "inflow":
                    sectors.sort(key=lambda x: x.get("main_net_inflow", 0), reverse=True)
                else:
                    sectors.sort(key=lambda x: x.get("index_change_pct", 0), reverse=True)
                result = {
                    "date": actual_date,
                    "ranking": [
                        {
                            "rank": i + 1,
                            "sector_name": s.get("sector_name", ""),
                            "change_pct": round(s.get("index_change_pct", 0), 2),
                            "main_inflow_yi": round(s.get("main_net_inflow", 0) / 1e8, 2),
                            "north_inflow_yi": round(s.get("north_net_inflow", 0) / 1e8, 2),
                        }
                        for i, s in enumerate(sectors[:limit])
                    ]
                }
                if actual_date != date:
                    result["note"] = f"{date} 无数据，已回退到最近交易日 {actual_date}"
                return result
            return {"error": f"近 {MAX_FALLBACK_DAYS} 天均无数据"}
        except Exception as e:
            return {"error": str(e)}

    async def _analyze_sector(self, args: dict) -> dict:
        sector_codes = args.get("sector_codes", [])
        single_code = args.get("sector_code", "")
        date = args.get("date") or _get_latest_trading_day()

        # 支持批量：sector_codes 数组 或 单个 sector_code
        if single_code and not sector_codes:
            sector_codes = [single_code]
        if not sector_codes:
            return {"error": "请提供 sector_code 或 sector_codes"}

        async def _query_one(code):
            try:
                data, actual_date = await self._query_with_fallback(
                    f"{self.data_collector_url}/query/sector-data",
                    {"sector_code": code, "start_date": date, "end_date": date},
                )
                if data and data.get("data"):
                    s = data["data"][0]
                    return {
                        "sector_code": code,
                        "sector_name": s.get("sector_name", ""),
                        "date": actual_date,
                        "change_pct": round(_safe_float(s.get("index_change_pct")), 2),
                        "main_inflow_yi": round(_safe_float(s.get("main_net_inflow")) / 1e8, 2),
                        "north_inflow_yi": round(_safe_float(s.get("north_net_inflow")) / 1e8, 2),
                        "turnover_yi": round(_safe_float(s.get("turnover")) / 1e8, 2),
                        "high": _safe_float(s.get("index_high")),
                        "low": _safe_float(s.get("index_low")),
                        "close": _safe_float(s.get("index_close")),
                    }
                return {"sector_code": code, "error": "无数据"}
            except Exception as e:
                return {"sector_code": code, "error": str(e)}

        results = await asyncio.gather(*[_query_one(c) for c in sector_codes[:10]])

        if len(sector_codes) == 1:
            return results[0] if results else {"error": "无数据"}
        return {"sectors": results, "count": len(results), "date": date}

    async def _get_today_signals(self, args: dict) -> dict:
        strategy_type = args.get("strategy_type", "MODERATE")
        try:
            resp = await self._client.get(f"{self.signal_url}/signals/today", params={"strategy_type": strategy_type})
            data = resp.json()
            if data.get("code") == 200:
                return {"strategy_type": strategy_type, "signals": data.get("data", [])}
            return {"error": "获取信号失败"}
        except Exception as e:
            return {"error": str(e)}

    async def _get_north_bound(self, args: dict) -> dict:
        date = args.get("date") or _get_latest_trading_day()
        try:
            data, actual_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/all-sectors",
                {"start_date": date, "end_date": date},
            )
            if data and data.get("data"):
                sectors = data["data"]
                total = sum(s.get("north_net_inflow", 0) for s in sectors) / 1e8
                top_in = sorted(sectors, key=lambda x: x.get("north_net_inflow", 0), reverse=True)[:5]
                top_out = sorted(sectors, key=lambda x: x.get("north_net_inflow", 0))[:5]
                result = {
                    "date": actual_date,
                    "total_north_inflow_yi": round(total, 2),
                    "top_inflow": [{"name": s["sector_name"], "yi": round(s.get("north_net_inflow", 0) / 1e8, 2)} for s in top_in],
                    "top_outflow": [{"name": s["sector_name"], "yi": round(s.get("north_net_inflow", 0) / 1e8, 2)} for s in top_out],
                }
                if actual_date != date:
                    result["note"] = f"{date} 无数据，已回退到最近交易日 {actual_date}"
                return result
            return {"error": f"近 {MAX_FALLBACK_DAYS} 天均无数据"}
        except Exception as e:
            return {"error": str(e)}

    async def _get_sector_history(self, args: dict) -> dict:
        sector_code = args.get("sector_code", "")
        days = _clamp_days(args.get("days"), default=20, maximum=60)
        try:
            await self._ensure_trade_dates()
            end = _get_latest_trading_day()
            start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
            resp = await self._client.get(f"{self.data_collector_url}/query/sector-data", params={"sector_code": sector_code, "start_date": start, "end_date": end})
            data = resp.json()
            if data.get("code") == 200 and data.get("data"):
                records = data["data"][-days:]
                return {
                    "sector_code": sector_code,
                    "records": [
                        {
                            "date": r.get("date", "") or r.get("_time", ""),
                            "close": _safe_float(r.get("index_close")),
                            "change_pct": round(_safe_float(r.get("index_change_pct")), 2),
                            "main_inflow_yi": round(_safe_float(r.get("main_net_inflow")) / 1e8, 2),
                        }
                        for r in records
                    ]
                }
            return {"error": "无历史数据"}
        except Exception as e:
            return {"error": str(e)}

    async def _run_backtest(self, args: dict) -> dict:
        strategy_type = args.get("strategy_type", "MODERATE")
        start_date = args.get("start_date", "")
        end_date = args.get("end_date", "")
        try:
            resp = await self._client.post(f"{self.strategy_url}/backtest", json={
                "strategy_type": strategy_type,
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": 1000000,
            })
            data = resp.json()
            if data.get("code") == 200:
                r = data["data"]
                return {
                    "strategy_type": strategy_type,
                    "total_return": r.get("total_return"),
                    "annual_return": r.get("annual_return"),
                    "max_drawdown": r.get("max_drawdown"),
                    "sharpe_ratio": r.get("sharpe_ratio"),
                    "win_rate": r.get("win_rate"),
                    "trade_count": r.get("trade_count_actual"),
                }
            return {"error": "回测失败"}
        except Exception as e:
            return {"error": str(e)}

    async def _check_portfolio_risk(self, args: dict) -> dict:
        """检查投资组合风险"""
        from .risk_monitor import RiskMonitor, PortfolioState

        monitor = RiskMonitor()
        state = PortfolioState(
            positions=args.get("positions", {}),
            total_assets=args.get("total_assets", 0),
            daily_pnl=args.get("daily_pnl", 0),
            max_drawdown=args.get("max_drawdown", 0),
            market_change=args.get("market_change", 0),
        )

        alerts = monitor.check_portfolio(state)
        return {
            "alerts": [
                {
                    "type": a.alert_type,
                    "level": a.level.value,
                    "title": a.title,
                    "description": a.description,
                    "suggestion": a.suggestion,
                }
                for a in alerts
            ],
            "alert_count": len(alerts),
            "has_critical": any(a.level == "CRITICAL" for a in alerts),
            "overall_risk": "HIGH" if any(a.level == "CRITICAL" for a in alerts) else "MEDIUM" if alerts else "LOW",
        }

    # ============================================================
    # 新增工具实现
    # ============================================================

    async def list_sectors(self, args: dict) -> dict:
        """获取板块列表，支持关键词搜索。返回 sector_code 和 sector_name。"""
        keyword = args.get("keyword", "")
        try:
            # 从 all-sectors 获取代码+名称映射，自动回退日期
            data, used_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/all-sectors", {},
            )
            if data and data.get("code") == 200 and data.get("data"):
                seen = set()
                sectors = []
                for s in data["data"]:
                    code = s.get("sector_code", "")
                    name = s.get("sector_name", "")
                    if code and code not in seen:
                        seen.add(code)
                        sectors.append({"code": code, "name": name})
                if keyword:
                    keywords = [kw.strip() for kw in keyword.split(",") if kw.strip()]
                    sectors = [s for s in sectors if any(
                        kw in s["name"] or kw.lower() in s["code"].lower() for kw in keywords
                    )]
                return {
                    "total": len(sectors),
                    "date": used_date,
                    "sectors": sectors[:30],
                }
            return {"error": "获取板块列表失败"}
        except Exception as e:
            return {"error": str(e)}

    async def get_trading_dates(self, args: dict) -> dict:
        """获取交易日历"""
        days = _clamp_days(args.get("days"), default=20, maximum=60)
        try:
            resp = await self._client.get(f"{self.data_collector_url}/trade-dates", params={"days": days}, timeout=10)
            data = resp.json()
            if data.get("code") == 200:
                dates = data.get("data", [])
                today = datetime.now().strftime("%Y%m%d")
                is_today_trading = today in dates
                return {
                    "dates": dates,
                    "count": len(dates),
                    "is_today_trading_day": is_today_trading,
                    "latest_trading_day": dates[-1] if dates else None,
                }
            return {"error": "获取交易日历失败"}
        except Exception as e:
            return {"error": str(e)}

    async def compare_sectors(self, args: dict) -> dict:
        """对比多个板块的近期表现"""
        sector_codes = args.get("sector_codes", [])
        days = _clamp_days(args.get("days"), default=5, maximum=30)
        if not sector_codes:
            return {"error": "请提供至少一个板块代码"}
        if len(sector_codes) > 10:
            return {"error": "最多对比10个板块"}

        # 并行获取所有板块数据
        async def _fetch_one(code):
            try:
                end = _get_latest_trading_day()
                start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
                resp = await self._client.get(
                    f"{self.data_collector_url}/query/sector-data",
                    params={"sector_code": code, "start_date": start, "end_date": end},
                )
                data = resp.json()
                if data.get("code") == 200 and data.get("data"):
                    records = data["data"][-days:]
                    if records:
                        changes = [r.get("index_change_pct", 0) for r in records]
                        inflows = [r.get("main_net_inflow", 0) for r in records]
                        return {
                            "sector_code": code,
                            "sector_name": records[-1].get("sector_name", code),
                            "latest_date": records[-1].get("date", ""),
                            "latest_change_pct": round(changes[-1], 2),
                            "avg_change_pct": round(sum(changes) / len(changes), 2),
                            "total_change_pct": round(sum(changes), 2),
                            "volatility": round(math.sqrt(sum((c - sum(changes)/len(changes))**2 for c in changes) / len(changes)), 2),
                            "total_main_inflow_yi": round(sum(inflows) / 1e8, 2),
                            "consecutive_up": _count_consecutive(changes, lambda x: x > 0),
                            "consecutive_down": _count_consecutive(changes, lambda x: x < 0),
                        }
            except Exception as e:
                return {"sector_code": code, "error": str(e)}
            return None

        # 限制并发为 5，避免过多同时请求打垮 data-collector
        sem = asyncio.Semaphore(5)
        async def _limited(c):
            async with sem:
                return await _fetch_one(c)
        all_results = await asyncio.gather(*[_limited(c) for c in sector_codes])
        results = [r for r in all_results if r is not None]

        # 按总涨跌幅排序
        results.sort(key=lambda x: x.get("total_change_pct", 0) or 0, reverse=True)
        return {"comparison": results, "days": days}

    async def get_capital_flow_trend(self, args: dict) -> dict:
        """分析资金流向趋势"""
        sector_code = args.get("sector_code")
        days = _clamp_days(args.get("days"), default=10, maximum=60)

        try:
            if sector_code:
                # 单个板块趋势
                start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
                data, used_date = await self._query_with_fallback(
                    f"{self.data_collector_url}/query/sector-data",
                    {"sector_code": sector_code, "start_date": start},
                )
                if data and data.get("code") == 200 and data.get("data"):
                    records = data["data"][-days:]
                    inflows = [r.get("main_net_inflow", 0) for r in records]
                    return _build_flow_trend(sector_code, records, inflows)
                return {"error": "无数据"}
            else:
                # 全部板块趋势摘要
                data, used_date = await self._query_with_fallback(
                    f"{self.data_collector_url}/query/all-sectors", {},
                )
                if data and data.get("code") == 200 and data.get("data"):
                    sectors = data["data"]
                    sorted_sectors = sorted(sectors, key=lambda x: x.get("main_net_inflow", 0), reverse=True)
                    return {
                        "date": used_date,
                        "top_inflow": [{
                            "name": s.get("sector_name", ""),
                            "main_inflow_yi": round(s.get("main_net_inflow", 0) / 1e8, 2),
                            "change_pct": round(s.get("index_change_pct", 0), 2),
                        } for s in sorted_sectors[:5]],
                        "top_outflow": [{
                            "name": s.get("sector_name", ""),
                            "main_inflow_yi": round(s.get("main_net_inflow", 0) / 1e8, 2),
                            "change_pct": round(s.get("index_change_pct", 0), 2),
                        } for s in sorted_sectors[-5:]],
                        "total_main_inflow_yi": round(sum(s.get("main_net_inflow", 0) for s in sectors) / 1e8, 2),
                    }
                return {"error": "无数据"}
        except Exception as e:
            return {"error": str(e)}

    async def get_signal_history(self, args: dict) -> dict:
        """获取历史信号记录"""
        strategy_type = args.get("strategy_type", "MODERATE")
        days = _clamp_days(args.get("days"), default=30, maximum=90)
        try:
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            resp = await self._client.get(
                f"{self.signal_url}/signals/history",
                params={"strategy_type": strategy_type, "start_date": start_date, "end_date": end_date},
            )
            data = resp.json()
            if data.get("code") == 200:
                signals = data.get("data", [])
                # 统计摘要
                buy_signals = [s for s in signals if s.get("direction") == "BUY"]
                sell_signals = [s for s in signals if s.get("direction") == "SELL"]
                avg_score = round(sum(s.get("score", 0) for s in signals) / max(len(signals), 1), 2)
                return {
                    "strategy_type": strategy_type,
                    "period": f"{start_date} ~ {end_date}",
                    "total_signals": len(signals),
                    "buy_count": len(buy_signals),
                    "sell_count": len(sell_signals),
                    "avg_score": avg_score,
                    "signals": signals[-10:],  # 最近10条详情
                }
            return {"error": "获取信号历史失败"}
        except Exception as e:
            return {"error": str(e)}

    async def get_technical_indicators(self, args: dict) -> dict:
        """计算技术指标"""
        sector_code = args.get("sector_code", "")
        indicators = args.get("indicators", ["MA", "MACD", "RSI", "BOLL"])
        days = _clamp_days(args.get("days"), default=60, maximum=120)
        if not sector_code:
            return {"error": "请提供板块代码"}

        try:
            end = _get_latest_trading_day()
            start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
            resp = await self._client.get(
                f"{self.data_collector_url}/query/sector-data",
                params={"sector_code": sector_code, "start_date": start, "end_date": end},
            )
            data = resp.json()
            if data.get("code") != 200 or not data.get("data"):
                return {"error": "无K线数据"}

            records = data["data"][-days:]
            closes = [float(r.get("index_close", 0)) for r in records if r.get("index_close")]
            if len(closes) < 10:
                return {"error": "数据不足，至少需要10个交易日"}

            result = {
                "sector_code": sector_code,
                "sector_name": records[-1].get("sector_name", sector_code) if records else "",
                "latest_date": records[-1].get("date", "") if records else "",
                "latest_close": closes[-1],
            }

            for ind in indicators:
                ind_upper = ind.upper()
                if ind_upper == "MA":
                    result["MA"] = {
                        "MA5": _calc_ma(closes, 5)[-1],
                        "MA10": _calc_ma(closes, 10)[-1],
                        "MA20": _calc_ma(closes, 20)[-1] if len(closes) >= 20 else None,
                    }
                elif ind_upper == "MACD":
                    result["MACD"] = _calc_macd(closes)
                elif ind_upper == "RSI":
                    result["RSI"] = _calc_rsi(closes)
                elif ind_upper == "BOLL":
                    result["BOLL"] = _calc_boll(closes)

            return result
        except Exception as e:
            return {"error": str(e)}

    # ============================================================
    # 新增金融分析工具
    # ============================================================

    async def _get_sector_valuation(self, args: dict) -> dict:
        """获取板块估值分析：PE/PB 及历史百分位"""
        sector_code = args.get("sector_code", "")
        date = args.get("date") or _get_latest_trading_day()
        if not sector_code:
            return {"error": "请提供板块代码"}

        try:
            data, actual_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/sector-data",
                {"sector_code": sector_code, "start_date": date, "end_date": date},
            )
            if data and data.get("data"):
                sector = data["data"][0]
                pe = sector.get("pe_ttm")
                pb = sector.get("pb")
                pe_pct = sector.get("pe_percentile")
                pb_pct = sector.get("pb_percentile")

                # 估值判断
                def _valuation_level(pct):
                    if pct is None:
                        return "未知"
                    if pct <= 20:
                        return "极度低估"
                    if pct <= 40:
                        return "低估"
                    if pct <= 60:
                        return "合理"
                    if pct <= 80:
                        return "偏高"
                    return "高估"

                result = {
                    "sector_code": sector_code,
                    "sector_name": sector.get("sector_name", ""),
                    "date": actual_date,
                    "pe_ttm": round(pe, 2) if pe else None,
                    "pb": round(pb, 2) if pb else None,
                    "pe_percentile": round(pe_pct, 1) if pe_pct is not None else None,
                    "pb_percentile": round(pb_pct, 1) if pb_pct is not None else None,
                    "pe_level": _valuation_level(pe_pct),
                    "pb_level": _valuation_level(pb_pct),
                    "close": sector.get("index_close", 0),
                }
                if actual_date != date:
                    result["note"] = f"{date} 无数据，已回退到 {actual_date}"
                return result
            return {"error": "无估值数据"}
        except Exception as e:
            return {"error": str(e)}

    async def _get_market_breadth(self, args: dict) -> dict:
        """市场宽度：个股涨跌统计 + 板块强弱"""
        date = args.get("date") or _get_latest_trading_day()
        result = {"date": date}

        # 1. 个股级涨跌统计（akshare 真实数据）
        try:
            from .external_data import get_market_breadth_real
            breadth = await get_market_breadth_real()
            if "total_stocks" in breadth:
                result["stocks"] = {
                    "total": breadth["total_stocks"],
                    "up": breadth["up"],
                    "down": breadth["down"],
                    "flat": breadth["flat"],
                    "up_down_ratio": breadth["up_down_ratio"],
                    "limit_up": breadth["limit_up"],
                    "limit_down": breadth["limit_down"],
                    "up_pct": breadth["up_pct"],
                    "avg_change_pct": breadth["avg_change_pct"],
                    "median_change_pct": breadth["median_change_pct"],
                    "above_5pct": breadth["above_5pct"],
                    "below_neg5pct": breadth["below_neg5pct"],
                }
        except Exception as e:
            logger.warning(f"获取个股涨跌统计失败: {e}")

        # 2. 板块级强弱（data-collector）
        try:
            data, actual_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/all-sectors",
                {"start_date": date, "end_date": date},
            )
            if data and data.get("data"):
                sectors = data["data"]
                total = len(sectors)
                changes = [_safe_float(s.get("index_change_pct")) for s in sectors]
                up_s = [c for c in changes if c > 0]
                down_s = [c for c in changes if c < 0]
                strong = [c for c in changes if c > 2]
                weak = [c for c in changes if c < -2]
                inflow_sectors = [s for s in sectors if _safe_float(s.get("main_net_inflow")) > 0]
                avg_change = sum(changes) / max(total, 1)

                up_down_ratio_s = round(len(up_s) / max(len(down_s), 1), 2)
                if up_down_ratio_s > 3 and avg_change > 1:
                    strength = "极强"
                elif up_down_ratio_s > 1.5 and avg_change > 0:
                    strength = "偏强"
                elif up_down_ratio_s < 0.5 and avg_change < -1:
                    strength = "极弱"
                elif up_down_ratio_s < 0.8 and avg_change < 0:
                    strength = "偏弱"
                else:
                    strength = "震荡"

                result["sectors"] = {
                    "total": total,
                    "up": len(up_s),
                    "down": len(down_s),
                    "flat": total - len(up_s) - len(down_s),
                    "up_down_ratio": up_down_ratio_s,
                    "strong_sectors": len(strong),
                    "weak_sectors": len(weak),
                    "avg_change_pct": round(avg_change, 2),
                    "max_change_pct": round(max(changes), 2),
                    "min_change_pct": round(min(changes), 2),
                    "fund_participation_pct": round(len(inflow_sectors) / max(total, 1) * 100, 1),
                    "market_strength": strength,
                }
                if actual_date != date:
                    result["note"] = f"{date} 无数据，已回退到 {actual_date}"
        except Exception as e:
            logger.warning(f"获取板块数据失败: {e}")

        return result if len(result) > 1 else {"error": "无数据"}

    async def _get_fund_flow_distribution(self, args: dict) -> dict:
        """资金流向分布：主力资金在各板块的分布"""
        date = args.get("date") or _get_latest_trading_day()
        top_n = args.get("top_n", 10)
        try:
            data, actual_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/all-sectors",
                {"start_date": date, "end_date": date},
            )
            if data and data.get("data"):
                sectors = data["data"]
                total_inflow = sum(s.get("main_net_inflow", 0) for s in sectors)

                # 按主力资金排序
                sorted_by_inflow = sorted(sectors, key=lambda x: x.get("main_net_inflow", 0), reverse=True)
                top_in = sorted_by_inflow[:top_n]
                top_out = sorted_by_inflow[-top_n:]

                # 资金集中度（前5板块占总流入的比例）
                top5_inflow = sum(s.get("main_net_inflow", 0) for s in sorted_by_inflow[:5])
                concentration = round(abs(top5_inflow) / max(abs(total_inflow), 1) * 100, 1)

                # 资金净流入板块数
                positive_count = sum(1 for s in sectors if s.get("main_net_inflow", 0) > 0)

                result = {
                    "date": actual_date,
                    "total_main_inflow_yi": round(total_inflow / 1e8, 2),
                    "positive_flow_sectors": positive_count,
                    "negative_flow_sectors": len(sectors) - positive_count,
                    "top5_concentration_pct": concentration,
                    "top_inflow": [{
                        "name": s.get("sector_name", ""),
                        "main_inflow_yi": round(s.get("main_net_inflow", 0) / 1e8, 2),
                        "change_pct": round(s.get("index_change_pct", 0), 2),
                        "turnover_yi": round(s.get("turnover", 0) / 1e8, 2),
                    } for s in top_in],
                    "top_outflow": [{
                        "name": s.get("sector_name", ""),
                        "main_inflow_yi": round(s.get("main_net_inflow", 0) / 1e8, 2),
                        "change_pct": round(s.get("index_change_pct", 0), 2),
                        "turnover_yi": round(s.get("turnover", 0) / 1e8, 2),
                    } for s in top_out],
                }
                if actual_date != date:
                    result["note"] = f"{date} 无数据，已回退到 {actual_date}"
                return result
            return {"error": "无数据"}
        except Exception as e:
            return {"error": str(e)}

    async def _get_sector_rotation(self, args: dict) -> dict:
        """板块轮动检测：动量加速/减速、资金方向转变"""
        days = _clamp_days(args.get("days"), default=10, maximum=60)
        try:
            await self._ensure_trade_dates()
            end = _get_latest_trading_day()

            # 获取所有板块数据
            resp = await self._client.get(
                f"{self.data_collector_url}/query/all-sectors",
                params={"start_date": end, "end_date": end},
            )
            all_data = resp.json()
            if not (all_data.get("code") == 200 and all_data.get("data")):
                return {"error": "无当日数据"}

            # 取前20个板块分析轮动（避免过多API调用）
            sectors_today = all_data["data"][:20]
            start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")

            # 并行获取所有板块历史数据
            async def _fetch_one(s):
                code = s.get("sector_code", "")
                if not code:
                    return None
                try:
                    hist_resp = await self._client.get(
                        f"{self.data_collector_url}/query/sector-data",
                        params={"sector_code": code, "start_date": start, "end_date": end},
                    )
                    hist_data = hist_resp.json()
                    if not (hist_data.get("code") == 200 and hist_data.get("data")):
                        return None
                    records = hist_data["data"][-days:]
                    if len(records) < 5:
                        return None

                    changes = [r.get("index_change_pct", 0) for r in records]
                    inflows = [r.get("main_net_inflow", 0) for r in records]

                    mid = len(changes) // 2
                    early_momentum = sum(changes[:mid]) / max(mid, 1)
                    late_momentum = sum(changes[mid:]) / max(len(changes) - mid, 1)
                    momentum_change = late_momentum - early_momentum

                    early_flow = sum(inflows[:mid])
                    late_flow = sum(inflows[mid:])
                    flow_reversal = (early_flow > 0 and late_flow < 0) or (early_flow < 0 and late_flow > 0)

                    signal = None
                    if momentum_change > 1.5 and late_flow > 0:
                        signal = "动量加速+资金流入（看多）"
                    elif momentum_change < -1.5 and late_flow < 0:
                        signal = "动量减速+资金流出（看空）"
                    elif flow_reversal and late_flow > 0:
                        signal = "资金转向流入（关注）"
                    elif flow_reversal and late_flow < 0:
                        signal = "资金转向流出（警惕）"

                    if signal:
                        return {
                            "sector_code": code,
                            "sector_name": s.get("sector_name", ""),
                            "signal": signal,
                            "momentum_change": round(momentum_change, 2),
                            "recent_flow_yi": round(late_flow / 1e8, 2),
                            "latest_change_pct": round(changes[-1], 2),
                        }
                except Exception:
                    pass
                return None

            sem = asyncio.Semaphore(5)
            async def _limited(s):
                async with sem:
                    return await _fetch_one(s)
            all_results = await asyncio.gather(*[_limited(s) for s in sectors_today])
            rotation_signals = [r for r in all_results if r is not None]

            # 按动量变化排序
            rotation_signals.sort(key=lambda x: abs(x.get("momentum_change", 0)), reverse=True)

            return {
                "analysis_days": days,
                "sectors_analyzed": len(sectors_today),
                "rotation_signals": rotation_signals,
                "signal_count": len(rotation_signals),
            }
        except Exception as e:
            return {"error": str(e)}

    async def _get_factor_analysis(self, args: dict) -> dict:
        """多因子评分：调用 strategy service 的因子分析接口"""
        sector_code = args.get("sector_code")
        strategy_type = args.get("strategy_type", "MODERATE")
        date = args.get("date") or _get_latest_trading_day()

        try:
            if sector_code:
                # 单板块因子分析
                resp = await self._client.post(
                    f"{self.strategy_url}/factors/analyze",
                    json={"sector_code": sector_code, "strategy_type": strategy_type, "date": date},
                )
                data = resp.json()
                if data.get("code") == 200:
                    result = data["data"]
                    return {
                        "sector_code": sector_code,
                        "sector_name": result.get("sector_name", ""),
                        "date": date,
                        "composite_score": round(result.get("composite_score", 0), 2),
                        "factors": [{
                            "name": f.get("name", ""),
                            "category": f.get("category", ""),
                            "raw_value": round(f.get("raw_value", 0), 4) if f.get("raw_value") is not None else None,
                            "score": round(f.get("score", 0), 2),
                            "weight": round(f.get("weight", 0), 2),
                            "confidence": round(f.get("confidence", 0), 2),
                        } for f in result.get("factors", [])],
                    }
                return {"error": "因子分析失败"}
            else:
                # 全板块因子排名
                # 先获取板块列表
                resp = await self._client.get(
                    f"{self.data_collector_url}/query/all-sectors",
                    params={"start_date": date, "end_date": date},
                )
                all_data = resp.json()
                if not (all_data.get("code") == 200 and all_data.get("data")):
                    return {"error": "无板块数据"}
                sector_codes = [s.get("sector_code", "") for s in all_data["data"] if s.get("sector_code")]

                # 调用批量因子分析
                resp = await self._client.post(
                    f"{self.strategy_url}/factors/batch",
                    json={"sector_codes": sector_codes[:30], "strategy_type": strategy_type, "date": date},
                )
                data = resp.json()
                if data.get("code") == 200:
                    rankings = data["data"].get("rankings", [])
                    return {
                        "date": date,
                        "strategy_type": strategy_type,
                        "total_ranked": len(rankings),
                        "top_10": [{
                            "rank": r.get("rank"),
                            "sector_name": r.get("sector_name", ""),
                            "composite_score": round(r.get("composite_score", 0), 2),
                            "change_pct": round(r.get("change_pct", 0), 2),
                            "main_inflow_yi": round(r.get("main_inflow", 0) / 1e8, 2),
                        } for r in rankings[:10]],
                        "bottom_5": [{
                            "rank": r.get("rank"),
                            "sector_name": r.get("sector_name", ""),
                            "composite_score": round(r.get("composite_score", 0), 2),
                            "change_pct": round(r.get("change_pct", 0), 2),
                        } for r in rankings[-5:]],
                    }
                return {"error": "批量因子分析失败"}
        except Exception as e:
            return {"error": str(e)}

    async def _get_market_heatmap(self, args: dict) -> dict:
        """市场热力图：全部板块涨跌幅+资金流概览"""
        date = args.get("date") or _get_latest_trading_day()
        try:
            data, actual_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/all-sectors",
                {"start_date": date, "end_date": date},
            )
            if data and data.get("data"):
                sectors = data["data"]
                # 按涨跌幅排序
                sectors_sorted = sorted(sectors, key=lambda x: x.get("index_change_pct", 0), reverse=True)

                heatmap = []
                for s in sectors_sorted:
                    change = s.get("index_change_pct", 0)
                    inflow = s.get("main_net_inflow", 0)
                    heatmap.append({
                        "name": s.get("sector_name", ""),
                        "code": s.get("sector_code", ""),
                        "change_pct": round(change, 2),
                        "main_inflow_yi": round(inflow / 1e8, 2),
                        "turnover_yi": round(s.get("turnover", 0) / 1e8, 2),
                        "close": s.get("index_close", 0),
                        # 热力图颜色级别
                        "heat": "hot" if change > 3 else "warm" if change > 1 else "cool" if change > -1 else "cold" if change > -3 else "frozen",
                    })

                # 板块间涨跌差异（衡量市场分化程度）
                changes = [s.get("index_change_pct", 0) for s in sectors]
                spread = round(max(changes) - min(changes), 2)

                result = {
                    "date": actual_date,
                    "total_sectors": len(sectors),
                    "spread": spread,
                    "differentiation": "严重分化" if spread > 8 else "明显分化" if spread > 5 else "温和分化" if spread > 3 else "同步",
                    "heatmap": heatmap,
                }
                if actual_date != date:
                    result["note"] = f"{date} 无数据，已回退到 {actual_date}"
                return result
            return {"error": "无数据"}
        except Exception as e:
            return {"error": str(e)}

    # ============================================================
    # 外部数据工具（AkShare）
    # ============================================================

    async def get_global_market(self, args: dict) -> dict:
        """全球主要市场指数行情"""
        from .external_data import get_global_market_overview
        return await get_global_market_overview()

    async def get_china_macro(self, args: dict) -> dict:
        """中国宏观经济指标"""
        from .external_data import get_china_macro_indicators, get_china_interest_rates
        macro = await get_china_macro_indicators()
        rates = await get_china_interest_rates()
        return {"macro": macro, "rates": rates}

    async def get_us_macro(self, args: dict) -> dict:
        """美国宏观经济数据"""
        from .external_data import get_us_macro_indicators
        return await get_us_macro_indicators()

    async def get_market_news(self, args: dict) -> dict:
        """市场新闻"""
        from .external_data import get_market_news as _get_news
        source = args.get("source", "global")
        limit = args.get("limit", 15)
        return await _get_news(source=source, limit=limit)

    async def get_bdi(self, args: dict) -> dict:
        """BDI波罗的海干散货指数"""
        from .external_data import get_bdi_index
        return await get_bdi_index()

    async def get_bond_spread(self, args: dict) -> dict:
        """中美国债收益率对比"""
        from .external_data import get_china_us_bond_spread
        days = _clamp_days(args.get("days"), default=30, maximum=90)
        return await get_china_us_bond_spread(days=days)

    async def get_margin_data(self, args: dict) -> dict:
        """融资融券数据"""
        from .external_data import get_margin_trading_data
        days = _clamp_days(args.get("days"), default=10, maximum=60)
        return await get_margin_trading_data(days=days)


# ============================================================
# 辅助函数
# ============================================================

def _count_consecutive(values: list[float], predicate) -> int:
    """计算从末尾开始连续满足条件的个数"""
    count = 0
    for v in reversed(values):
        if predicate(v):
            count += 1
        else:
            break
    return count


def _build_flow_trend(sector_code: str, records: list[dict], inflows: list[float]) -> dict:
    """构建资金流向趋势分析"""
    if not records:
        return {"error": "无数据"}

    consecutive_in = _count_consecutive(inflows, lambda x: x > 0)
    consecutive_out = _count_consecutive(inflows, lambda x: x < 0)
    total_flow = sum(inflows)
    recent_3d_flow = sum(inflows[-3:]) if len(inflows) >= 3 else total_flow

    # 资金加速度：近期 vs 前期
    if len(inflows) >= 6:
        first_half = sum(inflows[:len(inflows)//2]) / (len(inflows)//2)
        second_half = sum(inflows[len(inflows)//2:]) / (len(inflows) - len(inflows)//2)
        acceleration = round((second_half - first_half) / 1e8, 2)
    else:
        acceleration = 0

    trend = "持续流入" if consecutive_in >= 3 else "持续流出" if consecutive_out >= 3 else "震荡"

    return {
        "sector_code": sector_code,
        "sector_name": records[-1].get("sector_name", sector_code),
        "days": len(records),
        "total_main_inflow_yi": round(total_flow / 1e8, 2),
        "recent_3d_inflow_yi": round(recent_3d_flow / 1e8, 2),
        "consecutive_inflow_days": consecutive_in,
        "consecutive_outflow_days": consecutive_out,
        "flow_acceleration_yi": acceleration,
        "trend": trend,
        "daily_flows": [{
            "date": r.get("date", ""),
            "main_inflow_yi": round(r.get("main_net_inflow", 0) / 1e8, 2),
            "change_pct": round(r.get("index_change_pct", 0), 2),
        } for r in records[-5:]],
    }
