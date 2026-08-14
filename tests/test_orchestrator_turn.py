"""ConversationOrchestrator 单轮编排测试。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from offline_companion.core.emotion_analyzer import EmotionClassifier
from offline_companion.core.local_reformatter.rule_reformatter import LOCAL_FALLBACK_PREFIX
from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.memory_lifecycle.triggers import load_triggers
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.core.safety_boundary.classifier import SafetyTier
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.shared.errors import CloudConnectorError
from offline_companion.shared.types import (
    CloudCompletionRequest,
    CloudCompletionResponse,
    ModelRoutingDecision,
    PrivacyMode,
)
from offline_companion.shell.outbound_manager.a3_gateway import UIHostConsentGateway
from offline_companion.shell.ui_host.conversation_orchestrator import ConversationOrchestrator


@dataclass
class _StubRouter:
    decision: ModelRoutingDecision
    selected_type: str

    def route(self, _query: str, *, privacy_mode: PrivacyMode) -> ModelRoutingDecision:
        return self.decision

    def model_type(self, _model_name: str) -> str | None:
        return self.selected_type


class _FailingStreamBackend(EchoBackend):
    def generate_stream(self, **_kwargs):
        yield "半条回复"
        raise RuntimeError("stream failed")


def _orch(tmp_path, db_name: str = "o.db") -> tuple[ConversationOrchestrator, object]:
    conn = connect(tmp_path / db_name)
    persona = load_persona_file(Path(__file__).resolve().parents[1] / "configs" / "personas" / "default.yaml")
    new_session(conn, "s1", persona.persona_id, title=None)
    orchestrator = ConversationOrchestrator(
        session_core=PersonaSessionCore(persona),
        backend=EchoBackend("test"),
        conn=conn,
        session_id="s1",
        triggers=load_triggers(),
    )
    return orchestrator, conn


def _routed_orch(
    tmp_path,
    *,
    decision: ModelRoutingDecision,
    selected_type: str,
    cloud_post=None,
    gateway: UIHostConsentGateway | None = None,
) -> tuple[ConversationOrchestrator, object]:
    orchestrator, conn = _orch(tmp_path, "routed.db")
    orchestrator.privacy_mode = PrivacyMode.ALWAYS_ASK
    orchestrator.model_router = _StubRouter(decision=decision, selected_type=selected_type)  # type: ignore[assignment]
    orchestrator.cloud_post = cloud_post
    orchestrator.consent_gateway = gateway
    return orchestrator, conn


def test_orchestrator_safety_block(tmp_path) -> None:
    orchestrator, conn = _orch(tmp_path)
    result = orchestrator.run_turn("我不想活了", memory_on=True)
    assert result.blocked_by_safety
    assert result.safety_tier == SafetyTier.CRISIS_SELF.value
    row = conn.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT 1;").fetchone()
    assert row["role"] == "assistant"


def test_stream_close_persists_partial_assistant_message(tmp_path) -> None:
    orchestrator, conn = _orch(tmp_path)
    stream = orchestrator.run_turn_stream("测试断连", memory_on=False)

    assert next(stream) == {"recall": 0}
    assert next(stream)["token"]
    stream.close()

    row = conn.execute(
        "SELECT role, content, status, meta_json FROM messages ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    assert row["role"] == "assistant"
    assert "测试断连" in row["content"]
    assert row["status"] == "partial"
    assert "stream_interrupted" in row["meta_json"]


def test_stream_error_persists_error_assistant_message(tmp_path) -> None:
    orchestrator, conn = _orch(tmp_path)
    orchestrator.backend = _FailingStreamBackend("failing")

    with pytest.raises(RuntimeError, match="stream failed"):
        list(orchestrator.run_turn_stream("测试异常", memory_on=False))

    row = conn.execute(
        "SELECT role, content, status FROM messages ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    assert row["role"] == "assistant"
    assert row["content"] == "半条回复"
    assert row["status"] == "error"


def test_orchestrator_remember_and_chat(tmp_path) -> None:
    orchestrator, conn = _orch(tmp_path)
    first = orchestrator.run_turn("#remember 我讨厌香菜", memory_on=True)
    assert first.memory_saved
    assert first.memory_only
    second = orchestrator.run_turn("晚上想点菜", memory_on=True)
    assert second.reply
    assert second.memory_recalls
    hits = MemoryLifecycleManager.recall(conn, "点菜", limit=3)
    assert hits


def test_orchestrator_cloud_degrade_prefix(tmp_path) -> None:
    orchestrator, _conn = _orch(tmp_path, "cloud.db")

    def fail(_req: CloudCompletionRequest) -> CloudCompletionResponse:
        raise CloudConnectorError("stub fail")

    result = orchestrator.run_cloud_turn("帮我写一句问候", purpose="test", memory_on=False, cloud_post=fail)
    assert result.cloud_degraded
    assert result.reply.startswith(LOCAL_FALLBACK_PREFIX)


def test_orchestrator_memory_off_no_recall_in_turn(tmp_path) -> None:
    orchestrator, _conn = _orch(tmp_path)
    orchestrator.run_turn("#remember 测试", memory_on=True)
    result = orchestrator.run_turn("测试", memory_on=False)
    assert result.reply
    assert not result.memory_recalls


def test_orchestrator_persists_emotion_column(tmp_path) -> None:
    orchestrator, conn = _orch(tmp_path)
    result = orchestrator.run_turn("我现在很焦虑，有点睡不着", memory_on=False)
    assert result.reply
    row = conn.execute(
        "SELECT role, emotion FROM messages WHERE role = 'user' ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    assert row is not None
    assert row["emotion"] == "anxiety"


def test_orchestrator_b0_failure_does_not_block_main_path(tmp_path, monkeypatch) -> None:
    orchestrator, conn = _orch(tmp_path)

    def fail(self, text: str):
        raise RuntimeError("b0 boom")

    monkeypatch.setattr(EmotionClassifier, "predict", fail)
    result = orchestrator.run_turn("今天天气不错", memory_on=False)
    assert result.reply
    row = conn.execute(
        "SELECT role, emotion FROM messages WHERE role = 'user' ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    assert row is not None
    assert row["emotion"] is None


def test_orchestrator_emotion_strategy_flows_to_reply(tmp_path) -> None:
    orchestrator, _conn = _orch(tmp_path)
    result = orchestrator.run_turn("我现在真的很难过", memory_on=False)
    assert result.reply
    assert "我会陪着你" in result.reply


def test_orchestrator_local_reply_runs_through_b4(tmp_path) -> None:
    orchestrator, conn = _orch(tmp_path)
    result = orchestrator.run_turn("我现在真的很难过！！", memory_on=False)
    assert result.reply
    assert "我会陪着你" in result.reply
    row = conn.execute(
        "SELECT role, meta_json FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    assert row is not None
    assert "reformatted" in row["meta_json"]


def test_orchestrator_routed_local_turn_uses_local_backend(tmp_path) -> None:
    decision = ModelRoutingDecision(
        selected_model="qwen2.5-1.5b-instruct-q4_k_m",
        fallback_model=None,
        requires_consent=False,
        reason="local_candidate_satisfies_threshold",
        estimated_input_tokens=64,
        estimated_output_tokens=192,
        estimated_cost=0.0,
    )
    orchestrator, conn = _routed_orch(tmp_path, decision=decision, selected_type="local", cloud_post=lambda _req: None)

    result = orchestrator.run_turn("请帮我总结一下今天的安排", memory_on=False)

    assert result.reply
    assert result.route_mode == "local"
    assert result.selected_model == "qwen2.5-1.5b-instruct-q4_k_m"
    row = conn.execute("SELECT meta_json FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;").fetchone()
    assert row is not None
    assert "selected_model" in row["meta_json"]


def test_orchestrator_routed_cloud_turn_waits_for_consent_then_resumes(tmp_path) -> None:
    decision = ModelRoutingDecision(
        selected_model="deepseek-v4",
        fallback_model="qwen2.5-1.5b-instruct-q4_k_m",
        requires_consent=True,
        reason="cloud_candidate_selected",
        estimated_input_tokens=128,
        estimated_output_tokens=256,
        estimated_cost=0.02,
    )

    def cloud_ok(_req: CloudCompletionRequest) -> CloudCompletionResponse:
        return CloudCompletionResponse(text="云端回答", raw={"provider": "stub"})

    gateway = UIHostConsentGateway()
    orchestrator, conn = _routed_orch(
        tmp_path,
        decision=decision,
        selected_type="cloud",
        cloud_post=cloud_ok,
        gateway=gateway,
    )

    pending = orchestrator.run_turn("请联网搜索后给我答案", memory_on=False)
    assert pending.requires_consent is True
    assert pending.consent_request_id
    assert conn.execute("SELECT COUNT(*) AS c FROM messages;").fetchone()["c"] == 0

    resumed = orchestrator.resume_pending_turn(pending.consent_request_id, allowed=True)
    assert resumed.reply
    assert "云端回答" in resumed.reply
    assert resumed.cloud_used is True
    assert resumed.cloud_degraded is False
    assert gateway.get_pending(pending.consent_request_id).decided is True


def test_orchestrator_routed_cloud_turn_denied_does_not_execute(tmp_path) -> None:
    decision = ModelRoutingDecision(
        selected_model="deepseek-v4",
        fallback_model="qwen2.5-1.5b-instruct-q4_k_m",
        requires_consent=True,
        reason="cloud_candidate_selected",
        estimated_input_tokens=128,
        estimated_output_tokens=256,
        estimated_cost=0.02,
    )
    gateway = UIHostConsentGateway()
    orchestrator, conn = _routed_orch(
        tmp_path,
        decision=decision,
        selected_type="cloud",
        cloud_post=lambda _req: CloudCompletionResponse(text="不会执行", raw={}),
        gateway=gateway,
    )

    pending = orchestrator.run_turn("请联网搜索后给我答案", memory_on=False)
    denied = orchestrator.resume_pending_turn(pending.consent_request_id, allowed=False)

    assert denied.reply == "已取消本轮云端请求。"
    assert conn.execute("SELECT COUNT(*) AS c FROM messages;").fetchone()["c"] == 0


def test_orchestrator_cloud_failure_uses_router_fallback_model(tmp_path) -> None:
    decision = ModelRoutingDecision(
        selected_model="deepseek-v4",
        fallback_model="qwen2.5-1.5b-instruct-q4_k_m",
        requires_consent=False,
        reason="cloud_candidate_selected",
        estimated_input_tokens=128,
        estimated_output_tokens=256,
        estimated_cost=0.02,
    )

    def fail(_req: CloudCompletionRequest) -> CloudCompletionResponse:
        raise CloudConnectorError("cloud down")

    orchestrator, conn = _routed_orch(tmp_path, decision=decision, selected_type="cloud", cloud_post=fail)

    result = orchestrator.run_turn("给我一个需要联网的答案", memory_on=False)

    assert result.cloud_used is True
    assert result.cloud_degraded is True
    assert result.fallback_model == "qwen2.5-1.5b-instruct-q4_k_m"
    row = conn.execute("SELECT meta_json FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;").fetchone()
    assert row is not None
    assert "executed_fallback_model" in row["meta_json"]


def test_local_failure_auto_routes_cloud_without_using_local_backend(tmp_path) -> None:
    decision = ModelRoutingDecision(
        selected_model="qwen2.5-1.5b-instruct-q4_k_m",
        fallback_model=None,
        requires_consent=False,
        reason="local_candidate_satisfies_threshold",
        estimated_input_tokens=64,
        estimated_output_tokens=192,
        estimated_cost=0.0,
    )
    cloud_calls: list[CloudCompletionRequest] = []

    def cloud_ok(request: CloudCompletionRequest) -> CloudCompletionResponse:
        cloud_calls.append(request)
        return CloudCompletionResponse(text="云端可用", raw={})

    orchestrator, _conn = _routed_orch(
        tmp_path,
        decision=decision,
        selected_type="local",
        cloud_post=cloud_ok,
    )
    orchestrator.backend.generate = lambda **_kwargs: pytest.fail("不应调用本地后端")
    orchestrator.backend_mode = "cloud_fallback"
    orchestrator.local_available = False
    orchestrator.cloud_available = True
    orchestrator.privacy_mode = PrivacyMode.AUTO_ROUTE_CLOUD
    orchestrator.cloud_model_provider = lambda: {
        "id": "cloud-ready",
        "endpoint": "https://example.test/v1/chat/completions",
        "api_key": "secret",
        "model_name": "cloud-model",
    }

    result = orchestrator.run_turn("你好", memory_on=False)

    assert result.cloud_used is True
    assert result.fallback_model is None
    assert len(cloud_calls) == 1


def test_local_failure_local_only_returns_no_backend_without_outbound(tmp_path) -> None:
    decision = ModelRoutingDecision(
        selected_model="deepseek-v4",
        fallback_model=None,
        requires_consent=False,
        reason="cloud_candidate_selected",
        estimated_input_tokens=64,
        estimated_output_tokens=192,
        estimated_cost=0.01,
    )
    cloud_calls: list[CloudCompletionRequest] = []
    orchestrator, _conn = _routed_orch(
        tmp_path,
        decision=decision,
        selected_type="cloud",
        cloud_post=lambda request: cloud_calls.append(request),
    )
    orchestrator.backend.generate = lambda **_kwargs: pytest.fail("不应调用本地后端")
    orchestrator.backend_mode = "no_backend"
    orchestrator.local_available = False
    orchestrator.cloud_available = True
    orchestrator.privacy_mode = PrivacyMode.LOCAL_ONLY

    result = orchestrator.run_turn("你好", memory_on=False)
    stream = list(orchestrator.run_turn_stream("再试一次", memory_on=False))

    assert result.route_mode == "none"
    assert "LOCAL_ONLY" in str(result.reply)
    assert stream[-1]["turn_result"].route_mode == "none"
    assert cloud_calls == []
