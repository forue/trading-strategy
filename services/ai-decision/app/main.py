"""AI 决策服务 - FastAPI 主应用"""
import sys
import os
import json
import asyncio
import threading
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
            llm_client = ModelAdapterFactory.create(
                provider=config.get("provider", settings.ai_provider),
                api_key=config.get("api_key", settings.ai_api_key),
                base_url=config.get("base_url", settings.ai_base_url),
                model=config.get("model", settings.ai_model),
                ollama_base_url=config.get("ollama_base_url", settings.ollama_base_url),
                ollama_model=config.get("ollama_model", settings.ollama_model),
            )
            provider = config.get("provider", settings.ai_provider)
            model = config.get("model", settings.ai_model) if config.get("provider", settings.ai_provider) == "openai" else config.get("ollama_model", settings.ollama_model)
            logger.info(f"默认 LLM 客户端初始化完成: provider={provider}, model={model}")
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
    """从信号通知服务获取信号数据（信号存在 signal 服务的 Redis 中）"""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.signal_url}/signals/today",
                params={"strategy_type": strategy_type},
            )
            if resp.json().get("code") == 200:
                signals = resp.json().get("data", [])
                # 按日期过滤
                return [s for s in signals if s.get("signal_date", "") == signal_date] if signals else []
    except Exception as e:
        logger.warning(f"从信号服务获取信号失败: {e}")
    return []


async def _handle_signals(message: dict):
    """处理策略信号"""
    if not analyzer:
        logger.warning("LLM 未初始化，跳过信号解读")
        return

    signals = message.get("signals", [])
    strategy_type = message.get("strategy_type", "")
    signal_date = message.get("signal_date", "")

    if not signals:
        return

    logger.info(f"开始解读 {len(signals)} 个信号: strategy={strategy_type}")

    # 获取真实市场数据构建上下文
    contexts = await _build_signal_contexts(signals)

    analyses = await analyzer.analyze_signals(signals, contexts=contexts)

    analysis_dicts = [a.model_dump() for a in analyses]

    cache_key = f"ai:analysis:{strategy_type}:{signal_date}"
    redis_mgr.setex(cache_key, 7 * 86400, json.dumps(analysis_dicts, ensure_ascii=False))

    rmq.publish("ai.signal.analyzed", {
        "event": "signal_analyzed",
        "strategy_type": strategy_type,
        "signal_date": signal_date,
        "analyses": analysis_dicts,
        "timestamp": datetime.now().isoformat(),
    })

    logger.info(f"信号解读完成: {len(analyses)} 个, strategy={strategy_type}")


async def _build_signal_contexts(signals: list[dict]) -> dict:
    """为信号解读构建真实的市场上下文（含近15天历史数据）"""
    from .signal_analyzer import MarketContext
    import httpx
    from datetime import timedelta

    contexts = {}
    data_collector_url = settings.data_collector_url

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            today = datetime.now().strftime("%Y-%m-%d")
            start_15d = (datetime.now() - timedelta(days=25)).strftime("%Y-%m-%d")  # 25天确保覆盖15个交易日

            # 获取当日全部板块数据（市场宽度）
            resp = await client.get(f"{data_collector_url}/query/all-sectors",
                                    params={"start_date": today, "end_date": today})
            all_sectors = {}
            market_avg = 0.0
            if resp.json().get("code") == 200 and resp.json().get("data"):
                for s in resp.json()["data"]:
                    all_sectors[s.get("sector_code", "")] = s
                changes = [s.get("index_change_pct", 0) or 0 for s in resp.json()["data"]]
                market_avg = sum(changes) / max(len(changes), 1)

            # 为每个信号的板块获取近15天历史数据
            for sig in signals:
                code = sig.get("sector_code", "")
                if not code:
                    continue
                try:
                    hist_resp = await client.get(
                        f"{data_collector_url}/query/sector-data",
                        params={"sector_code": code, "start_date": start_15d, "end_date": today},
                    )
                    hist_data = hist_resp.json()
                    records = hist_data.get("data", []) if hist_data.get("code") == 200 else []

                    change_5d = 0.0
                    change_10d = 0.0
                    change_today = 0.0
                    main_flow = 0.0
                    turnover = 0.0
                    avg_flow_5d = 0.0

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

                    # 市场宽度
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

                    contexts[code] = MarketContext(
                        sector_code=code,
                        sector_name=sig.get("sector_name", ""),
                        change_5d=change_5d,
                        change_10d=change_10d,
                        change_today=change_today,
                        main_flow=main_flow,
                        north_flow=0.0,
                        turnover=turnover,
                        market_change=round(market_avg, 2),
                        market_sentiment=sentiment,
                    )
                except Exception as e:
                    logger.warning(f"获取板块{code}数据失败: {e}")

    except Exception as e:
        logger.error(f"获取市场数据失败: {e}")

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

        contexts = await _build_signal_contexts(signals)
        analyses = await analyzer.analyze_signals(signals, contexts=contexts)
        analysis_dicts = [a.model_dump() for a in analyses]

        redis_mgr.setex(cache_key, 7 * 86400, json.dumps(analysis_dicts, ensure_ascii=False))

        return success_response(data={"analyses": analysis_dicts})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"信号解读失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class RiskCheckRequest(BaseModel):
    strategy_type: str = "MODERATE"
    positions: dict = {}
    total_assets: float = 0.0
    daily_pnl: float = 0.0
    max_drawdown: float = 0.0
    market_change: float = 0.0


