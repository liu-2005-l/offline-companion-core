"""摘要：P3-A1 桌面 canonical 会话与人格切换契约测试。"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import replace
from multiprocessing import get_context
from pathlib import Path
from queue import Empty

import pytest

import offline_companion.core.persona_constraint.assembly as persona_assembly
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.persona_constraint import (
    L1_PROMPT_CHARACTER_LIMIT,
    PersonaL1AssemblyError,
    assemble_l1_prompt,
    default_frozen_l1_mapping,
    finalize_l1_prompt,
    load_persona_constraint_assets,
)
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.runtime.storage_index.engine import SCHEMA_VERSION, connect
from offline_companion.shared.persona_snapshot import (
    PERSONA_SNAPSHOT_SOURCE_A1,
    PERSONA_SNAPSHOT_SOURCE_L1,
    PERSONA_SNAPSHOT_SOURCE_LEGACY,
    normalize_persona_snapshot_source,
)
from offline_companion.shell.ui_host.bootstrap import bootstrap_ui_session
from offline_companion.shell.ui_host.desktop.session_binding import (
    DesktopSessionBindingService,
    DesktopSessionContextProvider,
    SessionBindingError,
    build_persona_snapshot,
    validate_persona_snapshot,
)
from offline_companion.storage.persona_repo import (
    get_persona,
    list_personas,
    sync_builtin_personas,
    update_persona,
)

_DEFAULT_PERSONA = Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _constraint_payloads(assets) -> list[dict]:
    """摘要：生成带发布 manifest 追溯字段的五预设存储 payload。"""
    payloads = []
    for preset in assets.builtin_presets:
        payload = preset.storage_payload()
        payload["constraint_manifest_sha256"] = assets.manifest_sha256
        payload["constraint_manifest_version"] = str(assets.manifest.get("version") or "")
        payloads.append(payload)
    return payloads


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


def _bootstrap_after_restart(data_dir: str, result_queue) -> None:
    """摘要：在第二真实进程中走完整 UI bootstrap 并回报绑定状态。"""
    bundle = None
    try:
        bundle = bootstrap_ui_session(
            persona_path=_DEFAULT_PERSONA,
            session_id="must-not-replace-canonical",
            data_dir=data_dir,
            memory=False,
            model=str(Path(data_dir) / "missing.gguf"),
        )
        context = bundle.session_context_provider.capture()
        state = bundle.conn.execute(
            "SELECT active_session_id, revision FROM desktop_session_state WHERE id = 1;"
        ).fetchone()
        result_queue.put(
            {
                "session_id": bundle.session_id,
                "context_session_id": context.session_id,
                "orchestrator_session_id": bundle.orchestrator.session_id,
                "canonical_session_id": state["active_session_id"],
                "revision": state["revision"],
                "source": context.snapshot.source,
                "auto_stream_bound": bundle.auto_turn_orchestrator.event_stream is context.event_stream,
                "consent_stream_bound": bundle.orchestrator.consent_gateway.event_stream
                is context.event_stream,
                "consent_session_id": bundle.orchestrator.consent_gateway.active_session_id,
                "sample_lifecycle_bound": bundle.sample_lifecycle._event_stream is context.event_stream,
                "sample_retriever_bound": bundle.sample_retriever._event_stream is context.event_stream,
                "integrity": bundle.conn.execute("PRAGMA integrity_check;").fetchone()[0],
                "foreign_keys": bundle.conn.execute("PRAGMA foreign_key_check;").fetchall(),
            }
        )
    finally:
        if bundle is not None:
            bundle.idle_detector.stop()
            if bundle.event_persistence is not None:
                bundle.event_persistence.shutdown()
            bundle.conn.close()


def _replay_switch_after_restart(
    db_path: str,
    target_persona_id: str,
    request_id: str,
    expected_revision: int,
    result_queue,
) -> None:
    """摘要：在新进程中验证持久化幂等键的 replay 或冲突语义。"""
    conn = connect(Path(db_path))
    try:
        service = DesktopSessionBindingService(
            conn,
            context_provider=DesktopSessionContextProvider(),
            event_stream_manager=None,
            semantic_embed_func=None,
        )
        service.restore_or_create(
            preferred_session_id="ignored-after-restart",
            startup_persona=load_persona_file(_DEFAULT_PERSONA),
            title="重启恢复",
        )
        try:
            result = service.switch_persona(
                target_persona_id,
                switch_request_id=request_id,
                expected_revision=expected_revision,
            )
        except SessionBindingError as exc:
            result_queue.put({"status": exc.status, "code": exc.code})
        else:
            result_queue.put(
                {
                    "status": 200,
                    "session_id": result.context.session_id,
                    "idempotent_replay": result.idempotent_replay,
                    "session_count": conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0],
                }
            )
    finally:
        conn.close()


def _spawn_result(target, args: tuple) -> dict:
    """摘要：运行一个 spawn 子进程并读取其结构化结果。"""
    process_context = get_context("spawn")
    result_queue = process_context.Queue()
    process = process_context.Process(target=target, args=(*args, result_queue))
    process.start()
    process.join(timeout=30)
    assert not process.is_alive(), "子进程未在时限内结束"
    assert process.exitcode == 0
    try:
        result = result_queue.get(timeout=5)
    except Empty as exc:
        raise AssertionError("子进程未返回结果") from exc
    return result


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
    db_path = tmp_path / "companion.db"
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

    recovered = _spawn_result(_bootstrap_after_restart, (str(tmp_path),))

    assert recovered["revision"] == 2
    assert recovered["session_id"] != "initial"
    assert recovered["session_id"] == recovered["context_session_id"]
    assert recovered["session_id"] == recovered["orchestrator_session_id"]
    assert recovered["session_id"] == recovered["canonical_session_id"]
    assert recovered["session_id"] == recovered["consent_session_id"]
    assert recovered["source"] == PERSONA_SNAPSHOT_SOURCE_A1
    assert recovered["auto_stream_bound"] is True
    assert recovered["consent_stream_bound"] is True
    assert recovered["sample_lifecycle_bound"] is True
    assert recovered["sample_retriever_bound"] is True
    assert recovered["integrity"] == "ok"
    assert recovered["foreign_keys"] == []


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


def test_switch_request_idempotency_survives_process_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "restart-idempotency.db"
    conn = connect(db_path)
    service = DesktopSessionBindingService(
        conn,
        context_provider=DesktopSessionContextProvider(),
        event_stream_manager=None,
        semantic_embed_func=None,
    )
    before = service.restore_or_create(
        preferred_session_id="initial",
        startup_persona=load_persona_file(_DEFAULT_PERSONA),
        title="初始会话",
    )
    targets = [item for item in list_personas(conn) if item["id"] != before.session_core.persona.persona_id]
    first = service.switch_persona(
        targets[0]["id"],
        switch_request_id="restart-replay",
        expected_revision=before.revision,
    )
    first_session_id = first.context.session_id
    conn.close()

    replay = _spawn_result(
        _replay_switch_after_restart,
        (str(db_path), targets[0]["id"], "restart-replay", before.revision),
    )

    assert replay == {
        "status": 200,
        "session_id": first_session_id,
        "idempotent_replay": True,
        "session_count": 2,
    }

    conn = connect(db_path)
    service = DesktopSessionBindingService(
        conn,
        context_provider=DesktopSessionContextProvider(),
        event_stream_manager=None,
        semantic_embed_func=None,
    )
    current = service.restore_or_create(
        preferred_session_id="ignored",
        startup_persona=load_persona_file(_DEFAULT_PERSONA),
        title="再次恢复",
    )
    moved = service.switch_persona(
        targets[1]["id"],
        switch_request_id="move-canonical",
        expected_revision=current.revision,
    )
    conn.close()

    conflict = _spawn_result(
        _replay_switch_after_restart,
        (str(db_path), targets[0]["id"], "restart-replay", moved.context.revision),
    )

    assert conflict == {"status": 409, "code": "switch_request_conflict"}


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
    proof = build_persona_snapshot(persona, source=PERSONA_SNAPSHOT_SOURCE_A1, created_at=1.0)

    assert proof.canonical_json == proof.canonical_json.strip()
    assert proof.payload["source"] == PERSONA_SNAPSHOT_SOURCE_A1
    assert len(proof.sha256) == 64
    with pytest.raises(ValueError, match="unsupported persona snapshot source"):
        normalize_persona_snapshot_source("unknown_source")


def test_validated_switch_burns_display_name_into_l1_snapshot_with_final_budget(
    tmp_path: Path,
) -> None:
    assets = load_persona_constraint_assets(root_override=_REPO_ROOT)
    conn = connect(tmp_path / "l1-snapshot.db")
    sync_builtin_personas(conn, _constraint_payloads(assets))
    service = DesktopSessionBindingService(
        conn,
        context_provider=DesktopSessionContextProvider(),
        event_stream_manager=None,
        semantic_embed_func=None,
        constraint_assets=assets,
    )
    initial = service.restore_or_create(
        preferred_session_id="initial",
        startup_persona=load_persona_file(_DEFAULT_PERSONA),
        title="初始会话",
    )
    display_name = "甜" * 32
    MemoryLifecycleManager.add_memory_chunk(
        conn,
        f"助手自画像：名字 = {display_name}",
        session_id=initial.session_id,
        source="semantic_auto",
        meta={
            "memory_type": "agent_profile",
            "target": "assistant",
            "field": "display_name",
            "value": display_name,
        },
    )

    switched = service.switch_persona(
        "builtin_tianmei",
        switch_request_id="l1-snapshot",
        expected_revision=initial.revision,
    ).context
    persona = get_persona(conn, "builtin_tianmei")
    assert persona is not None
    assembled = assemble_l1_prompt(
        persona.persona_id,
        assets,
        default_frozen_l1_mapping(persona.persona_id, assets),
    )
    expected_prompt = finalize_l1_prompt(assembled, display_name)

    assert switched.snapshot.source == PERSONA_SNAPSHOT_SOURCE_L1
    assert switched.snapshot.payload["effective_system_prompt"] == expected_prompt
    assert switched.snapshot.payload["companion_display_name"] == display_name
    assert switched.snapshot.payload["manifest_hash"] == assets.manifest_sha256
    assert len(expected_prompt) == 652 <= L1_PROMPT_CHARACTER_LIMIT
    assert "{display_name}" not in expected_prompt


def test_t22_l1_source_switch_does_not_rewrite_legacy_snapshot_rows(tmp_path: Path) -> None:
    assets = load_persona_constraint_assets(root_override=_REPO_ROOT)
    conn = connect(tmp_path / "source-zero-drift.db")
    sync_builtin_personas(conn, _constraint_payloads(assets))
    service = DesktopSessionBindingService(
        conn,
        context_provider=DesktopSessionContextProvider(),
        event_stream_manager=None,
        semantic_embed_func=None,
        constraint_assets=assets,
    )
    initial = service.restore_or_create(
        preferred_session_id="initial",
        startup_persona=load_persona_file(_DEFAULT_PERSONA),
        title="初始会话",
    )
    old_rows: dict[str, tuple[str, str, str]] = {}
    for source in (PERSONA_SNAPSHOT_SOURCE_A1, "bootstrap", "persona_switch"):
        payload = {**initial.snapshot.payload, "source": source}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        session_id = f"historical-{source}"
        conn.execute(
            """
            INSERT INTO sessions(
                id, title, persona_id, created_at, updated_at,
                persona_snapshot_json, persona_snapshot_schema, persona_snapshot_sha256,
                persona_snapshot_source
            ) VALUES(?,?,?,?,?,?,?,?,?);
            """,
            (
                session_id,
                "历史会话",
                initial.session_core.persona.persona_id,
                1.0,
                1.0,
                canonical,
                initial.snapshot.schema,
                digest,
                source,
            ),
        )
        old_rows[session_id] = (canonical, source, digest)
    before_count = conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0]

    switched = service.switch_persona(
        "builtin_tianmei",
        switch_request_id="t22-new-source",
        expected_revision=initial.revision,
    ).context

    assert switched.session_id not in old_rows
    assert switched.snapshot.source == PERSONA_SNAPSHOT_SOURCE_L1
    assert conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0] == before_count + 1
    for session_id, expected in old_rows.items():
        row = conn.execute(
            """
            SELECT persona_snapshot_json, persona_snapshot_source, persona_snapshot_sha256
            FROM sessions WHERE id = ?;
            """,
            (session_id,),
        ).fetchone()
        assert tuple(row) == expected


def test_t23_missing_frozen_asset_rejects_before_switch_transaction(tmp_path: Path) -> None:
    assets = load_persona_constraint_assets(root_override=_REPO_ROOT)
    source_payloads = {
        name: copy.deepcopy(dict(payload)) for name, payload in assets.source_payloads.items()
    }
    dialogues = source_payloads["dimension_corpus"]["dimension_units"]["O"]["high"]["dialogues"]
    source_payloads["dimension_corpus"]["dimension_units"]["O"]["high"]["dialogues"] = [
        item for item in dialogues if item["id"] != "O_high_advice"
    ]
    broken_assets = replace(assets, source_payloads=source_payloads)
    conn = connect(tmp_path / "missing-asset.db")
    sync_builtin_personas(conn, _constraint_payloads(assets))
    service = DesktopSessionBindingService(
        conn,
        context_provider=DesktopSessionContextProvider(),
        event_stream_manager=None,
        semantic_embed_func=None,
        constraint_assets=broken_assets,
    )
    initial = service.restore_or_create(
        preferred_session_id="initial",
        startup_persona=load_persona_file(_DEFAULT_PERSONA),
        title="初始会话",
    )
    before_sessions = conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0]
    before_memories = conn.execute("SELECT COUNT(*) FROM memory_chunks;").fetchone()[0]

    with pytest.raises(SessionBindingError, match="switch_failed") as captured:
        service.switch_persona(
            "builtin_tianmei",
            switch_request_id="missing-asset",
            expected_revision=initial.revision,
        )

    assert isinstance(captured.value.__cause__, PersonaL1AssemblyError)
    assert conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0] == before_sessions
    assert conn.execute("SELECT COUNT(*) FROM memory_chunks;").fetchone()[0] == before_memories
    assert service.current().session_id == initial.session_id
    assert service.current().revision == initial.revision


def test_t23_burned_prompt_budget_rejects_before_switch_transaction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    assets = load_persona_constraint_assets(root_override=_REPO_ROOT)
    conn = connect(tmp_path / "over-budget.db")
    sync_builtin_personas(conn, _constraint_payloads(assets))
    service = DesktopSessionBindingService(
        conn,
        context_provider=DesktopSessionContextProvider(),
        event_stream_manager=None,
        semantic_embed_func=None,
        constraint_assets=assets,
    )
    initial = service.restore_or_create(
        preferred_session_id="initial",
        startup_persona=load_persona_file(_DEFAULT_PERSONA),
        title="初始会话",
    )
    display_name = "甜" * 32
    MemoryLifecycleManager.add_memory_chunk(
        conn,
        f"助手自画像：名字 = {display_name}",
        session_id=initial.session_id,
        source="semantic_auto",
        meta={
            "memory_type": "agent_profile",
            "target": "assistant",
            "field": "display_name",
            "value": display_name,
        },
    )
    before_sessions = conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0]
    before_memories = conn.execute("SELECT COUNT(*) FROM memory_chunks;").fetchone()[0]
    monkeypatch.setattr(persona_assembly, "L1_PROMPT_CHARACTER_LIMIT", 651)

    with pytest.raises(SessionBindingError, match="switch_failed") as captured:
        service.switch_persona(
            "builtin_tianmei",
            switch_request_id="over-budget",
            expected_revision=initial.revision,
        )

    assert isinstance(captured.value.__cause__, PersonaL1AssemblyError)
    assert "persona_l1_prompt_over_budget" in str(captured.value.__cause__)
    assert conn.execute("SELECT COUNT(*) FROM sessions;").fetchone()[0] == before_sessions
    assert conn.execute("SELECT COUNT(*) FROM memory_chunks;").fetchone()[0] == before_memories
    assert service.current().session_id == initial.session_id
    assert service.current().revision == initial.revision


@pytest.mark.parametrize(
    ("legacy_source", "expected_source"),
    [
        ("bootstrap", PERSONA_SNAPSHOT_SOURCE_A1),
        ("persona_switch", PERSONA_SNAPSHOT_SOURCE_A1),
        ("legacy_backfill", PERSONA_SNAPSHOT_SOURCE_LEGACY),
    ],
)
def test_v13_snapshot_source_values_migrate_and_rehash(
    tmp_path: Path,
    legacy_source: str,
    expected_source: str,
) -> None:
    db_path = tmp_path / "source-migration.db"
    conn, service = _service(tmp_path)
    context = service.current()
    payload = dict(context.snapshot.payload)
    payload["source"] = legacy_source
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    conn.execute(
        """
        UPDATE sessions
        SET persona_snapshot_json = ?, persona_snapshot_sha256 = ?, persona_snapshot_source = ?
        WHERE id = ?;
        """,
        (canonical, digest, legacy_source, context.session_id),
    )
    conn.execute("UPDATE meta SET value = '13' WHERE key = 'schema_version';")
    destination = sqlite3.connect(db_path)
    conn.backup(destination)
    destination.close()
    conn.close()

    migrated = connect(db_path)
    row = migrated.execute("SELECT * FROM sessions WHERE id = ?;", (context.session_id,)).fetchone()
    proof = validate_persona_snapshot(row)

    assert proof.source == expected_source
    assert proof.payload["source"] == expected_source
    assert proof.sha256 != digest or legacy_source == expected_source
    assert migrated.execute("SELECT value FROM meta WHERE key = 'schema_version';").fetchone()[0] == str(
        SCHEMA_VERSION
    )
    migrated.close()


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
        assert first.session_context_provider.capture().snapshot.source == PERSONA_SNAPSHOT_SOURCE_A1
        assert "档位:" not in first.session_context_provider.capture().snapshot.payload[
            "effective_system_prompt"
        ]
        assert first.conn.execute(
            "SELECT COUNT(*) FROM personas WHERE id LIKE 'builtin_%';"
        ).fetchone()[0] == 5
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


def test_validated_active_persona_uses_l1_source_for_first_bootstrap_session(
    tmp_path: Path,
) -> None:
    assets = load_persona_constraint_assets(root_override=_REPO_ROOT)
    conn = connect(tmp_path / "companion.db")
    sync_builtin_personas(conn, _constraint_payloads(assets))
    conn.execute("UPDATE personas SET active = 0;")
    conn.execute("UPDATE personas SET active = 1 WHERE id = ?;", ("builtin_tianmei",))
    conn.close()

    bundle = bootstrap_ui_session(
        persona_path=_DEFAULT_PERSONA,
        session_id="validated-first-bootstrap",
        data_dir=str(tmp_path),
        memory=False,
        model=str(tmp_path / "missing.gguf"),
    )
    try:
        snapshot = bundle.session_context_provider.capture().snapshot
        assert bundle.session_id == "validated-first-bootstrap"
        assert snapshot.source == PERSONA_SNAPSHOT_SOURCE_L1
        assert snapshot.payload["companion_display_name"] == "甜美"
        assert "我是甜美" in snapshot.payload["effective_system_prompt"]
        assert "{display_name}" not in snapshot.payload["effective_system_prompt"]
    finally:
        bundle.idle_detector.stop()
        if bundle.event_persistence is not None:
            bundle.event_persistence.shutdown()
        bundle.conn.close()
