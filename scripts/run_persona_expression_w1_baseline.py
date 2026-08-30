"""拟人表述 W1 baseline runner。

摘要：
    按预注册 fixture 运行 40 条判例与双 seed 50 轮 probe，输出原始回复、
    召回计数与可重算指标。默认 echo backend 用于 CI/dry-run；传入 GGUF
    模型路径时走生产本地推理 backend。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from offline_companion.core.memory_lifecycle.manager import MemoryLifecycleManager
from offline_companion.core.persona_session.persona_loader import load_persona_file
from offline_companion.core.persona_session.session import PersonaSessionCore
from offline_companion.runtime.inference_backend.backend import create_llama_backend
from offline_companion.runtime.inference_backend.mock import EchoBackend
from offline_companion.runtime.storage_index.engine import (
    append_message,
    connect,
    new_session,
    recent_messages,
)
from offline_companion.shared.types import OceanVector, Persona
from persona_expression_metrics import calculate_metrics

DEFAULT_CASES = REPO_ROOT / "fixtures" / "persona_expression" / "w1_cases.json"
DEFAULT_PROBE = REPO_ROOT / "fixtures" / "persona_expression" / "w1_probe_turns.json"
DEFAULT_PERSONA = REPO_ROOT / "configs" / "personas" / "default.yaml"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "persona_expression"
PROBE_SEEDS = (42, 1337)


class SeededEchoBackend(EchoBackend):
    """摘要：带 seed 标记的确定性 echo backend，供 runner dry-run 使用。"""

    def __init__(self, label: str, seed: int | None = None) -> None:
        super().__init__(label=label)
        self.seed = seed

    def generate(
        self,
        *,
        system_prompt,
        history,
        user_message,
        memory_block,
        max_tokens=256,
    ) -> str:
        seed_text = f" seed={self.seed}" if self.seed is not None else ""
        history_text = f" history={len(history)}"
        memory_text = f"\n\n[memory]\n{memory_block}" if str(memory_block).strip() else ""
        return f"[{self.label}{seed_text}{history_text}] {user_message}{memory_text}"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _load_persona(path: Path) -> Persona:
    if path.is_file():
        return load_persona_file(path)
    return Persona(
        persona_id="default",
        name="default",
        system_prompt="你是一个本地运行的离线陪伴助手，回答应自然、诚实、克制。",
        role_lock=True,
        memory_default_on=True,
        default_companion_display_name="助手一只",
        companion_display_name=None,
        raw={},
        ocean=OceanVector(0.5, 0.5, 0.5, 0.5, 0.5),
    )


def _build_backend(args: argparse.Namespace, *, seed: int | None = None):
    if args.backend == "echo":
        return SeededEchoBackend("w1-echo", seed=seed)
    if args.model is None:
        raise SystemExit("--backend llama 需要提供 --model")
    return create_llama_backend(
        args.model,
        n_ctx=args.n_ctx,
        n_gpu_layers=args.n_gpu_layers,
        verbose=args.verbose,
        run_health_check=not args.skip_health_check,
        seed=seed,
    )


def _seed_memory(conn, session_id: str, memory_bundle: list[dict[str, Any]]) -> None:
    for memory in memory_bundle:
        MemoryLifecycleManager.add_memory_chunk(
            conn,
            str(memory["content"]),
            session_id=session_id,
            source="w1-baseline-seed",
            meta={"fixture_id": memory["id"], "memory_type": "fact"},
        )


def _assert_memory_injection_live(core: PersonaSessionCore, backend, memory_bundle: list[dict[str, Any]]) -> None:
    with tempfile.TemporaryDirectory(prefix="oc-w1-memory-check-") as temp_dir:
        conn = connect(Path(temp_dir) / "memory-check.db")
        try:
            session_id = "w1-memory-check"
            new_session(conn, session_id, "default", title=None)
            _seed_memory(conn, session_id, memory_bundle)
            result = core.assemble_reply(
                backend,
                conn,
                user_message="我下周三要考什么来着？",
                history=[],
                memory_enabled=True,
                max_tokens=128,
                audit_arithmetic=False,
            )
            if len(result.memory_recalls) <= 0:
                raise RuntimeError("W1 M 子集预灌记忆未触发召回，拒绝继续 baseline")
        finally:
            conn.close()


def _run_case(
    *,
    case: dict[str, Any],
    memory_bundle: list[dict[str, Any]],
    persona: Persona,
    backend,
    temp_root: Path,
    max_tokens: int,
) -> dict[str, Any]:
    session_id = f"w1-{case['id']}"
    conn = connect(temp_root / f"{session_id}.db")
    try:
        new_session(conn, session_id, persona.persona_id, title=None)
        if case["scenario"] == "memory":
            _seed_memory(conn, session_id, memory_bundle)
        core = PersonaSessionCore(persona)
        replies: list[str] = []
        turns_out: list[dict[str, Any]] = []
        recall_counts: list[int] = []
        for turn in case["turns"]:
            user_message = str(turn["user"])
            history = recent_messages(conn, session_id, limit=20)
            result = core.assemble_reply(
                backend,
                conn,
                user_message=user_message,
                history=history,
                memory_enabled=True,
                max_tokens=max_tokens,
            )
            append_message(conn, session_id, "user", user_message, {"case_id": case["id"]})
            append_message(conn, session_id, "assistant", result.reply, {"case_id": case["id"]})
            replies.append(result.reply)
            turns_out.append({"user": user_message})
            recall_counts.append(len(result.memory_recalls))
        return {
            "id": case["id"],
            "scenario": case["scenario"],
            "group": case.get("group", case["id"]),
            "focus": case.get("focus", []),
            "turns": turns_out,
            "replies": replies,
            "recall_counts": recall_counts,
        }
    finally:
        conn.close()


def _run_probe_seed(
    *,
    turns: list[dict[str, Any]],
    persona: Persona,
    backend,
    temp_root: Path,
    seed: int,
    max_tokens: int,
) -> dict[str, Any]:
    session_id = f"w1-probe-seed{seed}"
    conn = connect(temp_root / f"{session_id}.db")
    try:
        new_session(conn, session_id, persona.persona_id, title=None)
        core = PersonaSessionCore(persona)
        replies: list[dict[str, Any]] = []
        identity_probes: list[dict[str, Any]] = []
        for turn in turns:
            user_message = str(turn["user"])
            history = recent_messages(conn, session_id, limit=20)
            result = core.assemble_reply(
                backend,
                conn,
                user_message=user_message,
                history=history,
                memory_enabled=True,
                max_tokens=max_tokens,
            )
            append_message(conn, session_id, "user", user_message, {"probe_seed": seed})
            append_message(conn, session_id, "assistant", result.reply, {"probe_seed": seed})
            record = {
                "turn": int(turn["turn"]),
                "domain": turn["domain"],
                "user": user_message,
                "reply": result.reply,
                "is_probe": bool(turn.get("is_probe", False)),
            }
            replies.append(record)
            if record["is_probe"]:
                identity_probes.append(record)
        probe_payload = {
            "cases": [
                {
                    "id": f"probe-seed{seed}",
                    "scenario": "chat",
                    "group": f"probe-seed{seed}",
                    "turns": [{"user": item["user"]} for item in replies],
                    "replies": [item["reply"] for item in replies],
                }
            ]
        }
        drift = calculate_metrics(probe_payload)["aggregate"]
        return {"replies": replies, "identity_probes": identity_probes, "drift": drift}
    finally:
        conn.close()


def run_baseline(args: argparse.Namespace) -> dict[str, Any]:
    """摘要：执行 W1 baseline 并返回可落档 payload。"""
    cases_fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    probe_fixture = json.loads(args.probe.read_text(encoding="utf-8"))
    persona = _load_persona(args.persona)
    case_backend = _build_backend(args)
    core = PersonaSessionCore(persona)
    memory_bundle = list(cases_fixture.get("memory_bundle", []))
    _assert_memory_injection_live(core, case_backend, memory_bundle)
    with tempfile.TemporaryDirectory(prefix="oc-w1-baseline-") as temp_dir:
        temp_root = Path(temp_dir)
        case_results = [
            _run_case(
                case=case,
                memory_bundle=memory_bundle,
                persona=persona,
                backend=case_backend,
                temp_root=temp_root,
                max_tokens=args.max_tokens,
            )
            for case in cases_fixture["cases"]
        ]
        probe_results = {}
        for seed in PROBE_SEEDS:
            probe_backend = _build_backend(args, seed=seed)
            probe_results[f"seed{seed}"] = _run_probe_seed(
                turns=probe_fixture["turns"],
                persona=persona,
                backend=probe_backend,
                temp_root=temp_root,
                seed=seed,
                max_tokens=args.max_tokens,
            )
    payload = {
        "meta": {
            "commit": _git_commit(),
            "model": args.backend if args.backend == "echo" else str(args.model),
            "seeds": list(PROBE_SEEDS),
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "persona": persona.persona_id,
        },
        "cases": case_results,
        "metrics": {},
        "probe": probe_results,
        "verdicts": {"T": {}, "M": {}},
    }
    payload["metrics"] = calculate_metrics(payload)
    return payload


def main() -> int:
    """摘要：命令行入口，运行 baseline 并写出 JSON。"""
    parser = argparse.ArgumentParser(description="运行拟人表述 W1 baseline")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--probe", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--persona", type=Path, default=DEFAULT_PERSONA)
    parser.add_argument("--backend", choices=("echo", "llama"), default="echo")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--n-ctx", type=int, default=2048)
    parser.add_argument("--n-gpu-layers", type=int, default=0)
    parser.add_argument("--skip-health-check", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    payload = run_baseline(args)
    output = args.output
    if output is None:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        output = DEFAULT_OUTPUT_DIR / f"w1_baseline_{args.backend}_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
