"""摘要：锁定手动任务卡片的折叠与终态正文前端契约。"""

from pathlib import Path

STATIC_DIR = Path("src/offline_companion/shell/ui_host/desktop/static")


def _function_source(source: str, name: str, next_name: str) -> str:
    """摘要：截取两个顶层函数声明之间的源码。

    参数：
        source: JavaScript 源码。
        name: 目标函数名。
        next_name: 后续函数名。

    返回值：
        目标函数对应的源码片段。
    """

    start = source.index(f"async function {name}(")
    end = source.index(f"async function {next_name}(", start)
    return source[start:end]


def test_manual_plan_card_auto_collapses_once_without_overriding_user_choice() -> None:
    """摘要：自动折叠只发生一次，用户操作后不再被状态更新覆盖。"""

    source = (STATIC_DIR / "shell.js").read_text(encoding="utf-8")

    assert "var _planCardStates = {};" in source
    assert "userTouched: false" in source
    assert "autoCollapsed: false" in source
    assert "!state.userTouched && !state.autoCollapsed" in source
    assert "state.autoCollapsed = true;" in source
    assert "state.userTouched = true;" in source
    assert "requestAnimationFrame(function()" in source
    assert "_setPlanCardPhase(plan.id, 'executing');" in source
    assert "s.status === 'done' || s.status === 'failed' || s.status === 'skipped'" in source


def test_manual_plan_rest_chain_uses_terminal_response_as_reply_boundary() -> None:
    """摘要：手动执行链从终态响应渲染正文，不在前端伪造完成态。"""

    source = (STATIC_DIR / "shell_api.js").read_text(encoding="utf-8")
    execute_source = _function_source(source, "_executeNextStep", "_approveConsent")

    assert "const decompStartedAt = performance.now();" in source
    assert "plan._decompMs = performance.now() - decompStartedAt;" in source
    assert "body: JSON.stringify({ timeout: 20 })" in execute_source
    assert "_renderPlanFinalReply(planId, data.final_reply);" in execute_source
    assert "_renderPlanFinalReply(planId, error.data.final_reply);" in execute_source
    assert "plan.status = 'done';" not in execute_source
    assert "showToast('任务计划已完成')" not in execute_source
    assert "data.status === 'not_decomposable'" in source
    assert "fallbackToChat = true;" in source


def test_manual_plan_missing_reply_uses_terminal_step_fallback() -> None:
    """摘要：手动终态正文缺失时仍按计划快照生成确定性回复。"""

    source = (STATIC_DIR / "shell.js").read_text(encoding="utf-8")

    assert "resolvedReply = _buildPlanFallbackReply(_activePlans[planId]);" in source
    assert "if (!plan || !['done', 'failed', 'cancelled'].includes(plan.status)) return '';" in source
    assert "步骤成功。" in source
    assert "执行步骤：" in source
    assert "output = document.createElement('div');" in source
    assert "content.appendChild(output);" in source
    assert "if (chat) chat.scrollTop = chat.scrollHeight;" in source


def test_manual_plan_card_uses_animated_body_and_separate_reply_node() -> None:
    """摘要：卡片正文平滑折叠，最终回复位于卡片外的同一消息内。"""

    script = (STATIC_DIR / "shell.js").read_text(encoding="utf-8")
    stylesheet = (STATIC_DIR / "shell.css").read_text(encoding="utf-8")

    card_index = script.index('class="plan-card decomp-card"')
    reply_index = script.index('class="plan-final-reply msg-text"', card_index)
    message_end = script.index("</div>';", reply_index)
    assert card_index < reply_index < message_end
    assert ".plan-card-body" in stylesheet
    assert "max-height: 0; opacity: 0" in stylesheet
    assert "220ms ease-in-out" in stylesheet
    assert ".plan-card.collapsed .plan-card-body { display: none; }" not in stylesheet


def test_auto_plan_start_collapses_once_and_preserves_user_choice() -> None:
    """摘要：Auto 卡片在 plan_start 后折叠，用户选择具有更高优先级。"""

    source = (STATIC_DIR / "shell_api.js").read_text(encoding="utf-8")

    assert "message._autoPlanViewState = { collapsed: false, userTouched: false, autoCollapsed: false }" in source
    assert "if (!userTouched && state.userTouched) return;" in source
    assert "if (!userTouched && collapsed) state.autoCollapsed = true;" in source
    assert "_setAutoPlanCollapsed(message, !state.collapsed, true);" in source
    assert "requestAnimationFrame(function()" in source
    assert "_setAutoPlanCollapsed(message, true, false);" in source


