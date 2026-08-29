// 概要：后端第 1 批接线层，覆盖原型中的 mock 会话、聊天与记忆函数。
window.__shellApiActive = true;
var _currentSessionId = null;
var _windowDragState = null;
var _windowResizeState = null;
var _windowBoundsThrottle = null;
var _chatRequestActive = false;
var _chatAbortController = null;
var _chatStopRequested = false;
var _layoutRafPending = false;
// 与 Python 侧 offline_companion.core.plan_enums.PlanEventName 保持同步。
const PLAN_EVENTS = {
  ERROR: 'error',
  PLAN_START: 'plan_start',
  PLAN_COMPLETE: 'plan_complete',
  PLAN_FAILED: 'plan_failed',
  PLAN_CANCELLED: 'plan_cancelled',
  PLAN_BLOCKED: 'plan_blocked',
  STEP_START: 'step_start',
  STEP_COMPLETE: 'step_complete',
  STEP_FAILED: 'step_failed',
  STEP_ERROR: 'step_error',
  STEP_SKIPPED: 'step_skipped',
  CONSENT_REQUIRED: 'consent_required'
};

async function apiJson(url, options) {
  const resp = await fetch(url, options || {});
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const error = new Error(data.error || ('HTTP ' + resp.status));
    error.status = resp.status;
    error.data = data;
    throw error;
  }
  return data;
}

function applySettings(settings) {
  settings = settings || {};
  window._loadedSettings = settings;
  window.__settingsApplyTrace = { at: new Date().toISOString(), settings: settings, steps: [] };
  if (settings.theme) {
    document.documentElement.setAttribute('data-theme', settings.theme);
    const app = document.querySelector('.app');
    if (app) app.setAttribute('data-theme', settings.theme);
    document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.theme-btn').forEach(b => {
      if (b.textContent.includes(settings.theme === 'light' ? '浅' : settings.theme === 'dark' ? '深' : '粉')) b.classList.add('active');
    });
    document.querySelectorAll('select').forEach(select => {
      if (Array.from(select.options || []).some(option => option.value === settings.theme)) select.value = settings.theme;
    });
  }
  if (settings.privacy_mode) {
    window._privacyMode = privacyModeToUi(settings.privacy_mode);
    renderPrivacyMode(window._privacyMode);
  }
  if (typeof settings.improve_plan_enabled === 'boolean') {
    window._improvePlanEnabled = settings.improve_plan_enabled;
    const toggle = document.getElementById('improveToggle');
    if (toggle) toggle.classList.toggle('on', window._improvePlanEnabled);
  }
  if (typeof settings.auto_router_enabled === 'boolean') {
    window._autoRouterEnabled = settings.auto_router_enabled;
    const autoToggle = document.getElementById('autoToggle');
    if (autoToggle) autoToggle.classList.toggle('on', window._autoRouterEnabled);
  }
  if (typeof settings.close_to_tray === 'boolean') {
    const closeToTrayToggle = document.getElementById('closeToTrayToggle');
    if (closeToTrayToggle) closeToTrayToggle.classList.toggle('on', settings.close_to_tray);
  }
  if (typeof settings.memory_enabled === 'boolean') {
    const memoryToggle = document.getElementById('memoryToggle');
    if (memoryToggle) memoryToggle.classList.toggle('on', settings.memory_enabled);
    const memoryStatusLabel = document.getElementById('memoryStatusLabel');
    if (memoryStatusLabel) memoryStatusLabel.textContent = settings.memory_enabled ? '记忆 · 开' : '记忆 · 关';
  }
  if (typeof settings.idle_think_enabled === 'boolean') {
    const idleToggle = document.getElementById('idleThinkToggle');
    if (idleToggle) idleToggle.classList.toggle('on', settings.idle_think_enabled);
  }
  if (settings.idle_threshold_seconds != null) {
    const idleThreshold = document.getElementById('idleThresholdMinutes');
    if (idleThreshold) idleThreshold.value = Math.max(1, Math.round(Number(settings.idle_threshold_seconds || 300) / 60));
  }
  if (typeof settings.focus_mode_enabled === 'boolean') {
    const focusToggle = document.getElementById('focusModeToggle');
    if (focusToggle) focusToggle.classList.toggle('on', settings.focus_mode_enabled);
  }
  if (settings.active_persona_id) {
    window._activePersonaId = settings.active_persona_id;
    const personaChips = Array.from(document.querySelectorAll('.persona-chip'));
    const matchedPersona = personaChips.some(chip => chip.dataset.personaId === settings.active_persona_id);
    if (matchedPersona) {
      personaChips.forEach(chip => {
        chip.classList.toggle('active', chip.dataset.personaId === settings.active_persona_id);
      });
    }
    window.__settingsApplyTrace.steps.push({ name: 'active_persona_id', ok: matchedPersona, chips: personaChips.length, id: settings.active_persona_id });
  }
  if (settings.last_view) {
    try {
      if (typeof switchView === 'function') {
        switchView(settings.last_view, { persist: false });
        window.__settingsApplyTrace.steps.push({ name: 'last_view', ok: true, via: 'switchView' });
      } else {
        document.querySelectorAll('.view').forEach(section => section.classList.remove('active'));
        document.querySelectorAll('.nav-btn').forEach(button => button.classList.remove('active'));
        const view = document.querySelector('[data-view="' + settings.last_view + '"]');
        if (view) view.classList.add('active');
        const navBtn = document.querySelector('.nav-btn[onclick*="' + settings.last_view + '"]');
        if (navBtn) navBtn.classList.add('active');
        const controls = document.getElementById('windowControls');
        if (controls) controls.classList.toggle('hidden', settings.last_view !== 'chat');
        window.__settingsApplyTrace.steps.push({ name: 'last_view', ok: true, via: 'direct' });
      }
    } catch (error) {
      window.__settingsApplyTrace.steps.push({ name: 'last_view', ok: false, error: error && error.message ? error.message : String(error) });
      console.warn('[settings] last_view restore failed', error);
    }
  }
  if (settings.shell_custom) {
    const custom = settings.shell_custom || {};
    window._shellCustom = custom;
    if (custom.accent && window.PluginCSS) {
      PluginCSS.inject('shell-accent', [
        '[data-theme="light"] { --accent:' + custom.accent.color + '; --accent-hover:' + custom.accent.hover + '; --accent-soft:' + custom.accent.soft + '; --accent-glow:' + custom.accent.color + '26; }',
        '[data-theme="dark"] { --accent:' + custom.accent.color + '; --accent-hover:' + custom.accent.hover + '; --accent-soft:' + custom.accent.soft + '; --accent-glow:' + custom.accent.color + '33; }',
        '[data-theme="pink"] { --accent:' + custom.accent.color + '; --accent-hover:' + custom.accent.hover + '; --accent-soft:' + custom.accent.soft + '; --accent-glow:' + custom.accent.color + '2e; }'
      ].join('\n'));
    } else if (window.PluginCSS) {
      PluginCSS.remove('shell-accent');
    }
    if (custom.radius && window.PluginCSS) {
      PluginCSS.inject('shell-radius', ':root { --radius-sm:' + Math.max(4, custom.radius - 4) + 'px; --radius:' + custom.radius + 'px; --radius-lg:' + (custom.radius + 6) + 'px; --radius-bubble:' + (custom.radius + 6) + 'px; }');
    }
    const sidebarWidth = custom.sidebarWidth || custom.sidebar_width;
    if (sidebarWidth && window.PluginCSS) {
      PluginCSS.inject('shell-sidebar-width', '.app { grid-template-columns:' + sidebarWidth + 'px 1fr !important; }');
    }
    window.__settingsApplyTrace.steps.push({ name: 'shell_custom', ok: true, hasPluginCSS: !!window.PluginCSS, accent: !!custom.accent, radius: !!custom.radius, sidebarWidth: !!sidebarWidth });
  }
  postSettingsApplyTrace();
}

function applyAllSettings(settings) {
  settings = settings || {};
  var appearance = settings.appearance || {};
  var model = settings.model || {};
  var privacy = settings.privacy || {};
  var behavior = settings.behavior || {};
  var session = settings.session || {};
  var windowSettings = settings.window || {};
  applySettings(Object.assign({}, settings, {
    theme: appearance.theme,
    privacy_mode: privacy.privacy_mode,
    auto_router_enabled: model.auto_router_enabled,
    active_persona_id: model.active_persona_id,
    improve_plan_enabled: behavior.improve_plan_enabled,
    idle_think_enabled: behavior.idle_think_enabled,
    last_view: session.last_view,
    active_session_id: session.active_session_id,
    window_bounds: windowSettings.bounds,
    shell_custom: {
      accent: appearance.accent,
      radius: appearance.corner_radius,
      sidebarWidth: appearance.sidebar_width
    }
  }));
}

function postSettingsApplyTrace() {
  try {
    const trace = window.__settingsApplyTrace || {};
    fetch('/api/settings/apply-trace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(trace)
    }).catch(function(){});
  } catch (_error) {}
}

function collectSettingsDomSnapshot(label) {
  try {
    const rootStyle = getComputedStyle(document.documentElement);
    const app = document.querySelector('.app');
    const appStyle = app ? getComputedStyle(app) : null;
    const activeView = document.querySelector('.view.active');
    const activeNav = document.querySelector('.nav-btn.active');
    const activePersona = document.querySelector('.persona-chip.active');
    return {
      at: new Date().toISOString(),
      label: label || 'snapshot',
      loaded_settings: window._loadedSettings || null,
      html_theme: document.documentElement.getAttribute('data-theme'),
      app_theme: app ? app.getAttribute('data-theme') : null,
      css: {
        accent: rootStyle.getPropertyValue('--accent').trim(),
        accent_hover: rootStyle.getPropertyValue('--accent-hover').trim(),
        accent_soft: rootStyle.getPropertyValue('--accent-soft').trim(),
        radius: rootStyle.getPropertyValue('--radius').trim(),
        radius_lg: rootStyle.getPropertyValue('--radius-lg').trim(),
        sidebar_width: appStyle ? appStyle.gridTemplateColumns : null
      },
      active_view: activeView ? activeView.getAttribute('data-view') : null,
      active_nav: activeNav ? {
        title: activeNav.getAttribute('title') || '',
        onclick: activeNav.getAttribute('onclick') || '',
        classes: activeNav.className || ''
      } : null,
      active_persona_id: activePersona ? activePersona.dataset.personaId : null,
      persona_ids: Array.from(document.querySelectorAll('.persona-chip')).map(function(chip) { return chip.dataset.personaId || ''; }),
      plugin_css_ids: Array.from(document.querySelectorAll('style[data-plugin-css]')).map(function(style) { return style.getAttribute('data-plugin-css') || ''; })
    };
  } catch (error) {
    return {
      at: new Date().toISOString(),
      label: label || 'snapshot',
      error: error && error.message ? error.message : String(error)
    };
  }
}

function postSettingsDomSnapshot(label) {
  try {
    fetch('/api/settings/dom-snapshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(collectSettingsDomSnapshot(label))
    }).catch(function(){});
  } catch (_error) {}
}

async function loadSettings() {
  return loadAllSettings();
}

async function loadAllSettings() {
  try {
    const data = await apiJson('/api/settings');
    const settings = (data && data.data) || {};
    window.__SETTINGS = settings;
    applyAllSettings(settings);
    return settings;
  } catch (error) {
    showToast('Failed to load settings: ' + error.message);
    return {};
  }
}

async function patchSettings(module, patch) {
  const data = await apiJson('/api/settings/' + encodeURIComponent(module), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch || {})
  });
  if (data && data.ok) {
    window.__SETTINGS = window.__SETTINGS || {};
    window.__SETTINGS[module] = data.data;
    applyAllSettings(window.__SETTINGS);
  }
  return data && data.data;
}

function renderHealthStatus(data) {
  const overall = document.getElementById('healthOverall');
  const components = document.getElementById('healthComponents');
  if (!overall || !components) return;
  const labels = { healthy: '正常', degraded: '降级', unhealthy: '异常', unknown: '未知' };
  overall.textContent = '整体：' + (labels[data.overall] || data.overall || '未知');
  components.textContent = Object.keys(data.components || {}).map(function(name) {
    const item = data.components[name] || {};
    return name + '：' + (labels[item.status] || item.status || '未知');
  }).join(' · ') || '暂无检查项';
}

async function loadHealthStatus(force) {
  try {
    const data = await apiJson(force ? '/api/health/run' : '/api/health');
    renderHealthStatus(data);
    return data;
  } catch (error) {
    renderHealthStatus({ overall: 'unknown', components: {} });
    showToast('系统诊断失败：' + error.message);
    return null;
  }
}

async function exportDiagnosticsReport() {
  try {
    const data = await apiJson('/api/diagnostics/report');
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'offline-companion-diagnostics.json';
    link.click();
    URL.revokeObjectURL(link.href);
    showToast('诊断报告已导出');
  } catch (error) {
    showToast('诊断报告导出失败：' + error.message);
  }
}

async function startUiAnnotation() {
  try {
    const result = await apiJson('/api/ui_annotation/screenshot', { method: 'POST' });
    if (result && result.data) {
      window._annotationScreenshot = result.data;
      showToast('截图已准备，可以开始标注');
    }
  } catch (error) {
    showToast('无法开始标注：' + error.message);
  }
}

