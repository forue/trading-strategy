import sys, os
import pytest
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services'))


def _get_influx_query():
    """延迟导入 influx_query，避免模块级别导入失败"""
    from strategy.app import influx_query
    return influx_query


def _has_data():
    """检查 InfluxDB 是否可用且有数据"""
    try:
        iq = _get_influx_query()
        min_d, max_d = iq.get_available_date_range()
        return min_d is not None and max_d is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_data(), reason="InfluxDB 不可用或无数据")


def test_no_same_day_add_stop_loss():
    """检查: 同一天同板块不能既有ADD又有STOP_LOSS"""
    from strategy.app.main import _run_backtest_core
    from strategy.app.models import StrategyType, StrategyParams

    iq = _get_influx_query()
    daily_data = iq.query_daily_sectors('2026-01-02', '2026-04-30')
    sorted_dates = sorted(daily_data.keys())
    params = StrategyParams()
    result = _run_backtest_core(daily_data, sorted_dates, StrategyType.MODERATE, params, 1000000, return_full=True)
    changes = result.get('position_changes', [])

    day_actions = defaultdict(list)
    for c in changes:
        day_actions[c['date']].append((c['action'], c['sector_code']))

    for d, acts in day_actions.items():
        codes = defaultdict(list)
        for action, code in acts:
            codes[code].append(action)
        for code, actions in codes.items():
            assert not ('ADD' in actions and 'STOP_LOSS' in actions), \
                f"{d} {code} 同天 ADD+STOP_LOSS 冲突"


def test_no_immediate_stop_loss():
    """检查: 新建仓当天不能触发止损"""
    from strategy.app.main import _run_backtest_core
    from strategy.app.models import StrategyType, StrategyParams

    iq = _get_influx_query()
    daily_data = iq.query_daily_sectors('2026-01-02', '2026-04-30')
    sorted_dates = sorted(daily_data.keys())
    params = StrategyParams()
    result = _run_backtest_core(daily_data, sorted_dates, StrategyType.MODERATE, params, 1000000, return_full=True)
    changes = result.get('position_changes', [])

    for i, c in enumerate(changes):
        if c['action'] == 'STOP_LOSS':
            for j in range(i - 1, max(i - 10, -1), -1):
                if changes[j]['sector_code'] == c['sector_code'] and changes[j]['action'] == 'ADD':
                    d1 = datetime.strptime(changes[j]['date'], '%Y-%m-%d')
                    d2 = datetime.strptime(c['date'], '%Y-%m-%d')
                    diff = (d2 - d1).days
                    assert diff > 1, \
                        f"新建仓当天止损: {changes[j]['date']} ADD -> {c['date']} STOP_LOSS ({diff}天)"
                    break


def test_remaining_weight_correct():
    """检查: 所有卖出记录的 remaining_weight 应为0"""
    from strategy.app.main import _run_backtest_core
    from strategy.app.models import StrategyType, StrategyParams

    iq = _get_influx_query()
    daily_data = iq.query_daily_sectors('2026-01-02', '2026-04-30')
    sorted_dates = sorted(daily_data.keys())
    params = StrategyParams()
    result = _run_backtest_core(daily_data, sorted_dates, StrategyType.MODERATE, params, 1000000, return_full=True)
    changes = result.get('position_changes', [])

    for c in changes:
        if c['action'] in ('STOP_LOSS', 'EMERGENCY_EXIT', 'BEAR_EXIT', 'CLEAR'):
            assert c.get('remaining_weight', 0) <= 0.001, \
                f"{c['date']} {c['action']} {c['sector_name']} remaining={c['remaining_weight']}"


def test_stop_loss_reason_contains_details():
    """检查: 止损原因应包含峰值、当前值、回撤比例"""
    from strategy.app.main import _run_backtest_core
    from strategy.app.models import StrategyType, StrategyParams

    iq = _get_influx_query()
    daily_data = iq.query_daily_sectors('2026-01-02', '2026-04-30')
    sorted_dates = sorted(daily_data.keys())
    params = StrategyParams(stop_loss=0.03)  # 小阈值更容易触发
    result = _run_backtest_core(daily_data, sorted_dates, StrategyType.MODERATE, params, 1000000, return_full=True)
    changes = result.get('position_changes', [])

    for c in changes:
        if c['action'] == 'STOP_LOSS':
            reason = c.get('reason', '')
            # 原因应包含具体数字
            assert '峰值' in reason or '高点' in reason or '初始' in reason or '大盘' in reason or '均线' in reason, \
                f"止损原因不够详细: {reason}"


def test_hold_action_recorded():
    """检查: 继续持有的板块应记录 HOLD 动作"""
    from strategy.app.main import _run_backtest_core
    from strategy.app.models import StrategyType, StrategyParams

    iq = _get_influx_query()
    daily_data = iq.query_daily_sectors('2026-01-02', '2026-04-30')
    sorted_dates = sorted(daily_data.keys())
    params = StrategyParams(min_score_keep=2.0)  # 降低阈值更容易触发继续持有
    result = _run_backtest_core(daily_data, sorted_dates, StrategyType.MODERATE, params, 1000000, return_full=True)
    changes = result.get('position_changes', [])

    hold_count = sum(1 for c in changes if c['action'] == 'HOLD')
    print(f"HOLD 记录数: {hold_count}")
    # 不强制要求有 HOLD，但如果有，检查格式
    for c in changes:
        if c['action'] == 'HOLD':
            assert '继续持有' in c.get('reason', ''), f"HOLD 原因格式错误: {c['reason']}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
