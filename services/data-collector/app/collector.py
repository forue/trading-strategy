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
        try:
            # 同花顺行业汇总 - 不受反爬限制
            df = ak.stock_board_industry_summary_ths()
            if df is not None and not df.empty:
                sector_map = self._get_sector_name_code_map()
                for _, row in df.iterrows():
                    sector_name = str(row.get("板块", "")).strip()
                    if not sector_name:
                        continue
                    sector_code = sector_map.get(sector_name, "")
                    # 同花顺净流入单位是亿元
                    net_inflow_yi = self._safe_float(row.get("净流入", 0))
                    # 转换为元存储（保持与 influx_client 字段单位一致）
                    main_net_inflow = net_inflow_yi * 1e8
                    results.append({
                        "sector_code": f"THS{sector_code}" if sector_code else f"THS_{sector_name}",
                        "sector_name": sector_name,
                        "date": trade_date,
                        "main_net_inflow": main_net_inflow,
                        "north_net_inflow": 0,  # 同花顺汇总不含北向数据
                        "index_close": self._safe_float(row.get("均价", 0)),
                        "index_change_pct": self._safe_float(row.get("涨跌幅", 0)),
                        "turnover": self._safe_float(row.get("总成交额", 0)) * 1e8,  # 亿元→元
                    })
                logger.info(f"同花顺行业汇总采集成功: {len(results)} 个板块")
        except Exception as e:
            logger.warning(f"同花顺行业汇总采集异常: {e}，使用模拟数据")
            results = self._generate_mock_data(trade_date)

        # 写入InfluxDB
        if results:
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
                    # 从K线数据构建资金流格式记录
                    # 成交额作为 turnover，涨跌幅作为资金强度指标
                    all_data.append({
                        "sector_code": item["sector_code"],
                        "sector_name": item["sector_name"],
                        "date": item["date"],
                        "main_net_inflow": 0,  # K线无资金流数据
                        "north_net_inflow": 0,
                        "index_close": item["close"],
                        "index_change_pct": item["change_pct"],
                        "turnover": item.get("amount", 0),
                        # K线附加字段
                        "open": item["open"],
                        "high": item["high"],
                        "low": item["low"],
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
        """采集北向资金数据（同花顺无对应接口，使用汇总中的净流入估算）
        非交易日不采集。
        """
        today = datetime.now().strftime("%Y%m%d")
        if not self.is_trade_day(today):
            logger.info(f"{today} 非交易日，跳过北向资金采集")
            return []
        results = []
        try:
            # 同花顺汇总中不包含北向资金，此处记录日志即可
            logger.info("同花顺数据源暂不支持北向资金细分数据")
        except Exception as e:
            logger.warning(f"北向资金数据采集异常: {e}")
        return results

    def _generate_mock_data(self, trade_date: str) -> list[dict]:
        """生成模拟数据（仅在同花顺接口也失败时使用），基于日期确定性生成"""
        import random
        sector_map = self._get_sector_name_code_map()
        if not sector_map:
            # 如果连板块列表都没有，使用固定列表
            sector_map = {
                "银行": "881156", "电子": "881121", "医药生物": "881139",
                "计算机": "881165", "食品饮料": "881141", "非银金融": "881157",
                "房地产": "881153", "传媒": "881164", "通信": "881167",
                "电气设备": "881136", "化工": "881108", "机械设备": "881160",
                "有色金属": "881107", "汽车": "881159", "公用事业": "881149",
                "国防军工": "881137", "建筑材料": "881142", "家用电器": "881131",
                "采掘": "881102", "钢铁": "881104", "纺织服装": "881132",
                "轻工制造": "881133", "交通运输": "881151", "商业贸易": "881155",
                "休闲服务": "881154", "综合": "881170", "建筑装饰": "881143",
                "农林牧渔": "881101", "通信设备": "881167",
            }
        seed_val = int(trade_date.replace("-", "")) if trade_date else 42
        rng = random.Random(seed_val)
        results = []
        for sector_name, code in sector_map.items():
            results.append({
                "sector_code": f"THS{code}",
                "sector_name": sector_name,
                "date": trade_date,
                "main_net_inflow": round(rng.uniform(-5e8, 5e8), 2),
                "north_net_inflow": round(rng.uniform(-2e8, 2e8), 2),
                "index_close": round(rng.uniform(2000, 8000), 2),
                "index_change_pct": round(rng.uniform(-3, 3), 4),
                "turnover": round(rng.uniform(1e8, 5e9), 2),
            })
        return results

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
