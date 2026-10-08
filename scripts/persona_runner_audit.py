"""摘要：为人格测量 runner 提供 provenance、checkpoint 与 capture 审计工具。"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib.metadata
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_SCHEMA_VERSION = 1
_CONFIG_SECTIONS = ("model", "seeds", "sampling", "switches", "input_files")
_GIT_RECOVERY_HINT = "请在仓库根目录运行，并检查 git 可执行文件与仓库状态。"


class RunnerProvenanceError(RuntimeError):
    """摘要：runner 无法生成可信 provenance 时抛出的稳定异常。"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_git_bytes(*args: str) -> bytes:
    command = ["git", *args]
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        joined = " ".join(command)
        raise RunnerProvenanceError(
            f"git 状态采集失败：{joined}。{_GIT_RECOVERY_HINT}"
        ) from exc
    return bytes(result.stdout)


def compute_worktree_fingerprint() -> str:
    """摘要：计算 tracked diff 与未忽略 untracked 内容的稳定工作树指纹。

    返回值：
        小写十六进制 SHA-256 指纹。

    异常：
        RunnerProvenanceError：Git 查询或未跟踪文件读取失败。
    """

    tracked_bytes = _run_git_bytes("diff", "--binary", "HEAD")
    tracked_sha = hashlib.sha256(tracked_bytes).hexdigest()
    untracked_output = _run_git_bytes("ls-files", "--others", "--exclude-standard")
    try:
        untracked_paths = sorted(
            line.strip()
            for line in untracked_output.decode("utf-8").splitlines()
            if line.strip()
        )
    except UnicodeDecodeError as exc:
        raise RunnerProvenanceError(
            f"未跟踪文件列表不是 UTF-8。{_GIT_RECOVERY_HINT}"
        ) from exc

    untracked_rows: list[str] = []
    for relative_path in untracked_paths:
        path = REPO_ROOT / relative_path
        try:
            file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise RunnerProvenanceError(
                f"未跟踪文件读取失败：{relative_path}。{_GIT_RECOVERY_HINT}"
            ) from exc
        untracked_rows.append(f"{relative_path}:{file_sha}")
    untracked_bytes = "\n".join(untracked_rows).encode("utf-8")
    untracked_sha = hashlib.sha256(untracked_bytes).hexdigest()
    return hashlib.sha256(f"{tracked_sha}{untracked_sha}".encode("ascii")).hexdigest()


def collect_git_state() -> dict[str, Any]:
    """摘要：读取当前 HEAD、dirty 状态与工作树指纹。

    返回值：
        包含 ``git_commit``、``git_dirty`` 与 ``worktree_fingerprint`` 的字典。

    异常：
        RunnerProvenanceError：Git 不可用或 HEAD 为空。
    """

    commit_bytes = _run_git_bytes("rev-parse", "HEAD")
    try:
        git_commit = commit_bytes.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise RunnerProvenanceError(
            f"git rev-parse HEAD 输出无效。{_GIT_RECOVERY_HINT}"
        ) from exc
    if not git_commit:
        raise RunnerProvenanceError(
            f"git rev-parse HEAD 返回空输出。{_GIT_RECOVERY_HINT}"
        )
    status_bytes = _run_git_bytes("status", "--porcelain")
    return {
        "git_commit": git_commit,
        "git_dirty": bool(status_bytes.strip()),
        "worktree_fingerprint": compute_worktree_fingerprint(),
    }


def installed_distribution_version(distribution_name: str) -> str:
    """摘要：读取分发包版本，不导入包本体。

    参数：
        distribution_name: ``importlib.metadata`` 使用的分发包名称。

    返回值：
        非空版本字符串。

    异常：
        RunnerProvenanceError：版本元数据不存在或为空。
    """

    try:
        version = importlib.metadata.version(distribution_name).strip()
    except importlib.metadata.PackageNotFoundError as exc:
        raise RunnerProvenanceError(f"无法读取依赖版本：{distribution_name}") from exc
    if not version:
        raise RunnerProvenanceError(f"依赖版本为空：{distribution_name}")
    return version


