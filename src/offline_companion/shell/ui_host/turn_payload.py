"""turn_payload：TurnResult 序列化与单轮消息处理（A1 共用；CLI/Web/桌面）。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

from offline_companion.core.memory_lifecycle.triggers import maybe_summarize_to_memory
from offline_companion.shared.types import TurnResult


class ChatRuntime(Protocol):
    """摘要：单轮聊天运行时最小契约。"""

    orchestrator: object
    triggers: object | None


def turn_result_to_payload(result: TurnResult) -> dict[str, Any]:
    """摘要：将 ``TurnResult`` 转为 UI 可消费的 JSON 字典。

    参数：
        result: 编排器单轮结果。

    返回值：
        含 ``reply``、``blocked``、记忆字段等的字典。
    """
    reply = result.reply or ""
    if result.memory_only and result.memory_saved:
        reply = f"（已保存记忆：{'；'.join(result.memory_saved)}）"
    return {
        "reply": reply,
        "blocked": result.blocked_by_safety,
        "memory_saved": list(result.memory_saved),
        "memory_recall_count": len(result.memory_recalls),
        "safety_tier": result.safety_tier,
        "requires_consent": result.requires_consent,
        "consent_request_id": result.consent_request_id,
        "route_mode": result.route_mode,
        "selected_model": result.selected_model,
        "fallback_model": result.fallback_model,
        "routing_reason": result.routing_reason,
        "estimated_input_tokens": result.estimated_input_tokens,
        "estimated_output_tokens": result.estimated_output_tokens,
        "estimated_cost": result.estimated_cost,
    }


def process_chat_message(runtime: ChatRuntime, message: str) -> dict[str, Any]:
    """摘要：处理一条用户消息并返回 JSON 可序列化结果。

    参数：
        runtime: 含编排器与记忆开关的运行时。
        message: 用户输入。

    返回值：
        供 Web/桌面 bridge 返回的字典。
    """
    text = (message or "").strip()
    if not text:
        return {
            "reply": "（请输入内容）",
            "blocked": False,
            "memory_saved": [],
            "memory_recall_count": 0,
        }

    conn = getattr(getattr(runtime, "orchestrator", None), "conn", None)
    session_id = getattr(getattr(runtime, "orchestrator", None), "session_id", None)
    before_message_id = _max_message_id(conn, session_id)
    triggers = getattr(runtime, "triggers", None)
    memory_snippet = maybe_summarize_to_memory(text, triggers) if triggers is not None else []
    result = runtime.orchestrator.run_turn(text, memory_on=bool(getattr(runtime, "memory_on", True)))
    payload = turn_result_to_payload(result)
    payload.update(_new_message_ids(conn, session_id, before_message_id))
    if memory_snippet:
        payload.setdefault("memory_saved", [])
        payload["memory_saved"] = list(dict.fromkeys(list(payload["memory_saved"]) + memory_snippet))
    return payload


def process_chat_message_stream(runtime: ChatRuntime, message: str) -> Iterator[dict[str, Any]]:
    """摘要：处理一条用户消息并逐事件返回 recall/token/done payload。"""
    text = (message or "").strip()
    if not text:
        reply = "???????"
        yield {"token": reply}
        yield {
            "done": True,
            "reply": reply,
            "blocked": False,
            "memory_saved": [],
            "memory_recall_count": 0,
        }
        return
    conn = getattr(getattr(runtime, "orchestrator", None), "conn", None)
    session_id = getattr(getattr(runtime, "orchestrator", None), "session_id", None)
    before_message_id = _max_message_id(conn, session_id)
    triggers = getattr(runtime, "triggers", None)
    memory_snippet = maybe_summarize_to_memory(text, triggers) if triggers is not None else []
    for event in runtime.orchestrator.run_turn_stream(
        text,
        memory_on=bool(getattr(runtime, "memory_on", True)),
    ):
        if event.get("done"):
            result = event["turn_result"]
            payload = turn_result_to_payload(result)
            payload["done"] = True
            payload.update(_new_message_ids(conn, session_id, before_message_id))
            if memory_snippet:
                payload.setdefault("memory_saved", [])
                payload["memory_saved"] = list(dict.fromkeys(list(payload["memory_saved"]) + memory_snippet))
            yield payload
            continue
        yield event


def _max_message_id(conn: Any, session_id: Any) -> int:
    """摘要：读取当前会话处理前的最大消息 ID；无数据库时返回 0。"""
    if conn is None or not session_id:
        return 0
    row = conn.execute("SELECT MAX(id) AS max_id FROM messages WHERE session_id = ?;", (str(session_id),)).fetchone()
    return int(row["max_id"] or 0) if row is not None else 0


def _new_message_ids(conn: Any, session_id: Any, after_id: int) -> dict[str, int | None]:
    """摘要：提取本轮新增的用户与助手消息 ID，供前端反馈/回应精确定位。"""
    if conn is None or not session_id:
        return {"user_message_id": None, "message_id": None}
    rows = conn.execute(
        """
        SELECT id, role
        FROM messages
        WHERE session_id = ? AND id > ?
        ORDER BY id ASC;
        """,
        (str(session_id), int(after_id)),
    ).fetchall()
    user_id = next((int(row["id"]) for row in rows if row["role"] == "user"), None)
    assistant_id = next((int(row["id"]) for row in reversed(rows) if row["role"] == "assistant"), None)
    return {"user_message_id": user_id, "message_id": assistant_id}
