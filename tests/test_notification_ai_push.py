"""推送通道 AI 分析段落回归测试

覆盖：钉钉/企业微信推送必须携带 AI 解读，供用户决策参考。
"""
import os
import sys
import importlib.util

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "services"))

# 服务目录名含连字符，无法作为包导入，按文件路径加载
_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "services", "signal-notification", "app", "notify_channels.py",
)
_spec = importlib.util.spec_from_file_location("notify_channels", _MODULE_PATH)
notify_channels = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(notify_channels)


def _sample_analysis() -> dict:
    return {
        "sector_name": "银行",
        "sector_code": "THS881155",
        "direction": "SELL",
        "confidence": 0.72,
        "interpretation": "市场普跌，资金转为净流出，建议规避。",
        "risk_factors": ["市场宽度不足", "资金持续流出"],
        "suggestion": "清仓观望",
        "model": "deepseek-chat",
    }


def test_ai_section_contains_key_fields():
    """AI 段落需包含板块、方向、信心度、解读、风险、建议"""
    text = "".join(notify_channels._build_ai_section([_sample_analysis()]))

    assert "AI 解读" in text
    assert "银行" in text
    assert "卖出" in text
    assert "72%" in text
    assert "市场普跌" in text
    assert "风险" in text and "市场宽度不足" in text
    assert "清仓观望" in text
    assert "deepseek-chat" in text


def test_ai_section_empty_when_no_analysis():
    """无 AI 解读时不产生多余段落"""
    assert notify_channels._build_ai_section(None) == []
    assert notify_channels._build_ai_section([]) == []


def test_ai_section_truncates_long_content():
    """超长解读需截断，避免破坏 Markdown 排版"""
    analysis = _sample_analysis()
    analysis["interpretation"] = "很长的解读" * 100
    text = "".join(notify_channels._build_ai_section([analysis]))

    assert "..." in text
    assert len(text) < 1000


def test_push_signal_accepts_empty_signals():
    """空仓（无买卖信号）同样需要推送，以便用户知晓当前状态"""
    import inspect

    sig = inspect.signature(notify_channels.NotifyChannelManager.push_signal)
    assert "ai_analyses" in sig.parameters


def test_do_push_passes_ai_analyses_as_keyword():
    """回归：signal 服务 `_do_push` 必须以关键字传递 ai_analyses。

    `push_signal(signals, strategy_type, signal_date, is_test=False, ai_analyses=None)`
    若按位置传递第 4 个参数会绑定到 `is_test`，导致 AI 解读永远不进入推送消息，
    且被误判为测试消息。
    """
    import ast

    src_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "services", "signal-notification", "app", "main.py",
    )
    with open(src_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_do_push":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "push_signal":
                    calls.append(sub)

    assert calls, "未找到 _do_push 中对 push_signal 的调用"
    for call in calls:
        kw_names = {kw.arg for kw in call.keywords}
        assert "ai_analyses" in kw_names, "push_signal 调用必须用关键字传递 ai_analyses"
