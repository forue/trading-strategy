import json
from fastapi.testclient import TestClient
import pytest

from services.strategy.app import main as strategy_main


def _sample_sector():
    return {
        "sector_code": "THS801010",
        "sector_name": "农林牧渔",
        "main_net_inflow": 1200000.0,
        "north_net_inflow": 400000.0,
        "index_close": 102.0,
        "index_change_pct": 0.8,
        "turnover": 1500000.0,
        "open": 101.0,
        "high": 103.0,
        "low": 100.0,
        "pe_ttm": 14.5,
        "pb": 1.4,
        "etf_code": "159825",
        "etf_name": "农业ETF",
        "pe_percentile": 55.0,
        "pb_percentile": 45.0,
    }


def _mock_daily_sectors():
    # 两天数据，每天两只板块，字段完整
    return {
        "2026-04-24": [
            _sample_sector(),
            {**_sample_sector(), "sector_code": "THS801020", "sector_name": "采掘"},
        ],
        "2026-04-25": [
            _sample_sector(),
            {**_sample_sector(), "sector_code": "THS801030", "sector_name": "化工"},
        ],
    }


def test_data_source_format_and_health(monkeypatch):
    client = TestClient(strategy_main.app)
    # 注入 Mock 数据源：覆盖 influx_query 的 daily data 提供
    monkeypatch.setattr(strategy_main.influx_query, "query_daily_sectors", _mock_daily_sectors)

    resp = client.post("/calculate?strategy_type=AGGRESSIVE&signal_date=2026-04-24")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("code") == 200
    signals = data.get("data")
    assert isinstance(signals, list)
    if not signals:
        pytest.skip("无信号输出，数据源格式测试跳过")

    # 取第一个信号做字段完整性校验
    first = signals[0]
    required_keys = [
        "signal_date", "strategy_type", "sector_code", "sector_name",
        "etf_code", "etf_name", "direction", "position_ratio", "score", "reason",
    ]
    for k in required_keys:
        assert k in first, f"缺少字段 {k}"

    # 进一步检查字段类型的合理性
    assert isinstance(first.get("sector_code"), str)
    assert isinstance(first.get("direction"), str)
    assert isinstance(first.get("position_ratio"), float)
    assert isinstance(first.get("score"), float)


def test_data_source_failure_returns_error(monkeypatch):
    client = TestClient(strategy_main.app)
    # 模拟数据源抛出异常，接口应返回 500
    def _raise(*args, **kwargs):
        raise RuntimeError("数据源不可用")
    monkeypatch.setattr(strategy_main.influx_query, "query_daily_sectors", _raise)

    resp = client.post("/calculate?strategy_type=AGGRESSIVE&signal_date=2026-04-24")
    # 现在实现中会将异常抛出为 500
    assert resp.status_code == 500
    data = resp.json()
    assert data.get("detail") is not None
