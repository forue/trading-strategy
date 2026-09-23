"""AI 决策服务 - FastAPI 主应用"""
import sys
import os
import json
import asyncio
import threading
from typing import Optional
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from .config import settings
from .model_adapter import ModelAdapterFactory, BaseLLMClient
from .signal_analyzer import SignalAnalyzer, SignalAnalysis, MarketContext
from shared import RabbitMQManager, RedisManager, success_response

logger.remove()
logger.add(sys.stderr, level=settings.log_level)

rmq = RabbitMQManager()
redis_mgr = RedisManager()
_mq_thread = None
llm_client: BaseLLMClient = None
signal_llm_client: BaseLLMClient = None  # 信号分析专用 LLM 客户端
analyzer: SignalAnalyzer = None
_main_loop: asyncio.AbstractEventLoop = None


def _resolve_default_llm_args(config: dict) -> Optional[dict]:
    """解析默认 LLM 客户端的创建参数（不含 ollama_* 参数）

    ai:config 里的 provider / api_key / base_url 是前端设置页不再写入的遗留字段
    （设置页只写 temperature / max_tokens / signal_analysis_*），真实凭据保存在
    ai:providers，因此按 provider id 回查凭据；回查不到时退回信号分析提供商（后端唯一由
    用户选定的提供商），否则默认客户端恒定创建失败——每日复盘会返回
    "NoneType object has no attribute chat" 的假报告。

    非 ollama 的提供商统一走 OpenAI 兼容协议分支（与信号分析专用客户端一致）。
    """
    provider_mgr = _get_provider_mgr()
    provider_id = config.get("provider", "")
    if provider_id == "ollama":
        return {"provider": "ollama", "model": config.get("ollama_model", settings.ollama_model)}

    # 1. 遗留字段 provider 对应的凭据
    provider_config = provider_mgr.get(provider_id) if provider_id else None
    if provider_config and provider_config.api_key:
        return {
            "provider": "openai",
            "api_key": provider_config.api_key,
            "base_url": provider_config.base_url,
            "model": config.get("model", settings.ai_model),
        }

    # 2. 退回信号分析提供商（与其共用凭据与模型）
    signal_provider = config.get("signal_analysis_provider", "")
    signal_config = provider_mgr.get(signal_provider) if signal_provider else None
    if signal_config and signal_config.api_key:
        return {
            "provider": "openai",
            "api_key": signal_config.api_key,
            "base_url": signal_config.base_url,
            "model": config.get("signal_analysis_model") or config.get("model", settings.ai_model),
        }

    # 3. 兜底：ai:config 里直接写了凭据（直接调用 API 写入的旧配置）
    if config.get("api_key"):
        return {
            "provider": config.get("provider", settings.ai_provider),
            "api_key": config["api_key"],
            "base_url": config.get("base_url", settings.ai_base_url),
            "model": config.get("model", settings.ai_model),
        }
    return None


def _init_llm():
    """初始化 LLM 客户端（优先从 Redis 加载配置）

    初始化顺序：先尝试信号分析专用模型，再尝试默认模型。
    至少一个成功即视为就绪，默认模型失败不阻断专用模型的初始化。
    """
    global llm_client, signal_llm_client, analyzer
    config = _load_ai_config()

    # 1. 信号分析专用 LLM 客户端（优先）
    signal_provider = config.get("signal_analysis_provider", "")
    signal_model = config.get("signal_analysis_model", "")
    if signal_provider and signal_model:
        try:
            if signal_provider == "ollama":
                signal_llm_client = ModelAdapterFactory.create(
                    provider="ollama",
                    ollama_base_url=config.get("ollama_base_url", settings.ollama_base_url),
                    ollama_model=signal_model,
                )
            else:
                provider_mgr = _get_provider_mgr()
                provider_config = provider_mgr.get(signal_provider)
                if provider_config and provider_config.api_key:
                    signal_llm_client = ModelAdapterFactory.create(
                        provider="openai",
                        api_key=provider_config.api_key,
                        base_url=provider_config.base_url,
                        model=signal_model,
                    )
            if signal_llm_client:
                logger.info(f"信号分析专用 LLM 客户端初始化完成: provider={signal_provider}, model={signal_model}")
        except Exception as e:
            logger.warning(f"信号分析专用 LLM 客户端初始化失败: {e}")

    # 2. 默认 LLM 客户端（辅助用，失败不阻断）
    if not llm_client:
        try:
            llm_args = _resolve_default_llm_args(config)
            if not llm_args:
                logger.warning("默认 LLM 客户端未初始化：ai:providers 中没有可用凭据的提供商")
            else:
                llm_client = ModelAdapterFactory.create(
                    ollama_base_url=config.get("ollama_base_url", settings.ollama_base_url),
                    ollama_model=config.get("ollama_model", settings.ollama_model),
                    **llm_args,
                )
                logger.info(f"默认 LLM 客户端初始化完成: provider={llm_args['provider']}, model={llm_args['model']}")
        except Exception as e:
            logger.warning(f"默认 LLM 客户端初始化失败（信号分析不受影响）: {e}")

    # 3. 使用专用客户端或默认客户端
    if signal_llm_client or llm_client:
        analyzer = SignalAnalyzer(signal_llm_client or llm_client)
        logger.info("信号分析器初始化完成")
    else:
        logger.error("所有 LLM 客户端初始化均失败，信号解读不可用")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_loop
    _main_loop = asyncio.get_event_loop()
    rmq.connect(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        user=settings.rabbitmq_user,
        password=settings.rabbitmq_password,
    )
    redis_mgr.connect(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        db=settings.redis_db,
    )
    _init_llm()
    global _mq_thread
    _mq_thread = threading.Thread(target=_start_consumer, daemon=True)
    _mq_thread.start()
    yield
    # 关闭所有 httpx 客户端，避免连接泄漏
    if llm_client and hasattr(llm_client, 'close'):
        await llm_client.close()
    if signal_llm_client and hasattr(signal_llm_client, 'close'):
        await signal_llm_client.close()
    for client in _client_cache.values():
        if hasattr(client, 'close'):
            await client.close()
    _client_cache.clear()
    if tool_executor and hasattr(tool_executor, 'close'):
        await tool_executor.close()
    rmq.close()
    redis_mgr.close()


