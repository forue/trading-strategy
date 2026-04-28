import json
from fastapi.testclient import TestClient
import pytest

# Import the FastAPI app from the strategy service
from services.strategy.app import main as strategy_main


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def info(self, *args, **kwargs):
        return {"used_memory_human": "0B", "memory": {}}

    def ping(self):
        return True

    def keys(self, pattern):
        return []

    def scan_iter(self, match=None):
        return iter([])

    def flushdb(self):
        self.store.clear()


def mock_query_daily_sectors(start_date: str, end_date: str, sector_code: str = None):
    # 提供一个最小化且符合接口的数据集合，用于测试/calculation 路径
    sector = {
        "sector_code": "THS801010",
        "sector_name": "农林牧渔",
        "main_net_inflow": 1000000.0,
        "north_net_inflow": 200000.0,
        "index_close": 100.0,
        "index_change_pct": 1.0,
        "turnover": 1000000.0,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "pe_ttm": 15.0,
        "pb": 1.5,
        "etf_code": "159825",
        "etf_name": "农业ETF",
        "pe_percentile": 60.0,
        "pb_percentile": 40.0,
    }
    return {"2026-04-25": [sector]}


def test_health_endpoint():
    client = TestClient(strategy_main.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("service") == "strategy"
    assert data.get("status") == "healthy"


def test_configs_endpoint_structure(monkeypatch):
    # 使用一个简单的伪 Redis，避免真实 Redis 依赖
    monkeypatch.setattr(strategy_main, "redis_client", FakeRedis())
    client = TestClient(strategy_main.app)
    resp = client.get("/configs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert data.get("code") == 200
    assert isinstance(data.get("data"), list)


def test_calculate_signals_with_mocked_data(monkeypatch):
    # 注入伪 Redis 与数据源，确保 /calculate 能返回信号数据
    monkeypatch.setattr(strategy_main, "redis_client", FakeRedis())
    monkeypatch.setattr(strategy_main.influx_query, "query_daily_sectors", mock_query_daily_sectors)

    client = TestClient(strategy_main.app)
    resp = client.post("/calculate?strategy_type=AGGRESSIVE&signal_date=2026-04-24")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("code") == 200
    signals = payload.get("data")
    assert isinstance(signals, list)
    if signals:
        sig = signals[0]
        # 确保返回字段结构完整
        assert "sector_code" in sig
        assert "direction" in sig
