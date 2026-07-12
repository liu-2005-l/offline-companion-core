"""导出导入跨平台兼容最小测试。"""

from __future__ import annotations

from pathlib import Path

from offline_companion.core.memory_lifecycle.manager import prepare_export_bundle
from offline_companion.runtime.storage_index.engine import connect, new_session
from offline_companion.runtime.storage_index.export_import import read_bundle_archive, write_bundle_archive


def test_bundle_archive_roundtrip_cross_platform_path(tmp_path: Path) -> None:
    """导出包在普通文件路径下应可完整读写。"""
    db = tmp_path / "db.sqlite3"
    conn = connect(db)
    new_session(conn, "s1", "default", title="t")
    payload = prepare_export_bundle(conn, persona_snapshot={"id": "default", "name": "x"})
    archive = tmp_path / "bundle.zip"
    write_bundle_archive(payload, archive)
    loaded = read_bundle_archive(archive)
    assert loaded.manifest["format"] == payload.manifest["format"]