app = FastAPI(title="AI 决策服务", version="1.0.0", lifespan=lifespan)


# ============================================================
# RabbitMQ 消费者
# ============================================================

def _start_consumer():
    """启动 RabbitMQ 消费者"""
    def callback(ch, method, properties, body):
        try:
            message = json.loads(body)
            event = message.get("event", "")
            logger.info(f"收到消息: {event}")

            if event == "signals_generated":
                if _main_loop and not _main_loop.is_closed():
                    future = asyncio.run_coroutine_threadsafe(
                        _handle_signals(message), _main_loop
                    )
                    try:
                        future.result(timeout=120)
                    except Exception as e:
                        logger.error(f"信号处理超时: {e}")
        except Exception as e:
            logger.error(f"消息处理失败: {e}")

    try:
        rmq.consume(
            queue="ai_decision",
            callback=callback,
            routing_key="signal.#",
        )
    except Exception as e:
        logger.error(f"RabbitMQ 消费者启动失败: {e}")


async def _fetch_signals_from_signal_service(strategy_type: str, signal_date: str) -> list:
    """从信号通知服务获取信号数据（信号存在 signal 服务的 Redis 中）

    上游不可用或返回异常时抛 502：否则调用方会把服务故障当成"当日无信号"，
    在界面上显示为"暂无信号"，掩盖真实故障。
    """
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.signal_url}/signals/today",
                params={"strategy_type": strategy_type},
            )
            body = resp.json()
    except Exception as e:
        logger.error(f"从信号服务获取信号失败: {e}")
        raise HTTPException(status_code=502, detail=f"信号服务不可用: {e}")

    if body.get("code") != 200:
        logger.error(f"信号服务返回异常: {body.get('message')}")
        raise HTTPException(status_code=502, detail=f"信号服务返回异常: {body.get('message')}")

    signals = body.get("data") or []
    # 按日期过滤
    return [s for s in signals if s.get("signal_date", "") == signal_date]


async def _handle_signals(message: dict):
    """处理策略信号

    每次信号（重新）生成都会先作废该日期的旧 AI 分析，再决定是否解读：
    信号被重算/清空时，旧的解读必须失效，否则日历回放会展示过期结论。
    """
    signals = message.get("signals", [])
    strategy_type = message.get("strategy_type", "")
    signal_date = message.get("signal_date", "")

    if not signal_date:
        logger.warning("信号事件缺少 signal_date，跳过解读")
        return

    # 无论本次是否有信号，先作废该日期的旧 AI 分析。
    # 否则信号被重算/清空（如改为空仓、清仓）后，日历回放仍会展示过期的历史解读。
    cache_key = f"ai:analysis:{strategy_type}:{signal_date}"
    try:
        if redis_mgr.delete(cache_key):
            logger.info(f"已清除过期AI分析: {cache_key}（信号已重新生成）")
    except Exception as e:
        logger.warning(f"清除过期AI分析失败: {e}")

    if not signals:
        logger.info(f"{signal_date} 本次无信号（空仓/清仓），不生成AI分析")
        return

    if not analyzer:
        logger.warning("LLM 未初始化，跳过信号解读")
        return

    logger.info(f"开始解读 {len(signals)} 个信号: strategy={strategy_type}")

    # 获取真实市场数据构建上下文
    contexts = await _build_signal_contexts(signals, strategy_type)

    analyses = await analyzer.analyze_signals(signals, contexts=contexts)

    analysis_dicts = [a.model_dump() for a in analyses]

    cache_key = f"ai:analysis:{strategy_type}:{signal_date}"
    redis_mgr.setex(cache_key, 30 * 86400, json.dumps(analysis_dicts, ensure_ascii=False))

    rmq.publish("ai.signal.analyzed", {
        "event": "signal_analyzed",
        "strategy_type": strategy_type,
        "signal_date": signal_date,
        "analyses": analysis_dicts,
        "timestamp": datetime.now().isoformat(),
    })

    logger.info(f"信号解读完成: {len(analyses)} 个, strategy={strategy_type}")


async def _fetch_recent_signals(client, strategy_type: str, start_date: str, end_date: str) -> list[dict]:
    """拉取指定策略近段时间的历史信号（信号缓存 TTL 仅 7 天，实际可得区间可能更短）"""
    if not strategy_type:
        return []
    try:
        resp = await client.get(
            f"{settings.signal_url}/signals/history",
            params={"strategy_type": strategy_type, "start_date": start_date, "end_date": end_date},
        )
        body = resp.json()
        if body.get("code") == 200:
            return body.get("data", []) or []
    except Exception as e:
        logger.warning(f"获取历史信号失败: {e}")
    return []


def _format_signal_history(sector_signals: list[dict], records: list[dict]) -> str:
    """把该板块历史信号与行情对齐，生成"信号后收益/胜率"文本

    信号缓存 TTL 仅 7 天，故只按实际可得记录回溯，不夸大样本量。
    """
    if not sector_signals:
        return "近40天内该板块无历史信号记录"

    close_by_date = {}
    for r in records or []:
        day = str(r.get("_time") or r.get("date") or "")[:10]
        close = r.get("index_close")
        if day and close:
            close_by_date[day] = float(close)
    days_sorted = sorted(close_by_date)

    lines = []
    buy_rets: list[float] = []
    for sig in sorted(sector_signals, key=lambda x: str(x.get("signal_date", ""))):
        day = str(sig.get("signal_date", ""))
        direction = sig.get("direction", "")
        line = f"- {day} {direction} 评分{sig.get('score', '')}"
        if day in close_by_date:
            idx = days_sorted.index(day)
            end = min(idx + 5, len(days_sorted) - 1)
            if end > idx:
                ret = close_by_date[days_sorted[end]] / close_by_date[day] - 1
                line += f" → 信号后{end - idx}个交易日 {ret * 100:+.2f}%"
                if direction == "BUY":
                    buy_rets.append(ret)
        lines.append(line)

    if buy_rets:
        wins = sum(1 for r in buy_rets if r > 0)
        head = (
            f"近40天该板块历史信号 {len(sector_signals)} 次；其中 BUY 信号 {len(buy_rets)} 次"
            f"可验证，信号后至最新交易日上涨 {wins} 次（胜率 {wins / len(buy_rets) * 100:.0f}%），"
            f"平均收益 {sum(buy_rets) / len(buy_rets) * 100:+.2f}%"
        )
    else:
        head = f"近40天该板块历史信号 {len(sector_signals)} 次（信号后收益待后续交易日验证）"
    return head + "\n" + "\n".join(lines)


