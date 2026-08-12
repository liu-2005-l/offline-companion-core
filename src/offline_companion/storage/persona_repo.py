"""摘要：人格配置的 SQLite 持久化访问层。"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from offline_companion.shared.types import OceanVector, Persona

_SEED_PERSONAS: tuple[dict[str, Any], ...] = (
    {
        "id": "xiao_nuo",
        "name": "\u5c0f\u8bfa",
        "avatar": "\u8bfa",
        "desc": "\u6e29\u548c\u3001\u7b80\u77ed\u3001\u53ef\u4fe1\u8d56\u7684\u672c\u5730\u966a\u4f34\u8005\u3002",
        "ocean": [70, 62, 48, 82, 38],
        "traits": ["\u6e29\u548c", "\u8010\u5fc3", "\u7b80\u6d01"],
        "system_prompt": (
            "\u4f60\u662f\u5c0f\u8bfa\uff0c\u8fd0\u884c\u5728\u7528\u6237\u672c\u673a\u7684"
            "\u9690\u79c1\u4f18\u5148\u79bb\u7ebf\u966a\u4f34\u52a9\u624b\u3002\u4f60\u7528\u7b80\u4f53"
            "\u4e2d\u6587\u56de\u590d\uff0c\u8bed\u6c14\u6e29\u548c\u3001\u771f\u8bda\u3001\u7b80\u77ed\u3002"
        ),
    },
    {
        "id": "a_ce",
        "name": "\u963f\u7b56",
        "avatar": "\u7b56",
        "desc": "\u504f\u7406\u6027\u7684\u8ba1\u5212\u4f19\u4f34\uff0c\u64c5\u957f\u62c6\u89e3\u95ee\u9898\u548c\u7ed9\u51fa\u4e0b\u4e00\u6b65\u3002",
        "ocean": [74, 86, 42, 58, 30],
        "traits": ["\u7406\u6027", "\u6e05\u6670", "\u884c\u52a8\u5bfc\u5411"],
        "system_prompt": (
            "\u4f60\u662f\u963f\u7b56\uff0c\u4e00\u4e2a\u51b7\u9759\u6e05\u6670\u7684"
            "\u672c\u5730\u8ba1\u5212\u4f19\u4f34\u3002\u4f60\u4f18\u5148\u5e2e\u7528\u6237\u628a"
            "\u95ee\u9898\u62c6\u6210\u53ef\u6267\u884c\u7684\u5c0f\u6b65\u9aa4\u3002"
        ),
    },
    {
        "id": "zhi_xin",
        "name": "\u77e5\u5fc3",
        "avatar": "\u5fc3",
        "desc": "\u66f4\u5173\u6ce8\u60c5\u7eea\u548c\u611f\u53d7\u7684\u652f\u6301\u578b\u966a\u4f34\u8005\u3002",
        "ocean": [68, 55, 52, 90, 46],
        "traits": ["\u5171\u60c5", "\u652f\u6301", "\u7a33\u5b9a"],
        "system_prompt": (
            "\u4f60\u662f\u77e5\u5fc3\uff0c\u4e00\u4e2a\u66f4\u5173\u6ce8\u7528\u6237"
            "\u60c5\u7eea\u548c\u611f\u53d7\u7684\u672c\u5730\u966a\u4f34\u8005\u3002\u4f60\u5148"
            "\u63a5\u4f4f\u60c5\u7eea\uff0c\u518d\u7ed9\u51fa\u6e29\u548c\u7684\u5efa\u8bae\u3002"
        ),
    },
)


def init_personas(conn: Any) -> None:
    """摘要：首次运行时写入默认三个人格。

    参数：
        conn: 已迁移的 SQLite 连接。
    """
    row = conn.execute("SELECT COUNT(*) AS count FROM personas;").fetchone()
    if int(row["count"]) > 0:
        return
    now = time.time()
    for index, seed in enumerate(_SEED_PERSONAS):
        _insert_seed(conn, seed, active=index == 0, now=now)


def list_personas(conn: Any) -> list[dict[str, Any]]:
    """摘要：列出全部人格配置。

    参数：
        conn: SQLite 连接。
    返回值：
        前端人格 chip/detail 可直接消费的字典列表。
    """
    init_personas(conn)
    rows = conn.execute(
        """
        SELECT id, name, avatar, desc, ocean_json, traits_json, anchor, active
        FROM personas
        ORDER BY active DESC, created_at ASC, id ASC;
        """
    ).fetchall()
    return [_row_payload(row) for row in rows]


def get_persona(conn: Any, persona_id: str) -> Persona | None:
    """摘要：按 ID 读取 Persona 对象。

    参数：
        conn: SQLite 连接。
        persona_id: 人格 ID。
    返回值：
        Persona 对象；不存在时返回 None。
    """
    init_personas(conn)
    row = conn.execute("SELECT * FROM personas WHERE id = ?;", (persona_id,)).fetchone()
    return None if row is None else _row_persona(row)


def active_persona(conn: Any) -> Persona | None:
    """摘要：读取当前激活人格。

    参数：
        conn: SQLite 连接。
    返回值：
        当前 active Persona；不存在时返回 None。
    """
    init_personas(conn)
    row = conn.execute("SELECT * FROM personas WHERE active = 1 LIMIT 1;").fetchone()
    return None if row is None else _row_persona(row)


def activate_persona(conn: Any, persona_id: str) -> Persona | None:
    """摘要：激活指定人格，并保证同一时刻只有一个 active。

    参数：
        conn: SQLite 连接。
        persona_id: 人格 ID。
    返回值：
        激活后的人格；不存在时返回 None。
    """
    init_personas(conn)
    persona = get_persona(conn, persona_id)
    if persona is None:
        return None
    now = time.time()
    with conn:
        conn.execute("UPDATE personas SET active = 0, updated_at = ? WHERE active = 1;", (now,))
        conn.execute("UPDATE personas SET active = 1, updated_at = ? WHERE id = ?;", (now, persona_id))
    return get_persona(conn, persona_id)


def create_persona(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """摘要：创建自定义人格并返回前端 payload。

    参数：
        conn: SQLite 连接。
        payload: 前端提交的人格字段。

    返回值：
        创建后的人格 payload。

    Raises:
        ValueError: 字段不合法或名称重复。
    """
    init_personas(conn)
    name = _clean_required_text(payload.get("name"), "name")
    _ensure_unique_name(conn, name)
    avatar = str(payload.get("avatar") or name[:1] or "").strip()
    desc = str(payload.get("desc") or "").strip()
    ocean = _normalize_ocean(payload.get("ocean"))
    traits = _normalize_traits(payload.get("traits"))
    anchor = str(payload.get("anchor") or "").strip()
    system_prompt = anchor or f"你是{name}，一个运行在用户本机的隐私优先离线陪伴人格。"
    persona_id = uuid.uuid4().hex
    now = time.time()
    raw = _raw_payload(persona_id, name, avatar, desc, traits, system_prompt, ocean)
    with conn:
        conn.execute(
            """
            INSERT INTO personas(
                id, name, avatar, desc, ocean_json, traits_json, anchor, system_prompt,
                raw_json, active, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?);
            """,
            (
                persona_id,
                name,
                avatar,
                desc,
                json.dumps(ocean, ensure_ascii=False),
                json.dumps(traits, ensure_ascii=False),
                anchor,
                system_prompt,
                json.dumps(raw, ensure_ascii=False),
                0,
                now,
                now,
            ),
        )
    created = _get_persona_payload(conn, persona_id)
    if created is None:
        raise ValueError("persona_create_failed")
    return created


def update_persona(conn: Any, persona_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """摘要：更新指定人格并返回前端 payload。

    参数：
        conn: SQLite 连接。
        persona_id: 人格 ID。
        payload: 允许更新的人格字段。

    返回值：
        更新后的人格 payload；不存在时返回 None。

    Raises:
        ValueError: 字段不合法或名称重复。
    """
    init_personas(conn)
    current = _get_persona_payload(conn, persona_id)
    if current is None:
        return None
    updates: dict[str, Any] = {}
    if "name" in payload:
        name = _clean_required_text(payload.get("name"), "name")
        if name != current["name"]:
            _ensure_unique_name(conn, name, exclude_id=persona_id)
        updates["name"] = name
    if "avatar" in payload:
        updates["avatar"] = str(payload.get("avatar") or "").strip()
    if "desc" in payload:
        updates["desc"] = str(payload.get("desc") or "").strip()
    if "ocean" in payload:
        updates["ocean_json"] = json.dumps(_normalize_ocean(payload.get("ocean")), ensure_ascii=False)
    if "traits" in payload:
        updates["traits_json"] = json.dumps(_normalize_traits(payload.get("traits")), ensure_ascii=False)
    if "anchor" in payload:
        anchor = str(payload.get("anchor") or "").strip()
        updates["anchor"] = anchor
        updates["system_prompt"] = anchor or str(current.get("anchor") or "")
    if not updates:
        return current
    merged = dict(current)
    merged.update(
        {
            "name": updates.get("name", current["name"]),
            "avatar": updates.get("avatar", current["avatar"]),
            "desc": updates.get("desc", current["desc"]),
            "ocean": _loads_list(updates.get("ocean_json", json.dumps(current["ocean"], ensure_ascii=False))),
            "traits": _loads_list(updates.get("traits_json", json.dumps(current["traits"], ensure_ascii=False))),
            "anchor": updates.get("anchor", current["anchor"]),
        }
    )
    updates["raw_json"] = json.dumps(
        _raw_payload(
            persona_id,
            str(merged["name"]),
            str(merged["avatar"]),
            str(merged["desc"]),
            [str(item) for item in merged["traits"]],
            str(updates.get("system_prompt", merged["anchor"])),
            [int(item) for item in merged["ocean"]],
        ),
        ensure_ascii=False,
    )
    updates["updated_at"] = time.time()
    set_clause = ", ".join(f"{key} = ?" for key in updates)
    with conn:
        conn.execute(
            f"UPDATE personas SET {set_clause} WHERE id = ?;",
            (*updates.values(), persona_id),
        )
    return _get_persona_payload(conn, persona_id)


def delete_persona(conn: Any, persona_id: str) -> bool:
    """摘要：删除非 active 人格。

    参数：
        conn: SQLite 连接。
        persona_id: 人格 ID。

    返回值：
        删除成功返回 True；不存在返回 False。

    Raises:
        ValueError: 删除 active 或最后一个人格。
    """
    init_personas(conn)
    current = _get_persona_payload(conn, persona_id)
    if current is None:
        return False
    if bool(current["active"]):
        raise ValueError("cannot_delete_active_persona")
    row = conn.execute("SELECT COUNT(*) AS count FROM personas;").fetchone()
    if int(row["count"]) <= 1:
        raise ValueError("cannot_delete_last_persona")
    with conn:
        conn.execute("DELETE FROM personas WHERE id = ?;", (persona_id,))
    return True


def _insert_seed(conn: Any, seed: dict[str, Any], *, active: bool, now: float) -> None:
    raw = {
        "id": seed["id"],
        "name": seed["name"],
        "avatar": seed["avatar"],
        "description": seed["desc"],
        "traits": seed["traits"],
        "system_prompt": seed["system_prompt"],
        "role_lock": True,
        "memory_default_on": True,
        "default_companion_display_name": seed["name"],
        "ocean": _ocean_dict(seed["ocean"]),
    }
    conn.execute(
        """
        INSERT INTO personas(
            id, name, avatar, desc, ocean_json, traits_json, anchor, system_prompt,
            raw_json, active, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?);
        """,
        (
            seed["id"],
            seed["name"],
            seed["avatar"],
            seed["desc"],
            json.dumps(seed["ocean"], ensure_ascii=False),
            json.dumps(seed["traits"], ensure_ascii=False),
            seed["system_prompt"],
            seed["system_prompt"],
            json.dumps(raw, ensure_ascii=False),
            1 if active else 0,
            now,
            now,
        ),
    )


def _row_payload(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "avatar": str(row["avatar"] or ""),
        "desc": str(row["desc"] or ""),
        "ocean": _loads_list(row["ocean_json"]),
        "traits": [str(item) for item in _loads_list(row["traits_json"])],
        "anchor": str(row["anchor"] or ""),
        "active": bool(row["active"]),
    }


def _get_persona_payload(conn: Any, persona_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, name, avatar, desc, ocean_json, traits_json, anchor, active
        FROM personas
        WHERE id = ?;
        """,
        (persona_id,),
    ).fetchone()
    return None if row is None else _row_payload(row)


