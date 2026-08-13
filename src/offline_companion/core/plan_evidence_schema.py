"""plan_evidence_schema：计划阶段结构化 evidence 必填字段。"""

from __future__ import annotations

STAGE_EVIDENCE_SCHEMA: dict[str, list[str]] = {
    "planning": [
        "modules",
        "data_flow",
    ],
    "tdd": [
        "test_command",
        "test_result",
    ],
    "implementation": [
        "files_changed",
        "summary",
    ],
    "review": [
        "approved",
        "issues",
    ],
    "verification": [
        "command",
        "exit_code",
        "output_summary",
    ],
}
