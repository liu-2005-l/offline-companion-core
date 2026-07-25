#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""offline-companion 全量验收门禁编排器。

定位：
    只做步骤编排、子进程执行、结果汇总，不承载任何业务测试逻辑。
    所有功能验证全部下沉到 pytest 或独立 smoke 脚本，主脚本保持纯净。

运行模式：
    默认全量验收：执行所有门禁项 + 外围冒烟，用于合入门禁。
    --fast 快速门禁：仅执行核心单元测试 + 安全检查，用于开发期快速校验。

用法：
    python scripts/full_acceptance.py
    python scripts/full_acceptance.py --fast
    python scripts/full_acceptance.py --fail-fast
    python scripts/full_acceptance.py --skip-gpu --skip-cloud
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# 路径常量
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PY = sys.executable


# ===================== 数据结构定义 =====================
@dataclass(frozen=True)
class StepDef:
    """单个验收步骤的定义，所有步骤统一通过数据配置，不写硬编码逻辑。"""

    name: str
    cmd: list[str]
    is_gate: bool = True
    skip: bool | Callable[[], bool] = False
    cwd: Path = ROOT


@dataclass(frozen=True)
class StepResult:
    """单个步骤执行结果。"""

    name: str
    returncode: int
    elapsed_s: float
    summary: str


@dataclass(frozen=True)
class SkippedStep:
    """被跳过的验收步骤。"""

    name: str
    reason: str


# ===================== 基础工具函数 =====================
def _configure_stdio_utf8() -> None:
    """兼容 Windows 控制台中文输出。"""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _build_env() -> dict[str, str]:
    """构造子进程隔离环境，完全不污染主进程。"""
    env = {**os.environ}
    env["PYTHONPATH"] = str(SRC)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def _decode_stream(data: bytes | None) -> str:
    """多编码容错解码，避免 Windows 编码差异导致中断。"""
    if not data:
        return ""
    for encoding in ("utf-8", "gbk", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_failure_summary(stdout: str, stderr: str) -> str:
    """提取失败关键信息，最多取最后3条关键行，减少翻日志成本。"""
    keywords = ("[FAIL]", "FAILED", "ERROR", "Traceback", "AssertionError")
    lines = [
        line.strip()
        for line in f"{stderr}\n{stdout}".splitlines()
        if line.strip() and any(k in line for k in keywords)
    ]
    if not lines:
        lines = [line.strip() for line in f"{stderr}\n{stdout}".splitlines() if line.strip()]
    return " | ".join(lines[-3:])[:300] if lines else "无输出"


def _preflight_check() -> list[str]:
    """前置环境自检，提前发现基础环境问题，不用跑一半才报错。"""
    errors: list[str] = []
    if not SRC.is_dir():
        errors.append(f"源码目录不存在: {SRC}")
    if not (ROOT / "tests").is_dir():
        errors.append(f"测试目录不存在: {ROOT / 'tests'}")
    if sys.version_info < (3, 10):
        errors.append(f"Python 版本过低: {sys.version}, 要求 >= 3.10")
    return errors


# ===================== 步骤执行核心 =====================
def _run_step(step: StepDef) -> StepResult:
    """执行单个验收步骤，统一输出格式与结果封装。"""
    print(f"\n{'=' * 60}\n>>> {step.name}\n{'=' * 60}")
    print("$", " ".join(step.cmd))

    started = time.perf_counter()
    proc = subprocess.run(
        step.cmd,
        cwd=str(step.cwd),
        env=_build_env(),
        capture_output=True,
    )
    elapsed_s = time.perf_counter() - started

    stdout = _decode_stream(proc.stdout)
    stderr = _decode_stream(proc.stderr)
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="", file=sys.stderr)

    status = "PASS" if proc.returncode == 0 else "FAIL"
    print(f"\n[{status}] {step.name} | 耗时 {elapsed_s:.2f}s")

    return StepResult(
        name=step.name,
        returncode=proc.returncode,
        elapsed_s=elapsed_s,
        summary=_extract_failure_summary(stdout, stderr),
    )


# ===================== 步骤清单配置 =====================
def _skip_reason(step: StepDef, args: argparse.Namespace) -> str | None:
    """返回步骤跳过原因；不跳过时返回 None。"""
    explicit_skip = step.skip if isinstance(step.skip, bool) else step.skip()
    if explicit_skip:
        return "命令行参数或运行环境要求跳过"
    if args.fast and not step.is_gate:
        return "fast 模式仅执行核心门禁项"
    return None


