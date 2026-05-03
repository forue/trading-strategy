"""数据采集服务 - InfluxDB客户端封装"""
from datetime import datetime
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from loguru import logger

from .config import settings


class InfluxDBManager:
    """InfluxDB时序数据库管理器"""

    def __init__(self):
        self.client = InfluxDBClient(
            url=settings.influxdb_url,
            token=settings.influxdb_token,
            org=settings.influxdb_org,
        )
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.query_api = self.client.query_api()
        self.bucket = settings.influxdb_bucket
        self.org = settings.influxdb_org

    def write_sector_capital_flow(self, data: list[dict]):
        """写入板块资金流向数据

        Args:
            data: [{sector_code, sector_name, date, main_net_inflow,
                    north_net_inflow, index_close, index_change_pct, ...}]
        """
        points = []
        for item in data:
            # 将日期字符串转为datetime对象作为时间戳
            date_str = item.get("date", "")
            try:
                if len(date_str) == 8:  # YYYYMMDD
                    dt = datetime.strptime(date_str, "%Y%m%d")
                else:  # YYYY-MM-DD
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                dt = datetime.now()

            point = (
                Point("sector_capital_flow")
                .tag("sector_code", item["sector_code"])
                .tag("sector_name", item["sector_name"])
                .field("main_net_inflow", float(item.get("main_net_inflow", 0)))
                .field("north_net_inflow", float(item.get("north_net_inflow", 0)))
                .field("index_close", float(item.get("index_close", 0)))
                .field("index_change_pct", float(item.get("index_change_pct", 0)))
                .field("turnover", float(item.get("turnover", 0)))
            )
            # K线附加字段（如果有）
            for k in ("open", "high", "low"):
                if item.get(k) is not None and item.get(k) != 0:
                    point = point.field(k, float(item[k]))
            # 估值字段（如果有）
            for k in ("pe_ttm", "pb", "pe_percentile", "pb_percentile"):
                if item.get(k) is not None and item.get(k) != 0:
                    point = point.field(k, float(item[k]))
            # 基金字段（如果有）
            if item.get("etf_code"):
                point = point.field("etf_code", str(item["etf_code"]))
            if item.get("etf_name"):
                point = point.field("etf_name", str(item["etf_name"]))
            point = point.time(dt, WritePrecision.MS)
            points.append(point)

        if points:
            self.write_api.write(bucket=self.bucket, org=self.org, record=points)
            logger.info(f"写入板块资金流数据 {len(points)} 条")

    def write_sector_kline(self, data: list[dict]):
        """写入板块K线数据

        Args:
            data: [{sector_code, sector_name, date, open, close, high, low,
                    volume, amount, change_pct}, ...]
        """
        points = []
        for item in data:
            date_str = item.get("date", "")
            try:
                if len(date_str) == 8:
                    dt = datetime.strptime(date_str, "%Y%m%d")
                else:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                dt = datetime.now()

            point = (
                Point("sector_kline")
                .tag("sector_code", item["sector_code"])
                .tag("sector_name", item["sector_name"])
                .field("open", float(item.get("open", 0)))
                .field("close", float(item.get("close", 0)))
                .field("high", float(item.get("high", 0)))
                .field("low", float(item.get("low", 0)))
                .field("volume", float(item.get("volume", 0)))
                .field("amount", float(item.get("amount", 0)))
                .field("change_pct", float(item.get("change_pct", 0)))
                .time(dt, WritePrecision.MS)
            )
            points.append(point)

        if points:
            self.write_api.write(bucket=self.bucket, org=self.org, record=points)
            logger.info(f"写入板块K线数据 {len(points)} 条")

    def write_minute_capital_flow(self, data: list[dict]):
        """写入分钟级资金流向数据"""
        points = []
        for item in data:
            point = (
                Point("minute_capital_flow")
                .tag("sector_code", item["sector_code"])
                .tag("sector_name", item["sector_name"])
                .field("net_inflow", float(item.get("net_inflow", 0)))
                .field("buy_amount", float(item.get("buy_amount", 0)))
                .field("sell_amount", float(item.get("sell_amount", 0)))
                .time(item["timestamp"])
            )
            points.append(point)

        if points:
            self.write_api.write(bucket=self.bucket, org=self.org, record=points)
            logger.info(f"写入分钟资金流数据 {len(points)} 条")

    def query_sector_data(self, sector_code: str, start_date: str, end_date: str) -> list[dict]:
        """查询板块资金流数据"""
        # 转换为 RFC3339 格式
        start = f"{start_date}T00:00:00Z"
        stop = f"{end_date}T23:59:59Z"
        query = f'''
        from(bucket: "{self.bucket}")
          |> range(start: {start}, stop: {stop})
          |> filter(fn: (r) => r._measurement == "sector_capital_flow")
          |> filter(fn: (r) => r.sector_code == "{sector_code}")
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        tables = self.query_api.query_data_frame(query)
        if tables.empty:
            return []
        return tables.to_dict("records")

    def query_all_sectors_data(self, start_date: str, end_date: str) -> list[dict]:
        """查询所有板块资金流数据"""
        # 转换为 RFC3339 格式
        start = f"{start_date}T00:00:00Z"
        stop = f"{end_date}T23:59:59Z"
        query = f'''
        from(bucket: "{self.bucket}")
          |> range(start: {start}, stop: {stop})
          |> filter(fn: (r) => r._measurement == "sector_capital_flow")
          |> pivot(rowKey: ["_time", "sector_code"], columnKey: ["_field"], valueColumn: "_value")
        '''
        tables = self.query_api.query_data_frame(query)
        if tables.empty:
            return []
        return tables.to_dict("records")

    def close(self):
        self.client.close()


# 全局实例
influx_manager = InfluxDBManager()
