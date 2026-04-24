"""数据采集服务 - AkShare数据采集器（同花顺数据源）"""
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger

from .config import settings
from .influx_client import influx_manager


class DataCollector:
    """A股板块数据采集器 - 使用同花顺(THS)数据源

    同花顺接口不受东方财富反爬限制，数据稳定可靠。
    板块列表从 stock_board_industry_name_ths() 动态获取。
    """

    # 缓存交易日历
    _trade_dates_cache: list[str] | None = None
    # 缓存板块名称→代码映射
    _sector_name_code_map: dict[str, str] | None = None

    _SECTOR_ETF_MAP = {
        "农林牧渔": {"code": "159825", "name": "农业ETF"}, "采掘": {"code": "516260", "name": "矿业ETF"},
        "化工": {"code": "159870", "name": "化工ETF"}, "钢铁": {"code": "562300", "name": "钢铁ETF"},
        "有色金属": {"code": "512400", "name": "有色金属ETF"}, "电子": {"code": "159997", "name": "电子ETF"},
        "家用电器": {"code": "159746", "name": "家电ETF"}, "食品饮料": {"code": "512170", "name": "食品饮料ETF"},
        "纺织服装": {"code": "159573", "name": "纺织服装ETF"}, "轻工制造": {"code": "159608", "name": "轻工ETF"},
        "医药生物": {"code": "512010", "name": "医药ETF"}, "公用事业": {"code": "159611", "name": "公用事业ETF"},
        "交通运输": {"code": "159662", "name": "交运ETF"}, "房地产": {"code": "512200", "name": "房地产ETF"},
        "商业贸易": {"code": "159828", "name": "消费ETF"}, "休闲服务": {"code": "159766", "name": "旅游ETF"},
        "综合": {"code": "511020", "name": "综合ETF"}, "建筑材料": {"code": "159745", "name": "建材ETF"},
        "建筑装饰": {"code": "159740", "name": "基建ETF"}, "电气设备": {"code": "159611", "name": "新能源ETF"},
        "国防军工": {"code": "512810", "name": "军工ETF"}, "计算机": {"code": "512720", "name": "计算机ETF"},
        "传媒": {"code": "512980", "name": "传媒ETF"}, "通信": {"code": "515880", "name": "通信ETF"},
        "银行": {"code": "512800", "name": "银行ETF"}, "非银金融": {"code": "512070", "name": "非银ETF"},
        "证券": {"code": "512070", "name": "非银ETF"}, "保险": {"code": "512070", "name": "非银ETF"},
        "汽车": {"code": "516110", "name": "汽车ETF"}, "机械设备": {"code": "159883", "name": "机械ETF"},
    }

    def _get_etf_code_by_name(self, sector_name: str) -> str | None:
        etf = self._SECTOR_ETF_MAP.get(sector_name)
        return etf["code"] if etf else None

    def _get_etf_name_by_name(self, sector_name: str) -> str | None:
        etf = self._SECTOR_ETF_MAP.get(sector_name)
        return etf["name"] if etf else None

    def _get_sector_name_code_map(self) -> dict[str, str]:
        """获取板块名称→代码映射（从同花顺动态获取）"""
        if self._sector_name_code_map is not None:
            return self._sector_name_code_map
        try:
            df = ak.stock_board_industry_name_ths()
            if df is not None and not df.empty:
                self._sector_name_code_map = {}
                for _, row in df.iterrows():
                    name = str(row["name"]).strip()
                    code = str(row["code"]).strip()
                    self._sector_name_code_map[name] = code
                logger.info(f"获取同花顺板块列表: {len(self._sector_name_code_map)} 个")
                return self._sector_name_code_map
        except Exception as e:
            logger.warning(f"获取板块列表失败: {e}")
        # 回退：空映射
        self._sector_name_code_map = {}
        return self._sector_name_code_map

    def get_sector_names(self) -> list[str]:
        """获取所有板块名称列表"""
        return list(self._get_sector_name_code_map().keys())

    def get_trade_dates(self, days: int = 365) -> list[str]:
        """获取A股交易日历（从新浪获取真实交易日）"""
        if self._trade_dates_cache is not None:
            return self._trade_dates_cache
        try:
            df = ak.tool_trade_date_hist_sina()
            if df is not None and not df.empty:
                dates = df.iloc[:, 0].tolist()
                self._trade_dates_cache = [
                    d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d)
                    for d in dates
                ]
                logger.info(f"获取交易日历成功: {len(self._trade_dates_cache)} 个交易日")
                return self._trade_dates_cache
        except Exception as e:
            logger.warning(f"获取交易日历失败: {e}，使用周末过滤")
        return None

    def is_trade_day(self, date_str: str) -> bool:
        """判断是否为交易日"""
        trade_dates = self.get_trade_dates()
        date_compact = date_str.replace("-", "")
        if trade_dates:
            return date_compact in trade_dates
        # 回退：简单跳过周末
        try:
            d = datetime.strptime(date_compact, "%Y%m%d")
            return d.weekday() < 5  # 0-4 = Mon-Fri
        except ValueError:
            return False

    def _get_yesterday_close_price(self, sector_name: str) -> float | None:
        """获取指定板块的昨日收盘价（从K线接口）"""
        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            df = ak.stock_board_industry_index_ths(
                symbol=sector_name,
                start_date=yesterday,
                end_date=yesterday,
            )
            if df is not None and not df.empty:
                close = self._safe_float(df.iloc[0].get("收盘价", 0))
                if close > 0:
                    logger.debug(f"获取 {sector_name} 昨日收盘价: {close}")
                    return close
        except Exception as e:
            logger.debug(f"获取 {sector_name} 昨日收盘价失败: {e}")
        return None

    def _get_today_close_price(self, sector_name: str) -> float | None:
        """获取指定板块的今日收盘价（从K线接口）"""
        try:
            today = datetime.now().strftime("%Y%m%d")
            df = ak.stock_board_industry_index_ths(
                symbol=sector_name,
                start_date=today,
                end_date=today,
            )
            if df is not None and not df.empty:
                close = self._safe_float(df.iloc[0].get("收盘价", 0))
                if close > 0:
                    return close
        except Exception as e:
            logger.debug(f"获取 {sector_name} 收盘价失败: {e}")
        return None

    def collect_sector_capital_flow(self, trade_date: str = None) -> list[dict]:
        """采集板块资金流向数据（同花顺行业汇总接口）

        使用 stock_board_industry_summary_ths() 获取所有板块实时汇总数据，
        包含涨跌幅、净流入、成交额等。
        非交易日不采集，直接返回空列表。

        Args:
            trade_date: 交易日期 YYYY-MM-DD 或 YYYYMMDD，默认今天
        Returns:
            板块资金流数据列表
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y%m%d")
        else:
            trade_date = trade_date.replace("-", "")

        # 非交易日检查：不采集，不生成模拟数据
        if not self.is_trade_day(trade_date):
            logger.info(f"{trade_date} 非交易日，跳过板块资金流采集")
            return []

        results = []
        close_cache = {}
        try:
            df = ak.stock_board_industry_summary_ths()
            if df is not None and not df.empty:
                sector_map = self._get_sector_name_code_map()
                for _, row in df.iterrows():
                    sector_name = str(row.get("板块", "")).strip()
                    if not sector_name:
                        continue
                    sector_code = sector_map.get(sector_name, "")
                    close_cache[sector_name] = self._safe_float(row.get("均价", 0))
                    # 同花顺净流入单位是亿元
                    net_inflow_yi = self._safe_float(row.get("净流入", 0))
                    # 转换为元存储（保持与 influx_client 字段单位一致）
                    main_net_inflow = net_inflow_yi * 1e8
                    # 估值数据处理
                    pe_str = str(row.get("市盈率", ""))
                    pb_str = str(row.get("市净率", ""))
                    try:
                        pe_ttm = float(pe_str) if pe_str and pe_str != "--" else None
                    except (ValueError, TypeError):
                        pe_ttm = None
                    try:
                        pb = float(pb_str) if pb_str and pb_str != "--" else None
                    except (ValueError, TypeError):
                        pb = None
                    
                    results.append({
                        "sector_code": f"THS{sector_code}" if sector_code else f"THS_{sector_name}",
                        "sector_name": sector_name,
                        "date": trade_date,
                        "main_net_inflow": main_net_inflow,
                        "north_net_inflow": 0,
                        "index_close": self._safe_float(row.get("均价", 0)),
                        "index_change_pct": self._safe_float(row.get("涨跌幅", 0)),
                        "turnover": self._safe_float(row.get("总成交额", 0)) * 1e8,
                        "pe_ttm": pe_ttm,
                        "pb": pb,
                        "pe_percentile": None,
                        "pb_percentile": None,
                        "open": 0,
                        "high": 0,
                        "low": 0,
                    })
                logger.info(f"同花顺行业汇总采集成功: {len(results)} 个板块")
        except Exception as e:
            logger.error(f"同花顺行业汇总采集异常: {e}，返回空数据")
            results = []
            close_cache = {}

        # 获取收盘价（从K线接口替换均价）
        # 优先获取昨日收盘价，非交易时段今日收盘价可能为空
        if close_cache:
            for item in results:
                sector_name = item["sector_name"]
                close_price = self._get_yesterday_close_price(sector_name)
                if close_price and close_price > 0:
                    item["index_close"] = close_price
                else:
                    # 无昨日数据时回退到均价
                    item["index_close"] = close_cache.get(sector_name, item["index_close"])

        # 写入InfluxDB
        if results:
            # 计算每条记录的估值分位
            for item in results:
                pe_pct, pb_pct = self.calculate_sector_valuation_percentile(
                    item["sector_code"], 
                    item["date"]
                )
                item["pe_percentile"] = pe_pct
                item["pb_percentile"] = pb_pct
            
            influx_manager.write_sector_capital_flow(results)
            logger.info(f"板块资金流数据写入完成: {len(results)} 个板块")

        return results

    def collect_sector_history(self, days: int = 30) -> list[dict]:
        """采集板块历史资金流数据（自动跳过非交易日）

        注意：同花顺汇总接口只有当日数据，历史数据需通过K线获取。
        此方法仅采集当日汇总数据用于实时展示。

        Args:
            days: 回溯天数（实际只采集当日）
        """
        all_data = []
        # 只采集当日数据（同花顺汇总无历史查询能力）
        today = datetime.now().strftime("%Y%m%d")
        if self.is_trade_day(today):
            try:
                data = self.collect_sector_capital_flow(today)
                all_data.extend(data)
            except Exception as e:
                logger.warning(f"采集当日数据失败: {e}")
        else:
            logger.info(f"今日 {today} 非交易日，跳过采集")
        return all_data

    def collect_sector_history_via_kline(self, days: int = 30) -> list[dict]:
        """通过K线历史数据填充板块资金流（用于回放）

        K线数据包含 OHLC + 成交额，不含资金流，但涨跌幅可替代资金强度指标。

        Args:
            days: 回溯天数
        """
        all_data = []
        sector_names = self.get_sector_names()
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")

        for sector_name in sector_names:
            try:
                kline = self.collect_sector_kline(sector_name, start_date, end_date)
                for item in kline:
                    all_data.append({
                        "sector_code": item["sector_code"],
                        "sector_name": item["sector_name"],
                        "date": item["date"],
                        "main_net_inflow": 0,
                        "north_net_inflow": 0,
                        "index_close": item["close"],
                        "index_change_pct": item["change_pct"],
                        "turnover": item.get("amount", 0),
                        "open": item["open"],
                        "high": item["high"],
                        "low": item["low"],
                        "pe_ttm": None,
                        "pb": None,
                        "pe_percentile": None,
                        "pb_percentile": None,
                    })
            except Exception as e:
                logger.warning(f"采集 {sector_name} K线历史失败: {e}")

        if all_data:
            influx_manager.write_sector_capital_flow(all_data)
            logger.info(f"通过K线填充历史资金流: {len(all_data)} 条")

        return all_data

    def collect_sector_kline(self, sector_name: str, start_date: str = None, end_date: str = None, period: str = "日k") -> list[dict]:
        """采集板块K线数据（同花顺源 - OHLC + 成交量）

        使用 stock_board_industry_index_ths() 获取同花顺行业指数K线。

        Args:
            sector_name: 板块名称（同花顺格式，如"银行"、"电子"等）
            start_date: 开始日期 YYYYMMDD，默认 60天前
            end_date: 结束日期 YYYYMMDD，默认今天
            period: K线周期 "日k"/"周k"/"月k"
        Returns:
            K线数据列表 [{date, open, close, high, low, volume, amount, change_pct}, ...]
        """
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        sector_map = self._get_sector_name_code_map()
        sector_code = sector_map.get(sector_name, "")

        results = []
        try:
            df = ak.stock_board_industry_index_ths(
                symbol=sector_name,
                start_date=start_date,
                end_date=end_date,
            )
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    close = self._safe_float(row.get("收盘价", 0))
                    open_ = self._safe_float(row.get("开盘价", 0))
                    high = self._safe_float(row.get("最高价", 0))
                    low = self._safe_float(row.get("最低价", 0))
                    # 计算涨跌幅
                    change_pct = ((close - open_) / open_ * 100) if open_ != 0 else 0

                    results.append({
                        "sector_code": f"THS{sector_code}" if sector_code else f"THS_{sector_name}",
                        "sector_name": sector_name,
                        "date": str(row.get("日期", "")),
                        "open": open_,
                        "close": close,
                        "high": high,
                        "low": low,
                        "volume": self._safe_float(row.get("成交量", 0)),
                        "amount": self._safe_float(row.get("成交额", 0)),
                        "change_pct": round(change_pct, 4),
                    })
                logger.info(f"采集 {sector_name} K线数据: {len(results)} 条")
        except Exception as e:
            logger.warning(f"采集 {sector_name} K线数据失败: {e}")
        return results

    def collect_all_sectors_kline(self, start_date: str = None, end_date: str = None) -> list[dict]:
        """采集所有板块K线数据"""
        all_data = []
        sector_names = self.get_sector_names()
        total = len(sector_names)

        for i, sector_name in enumerate(sector_names):
            try:
                data = self.collect_sector_kline(sector_name, start_date, end_date)
                all_data.extend(data)
                if (i + 1) % 10 == 0:
                    logger.info(f"K线采集进度: {i + 1}/{total}")
            except Exception as e:
                logger.warning(f"采集 {sector_name} K线失败: {e}")

        if all_data:
            influx_manager.write_sector_kline(all_data)
            logger.info(f"所有板块K线数据采集完成: {len(all_data)} 条")
        return all_data

    def collect_north_bound_flow(self) -> list[dict]:
        """采集北向资金数据（同花顺无对应接口，返回空列表）
        非交易日不采集。
        """
        today = datetime.now().strftime("%Y%m%d")
        if not self.is_trade_day(today):
            logger.info(f"{today} 非交易日，跳过北向资金采集")
            return []
        logger.info("北向资金数据暂无数据源")
        return []

    def calculate_sector_valuation_percentile(self, sector_code: str, trade_date: str = None) -> tuple[float | None, float | None]:
        """计算板块PE/PB历史分位

        从InfluxDB查询历史数据，计算当前PE/PB在历史数据中的分位

        Args:
            sector_code: 板块代码
            trade_date: 交易日期，默认今天

        Returns:
            (pe_percentile, pb_percentile) - 0-100范围，None表示无足够历史数据
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y%m%d")
        else:
            trade_date = trade_date.replace("-", "")

        from .influx_client import influx_manager
        
        lookback_days = 365
        start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=lookback_days)).strftime("%Y%m%d")
        
        query = f'''
        from(bucket: "{influx_manager.bucket}")
          |> range(start: -{lookback_days}d, stop: now())
          |> filter(fn: (r) => r._measurement == "sector_capital_flow")
          |> filter(fn: (r) => r.sector_code == "{sector_code}")
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> keep(columns: ["_time", "pe_ttm", "pb"])
        '''
        try:
            tables = influx_manager.query_api.query_data_frame(query)
        except Exception as e:
            logger.warning(f"查询历史估值数据失败: {e}")
            return None, None

        if isinstance(tables, list) and len(tables) == 0:
            return None, None
        if hasattr(tables, "empty") and tables.empty:
            return None, None

        records = tables.to_dict("records")
        
        pe_values = []
        pb_values = []
        current_pe = None
        current_pb = None
        
        target_date = trade_date[:4] + "-" + trade_date[4:6] + "-" + trade_date[6:8]
        
        for row in records:
            time_str = str(row.get("_time", ""))
            try:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                date_key = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            
            if date_key != target_date:
                continue
                
            pe = self._safe_float(row.get("pe_ttm"), 0)
            pb = self._safe_float(row.get("pb"), 0)
            
            if pe > 0:
                current_pe = pe
            if pb > 0:
                current_pb = pb
        
        for row in records:
            time_str = str(row.get("_time", ""))
            try:
                datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            
            pe = self._safe_float(row.get("pe_ttm"), 0)
            pb = self._safe_float(row.get("pb"), 0)
            
            if pe > 0:
                pe_values.append(pe)
            if pb > 0:
                pb_values.append(pb)

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

    @staticmethod
    def _safe_float(val, default=0.0) -> float:
        try:
            if pd.isna(val):
                return default
            return float(val)
        except (ValueError, TypeError):
            return default


# 全局实例
data_collector = DataCollector()