def _validate_config_value(value: Any, path: str) -> None:
    if value is None:
        raise RunnerProvenanceError(f"配置指纹字段不可为 None：{path}")
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise RunnerProvenanceError(f"配置指纹键必须为字符串：{path}")
            _validate_config_value(nested, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            _validate_config_value(nested, f"{path}[{index}]")


def build_config_fingerprint(declared: dict[str, Any]) -> dict[str, Any]:
    """摘要：校验 runner 声明配置并生成稳定 JSON 指纹。

    参数：
        declared: 含五类冻结键的 runner 实际配置。

    返回值：
        ``config_sha256`` 与结构化 ``config``。

    异常：
        RunnerProvenanceError：必需键缺失、值为 ``None`` 或不可序列化。
    """

    for key in _CONFIG_SECTIONS:
        if key not in declared or declared[key] is None:
            raise RunnerProvenanceError(f"配置指纹缺少必需键：{key}")
    _validate_config_value(declared, "config")
    try:
        serialized = json.dumps(
            declared,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RunnerProvenanceError("配置指纹包含不可序列化值") from exc
    normalized = json.loads(serialized.decode("utf-8"))
    return {
        "config_sha256": hashlib.sha256(serialized).hexdigest(),
        "config": normalized,
    }


def build_provenance(config_fingerprint: dict[str, Any]) -> dict[str, Any]:
    """摘要：组合首次 checkpoint 所需的完整 provenance。

    参数：
        config_fingerprint: ``build_config_fingerprint`` 的返回值。

    返回值：
        带创建时间、Git 状态与 sticky 漂移标志的 provenance。
    """

    git_state = collect_git_state()
    return {
        "created_at": _utc_now(),
        **git_state,
        "config_fingerprint": copy.deepcopy(config_fingerprint),
        "resumed_history": [],
        "code_drift_detected": False,
        "config_drift_detected": False,
    }


def save_checkpoint(
    path: Path,
    payload: dict[str, Any],
    provenance: dict[str, Any],
    captures: list[dict[str, Any]],
) -> None:
    """摘要：以 v1 包裹结构原子写入 checkpoint。

    参数：
        path: checkpoint 路径。
        payload: 保持旧结构不变的业务 payload。
        provenance: 当前 checkpoint provenance。
        captures: 已完成轮次的 capture 行。
    """

    document = {
        "provenance_schema": PROVENANCE_SCHEMA_VERSION,
        "provenance": provenance,
        "captures": captures,
        "payload": payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_checkpoint_full(path: Path) -> dict[str, Any]:
    """摘要：读取 checkpoint 完整结构，兼容 legacy 平铺对象。

    参数：
        path: checkpoint 路径。

    返回值：
        完整 JSON 对象。

    异常：
        RunnerProvenanceError：根节点不是对象。
    """

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerProvenanceError(f"checkpoint 读取失败：{path}") from exc
    if not isinstance(loaded, dict):
        raise RunnerProvenanceError(f"checkpoint 根节点必须为对象：{path}")
    return loaded


def load_checkpoint_payload(path: Path) -> dict[str, Any]:
    """摘要：剥离新格式审计段，并原样返回 legacy payload。

    参数：
        path: checkpoint 路径。

    返回值：
        可原样嵌入既有矩阵的业务 payload。

    异常：
        RunnerProvenanceError：新格式 ``payload`` 不是对象。
    """

    checkpoint = load_checkpoint_full(path)
    if "payload" not in checkpoint:
        return checkpoint
    payload = checkpoint["payload"]
    if not isinstance(payload, dict):
        raise RunnerProvenanceError(f"checkpoint payload 必须为对象：{path}")
    return payload


def _config_diff_keys(previous: Any, current: Any, prefix: str = "") -> list[str]:
    if isinstance(previous, dict) and isinstance(current, dict):
        differences: list[str] = []
        for key in sorted(set(previous) | set(current)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in previous or key not in current:
                differences.append(path)
                continue
            differences.extend(_config_diff_keys(previous[key], current[key], path))
        return differences
    return [] if previous == current else [prefix or "<root>"]


def reconcile_resume(checkpoint: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """摘要：对账 resume 状态并返回 sticky 漂移结果。

    参数：
        checkpoint: ``load_checkpoint_full`` 返回的完整对象。
        current: 当前 ``build_provenance`` 结果。

    返回值：
        更新后的 provenance、警告列表与 legacy 标志。

    异常：
        RunnerProvenanceError：新旧 provenance 缺少对账字段。
    """

    previous = checkpoint.get("provenance")
    if not isinstance(previous, dict):
        return {
            "provenance": None,
            "warnings": ["legacy_provenance_missing"],
            "legacy": True,
        }

    required = ("git_commit", "git_dirty", "worktree_fingerprint", "config_fingerprint")
    for label, candidate in (("checkpoint", previous), ("current", current)):
        missing = [key for key in required if key not in candidate or candidate[key] is None]
        if missing:
            raise RunnerProvenanceError(
                f"{label} provenance 缺少字段：{','.join(missing)}"
            )

    updated = copy.deepcopy(previous)
    warnings: list[str] = []
    code_drift = bool(previous.get("code_drift_detected", False))
    config_drift = bool(previous.get("config_drift_detected", False))
    if previous["git_commit"] != current["git_commit"]:
        code_drift = True
        warnings.append(
            f"code_drift:git_commit:{previous['git_commit']}->{current['git_commit']}"
        )
    if previous["worktree_fingerprint"] != current["worktree_fingerprint"]:
        code_drift = True
        warnings.append(
            "code_drift:worktree_fingerprint:"
            f"{previous['worktree_fingerprint']}->{current['worktree_fingerprint']}"
        )

    previous_config = previous["config_fingerprint"]
    current_config = current["config_fingerprint"]
    if not isinstance(previous_config, dict) or not isinstance(current_config, dict):
        raise RunnerProvenanceError("config_fingerprint 必须为对象")
    if previous_config.get("config_sha256") != current_config.get("config_sha256"):
        config_drift = True
        differences = _config_diff_keys(
            previous_config.get("config", {}),
            current_config.get("config", {}),
        )
        warnings.append(f"config_drift:{','.join(differences or ['<hash_only>'])}")

    history = list(previous.get("resumed_history") or [])
    history.append(
        {
            "resumed_at": _utc_now(),
            "git_commit": current["git_commit"],
            "git_dirty": current["git_dirty"],
            "worktree_fingerprint": current["worktree_fingerprint"],
        }
    )
    updated["resumed_history"] = history
    updated["code_drift_detected"] = code_drift
    updated["config_drift_detected"] = config_drift
    return {"provenance": updated, "warnings": warnings, "legacy": False}


def load_resume_state(path: Path, current: dict[str, Any]) -> dict[str, Any]:
    """摘要：统一读取 checkpoint payload、capture 与 provenance 对账结果。

    参数：
        path: 待恢复 checkpoint 路径。
        current: 当前运行 provenance。

    返回值：
        含 payload、captures、更新后 provenance、warnings 与 legacy 缺口的对象。

    异常：
        RunnerProvenanceError：checkpoint 审计段结构非法。
    """

    checkpoint = load_checkpoint_full(path)
    payload = load_checkpoint_payload(path)
    reconciled = reconcile_resume(checkpoint, current)
    if reconciled["legacy"]:
        return {
            "payload": payload,
            "captures": [],
            "provenance": None,
            "warnings": reconciled["warnings"],
            "legacy": True,
            "legacy_gap": f"legacy_checkpoint_without_capture:{path}",
        }
    captures = checkpoint.get("captures")
    if not isinstance(captures, list):
        raise RunnerProvenanceError(f"checkpoint captures 必须为列表：{path}")
    return {
        "payload": payload,
        "captures": copy.deepcopy(captures),
        "provenance": reconciled["provenance"],
        "warnings": reconciled["warnings"],
        "legacy": False,
        "legacy_gap": None,
    }


class CaptureSink:
    """摘要：按单轮生命周期深拷贝保存 first/retry 候选事件。"""

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []

    def push(
        self,
        phase: str,
        text: str,
        l4_decision: Any,
        repetition_decision: Any,
    ) -> None:
        """摘要：旁路暂存候选正文与双门原始 decision DTO。

        参数：
            phase: ``first`` 或 ``retry``。
            text: 实际送入出口判定的候选正文。
            l4_decision: L4 原始 decision DTO。
            repetition_decision: 跨轮复读原始 decision DTO。
        """

        self._items.append(
            copy.deepcopy(
                {
                    "phase": phase,
                    "text": text,
                    "l4_decision": l4_decision,
                    "repetition_decision": repetition_decision,
                }
            )
        )

    def drain(self) -> list[dict[str, Any]]:
        """摘要：取走本轮全部候选事件并清空 sink。

        返回值：
            按 push 顺序排列的深拷贝事件列表。
        """

        drained = self._items
        self._items = []
        return drained


def _decision_payload(decision: Any) -> dict[str, Any]:
    if decision is None:
        return {}
    if dataclasses.is_dataclass(decision) and not isinstance(decision, type):
        return dataclasses.asdict(decision)
    if isinstance(decision, dict):
        return copy.deepcopy(decision)
    raise RunnerProvenanceError("capture decision 必须为 dataclass、对象或 None")


def build_capture_row(
    capture_events: list[dict[str, Any]],
    *,
    runner: str,
    arm: str,
    source_kind: str,
    seed: int,
    scenario_id: str,
    turn_index: int,
) -> dict[str, Any]:
    """摘要：把单轮 first/retry 事件整形成冻结六元 join schema。

    参数：
        capture_events: ``CaptureSink.drain`` 返回的单轮事件。
        runner: runner 稳定标识。
        arm: A/B 臂标识。
        source_kind: case/probe/validation 来源类型。
        seed: 当前采样 seed。
        scenario_id: 当前判例或 probe 标识。
        turn_index: 判例内零基轮次。

    返回值：
        含六元 join 键、retry 标记及双阶段原始判定的 JSON 对象。
    """

    phases: dict[str, dict[str, Any]] = {}
    for event in capture_events:
        phase = str(event.get("phase") or "")
        if phase not in {"first", "retry"} or phase in phases:
            raise RunnerProvenanceError(f"capture phase 非法或重复：{phase}")
        phases[phase] = event
    if "first" not in phases:
        raise RunnerProvenanceError("capture 缺少 first 阶段")

    def render(phase: str) -> dict[str, Any]:
        event = phases.get(phase)
        if event is None:
            return {}
        return {
            "text": str(event.get("text") or ""),
            "l4_decision": _decision_payload(event.get("l4_decision")),
            "repetition_decision": _decision_payload(
                event.get("repetition_decision")
            ),
        }

    return {
        "runner": runner,
        "arm": arm,
        "source_kind": source_kind,
        "seed": seed,
        "scenario_id": scenario_id,
        "turn_index": turn_index,
        "retry_taken": "retry" in phases,
        "first": render("first"),
        "retry": render("retry"),
    }


def build_sidecar(
    capture_rows: list[dict[str, Any]],
    matrix_path: Path,
    matrix_bytes: bytes,
    legacy_gap: str | None,
) -> dict[str, Any]:
    """摘要：构造可与终态矩阵机械对账的 candidates sidecar。

    参数：
        capture_rows: 六元 join 键完整的 capture 行。
        matrix_path: 对应终态矩阵路径。
        matrix_bytes: 已落盘矩阵的原始字节。
        legacy_gap: Legacy checkpoint 缺口说明；完整时为 ``None``。

    返回值：
        含矩阵哈希、完整性标志与 capture 行的 sidecar 对象。
    """

    return {
        "meta": {
            "matrix_path": str(matrix_path),
            "matrix_sha256": hashlib.sha256(matrix_bytes).hexdigest(),
            "capture_complete": legacy_gap is None,
            "legacy_gap": legacy_gap,
        },
        "capture_rows": copy.deepcopy(capture_rows),
    }
