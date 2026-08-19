"""首次引导状态 API 与前端行为测试。"""

from pathlib import Path

from tests.test_desktop_http import _runtime

from offline_companion.shell.ui_host.desktop.http_host import create_desktop_app

STATIC_DIR = Path(__file__).resolve().parents[1] / "src/offline_companion/shell/ui_host/desktop/static"


def test_onboarding_state_defaults_to_incomplete(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    payload = create_desktop_app(runtime).test_client().get("/api/onboarding/state").get_json()

    assert payload["completed"] is False
    assert payload["step"] == 0
    assert payload["skipped_model"] is False


def test_onboarding_skip_persists_completed_state(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    client = create_desktop_app(runtime).test_client()

    response = client.post("/api/onboarding/skip", json={})

    assert response.status_code == 200
    state = client.get("/api/onboarding/state").get_json()
    assert state["completed"] is True
    assert state["step"] == 3
    assert state["skipped_model"] is True


def test_onboarding_complete_persists_completed_state(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    client = create_desktop_app(runtime).test_client()

    response = client.post("/api/onboarding/complete", json={})

    assert response.status_code == 200
    assert client.get("/api/onboarding/state").get_json()["completed"] is True


def test_onboarding_ui_contains_three_steps_and_model_fallback_actions() -> None:
    source = (STATIC_DIR / "shell_api.js").read_text(encoding="utf-8")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert "loadOnboardingState" in source
    assert "downloadOnboardingModel" in source
    assert "skipOnboardingModel" in source
    assert "async function skipOnboardingModel()" in source
    assert "await skipOnboarding();" in source
    assert "saveOnboardingPreferences" in source
    assert "校验中" in source
    assert "id=\"onboardingOverlay\"" in html
    assert 'id="toast"' in html and "z-index:1200" in html


def test_onboarding_step_is_restored_after_restart(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    (tmp_path / "settings.json").write_text(
        '{"onboarding": {"completed": false, "step": 1, "skipped_model": false}}',
        encoding="utf-8",
    )

    state = create_desktop_app(runtime).test_client().get("/api/onboarding/state").get_json()

    assert state["completed"] is False
    assert state["step"] == 1


def test_legacy_active_model_without_onboarding_skips_first_run(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.model_label = "legacy-model.gguf"
    (tmp_path / "settings.json").write_text(
        '{"active_model_id": "legacy-model"}',
        encoding="utf-8",
    )

    state = create_desktop_app(runtime).test_client().get("/api/onboarding/state").get_json()

    assert state["completed"] is True
