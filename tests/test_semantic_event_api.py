from __future__ import annotations

from tests.test_desktop_http import _runtime

from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app


def test_semantic_event_api_crud_and_soft_delete(tmp_path) -> None:
    client = create_desktop_app(_runtime(tmp_path)).test_client()

    created = client.post(
        "/api/memory/events",
        json={"event_type": "preference", "content": "用户喜欢安静的沟通", "importance": 3},
    )
    assert created.status_code == 201
    event_id = created.get_json()["event_id"]

    listed = client.get("/api/memory/events?type=preference")
    assert listed.status_code == 200
    assert listed.get_json()[0]["event_id"] == event_id

    patched = client.patch(
        f"/api/memory/events/{event_id}",
        json={"content": "用户喜欢简洁安静的沟通"},
    )
    assert patched.status_code == 200
    assert patched.get_json()["item"]["content"] == "用户喜欢简洁安静的沟通"

    deleted = client.delete(f"/api/memory/events/{event_id}")
    assert deleted.status_code == 200
    assert client.get("/api/memory/events").get_json() == []


def test_semantic_event_api_rejects_empty_content(tmp_path) -> None:
    client = create_desktop_app(_runtime(tmp_path)).test_client()

    response = client.post("/api/memory/events", json={"content": "  "})

    assert response.status_code == 400