async def _fetch_market_index_change() -> float | None:
    """获取真实大盘（上证指数）当日涨跌幅（%），失败返回 None

    提示词中的"大盘涨跌幅"必须用该值。不能用全市场板块涨跌幅的等权均值代替，
    两者差异显著（2026-09-21 上证 +0.97% vs 板块等权均值 +1.86%），
    混用会放大市场强弱判断；风险预警阈值（1.0%/2.5%）也因此失真。
    """
    try:
        from .external_data import get_market_indices
        data = await get_market_indices()
        for item in data.get("indices") or []:
            if item.get("name") == "上证指数":
                return round(float(item.get("change_pct") or 0), 2)
        logger.warning(f"大盘指数数据中未找到上证指数: {list(data.keys())}")
    except Exception as e:
        logger.warning(f"获取大盘指数失败: {e}")
    return None


async def _get_with_retry(client, url: str, params: dict, attempts: int = 3, backoff: float = 2.0):
    """带退避重试的 GET 请求

    单次超时不代表数据不可得：采集任务在线程池排队或数据源限流时，
    查询接口可能短暂无响应，故重试若干次再判定失败。
    """
    last_exc: Optional[Exception] = None
    for i in range(attempts):
        try:
            return await client.get(url, params=params)
        except Exception as e:
            last_exc = e
            logger.warning(
                f"请求 {url} 失败（第 {i + 1}/{attempts} 次）: "
                f"{type(e).__name__}: {str(e) or '无附加信息'}"
            )
            if i < attempts - 1:
                await asyncio.sleep(backoff * (i + 1))
    raise last_exc


async def _build_signal_contexts(signals: list[dict], strategy_type: str = "") -> dict:
    """为信号解读构建真实的市场上下文（含近25天历史数据 + 历史信号回溯）

    关键请求带退避重试；仍取不到数据的板块写入 data_available=False 的占位上下文，
    使提示词把这些字段标注为"数据不可用"，避免把 0.0 当作真实行情解读。
    """
    from .signal_analyzer import MarketContext
    import httpx
    from datetime import timedelta

    contexts = {}
    data_collector_url = settings.data_collector_url
    # 同批信号来自同一策略；未显式传入时取信号自带字段
    if not strategy_type and signals:
        strategy_type = signals[0].get("strategy_type", "")

    try:
        async with httpx.AsyncClient(timeout=6) as client:
            today = datetime.now().strftime("%Y-%m-%d")
            start_15d = (datetime.now() - timedelta(days=25)).strftime("%Y-%m-%d")  # 25天确保覆盖15个交易日
            start_hist = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")

            # 历史信号（供"信号可靠性/历史胜率"分析）
            recent_signals = await _fetch_recent_signals(client, strategy_type, start_hist, today)

            # 获取当日全部板块数据（市场宽度）
            all_sectors = {}
            market_avg = 0.0
            try:
                resp = await _get_with_retry(
                    client, f"{data_collector_url}/query/all-sectors",
                    {"start_date": today, "end_date": today},
                )
                body = resp.json()
                if body.get("code") == 200 and body.get("data"):
                    for s in body["data"]:
                        all_sectors[s.get("sector_code", "")] = s
                    changes = [s.get("index_change_pct", 0) or 0 for s in body["data"]]
                    market_avg = sum(changes) / max(len(changes), 1)
            except Exception as e:
                logger.error(
                    f"获取全市场板块数据失败（重试后仍未成功）: {type(e).__name__}: {str(e) or '无附加信息'}"
                )

            if not all_sectors:
                logger.error("全市场板块数据为空，本次市场宽度与市场情绪将标注为不可用")

            # 大盘指数（真实上证指数）与板块等权均值是两个指标，分别传入上下文
            market_index_change = await _fetch_market_index_change()

            # 为每个信号的板块获取近15天历史数据
            for sig in signals:
                code = sig.get("sector_code", "")
                if not code:
                    continue
                try:
                    hist_resp = await _get_with_retry(
                        client, f"{data_collector_url}/query/sector-data",
                        {"sector_code": code, "start_date": start_15d, "end_date": today},
                    )
                    hist_data = hist_resp.json()
                    records = hist_data.get("data", []) if hist_data.get("code") == 200 else []

                    change_5d = 0.0
                    change_10d = 0.0
                    change_today = 0.0
                    main_flow = 0.0
                    turnover = 0.0
                    avg_flow_5d = None
                    pe_ttm = None
                    pb = None
                    pe_percentile = None
                    pb_percentile = None

                    if records:
                        chg = [r.get("index_change_pct", 0) or 0 for r in records]
                        flows = [r.get("main_net_inflow", 0) or 0 for r in records]
                        change_today = round(chg[-1], 2) if chg else 0
                        if len(chg) >= 5:
                            change_5d = round(sum(chg[-5:]), 2)
                            avg_flow_5d = round(sum(flows[-5:]) / 5 / 1e8, 2)
                        if len(chg) >= 10:
                            change_10d = round(sum(chg[-10:]), 2)
                        main_flow = flows[-1] if flows else 0
                        turnover = records[-1].get("turnover", 0) or 0
                        # 估值取自最新交易日（历史分位需≥10个交易日样本，早期为空）
                        pe_ttm = records[-1].get("pe_ttm")
                        pb = records[-1].get("pb")
                        pe_percentile = records[-1].get("pe_percentile")
                        pb_percentile = records[-1].get("pb_percentile")

                    # 市场宽度（全市场数据缺失时不得按 0 计算，否则会误判为"弱势"）
                    if all_sectors:
                        up_count = sum(1 for s in all_sectors.values() if (s.get("index_change_pct", 0) or 0) > 0)
                        total = max(len(all_sectors), 1)
                        up_ratio = up_count / total
                        if up_ratio >= 0.6:
                            sentiment = "强势"
                        elif up_ratio >= 0.5:
                            sentiment = "偏强"
                        elif up_ratio >= 0.4:
                            sentiment = "中性"
                        elif up_ratio >= 0.3:
                            sentiment = "偏弱"
                        else:
                            sentiment = "弱势"
                    else:
                        sentiment = "未知（全市场板块数据获取失败）"

                    # 该板块历史信号回溯（与行情对齐，给出信号后收益/胜率）
                    hit_signals = [s for s in recent_signals if s.get("sector_code") == code]
                    signal_history_text = _format_signal_history(hit_signals, records)

                    contexts[code] = MarketContext(
                        sector_code=code,
                        sector_name=sig.get("sector_name", ""),
                        change_5d=change_5d,
                        change_10d=change_10d,
                        change_today=change_today,
                        main_flow=main_flow,
                        north_flow=0.0,
                        # 北向净买额自 2024-08-19 起停止披露，采集值恒为 0，
                        # 标记为不可用以免 LLM 误读为"外资缺席"
                        north_flow_available=False,
                        turnover=turnover,
                        market_change=market_index_change or 0.0,
                        market_change_available=market_index_change is not None,
                        # 全市场数据缺失时传 None 而非 0.0，模板会渲染为"数据不可用"
                        market_avg_change=round(market_avg, 2) if all_sectors else None,
                        market_sentiment=sentiment,
                        signal_history_text=signal_history_text,
                        avg_flow_5d=avg_flow_5d,
                        pe_ttm=pe_ttm,
                        pb=pb,
                        pe_percentile=pe_percentile,
                        pb_percentile=pb_percentile,
                        etf_code=sig.get("etf_code", ""),
                        etf_name=sig.get("etf_name", ""),
                        rank=sig.get("rank"),
                        total_sectors=sig.get("total_sectors"),
                        # 未取到该板块行情时标记不可用，提示词据此渲染"数据不可用"
                        data_available=bool(records),
                    )
                except Exception as e:
                    logger.warning(
                        f"获取板块{code}数据失败: {type(e).__name__}: {str(e) or '无附加信息'}"
                    )
                    # 写入占位上下文，让提示词把该板块行情标注为不可用，
                    # 而不是把默认值 0.0 当作真实行情解读
                    contexts[code] = MarketContext(
                        sector_code=code,
                        sector_name=sig.get("sector_name", ""),
                        data_available=False,
                        etf_code=sig.get("etf_code", ""),
                        etf_name=sig.get("etf_name", ""),
                        rank=sig.get("rank"),
                        total_sectors=sig.get("total_sectors"),
                    )

    except Exception as e:
        logger.error(f"获取市场数据失败: {type(e).__name__}: {str(e) or '无附加信息'}")

    return contexts


