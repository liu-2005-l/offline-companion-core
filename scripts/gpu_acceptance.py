#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摘要：4090 / CUDA 服务器 Phase 1+Sprint0 一键验收（零交互）。

用法（冷启动，复制整行）::

    cd ~/offline-companion-core && source .venv/bin/activate && \\
    export OFFLINE_COMPANION_GGUF=/root/data/models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf && \\
    export OFFLINE_COMPANION_N_GPU_LAYERS=99 && \\
    python scripts/gpu_acceptance.py --root .

环境变量：
    OFFLINE_COMPANION_GGUF：GGUF 路径（推理步骤必需）
    OFFLINE_COMPANION_N_GPU_LAYERS：默认 99
    OFFLINE_COMPANION_N_CTX：默认 2048
    OFFLINE_COMPANION_SKIP_PYTEST=1：跳过 pytest
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path


class Step:
    """摘要：验收步骤收集器。"""

    def __init__(self) -> None:
        self.failed: list[str] = []
        self.warned: list[str] = []

    def ok(self, name: str, detail: str = "") -> None:
        """摘要：记录通过步骤。"""
        msg = f"[PASS] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)

    def fail(self, name: str, detail: str) -> None:
        """摘要：记录失败步骤。"""
        self.failed.append(name)
        print(f"[FAIL] {name} — {detail}", file=sys.stderr)

    def warn(self, name: str, detail: str) -> None:
        """摘要：记录警告（不导致退出码 1，除非与 fail 并存）。"""
        self.warned.append(name)
        print(f"[WARN] {name} — {detail}")


