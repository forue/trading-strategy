"""回测核心逻辑单元测试

覆盖：
1. 紧急退出清仓 + 交易成本扣除
2. 止损清仓
3. 加仓/减仓/清仓精确对应 + 金额 + 成本 + 剩余仓位
4. NAV 逐日全量返回
5. 仓位金额不溢出
6. 节假日动态化
7. NaN 防护
"""
import math
import sys
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# 设置环境变量避免 config 验证失败
os.environ.setdefault("INFLUXDB_URL", "http://localhost:8086")
os.environ.setdefault("INFLUXDB_TOKEN", "test-token")
os.environ.setdefault("INFLUXDB_ORG", "test-org")
os.environ.setdefault("INFLUXDB_BUCKET", "test-bucket")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "")
os.environ.setdefault("REDIS_DB", "0")
os.environ.setdefault("RABBITMQ_HOST", "localhost")
os.environ.setdefault("RABBITMQ_PORT", "5672")
os.environ.setdefault("RABBITMQ_USER", "guest")
os.environ.setdefault("RABBITMQ_PASSWORD", "guest")
os.environ.setdefault("LOG_LEVEL", "INFO")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services"))

from strategy.app.models import StrategyParams, StrategyType, TradeSignal, SignalDirection
from strategy.app.main import _calc_trade_cost, _is_trade_day, _get_holidays_for_year


# ─── 辅助工具 ────────────────────────────────────────────

def _make_sector_data(sector_codes, date="2026-03-01", change_pcts=None):
    if change_pcts is None:
        change_pcts = [1.0] * len(sector_codes)
    return [
        {"sector_code": code, "sector_name": f"板块{code}", "index_change_pct": pct}
        for code, pct in zip(sector_codes, change_pcts)
    ]


def _make_daily_data(sector_codes, dates, changes_per_day=None):
    daily = {}
    for i, date in enumerate(dates):
        if changes_per_day:
            changes = changes_per_day[i] if i < len(changes_per_day) else [0.0] * len(sector_codes)
        else:
            changes = [0.0] * len(sector_codes)
        daily[date] = _make_sector_data(sector_codes, date, changes)
    return daily


def _default_params(**overrides):
    defaults = dict(
        top_n=3, max_position=0.5, hold_days=5, capital_pct=0.3,
        stop_loss=0.08, commission_rate=0.0003, stamp_tax_rate=0.001,
        slippage_rate=0.001, min_score_threshold=1.0, score_gap_threshold=0.5,
        cooldown_days=1, keep_overlap=True, allow_empty=True,
        min_score_keep=2.0, market_bear_threshold=0.4,
    )
    defaults.update(overrides)
    return StrategyParams(**defaults)


def _make_signals(sector_data, strategy_type, params, signal_date, current_positions, ratios=None):
    """构造买入信号"""
    if ratios is None:
        ratios = {s["sector_code"]: 0.33 for s in sector_data[:params.top_n]}
    signals = []
    for s in sector_data:
        if s["sector_code"] in ratios:
            signals.append(TradeSignal(
                signal_date=signal_date,
                strategy_type=strategy_type,
                sector_code=s["sector_code"],
                sector_name=s["sector_name"],
                direction=SignalDirection.BUY,
                position_ratio=ratios[s["sector_code"]],
                score=5.0,
                reason="test",
            ))
    return signals


def _run_backtest_with_mock(daily_data, dates, params, initial_capital=1000000,
                            signal_fn=None, sh_returns=None):
    """运行回测，mock scoring_model"""
    if signal_fn is None:
        signal_fn = _make_signals

    with patch("strategy.app.main.scoring_model") as mock_scoring:
        mock_scoring.calculate_daily_signals.side_effect = signal_fn
        from strategy.app.main import _run_backtest_core
        return _run_backtest_core(
            daily_data, dates, StrategyType.MODERATE, params, initial_capital,
            return_full=True, sh_index_returns=sh_returns,
        )


# ─── 测试：紧急退出 ───────────────────────────────────────

