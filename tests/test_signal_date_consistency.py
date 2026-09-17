"""轮动信号日期一致性与持仓安全回归测试

覆盖以下修复点：
1. 信号日期必须与板块数据日期严格一致（禁止用 T-1 数据生成 T 日信号）
2. 板块快照缓存按日期分键，不跨交易日复用
3. 未产生买卖信号时不得清空持仓
4. 手动触发（非交易日/数据未入库）可回退到最近有数据的交易日，并同步修正信号日期
5. 市场宽度绝对下限：全市场普跌时不得因头部板块相对高分而建仓

测试不依赖 Redis / InfluxDB / RabbitMQ 等基础设施。
"""
import os
import sys
import json

import pytest
from fastapi.testclient import TestClient

# 保证 `from shared import ...` 可用（与项目内其它测试一致）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "services"))

from services.strategy.app import main as strategy_main  # noqa: E402
from services.strategy.app.scoring import scoring_model  # noqa: E402
from services.strategy.app.models import StrategyParams, StrategyType  # noqa: E402


TRADE_DAY = "2026-04-24"          # 周五，交易日
WEEKEND_DAY = "2026-04-25"        # 周六，非交易日
EMPTY_DAY = "2026-04-20"          # 交易日，但无任何板块数据


class FakeRedis:
    """内存版 Redis，记录写入以便断言"""

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

    def exists(self, key):
        return 1 if key in self.store else 0

    def ping(self):
        return True


def _make_sector(code: str, name: str, change_pct: float, inflow_yi: float) -> dict:
    """构造板块快照记录（净流入单位为亿元，内部按元存储）"""
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


def _market_rows(up_count: int, down_count: int) -> list:
    """构造指定宽度（上涨/下跌板块数）的全市场快照

    前两个板块始终为"逆势流入的大金融"，用于复现相对动量陷阱场景。
    """
    rows = [
        _make_sector("THS881155", "银行", 1.47, 44.38),
        _make_sector("THS881156", "证券", 0.84, 26.15),
    ]
    for i in range(up_count):
        rows.append(_make_sector(f"THSU{i:03d}", f"上涨板块{i}", 1.2, 0.5))
    for i in range(down_count):
        rows.append(_make_sector(f"THSD{i:03d}", f"下跌板块{i}", -1.8, -3.0))
    return rows


@pytest.fixture
def client_factory(monkeypatch):
    """返回可定制数据源的测试客户端工厂"""
    created = {}

    def _build(daily_data: dict, initial_redis: dict = None):
        fake_redis = FakeRedis(initial_redis)
        monkeypatch.setattr(strategy_main, "redis_mgr", fake_redis)
        monkeypatch.setattr(
            strategy_main.influx_query,
            "query_daily_sectors",
            lambda start, end, sector_code=None: daily_data,
        )
        monkeypatch.setattr(
            strategy_main.influx_query, "query_all_sector_kline", lambda s, e: {}
        )
        monkeypatch.setattr(strategy_main, "_load_sector_history_cache", lambda dates: {})
        published = []
        monkeypatch.setattr(
            strategy_main, "publish_message", lambda routing_key, msg: published.append((routing_key, msg))
        )
        created["redis"] = fake_redis
        created["published"] = published
        return TestClient(strategy_main.app)

    created["build"] = _build
    return created


