"""外部数据源 - 通过 AkShare 获取宏观经济、全球市场、新闻等数据

所有查询带内存缓存（TTL），避免频繁请求外部接口。
"""
import time
import asyncio
import random
from typing import Any
from functools import lru_cache
from contextlib import asynccontextmanager
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


# ============================================================
# 东方财富 push2 集群访问控制：串行 + 限流 + 递增熔断
#
# push2 集群按 IP 封禁（表现为 RemoteDisconnected），一旦触发至少数分钟不恢复，
# 且在封禁期内反复重试会把时长从几分钟拉长到数小时。因此所有走 push2/push2his
# 的请求统一经过 _push2_guard()：
#   1. 全局串行——同一时刻只有一个在途请求，等价于并发 1；
#   2. 相邻请求间隔 ≥ _PUSH2_MIN_INTERVAL + 随机抖动，避免节奏规律；
#   3. 判定为限流（连接被重置/超时）时不再重试，直接熔断走备用源；
#   4. 熔断时长按连续失败次数递增 300 → 900 → 1800 秒，成功一次清零。
#
# 单次问询只需要 4-6 次 push2 请求，串行带来的 1-2 秒延迟远小于被封禁的代价。
# ============================================================
_PUSH2_BLOCKED_UNTIL = 0.0
_PUSH2_COOLDOWN_STEPS = (300, 900, 1800)  # 连续失败递增：5 → 15 → 30 分钟
_PUSH2_FAIL_STREAK = 0
_PUSH2_MIN_INTERVAL = 1.0   # 相邻两次 push2 请求的最小间隔(秒)
_PUSH2_JITTER = (0.1, 0.5)  # 随机抖动区间(秒)
_PUSH2_QUEUE_TIMEOUT = 15   # 排队等待上限(秒)，超时视同被限流
_PUSH2_FAIL_RESET_SECONDS = 1800  # 距上次失败超过该时长则失败计数归零
_PUSH2_LAST_CALL = 0.0
_PUSH2_LAST_FAIL_AT = 0.0
_PUSH2_LOCK: asyncio.Lock | None = None

# 限流特征：akshare 1.20+ 把 push2 断连包装成 RateLimitError（附中文说明），
# 旧版本直接抛 ConnectionError/RemoteDisconnected，两种都要认
_PUSH2_RATE_LIMIT_TYPES = ("RateLimitError", "Push2RateLimitError")
_PUSH2_RATE_LIMIT_HINTS = (
    "RemoteDisconnected", "Remote end closed", "Connection aborted",
    "ConnectionReset", "Max retries exceeded", "Too Many Requests", "429",
    "临时限流", "请求过多",
)


class _Push2Busy(Exception):
    """push2 请求排队超时：视同被限流，调用方应改用备用源"""


def _push2_lock() -> asyncio.Lock:
    """惰性创建全局锁（避免在 import 阶段绑定事件循环）"""
    global _PUSH2_LOCK
    if _PUSH2_LOCK is None:
        _PUSH2_LOCK = asyncio.Lock()
    return _PUSH2_LOCK


def _is_rate_limited(exc: BaseException) -> bool:
    """判断是否被东财限流/封禁（连接被重置或超时），而非普通解析错误

    akshare 1.20+ 会把 push2 的断连包装成 RateLimitError 并附中文提示，旧版本
    则直接抛 ConnectionError，因此既看异常链上的类名，也看文本特征。
    """
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True

    stack, seen = [exc], set()
    while stack:
        e = stack.pop()
        if id(e) in seen:
            continue
        seen.add(id(e))
        if type(e).__name__ in _PUSH2_RATE_LIMIT_TYPES:
            return True
        stack.extend(a for a in e.args if isinstance(a, BaseException))
        stack.extend(x for x in (e.__cause__, e.__context__) if x is not None)

    text = f"{type(exc).__name__}: {exc}"
    return any(hint in text for hint in _PUSH2_RATE_LIMIT_HINTS)


def _push2_available() -> bool:
    """push2 集群是否处于可用窗口（熔断未打开）"""
    return time.monotonic() >= _PUSH2_BLOCKED_UNTIL


