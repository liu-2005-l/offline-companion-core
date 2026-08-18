"""UI 标注会话、Skill 导出与桌面 API 测试。"""

from __future__ import annotations

import json

import pytest
import yaml

from offline_companion.core.ui_annotation import AnnotationError, AnnotationSession, detect_danger


def test_danger_detector() -> None:
    assert detect_danger("删除联系人") == "hard"
    assert detect_danger("关闭窗口") == "soft"
    assert detect_danger("发送") == "none"


def test_annotation_session_features_and_export(tmp_path) -> None:
    session = AnnotationSession()
    session.add_page("主界面", "main")
    session.add_page("聊天", "chat")
    element = session.add_element("main", [10, 20, 40, 50], "文件传输助手", "link")
    session.add_transition("main", "chat", element["id"])
    session.generate_features({"main": ["导航", "文件传输助手"], "chat": ["导航", "发送"]})
    target = session.export(tmp_path, "wechat-ops", "微信")
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    ui_map = yaml.safe_load((target / "ui_map.yaml").read_text(encoding="utf-8"))
    from offline_companion.shell.skill_manager.registry import validate_manifest_dict

    validate_manifest_dict(manifest)
    assert manifest["app_target"]["name"] == "微信"
    assert ui_map["pages"][0]["features"] == ["文件传输助手"]
    assert ui_map["transitions"][0]["to"] == "chat"


def test_annotation_rejects_invalid_region() -> None:
    session = AnnotationSession()
    session.add_page("主界面", "main")
    with pytest.raises(AnnotationError):
        session.add_element("main", [1, 2, 3], "按钮", "button")


def test_annotation_api_export(tmp_path) -> None:
    from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app
    from test_desktop_http import _runtime

    client = create_desktop_app(_runtime(tmp_path)).test_client()
    assert client.post("/api/ui_annotation/page", json={"name": "主界面", "page_id": "main"}).status_code == 201
    response = client.post(
        "/api/ui_annotation/element",
        json={"page_id": "main", "region": [1, 2, 20, 30], "target_text": "发送", "type": "button"},
    )
    assert response.status_code == 201
    result = client.post("/api/ui_annotation/export", json={"skill_name": "demo-ui", "app_name": "演示"})
    assert result.status_code == 200
    assert (tmp_path / "skills" / "demo-ui" / "ui_map.yaml").is_file()
