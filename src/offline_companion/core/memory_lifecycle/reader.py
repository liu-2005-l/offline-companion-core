"""reader：记忆读取与分类装配。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .fts_ops import latest_profile_memory, list_memory_rows


class MemoryReader:
    """摘要：把记忆库整理成适合展示与 prompt 注入的结构。"""

    def build_grouped_view(
        self,
        conn,
        *,
        limit: int = 200,
        offset: int = 0,
        order_by: str = "modified_at DESC, id DESC",
    ) -> dict[str, list[dict[str, Any]]]:
        """摘要：按 memory_type 分组返回记忆行。

        参数：
            conn: SQLite 连接。
            limit: 每页条数。
            offset: 偏移量。
            order_by: 排序子句（默认 modified_at DESC, id DESC）。

        返回值：
            {memory_type: [row_dict, ...]} 格式的分组字典。
        """
        rows = list_memory_rows(conn, limit=limit, offset=offset, order_by=order_by)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            memory_type = str(row.get("memory_type") or row.get("meta", {}).get("memory_type") or row.get("source") or "other")
            groups[memory_type].append(row)
        return dict(groups)

    def build_prompt_blocks(self, conn) -> dict[str, str]:
        profile = latest_profile_memory(conn)
        assistant_lines: list[str] = []
        user_lines: list[str] = []
        if profile.get("assistant", {}).get("display_name"):
            assistant_lines.append(f"名字：{profile['assistant']['display_name']}")
        if profile.get("user", {}).get("display_name"):
            user_lines.append(f"名字：{profile['user']['display_name']}")
        if profile.get("user", {}).get("preference"):
            user_lines.append(f"偏好：{profile['user']['preference']}")
        return {
            "agent_profile": "\n".join(assistant_lines),
            "user_profile": "\n".join(user_lines),
        }
