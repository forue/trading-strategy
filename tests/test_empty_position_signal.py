"""空仓信号回归测试

覆盖：市场转弱时必须输出明确的空仓/清仓信号，而不是"什么都不返回"。

关键语义：
1. 已连续确认 BEAR 且持有仓位 → 生成清仓 SELL 信号（空仓动作）
2. 仅单日 BEAR（未达连续确认天数）→ 只不买入，不主动卖出（避免假信号频繁清仓）
3. 无论是否持仓，"空仓"这一状态都必须被接口明确表达（position_status=EMPTY + 原因）
4. 回测路径不传 regime_history，行为保持"只不买入"（由回测自身 BEAR_EXIT 处理）
"""
import os
import sys
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "services"))

from services.strategy.app import main as strategy_main  # noqa: E402
from services.strategy.app.models import StrategyParams, StrategyType  # noqa: E402
from services.strategy.app.scoring import scoring_model  # noqa: E402


TRADE_DAY = "2026-04-24"
PREV_DAY = "2026-04-23"


class FakeRedis:
    def __init__(self, initial=None):
        self.store = dict(initial or {})

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value
        return True

    def set(self, key, value, ex=None):
        self.store[key] = value
        return True

    def delete(self, key):
        self.store.pop(key, None)
        return True

    def ping(self):
        return True


def _make_sector(code: str, name: str, change_pct: float, inflow_yi: float) -> dict:
    return {
        "sector_code": code,
        "sector_name": name,
        "index_change_pct": change_pct,
        "main_net_inflow": inflow_yi * 1e8,
        "north_net_inflow": 0.0,
        "index_close": 1000.0,
        "turnover": 5e9,
        "pe_ttm": 15.0,
        "pb": 1.5,
        "pe_percentile": 50.0,
        "pb_percentile": 50.0,
    }


def _bear_market_rows() -> list:
    """全市场普跌：8 涨 78 跌（宽度约 9%），复现 9/10 行情"""
    rows = [
        _make_sector("THS881155", "银行", 1.47, 44.38),
        _make_sector("THS881156", "证券", 0.84, 26.15),
    ]
    for i in range(8):
        rows.append(_make_sector(f"THSU{i:03d}", f"上涨板块{i}", 1.2, 0.5))
    for i in range(78):
        rows.append(_make_sector(f"THSD{i:03d}", f"下跌板块{i}", -1.8, -3.0))
    return rows


@pytest.fixture
def env(monkeypatch):
    state = {}

    def _build(initial_redis: dict = None):
        state["redis"] = FakeRedis(initial_redis)
        monkeypatch.setattr(strategy_main, "redis_mgr", state["redis"])
        monkeypatch.setattr(
            strategy_main.influx_query,
            "query_daily_sectors",
            lambda start, end, sector_code=None: {TRADE_DAY: _bear_market_rows()},
        )
        monkeypatch.setattr(strategy_main.influx_query, "query_all_sector_kline", lambda s, e: {})
        monkeypatch.setattr(strategy_main, "_load_sector_history_cache", lambda dates: {})
        state["published"] = []
        monkeypatch.setattr(
            strategy_main,
            "publish_message",
            lambda routing_key, msg: state["published"].append((routing_key, msg)),
        )
        return TestClient(strategy_main.app)

    state["build"] = _build
    return state


def test_confirmed_bear_emits_clear_signals(env):
    """连续确认 BEAR 且持有仓位 → 生成清仓卖出信号"""
    positions = {"THS881155": 0.4, "THS881156": 0.3}
    client = env["build"]({
        "positions:MODERATE": json.dumps(positions),
        f"market_regime:MODERATE:{PREV_DAY}": "BEAR",  # 上一交易日已为 BEAR
    })

    resp = client.post(f"/calculate?strategy_type=MODERATE&signal_date={TRADE_DAY}")
    assert resp.status_code == 200
    payload = resp.json()

    sell_signals = [s for s in payload["data"] if s["direction"] == "SELL"]
    assert len(sell_signals) == 2, "连续确认 BEAR 时应对每个持仓生成清仓信号"
    assert {s["sector_code"] for s in sell_signals} == set(positions)
    assert all("空仓清仓" in s["reason"] for s in sell_signals)
    assert payload["position_status"] == "EMPTY"
    assert payload["market_regime"] == "BEAR"
    # 清仓后持仓应被清空
    assert json.loads(env["redis"].store["positions:MODERATE"]) == {}


