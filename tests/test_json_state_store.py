"""JSON 状态备份与恢复测试。"""

from __future__ import annotations

import json
from pathlib import Path

from offline_companion.storage.json_state_store import JsonStateStore, check_state_integrity


def test_second_save_creates_backup(tmp_path: Path) -> None:
    store = JsonStateStore(tmp_path)
    path = tmp_path / "settings.json"

    store.save(path, {"version": 1})
    store.save(path, {"version": 2})

    backups = list((tmp_path / "backups").glob("settings.json.bak.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == {"version": 1}


def test_corrupt_main_file_restores_latest_valid_backup(tmp_path: Path) -> None:
    store = JsonStateStore(tmp_path)
    path = tmp_path / "settings.json"
    store.save(path, {"version": 1})
    store.save(path, {"version": 2})
    path.write_text("{broken", encoding="utf-8")

    result = store.load_result(path, {})

    assert result.value == {"version": 1}
    assert result.repaired is True
    assert result.backup_path is not None
    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 1}


def test_backup_rotation_keeps_latest_three_versions(tmp_path: Path) -> None:
    store = JsonStateStore(tmp_path, max_backups=3)
    path = tmp_path / "settings.json"

    for version in range(5):
        store.save(path, {"version": version})

    backups = sorted((tmp_path / "backups").glob("settings.json.bak.*"))
    assert len(backups) == 3
    assert [json.loads(path.read_text(encoding="utf-8"))["version"] for path in backups] == [1, 2, 3]


def test_backup_rotation_preserves_order_when_clock_does_not_advance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = JsonStateStore(tmp_path, max_backups=3)
    path = tmp_path / "settings.json"
    monkeypatch.setattr("offline_companion.storage.json_state_store.time.time_ns", lambda: 1)

    for version in range(5):
        store.save(path, {"version": version})

    backups = sorted((tmp_path / "backups").glob("settings.json.bak.*"))
    versions = [json.loads(item.read_text(encoding="utf-8"))["version"] for item in backups]
    assert versions == [1, 2, 3]


def test_corrupt_file_without_backup_returns_default(tmp_path: Path) -> None:
    store = JsonStateStore(tmp_path)
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")

    result = store.load_result(path, {"theme": "light"})

    assert result.value == {"theme": "light"}
    assert result.corrupt is True
    assert result.repaired is False


def test_integrity_check_repairs_known_state_file(tmp_path: Path) -> None:
    store = JsonStateStore(tmp_path)
    path = tmp_path / "settings.json"
    store.save(path, {"theme": "dark"})
    store.save(path, {"theme": "light"})
    path.write_text("{broken", encoding="utf-8")

    repaired = check_state_integrity(tmp_path)

    assert repaired == ["settings.json"]
    assert json.loads(path.read_text(encoding="utf-8")) == {"theme": "dark"}
