"""策略引擎服务 - InfluxDB历史数据查询"""
import warnings
from datetime import datetime, timedelta
from influxdb_client import InfluxDBClient
from influxdb_client.client.warnings import MissingPivotFunction
from loguru import logger

from .config import settings

# 抑制MissingPivotFunction警告，因为我们已经在所有查询中正确使用了pivot()函数
warnings.simplefilter("ignore", MissingPivotFunction)


class InfluxDBQuery:
    """从InfluxDB读取板块历史数据供回测使用"""

    _date_range_cache: dict = None
    _date_range_cache_time: datetime = None
    CACHE_TTL = 300  # 5分钟

    @staticmethod
    def _safe_float(val, default=0.0) -> float:
        """安全转换为浮点数，处理 NaN/Infinity/None"""
        try:
            if val is None:
                return default
            if isinstance(val, float) and (val != val or val == float('inf') or val == float('-inf')):
                return default
            result = float(val)
            if result != result or result == float('inf') or result == float('-inf'):
                return default
            return result
        except (ValueError, TypeError, ArithmeticError):
            return default

    @staticmethod
    def _to_records(tables) -> list[dict]:
        """将 query_data_frame 返回的结果统一转换为 records 列表

        query_data_frame 可能返回：
        - 空列表 []（无数据）
        - 单个 DataFrame
        - DataFrame 列表（多表合并）
        """
        if tables is None:
            return []
        if isinstance(tables, list):
            if len(tables) == 0:
                return []
            # 多个 DataFrame 合并
            import pandas as pd
            combined = pd.concat(tables, ignore_index=True)
            return combined.to_dict("records") if not combined.empty else []
        if hasattr(tables, "empty") and tables.empty:
            return []
        if hasattr(tables, "to_dict"):
            return tables.to_dict("records")
        return []

    def __init__(self):
        self.client = InfluxDBClient(
            url=settings.influxdb_url,
            token=settings.influxdb_token,
            org=settings.influxdb_org,
        )
        self.query_api = self.client.query_api()
        self.bucket = settings.influxdb_bucket
        self.org = settings.influxdb_org

    @staticmethod
    def _date_to_flux_range(start_date: str, end_date: str) -> tuple[str, str]:
        """将 YYYY-MM-DD 日期转换为 FluxQL range() 所需的 RFC3339 格式

        InfluxDB 的 range() 不接受纯日期字符串(如 2026-01-01)，
        必须是相对时间(如 -365d)或 RFC3339 时间戳(如 2026-01-01T00:00:00Z)。
        """
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            # end_date 需要加1天，因为 range() 的 stop 是排他的
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            flux_start = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            flux_stop = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            return flux_start, flux_stop
        except ValueError:
            # 回退：用足够大的相对时间范围
            return "-730d", "now()"

    def query_daily_sectors(self, start_date: str, end_date: str,
                            sector_code: str = None) -> dict[str, list[dict]]:
        """查询指定日期范围内每天的板块资金流数据

        Args:
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            sector_code: 可选，筛选特定板块代码

        Returns:
            {date_str: [{sector_code, sector_name, main_net_inflow, north_net_inflow,
                         index_close, index_change_pct, turnover}, ...]}
        """
        flux_start, flux_stop = self._date_to_flux_range(start_date, end_date)

        # 构建板块过滤条件
        sector_filter = ""
        if sector_code:
            sector_filter = f'  |> filter(fn: (r) => r.sector_code == "{sector_code}")\n'

        query = f'''
        from(bucket: "{self.bucket}")
          |> range(start: {flux_start}, stop: {flux_stop})
          |> filter(fn: (r) => r._measurement == "sector_capital_flow")
{sector_filter}          |> pivot(rowKey: ["_time", "sector_code"], columnKey: ["_field"], valueColumn: "_value")
          |> keep(columns: ["_time", "sector_code", "sector_name",
                            "main_net_inflow", "north_net_inflow",
                            "index_close", "index_change_pct", "turnover",
                            "open", "high", "low",
                            "pe_ttm", "pb", "pe_percentile", "pb_percentile",
                            "etf_code", "etf_name"])
        '''
        try:
            tables = self.query_api.query_data_frame(query)
        except Exception as e:
            logger.error(f"InfluxDB查询失败: {e}")
            return {}

        records = self._to_records(tables)
        if not records:
            return {}

        daily_data: dict[str, list[dict]] = {}
        for row in records:
            time_str = str(row.get("_time", ""))
            try:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                date_key = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue

            if date_key not in daily_data:
                daily_data[date_key] = []

            daily_data[date_key].append({
                "sector_code": str(row.get("sector_code", "")),
                "sector_name": str(row.get("sector_name", "")),
                "main_net_inflow": self._safe_float(row.get("main_net_inflow", 0)),
                "north_net_inflow": self._safe_float(row.get("north_net_inflow", 0)),
                "index_close": self._safe_float(row.get("index_close", 0)),
                "index_change_pct": self._safe_float(row.get("index_change_pct", 0)),
                "turnover": self._safe_float(row.get("turnover", 0)),
                "open": self._safe_float(row.get("open", 0)),
                "high": self._safe_float(row.get("high", 0)),
                "low": self._safe_float(row.get("low", 0)),
                "pe_ttm": self._safe_float(row.get("pe_ttm", 0)),
                "pb": self._safe_float(row.get("pb", 0)),
                "pe_percentile": self._safe_float(row.get("pe_percentile", 0)),
                "pb_percentile": self._safe_float(row.get("pb_percentile", 0)),
                "etf_code": str(row.get("etf_code", "")) or None,
                "etf_name": str(row.get("etf_name", "")) or None,
            })

        logger.info(f"从InfluxDB查询到 {len(daily_data)} 天数据, 共 {len(records)} 条记录")
        return daily_data

    def get_available_date_range(self) -> tuple[str, str]:
        """获取InfluxDB中数据的可用日期范围（结果缓存5分钟）

        使用单次查询获取 first 和 last 时间，避免两次查询。
        """
        now = datetime.now()
        if self._date_range_cache is not None and self._date_range_cache_time is not None:
            if (now - self._date_range_cache_time).total_seconds() < self.CACHE_TTL:
                return self._date_range_cache

        # 直接使用回退方案：两次查询获取最早和最新日期
        return self._get_date_range_fallback()

    def _get_date_range_fallback(self) -> tuple[str, str]:
        """回退方案：两次查询获取日期范围"""
        now = datetime.now()
        query_min = f'''
        from(bucket: "{self.bucket}")
          |> range(start: -730d)
          |> filter(fn: (r) => r._measurement == "sector_capital_flow")
          |> group()
          |> sort(columns: ["_time"])
          |> limit(n: 1)
        '''
        try:
            tables = self.query_api.query_data_frame(query_min)
            if isinstance(tables, list) and len(tables) == 0:
                return "", ""
            if hasattr(tables, "empty") and tables.empty:
                return "", ""
        except Exception as e:
            logger.error(f"获取最早日期失败: {e}")
            return "", ""

        records = self._to_records(tables)
        if not records:
            return "", ""
        times = sorted([str(r.get("_time", "")) for r in records if r.get("_time")])
        if not times:
            return "", ""

        min_date = datetime.fromisoformat(times[0].replace("Z", "+00:00")).strftime("%Y-%m-%d")

        query_max = f'''
        from(bucket: "{self.bucket}")
          |> range(start: -730d)
          |> filter(fn: (r) => r._measurement == "sector_capital_flow")
          |> group()
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: 1)
        '''
        try:
            tables_max = self.query_api.query_data_frame(query_max)
            records_max = self._to_records(tables_max)
            times_max = sorted([str(r.get("_time", "")) for r in records_max if r.get("_time")])
            if times_max:
                max_date = datetime.fromisoformat(times_max[-1].replace("Z", "+00:00")).strftime("%Y-%m-%d")
                self._date_range_cache = (min_date, max_date)
                self._date_range_cache_time = now
                return min_date, max_date
        except Exception as e:
            logger.error(f"获取最新日期失败: {e}")

        self._date_range_cache = (min_date, min_date)
        self._date_range_cache_time = now
        return min_date, min_date

    def get_sector_list(self) -> list[dict]:
        """获取所有可用的板块列表（代码+名称）"""
        # 使用 pivot 后的数据按 sector_code 去重
        # 先取最近1天的数据获取所有板块（包含sector_code和sector_name）
        query = f'''
        from(bucket: "{self.bucket}")
          |> range(start: -730d)
          |> filter(fn: (r) => r._measurement == "sector_capital_flow")
          |> pivot(rowKey: ["_time", "sector_code"], columnKey: ["_field"], valueColumn: "_value")
          |> keep(columns: ["sector_code", "sector_name"])
          |> group()
          |> distinct(column: "sector_code")
        '''
        try:
            tables = self.query_api.query_data_frame(query)
            records = self._to_records(tables)
            # distinct结果中 sector_code 在 _value 列
            codes = []
            for r in records:
                code = str(r.get("_value", "") or r.get("sector_code", ""))
                if code:
                    codes.append(code)

            # 再查一次获取板块名称（从最近有数据的日期）
            if not codes:
                return []
            sectors = []
            for code in sorted(set(codes)):
                sectors.append({"sector_code": code, "sector_name": ""})

            # 用最近一天数据补充板块名称
            recent_data = self.query_daily_sectors(
                self.get_available_date_range()[1] or "2026-01-01",
                self.get_available_date_range()[1] or "2026-12-31",
            )
            if recent_data:
                last_date = sorted(recent_data.keys())[-1]
                name_map = {s["sector_code"]: s["sector_name"] for s in recent_data[last_date]}
                for s in sectors:
                    if s["sector_code"] in name_map:
                        s["sector_name"] = name_map[s["sector_code"]]
                    else:
                        s["sector_name"] = s["sector_code"]  # fallback

            return sectors
        except Exception as e:
            logger.error(f"获取板块列表失败: {e}")
            return []

    def query_sector_history(self, sector_code: str, start_date: str, end_date: str) -> list[dict]:
        """查询单个板块的历史数据序列（用于按板块回放）

        优先使用K线数据（sector_kline measurement），如果无K线数据则回退到资金流数据

        Returns:
            [{date, sector_code, sector_name, main_net_inflow, north_net_inflow,
              index_close, index_change_pct, turnover, open, high, low}, ...]
        """
        # 先尝试查询K线数据
        kline_data = self.query_sector_kline(sector_code, start_date, end_date)

        # 查询资金流数据
        daily_data = self.query_daily_sectors(start_date, end_date, sector_code=sector_code)
        flow_result = []
        for date in sorted(daily_data.keys()):
            for sector in daily_data[date]:
                if sector["sector_code"] == sector_code:
                    flow_result.append({"date": date, **sector})

        # 如果有K线数据，合并到结果中
        if kline_data:
            kline_map = {k["date"]: k for k in kline_data}
            for item in flow_result:
                kline = kline_map.get(item["date"])
                if kline:
                    item["open"] = kline["open"]
                    item["high"] = kline["high"]
                    item["low"] = kline["low"]
                    item["close"] = kline["close"]
                    item["volume"] = kline["volume"]
        return flow_result

    def query_sector_kline(self, sector_code: str, start_date: str, end_date: str) -> list[dict]:
        """查询板块K线数据（OHLC）

        Returns:
            [{date, sector_code, sector_name, open, close, high, low, volume, amount, change_pct}, ...]
        """
        flux_start, flux_stop = self._date_to_flux_range(start_date, end_date)

        query = f'''
        from(bucket: "{self.bucket}")
          |> range(start: {flux_start}, stop: {flux_stop})
          |> filter(fn: (r) => r._measurement == "sector_kline")
          |> filter(fn: (r) => r.sector_code == "{sector_code}")
          |> pivot(rowKey: ["_time", "sector_code"], columnKey: ["_field"], valueColumn: "_value")
          |> keep(columns: ["_time", "sector_code", "sector_name",
                            "open", "close", "high", "low",
                            "volume", "amount", "change_pct"])
        '''
        try:
            tables = self.query_api.query_data_frame(query)
        except Exception as e:
            logger.debug(f"K线数据查询失败(可能无数据): {e}")
            return []

        if isinstance(tables, list) and len(tables) == 0:
            return []
        if hasattr(tables, "empty") and tables.empty:
            return []

        result = []
        records = self._to_records(tables)
        for row in records:
            time_str = str(row.get("_time", ""))
            try:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                date_key = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue

            result.append({
                "date": date_key,
                "sector_code": str(row.get("sector_code", "")),
                "sector_name": str(row.get("sector_name", "")),
                "open": self._safe_float(row.get("open", 0)),
                "close": self._safe_float(row.get("close", 0)),
                "high": self._safe_float(row.get("high", 0)),
                "low": self._safe_float(row.get("low", 0)),
                "volume": self._safe_float(row.get("volume", 0)),
                "amount": self._safe_float(row.get("amount", 0)),
                "change_pct": self._safe_float(row.get("change_pct", 0)),
            })

        return result

    def close(self):
        self.client.close()

    def calculate_valuation_percentile(self, sector_code: str, date: str, lookback_days: int = 365) -> tuple[float | None, float | None]:
        """计算指定日期板块的PE/PB历史分位

        Args:
            sector_code: 板块代码
            date: 日期 YYYY-MM-DD
            lookback_days: 回溯天数

        Returns:
            (pe_percentile, pb_percentile) - 0-100范围，None表示无数据
        """
        start_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        
        flux_start, flux_stop = self._date_to_flux_range(start_date, date)

        query = f'''
        from(bucket: "{self.bucket}")
          |> range(start: {flux_start}, stop: {flux_stop})
          |> filter(fn: (r) => r._measurement == "sector_capital_flow")
          |> filter(fn: (r) => r.sector_code == "{sector_code}")
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> keep(columns: ["_time", "pe_ttm", "pb"])
        '''
        try:
            tables = self.query_api.query_data_frame(query)
        except Exception as e:
            logger.debug(f"估值分位计算失败: {e}")
            return None, None

        if isinstance(tables, list) and len(tables) == 0:
            return None, None
        if hasattr(tables, "empty") and tables.empty:
            return None, None

        records = self._to_records(tables)
        
        pe_values = []
        pb_values = []
        current_pe = None
        current_pb = None
        
        target_dt = datetime.strptime(date, "%Y-%m-%d")
        
        for row in records:
            time_str = str(row.get("_time", ""))
            try:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            
            pe = self._safe_float(row.get("pe_ttm"), 0)
            pb = self._safe_float(row.get("pb"), 0)
            
            if pe > 0:
                pe_values.append(pe)
                if dt.date() == target_dt.date():
                    current_pe = pe
            if pb > 0:
                pb_values.append(pb)
                if dt.date() == target_dt.date():
                    current_pb = pb

        pe_percentile = None
        pb_percentile = None
        
        if current_pe is not None and len(pe_values) >= 10:
            sorted_pe = sorted(pe_values)
            rank = sum(1 for v in sorted_pe if v < current_pe)
            pe_percentile = rank / len(sorted_pe) * 100
        
        if current_pb is not None and len(pb_values) >= 10:
            sorted_pb = sorted(pb_values)
            rank = sum(1 for v in sorted_pb if v < current_pb)
            pb_percentile = rank / len(sorted_pb) * 100

        return pe_percentile, pb_percentile

    def batch_update_valuation_percentile(self, start_date: str, end_date: str):
        """批量更新历史数据的估值分位"""
        daily_data = self.query_daily_sectors(start_date, end_date)
        
        updated_count = 0
        for date, sectors in daily_data.items():
            for sector in sectors:
                sector_code = sector.get("sector_code")
                if not sector_code:
                    continue
                
                pe_pct, pb_pct = self.calculate_valuation_percentile(sector_code, date)
                if pe_pct is not None or pb_pct is not None:
                    sector["pe_percentile"] = pe_pct
                    sector["pb_percentile"] = pb_pct
                    updated_count += 1
        
        logger.info(f"估值分位更新完成: {updated_count} 条")
        return daily_data


# 全局实例
influx_query = InfluxDBQuery()