def test_single_day_bear_does_not_sell(env):
    """仅单日 BEAR（未达连续确认天数）→ 只不买入，不主动清仓"""
    positions = {"THS881155": 0.4}
    client = env["build"]({"positions:MODERATE": json.dumps(positions)})

    resp = client.post(f"/calculate?strategy_type=MODERATE&signal_date={TRADE_DAY}")
    payload = resp.json()

    buy_signals = [s for s in payload["data"] if s["direction"] == "BUY"]
    sell_signals = [s for s in payload["data"] if s["direction"] == "SELL"]
    assert buy_signals == [], "普跌市场不应买入"
    assert sell_signals == [], "未确认 BEAR 不应触发清仓"
    # 持仓维持不变
    assert json.loads(env["redis"].store["positions:MODERATE"]) == positions
    assert payload["position_status"] == "HOLD"


def test_empty_position_is_reported_with_reason(env):
    """无持仓且市场判定熊市 → 明确表达空仓状态与原因"""
    client = env["build"]()

    resp = client.post(f"/calculate?strategy_type=MODERATE&signal_date={TRADE_DAY}")
    payload = resp.json()

    assert payload["position_status"] == "EMPTY"
    assert payload["market_regime"] == "BEAR"
    assert "空仓" in payload["empty_reason"]
    assert "上涨板块占比" in payload["empty_reason"]
    assert payload["data"] == []


def test_signals_today_reports_empty_status(env):
    """/signals/today 需区分"已计算且空仓"、"持有"、"未计算" """
    today = datetime.now().strftime("%Y-%m-%d")

    # 1) 已计算且空仓
    client = env["build"]({
        f"signals:MODERATE:{today}": "[]",
        f"signals:MODERATE:{today}:status": json.dumps(
            {"position_status": "EMPTY", "market_regime": "BEAR",
             "empty_reason": "市场判定熊市，空仓观望", "signal_date": today},
            ensure_ascii=False,
        ),
    })
    payload = client.get("/signals/today?strategy_type=MODERATE").json()
    assert payload["position_status"] == "EMPTY"
    assert payload["empty_reason"] == "市场判定熊市，空仓观望"
    assert payload["market_regime"] == "BEAR"

    # 2) 持有信号
    env["redis"].store[f"signals:MODERATE:{today}"] = json.dumps(
        [{"sector_code": "THS881155", "direction": "BUY"}]
    )
    payload = client.get("/signals/today?strategy_type=MODERATE").json()
    assert payload["position_status"] == "HOLD"

    # 3) 无任何缓存 → 未计算
    env["redis"].store.pop(f"signals:MODERATE:{today}", None)
    env["redis"].store.pop(f"signals:MODERATE:{today}:status", None)
    payload = client.get("/signals/today?strategy_type=MODERATE").json()
    assert payload["position_status"] == "NO_DATA"


def test_backtest_path_keeps_no_sell_behavior():
    """回测路径（不传 regime_history）保持原行为：只不买入，不生成清仓信号"""
    sectors = [{"composite_score": 1.0, "index_change_pct": -1.0} for _ in range(15)]
    for i in range(3):
        sectors[i]["composite_score"] = 2.5

    params = StrategyParams(min_score_threshold=2.0)
    # 不传 regime_history → bear_exit=False
    signals = scoring_model._rotation_core(
        sectors, params, StrategyType.MODERATE, TRADE_DAY,
        current_positions={"THS881155": 0.4},
    )
    assert signals == [], "回测路径不应由轮动逻辑生成清仓信号（BEAR_EXIT 由回测自身处理）"

    # 显式开启 bear_exit 时才清仓
    signals = scoring_model._rotation_core(
        sectors, params, StrategyType.MODERATE, TRADE_DAY,
        current_positions={"THS881155": 0.4}, bear_exit=True,
    )
    assert len(signals) == 1 and signals[0].direction.value == "SELL"
