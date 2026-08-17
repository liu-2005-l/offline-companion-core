from pathlib import Path

SHELL_API = Path("src/offline_companion/shell/ui_host/desktop/static/shell_api.js")


def test_task_progress_api_is_exposed_and_frontend_has_snapshot_loader() -> None:
    source = SHELL_API.read_text(encoding="utf-8")

    assert "/api/plan/" in source
    assert "/status" in source
    assert "loadTaskProgress" in source