def _mark_push2_unavailable(reason: str = ""):
    """标记 push2 集群不可用，熔断时长随连续失败次数递增"""
    global _PUSH2_BLOCKED_UNTIL, _PUSH2_FAIL_STREAK, _PUSH2_LAST_FAIL_AT
    now = time.monotonic()
    # 距上次失败已很久，说明中间恢复过，计数重新开始，避免历史失败把熔断永久拉到 30 分钟
    if _PUSH2_LAST_FAIL_AT and now - _PUSH2_LAST_FAIL_AT > _PUSH2_FAIL_RESET_SECONDS:
        _PUSH2_FAIL_STREAK = 0
    _PUSH2_LAST_FAIL_AT = now
    cooldown = _PUSH2_COOLDOWN_STEPS[min(_PUSH2_FAIL_STREAK, len(_PUSH2_COOLDOWN_STEPS) - 1)]
    _PUSH2_FAIL_STREAK += 1
    _PUSH2_BLOCKED_UNTIL = now + cooldown
    detail = f"：{reason}" if reason else ""
    logger.warning(
        f"东方财富 push2 不可用{detail}，熔断 {cooldown}s（连续第 {_PUSH2_FAIL_STREAK} 次），"
        f"期内改用备用数据源"
    )


def _clear_push2_unavailable():
    """push2 集群恢复可用：清零熔断与失败计数"""
    global _PUSH2_BLOCKED_UNTIL, _PUSH2_FAIL_STREAK, _PUSH2_LAST_FAIL_AT
    if _PUSH2_FAIL_STREAK:
        logger.info(f"东方财富 push2 恢复正常（此前连续失败 {_PUSH2_FAIL_STREAK} 次）")
    _PUSH2_FAIL_STREAK = 0
    _PUSH2_LAST_FAIL_AT = 0.0
    _PUSH2_BLOCKED_UNTIL = 0.0


@asynccontextmanager
async def _push2_guard(what: str):
    """push2 请求入口：串行 + 最小间隔 + 抖动；排队超时视同被限流"""
    global _PUSH2_LAST_CALL
    lock = _push2_lock()
    try:
        await asyncio.wait_for(lock.acquire(), timeout=_PUSH2_QUEUE_TIMEOUT)
    except asyncio.TimeoutError:
        _mark_push2_unavailable(f"{what} 排队超时")
        raise _Push2Busy(f"{what}：push2 请求排队超时")

    try:
        # 排队期间熔断可能已被其他请求打开：此时不再发请求，直接让调用方走备用源，
        # 否则并发的一轮工具会各自撞一次限流，把熔断从 5 分钟叠加到 30 分钟
        if not _push2_available():
            raise _Push2Busy(f"{what}：push2 熔断中")

        elapsed = time.monotonic() - _PUSH2_LAST_CALL
        wait = _PUSH2_MIN_INTERVAL + random.uniform(*_PUSH2_JITTER) - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        yield
    finally:
        _PUSH2_LAST_CALL = time.monotonic()
        lock.release()