async function saveSetting(key, value) {
  const mapping = {
    theme: ['appearance', 'theme'],
    privacy_mode: ['privacy', 'privacy_mode'],
    improve_plan_enabled: ['behavior', 'improve_plan_enabled'],
    auto_router_enabled: ['model', 'auto_router_enabled'],
    active_persona_id: ['model', 'active_persona_id'],
    active_model_id: ['model', 'local_model_id'],
    active_session_id: ['session', 'active_session_id'],
    last_view: ['session', 'last_view'],
    window_bounds: ['window', 'bounds'],
    idle_think_enabled: ['behavior', 'idle_think_enabled']
  };
  const target = mapping[key];
  if (target) return patchSettings(target[0], { [target[1]]: value });
  const data = await apiJson('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ [key]: value }) });
  applyAllSettings((data && data.data) || {});
  return data.data || {};
}

window.applySettings = applySettings;
window.applyAllSettings = applyAllSettings;
window.loadSettings = loadSettings;
window.loadAllSettings = loadAllSettings;
window.patchSettings = patchSettings;
window.saveSetting = saveSetting;
window.loadHealthStatus = loadHealthStatus;
window.renderHealthStatus = renderHealthStatus;
window.startUiAnnotation = startUiAnnotation;
window.exportDiagnosticsReport = exportDiagnosticsReport;
window.collectSettingsDomSnapshot = collectSettingsDomSnapshot;
window.postSettingsDomSnapshot = postSettingsDomSnapshot;

let idlePollTimer = null;

function formatIdleTime(timestamp) {
  if (!timestamp) return '';
  const numeric = Number(timestamp);
  if (!Number.isNaN(numeric)) return new Date(numeric * 1000).toLocaleTimeString();
  return String(timestamp);
}

function renderIdleStatus(data) {
  const panel = document.getElementById('idleStatusPanel');
  if (!panel) return;
  if (!data || !data.idle_enabled) {
    panel.hidden = true;
    panel.innerHTML = '';
    return;
  }
  const status = data.current_status || null;
  const progress = data.last_progress || null;
  const result = data.last_idle_result || null;
  if (!status && !progress && !result) {
    panel.hidden = true;
    panel.innerHTML = '';
    return;
  }
  const statusText = !status ? '观察中' :
    status.status === 'paused' ? '⏸ 暂停：' + (status.reason || '用户输入') :
    status.status === 'completed' ? '✅ 已完成' :
    '▶ ' + status.status;
  const plan = result && result.idle_plan ? result.idle_plan : null;
  const goal = plan ? '<div class="idle-goal">' + apiEscapeHtml(plan.goal_title || '') + '</div>' : '';
  const step = progress ? '<div class="idle-progress"><span>' + apiEscapeHtml(progress.title || progress.step_id || '') + '</span><small>' + apiEscapeHtml(String(progress.result || '')) + '</small></div>' : '';
  panel.hidden = false;
  panel.innerHTML = '<div class="idle-header">空闲思考</div>' +
    '<div class="idle-state">' + apiEscapeHtml(statusText) + '</div>' +
    goal + step +
    '<div class="idle-time">' + apiEscapeHtml(formatIdleTime((status && status.timestamp) || (progress && progress.timestamp))) + '</div>';
}

async function loadIdleStatus() {
  try {
    const data = await apiJson('/api/idle/status');
    renderIdleStatus(data);
    return data;
  } catch (_error) {
    return null;
  }
}

function startIdlePolling() {
  if (idlePollTimer) return;
  loadIdleStatus();
  idlePollTimer = setInterval(loadIdleStatus, 30000);
}

async function toggleIdleThink(el) {
  const enabled = !el.classList.contains('on');
  const input = document.getElementById('idleThresholdMinutes');
  const minutes = Math.min(60, Math.max(1, parseInt(input && input.value ? input.value : '5', 10) || 5));
  try {
    const data = await apiJson('/api/idle/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled, threshold_seconds: minutes * 60 })
    });
    if (data.settings) applySettings(data.settings);
    await loadIdleStatus();
  } catch (error) {
    showToast('空闲检测设置失败：' + error.message);
  }
}

async function updateIdleThreshold(input) {
  const minutes = Math.min(60, Math.max(1, parseInt(input.value || '5', 10) || 5));
  input.value = String(minutes);
  const idleToggle = document.getElementById('idleThinkToggle');
  const enabled = !idleToggle || idleToggle.classList.contains('on');
  try {
    const data = await apiJson('/api/idle/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled, threshold_seconds: minutes * 60 })
    });
    if (data.settings) applySettings(data.settings);
  } catch (error) {
    showToast('空闲阈值保存失败：' + error.message);
  }
}

function toggleFocusMode(el) {
  const enabled = !el.classList.contains('on');
  el.classList.toggle('on', enabled);
  saveSetting('focus_mode_enabled', enabled).catch(function(error) {
    el.classList.toggle('on', !enabled);
    showToast('专注模式保存失败：' + error.message);
  });
}

window.loadIdleStatus = loadIdleStatus;
window.renderIdleStatus = renderIdleStatus;
window.toggleIdleThink = toggleIdleThink;
window.updateIdleThreshold = updateIdleThreshold;
window.toggleFocusMode = toggleFocusMode;

function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  const app = document.querySelector('.app');
  if (app) app.setAttribute('data-theme', t);
  document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.theme-btn').forEach(b => {
    if (b.textContent.includes(t === 'light' ? '浅' : t === 'dark' ? '深' : '粉')) b.classList.add('active');
  });
  saveSetting('theme', t).catch(function(error) {
    showToast('Failed to save theme: ' + error.message);
  });
}

window.setTheme = setTheme;

function toggleCloseToTray(el) {
  const enabled = !el.classList.contains('on');
  el.classList.toggle('on', enabled);
  saveSetting('close_to_tray', enabled).catch(function(error) {
    el.classList.toggle('on', !enabled);
    showToast('Failed to save close behavior: ' + error.message);
  });
}

window.toggleCloseToTray = toggleCloseToTray;

async function toggleMemory(el) {
  const enabled = !el.classList.contains('on');
  el.classList.toggle('on', enabled);
  try {
    const data = await apiJson('/api/memory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled })
    });
    if (data && data.settings) applySettings(data.settings);
  } catch (error) {
    el.classList.toggle('on', !enabled);
    showToast('记忆设置保存失败：' + error.message);
  }
}

window.toggleMemory = toggleMemory;

function desktopWindowApi() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

async function windowMinimize() {
  const api = desktopWindowApi();
  if (!api || !api.minimize) {
    showToast('窗口控制仅在桌面应用中可用');
    return;
  }
  await api.minimize();
}

async function windowToggleMaximize() {
  const api = desktopWindowApi();
  const app = document.getElementById('appRoot');
  if (!api || !api.toggle_maximize) {
    showToast('窗口控制仅在桌面应用中可用');
    return;
  }
  const result = await api.toggle_maximize();
  if (app) app.classList.toggle('maximized', !!(result && result.maximized));
}

async function syncWindowMaximizedState() {
  const api = desktopWindowApi();
  const app = document.getElementById('appRoot');
  if (!app) return;
  if (!api || !api.is_maximized) {
    app.classList.toggle('maximized', false);
    return;
  }
  try {
    const result = await api.is_maximized();
    app.classList.toggle('maximized', !!(result && result.maximized));
  } catch (_error) {
    app.classList.toggle('maximized', false);
  }
}

function registerWindowChrome() {
  const titleBar = document.querySelector('.title-bar');
  if (titleBar) titleBar.addEventListener('mousedown', beginWindowDrag, true);
  document.querySelectorAll('.resize-handle').forEach(function(handle) {
    handle.addEventListener('pointerdown', beginWindowResize, true);
  });
}

function resolveLayout(width, height) {
  if (width < 900 || height < 600) return 'compact';
  if (width >= 1600 && height >= 900) return 'wide';
  return 'standard';
}

function applyAdaptiveLayout() {
  if (_layoutRafPending) return;
  _layoutRafPending = true;
  window.requestAnimationFrame(function() {
    _layoutRafPending = false;
    var layout = resolveLayout(Math.round(window.innerWidth), Math.round(window.innerHeight));
    if (document.documentElement.dataset.layout !== layout) {
      document.documentElement.dataset.layout = layout;
    }
  });
}

window.addEventListener('resize', applyAdaptiveLayout);
applyAdaptiveLayout();

async function windowClose() {
  const api = desktopWindowApi();
  if (!api || !api.close) {
    showToast('窗口退出仅在桌面应用中可用');
    return;
  }
  await api.close();
}

function scheduleWindowBounds(bounds) {
  const api = desktopWindowApi();
  if (!api || !api.set_bounds || _windowBoundsThrottle) return;
  _windowBoundsThrottle = setTimeout(function() {
    _windowBoundsThrottle = null;
    api.set_bounds(Math.round(bounds.x), Math.round(bounds.y), Math.round(bounds.width), Math.round(bounds.height));
  }, 16);
}

async function persistCurrentWindowBounds(fallbackBounds) {
  const api = desktopWindowApi();
  let bounds = fallbackBounds;
  try {
    if (api && api.get_bounds) bounds = await api.get_bounds();
  } catch (_error) {
    bounds = fallbackBounds;
  }
  if (!bounds) return;
  saveSetting('window_bounds', {
    x: Math.round(bounds.x || 0),
    y: Math.round(bounds.y || 0),
    width: Math.round(bounds.width || 960),
    height: Math.round(bounds.height || 640)
  }).catch(function(error) {
    showToast('Failed to save window bounds: ' + error.message);
  });
}

function clampWindowBounds(bounds) {
  bounds.width = Math.max(720, bounds.width);
  bounds.height = Math.max(480, bounds.height);
  return bounds;
}

async function beginWindowDrag(event) {
  const api = desktopWindowApi();
  if (!api || !api.get_bounds || event.button !== 0 || event.target.closest('.window-controls')) return;
  event.preventDefault();
  event.stopPropagation();
  const bounds = await api.get_bounds();
  _windowDragState = {
    startX: event.screenX,
    startY: event.screenY,
    bounds: bounds
  };
  document.addEventListener('mousemove', moveWindowDrag, true);
  document.addEventListener('mouseup', endWindowDrag, true);
}

function moveWindowDrag(event) {
  if (!_windowDragState) return;
  event.preventDefault();
  event.stopPropagation();
  const dx = event.screenX - _windowDragState.startX;
  const dy = event.screenY - _windowDragState.startY;
  scheduleWindowBounds({
    x: (_windowDragState.bounds.x || 0) + dx,
    y: (_windowDragState.bounds.y || 0) + dy,
    width: _windowDragState.bounds.width || 960,
    height: _windowDragState.bounds.height || 640
  });
}

function endWindowDrag(event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  const fallbackBounds = _windowDragState ? {
    x: (_windowDragState.bounds.x || 0) + (event ? event.screenX - _windowDragState.startX : 0),
    y: (_windowDragState.bounds.y || 0) + (event ? event.screenY - _windowDragState.startY : 0),
    width: _windowDragState.bounds.width || 960,
    height: _windowDragState.bounds.height || 640
  } : null;
  _windowDragState = null;
  document.removeEventListener('mousemove', moveWindowDrag, true);
  document.removeEventListener('mouseup', endWindowDrag, true);
  persistCurrentWindowBounds(fallbackBounds);
}

async function beginWindowResize(event) {
  const api = desktopWindowApi();
  if (!api || !api.get_bounds || event.button !== 0) return;
  const handle = event.currentTarget;
  if (!handle) return;
  event.preventDefault();
  event.stopPropagation();
  const direction = handle.dataset.dir || '';
  if (handle.setPointerCapture) handle.setPointerCapture(event.pointerId);
  _windowResizeState = {
    dir: direction,
    startX: event.screenX,
    startY: event.screenY,
    bounds: null,
    handle: handle,
    pointerId: event.pointerId
  };
  document.addEventListener('pointermove', moveWindowResize, true);
  document.addEventListener('pointerup', endWindowResize, true);
  try {
    const bounds = await api.get_bounds();
    if (_windowResizeState) _windowResizeState.bounds = bounds;
  } catch (_error) {
    endWindowResize(event);
  }
}

function moveWindowResize(event) {
  if (!_windowResizeState || !_windowResizeState.bounds) return;
  event.preventDefault();
  event.stopPropagation();
  const state = _windowResizeState;
  const dx = event.screenX - state.startX;
  const dy = event.screenY - state.startY;
  const next = {
    x: state.bounds.x || 0,
    y: state.bounds.y || 0,
    width: state.bounds.width || 960,
    height: state.bounds.height || 640
  };
  if (state.dir.includes('e')) next.width += dx;
  if (state.dir.includes('s')) next.height += dy;
  if (state.dir.includes('w')) {
    next.x += dx;
    next.width -= dx;
  }
  if (state.dir.includes('n')) {
    next.y += dy;
    next.height -= dy;
  }
  scheduleWindowBounds(clampWindowBounds(next));
}

function endWindowResize(event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  let fallbackBounds = null;
  if (_windowResizeState) {
    const state = _windowResizeState;
    if (state.handle && state.handle.releasePointerCapture && state.handle.hasPointerCapture &&
        state.handle.hasPointerCapture(state.pointerId)) {
      state.handle.releasePointerCapture(state.pointerId);
    }
    if (state.bounds) {
      const dx = event ? event.screenX - state.startX : 0;
      const dy = event ? event.screenY - state.startY : 0;
      fallbackBounds = {
        x: state.bounds.x || 0,
        y: state.bounds.y || 0,
        width: state.bounds.width || 960,
        height: state.bounds.height || 640
      };
      if (state.dir.includes('e')) fallbackBounds.width += dx;
      if (state.dir.includes('s')) fallbackBounds.height += dy;
      if (state.dir.includes('w')) {
        fallbackBounds.x += dx;
        fallbackBounds.width -= dx;
      }
      if (state.dir.includes('n')) {
        fallbackBounds.y += dy;
        fallbackBounds.height -= dy;
      }
      fallbackBounds = clampWindowBounds(fallbackBounds);
    }
  }
  _windowResizeState = null;
  document.removeEventListener('pointermove', moveWindowResize, true);
  document.removeEventListener('pointerup', endWindowResize, true);
  persistCurrentWindowBounds(fallbackBounds);
}

function apiEscapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : String(value);
  return div.innerHTML;
}

function apiTime(value) {
  if (value == null || value === '') return new Date().toTimeString().slice(0, 5);
  const numeric = typeof value === 'number' ? value : parseFloat(value);
  const date = !Number.isNaN(numeric) && Number.isFinite(numeric) ? new Date(numeric * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? String(value).slice(0, 5) : date.toTimeString().slice(0, 5);
}

function apiDateTime(value) {
  return _formatTimestamp(value, '');
}

function _formatTimestamp(raw, fallback) {
  if (raw == null || raw === '') return fallback == null ? '-' : fallback;
  const numeric = typeof raw === 'number' ? raw : parseFloat(raw);
  if (!Number.isNaN(numeric) && Number.isFinite(numeric)) {
    const date = new Date(numeric * 1000);
    if (!Number.isNaN(date.getTime())) return formatLocalDateTime(date);
  }
  const parsed = new Date(raw);
  if (!Number.isNaN(parsed.getTime())) return formatLocalDateTime(parsed);
  return String(raw);
}

function formatLocalDateTime(date) {
  const pad = function(n) { return n < 10 ? '0' + n : String(n); };
  return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) +
    ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes());
}

