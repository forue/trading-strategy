"""策略工坊：用户自定义策略的持久化、版本、分享复制与运行记录

与现有三档策略的关系：工坊策略绑定一个场景（AGGRESSIVE/MODERATE/CONSERVATIVE），
风控参数映射为 StrategyParams 覆盖项后交给既有回测/信号引擎执行；触发条件与执行动作
在信号层逐条生效（过滤信号、调整仓位/方向）。这样编辑器里的配置不是装饰性元数据。

数据库沿用 strategy 服务的自愈建表方式（无迁移框架），与 scripts/init-db.sql 保持一致。
"""
from datetime import datetime
from typing import Any, Optional

import psycopg2
from loguru import logger
from psycopg2.extras import Json, RealDictCursor
from pydantic import BaseModel, Field

from .config import settings
from .models import StrategyParams, StrategyType

CONDITION_FIELDS = {
    "score", "position_ratio", "rank", "direction", "sector_code", "sector_name",
    "index_change_pct", "main_net_inflow", "turnover", "pe_percentile", "pb_percentile",
}
# 信号本身不带板块行情/估值指标，实际环境运行时从当日板块快照按 sector_code 注入这些字段
SNAPSHOT_FIELDS = ("index_change_pct", "main_net_inflow", "turnover", "pe_percentile", "pb_percentile")
CONDITION_OPS = {"gt", "gte", "lt", "lte", "eq", "contains"}
ACTION_TYPES = {"set_position_ratio", "force_direction", "exclude_sector", "include_only_sector"}
RISK_KEYS = {
    "stop_loss", "trailing_stop_loss", "max_drawdown_stop", "max_position",
    "min_score_threshold", "top_n", "hold_days", "capital_pct",
}
# 风控参数 → StrategyParams 字段名（同名，集中列出以便校验与前端展示保持一致）
PARAM_KEYS = {
    "stop_loss": (float, 0.0, 1.0),
    "trailing_stop_loss": (float, 0.0, 1.0),
    "max_drawdown_stop": (float, 0.0, 1.0),
    "max_position": (float, 0.0, 1.0),
    "min_score_threshold": (float, 0.0, 100.0),
    "top_n": (int, 1, 20),
    "hold_days": (int, 1, 120),
    "capital_pct": (float, 0.0, 1.0),
}

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS user_strategies (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id),
        name VARCHAR(80) NOT NULL,
        scenario VARCHAR(20) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        condition_logic VARCHAR(4) NOT NULL DEFAULT 'AND',
        conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
        actions JSONB NOT NULL DEFAULT '[]'::jsonb,
        risk JSONB NOT NULL DEFAULT '{}'::jsonb,
        is_public BOOLEAN NOT NULL DEFAULT FALSE,
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        version INT NOT NULL DEFAULT 1,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    # 老库已建表时补列（与 CREATE TABLE 保持同一默认值）
    "ALTER TABLE user_strategies ADD COLUMN IF NOT EXISTS condition_logic VARCHAR(4) NOT NULL DEFAULT 'AND'",
    "CREATE INDEX IF NOT EXISTS idx_user_strategies_user ON user_strategies(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_strategies_public ON user_strategies(is_public) WHERE is_public",
    """
    CREATE TABLE IF NOT EXISTS user_strategy_versions (
        id BIGSERIAL PRIMARY KEY,
        strategy_id BIGINT NOT NULL REFERENCES user_strategies(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL,
        version INT NOT NULL,
        snapshot JSONB NOT NULL,
        change_note VARCHAR(200) NOT NULL DEFAULT '',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(strategy_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_strategy_runs (
        id BIGSERIAL PRIMARY KEY,
        strategy_id BIGINT NOT NULL REFERENCES user_strategies(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL,
        mode VARCHAR(16) NOT NULL,
        status VARCHAR(20) NOT NULL,
        result JSONB,
        error TEXT,
        started_at TIMESTAMP NOT NULL DEFAULT NOW(),
        finished_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_user_strategy_runs_user ON user_strategy_runs(user_id, started_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS user_workshop_algorithms (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id),
        name VARCHAR(80) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_workshop_algorithms_user ON user_workshop_algorithms(user_id)",
    """
    CREATE TABLE IF NOT EXISTS user_strategy_likes (
        id BIGSERIAL PRIMARY KEY,
        strategy_id BIGINT NOT NULL REFERENCES user_strategies(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(id),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(strategy_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_strategy_likes_strategy ON user_strategy_likes(strategy_id)",
]

# 系统内置算法：一键插入到触发条件列表，字段全部在 CONDITION_FIELDS 白名单内
BUILTIN_ALGORITHMS = [
    {"id": "strong_momentum", "name": "强势动量", "description": "当日涨幅≥2% 且评分≥5",
     "conditions": [{"field": "index_change_pct", "op": "gte", "value": 2},
                    {"field": "score", "op": "gte", "value": 5}]},
    {"id": "top_rank", "name": "头部板块", "description": "板块排名在前 3",
     "conditions": [{"field": "rank", "op": "lte", "value": 3}]},
    {"id": "capital_inflow", "name": "主力资金流入", "description": "主力净流入≥5000万元",
     "conditions": [{"field": "main_net_inflow", "op": "gte", "value": 50000000}]},
    {"id": "low_valuation", "name": "低估值分位", "description": "PE 分位≤40",
     "conditions": [{"field": "pe_percentile", "op": "lte", "value": 40}]},
    {"id": "active_turnover", "name": "高活跃度", "description": "换手率≥2%",
     "conditions": [{"field": "turnover", "op": "gte", "value": 2}]},
    {"id": "heavy_position", "name": "重仓信号", "description": "建议仓位≥30%",
     "conditions": [{"field": "position_ratio", "op": "gte", "value": 0.3}]},
    {"id": "sell_only", "name": "仅卖出信号", "description": "只保留 SELL 方向的信号",
     "conditions": [{"field": "direction", "op": "eq", "value": "SELL"}]},
    {"id": "quality_pick", "name": "优质精选", "description": "评分≥6 且排名前 2",
     "conditions": [{"field": "score", "op": "gte", "value": 6},
                    {"field": "rank", "op": "lte", "value": 2}]},
]


def ensure_schema() -> None:
    """幂等建表：全新库未跑 init-db.sql 时也能自愈（与 signal_tracker 同款机制）"""
    conn = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            for ddl in _DDL:
                cur.execute(ddl)
        conn.commit()
    except Exception as e:
        logger.error(f"策略工坊建表失败: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def _connect():
    return psycopg2.connect(
        host=settings.postgres_host,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        connect_timeout=5,
    )


class Condition(BaseModel):
    field: str
    op: str
    value: Any


class Action(BaseModel):
    type: str
    value: Any = None


class StrategyPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scenario: StrategyType
    description: str = Field(default="", max_length=500)
    # 多条件组合方式：AND 全部满足 / OR 任一满足（算法并行插入时避免互相抵消）
    condition_logic: str = "AND"
    conditions: list[Condition] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    risk: dict[str, Any] = Field(default_factory=dict)
    is_public: bool = False
    status: str = "draft"


class ApplyRequest(BaseModel):
    # simulation=历史回测；live=当日策略计算（沿用既有 signal.generated 链路）
    mode: str = "simulation"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: float = 1000000.0


class AlgorithmPayload(BaseModel):
    """用户自建算法：一组可复用的触发条件，跨策略插入使用"""
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    conditions: list[Condition] = Field(default_factory=list)


def purge_user_rows(user_id: int) -> int:
    """账号删除前清理：versions/runs 由 strategy_id 外键级联删除"""
    conn = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_strategy_likes WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM user_strategies WHERE user_id = %s", (user_id,))
            removed = cur.rowcount
            cur.execute("DELETE FROM user_workshop_algorithms WHERE user_id = %s", (user_id,))
        conn.commit()
        return removed
    finally:
        if conn:
            conn.close()


def _validate_conditions(conditions: list[Condition]) -> None:
    for c in conditions:
        if c.field not in CONDITION_FIELDS:
            raise ValueError(f"不支持的条件字段: {c.field}")
        if c.op not in CONDITION_OPS:
            raise ValueError(f"不支持的条件运算符: {c.op}")
        if c.value is None or c.value == "":
            raise ValueError("条件值不能为空")


def _validate(payload: StrategyPayload) -> None:
    if payload.status not in {"draft", "active", "paused"}:
        raise ValueError("status 仅支持 draft/active/paused")
    if payload.condition_logic not in {"AND", "OR"}:
        raise ValueError("条件组合方式仅支持 AND/OR")
    _validate_conditions(payload.conditions)
    for a in payload.actions:
        if a.type not in ACTION_TYPES:
            raise ValueError(f"不支持的执行动作: {a.type}")
        if a.value is None or a.value == "":
            raise ValueError("执行动作值不能为空")
        if a.type == "set_position_ratio":
            _number(a.value, 0.0, 1.0, "仓位比例")
        elif a.type == "force_direction" and str(a.value).upper() not in {"BUY", "SELL"}:
            raise ValueError("方向只能是 BUY 或 SELL")
    for key, value in payload.risk.items():
        if key not in RISK_KEYS:
            raise ValueError(f"不支持的风控参数: {key}")
        cls, low, high = PARAM_KEYS[key]
        _number(value, low, high, key)


def _number(value: Any, low: float, high: float, label: str):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} 必须是数字")
    if number < low or number > high:
        raise ValueError(f"{label} 必须在 {low}~{high} 之间")
    return number


def _payload_from_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "scenario": row["scenario"],
        "description": row["description"],
        "condition_logic": row.get("condition_logic") or "AND",
        "conditions": row["conditions"] or [],
        "actions": row["actions"] or [],
        "risk": row["risk"] or {},
        "is_public": row["is_public"],
        "status": row["status"],
        "version": row["version"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


_JSON_FIELDS = ("conditions", "actions", "risk")


def _json(value: Any):
    return Json(value)


def list_strategies(user_id: int, scope: str = "mine") -> list[dict]:
    """scope=mine 自己的；public 公开广场（含自己公开的策略，公开后作者自己也要能看到）"""
    where, where_params = {
        "mine": ("WHERE s.user_id = %s", (user_id,)),
        "public": ("WHERE s.is_public = TRUE", ()),
    }[scope]
    order = "like_count DESC, s.updated_at DESC" if scope == "public" else "s.updated_at DESC"
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""SELECT s.*, u.username AS owner_name,
                    (SELECT count(*) FROM user_strategy_runs r WHERE r.strategy_id = s.id) AS run_count,
                    (SELECT count(*) FROM user_strategy_versions v WHERE v.strategy_id = s.id) AS version_count,
                    (SELECT count(*) FROM user_strategy_likes l WHERE l.strategy_id = s.id) AS like_count,
                    EXISTS(SELECT 1 FROM user_strategy_likes l
                           WHERE l.strategy_id = s.id AND l.user_id = %s) AS liked_by_me
                    FROM user_strategies s JOIN users u ON u.id = s.user_id
                    {where} ORDER BY {order}""",
                (user_id,) + where_params,
            )
            rows = cur.fetchall()
        items = []
        for row in rows:
            item = _payload_from_row(row)
            item["owner_name"] = row["owner_name"]
            item["is_owner"] = row["user_id"] == user_id
            item["run_count"] = row["run_count"]
            item["version_count"] = row["version_count"]
            item["like_count"] = row["like_count"]
            item["liked_by_me"] = row["liked_by_me"]
            items.append(item)
        return items
    finally:
        if conn:
            conn.close()


def get_strategy(user_id: int, strategy_id: int, public_only: bool = False) -> Optional[dict]:
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT s.*, u.username AS owner_name FROM user_strategies s
                   JOIN users u ON u.id = s.user_id WHERE s.id = %s"""
                + (" AND s.is_public = TRUE" if public_only else " AND s.user_id = %s"),
                (strategy_id,) if public_only else (strategy_id, user_id),
            )
            row = cur.fetchone()
        return _payload_from_row(row) | {"owner_name": row["owner_name"]} if row else None
    finally:
        if conn:
            conn.close()


def _snapshot(payload: StrategyPayload) -> dict:
    return {
        "name": payload.name,
        "scenario": payload.scenario.value,
        "description": payload.description,
        "condition_logic": payload.condition_logic,
        "conditions": [c.model_dump() for c in payload.conditions],
        "actions": [a.model_dump() for a in payload.actions],
        "risk": payload.risk,
    }


def _content_snapshot(row: dict) -> dict:
    return {
        "name": row["name"], "scenario": row["scenario"], "description": row["description"],
        "condition_logic": row.get("condition_logic") or "AND",
        "conditions": row["conditions"], "actions": row["actions"], "risk": row["risk"],
    }


def create_strategy(user_id: int, payload: StrategyPayload) -> dict:
    _validate(payload)
    snap = _snapshot(payload)
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO user_strategies
                   (user_id, name, scenario, description, condition_logic, conditions, actions, risk, is_public, status, version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1) RETURNING *""",
                (user_id, payload.name, payload.scenario.value, payload.description,
                 payload.condition_logic, _json(snap["conditions"]), _json(snap["actions"]),
                 _json(snap["risk"]), payload.is_public, payload.status),
            )
            row = cur.fetchone()
            cur.execute(
                """INSERT INTO user_strategy_versions (strategy_id, user_id, version, snapshot, change_note)
                   VALUES (%s,%s,1,%s,%s)""",
                (row["id"], user_id, _json(snap), "创建策略"),
            )
        conn.commit()
        return _payload_from_row(row)
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def update_strategy(user_id: int, strategy_id: int, payload: StrategyPayload, change_note: str = "") -> Optional[dict]:
    """内容变化才升版本；仅改发布状态/启停不产生新版本"""
    _validate(payload)
    snap = _snapshot(payload)
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM user_strategies WHERE id = %s AND user_id = %s FOR UPDATE",
                        (strategy_id, user_id))
            row = cur.fetchone()
            if not row:
                return None
            old_snapshot = _content_snapshot(row)
            changed = old_snapshot != {k: snap[k] for k in old_snapshot}
            version = row["version"] + (1 if changed else 0)
            cur.execute(
                """UPDATE user_strategies SET name=%s, scenario=%s, description=%s, condition_logic=%s, conditions=%s,
                   actions=%s, risk=%s, is_public=%s, status=%s, version=%s, updated_at=NOW()
                   WHERE id=%s AND user_id=%s RETURNING *""",
                (payload.name, payload.scenario.value, payload.description, payload.condition_logic,
                 _json(snap["conditions"]), _json(snap["actions"]), _json(snap["risk"]),
                 payload.is_public, payload.status, version, strategy_id, user_id),
            )
            updated = cur.fetchone()
            if changed:
                cur.execute(
                    """INSERT INTO user_strategy_versions (strategy_id, user_id, version, snapshot, change_note)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (strategy_id, user_id, version, _json(snap), (change_note or "修改策略")[:200]),
                )
        conn.commit()
        return _payload_from_row(updated)
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def delete_strategy(user_id: int, strategy_id: int) -> bool:
    conn = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_strategies WHERE id=%s AND user_id=%s", (strategy_id, user_id))
            removed = cur.rowcount > 0
        conn.commit()
        return removed
    finally:
        if conn:
            conn.close()


def list_versions(user_id: int, strategy_id: int) -> list[dict]:
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT v.version, v.change_note, v.created_at, v.snapshot
                   FROM user_strategy_versions v
                   JOIN user_strategies s ON s.id = v.strategy_id
                   WHERE v.strategy_id = %s AND s.user_id = %s ORDER BY v.version DESC""",
                (strategy_id, user_id),
            )
            return [
                {"version": r["version"], "change_note": r["change_note"],
                 "created_at": r["created_at"].isoformat(), "snapshot": r["snapshot"]}
                for r in cur.fetchall()
            ]
    finally:
        if conn:
            conn.close()


def fork_strategy(user_id: int, strategy_id: int) -> Optional[dict]:
    source = get_strategy(user_id, strategy_id, public_only=True)
    if not source:
        return None
    if source["user_id"] == user_id:
        raise ValueError("自己的策略已在「我的策略」中，无需复制")
    payload = StrategyPayload(
        name=f"{source['name'][:70]}（副本）", scenario=source["scenario"],
        description=source["description"], condition_logic=source.get("condition_logic") or "AND",
        conditions=source["conditions"],
        actions=source["actions"], risk=source["risk"], is_public=False, status="draft",
    )
    return create_strategy(user_id, payload)


def params_from_strategy(strategy: dict) -> StrategyParams:
    """风控参数 → 引擎参数；未配置的风控项沿用用户已有策略配置（由 _merge_backtest_params 合并）"""
    overrides = {}
    for key, value in (strategy.get("risk") or {}).items():
        if key in PARAM_KEYS:
            cls, _, _ = PARAM_KEYS[key]
            overrides[key] = cls(value)
    return StrategyParams(**overrides)


def _match(condition: dict, signal: dict) -> bool:
    actual = signal.get(condition["field"])
    expected = condition["value"]
    if condition["op"] == "contains":
        return expected in str(actual or "")
    if condition["op"] == "eq" and isinstance(expected, str) and isinstance(actual, str):
        return actual == expected
    if actual is None:
        return False
    try:
        left, right = float(actual), float(expected)
    except (TypeError, ValueError):
        return False
    return {
        "gt": left > right, "gte": left >= right, "lt": left < right,
        "lte": left <= right, "eq": left == right,
    }[condition["op"]]


def apply_rules(signals: list[dict], strategy: dict) -> tuple[list[dict], dict]:
    """把触发条件/执行动作真正作用到引擎产生的信号上，返回采纳信号与过程统计"""
    conditions = strategy.get("conditions") or []
    if not conditions:
        accepted = [dict(s) for s in signals]
    elif (strategy.get("condition_logic") or "AND").upper() == "OR":
        accepted = [dict(s) for s in signals if any(_match(c, s) for c in conditions)]
    else:
        accepted = [dict(s) for s in signals if all(_match(c, s) for c in conditions)]
    filtered = len(signals) - len(accepted)
    adjustments = []
    for action in strategy.get("actions") or []:
        kind, value = action.get("type"), action.get("value")
        before = len(accepted)
        if kind == "set_position_ratio":
            cap = _number(value, 0.0, 1.0, "仓位比例")
            for s in accepted:
                if float(s.get("position_ratio") or 0) > cap:
                    s["position_ratio"] = cap
                    adjustments.append(f"{s.get('sector_name')} 仓位压至 {cap:.0%}")
        elif kind == "force_direction":
            for s in accepted:
                s["direction"] = str(value).upper()
        elif kind == "exclude_sector":
            accepted = [s for s in accepted if value not in str(s.get("sector_name") or "")]
        elif kind == "include_only_sector":
            accepted = [s for s in accepted if value == s.get("sector_name")]
        if before != len(accepted):
            adjustments.append(f"{kind} 过滤 {before - len(accepted)} 条")
    max_position = (strategy.get("risk") or {}).get("max_position")
    if max_position is not None:
        cap = _number(max_position, 0.0, 1.0, "最大仓位")
        for s in accepted:
            if float(s.get("position_ratio") or 0) > cap:
                s["position_ratio"] = cap
    stats = {"generated": len(signals), "filtered": filtered,
             "accepted": len(accepted), "adjustments": adjustments}
    return accepted, stats


def save_run(user_id: int, strategy_id: int, mode: str, status: str,
             result: Optional[dict] = None, error: Optional[str] = None,
             started_at: Optional[str] = None) -> dict:
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO user_strategy_runs
                   (strategy_id, user_id, mode, status, result, error, started_at, finished_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,NOW()) RETURNING *""",
                (strategy_id, user_id, mode, status, _json(result) if result is not None else None,
                 (error or None), started_at or datetime.now(),
                 ),
            )
            row = cur.fetchone()
        conn.commit()
        return _run_from_row(row)
    finally:
        if conn:
            conn.close()


