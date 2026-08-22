"""任务拆解样本库存储与生命周期测试。"""

from __future__ import annotations

import json

import pytest

from offline_companion.core.decomposition_sample_library import (
    PLANSTEP_SCHEMA_VERSION,
    SAMPLE_MEMORY_TYPE,
    InvalidSampleTransitionError,
    SampleLifecycleManager,
    SampleMaintenance,
    SampleRepository,
    SampleRetriever,
    SampleShot,
    SampleState,
    VerifyKind,
)
from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.core.plan_orchestrator import (
    InMemoryPlanStore,
    PlanContext,
    PlanOrchestrator,
    PlanStep,
    StepStatus,
)
from offline_companion.runtime.storage_index.engine import connect


def _step(**overrides):
    payload = {
        "step_id": "step_1",
        "skill_id": "file_read:inspect",
        "result_key": "result_1",
        "payload": {"description": "检查现有模块"},
        "title": "检查模块",
        "description": "检查现有模块和数据流",
        "expected_output": "模块清单",
        "verification": "确认模块清单完整",
        "completion_criteria": "所有关联模块均已列出",
        "stage": "planning",
        "files": ("C:/private/project.py",),
    }
    payload.update(overrides)
    return PlanStep(**payload)


def _successful_plan_result(step, _context):
    if step.stage == "planning":
        return {"result": "完成模块、数据流和风险分析"}
    if step.stage == "tdd":
        return {"result": "测试 passed"}
    if step.stage == "implementation":
        return {"result": "修改 src/app.py 完成实现"}
    if step.stage == "verification":
        return {"result": "验证 output ok"}
    return {"result": "完成"}


@pytest.fixture
def sample_library(tmp_path):
    conn = connect(tmp_path / "samples.db")
    stream = EventStream("samples", build_default_registry())
    repository = SampleRepository(conn)
    lifecycle = SampleLifecycleManager(repository, stream)
    return conn, stream, repository, lifecycle


def test_create_candidate_reuses_memory_chunks_and_emits_event(sample_library) -> None:
    conn, stream, repository, lifecycle = sample_library
    sample = lifecycle.create_candidate(
        "分析任务拆解链路",
        [_step()],
        source="llm",
        plan_id="plan_1",
        provenance_sample_ids=["7", "8"],
    )

    row = conn.execute(
        "SELECT content, body, memory_type, status, source, metadata FROM memory_chunks WHERE id = ?;",
        (int(sample.sample_id),),
    ).fetchone()
    assert row["content"] == "分析任务拆解链路"
    assert row["body"] == "分析任务拆解链路"
    assert row["memory_type"] == SAMPLE_MEMORY_TYPE
    assert row["status"] == "active"
    assert row["source"] == "plan_decomposer"
    assert repository.get(sample.sample_id) == sample
    event = stream.get_events()[-1]
    assert event.event_type == "sample/created"
    assert event.payload["sample_id"] == sample.sample_id
    assert event.payload["provenance"] == {"sample_ids": ["7", "8"]}


def test_repository_permanently_deletes_sample_without_event(sample_library) -> None:
    """摘要：永久删除直接移除样本行，且不追加删除留痕事件。"""

    conn, stream, repository, lifecycle = sample_library
    sample = lifecycle.create_candidate(
        "删除无效拆解范例",
        [_step()],
        source="llm",
    )
    event_count = len(stream.get_events())

    assert repository.delete(sample.sample_id) is True
    assert repository.get(sample.sample_id) is None
    assert repository.delete(sample.sample_id) is False
    assert len(stream.get_events()) == event_count
    row = conn.execute(
        "SELECT 1 FROM memory_chunks WHERE id = ?;",
        (int(sample.sample_id),),
    ).fetchone()
    assert row is None


def _verified_sample(lifecycle, description: str, *, tool: str, auto: bool = False):
    candidate = lifecycle.create_candidate(
        description,
        [_step(skill_id=f"{tool}:run")],
        source="llm",
    )
    if auto:
        return lifecycle.auto_verify(candidate.sample_id, reason="plan_all_green")
    return lifecycle.confirm(candidate.sample_id)