def _build_step_list(args: argparse.Namespace) -> tuple[list[StepDef], list[SkippedStep]]:
    """根据参数生成最终执行步骤清单，所有步骤集中定义，便于维护扩展。"""
    steps: list[StepDef] = [
        # ========== 核心门禁项（--fast 也执行） ==========
        StepDef(
            name="pytest 核心集",
            cmd=[PY, "-m", "pytest", "-q", "tests/test_state_manager.py", "tests/test_runtime_sandbox.py", "tests/test_check_imports.py", "--tb=short"],
            is_gate=True,
            skip=lambda: not args.fast,
        ),
        StepDef(
            name="pytest 全量",
            cmd=[PY, "-m", "pytest", "-q", "tests/", "--tb=short"],
            is_gate=False,
            skip=lambda: args.fast,
        ),
        StepDef(
            name="ruff 代码检查",
            cmd=[PY, "-m", "ruff", "check", "src", "tests", "scripts"],
            is_gate=True,
            skip=args.skip_lint,
        ),
        StepDef(
            name="分层依赖检查",
            cmd=[PY, "scripts/ci/check_imports.py"],
            is_gate=True,
        ),
        StepDef(
            name="安全合规汇总",
            cmd=[PY, "scripts/ci/security_summary.py", "--static-checks", "--dependency-audit"],
            is_gate=True,
        ),

        # ========== 功能回归（全量模式执行） ==========
        StepDef(
            name="fixture 用例回归",
            cmd=[PY, "scripts/ci/run_eval.py", "--fixtures"],
            is_gate=False,
            skip=args.skip_fixtures,
        ),
        StepDef(
            name="知识 RAG 冒烟",
            cmd=[PY, "scripts/knowledge_smoke.py"],
            is_gate=False,
            skip=args.skip_knowledge,
        ),
        StepDef(
            name="记忆向量冒烟",
            cmd=[PY, "scripts/embedding_smoke.py"],
            is_gate=False,
        ),
        StepDef(
            name="压力测试",
            cmd=[PY, "scripts/stress_test.py", "--turns", "15"],
            is_gate=False,
            skip=args.skip_stress,
        ),
        StepDef(
            name="云端 Stub 冒烟",
            cmd=[PY, "scripts/cloud_smoke.py"],
            is_gate=False,
            skip=args.skip_cloud,
        ),

        # ========== 外围验证 ==========
        StepDef(
            name="GPU 推理验收",
            cmd=[PY, "scripts/gpu_acceptance.py", "--root", str(ROOT)],
            is_gate=False,
            skip=args.skip_gpu or not (ROOT / "scripts" / "gpu_acceptance.py").is_file(),
        ),
        StepDef(
            name="便携包冒烟",
            cmd=[PY, "scripts/packaged_smoke.py"],
            is_gate=False,
            skip=args.skip_packaged or not (ROOT / "scripts" / "packaged_smoke.py").is_file(),
        ),
    ]

    executable: list[StepDef] = []
    skipped: list[SkippedStep] = []
    for step in steps:
        reason = _skip_reason(step, args)
        if reason is None:
            executable.append(step)
        else:
            skipped.append(SkippedStep(name=step.name, reason=reason))
    return executable, skipped


# ===================== 主流程 =====================
def main() -> int:
    """执行验收主流程。"""
    _configure_stdio_utf8()

    # 1. 参数解析
    parser = argparse.ArgumentParser(description="offline-companion 验收门禁编排器")
    parser.add_argument("--fast", action="store_true", help="快速门禁模式，仅执行核心项")
    parser.add_argument("--fail-fast", action="store_true", help="失败立即终止，不继续后续步骤")
    parser.add_argument("--skip-gpu", action="store_true", help="跳过 GPU 验收")
    parser.add_argument("--skip-cloud", action="store_true", help="跳过云端 Stub 验收")
    parser.add_argument("--skip-knowledge", action="store_true", help="跳过知识 RAG 验收")
    parser.add_argument("--skip-lint", action="store_true", help="跳过 ruff 代码检查")
    parser.add_argument("--skip-fixtures", action="store_true", help="跳过 fixture 回归测试")
    parser.add_argument("--skip-stress", action="store_true", help="跳过压力测试")
    parser.add_argument("--skip-packaged", action="store_true", help="跳过便携包冒烟")
    args = parser.parse_args()

    # 2. 前置环境自检
    preflight_errors = _preflight_check()
    if preflight_errors:
        print("[ERROR] 环境自检未通过，终止验收：", file=sys.stderr)
        for err in preflight_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # 3. 生成执行步骤
    steps, skipped = _build_step_list(args)
    print(f"验收模式：{'快速门禁' if args.fast else '全量验收'}，共 {len(steps)} 个步骤")
    if skipped:
        print("跳过项：")
        for item in skipped:
            print(f"  [SKIP] {item.name}: {item.reason}")

    # 4. 执行所有步骤
    started = time.perf_counter()
    results: list[StepResult] = []
    for step in steps:
        result = _run_step(step)
        results.append(result)

        if args.fail_fast and result.returncode != 0:
            print("\n[FAIL-FAST] 核心步骤失败，终止验收", file=sys.stderr)
            break

    total_s = time.perf_counter() - started
    failed = [r for r in results if r.returncode != 0]

    # 5. 汇总输出
    print(f"\n{'=' * 60}")
    print(f"验收汇总 | 总耗时 {total_s:.2f}s | 通过 {len(results)-len(failed)}/{len(results)} | 跳过 {len(skipped)}")
    print("-" * 60)
    for r in results:
        status = "PASS" if r.returncode == 0 else "FAIL"
        print(f"  [{status}] {r.name:<20} {r.elapsed_s:>6.2f}s")

    if skipped:
        print("\n跳过详情：")
        for item in skipped:
            print(f"  - {item.name}: {item.reason}")

    if failed:
        print("\n失败详情：")
        for r in failed:
            print(f"  - {r.name}")
            print(f"    退出码: {r.returncode}")
            print(f"    关键信息: {r.summary}")
        print(f"\n最终结果: 未通过 ({len(failed)} 项失败)")
        return 1

    print("\n最终结果: 全部通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
