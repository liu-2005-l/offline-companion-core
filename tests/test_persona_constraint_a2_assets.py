"""摘要：P3-A2 冻结资产解析与五预设入库测试。"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from offline_companion.core.persona_constraint import assets as asset_module
from offline_companion.core.persona_constraint.assets import (
    PERSONA_CONSTRAINT_MANIFEST_SHA256,
    PersonaConstraintConfigError,
    load_persona_constraint_assets,
)
from offline_companion.runtime.storage_index.engine import connect
from offline_companion.shell.ui_host.desktop.session_binding import (
    PERSONA_SNAPSHOT_SOURCE_A1,
    SessionBindingError,
    build_persona_snapshot,
    validate_persona_snapshot,
)
from offline_companion.storage.persona_repo import (
    delete_persona,
    get_persona,
    list_personas,
    sync_builtin_personas,
    update_persona,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _payloads() -> tuple[dict[str, object], ...]:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    result: list[dict[str, object]] = []
    for preset in assets.builtin_presets:
        payload = preset.storage_payload()
        payload["constraint_manifest_sha256"] = assets.manifest_sha256
        payload["constraint_manifest_version"] = str(assets.manifest["version"])
        result.append(payload)
    return tuple(result)


def test_complete_root_loads_manifest_sources_and_builtin_presets() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)

    assert assets.root == REPO_ROOT
    assert assets.manifest_sha256 == PERSONA_CONSTRAINT_MANIFEST_SHA256
    assert set(assets.source_payloads) == {
        "mappings",
        "coverage_contract",
        "dimension_corpus",
        "structural_corpus",
        "persona_compositions",
        "reply_copy",
        "downgrade",
        "l4_patterns",
    }
    assert [preset.persona_id for preset in assets.builtin_presets] == [
        "builtin_wenrou",
        "builtin_baizao",
        "builtin_kekao",
        "builtin_tianmei",
        "builtin_keai",
    ]


def test_builtin_numeric_values_reverse_to_frozen_levels() -> None:
    assets = load_persona_constraint_assets(root_override=REPO_ROOT)
    level_by_value = {17: "low", 50: "mid", 83: "high"}

    for preset in assets.builtin_presets:
        assert set(preset.ocean) <= set(level_by_value)
        assert tuple(level_by_value[value] for value in preset.ocean) == preset.levels


def test_incomplete_seeded_root_is_skipped_as_a_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seeded_root = tmp_path / "seeded"
    persona_dir = seeded_root / "configs" / "personas"
    persona_dir.mkdir(parents=True)
    (persona_dir / "default.yaml").write_text("id: stale\n", encoding="utf-8")
    monkeypatch.setattr(asset_module, "data_root", lambda: seeded_root)
    monkeypatch.setattr(asset_module, "bundled_configs_dir", lambda: None)
    monkeypatch.setattr(asset_module, "dev_repo_root", lambda: REPO_ROOT)

    assets = load_persona_constraint_assets()

    assert assets.root == REPO_ROOT


def test_stale_seeded_root_with_residual_field_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seeded_root = tmp_path / "seeded"
    shutil.copytree(REPO_ROOT / "configs", seeded_root / "configs")
    manifest_path = seeded_root / "configs" / "persona_constraint_corpus.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "\nlegacy_residual: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(asset_module, "data_root", lambda: seeded_root)
    monkeypatch.setattr(asset_module, "bundled_configs_dir", lambda: None)
    monkeypatch.setattr(asset_module, "dev_repo_root", lambda: REPO_ROOT)

    assets = load_persona_constraint_assets()

    assert assets.root == REPO_ROOT


def test_whitelist_parser_ignores_unknown_fields_in_a_published_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutil.copytree(REPO_ROOT / "configs", tmp_path / "configs")
    manifest_path = tmp_path / "configs" / "persona_constraint_corpus.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "\nfuture_optional_metadata:\n  ignored: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        asset_module,
        "PERSONA_CONSTRAINT_MANIFEST_SHA256",
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )

    assets = load_persona_constraint_assets(root_override=tmp_path)

    assert [preset.name for preset in assets.builtin_presets] == ["温柔", "暴躁", "可靠", "甜美", "可爱"]


def test_explicit_root_rejects_tampered_source(tmp_path: Path) -> None:
    shutil.copytree(REPO_ROOT / "configs", tmp_path / "configs")
    target = tmp_path / "configs" / "persona_constraint_dimension_corpus.yaml"
    target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    with pytest.raises(PersonaConstraintConfigError, match="source_hash_mismatch:dimension_corpus"):
        load_persona_constraint_assets(root_override=tmp_path)


def test_explicit_root_rejects_manifest_path_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.copytree(REPO_ROOT / "configs", tmp_path / "configs")
    manifest_path = tmp_path / "configs" / "persona_constraint_corpus.yaml"
    text = manifest_path.read_text(encoding="utf-8").replace(
        "configs/persona_constraint_mappings.yaml",
        "../persona_constraint_mappings.yaml",
        1,
    )
    manifest_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        asset_module,
        "PERSONA_CONSTRAINT_MANIFEST_SHA256",
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )

    with pytest.raises(PersonaConstraintConfigError, match="source_path_outside_root"):
        load_persona_constraint_assets(root_override=tmp_path)


def test_builtin_presets_are_idempotently_synced_and_read_only(tmp_path: Path) -> None:
    conn = connect(tmp_path / "companion.db")
    try:
        sync_builtin_personas(conn, _payloads())
        first_updated_at = conn.execute(
            "SELECT updated_at FROM personas WHERE id = ?;",
            ("builtin_wenrou",),
        ).fetchone()["updated_at"]
        sync_builtin_personas(conn, _payloads())

        items = list_personas(conn)
        builtin_ids = {item["id"] for item in items if str(item["id"]).startswith("builtin_")}
        assert builtin_ids == {
            "builtin_wenrou",
            "builtin_baizao",
            "builtin_kekao",
            "builtin_tianmei",
            "builtin_keai",
        }
        assert len(items) == 8
        assert conn.execute(
            "SELECT updated_at FROM personas WHERE id = ?;",
            ("builtin_wenrou",),
        ).fetchone()["updated_at"] == first_updated_at
        row = conn.execute(
            "SELECT ocean_json, traits_json, raw_json FROM personas WHERE id = ?;",
            ("builtin_wenrou",),
        ).fetchone()
        assert json.loads(row["ocean_json"]) == [50, 50, 17, 83, 83]
        assert json.loads(row["traits_json"]) == []
        raw = json.loads(row["raw_json"])
        assert raw["derived_traits"] == ["温柔"]
        assert raw["derived_levels"] == {"O": "mid", "C": "mid", "E": "low", "A": "high", "N": "high"}
        assert raw["constraint_manifest_sha256"] == PERSONA_CONSTRAINT_MANIFEST_SHA256

        persona = get_persona(conn, "builtin_wenrou")
        assert persona is not None
        snapshot = build_persona_snapshot(persona, source=PERSONA_SNAPSHOT_SOURCE_A1, created_at=1.0)
        assert snapshot.payload["manifest_hash"] == PERSONA_CONSTRAINT_MANIFEST_SHA256
        assert snapshot.payload["constraint_manifest"]["sha256"] == PERSONA_CONSTRAINT_MANIFEST_SHA256

        with pytest.raises(ValueError, match="builtin_persona_read_only"):
            update_persona(conn, "builtin_wenrou", {"name": "被改写"})
        with pytest.raises(ValueError, match="builtin_persona_read_only"):
            delete_persona(conn, "builtin_wenrou")

        stale_persona = replace(
            persona,
            raw={**persona.raw, "constraint_manifest_sha256": "0" * 64},
        )
        with pytest.raises(SessionBindingError, match="persona_constraint_manifest_mismatch"):
            build_persona_snapshot(stale_persona, source=PERSONA_SNAPSHOT_SOURCE_A1, created_at=2.0)
    finally:
        conn.close()


def test_historical_snapshot_uses_its_recorded_manifest_hash(tmp_path: Path) -> None:
    conn = connect(tmp_path / "historical.db")
    try:
        sync_builtin_personas(conn, _payloads())
        persona = get_persona(conn, "builtin_wenrou")
        assert persona is not None
        proof = build_persona_snapshot(persona, source=PERSONA_SNAPSHOT_SOURCE_A1, created_at=1.0)
        payload = dict(proof.payload)
        payload["manifest_hash"] = "0" * 64
        payload["constraint_manifest"] = {
            **payload["constraint_manifest"],
            "sha256": "0" * 64,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO sessions(
                id, title, persona_id, created_at, updated_at,
                persona_snapshot_json, persona_snapshot_schema, persona_snapshot_sha256,
                persona_snapshot_source
            ) VALUES(?,?,?,?,?,?,?,?,?);
            """,
            (
                "historical",
                "历史会话",
                persona.persona_id,
                1.0,
                1.0,
                canonical,
                proof.schema,
                digest,
                proof.source,
            ),
        )

        row = conn.execute("SELECT * FROM sessions WHERE id = ?;", ("historical",)).fetchone()
        restored = validate_persona_snapshot(row)

        assert restored.payload["manifest_hash"] == "0" * 64
    finally:
        conn.close()


def test_builtin_sync_rolls_back_the_whole_batch_on_id_conflict(tmp_path: Path) -> None:
    conn = connect(tmp_path / "conflict.db")
    try:
        list_personas(conn)
        conn.execute(
            """
            INSERT INTO personas(
                id, name, avatar, desc, ocean_json, traits_json, anchor, system_prompt,
                raw_json, active, created_at, updated_at
            )
            SELECT ?, ?, avatar, desc, ocean_json, traits_json, anchor, system_prompt,
                   raw_json, 0, created_at, updated_at
            FROM personas
            WHERE id = ?;
            """,
            ("builtin_baizao", "占位冲突", "xiao_nuo"),
        )

        with pytest.raises(ValueError, match="builtin_persona_id_conflict"):
            sync_builtin_personas(conn, _payloads())

        assert conn.execute(
            "SELECT 1 FROM personas WHERE id = ?;",
            ("builtin_wenrou",),
        ).fetchone() is None
    finally:
        conn.close()