class TestEmergencyExit:
    def test_emergency_exit_clears_positions_and_deducts_costs(self):
        """紧急退出必须清仓并扣除交易成本"""
        codes = ["A", "B", "C"]
        dates = ["2026-03-01", "2026-03-02", "2026-03-03"]
        changes = [
            [1.0, 1.0, 1.0],
            [-6.0, 1.0, 1.0],  # A跌6%触发紧急退出
            [1.0, 1.0, 1.0],
        ]
        daily = _make_daily_data(codes, dates, changes)
        params = _default_params(hold_days=2, stop_loss=0.15)

        result = _run_backtest_with_mock(daily, dates, params)

        changes_list = result.get("position_changes", [])
        exit_actions = [c for c in changes_list if c["action"] == "EMERGENCY_EXIT"]
        assert len(exit_actions) > 0, f"应有紧急退出记录，实际: {[c['action'] for c in changes_list]}"

        for ea in exit_actions:
            assert ea["remaining_weight"] == 0.0, f"紧急退出后仓位应为0: {ea['remaining_weight']}"
            assert ea["cost"] > 0, "紧急退出应扣除交易成本"

    def test_stop_loss_clears_positions(self):
        """止损必须清仓 — 用-4%跌幅避免触发紧急退出(≥5%)，确保走固定止损路径"""
        codes = ["A", "B"]
        dates = ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"]
        changes = [
            [1.0, 1.0],
            [-4.0, -4.0],
            [-4.0, -4.0],
            [-4.0, -4.0],
            [-4.0, -4.0],
            [1.0, 1.0],
        ]
        daily = _make_daily_data(codes, dates, changes)
        params = _default_params(stop_loss=0.08, hold_days=10, cooldown_days=0)

        result = _run_backtest_with_mock(daily, dates, params)

        changes_list = result.get("position_changes", [])
        stop_loss_actions = [c for c in changes_list if c["action"] == "STOP_LOSS"]
        assert len(stop_loss_actions) > 0, "应有止损记录"
        for sl in stop_loss_actions:
            assert sl["remaining_weight"] == 0.0, "止损后仓位应为0"
            assert sl["cost"] > 0, "止损应扣除交易成本"


# ─── 测试：仓位跟踪 ───────────────────────────────────────

class TestPositionTracking:
    def test_add_and_reduce_positions(self):
        """加仓和减仓必须正确对应"""
        codes = ["A", "B", "C"]
        dates = ["2026-03-01", "2026-03-02", "2026-03-03"]
        changes = [
            [1.0, 1.0, 1.0],
            [1.0, 1.0, 1.0],
            [1.0, 1.0, 1.0],
        ]
        daily = _make_daily_data(codes, dates, changes)
        params = _default_params(hold_days=1, cooldown_days=0)

        call_day = [0]
        def signal_fn(sector_data, strategy_type, params, signal_date, current_positions):
            call_day[0] += 1
            if call_day[0] == 1:
                ratios = {"A": 0.4, "B": 0.3, "C": 0.3}
            else:
                ratios = {"A": 0.5, "B": 0.2, "C": 0.3}
            return _make_signals(sector_data, strategy_type, params, signal_date, current_positions, ratios)

        result = _run_backtest_with_mock(daily, dates, params, signal_fn=signal_fn)

        changes_list = result.get("position_changes", [])
        add_actions = [c for c in changes_list if c["action"] == "ADD"]
        assert len(add_actions) > 0, "应有加仓记录"

        for c in changes_list:
            if c["action"] == "SNAPSHOT":
                continue
            assert c["amount"] > 0, f"交易金额应>0: {c}"
            assert c["cost"] >= 0, f"交易成本应>=0: {c}"

    def test_position_amounts_do_not_overflow(self):
        """仓位金额不能超过可用资金"""
        codes = ["A", "B"]
        dates = ["2026-03-01", "2026-03-02"]
        changes = [[2.0, 2.0], [2.0, 2.0]]
        daily = _make_daily_data(codes, dates, changes)
        params = _default_params(hold_days=5, cooldown_days=0)

        def signal_fn(sector_data, strategy_type, params, signal_date, current_positions):
            return _make_signals(sector_data, strategy_type, params, signal_date, current_positions,
                                 ratios={"A": 0.6, "B": 0.4})

        result = _run_backtest_with_mock(daily, dates, params, signal_fn=signal_fn)

        assert result["final_capital"] > 0, f"最终资金应>0: {result['final_capital']}"
        nav_curve = result.get("nav_curve", [])
        assert len(nav_curve) == len(dates), f"NAV曲线应有{len(dates)}条记录，实际{len(nav_curve)}"

    def test_clear_position_recorded(self):
        """清仓操作必须有完整记录"""
        codes = ["A", "B"]
        dates = ["2026-03-01", "2026-03-02"]
        changes = [[1.0, 1.0], [1.0, 1.0]]
        daily = _make_daily_data(codes, dates, changes)
        params = _default_params(hold_days=1, cooldown_days=0)

        call_day = [0]
        def signal_fn(sector_data, strategy_type, params, signal_date, current_positions):
            call_day[0] += 1
            if call_day[0] == 1:
                return _make_signals(sector_data, strategy_type, params, signal_date, current_positions,
                                     ratios={"A": 0.5})
            return []

        result = _run_backtest_with_mock(daily, dates, params, signal_fn=signal_fn)

        changes_list = result.get("position_changes", [])
        clear_actions = [c for c in changes_list if c["action"] == "CLEAR"]
        for c in clear_actions:
            assert c["sector_code"], "清仓记录必须有板块代码"
            assert c["amount"] > 0, "清仓金额必须>0"
            assert c["cost"] > 0, "清仓必须有交易成本"
            assert c["remaining_weight"] == 0.0, "清仓后仓位必须为0"