function apiJsArg(value) {
  return apiEscapeHtml(JSON.stringify(String(value == null ? '' : value)));
}

function apiEnsureTypingNode() {
  const chat = document.getElementById('chatMessages');
  if (!chat || document.getElementById('typingMsg')) return;
  chat.insertAdjacentHTML('beforeend',
    '<div class="msg msg-bot" id="typingMsg" style="display:none;">' +
      '<div class="msg-avatar">诺</div>' +
      '<div class="msg-bubble"><div class="typing"><span></span><span></span><span></span></div></div>' +
    '</div>');
}

function apiNextMsgIdx() {
  const chat = document.getElementById('chatMessages');
  return chat ? chat.querySelectorAll('[data-msg-idx]').length : 0;
}

function apiRenderMessage(role, content, msgIdx, createdAt, quoteHtml, messageId) {
  if (role === 'system') {
    return '<div class="msg msg-system"><div class="msg-bubble">' + apiEscapeHtml(content) + '</div></div>';
  }
  const isUser = role === 'user';
  const idAttr = messageId == null ? '' : ' data-message-id="' + apiEscapeHtml(messageId) + '"';
  return '<div class="msg ' + (isUser ? 'msg-user' : 'msg-bot') + '" data-msg-idx="' + msgIdx + '"' + idAttr + '>' +
    '<div class="msg-avatar">' + (isUser ? '我' : '诺') + '</div>' +
    '<div class="msg-bubble">' + (quoteHtml || '') + '<p>' + apiEscapeHtml(content) + '</p><span class="meta-time">' + apiTime(createdAt) + '</span></div>' +
  '</div>';
}

function apiAppendMessage(role, content, msgIdx, createdAt, quoteHtml, messageId) {
  apiEnsureTypingNode();
  const typing = document.getElementById('typingMsg');
  if (typing) typing.insertAdjacentHTML('beforebegin', apiRenderMessage(role, content, msgIdx, createdAt, quoteHtml, messageId));
}

function apiAppendConsentDeclined(message) {
  const chat = document.getElementById('chatMessages');
  apiAppendMessage('assistant', message, apiNextMsgIdx(), Date.now() / 1000);
  if (chat) chat.scrollTop = chat.scrollHeight;
}

function setChatRequestActive(active) {
  _chatRequestActive = !!active;
  const button = document.getElementById('sendBtn');
  if (!button) return;
  button.classList.toggle('active', !_chatRequestActive && !!(document.getElementById('chatInput') || {}).value.trim());
  button.classList.toggle('stop', _chatRequestActive);
  button.onclick = _chatRequestActive ? stopMessageGeneration : sendMessage;
  button.title = _chatRequestActive ? '停止思考' : '发送';
  button.setAttribute('aria-label', _chatRequestActive ? '停止思考' : '发送');
  button.innerHTML = _chatRequestActive
    ? '<svg viewBox="0 0 24 24" width="16" height="16"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>'
    : '<svg viewBox="0 0 24 24" width="16" height="16"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>';
}

function stopMessageGeneration() {
  if (!_chatRequestActive) return;
  _chatStopRequested = true;
  if (_chatAbortController) _chatAbortController.abort();
  _chatAbortController = null;
  setChatRequestActive(false);
  hideTyping();
  showToast('已停止思考');
}

function apiCreateStreamingMessage(msgIdx) {
  apiAppendMessage('assistant', '', msgIdx, Date.now() / 1000);
  const chat = document.getElementById('chatMessages');
  return chat ? chat.querySelector('[data-msg-idx="' + msgIdx + '"] .msg-bubble p') : null;
}

function apiSetRenderedMessageId(msgIdx, messageId) {
  if (messageId == null) return;
  const chat = document.getElementById('chatMessages');
  const msg = chat ? chat.querySelector('[data-msg-idx="' + msgIdx + '"]') : null;
  if (msg) msg.dataset.messageId = String(messageId);
}

async function apiReadSseStream(resp, onEvent, options) {
  options = options || {};
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let latestSeq = Number.isFinite(Number(options.initialSeq)) ? Number(options.initialSeq) : -1;
  let done = false;
  const consumeEvent = async function(event) {
    const seq = Number(event && event.seq);
    if (Number.isFinite(seq)) {
      if (seq <= latestSeq) return;
      if (seq > latestSeq + 1 && typeof options.onGap === 'function') {
        const repaired = await options.onGap(latestSeq, seq - 1);
        if (repaired && Number.isFinite(Number(repaired.latestSeq))) {
          latestSeq = Math.max(latestSeq, Number(repaired.latestSeq));
        }
        if (latestSeq < seq - 1) throw new Error('SSE 事件缺口修复失败');
      }
      latestSeq = seq;
    }
    if (event.done) done = true;
    await onEvent(event);
  };
  const consumePart = async function(part) {
    for (const line of part.split('\n')) {
      if (!line.startsWith('data:')) continue;
      const raw = line.slice(5).trim();
      if (raw) await consumeEvent(JSON.parse(raw));
    }
  };
  while (true) {
    const result = await reader.read();
    if (result.done) break;
    buffer += decoder.decode(result.value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const part of parts) await consumePart(part);
  }
  const rest = buffer.trim();
  if (rest.startsWith('data:')) await consumePart(rest);
  return { done: done, latestSeq: latestSeq };
}

const SSE_MAX_RECONNECT = 3;

async function apiRepairSseGap(sessionId, fromSeq, onEvent, untilSeq) {
  let latestSeq = Number(fromSeq) || 0;
  const upperBound = Number.isFinite(Number(untilSeq)) ? Number(untilSeq) : null;
  for (let attempt = 1; attempt <= SSE_MAX_RECONNECT; attempt++) {
    const data = await apiJson(
      '/api/sessions/' + encodeURIComponent(sessionId) + '/events?from_seq=' + latestSeq
    );
    let done = false;
    let progressed = false;
    (data.events || []).forEach(function(event) {
      const eventSeq = Number(event.seq);
      if (!Number.isFinite(eventSeq) || eventSeq <= latestSeq) return;
      if (upperBound !== null && eventSeq > upperBound) return;
      latestSeq = eventSeq;
      progressed = true;
      if (event.done) done = true;
      onEvent(event);
    });
    if (upperBound !== null) {
      return { done: done, latestSeq: Math.max(latestSeq, upperBound) };
    }
    if (done) return { done: true, latestSeq: latestSeq };
    if (!progressed && (data.events || []).length > 0) break;
    if (attempt < SSE_MAX_RECONNECT) {
      await new Promise(function(resolve) { setTimeout(resolve, Math.min(attempt * 1000, 5000)); });
    }
  }
  return { done: false, latestSeq: latestSeq };
}

async function apiLatestSseSeq(sessionId) {
  const data = await apiJson(
    '/api/sessions/' + encodeURIComponent(sessionId) + '/events?from_seq=' + Number.MAX_SAFE_INTEGER
  );
  return Number(data.latest_seq) || 0;
}

async function sendMessage() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;
  if (_chatRequestActive) return;
  _chatStopRequested = false;
  _chatAbortController = new AbortController();
  setChatRequestActive(true);
  fetch('/api/idle/touch', { method: 'POST' }).catch(() => {});
  const chat = document.getElementById('chatMessages');
  const nextIdx = apiNextMsgIdx();
  let quoteHtml = '';
  const quote = window._pendingQuote || null;
  if (window._pendingQuote) {
    quoteHtml = '<div class="msg-quote"><div class="msg-quote-sender">' + apiEscapeHtml(window._pendingQuote.sender) + '</div>' + apiEscapeHtml(window._pendingQuote.text) + '</div>';
    clearReplyPreview();
  }
  apiAppendMessage('user', text, nextIdx, Date.now() / 1000, quoteHtml);
  input.value = '';
  autoResize(input);
  updateSendBtn();
  chat.scrollTop = chat.scrollHeight;

  let fallbackNotice = '';
  if (window._planMode && !window._autoRouterEnabled) {
    showTyping();
    const decompStartedAt = performance.now();
    let fallbackToChat = false;
    try {
      const data = await apiJson('/api/plan/decompose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: text })
      });
      hideTyping();
      if (data.status === 'not_decomposable') {
        fallbackToChat = true;
        fallbackNotice = String(data.fallback_notice || '').trim();
      } else {
      const plan = data.plan;
      plan._decompMs = performance.now() - decompStartedAt;
      window._activePlans[plan.id] = plan;
      _renderPlanCard(plan, new Date().toTimeString().slice(0, 5));
      chat.scrollTop = chat.scrollHeight;
      }
    } catch (error) {
      hideTyping();
      showToast('任务拆解失败：' + error.message);
      setChatRequestActive(false);
      _chatAbortController = null;
      return;
    }
    if (!fallbackToChat) {
      setChatRequestActive(false);
      _chatAbortController = null;
      return;
    }
  }

  showTyping();
  try {
    let lastStreamSeq = await apiLatestSseSeq(_currentSessionId);
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: _currentSessionId, quote: quote, stream: true }),
      signal: _chatAbortController.signal
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.error || ('HTTP ' + resp.status));
    }
    if (!resp.body) {
      const data = await resp.json();
      hideTyping();
      const replyText = data.reply || data.error || '';
      const displayedReply = fallbackNotice ? fallbackNotice + '\n\n' + replyText : replyText;
      apiAppendMessage(data.blocked ? 'system' : 'assistant', displayedReply, nextIdx + 1, Date.now() / 1000);
      apiSetRenderedMessageId(nextIdx + 1, data.message_id);
      chat.scrollTop = chat.scrollHeight;
      if (data.memory_saved && data.memory_saved.length) loadMemories();
      return;
    }
    hideTyping();
    let bubble = window._autoRouterEnabled ? null : apiCreateStreamingMessage(nextIdx + 1);
    let finalData = null;
    let streamedText = '';
    const handleStreamEvent = function(event) {
      if (event.seq) lastStreamSeq = Math.max(lastStreamSeq, Number(event.seq) || 0);
      if (_handleAutoPlanEvent(event, nextIdx + 1)) {
        if (event.done) finalData = event;
        return;
      }
      if (event.type === 'chat_fallback' && !bubble) bubble = apiCreateStreamingMessage(nextIdx + 1);
      if (event.error) throw new Error(event.error);
      if (event.recall != null && event.recall > 0) showToast('召回 ' + event.recall + ' 条记忆');
      if (event.token) {
        streamedText += event.token;
        if (bubble) bubble.textContent = streamedText;
        chat.scrollTop = chat.scrollHeight;
      }
      if (event.done) finalData = event;
    };
    const repairGap = function(fromSeq, untilSeq) {
      return apiRepairSseGap(_currentSessionId, fromSeq, handleStreamEvent, untilSeq);
    };
    let streamState;
    try {
      streamState = await apiReadSseStream(resp, handleStreamEvent, {
        initialSeq: lastStreamSeq,
        onGap: repairGap
      });
      lastStreamSeq = Math.max(lastStreamSeq, streamState.latestSeq || 0);
    } catch (streamError) {
      if (_chatStopRequested) return;
      const repaired = await apiRepairSseGap(_currentSessionId, lastStreamSeq, handleStreamEvent);
      if (!repaired.done) throw streamError;
      streamState = repaired;
    }
    if (!streamState.done) {
      const repaired = await apiRepairSseGap(_currentSessionId, lastStreamSeq, handleStreamEvent);
      if (!repaired.done) throw new Error('流式连接中断，已保留未完成回复');
    }
    if (finalData && finalData.type === PLAN_EVENTS.PLAN_COMPLETE) {
      _finalizeAutoPlan(finalData);
    } else if (finalData && finalData.type === PLAN_EVENTS.PLAN_FAILED) {
      _failAutoPlan(finalData);
    } else if (finalData && finalData.type === PLAN_EVENTS.PLAN_CANCELLED) {
      _cancelAutoPlan(finalData);
    } else if (finalData && finalData.blocked && bubble) {
      const msg = bubble.closest('.msg');
      if (msg) {
        msg.classList.remove('msg-bot');
        msg.classList.add('msg-system');
      }
    }
    if (bubble && fallbackNotice) {
      bubble.textContent = fallbackNotice + '\n\n' + ((finalData && finalData.reply) || streamedText);
    } else if (finalData && finalData.reply && bubble && finalData.reply !== streamedText) {
      bubble.textContent = finalData.reply;
    }
    if (finalData) apiSetRenderedMessageId(nextIdx + 1, finalData.message_id);
    chat.scrollTop = chat.scrollHeight;
    if (finalData && finalData.memory_saved && finalData.memory_saved.length) loadMemories();
  } catch (error) {
    if (_chatStopRequested) return;
    hideTyping();
    showToast('消息发送失败：' + error.message);
  } finally {
    setChatRequestActive(false);
    _chatAbortController = null;
  }
}

function renderChatHistory(messages) {
  const chat = document.getElementById('chatMessages');
  if (!chat) return;
  let html = '<div class="msg msg-system"><div class="msg-bubble">会话已加载 · 本地记忆可用</div></div>';
  (messages || []).forEach(function(msg) {
    const suffix = msg.status === 'partial' ? '（回复因连接中断未完成）' :
      (msg.status === 'error' ? '（回复生成异常，内容未完成）' : '');
    const content = suffix ? (msg.content + '\n' + suffix) : msg.content;
    html += apiRenderMessage(msg.role === 'assistant' ? 'assistant' : msg.role, content, msg.msg_idx, msg.created_at, '', msg.id);
  });
  chat.innerHTML = html;
  apiEnsureTypingNode();
  chat.scrollTop = chat.scrollHeight;
}

async function loadCurrentSessionMessages(sessionId) {
  if (!sessionId) return;
  const data = await apiJson('/api/sessions/' + encodeURIComponent(sessionId) + '/messages');
  renderChatHistory(data.items || []);
}