# 缓存: {key: (data, timestamp)}
_cache: dict[str, tuple[Any, float]] = {}
_MAX_CACHE_ENTRIES = 200
# 默认 TTL（秒）
_CACHE_TTL = {
    "global_market": 600,     # 10分钟（全球市场实时行情；push2 易被限流，靠缓存摊薄请求）
    "macro": 3600,            # 1小时（宏观数据变化慢）
    "margin": 600,            # 10分钟
    "news": 300,              # 5分钟
    "bdi": 3600,              # 1小时
    "market_index": 60,       # 1分钟（大盘指数实时）
    "market_breadth": 300,    # 5分钟（涨跌统计；全A快照是重请求，缓存摊薄 push2 压力）
    "overseas": 120,          # 2分钟（外盘商品/汇率快照）
    "futures": 180,           # 3分钟（期货日频，盘中变动慢）
    "bond": 3600,             # 1小时（国债收益率日频）
    "valuation": 3600,        # 1小时（估值日频）
    "sentiment": 300,         # 5分钟（涨停/龙虎榜）
    "fundflow": 300,          # 5分钟（资金结构）
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
    """获取全球主要市场指数行情（东财 → 新浪降级 → 过期缓存降级）"""
    cached = _get_cached("global_market_overview", "global_market")
    if cached is not None:
        return cached

    if _push2_available():
        result = await _fetch_global_market_from_em()
        if result:
            _set_cached("global_market_overview", result)
            return result

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


async def _fetch_global_market_from_em() -> dict:
    """从东方财富获取全球指数（串行限流；限流不重试，非限流错误才退避重试）"""
    import akshare as ak
    for attempt in range(3):
        try:
            async with _push2_guard("全球指数"):
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

            _clear_push2_unavailable()
            return {
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
        except _Push2Busy:
            break
        except Exception as e:
            if _is_rate_limited(e):
                # 限流后继续重试会把封禁从几分钟拉长到数小时，直接熔断走备用源
                logger.error(f"全球市场行情被限流，停止重试: {e}")
                _mark_push2_unavailable("全球指数被限流")
                break
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s → 2s
                continue
            logger.error(f"获取全球市场行情失败(非限流，已重试3次): {e}")
    return {}


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

    if not _push2_available():
        return {"error": f"{symbol} 历史数据暂不可用（push2 熔断中）", "unavailable": True}

    try:
        import akshare as ak
        async with _push2_guard(f"全球指数历史 {symbol}"):
            df = await _run_with_timeout(ak.index_global_hist_em, symbol=symbol, timeout=20)
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
    except _Push2Busy as e:
        return {"error": str(e), "unavailable": True}
    except Exception as e:
        if _is_rate_limited(e):
            _mark_push2_unavailable("全球指数历史被限流")
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
    """获取大盘主要指数实时行情（新浪主源 → 东财备用 → 过期缓存降级）"""
    cached = _get_cached("market_indices", "market_index")
    if cached is not None:
        return cached

    # 主源用新浪：东方财富 push2 接口在部分网络环境会被直接重置连接（RemoteDisconnected），
    # akshare 内部重试叠加退避后单次调用耗时 20s+，只能退居备用
    indices = await _fetch_market_indices_from_sina()
    source = "sina"
    if not indices:
        indices = await _fetch_market_indices_from_em()
        source = "eastmoney"

    if indices:
        result = {"indices": indices, "count": len(indices), "source": source}
        _set_cached("market_indices", result)
        return result

    expired = _get_expired_cache("market_indices")
    if expired:
        expired["_stale"] = True
        return expired
    logger.error("获取大盘指数失败：新浪与东方财富均不可用")
    return {"error": "大盘指数数据暂不可用"}


async def _fetch_market_indices_from_sina() -> list:
    """从新浪财经API获取A股主要指数（主数据源，字段完整且响应快）"""
    import httpx
    # key 同时用于拼 URL 和回填名称，名称不取自响应文本，避免 GBK 解码差异
    codes = {
        "sh000001": ("上证指数", "000001"), "sz399001": ("深证成指", "399001"),
        "sz399006": ("创业板指", "399006"), "sh000688": ("科创50", "000688"),
        "sh000300": ("沪深300", "000300"), "sh000905": ("中证500", "000905"),
        "sh000852": ("中证1000", "000852"),
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
                info = codes.get(key)
                if not info or len(vals) < 10:
                    continue
                # 完整行情字段：0名称 1今开 2昨收 3现价 4最高 5最低 6买一 7卖一 8成交量(股) 9成交额(元)
                try:
                    name, code = info
                    open_px = float(vals[1])
                    prev_close = float(vals[2])
                    price = float(vals[3])
                    high = float(vals[4])
                    low = float(vals[5])
                    amount = float(vals[9])
                except (ValueError, IndexError):
                    continue
                # 集合竞价前现价为 0，用昨收兜底，避免出现 -100% 的假涨跌幅
                if price <= 0:
                    price = prev_close
                change = price - prev_close
                change_pct = change / prev_close * 100 if prev_close else 0.0
                indices.append({
                    "name": name, "code": code,
                    "price": round(price, 2),
                    "change_pct": round(change_pct, 2),
                    "change": round(change, 2),
                    "volume_yi": round(amount / 1e8, 2),
                    "high": round(high, 2) if high else "",
                    "low": round(low, 2) if low else "",
                    "open": round(open_px, 2) if open_px else "",
                    "prev_close": round(prev_close, 2),
                })
            return indices
    except Exception as e:
        logger.warning(f"新浪大盘指数获取失败: {e}")
    return []


async def _fetch_market_indices_from_em() -> list:
    """从东方财富获取A股主要指数（备用数据源，字段更全但部分网络环境不可达）"""
    if not _push2_available():
        return []
    import akshare as ak
    for attempt in range(2):
        try:
            async with _push2_guard("大盘指数"):
                df = await _run_with_timeout(ak.stock_zh_index_spot_em, timeout=15)
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
            _clear_push2_unavailable()
            return indices
        except _Push2Busy:
            break
        except Exception as e:
            if _is_rate_limited(e):
                logger.warning(f"东方财富大盘指数被限流，停止重试: {e}")
                _mark_push2_unavailable("大盘指数被限流")
                break
            if attempt < 1:
                await asyncio.sleep(1)
                continue
            logger.warning(f"东方财富大盘指数获取失败(非限流): {e}")
    return []


async def get_market_breadth_real() -> dict:
    """获取真实市场涨跌统计（东财全A行情 → 乐咕涨跌家数备用 → 过期缓存降级）"""
    cached = _get_cached("market_breadth_real", "market_breadth")
    if cached is not None:
        return cached

    result = await _fetch_market_breadth_from_em() if _push2_available() else {}
    if not result:
        result = await _fetch_market_breadth_from_legu()
    if result:
        _set_cached("market_breadth_real", result)
        return result

    expired = _get_expired_cache("market_breadth_real")
    if expired:
        expired["_stale"] = True
        return expired
    return {"error": "市场涨跌数据暂不可用"}


async def _fetch_market_breadth_from_em() -> dict:
    """从东方财富全A行情统计涨跌家数与涨跌幅分布（串行限流；限流不重试）"""
    import akshare as ak
    for attempt in range(2):
        try:
            async with _push2_guard("全A行情"):
                df = await _run_with_timeout(ak.stock_zh_a_spot_em, timeout=20)
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

            _clear_push2_unavailable()
            return {
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
                "source": "eastmoney",
            }
        except _Push2Busy:
            break
        except Exception as e:
            if _is_rate_limited(e):
                logger.error(f"获取市场涨跌统计被限流，停止重试: {e}")
                _mark_push2_unavailable("全A行情被限流")
                break
            if attempt < 1:
                await asyncio.sleep(1)
                continue
            logger.error(f"获取市场涨跌统计失败(非限流): {e}")
    return {}


async def _fetch_market_breadth_from_legu() -> dict:
    """从乐咕乐股获取涨跌家数（备用源，无涨跌幅分布字段）"""
    import akshare as ak
    try:
        df = await _run_with_timeout(ak.stock_market_activity_legu, timeout=15)
        if df is None or df.empty:
            return {}
        activity = {str(r["item"]).strip(): r["value"] for _, r in df.iterrows()}
        up = int(float(activity.get("上涨", 0) or 0))
        down = int(float(activity.get("下跌", 0) or 0))
        flat = int(float(activity.get("平盘", 0) or 0))
        total = up + down + flat
        if total == 0:
            return {}
        return {
            "total_stocks": total,
            "up": up,
            "down": down,
            "flat": flat,
            "up_down_ratio": round(up / max(down, 1), 2),
            "limit_up": int(float(activity.get("真实涨停", 0) or 0)),
            "limit_down": int(float(activity.get("真实跌停", 0) or 0)),
            "up_pct": round(up / total * 100, 1),
            "activity": str(activity.get("活跃度", "")),
            "stat_time": str(activity.get("统计日期", "")),
            "source": "legu",
        }
    except Exception as e:
        logger.warning(f"乐咕涨跌家数获取失败: {e}")
    return {}


# ============================================================
# 外盘商品与人民币汇率
# ============================================================

# 新浪外盘期货：0 最新价, 4 最高, 5 最低, 6 时间, 7 昨收, 8 开盘, 12 日期, 13 名称
_SINA_HF_SYMBOLS = {
    "hf_CL": "WTI原油", "hf_OIL": "布伦特原油", "hf_GC": "COMEX黄金",
    "hf_SI": "COMEX白银", "hf_HG": "COMEX铜", "hf_NG": "美国天然气",
    "hf_CHA50CFD": "富时A50期货",
}


def _safe_float(v, default: float = 0.0) -> float:
    """安全转 float，NaN/None/非法值返回 default"""
    try:
        f = float(v)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


async def _fetch_sina_hf() -> list[dict]:
    """新浪外盘期货实时快照"""
    import re

    import httpx
    url = f"https://hq.sinajs.cn/list={','.join(_SINA_HF_SYMBOLS)}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={
                "Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0",
            })
        if resp.status_code != 200:
            return []
        out = []
        for line in resp.text.strip().split("\n"):
            m = re.match(r'var hq_str_(\w+)="(.*)"', line.strip())
            if not m:
                continue
            code, vals = m.group(1), m.group(2).split(",")
            last, prev = _safe_float(vals[0]), _safe_float(vals[7]) if len(vals) > 7 else 0.0
            if last <= 0 or prev <= 0:
                continue
            out.append({
                "name": vals[13] if len(vals) > 13 and vals[13] else _SINA_HF_SYMBOLS.get(code, code),
                "price": round(last, 3),
                "change_pct": round((last - prev) / prev * 100, 2),
                "date": vals[12] if len(vals) > 12 else "",
            })
        return out
    except Exception as e:
        logger.warning(f"新浪外盘期货获取失败: {e}")
        return []


async def _fetch_cny_midprice(days: int = 25) -> dict:
    """人民币兑美元中间价趋势（避开外汇实时接口的字段歧义）"""
    import akshare as ak
    from datetime import datetime, timedelta

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    try:
        df = await _run_with_timeout(
            ak.currency_boc_sina, symbol="美元", start_date=start, end_date=end, timeout=20
        )
    except Exception as e:
        logger.warning(f"人民币中间价获取失败: {e}")
        return {"error": str(e)}
    rows = [r for r in _df_to_records(df) if _safe_float(r.get("央行中间价")) > 0]
    if not rows:
        return {"error": "人民币中间价为空"}

    level = _safe_float(rows[-1].get("央行中间价")) / 100  # 源数据 671.80 → 6.718

    def _chg(n: int):
        if len(rows) <= n:
            return None
        base = _safe_float(rows[-1 - n].get("央行中间价")) / 100
        return round((level - base) / base * 100, 2) if base > 0 else None

    return {
        "date": str(rows[-1].get("日期"))[:10],
        "usd_cny_midprice": round(level, 4),
        "change_pct_5d": _chg(5),
        "change_pct_20d": _chg(20),
        "note": "数值下降=人民币升值",
    }


async def get_overseas_commodity_fx() -> dict:
    """外盘商品（原油/贵金属/铜/天然气/A50期货）与人民币中间价快照"""
    cached = _get_cached("overseas_commodity_fx", "overseas")
    if cached is not None:
        return cached

    commodities, cny = await asyncio.gather(_fetch_sina_hf(), _fetch_cny_midprice())
    if not commodities:
        expired = _get_expired_cache("overseas_commodity_fx")
        if expired:
            expired["_stale"] = True
            return expired
        return {"error": "外盘商品数据暂不可用", "cny": cny}

    result = {"commodities": commodities, "cny": cny}
    a50 = next((c for c in commodities if "A50" in c["name"]), None)
    if a50:
        result["foreign_sentiment_proxy"] = f"富时A50期货 {a50['change_pct']:+.2f}%（隔夜外盘对A股的开盘指引）"
    _set_cached("overseas_commodity_fx", result)
    return result


# ============================================================
# 股指期货基差
# ============================================================

_FUT_SPOT_MAP = [
    ("IF0", "沪深300", "sh000300"),
    ("IH0", "上证50", "sh000016"),
    ("IC0", "中证500", "sh000905"),
    ("IM0", "中证1000", "sh000852"),
]


async def _fetch_sina_index_quotes(codes: list[str]) -> dict:
    """新浪宽基指数快照: 1 今开, 2 昨收, 3 最新"""
    import re

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://hq.sinajs.cn/list={','.join(codes)}",
                headers={"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"},
            )
        out = {}
        for line in resp.text.strip().split("\n"):
            m = re.match(r'var hq_str_(\w+)="(.*)"', line.strip())
            if not m:
                continue
            vals = m.group(2).split(",")
            if len(vals) < 4:
                continue
            out[m.group(1)] = {"last": _safe_float(vals[3]), "prev_close": _safe_float(vals[2])}
        return out
    except Exception as e:
        logger.warning(f"新浪宽基指数获取失败: {e}")
        return {}


