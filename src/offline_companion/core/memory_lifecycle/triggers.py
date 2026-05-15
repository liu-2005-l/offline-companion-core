"""triggers：记忆写入触发器注册表（Phase 0 占位）。"""

from __future__ import annotations

from typing import Any

# 摘要：后续注册 on_explicit_save / on_summarize_request 等；MVP 仅占位。
TriggerFn = Any
TRIGGER_REGISTRY: dict[str, TriggerFn] = {}
