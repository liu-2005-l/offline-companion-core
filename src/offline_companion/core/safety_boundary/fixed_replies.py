"""fixed_replies：从 YAML 加载版本化固定话术与关键词（B3）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# 兼容旧引用（测试或外部 import）；内容由默认 YAML 填充
SELF_REPLY_ZH: str = ""
OTHER_REPLY_ZH: str = ""


@dataclass(frozen=True)
class SafetyRepliesBundle:
    """摘要：已加载的安全话术包。"""

    version: int
    locale: str
    path: Path
    self_markers: tuple[str, ...]
    other_markers: tuple[str, ...]
    self_reply: str
    other_reply: str


_CACHE_BY_PATH: dict[Path, SafetyRepliesBundle] = {}


def default_safety_replies_path() -> Path:
    """摘要：解析默认话术库路径（仓库内 ``configs/safety_replies/zh_v1.yaml``）。

    返回值：
        话术 YAML 的绝对路径。

    说明：
        可通过环境变量 ``OFFLINE_COMPANION_SAFETY_REPLIES`` 覆盖。
    """
    env = os.environ.get("OFFLINE_COMPANION_SAFETY_REPLIES")
    if env:
        return Path(env).expanduser().resolve()
    # fixed_replies.py → safety_boundary → core → offline_companion → src → 仓库根
    root = Path(__file__).resolve().parents[4]
    return root / "configs" / "safety_replies" / "zh_v1.yaml"


def _parse_bundle(path: Path, data: dict[str, Any]) -> SafetyRepliesBundle:
    tiers = data.get("tiers")
    if not isinstance(tiers, dict):
        raise ValueError(f"话术库 {path} 缺少 tiers 节点")

    def _tier(name: str) -> tuple[tuple[str, ...], str]:
        block = tiers.get(name)
        if not isinstance(block, dict):
            raise ValueError(f"话术库 {path} 缺少 tiers.{name}")
        markers_raw = block.get("markers")
        if not isinstance(markers_raw, list) or not markers_raw:
            raise ValueError(f"话术库 {path} tiers.{name}.markers 无效")
        markers = tuple(str(m).strip() for m in markers_raw if str(m).strip())
        reply = str(block.get("reply") or "").strip()
        if not reply:
            raise ValueError(f"话术库 {path} tiers.{name}.reply 为空")
        return markers, reply

    self_markers, self_reply = _tier("crisis_self")
    other_markers, other_reply = _tier("crisis_other")

    return SafetyRepliesBundle(
        version=int(data.get("version") or 1),
        locale=str(data.get("locale") or "zh-CN"),
        path=path,
        self_markers=self_markers,
        other_markers=other_markers,
        self_reply=self_reply,
        other_reply=other_reply,
    )


def load_safety_replies(path: Path | None = None, *, reload: bool = False) -> SafetyRepliesBundle:
    """摘要：加载话术 YAML（带进程内缓存）。

    参数：
        path: 话术文件路径；默认 ``default_safety_replies_path()``。
        reload: 为 True 时强制重新读取文件。

    返回值：
        ``SafetyRepliesBundle``。

    异常：
        FileNotFoundError：文件不存在。
        ValueError：结构不合法。
    """
    global SELF_REPLY_ZH, OTHER_REPLY_ZH

    resolved = (path or default_safety_replies_path()).resolve()
    if not reload and resolved in _CACHE_BY_PATH:
        return _CACHE_BY_PATH[resolved]

    if not resolved.is_file():
        raise FileNotFoundError(f"安全话术库不存在: {resolved}")

    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"话术库格式错误: {resolved}")

    bundle = _parse_bundle(resolved, raw)
    _CACHE_BY_PATH[resolved] = bundle
    if resolved == default_safety_replies_path().resolve():
        SELF_REPLY_ZH = bundle.self_reply
        OTHER_REPLY_ZH = bundle.other_reply
    return bundle


def ensure_safety_replies_loaded() -> SafetyRepliesBundle:
    """摘要：确保默认话术库已加载（供 classifier 调用）。"""
    return load_safety_replies()


# 模块导入时预加载，失败则推迟到首次 classify（便于测试注入路径）
try:
    ensure_safety_replies_loaded()
except (FileNotFoundError, ValueError):
    pass
