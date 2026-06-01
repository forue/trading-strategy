"""外部数据源 - 通过 AkShare 获取宏观经济、全球市场、新闻等数据

所有查询带内存缓存（TTL），避免频繁请求外部接口。
"""
import time
import asyncio
from typing import Any
from functools import lru_cache
from loguru import logger


async def _run_with_timeout(func, *args, timeout: int = 20, **kwargs):
    """在线程池中执行同步函数，带超时控制"""
    try:
        return await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, lambda: func(*args, **kwargs)),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(f"AkShare 调用超时({timeout}s)")


# 缓存: {key: (data, timestamp)}
_cache: dict[str, tuple[Any, float]] = {}
_MAX_CACHE_ENTRIES = 200
# 默认 TTL（秒）
_CACHE_TTL = {
    "global_market": 300,     # 5分钟（全球市场实时行情）
    "macro": 3600,            # 1小时（宏观数据变化慢）
    "margin": 600,            # 10分钟
    "news": 300,              # 5分钟
    "bdi": 3600,              # 1小时
    "market_index": 60,       # 1分钟（大盘指数实时）
    "market_breadth": 120,    # 2分钟（涨跌统计）
}


def _get_cached(key: str, category: str = "global_market") -> Any | None:
    """获取缓存数据，自动淘汰过期条目"""
    if key in _cache:
        data, ts = _cache[key]
        ttl = _CACHE_TTL.get(category, 300)
        if time.time() - ts < ttl:
            return data
        else:
            del _cache[key]  # 过期，删除
    return None


def _set_cached(key: str, data: Any):
    """设置缓存，超限时淘汰最老条目"""
    # 淘汰过期条目
    now = time.time()
    expired = [k for k, (_, ts) in _cache.items() if now - ts > 3600]  # 超过 1 小时的直接删
    for k in expired:
        del _cache[k]
    # 超限时淘汰最老的
    if len(_cache) >= _MAX_CACHE_ENTRIES:
        oldest_key = min(_cache, key=lambda k: _cache[k][1])
        del _cache[oldest_key]
    _cache[key] = (data, now)


def _get_expired_cache(key: str) -> Any | None:
    """获取过期但仍存在的缓存数据（降级用）"""
    if key in _cache:
        data, _ = _cache[key]
        return data
    return None


def _df_to_records(df) -> list[dict]:
    """DataFrame 转为 JSON 可序列化的 list[dict]"""
    if df is None or df.empty:
        return []
    try:
        return df.to_dict(orient="records")
    except Exception:
        return []



# ============================================================
# 全球市场指数
# ============================================================

async def get_global_market_overview() -> dict:
    """获取全球主要市场指数行情（含重试和过期缓存降级）"""
    cached = _get_cached("global_market_overview", "global_market")
    if cached is not None:
        return cached

    import akshare as ak
    # 重试3次，间隔递增
    for attempt in range(3):
        try:
            df = await _run_with_timeout(ak.index_global_spot_em, timeout=15)
            if df is None or df.empty:
                continue

            key_indices = ["道琼斯", "纳斯达克", "标普500", "恒生指数", "日经225",
                           "富时100", "德国DAX30", "法国CAC40", "韩国综合指数",
                           "澳大利亚标普200", "台湾加权指数"]
            rows = df.to_dict(orient="records")
            filtered = [r for r in rows if any(k in str(r.get("名称", "")) for k in key_indices)]

            if len(filtered) < 5:
                for r in rows:
                    if r not in filtered:
                        filtered.append(r)
                    if len(filtered) >= 15:
                        break

            result = {
                "indices": [{
                    "name": r.get("名称", ""),
                    "price": r.get("最新价", ""),
                    "change": r.get("涨跌额", ""),
                    "change_pct": r.get("涨跌幅", ""),
                    "open": r.get("今开", ""),
                    "high": r.get("最高", ""),
                    "low": r.get("最低", ""),
                    "prev_close": r.get("昨收", ""),
                } for r in filtered[:15]],
                "timestamp": str(df.columns[0]) if len(df.columns) > 0 else "",
            }
            _set_cached("global_market_overview", result)
            return result
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                logger.error(f"获取全球市场行情失败(重试3次): {e}")

    # 降级：尝试新浪财经API
    sina_result = await _fetch_global_market_from_sina()
    if sina_result and "indices" in sina_result:
        _set_cached("global_market_overview", sina_result)
        return sina_result

    # 最终降级：返回过期缓存
    expired = _get_expired_cache("global_market_overview")
    if expired:
        expired["_stale"] = True
        return expired
    return {"error": "全球市场数据暂不可用"}


