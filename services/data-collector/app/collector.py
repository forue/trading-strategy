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
    _trade_dates_cache_ts: datetime | None = None
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
        """获取A股交易日历（从新浪获取真实交易日）

        缓存1小时自动刷新，避免 AkShare 返回不完整数据后永久失效。
        """
        now = datetime.now()
        if self._trade_dates_cache is not None and self._trade_dates_cache_ts is not None:
            cache_age = (now - self._trade_dates_cache_ts).total_seconds()
            if cache_age < 3600:
                return self._trade_dates_cache
        try:
            df = ak.tool_trade_date_hist_sina()
            if df is not None and not df.empty:
                dates = df.iloc[:, 0].tolist()
                self._trade_dates_cache = [
                    d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d)
                    for d in dates
                ]
                self._trade_dates_cache_ts = now
                # 校验：缓存必须覆盖当前月份，否则视为无效
                current_month = now.strftime("%Y%m")
                month_dates = [d for d in self._trade_dates_cache if d.startswith(current_month)]
                if month_dates:
                    logger.info(f"获取交易日历成功: {len(self._trade_dates_cache)} 个交易日 (当前月 {len(month_dates)} 个)")
                    return self._trade_dates_cache
                logger.warning(f"交易日历缺少当前月份 {current_month} 数据，回退到周末过滤")
                self._trade_dates_cache = None
                return None
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

    def _get_last_trade_date(self, before_date: str = None) -> str:
        """获取指定日期之前最近一个交易日（格式 YYYYMMDD）"""
        if before_date is None:
            before_date = datetime.now().strftime("%Y%m%d")
        trade_dates = self.get_trade_dates()
        if trade_dates:
            past = [d for d in trade_dates if d < before_date]
            if past:
                return past[-1]
        return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    def _get_yesterday_close_price(self, sector_name: str) -> float | None:
        """获取指定板块前一个交易日的收盘价（从K线接口，自动跳过周末和节假日）"""
        try:
            last_trade_date = self._get_last_trade_date()
            df = ak.stock_board_industry_index_ths(
                symbol=sector_name,
                start_date=last_trade_date,
                end_date=last_trade_date,
            )
            if df is not None and not df.empty:
                close = self._safe_float(df.iloc[0].get("收盘价", 0))
                if close > 0:
                    logger.debug(f"获取 {sector_name} 前交易日({last_trade_date})收盘价: {close}")
                    return close
        except Exception as e:
            logger.debug(f"获取 {sector_name} 前交易日收盘价失败: {e}")
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
                        "north_net_inflow": None,  # 不覆盖北向资金（独立采集）
                        "index_close": self._safe_float(row.get("均价", 0)),
                        "index_change_pct": self._safe_float(row.get("涨跌幅", 0)),
                        "turnover": self._safe_float(row.get("总成交额", 0)) * 1e8,
                        "pe_ttm": pe_ttm,
                        "pb": pb,
                        "pe_percentile": None,
                        "pb_percentile": None,
                        "open": None,
                        "high": None,
                        "low": None,
                    })
                logger.info(f"同花顺行业汇总采集成功: {len(results)} 个板块")
        except Exception as e:
            logger.error(f"同花顺行业汇总采集异常: {e}，返回空数据")
            results = []
            close_cache = {}

        # 获取收盘价（从K线接口替换均价，并发获取以控制在合理时间内完成）
        if close_cache:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            sector_names = [item["sector_name"] for item in results]
            close_prices: dict[str, float | None] = {}
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(self._get_yesterday_close_price, name): name for name in sector_names}
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        close_prices[name] = future.result()
                    except Exception:
                        close_prices[name] = None
            for item in results:
                name = item["sector_name"]
                close_price = close_prices.get(name)
                if close_price and close_price > 0:
                    item["index_close"] = close_price
                else:
                    # 无前交易日数据时回退到均价
                    item["index_close"] = close_cache.get(name, item["index_close"])

        # 写入InfluxDB
        if results:
            # 计算每条记录的估值分位
            for item in results:
                pe_pct, pb_pct = self.calculate_sector_valuation_percentile(
                    item["sector_code"], 
                    item["date"],
                    item.get("pe_ttm"),
                    item.get("pb")
                )
                item["pe_percentile"] = pe_pct
                item["pb_percentile"] = pb_pct
            
            influx_manager.write_sector_capital_flow(results)
            logger.info(f"板块资金流数据写入完成: {len(results)} 个板块")

        return results

    def collect_sector_history(self, days: int = 30, trade_date: str = None) -> list[dict]:
        """采集板块历史资金流数据（自动跳过非交易日）

        注意：同花顺汇总接口只有当日数据，历史数据需通过K线获取。
        此方法仅采集指定日期（或当日）汇总数据用于实时展示。

        Args:
            days: 回溯天数（实际只采集指定日期单日）
            trade_date: 目标采集日期 YYYYMMDD 或 YYYY-MM-DD，不传则使用今日。
                        未传且今日非交易日时，自动回退到最近一个交易日。
        """
        all_data = []
        if trade_date:
            target = trade_date.replace("-", "")
        else:
            target = datetime.now().strftime("%Y%m%d")
        # 非交易日自动回退到最近一个交易日（仅当未显式指定日期时）
        if not self.is_trade_day(target):
            if trade_date:
                logger.info(f"{target} 非交易日，跳过采集")
                return all_data
            fallback = self._get_last_trade_date(target)
            logger.info(f"今日 {target} 非交易日，回退到最近交易日 {fallback}")
            target = fallback
        try:
            data = self.collect_sector_capital_flow(target)
            all_data.extend(data)
        except Exception as e:
            logger.warning(f"采集 {target} 数据失败: {e}")
        return all_data

    def collect_sector_history_via_kline(self, days: int = 30) -> list[dict]:
        """通过K线历史数据填充板块资金流（用于回放）

        K线数据包含 OHLC + 成交额，不含资金流，但涨跌幅可替代资金强度指标。
        使用线程池并发采集，提升效率。

        Args:
            days: 回溯天数
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        sector_names = self.get_sector_names()
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")

        all_data = []
        failed = []

        def _fetch_one(sector_name):
            """采集单个板块K线"""
            try:
                kline = self.collect_sector_kline(sector_name, start_date, end_date)
                result = []
                for item in kline:
                    result.append({
                        "sector_code": item["sector_code"],
                        "sector_name": item["sector_name"],
                        "date": item["date"],
                        "main_net_inflow": None,
                        "north_net_inflow": None,
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
                return sector_name, result
            except Exception as e:
                return sector_name, e

        # 并发采集，最多 5 个线程
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_one, name): name for name in sector_names}
            for future in as_completed(futures):
                sector_name, result = future.result()
                if isinstance(result, Exception):
                    failed.append(sector_name)
                    logger.warning(f"采集 {sector_name} K线历史失败: {result}")
                else:
                    all_data.extend(result)

        if all_data:
            merged = self._merge_with_existing_data(all_data)
            influx_manager.write_sector_capital_flow(merged)
            logger.info(f"通过K线填充历史资金流: {len(merged)} 条, 失败: {len(failed)} 个板块")

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
                # 尝试使用 akshare 提供的涨跌幅字段，否则计算日内涨跌幅
                has_change_col = "涨跌幅" in df.columns
                prev_close = None
                for _, row in df.iterrows():
                    close = self._safe_float(row.get("收盘价", 0))
                    open_ = self._safe_float(row.get("开盘价", 0))
                    high = self._safe_float(row.get("最高价", 0))
                    low = self._safe_float(row.get("最低价", 0))
                    # 优先使用 akshare 提供的涨跌幅（基于前收盘价）
                    if has_change_col:
                        change_pct = self._safe_float(row.get("涨跌幅", 0))
                    elif prev_close and prev_close > 0:
                        change_pct = ((close - prev_close) / prev_close * 100)
                    else:
                        change_pct = ((close - open_) / open_ * 100) if open_ != 0 else 0
                    prev_close = close

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

    def collect_north_bound_flow(self, trade_date: str = None) -> list[dict]:
        """采集北向资金数据

        使用 AkShare 的 stock_hsgt_fund_flow_summary_em() 获取当日沪深股通资金流向。
        返回单日汇总数据（北向净流入 = 沪股通 + 深股通 净买额之和）。
        未传日期且今日非交易日时，自动回退到最近一个交易日。

        Args:
            trade_date: 目标采集日期 YYYYMMDD 或 YYYY-MM-DD，不传则使用今日
        """
        if trade_date:
            target = trade_date.replace("-", "")
        else:
            target = datetime.now().strftime("%Y%m%d")
        if not self.is_trade_day(target):
            if trade_date:
                logger.info(f"{target} 非交易日，跳过北向资金采集")
                return []
            fallback = self._get_last_trade_date(target)
            logger.info(f"今日 {target} 非交易日，回退到最近交易日 {fallback} 采集北向资金")
            target = fallback

        try:
            df = ak.stock_hsgt_fund_flow_summary_em()
            if df is None or df.empty:
                logger.warning("北向资金数据为空")
                return []

            # 接口返回 4 行: [沪股通北向, 沪股通南向, 深股通北向, 深股通南向]
            # 列结构 (positional): 0=日期, 1=市场, 2=方向, 3=资金向, 4=状态, 5=成交净买额(亿), 6=资金余额(亿)
            if len(df) < 2:
                logger.warning(f"北向资金数据行数不足: {len(df)}")
                return []

            date_val = df.iloc[0, 0]
            if hasattr(date_val, "strftime"):
                date_str = date_val.strftime("%Y-%m-%d")
            else:
                date_str = str(date_val)[:10]

            # 北向净流入 = 沪股通北向 + 深股通北向 (第0行和第2行的第5列, 单位亿元)
            north_sh = self._safe_float(df.iloc[0, 5])
            north_sz = self._safe_float(df.iloc[2, 5]) if len(df) >= 3 else 0.0
            net_inflow = (north_sh + north_sz) * 1e8  # 亿元 → 元

            results = [{"date": date_str, "north_net_inflow": net_inflow}]

            influx_manager.write_north_bound_flow(results)
            logger.info(f"北向资金采集完成: 日期={date_str}, 净流入={net_inflow/1e8:.2f}亿")

            return results
        except Exception as e:
            logger.error(f"北向资金采集失败: {e}")
            return []

    # 东方财富板块代码缓存
    _em_code_map: dict[str, str] | None = None

    def _get_em_code_map(self) -> dict[str, str]:
        """从东方财富网页抓取板块名称→EM代码映射（push2.eastmoney.com 被封，改从HTML页面提取）"""
        if self._em_code_map is not None:
            return self._em_code_map
        import requests
        import re
        try:
            r = requests.get(
                "https://data.eastmoney.com/bkzj/hy.html",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=15,
            )
            pairs = re.findall(r'<a href="/bkzj/(BK\d+)\.html">([^<]+)</a>', r.text)
            self._em_code_map = {name: code for code, name in pairs}
            logger.info(f"从东方财富抓取板块代码映射: {len(self._em_code_map)} 个")
        except Exception as e:
            logger.warning(f"抓取东方财富板块代码映射失败: {e}")
            self._em_code_map = {}
        return self._em_code_map

    def _match_em_code(self, ths_name: str) -> str | None:
        """将THS板块名称匹配到东方财富板块代码"""
        em_map = self._get_em_code_map()
        if not em_map:
            return None
        # 精确匹配
        if ths_name in em_map:
            return em_map[ths_name]
        # 模糊匹配: EM名称以THS名称开头，或THS名称以EM名称开头
        for em_name, code in em_map.items():
            if em_name.startswith(ths_name) or ths_name.startswith(em_name):
                return code
        return None

    def backfill_sector_fund_flow_hist(self, start_date: str = "20240101", end_date: str = None) -> int:
        """回填历史板块资金流数据

        由于 akshare 的 stock_sector_fund_flow_hist() 底层调用 push2.eastmoney.com
        获取板块代码映射时被封，本方法改为:
        1. 从 data.eastmoney.com 网页抓取 EM 板块代码映射
        2. 直接调用 push2his.eastmoney.com 数据接口（未被封）
        3. 解析主力净流入并写入 InfluxDB
        """
        import requests as req
        import time as _time

        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        sector_names = self.get_sector_names()
        if not sector_names:
            logger.warning("无可用板块名称，跳过资金流回填")
            return 0

        # 提前获取 EM 代码映射
        em_map = self._get_em_code_map()
        if not em_map:
            logger.warning("无法获取东方财富板块代码映射，跳过回填")
            return 0

        # 建立 THS名称 → EM代码 的匹配表
        name_to_em: dict[str, str] = {}
        unmatched: list[str] = []
        for name in sector_names:
            code = self._match_em_code(name)
            if code:
                name_to_em[name] = code
            else:
                unmatched.append(name)
        logger.info(
            f"板块匹配: {len(name_to_em)} 个成功, {len(unmatched)} 个未匹配"
            + (f" ({', '.join(unmatched[:10])}...)" if unmatched else "")
        )

        if not name_to_em:
            logger.warning("无任何板块匹配成功，跳过回填")
            return 0

        logger.info(f"开始回填 {len(name_to_em)} 个板块的历史资金流 ({start_date}~{end_date})（串行模式，间隔2秒）")

        all_records: list[dict] = []
        failed: list[str] = []

        for idx, (name, em_code) in enumerate(name_to_em.items()):
            ths_code = self._get_sector_name_code_map().get(name, "")
            try:
                url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
                params = {
                    "lmt": "0",
                    "klt": "101",
                    "fields1": "f1,f2,f3,f7",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                    "secid": f"90.{em_code}",
                }
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": f"https://data.eastmoney.com/bkzj/{em_code}.html",
                }
                r = req.get(url, params=params, headers=headers, timeout=15)
                data_json = r.json()
                klines = data_json.get("data", {}).get("klines")
                if not klines:
                    failed.append(name)
                    continue

                records = []
                for line in klines:
                    parts = line.split(",")
                    if len(parts) < 2:
                        continue
                    date_str = parts[0].replace("-", "") if parts[0] else ""
                    if not date_str or not (start_date <= date_str <= end_date):
                        continue
                    if not self.is_trade_day(date_str):
                        continue

                    main_net_inflow = self._safe_float(parts[1])  # 主力净流入-净额（元）

                    records.append({
                        "sector_code": f"THS{ths_code}" if ths_code else f"THS_{name}",
                        "sector_name": name,
                        "date": date_str,
                        "main_net_inflow": main_net_inflow,
                        "north_net_inflow": 0,
                        "index_close": None,
                        "index_change_pct": None,
                        "turnover": 0,
                        "pe_ttm": None,
                        "pb": None,
                        "pe_percentile": None,
                        "pb_percentile": None,
                        "open": None,
                        "high": None,
                        "low": None,
                    })
                all_records.extend(records)
                if (idx + 1) % 10 == 0:
                    logger.info(f"资金流回填进度: {idx + 1}/{len(name_to_em)} (已写入 {len(all_records)} 条)")
            except Exception as e:
                logger.warning(f"回填 {name}({em_code}) 失败: {e}")
                failed.append(name)
            # 每个请求间隔 2 秒，避免触发反爬
            if idx < len(name_to_em) - 1:
                _time.sleep(2)

        if all_records:
            merged = self._merge_with_existing_data(all_records)
            influx_manager.write_sector_capital_flow(merged)
            logger.info(f"资金流回填完成: {len(merged)} 条记录, 失败板块: {len(failed)}")
        else:
            logger.warning("资金流回填: 无数据写入")

        return len(all_records)

    _MERGEABLE_FIELDS = (
        "open", "high", "low", "index_close", "index_change_pct",
        "main_net_inflow", "north_net_inflow", "turnover",
        "pe_ttm", "pb", "pe_percentile", "pb_percentile",
    )

    def _merge_with_existing_data(self, new_records: list[dict]) -> list[dict]:
        """将新数据与 InfluxDB 中已有数据合并，双向保留已有字段不被 None 覆盖。

        回填场景：OHLC 字段为 None，从已有数据恢复 OHLC
        K线填充场景：资金流字段为 None，从已有数据恢复资金流
        """
        if not new_records:
            return new_records

        lookup: dict[str, set[str]] = {}
        for r in new_records:
            d = r.get("date", "")
            sc = r.get("sector_code", "")
            if d and sc:
                d_normalized = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d[:10]
                lookup.setdefault(d_normalized, set()).add(sc)

        if not lookup:
            return new_records

        dates = sorted(lookup.keys())
        start, end = dates[0], dates[-1]
        existing_map: dict[str, dict] = {}
        try:
            daily = influx_manager.query_all_sectors_data(start, end)
            for rec in daily:
                t = str(rec.get("_time", ""))[:10]
                sc = str(rec.get("sector_code", ""))
                key = f"{t}|{sc}"
                if key not in existing_map:
                    existing_map[key] = rec
        except Exception as e:
            logger.warning(f"查询已有数据失败，跳过合并: {e}")
            return new_records

        merged = []
        for r in new_records:
            d = r.get("date", "")
            sc = r.get("sector_code", "")
            d_normalized = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d[:10]
            key = f"{d_normalized}|{sc}"
            existing = existing_map.get(key)
            if existing:
                for f in self._MERGEABLE_FIELDS:
                    if r.get(f) is None and existing.get(f) is not None:
                        r[f] = float(existing[f]) if existing[f] else 0.0
            merged.append(r)

        return merged

    @staticmethod
    def _safe_float(val, default=0.0) -> float:
        """安全转换为浮点数"""
        try:
            if val is None:
                return default
            if isinstance(val, float) and (val != val or val == float('inf') or val == float('-inf')):
                return default
            return float(val)
        except (ValueError, TypeError):
            return default

    def calculate_sector_valuation_percentile(self, sector_code: str, trade_date: str = None, current_pe: float = None, current_pb: float = None) -> tuple[float | None, float | None]:
        """计算板块PE/PB历史分位

        从InfluxDB查询历史数据，计算当前PE/PB在历史数据中的分位

        Args:
            sector_code: 板块代码
            trade_date: 交易日期，默认今天
            current_pe: 当前PE值（用于避免查询新写入的数据）
            current_pb: 当前PB值

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
        
        if current_pe is not None and current_pe > 0 and len(pe_values) >= 10:
            sorted_pe = sorted(pe_values)
            rank = sum(1 for v in sorted_pe if v < current_pe)
            pe_percentile = rank / len(sorted_pe) * 100
        
        if current_pb is not None and current_pb > 0 and len(pb_values) >= 10:
            sorted_pb = sorted(pb_values)
            rank = sum(1 for v in sorted_pb if v < current_pb)
            pb_percentile = rank / len(sorted_pb) * 100

        return pe_percentile, pb_percentile


# 全局实例
data_collector = DataCollector()
