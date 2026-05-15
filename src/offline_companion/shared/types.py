"""types：跨层数据传输对象（DTO），不含业务执行逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

# --- 导出包常量（与历史 bundle 兼容） ---
BUNDLE_FORMAT = "offline-companion-bundle"
BUNDLE_VERSION = 1


class PrivacyMode(str, Enum):
    """摘要：出站/云端相关隐私模式。"""

    LOCAL_ONLY = "local_only"
    ASK_BEFORE_CLOUD = "ask_before_cloud"
    ALWAYS_ASK = "always_ask"
    AUTO_ROUTE_CLOUD = "auto_route_cloud"


class OutboundScope(str, Enum):
    """摘要：出站同意范围。"""

    THIS_TURN = "this_turn"
    THIS_SESSION = "this_session"
    GLOBAL = "global"


@dataclass(frozen=True)
class AppPaths:
    """摘要：应用本地数据目录解析结果。"""

    root: Path
    db_path: Path
    personas_dir: Path
    exports_dir: Path


@dataclass(frozen=True)
class MessageRow:
    """摘要：单条会话消息行。"""

    role: str
    content: str
    created_at: float
    meta: dict[str, Any]


@dataclass
class MemoryHit:
    """摘要：记忆检索命中项。"""

    id: int
    body: str
    score: float | None


@dataclass(frozen=True)
class Persona:
    """摘要：已加载人设；`role_lock` 为真时仅使用本系统提示。"""

    persona_id: str
    name: str
    system_prompt: str
    role_lock: bool
    memory_default_on: bool
    raw: dict[str, Any]


@dataclass(frozen=True)
class OutboundPlan:
    """摘要：出站前向用户披露的计划（最小上传说明）。"""

    payload_excerpt: str
    will_send: list[str]
    will_not_send: list[str]
    purpose: str
    scope: OutboundScope


@dataclass(frozen=True)
class ExportBundlePayload:
    """摘要：已由 B2 组装完成的导出包载荷；C2 仅序列化与落盘，不解释业务字段。

    参数：
        manifest: manifest.json 对应字典。
        persona_json: persona.json 文本。
        sessions_jsonl: sessions 表 JSONL。
        messages_jsonl: messages 表 JSONL。
        memory_chunks_jsonl: memory_chunks 表 JSONL。
    """

    manifest: dict[str, Any]
    persona_json: str
    sessions_jsonl: str
    messages_jsonl: str
    memory_chunks_jsonl: str
