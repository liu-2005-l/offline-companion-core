from __future__ import annotations

from tests.test_desktop_http import _runtime

from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app


def test_semantic_event_api_crud_and_soft_delete(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    client = create_desktop_app(runtime).test_client()

    created = client.post(
        "/api/memory/events",
        json={"event_type": "preference", "content": "用户喜欢安静的沟通", "importance": 3},
    )
    assert created.status_code == 201
    created_body = created.get_json()
    event_id = created_body["event_id"]
    stored = runtime.orchestrator.conn.execute(
        "SELECT content_embedding, content_embedding_space FROM semantic_events WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    assert stored["content_embedding"]
    assert stored["content_embedding_space"] == "hash_bow_768"

    listed = client.get("/api/memory/events?type=preference")
    assert listed.status_code == 200
    listed_item = listed.get_json()[0]
    assert listed_item["event_id"] == event_id
    assert listed_item["id"] == event_id
    assert listed_item["body"] == "用户喜欢安静的沟通"
    assert listed_item["memory_type"] == "preference"
    assert listed_item["source"] == "semantic_event"
    assert listed_item["content_embedding_space"] == "hash_bow_768"
    invalid_type = client.get("/api/memory/events?type=invalid")
    assert invalid_type.status_code == 200
    assert invalid_type.get_json() == []

    patched = client.patch(
        f"/api/memory/events/{event_id}",
        json={"content": "用户喜欢简洁安静的沟通", "importance": 4},
    )
    assert patched.status_code == 200
    assert patched.get_json()["item"]["content"] == "用户喜欢简洁安静的沟通"
    assert patched.get_json()["item"]["importance"] == 4.0
    stored_after_patch = runtime.orchestrator.conn.execute(
        "SELECT content, importance FROM semantic_events WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    assert stored_after_patch["content"] == "用户喜欢简洁安静的沟通"
    assert stored_after_patch["importance"] == 4.0

    deleted = client.delete(f"/api/memory/events/{event_id}")
    assert deleted.status_code == 200
    stored_after_delete = runtime.orchestrator.conn.execute(
        "SELECT status FROM semantic_events WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    assert stored_after_delete["status"] == "dormant"
    assert client.get("/api/memory/events?type=preference").get_json() == []
    assert client.get("/api/memory/events").get_json() == []


def test_semantic_event_api_returns_empty_list_for_empty_store(tmp_path) -> None:
    """摘要：空语义事件库返回稳定的空 JSON 列表。"""
    client = create_desktop_app(_runtime(tmp_path)).test_client()

    response = client.get("/api/memory/events")

    assert response.status_code == 200
    assert response.get_json() == []


def test_semantic_event_api_missing_event_returns_404(tmp_path) -> None:
    """摘要：PATCH/DELETE 不存在的语义事件时显式返回 404。"""
    client = create_desktop_app(_runtime(tmp_path)).test_client()

    patched = client.patch("/api/memory/events/missing", json={"content": "不存在"})
    deleted = client.delete("/api/memory/events/missing")

    assert patched.status_code == 404
    assert deleted.status_code == 404


def test_semantic_event_api_rejects_empty_content(tmp_path) -> None:
    client = create_desktop_app(_runtime(tmp_path)).test_client()

    response = client.post("/api/memory/events", json={"content": "  "})

    assert response.status_code == 400