async def _fetch_global_market_from_sina() -> dict:
    """从新浪财经API获取全球主要指数（备用数据源）"""
    import httpx
    symbols = {
        "int_dji": "道琼斯", "int_nasdaq": "纳斯达克", "int_sp500": "标普500",
        "int_hangseng": "恒生指数", "int_nikkei": "日经225", "int_ftse": "富时100",
    }
    try:
        url = f"https://hq.sinajs.cn/list={','.join(symbols.keys())}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={
                "Referer": "https://finance.sina.com.cn/",
                "User-Agent": "Mozilla/5.0",
            })
            if resp.status_code != 200:
                return {}
            indices = []
            for line in resp.text.strip().split("\n"):
                if "=" not in line:
                    continue
                key_part, val_part = line.split("=", 1)
                key = key_part.split("_")[-1]
                vals = val_part.strip('" ;\n\r').split(",")
                if len(vals) >= 4:
                    name = vals[0]
                    try:
                        price = float(vals[1])
                        change = float(vals[2])
                        change_pct = float(vals[3])
                    except (ValueError, IndexError):
                        continue
                    indices.append({
                        "name": name, "price": price, "change": change,
                        "change_pct": change_pct, "open": "", "high": "",
                        "low": "", "prev_close": round(price - change, 2) if price and change else "",
                    })
            if indices:
                return {"indices": indices, "source": "sina"}
    except Exception as e:
        logger.warning(f"新浪财经全球指数获取失败: {e}")
    return {}


async def get_global_index_history(symbol: str, days: int = 30) -> dict:
    """获取单个全球指数的历史数据"""
    cache_key = f"global_hist_{symbol}_{days}"
    cached = _get_cached(cache_key, "global_market")
    if cached is not None:
        return cached

    try:
        import akshare as ak
        df = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ak.index_global_hist_em(symbol=symbol)
        )
        if df is None or df.empty:
            return {"error": f"无 {symbol} 历史数据"}

        df = df.tail(days)
        records = _df_to_records(df)
        result = {
            "symbol": symbol,
            "records": records[-days:],
            "count": len(records),
        }
        _set_cached(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"获取全球指数 {symbol} 历史失败: {e}")
        return {"error": str(e)}


# ============================================================
# 中国宏观经济数据
# ============================================================

async def get_china_macro_indicators() -> dict:
    """获取中国核心宏观经济指标（最新值）"""
    cached = _get_cached("china_macro", "macro")
    if cached is not None:
        return cached

    result = {"indicators": []}

    # 定义要获取的指标
    indicators = [
        ("PMI（制造业）", "macro_china_pmi"),
        ("CPI（月度）", "macro_china_cpi_monthly"),
        ("PPI", "macro_china_ppi"),
        ("GDP", "macro_china_gdp"),
        ("M2货币供应量", "macro_china_m2_yearly"),
        ("LPR贷款市场报价利率", "macro_china_lpr"),
        ("工业增加值同比", "macro_china_industrial_production_yoy"),
        ("社会消费品零售总额", "macro_china_consumer_goods_retail"),
    ]

    import akshare as ak
    sem = asyncio.Semaphore(4)  # 限制并发为 4，避免打垮外部 API

    async def _fetch_one(name, func_name):
        try:
            func = getattr(ak, func_name, None)
            if func is None:
                return None
            async with sem:
                df = await _run_with_timeout(func, timeout=15)
            if df is not None and not df.empty:
                latest = df.tail(1).to_dict(orient="records")[0]
                return {"name": name, "latest": latest}
        except Exception as e:
            logger.warning(f"获取 {name} 失败: {e}")
        return None

    results = await asyncio.gather(*[_fetch_one(n, f) for n, f in indicators])
    result["indicators"] = [r for r in results if r is not None]

    _set_cached("china_macro", result)
    return result