function renderSessionList(items) {
  const list = document.getElementById('sessionList');
  if (!list) return;
  list.innerHTML = '';
  if (!items || !items.length) {
    list.innerHTML = apiEmptyState(EMPTY_ICONS.memory, '暂无会话', '新建会话后会显示在这里');
    applyMemoryFilter();
    return;
  }
  (items || []).forEach(function(item) {
    const title = item.title || item.session_id || '当前会话';
    list.insertAdjacentHTML('beforeend',
      '<div class="session-item' + (item.current ? ' active' : '') + '" data-session-id="' + apiEscapeHtml(item.session_id) + '" onclick="selectSession(this, \'' + apiEscapeHtml(title).replace(/'/g, '&#39;') + '\')">' +
        '<div class="session-item-main">' +
          '<div class="session-item-title">' + apiEscapeHtml(title) + '</div>' +
          '<div class="session-item-meta">' + item.message_count + ' 条消息 · ' + apiDateTime(item.updated_at) + '</div>' +
        '</div>' +
        '<div class="model-item-actions"><button class="icon-btn del" onclick="event.stopPropagation(); deleteSession(this)">×</button></div>' +
      '</div>');
  });
}

async function loadSessions() {
  try {
    const data = await apiJson('/api/sessions');
    renderSessionList(data.items || []);
    const current = (data.items || []).find(item => item.current) || (data.items || [])[0];
    if (current) {
      _currentSessionId = current.session_id;
      const info = document.getElementById('sessionInfo');
      if (info) info.textContent = '\u4f1a\u8bdd \u00b7 ' + (current.title || current.session_id);
      await loadCurrentSessionMessages(_currentSessionId);
      if (trajectoryDebugEnabled()) await loadTrajectory();
    }
  } catch (error) {
    showToast('会话加载失败：' + error.message);
  }
}

function trajectoryDebugEnabled() {
  return new URLSearchParams(window.location.search).get('debug') === 'trajectory';
}

function ensureTrajectoryPanel() {
  if (!trajectoryDebugEnabled()) return null;
  let panel = document.getElementById('trajectoryDebugPanel');
  if (panel) return panel;
  panel = document.createElement('aside');
  panel.id = 'trajectoryDebugPanel';
  panel.style.cssText = 'position:fixed;right:12px;bottom:12px;width:420px;max-height:45vh;overflow:auto;z-index:900;background:rgba(20,20,28,.96);color:#f3f4f6;border:1px solid #6366f1;border-radius:10px;padding:12px;font:12px/1.5 sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.3);';
  document.body.appendChild(panel);
  return panel;
}

function renderTrajectory(data) {
  const panel = ensureTrajectoryPanel();
  if (!panel) return;
  const summary = data.summary || {};
  const rows = (data.timeline || []).map(function(item) {
    const payload = item.payload || {};
    const label = payload.step_title || payload.content_preview || payload.model || payload.status || '';
    return '<tr><td>' + apiEscapeHtml(item.seq) + '</td><td>' + apiEscapeHtml(item.type) + '</td><td>' + apiEscapeHtml(label) + '</td></tr>';
  }).join('');
  panel.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
    '<strong>Trajectory（开发模式）</strong><button id="trajectoryRefresh" style="background:none;border:0;color:#a5b4fc;cursor:pointer;">刷新</button></div>' +
    '<div style="color:#c4b5fd;margin-bottom:8px;">事件 ' + apiEscapeHtml(summary.event_count || 0) +
    ' · 当前步骤 ' + apiEscapeHtml(summary.current_step || '—') + '</div>' +
    '<table style="width:100%;border-collapse:collapse;"><thead><tr><th>seq</th><th>类型</th><th>摘要</th></tr></thead><tbody>' +
    (rows || '<tr><td colspan="3">暂无事件</td></tr>') + '</tbody></table>';
  const refresh = document.getElementById('trajectoryRefresh');
  if (refresh) refresh.onclick = loadTrajectory;
}

async function loadTrajectory() {
  if (!trajectoryDebugEnabled() || !_currentSessionId) return;
  try {
    const data = await apiJson('/api/trajectory/' + encodeURIComponent(_currentSessionId));
    renderTrajectory(data);
  } catch (error) {
    showToast('Trajectory 加载失败：' + error.message);
  }
}

async function selectSession(el, title) {
  document.querySelectorAll('#sessionList .session-item').forEach(s => s.classList.remove('active'));
  el.classList.add('active');
  _currentSessionId = el.dataset.sessionId;
  document.getElementById('sessionInfo').textContent = '\u4f1a\u8bdd \u00b7 ' + title;
  try {
    await loadCurrentSessionMessages(_currentSessionId);
    showToast('已切换到 · ' + title);
  } catch (error) {
    showToast('会话切换失败：' + error.message);
  }
  setTimeout(toggleSessionPanel, 300);
}

async function newSession() {
  try {
    await apiJson('/api/clear', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    renderChatHistory([]);
    await loadSessions();
    showToast('当前会话已清空');
  } catch (error) {
    showToast('清空会话失败：' + error.message);
  }
  setTimeout(toggleSessionPanel, 300);
}

async function deleteSession(btn) {
  const item = btn.closest('.session-item');
  if (!item || !item.classList.contains('active')) {
    if (item) item.remove();
    showToast('暂未接入删除非当前会话');
    return;
  }
  showConfirm('清空当前会话', '确定要清空当前会话吗？这将调用 /api/clear 并删除所有消息，操作不可撤销。', async function() {
    try {
      await apiJson('/api/clear', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      renderChatHistory([]);
      await loadSessions();
      showToast('当前会话已清空');
    } catch (error) {
      showToast('清空失败：' + error.message);
    }
  });
}

function memoryTypeLabel(item) {
  const value = item.memory_type || item.event_type || (item.meta && item.meta.memory_type) || 'fact';
  return ({ fact: '\u77e5\u8bc6', preference: '\u504f\u597d', user_preference: '\u504f\u597d', relationship: '\u5173\u7cfb', emotional: '\u60c5\u7eea', decision: '\u51b3\u7b56', milestone: '\u91cc\u7a0b\u7891', episode: '\u4e8b\u4ef6', agent_profile: '\u753b\u50cf', user_profile: '\u753b\u50cf', knowledge: '\u77e5\u8bc6' })[value] || value;
}

function memoryPanelTitle(item, idx) {
  const body = item.body || item.content || '';
  const meta = item.metadata || item.meta || {};
  const title = item.title || meta.title || meta.summary_title;
  if (title) return String(title);
  if (body) return String(body).replace(/\s+/g, ' ').slice(0, 16);
  return '\u8bb0\u5fc6 ' + (idx + 1);
}

function memoryTags(item) {
  const tags = (item.metadata && item.metadata.tags) || (item.meta && item.meta.tags) || [];
  return Array.isArray(tags) ? tags : [];
}

function renderMemoryCards(items) {
  const list = document.getElementById('memoryCardList');
  if (!list) return;
  list.innerHTML = '';
  (items || []).forEach(function(item) {
    const tags = memoryTags(item);
    const type = memoryTypeLabel(item);
    const body = item.body || item.content || '';
    const itemId = item.event_id || item.id || '';
    const itemKind = item.event_id ? 'semantic_event' : 'memory_chunk';
    const created = _formatTimestamp(item.created_at, '-');
    const modified = _formatTimestamp(item.modified_at || item.updated_at, created);
    list.insertAdjacentHTML('beforeend',
      '<div class="memory-card" onclick="openMemoryDetail(this)" data-kind="' + itemKind + '" data-id="' + apiEscapeHtml(String(itemId)) + '" data-type="' + apiEscapeHtml(type) + '" data-source="' + apiEscapeHtml(item.source || '') + '" data-created="' + created + '" data-modified="' + modified + '" data-status="' + (item.status || 'active') + '" data-tags=\'' + apiEscapeHtml(JSON.stringify(tags)) + '\'>' +
        '<div class="memory-card-header"><span class="memory-type">' + apiEscapeHtml(type) + '</span><span class="memory-date">' + apiEscapeHtml(modified || created) + '</span></div>' +
        '<div class="memory-content">' + apiEscapeHtml(body) + '</div>' +
        '<div class="memory-tags">' + tags.map(tag => '<span class="memory-tag">' + apiEscapeHtml(tag) + '</span>').join('') + '</div>' +
      '</div>');
  });
  applyMemoryFilter();
}

async function loadMemories() {
  try {
    const data = await apiJson('/api/memories?page=1&page_size=100');
    const semanticEvents = await loadSemanticEvents();
    const items = (semanticEvents || []).concat(data.items || []);
    renderMemoryCards(items);
    window._memoryPoints = items.slice(0, 8).map(function(item, idx) {
      return { msgIdx: idx, id: item.id, title: memoryPanelTitle(item, idx), badge: memoryTypeLabel(item), summary: item.body || item.content || '', original: item.body || item.content || '', turn: idx + 1, time: apiTime(item.modified_at || item.created_at) };
    });
    initMemoryPanel();
  } catch (error) {
    showToast('记忆加载失败：' + error.message);
  }
}

async function loadSemanticEvents(type) {
  try {
    var url = type ? '/api/memory/events?type=' + encodeURIComponent(type) : '/api/memory/events';
    var events = await apiJson(url);
    window._semanticEvents = events || [];
    return window._semanticEvents;
  } catch (error) {
    showToast('语义事件加载失败：' + error.message);
    return [];
  }
}

async function deleteSemanticEvent(eventId) {
  await apiJson('/api/memory/events/' + encodeURIComponent(eventId), { method: 'DELETE' });
  await loadSemanticEvents();
  showToast('语义事件已删除');
}

async function ctxSaveMemory() {
  document.getElementById('msgContextMenu').style.display = 'none';
  if (!window._ctxTargetMsg) return;
  const text = _getMsgText();
  if (!text) return;
  try {
    await apiJson('/api/memories', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: text, source: 'manual', tags: ['manual'] }) });
    await loadMemories();
    showToast('已存入记忆 · ' + (text.length > 20 ? text.slice(0, 20) + '...' : text));
  } catch (error) {
    showToast('存入记忆失败：' + error.message);
  }
}

async function toggleMemoryStatus() {
  if (!window._currentMemoryCard) return;
  if (window._currentMemoryCard.dataset.kind === 'semantic_event') {
    await deleteSemanticEvent(window._currentMemoryCard.dataset.id);
    window._currentMemoryCard.remove();
    window._currentMemoryCard = null;
    closeMemoryDetail();
    applyMemoryFilter();
    return;
  }
  const nextStatus = window._currentMemoryCard.dataset.status === 'active' ? 'inactive' : 'active';
  try {
    const data = await apiJson('/api/memories/' + encodeURIComponent(window._currentMemoryCard.dataset.id), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: nextStatus }) });
    window._currentMemoryCard.dataset.status = data.item.status;
    window._currentMemoryCard.style.opacity = data.item.status === 'active' ? '' : '0.5';
    document.getElementById('detailStatus').textContent = data.item.status === 'active' ? '启用' : '停用';
    updateMemStatusBtn(data.item.status);
    showToast(data.item.status === 'active' ? '记忆已激活' : '记忆已停用');
  } catch (error) {
    showToast('状态更新失败：' + error.message);
  }
}

async function saveMemoryEdit() {
  if (!window._currentMemoryCard) return;
  const content = document.getElementById('detailContent').value.trim();
  if (!content) return showToast('记忆内容不能为空');
  try {
    if (window._currentMemoryCard.dataset.kind === 'semantic_event') {
      await apiJson('/api/memory/events/' + encodeURIComponent(window._currentMemoryCard.dataset.id), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: content }) });
    } else {
      await apiJson('/api/memories/' + encodeURIComponent(window._currentMemoryCard.dataset.id), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: content }) });
    }
    window._memoryEditMode = false;
    closeMemoryDetail();
    await loadMemories();
    showToast('记忆已保存');
  } catch (error) {
    showToast('记忆保存失败：' + error.message);
  }
}

async function deleteMemory() {
  if (!window._currentMemoryCard) return;
  const id = window._currentMemoryCard.dataset.id || '';
  showConfirm('删除记忆', '确认删除记忆 #' + id + ' 此操作不可撤销。', async function() {
    try {
      if (window._currentMemoryCard.dataset.kind === 'semantic_event') {
        await apiJson('/api/memory/events/' + encodeURIComponent(id), { method: 'DELETE' });
      } else {
        await apiJson('/api/memories/' + encodeURIComponent(id) + '/delete', { method: 'POST' });
      }
      window._currentMemoryCard = null;
      closeMemoryDetail();
      await loadMemories();
      showToast('记忆已删除');
    } catch (error) {
      showToast('删除记忆失败：' + error.message);
    }
  });
}

let _onboardingState = null;
let _onboardingStep = 0;
let _onboardingDownloadTimer = null;
let _onboardingModelsLoaded = false;

async function loadOnboardingState() {
  try {
    const data = await apiJson('/api/onboarding/state');
    _onboardingState = data || {};
    _onboardingStep = Number(_onboardingState.step || 0);
    if (!_onboardingState.completed) openOnboarding();
  } catch (error) {
    console.warn('[onboarding] state load failed', error);
  }
}

function openOnboarding() {
  const overlay = document.getElementById('onboardingOverlay');
  if (!overlay) return;
  overlay.style.display = 'flex';
  renderOnboarding();
}

function closeOnboarding() {
  const overlay = document.getElementById('onboardingOverlay');
  if (overlay) overlay.style.display = 'none';
  if (_onboardingDownloadTimer) clearInterval(_onboardingDownloadTimer);
  _onboardingDownloadTimer = null;
}

