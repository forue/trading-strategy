"""数据采集服务 - AkShare数据采集器（同花顺数据源）"""
import os
import re
import sys
import requests
import akshare as ak
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from loguru import logger

# 引入共享库（services/shared）：板块→ETF 映射的唯一来源，与 strategy 共用同一份，
# 避免两边映射漂移导致「策略用到的 ETF 采集不到收盘价」
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.sector_etf_map import (
    SECTOR_MAP,
    SECTOR_ETF_MAP,
    SECTOR_ETF_CANDIDATES,
    all_etf_codes,
    default_etf,
)

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

    # 可交易性判定：最近交易日距今超过该天数即视为退市/长期停牌
    TRADABLE_MAX_STALE_DAYS = 10

    # 申万宏源「指数分析」接口（akshare index_analysis_daily_sw 的上游）
    # akshare 把 page_size 写死为 50：回填 1 年需 200+ 次请求（容器内约 4.5s/次，约 20 分钟），
    # 该接口实际支持自定义 page_size，改大后请求数降到个位数，故这里自行翻页。
    _SW_ANALYSIS_URL = "https://www.swsresearch.com/institute-sw/api/index_analysis/index_analysis_report/"
    _SW_ANALYSIS_PAGE_SIZE = 5000
    _SW_ANALYSIS_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }

    # 同花顺板块 → 申万行业 估值映射。
    # stock_board_industry_summary_ths() 不返回市盈率/市净率，同花顺亦无行业估值接口，
    # 故板块估值统一取申万宏源「指数分析」口径（ak.index_analysis_daily_sw）：
    #   1) 板块名与申万二级行业同名（90 个板块中 66 个）→ 直接匹配
    #   2) 申万一级行业同名（钢铁/建筑材料/建筑装饰/房地产/银行/美容护理）→ 回退一级
    #   3) 其余 18 个板块在此显式映射，一对多时按 Σ流通市值/Σ(流通市值/估值) 调和平均合成
    #
    # 重要：当日值与历史序列必须同源（同为 index_analysis_daily_sw），估值分位才有可比性。
    # 乐咕乐股的 sw_index_second_info/first_info 虽为申万行业口径，但统计方法不同
    # （同日农林牧渔 PE 83.73 vs 33.25、钢铁 30.55 vs 20.34），混用会使分位失真，已弃用。
    _THS_TO_SW_INDUSTRY = {
        "种植业与林业": ["种植业", "林业Ⅱ"],
        "煤炭开采加工": ["煤炭开采", "焦炭Ⅱ"],
        "油气开采及服务": ["油气开采Ⅱ", "油服工程"],
        "汽车整车": ["乘用车", "商用车"],
        "汽车服务及其他": ["汽车服务", "摩托车及其他"],
        "饮料制造": ["白酒Ⅱ", "非白酒", "饮料乳品"],
        "食品加工制造": ["食品加工", "休闲食品", "调味发酵品Ⅱ"],
        "港口航运": ["航运港口"],
        "公路铁路运输": ["铁路公路"],
        "机场航运": ["航空机场"],
        "零售": ["一般零售", "专业连锁Ⅱ", "旅游零售Ⅱ"],
        "旅游及酒店": ["酒店餐饮", "旅游及景区"],
        "文化传媒": ["出版", "广告营销", "数字媒体", "电视广播Ⅱ"],
        "军工装备": ["航天装备Ⅱ", "航空装备Ⅱ", "地面兵装Ⅱ", "航海装备Ⅱ"],
        "其他社会服务": ["专业服务", "体育Ⅱ"],
        "石油加工贸易": ["炼化及贸易"],
        "塑料制品": ["塑料"],
        "橡胶制品": ["橡胶"],
    }

    def _get_etf_code_by_name(self, sector_name: str) -> str | None:
        etf = default_etf(sector_name)
        return etf["code"] if etf else None

    def _get_etf_name_by_name(self, sector_name: str) -> str | None:
        etf = default_etf(sector_name)
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

    @staticmethod
    def _norm_sw_name(name) -> str:
        """归一化申万行业名（去掉 Ⅱ/Ⅲ 后缀与空白），用于与同花顺板块名同名匹配"""
        return re.sub(r"[ⅡⅢ]", "", str(name)).strip()

    @staticmethod
    def _parse_optional_float(val) -> float | None:
        """解析可空数值字段（同花顺用 "--" 表示缺失）"""
        text = str(val).strip()
        if not text or text == "--" or text.lower() == "nan":
            return None
        try:
            return float(text)
        except (ValueError, TypeError):
            return None

    def _fetch_sw_analysis(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
        """拉取申万宏源「指数分析」数据（symbol: 二级行业/一级行业）

        该接口是系统唯一同时覆盖「当日值」与「历史序列」的申万估值来源
        （市盈率/市净率/流通市值），自行按大分页翻页以避免 akshare 每页 50 条的低效。
        取不到数据时返回 None，由调用方保持估值空缺，不编造数值。
        """
        params = {
            "page": 1,
            "page_size": self._SW_ANALYSIS_PAGE_SIZE,
            "index_type": symbol,
            "start_date": f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}",
            "end_date": f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}",
            "type": "DAY",
            "swindexcode": "all",
        }
        frames: list[pd.DataFrame] = []
        total_num = None
        try:
            page = 1
            while True:
                params["page"] = page
                resp = requests.get(
                    self._SW_ANALYSIS_URL, params=params,
                    headers=self._SW_ANALYSIS_HEADERS, verify=False, timeout=120,
                )
                payload = resp.json().get("data") or {}
                rows = payload.get("results") or []
                if total_num is None:
                    total_num = int(payload.get("count") or 0)
                if not rows:
                    break
                frames.append(pd.DataFrame(rows))
                if sum(len(f) for f in frames) >= total_num:
                    break
                page += 1
        except Exception as e:
            logger.warning(f"获取申万{symbol}分析数据失败({start_date}~{end_date}): {e}")
            return None

        if not frames:
            return None
        df = pd.concat(frames, ignore_index=True).rename(columns={
            "swindexname": "指数名称",
            "bargaindate": "发布日期",
            "pe": "市盈率",
            "pb": "市净率",
            "negotiablessharesum1": "流通市值",
        })
        for col in ("市盈率", "市净率", "流通市值"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        logger.info(f"申万{symbol}分析数据获取成功: {len(df)} 行（{start_date}~{end_date}）")
        return df

    def _sw_valuation_by_date(
        self, df: pd.DataFrame | None, end_date: str = None
    ) -> dict[str, dict[str, tuple]]:
        """把申万分析数据整理为 {发布日期: {归一化行业名: (pe, pb, 流通市值)}}

        仅保留 PE/PB 均为正的行业（亏损行业 PE 无意义，写入会污染估值分位）。
        end_date 给定时只保留 <= end_date 的记录。
        """
        out: dict[str, dict[str, tuple]] = {}
        if df is None or df.empty:
            return out
        for _, row in df.iterrows():
            d = str(row.get("发布日期", ""))[:10].replace("-", "")
            if len(d) != 8 or not d.isdigit():
                continue
            if end_date and d > end_date:
                continue
            name = self._norm_sw_name(row.get("指数名称", ""))
            pe = self._safe_float(row.get("市盈率"), 0)
            pb = self._safe_float(row.get("市净率"), 0)
            cap = self._safe_float(row.get("流通市值"), 0)
            if name and pe > 0 and pb > 0:
                out.setdefault(d, {})[name] = (pe, pb, cap)
        return out

    def fetch_sw_industry_valuation(self, trade_date: str) -> tuple[dict[str, tuple], dict[str, tuple]]:
        """采集指定交易日的申万行业估值，返回 (二级, 一级) 两张 {行业名: (pe, pb, 流通市值)}

        与历史回填同用申万宏源「指数分析」接口，保证当日值与历史序列口径一致。
        取 [trade_date-7, trade_date] 窗口内每个行业最近一期的数据，
        以容忍申万当日数据发布延迟；窗口内无数据的行业保持空缺。
        """
        trade_date = trade_date.replace("-", "")
        start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d")

        def _latest_table(symbol: str) -> dict[str, tuple]:
            by_date = self._sw_valuation_by_date(
                self._fetch_sw_analysis(symbol, start_date, trade_date), end_date=trade_date
            )
            table: dict[str, tuple] = {}
            for d in sorted(by_date):
                table.update(by_date[d])  # 日期升序覆盖 → 保留最近一期
            return table

        sw_second = _latest_table("二级行业")
        sw_first = _latest_table("一级行业")
        return sw_second, sw_first

    def backfill_sector_valuation_history(self, days: int = 365) -> dict:
        """用申万行业历史估值回填板块 PE/PB 序列，使估值分位可立即生成

        估值分位需 >=10 个交易日样本，逐日积累需等待两周以上。此方法一次性拉取
        申万宏源历史估值（与当日采集同源），按板块解析后写入 InfluxDB，回填后
        立即可算出分位。

        Args:
            days: 回溯自然日数，默认 365 天（与估值分位的 1 年回溯窗口对齐）
        Returns:
            {start, end, dates, sectors, covered_sectors, records}
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        second_by_date = self._sw_valuation_by_date(
            self._fetch_sw_analysis("二级行业", start_date, end_date)
        )
        first_by_date = self._sw_valuation_by_date(
            self._fetch_sw_analysis("一级行业", start_date, end_date)
        )
        all_dates = sorted(set(second_by_date) | set(first_by_date))
        if not all_dates:
            logger.warning(f"申万历史估值回填失败：{start_date}~{end_date} 未取到数据")
            return {"start": start_date, "end": end_date, "dates": 0, "sectors": 0, "records": 0}

        sector_map = self._get_sector_name_code_map()
        records: list[dict] = []
        covered_sectors: set[str] = set()
        for sector_name, code in sector_map.items():
            sector_code = f"THS{code}" if code else f"THS_{sector_name}"
            for d in all_dates:
                pe, pb = self.resolve_sector_valuation(
                    sector_name, second_by_date.get(d, {}), first_by_date.get(d, {})
                )
                if pe is None or pb is None:
                    continue
                covered_sectors.add(sector_name)
                records.append({
                    "sector_code": sector_code,
                    "sector_name": sector_name,
                    "date": d,
                    "pe_ttm": pe,
                    "pb": pb,
                })

        # 同步重算分位：历史日期不会再被当日采集覆盖，只回填 PE/PB 的话，
        # 切换口径前残留的 pe_percentile/pb_percentile 会一直失真，
        # 回测与复盘页据此做保守档估值筛选时结论相反。
        # 口径与 calculate_sector_valuation_percentile 一致：严格小于当前值的
        # 样本占比，样本不足 10 个交易日时不写入。
        by_code: dict[str, list[dict]] = {}
        for r in records:
            by_code.setdefault(r["sector_code"], []).append(r)

        for rows in by_code.values():
            pe_series = sorted(x["pe_ttm"] for x in rows if x["pe_ttm"] and x["pe_ttm"] > 0)
            pb_series = sorted(x["pb"] for x in rows if x["pb"] and x["pb"] > 0)
            for r in rows:
                if len(pe_series) >= 10:
                    r["pe_percentile"] = (
                        sum(1 for v in pe_series if v < r["pe_ttm"]) / len(pe_series) * 100
                    )
                if len(pb_series) >= 10:
                    r["pb_percentile"] = (
                        sum(1 for v in pb_series if v < r["pb"]) / len(pb_series) * 100
                    )

        # 只写估值字段，InfluxDB 按同 measurement+tags+时间戳做字段合并，不会覆盖已采行情
        for i in range(0, len(records), 5000):
            influx_manager.write_sector_capital_flow(records[i:i + 5000])

        uncovered = sorted(set(sector_map) - covered_sectors)
        summary = {
            "start": start_date,
            "end": end_date,
            "dates": len(all_dates),
            "sectors": len(sector_map),
            "covered_sectors": len(covered_sectors),
            "records": len(records),
        }
        if uncovered:
            logger.warning(f"未匹配到申万估值、未回填的板块({len(uncovered)}): {uncovered}")
        logger.info(f"申万历史估值回填完成: {summary}")
        return summary

    def resolve_sector_valuation(
        self, sector_name: str, sw_second: dict[str, tuple], sw_first: dict[str, tuple]
    ) -> tuple[float | None, float | None]:
        """按同花顺板块名解析板块 PE/PB（申万行业口径），一对多时按市值加权调和平均合成

        取不到时返回 (None, None)，由调用方保持空缺，不编造数值。
        """
        key = self._norm_sw_name(sector_name)
        if key in sw_second:
            matched = [sw_second[key]]
        elif sector_name in self._THS_TO_SW_INDUSTRY:
            matched = []
            for name in self._THS_TO_SW_INDUSTRY[sector_name]:
                nk = self._norm_sw_name(name)
                if nk in sw_second:
                    matched.append(sw_second[nk])
                elif nk in sw_first:
                    matched.append(sw_first[nk])
        elif key in sw_first:
            matched = [sw_first[key]]
        else:
            return None, None

        if not matched:
            return None, None

        # 组合板块的估值必须按 Σ流通市值 / Σ(流通市值/估值) 合成（市值加权调和平均）。
        # 不能对子行业估值做市值加权算术平均：市值占比高但盈利占比极低的子行业会把
        # 整体估值拉飞——「种植业与林业」由 种植业(PE 54.58/市值 846.84亿) 与
        # 林业(PE 3673.6/市值 165.97亿) 组成，算术平均得 647.63，调和平均得 65.09。
        # 用申万官方一级行业值反验：调和平均平均偏差 0.9%（多个行业精确复现），
        # 算术平均偏差 28.6%（农林牧渔 官方 83.73 vs 算术 251.44）。
        def _combine(idx: int) -> float:
            weighted = [(m[idx], m[2]) for m in matched if m[2] > 0]
            total_cap = sum(cap for _, cap in weighted)
            if weighted and total_cap > 0:
                return total_cap / sum(cap / val for val, cap in weighted)
            # 无流通市值时退化为简单平均
            return sum(m[idx] for m in matched) / len(matched)

        return round(_combine(0), 2), round(_combine(1), 2)

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
        """判断是否为交易日

        优先用交易日历，若缓存未覆盖目标月份则回退到周末判断。
        """
        trade_dates = self.get_trade_dates()
        date_compact = date_str.replace("-", "")
        if trade_dates:
            if date_compact in trade_dates:
                return True
            # 缓存中没找到，检查缓存是否覆盖了目标月份（未覆盖则不可信）
            target_month = date_compact[:6]
            month_covered = any(d.startswith(target_month) for d in trade_dates)
            if month_covered:
                return False  # 缓存覆盖了该月但没这个日期 → 确认为非交易日
            # 缓存未覆盖目标月份，不可信，回退到周末判断
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
                # 同花顺行业汇总不返回市盈率/市净率，估值统一取申万宏源口径（每轮仅采集一次）
                sw_second, sw_first = self.fetch_sw_industry_valuation(trade_date)
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
                    # 估值：优先用同花顺自带字段（当前版本为空），否则回退申万行业估值
                    pe_ttm = self._parse_optional_float(row.get("市盈率"))
                    pb = self._parse_optional_float(row.get("市净率"))
                    if pe_ttm is None or pb is None:
                        sw_pe, sw_pb = self.resolve_sector_valuation(sector_name, sw_second, sw_first)
                        pe_ttm = sw_pe if pe_ttm is None else pe_ttm
                        pb = sw_pb if pb is None else pb

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
                covered = [item for item in results if item["pe_ttm"] is not None and item["pb"] is not None]
                logger.info(
                    f"同花顺行业汇总采集成功: {len(results)} 个板块，"
                    f"估值覆盖 {len(covered)} 个（来源：申万宏源行业 市盈率/市净率）"
                )
                if len(covered) < len(results):
                    missing = [item["sector_name"] for item in results if item["pe_ttm"] is None]
                    logger.warning(f"未匹配到申万行业估值的板块({len(missing)}): {missing}")
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
                    # 前收 × (1+当日涨跌幅) = 当日收盘，与K线回填口径保持一致
                    # （index_close 语义为"当日收盘指数"，下游因子/前端/记账均按当日收盘使用）
                    chg = self._safe_float(item.get("index_change_pct", 0))
                    item["index_close"] = round(close_price * (1 + chg / 100.0), 3)
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

    def check_etf_tradable(self, etf_code: str) -> dict:
        """校验 ETF 是否可交易：能否取到最近交易日的收盘价

        Returns:
            {code, tradable, reason, last_date, close}
        """
        try:
            df = ak.fund_etf_hist_sina(symbol=self._sina_etf_symbol(etf_code))
        except Exception as e:
            return {"code": etf_code, "tradable": False,
                    "reason": f"{type(e).__name__}: {str(e)[:80]}"}
        if df is None or df.empty or "date" not in df.columns:
            return {"code": etf_code, "tradable": False, "reason": "行情接口无数据"}
        last = df.iloc[-1]
        try:
            close = float(last["close"])
        except (TypeError, ValueError):
            return {"code": etf_code, "tradable": False, "reason": "收盘价解析失败"}

        # 新鲜度：仅「能取到收盘价」不够——退市/长期停牌的标的会残留历史数据
        # （实测 159999 最后交易日停留在 2023-03-10 却被判为可取价），
        # 故要求最近交易日距今天数在阈值内。
        last_date = str(last["date"])
        try:
            stale_days = (datetime.now().date()
                          - datetime.strptime(last_date[:10], "%Y-%m-%d").date()).days
        except (ValueError, TypeError):
            stale_days = 0
        fresh = stale_days <= self.TRADABLE_MAX_STALE_DAYS

        return {
            "code": etf_code,
            "tradable": close > 0 and fresh,
            "reason": None if (close > 0 and fresh)
                      else f"最近交易日 {last_date} 距今 {stale_days} 天，疑似退市或长期停牌",
            "last_date": last_date,
            "close": close,
            "stale_days": stale_days,
        }

    @staticmethod
    def _sina_etf_symbol(etf_code: str) -> str:
        """新浪 ETF 日线的代码格式：沪市 sh 前缀、深市 sz 前缀"""
        return ("sh" if etf_code.startswith("5") else "sz") + etf_code

    def collect_etf_quotes(self, trade_date: str = None, codes: list = None) -> list[dict]:
        """采集板块对应 ETF 的收盘价（measurement: etf_quote）

        持仓盯市需要「可交易标的(ETF)」的价格，而不是板块指数点位。ETF 代码取自共享映射
        services/shared/sector_etf_map.py —— 与 strategy 共用同一份，杜绝两边漂移。

        数据源：新浪 ETF 日线（ak.fund_etf_hist_sina），按代码逐只拉取指定交易日的收盘价。
        东方财富的 fund_etf_spot_em / fund_etf_hist_em 实测稳定返回 ConnectionError
        （远端直接关闭连接）而不可用，故改用新浪日线；取不到价的 ETF 一律计入 missing
        并告警，绝不回退到「用上一交易日价格顶替」。

        Args:
            trade_date: 交易日 YYYY-MM-DD 或 YYYYMMDD，默认今天；当日无数据即视为缺失
            codes: 指定 ETF 代码列表（按持仓需求驱动采集）；为空则采集映射全集
        Returns:
            [{etf_code, etf_name, sector_name, date, close}, ...]
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")
        if len(trade_date) == 8:
            trade_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"

        targets = [str(c).strip() for c in codes] if codes else sorted(all_etf_codes())

        # 代码 → {etf_name, sector_name}，用于落库标注（取映射中首个匹配）
        meta_of: dict[str, dict] = {}
        for sector_name, cands in SECTOR_ETF_CANDIDATES.items():
            for c in cands:
                meta_of.setdefault(c["code"], {"etf_name": c["name"], "sector_name": sector_name})
        for code, etf in SECTOR_ETF_MAP.items():
            meta_of.setdefault(etf["code"],
                               {"etf_name": etf["name"], "sector_name": SECTOR_MAP.get(code, "")})

        def fetch(code: str):
            try:
                df = ak.fund_etf_hist_sina(symbol=self._sina_etf_symbol(code))
                if df is None or df.empty:
                    return code, None, "返回空数据"
                # 兼容 date 列为 Timestamp 的情况，统一截取前 10 位比较
                day = df[df["date"].astype(str).str.slice(0, 10) == trade_date]
                if day.empty:
                    return code, None, "当日无数据"
                close = float(day.iloc[-1]["close"])
                if close <= 0:
                    return code, None, "价格非正"
                return code, close, None
            except Exception as e:
                return code, None, f"{type(e).__name__}: {str(e)[:60]}"

        results, missing = [], []
        # 全集 76 只若串行约 20s，用线程池并发压到数秒
        with ThreadPoolExecutor(max_workers=8) as pool:
            for code, close, err in pool.map(fetch, targets):
                if close is None:
                    missing.append(code)
                    logger.debug(f"ETF {code} 收盘价获取失败: {err}")
                    continue
                meta = meta_of.get(code, {"etf_name": "", "sector_name": ""})
                results.append({
                    "etf_code": code,
                    "etf_name": meta["etf_name"],
                    "sector_name": meta["sector_name"],
                    "date": trade_date,
                    "close": close,
                })

        if results:
            influx_manager.write_etf_quotes(results)
        if missing:
            logger.warning(f"ETF 收盘价缺失 {len(missing)}/{len(targets)} 只: {missing}")
        logger.info(f"采集 ETF 收盘价 {len(results)} 条（交易日 {trade_date}，目标 {len(targets)} 只）")
        return results

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

    def collect_market_index_kline(
        self,
        index_code: str = "sh000001",
        start_date: str = None,
        end_date: str = None,
    ) -> list[dict]:
        """采集大盘指数日K（默认上证指数），写入 InfluxDB market_kline

        Args:
            index_code: AkShare 指数代码，如 sh000001 / sz399300
            start_date: YYYYMMDD 或 YYYY-MM-DD
            end_date: YYYYMMDD 或 YYYY-MM-DD
        """
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        start_norm = start_date.replace("-", "")[:8]
        end_norm = end_date.replace("-", "")[:8]
        name_map = {
            "sh000001": "上证指数",
            "sz399001": "深证成指",
            "sz399300": "沪深300",
            "sh000300": "沪深300",
        }
        index_name = name_map.get(index_code, index_code)
        results = []
        df = None
        # 优先东方财富，失败回退新浪
        for func_name in ["stock_zh_index_daily_em", "stock_zh_index_daily"]:
            try:
                func = getattr(ak, func_name)
                df = func(symbol=index_code)
                if df is not None and not df.empty:
                    logger.info(f"大盘指数 {index_code} 使用 {func_name} 获取成功")
                    break
            except Exception as e:
                logger.debug(f"大盘指数 {func_name} 失败: {e}")
                df = None
        if df is None or df.empty:
            logger.warning(f"大盘指数 {index_code} 所有数据源均失败")
            return []

        try:
            # 东方财富日线常见列为 date / open / close / high / low / volume
            date_col = "date" if "date" in df.columns else ("日期" if "日期" in df.columns else None)
            close_col = "close" if "close" in df.columns else ("收盘" if "收盘" in df.columns else None)
            if not date_col or not close_col:
                logger.warning(f"大盘指数列名无法识别: {list(df.columns)}")
                return []
            df = df.copy()
            df["_date"] = df[date_col].astype(str).str[:10].str.replace("-", "")
            df = df[(df["_date"] >= start_norm) & (df["_date"] <= end_norm)]
            df = df.sort_values("_date")
            prev_close = None
            for _, row in df.iterrows():
                close = self._safe_float(row.get(close_col, 0))
                open_ = self._safe_float(row.get("open", row.get("开盘", close)))
                high = self._safe_float(row.get("high", row.get("最高", close)))
                low = self._safe_float(row.get("low", row.get("最低", close)))
                volume = self._safe_float(row.get("volume", row.get("成交量", 0)))
                change_pct = None
                if "涨跌幅" in df.columns:
                    change_pct = self._safe_float(row.get("涨跌幅"))
                if change_pct is None and prev_close and prev_close > 0:
                    change_pct = (close - prev_close) / prev_close * 100
                d8 = str(row["_date"])
                d_iso = f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}" if len(d8) == 8 else str(row[date_col])[:10]
                results.append({
                    "index_code": index_code,
                    "index_name": index_name,
                    "date": d_iso,
                    "open": open_,
                    "close": close,
                    "high": high,
                    "low": low,
                    "volume": volume,
                    "change_pct": round(change_pct, 4) if change_pct is not None else 0.0,
                })
                if close:
                    prev_close = close
            if results:
                influx_manager.write_market_kline(results)
                logger.info(f"采集大盘K线 {index_name}: {len(results)} 条")
        except Exception as e:
            logger.warning(f"采集大盘K线失败 {index_code}: {e}")
        return results

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
            # 注意：2024-08-19 起沪深港通已停止披露北向资金成交净买额，该列恒为 0，
            # 采集值不具备分析价值（保留写入仅为维持历史序列连续）
            north_sh = self._safe_float(df.iloc[0, 5])
            north_sz = self._safe_float(df.iloc[2, 5]) if len(df) >= 3 else 0.0
            net_inflow = (north_sh + north_sz) * 1e8  # 亿元 → 元

            results = [{"date": date_str, "north_net_inflow": net_inflow}]

            influx_manager.write_north_bound_flow(results)
            if net_inflow == 0:
                logger.warning(
                    f"北向资金采集完成: 日期={date_str}, 净流入=0.00亿"
                    f"（数据源已停止披露北向净买额，该指标不可用于分析）"
                )
            else:
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

    def backfill_sector_fund_flow_hist(self, start_date: str = "20240101", end_date: str = None) -> dict:
        """回填历史板块资金流数据

        由于 akshare 的 stock_sector_fund_flow_hist() 底层调用 push2.eastmoney.com
        获取板块代码映射时被封，本方法改为:
        1. 从 data.eastmoney.com 网页抓取 EM 板块代码映射
        2. 直接调用 push2his.eastmoney.com 数据接口
        3. 解析主力净流入并写入 InfluxDB

        Returns:
            {"count": 写入条数, "success": 成功板块数, "failed": 失败板块数,
             "total_sectors": 待回填板块数, "aborted": 是否因连续失败提前终止}
        """
        import time as _time

        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        sector_names = self.get_sector_names()
        if not sector_names:
            logger.warning("无可用板块名称，跳过资金流回填")
            return {"count": 0, "success": 0, "failed": 0, "total_sectors": 0, "aborted": False}

        # 提前获取 EM 代码映射
        em_map = self._get_em_code_map()
        if not em_map:
            logger.warning("无法获取东方财富板块代码映射，跳过回填")
            return {"count": 0, "success": 0, "failed": 0, "total_sectors": 0, "aborted": False}

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
            return {"count": 0, "success": 0, "failed": 0, "total_sectors": 0, "aborted": False}

        logger.info(f"开始回填 {len(name_to_em)} 个板块的历史资金流 ({start_date}~{end_date})（串行模式，间隔2秒）")

        all_records: list[dict] = []
        failed: list[str] = []
        attempted = 0
        consecutive_failures = 0
        aborted = False
        retry_times = 3
        max_consecutive_failures = 5  # 连续失败过多说明已被数据源限流/封禁，提前终止避免加重封禁

        for idx, (name, em_code) in enumerate(name_to_em.items()):
            attempted += 1
            ths_code = self._get_sector_name_code_map().get(name, "")
            klines = None
            for attempt in range(retry_times):
                try:
                    klines = self._fetch_em_fund_flow_klines(em_code)
                    if klines:
                        break
                    raise ValueError("接口返回空 klines")
                except Exception as e:
                    if attempt < retry_times - 1:
                        backoff = 3 * (attempt + 1)
                        logger.debug(
                            f"回填 {name}({em_code}) 第{attempt + 1}次请求失败: {e}，{backoff}s 后重试"
                        )
                        _time.sleep(backoff)
                    else:
                        logger.warning(f"回填 {name}({em_code}) 失败(已重试{retry_times}次): {e}")

            if not klines:
                failed.append(name)
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    logger.error(
                        f"资金流回填提前终止: 连续 {consecutive_failures} 个板块请求失败，"
                        f"疑似数据源限流/封禁；已尝试 {attempted}/{len(name_to_em)} 个"
                        f"（成功 {attempted - len(failed)} 个），"
                        f"剩余 {len(name_to_em) - attempted} 个板块待下次重试"
                    )
                    aborted = True
                    break
            else:
                consecutive_failures = 0
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

            # 每个请求间隔 2 秒，避免触发反爬
            if idx < len(name_to_em) - 1:
                _time.sleep(2)

        if all_records:
            merged = self._merge_with_existing_data(all_records)
            influx_manager.write_sector_capital_flow(merged)
            logger.info(f"资金流回填完成: {len(merged)} 条记录, 失败板块: {len(failed)}")
        else:
            logger.warning("资金流回填: 无数据写入")

        return {
            "count": len(all_records),
            "success": attempted - len(failed),
            "failed": len(failed),
            "total_sectors": len(name_to_em),
            "aborted": aborted,
        }

    def _fetch_em_fund_flow_klines(self, em_code: str) -> list[str]:
        """获取东方财富板块资金流日K线原始 klines 列表（push2his 接口）

        说明：该接口存在反爬，容器出网 IP 被限流时会返回 RemoteDisconnected，
        调用方需配合重试与熔断。
        """
        import requests as req

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
        return r.json().get("data", {}).get("klines") or []

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
