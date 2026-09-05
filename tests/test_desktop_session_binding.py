"""摘要：P3-A1 桌面 canonical 会话与人格切换契约测试。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from multiprocessing import get_context
from pathlib import Path

import pytest

from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.runtime.storage_index.engine import SCHEMA_VERSION, connect
from offline_companion.shell.ui_host.bootstrap import bootstrap_ui_session
from offline_companion.shell.ui_host.desktop.session_binding import (
    DesktopSessionBindingService,
    DesktopSessionContextProvider,
    SessionBindingError,
    build_persona_snapshot,
    validate_persona_snapshot,
)
from offline_companion.storage.persona_repo import list_personas, update_persona

_DEFAULT_PERSONA = Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"


def _commit_then_wait_for_kill(db_path: str, ready_path: str) -> None:
    """摘要：子进程提交切换后停在 context 发布前，供真实 kill 恢复测试。"""
    conn = connect(Path(db_path))
    provider = DesktopSessionContextProvider()

    def after_commit(_context) -> None:
        Path(ready_path).write_text("committed", encoding="utf-8")
        time.sleep(60)

    service = DesktopSessionBindingService(
        conn,
        context_provider=provider,
        event_stream_manager=None,
        semantic_embed_func=None,
        after_commit_hook=after_commit,
    )
    initial = service.restore_or_create(
        preferred_session_id="initial",
        startup_persona=load_persona_file(_DEFAULT_PERSONA),
        title="初始会话",
    )
    target = next(
        item for item in list_personas(conn) if item["id"] != initial.session_core.persona.persona_id
    )
    service.switch_persona(
        target["id"],
        switch_request_id="kill-after-commit",
        expected_revision=initial.revision,
    )


def _service(tmp_path: Path) -> tuple[sqlite3.Connection, DesktopSessionBindingService]:
    conn = connect(tmp_path / "session-binding.db")
    service = DesktopSessionBindingService(
        conn,
        context_provider=DesktopSessionContextProvider(),
        event_stream_manager=None,
        semantic_embed_func=None,
    )
    service.restore_or_create(
        preferred_session_id="initial",
        startup_persona=load_persona_file(_DEFAULT_PERSONA),
        title="初始会话",
    )
    return conn, service


def test_v12_migration_adds_snapshot_and_canonical_constraints(tmp_path: Path) -> None:
    db_path = tmp_path / "v12.db"
    legacy = sqlite3.connect(str(db_path), isolation_level=None)
    legacy.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);")
    legacy.execute("INSERT INTO meta(key, value) VALUES('schema_version', '12');")
    legacy.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            persona_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        """
    )
    legacy.close()

    conn = connect(db_path)
    columns = {row["name"]: row["type"] for row in conn.execute("PRAGMA table_info(sessions);")}
    assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version';").fetchone()[0] == str(
        SCHEMA_VERSION
    )
    assert columns["persona_snapshot_json"] == "TEXT"
    assert columns["persona_snapshot_schema"] == "INTEGER"
    assert columns["persona_snapshot_sha256"] == "TEXT"
    assert columns["persona_snapshot_source"] == "TEXT"
    assert columns["switch_request_id"] == "TEXT"
    indexes = {row["name"]: row for row in conn.execute("PRAGMA index_list(sessions);")}
    assert indexes["idx_sessions_switch_request_id"]["unique"] == 1
    assert indexes["idx_sessions_switch_request_id"]["partial"] == 1
    foreign_keys = conn.execute("PRAGMA foreign_key_list(desktop_session_state);").fetchall()
    assert [(row["from"], row["table"], row["to"]) for row in foreign_keys] == [
        ("active_session_id", "sessions", "id")
    ]
    conn.execute(
        "INSERT INTO sessions(id, title, persona_id, created_at, updated_at) VALUES(?,?,?,?,?);",
        ("constraint-session", None, "persona", 1.0, 1.0),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO desktop_session_state(id, active_session_id, revision, updated_at) VALUES(2, ?, 1, 1.0);",
            ("constraint-session",),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO desktop_session_state(id, active_session_id, revision, updated_at) VALUES(1, ?, 0, 1.0);",
            ("constraint-session",),
        )


def test_initial_session_has_canonical_snapshot_and_hash(tmp_path: Path) -> None:
    conn, service = _service(tmp_path)
    context = service.current()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?;", (context.session_id,)).fetchone()

    proof = validate_persona_snapshot(row)

    assert context.revision == 1
    assert proof.sha256 == context.snapshot.sha256
    assert proof.payload["effective_system_prompt"]
    assert proof.payload["persona_id"] == conn.execute(
        "SELECT id FROM personas WHERE active = 1;"
    ).fetchone()[0]
    assert len(proof.payload["ocean_levels"]) == 5
    assert proof.payload["constraint_manifest"] == {"sha256": None, "version": None}