async def get_china_interest_rates() -> dict:
    """获取中国利率数据（LPR、存款准备金率、SHIBOR）"""
    cached = _get_cached("china_rates", "macro")
    if cached is not None:
        return cached

    import akshare as ak
    result = {}

    # LPR
    try:
        df = await asyncio.get_event_loop().run_in_executor(None, ak.macro_china_lpr)
        if df is not None and not df.empty:
            result["lpr"] = _df_to_records(df.tail(5))
    except Exception as e:
        logger.warning(f"LPR 获取失败: {e}")

    # 存款准备金率
    try:
        df = await asyncio.get_event_loop().run_in_executor(None, ak.macro_china_reserve_requirement_ratio)
        if df is not None and not df.empty:
            result["rrr"] = _df_to_records(df.tail(5))
    except Exception as e:
        logger.warning(f"RRR 获取失败: {e}")

    # SHIBOR
    try:
        df = await asyncio.get_event_loop().run_in_executor(None, ak.macro_china_shibor_all)
        if df is not None and not df.empty:
            result["shibor"] = _df_to_records(df.tail(5))
    except Exception as e:
        logger.warning(f"SHIBOR 获取失败: {e}")

    _set_cached("china_rates", result)
    return result


async def get_us_macro_indicators() -> dict:
    """获取美国核心宏观经济数据"""
    cached = _get_cached("us_macro", "macro")
    if cached is not None:
        return cached

    import akshare as ak
    result = {"indicators": []}

    indicators = [
        ("美国CPI（月度）", "macro_usa_cpi_monthly"),
        ("美国ISM制造业PMI", "macro_usa_ism_pmi"),
        ("美国非农就业", "macro_usa_non_farm"),
        ("美国失业率", "macro_usa_unemployment_rate"),
        ("美国GDP", "macro_usa_gdp_monthly"),
        ("美联储利率", "macro_bank_usa_interest_rate"),
    ]

    for name, func_name in indicators:
        try:
            func = getattr(ak, func_name, None)
            if func is None:
                continue
            df = await asyncio.get_event_loop().run_in_executor(None, func)
            if df is not None and not df.empty:
                latest = df.tail(1).to_dict(orient="records")[0]
                result["indicators"].append({"name": name, "latest": latest})
        except Exception as e:
            logger.warning(f"获取 {name} 失败: {e}")
            continue

    _set_cached("us_macro", result)
    return result


# ============================================================
# 融资融券数据
# ============================================================

async def get_margin_trading_data(days: int = 10) -> dict:
    """获取融资融券数据（两市汇总）"""
    cached = _get_cached(f"margin_{days}", "margin")
    if cached is not None:
        return cached

    import akshare as ak
    result = {}

    # 上海融资融券
    try:
        df = await asyncio.get_event_loop().run_in_executor(None, ak.macro_china_market_margin_sh)
        if df is not None and not df.empty:
            result["shanghai"] = _df_to_records(df.tail(days))
    except Exception as e:
        logger.warning(f"沪市融资融券获取失败: {e}")

    # 深圳融资融券
    try:
        df = await asyncio.get_event_loop().run_in_executor(None, ak.macro_china_market_margin_sz)
        if df is not None and not df.empty:
            result["shenzhen"] = _df_to_records(df.tail(days))
    except Exception as e:
        logger.warning(f"深市融资融券获取失败: {e}")

    _set_cached(f"margin_{days}", result)
    return result


# ============================================================
# 市场新闻
# ============================================================

