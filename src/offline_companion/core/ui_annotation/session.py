"""UI 标注会话与 Skill 包导出。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .danger_detector import detect_danger


class AnnotationError(ValueError):
    """标注数据不符合 UI 地图约束。"""


@dataclass
class AnnotationSession:
    """摘要：收集页面、元素与跳转关系并导出私人 Skill 包。"""

    pages: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, str]] = field(default_factory=list)

    def add_page(self, name: str, page_id: str | None = None) -> dict[str, Any]:
        """摘要：创建一个标注页面。"""
        page_id = page_id or self._slug(name or "page")
        if any(page["id"] == page_id for page in self.pages):
            raise AnnotationError(f"页面 ID 已存在: {page_id}")
        page = {"id": page_id, "name": str(name or page_id), "features": [], "elements": []}
        self.pages.append(page)
        return page

    def add_element(
        self,
        page_id: str,
        region: list[float],
        target_text: str,
        element_type: str,
        element_id: str | None = None,
    ) -> dict[str, Any]:
        """摘要：向页面添加百分比区域标注。"""
        page = self._page(page_id)
        if len(region) != 4 or any(float(value) < 0 or float(value) > 100 for value in region):
            raise AnnotationError("region 必须是 0 到 100 之间的四个百分比")
        values = [float(value) for value in region]
        if values[0] >= values[2] or values[1] >= values[3]:
            raise AnnotationError("region 左上角必须位于右下角之前")
        text = str(target_text or "")
        element_id = element_id or self._slug(text or "element")
        if any(item["id"] == element_id for item in page["elements"]):
            raise AnnotationError(f"元素 ID 已存在: {element_id}")
        element = {
            "id": element_id,
            "target_text": text,
            "type": str(element_type or "display"),
            "region": values,
            "locate_by": "ocr" if text else "ocr_placeholder",
            "danger": detect_danger(text),
        }
        page["elements"].append(element)
        return element

    def add_transition(self, from_page: str, to_page: str, trigger_element_id: str) -> dict[str, str]:
        """摘要：记录点击元素后的页面跳转。"""
        self._page(from_page)
        self._page(to_page)
        transition = {"from": from_page, "to": to_page, "trigger": "click", "target": trigger_element_id}
        self.transitions.append(transition)
        return transition

    def generate_features(self, page_texts: dict[str, list[str]]) -> None:
        """摘要：用页面文字集合差异更新页面特征。"""
        all_texts = [set(page_texts.get(page["id"], [])) for page in self.pages]
        common = set.intersection(*all_texts) if all_texts else set()
        for page, texts in zip(self.pages, all_texts):
            page["features"] = sorted(texts - common)

    def export(self, root: Path, skill_name: str, app_name: str) -> Path:
        """摘要：导出 manifest.json 与 ui_map.yaml 到本地 Skill 目录。"""
        name = str(skill_name or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
            raise AnnotationError("skill_name 必须是小写字母、数字和短横线")
        if not self.pages:
            raise AnnotationError("至少需要一个标注页面")
        target = root / "skills" / name
        target.mkdir(parents=True, exist_ok=True)
        manifest = {
            "type": "skill",
            "name": name,
            "version": "1.0.0",
            "description": f"操作 {app_name or name} 的私人 UI Skill",
            "market_id": f"{name}@1.0.0",
            "trust": "user_installed",
            "capabilities": ["ui_automation"],
            "app_target": {"name": str(app_name or name), "platform": "windows"},
            "entrypoint": {"type": "local_api", "host": "127.0.0.1", "port": 1, "path": "/ui"},
            "permissions": [],
            "output_mode": "block",
        }
        (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (target / "ui_map.yaml").write_text(
            yaml.safe_dump({"schema_version": 1, "pages": self.pages, "transitions": self.transitions}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return target

    def _page(self, page_id: str) -> dict[str, Any]:
        for page in self.pages:
            if page["id"] == page_id:
                return page
        raise AnnotationError(f"页面不存在: {page_id}")

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "page"