async def get_index_futures_basis() -> dict:
    """四大股指期货主力基差（期货-现货），贴水收窄/转升水反映机构预期改善"""
    cached = _get_cached("index_futures_basis", "futures")
    if cached is not None:
        return cached

    import akshare as ak
    tasks = [_fetch_sina_index_quotes([c for _, _, c in _FUT_SPOT_MAP])]
    tasks += [_run_with_timeout(ak.futures_main_sina, symbol=code, timeout=15) for code, _, _ in _FUT_SPOT_MAP]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    spot = results[0] if isinstance(results[0], dict) else {}

    rows = []
    for (code, name, spot_code), df in zip(_FUT_SPOT_MAP, results[1:]):
        if isinstance(df, Exception) or df is None or len(df) < 2:
            continue
        last, prev = df.iloc[-1], df.iloc[-2]
        fut, fut_prev = _safe_float(last["收盘价"]), _safe_float(prev["收盘价"])
        oi, oi_prev = _safe_float(last["持仓量"]), _safe_float(prev["持仓量"])
        s = spot.get(spot_code) or {}
        if fut <= 0 or s.get("last", 0) <= 0:
            continue
        basis_pct = (fut - s["last"]) / s["last"] * 100
        prev_basis = ((fut_prev - s["prev_close"]) / s["prev_close"] * 100
                      if fut_prev > 0 and s.get("prev_close", 0) > 0 else None)
        rows.append({
            "contract": code,
            "target": name,
            "date": str(last["日期"])[:10],
            "futures_close": round(fut, 2),
            "spot_close": round(s["last"], 2),
            "basis": round(fut - s["last"], 2),
            "basis_pct": round(basis_pct, 2),
            "basis_pct_prev": round(prev_basis, 2) if prev_basis is not None else None,
            "basis_change": round(basis_pct - prev_basis, 2) if prev_basis is not None else None,
            "state": "贴水" if basis_pct < 0 else "升水",
            "oi_change_pct": round((oi - oi_prev) / oi_prev * 100, 2) if oi_prev > 0 else None,
        })

    if not rows:
        return {"error": "股指期货基差数据暂不可用"}
    result = {
        "rows": rows,
        "note": "基差=期货-现货，负为贴水；basis_change>0 表示贴水收窄（预期改善），<0 表示贴水加深（对冲/看空压力上升）",
    }
    _set_cached("index_futures_basis", result)
    return result