def test_signal_date_equals_data_date(client_factory):
    """目标日期有数据时，信号日期必须等于该日期"""
    client = client_factory["build"]({TRADE_DAY: _market_rows(up_count=50, down_count=38)})

    resp = client.post(f"/calculate?strategy_type=AGGRESSIVE&signal_date={TRADE_DAY}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["data_ready"] is True
    assert payload["signal_date"] == TRADE_DAY
    assert payload["stale"] is False


def test_reject_when_target_date_has_no_data(client_factory):
    """数据未就绪且不允许回退时：不生成信号、不落缓存、不推送、不动持仓"""
    redis = FakeRedis({"positions:AGGRESSIVE": json.dumps({"THS881155": 0.5})})
    client = client_factory["build"]({TRADE_DAY: _market_rows(up_count=50, down_count=38)})
    client_factory["redis"].store.update(redis.store)

    resp = client.post(f"/calculate?strategy_type=AGGRESSIVE&signal_date={EMPTY_DAY}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["data_ready"] is False
    assert payload["data"] == []
    # 不得写入信号缓存
    assert f"signals:AGGRESSIVE:{EMPTY_DAY}" not in client_factory["redis"].store
    # 不得触发信号推送
    assert client_factory["published"] == []
    # 不得改动持仓
    assert client_factory["redis"].store["positions:AGGRESSIVE"] == json.dumps({"THS881155": 0.5})


def test_manual_trigger_on_weekend_falls_back(client_factory):
    """周末手动触发：回退到最近有数据的交易日，信号日期同步修正"""
    client = client_factory["build"]({TRADE_DAY: _market_rows(up_count=50, down_count=38)})

    resp = client.post(
        f"/calculate?strategy_type=AGGRESSIVE&signal_date={WEEKEND_DAY}&allow_stale=true"
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["stale"] is True
    assert payload["signal_date"] == TRADE_DAY
    assert payload["requested_date"] == WEEKEND_DAY
    assert payload["data_ready"] is True


def test_fallback_does_not_recompute_existing_signals(client_factory):
    """回退到已有信号的日期时，默认不重算，避免重复触发覆盖持仓"""
    existing = [{"sector_code": "THS881155", "sector_name": "银行", "direction": "BUY"}]
    client = client_factory["build"](
        {TRADE_DAY: _market_rows(up_count=50, down_count=38)},
        initial_redis={"signals:AGGRESSIVE:" + TRADE_DAY: json.dumps(existing)},
    )

    resp = client.post(
        f"/calculate?strategy_type=AGGRESSIVE&signal_date={WEEKEND_DAY}&allow_stale=true"
    )
    payload = resp.json()
    assert payload["data"] == existing          # 直接返回已有信号
    assert payload["signal_date"] == TRADE_DAY
    assert client_factory["published"] == []    # 未重复推送


def test_snapshot_cache_is_keyed_by_date(client_factory):
    """板块快照按日期分键缓存，不再使用全局 latest 键"""
    client = client_factory["build"]({TRADE_DAY: _market_rows(up_count=50, down_count=38)})

    client.post(f"/calculate?strategy_type=AGGRESSIVE&signal_date={TRADE_DAY}")

    store = client_factory["redis"].store
    assert f"sector_capital_flow:{TRADE_DAY}" in store
    assert "sector_capital_flow:latest" not in store   # 旧全局键已废弃


def test_empty_signals_keep_existing_positions(client_factory):
    """未产生买卖信号时，现有持仓必须保持不变（不得被清空）"""
    original_positions = json.dumps({"THS881155": 0.5, "THS881156": 0.3})
    # 全市场普跌：10 涨 78 跌，宽度 11% —— 复现 9/10 行情
    client = client_factory["build"](
        {TRADE_DAY: _market_rows(up_count=8, down_count=78)},
        initial_redis={"positions:MODERATE": original_positions},
    )

    resp = client.post(f"/calculate?strategy_type=MODERATE&signal_date={TRADE_DAY}")
    assert resp.status_code == 200
    payload = resp.json()

    buy_signals = [s for s in payload["data"] if s.get("direction") == "BUY"]
    assert buy_signals == [], "普跌市场不应产生买入信号"
    # 关键断言：持仓未被空信号清空
    assert client_factory["redis"].store["positions:MODERATE"] == original_positions


def test_breadth_filter_is_the_deciding_factor(client_factory, monkeypatch):
    """区分度验证：关闭宽度过滤后，同一普跌场景应产生买入信号

    证明"普跌不建仓"确实由宽度过滤导致，而非评分不足等其它原因。
    """
    config = strategy_main.DEFAULT_CONFIGS[StrategyType.MODERATE]
    monkeypatch.setattr(config.params, "market_breadth_floor", 0.0)

    client = client_factory["build"]({TRADE_DAY: _market_rows(up_count=8, down_count=78)})

    resp = client.post(f"/calculate?strategy_type=MODERATE&signal_date={TRADE_DAY}")
    assert resp.status_code == 200
    payload = resp.json()
    buy_signals = [s for s in payload["data"] if s.get("direction") == "BUY"]
    assert buy_signals, "关闭宽度过滤后应产生买入信号（否则说明测试数据无法区分过滤效果）"


def test_market_breadth_floor_forces_bear():
    """市场宽度绝对下限：普跌时即使头部板块评分高也判定 BEAR"""
    params = StrategyParams()

    # 11% 上涨（复现 9/10：90 个板块仅 10 个上涨）
    bear_market = [{"sector_code": f"C{i}", "composite_score": 8.0, "index_change_pct": 2.0}
                   for i in range(10)]
    bear_market += [{"sector_code": f"D{i}", "composite_score": 1.0, "index_change_pct": -2.0}
                    for i in range(80)]

    assert scoring_model._evaluate_market_regime(
        bear_market, StrategyType.MODERATE, params
    ) == "BEAR"

    # 正常偏强市场：60% 上涨且头部达标 → 不应被误杀
    bull_market = [{"sector_code": f"U{i}", "composite_score": 8.0, "index_change_pct": 2.0}
                   for i in range(60)]
    bull_market += [{"sector_code": f"V{i}", "composite_score": 1.0, "index_change_pct": -1.0}
                    for i in range(40)]

    assert scoring_model._evaluate_market_regime(
        bull_market, StrategyType.MODERATE, params
    ) == "BULL"


def test_market_breadth_floor_can_be_disabled():
    """阈值设为 0 时回退到旧行为（仅按 top10 达标判断）"""
    params = StrategyParams(market_breadth_floor=0.0)

    market = [{"sector_code": f"C{i}", "composite_score": 8.0, "index_change_pct": 2.0}
              for i in range(10)]
    market += [{"sector_code": f"D{i}", "composite_score": 1.0, "index_change_pct": -2.0}
               for i in range(80)]

    assert scoring_model._evaluate_market_regime(
        market, StrategyType.MODERATE, params
    ) == "NEUTRAL"
