#!/usr/bin/env python3
"""摘要：校验 P7 输入并调用 Inno Setup 编译安装器。"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISS_PATH = ROOT / "installer" / "OfflineCompanion.iss"
DIST_DIR = ROOT / "dist" / "OfflineCompanion"
PYPROJECT_PATH = ROOT / "pyproject.toml"


def _project_version() -> str:
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if match is None:
        raise RuntimeError("pyproject.toml 缺少 project.version")
    return match.group(1)


def _installer_version() -> str:
    text = ISS_PATH.read_text(encoding="utf-8")
    match = re.search(r'^#define AppVersion "([^"]+)"', text, flags=re.MULTILINE)
    if match is None:
        raise RuntimeError("OfflineCompanion.iss 缺少 AppVersion")
    return match.group(1)


def validate_inputs() -> None:
    """摘要：验证 frozen 产物、可选模型和安装器版本一致性。"""
    required = (
        DIST_DIR / "OfflineCompanion.exe",
        DIST_DIR / "_internal",
        DIST_DIR / "llama_server" / "llama-server.exe",
        DIST_DIR
        / "_internal"
        / "offline_companion"
        / "shell"
        / "ui_host"
        / "desktop"
        / "static"
        / "index.html",
        ROOT / "README.md",
        ISS_PATH,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("安装器输入不完整：\n- " + "\n- ".join(missing))
    project_version = _project_version()
    installer_version = _installer_version()
    if project_version != installer_version:
        raise RuntimeError(
            f"版本不一致: pyproject={project_version}, installer={installer_version}"
        )


def find_iscc(explicit: Path | None = None) -> Path:
    """摘要：定位 Inno Setup 命令行编译器。"""
    candidates = [] if explicit is None else [explicit]
    command = shutil.which("iscc.exe") or shutil.which("iscc")
    if command:
        candidates.append(Path(command))
    local_app_data = Path.home() / "AppData" / "Local"
    candidates.extend(
        [
            Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
            Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
            local_app_data / "Programs" / "Inno Setup 6" / "ISCC.exe",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("未找到 ISCC.exe，请先安装 Inno Setup 6")


def main(argv: list[str] | None = None) -> int:
    """摘要：执行安装器前置校验和编译。"""
    parser = argparse.ArgumentParser(description="构建 Offline Companion 安装器")
    parser.add_argument("--iscc", type=Path, default=None)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    validate_inputs()
    if args.check_only:
        print("[OK] 安装器输入与版本检查通过。")
        return 0
    iscc = find_iscc(args.iscc)
    completed = subprocess.run(
        [str(iscc), str(ISS_PATH)],
        cwd=ISS_PATH.parent,
        check=False,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