def test_retriever_only_reads_verified_active_samples(sample_library, monkeypatch) -> None:
    conn, stream, repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("候选 文件 检索", [_step()], source="rule")
    verified = _verified_sample(lifecycle, "验证 文件 检索", tool="file_read")
    stale = _verified_sample(lifecycle, "过时 文件 检索", tool="web", auto=True)
    lifecycle.mark_stale(stale.sample_id, reason="tool_disabled")
    rejected = _verified_sample(lifecycle, "丢弃 文件 检索", tool="shell")
    lifecycle.reject(rejected.sample_id)
    archived = _verified_sample(lifecycle, "归档 文件 检索", tool="python", auto=True)
    lifecycle.archive(archived.sample_id, reason="cold")
    retriever = SampleRetriever(conn, repository, stream)
    monkeypatch.setattr(
        retriever,
        "_fused_similarities",
        lambda goal, samples: {sample.sample_id: 0.8 for sample in samples},
    )

    shots = retriever.retrieve("文件检索")

    assert [shot.sample_id for shot in shots] == [verified.sample_id]
    assert candidate.sample_id not in {shot.sample_id for shot in shots}


def test_retriever_applies_similarity_bounds_and_diverse_top_two(sample_library, monkeypatch) -> None:
    conn, stream, repository, lifecycle = sample_library
    low = _verified_sample(lifecycle, "低相似", tool="low")
    exact = _verified_sample(lifecycle, "完全重复", tool="exact")
    first = _verified_sample(lifecycle, "文件任务", tool="file")
    same_domain = _verified_sample(lifecycle, "另一文件任务", tool="file")
    different = _verified_sample(lifecycle, "网页任务", tool="web")
    retriever = SampleRetriever(conn, repository, stream)
    similarities = {
        low.sample_id: 0.34,
        exact.sample_id: 0.99,
        first.sample_id: 0.90,
        same_domain.sample_id: 0.89,
        different.sample_id: 0.88,
    }
    monkeypatch.setattr(retriever, "_fused_similarities", lambda goal, samples: similarities)

    shots = retriever.retrieve("组合任务")

    assert [shot.sample_id for shot in shots] == [first.sample_id, different.sample_id]
    assert len(shots) <= 2


def test_user_verified_quality_exceeds_auto_verified(sample_library) -> None:
    _conn, _stream, _repository, lifecycle = sample_library
    user_sample = _verified_sample(lifecycle, "用户样本", tool="file")
    auto_sample = _verified_sample(lifecycle, "自动样本", tool="web", auto=True)

    user_quality = SampleRetriever._quality(user_sample, now=user_sample.updated_at)
    auto_quality = SampleRetriever._quality(auto_sample, now=auto_sample.updated_at)

    assert user_quality > auto_quality


def test_retriever_crops_fields_and_enforces_token_budget(sample_library) -> None:
    _conn, _stream, _repository, lifecycle = sample_library
    long_step = _step(
        title="标" * 100,
        description="描" * 200,
        verification="验" * 120,
        expected_output="产" * 120,
    )
    sample = lifecycle.confirm(
        lifecycle.create_candidate("任务" * 150, [long_step, long_step, long_step], source="llm").sample_id
    )

    shot = SampleRetriever._crop_sample(sample, similarity=0.8, score=0.7)

    assert isinstance(shot, SampleShot)
    assert shot.token_count <= 400
    assert len(shot.task_description) <= 200
    assert all(len(step["description"]) <= 120 for step in shot.steps)
    assert all(len(step["verification"]) <= 80 for step in shot.steps)
    assert all(len(step["expected_output"]) <= 80 for step in shot.steps)


def test_retriever_updates_usage_and_emits_injected_event(sample_library, monkeypatch) -> None:
    conn, stream, repository, lifecycle = sample_library
    sample = _verified_sample(lifecycle, "文件检索", tool="file")
    retriever = SampleRetriever(conn, repository, stream)
    monkeypatch.setattr(
        retriever,
        "_fused_similarities",
        lambda goal, samples: {item.sample_id: 0.8 for item in samples},
    )

    shots = retriever.retrieve("查找文件")

    updated = repository.get(sample.sample_id)
    assert shots and updated is not None
    assert updated.usage["injected_count"] == 1
    assert updated.usage["last_hit_at"] is not None
    event = stream.get_events()[-1]
    assert event.event_type == "sample/injected"
    assert event.payload["sample_id"] == sample.sample_id


