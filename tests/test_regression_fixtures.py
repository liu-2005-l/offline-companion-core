"""摘要：fixtures/regression_dialogues.yaml 结构化回归（Sprint 1）。"""

from __future__ import annotations

from pathlib import Path

import yaml

from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.recall import format_recall_prompt_block, recall
from offline_companion.core.safety_boundary.classifier import SafetyTier, classify_user_text
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator
from offline_companion.core.memory_lifecycle.triggers import load_triggers


def _load_cases() -> list[dict]:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "regression_dialogues.yaml"
    data = yaml.safe_load(root.read_text(encoding="utf-8"))
    return list(data.get("cases") or [])


def test_safety_fixtures_from_yaml() -> None:
    tier_map = {
        "ok": SafetyTier.OK,
        "crisis_self": SafetyTier.CRISIS_SELF,
        "crisis_other": SafetyTier.CRISIS_OTHER,
    }
    for c in _load_cases():
        if c.get("category") != "safety":
            continue
        if "expect_tier" not in c:
            continue
        r = classify_user_text(c["user"])
        assert r.tier is tier_map[c["expect_tier"]]
        assert r.block_model is c["expect_block_model"]


def test_memory_hash_fixtures_from_yaml() -> None:
    for c in _load_cases():
        if c.get("category") != "memory":
            continue
        if "expect_memory_contains" not in c:
            continue
        assert c["expect_memory_contains"] in c["user"]


def test_memory_recall_fixtures_from_yaml(tmp_path) -> None:
    for c in _load_cases():
        if c.get("category") != "memory_recall":
            continue
        conn = connect(tmp_path / f"recall_{c['id']}.db")
        new_session(conn, "s1", "default", title=None)
        MemoryLifecycleManager.add_memory_chunk(
            conn, c["memory_body"], session_id="s1", source="fixture"
        )
        hits = recall(conn, c["user_query"], limit=5)
        if c.get("expect_recall_empty"):
            assert not hits
            continue
        assert hits, c["id"]
        bodies = " ".join(h.body for h in hits)
        assert c["expect_recall_contains"] in bodies, c["id"]
        block = format_recall_prompt_block(hits)
        if "expect_block_contains" in c:
            assert c["expect_block_contains"] in block, c["id"]


def test_memory_lifecycle_del_fixture(tmp_path) -> None:
    for c in _load_cases():
        if c.get("category") != "memory_lifecycle":
            continue
        conn = connect(tmp_path / f"life_{c['id']}.db")
        new_session(conn, "s1", "default", title=None)
        MemoryLifecycleManager.add_memory_chunk(
            conn, c["memory_body"], session_id="s1", source="fixture"
        )
        hits = recall(conn, c["user_query"], limit=5)
        assert hits
        mid = hits[0].id
        assert MemoryLifecycleManager.delete_memory_chunk(conn, mid)
        after = recall(conn, c["user_query"], limit=5)
        if c.get("expect_recall_empty_after_del"):
            assert not after, c["id"]


def test_orchestrator_fixtures_from_yaml(tmp_path) -> None:
    tier_map = {
        "ok": SafetyTier.OK,
        "crisis_self": SafetyTier.CRISIS_SELF,
        "crisis_other": SafetyTier.CRISIS_OTHER,
    }
    persona_path = Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml"
    for c in _load_cases():
        if c.get("category") != "orchestrator":
            continue
        conn = connect(tmp_path / f"orch_{c['id']}.db")
        persona = load_persona_file(persona_path)
        new_session(conn, "s1", persona.persona_id, title=None)
        orch = ConversationOrchestrator(
            session_core=PersonaSessionCore(persona),
            backend=EchoBackend("fixture"),
            conn=conn,
            session_id="s1",
            triggers=load_triggers(),
        )
        if "user" in c and c.get("expect_blocked"):
            r = orch.run_turn(c["user"], memory_on=True)
            assert r.blocked_by_safety, c["id"]
            if "expect_tier" in c:
                assert r.safety_tier == tier_map[c["expect_tier"]].value, c["id"]
            continue
        if "remember" in c and "chat" in c:
            orch.run_turn(c["remember"], memory_on=True)
            r2 = orch.run_turn(c["chat"], memory_on=c.get("memory_on", True))
            if c.get("expect_no_recall"):
                assert not r2.memory_recalls, c["id"]
            elif c.get("expect_recall_keyword"):
                assert r2.memory_recalls, c["id"]
                kw = c["expect_recall_keyword"]
                assert any(kw in h.body for h in r2.memory_recalls), c["id"]


def test_knowledge_query_safety_fixtures_from_yaml() -> None:
    tier_map = {
        "ok": SafetyTier.OK,
        "crisis_self": SafetyTier.CRISIS_SELF,
        "crisis_other": SafetyTier.CRISIS_OTHER,
    }
    for c in _load_cases():
        if c.get("category") != "knowledge":
            continue
        if "query" not in c or "expect_tier" not in c:
            continue
        r = classify_user_text(c["query"])
        assert r.tier is tier_map[c["expect_tier"]], c["id"]
