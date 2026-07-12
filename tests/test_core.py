from __future__ import annotations

from pathlib import Path

import yaml

from offline_companion.core.memory_lifecycle.manager import (
    MemoryLifecycleManager,
    apply_bundle_import,
    prepare_export_bundle,
)
from offline_companion.core.safety_boundary.classifier import SafetyTier, classify_user_text
from offline_companion.runtime.storage_index.engine import append_message, connect, new_session
from offline_companion.runtime.storage_index.export_import import read_bundle_archive, write_bundle_archive
from offline_companion.shared.errors import OutboundDenied
from offline_companion.shared.types import OutboundPlan, OutboundScope, PrivacyMode
from offline_companion.shell.policy_engine.engine import ensure_outbound_allowed


def test_safety_from_fixtures() -> None:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "regression_dialogues.yaml"
    data = yaml.safe_load(root.read_text(encoding="utf-8"))
    for c in data["cases"]:
        if c["category"] != "safety":
            continue
        tier_map = {
            "ok": SafetyTier.OK,
            "crisis_self": SafetyTier.CRISIS_SELF,
            "crisis_other": SafetyTier.CRISIS_OTHER,
        }
        r = classify_user_text(c["user"])
        assert r.tier is tier_map[c["expect_tier"]]
        assert r.block_model is c["expect_block_model"]


def test_memory_write_and_search(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    new_session(conn, "s1", "default", title=None)
    MemoryLifecycleManager.add_memory_chunk(conn, "My cat is called Mimi", session_id="s1", source="test")
    hits = MemoryLifecycleManager.search_memory(conn, "Mimi", limit=5)
    assert hits and "Mimi" in hits[0].body


def test_export_import_roundtrip(tmp_path) -> None:
    db = tmp_path / "a.db"
    conn = connect(db)
    new_session(conn, "s1", "default", title="t")
    append_message(conn, "s1", "user", "hello", meta={})
    z = tmp_path / "out.zip"
    payload = prepare_export_bundle(conn, persona_snapshot={"id": "default", "name": "x"})
    write_bundle_archive(payload, z)
    db2 = tmp_path / "b.db"
    conn2 = connect(db2)
    loaded = read_bundle_archive(z)
    summary = apply_bundle_import(conn2, loaded, prefix_session="imp")
    assert summary["imported_sessions"] == 1
    row = conn2.execute("SELECT COUNT(*) AS c FROM messages;").fetchone()
    assert int(row["c"]) >= 1


def test_outbound_local_only_blocks() -> None:
    plan = OutboundPlan(
        payload_excerpt="x",
        will_send=["a"],
        will_not_send=["b"],
        purpose="p",
        scope=OutboundScope.THIS_TURN,
    )
    try:
        ensure_outbound_allowed(PrivacyMode.LOCAL_ONLY, plan, confirm=lambda p: True)
    except OutboundDenied:
        return
    raise AssertionError("expected block")


def test_memory_fixture_contains_expected() -> None:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "regression_dialogues.yaml"
    data = yaml.safe_load(root.read_text(encoding="utf-8"))
    for c in data["cases"]:
        if c["category"] != "memory":
            continue
        if "expect_memory_contains" not in c:
            continue
        assert c["expect_memory_contains"] in c["user"]


def test_outbound_ask_accepts_with_confirm() -> None:
    plan = OutboundPlan(
        payload_excerpt="x",
        will_send=["a"],
        will_not_send=["b"],
        purpose="p",
        scope=OutboundScope.THIS_TURN,
    )
    ensure_outbound_allowed(PrivacyMode.ASK_BEFORE_CLOUD, plan, confirm=lambda p: True)


def test_outbound_global_can_use_confirm_callable() -> None:
    plan = OutboundPlan(
        payload_excerpt="x",
        will_send=["a"],
        will_not_send=["b"],
        purpose="p",
        scope=OutboundScope.GLOBAL,
    )
    ensure_outbound_allowed(PrivacyMode.ASK_BEFORE_CLOUD, plan, confirm=lambda p: True)
