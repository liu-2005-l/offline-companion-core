"""UI 自动化可选能力探测。"""

from __future__ import annotations

import importlib.util


def is_ui_automation_available() -> bool:
    """摘要：判断 OCR、截图和输入注入依赖是否全部可导入。"""
    return all(importlib.util.find_spec(name) is not None for name in ("rapidocr_onnxruntime", "mss", "pynput"))


def capability_warnings(manifest: dict) -> list[str]:
    """摘要：返回能力声明的非阻断警告。"""
    capabilities = manifest.get("capabilities", []) if isinstance(manifest, dict) else []
    if "ui_automation" in capabilities and not is_ui_automation_available():
        return ["声明 ui_automation，但本机未启用完整 UI 自动化依赖"]
    return []