function renderOnboarding() {
  const content = document.getElementById('onboardingContent');
  const actions = document.getElementById('onboardingActions');
  const progress = document.getElementById('onboardingProgress');
  if (!content || !actions || !progress) return;
  progress.textContent = _onboardingStep === 0 ? '● ○ ○' : _onboardingStep === 1 ? '○ ● ○' : '○ ○ ●';
  if (_onboardingStep === 0) {
    content.innerHTML = '<h2 class="onboarding-title">欢迎使用 Offline Companion</h2><p class="onboarding-desc">这是一个本地优先的 AI 私人助理。接下来 3 步完成首次设置，你可以随时在设置中修改。</p>';
    actions.innerHTML = '<button class="onboarding-secondary" onclick="skipOnboarding()">跳过引导</button><button class="onboarding-primary" onclick="startOnboarding()">开始设置</button>';
  } else if (_onboardingStep === 1) {
    const models = _onboardingState.models || [];
    const modelHtml = models.map(function(model, index) {
      return '<label class="onboarding-model"><input type="radio" name="onboardingModel" value="' + apiEscapeHtml(model.model_id) + '" ' + (model.recommended || index === 0 ? 'checked' : '') + '><span class="onboarding-model-name">' + apiEscapeHtml(model.display_name) + '</span><div class="onboarding-model-meta">约 ' + Math.round(Number(model.size_bytes || 0) / 1048576) + ' MB · 最低内存 ' + model.min_ram_mb + ' MB</div></label>';
    }).join('');
    content.innerHTML = '<h2 class="onboarding-title">选择本地模型</h2><p class="onboarding-desc">推荐模型会下载到本地，下载完成后即可开始对话。</p><div class="onboarding-models">' + modelHtml + '</div><div id="onboardingDownloadProgress"></div>';
    actions.innerHTML = '<button class="onboarding-secondary" onclick="skipOnboardingModel()">跳过引导</button><button class="onboarding-primary" onclick="downloadOnboardingModel()">下载模型</button>';
    if (!_onboardingModelsLoaded) loadOnboardingModels();
  } else if (_onboardingStep === 2) {
    content.innerHTML = '<h2 class="onboarding-title">设置你的偏好</h2><p class="onboarding-desc">这些偏好只保存在本地，用来让后续对话更自然。</p><input class="onboarding-field" id="onboardingName" placeholder="你想让我怎么称呼你？" maxlength="40"><label class="setting-row"><span><span class="setting-label">允许联网搜索</span><br><span class="setting-desc">默认关闭，之后可在设置中修改</span></span><input type="checkbox" id="onboardingWebSearch"></label>';
    actions.innerHTML = '<button class="onboarding-secondary" onclick="previousOnboardingStep()">上一步</button><button class="onboarding-primary" onclick="saveOnboardingPreferences()">下一步</button>';
  } else {
    content.innerHTML = '<h2 class="onboarding-title">设置完成！</h2><p class="onboarding-desc">你可以随时在设置里修改这些选项。现在开始和你的本地陪伴 Agent 对话吧。</p>';
    actions.innerHTML = '<button class="onboarding-primary" onclick="completeOnboarding()">开始使用</button>';
  }
}

async function loadOnboardingModels() {
  try {
    const data = await apiJson('/api/models/registry');
    _onboardingState.models = data.items || [];
    _onboardingModelsLoaded = true;
    if (_onboardingStep === 1) renderOnboarding();
  } catch (error) {
    showToast('模型列表加载失败：' + error.message);
  }
}

function startOnboarding() { _onboardingStep = 1; renderOnboarding(); }
function previousOnboardingStep() { _onboardingStep = Math.max(1, _onboardingStep - 1); renderOnboarding(); }

async function skipOnboardingModel() {
  await skipOnboarding();
}

async function downloadOnboardingModel() {
  const selected = document.querySelector('input[name="onboardingModel"]:checked');
  if (!selected) return showToast('请先选择一个模型');
  const modelId = selected.value;
  try {
    await apiJson('/api/models/download', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model_id: modelId }) });
    if (_onboardingDownloadTimer) clearInterval(_onboardingDownloadTimer);
    _onboardingDownloadTimer = setInterval(async function() {
      const data = await apiJson('/api/models/download/status');
      const item = (data.items || []).find(function(candidate) { return candidate.model_id === modelId; });
      const node = document.getElementById('onboardingDownloadProgress');
      if (!item || !node) return;
      const percent = item.total_bytes ? Math.min(100, item.downloaded_bytes / item.total_bytes * 100) : 0;
      node.innerHTML = '<div class="onboarding-progressbar"><div style="width:' + percent + '%"></div></div><div class="setting-desc">' + Math.round(percent) + '% · ' + item.state + '</div>';
      node.innerHTML = node.innerHTML.replace('verifying', '校验中').replace('downloading', '下载中');
      if (item.state === 'completed') {
        clearInterval(_onboardingDownloadTimer);
        _onboardingStep = 2;
        renderOnboarding();
      } else if (item.state === 'failed' || item.state === 'cancelled') {
        clearInterval(_onboardingDownloadTimer);
        showToast(item.state === 'cancelled' ? '下载已取消，可以重新下载' : '下载失败，可以稍后重试');
      }
    }, 500);
  } catch (error) {
    showToast('下载启动失败：' + error.message);
  }
}

async function saveOnboardingPreferences() {
  const name = (document.getElementById('onboardingName') || {}).value || '';
  const allowWebSearch = !!((document.getElementById('onboardingWebSearch') || {}).checked);
  try {
    if (name.trim()) await apiJson('/api/memories', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: '用户希望被称呼为：' + name.trim(), source: 'onboarding', tags: ['preference', 'onboarding'] }) });
    await apiJson('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ onboarding: { completed: false, step: 2, skipped_model: !!_onboardingState.skipped_model }, onboarding_allow_web_search: allowWebSearch }) });
    _onboardingStep = 3;
    renderOnboarding();
  } catch (error) {
    showToast('偏好保存失败：' + error.message);
  }
}

async function completeOnboarding() {
  try {
    await apiJson('/api/onboarding/complete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    closeOnboarding();
  } catch (error) {
    showToast('引导完成失败：' + error.message);
  }
}

async function skipOnboarding() {
  try {
    await apiJson('/api/onboarding/skip', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    closeOnboarding();
  } catch (error) {
    showToast('跳过引导失败：' + error.message);
  }
}

async function loadDecompSamples(state, append) {
  if (typeof state === 'string') _decompSampleState = state;
  var offset = append ? _decompSampleOffset : 0;
  var query = _decompSampleState ? '?state=' + encodeURIComponent(_decompSampleState) : '?';
  query += (query === '?' ? '' : '&') + 'limit=100&offset=' + offset;
  try {
    var data = await apiJson('/api/decomp-samples' + query);
    var incoming = data.items || [];
    var items = append ? _decompSamples.concat(incoming) : incoming;
    _decompSampleOffset = offset + incoming.length;
    _decompSampleHasMore = !!data.has_more;
    renderDecompSamples(items);
  } catch (error) {
    showToast('读取任务拆解范例失败：' + error.message);
  }
}

function loadMoreDecompSamples() {
  return loadDecompSamples(_decompSampleState, true);
}

async function focusDecompSample(sampleId) {
  try {
    var data = await apiJson('/api/decomp-samples/' + encodeURIComponent(sampleId));
    var sample = data.sample;
    var state = 'all';
    _decompSampleState = state;
    document.querySelectorAll('.sample-tab').forEach(function(button) {
      button.classList.toggle('active', button.dataset.state === state);
    });
    await loadDecompSamples(state);
  } catch (error) {
    showToast('定位任务拆解范例失败：' + error.message);
    await loadDecompSamples();
  }
}

async function loadDecompSampleSummary() {
  try {
    var data = await apiJson('/api/decomp-samples?state=stale&limit=500');
    var count = Number(data.total || 0);
    var dot = document.getElementById('sampleStaleDot');
    var summary = document.getElementById('sampleLibrarySummary');
    var banner = document.getElementById('sampleStaleSummary');
    if (dot) dot.hidden = count === 0;
    if (summary) summary.textContent = count ? count + ' 个范例需要复核' : '管理本地留档的任务拆解范例';
    if (banner) {
      banner.hidden = count === 0;
      banner.textContent = count ? count + ' 个范例因连续失败被标记为待复核，请确认、编辑或丢弃。' : '';
    }
  } catch (error) {
    console.warn('[samples] summary load failed', error);
  }
}

function _replaceDecompSample(updated) {
  var index = _decompSamples.findIndex(function(item) { return item.id === updated.id; });
  if (index >= 0) _decompSamples[index] = updated;
  else _decompSamples.unshift(updated);
  renderDecompSamples(_decompSamples);
}

async function apiTransitionDecompSample(sampleId, action) {
  var optimistic = action === 'verify' ? { state: 'verified', verify_kind: 'user', stale_reason: null } :
    action === 'reject' ? { state: 'rejected', verify_kind: null, stale_reason: null } :
    { state: 'candidate', verify_kind: null, stale_reason: null };
  var previous = applyOptimisticDecompSample(sampleId, optimistic);
  try {
    var data = await apiJson('/api/decomp-samples/' + encodeURIComponent(sampleId) + '/' + action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}'
    });
    _replaceDecompSample(data.sample);
    await loadDecompSampleSummary();
    showToast(action === 'verify' ? '已确认为用户范例' : action === 'reject' ? '已丢弃范例' : '已恢复为候选范例');
  } catch (error) {
    rollbackOptimisticDecompSample(previous);
    showToast(error.message === 'invalid_transition' ? '当前状态不允许此操作' : '更新范例失败：' + error.message);
  }
}

async function apiDeleteDecompSample(sampleId) {
  try {
    await apiJson('/api/decomp-samples/' + encodeURIComponent(sampleId), { method: 'DELETE' });
    if (_selectedDecompSampleId === String(sampleId)) _selectedDecompSampleId = null;
    await loadDecompSamples(_decompSampleState);
    await loadDecompSampleSummary();
    showToast('范例已永久删除');
  } catch (error) {
    showToast('删除范例失败：' + error.message);
  }
}

async function apiEditDecompSample(sampleId) {
  var taskInput = document.getElementById('sampleTaskDescription');
  var titles = Array.from(document.querySelectorAll('[data-sample-step-title]'));
  var descriptions = Array.from(document.querySelectorAll('[data-sample-step-description]'));
  var taskDescription = taskInput ? taskInput.value.trim() : '';
  var steps = titles.map(function(input, index) {
    return { title: input.value.trim(), description: descriptions[index] ? descriptions[index].value.trim() : '' };
  });
  if (!taskDescription || steps.some(function(step) { return !step.title || !step.description; })) {
    showToast('任务描述、步骤标题和步骤说明不能为空');
    return;
  }
  var previous = applyOptimisticDecompSample(sampleId, {
    task_description: taskDescription,
    steps: steps,
    state: 'verified',
    verify_kind: 'user',
    stale_reason: null
  });
  try {
    var data = await apiJson('/api/decomp-samples/' + encodeURIComponent(sampleId), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_description: taskDescription, steps: steps })
    });
    _replaceDecompSample(data.sample);
    await loadDecompSampleSummary();
    showToast('范例已保存并确认为用户范例');
  } catch (error) {
    rollbackOptimisticDecompSample(previous);
    showToast('保存范例失败：' + error.message);
  }
}

async function savePlanAsDecompSample(planId) {
  try {
    var data = await apiJson('/api/plans/' + encodeURIComponent(planId) + '/save-as-sample', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}'
    });
    var plan = window._activePlans[planId];
    if (plan) {
      plan.candidate_sample_id = data.sample.id;
      _updatePlanCard(plan);
    }
    showToast(data.created ? '计划已保存为用户范例' : '该计划已有范例');
    openDecompSampleLibrary(data.sample.id);
  } catch (error) {
    showToast('保存计划范例失败：' + error.message);
  }
}

document.addEventListener('DOMContentLoaded', async function() {
  apiEnsureTypingNode();
  syncWindowMaximizedState();
  registerWindowChrome();
  await loadSettings();
  loadSessions();
  loadMemories();
  loadPersonas();
  loadModels();
  loadExtensions();
  loadRuntimeStatus();
  loadHealthStatus(false);
  loadPendingCrashReport();
  loadAuthStatus();
  loadImprovePlan();
  loadOnboardingState();
  loadDecompSampleSummary();
  startIdlePolling();
  setTimeout(function() { postSettingsDomSnapshot('after-startup-loads'); }, 300);
  setTimeout(function() { postSettingsDomSnapshot('after-startup-settle'); }, 1200);
});

async function _executeNextStep(planId) {
  const plan = window._activePlans[planId];
  if (!plan || plan.status !== 'running') return;
  const step = (plan.steps || []).find(function(candidate) {
    if (candidate.status !== 'pending') return false;
    return (candidate.deps || []).every(function(dep) {
      return plan.steps[dep] && plan.steps[dep].status === 'done';
    });
  });
  if (!step) {
    if ((plan.steps || []).every(item => item.status === 'done')) {
      try {
        const data = await apiJson('/api/plan/' + encodeURIComponent(planId) + '/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ timeout: 20 })
        });
        window._activePlans[planId] = data.plan;
        _updatePlanCard(data.plan);
        _renderPlanFinalReply(planId, data.final_reply);
      } catch (error) {
        showToast('获取任务结果失败：' + error.message);
      }
    }
    return;
  }
  step.status = 'running';
  _updatePlanCard(plan);
  try {
    const data = await apiJson('/api/plan/' + encodeURIComponent(planId) + '/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step_id: step.id, timeout: 20 })
    });
    window._activePlans[planId] = data.plan;
    _updatePlanCard(data.plan);
    _renderPlanFinalReply(planId, data.final_reply);
    if (data.plan.status === 'running') _executeNextStep(planId);
  } catch (error) {
    if (error.message === 'requires_consent' || error.message === 'HTTP 409') {
      const data = error.data || {};
      if (data.plan) {
        window._activePlans[planId] = data.plan;
        _updatePlanCard(data.plan);
      } else {
        step.status = 'consent';
        plan.status = 'paused';
        _updatePlanCard(plan);
      }
      showToast('高危步骤需要授权');
      return;
    }
    if (error.message === 'timeout' || error.message === 'HTTP 408') {
      step.status = 'failed';
      step.error = '该步骤执行超时';
      plan.status = 'paused';
      _updatePlanCard(plan);
      showToast('步骤超时，可重试或跳过');
      return;
    }
    if (error.data && error.data.plan) {
      window._activePlans[planId] = error.data.plan;
      _updatePlanCard(error.data.plan);
      _renderPlanFinalReply(planId, error.data.final_reply);
      showToast('步骤执行失败：' + error.message);
      return;
    }
    step.status = 'failed';
    step.error = error.message;
    plan.status = 'failed';
    _updatePlanCard(plan);
    showToast('步骤执行失败：' + error.message);
  }
}

