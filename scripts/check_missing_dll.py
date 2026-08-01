#!/usr/bin/env python3
"""摘要：扫描 Windows 便携包 PE 文件的未满足 DLL 依赖。"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from pathlib import Path

VC_RUNTIME_PREFIXES = ("concrt", "msvcp", "vcruntime")
SYSTEM_PREFIXES = ("api-ms-win-", "ext-ms-win-")


def _load_pefile():
    """摘要：加载构建期 PE 解析依赖并提供明确安装提示。"""
    try:
        import pefile
    except ImportError as exc:
        raise RuntimeError("缺少 pefile，请执行: python -m pip install pefile") from exc
    return pefile


def _dependencies(path: Path) -> set[str]:
    """摘要：读取单个 PE 文件的普通与延迟加载 DLL 依赖。"""
    pefile = _load_pefile()
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(
            directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
            ]
        )
    except pefile.PEFormatError:
        return set()

    names: set[str] = set()
    for attribute in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
        for entry in getattr(pe, attribute, ()):
            names.add(entry.dll.decode("ascii", errors="replace").lower())
    pe.close()
    return names


def _system_dll_names() -> set[str]:
    """摘要：收集当前 Windows 系统目录提供的 DLL 名称。"""
    windows_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    names: set[str] = set()
    for directory in (windows_dir / "System32", windows_dir / "SysWOW64"):
        if directory.is_dir():
            names.update(path.name.lower() for path in directory.glob("*.dll"))
    return names


def scan_portable(root: Path) -> tuple[dict[str, set[Path]], dict[str, set[Path]]]:
    """摘要：扫描便携包并区分缺失依赖与未随包携带的 VC++ Runtime。

    参数：
        root: PyInstaller onedir 输出目录。

    返回值：
        ``(missing, external_vc_runtime)``，值为依赖该 DLL 的 PE 文件集合。
    """
    root = root.resolve()
    pe_paths = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".exe", ".dll", ".pyd"}
    ]
    bundled = {path.name.lower() for path in pe_paths}
    system = _system_dll_names()
    missing: dict[str, set[Path]] = defaultdict(set)
    external_vc_runtime: dict[str, set[Path]] = defaultdict(set)

    for path in pe_paths:
        relative_path = path.relative_to(root)
        is_sidecar = relative_path.parts[:1] == ("llama_server",)
        sibling_names = {
            sibling.name.lower() for sibling in path.parent.iterdir() if sibling.is_file()
        }
        for dependency in _dependencies(path):
            if dependency.startswith(SYSTEM_PREFIXES):
                continue
            if is_sidecar and dependency in sibling_names:
                continue
            if not is_sidecar and dependency in bundled:
                continue
            if dependency.startswith(VC_RUNTIME_PREFIXES):
                external_vc_runtime[dependency].add(relative_path)
            elif dependency not in system:
                missing[dependency].add(relative_path)
    return dict(missing), dict(external_vc_runtime)


def _print_findings(title: str, findings: dict[str, set[Path]]) -> None:
    print(title)
    for dependency, consumers in sorted(findings.items()):
        sample = ", ".join(str(path) for path in sorted(consumers)[:3])
        print(f"  {dependency}: {sample}")


def main(argv: list[str] | None = None) -> int:
    """摘要：执行 DLL 扫描并以退出码表示便携包是否自给自足。"""
    parser = argparse.ArgumentParser(description="扫描 Windows 便携包 DLL 依赖")
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path("dist/OfflineCompanion"),
    )
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("该脚本仅支持 Windows")
    if not args.root.is_dir():
        parser.error(f"目录不存在: {args.root}")

    missing, external_vc_runtime = scan_portable(args.root)
    if missing:
        _print_findings("[FAIL] 未找到 DLL：", missing)
    if external_vc_runtime:
        _print_findings("[FAIL] VC++ Runtime 尚未随包携带：", external_vc_runtime)
    if missing or external_vc_runtime:
        return 1
    print("[OK] PE 依赖闭合，未发现缺失 DLL 或外部 VC++ Runtime 依赖。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