def _ensure_unique_name(conn: Any, name: str, *, exclude_id: str | None = None) -> None:
    if exclude_id is None:
        row = conn.execute("SELECT id FROM personas WHERE name = ? LIMIT 1;", (name,)).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM personas WHERE name = ? AND id <> ? LIMIT 1;",
            (name, exclude_id),
        ).fetchone()
    if row is not None:
        raise ValueError("persona_name_exists")


def _clean_required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field}_required")
    return text


def _normalize_ocean(value: Any) -> list[int]:
    items = value if isinstance(value, list) else [50, 50, 50, 50, 50]
    normalized: list[int] = []
    for item in items[:5]:
        try:
            number = int(item)
        except (TypeError, ValueError):
            number = 50
        normalized.append(max(0, min(100, number)))
    while len(normalized) < 5:
        normalized.append(50)
    return normalized


def _normalize_traits(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    traits: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in traits:
            traits.append(text)
    return traits


def _raw_payload(
    persona_id: str,
    name: str,
    avatar: str,
    desc: str,
    traits: list[str],
    system_prompt: str,
    ocean: list[int],
) -> dict[str, Any]:
    return {
        "id": persona_id,
        "name": name,
        "avatar": avatar,
        "description": desc,
        "traits": traits,
        "system_prompt": system_prompt,
        "role_lock": True,
        "memory_default_on": True,
        "default_companion_display_name": name,
        "ocean": _ocean_dict(ocean),
    }


def _row_persona(row: Any) -> Persona:
    raw = _loads_dict(row["raw_json"])
    ocean_values = _loads_list(row["ocean_json"])
    ocean = None
    if len(ocean_values) == 5:
        ocean = OceanVector(
            openness=float(ocean_values[0]) / 100,
            conscientiousness=float(ocean_values[1]) / 100,
            extraversion=float(ocean_values[2]) / 100,
            agreeableness=float(ocean_values[3]) / 100,
            neuroticism=float(ocean_values[4]) / 100,
        )
    return Persona(
        persona_id=str(row["id"]),
        name=str(row["name"]),
        system_prompt=str(row["system_prompt"]),
        role_lock=bool(raw.get("role_lock", True)),
        memory_default_on=bool(raw.get("memory_default_on", True)),
        default_companion_display_name=str(raw.get("default_companion_display_name") or row["name"]),
        companion_display_name=raw.get("companion_display_name"),
        raw=raw,
        ocean=ocean,
    )


def _loads_list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _loads_dict(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ocean_dict(values: list[int]) -> dict[str, float]:
    return {
        "openness": float(values[0]) / 100,
        "conscientiousness": float(values[1]) / 100,
        "extraversion": float(values[2]) / 100,
        "agreeableness": float(values[3]) / 100,
        "neuroticism": float(values[4]) / 100,
    }
