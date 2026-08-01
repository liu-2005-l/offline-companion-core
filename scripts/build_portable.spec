# ruff: noqa: F821, I001
"""PyInstaller 配置：构建使用独立 llama-server 的便携版。"""

import shutil
from pathlib import Path

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_all


SPEC_DIR = Path(SPEC).resolve().parent
ROOT = SPEC_DIR.parent
SRC_DIR = ROOT / "src"
CONFIGS_DIR = ROOT / "configs"
DESKTOP_STATIC_DIR = (
    SRC_DIR / "offline_companion" / "shell" / "ui_host" / "desktop" / "static"
)
WEB_TEMPLATES_DIR = SRC_DIR / "offline_companion" / "shell" / "ui_host" / "templates"
VENDOR_DIR = SPEC_DIR / "vendor"
LLAMA_SERVER_EXE = VENDOR_DIR / "llama-server.exe"

if not LLAMA_SERVER_EXE.is_file():
    raise FileNotFoundError(
        f"未找到 {LLAMA_SERVER_EXE}。请从 llama.cpp Windows CPU x64 发布包中解压服务端文件。"
    )

onnxruntime_datas, onnxruntime_binaries, onnxruntime_hidden = collect_all("onnxruntime")
tokenizers_datas, tokenizers_binaries, tokenizers_hidden = collect_all("tokenizers")
sqlite_vec_datas, sqlite_vec_binaries, sqlite_vec_hidden = collect_all("sqlite_vec")

a = Analysis(
    [str(SRC_DIR / "offline_companion" / "__main__.py")],
    pathex=[str(SRC_DIR)],
    binaries=(
        onnxruntime_binaries + tokenizers_binaries + sqlite_vec_binaries
    ),
    datas=(
        [
            (str(CONFIGS_DIR), "configs"),
            (
                str(DESKTOP_STATIC_DIR),
                "offline_companion/shell/ui_host/desktop/static",
            ),
            (
                str(WEB_TEMPLATES_DIR),
                "offline_companion/shell/ui_host/templates",
            ),
        ]
        + onnxruntime_datas
        + tokenizers_datas
        + sqlite_vec_datas
    ),
    hiddenimports=[
        "onnxruntime.providers",
        "onnxruntime.providers.cpu",
        "tokenizers.models",
        "tokenizers.pre_tokenizers",
        "tokenizers.processors",
        "tokenizers.decoders",
        "tokenizers.normalizers",
        "waitress",
    ]
    + onnxruntime_hidden
    + tokenizers_hidden
    + sqlite_vec_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "llama_cpp",
        "torch",
        "matplotlib",
        "pytest",
        "pip",
        "setuptools",
        "distutils",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OfflineCompanion",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="OfflineCompanion",
)

# 原生服务端不能位于 PyInstaller 的 _internal DLL 环境中，需原样复制为 sidecar。
sidecar_dir = Path(CONF["distpath"]) / "OfflineCompanion" / "llama_server"
if sidecar_dir.exists():
    shutil.rmtree(sidecar_dir)
shutil.copytree(VENDOR_DIR, sidecar_dir)
