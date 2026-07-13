#!/usr/bin/env python3
"""摘要：统一安全摘要输出（PR / 夜间评测复用）。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class SecuritySummary:
    static_checks_passed: bool
    security_pytests_passed: bool
    dependency_audit_passed: bool
    notes: tuple[str, ...] = ()

    def format_line(self) -> str:
        parts = [
            "static checks passed" if self.static_checks_passed else "static checks failed",
            "security pytest gate passed" if self.security_pytests_passed else "security pytest gate failed",
            "dependency audit passed" if self.dependency_audit_passed else "dependency audit failed",
        ]
        return "Security summary: " + " | ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="offline-companion security summary")
    parser.add_argument("--static-checks", action="store_true")
    parser.add_argument("--security-pytests", action="store_true")
    parser.add_argument("--dependency-audit", action="store_true")
    args = parser.parse_args()
    summary = SecuritySummary(
        static_checks_passed=args.static_checks,
        security_pytests_passed=args.security_pytests,
        dependency_audit_passed=args.dependency_audit,
    )
    print(summary.format_line())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
