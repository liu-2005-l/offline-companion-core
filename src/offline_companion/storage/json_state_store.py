"""摘要：为本地 JSON 状态提供原子写、滚动备份与损坏恢复。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JsonLoadResult:
    """摘要：JSON 状态读取结果及其恢复信息。"""

    value: Any
    repaired: bool = False
    corrupt: bool = False
    backup_path: Path | None = None


class JsonStateStore:
    """摘要：管理数据目录内 JSON 状态文件及最近三个有效备份。"""

    def __init__(self, data_root: Path, *, max_backups: int = 3) -> None:
        """摘要：初始化状态存储。

        参数：
            data_root: 应用数据根目录。
            max_backups: 每个状态文件最多保留的备份数量。
        """
        self.data_root = data_root
        self.backup_dir = data_root / "backups"
        self.max_backups = max(1, int(max_backups))

    def load(self, path: Path, default: Any = None) -> Any:
        """摘要：读取 JSON；主文件损坏时恢复最新有效备份。

        参数：
            path: 状态文件路径。
            default: 文件缺失或无有效备份时的默认值。

        返回值：
            解析或恢复后的 JSON 值。
        """
        return self.load_result(path, default).value

    def load_result(self, path: Path, default: Any = None) -> JsonLoadResult:
        """摘要：读取 JSON，并返回是否发生损坏与恢复。"""
        if not path.is_file():
            return JsonLoadResult(default)
        try:
            value = self._read_valid_json(path, default)
        except (json.JSONDecodeError, OSError, ValueError):
            logger.warning("JSON 状态文件损坏，尝试备份恢复: %s", path)
            return self._load_from_backup(path, default)
        return JsonLoadResult(value)

    def save(self, path: Path, data: Any) -> None:
        """摘要：备份当前有效版本后原子写入新 JSON 状态。"""
        if path.is_file():
            try:
                current = self._read_valid_json(path, data)
            except (json.JSONDecodeError, OSError, ValueError):
                logger.warning("当前 JSON 状态已损坏，跳过备份: %s", path)
            else:
                self._rotate_backup(path, current)
        self._atomic_write(path, data)

    def check_integrity(self, paths: list[Path]) -> list[str]:
        """摘要：检查状态文件并返回已从备份修复的文件名列表。"""
        repaired: list[str] = []
        for path in paths:
            result = self.load_result(path, {})
            if result.repaired:
                repaired.append(path.name)
        return repaired

    def _read_valid_json(self, path: Path, default: Any) -> Any:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if default is not None and not isinstance(value, type(default)):
            raise ValueError(f"JSON 顶层类型不匹配: {path}")
        return value

    def _rotate_backup(self, path: Path, data: Any) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backups = self._backup_paths(path)
        while len(backups) >= self.max_backups:
            backups.pop(0).unlink(missing_ok=True)
        backup_path = self.backup_dir / f"{path.name}.bak.{time.time_ns()}-{uuid.uuid4().hex}"
        self._atomic_write(backup_path, data)

    def _load_from_backup(self, path: Path, default: Any) -> JsonLoadResult:
        for backup_path in reversed(self._backup_paths(path)):
            try:
                value = self._read_valid_json(backup_path, default)
            except (json.JSONDecodeError, OSError, ValueError):
                continue
            self._atomic_write(path, value)
            logger.info("已从备份恢复 JSON 状态: %s <- %s", path, backup_path)
            return JsonLoadResult(
                value=value,
                repaired=True,
                corrupt=True,
                backup_path=backup_path,
            )
        logger.error("JSON 状态损坏且无有效备份: %s", path)
        return JsonLoadResult(default, corrupt=True)

    def _backup_paths(self, path: Path) -> list[Path]:
        if not self.backup_dir.is_dir():
            return []
        return sorted(self.backup_dir.glob(f"{path.name}.bak.*"))

    @staticmethod
    def _atomic_write(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=f"{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(str(temporary_path), str(path))
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise


def check_state_integrity(data_root: Path) -> list[str]:
    """摘要：检查当前仍由 JSON 持久化的用户状态并自动恢复。"""
    filenames = (
        "settings.json",
        "cloud_models.json",
        "improve_plan.json",
        "auth.json",
        "extension_state.json",
    )
    store = JsonStateStore(data_root)
    return store.check_integrity([data_root / filename for filename in filenames])
