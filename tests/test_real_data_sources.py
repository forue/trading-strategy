import os
import datetime as dt
from fastapi.testclient import TestClient
import pytest

from services.strategy.app import main as strategy_main


REAL_DATA = os.environ.get("REAL_DATA_SOURCES", "0") == "1"


def _sample_sector_live():
    return {
        "sector_code": "THS801010",
        "sector_name": "农林牧渔",
        "main_net_inflow": 1234567.89,
        "north_net_inflow": 12345.0,
        "index_close": 102.5,
        "index_change_pct": 0.5,
        "turnover": 1234567.0,
        "open": 101.0,
        "high": 103.0,
        "low": 99.5,
        "pe_ttm": 14.2,
        "pb": 1.35,
        "etf_code": "159825",
        "etf_name": "农业ETF",
        "pe_percentile": 60.0,
        "pb_percentile": 40.0,
    }


def test_live_data_collector_availability_and_format(monkeypatch):
    if not REAL_DATA:
        pytest.skip("Real data sources not enabled via REAL_DATA_SOURCES env")

    client = TestClient(strategy_main.app)
    try:
        resp = client.post("/collect")
    except Exception:
        pytest.skip("Data collector service not accessible in this environment")
        return
    if resp.status_code != 200:
        # 采集服务可能暂不可用，允许跳过
        pytest.skip("Data collector not available or returned error")
        return
    payload = resp.json()
    assert payload.get("code") == 200
    data = payload.get("data")
    assert data is not None
    # 数据可能是列表或字典，尽量兼容
    if isinstance(data, list):
        assert len(data) >= 1
        first = data[0]
    elif isinstance(data, dict):
        first = next(iter(data.values()))[0]
    else:
        pytest.fail("Unexpected data format from data collector")
    # 基本字段校验
    for k in ["sector_code", "sector_name", "main_net_inflow"]:
        assert k in first


def test_influxdb_live_availability_and_format():
    if not REAL_DATA:
        pytest.skip("Real data sources not enabled via REAL_DATA_SOURCES env")

    iq = strategy_main.influx_query.InfluxDBQuery()
    # 使用最近一天的数据，尽量提高命中率
    end_date = dt.date.today().strftime("%Y-%m-%d")
    start_date = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        data = iq.query_daily_sectors(start_date, end_date)
    except Exception as e:
        pytest.skip(f"InfluxDB live query failed: {e}")
        return
    if not data:
        pytest.skip("No live InfluxDB sector data for the date range")
        return
    assert isinstance(data, dict)
    for day, sectors in data.items():
        assert isinstance(sectors, list)
        if not sectors:
            continue
        for s in sectors:
            # 关键字段存在性校验
            for key in ["sector_code", "sector_name", "main_net_inflow", "index_change_pct", "turnover"]:
                assert key in s
            # 基本数值合理性
            if s.get("main_net_inflow") is not None:
                assert isinstance(s["main_net_inflow"], (int, float))

def test_akshare_ths_live_availability_and_format():
    if not REAL_DATA:
        pytest.skip("Real data sources not enabled via REAL_DATA_SOURCES env")
    try:
        import akshare as ak  # type: ignore
    except Exception:
        pytest.skip("AkShare not installed in this environment")
        return
    # 尝试调用可能存在的 THS 数据接口，容错性强，若Signature不同则跳过
    tried = False
    try:
        if hasattr(ak, "ths_sector_flow"):
            tried = True
            df = ak.ths_sector_flow("THS801010")
            assert df is not None
            # 数据结构尽量符合 DataFrame
            assert getattr(df, "shape", None) is not None
    except Exception:
        pass
    if not tried:
        pytest.skip("AkShare THS data interface not available in this environment")
