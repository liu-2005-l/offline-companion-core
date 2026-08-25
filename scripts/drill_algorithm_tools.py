"""摘要：重跑 Batch D-3 算法工具联测 drill。"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from offline_companion.core.algorithm_tools import crc32_utf8
from offline_companion.core.decomposition_result import NotDecomposableResult
from offline_companion.core.event_stream import EventStream, build_default_registry
from offline_companion.core.plan_decomposer import PlanDecomposer
from offline_companion.core.tools.crc32_tool import crc32_tool
from offline_companion.core.tools.gcd_tool import gcd_tool
from offline_companion.core.tools.quicksort_tool import quicksort_tool
from offline_companion.shared.types import PrivacyMode, ToolManifest
from offline_companion.shell.tool_registry import ToolInvoker, ToolRegistry


@dataclass(frozen=True)
class DrillCase:
    """摘要：一条算法工具联测判例。"""

    name: str
    user_input: str
    expected_tool_id: str | None
    expected_result: object | None
    expected_status: str = "tool"


CASES = (
    DrillCase(
        name="crc32_abc",
        user_input='按照CRC算法计算"abc"的校验值',
        expected_tool_id="algorithm_crc32",
        expected_result="0x352441C2",
    ),
    DrillCase(
        name="gcd_method",
        user_input="用欧几里得算法求48和18的最大公约数",
        expected_tool_id="algorithm_gcd",
        expected_result=6,
    ),
    DrillCase(
        name="gcd_trigger",
        user_input="求48和18的最大公约数",
        expected_tool_id="algorithm_gcd",
        expected_result=6,
    ),
    DrillCase(
        name="quicksort",
        user_input="按快速排序排[5,2,9,1]",
        expected_tool_id="algorithm_quicksort",
        expected_result=[1, 2, 5, 9],
    ),
    DrillCase(
        name="md5_degrade",
        user_input="按照MD5算法计算这段文字的哈希",
        expected_tool_id=None,
        expected_result=None,
        expected_status="degrade",
    ),
)

CRC32_STANDARD_CHECK = "0xCBF43926"


def main() -> int:
    """摘要：执行 drill 并按失败层独立输出。"""
    registry = _build_registry()
    stream = EventStream("d3-drill", build_default_registry())
    invoker = ToolInvoker(registry, event_stream=stream)
    decomposer = PlanDecomposer(
        method_entity_names=registry.algorithm_names,
        algorithm_name_map=registry.algorithm_name_map,
        trigger_keyword_map=registry.trigger_keyword_map,
    )
    failures: list[str] = []

    check = crc32_utf8("123456789")
    if check["hex"] != CRC32_STANDARD_CHECK:
        failures.append(
            f"[execute] crc32_standard_check expected={CRC32_STANDARD_CHECK} actual={check['hex']}"
        )

    for case in CASES:
        failures.extend(_run_case(case, decomposer=decomposer, invoker=invoker))

    events = stream.get_events()
    tool_events = [event.event_type for event in events]
    if "tool/call" not in tool_events or "tool/result" not in tool_events:
        failures.append("[event] missing tool/call or tool/result event")

    if failures:
        print("D-3 drill FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("D-3 drill PASSED")
    print(f"- cases={len(CASES)}")
    print(f"- events={tool_events.count('tool/call')} calls / {tool_events.count('tool/result')} results")
    return 0


def _run_case(
    case: DrillCase,
    *,
    decomposer: PlanDecomposer,
    invoker: ToolInvoker,
) -> list[str]:
    failures: list[str] = []
    decision = decomposer.decide(case.user_input)
    if case.expected_status == "degrade":
        if not isinstance(decision, NotDecomposableResult):
            return [f"[route] {case.name} expected degrade actual=plan"]
        if decision.reason != "method_constraint_lost" or not decision.fallback_notice:
            failures.append(
                f"[route] {case.name} expected visible method_constraint_lost actual={decision}"
            )
        return failures

    if isinstance(decision, NotDecomposableResult):
        return [f"[route] {case.name} expected plan actual={decision.reason}"]
    if not decision:
        return [f"[route] {case.name} expected plan actual=empty"]
    first = decision[0]
    if first.skill_id != case.expected_tool_id:
        failures.append(
            f"[route] {case.name} expected_tool={case.expected_tool_id} actual={first.skill_id}"
        )
        return failures
    if len(decision) < 2 or decision[1].skill_id != "chat":
        failures.append(f"[transcribe] {case.name} missing chat transcribe step")

    tool_args = first.payload.get("tool_args")
    if not isinstance(tool_args, dict):
        failures.append(f"[execute] {case.name} missing tool_args")
        return failures
    result = invoker.execute(
        first.skill_id,
        tool_args,
        session_id="d3-drill",
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )
    if result.status != "completed" or not isinstance(result.result, dict):
        failures.append(f"[execute] {case.name} status={result.status} error={result.error}")
        return failures
    actual = _extract_result(first.skill_id, result.result)
    if actual != case.expected_result:
        failures.append(
            f"[execute] {case.name} expected_result={case.expected_result!r} actual={actual!r}"
        )
    formatted = str(result.result.get("formatted") or "")
    if str(case.expected_result) not in formatted:
        failures.append(f"[transcribe] {case.name} formatted output missing expected result")
    return failures


def _extract_result(tool_id: str, result: dict[str, Any]) -> object:
    trace = result.get("trace")
    if not isinstance(trace, dict):
        return None
    if tool_id == "algorithm_crc32":
        return trace.get("hex")
    if tool_id == "algorithm_gcd":
        return trace.get("result")
    if tool_id == "algorithm_quicksort":
        return trace.get("result")
    return trace.get("result")


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_builtin(
        ToolManifest(
            tool_id="algorithm_crc32",
            display_name="CRC-32 算法",
            description="本地确定性 CRC-32 UTF-8 校验，返回按位迭代轨迹与校验值。",
            tool_type="builtin",
            permission="allow",
            scope="local_computation",
            params_schema={"type": "object", "required": ["text"]},
            return_schema={"type": "object"},
            handler_module="offline_companion.core.tools.crc32_tool",
            handler_function="crc32_tool",
            external_config=None,
            version="1.0.0",
            algorithm_names=("crc", "crc32", "crc-32"),
            trigger_keywords=("crc", "crc32", "crc-32"),
        ),
        crc32_tool,
    )
    registry.register_builtin(
        ToolManifest(
            tool_id="algorithm_gcd",
            display_name="欧几里得算法",
            description="本地确定性最大公约数工具，返回辗转相除余数序列。",
            tool_type="builtin",
            permission="allow",
            scope="local_computation",
            params_schema={"type": "object", "required": ["left", "right"]},
            return_schema={"type": "object"},
            handler_module="offline_companion.core.tools.gcd_tool",
            handler_function="gcd_tool",
            external_config=None,
            version="1.0.0",
            algorithm_names=("欧几里得", "gcd"),
            trigger_keywords=("最大公约数", "gcd"),
        ),
        gcd_tool,
    )
    registry.register_builtin(
        ToolManifest(
            tool_id="algorithm_quicksort",
            display_name="快速排序算法",
            description="本地确定性快速排序工具，返回每轮分区快照。",
            tool_type="builtin",
            permission="allow",
            scope="local_computation",
            params_schema={"type": "object", "required": ["values"]},
            return_schema={"type": "object"},
            handler_module="offline_companion.core.tools.quicksort_tool",
            handler_function="quicksort_tool",
            external_config=None,
            version="1.0.0",
            algorithm_names=("快速排序", "quicksort"),
            trigger_keywords=("快速排序", "quicksort"),
        ),
        quicksort_tool,
    )
    return registry


if __name__ == "__main__":
    raise SystemExit(main())