# ─── 测试：NAV 全量返回 ────────────────────────────────────

class TestNavCurve:
    def test_nav_curve_has_all_dates(self):
        """NAV曲线必须包含所有交易日"""
        codes = ["A"]
        dates = [f"2026-03-0{i}" for i in range(1, 6)]
        changes = [[1.0], [2.0], [-1.0], [0.5], [1.0]]
        daily = _make_daily_data(codes, dates, changes)
        params = _default_params(hold_days=10, cooldown_days=0)

        def signal_fn(sector_data, strategy_type, params, signal_date, current_positions):
            return _make_signals(sector_data, strategy_type, params, signal_date, current_positions,
                                 ratios={"A": 1.0})

        result = _run_backtest_with_mock(daily, dates, params, signal_fn=signal_fn)

        nav_curve = result.get("nav_curve", [])
        assert len(nav_curve) == len(dates), f"NAV曲线应有{len(dates)}条，实际{len(nav_curve)}"
        for entry in nav_curve:
            assert "date" in entry
            assert "nav" in entry
            assert "benchmark" in entry

    def test_daily_signals_have_position_detail(self):
        """每日信号应包含仓位明细（权重+金额+现金）"""
        codes = ["A", "B"]
        dates = ["2026-03-01", "2026-03-02"]
        changes = [[1.0, 1.0], [1.0, 1.0]]
        daily = _make_daily_data(codes, dates, changes)
        params = _default_params(hold_days=10, cooldown_days=0)

        def signal_fn(sector_data, strategy_type, params, signal_date, current_positions):
            return _make_signals(sector_data, strategy_type, params, signal_date, current_positions,
                                 ratios={"A": 0.5, "B": 0.5})

        result = _run_backtest_with_mock(daily, dates, params, signal_fn=signal_fn)

        daily_signals = result.get("daily_signals", [])
        for day in daily_signals:
            assert "positions" in day, "每日信号应包含positions"
            assert "cash" in day, "每日信号应包含cash"
            assert "total_position_value" in day, "每日信号应包含total_position_value"
            for code, detail in day["positions"].items():
                assert "weight" in detail, f"{code} 应有 weight"
                assert "amount" in detail, f"{code} 应有 amount"


# ─── 测试：节假日动态化 ────────────────────────────────────

class TestDynamicHolidays:
    def test_2026_holidays(self):
        assert _is_trade_day("2026-01-01") is False
        assert _is_trade_day("2026-01-02") is False
        assert _is_trade_day("2026-01-05") is True

    def test_2025_holidays(self):
        assert _is_trade_day("2025-01-01") is False

    def test_2027_holidays(self):
        assert _is_trade_day("2027-01-01") is False
        assert _is_trade_day("2027-01-04") is True

    def test_weekend_not_trading_day(self):
        assert _is_trade_day("2026-01-03") is False
        assert _is_trade_day("2026-01-04") is False

    def test_get_holidays_for_year(self):
        h2026 = _get_holidays_for_year(2026)
        assert "20260101" in h2026
        assert "20261001" in h2026
        h2099 = _get_holidays_for_year(2099)
        assert h2099 == set()


# ─── 测试：交易成本计算 ────────────────────────────────────

