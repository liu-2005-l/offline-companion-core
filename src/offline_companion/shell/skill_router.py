"""skill_router：扫描可信技能定义并按用户输入选择 Prompt 技能。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from offline_companion.shared.runtime_paths import dev_repo_root

_STOP_WORDS = frozenset({"the", "a", "an", "for", "to", "of", "and", "or", "in", "on", "with", "use", "when"})
_MAX_SKILL_BYTES = 65536


@dataclass(frozen=True)
class SkillDescriptor:
    """摘要：可信 skills 根目录内的单个 Prompt 技能描述。"""

    name: str
    description: str
    path: Path
    stages: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillRoutingDecision:
    """摘要：Skill 路由结果；chat 表示未匹配。"""

    route: str
    skill_name: str | None = None
    skill_md_path: str | None = None


def default_skills_dir() -> Path:
    """摘要：返回开发仓库或冻结资源中的可信 skills 根目录。"""
    return (dev_repo_root() / "skills").resolve()


@lru_cache(maxsize=8)
def load_skill_descriptions(skills_dir: Path | None = None) -> tuple[SkillDescriptor, ...]:
    """摘要：读取可信根目录下 SKILL.md 的名称、描述和规范化路径。"""
    root = (skills_dir or default_skills_dir()).resolve()
    if not root.is_dir():
        return ()
    descriptors: list[SkillDescriptor] = []
    for skill_md in sorted(root.glob("*/SKILL.md")):
        path = skill_md.resolve()
        if not _is_within(path, root) or path.stat().st_size > _MAX_SKILL_BYTES:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            frontmatter = _frontmatter(raw)
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        name = str(frontmatter.get("name") or "").strip()
        description = str(frontmatter.get("description") or "").strip()
        stages = _normalize_stages(frontmatter.get("stages"))
        if name and description and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
            descriptors.append(SkillDescriptor(name=name, description=description, path=path, stages=stages))
    return tuple(descriptors)


def match_skill(user_input: str, skills: tuple[SkillDescriptor, ...]) -> SkillDescriptor | None:
    """摘要：按描述关键词命中数选择技能，至少命中两个词才触发。"""
    normalized_input = user_input.casefold()
    best_match: SkillDescriptor | None = None
    best_score = 0
    for skill in skills:
        keywords = _description_keywords(skill.description)
        score = sum(1 for keyword in keywords if keyword in normalized_input)
        if score >= 2 and score > best_score:
            best_match = skill
            best_score = score
    return best_match


class SkillDecisionEngine:
    """摘要：在记忆与澄清决策完成后执行 Prompt 技能路由。"""

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._skills_dir = (skills_dir or default_skills_dir()).resolve()

    def decide(
        self,
        user_input: str,
        *,
        memory_route: str | None = None,
        needs_clarification: bool = False,
    ) -> SkillRoutingDecision:
        """摘要：按 memory、clarify、skill、chat 优先级返回路由。"""
        if memory_route == "memory":
            return SkillRoutingDecision(route="memory")
        if needs_clarification or memory_route == "clarify":
            return SkillRoutingDecision(route="clarify")
        match = match_skill(user_input, load_skill_descriptions(self._skills_dir))
        if match is None:
            return SkillRoutingDecision(route="chat")
        return SkillRoutingDecision(route="skill", skill_name=match.name, skill_md_path=str(match.path))

    def build_prompt(self, decision: SkillRoutingDecision) -> str:
        """摘要：仅从可信根目录读取已决策技能，并构造系统提示片段。"""
        if decision.route != "skill" or not decision.skill_name or not decision.skill_md_path:
            return ""
        path = Path(decision.skill_md_path).resolve()
        if not _is_within(path, self._skills_dir) or path.stat().st_size > _MAX_SKILL_BYTES:
            return ""
        content = path.read_text(encoding="utf-8")
        descriptor = next(
            (item for item in load_skill_descriptions(self._skills_dir) if item.name == decision.skill_name),
            None,
        )
        stage_instruction = _stage_instruction(decision.skill_name, descriptor.stages if descriptor else ())
        return (
            f"## 激活技能：{decision.skill_name}\n\n"
            "以下技能定义已激活，必须按其 Iron Laws 和 Procedure 执行：\n\n"
            f"---\n{content}\n---{stage_instruction}"
        )


def _frontmatter(raw: str) -> dict[str, object]:
    match = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|\Z)", raw, re.DOTALL)
    if match is None:
        return {}
    payload = yaml.safe_load(match.group(1)) or {}
    return payload if isinstance(payload, dict) else {}


def _description_keywords(description: str) -> tuple[str, ...]:
    tokens = re.split(r"[\s,，、。；;：:/|]+", description.casefold())
    return tuple(dict.fromkeys(token for token in tokens if token not in _STOP_WORDS and len(token) >= 2))


def _normalize_stages(value: object) -> tuple[str, ...]:
    """摘要：校验并去重 frontmatter 阶段序列。"""
    if not isinstance(value, list):
        return ()
    stages = tuple(str(stage).strip() for stage in value if str(stage).strip())
    if len(stages) != len(set(stages)):
        return ()
    if any(re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", stage) is None for stage in stages):
        return ()
    return stages


def _stage_instruction(skill_name: str, stages: tuple[str, ...]) -> str:
    """摘要：为声明阶段的技能构造不可跳过的工具推进指令。"""
    if not stages:
        return ""
    sequence = " → ".join(stages)
    return f"""

## 硬门禁：阶段序列

此技能必须按以下顺序执行：{sequence}

### Iron Law: 阶段推进
- 每个阶段开始前，必须调用 `skill_advance_stage`，参数为 `action=start, skill_name={skill_name}, stage=<阶段名>`。
- 返回 `blocked` 时，必须先完成 `missing_stages` 中的前置阶段。
- 每个阶段完成后，必须调用 `skill_advance_stage`，参数为 `action=complete, skill_name={skill_name}, stage=<阶段名>, evidence=<验证证据>`。
- 禁止跳过阶段，禁止在未调用 `skill_advance_stage` 的情况下开始阶段。
"""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