def test_legacy_orphan_stays_read_only_and_new_canonical_is_created(tmp_path: Path) -> None:
    conn = connect(tmp_path / "orphan.db")
    conn.execute(
        "INSERT INTO sessions(id, title, persona_id, created_at, updated_at) VALUES(?,?,?,?,?);",
        ("orphan", "孤儿", "deleted-persona", 1.0, 1.0),
    )
    service = DesktopSessionBindingService(
        conn,
        context_provider=DesktopSessionContextProvider(),
        event_stream_manager=None,
        semantic_embed_func=None,
    )

    context = service.restore_or_create(
        preferred_session_id="orphan",
        startup_persona=load_persona_file(_DEFAULT_PERSONA),
        title="恢复会话",
    )

    orphan = conn.execute("SELECT * FROM sessions WHERE id = 'orphan';").fetchone()
    assert orphan["persona_snapshot_json"] is None
    assert context.session_id != "orphan"
    assert conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0] == 2


def test_snapshot_hash_or_json_mismatch_is_rejected(tmp_path: Path) -> None:
    conn, service = _service(tmp_path)
    context = service.current()
    conn.execute(
        "UPDATE sessions SET persona_snapshot_sha256 = ? WHERE id = ?;",
        ("0" * 64, context.session_id),
    )

    with pytest.raises(SessionBindingError, match="persona_snapshot_invalid"):
        service.current()


def test_snapshot_semantics_are_rejected_even_with_matching_hash(tmp_path: Path) -> None:
    conn, service = _service(tmp_path)
    context = service.current()
    payload = dict(context.snapshot.payload)
    payload["ocean_levels"] = ["mid"] * 5
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    conn.execute(
        "UPDATE sessions SET persona_snapshot_json = ?, persona_snapshot_sha256 = ? WHERE id = ?;",
        (canonical, digest, context.session_id),
    )

    with pytest.raises(SessionBindingError, match="persona_snapshot_invalid"):
        service.current()


def test_process_kill_after_commit_recovers_sqlite_canonical(tmp_path: Path) -> None:
    db_path = tmp_path / "kill-recovery.db"
    ready_path = tmp_path / "committed.marker"
    process = get_context("spawn").Process(
        target=_commit_then_wait_for_kill,
        args=(str(db_path), str(ready_path)),
    )
    process.start()
    deadline = time.time() + 15
    while time.time() < deadline and not ready_path.exists():
        time.sleep(0.05)
    assert ready_path.exists(), "子进程未到达 commit 后恢复探针"
    process.kill()
    process.join(timeout=10)
    assert not process.is_alive()

    conn = connect(db_path)
    service = DesktopSessionBindingService(
        conn,
        context_provider=DesktopSessionContextProvider(),
        event_stream_manager=None,
        semantic_embed_func=None,
    )
    recovered = service.restore_or_create(
        preferred_session_id="ignored-after-canonical",
        startup_persona=load_persona_file(_DEFAULT_PERSONA),
        title="恢复会话",
    )

    assert recovered.revision == 2
    assert recovered.session_id != "initial"
    assert recovered.snapshot.source == "persona_switch"
    assert conn.execute("PRAGMA integrity_check;").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check;").fetchall() == []


def test_switch_failure_rolls_back_session_default_and_pointer(tmp_path: Path, monkeypatch) -> None:
    conn, service = _service(tmp_path)
    before = service.current()
    target = next(item for item in list_personas(conn) if item["id"] != before.session_core.persona.persona_id)
    before_count = conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0]
    before_default = conn.execute("SELECT id FROM personas WHERE active = 1;").fetchone()[0]
    original_insert = service._insert_session

    def fail_after_insert(**kwargs) -> None:
        original_insert(**kwargs)
        raise sqlite3.OperationalError("injected failure")

    monkeypatch.setattr(service, "_insert_session", fail_after_insert)
    with pytest.raises(SessionBindingError, match="switch_failed"):
        service.switch_persona(
            target["id"],
            switch_request_id="rollback-request",
            expected_revision=before.revision,
        )

    assert conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0] == before_count
    assert conn.execute("SELECT id FROM personas WHERE active = 1;").fetchone()[0] == before_default
    assert service.current().session_id == before.session_id
    assert service.current().revision == before.revision


@pytest.mark.parametrize("failure_stage", ["snapshot", "session", "default", "canonical"])
def test_each_switch_failure_stage_preserves_atomic_state(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    conn = connect(tmp_path / f"fault-{failure_stage}.db")

    def inject(stage: str) -> None:
        if stage == failure_stage:
            raise ValueError(f"injected-{stage}")

    service = DesktopSessionBindingService(
        conn,
        context_provider=DesktopSessionContextProvider(),
        event_stream_manager=None,
        semantic_embed_func=None,
        fault_injector=inject,
    )
    before = service.restore_or_create(
        preferred_session_id="initial",
        startup_persona=load_persona_file(_DEFAULT_PERSONA),
        title="初始会话",
    )
    target = next(item for item in list_personas(conn) if item["id"] != before.session_core.persona.persona_id)
    before_default = conn.execute("SELECT id FROM personas WHERE active = 1;").fetchone()[0]

    with pytest.raises(SessionBindingError, match="switch_failed"):
        service.switch_persona(
            target["id"],
            switch_request_id=f"fault-{failure_stage}",
            expected_revision=before.revision,
        )

    assert conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0] == 1
    assert conn.execute("SELECT id FROM personas WHERE active = 1;").fetchone()[0] == before_default
    state = conn.execute("SELECT * FROM desktop_session_state WHERE id = 1;").fetchone()
    assert state["active_session_id"] == before.session_id
    assert state["revision"] == before.revision