def test_candidate_serializes_only_safe_few_shot_fields(sample_library) -> None:
    conn, _stream, _repository, lifecycle = sample_library
    sample = lifecycle.create_candidate("检查隐私字段", [_step()], source="rule")
    metadata = json.loads(
        conn.execute("SELECT metadata FROM memory_chunks WHERE id = ?;", (int(sample.sample_id),)).fetchone()[
            "metadata"
        ]
    )

    assert metadata["schema_version"] == PLANSTEP_SCHEMA_VERSION
    assert set(metadata["steps"][0]) == {
        "title",
        "description",
        "expected_output",
        "verification",
        "completion_criteria",
        "stage",
        "subagent_type",
    }
    serialized = json.dumps(metadata["steps"], ensure_ascii=False)
    assert "files" not in serialized
    assert "private" not in serialized
    assert metadata["tool_refs"] == ["file_read"]


def test_create_candidate_validates_required_content(sample_library) -> None:
    _conn, _stream, _repository, lifecycle = sample_library
    with pytest.raises(ValueError, match="description"):
        lifecycle.create_candidate(" ", [_step()], source="llm")
    with pytest.raises(ValueError, match="steps"):
        lifecycle.create_candidate("任务", [], source="llm")
    with pytest.raises(ValueError, match="source"):
        lifecycle.create_candidate("任务", [_step()], source="unknown")