# ============================================================
# REST API
# ============================================================

@app.get("/health")
async def health_check():
    checks = {}
    # LLM
    if llm_client:
        try:
            llm_ok = await llm_client.health_check()
            checks["llm"] = {"status": "pass" if llm_ok else "fail"}
        except Exception as e:
            checks["llm"] = {"status": "fail", "message": str(e)}
    else:
        checks["llm"] = {"status": "fail", "message": "未初始化"}
    # RabbitMQ consumer thread
    mq_alive = _mq_thread is not None and _mq_thread.is_alive()
    checks["mq_consumer"] = {"status": "pass" if mq_alive else "fail"}
    # RabbitMQ connection
    try:
        rmq_ok = rmq._connection and rmq._connection.is_open
        checks["rabbitmq"] = {"status": "pass" if rmq_ok else "fail"}
    except Exception as e:
        checks["rabbitmq"] = {"status": "fail", "message": str(e)}
    # Redis
    try:
        redis_mgr._client.ping()
        checks["redis"] = {"status": "pass"}
    except Exception as e:
        checks["redis"] = {"status": "fail", "message": str(e)}

    all_ok = all(c.get("status") == "pass" for c in checks.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "service": "ai-decision",
        "provider": settings.ai_provider,
        "checks": checks,
        "timestamp": datetime.now().isoformat(),
    }


class AnalyzeRequest(BaseModel):
    strategy_type: str = "MODERATE"
    signal_date: str = ""


@app.post("/api/ai/analyze-signal")
async def analyze_signal(request: AnalyzeRequest):
    """解读信号"""
    try:
        if not analyzer:
            raise HTTPException(status_code=503, detail="AI 服务未就绪，请检查 LLM 配置")

        signal_date = request.signal_date or datetime.now().strftime("%Y-%m-%d")
        cache_key = f"ai:analysis:{request.strategy_type}:{signal_date}"
        cached = redis_mgr.get(cache_key)
        if cached:
            return success_response(data={"analyses": json.loads(cached)})

        # 从信号通知服务获取信号（信号存在其 Redis DB 1 中）
        signals = await _fetch_signals_from_signal_service(request.strategy_type, signal_date)
        if not signals:
            return success_response(data={"analyses": [], "message": "当日无信号"})

        contexts = await _build_signal_contexts(signals, request.strategy_type)
        analyses = await analyzer.analyze_signals(signals, contexts=contexts)
        analysis_dicts = [a.model_dump() for a in analyses]

        redis_mgr.setex(cache_key, 30 * 86400, json.dumps(analysis_dicts, ensure_ascii=False))

        return success_response(data={"analyses": analysis_dicts})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"信号解读失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ai/analysis-history")
