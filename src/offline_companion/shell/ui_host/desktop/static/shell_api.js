// 概要：后端第 1 批接线层，覆盖原型中的 mock 会话、聊天与记忆函数。
var _currentSessionId = null;
var _windowDragState = null;
var _windowResizeState = null;
var _windowBoundsThrottle = null;

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
  try {
    const data = await apiJson('/api/settings');
    const settings = (data && data.settings) || {};
    applySettings(settings);
    setTimeout(function() { applySettings(settings); }, 0);
    setTimeout(function() { applySettings(settings); }, 100);
    return data.settings || {};
  } catch (error) {
    showToast('Failed to load settings: ' + error.message);
    return {};
  }
}

async function saveSetting(key, value) {
  const payload = {};
  payload[key] = value;
  const data = await apiJson('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  applySettings((data && data.settings) || {});
  return data.settings || {};
}

window.applySettings = applySettings;
window.loadSettings = loadSettings;
window.saveSetting = saveSetting;
window.collectSettingsDomSnapshot = collectSettingsDomSnapshot;
window.postSettingsDomSnapshot = postSettingsDomSnapshot;

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
  const handle = event.target.closest('.resize-handle');
  if (!handle) return;
  event.preventDefault();
  event.stopPropagation();
  const bounds = await api.get_bounds();
  _windowResizeState = {
    dir: handle.dataset.dir || '',
    startX: event.screenX,
    startY: event.screenY,
    bounds: bounds
  };
  document.addEventListener('mousemove', moveWindowResize, true);
  document.addEventListener('mouseup', endWindowResize, true);
}

function moveWindowResize(event) {
  if (!_windowResizeState) return;
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
  _windowResizeState = null;
  document.removeEventListener('mousemove', moveWindowResize, true);
  document.removeEventListener('mouseup', endWindowResize, true);
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

async function apiReadSseStream(resp, onEvent) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const result = await reader.read();
    if (result.done) break;
    buffer += decoder.decode(result.value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    parts.forEach(function(part) {
      part.split('\n').forEach(function(line) {
        if (!line.startsWith('data:')) return;
        const raw = line.slice(5).trim();
        if (raw) onEvent(JSON.parse(raw));
      });
    });
  }
  const rest = buffer.trim();
  if (rest.startsWith('data:')) onEvent(JSON.parse(rest.slice(5).trim()));
}

async function sendMessage() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;
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

  if (window._planMode) {
    showTyping();
    try {
      const data = await apiJson('/api/plan/decompose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: text })
      });
      hideTyping();
      const plan = data.plan;
      window._activePlans[plan.id] = plan;
      _renderPlanCard(plan, new Date().toTimeString().slice(0, 5));
      chat.scrollTop = chat.scrollHeight;
    } catch (error) {
      hideTyping();
      showToast('任务拆解失败：' + error.message);
    }
    return;
  }

  showTyping();
  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: _currentSessionId, quote: quote, stream: true })
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.error || ('HTTP ' + resp.status));
    }
    if (!resp.body) {
      const data = await resp.json();
      hideTyping();
      apiAppendMessage(data.blocked ? 'system' : 'assistant', data.reply || data.error || '', nextIdx + 1, Date.now() / 1000);
      apiSetRenderedMessageId(nextIdx + 1, data.message_id);
      chat.scrollTop = chat.scrollHeight;
      if (data.memory_saved && data.memory_saved.length) loadMemories();
      return;
    }
    hideTyping();
    const bubble = apiCreateStreamingMessage(nextIdx + 1);
    let finalData = null;
    let streamedText = '';
    await apiReadSseStream(resp, function(event) {
      if (event.error) throw new Error(event.error);
      if (event.recall != null && event.recall > 0) showToast('召回 ' + event.recall + ' 条记忆');
      if (event.token) {
        streamedText += event.token;
        if (bubble) bubble.textContent = streamedText;
        chat.scrollTop = chat.scrollHeight;
      }
      if (event.done) finalData = event;
    });
    if (finalData && finalData.blocked && bubble) {
      const msg = bubble.closest('.msg');
      if (msg) {
        msg.classList.remove('msg-bot');
        msg.classList.add('msg-system');
      }
    }
    if (finalData && finalData.reply && !streamedText && bubble) bubble.textContent = finalData.reply;
    if (finalData) apiSetRenderedMessageId(nextIdx + 1, finalData.message_id);
    chat.scrollTop = chat.scrollHeight;
    if (finalData && finalData.memory_saved && finalData.memory_saved.length) loadMemories();
  } catch (error) {
    hideTyping();
    showToast('消息发送失败：' + error.message);
  }
}