async function _approveConsent(planId, stepId) {
  const plan = window._activePlans[planId];
  if (!plan) return;
  const step = plan.steps[stepId];
  if (!step) return;
  const consentRequestId = step.consent_request_id;
  if (!consentRequestId) {
    showToast('缺少授权请求 ID，无法继续');
    return;
  }
  step.status = 'running';
  plan.status = 'running';
  _updatePlanCard(plan);
  try {
    await apiJson('/api/consent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: consentRequestId, allowed: true })
    });
    const data = await apiJson('/api/plan/' + encodeURIComponent(planId) + '/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step_id: stepId, timeout: 20, consent_request_id: consentRequestId })
    });
    window._activePlans[planId] = data.plan;
    _updatePlanCard(data.plan);
    _renderPlanFinalReply(planId, data.final_reply);
    showToast('已授权，继续执行');
    if (data.plan.status === 'running') _executeNextStep(planId);
  } catch (error) {
    step.status = 'failed';
    step.error = error.message;
    plan.status = 'failed';
    _updatePlanCard(plan);
    showToast('授权后执行失败：' + error.message);
  }
}

async function _rejectConsent(planId, stepId) {
  const plan = window._activePlans[planId];
  if (!plan) return;
  const step = plan.steps[stepId];
  if (!step) return;
  const consentRequestId = step.consent_request_id;
  if (!consentRequestId) {
    showToast('缺少授权请求 ID，无法记录拒绝');
    return;
  }
  try {
    const data = await apiJson('/api/consent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: consentRequestId, allowed: false })
    });
    if (data.plan) window._activePlans[planId] = data.plan;
    else {
      step.status = 'skipped';
      delete step.error;
      plan.status = 'paused';
    }
    _updatePlanCard(window._activePlans[planId] || plan);
    if (data.status === 'declined') apiAppendConsentDeclined(data.message);
  } catch (error) {
    showToast('拒绝授权记录失败：' + error.message);
  }
}

let _autoPlanState = null;

function _ensureAutoPlanViewState(message) {
  if (!message._autoPlanViewState) {
    message._autoPlanViewState = { collapsed: false, userTouched: false, autoCollapsed: false };
  }
  return message._autoPlanViewState;
}

function _applyAutoPlanViewState(message) {
  if (!message) return;
  const state = _ensureAutoPlanViewState(message);
  const card = message.querySelector('.auto-plan-card');
  if (!card) return;
  card.classList.toggle('collapsed', state.collapsed);
  const header = card.querySelector('.auto-plan-header');
  if (header) header.setAttribute('aria-expanded', state.collapsed ? 'false' : 'true');
}

function _setAutoPlanCollapsed(message, collapsed, userTouched) {
  if (!message) return;
  const state = _ensureAutoPlanViewState(message);
  if (userTouched) state.userTouched = true;
  if (!userTouched && state.userTouched) return;
  state.collapsed = collapsed;
  if (!userTouched && collapsed) state.autoCollapsed = true;
  _applyAutoPlanViewState(message);
}

function _toggleAutoPlanCollapse(planId) {
  const chat = document.getElementById('chatMessages');
  if (!chat) return;
  const message = Array.from(chat.querySelectorAll('.auto-plan-msg')).find(function(item) {
    return item.dataset.planId === String(planId);
  });
  if (!message) return;
  const state = _ensureAutoPlanViewState(message);
  _setAutoPlanCollapsed(message, !state.collapsed, true);
}

function _setAutoPlanSummary(message, label) {
  const summary = message && message.querySelector('.auto-plan-progress');
  if (summary) summary.textContent = label;
}

async function loadTaskProgress(planId) {
  const data = await apiJson('/api/plan/' + encodeURIComponent(planId) + '/status');
  return data;
}

function _renderAutoPlanCard(event, msgIdx) {
  const chat = document.getElementById('chatMessages');
  if (!chat) return;
  if (event.resume && _autoPlanState && _autoPlanState.planId === event.plan_id) return;
  const steps = event.steps || [];
  _autoPlanState = { planId: event.plan_id, cardEl: null, consentRequestId: null };
  const stepsHtml = steps.map(function(step) {
    return '<div class="auto-step" data-step-id="' + apiEscapeHtml(step.step_id) + '">' +
      '<div class="auto-step-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/></svg></div>' +
      '<div class="auto-step-desc">' + apiEscapeHtml(step.description || step.step_id) + '</div>' +
      '<div class="auto-step-route">' + apiEscapeHtml((step.route_mode || '').toUpperCase()) + '</div>' +
      '<div class="auto-step-status">待执行</div></div>';
  }).join('');
  const html = '<div class="msg msg-bot auto-plan-msg" data-msg-idx="' + msgIdx + '" data-plan-id="' + apiEscapeHtml(event.plan_id) + '">' +
    '<div class="msg-avatar">伴</div><div class="auto-plan-message-content"><div class="msg-bubble auto-plan-bubble"><div class="auto-plan-card">' +
    '<button type="button" class="auto-plan-header" onclick="_toggleAutoPlanCollapse(\'' + apiEscapeHtml(event.plan_id) + '\')" aria-expanded="true">' +
    '<span class="auto-plan-title">任务拆解 · ' + steps.length + ' 步</span><span class="auto-plan-progress">执行中 · 0/' + steps.length + '</span>' +
    '<span class="auto-plan-collapse"><svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg></span></button>' +
    '<div class="auto-plan-body"><div class="auto-plan-steps">' + stepsHtml + '</div></div>' +
    '<div class="auto-plan-consent" hidden></div></div></div><div class="auto-plan-reply msg-text" hidden></div></div></div>';
  const typing = document.getElementById('typingMsg');
  if (typing) typing.insertAdjacentHTML('beforebegin', html);
  else chat.insertAdjacentHTML('beforeend', html);
  _autoPlanState.cardEl = Array.from(chat.querySelectorAll('[data-plan-id]')).find(function(card) {
    return card.dataset.planId === String(event.plan_id);
  }) || null;
  const message = _autoPlanState.cardEl;
  if (message) {
    _ensureAutoPlanViewState(message);
    requestAnimationFrame(function() {
      _setAutoPlanCollapsed(message, true, false);
    });
  }
  chat.scrollTop = chat.scrollHeight;
}

function _updateAutoStep(event, status, result) {
  if (!_autoPlanState || !_autoPlanState.cardEl) return;
  const step = Array.from(_autoPlanState.cardEl.querySelectorAll('[data-step-id]')).find(function(item) {
    return item.dataset.stepId === String(event.step_id);
  });
  if (!step) return;
  step.classList.remove('running', 'done', 'failed', 'skipped');
  step.classList.add(status);
  const labels = { running: '执行中', done: '完成', failed: '失败', skipped: '已跳过' };
  const statusEl = step.querySelector('.auto-step-status');
  if (statusEl) {
    statusEl.textContent = labels[status] || status;
    if (result != null) statusEl.title = String(result).slice(0, 200);
  }
  const icon = step.querySelector('.auto-step-icon');
  if (icon && status === 'running') icon.innerHTML = '<span class="auto-step-spinner"></span>';
  if (icon && status === 'done') icon.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>';
  if (icon && status === 'failed') icon.innerHTML = '<svg viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17"/></svg>';
  const complete = _autoPlanState.cardEl.querySelectorAll('.auto-step.done, .auto-step.failed, .auto-step.skipped').length;
  const total = _autoPlanState.cardEl.querySelectorAll('.auto-step').length;
  _setAutoPlanSummary(_autoPlanState.cardEl, '执行中 · ' + complete + '/' + total);
}

function _showAutoConsent(event) {
  if (!_autoPlanState || !_autoPlanState.cardEl) return;
  _autoPlanState.planId = event.plan_id;
  _autoPlanState.consentRequestId = event.consent_request_id;
  const consent = _autoPlanState.cardEl.querySelector('.auto-plan-consent');
  if (!consent) return;
  const payload = event.consent_payload || {};
  consent.hidden = false;
  consent.innerHTML = '<div class="auto-consent-card"><div class="auto-consent-title">需要授权</div>' +
    '<div class="auto-consent-desc">' + apiEscapeHtml(payload.description || ('步骤“' + (event.step_id || '') + '”需要授权后才能执行')) + '</div>' +
    '<div class="auto-consent-actions"><button class="cloud-test-btn" onclick="_approveAutoConsent()">授权并继续</button>' +
    '<button class="cloud-save-btn auto-consent-reject" onclick="_rejectAutoConsent()">拒绝</button></div></div>';
}

async function _decideAutoConsent(allowed) {
  if (!_autoPlanState || !_autoPlanState.consentRequestId) return;
  const planId = _autoPlanState.planId;
  const requestId = _autoPlanState.consentRequestId;
  const consent = _autoPlanState.cardEl && _autoPlanState.cardEl.querySelector('.auto-plan-consent');
  if (consent) consent.innerHTML = '<div class="auto-consent-pending">正在记录决定…</div>';
  try {
    const data = await apiJson('/api/consent', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId, allowed: allowed })
    });
    if (consent) consent.hidden = true;
    if (!allowed && data.status === 'declined') apiAppendConsentDeclined(data.message);
    await _resumeAutoPlan(planId, requestId);
  } catch (error) {
    if (consent) {
      consent.hidden = false;
      consent.innerHTML = '<div class="auto-consent-error">处理授权失败：' + apiEscapeHtml(error.message) + '</div>';
    }
    showToast('处理授权失败：' + error.message);
  }
}

function _approveAutoConsent() { return _decideAutoConsent(true); }
function _rejectAutoConsent() { return _decideAutoConsent(false); }

async function _resumeAutoPlan(planId, consentRequestId) {
  const response = await fetch('/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: '', resume: true, plan_id: planId, consent_request_id: consentRequestId, stream: true })
  });
  if (!response.ok) {
    const data = await response.json().catch(function() { return {}; });
    throw new Error(data.error || ('HTTP ' + response.status));
  }
  let finalData = null;
  await apiReadSseStream(response, function(event) {
    if (_handleAutoPlanEvent(event)) {
      if (event.done) finalData = event;
      return;
    }
    if (event.error) throw new Error(event.error);
  });
  if (finalData && finalData.type === PLAN_EVENTS.PLAN_COMPLETE) _finalizeAutoPlan(finalData);
  else if (finalData && finalData.type === PLAN_EVENTS.PLAN_FAILED) _failAutoPlan(finalData);
  else if (finalData && finalData.type === PLAN_EVENTS.PLAN_CANCELLED) _cancelAutoPlan(finalData);
}

function _handleAutoPlanEvent(event, msgIdx) {
  if (!event || !event.type) return false;
  if (event.type === PLAN_EVENTS.PLAN_START) _renderAutoPlanCard(event, msgIdx);
  else if (event.type === PLAN_EVENTS.STEP_START) _updateAutoStep(event, 'running');
  else if (event.type === PLAN_EVENTS.STEP_COMPLETE) _updateAutoStep(event, 'done', event.result);
  else if (event.type === PLAN_EVENTS.STEP_ERROR || event.type === PLAN_EVENTS.STEP_FAILED) _updateAutoStep(event, 'failed', event.message || event.error);
  else if (event.type === PLAN_EVENTS.STEP_SKIPPED) _updateAutoStep(event, 'skipped');
  else if (event.type === PLAN_EVENTS.CONSENT_REQUIRED) _showAutoConsent(event);
  else if (event.type === PLAN_EVENTS.PLAN_BLOCKED) _showAutoPlanBlocked(event);
  else if (![PLAN_EVENTS.PLAN_COMPLETE, PLAN_EVENTS.PLAN_FAILED, PLAN_EVENTS.PLAN_CANCELLED, PLAN_EVENTS.ERROR].includes(event.type)) return false;
  if ([PLAN_EVENTS.PLAN_COMPLETE, PLAN_EVENTS.PLAN_FAILED, PLAN_EVENTS.PLAN_CANCELLED].includes(event.type) && !_autoPlanState && msgIdx != null) {
    _renderAutoPlanCard({ plan_id: event.plan_id || ('auto-result-' + msgIdx), steps: [] }, msgIdx);
  }
  if (event.type === PLAN_EVENTS.ERROR) throw new Error(event.error || 'Auto 执行错误');
  return true;
}

function _finishAutoPlan(event, stateClass, message) {
  if (!_autoPlanState || !_autoPlanState.cardEl) return;
  const card = _autoPlanState.cardEl;
  card.classList.add(stateClass);
  const stateLabels = {
    'auto-plan-done': '已完成',
    'auto-plan-failed': '执行失败',
    'auto-plan-cancelled': '已取消'
  };
  _setAutoPlanSummary(card, stateLabels[stateClass] || '计划已结束');
  const reply = card.parentElement && card.parentElement.querySelector('.auto-plan-reply');
  if (reply) {
    reply.hidden = false;
    reply.textContent = message;
    requestAnimationFrame(function() {
      const chat = document.getElementById('chatMessages');
      if (chat) chat.scrollTop = chat.scrollHeight;
    });
  }
  if (event && event.message_id) apiSetRenderedMessageId(Number(card.closest('.msg').dataset.msgIdx), event.message_id);
  _autoPlanState = null;
}

function _finalizeAutoPlan(event) { _finishAutoPlan(event, 'auto-plan-done', event.reply || '计划已完成'); }
function _failAutoPlan(event) { _finishAutoPlan(event, 'auto-plan-failed', event.reply || ('计划执行失败：' + (event.error || '未知错误'))); }
function _cancelAutoPlan(event) { _finishAutoPlan(event, 'auto-plan-cancelled', event.reply || '计划已取消'); }

function _showAutoPlanBlocked(event) {
  if (!_autoPlanState || !_autoPlanState.cardEl) return;
  if (event.blocked_step_id) _updateAutoStep({ step_id: event.blocked_step_id }, 'failed', event.message);
  const card = _autoPlanState.cardEl;
  card.classList.add('auto-plan-failed');
  _setAutoPlanSummary(card, '执行失败');
  const reply = card.parentElement && card.parentElement.querySelector('.auto-plan-reply');
  if (reply) {
    reply.hidden = false;
    const missing = (event.missing_stages || []).join(' → ');
    reply.textContent = (event.message || '计划被硬门禁阻断') + (missing ? '（缺失阶段：' + missing + '）' : '');
    requestAnimationFrame(function() {
      const chat = document.getElementById('chatMessages');
      if (chat) chat.scrollTop = chat.scrollHeight;
    });
  }
  _autoPlanState = null;
}

window._approveAutoConsent = _approveAutoConsent;
window._rejectAutoConsent = _rejectAutoConsent;
window._toggleAutoPlanCollapse = _toggleAutoPlanCollapse;