# ============================================================
# 国债收益率曲线（期限利差 + 中美利差）
# ============================================================

async def get_bond_curve_summary(days: int = 40) -> dict:
    """中债 2/5/10/30Y、10Y-2Y 期限利差、中美 10Y 利差及 20 日变化"""
    cache_key = f"bond_curve_{days}"
    cached = _get_cached(cache_key, "bond")
    if cached is not None:
        return cached

    import akshare as ak
    from datetime import datetime, timedelta

    start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    try:
        df = await _run_with_timeout(ak.bond_zh_us_rate, start_date=start, timeout=25)
    except Exception as e:
        logger.error(f"获取国债收益率失败: {e}")
        return {"error": str(e)}
    rows = [r for r in _df_to_records(df) if _safe_float(r.get("中国国债收益率10年")) > 0]
    if not rows:
        return {"error": "国债收益率数据为空"}

    latest = rows[-1]
    # 中债变化用真正的 20 个交易日前做基准；中美利差需美债同时有值（美债序列早期缺失）
    base_cn = rows[-21] if len(rows) > 21 else rows[0]
    base_both = None
    for r in reversed(rows[-26:-1] or rows[:-1]):
        if _safe_float(r.get("中国国债收益率10年")) > 0 and _safe_float(r.get("美国国债收益率10年")) > 0:
            base_both = r
            break

    def _bp(key: str, base: dict | None):
        if not base:
            return None
        cur, old = _safe_float(latest.get(key)), _safe_float(base.get(key))
        return round((cur - old) * 100, 1) if cur > 0 and old > 0 else None

    cn10, us10 = _safe_float(latest.get("中国国债收益率10年")), _safe_float(latest.get("美国国债收益率10年"))
    cn10_old = _safe_float((base_both or {}).get("中国国债收益率10年"))
    us10_old = _safe_float((base_both or {}).get("美国国债收益率10年"))
    spread_now = (cn10 - us10) if cn10 > 0 and us10 > 0 else None
    spread_old = (cn10_old - us10_old) if cn10_old > 0 and us10_old > 0 else None

    result = {
        "as_of": str(latest.get("日期"))[:10],
        "china": {
            "2y": _safe_float(latest.get("中国国债收益率2年")),
            "5y": _safe_float(latest.get("中国国债收益率5年")),
            "10y": cn10,
            "30y": _safe_float(latest.get("中国国债收益率30年")),
            "curve_10y_2y": _safe_float(latest.get("中国国债收益率10年-2年")),
            "10y_change_bp_20d": _bp("中国国债收益率10年", base_cn),
        },
        "us": {
            "2y": _safe_float(latest.get("美国国债收益率2年")),
            "10y": us10,
            "30y": _safe_float(latest.get("美国国债收益率30年")),
            "10y_change_bp_since": _bp("美国国债收益率10年", base_both),
            "change_base_date": str(base_both.get("日期"))[:10] if base_both else None,
        },
        "cn_us_10y_spread": round(spread_now, 2) if spread_now is not None else None,
        "cn_us_10y_spread_change_bp_since": (
            round((spread_now - spread_old) * 100, 1)
            if spread_now is not None and spread_old is not None else None
        ),
        "note": "收益率下行(bp为负)=债市走强/宽松预期；中美利差负值扩大通常对应人民币贬值压力与外资流出"
                "；美债变化以 change_base_date 为基准（美债序列存在缺失，非固定20日）",
    }
    _set_cached(cache_key, result)
    return result