async def get_analysis_history(strategy_type: str = "AGGRESSIVE", start_date: str = "", end_date: str = ""):
    """获取历史AI分析结果（供日历回放）"""
    try:
        results = []
        # 遍历日期范围，从 Redis 缓存读取
        from datetime import timedelta
        start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime.now() - timedelta(days=30)
        end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()
        current = start
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            cache_key = f"ai:analysis:{strategy_type}:{date_str}"
            cached = redis_mgr.get(cache_key)
            if cached:
                analyses = json.loads(cached)
                results.append({
                    "date": date_str,
                    "analyses": analyses,
                    "count": len(analyses),
                })
            current += timedelta(days=1)
        return success_response(data={"history": results, "count": len(results)})
    except Exception as e:
        logger.error(f"获取分析历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class RiskCheckRequest(BaseModel):
    """风险检查入参

    未提供的字段用 None 表示：用 0.0 当哨兵会把"真实为 0"（平盘、零盈亏）误判为未提供。
    """
    strategy_type: str = "MODERATE"
    positions: Optional[dict] = None
    total_assets: Optional[float] = None
    daily_pnl: Optional[float] = None
    max_drawdown: Optional[float] = None
    market_change: Optional[float] = None


@app.post("/api/ai/risk-check")
async def risk_check(request: RiskCheckRequest):
    """风险检查 - 使用 RiskMonitor 进行全面风险评估"""
    try:
        from .risk_monitor import RiskMonitor, PortfolioState
        import httpx

        monitor = RiskMonitor()

        # 如果没有传入持仓，从 Redis DB 1 读取该策略的持仓（持仓由 strategy 服务写入）
        positions = request.positions or {}
        if not positions:
            try:
                import redis as _redis
                _pos_client = _redis.Redis(
                    host=settings.redis_host, port=settings.redis_port,
                    password=settings.redis_password or None, db=1,
                    decode_responses=True, socket_timeout=3,
                )
                positions_raw = _pos_client.get(f"positions:{request.strategy_type}")
                if positions_raw:
                    positions = json.loads(positions_raw)
                _pos_client.close()
            except Exception as e:
                logger.warning(f"读取持仓数据失败: {e}")

        # 未显式传入时才自动补齐
        market_change = request.market_change
        if market_change is None:
            # 大盘涨跌幅取真实上证指数；取不到时保持 0（不触发大盘跌幅预警），
            # 不能用板块等权均值代替，否则 1.0%/2.5% 的预警阈值会失真
            index_change = await _fetch_market_index_change()
            market_change = index_change if index_change is not None else 0.0

        daily_pnl = request.daily_pnl
        if daily_pnl is None:
            # 未传入时用持仓的板块加权涨跌幅估算组合当日盈亏
            daily_pnl = 0.0
            if positions:
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        # 往前查找最近有数据的日期
                        from datetime import timedelta as _td
                        sectors = []
                        for delta in range(7):
                            check_date = (datetime.now() - _td(days=delta)).strftime("%Y-%m-%d")
                            resp = await client.get(
                                f"{settings.data_collector_url}/query/all-sectors",
                                params={"start_date": check_date, "end_date": check_date},
                            )
                            if resp.json().get("code") == 200 and resp.json().get("data"):
                                sectors = resp.json()["data"]
                                break
                        if sectors:
                            sector_map = {s.get("sector_code"): s.get("index_change_pct", 0) or 0 for s in sectors}
                            weighted_pnl = 0.0
                            for code, weight in positions.items():
                                weighted_pnl += weight * sector_map.get(code, 0)
                            daily_pnl = round(weighted_pnl, 4)
                except Exception as e:
                    logger.warning(f"获取市场数据失败: {e}")

        state = PortfolioState(
            positions=positions,
            total_assets=request.total_assets or 0.0,
            daily_pnl=daily_pnl,
            max_drawdown=request.max_drawdown or 0.0,
            market_change=market_change,
        )

        alerts = monitor.check_portfolio(state)
        alert_dicts = [
            {
                "alert_type": a.alert_type,
                "level": a.level.value,
                "title": a.title,
                "description": a.description,
                "suggestion": a.suggestion,
                "metrics": a.metrics,
            }
            for a in alerts
        ]

        return success_response(data={
            "alerts": alert_dicts,
            "alert_count": len(alert_dicts),
            "overall_risk": "HIGH" if any(a.level.value == "CRITICAL" for a in alerts) else "MEDIUM" if alerts else "LOW",
        })
    except Exception as e:
        logger.error(f"风险检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class DailyReviewRequest(BaseModel):
    date: str = ""


@app.post("/api/ai/daily-review")
async def daily_review(request: DailyReviewRequest):
    """生成每日复盘报告"""
    try:
        # 复盘走默认客户端（analyzer 可能由信号专用客户端兜底而存在），两者都要就绪
        if not analyzer or not llm_client:
            raise HTTPException(status_code=503, detail="AI 服务未就绪，请检查 LLM 配置")

        review_date = request.date or datetime.now().strftime("%Y-%m-%d")

        cache_key = f"ai:review:{review_date}"
        cached = redis_mgr.get(cache_key)
        if cached:
            return success_response(data=json.loads(cached))

        from .daily_reviewer import DailyReviewer, DailyReviewDataCollector
        collector = DailyReviewDataCollector(
            settings.strategy_url, settings.data_collector_url, settings.signal_url
        )
        market_data = await collector.collect(review_date)

        reviewer = DailyReviewer(llm_client)
        report = await reviewer.generate_review(market_data)

        # 生成失败的报告（model=error）只含错误文本，缓存 30 天会让偶发故障长期固化
        if report.model == "error":
            raise HTTPException(status_code=502, detail=report.market_summary)

        redis_mgr.setex(cache_key, 30 * 86400, json.dumps(report.model_dump(), ensure_ascii=False))

        return success_response(data=report.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"复盘报告生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


AI_CONFIG_KEY = "ai:config"


def _load_ai_config() -> dict:
    """从 Redis 加载 AI 配置，合并环境变量默认值"""
    defaults = {
        "provider": settings.ai_provider,
        "api_key": settings.ai_api_key,
        "base_url": settings.ai_base_url,
        "model": settings.ai_model,
        "temperature": settings.ai_temperature,
        "max_tokens": settings.ai_max_tokens,
        "ollama_base_url": settings.ollama_base_url,
        "ollama_model": settings.ollama_model,
    }
    try:
        raw = redis_mgr.get(AI_CONFIG_KEY)
        if raw:
            saved = json.loads(raw)
            defaults.update(saved)
    except Exception as e:
        logger.warning(f"加载 AI 配置失败: {e}")

    # 修复 Ollama URL：Docker 容器内 localhost 指向容器自身，需替换为宿主机地址
    _ollama_host = os.environ.get("OLLAMA_HOST", "host.docker.internal")
    if "localhost:11434" in defaults.get("ollama_base_url", ""):
        defaults["ollama_base_url"] = f"http://{_ollama_host}:11434"

    return defaults


def _save_ai_config(config: dict):
    """保存 AI 配置到 Redis"""
    redis_mgr.set(AI_CONFIG_KEY, json.dumps(config, ensure_ascii=False))


@app.get("/api/ai/config")
async def get_config():
    """获取 AI 配置"""
    config = _load_ai_config()
    api_key = config.get("api_key", "")
    masked_key = ""
    if api_key:
        if len(api_key) <= 8:
            masked_key = api_key[:2] + "***"
        else:
            masked_key = api_key[:4] + "***" + api_key[-4:]
    return success_response(data={
        "provider": config.get("provider", "openai"),
        "api_key": masked_key,
        "base_url": config.get("base_url", ""),
        "model": config.get("model", ""),
        "temperature": config.get("temperature", 0.7),
        "max_tokens": config.get("max_tokens", 2000),
        "ollama_base_url": config.get("ollama_base_url", ""),
        "ollama_model": config.get("ollama_model", ""),
        "has_api_key": bool(api_key),
        "signal_analysis_provider": config.get("signal_analysis_provider", ""),
        "signal_analysis_model": config.get("signal_analysis_model", ""),
    })


class UpdateConfigRequest(BaseModel):
    provider: str = "openai"
    api_key: str = ""
    base_url: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 2000
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    signal_analysis_provider: str = ""
    signal_analysis_model: str = ""


@app.put("/api/ai/config")
async def update_config(request: UpdateConfigRequest):
    """更新 AI 配置"""
    global llm_client, signal_llm_client, analyzer
    try:
        config = request.model_dump()

        # 修复 Ollama URL
        _ollama_host = os.environ.get("OLLAMA_HOST", "host.docker.internal")
        if "localhost:11434" in config.get("ollama_base_url", ""):
            config["ollama_base_url"] = f"http://{_ollama_host}:11434"

        _save_ai_config(config)

        # 重新初始化 LLM 客户端（信号分析专用模型优先，默认模型失败不阻断）
        signal_llm_client_temp = None
        llm_client_temp = None

        # 1. 信号分析专用客户端
        signal_provider = config.get("signal_analysis_provider", "")
        signal_model = config.get("signal_analysis_model", "")
        if signal_provider and signal_model:
            try:
                if signal_provider == "ollama":
                    signal_llm_client_temp = ModelAdapterFactory.create(
                        provider="ollama",
                        ollama_base_url=config["ollama_base_url"],
                        ollama_model=signal_model,
                    )
                else:
                    provider_mgr = _get_provider_mgr()
                    provider_config = provider_mgr.get(signal_provider)
                    if provider_config and provider_config.api_key:
                        signal_llm_client_temp = ModelAdapterFactory.create(
                            provider="openai",
                            api_key=provider_config.api_key,
                            base_url=provider_config.base_url,
                            model=signal_model,
                        )
            except Exception as e:
                logger.warning(f"信号分析专用客户端更新失败: {e}")

        # 2. 默认客户端
        try:
            llm_args = _resolve_default_llm_args(config)
            if llm_args:
                llm_client_temp = ModelAdapterFactory.create(
                    ollama_base_url=config["ollama_base_url"],
                    ollama_model=config["ollama_model"],
                    **llm_args,
                )
        except Exception as e:
            logger.warning(f"默认 LLM 客户端更新失败（信号分析不受影响）: {e}")

        # 3. 应用更新
        if signal_llm_client_temp:
            signal_llm_client = signal_llm_client_temp
        if llm_client_temp:
            llm_client = llm_client_temp
        if signal_llm_client or llm_client:
            analyzer = SignalAnalyzer(signal_llm_client or llm_client)
            logger.info(f"LLM 客户端已更新: signal_analyzer={'ready' if signal_llm_client else 'fallback'}")
        else:
            logger.error("所有 LLM 客户端更新均失败")

        api_key = config.get("api_key", "")
        masked_key = ""
        if api_key:
            if len(api_key) <= 8:
                masked_key = api_key[:2] + "***"
            else:
                masked_key = api_key[:4] + "***" + api_key[-4:]
        resp = {**config, "api_key": masked_key, "has_api_key": bool(api_key)}
        return success_response(data=resp, message="AI 配置已更新")
    except Exception as e:
        logger.error(f"更新 AI 配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ai/models")
async def list_models(base_url: str = ""):
    """获取 Ollama 可用模型列表"""
    try:
        url = base_url or settings.ollama_base_url
        from .model_adapter import OllamaClient
        client = OllamaClient(base_url=url, model="")
        models = await client.list_models()
        return success_response(data={"models": models})
    except Exception as e:
        logger.error(f"获取模型列表失败: {e}")
        return success_response(data={"models": []})


# ============================================================
# 提供商管理
# ============================================================

provider_mgr = None

def _get_provider_mgr():
    global provider_mgr
    if provider_mgr is None:
        from .provider_manager import ProviderManager, ProviderConfig
        provider_mgr = ProviderManager(redis_mgr.client)
    return provider_mgr


@app.get("/api/ai/providers")
async def list_providers(configured_only: bool = False):
    """获取提供商列表"""
    try:
        mgr = _get_provider_mgr()
        if configured_only:
            providers = mgr.get_configured()
        else:
            providers = mgr.get_all()
        return success_response(data=[p.model_dump() for p in providers])
    except Exception as e:
        logger.error(f"获取提供商列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ai/providers/{provider_id}")
async def get_provider(provider_id: str):
    """获取单个提供商"""
    try:
        mgr = _get_provider_mgr()
        provider = mgr.get(provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="提供商不存在")
        return success_response(data=provider.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取提供商失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SaveProviderRequest(BaseModel):
    id: str
    name: str
    base_url: str
    api_key: str = ""
    models: list[dict] = []


@app.post("/api/ai/providers")
async def save_provider(request: SaveProviderRequest):
    """保存提供商配置"""
    try:
        from .provider_manager import ProviderConfig, ModelInfo
        mgr = _get_provider_mgr()

        models = [ModelInfo(**m) for m in request.models]
        config = ProviderConfig(
            id=request.id,
            name=request.name,
            base_url=request.base_url,
            api_key=request.api_key,
            models=models,
        )
        saved = mgr.save(config)
        return success_response(data=saved.model_dump(), message="提供商已保存")
    except Exception as e:
        logger.error(f"保存提供商失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/ai/providers/{provider_id}")
async def delete_provider(provider_id: str):
    """删除自定义提供商"""
    try:
        mgr = _get_provider_mgr()
        if not mgr.delete(provider_id):
            raise HTTPException(status_code=400, detail="内置提供商不可删除")
        return success_response(message="提供商已删除")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除提供商失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai/providers/{provider_id}/test")
async def test_provider(provider_id: str):
    """测试提供商连接"""
    try:
        mgr = _get_provider_mgr()
        provider = mgr.get(provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="提供商不存在")

        if not provider.api_key and provider_id != "ollama":
            raise HTTPException(status_code=400, detail="请先配置 API Key")

        from .model_adapter import ModelAdapterFactory
        client = ModelAdapterFactory.create(
            provider="ollama" if provider_id == "ollama" else "openai",
            api_key=provider.api_key,
            base_url=provider.base_url,
            model=provider.models[0].value if provider.models else "",
            ollama_base_url=provider.base_url,
            ollama_model=provider.models[0].value if provider.models else "",
        )
        ok = await client.health_check()
        return success_response(data={"connected": ok})
    except HTTPException:
        raise
    except Exception as e:
        return success_response(data={"connected": False, "error": str(e)})


# ============================================================
# 对话管理
# ============================================================

# 客户端缓存（避免每次请求都创建新客户端）
_CLIENT_CACHE_MAX = 20  # 最大缓存客户端数
_client_cache: dict[str, BaseLLMClient] = {}


def _get_llm_client(provider: str = "", model: str = "") -> BaseLLMClient:
    """动态获取 LLM 客户端（支持运行时切换提供商）"""
    global llm_client, analyzer

    # 如果没有指定提供商，使用默认客户端
    if not provider:
        if llm_client:
            return llm_client
        _init_llm()
        return llm_client

    # Ollama 每次都创建新客户端（模型可能切换）
    if provider == "ollama":
        return _create_ollama_client(model)

    # 检查缓存
    cache_key = f"{provider}:{model}"
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    # 根据提供商创建客户端
    try:
        provider_mgr = _get_provider_mgr()
        provider_config = provider_mgr.get(provider)

        if not provider_config:
            logger.warning(f"提供商 {provider} 不存在，尝试使用默认配置")
            if llm_client:
                return llm_client
            return None

        if not provider_config.api_key:
            logger.warning(f"提供商 {provider} 未配置 API Key")
            return None

        client = ModelAdapterFactory.create(
            provider="openai",
            api_key=provider_config.api_key,
            base_url=provider_config.base_url,
            model=model or (provider_config.models[0].value if provider_config.models else ""),
        )

        _client_cache[cache_key] = client
        # 缓存淘汰：超过上限时移除最早的条目
        if len(_client_cache) > _CLIENT_CACHE_MAX:
            oldest_key = next(iter(_client_cache))
            old_client = _client_cache.pop(oldest_key)
            if hasattr(old_client, 'close'):
                asyncio.create_task(old_client.close())
        return client
    except Exception as e:
        logger.error(f"创建 LLM 客户端失败: {e}")
        return llm_client


def _create_ollama_client(model: str = "") -> BaseLLMClient:
    """创建 Ollama 客户端"""
    try:
        provider_mgr = _get_provider_mgr()
        provider_config = provider_mgr.get("ollama")
        ollama_url = provider_config.base_url if provider_config else settings.ollama_base_url
        ollama_model = model or (provider_config.models[0].value if provider_config and provider_config.models else settings.ollama_model)

        return ModelAdapterFactory.create(
            provider="ollama",
            ollama_base_url=ollama_url,
            ollama_model=ollama_model,
        )
    except Exception as e:
        logger.error(f"创建 Ollama 客户端失败: {e}")
        return None

chat_mgr = None

def _get_chat_mgr():
    global chat_mgr
    if chat_mgr is None:
        from .chat_manager import ChatManager
        chat_mgr = ChatManager(redis_mgr.client)
    return chat_mgr


# MCP 工具执行器
tool_executor = None
agent = None

def _get_agent(provider: str = "", model: str = ""):
    """获取 Agent 实例"""
    global agent, tool_executor
    client = _get_llm_client(provider, model)
    if not client:
        return None
    if tool_executor is None:
        from .tools import MCPToolExecutor
        tool_executor = MCPToolExecutor(
            strategy_url=settings.strategy_url,
            data_collector_url=settings.data_collector_url,
            signal_url=settings.signal_url,
        )
    from .agent import ReActAgent
    return ReActAgent(client, tool_executor)


class ChatRequest(BaseModel):
    message: str
    conversation_id: str = ""
    provider: str = ""
    model: str = ""
    no_save: bool = False  # 测试模式，不保存到数据库


@app.post("/api/ai/chat")
async def chat(request: ChatRequest):
    """对话式投研（非流式，走 Agent 支持工具调用）"""
    try:
        mgr = _get_chat_mgr()
        conv_id = request.conversation_id
        save = not request.no_save

        # 创建或获取对话
        if save:
            if not conv_id:
                conv = mgr.create_conversation(
                    provider=request.provider or settings.ai_provider,
                    model=request.model or settings.ai_model,
                )
                conv_id = conv.id
            else:
                conv = mgr.get_conversation(conv_id)
                if not conv:
                    conv = mgr.create_conversation(
                        provider=request.provider or settings.ai_provider,
                        model=request.model or settings.ai_model,
                    )
                    conv_id = conv.id

            from .chat_manager import ChatMessage
            mgr.add_message(conv_id, ChatMessage(role="user", content=request.message))

            context_messages = []
            if conv and conv.messages:
                for msg in conv.messages[-10:]:
                    context_messages.append({"role": msg.role, "content": msg.content})
        else:
            context_messages = []

        # 通过 Agent 执行（支持工具调用）
        agent = _get_agent(request.provider, request.model)
        if not agent:
            raise HTTPException(
                status_code=503,
                detail=f"AI 服务未就绪：提供商 {request.provider or '默认'} 缺少可用的 API Key",
            )
        full_content = ""
        full_thinking = ""
        total_tokens = 0
        async for chunk in agent.run(request.message, context_messages):
            if chunk["type"] == "content":
                full_content += chunk["data"]
            elif chunk["type"] == "thinking":
                full_thinking += chunk["data"]
            elif chunk["type"] == "usage":
                total_tokens = chunk["data"].get("tokens_used", 0)

        if save and full_content:
            from .chat_manager import ChatMessage
            mgr.add_message(conv_id, ChatMessage(
                role="assistant",
                content=full_content,
                thinking=full_thinking,
                model=request.model or settings.ai_model,
                tokens_used=total_tokens,
            ))

        return success_response(data={
            "conversation_id": conv_id,
            "reply": full_content,
            "thinking": full_thinking,
            "model": request.model or settings.ai_model,
            "tokens_used": total_tokens,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话（SSE）- 支持 Agent 工具调用"""
    from fastapi.responses import StreamingResponse

    async def generate():
        try:
            # 获取 Agent
            agent = _get_agent(request.provider, request.model)
            if not agent:
                yield f"data: {json.dumps({'type': 'error', 'data': 'AI 服务未就绪，请先配置模型提供商'})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            mgr = _get_chat_mgr()
            conv_id = request.conversation_id
            save = not request.no_save

            if save:
                if not conv_id:
                    conv = mgr.create_conversation(
                        provider=request.provider or settings.ai_provider,
                        model=request.model or settings.ai_model,
                    )
                    conv_id = conv.id
                else:
                    conv = mgr.get_conversation(conv_id)
                    if not conv:
                        conv = mgr.create_conversation(
                            provider=request.provider or settings.ai_provider,
                            model=request.model or settings.ai_model,
                        )
                        conv_id = conv.id

                from .chat_manager import ChatMessage
                mgr.add_message(conv_id, ChatMessage(role="user", content=request.message))

                context_messages = []
                if conv and conv.messages:
                    for msg in conv.messages[-10:]:
                        context_messages.append({"role": msg.role, "content": msg.content})
            else:
                context_messages = []

            # 发送 conversation_id
            yield f"data: {json.dumps({'type': 'conversation_id', 'data': conv_id})}\n\n"

            # 执行 Agent
            full_content = ""
            full_thinking = ""
            total_tokens = 0
            async for chunk in agent.run(request.message, context_messages):
                if chunk["type"] == "thinking":
                    full_thinking += chunk["data"]
                    yield f"data: {json.dumps({'type': 'thinking', 'data': chunk['data']})}\n\n"
                elif chunk["type"] == "content":
                    full_content += chunk["data"]
                    yield f"data: {json.dumps({'type': 'content', 'data': chunk['data']})}\n\n"
                elif chunk["type"] == "tool_call":
                    yield f"data: {json.dumps({'type': 'tool_call', 'data': chunk['data']})}\n\n"
                elif chunk["type"] == "tool_result":
                    yield f"data: {json.dumps({'type': 'tool_result', 'data': chunk['data']})}\n\n"
                elif chunk["type"] == "usage":
                    total_tokens = chunk["data"].get("tokens_used", 0)
                elif chunk["type"] == "error":
                    yield f"data: {json.dumps({'type': 'error', 'data': chunk['data']})}\n\n"

            # 保存 AI 回复
            if save and full_content:
                from .chat_manager import ChatMessage
                mgr.add_message(conv_id, ChatMessage(
                    role="assistant",
                    content=full_content,
                    thinking=full_thinking,
                    model=request.model or settings.ai_model,
                    tokens_used=total_tokens,
                ))

            yield f"data: {json.dumps({'type': 'done', 'tokens_used': total_tokens})}\n\n"

        except Exception as e:
            logger.error(f"Agent 对话失败: {e}")
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/ai/conversations")
async def list_conversations():
    """获取对话列表"""
    try:
        mgr = _get_chat_mgr()
        conversations = mgr.list_conversations()
        return success_response(data=[c.model_dump() for c in conversations])
    except Exception as e:
        logger.error(f"获取对话列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ai/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    """获取对话详情"""
    try:
        mgr = _get_chat_mgr()
        conv = mgr.get_conversation(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="对话不存在")
        return success_response(data=conv.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/ai/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    """删除对话"""
    try:
        mgr = _get_chat_mgr()
        mgr.delete_conversation(conv_id)
        return success_response(message="对话已删除")
    except Exception as e:
        logger.error(f"删除对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ai/conversations/{conv_id}/export")
async def export_conversation(conv_id: str, fmt: str = "markdown"):
    """导出对话"""
    try:
        mgr = _get_chat_mgr()
        content = mgr.export_conversation(conv_id, fmt)
        if not content:
            raise HTTPException(status_code=404, detail="对话不存在")

        conv = mgr.get_conversation(conv_id)
        filename = f"{conv.title}_{conv_id[:8]}.{fmt if fmt != 'markdown' else 'md'}"

        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