async function _pausePlan(planId) {
  const plan = window._activePlans[planId];
  if (!plan) return;
  try {
    const data = await apiJson('/api/plan/' + encodeURIComponent(planId) + '/pause', { method: 'POST' });
    window._activePlans[planId] = data.plan;
    _updatePlanCard(data.plan);
    showToast('已暂停');
  } catch (error) {
    plan.status = 'paused';
    _updatePlanCard(plan);
    showToast('已本地暂停：' + error.message);
  }
}

async function _resumePlan(planId) {
  const plan = window._activePlans[planId];
  if (!plan) return;
  try {
    const data = await apiJson('/api/plan/' + encodeURIComponent(planId) + '/resume', { method: 'POST' });
    window._activePlans[planId] = data.plan;
    _updatePlanCard(data.plan);
    showToast('计划已恢复');
    _executeNextStep(planId);
  } catch (error) {
    showToast('恢复失败：' + error.message);
  }
}

async function _cancelPlan(planId) {
  const plan = window._activePlans[planId];
  if (!plan) return;
  try {
    const data = await apiJson('/api/plan/' + encodeURIComponent(planId) + '/cancel', { method: 'POST' });
    window._activePlans[planId] = data.plan;
    _updatePlanCard(data.plan);
    _renderPlanFinalReply(planId, data.final_reply);
  } catch (error) {
    plan.status = 'cancelled';
    _updatePlanCard(plan);
    showToast('已本地取消：' + error.message);
  }
}

async function loadPersonas() {
  try {
    const data = await apiJson('/api/personas');
    const selector = document.getElementById('personaSelector');
    if (!selector) return;
    window._personaRegistry = {};
    if (!data.items || !data.items.length) {
      selector.innerHTML = apiEmptyState(EMPTY_ICONS.persona, '暂无人格', '确保后端已预置默认人格');
      const card = document.getElementById('personaDetailCard');
      if (card) card.innerHTML = apiEmptyState(EMPTY_ICONS.persona, '暂无人格', '确保后端已预置默认人格');
      return;
    }
    selector.innerHTML = '';
    (data.items || []).forEach(function(persona) {
      selector.insertAdjacentHTML('beforeend',
        '<div class="persona-chip' + (persona.active ? ' active' : '') + '" data-persona-id="' + apiEscapeHtml(persona.id) + '" onclick="selectPersona(this, \'' + apiEscapeHtml(persona.name).replace(/'/g, '&#39;') + '\')">' +
          '<span class="persona-chip-avatar">' + apiEscapeHtml(persona.avatar || persona.name.slice(0, 1)) + '</span>' +
          '<span>' + apiEscapeHtml(persona.name) + '</span>' +
        '</div>');
      var oceanVal = (persona.ocean && persona.ocean.length === 5) ? persona.ocean : [50, 50, 50, 50, 50];
      var traitsVal = Array.isArray(persona.traits)
        ? persona.traits.filter(function(t) { return typeof t === 'string' && t.length >= 2; })
        : [];
      if (!traitsVal.length) traitsVal = _deriveTraits(oceanVal);
      window._personaRegistry[persona.name] = {
        id: persona.id,
        avatar: persona.avatar || persona.name.slice(0, 1),
        desc: persona.desc || '',
        ocean: oceanVal,
        traits: traitsVal,
        anchor: persona.anchor || ''
      };
      if (persona.active) renderPersonaDetail(persona.name);
    });
    if (window._loadedSettings) applySettings(window._loadedSettings);
    const activeItem = (data.items || []).find(function(persona) { return persona.active; });
    const activeChip = document.querySelector('.persona-chip.active');
    if (!activeChip && activeItem) {
      const fallbackChip = document.querySelector('.persona-chip[data-persona-id="' + apiEscapeHtml(activeItem.id) + '"]');
      if (fallbackChip) fallbackChip.classList.add('active');
      if (window._loadedSettings && window._loadedSettings.active_persona_id && window._loadedSettings.active_persona_id !== activeItem.id) {
        saveSetting('active_persona_id', activeItem.id).catch(function(){});
      }
    }
  } catch (error) {
    const selector = document.getElementById('personaSelector');
    if (selector) selector.innerHTML = apiRetryEmptyState('人格加载失败', error.message, 'loadPersonas()');
    const card = document.getElementById('personaDetailCard');
    if (card) card.innerHTML = apiRetryEmptyState('人格加载失败', error.message, 'loadPersonas()');
    showToast('加载失败：' + error.message);
  }
}

async function selectPersona(el, name) {
  const personaId = el.dataset.personaId || (window._personaRegistry[name] && window._personaRegistry[name].id);
  // 本地行为：激活 chip + 渲染详情
  function localActivate() {
    document.querySelectorAll('.persona-chip').forEach(chip => chip.classList.remove('active'));
    el.classList.add('active');
    renderPersonaDetail(name);
    if (personaId) saveSetting('active_persona_id', personaId).catch(function(){});
  }
  // 没有 personaId 时走本地 fallback
  if (!personaId) {
    localActivate();
    showToast('已切换到人格 · ' + name);
    return;
  }
  try {
    await apiJson('/api/personas/' + encodeURIComponent(personaId) + '/activate', { method: 'POST' });
    localActivate();
    showToast('已切换到人格 · ' + name);
  } catch (error) {
    // API 不可用时 fallback 到本地行为——不弹错误
    localActivate();
    showToast('已切换到人格 · ' + name);
  }
}

async function createPersonaApi(formData) {
  const data = await apiJson('/api/personas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData)
  });
  await loadPersonas();
  return data.id || (data.persona && data.persona.id);
}

async function updatePersonaApi(personaId, formData) {
  const data = await apiJson('/api/personas/' + encodeURIComponent(personaId), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData)
  });
  await loadPersonas();
  return data.persona;
}

async function deletePersonaApi(personaId) {
  await apiJson('/api/personas/' + encodeURIComponent(personaId), {
    method: 'DELETE'
  });
  await loadPersonas();
}

function modelMetaLine(model) {
  const meta = model.meta || {};
  const size = meta.size ? (meta.size / 1024 / 1024 / 1024).toFixed(1) + ' GB' : model.status;
  return [size, meta.backend, meta.n_ctx ? ('ctx ' + meta.n_ctx) : ''].filter(Boolean).join(' · ');
}

function renderModels(items, autoEnabled) {
  const localList = document.getElementById('localModelList');
  const cloudList = document.getElementById('cloudModelList');
  if (localList) localList.innerHTML = '';
  if (cloudList) cloudList.innerHTML = '';
  (items || []).filter(model => model.type !== 'cloud').forEach(function(model) {
    if (!localList) return;
    localList.insertAdjacentHTML('beforeend',
      '<div class="model-item' + (model.active ? ' active' : '') + '" data-model-id="' + apiEscapeHtml(model.id) + '" data-model-name="' + apiEscapeHtml(model.name) + '" data-model-type="' + apiEscapeHtml(model.type) + '" data-locked="' + (!!model.locked) + '" onclick="selectModel(this, \'' + apiEscapeHtml(model.name).replace(/'/g, '&#39;') + '\', \'' + apiEscapeHtml(model.type) + '\')">' +
        '<div class="model-item-toggle' + (model.enabled ? ' on' : '') + '" onclick="event.stopPropagation(); toggleModelEnable(this)"></div>' +
        '<div class="model-item-info"><div class="model-item-name">' + apiEscapeHtml(model.name) + '</div><div class="model-item-meta">' + apiEscapeHtml(modelMetaLine(model)) + '</div></div>' +
      '</div>');
  });
  (items || []).filter(model => model.type === 'cloud').forEach(function(model) {
    if (!cloudList) return;
    const meta = model.meta || {};
    cloudList.insertAdjacentHTML('beforeend',
      '<div class="model-item' + (model.active ? ' active' : '') + (model.locked ? ' locked' : '') + '" data-model-id="' + apiEscapeHtml(model.id) + '" data-model-name="' + apiEscapeHtml(model.name) + '" data-model-type="cloud" data-endpoint="' + apiEscapeHtml(meta.endpoint || '') + '" data-cloud-model-name="' + apiEscapeHtml(meta.model_name || model.name || '') + '" data-api-key-masked="' + apiEscapeHtml(meta.api_key_masked || '') + '" data-locked="' + (!!model.locked) + '" onclick="selectModel(this, \'' + apiEscapeHtml(model.name).replace(/'/g, '&#39;') + '\', \'cloud\')">' +
        '<div class="model-item-toggle' + (model.enabled ? ' on' : '') + '" onclick="event.stopPropagation(); toggleModelEnable(this)"></div>' +
        '<div class="model-item-info"><div class="model-item-name">' + apiEscapeHtml(model.name) + (model.locked ? ' 🔒' : '') + '</div><div class="model-item-meta">' + apiEscapeHtml(model.locked ? '登录后可用 · ' + modelMetaLine(model) : modelMetaLine(model)) + '</div><div class="model-item-cloud-meta">' + apiEscapeHtml(meta.endpoint || '') + '</div></div>' +
        '<div class="model-item-actions">' +
          '<button class="edit-btn" onclick="event.stopPropagation(); editCloudModel(this)" title="修改"><svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>' +
          '<button class="del-btn" onclick="event.stopPropagation(); deleteCloudModel(this)" title="删除"><svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>' +
        '</div>' +
      '</div>');
  });
  if (cloudList && !cloudList.children.length) {
    cloudList.innerHTML = '<div class="model-empty" id="cloudEmpty">尚未添加云端模型，在下方配置 API</div>';
  }  const autoToggle = document.getElementById('autoToggle');
  if (autoToggle) autoToggle.classList.toggle('on', !!autoEnabled);
  if (window._loadedSettings && typeof window._loadedSettings.auto_router_enabled === 'boolean' && autoToggle) {
    autoToggle.classList.toggle('on', window._loadedSettings.auto_router_enabled);
  }
  const active = (items || []).find(model => model.active);
  const currentDescription = document.getElementById('currentModelDescription');
  const currentSelect = document.getElementById('currentModelSelect');
  if (currentSelect) {
    currentSelect.innerHTML = '';
    if (!(items || []).length) {
      currentSelect.innerHTML = '<option value="">暂无可用模型</option>';
      currentSelect.disabled = true;
    } else {
      (items || []).forEach(function(model) {
        const option = document.createElement('option');
        option.value = model.id;
        option.textContent = model.name;
        option.dataset.modelName = model.name;
        option.disabled = !!model.locked || model.status !== 'ready';
        option.selected = !!model.active;
        currentSelect.appendChild(option);
      });
      currentSelect.disabled = false;
    }
  }
  if (active) {
    const switcher = document.getElementById('modelSwitcher');
    if (switcher) switcher.textContent = '模型 · ' + active.name;
    if (currentDescription) currentDescription.textContent = '已加载 · ' + active.name;
  } else if (currentDescription) {
    currentDescription.textContent = '尚未加载模型';
  }
  refreshModelCard();
}

async function activateModelFromSettings(select) {
  const modelId = select && select.value;
  if (!modelId) return;
  const option = select.options[select.selectedIndex];
  try {
    await apiJson('/api/models/' + encodeURIComponent(modelId) + '/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: true, name: option.dataset.modelName || option.textContent || modelId })
    });
    await loadModels();
  } catch (error) {
    showToast('模型切换失败：' + error.message);
    await loadModels();
  }
}

async function loadModels() {
  try {
    const data = await apiJson('/api/models');
    renderModels(data.items || [], data.auto);
  } catch (error) {
    showToast('模型加载失败：' + error.message);
  }
}

async function addCloudModelApi(formData) {
  const data = await apiJson('/api/models/cloud', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData)
  });
  await loadModels();
  return data.id || (data.model && data.model.id);
}

async function updateCloudModelApi(modelId, formData) {
  const data = await apiJson('/api/models/cloud/' + encodeURIComponent(modelId), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData)
  });
  await loadModels();
  return data.model;
}

async function deleteCloudModelApi(modelId) {
  await apiJson('/api/models/cloud/' + encodeURIComponent(modelId), {
    method: 'DELETE'
  });
  await loadModels();
}
async function selectModel(el, name, type) {
  const modelId = el.dataset.modelId || name;
  if (el.dataset.locked === 'true') {
    showToast('请先登录以使用云端模型');
    return;
  }
  try {
    await apiJson('/api/models/' + encodeURIComponent(modelId) + '/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: true, name: name, type: type })
    });
    await loadModels();
    showToast('已切换到 ' + name);
  } catch (error) {
    showToast('模型切换失败：' + error.message);
  }
}

async function cardSelectModel(el, name) {
  const matched = Array.from(document.querySelectorAll('#localModelList .model-item, #cloudModelList .model-item')).find(function(item) {
    return (item.dataset.modelName || '').trim() === name;
  });
  if (matched) return selectModel(matched, name, matched.dataset.modelType || 'local');
}

async function toggleAuto(toggle) {
  const enabled = !toggle.classList.contains('on');
  try {
    if (enabled) {
      const models = await apiJson('/api/models');
      const hasEnabledCloud = (models.items || []).some(function(model) {
        return model.type === 'cloud' && model.enabled;
      });
      if (!hasEnabledCloud) {
        showToast('Auto 模式需要至少一个已启用的云端模型');
        return;
      }
    }
    const data = await apiJson('/api/models/auto', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled })
    });
    toggle.classList.toggle('on', data.auto);
    window._autoRouterEnabled = !!data.auto;
    if (data.auto) {
      document.getElementById('modelSwitcher').textContent = '\u6a21\u578b \u00b7 Auto';
      window._planMode = false;
    }
    saveSetting('auto_router_enabled', !!data.auto).catch(function(){});
    showToast(data.auto ? '已启用 Auto 自动路由' : '已关闭 Auto');
  } catch (error) {
    showToast('Auto 切换失败：' + error.message);
  }
}

async function toggleModelEnable(toggle) {
  const item = toggle.closest('.model-item');
  const enabled = !toggle.classList.contains('on');
  try {
    await apiJson('/api/models/' + encodeURIComponent(item.dataset.modelId) + '/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled, name: item.dataset.modelName })
    });
    await loadModels();
    showToast(enabled ? '扩展已启用' : '扩展已停用');
  } catch (error) {
    showToast('模型状态更新失败：' + error.message);
  }
}