def test_persona_edit_only_changes_future_session_snapshot(tmp_path: Path) -> None:
    conn, service = _service(tmp_path)
    first = service.current()
    target = list_personas(conn)[0]
    switched = service.switch_persona(
        target["id"],
        switch_request_id="version-before",
        expected_revision=first.revision,
    ).context
    old_json = switched.snapshot.canonical_json
    old_hash = switched.snapshot.sha256
    update_persona(conn, target["id"], {"anchor": "更新后的系统提示。"})

    updated = service.switch_persona(
        target["id"],
        switch_request_id="version-after",
        expected_revision=switched.revision,
    ).context

    old_row = conn.execute("SELECT * FROM sessions WHERE id = ?;", (switched.session_id,)).fetchone()
    assert old_row["persona_snapshot_json"] == old_json
    assert old_row["persona_snapshot_sha256"] == old_hash
    assert updated.snapshot.canonical_json != old_json
    assert updated.snapshot.payload["effective_system_prompt"] == "更新后的系统提示。"


def test_switch_request_is_idempotent_and_cannot_change_target(tmp_path: Path) -> None:
    conn, service = _service(tmp_path)
    before = service.current()
    targets = [item for item in list_personas(conn) if item["id"] != before.session_core.persona.persona_id]
    first = service.switch_persona(
        targets[0]["id"],
        switch_request_id="same-request",
        expected_revision=before.revision,
    )
    replay = service.switch_persona(
        targets[0]["id"],
        switch_request_id="same-request",
        expected_revision=before.revision,
    )

    assert replay.idempotent_replay is True
    assert replay.context.session_id == first.context.session_id
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE switch_request_id = ?;", ("same-request",)).fetchone()[0] == 1
    with pytest.raises(SessionBindingError, match="switch_request_conflict"):
        service.switch_persona(
            targets[1]["id"],
            switch_request_id="same-request",
            expected_revision=replay.context.revision,
        )


def test_concurrent_switch_returns_conflict_without_second_write(tmp_path: Path, monkeypatch) -> None:
    conn, service = _service(tmp_path)
    before = service.current()
    target = next(item for item in list_personas(conn) if item["id"] != before.session_core.persona.persona_id)
    entered = threading.Event()
    release = threading.Event()
    original = service._switch_locked

    def delayed_switch(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_switch_locked", delayed_switch)
    thread = threading.Thread(
        target=lambda: service.switch_persona(
            target["id"],
            switch_request_id="first-concurrent",
            expected_revision=before.revision,
        )
    )
    thread.start()
    assert entered.wait(timeout=5)

    with pytest.raises(SessionBindingError, match="switch_in_progress"):
        service.switch_persona(
            target["id"],
            switch_request_id="second-concurrent",
            expected_revision=before.revision,
        )
    assert conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0] == 1

    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0] == 2


def test_snapshot_builder_uses_canonical_json_and_preregistered_cutpoints() -> None:
    persona = load_persona_file(_DEFAULT_PERSONA)
    proof = build_persona_snapshot(persona, source="test", created_at=1.0)

    assert proof.canonical_json == proof.canonical_json.strip()
    assert proof.payload["source"] == "test"
    assert len(proof.sha256) == 64


def test_bootstrap_restores_sqlite_canonical_instead_of_new_random_session(tmp_path: Path) -> None:
    first = bootstrap_ui_session(
        persona_path=_DEFAULT_PERSONA,
        session_id="first-bootstrap",
        data_dir=str(tmp_path),
        memory=False,
        model=str(tmp_path / "missing.gguf"),
    )
    try:
        assert first.session_id == "first-bootstrap"
        assert first.session_context_provider.capture().session_id == "first-bootstrap"
    finally:
        first.idle_detector.stop()
        if first.event_persistence is not None:
            first.event_persistence.shutdown()
        first.conn.close()

    restored = bootstrap_ui_session(
        persona_path=_DEFAULT_PERSONA,
        session_id="should-not-replace-canonical",
        data_dir=str(tmp_path),
        memory=False,
        model=str(tmp_path / "missing.gguf"),
    )
    try:
        assert restored.session_id == "first-bootstrap"
        assert restored.orchestrator.session_id == "first-bootstrap"
        assert restored.session_context_provider.capture().snapshot.sha256
    finally:
        restored.idle_detector.stop()
        if restored.event_persistence is not None:
            restored.event_persistence.shutdown()
        restored.conn.close()