def test_auto_plan_reply_is_outside_collapsible_card_and_uses_unified_reply() -> None:
    """摘要：Auto 正文位于折叠卡片外，并优先展示统一终态回复。"""

    source = (STATIC_DIR / "shell_api.js").read_text(encoding="utf-8")
    card_body = source.index('class="auto-plan-body"')
    consent = source.index('class="auto-plan-consent"', card_body)
    reply = source.index('class="auto-plan-reply msg-text"', consent)

    assert card_body < consent < reply
    assert "querySelectorAll('.auto-step.done, .auto-step.failed, .auto-step.skipped')" in source
    assert "_setAutoPlanSummary(_autoPlanState.cardEl, '执行中 · ' + complete + '/' + total);" in source
    assert "event.reply || ('计划执行失败：'" in source
    assert "event.reply || '计划已取消'" in source
    assert "event.type === 'chat_fallback' && !bubble" in source
    assert "card.parentElement.querySelector('.auto-plan-reply')" in source
    assert "card.querySelector('.auto-plan-reply')" not in source
    assert "if (chat) chat.scrollTop = chat.scrollHeight;" in source


def test_auto_plan_card_uses_animated_body_without_hiding_consent() -> None:
    """摘要：Auto 步骤区平滑折叠，Consent 区保持在折叠体之外。"""

    stylesheet = (STATIC_DIR / "shell.css").read_text(encoding="utf-8")

    assert ".auto-plan-body { max-height: 520px" in stylesheet
    assert ".auto-plan-card.collapsed .auto-plan-body { max-height: 0; opacity: 0" in stylesheet
    assert ".auto-plan-collapse svg" in stylesheet
    assert "220ms ease-in-out" in stylesheet
    assert ".auto-plan-card.collapsed .auto-plan-body { display: none; }" not in stylesheet


def test_desktop_static_assets_use_cache_busting_version() -> None:
    """摘要：桌面静态资源引用携带版本号，避免前端继续使用旧缓存。"""

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'href="/shell.css?v=20260822-arithmetic-audit-v1"' in html
    assert 'src="/shell.js?v=20260822-arithmetic-audit-v1"' in html
    assert 'src="/shell_api.js?v=20260822-arithmetic-audit-v1"' in html


def test_sample_library_has_sidebar_entry_and_defaults_to_all_samples() -> None:
    """摘要：左栏直接进入范例库，且默认展示所有状态的范例。"""

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "shell.js").read_text(encoding="utf-8")

    sample_nav = html.index("onclick=\"switchView('samples')\"")
    settings_nav = html.index("onclick=\"switchView('settings')\"")
    assert sample_nav < settings_nav
    assert 'title="任务拆解范例"' in html
    assert '<button class="sample-tab active" data-state="all"' in html
    assert "selectDecompSampleState('all')\">全部</button>" in html
    assert "var _decompSampleState = 'all';" in script


def test_sample_library_uses_compact_refresh_and_confirmed_hard_delete() -> None:
    """摘要：刷新按钮保持紧凑，永久删除必须经过通用确认弹窗。"""

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "shell.js").read_text(encoding="utf-8")
    api_script = (STATIC_DIR / "shell_api.js").read_text(encoding="utf-8")
    stylesheet = (STATIC_DIR / "shell.css").read_text(encoding="utf-8")

    assert 'class="cloud-test-btn sample-refresh-btn"' in html
    assert ".sample-refresh-btn { flex: 0 0 auto; width: auto; padding: 6px 12px; }" in stylesheet
    assert "function confirmDeleteDecompSample(sampleId)" in script
    assert "showConfirm('永久删除任务拆解范例'" in script
    assert "此操作不可撤销。" in script
    assert "function apiDeleteDecompSample(sampleId)" in api_script
    assert "{ method: 'DELETE' }" in api_script


def test_stream_terminal_reply_replaces_unverified_streamed_text() -> None:
    """摘要：流结束后以前端终态正文替换尚未审计的流式文本。"""

    api_script = (STATIC_DIR / "shell_api.js").read_text(encoding="utf-8")

    assert "finalData.reply !== streamedText" in api_script
    assert "bubble.textContent = finalData.reply;" in api_script