# ============================================================
# 涨停/炸板/龙虎榜（情绪温度）
# ============================================================

async def get_limit_up_stats(date_str: str) -> dict:
    """涨停家数、炸板率、连板梯队、行业分布与龙虎榜机构动向（date_str: YYYY-MM-DD）"""
    cache_key = f"limit_up_{date_str}"
    cached = _get_cached(cache_key, "sentiment")
    if cached is not None:
        return cached

    import akshare as ak
    from collections import Counter

    compact = date_str.replace("-", "")
    zt_df, zb_df, lhb_df = await asyncio.gather(
        _run_with_timeout(ak.stock_zt_pool_em, date=compact, timeout=25),
        _run_with_timeout(ak.stock_zt_pool_zbgc_em, date=compact, timeout=25),
        _run_with_timeout(ak.stock_lhb_detail_em, start_date=compact, end_date=compact, timeout=25),
        return_exceptions=True,
    )

    zt_rows = [] if isinstance(zt_df, Exception) or zt_df is None else _df_to_records(zt_df)
    if not zt_rows:
        return {"date": date_str, "unavailable": True,
                "error": f"{date_str} 无涨停池数据（非交易日或数据尚未生成）"}

    broken = 0 if isinstance(zb_df, Exception) or zb_df is None else len(zb_df)
    boards = Counter(int(_safe_float(r.get("连板数"), 1)) for r in zt_rows)
    industry = Counter(str(r.get("所属行业", "")).strip() for r in zt_rows if r.get("所属行业"))

    result = {
        "date": date_str,
        "limit_up": len(zt_rows),
        "broken": broken,
        "broken_rate": round(broken / max(len(zt_rows) + broken, 1) * 100, 1),
        "max_boards": max(boards) if boards else 0,
        "board_distribution": {f"{k}板": v for k, v in sorted(boards.items(), reverse=True)},
        "top_industries": [{"industry": k, "count": v} for k, v in industry.most_common(5)],
    }
    if not isinstance(lhb_df, Exception) and lhb_df is not None and len(lhb_df) > 0:
        lhb_rows = _df_to_records(lhb_df)
        inst = [r for r in lhb_rows if "机构" in str(r.get("解读", ""))]
        # 同一只票在龙虎榜有多条解读行，按名称去重取最大净买额
        best: dict[str, dict] = {}
        for r in inst:
            name = str(r.get("名称", ""))
            net = _safe_float(r.get("龙虎榜净买额"))
            if net > best.get(name, {}).get("net", -1e18):
                best[name] = {"net": net, "change_pct": _safe_float(r.get("涨跌幅"))}
        ranked = sorted(best.items(), key=lambda kv: kv[1]["net"], reverse=True)
        result["lhb"] = {
            "listed_count": len(lhb_rows),
            "institution_count": len(inst),
            "top_inst_net_buy_yi": [
                {"name": name, "net_buy_yi": round(item["net"] / 1e8, 2),
                 "change_pct": round(item["change_pct"], 2)}
                for name, item in ranked[:3] if item["net"] > 0
            ],
        }
    _set_cached(cache_key, result)
    return result