def test_list_samples_filters_business_state(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("候选任务", [_step()], source="rule")
    verified = lifecycle.create_candidate("验证任务", [_step()], source="rule")
    lifecycle.confirm(verified.sample_id)

    assert [item.sample_id for item in repository.list_samples(sample_state="candidate")] == [
        candidate.sample_id
    ]
    assert [item.sample_id for item in repository.list_samples(sample_state="verified")] == [
        verified.sample_id
    ]


def test_list_samples_filters_and_paginates_in_sql(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    created_ids: list[str] = []
    for index in range(125):
        suffix = f"unique{index:04d}value"
        sample = lifecycle.create_candidate(
            f"task{suffix}",
            [
                _step(
                    title=f"title{suffix}",
                    description=f"description{suffix}",
                    expected_output=f"output{suffix}",
                    verification=f"verification{suffix}",
                    completion_criteria=f"criteria{suffix}",
                    stage=f"stage{suffix}",
                )
            ],
            source="rule",
        )
        created_ids.append(sample.sample_id)

    first_page = repository.list_samples(sample_state="candidate", limit=100, offset=0)
    second_page = repository.list_samples(sample_state="candidate", limit=100, offset=100)

    assert len(first_page) == 100
    assert len(second_page) == 25
    assert {sample.sample_id for sample in [*first_page, *second_page]} == set(created_ids)
    assert repository.count_samples(sample_state="candidate") == 125


def test_confirm_promotes_candidate_to_user_verified(sample_library) -> None:
    _conn, stream, _repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("用户确认", [_step()], source="rule")
    confirmed = lifecycle.confirm(candidate.sample_id)

    assert confirmed.sample_state == SampleState.VERIFIED.value
    assert confirmed.verify_kind == VerifyKind.USER.value
    assert confirmed.last_actor == "user"
    assert stream.get_events()[-1].event_type == "sample/verified"


def test_auto_verify_only_accepts_candidate(sample_library) -> None:
    _conn, _stream, _repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("自动确认", [_step()], source="llm")
    verified = lifecycle.auto_verify(candidate.sample_id, reason="plan_all_green")
    assert verified.verify_kind == VerifyKind.AUTO.value

    with pytest.raises(InvalidSampleTransitionError, match="auto verify"):
        lifecycle.auto_verify(candidate.sample_id, reason="again")


def test_reject_and_restore_preserve_record(sample_library) -> None:
    conn, stream, repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("用户丢弃", [_step()], source="rule")
    rejected = lifecycle.reject(candidate.sample_id)
    restored = lifecycle.restore(candidate.sample_id)

    assert rejected.sample_state == SampleState.REJECTED.value
    assert rejected.rejected_by == "user"
    assert restored.sample_state == SampleState.CANDIDATE.value
    assert restored.status == "active"
    assert repository.get(candidate.sample_id) is not None
    assert conn.execute("SELECT COUNT(*) AS c FROM memory_chunks WHERE id = ?;", (int(candidate.sample_id),)).fetchone()[
        "c"
    ] == 1
    assert [event.event_type for event in stream.get_events()][-2:] == ["sample/rejected", "sample/restored"]


def test_archive_cancels_db_row_and_user_can_restore(sample_library) -> None:
    _conn, _stream, _repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("冷归档", [_step()], source="rule")
    archived = lifecycle.archive(candidate.sample_id, reason="cold_90_days")
    restored = lifecycle.restore(candidate.sample_id)

    assert archived.sample_state == SampleState.ARCHIVED.value
    assert archived.status == "cancelled"
    assert restored.sample_state == SampleState.CANDIDATE.value
    assert restored.status == "active"


def test_automatic_signals_cannot_override_user_authority(sample_library) -> None:
    _conn, _stream, _repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("用户权威", [_step()], source="rule")
    user_verified = lifecycle.confirm(candidate.sample_id)

    with pytest.raises(InvalidSampleTransitionError, match="override"):
        lifecycle.mark_stale(user_verified.sample_id, reason="tool_missing")
    with pytest.raises(InvalidSampleTransitionError, match="user_verified"):
        lifecycle.archive(user_verified.sample_id, reason="cold")
    with pytest.raises(InvalidSampleTransitionError, match="actor=user"):
        lifecycle.reject(user_verified.sample_id, actor="auto")


def test_auto_verified_can_be_staled_with_reason(sample_library) -> None:
    _conn, stream, _repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("自动降级", [_step()], source="llm")
    lifecycle.auto_verify(candidate.sample_id, reason="plan_all_green")
    stale = lifecycle.mark_stale(candidate.sample_id, reason="consecutive_failure")

    assert stale.sample_state == SampleState.STALE.value
    assert stale.verify_kind is None
    assert stale.stale_reason == "consecutive_failure"
    assert stream.get_events()[-1].payload["reason"] == "consecutive_failure"


def test_plan_outcome_tracks_streak_and_stales_auto_verified(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("反馈闭环", [_step()], source="llm")
    verified = lifecycle.auto_verify(candidate.sample_id, reason="plan_all_green")
    repository.record_injection(verified.sample_id)
    repository.record_injection(verified.sample_id)
    repository.record_injection(verified.sample_id)

    lifecycle.record_plan_outcome(verified.sample_id, completed=False)
    lifecycle.record_plan_outcome(verified.sample_id, completed=False)
    recovered = lifecycle.record_plan_outcome(verified.sample_id, completed=True)
    assert recovered.usage["consecutive_failures"] == 0

    lifecycle.record_plan_outcome(verified.sample_id, completed=False)
    lifecycle.record_plan_outcome(verified.sample_id, completed=False)
    stale = lifecycle.record_plan_outcome(verified.sample_id, completed=False)

    assert stale.sample_state == SampleState.STALE.value
    assert stale.stale_reason == "consecutive_failure"
    assert stale.usage["plan_completed"] == 1
    assert stale.usage["plan_failed"] == 5
    assert repository.get(verified.sample_id) == stale


def test_plan_outcome_never_overrides_user_verified(sample_library) -> None:
    _conn, _stream, _repository, lifecycle = sample_library
    sample = lifecycle.confirm(
        lifecycle.create_candidate("用户权威反馈", [_step()], source="rule").sample_id
    )

    for _ in range(3):
        sample = lifecycle.record_plan_outcome(sample.sample_id, completed=False)

    assert sample.sample_state == SampleState.VERIFIED.value
    assert sample.verify_kind == VerifyKind.USER.value
    assert sample.usage["consecutive_failures"] == 3


def test_failed_outcomes_reduce_auto_verified_quality_before_stale(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    sample = lifecycle.auto_verify(
        lifecycle.create_candidate("质量降权", [_step()], source="llm").sample_id,
        reason="plan_all_green",
    )
    repository.record_injection(sample.sample_id)
    repository.record_injection(sample.sample_id)
    sample = repository.get(sample.sample_id)
    assert sample is not None
    baseline = SampleRetriever._quality(sample, now=sample.updated_at)

    lifecycle.record_plan_outcome(sample.sample_id, completed=False)
    updated = lifecycle.record_plan_outcome(sample.sample_id, completed=False)

    assert updated.sample_state == SampleState.VERIFIED.value
    assert updated.verify_kind == VerifyKind.AUTO.value
    assert SampleRetriever._quality(updated, now=updated.updated_at) < baseline


def test_auto_verify_candidate_is_idempotent_for_user_state(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("候选全绿", [_step()], source="llm")
    lifecycle.record_plan_outcome(candidate.sample_id, completed=True)
    still_candidate = lifecycle.auto_verify_candidate(candidate.sample_id)
    lifecycle.record_plan_outcome(candidate.sample_id, completed=True)
    auto_verified = lifecycle.auto_verify_candidate(candidate.sample_id)
    user_verified = lifecycle.confirm(auto_verified.sample_id)

    unchanged = lifecycle.auto_verify_candidate(user_verified.sample_id)

    assert still_candidate.sample_state == SampleState.CANDIDATE.value
    assert repository.get(candidate.sample_id).usage["plan_completed"] == 2
    assert auto_verified.verify_kind == VerifyKind.AUTO.value
    assert unchanged.verify_kind == VerifyKind.USER.value


def test_plan_terminal_feedback_closes_real_sample_lifecycle(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    provenance = lifecycle.auto_verify(
        lifecycle.create_candidate("历史范例", [_step()], source="llm").sample_id,
        reason="plan_all_green",
    )
    candidate = lifecycle.create_candidate(
        "本次拆解",
        [_step(skill_id="chat")],
        source="llm",
        provenance_sample_ids=[provenance.sample_id],
    )
    step = _step(skill_id="chat", stage=None)
    context = PlanContext(
        plan_id="plan-real-feedback",
        steps={step.step_id: step},
        step_status={step.step_id: StepStatus.PENDING},
        context_vars={
            "decomposition": {
                "sample_ids": [provenance.sample_id],
                "candidate_sample_id": candidate.sample_id,
            }
        },
    )
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), sample_lifecycle=lifecycle)

    completed = orchestrator.execute_next(
        context,
        invoke_skill=lambda current_step, current_context: "完成",
    )

    updated_provenance = repository.get(provenance.sample_id)
    updated_candidate = repository.get(candidate.sample_id)
    assert completed.plan_status == "completed"
    assert updated_provenance is not None
    assert updated_provenance.usage["plan_completed"] == 1
    assert updated_candidate is not None
    assert updated_candidate.sample_state == SampleState.CANDIDATE.value
    assert updated_candidate.usage["plan_completed"] == 1

    second_context = PlanContext(
        plan_id="plan-real-feedback-second",
        steps={step.step_id: step},
        step_status={step.step_id: StepStatus.PENDING},
        context_vars={
            "decomposition": {
                "sample_ids": [candidate.sample_id],
                "candidate_sample_id": candidate.sample_id,
            }
        },
    )
    orchestrator.execute_next(
        second_context,
        invoke_skill=lambda current_step, current_context: "再次完成",
    )
    twice_completed = repository.get(candidate.sample_id)
    assert twice_completed is not None
    assert twice_completed.usage["plan_completed"] == 2
    assert twice_completed.sample_state == SampleState.VERIFIED.value
    assert twice_completed.verify_kind == VerifyKind.AUTO.value


def test_edit_any_state_becomes_user_verified_and_resets_statistics(sample_library) -> None:
    _conn, stream, repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("旧描述", [_step()], source="llm")
    lifecycle.reject(candidate.sample_id)
    repository.mutate_metadata(
        candidate.sample_id,
        lambda metadata: metadata.update(
            usage={
                "injected_count": 4,
                "last_hit_at": 123.0,
                "plan_completed": 1,
                "plan_failed": 3,
            }
        ),
    )
    before = repository.get(candidate.sample_id)

    edited = lifecycle.edit(
        candidate.sample_id,
        task_description="新描述",
        steps=[_step(title="新步骤", description="新的拆解内容")],
    )

    assert edited.task_description == "新描述"
    assert edited.steps[0]["title"] == "新步骤"
    assert edited.sample_state == SampleState.VERIFIED.value
    assert edited.verify_kind == VerifyKind.USER.value
    assert edited.usage == SampleRepository.empty_usage()
    assert edited.version == before.version + 1
    assert edited.content_hash != before.content_hash
    assert edited.rejected_by is None
    assert stream.get_events()[-1].payload["reason"] == "user_edit"


def test_invalid_restore_and_duplicate_reject_are_rejected(sample_library) -> None:
    _conn, _stream, _repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("非法迁移", [_step()], source="rule")
    with pytest.raises(InvalidSampleTransitionError, match="restore"):
        lifecycle.restore(candidate.sample_id)
    lifecycle.reject(candidate.sample_id)
    with pytest.raises(InvalidSampleTransitionError, match="already rejected"):
        lifecycle.reject(candidate.sample_id)


def test_exact_duplicate_merges_usage_without_new_row(sample_library) -> None:
    conn, _stream, repository, lifecycle = sample_library
    first = lifecycle.create_candidate("相同拆解", [_step()], source="llm")
    merged = lifecycle.create_candidate("相同拆解", [_step()], source="llm")

    assert merged.sample_id == first.sample_id
    assert repository.count_samples() == 1
    assert merged.usage["similarity_sum"] == pytest.approx(1.0)
    assert merged.usage["similarity_count"] == 1
    assert conn.execute("SELECT COUNT(*) AS count FROM memory_chunks;").fetchone()["count"] == 1


def test_near_duplicate_over_threshold_merges(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    first = lifecycle.create_candidate(
        "整理发布清单 alpha beta gamma delta epsilon",
        [_step(title="核对版本 alpha beta gamma delta epsilon")],
        source="llm",
    )
    merged = lifecycle.create_candidate(
        "整理发布清单 alpha beta gamma delta epsilon zeta",
        [_step(title="核对版本 alpha beta gamma delta epsilon")],
        source="llm",
    )

    assert merged.sample_id == first.sample_id
    assert repository.count_samples() == 1
    assert merged.usage["similarity_count"] == 1
    assert 0.95 < merged.usage["similarity_sum"] < 1.0


def test_duplicate_merge_does_not_restore_rejected_sample(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    first = lifecycle.create_candidate("拒绝样本保持拒绝", [_step()], source="rule")
    lifecycle.reject(first.sample_id)

    merged = lifecycle.create_candidate("拒绝样本保持拒绝", [_step()], source="rule")

    assert merged.sample_id == first.sample_id
    assert merged.sample_state == SampleState.REJECTED.value
    assert merged.status == "active"
    assert merged.usage["similarity_count"] == 1
    assert repository.count_samples(sample_state="rejected") == 1


def test_merged_sample_receives_terminal_plan_attribution(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    orchestrator = PlanOrchestrator(InMemoryPlanStore(), sample_lifecycle=lifecycle)
    first_steps = orchestrator.decide("分析重复计划终态归因")
    first_context = orchestrator.create_plan("merge-plan-1", first_steps)
    while not first_context.is_terminal():
        first_context = orchestrator.execute_next(
            first_context,
            invoke_skill=_successful_plan_result,
        )
    first_sample_id = first_context.context_vars["decomposition"]["candidate_sample_id"]

    second_steps = orchestrator.decide("分析重复计划终态归因")
    second_context = orchestrator.create_plan("merge-plan-2", second_steps)
    completed = second_context
    while not completed.is_terminal():
        completed = orchestrator.execute_next(
            completed,
            invoke_skill=_successful_plan_result,
        )

    assert completed.context_vars["decomposition"]["sample_ids"] == [first_sample_id]
    assert completed.context_vars["decomposition"]["candidate_sample_id"] == first_sample_id
    updated = repository.get(first_sample_id)
    assert updated is not None
    assert updated.usage["plan_completed"] == 2
    assert updated.sample_state == SampleState.VERIFIED.value
    assert updated.verify_kind == VerifyKind.AUTO.value
    assert repository.count_samples() == 1


def test_record_injection_tracks_timestamp_and_similarity(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    sample = lifecycle.create_candidate("注入时间", [_step()], source="llm")

    updated = repository.record_injection(sample.sample_id, hit_at=1234.0, similarity=0.8)

    assert updated.usage["last_injected_at"] == 1234.0
    assert updated.usage["similarity_sum"] == pytest.approx(0.8)
    assert updated.usage["similarity_count"] == 1


def test_sample_maintenance_archives_cold_but_not_missing_timestamp(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    cold = lifecycle.auto_verify(
        lifecycle.create_candidate("冷样本", [_step()], source="llm").sample_id,
        reason="plan_all_green",
    )
    missing = lifecycle.auto_verify(
        lifecycle.create_candidate("缺失时间样本", [_step(title="不同步骤")], source="llm").sample_id,
        reason="plan_all_green",
    )
    repository.record_injection(cold.sample_id, hit_at=1000.0, similarity=0.6)
    maintenance = SampleMaintenance(repository, lifecycle)

    actions = maintenance.run(now=1000.0 + 91 * 86400.0)

    assert f"{cold.sample_id}:cold" in actions
    assert repository.get(cold.sample_id).sample_state == SampleState.ARCHIVED.value
    assert repository.get(missing.sample_id).sample_state == SampleState.VERIFIED.value


def test_sample_maintenance_archives_abandoned_failed_candidate(sample_library) -> None:
    conn, _stream, repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate(
        "失败计划候选",
        [_step()],
        source="llm",
        plan_id="failed-plan",
    )
    now = 10_000_000.0
    old = now - 31 * 86400.0
    conn.execute(
        "UPDATE memory_chunks SET modified_at = ? WHERE id = ?;",
        (old, int(candidate.sample_id)),
    )
    conn.commit()
    maintenance = SampleMaintenance(
        repository,
        lifecycle,
        plan_failed_provider=lambda plan_id: plan_id == "failed-plan",
    )

    actions = maintenance.run(now=now)

    assert actions == [f"{candidate.sample_id}:abandoned"]
    assert repository.get(candidate.sample_id).sample_state == SampleState.ARCHIVED.value


def test_sample_maintenance_evicts_zero_injection_auto_sample_first(sample_library) -> None:
    _conn, _stream, repository, lifecycle = sample_library
    zero = lifecycle.auto_verify(
        lifecycle.create_candidate("零命中", [_step()], source="llm").sample_id,
        reason="plan_all_green",
    )
    used = lifecycle.auto_verify(
        lifecycle.create_candidate("已有命中", [_step(title="另一命中步骤")], source="llm").sample_id,
        reason="plan_all_green",
    )
    protected = lifecycle.confirm(
        lifecycle.create_candidate("用户权威", [_step(title="用户步骤")], source="llm").sample_id
    )
    repository.record_injection(used.sample_id, hit_at=9000.0, similarity=0.9)
    maintenance = SampleMaintenance(repository, lifecycle, verified_limit=2)

    actions = maintenance.run(now=10_000.0)

    assert actions == [f"{zero.sample_id}:capacity"]
    assert repository.get(zero.sample_id).sample_state == SampleState.ARCHIVED.value
    assert repository.get(used.sample_id).sample_state == SampleState.VERIFIED.value
    assert repository.get(protected.sample_id).verify_kind == VerifyKind.USER.value


def test_metadata_updates_do_not_overwrite_task_description(sample_library) -> None:
    conn, _stream, repository, lifecycle = sample_library
    candidate = lifecycle.create_candidate("正文保持稳定", [_step()], source="rule")
    repository.mutate_metadata(candidate.sample_id, lambda metadata: metadata.update(stale_reason="test"))
    row = conn.execute(
        "SELECT content, body FROM memory_chunks WHERE id = ?;",
        (int(candidate.sample_id),),
    ).fetchone()
    assert row["content"] == "正文保持稳定"
    assert row["body"] == "正文保持稳定"