async def get_market_news(source: str = "global", limit: int = 15) -> dict:
    """获取市场新闻

    source: global=全球财经, ths=同花顺, sina=新浪
    """
    cache_key = f"news_{source}"
    cached = _get_cached(cache_key, "news")
    if cached is not None:
        return cached

    import akshare as ak
    try:
        if source == "global":
            df = await _run_with_timeout(ak.stock_info_global_em, timeout=20)
        elif source == "ths":
            df = await _run_with_timeout(ak.stock_info_global_ths, timeout=20)
        elif source == "sina":
            df = await _run_with_timeout(ak.stock_info_global_sina, timeout=20)
        elif source == "cls":
            df = await _run_with_timeout(ak.stock_info_global_cls, symbol="全部", timeout=20)
        else:
            return {"error": f"未知新闻源: {source}"}

        if df is None or df.empty:
            return {"error": "获取新闻失败"}

        records = _df_to_records(df.head(limit))
        result = {"source": source, "news": records, "count": len(records)}
        _set_cached(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"获取市场新闻失败: {e}")
        return {"error": str(e)}


# ============================================================
# BDI 波罗的海干散货指数
# ============================================================

async def get_bdi_index() -> dict:
    """获取BDI波罗的海干散货指数（大宗商品/航运领先指标）"""
    cached = _get_cached("bdi", "bdi")
    if cached is not None:
        return cached

    import akshare as ak
    try:
        df = await asyncio.get_event_loop().run_in_executor(None, ak.macro_shipping_bdi)
        if df is None or df.empty:
            return {"error": "BDI 数据为空"}

        records = _df_to_records(df.tail(30))
        result = {
            "records": records,
            "latest": records[-1] if records else None,
        }
        _set_cached("bdi", result)
        return result
    except Exception as e:
        logger.error(f"获取BDI失败: {e}")
        return {"error": str(e)}


# ============================================================
# 中美利差
# ============================================================

async def get_china_us_bond_spread(days: int = 30) -> dict:
    """获取中美国债收益率对比"""
    cache_key = f"cn_us_bond_{days}"
    cached = _get_cached(cache_key, "macro")
    if cached is not None:
        return cached

    import akshare as ak
    try:
        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
        df = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ak.bond_zh_us_rate(start_date=start)
        )
        if df is None or df.empty:
            return {"error": "中美债收益率数据为空"}

        records = _df_to_records(df.tail(days))
        result = {"records": records, "count": len(records)}
        _set_cached(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"获取中美债收益率失败: {e}")
        return {"error": str(e)}


# ============================================================
# 大盘指数实时行情
# ============================================================

async def get_market_indices() -> dict:
    """获取大盘主要指数实时行情（含重试和过期缓存降级）"""
    cached = _get_cached("market_indices", "market_index")
    if cached is not None:
        return cached

    import akshare as ak
    for attempt in range(3):
        try:
            df = await asyncio.get_event_loop().run_in_executor(None, ak.stock_zh_index_spot_em)
            if df is None or df.empty:
                continue

            # 筛选主要指数
            key_names = ["上证指数", "深证成指", "创业板指", "科创50", "沪深300", "中证500", "中证1000"]
            rows = df.to_dict(orient="records")
            indices = []
            for r in rows:
                name = str(r.get("名称", ""))
                if any(k in name for k in key_names):
                    indices.append({
                        "name": name,
                        "code": r.get("代码", ""),
                        "price": r.get("最新价", ""),
                        "change_pct": r.get("涨跌幅", ""),
                        "change": r.get("涨跌额", ""),
                        "volume_yi": round(float(r.get("成交额", 0) or 0) / 1e8, 2),
                        "high": r.get("最高", ""),
                        "low": r.get("最低", ""),
                        "open": r.get("今开", ""),
                        "prev_close": r.get("昨收", ""),
                    })

            result = {"indices": indices, "count": len(indices)}
            _set_cached("market_indices", result)
            return result
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                logger.error(f"获取大盘指数失败(重试3次): {e}")

    # 降级：尝试新浪财经API
    sina_indices = await _fetch_market_indices_from_sina()
    if sina_indices:
        result = {"indices": sina_indices, "count": len(sina_indices), "source": "sina"}
        _set_cached("market_indices", result)
        return result

    expired = _get_expired_cache("market_indices")
    if expired:
        expired["_stale"] = True
        return expired
    return {"error": "大盘指数数据暂不可用"}