# ============================================================
# 全市场资金结构（超大单/大单/中单/小单）
# ============================================================

async def get_market_fund_structure(days: int = 5) -> dict:
    """按单笔金额拆分的全市场净流入，区分机构(超大单/大单)与散户(中单/小单)"""
    cache_key = f"fund_structure_{days}"
    cached = _get_cached(cache_key, "fundflow")
    if cached is not None:
        return cached

    if not _push2_available():
        return {"error": "东方财富 push2 暂不可用（熔断中）", "unavailable": True}

    import akshare as ak
    try:
        async with _push2_guard("全市场资金流"):
            df = await _run_with_timeout(ak.stock_market_fund_flow, timeout=20)
    except _Push2Busy as e:
        return {"error": str(e), "unavailable": True}
    except Exception as e:
        if _is_rate_limited(e):
            _mark_push2_unavailable("全市场资金流被限流")
        logger.error(f"获取全市场资金结构失败: {e}")
        return {"error": str(e)}
    rows = _df_to_records(df)
    if not rows:
        return {"error": "全市场资金流数据为空"}

    daily = [{
        "date": str(r.get("日期"))[:10],
        "index_change_pct": round(_safe_float(r.get("上证-涨跌幅")), 2),
        "main_yi": round(_safe_float(r.get("主力净流入-净额")) / 1e8, 1),
        "xl_yi": round(_safe_float(r.get("超大单净流入-净额")) / 1e8, 1),
        "l_yi": round(_safe_float(r.get("大单净流入-净额")) / 1e8, 1),
        "m_yi": round(_safe_float(r.get("中单净流入-净额")) / 1e8, 1),
        "s_yi": round(_safe_float(r.get("小单净流入-净额")) / 1e8, 1),
    } for r in rows[-days:]]

    today = daily[-1]
    result = {
        "daily": daily,
        f"sum_{len(daily)}d": {k: round(sum(d[k] for d in daily), 1)
                               for k in ("main_yi", "xl_yi", "l_yi", "m_yi", "s_yi")},
        "today_structure": ("机构进场/散户离场" if today["xl_yi"] > 0 > today["s_yi"]
                            else "散户接盘/机构离场" if today["s_yi"] > 0 > today["xl_yi"] else "同步"),
        "note": "xl=超大单(机构)、s=小单(散户)；单位亿元",
    }
    _set_cached(cache_key, result)
    return result


# ============================================================
# 全市场估值分位
# ============================================================

