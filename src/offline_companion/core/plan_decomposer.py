"""plan_decomposer：计划步骤拆解与规则 fallback。"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from offline_companion.core import plan_snapshot
from offline_companion.core.decomposition_result import NotDecomposableResult
from offline_companion.core.decomposition_templates import GENERIC_SCAFFOLD_TITLES
from offline_companion.core.plan_enums import PlanStage
from offline_companion.shared.deterministic_embedding import tokenize_for_embedding
from offline_companion.shared.errors import A2PlanValidationError

if TYPE_CHECKING:
    from offline_companion.core.decomposition_sample_library import (
        SampleLifecycleManager,
        SampleRetriever,
    )
    from offline_companion.core.plan_orchestrator import PlanStep

logger = logging.getLogger(__name__)

_NON_TASK_INPUTS = frozenset(
    {
        "你好",
        "您好",
        "hi",
        "hello",
        "hey",
        "嗨",
        "早上好",
        "中午好",
        "晚上好",
        "晚安",
        "再见",
        "拜拜",
        "嗯",
        "哦",
        "好",
        "好的",
        "ok",
        "okay",
        "是的",
        "对",
        "没错",
        "谢谢",
        "不客气",
        "你擅长什么",
        "你能做什么",
        "你会什么",
        "你会做什么",
        "你能干嘛",
        "介绍一下你自己",
        "介绍你自己",
        "你叫什么",
        "你叫什么名字",
        "你是谁",
    }
)
_MIN_STEP_RELEVANCE = 0.05
_EXPLANATION_INTENT_PATTERN = re.compile(
    r"(?:^(?:(?:请|请给我|给我|帮我|替我|为我|麻烦)\s*)?"
    r"(?:讲讲|解释(?:一下)?|说说|谈谈|介绍(?:一下)?|科普(?:一下)?|什么是|什么叫).+)"
    r"|(?:^(?:能|可以|能不能|可不可以)(?:详细)?(?:地)?(?:给我)?"
    r"(?:讲讲|解释|说说|介绍)(?:一下)?(?:吗)?(?:[，,：:]?.*)$)"
)
_EXPLANATION_NOUN_PATTERN = re.compile(r"^.+(?:的)?原理(?:是什么|是啥)?$")
_TASK_IMPERATIVE_PREFIXES = ("帮我", "给我", "替我", "为我", "请", "麻烦")
_TASK_ACTION_PHRASES = (
    "写一个",
    "写个",
    "做一个",
    "做个",
    "生成一份",
    "生成一个",
    "创建",
    "新建",
    "保存",
    "导出",
    "整理成",
    "实现一个",
    "开发一个",
)

_META_PATTERNS = (
    "执行核心步骤",
    "理解目标",
    "制定方案",
    "验证与收尾",
    "implement core",
    "understand goal",
    "make plan",
    "verify and finish",
)
_REQUIRED_FIELDS = (
    "title",
    "description",
    "expected_output",
    "verification",
    "completion_criteria",
)


class PlanDecomposer:
    """摘要：将用户目标拆解为强类型计划步骤，不持有执行编排状态。"""

    def __init__(
        self,
        *,
        llm_router: object | None = None,
        skill_resolver: Callable[[str], tuple[str | None, list[str]]] | None = None,
        sample_retriever: SampleRetriever | None = None,
        sample_lifecycle: SampleLifecycleManager | None = None,
        learning_enabled_provider: Callable[[], bool] | None = None,
    ) -> None:
        """摘要：初始化计划拆解器。

        参数：
            llm_router: 可选 LLM 后端，支持 ``chat`` 或 ``generate``。
            skill_resolver: 可选 Skill 解析函数，返回 Skill 名称与阶段序列。
            sample_retriever: 可选本地拆解样本检索器。
            sample_lifecycle: 可选拆解样本生命周期管理器。
            learning_enabled_provider: 可选动态设置开关读取函数。
        """
        self._router = llm_router
        self._skill_resolver = skill_resolver
        self._sample_retriever = sample_retriever
        self._sample_lifecycle = sample_lifecycle
        self._learning_enabled_provider = learning_enabled_provider
        self.skill_name: str | None = None
        self.skill_stages: list[str] = []
        self.last_source: str | None = None
        self.last_sample_ids: list[str] = []
        self.last_candidate_sample_id: str | None = None

    def decide(self, user_input: str) -> list[PlanStep] | NotDecomposableResult:
        """摘要：将用户目标拆成可执行、可验证的计划步骤。

        参数：
            user_input: 用户提交的完整目标文本。

        返回值：
            满足 DAG 依赖关系的 ``PlanStep`` 列表；空输入返回空列表。
        """
        goal = (user_input or "").strip()
        self.last_source = None
        self.last_sample_ids = []
        self.last_candidate_sample_id = None
        if not goal:
            self.skill_name = None
            self.skill_stages = []
            return []
        if _normalize_non_task_input(goal) in _NON_TASK_INPUTS:
            return NotDecomposableResult(reason="greeting", original_input=user_input)
        if _is_explanation_request(goal):
            return NotDecomposableResult(reason="explanation", original_input=user_input)
        self._resolve_skill(goal)
        learning_enabled = self._learning_enabled()
        shots: list[object] = []
        if learning_enabled and self._sample_retriever is not None:
            try:
                shots = list(self._sample_retriever.retrieve(goal))
            except Exception:
                logger.exception("拆解样本检索失败，继续使用零样本拆解")
        self.last_sample_ids = [
            str(shot.sample_id)
            for shot in shots
            if getattr(shot, "sample_id", None) is not None
        ]
        raw_steps: list[dict[str, Any]] | NotDecomposableResult | None = None
        source = "rule"
        if self._router is not None:
            from offline_companion.core.llm_decomposer import decompose_with_llm

            raw_steps = decompose_with_llm(
                goal,
                self._router,
                skill_stages=self.skill_stages or None,
                skill_name=self.skill_name,
                shots=shots or None,
            )
            if isinstance(raw_steps, NotDecomposableResult):
                return raw_steps
            if raw_steps is not None:
                source = "llm"
        if raw_steps is None:
            raw_steps = rule_decompose(goal)
            if raw_steps is None:
                logger.info("任务未命中专用规则模板，降级为普通对话")
                return NotDecomposableResult(
                    reason="no_rule_match",
                    original_input=user_input,
                )
        steps = [
            raw_to_plan_step(step, goal, idx)
            for idx, step in enumerate(raw_steps)
        ]
        if source == "llm" and _contains_generic_scaffold(steps):
            logger.warning("任务拆解命中通用脚手架闭集，降级为普通对话")
            return NotDecomposableResult(reason="meta_template", original_input=user_input)
        if source == "llm" and _detect_echo(
            goal,
            _raw_goal_text(raw_steps),
            _plan_step_texts(steps),
        ):
            logger.warning("任务拆解复述原始输入，降级为普通对话")
            return NotDecomposableResult(reason="echo", original_input=user_input)
        relevance = _step_relevance(goal, steps)
        if relevance < _MIN_STEP_RELEVANCE:
            logger.warning("任务拆解相关性过低，降级为普通对话: relevance=%.4f", relevance)
            return NotDecomposableResult(reason="low_relevance", original_input=user_input)
        self.last_source = source
        if self._sample_lifecycle is not None:
            try:
                candidate = self._sample_lifecycle.create_candidate(
                    goal,
                    steps,
                    source=source,
                    provenance_sample_ids=self.last_sample_ids,
                )
                self.last_candidate_sample_id = candidate.sample_id
                if int(candidate.usage.get("similarity_count") or 0) > 0:
                    self.last_sample_ids = list(
                        dict.fromkeys([*self.last_sample_ids, candidate.sample_id])
                    )
            except Exception:
                logger.exception("拆解候选样本留档失败，不阻塞计划生成")
        return steps
    def bind_candidate_plan(self, plan_id: str) -> None:
        """摘要：计划 ID 分配后回填本次拆解候选样本。"""
        if self._sample_lifecycle is None or self.last_candidate_sample_id is None:
            return
        try:
            self._sample_lifecycle.assign_plan_id(self.last_candidate_sample_id, plan_id)
        except Exception:
            logger.exception("候选样本 plan_id 回填失败，不阻塞计划落库")

    def _learning_enabled(self) -> bool:
        """摘要：读取动态开关，读取失败时安全退回关闭。"""
        if self._learning_enabled_provider is None:
            return self._sample_retriever is not None or self._sample_lifecycle is not None
        try:
            return bool(self._learning_enabled_provider())
        except (OSError, RuntimeError, TypeError, ValueError):
            logger.warning("拆解学习开关读取失败，本次关闭样本学习")
            return False

    def _resolve_skill(self, user_input: str) -> None:
        """摘要：解析当前计划匹配的 Prompt Skill 及阶段序列。"""
        if self._skill_resolver is None:
            self.skill_name = None
            self.skill_stages = []
            return
        try:
            skill_name, stages = self._skill_resolver(user_input)
        except (OSError, RuntimeError, ValueError):
            self.skill_name = None
            self.skill_stages = []
            return
        if skill_name and stages:
            self.skill_name = str(skill_name)
            self.skill_stages = [str(stage) for stage in stages if str(stage).strip()]
            return
        self.skill_name = None
        self.skill_stages = []


def _normalize_non_task_input(text: str) -> str:
    """摘要：移除输入首尾空白和标点，保留中间内容用于精确匹配。"""

    normalized = str(text).strip().lower()
    start = 0
    end = len(normalized)
    while start < end and unicodedata.category(normalized[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(normalized[end - 1]).startswith("P"):
        end -= 1
    return normalized[start:end].strip()


def _is_explanation_request(text: str) -> bool:
    """摘要：以讲解意图优先的两级规则识别对话型输入。"""

    normalized = _normalize_non_task_input(text)
    if _EXPLANATION_INTENT_PATTERN.fullmatch(normalized):
        return True
    if _EXPLANATION_NOUN_PATTERN.fullmatch(normalized):
        return True
    if normalized.startswith(_TASK_IMPERATIVE_PREFIXES):
        return False
    if any(marker in normalized for marker in _TASK_ACTION_PHRASES):
        return False
    return False


def _step_relevance(original_input: str, steps: list[PlanStep]) -> float:
    """摘要：计算原始输入与全部步骤文本的稀疏词袋余弦相似度。"""

    step_text = "\n".join(
        " ".join(
            (
                step.title,
                step.description,
                step.expected_output,
                step.verification,
                step.completion_criteria,
                *step.files,
            )
        )
        for step in steps
    )
    input_tokens = set(tokenize_for_embedding(original_input))
    step_tokens = set(tokenize_for_embedding(step_text))
    if not input_tokens or not step_tokens:
        return 0.0
    return len(input_tokens & step_tokens) / (len(input_tokens) * len(step_tokens)) ** 0.5


def _detect_echo(input_text: str, goal_text: str, step_texts: list[str]) -> bool:
    """摘要：检测模型目标或步骤是否连续复述用户整句输入。"""

    normalized_input = _normalize_echo_text(input_text)
    if len(normalized_input) < 4:
        return False
    return any(
        normalized_input in _normalize_echo_text(text)
        for text in (goal_text, *step_texts)
    )


def _contains_generic_scaffold(steps: list[PlanStep]) -> bool:
    """摘要：两个及以上步骤标题命中通用脚手架闭集时判定为元模板复读。"""

    matched_steps = sum(
        1
        for step in steps
        if any(pattern in step.title for pattern in GENERIC_SCAFFOLD_TITLES)
    )
    return matched_steps >= 2


def _normalize_echo_text(text: str) -> str:
    """摘要：移除标点与空白并统一小写，供整句复述检测使用。"""

    return "".join(
        char
        for char in str(text).strip().lower()
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def _raw_goal_text(raw_steps: list[dict[str, Any]]) -> str:
    """摘要：聚合模型步骤中可选的目标字段，兼容未来输出契约。"""

    return "\n".join(str(step.get("goal") or "") for step in raw_steps)


def _plan_step_texts(steps: list[PlanStep]) -> list[str]:
    """摘要：展开步骤字段，避免跨字段拼接产生误判。"""

    texts: list[str] = []
    for step in steps:
        texts.extend(
            (
                step.title,
                step.description,
                step.expected_output,
                step.verification,
                step.completion_criteria,
                *step.files,
            )
        )
    return texts


def raw_to_plan_step(raw: Mapping[str, Any], user_input: str, idx: int) -> PlanStep:
    """摘要：将 LLM 或规则模板产出的字典转换为强类型计划步骤。"""
    from offline_companion.core.plan_orchestrator import PlanStep

    _validate_raw_step(raw, idx)
    step_id = str(raw.get("step_id") or f"step_{idx}")
    risk = str(raw.get("risk") or "low")
    title = str(raw.get("title") or raw.get("description") or step_id)
    description = str(raw.get("description") or title)
    expected_output = str(raw.get("expected_output") or "")
    verification = str(raw.get("verification") or "")
    completion_criteria = str(raw.get("completion_criteria") or "")
    estimated_minutes = plan_snapshot.safe_non_negative_int(raw.get("estimated_minutes"))
    files = tuple(str(path) for path in raw.get("files", ()) or ())
    return PlanStep(
        step_id=step_id,
        skill_id=str(raw.get("skill_id") or "chat"),
        result_key=str(raw.get("result_key") or f"{step_id}_result"),
        depends_on=plan_snapshot.normalize_raw_dependencies(raw, idx),
        condition_key=str(raw["condition_key"]) if raw.get("condition_key") is not None else None,
        retry_max=plan_snapshot.safe_non_negative_int(raw.get("retry_max")),
        require_consent=bool(raw.get("require_consent", risk == "high")),
        payload={
            "description": title,
            "query": user_input,
            "risk": risk,
            "complexity": 7 if risk in {"medium", "high"} else 2,
            "expected_output": expected_output,
            "verification": verification,
            "completion_criteria": completion_criteria,
            "stage": raw.get("stage") or None,
            "estimated_minutes": estimated_minutes,
            "files": list(files),
        },
        title=title,
        description=description,
        expected_output=expected_output,
        verification=verification,
        completion_criteria=completion_criteria,
        stage=str(raw["stage"]) if raw.get("stage") else None,
        estimated_minutes=estimated_minutes,
        files=files,
        subagent_type=plan_snapshot.normalize_subagent_role(raw.get("subagent_type")),
    )


def _validate_raw_step(raw: Mapping[str, Any], idx: int) -> None:
    """摘要：在转换强类型步骤前拦截缺字段与元模板描述。"""
    for field_name in _REQUIRED_FIELDS:
        value = raw.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise A2PlanValidationError(f"step {idx} missing required field: {field_name}")
    haystack = f"{raw.get('title', '')}\n{raw.get('description', '')}".lower()
    for pattern in _META_PATTERNS:
        if pattern.lower() in haystack:
            raise A2PlanValidationError(f"step {idx} contains meta template: {pattern}")


def rule_decompose(goal: str) -> list[dict[str, Any]] | None:
    """摘要：按目标关键词生成专用串行步骤模板，无匹配时返回 None。"""
    if any(keyword in goal for keyword in ("写", "制作", "实现", "开发", "代码")):
        return [
            _rule_step(
                title="理解需求：解析目标功能与约束",
                description=f"分析用户请求「{goal}」，明确输入、输出、限制和验收口径。",
                expected_output="需求边界说明，包含输入、输出、约束和验收口径。",
                verification="检查需求边界说明是否覆盖输入、输出、约束和验收口径四项。",
                completion_criteria="四项信息均有具体描述，且没有仅复述用户原话。",
                stage=PlanStage.BRAINSTORMING.value,
                estimated_minutes=5,
            ),
            _rule_step(
                title="设计方案：确定模块边界与数据流",
                description=f"为「{goal}」确定需要修改的模块、数据流和最小实现路径。",
                expected_output="实现方案，包含涉及模块、数据流、风险点和测试策略。",
                verification="方案中列出至少一个涉及模块，并说明对应测试或检查方式。",
                completion_criteria="模块边界清楚，测试策略可执行，风险点有处理方式。",
                deps=(0,),
                stage=PlanStage.PLANNING.value,
                estimated_minutes=10,
            ),
            _rule_step(
                title="实现核心逻辑：完成主要代码改动",
                description=f"按方案实现「{goal}」所需的核心代码，并保持现有架构边界。",
                expected_output="完成的代码改动，包含核心逻辑和必要的兼容处理。",
                verification="运行相关窄测试、静态检查或手动验证命令确认改动可用。",
                completion_criteria="核心路径可运行，相关验证通过，未引入无关重构。",
                deps=(1,),
                risk="medium",
                stage=PlanStage.TDD.value,
                estimated_minutes=30,
            ),
            _rule_step(
                title="运行验证：执行相关测试与检查",
                description=f"运行覆盖「{goal}」的最小测试集，并记录实际输出。",
                expected_output="测试或检查输出，包含 pass/fail 计数或明确的手动验证结果。",
                verification="确认输出中没有新增 failure，skip 项有合理说明。",
                completion_criteria="验证结果可追溯，失败项已修复或明确标记为无关问题。",
                deps=(2,),
                stage=PlanStage.REVIEW.value,
                estimated_minutes=10,
            ),
            _rule_step(
                title="整理交付：总结变更与后续风险",
                description=f"汇总「{goal}」的实现结果、验证结果和剩余风险。",
                expected_output="交付摘要，包含改动文件、验证命令和后续风险。",
                verification="摘要中包含至少一条验证证据，并列出无验证时的原因。",
                completion_criteria="用户可以根据摘要复查改动和验证结果。",
                deps=(3,),
                stage=PlanStage.FINALIZE.value,
                estimated_minutes=5,
            ),
        ]
    if any(keyword in goal for keyword in ("部署", "安装", "下载", "网络", "权限")):
        return [
            _rule_step(
                title="检查环境：确认运行时、路径与权限",
                description=f"检查「{goal}」需要的运行时、文件路径、权限和隐私边界。",
                expected_output="环境检查记录，包含路径、权限、网络或出站需求。",
                verification="逐项确认环境检查记录中的前置条件是否满足。",
                completion_criteria="阻断项已列出，涉及出站或高风险操作已标明 consent 需求。",
                stage=PlanStage.BRAINSTORMING.value,
                estimated_minutes=5,
            ),
            _rule_step(
                title="准备依赖：下载或定位所需组件",
                description=f"准备「{goal}」所需依赖，优先使用本地已有资源。",
                expected_output="依赖清单及来源，包含本地路径或经过同意的下载来源。",
                verification="检查依赖文件存在、版本符合要求，或记录无法获取的原因。",
                completion_criteria="依赖来源可追溯，不存在未经同意的静默出站。",
                deps=(0,),
                risk="medium",
                stage=PlanStage.PLANNING.value,
                estimated_minutes=15,
            ),
            _rule_step(
                title="执行变更：修改系统或服务配置",
                description=f"在授权范围内执行「{goal}」涉及的安装、部署或配置变更。",
                expected_output="完成的配置或部署变更记录。",
                verification="检查目标服务、文件或配置项达到预期状态。",
                completion_criteria="变更已完成，高风险步骤有 consent 证据，失败时保留错误信息。",
                deps=(1,),
                risk="high",
                stage=PlanStage.TDD.value,
                estimated_minutes=30,
            ),
            _rule_step(
                title="验证结果：检查服务状态与日志",
                description=f"验证「{goal}」完成后的服务状态、日志和回退风险。",
                expected_output="验证记录，包含状态检查、日志摘要和剩余风险。",
                verification="运行状态检查命令或读取日志，确认没有新增错误。",
                completion_criteria="关键服务或配置状态符合预期，异常已记录并给出处理建议。",
                deps=(2,),
                stage=PlanStage.FINALIZE.value,
                estimated_minutes=10,
            ),
        ]
    if any(keyword in goal for keyword in ("分析", "研究", "评估", "梳理")):
        return [
            _rule_step(
                title="收集上下文：整理相关代码与数据",
                description=f"定位与「{goal}」相关的文件、数据、日志或文档。",
                expected_output="上下文清单，包含来源路径和关键片段摘要。",
                verification="确认清单中的来源可访问，且覆盖用户问题中的关键对象。",
                completion_criteria="上下文足以支持后续判断，没有明显遗漏的主路径。",
                stage=PlanStage.BRAINSTORMING.value,
                estimated_minutes=10,
            ),
            _rule_step(
                title="结构化分析：提取关键事实与差异",
                description=f"对「{goal}」相关上下文进行归类、对比和因果分析。",
                expected_output="结构化分析结果，包含事实、差异、风险和推论边界。",
                verification="每个关键结论都能追溯到上下文来源或明确标记为推论。",
                completion_criteria="事实与推论分离，风险项有优先级。",
                deps=(0,),
                stage=PlanStage.PLANNING.value,
                estimated_minutes=20,
            ),
            _rule_step(
                title="输出结论：给出判断和建议路径",
                description=f"基于分析给出「{goal}」的结论、建议和下一步行动。",
                expected_output="结论摘要，包含建议路径、证据和未决问题。",
                verification="结论覆盖用户问题，并列出至少一项可执行下一步。",
                completion_criteria="建议可执行，证据充分，未决问题不被包装成事实。",
                deps=(1,),
                stage=PlanStage.FINALIZE.value,
                estimated_minutes=10,
            ),
        ]
    return None


def _rule_step(
    *,
    title: str,
    description: str,
    expected_output: str,
    verification: str,
    completion_criteria: str,
    deps: tuple[int, ...] = (),
    risk: str = "low",
    stage: str | None = None,
    estimated_minutes: int = 0,
    files: tuple[str, ...] = (),
) -> dict[str, Any]:
    """摘要：构造规则拆解步骤，确保 fallback 也满足强类型计划字段。"""
    return {
        "title": title,
        "description": description,
        "expected_output": expected_output,
        "verification": verification,
        "completion_criteria": completion_criteria,
        "deps": list(deps),
        "risk": risk,
        "stage": stage,
        "estimated_minutes": max(0, int(estimated_minutes)),
        "files": list(files),
    }