async def _fetch_market_indices_from_sina() -> list:
    """从新浪财经API获取A股主要指数（备用数据源）"""
    import httpx
    codes = {
        "s_sh000001": ("上证指数", "000001"), "s_sz399001": ("深证成指", "399001"),
        "s_sz399006": ("创业板指", "399006"), "s_sh000688": ("科创50", "000688"),
        "s_sh000300": ("沪深300", "000300"), "s_sh000905": ("中证500", "000905"),
        "s_sh000852": ("中证1000", "000852"),
    }
    try:
        url = f"https://hq.sinajs.cn/list={','.join(codes.keys())}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return []
            indices = []
            for line in resp.text.strip().split("\n"):
                if "=" not in line:
                    continue
                key_part, val_part = line.split("=", 1)
                key = key_part.split("_")[-1]
                vals = val_part.strip('" ;\n\r').split(",")
                info = codes.get(f"s_{key}")
                if not info or len(vals) < 4:
                    continue
                try:
                    name, code = info
                    price = float(vals[1])
                    change = float(vals[2])
                    change_pct = float(vals[3])
                except (ValueError, IndexError):
                    continue
                indices.append({
                    "name": name, "code": code, "price": price,
                    "change_pct": change_pct, "change": change,
                    "volume_yi": 0, "high": "", "low": "", "open": "",
                    "prev_close": round(price - change, 2),
                })
            return indices
    except Exception as e:
        logger.warning(f"新浪大盘指数获取失败: {e}")
    return []


async def get_market_breadth_real() -> dict:
    """获取真实市场涨跌统计（含重试和过期缓存降级）"""
    cached = _get_cached("market_breadth_real", "market_breadth")
    if cached is not None:
        return cached

    import akshare as ak
    for attempt in range(3):
        try:
            df = await asyncio.get_event_loop().run_in_executor(None, ak.stock_zh_a_spot_em)
            if df is None or df.empty:
                continue

            # 使用 pandas 向量化操作，避免 to_dict 和逐行遍历
            import numpy as np
            changes = df["涨跌幅"].fillna(0).astype(float)
            codes = df["代码"].astype(str)
            total = len(df)

            up = int((changes > 0).sum())
            down = int((changes < 0).sum())
            flat = total - up - down

            # 涨跌停：按板块区分阈值
            is_gem_star = codes.str.startswith(("300", "301", "688"))  # 创业板/科创板 20%
            is_bse = codes.str.startswith("8")  # 北交所 30%
            thresholds = np.where(is_gem_star, 19.9, np.where(is_bse, 29.9, 9.9))
            limit_up = int((changes >= thresholds).sum())
            limit_down = int((-changes >= thresholds).sum())

            above_5 = int((changes > 5).sum())
            below_neg5 = int((changes < -5).sum())

            result = {
                "total_stocks": total,
                "up": up,
                "down": down,
                "flat": flat,
                "up_down_ratio": round(up / max(down, 1), 2),
                "limit_up": limit_up,
                "limit_down": limit_down,
                "above_5pct": above_5,
                "below_neg5pct": below_neg5,
                "up_pct": round(up / total * 100, 1),
                "avg_change_pct": round(float(changes.mean()), 2),
                "median_change_pct": round(float(changes.median()), 2),
            }
            _set_cached("market_breadth_real", result)
            return result
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                logger.error(f"获取市场涨跌统计失败(重试3次): {e}")

    expired = _get_expired_cache("market_breadth_real")
    if expired:
        expired["_stale"] = True
        return expired
    return {"error": "市场涨跌数据暂不可用"}


# ============================================================
# 缓存管理
# ============================================================

def clear_external_cache():
    """清空所有外部数据缓存"""
    _cache.clear()
    logger.info("外部数据缓存已清空")


def get_cache_stats() -> dict:
    """获取缓存统计"""
    now = time.time()
    stats = {}
    for key, (_, ts) in _cache.items():
        stats[key] = f"{now - ts:.0f}s ago"
    return {"cache_entries": len(_cache), "entries": stats}
