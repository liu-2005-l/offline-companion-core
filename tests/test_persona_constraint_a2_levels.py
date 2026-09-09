"""摘要：P3-A2 OCEAN 档位派生与缓存迁移测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from offline_companion.core.persona_constraint import (
    CUTPOINT_VERSION,
    DIMENSION_ORDER,
    PersonaLevelDerivationError,
    derive_levels,
    load_persona_constraint_assets,
    serialize_levels,
    to_level,
)
from offline_companion.runtime.storage_index.engine import connect
from offline_companion.shared.types import PrivacyMode
from offline_companion.shell.ui_host.bootstrap import bootstrap_ui_session_or_exit
from offline_companion.storage.persona_repo import (
    create_persona,
    init_personas,
    sync_builtin_personas,
    update_persona,
)
from offline_companion.storage.persona_traits_migration import (
    PERSONA_TRAITS_MIGRATION_ID,
    PersonaTraitsMigrationError,
    complete_persona_level_migration,
    prepare_persona_traits_migration,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(33, "low"), (34, "mid"), (66, "mid"), (67, "high")],
)
@pytest.mark.parametrize("dimension_index", range(5))
def test_cutpoint_boundaries_are_fixed_for_every_dimension(
    dimension_index: int,
    value: int,
    expected: str,
) -> None:
    ocean = [50, 50, 50, 50, 50]
    ocean[dimension_index] = value

    levels = derive_levels(ocean)

    assert levels[DIMENSION_ORDER[dimension_index]] == expected
    assert to_level(value) == expected


@pytest.mark.parametrize("value", [True, None, "33", float("nan"), float("inf"), -1, 101])
def test_to_level_rejects_non_numeric_non_finite_and_out_of_range(value: object) -> None:
    with pytest.raises(PersonaLevelDerivationError, match="persona_ocean_value_invalid"):
        to_level(value)


@pytest.mark.parametrize("ocean", [[], [50] * 4, [50] * 6, {"O": 50}, "50,50,50,50,50"])
def test_derive_levels_rejects_invalid_vector_shape(ocean: object) -> None:
    with pytest.raises(PersonaLevelDerivationError, match="persona_ocean_vector_invalid"):
        derive_levels(ocean)  # type: ignore[arg-type]


def test_level_derivation_and_serialization_are_byte_deterministic() -> None:
    ocean = [17, 33, 34, 66, 83]

    first = serialize_levels(derive_levels(ocean))
    second = serialize_levels(derive_levels(list(ocean)))

    assert first == second == '{"O":"low","C":"low","E":"mid","A":"mid","N":"high"}'


def test_level_serialization_rejects_unknown_or_reordered_dimensions() -> None:
    with pytest.raises(PersonaLevelDerivationError, match="persona_level_dimensions_invalid"):
        serialize_levels({"O": "mid", "C": "mid", "E": "mid", "N": "mid", "X": "mid"})


def test_five_presets_and_custom_persona_are_cached_and_migration_completes(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "companion.db")
    try:
        init_personas(conn)
        legacy_traits = {
            row["id"]: (row["traits_json"], row["raw_json"])
            for row in conn.execute("SELECT id, traits_json, raw_json FROM personas;").fetchall()
        }
        prepare_persona_traits_migration(conn, exports_dir=tmp_path / "exports")
        assets = load_persona_constraint_assets(root_override=REPO_ROOT)
        payloads = []
        for preset in assets.builtin_presets:
            payload = preset.storage_payload()
            payload["constraint_manifest_sha256"] = assets.manifest_sha256
            payload["constraint_manifest_version"] = str(assets.manifest["version"])
            payloads.append(payload)
        sync_builtin_personas(conn, payloads)
        custom = create_persona(
            conn,
                {
                    "name": "边界人格",
                    "ocean": [33, 34, 66, 67, 50],
                    "derived_traits_cache": ["手写保留"],
                    "anchor": "边界测试人格。",
                },
        )

        migrated_count = complete_persona_level_migration(conn)
        rows = conn.execute(
            """
            SELECT id, ocean_json, traits_json, raw_json,
                   derived_levels_json, derived_cutpoint_version
            FROM personas
            ORDER BY id;
            """
        ).fetchall()

        assert migrated_count == len(rows) == 9
        for row in rows:
            expected = serialize_levels(derive_levels(json.loads(row["ocean_json"])))
            assert row["derived_levels_json"] == expected
            assert row["derived_cutpoint_version"] == CUTPOINT_VERSION
        for preset in assets.builtin_presets:
            row = next(item for item in rows if item["id"] == preset.persona_id)
            assert json.loads(row["derived_levels_json"]) == dict(
                zip(DIMENSION_ORDER, preset.levels, strict=True)
            )
        custom_row = next(row for row in rows if row["id"] == custom["id"])
        assert json.loads(custom_row["derived_levels_json"]) == {
            "O": "low",
            "C": "mid",
            "E": "mid",
            "A": "high",
            "N": "mid",
        }
        assert custom_row["traits_json"] == '["手写保留"]'
        for persona_id, originals in legacy_traits.items():
            row = next(item for item in rows if item["id"] == persona_id)
            assert (row["traits_json"], row["raw_json"]) == originals
        state = conn.execute(
            "SELECT status FROM persona_migration_state WHERE migration_id = ?;",
            (PERSONA_TRAITS_MIGRATION_ID,),
        ).fetchone()
        assert state["status"] == "completed"

        before = [tuple(row) for row in rows]
        assert complete_persona_level_migration(conn) == len(rows)
        after = conn.execute(
            """
            SELECT id, ocean_json, traits_json, raw_json,
                   derived_levels_json, derived_cutpoint_version
            FROM personas
            ORDER BY id;
            """
        ).fetchall()
        assert [tuple(row) for row in after] == before
    finally:
        conn.close()


def test_custom_persona_ocean_update_refreshes_cache_and_cutpoint_version(tmp_path: Path) -> None:
    conn = connect(tmp_path / "companion.db")
    try:
        item = create_persona(conn, {"name": "自建人格", "ocean": [0, 33, 34, 67, 100]})
        update_persona(conn, item["id"], {"ocean": [67, 66, 34, 33, 50]})

        row = conn.execute(
            """
            SELECT derived_levels_json, derived_cutpoint_version
            FROM personas WHERE id = ?;
            """,
            (item["id"],),
        ).fetchone()
        assert json.loads(row["derived_levels_json"]) == {
            "O": "high",
            "C": "mid",
            "E": "mid",
            "A": "low",
            "N": "mid",
        }
        assert row["derived_cutpoint_version"] == CUTPOINT_VERSION
    finally:
        conn.close()


@pytest.mark.parametrize(
    "invalid_ocean_json",
    [
        "[50,50,50]",
        "[50,50,101,50,50]",
        '[50,50,"bad",50,50]',
        "[50,50,null,50,50]",
    ],
)
def test_invalid_legacy_ocean_rolls_back_all_cache_updates_and_keeps_exported(
    tmp_path: Path,
    invalid_ocean_json: str,
) -> None:
    conn = connect(tmp_path / "companion.db")
    try:
        init_personas(conn)
        prepare_persona_traits_migration(conn, exports_dir=tmp_path / "exports")
        conn.execute(
            "UPDATE personas SET ocean_json = ? WHERE id = 'zhi_xin';",
            (invalid_ocean_json,),
        )
        before = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT id, derived_levels_json, derived_cutpoint_version
                FROM personas ORDER BY id;
                """
            ).fetchall()
        ]

        with pytest.raises(PersonaTraitsMigrationError, match="persona_ocean_invalid:zhi_xin"):
            complete_persona_level_migration(conn)

        after = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT id, derived_levels_json, derived_cutpoint_version
                FROM personas ORDER BY id;
                """
            ).fetchall()
        ]
        status = conn.execute(
            "SELECT status FROM persona_migration_state WHERE migration_id = ?;",
            (PERSONA_TRAITS_MIGRATION_ID,),
        ).fetchone()["status"]
        assert after == before
        assert status == "exported"
    finally:
        conn.close()


def test_desktop_bootstrap_explicitly_rejects_invalid_legacy_ocean(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = connect(tmp_path / "companion.db")
    init_personas(conn)
    conn.execute(
        "UPDATE personas SET ocean_json = '[50,50,null,50,50]' WHERE id = 'zhi_xin';"
    )
    conn.close()
    args = SimpleNamespace(
        persona=REPO_ROOT / "configs" / "personas" / "default.yaml",
        session_id="invalid-legacy-startup",
        data_dir=str(tmp_path),
        memory=False,
        model=str(tmp_path / "missing.gguf"),
        n_ctx=512,
        n_gpu_layers=0,
        privacy=PrivacyMode.LOCAL_ONLY.value,
    )

    with pytest.raises(SystemExit) as exc_info:
        bootstrap_ui_session_or_exit(args, session_title="invalid legacy")

    assert exc_info.value.code == 1
    assert "人格档位迁移失败，已拒绝启动" in capsys.readouterr().err
    reopened = connect(tmp_path / "companion.db")
    try:
        state = reopened.execute(
            "SELECT status FROM persona_migration_state WHERE migration_id = ?;",
            (PERSONA_TRAITS_MIGRATION_ID,),
        ).fetchone()
        invalid = reopened.execute(
            "SELECT ocean_json FROM personas WHERE id = 'zhi_xin';"
        ).fetchone()
        assert state["status"] == "exported"
        assert invalid["ocean_json"] == "[50,50,null,50,50]"
    finally:
        reopened.close()


def test_completed_consistency_check_identifies_old_cutpoint_rows(tmp_path: Path) -> None:
    conn = connect(tmp_path / "companion.db")
    try:
        init_personas(conn)
        prepare_persona_traits_migration(conn, exports_dir=tmp_path / "exports")
        complete_persona_level_migration(conn)
        conn.execute(
            "UPDATE personas SET derived_cutpoint_version = 'legacy' WHERE id = 'a_ce';"
        )

        with pytest.raises(
            PersonaTraitsMigrationError,
            match="persona_level_cache_inconsistent:a_ce",
        ):
            complete_persona_level_migration(conn)
    finally:
        conn.close()