function renderChatHistory(messages) {
  const chat = document.getElementById('chatMessages');
  if (!chat) return;
  let html = '<div class="msg msg-system"><div class="msg-bubble">会话已加载 · 本地记忆可用</div></div>';
  (messages || []).forEach(function(msg) {
    html += apiRenderMessage(msg.role === 'assistant' ? 'assistant' : msg.role, msg.content, msg.msg_idx, msg.created_at, '', msg.id);
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
    }
  } catch (error) {
    showToast('会话加载失败：' + error.message);
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
  const value = item.memory_type || (item.meta && item.meta.memory_type) || 'fact';
  return ({ fact: '\u77e5\u8bc6', preference: '\u504f\u597d', user_preference: '\u504f\u597d', episode: '\u4e8b\u4ef6', agent_profile: '\u753b\u50cf', user_profile: '\u753b\u50cf', knowledge: '\u77e5\u8bc6' })[value] || value;
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
    const created = _formatTimestamp(item.created_at, '-');
    const modified = _formatTimestamp(item.modified_at || item.updated_at, created);
    list.insertAdjacentHTML('beforeend',
      '<div class="memory-card" onclick="openMemoryDetail(this)" data-id="' + item.id + '" data-type="' + apiEscapeHtml(type) + '" data-source="' + apiEscapeHtml(item.source || '') + '" data-created="' + created + '" data-modified="' + modified + '" data-status="' + (item.status || 'active') + '" data-tags=\'' + apiEscapeHtml(JSON.stringify(tags)) + '\'>' +
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
    renderMemoryCards(data.items || []);
    window._memoryPoints = (data.items || []).slice(0, 8).map(function(item, idx) {
      return { msgIdx: idx, id: item.id, title: memoryPanelTitle(item, idx), badge: memoryTypeLabel(item), summary: item.body || item.content || '', original: item.body || item.content || '', turn: idx + 1, time: apiTime(item.modified_at || item.created_at) };
    });
    initMemoryPanel();
  } catch (error) {
    showToast('记忆加载失败：' + error.message);
  }
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
    await apiJson('/api/memories/' + encodeURIComponent(window._currentMemoryCard.dataset.id), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: content }) });
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
      await apiJson('/api/memories/' + encodeURIComponent(id) + '/delete', { method: 'POST' });
      window._currentMemoryCard = null;
      closeMemoryDetail();
      await loadMemories();
      showToast('记忆已删除');
    } catch (error) {
      showToast('删除记忆失败：' + error.message);
    }
  });
}

document.addEventListener('DOMContentLoaded', async function() {
  apiEnsureTypingNode();
  syncWindowMaximizedState();
  const titleBar = document.querySelector('.title-bar');
  if (titleBar) titleBar.addEventListener('mousedown', beginWindowDrag, true);
  document.querySelectorAll('.resize-handle').forEach(function(handle) {
    handle.addEventListener('mousedown', beginWindowResize, true);
  });
  await loadSettings();
  loadSessions();
  loadMemories();
  loadPersonas();
  loadModels();
  loadExtensions();
  loadRuntimeStatus();
  loadAuthStatus();
  loadImprovePlan();
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
      plan.status = 'done';
      _updatePlanCard(plan);
      showToast('任务计划已完成');
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
    if (data.plan.status === 'running') _executeNextStep(planId);
    if (data.plan.status === 'done') showToast('任务计划已完成');
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
    await apiJson('/api/consent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: consentRequestId, allowed: false })
    });
    step.status = 'failed';
    step.error = '用户拒绝授权';
    plan.status = 'paused';
    _updatePlanCard(plan);
    showToast('已拒绝授权，计划已暂停');
  } catch (error) {
    showToast('拒绝授权记录失败：' + error.message);
  }
}

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
    showToast('计划已取消');
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
    cloudList.insertAdjacentHTML('beforeend',
      '<div class="model-item' + (model.active ? ' active' : '') + (model.locked ? ' locked' : '') + '" data-model-id="' + apiEscapeHtml(model.id) + '" data-model-name="' + apiEscapeHtml(model.name) + '" data-model-type="cloud" data-locked="' + (!!model.locked) + '" onclick="selectModel(this, \'' + apiEscapeHtml(model.name).replace(/'/g, '&#39;') + '\', \'cloud\')">' +
        '<div class="model-item-toggle' + (model.enabled ? ' on' : '') + '" onclick="event.stopPropagation(); toggleModelEnable(this)"></div>' +
        '<div class="model-item-info"><div class="model-item-name">' + apiEscapeHtml(model.name) + (model.locked ? ' 🔒' : '') + '</div><div class="model-item-meta">' + apiEscapeHtml(model.locked ? '登录后可用 · ' + modelMetaLine(model) : modelMetaLine(model)) + '</div></div>' +
      '</div>');
  });
  const autoToggle = document.getElementById('autoToggle');
  if (autoToggle) autoToggle.classList.toggle('on', !!autoEnabled);
  if (window._loadedSettings && typeof window._loadedSettings.auto_router_enabled === 'boolean' && autoToggle) {
    autoToggle.classList.toggle('on', window._loadedSettings.auto_router_enabled);
  }
  const active = (items || []).find(model => model.active);
  if (active) {
    const switcher = document.getElementById('modelSwitcher');
    if (switcher) switcher.textContent = '模型 · ' + active.name;
  }
  refreshModelCard();
}

async function loadModels() {
  try {
    const data = await apiJson('/api/models');
    renderModels(data.items || [], data.auto);
  } catch (error) {
    showToast('模型加载失败：' + error.message);
  }
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
    const data = await apiJson('/api/models/auto', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled })
    });
    toggle.classList.toggle('on', data.auto);
    if (data.auto) document.getElementById('modelSwitcher').textContent = '\u6a21\u578b \u00b7 Auto';
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

async function loadRuntimeStatus() {
  try {
    const data = await apiJson('/api/status');
    window._privacyMode = privacyModeToUi(data.privacy_mode);
    window._loggedIn = !!data.logged_in;
    renderPrivacyMode(window._privacyMode);
    renderLoginState(window._loggedIn, data.account_name || 'local-user');
  } catch (error) {
    showToast('状态加载失败：' + error.message);
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

