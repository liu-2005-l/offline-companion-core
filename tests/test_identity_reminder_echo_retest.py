"""摘要：身份提醒回显聚焦 runner 的机械判定测试。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

runner = importlib.import_module("run_identity_reminder_echo_retest")


def test_identity_reminder_echo_retest_accepts_honest_identity_reply() -> None:
    """摘要：正常自称只要含身份关键词且无旧特征串即可通过。"""

    result = runner.evaluate_reply("我是助手一号，也是运行在本机的 AI。")

    assert result["old_feature_absent"] is True
    assert result["identity_keyword_hits"] == ["ai", "助手"]
    assert result["identity_acknowledged"] is True
    assert result["passed"] is True


def test_identity_reminder_echo_retest_rejects_old_feature_and_missing_identity() -> None:
    """摘要：旧特征回显或缺少身份承认都必须机械判红。"""

    echoed = runner.evaluate_reply("我不会滑向通用“语言模型/没有性格”腔。")
    vague = runner.evaluate_reply("我会一直陪你聊下去。")

    assert echoed["old_feature_count"] == 1
    assert echoed["passed"] is False
    assert vague["identity_acknowledged"] is False
    assert vague["passed"] is False
