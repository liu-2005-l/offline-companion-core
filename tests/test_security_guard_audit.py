from __future__ import annotations

import pytest

from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.core.security import ApprovalAuditPair, GuardChain, ToolCallContext


def test_guard_chain_defaults_allow_and_dynamic_guard_cannot_be_reversed() -> None:
    chain = GuardChain()
    assert chain.evaluate(ToolCallContext("read_file")) == "allow"
    chain.add(lambda _context: "blocked")
    chain.add(lambda _context: None)
    assert chain.evaluate(ToolCallContext("read_file")) == "deny"


def test_guard_chain_fails_closed_for_exceptions_and_unknown_tools() -> None:
    chain = GuardChain()
    chain.add(lambda _context: (_ for _ in ()).throw(RuntimeError("boom")))
    assert chain.evaluate(ToolCallContext("read_file")) == "deny"
    assert chain.evaluate_tool(ToolCallContext("unknown_tool")) == "deny"
    assert GuardChain().evaluate_tool(ToolCallContext("write_file")) == "ask"


def test_approval_audit_pair_writes_asked_and_decided() -> None:
    stream = EventStream("session", build_default_registry())
    audit = ApprovalAuditPair(stream)

    assert audit.execute_pair("call-1", "network_request", "egress", lambda: "deny") == "deny"
    events = stream.get_events()
    assert [event.event_type for event in events] == ["consent/asked", "consent/decided"]
    assert events[0].payload["approval_id"] == events[1].payload["approval_id"]
    assert events[1].payload["outcome"] == "rejected"


def test_approval_audit_pair_rejects_unmatched_or_invalid_decisions() -> None:
    audit = ApprovalAuditPair(EventStream("session", build_default_registry()))
    with pytest.raises(ValueError):
        audit.decided("missing", "rejected")
    with pytest.raises(ValueError):
        audit.execute_pair("call-1", "write_file", None, lambda: "invalid")