def find_repo_root(explicit: str | None) -> Path:
    """摘要：解析仓库根目录。

    参数：
        explicit: 显式路径；为空则尝试 cwd 与脚本上级目录。

    返回值：
        含 ``pyproject.toml`` 与 ``src/offline_companion`` 的根路径。
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    here = Path.cwd().resolve()
    for p in [here, Path(__file__).resolve().parents[1]]:
        if (p / "pyproject.toml").is_file() and (p / "src" / "offline_companion").is_dir():
            return p
    return here


def run_cmd(step: Step, name: str, cmd: list[str], *, cwd: Path, timeout: int = 600) -> bool:
    """摘要：运行子进程并打印输出。

    返回值：
        退出码为 0 时 True。
    """
    print(f"\n--- {name} ---")
    print("$", " ".join(cmd))
    t0 = time.perf_counter()
    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(cwd / "src")},
        )
    except subprocess.TimeoutExpired:
        step.fail(name, f"超时 ({timeout}s)")
        return False
    elapsed = time.perf_counter() - t0
    if r.stdout:
        print(r.stdout.rstrip())
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
        step.fail(name, f"{err} ({elapsed:.1f}s)")
        return False
    step.ok(name, f"{elapsed:.1f}s")
    return True


def check_python(step: Step) -> None:
    """摘要：检查 Python 版本。"""
    v = sys.version_info
    if v < (3, 10):
        step.fail("Python 版本", f"需要 >=3.10，当前 {sys.version}")
        return
    step.ok("Python 版本", sys.version.split()[0])
    if v[:2] != (3, 11):
        step.warn("Python 版本", "官方推荐 3.11")


def check_nvidia(step: Step, require_gpu: bool) -> None:
    """摘要：检查 NVIDIA 驱动与 GPU。"""
    if shutil.which("nvidia-smi") is None:
        if require_gpu:
            step.fail("nvidia-smi", "未找到")
        else:
            step.warn("nvidia-smi", "未找到，已跳过")
        return
    r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True)
    if r.returncode != 0:
        step.fail("nvidia-smi", r.stderr or "执行失败")
        return
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    step.ok("nvidia-smi", f"{len(lines)} GPU(s)")
    r2 = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
        capture_output=True,
        text=True,
    )
    if r2.returncode == 0 and r2.stdout.strip():
        print("       ", r2.stdout.strip().replace("\n", " | "))


def check_repo_layout(step: Step, root: Path) -> None:
    """摘要：检查仓库关键路径。"""
    required = [
        "pyproject.toml",
        "configs/personas/default.yaml",
        "configs/safety_replies/zh_v1.yaml",
        "src/offline_companion",
        "scripts/ci/check_imports.py",
    ]
    missing = [p for p in required if not (root / p).exists()]
    if missing:
        step.fail("仓库布局", "缺少: " + ", ".join(missing))
        return
    step.ok("仓库布局", str(root))


def check_packages(step: Step) -> None:
    """摘要：检查核心依赖可 import。"""
    for mod, label in [
        ("yaml", "pyyaml"),
        ("pytest", "pytest"),
        ("offline_companion", "offline-companion-core (editable)"),
    ]:
        try:
            importlib.import_module(mod)
            step.ok(f"import {mod}", label)
        except ImportError as e:
            step.fail(f"import {mod}", str(e))
    try:
        import llama_cpp  # noqa: F401

        step.ok("import llama_cpp", getattr(llama_cpp, "__version__", "unknown"))
    except ImportError:
        step.fail("import llama_cpp", "请 pip install llama-cpp-python")


def run_pytest(step: Step, root: Path, skip: bool) -> None:
    """摘要：运行 pytest 与 check_imports。"""
    if skip:
        step.warn("pytest", "已跳过")
        return
    if not run_cmd(
        step,
        "pytest",
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"],
        cwd=root,
    ):
        return
    run_cmd(step, "check_imports", [sys.executable, "scripts/ci/check_imports.py"], cwd=root)


def run_check_model_cli(
    step: Step,
    root: Path,
    model: Path,
    n_ctx: int,
    n_gpu_layers: int,
) -> None:
    """摘要：CLI check-model 探测。"""
    run_cmd(
        step,
        "CLI check-model",
        [
            sys.executable,
            "-m",
            "offline_companion",
            "check-model",
            "--model",
            str(model),
            "--n-ctx",
            str(min(n_ctx, 512)),
            "--n-gpu-layers",
            str(n_gpu_layers),
        ],
        cwd=root,
        timeout=600,
    )


def smoke_core_api(
    step: Step,
    root: Path,
    model: Path,
    n_ctx: int,
    n_gpu_layers: int,
    max_tokens: int,
    *,
    strict_product: bool,
) -> None:
    """摘要：B3 + B2 + B1 真推理冒烟（含香菜记忆场景）。"""
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
    from offline_companion.core.persona_session.persona_loader import load_persona_file
    from offline_companion.core.persona_session.session import PersonaSessionCore
    from offline_companion.core.safety_boundary.classifier import SafetyTier, classify_user_text
    from offline_companion.core.safety_boundary.fixed_replies import load_safety_replies
    from offline_companion.runtime.inference_backend.backend import create_llama_backend
    from offline_companion.runtime.storage_index.engine import connect, new_session
    from offline_companion.shared.types import MessageRow

    bundle = load_safety_replies(reload=True)
    r_safe = classify_user_text("我不想活了")
    if r_safe.tier is not SafetyTier.CRISIS_SELF or not r_safe.block_model:
        step.fail("B3 安全", f"期望 crisis_self，得到 {r_safe.tier}")
    else:
        step.ok("B3 安全", f"话术库 v{bundle.version} locale={bundle.locale}")

    persona = load_persona_file(root / "configs/personas/default.yaml")
    session_core = PersonaSessionCore(persona)

    with tempfile.TemporaryDirectory(prefix="oc_accept_") as td:
        db = Path(td) / "accept.db"
        conn = connect(db)
        new_session(conn, "accept-s1", persona.persona_id, title="gpu-acceptance")
        MemoryLifecycleManager.add_memory_chunk(
            conn,
            "我讨厌香菜",
            session_id="accept-s1",
            source="acceptance",
        )

        hits = MemoryLifecycleManager.recall(conn, "晚上点菜吃什么好", limit=5)
        if not hits:
            step.fail("B2 recall", "未召回「香菜」相关记忆")
        else:
            step.ok(
                "B2 recall",
                f"命中 {len(hits)} 条, matched_on={hits[0].matched_on!r}",
            )

        print("\n--- 加载 GGUF（可能需数十秒）---")
        t0 = time.perf_counter()
        try:
            backend = create_llama_backend(
                model,
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers,
                run_health_check=True,
            )
        except Exception as e:
            step.fail("C1 加载模型", str(e))
            traceback.print_exc()
            return
        step.ok("C1 加载模型", f"{time.perf_counter() - t0:.1f}s, n_gpu_layers={n_gpu_layers}")

        cases: list[tuple[str, bool, bool]] = [
            ("你好，用一句话介绍你自己。", False, False),
            ("晚上点菜吃什么好？", True, True),
        ]
        history: list[MessageRow] = []
        for user_msg, mem_on, check_cilantro in cases:
            t1 = time.perf_counter()
            try:
                out = session_core.assemble_reply(
                    backend,
                    conn,
                    user_message=user_msg,
                    history=history,
                    memory_enabled=mem_on,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                step.fail(f"B1 推理: {user_msg[:16]}", str(e))
                continue
            gen_s = time.perf_counter() - t1
            preview = (out.reply or "").replace("\n", " ")[:160]
            tag = "memory=on" if mem_on else "memory=off"
            step.ok(f"B1 推理 ({tag})", f"{gen_s:.1f}s, recalls={len(out.memory_recalls)}")
            warn_sec = float(os.environ.get("OFFLINE_COMPANION_GPU_WARN_SEC", "30"))
            if gen_s > warn_sec:
                step.warn(
                    f"B1 耗时 ({tag})",
                    f"{gen_s:.1f}s > {warn_sec}s；请确认 CUDA 版 llama-cpp（见 docs/inference-cuda.md）",
                )
            print(f"       用户: {user_msg}")
            print(f"       助手: {preview}...")

            if check_cilantro:
                if "重要提醒" not in out.memory_block:
                    step.warn("记忆块约束", "memory_block 未含「重要提醒」固定段")
                if "香菜" in (out.reply or ""):
                    msg = "回复仍含「香菜」，模型未遵守禁忌记忆（小模型可能偶发）"
                    if strict_product:
                        step.fail("产品·香菜禁忌", msg)
                    else:
                        step.warn("产品·香菜禁忌", msg)
                else:
                    step.ok("产品·香菜禁忌", "回复未出现「香菜」")

            history.append(
                MessageRow(role="user", content=user_msg, created_at=time.time(), meta={})
            )
            history.append(
                MessageRow(
                    role="assistant",
                    content=out.reply,
                    created_at=time.time(),
                    meta={},
                )
            )


def main() -> int:
    """摘要：验收入口。"""
    parser = argparse.ArgumentParser(description="GPU / Phase1 一键验收（零交互）")
    parser.add_argument("--root", type=str, default=os.environ.get("OFFLINE_COMPANION_ROOT"))
    parser.add_argument("--model", type=str, default=os.environ.get("OFFLINE_COMPANION_GGUF"))
    parser.add_argument(
        "--n-gpu-layers",
        type=int,
        default=int(os.environ.get("OFFLINE_COMPANION_N_GPU_LAYERS", "99")),
    )
    parser.add_argument("--n-ctx", type=int, default=int(os.environ.get("OFFLINE_COMPANION_N_CTX", "2048")))
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--skip-inference", action="store_true")
    parser.add_argument("--no-gpu-required", action="store_true")
    parser.add_argument(
        "--strict-product",
        action="store_true",
        help="香菜场景回复含「香菜」时记为 FAIL（默认仅 WARN）",
    )
    parser.add_argument("--log-file", type=str, default=None, help="同时将 stdout 写入该文件")
    args = parser.parse_args()

    log_fp = None
    if args.log_file:
        log_path = Path(args.log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fp = log_path.open("w", encoding="utf-8")

        class _Tee:
            def write(self, s: str) -> int:
                sys.stdout.write(s)
                log_fp.write(s)
                return len(s)

            def flush(self) -> None:
                sys.stdout.flush()
                log_fp.flush()

        sys.stdout = _Tee()  # type: ignore[assignment]

    step = Step()
    root = find_repo_root(args.root)
    os.chdir(root)

    print("=" * 60)
    print("offline-companion-core · GPU 验收")
    print("ROOT:", root)
    print("MODEL:", args.model or "(未设置)")
    print("N_GPU_LAYERS:", args.n_gpu_layers, "| N_CTX:", args.n_ctx)
    print("=" * 60)

    try:
        check_python(step)
        check_nvidia(step, require_gpu=not args.no_gpu_required and not args.skip_inference)
        check_repo_layout(step, root)
        check_packages(step)

        if os.environ.get("OFFLINE_COMPANION_SKIP_PYTEST") == "1":
            args.skip_pytest = True
        run_pytest(step, root, args.skip_pytest)

        if args.skip_inference:
            step.warn("推理验收", "已 --skip-inference")
        else:
            if not args.model:
                step.fail("GGUF 路径", "请设置 --model 或 OFFLINE_COMPANION_GGUF")
            else:
                model = Path(args.model).expanduser().resolve()
                if not model.is_file():
                    step.fail("GGUF 路径", f"不存在: {model}")
                else:
                    step.ok("GGUF 路径", f"{model.name} ({model.stat().st_size / 1e9:.2f} GB)")
                    run_check_model_cli(step, root, model, args.n_ctx, args.n_gpu_layers)
                    if not step.failed:
                        smoke_core_api(
                            step,
                            root,
                            model,
                            args.n_ctx,
                            args.n_gpu_layers,
                            args.max_tokens,
                            strict_product=args.strict_product,
                        )

        print("\n" + "=" * 60)
        if step.failed:
            print("结果: 未通过 —", ", ".join(step.failed))
            code = 1
        elif step.warned:
            print("结果: 通过（有警告）—", ", ".join(step.warned))
            code = 0
        else:
            print("结果: 全部通过")
            code = 0
        print("=" * 60)
        return code
    finally:
        if log_fp is not None:
            log_fp.close()


if __name__ == "__main__":
    raise SystemExit(main())