function apiEmptyState(iconPath, title, desc, extraClass) {
  return '<div class="empty-state product-empty-state ' + apiEscapeHtml(extraClass || '') + '">' +
    '<div class="empty-icon"><svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' + iconPath + '</svg></div>' +
    '<div class="empty-title">' + apiEscapeHtml(title) + '</div>' +
    '<div class="empty-desc">' + apiEscapeHtml(desc || '') + '</div>' +
  '</div>';
}

function apiRetryEmptyState(title, desc, retryCall) {
  return '<div class="empty-state product-empty-state error-state">' +
    '<div class="empty-icon"><svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg></div>' +
    '<div class="empty-title">' + apiEscapeHtml(title) + '</div>' +
    '<div class="empty-desc">' + apiEscapeHtml(desc || '') + '</div>' +
    '<button class="empty-action" onclick="' + retryCall + '">点击重试</button>' +
  '</div>';
}

const EMPTY_ICONS = {
  persona: '<path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"/><path d="M4 21c0-4 4-7 8-7s8 3 8 7"/>',
  skill: '<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"/>',
  plugin: '<path d="M9 2v6"/><path d="M15 2v6"/><path d="M6 8h12v4a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z"/><path d="M12 16v6"/>',
  memory: '<path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>',
  model: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/>'
};

function extensionIconPath(type) {
  return type === 'plugin'
    ? '<path d="M9 2v6M15 2v6M6 8h12v4a4 4 0 0 1-4 4H10a4 4 0 0 1-4-4z"/>'
    : '<path d="M13 2L3 14h7l-1 8 10-12h-7z"/>';
}

function renderExtensions(items) {
  window._extRegistry = {};
  const skillGrid = document.getElementById('skillGrid');
  const pluginGrid = document.getElementById('pluginGrid');
  if (skillGrid) skillGrid.innerHTML = '';
  if (pluginGrid) pluginGrid.innerHTML = '';
  const extList = items || [];
  if (!extList.length) {
    if (skillGrid) skillGrid.innerHTML = apiEmptyState(EMPTY_ICONS.skill, '暂无已安装技能', '从商城浏览或导入本地技能来扩展能力');
    if (pluginGrid) pluginGrid.innerHTML = apiEmptyState(EMPTY_ICONS.plugin, '暂无已安装插件', '从商城浏览或导入本地插件来扩展能力');
    return;
  }
  extList.forEach(function(ext) {
    const extensionId = String(ext.id || ext.plugin_id || ext.name || '');
    const target = ext.type === 'plugin' ? pluginGrid : skillGrid;
    if (!target) return;
    window._extRegistry[extensionId] = {
      type: ext.type,
      name: ext.name,
      source: ext.source,
      status: ext.enabled ? 'enabled' : (ext.status || 'disabled'),
      icon: ext.icon || extensionIconPath(ext.type),
      desc: ext.description || '',
      version: ext.version || '',
      author: ext.author || 'local',
      installDate: _formatTimestamp(ext.installed_at, '-'),
      size: ext.size || '-',
      seccompProfile: ext.seccomp_profile || ext.type || '-',
      capabilities: ext.capabilities || [],
      permissions: (ext.permissions || []).map(function(permission) {
        return { name: String(permission), desc: '', level: 'granted', modifiable: false };
      }),
      usage: ext.usage || '',
      runCount: ext.run_count || 0,
      lastRun: _formatTimestamp(ext.last_run, '-'),
      errorCount: ext.error_count || 0,
      reviewStatus: ext.review_status,
      canSubmit: !!ext.can_submit
    };
    target.insertAdjacentHTML('beforeend',
      '<div class="ext-card" data-ext-id="' + apiEscapeHtml(extensionId) + '" data-type="' + apiEscapeHtml(ext.type || 'skill') + '" onclick="showExtDetail(' + apiJsArg(extensionId) + ')">' +
        '<div class="ext-card-icon"><svg viewBox="0 0 24 24">' + extensionIconPath(ext.type) + '</svg></div>' +
        '<div class="ext-card-body">' +
          '<div class="ext-card-title">' + apiEscapeHtml(ext.name) + '</div>' +
          '<div class="ext-card-desc">' + apiEscapeHtml(ext.description || '') + '</div>' +
          '<div class="ext-card-footer"><button class="cloud-test-btn" data-enabled="' + (!!ext.enabled) + '" onclick="event.stopPropagation(); toggleExtension(this, ' + apiJsArg(extensionId) + ')">' + (ext.enabled ? '禁用' : '启用') + '</button></div>' +
        '</div>' +
      '</div>');
  });
  if (skillGrid && !skillGrid.children.length) skillGrid.innerHTML = apiEmptyState(EMPTY_ICONS.skill, '暂无已安装技能', '从商城浏览或导入本地技能来扩展能力');
  if (pluginGrid && !pluginGrid.children.length) pluginGrid.innerHTML = apiEmptyState(EMPTY_ICONS.plugin, '暂无已安装插件', '从商城浏览或导入本地插件来扩展能力');
}

async function loadExtensions() {
  try {
    const data = await apiJson('/api/extensions');
    renderExtensions(data.items || data.extensions || []);
  } catch (error) {
    window._extRegistry = {};
    const skillGrid = document.getElementById('skillGrid');
    const pluginGrid = document.getElementById('pluginGrid');
    if (skillGrid) skillGrid.innerHTML = apiRetryEmptyState('扩展加载失败', error.message, 'loadExtensions()');
    if (pluginGrid) pluginGrid.innerHTML = apiRetryEmptyState('扩展加载失败', error.message, 'loadExtensions()');
    showToast('加载失败：' + error.message);
  }
}

async function toggleExtension(btn, extensionId) {
  const enabled = btn.dataset.enabled !== 'true';
  try {
    await apiJson('/api/extensions/' + encodeURIComponent(extensionId) + '/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled })
    });
    await loadExtensions();
    showToast(enabled ? '扩展已启用' : '扩展已停用');
  } catch (error) {
    showToast('扩展状态更新失败：' + error.message);
  }
}

async function installExtension(sourcePath) {
  const data = await apiJson('/api/extensions/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_path: sourcePath })
  });
  await loadExtensions();
  return data;
}

async function uninstallExtension(extensionId) {
  await apiJson('/api/extensions/' + encodeURIComponent(extensionId), {
    method: 'DELETE'
  });
  await loadExtensions();
}

async function loadRuntimeStatus() {
  try {
    const data = await apiJson('/api/status');
    window._privacyMode = privacyModeToUi(data.privacy_mode);
    window._loggedIn = !!data.logged_in;
    renderPrivacyMode(window._privacyMode);
    renderLoginState(window._loggedIn, data.account_name || 'local-user');
    if (data.repaired_state_files && data.repaired_state_files.length) {
      showToast('检测到配置文件损坏，已从备份恢复');
    }
    if (data.backend_mode === 'cloud_fallback') {
      showToast('本地模型加载失败，已切换到云端模式');
    } else if (data.backend_mode === 'no_backend') {
      if (data.privacy_mode === 'local_only' && data.cloud_available) {
        showToast('本地模型加载失败，LOCAL_ONLY 隐私模式阻止上云');
      } else {
        showToast('本地模型加载失败，且未配置可用的云端模型');
      }
    }
  } catch (error) {
    showToast('状态加载失败：' + error.message);
  }
}

async function loadPendingCrashReport() {
  try {
    const data = await apiJson('/api/crash-report/pending');
    if (!data.has_crash) return;
    const markForSubmit = window.confirm(
      '上次运行异常退出。是否将本地崩溃日志标记为待上报？\n应用不会自动联网发送。'
    );
    const endpoint = markForSubmit ? '/api/crash-report/submit' : '/api/crash-report/dismiss';
    const result = await apiJson(endpoint, { method: 'POST' });
    if (markForSubmit && result.submitted) {
      showToast('崩溃日志已保存为待上报（未自动联网）');
    } else {
      showToast('崩溃日志已在本地归档');
    }
  } catch (error) {
    showToast('处理崩溃日志失败：' + error.message);
  }
}

function privacyModeToUi(mode) {
  if (mode === 'local_only') return 'LOCAL_ONLY';
  if (mode === 'auto_route_cloud') return 'CLOUD';
  if (mode === 'ask_before_cloud' || mode === 'always_ask') return 'LAN';
  return mode || 'LOCAL_ONLY';
}

function renderPrivacyMode(mode) {
  const desc = document.getElementById('privacyDesc');
  if (desc && window._privacyDescMap) desc.textContent = window._privacyDescMap[mode] || mode;
  document.querySelectorAll('[data-privacy-mode]').forEach(function(item) {
    item.classList.toggle('active', item.dataset.privacyMode === mode);
  });
}

function renderLoginState(loggedIn, accountName) {
  window._loggedIn = !!loggedIn;
  const loginBtn = document.getElementById('loginBtn');
  if (loginBtn) loginBtn.textContent = loggedIn ? 'Logout' : 'Login';
  const cloudSyncBtn = document.getElementById('cloudSyncBtn');
  if (cloudSyncBtn) cloudSyncBtn.style.display = loggedIn ? '' : 'none';
  const feature = document.getElementById('cloudSyncFeature');
  if (feature) feature.classList.toggle('locked', !loggedIn);
  const avatar = document.querySelector('.avatar-btn');
  if (avatar && accountName) avatar.title = loggedIn ? ('Logged in · ' + accountName) : 'Not logged in';
}

async function loadAuthStatus() {
  try {
    const data = await apiJson('/api/auth/status');
    renderLoginState(data.logged_in, data.account_name);
  } catch (error) {
    showToast('Failed to load login status: ' + error.message);
  }
}

async function toggleLogin() {
  try {
    if (window._loggedIn) {
      const data = await apiJson('/api/auth/logout', { method: 'POST' });
      renderLoginState(false);
      window._improvePlanEnabled = false;
      renderImprovePlan({ enabled: false, queued_count: 0 });
      await loadModels();
      showToast(data.logged_in ? 'Login state unchanged' : 'Logged out');
      return;
    }
    const status = await apiJson('/api/auth/status');
    const token = window.prompt('Enter local login token (see auth.json):', status.token_preview || '');
    if (!token) return;
    const data = await apiJson('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token })
    });
    renderLoginState(data.logged_in, data.account_name);
    await loadModels();
    showToast('Logged in · cloud models unlocked');
  } catch (error) {
    showToast('Login failed: ' + error.message);
  }
}

function renderImprovePlan(data) {
  window._improvePlanEnabled = !!(data && data.enabled);
  if (window._loadedSettings && typeof window._loadedSettings.improve_plan_enabled === 'boolean') {
    window._improvePlanEnabled = window._loadedSettings.improve_plan_enabled;
  }
  const toggle = document.getElementById('improveToggle');
  if (toggle) toggle.classList.toggle('on', window._improvePlanEnabled);
  const row = document.getElementById('improveStatusRow');
  if (row) row.style.display = window._improvePlanEnabled ? '' : 'none';
  const status = document.getElementById('improveStatus');
  if (status && data) status.textContent = 'Local upload queue: ' + (data.queued_count || 0) + ' items';
}

async function loadImprovePlan() {
  try {
    renderImprovePlan(await apiJson('/api/improve-plan'));
  } catch (error) {
    showToast('Failed to load improve-plan status: ' + error.message);
  }
}

async function toggleImprovePlan(el) {
  const enabled = !(el && el.classList.contains('on'));
  try {
    const data = await apiJson('/api/improve-plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled })
    });
    renderImprovePlan(data);
    showToast(data.enabled ? 'Improve plan enabled · local queue only' : 'Improve plan disabled');
  } catch (error) {
    if (error.message === 'requires_login_and_cloud') {
      showToast('Improve plan requires login and CLOUD mode');
      return;
    }
    showToast('Failed to update improve plan: ' + error.message);
  }
}

async function updatePrivacyDesc(mode) {
  renderPrivacyMode(mode);
  try {
    const data = await apiJson('/api/privacy/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode })
    });
    window._privacyMode = privacyModeToUi(data.privacy_mode);
    renderPrivacyMode(window._privacyMode);
    loadImprovePlan();
    showToast('隐私模式已切换 · ' + window._privacyMode);
  } catch (error) {
    showToast('隐私模式切换失败：' + error.message);
  }
}

function currentContextMessageId() {
  if (!window._ctxTargetMsg) return null;
  const msg = window._ctxTargetMsg.closest('.msg');
  if (!msg) return null;
  return msg.dataset.messageId || msg.dataset.msgIdx || null;
}

async function ctxFlagError() {
  document.getElementById('msgContextMenu').style.display = 'none';
  if (!window._ctxTargetMsg) return;
  const msg = window._ctxTargetMsg.closest('.msg');
  if (msg) {
    msg.style.opacity = '0.6';
    const bubble = msg.querySelector('.msg-bubble');
    if (bubble) {
      bubble.style.borderLeft = '3px solid var(--warning)';
      bubble.style.borderRadius = '0 8px 8px 0';
    }
  }
  try {
    await apiJson('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ msg_id: currentContextMessageId(), session_id: _currentSessionId, type: 'error' })
    });
    showToast(window._improvePlanEnabled && window._privacyMode === 'CLOUD' ? '已标记有误 · 等待匿名上传' : '已标记有误 · 本地记录');
  } catch (error) {
    showToast('反馈记录失败：' + error.message);
  }
}

function addReaction(btn, emoji) {
  if (!window._ctxTargetMsg) return;
  const bar = document.getElementById('emojiBar');
  bar.style.display = 'none';
  const bubble = window._ctxTargetMsg;
  let reactionsEl = bubble.querySelector('.msg-reactions');
  if (!reactionsEl) {
    reactionsEl = document.createElement('div');
    reactionsEl.className = 'msg-reactions';
    bubble.appendChild(reactionsEl);
  }
  // toggle: if emoji already exists, remove it; otherwise add it
  const existing = reactionsEl.querySelectorAll('.msg-reaction');
  for (const r of existing) {
    if (r.dataset.emoji === emoji) { r.remove(); return; }
  }
  const reaction = document.createElement('span');
  reaction.className = 'msg-reaction';
  reaction.dataset.emoji = emoji;
  reaction.innerHTML = '<span>' + emoji + '</span>';
  reactionsEl.appendChild(reaction);
}