async def get_full_market_valuation() -> dict:
    """全 A 估值分位（中位/平均 PE-TTM）+ 沪深300/中证500 市盈率"""
    cached = _get_cached("full_market_valuation", "valuation")
    if cached is not None:
        return cached

    import akshare as ak
    ttm_df, pe300_df, pe500_df = await asyncio.gather(
        _run_with_timeout(ak.stock_a_ttm_lyr, timeout=25),
        _run_with_timeout(ak.stock_index_pe_lg, symbol="沪深300", timeout=25),
        _run_with_timeout(ak.stock_index_pe_lg, symbol="中证500", timeout=25),
        return_exceptions=True,
    )

    result: dict = {}
    if not isinstance(ttm_df, Exception) and ttm_df is not None and len(ttm_df) > 0:
        rows = _df_to_records(ttm_df)
        latest, base = rows[-1], (rows[-21] if len(rows) > 21 else rows[0])
        cur, old = _safe_float(latest.get("middlePETTM")), _safe_float(base.get("middlePETTM"))
        result["all_a"] = {
            "date": str(latest.get("date"))[:10],
            "median_pe_ttm": round(cur, 2),
            "average_pe_ttm": round(_safe_float(latest.get("averagePETTM")), 2),
            "pe_change_pct_20d": round((cur - old) / old * 100, 1) if old > 0 else None,
            "quantile_all_history": round(_safe_float(latest.get("quantileInAllHistoryMiddlePeTtm")) * 100, 1),
            "quantile_10y": round(_safe_float(latest.get("quantileInRecent10YearsMiddlePeTtm")) * 100, 1),
        }
    for key, df in (("csi300", pe300_df), ("csi500", pe500_df)):
        if isinstance(df, Exception) or df is None or len(df) == 0:
            continue
        last = _df_to_records(df)[-1]
        result[key] = {
            "date": str(last.get("日期"))[:10],
            "index_close": round(_safe_float(last.get("指数")), 2),
            "pe_ttm": round(_safe_float(last.get("滚动市盈率")), 2),
            "pe_lyr": round(_safe_float(last.get("静态市盈率")), 2),
        }
    if not result:
        return {"error": "全市场估值数据暂不可用"}
    result["note"] = "quantile 为历史分位(%)，越低越便宜；仅反映相对自身历史的位置"
    _set_cached("full_market_valuation", result)
    return result


# ============================================================
# 国内商品期货主力趋势
# ============================================================

_CN_FUTURES = {"SC0": "原油", "RB0": "螺纹钢", "I0": "铁矿石", "CU0": "沪铜"}


async def get_commodity_futures_trend(days: int = 20) -> dict:
    """国内商品期货主力连续涨跌与持仓变化，用于周期板块（石化/钢铁/有色）景气跟踪"""
    cache_key = f"commodity_trend_{days}"
    cached = _get_cached(cache_key, "futures")
    if cached is not None:
        return cached

    import akshare as ak
    results = await asyncio.gather(
        *[_run_with_timeout(ak.futures_main_sina, symbol=code, timeout=15) for code in _CN_FUTURES],
        return_exceptions=True,
    )

    rows = []
    for (code, name), df in zip(_CN_FUTURES.items(), results):
        if isinstance(df, Exception) or df is None or len(df) < 2:
            continue
        closes = [_safe_float(v) for v in df["收盘价"].tolist() if _safe_float(v) > 0]
        ois = [_safe_float(v) for v in df["持仓量"].tolist()]
        if len(closes) < 2:
            continue

        def _pct(n: int):
            return round((closes[-1] - closes[-1 - n]) / closes[-1 - n] * 100, 2) if len(closes) > n else None

        oi_now = ois[-1] if ois else 0
        oi_5 = ois[-6] if len(ois) > 5 else 0
        rows.append({
            "symbol": code,
            "name": name,
            "date": str(df.iloc[-1]["日期"])[:10],
            "close": round(closes[-1], 2),
            "chg_1d": _pct(1),
            "chg_5d": _pct(5),
            "chg_20d": _pct(min(days, 20)),
            "oi_change_pct_5d": round((oi_now - oi_5) / oi_5 * 100, 2) if oi_5 > 0 else None,
        })
    if not rows:
        return {"error": "商品期货数据暂不可用"}
    result = {"rows": rows, "note": "主力连续合约；持仓量放大+价格上涨通常表示趋势获得增量资金确认"}
    _set_cached(cache_key, result)
    return result


# ============================================================
# 缓存管理
# ============================================================

def clear_external_cache():
    """清空所有外部数据缓存"""
    _cache.clear()
    logger.info("外部数据缓存已清空")


def get_cache_stats() -> dict:
    """获取缓存统计与 push2 熔断状态"""
    now = time.time()
    stats = {}
    for key, (_, ts) in _cache.items():
        stats[key] = f"{now - ts:.0f}s ago"
    return {
        "cache_entries": len(_cache),
        "entries": stats,
        "push2": {
            "available": _push2_available(),
            "blocked_for_s": max(0, round(_PUSH2_BLOCKED_UNTIL - time.monotonic())),
            "fail_streak": _PUSH2_FAIL_STREAK,
        },
    }
