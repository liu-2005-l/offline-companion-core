"""摘要：P3-A2 T26 persona 写门面与合法迁移豁免测试。"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from offline_companion.runtime.storage_index.engine import connect
from offline_companion.storage.persona_repo import (
    activate_persona,
    init_personas,
    set_active_persona_in_transaction,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PERSONA_WRITE_PATTERN = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+(?:REPLACE|IGNORE))?\s+INTO|UPDATE|DELETE\s+FROM)\s+personas\b",
    flags=re.IGNORECASE,
)
EXPECTED_WRITE_FUNCTIONS = {
    "src/offline_companion/storage/persona_repo.py": {
        "sync_builtin_personas",
        "set_active_persona_in_transaction",
        "create_persona",
        "update_persona",
        "delete_persona",
        "_insert_seed",
    },
    "src/offline_companion/storage/persona_traits_migration.py": {
        "complete_persona_level_migration",
    },
}


def _persona_write_functions(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        segment = ast.get_source_segment(source, node) or ""
        if PERSONA_WRITE_PATTERN.search(segment):
            result.add(node.name)
    return result


def test_t26_persona_sql_writes_are_limited_to_repo_facade_and_migration_exemption() -> None:
    actual: dict[str, set[str]] = {}
    for root_name in ("src", "scripts"):
        for path in (REPO_ROOT / root_name).rglob("*.py"):
            functions = _persona_write_functions(path)
            if functions:
                actual[path.relative_to(REPO_ROOT).as_posix()] = functions

    assert actual == EXPECTED_WRITE_FUNCTIONS
    session_binding = (
        REPO_ROOT
        / "src"
        / "offline_companion"
        / "shell"
        / "ui_host"
        / "desktop"
        / "session_binding.py"
    ).read_text(encoding="utf-8")
    assert PERSONA_WRITE_PATTERN.search(session_binding) is None
    assert "set_active_persona_in_transaction(" in session_binding


def test_t26_active_setter_obeys_caller_transaction_boundary(tmp_path: Path) -> None:
    conn = connect(tmp_path / "persona-write-paths.db")
    try:
        init_personas(conn)
        original_id = conn.execute("SELECT id FROM personas WHERE active = 1;").fetchone()[0]
        target_id = conn.execute(
            "SELECT id FROM personas WHERE id <> ? ORDER BY id LIMIT 1;",
            (original_id,),
        ).fetchone()[0]

        conn.execute("BEGIN IMMEDIATE;")
        assert set_active_persona_in_transaction(conn, target_id, updated_at=123.0) is True
        assert conn.execute("SELECT id FROM personas WHERE active = 1;").fetchone()[0] == target_id
        conn.execute("ROLLBACK;")
        assert conn.execute("SELECT id FROM personas WHERE active = 1;").fetchone()[0] == original_id

        activated = activate_persona(conn, target_id)
        assert activated is not None
        assert activated.persona_id == target_id
        assert conn.execute("SELECT id FROM personas WHERE active = 1;").fetchone()[0] == target_id
    finally:
        conn.close()
