"""trusted_skill_bootstrap：在受信路径内装载 seccomp 后再执行 Skill 入口。"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

from offline_companion.shell.skill_manager.seccomp.loader import load_profile
from offline_companion.shell.skill_manager.seccomp.profiles import SECCOMP_PROFILE_COMPUTE

_ENTRYPOINT_ENV = "OFFLINE_COMPANION_SKILL_ENTRYPOINT"
_PROFILE_ENV = "OFFLINE_COMPANION_SKILL_SECCOMP_PROFILE"
_STATUS_ENV = "OFFLINE_COMPANION_SKILL_SECCOMP_STATUS"
_REASON_ENV = "OFFLINE_COMPANION_SKILL_SECCOMP_REASON"


def main() -> int:
    """摘要：装载 seccomp 并执行 Skill 入口脚本。"""
    entrypoint = os.environ.get(_ENTRYPOINT_ENV, "").strip()
    if not entrypoint:
        raise RuntimeError(f"缺少环境变量 {_ENTRYPOINT_ENV}")
    profile_name = os.environ.get(_PROFILE_ENV, SECCOMP_PROFILE_COMPUTE).strip() or SECCOMP_PROFILE_COMPUTE
    result = load_profile(profile_name)
    os.environ[_STATUS_ENV] = "applied" if result.applied else "skipped"
    os.environ[_REASON_ENV] = result.reason
    script_path = Path(entrypoint).resolve()
    sys.argv = [str(script_path)]
    runpy.run_path(str(script_path), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
