"""consent_feedback：Consent 拒绝后的自然语言反馈。"""

from __future__ import annotations

from typing import Any

CONSENT_DECLINED_MESSAGE = "好的，那我不做这个了。"


def consent_decision_payload(payload: dict[str, Any], *, allowed: bool) -> dict[str, Any]:
    """摘要：为拒绝决策补充正常对话状态，不引入错误字段。

    参数：
        payload: 原始成功响应。
        allowed: 用户是否允许操作。

    返回值：
        同意时返回原响应；拒绝时返回含自然语言反馈的响应。
    """
    if allowed:
        return payload
    declined = {key: value for key, value in payload.items() if key != "error"}
    declined.update({"status": "declined", "message": CONSENT_DECLINED_MESSAGE})
    return declined