def _run_from_row(row: dict) -> dict:
    return {
        "id": row["id"], "strategy_id": row["strategy_id"], "mode": row["mode"],
        "status": row["status"], "result": row["result"], "error": row["error"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
    }


def list_runs(user_id: int, strategy_id: Optional[int] = None, limit: int = 50) -> list[dict]:
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if strategy_id:
                cur.execute(
                    """SELECT * FROM user_strategy_runs WHERE user_id=%s AND strategy_id=%s
                       ORDER BY started_at DESC LIMIT %s""",
                    (user_id, strategy_id, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM user_strategy_runs WHERE user_id=%s ORDER BY started_at DESC LIMIT %s",
                    (user_id, limit),
                )
            return [_run_from_row(r) for r in cur.fetchall()]
    finally:
        if conn:
            conn.close()


def get_run(user_id: int, run_id: int) -> Optional[dict]:
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM user_strategy_runs WHERE id=%s AND user_id=%s", (run_id, user_id))
            row = cur.fetchone()
        return _run_from_row(row) if row else None
    finally:
        if conn:
            conn.close()


def _algorithm_from_row(row: dict) -> dict:
    return {
        "id": row["id"], "user_id": row["user_id"], "name": row["name"],
        "description": row["description"], "conditions": row["conditions"] or [],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def list_algorithms(user_id: int) -> list[dict]:
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM user_workshop_algorithms WHERE user_id=%s ORDER BY updated_at DESC", (user_id,))
            return [_algorithm_from_row(r) for r in cur.fetchall()]
    finally:
        if conn:
            conn.close()


def create_algorithm(user_id: int, payload: AlgorithmPayload) -> dict:
    _validate_conditions(payload.conditions)
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO user_workshop_algorithms (user_id, name, description, conditions)
                   VALUES (%s,%s,%s,%s) RETURNING *""",
                (user_id, payload.name, payload.description,
                 _json([c.model_dump() for c in payload.conditions])),
            )
            row = cur.fetchone()
        conn.commit()
        return _algorithm_from_row(row)
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def update_algorithm(user_id: int, algorithm_id: int, payload: AlgorithmPayload) -> Optional[dict]:
    _validate_conditions(payload.conditions)
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """UPDATE user_workshop_algorithms SET name=%s, description=%s, conditions=%s, updated_at=NOW()
                   WHERE id=%s AND user_id=%s RETURNING *""",
                (payload.name, payload.description,
                 _json([c.model_dump() for c in payload.conditions]), algorithm_id, user_id),
            )
            row = cur.fetchone()
        conn.commit()
        return _algorithm_from_row(row) if row else None
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def delete_algorithm(user_id: int, algorithm_id: int) -> bool:
    conn = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_workshop_algorithms WHERE id=%s AND user_id=%s",
                        (algorithm_id, user_id))
            removed = cur.rowcount > 0
        conn.commit()
        return removed
    finally:
        if conn:
            conn.close()


def like_state(user_id: int, strategy_id: int) -> dict:
    conn = None
    try:
        conn = _connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT (SELECT count(*) FROM user_strategy_likes WHERE strategy_id=%s) AS like_count,
                   EXISTS(SELECT 1 FROM user_strategy_likes
                          WHERE strategy_id=%s AND user_id=%s) AS liked_by_me""",
                (strategy_id, strategy_id, user_id),
            )
            row = cur.fetchone()
        return {"like_count": row["like_count"], "liked_by_me": row["liked_by_me"]}
    finally:
        if conn:
            conn.close()


def like_strategy(user_id: int, strategy_id: int) -> dict:
    """幂等：UNIQUE(strategy_id, user_id) + ON CONFLICT DO NOTHING，同一账号只计一次"""
    conn = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_strategy_likes (strategy_id, user_id) VALUES (%s,%s)
                   ON CONFLICT (strategy_id, user_id) DO NOTHING""",
                (strategy_id, user_id),
            )
        conn.commit()
        return like_state(user_id, strategy_id)
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def unlike_strategy(user_id: int, strategy_id: int) -> dict:
    conn = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_strategy_likes WHERE strategy_id=%s AND user_id=%s",
                        (strategy_id, user_id))
        conn.commit()
        return like_state(user_id, strategy_id)
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
