"""便携运行时与 configs 路径解析测试。"""

from __future__ import annotations

import os
import shutil
import sys

from offline_companion.shared.runtime_paths import configs_dir, data_root, dev_repo_root

from tests.conftest import patch_platform_user_data_home


def test_dev_repo_root_has_configs():
    root = dev_repo_root()
    assert (root / "configs" / "personas" / "default.yaml").is_file()


def test_data_root_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFLINE_COMPANION_DATA_DIR", str(tmp_path / "OfflineCompanion"))
    assert data_root() == (tmp_path / "OfflineCompanion").resolve()


def test_configs_dir_uses_seeded_data_dir(tmp_path, monkeypatch):
    data = tmp_path / "OfflineCompanion"
    cfg = data / "configs" / "personas"
    cfg.mkdir(parents=True)
    shutil.copy(
        dev_repo_root() / "configs" / "personas" / "default.yaml",
        cfg / "default.yaml",
    )
    monkeypatch.setenv("OFFLINE_COMPANION_DATA_DIR", str(data))
    assert configs_dir() == (data / "configs").resolve()


def test_portable_seed_copies_configs(tmp_path, monkeypatch):
    from offline_companion.shell.ui_host import portable_runtime

    bundle = tmp_path / "bundle"
    shutil.copytree(dev_repo_root() / "configs", bundle / "configs", dirs_exist_ok=True)
    user_base = tmp_path / "user_data"
    data = user_base / "OfflineCompanion"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    patch_platform_user_data_home(monkeypatch, user_base)

    root = portable_runtime.setup_portable_env()
    assert root == data.resolve()
    assert (data / "configs" / "personas" / "default.yaml").is_file()
    assert (data / "logs" / "companion.log").is_file()
    assert os.environ["OFFLINE_COMPANION_DATA_DIR"] == str(data.resolve())
