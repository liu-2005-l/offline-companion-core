"""摘要：汇总 W3-P1 逐轮 L4 trace，生成重校批可审计计数。"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def summarize_l4_records(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """摘要：把逐轮 trace 汇总为 AC-13 冻结计数。

    参数：
        records: trace 本体或带 ``persona_l4_trace`` 的归档记录。
    返回值：
        zone/family、guard 拦截与 E3 fallthrough 的确定性汇总。
    """
    zone_family_hits: dict[str, Counter[str]] = defaultdict(Counter)
    guard_blocked_families: Counter[str] = Counter()
    fallthrough_counts: Counter[str] = Counter()
    record_count = 0

    for record in records:
        record_count += 1
        trace = _trace_payload(record)
        for prefix in ("first", "retry"):
            zone = _optional_text(trace.get(f"{prefix}_zone"))
            family = _optional_text(trace.get(f"{prefix}_family"))
            if zone is not None and family is not None:
                zone_family_hits[zone][family] += 1

        for family in record.get("guard_blocked_families") or ():
            normalized = _optional_text(family)
            if normalized is not None:
                guard_blocked_families[normalized] += 1

        for warning in trace.get("warnings") or ():
            if warning == "l4_e3_fallthrough_hit":
                fallthrough_counts["hit"] += 1
            elif warning == "l4_e3_fallthrough_error":
                fallthrough_counts["error"] += 1

    identity_cliff_hits = zone_family_hits.get("identity_cliff", Counter())
    return {
        "record_count": record_count,
        "zone_family_hits": {
            zone: dict(sorted(family_counts.items()))
            for zone, family_counts in sorted(zone_family_hits.items())
        },
        "identity_cliff_family_hits": dict(sorted(identity_cliff_hits.items())),
        "local_storage_denial_hit_count": _family_hit_count(
            zone_family_hits,
            "local_storage_denial",
        ),
        "companion_role_denial_hit_count": _family_hit_count(
            zone_family_hits,
            "companion_role_denial",
        ),
        "guard_blocked_family_counts": dict(sorted(guard_blocked_families.items())),
        "guard_blocked_count": sum(guard_blocked_families.values()),
        "e3_fallthrough_counts": {
            "hit": fallthrough_counts["hit"],
            "error": fallthrough_counts["error"],
        },
    }


def _trace_payload(record: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = record.get("persona_l4_trace")
    return nested if isinstance(nested, Mapping) else record


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _family_hit_count(
    zone_family_hits: Mapping[str, Counter[str]],
    family: str,
) -> int:
    return sum(family_counts[family] for family_counts in zone_family_hits.values())


def main() -> int:
    """摘要：读取 JSON 归档并输出 AC-13 聚合结果。"""
    parser = argparse.ArgumentParser(description="汇总 W3-P1 L4 trace 归档")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("trace archive must be a list or contain records list")
    summary = summarize_l4_records(records)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