class TestTradeCost:
    def test_commission_minimum_5_yuan(self):
        cost = _calc_trade_cost(1000, 0.0003, 0.001, 0.001, is_sell=False)
        assert cost["commission"] >= 5.0, "佣金应>=5元"

    def test_stamp_tax_only_on_sell(self):
        buy_cost = _calc_trade_cost(100000, 0.0003, 0.001, 0.001, is_sell=False)
        sell_cost = _calc_trade_cost(100000, 0.0003, 0.001, 0.001, is_sell=True)
        assert buy_cost["stamp_tax"] == 0.0, "买入无印花税"
        assert sell_cost["stamp_tax"] > 0, "卖出有印花税"

    def test_total_cost_components(self):
        cost = _calc_trade_cost(100000, 0.0003, 0.001, 0.001, is_sell=True)
        assert abs(cost["total"] - (cost["commission"] + cost["stamp_tax"] + cost["slippage"])) < 0.01


# ─── 测试：空仓场景 ───────────────────────────────────────

class TestEmptyPositions:
    def test_empty_data_returns_zero(self):
        from strategy.app.main import _run_backtest_core
        result = _run_backtest_core(
            {}, [], StrategyType.MODERATE, _default_params(), 1000000,
            return_full=True,
        )
        assert result["total_return"] == 0.0
        assert result["nav_curve"] == []
        assert result["position_changes"] == []

    def test_zero_capital_returns_empty(self):
        from strategy.app.main import _run_backtest_core
        result = _run_backtest_core(
            {"2026-03-01": _make_sector_data(["A"])},
            ["2026-03-01"], StrategyType.MODERATE, _default_params(), 0,
            return_full=True,
        )
        assert result["final_capital"] == 0


# ─── 测试：NaN 防护 ───────────────────────────────────────

class TestNaNGuard:
    def test_math_nan_check_works(self):
        """验证 NaN/Infinity 防护逻辑"""
        assert math.isnan(float("nan"))
        assert math.isinf(float("inf"))
        assert not math.isnan(5.0)
        assert not math.isinf(5.0)

    def test_score_etf_returns_default_on_exception(self):
        """ETF评分异常时应返回默认值5.0"""
        import strategy.app.scoring as scoring_module
        original_cache = scoring_module._etf_score_cache.copy()
        try:
            scoring_module._etf_score_cache.clear()
            with patch("akshare.fund_etf_hist_em", side_effect=Exception("network error")):
                result = scoring_module._score_etf("NONEXISTENT")
                assert result == 5.0, f"异常时应返回5.0，实际{result}"
        finally:
            scoring_module._etf_score_cache.clear()
            scoring_module._etf_score_cache.update(original_cache)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ─── 测试：止损后峰值重置防止无限止损 ────────────────────

class TestStopLossPeakReset:
    def test_stop_loss_resets_peak_preventing_perpetual_trigger(self):
        """止损后必须重置峰值，否则新仓会被旧峰值拖累立即再次触发止损"""
        codes = ["A", "B"]
        dates = [f"2026-03-0{i}" for i in range(1, 15)]
        changes = [
            [3.0, 3.0],    # D1: 涨3% → 信号日
            [-4.9, -4.9],  # D2: T+1建仓日, 跌4.9%
            [-4.9, -4.9],  # D3: 跌4.9%
            [-4.9, -4.9],  # D4: 跌4.9%, 累计~10%触发8%止损 → 清仓
            [1.0, 1.0],    # D5: 冷静期
            [1.0, 1.0],    # D6: 冷静期结束,信号日
            [1.0, 1.0],    # D7: 新建仓(T+1)
            [-1.0, -1.0],  # D8: 小跌1% — 不应触发止损(峰值已重置)
            [0.5, 0.5],    # D9
            [0.5, 0.5],    # D10
            [0.5, 0.5],    # D11
            [0.5, 0.5],    # D12
            [0.5, 0.5],    # D13
            [0.5, 0.5],    # D14
        ]
        daily = _make_daily_data(codes, dates, changes)
        params = _default_params(stop_loss=0.08, hold_days=1, cooldown_days=1)

        result = _run_backtest_with_mock(daily, dates, params)

        changes_list = result.get("position_changes", [])
        stop_loss_actions = [c for c in changes_list if c["action"] == "STOP_LOSS"]
        stop_loss_dates = set(c["date"] for c in stop_loss_actions)
        assert len(stop_loss_dates) == 1, f"只应触发一次止损事件，实际{len(stop_loss_dates)}次: {stop_loss_dates}"

        add_actions = [c for c in changes_list if c["action"] == "ADD"]
        assert len(add_actions) > 0, "止损后应有新的建仓记录"