@app.post("/api/ai/risk-check")
async def risk_check(request: RiskCheckRequest):
    """风险检查 - 使用 RiskMonitor 进行全面风险评估"""
    try:
        from .risk_monitor import RiskMonitor, PortfolioState
        import httpx

        monitor = RiskMonitor()

        # 如果没有传入持仓，从 Redis 读取
        positions = request.positions
        if not positions:
            for st in ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]:
                positions_raw = redis_mgr.get(f"positions:{st}")
                if positions_raw:
                    positions = json.loads(positions_raw)
                    break

        # 获取真实市场数据（如果未传入）
        market_change = request.market_change
        daily_pnl = request.daily_pnl

        if market_change == 0.0 or daily_pnl == 0.0:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    today = datetime.now().strftime("%Y-%m-%d")
                    resp = await client.get(
                        f"{settings.data_collector_url}/query/all-sectors",
                        params={"start_date": today, "end_date": today},
                    )
                    if resp.json().get("code") == 200 and resp.json().get("data"):
                        sectors = resp.json()["data"]
                        changes = [s.get("index_change_pct", 0) or 0 for s in sectors]
                        if market_change == 0.0:
                            market_change = round(sum(changes) / max(len(changes), 1), 2)
                        # 根据持仓权重估算日盈亏
                        if daily_pnl == 0.0 and positions:
                            sector_map = {s.get("sector_code"): s.get("index_change_pct", 0) or 0 for s in sectors}
                            weighted_pnl = 0.0
                            for code, weight in positions.items():
                                weighted_pnl += weight * sector_map.get(code, 0)
                            daily_pnl = round(weighted_pnl, 4)
            except Exception as e:
                logger.warning(f"获取市场数据失败: {e}")

        state = PortfolioState(
            positions=positions,
            total_assets=request.total_assets,
            daily_pnl=daily_pnl,
            max_drawdown=request.max_drawdown,
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
            "overall_risk": "HIGH" if any(a.level == "CRITICAL" for a in alerts) else "MEDIUM" if alerts else "LOW",
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
        if not analyzer:
            raise HTTPException(status_code=503, detail="AI 服务未就绪")

        review_date = request.date or datetime.now().strftime("%Y-%m-%d")

        cache_key = f"ai:review:{review_date}"
        cached = redis_mgr.get(cache_key)
        if cached:
            return success_response(data=json.loads(cached))

        from .daily_reviewer import DailyReviewer, DailyReviewDataCollector
        collector = DailyReviewDataCollector(redis_mgr.client)
        market_data = await collector.collect(review_date)

        reviewer = DailyReviewer(llm_client)
        report = await reviewer.generate_review(market_data)

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
            llm_client_temp = ModelAdapterFactory.create(
                provider=config["provider"],
                api_key=config["api_key"],
                base_url=config["base_url"],
                model=config["model"],
                ollama_base_url=config["ollama_base_url"],
                ollama_model=config["ollama_model"],
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
