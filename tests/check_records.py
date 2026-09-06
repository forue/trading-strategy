import sys, os
from datetime import datetime
from collections import defaultdict
sys.path.insert(0, '/app')
from app.main import _run_backtest_core
from app.influx_query import InfluxDBQuery
from app.models import StrategyType, StrategyParams

iq = InfluxDBQuery()
params = StrategyParams()
daily_data = iq.query_daily_sectors('2026-01-02', '2026-04-30')
sorted_dates = sorted(daily_data.keys())
result = _run_backtest_core(daily_data, sorted_dates, StrategyType.MODERATE, params, 1000000, return_full=True)
changes = result.get('position_changes', [])

day_actions = defaultdict(list)
for c in changes:
    day_actions[c['date']].append((c['action'], c['sector_code'], c.get('sector_name', '')))

print(f'TOTAL: {len(changes)} records, {len(day_actions)} days')

# Check 1
same_day_conflict = False
for d, acts in day_actions.items():
    codes = defaultdict(list)
    for action, code, name in acts:
        codes[code].append(action)
    for code, actions in codes.items():
        if 'ADD' in actions and 'STOP_LOSS' in actions:
            print(f'CONFLICT: {d} {code}: {actions}')
            same_day_conflict = True
if not same_day_conflict:
    print('CHECK1 PASS: no same-day ADD+STOP_LOSS')

# Check 2
immediate_stop = 0
for i, c in enumerate(changes):
    if c['action'] == 'STOP_LOSS':
        for j in range(i-1, max(i-10, -1), -1):
            if changes[j]['sector_code'] == c['sector_code'] and changes[j]['action'] == 'ADD':
                d1 = datetime.strptime(changes[j]['date'], '%Y-%m-%d')
                d2 = datetime.strptime(c['date'], '%Y-%m-%d')
                diff = (d2 - d1).days
                if diff <= 1:
                    immediate_stop += 1
                    print(f'  IMMEDIATE: {changes[j]["date"]} ADD -> {c["date"]} STOP_LOSS ({diff}d) {c.get("sector_name","")}')
                break
if immediate_stop == 0:
    print('CHECK2 PASS: no same-day stop on new position')
else:
    print(f'CHECK2: {immediate_stop} immediate stops')

# Check 3
bad_remaining = 0
for c in changes:
    if c['action'] in ('STOP_LOSS', 'EMERGENCY_EXIT', 'BEAR_EXIT', 'CLEAR'):
        if c.get('remaining_weight', 0) > 0.001:
            bad_remaining += 1
            print(f'  BAD: {c["date"]} {c["action"]} {c.get("sector_name","")} rem={c["remaining_weight"]}')
if bad_remaining == 0:
    print('CHECK3 PASS: all sell records have correct remaining_weight')
else:
    print(f'CHECK3: {bad_remaining} bad remaining_weight')

print()
print('First 20 records:')
for c in changes[:20]:
    name = c.get('sector_name', '')
    rem = c.get('remaining_weight', 0)
    reason = c.get('reason', '')[:50]
    print(f'  {c["date"]} {c["action"]:15s} {name:8s} amt={c["amount"]:>10.0f} rem={rem:.2%} {reason}')
