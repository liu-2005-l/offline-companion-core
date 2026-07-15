"""plan_orchestrator：A2 任务规划与执行编排的最小闭环骨架。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from offline_companion.core.state_manager import StateManager


@dataclass(frozen=True)
class PlanStep:
    """摘要：单个规划步骤。"""

    step_id: str
    skill_id: str
    result_key: str
    condition_key: str | None = None
    condition_value: Any | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0

    def condition_met(self, context_state: dict[str, Any]) -> bool:
        if self.condition_key is None:
            return True
        return context_state.get(self.condition_key) == self.condition_value


@dataclass
class PlanContext:
    """摘要：任务执行上下文。"""

    plan_id: str
    state: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def update(self, key: str, value: Any) -> None:
        self.state[key] = value
        self.results[key] = value

    def record_error(self, step_id: str, error: Exception) -> None:
        self.errors.append({"step_id": step_id, "error": str(error)})

    def to_result(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "state": dict(self.state),
            "results": dict(self.results),
            "errors": list(self.errors),
        }


class PlanOrchestrator:
    """摘要：规则驱动的最小规划编排器。

    说明：
        当前版本只做 YAML/JSON 模板驱动的单步闭环，不做 LLM 自主拆解。
        后续可扩展为动态 DAG 生成器。
    """

    def __init__(self, state_manager: StateManager, templates_dir: str | Path | None = None) -> None:
        self._state_manager = state_manager
        default_templates_dir = Path(__file__).resolve().parents[3] / "configs" / "plans"
        self._templates_dir = Path(templates_dir) if templates_dir is not None else default_templates_dir

    def load_template(self, plan_id: str) -> list[PlanStep]:
        """摘要：加载预设任务模板。"""
        for candidate in (
            self._templates_dir / f"{plan_id}.json",
            self._templates_dir / f"{plan_id}.yaml",
            self._templates_dir / f"{plan_id}.yml",
        ):
            if not candidate.is_file():
                continue
            content = candidate.read_text(encoding="utf-8")
            if candidate.suffix == ".json":
                raw = json.loads(content)
            else:
                try:
                    import yaml
                except Exception as exc:  # pragma: no cover - dependency guard
                    raise RuntimeError("PyYAML is required to load YAML plan templates") from exc
                raw = yaml.safe_load(content)
            steps: list[PlanStep] = []
            for idx, item in enumerate(raw or []):
                steps.append(
                    PlanStep(
                        step_id=str(item.get("step_id", f"step-{idx}")),
                        skill_id=str(item["skill_id"]),
                        result_key=str(item.get("result_key", item.get("skill_id", f"result_{idx}"))),
                        condition_key=item.get("condition_key"),
                        condition_value=item.get("condition_value"),
                        payload=dict(item.get("payload", {})),
                        retry_count=int(item.get("retry_count", 0)),
                    )
                )
            return steps
        return []

    def create_context(self, plan_id: str) -> PlanContext:
        """摘要：创建任务上下文，并写入 StateManager。"""
        context = PlanContext(plan_id=plan_id)
        self._state_manager.set_task_state(f"plan.{plan_id}.context", context.to_result())
        return context

    def _persist_context(self, plan_id: str, context: PlanContext) -> None:
        self._state_manager.set_task_state(f"plan.{plan_id}.context", context.to_result())

    def _finalize(self, plan_id: str, context: PlanContext, status: str) -> PlanContext:
        context.state["status"] = status
        self._state_manager.set_task_state(f"plan.{plan_id}.result", context.to_result())
        self._state_manager.set_task_state(f"plan.{plan_id}.status", status)
        return context

    def execute_plan(
        self,
        plan_id: str,
        *,
        invoke_skill: Callable[[PlanStep, PlanContext], Any],
        context: PlanContext | None = None,
    ) -> PlanContext:
        """摘要：执行模板化规划闭环。

        参数：
            plan_id: 任务 ID。
            invoke_skill: Skill 调用函数，签名为 ``invoke_skill(step, context) -> Any``。
            context: 可选上下文；未提供时自动创建。
        """
        current_context = context or self.create_context(plan_id)
        steps = self.load_template(plan_id)
        current_context.state.setdefault("plan_id", plan_id)
        current_context.state.setdefault("progress", 0.0)
        current_context.state.setdefault("step_status", {})
        current_context.state.setdefault("task_steps", [])
        current_context.state.setdefault("attempts", {})

        if not steps:
            current_context.state["status"] = "empty"
            self._state_manager.set_task_state(f"plan.{plan_id}.status", "empty")
            self._state_manager.set_task_state(f"plan.{plan_id}.result", current_context.to_result())
            return current_context

        try:
            executed = 0
            for step in steps:
                if not step.condition_met(current_context.state):
                    current_context.state["step_status"][step.step_id] = "skipped"
                    continue

                current_context.state["step_status"][step.step_id] = "running"
                self._state_manager.set_task_state(f"plan.{plan_id}.current_step", step.step_id)
                attempts = 0
                last_error: Exception | None = None
                while attempts <= step.retry_count:
                    attempts += 1
                    current_context.state["attempts"][step.step_id] = attempts
                    try:
                        result = invoke_skill(step, current_context)
                        current_context.update(step.result_key, result)
                        current_context.state["step_status"][step.step_id] = "done"
                        current_context.state["task_steps"].append(step.step_id)
                        executed += 1
                        current_context.state["progress"] = executed / max(len(steps), 1)
                        self._persist_context(plan_id, current_context)
                        self._state_manager.set_task_state(
                            f"plan.{plan_id}.progress", current_context.state["progress"]
                        )
                        break
                    except Exception as exc:
                        last_error = exc
                        current_context.record_error(step.step_id, exc)
                        current_context.state["step_status"][step.step_id] = "retrying"
                        if attempts > step.retry_count:
                            raise
                if last_error is not None and current_context.state["step_status"][step.step_id] != "done":
                    raise last_error
        except Exception as exc:
            current_context.state["status"] = "failed"
            current_context.state["error"] = str(exc)
            self._state_manager.set_task_state(f"plan.{plan_id}.error", str(exc))
            self._state_manager.set_task_state(f"plan.{plan_id}.result", current_context.to_result())
            self._state_manager.set_task_state(f"plan.{plan_id}.status", "failed")
            raise

        return self._finalize(plan_id, current_context, "done")
