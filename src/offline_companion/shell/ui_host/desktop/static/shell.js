function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  document.querySelector('.app').setAttribute('data-theme', t);
  document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.theme-btn').forEach(b => { if (b.textContent.includes(t === 'light' ? '浅' : t === 'dark' ? '深' : '粉')) b.classList.add('active'); });
  if (typeof saveSetting === 'function') saveSetting('theme', t).catch(function(){});
}

var _privacyDescMap = {
  'LOCAL_ONLY': 'LOCAL_ONLY：纯本地运行，不联网，所有数据不出本机',
  'LAN': 'LAN：局域网内可通信，不出公网，适合局域网内模型共享',
  'CLOUD': 'CLOUD：允许公网访问，需 A2 许可 + A3 授权审计，数据可能出本机'
};

function updatePrivacyDesc(mode) {
  var el = document.getElementById('privacyDesc');
  if (el) el.textContent = _privacyDescMap[mode] || mode;
}

// ── 改进计划 ──
var _improvePlanEnabled = false;
var _privacyMode = 'LOCAL_ONLY';

function toggleImprovePlan(el) {
  if (!_improvePlanEnabled) {
    // 前置条件：非本地 + 已登录
    if (!_loggedIn) {
      showToast('改进计划需要登录后才能参与');
      return;
    }
    if (_privacyMode === 'LOCAL_ONLY') {
      showToast('改进计划需要在云端模式下才能参与');
      return;
    }
    showConfirm(
      '参与改进计划',
      '开启后，你对 Agent 回复的「标记有误」和「表情回应」将匿名上传到云端用于优化回复质量。不包含对话原文，不包含个人数据。你可随时关闭。',
      function() {
        _improvePlanEnabled = true;
        el.classList.add('on');
        var statusEl = document.getElementById('improveStatus');
        var statusRow = document.getElementById('improveStatusRow');
        if (statusRow) statusRow.style.display = '';
        if (statusEl) statusEl.innerHTML = '<span style="color:var(--success);">● 已参与 · 反馈数据匿名上传</span>';
        showToast('已加入改进计划 · 感谢你的贡献');
      },
      null,
      'success'
    );
  } else {
    _improvePlanEnabled = false;
    el.classList.remove('on');
    var statusRow = document.getElementById('improveStatusRow');
    if (statusRow) statusRow.style.display = 'none';
    showToast('已退出改进计划');
  }
}

function switchView(v, opts) {
  opts = opts || {};
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.view').forEach(s => s.classList.remove('active'));
  var view = document.querySelector('[data-view="' + v + '"]');
  if (view) view.classList.add('active');
  var navBtn = document.querySelector('.nav-btn[onclick*="' + v + '"]');
  if (navBtn) navBtn.classList.add('active');
  if (opts.persist !== false && typeof saveSetting === 'function') saveSetting('last_view', v).catch(function(){});
  // 窗口按钮只在 chat 视图显示，其他视图隐藏
  var wc = document.getElementById('windowControls');
  if (wc) wc.classList.toggle('hidden', v !== 'chat');
  if (v === 'samples' && !opts.skipSampleLoad && typeof loadDecompSamples === 'function') loadDecompSamples();
}

var _decompSamples = [];
var _decompSampleState = 'all';
var _selectedDecompSampleId = null;
var _decompSampleHasMore = false;
var _decompSampleOffset = 0;

function openDecompSampleLibrary(sampleId) {
  _selectedDecompSampleId = sampleId ? String(sampleId) : null;
  switchView('samples', { skipSampleLoad: true });
  if (_selectedDecompSampleId && typeof focusDecompSample === 'function') focusDecompSample(_selectedDecompSampleId);
  else if (typeof loadDecompSamples === 'function') loadDecompSamples();
}

function selectDecompSampleState(state) {
  _decompSampleState = state || '';
  document.querySelectorAll('.sample-tab').forEach(function(button) {
    button.classList.toggle('active', button.dataset.state === _decompSampleState);
  });
  if (typeof loadDecompSamples === 'function') loadDecompSamples(_decompSampleState);
}

function _decompSampleBadge(sample) {
  if (sample.state === 'verified') return sample.verify_kind === 'user' ? '已验证 · 用户' : '已验证 · 自动';
  return { candidate: '候选', stale: '待复核', rejected: '已丢弃', archived: '已归档' }[sample.state] || sample.state;
}

function renderDecompSamples(items) {
  _decompSamples = Array.isArray(items) ? items : [];
  var list = document.getElementById('decompSampleList');
  if (!list) return;
  if (!_decompSamples.length) {
    list.innerHTML = '<div class="sample-empty">当前筛选下没有范例</div>';
    renderDecompSampleDetail(null);
    return;
  }
  if (!_selectedDecompSampleId || !_decompSamples.some(function(item) { return item.id === _selectedDecompSampleId; })) {
    _selectedDecompSampleId = _decompSamples[0].id;
  }
  list.innerHTML = _decompSamples.map(function(sample) {
    var usage = sample.usage || {};
    var active = sample.id === _selectedDecompSampleId ? ' active' : '';
    var lastHit = sample.last_hit_at ? formatApiDateTime(sample.last_hit_at) : '尚未命中';
    return '<button class="sample-list-item' + active + '" onclick="selectDecompSample(\'' + sample.id + '\')">' +
      '<div class="sample-list-top"><span class="sample-task">' + escapeHtml(sample.task_description) + '</span>' +
      '<span class="sample-badge ' + sample.state + '">' + escapeHtml(_decompSampleBadge(sample)) + '</span></div>' +
      '<div class="sample-meta">使用 ' + Number(usage.injected_count || 0) + ' · 成功 ' + Number(usage.plan_completed || 0) +
      ' · ' + escapeHtml(lastHit) + '</div></button>';
  }).join('') + (_decompSampleHasMore ?
    '<button class="sample-load-more" onclick="loadMoreDecompSamples()">加载更多</button>' : '');
  renderDecompSampleDetail(_decompSamples.find(function(item) { return item.id === _selectedDecompSampleId; }));
}

function selectDecompSample(sampleId) {
  _selectedDecompSampleId = String(sampleId);
  renderDecompSamples(_decompSamples);
}

function renderDecompSampleDetail(sample) {
  var detail = document.getElementById('decompSampleDetail');
  if (!detail) return;
  if (!sample) {
    detail.innerHTML = '<div class="sample-empty">选择一个范例查看详情</div>';
    return;
  }
  var provenance = ((sample.provenance || {}).sample_ids || []);
  var steps = (sample.steps || []).map(function(step, index) {
    return '<div class="sample-step-edit"><span>' + (index + 1) + '</span><input value="' +
      escapeHtml(step.title || '') + '" data-sample-step-title><textarea data-sample-step-description>' +
      escapeHtml(step.description || '') + '</textarea></div>';
  }).join('');
  var actions = '<button class="cloud-save-btn" onclick="apiEditDecompSample(\'' + sample.id + '\')">保存编辑</button>';
  if (!(sample.state === 'verified' && sample.verify_kind === 'user')) {
    actions += '<button class="cloud-test-btn" onclick="apiTransitionDecompSample(\'' + sample.id + '\',\'verify\')">确认为范例</button>';
  }
  if (sample.state === 'rejected' || sample.state === 'archived' || sample.state === 'stale') {
    actions += '<button class="cloud-test-btn" onclick="apiTransitionDecompSample(\'' + sample.id + '\',\'restore\')">恢复</button>';
  } else {
    actions += '<button class="cloud-test-btn danger" onclick="confirmRejectDecompSample(\'' + sample.id + '\')">丢弃</button>';
  }
  actions += '<button class="cloud-test-btn danger" onclick="confirmDeleteDecompSample(\'' + sample.id + '\')">永久删除</button>';
  detail.innerHTML = '<div class="sample-detail-head"><span class="sample-badge ' + sample.state + '">' +
    escapeHtml(_decompSampleBadge(sample)) + '</span><span>版本 ' + Number(sample.version || 1) + '</span></div>' +
    '<label class="sample-field-label">任务描述</label><textarea id="sampleTaskDescription" class="sample-task-editor">' +
    escapeHtml(sample.task_description) + '</textarea><label class="sample-field-label">拆解步骤</label>' + steps +
    '<div class="sample-provenance">参考了 ' + provenance.length + ' 个历史范例' +
    (provenance.length ? '：' + provenance.map(escapeHtml).join('、') : '') + '</div>' +
    (sample.stale_reason ? '<div class="sample-stale-reason">待复核原因：' + escapeHtml(sample.stale_reason) + '</div>' : '') +
    '<div class="sample-detail-actions">' + actions + '</div>';
}

function applyOptimisticDecompSample(sampleId, changes) {
  var sample = _decompSamples.find(function(item) { return item.id === String(sampleId); });
  if (!sample) return null;
  var previous = JSON.parse(JSON.stringify(sample));
  Object.assign(sample, changes || {});
  renderDecompSamples(_decompSamples);
  return previous;
}

function rollbackOptimisticDecompSample(previous) {
  if (!previous) return;
  var index = _decompSamples.findIndex(function(item) { return item.id === previous.id; });
  if (index >= 0) _decompSamples[index] = previous;
  renderDecompSamples(_decompSamples);
}

function confirmRejectDecompSample(sampleId) {
  showConfirm('丢弃任务拆解范例', '确认丢弃这个范例吗？之后仍可在「已丢弃」中恢复。', function() {
    apiTransitionDecompSample(sampleId, 'reject');
  });
}

function confirmDeleteDecompSample(sampleId) {
  showConfirm('永久删除任务拆解范例', '确定要永久删除这个范例吗？此操作不可撤销。', function() {
    apiDeleteDecompSample(sampleId);
  });
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 82) + 'px';
}

function updateSendBtn() {
  const input = document.getElementById('chatInput');
  const btn = document.getElementById('sendBtn');
  if (typeof _chatRequestActive !== 'undefined' && _chatRequestActive) return;
  if (input.value.trim()) { btn.classList.add('active'); }
  else { btn.classList.remove('active'); }
}

var _planMode = false;
var _currentSessionId = null;

async function apiJson(url, options) {
  var resp = await fetch(url, options || {});
  var data = await resp.json().catch(function() { return {}; });
  if (!resp.ok) {
    throw new Error(data.error || ('HTTP ' + resp.status));
  }
  return data;
}

function formatApiTime(value) {
  if (value === null || value === undefined || value === '') return '';
  var date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  return date.toTimeString().slice(0, 5);
}

function formatApiDateTime(value) {
  if (value === null || value === undefined || value === '') return '';
  var date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  return date.toISOString().slice(0, 16).replace('T', ' ');
}

function roleToClass(role) {
  return role === 'user' ? 'msg-user' : (role === 'system' ? 'msg-system' : 'msg-bot');
}

function roleToAvatar(role) {
  return role === 'user' ? '我' : (role === 'system' ? '' : '诺');
}

function ensureTypingNode() {
  var chat = document.getElementById('chatMessages');
  if (!chat || document.getElementById('typingMsg')) return;
  chat.insertAdjacentHTML('beforeend',
    '<div class="msg msg-bot" id="typingMsg" style="display:none;">' +
      '<div class="msg-avatar">诺</div>' +
      '<div class="msg-bubble"><div class="typing"><span></span><span></span><span></span></div></div>' +
    '</div>');
}

function renderMessage(role, content, msgIdx, createdAt, quoteHtml) {
  var cls = roleToClass(role);
  var avatar = roleToAvatar(role);
  var time = formatApiTime(createdAt) || new Date().toTimeString().slice(0,5);
  if (role === 'system') {
    return '<div class="msg msg-system">' +
      '<div class="msg-bubble">' + escapeHtml(content || '') + '</div>' +
    '</div>';
  }
  return '<div class="msg ' + cls + '" data-msg-idx="' + msgIdx + '">' +
    '<div class="msg-avatar">' + avatar + '</div>' +
    '<div class="msg-bubble">' + (quoteHtml || '') + '<p>' + escapeHtml(content || '') + '</p><span class="meta-time">' + time + '</span></div>' +
  '</div>';
}

function appendChatMessage(role, content, msgIdx, createdAt, quoteHtml) {
  ensureTypingNode();
  var typing = document.getElementById('typingMsg');
  if (typing) {
    typing.insertAdjacentHTML('beforebegin', renderMessage(role, content, msgIdx, createdAt, quoteHtml));
  } else {
    document.getElementById('chatMessages').insertAdjacentHTML('beforeend', renderMessage(role, content, msgIdx, createdAt, quoteHtml));
  }
}

function nextMessageIndex() {
  return document.getElementById('chatMessages').querySelectorAll('[data-msg-idx]').length;
}

// ── 窗口控制（浏览器式） ──
function windowMinimize() {
  showToast('窗口已收起');
}

var _savedAppStyle = null;

function windowToggleMaximize() {
  var app = document.getElementById('appRoot');
  var btn = document.getElementById('maximizeBtn');
  if (!app.classList.contains('maximized')) {
    // save current size/pos before maximizing
    _savedAppStyle = {
      width: app.style.width || '960px',
      height: app.style.height || '640px',
      left: app.style.left || '',
      top: app.style.top || '',
      margin: app.style.margin || ''
    };
    app.classList.add('maximized');
    app.style.width = '100vw';
    app.style.height = '100vh';
    app.style.left = '0';
    app.style.top = '0';
    app.style.margin = '0';
    btn.innerHTML = '<svg viewBox="0 0 12 12" width="12" height="12"><rect x="2.5" y="4" width="5" height="5" fill="none" stroke="currentColor" stroke-width="1"/><path d="M4.5 4V2.5h5v5H8" fill="none" stroke="currentColor" stroke-width="1"/></svg>';
    btn.title = '还原';
  } else {
    app.classList.remove('maximized');
    if (_savedAppStyle) {
      app.style.width = _savedAppStyle.width;
      app.style.height = _savedAppStyle.height;
      app.style.left = _savedAppStyle.left;
      app.style.top = _savedAppStyle.top;
      app.style.margin = _savedAppStyle.margin;
    } else {
      app.style.width = '';
      app.style.height = '';
      app.style.left = '';
      app.style.top = '';
      app.style.margin = '';
    }
    btn.innerHTML = '<svg viewBox="0 0 12 12" width="12" height="12"><rect x="2.5" y="2.5" width="7" height="7" rx="1" fill="none" stroke="currentColor" stroke-width="1"/></svg>';
    btn.title = '缩放';
  }
}

function windowClose() {
  showConfirm('退出应用', '确定要退出 Offline Companion 吗？', function() {
    showToast('应用已退出');
  });
}

// ── 拖拽缩放 ──
var _resizeState = null;
var MIN_W = 720, MIN_H = 480;

function initResizeHandles() {
  document.querySelectorAll('.resize-handle').forEach(function(h) {
    h.addEventListener('mousedown', _resizeStart);
  });
}

function _resizeStart(e) {
  e.preventDefault();
  var dir = e.currentTarget.dataset.dir;
  var app = document.getElementById('appRoot');
  var rect = app.getBoundingClientRect();
  _resizeState = {
    dir: dir,
    startX: e.clientX,
    startY: e.clientY,
    startW: rect.width,
    startH: rect.height,
    startL: rect.left,
    startT: rect.top
  };
  document.body.style.userSelect = 'none';
  document.addEventListener('mousemove', _resizeMove);
  document.addEventListener('mouseup', _resizeEnd);
}

function _resizeMove(e) {
  if (!_resizeState) return;
  e.preventDefault();
  var app = document.getElementById('appRoot');
  var s = _resizeState;
  var dx = e.clientX - s.startX;
  var dy = e.clientY - s.startY;
  var w = s.startW, h = s.startH, l = s.startL, t = s.startT;

  if (s.dir.indexOf('e') >= 0) {
    w = Math.max(MIN_W, s.startW + dx);
  }
  if (s.dir.indexOf('s') >= 0) {
    h = Math.max(MIN_H, s.startH + dy);
  }
  if (s.dir.indexOf('w') >= 0) {
    w = Math.max(MIN_W, s.startW - dx);
    l = s.startL + (s.startW - w);
  }
  if (s.dir.indexOf('n') >= 0) {
    h = Math.max(MIN_H, s.startH - dy);
    t = s.startT + (s.startH - h);
  }

  // clamp to viewport
  var maxW = window.innerWidth - l - 4;
  var maxH = window.innerHeight - t - 4;
  if (w > maxW) w = maxW;
  if (h > maxH) h = maxH;

  app.style.width = w + 'px';
  app.style.height = h + 'px';
  app.style.left = l + 'px';
  app.style.top = t + 'px';
  app.style.margin = '0';
}

function _resizeEnd() {
  _resizeState = null;
  document.body.style.userSelect = '';
  document.removeEventListener('mousemove', _resizeMove);
  document.removeEventListener('mouseup', _resizeEnd);
}

function registerProtoWindowChrome() {
  initResizeHandles();
}

window.addEventListener('load', function() {
  if (window.__shellApiActive) return;
  registerProtoWindowChrome();
});

function togglePlanMode() {
  _planMode = !_planMode;
  var btn = document.getElementById('planToggleBtn');
  if (_planMode) {
    btn.classList.add('active');
    showToast('任务拆解模式已开启 · 复杂任务将自动分解为可审核步骤');
  } else {
    btn.classList.remove('active');
    showToast('任务拆解模式已关闭');
  }
}

function sendMessage() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;
  const time = new Date().toTimeString().slice(0,5);
  const chat = document.getElementById('chatMessages');
  var nextIdx = chat.querySelectorAll('[data-msg-idx]').length;
  var quoteHtml = '';
  if (_pendingQuote) {
    quoteHtml = '<div class="msg-quote"><div class="msg-quote-sender">' + _pendingQuote.sender + '</div>' + escapeHtml(_pendingQuote.text) + '</div>';
    clearReplyPreview();
  }
  chat.insertAdjacentHTML('beforeend', `
    <div class="msg msg-user" data-msg-idx="${nextIdx}">
      <div class="msg-avatar">我</div>
      <div class="msg-bubble">${quoteHtml}${escapeHtml(text)}<span class="meta-time">${time}</span></div>
    </div>`);
  input.value = '';
  autoResize(input);
  updateSendBtn();
  chat.scrollTop = chat.scrollHeight;

  // Plan Mode → 走 PlanOrchestrator 任务拆解
  if (_planMode) {
    showTyping();
    setTimeout(function() {
      hideTyping();
      showToast('Plan Mode 需要后端 API 接线');
    }, 1200);
  } else {
    // 普通聊天 → 直接回复
    showTyping();
    setTimeout(() => {
      hideTyping();
      chat.insertAdjacentHTML('beforeend', `
        <div class="msg msg-bot" data-msg-idx="${nextIdx + 1}">
          <div class="msg-avatar">诺</div>
          <div class="msg-bubble"><p>收到～ 这条消息是原型演示，实际对话会通过 llama-server 本地推理生成回复。</p><span class="meta-time">${time}</span></div>
        </div>`);
      chat.scrollTop = chat.scrollHeight;
    }, 1500);
  }
}

// ════════════════════════════════════════════════════════════════
// PlanNotebook · 任务拆解与执行（模拟后端 PlanOrchestrator）
// ════════════════════════════════════════════════════════════════
//       POST /api/plan/:id/approve | pause | resume | cancel
//       WS /api/plan/:id/events → 实时推送 step 状态变更

var _planIdCounter = 0;
var _activePlans = {};
var _planCardStates = {};

function _ensurePlanCardState(plan) {
  if (!_planCardStates[plan.id]) {
    _planCardStates[plan.id] = {
      phase: 'decomposing',
      collapsed: false,
      userTouched: false,
      autoCollapsed: false,
      startedAt: Date.now(),
      decompMs: Number(plan._decompMs || 0)
    };
  }
  return _planCardStates[plan.id];
}

function _planPhaseFromStatus(status) {
  if (status === 'done') return 'done';
  if (status === 'failed') return 'failed';
  if (status === 'cancelled') return 'cancelled';
  return 'executing';
}

function _setPlanCardPhase(planId, phase) {
  var plan = _activePlans[planId];
  if (!plan) return;
  var state = _ensurePlanCardState(plan);
  var previous = state.phase;
  state.phase = phase;
  if (previous === 'decomposing' && phase !== 'decomposing' && !state.userTouched && !state.autoCollapsed) {
    state.collapsed = true;
    state.autoCollapsed = true;
  }
  _renderPlanCardContents(plan);
}

function _applyPlanCardState(planId) {
  var card = document.getElementById(planId);
  var state = _planCardStates[planId];
  if (!card || !state) return;
  card.classList.toggle('collapsed', state.collapsed);
  card.dataset.phase = state.phase;
  var summary = card.querySelector('.plan-card-header');
  if (summary) summary.setAttribute('aria-expanded', state.collapsed ? 'false' : 'true');
}

function _renderPlanCardContents(plan) {
  var card = document.getElementById(plan.id);
  if (!card) return;
  card.innerHTML = _renderPlanCardInner(plan);
  _applyPlanCardState(plan.id);
}

function _renderPlanFinalReply(planId, reply) {
  var card = document.getElementById(planId);
  var message = card && card.closest('.plan-message');
  var output = message && message.querySelector('.plan-final-reply');
  if (!output && message) {
    var content = message.querySelector('.plan-message-content');
    if (content) {
      output = document.createElement('div');
      output.className = 'plan-final-reply msg-text';
      output.hidden = true;
      content.appendChild(output);
    }
  }
  if (!output) return;
  var resolvedReply = String(reply || '').trim();
  if (!resolvedReply) resolvedReply = _buildPlanFallbackReply(_activePlans[planId]);
  if (!resolvedReply) return;
  output.hidden = false;
  output.textContent = resolvedReply;
  requestAnimationFrame(function() {
    var chat = document.getElementById('chatMessages');
    if (chat) chat.scrollTop = chat.scrollHeight;
  });
}

function _buildPlanFallbackReply(plan) {
  if (!plan || !['done', 'failed', 'cancelled'].includes(plan.status)) return '';
  var steps = Array.isArray(plan.steps) ? plan.steps : [];
  var successful = steps.filter(function(step) {
    return step.status === 'done' || step.status === 'degraded' || step.status === 'skipped';
  }).length;
  var label = plan.status === 'failed' ? '任务执行失败' :
    (plan.status === 'cancelled' ? '任务已取消' : '任务已完成');
  var titles = steps.map(function(step) { return '- ' + String(step.title || step.description || '未命名步骤'); });
  return label + '，' + successful + '/' + steps.length + ' 步骤成功。' +
    (titles.length ? '\n\n执行步骤：\n' + titles.join('\n') : '');
}

function _renderPlanCard(plan, time) {
  var chat = document.getElementById('chatMessages');
  _ensurePlanCardState(plan);
  var html =
    '<div class="msg msg-bot plan-message" data-manual-plan-id="' + escapeHtml(plan.id) + '">' +
      '<div class="msg-avatar">诺</div>' +
      '<div class="plan-message-content">' +
        '<div class="plan-card decomp-card" id="' + plan.id + '">' +
          _renderPlanCardInner(plan) +
        '</div>' +
        '<div class="plan-final-reply msg-text" hidden></div>' +
      '</div>' +
    '</div>';
  chat.insertAdjacentHTML('beforeend', html);
  _applyPlanCardState(plan.id);

  requestAnimationFrame(function() {
    _setPlanCardPhase(plan.id, 'executing');
  });

  // auto-start execution after 1.5s review window
  // user can click "暂停审核" during this window to intervene
  setTimeout(function() {
    if (plan.status === 'pending') {
      plan.status = 'running';
      _updatePlanCard(plan);
      _executeNextStep(plan.id);
    }
  }, 1500);
}

function _renderPlanCardInner(plan) {
  var processed = plan.steps.filter(function(s) {
    return s.status === 'done' || s.status === 'failed' || s.status === 'skipped';
  }).length;
  var total = plan.steps.length;
  var pct = total ? Math.round(processed / total * 100) : 0;
  var state = _ensurePlanCardState(plan);

  var statusLabel = {
    pending: '即将执行',
    running: '执行中',
    paused: '已暂停 · 审核',
    done: '已完成',
    cancelled: '已取消',
    failed: '执行失败'
  }[plan.status] || plan.status;
  if (state.phase === 'decomposing') statusLabel = '拆解中…';
  if (state.phase === 'executing' && plan.status !== 'paused') statusLabel = '执行中 · ' + processed + '/' + total;
  var elapsedLabel = state.decompMs > 0 ? ' · 用时 ' + (state.decompMs / 1000).toFixed(1) + ' 秒' : '';
  var iconHtml = state.phase === 'done' ?
    '<svg viewBox="0 0 24 24"><path d="M5 12l4 4L19 6"/></svg>' :
    state.phase === 'failed' ? '<svg viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17"/></svg>' :
    state.phase === 'cancelled' ? '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m8 8 8 8"/></svg>' :
    '<span class="plan-card-spinner"></span>';

  var html =
    '<button type="button" class="plan-card-header" onclick="_togglePlanCollapse(\'' + plan.id + '\')" aria-expanded="true">' +
      '<div class="plan-card-icon">' + iconHtml + '</div>' +
      '<div class="plan-card-heading">' +
        '<div class="plan-card-title">任务拆解 · ' + total + ' 步</div>' +
        '<div class="plan-card-summary">' + statusLabel + elapsedLabel + '</div>' +
      '</div>' +
      '<span class="plan-card-collapse">' +
        '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>' +
      '</span>' +
    '</button>' +
    '<div class="plan-card-body">' +
      '<div class="plan-card-goal">' + escapeHtml(plan.goal) + '</div>' +
      '<div class="plan-progress-wrap">' +
        '<div class="plan-progress-track"><div class="plan-progress-fill" style="width:' + pct + '%"></div></div>' +
        '<span class="plan-progress-text">' + processed + '/' + total + ' · ' + statusLabel + '</span>' +
      '</div>' +
      '<div class="plan-steps">';

  plan.steps.forEach(function(step) {
    var statusText = { pending: '待执行', running: '执行中', done: '已完成', failed: '失败', consent: '待确认' }[step.status] || step.status;
    var riskIcon = step.risk === 'high' ? ' <span class="plan-step-status" style="background:var(--danger-soft,#fee2e2);color:var(--danger);">高危</span>' :
                   step.risk === 'medium' ? ' <span class="plan-step-status" style="background:var(--warning-soft);color:var(--warning);">中危</span>' : '';

    html +=
      '<div class="plan-step ' + step.status + '" id="' + plan.id + '_step_' + step.id + '">' +
        '<div class="plan-step-num">' + (step.status === 'done' ? '✓' : step.id + 1) + '</div>' +
        '<div class="plan-step-body">' +
          '<div class="plan-step-title">' + escapeHtml(step.title) + riskIcon +
            '<span class="plan-step-status">' + statusText + '</span>' +
          '</div>';

    if (step.deps.length > 0) {
      html += '<div class="plan-step-dep">依赖：Step ' + step.deps.map(function(d) { return d + 1; }).join(', ') + '</div>';
    }
    if (step.result) {
      html += '<div class="plan-step-result">' + escapeHtml(step.result) + '</div>';
    }
    if (step.error) {
      html += '<div class="plan-step-error">' + escapeHtml(step.error) + '</div>';
    }

    html += '</div>' +
      '<div class="plan-step-actions">' +
        '<button class="plan-step-action" title="编辑" onclick="_editPlanStep(\'' + plan.id + '\',' + step.id + ')">' +
          '<svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>' +
        '</button>' +
        '<button class="plan-step-action" title="删除" onclick="_deletePlanStep(\'' + plan.id + '\',' + step.id + ')">' +
          '<svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>' +
        '</button>' +
      '</div>' +
    '</div>';
  });

  html += '</div>';

  // consent bar
  var consentStep = plan.steps.find(function(s) { return s.status === 'consent'; });
  if (consentStep) {
    html +=
      '<div class="plan-consent-bar">' +
        '<svg class="plan-consent-icon" viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>' +
        '<span class="plan-consent-text">Step ' + (consentStep.id + 1) + ' 需要授权：' + escapeHtml(consentStep.title) + '</span>' +
        '<button class="plan-consent-btn" onclick="_approveConsent(\'' + plan.id + '\',' + consentStep.id + ')">授权</button>' +
        '<button class="plan-consent-btn" onclick="_rejectConsent(\'' + plan.id + '\',' + consentStep.id + ')">拒绝</button>' +
      '</div>';
  }

  // action buttons
  html += '<div class="plan-actions">';
  if (plan.status === 'pending') {
    // brief review window — auto-starts, but user can pause to review
    html += '<span style="font-size:12px;color:var(--text-tertiary);padding:4px 0;">即将自动执行…</span>';
    html += '<button class="plan-action-btn" onclick="_pausePlan(\'' + plan.id + '\')" title="暂停审核">' +
      '<svg viewBox="0 0 24 24" stroke-linecap="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>暂停审核</button>';
    html += '<button class="plan-action-btn danger" onclick="_cancelPlan(\'' + plan.id + '\')">取消</button>';
    html += '<button class="plan-action-btn" onclick="_addPlanStep(\'' + plan.id + '\')">' +
      '<svg viewBox="0 0 24 24" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>添加步骤</button>';
  } else if (plan.status === 'running') {
    html += '<button class="plan-action-btn" onclick="_pausePlan(\'' + plan.id + '\')">' +
      '<svg viewBox="0 0 24 24" stroke-linecap="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>暂停</button>';
    html += '<button class="plan-action-btn danger" onclick="_cancelPlan(\'' + plan.id + '\')">取消</button>';
    html += '<button class="plan-action-btn" onclick="_addPlanStep(\'' + plan.id + '\')">' +
      '<svg viewBox="0 0 24 24" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>添加步骤</button>';
  } else if (plan.status === 'paused') {
    html += '<button class="plan-action-btn primary" onclick="_resumePlan(\'' + plan.id + '\')">' +
      '<svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>继续执行</button>';
    html += '<button class="plan-action-btn" onclick="_addPlanStep(\'' + plan.id + '\')">' +
      '<svg viewBox="0 0 24 24" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>添加步骤</button>';
    html += '<button class="plan-action-btn danger" onclick="_cancelPlan(\'' + plan.id + '\')">取消</button>';
  } else {
    html += '<span style="font-size:12px;color:var(--text-tertiary);padding:4px 0;">计划已结束</span>';
    if (plan.candidate_sample_id) {
      html += '<button class="plan-action-btn" onclick="openDecompSampleLibrary(\'' + plan.candidate_sample_id + '\')">查看范例</button>';
    } else {
      html += '<button class="plan-action-btn" onclick="savePlanAsDecompSample(\'' + plan.id + '\')">存为范例</button>';
    }
  }
  html += '</div>';

  return html;
}

function _togglePlanCollapse(planId) {
  var plan = _activePlans[planId];
  if (!plan) return;
  var state = _ensurePlanCardState(plan);
  state.userTouched = true;
  state.collapsed = !state.collapsed;
  _applyPlanCardState(planId);
}

function _updatePlanCard(plan) {
  var state = _ensurePlanCardState(plan);
  state.phase = _planPhaseFromStatus(plan.status);
  _renderPlanCardContents(plan);
  document.getElementById('chatMessages').scrollTop = document.getElementById('chatMessages').scrollHeight;
}

function _approveConsent(planId, stepId) {
  var plan = _activePlans[planId];
  if (!plan) return;
  var step = plan.steps[stepId];
  if (step) step.status = 'pending';
  _updatePlanCard(plan);
  showToast('已授权，继续执行');
  _executeNextStep(planId);
}

function _pausePlan(planId) {
  var plan = _activePlans[planId];
  if (!plan) return;
  if (plan.status !== 'running' && plan.status !== 'pending') return;
  plan.status = 'paused';
  _updatePlanCard(plan);
  showToast('已暂停，可审核或调整步骤');
}

function _resumePlan(planId) {
  var plan = _activePlans[planId];
  if (!plan) return;
  plan.status = 'running';
  _updatePlanCard(plan);
  showToast('计划已恢复');
  _executeNextStep(planId);
}

function _cancelPlan(planId) {
  var plan = _activePlans[planId];
  if (!plan) return;
  plan.status = 'cancelled';
  plan.steps.forEach(function(s) {
    if (s.status === 'running' || s.status === 'pending' || s.status === 'consent') {
      s.status = 'failed';
      s.error = '计划已取消';
    }
  });
  _updatePlanCard(plan);
  showToast('计划已取消');
}

function _addPlanStep(planId) {
  var plan = _activePlans[planId];
  if (!plan) return;
  var title = window.prompt('输入新步骤描述：');
  if (!title) return;
  var newId = plan.steps.length;
  plan.steps.push({
    id: newId,
    title: title,
    deps: [newId - 1],
    risk: 'low',
    status: 'pending',
    result: null,
    error: null
  });
  _updatePlanCard(plan);
  showToast('已添加步骤');
}

function _editPlanStep(planId, stepId) {
  var plan = _activePlans[planId];
  if (!plan) return;
  var step = plan.steps[stepId];
  if (!step) return;
  var newTitle = window.prompt('编辑步骤描述：', step.title);
  if (newTitle && newTitle !== step.title) {
    step.title = newTitle;
    _updatePlanCard(plan);
    showToast('步骤已更新');
  }
}

function _deletePlanStep(planId, stepId) {
  var plan = _activePlans[planId];
  if (!plan) return;
  if (plan.status === 'running') {
    showToast('执行中无法删除步骤，请先暂停');
    return;
  }
  plan.steps = plan.steps.filter(function(s) { return s.id !== stepId; });
  _updatePlanCard(plan);
  showToast('步骤已删除');
}

function showTyping() {
  const t = document.getElementById('typingMsg');
  const chat = document.getElementById('chatMessages');
  t.style.display = 'flex';
  chat.scrollTop = chat.scrollHeight;
}
function hideTyping() { document.getElementById('typingMsg').style.display = 'none'; }

// ════════════════════════════════════════════════════════════════
// 消息右键菜单（飞书式）
// ════════════════════════════════════════════════════════════════
var _ctxTargetMsg = null;

function initContextMenu() {
  var menu = document.getElementById('msgContextMenu');
  var emojiBar = document.getElementById('emojiBar');

  // right-click on bot messages
  document.getElementById('chatMessages').addEventListener('contextmenu', function(e) {
    var bubble = e.target.closest('.msg-bot .msg-bubble');
    if (!bubble) return;
    e.preventDefault();
    _ctxTargetMsg = bubble;
    menu.style.display = 'block';
    menu.style.left = Math.min(e.clientX, window.innerWidth - 180) + 'px';
    menu.style.top = Math.min(e.clientY, window.innerHeight - 220) + 'px';
    emojiBar.style.display = 'none';
  });

  // hover on bot messages → show emoji bar
  document.getElementById('chatMessages').addEventListener('mouseover', function(e) {
    var bubble = e.target.closest('.msg-bot .msg-bubble');
    if (!bubble) { emojiBar.style.display = 'none'; return; }
    var rect = bubble.getBoundingClientRect();
    emojiBar.style.display = 'flex';
    emojiBar.style.left = Math.min(rect.right - 150, window.innerWidth - 160) + 'px';
    emojiBar.style.top = (rect.top - 34) + 'px';
    _ctxTargetMsg = bubble;
  });

  document.getElementById('chatMessages').addEventListener('mouseleave', function() {
    setTimeout(function() {
      if (!emojiBar.matches(':hover')) emojiBar.style.display = 'none';
    }, 200);
  });

  emojiBar.addEventListener('mouseleave', function() {
    emojiBar.style.display = 'none';
  });

  // click outside to close
  document.addEventListener('click', function() {
    menu.style.display = 'none';
  });
  document.addEventListener('contextmenu', function(e) {
    if (!e.target.closest('.msg-bot .msg-bubble')) {
      menu.style.display = 'none';
    }
  });
}

function _getMsgText() {
  if (!_ctxTargetMsg) return '';
  return _ctxTargetMsg.textContent.replace(/\d{2}:\d{2}$/, '').trim();
}

function ctxReply() {
  var text = _getMsgText();
  if (!text) return;
  var input = document.getElementById('chatInput');
  var preview = text.length > 50 ? text.slice(0, 50) + '…' : text;
  input.value = '';
  input.focus();
  // set reply state — next sendMessage will include quote
  _pendingQuote = { sender: '小诺', text: preview };
  _showReplyPreview();
  document.getElementById('msgContextMenu').style.display = 'none';
}

function ctxCopy() {
  var text = _getMsgText();
  if (!text) return;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text);
  } else {
    var ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove();
  }
  showToast('已复制到剪贴板');
  document.getElementById('msgContextMenu').style.display = 'none';
}

function ctxFlagError() {
  document.getElementById('msgContextMenu').style.display = 'none';
  if (!_ctxTargetMsg) return;
  var msg = _ctxTargetMsg.closest('.msg');
  if (msg) {
    msg.style.opacity = '0.6';
    var bubble = msg.querySelector('.msg-bubble');
    bubble.style.borderLeft = '3px solid var(--warning)';
    bubble.style.borderRadius = '0 8px 8px 0';
  }
  if (_improvePlanEnabled && _privacyMode === 'CLOUD') {
    showToast('已标记为有误 · 反馈已匿名上传');
  } else {
    showToast('已标记为有误 · 本地记录（改进计划未开启，不上传）');
  }
}

function addReaction(btn, emoji) {
  if (!_ctxTargetMsg) return;
  var bar = document.getElementById('emojiBar');
  bar.style.display = 'none';

  // find or create reactions container
  var msg = _ctxTargetMsg.closest('.msg');
  var bubble = _ctxTargetMsg;
  var reactionsEl = bubble.querySelector('.msg-reactions');
  if (!reactionsEl) {
    reactionsEl = document.createElement('div');
    reactionsEl.className = 'msg-reactions';
    bubble.appendChild(reactionsEl);
  }

  // check if this emoji already exists — toggle off if clicked again
  var existing = reactionsEl.querySelectorAll('.msg-reaction');
  var found = false;
  existing.forEach(function(r) {
    if (r.dataset.emoji === emoji) {
      r.remove();
      found = true;
    }
  });

  if (!found) {
    var reaction = document.createElement('span');
    reaction.className = 'msg-reaction';
    reaction.dataset.emoji = emoji;
    reaction.innerHTML = '<span>' + emoji + '</span>';
    reactionsEl.appendChild(reaction);
  }
}

function ctxRegenerate() {
  document.getElementById('msgContextMenu').style.display = 'none';
  if (!_ctxTargetMsg) return;
  var msg = _ctxTargetMsg.closest('.msg');
  if (msg) {
    msg.querySelector('.msg-bubble').style.opacity = '0.5';
    showTyping();
    setTimeout(function() {
      hideTyping();
      msg.querySelector('.msg-bubble').style.opacity = '1';
      msg.querySelector('.msg-bubble').innerHTML =
        '<p>（已重新生成）收到～ 这是重新生成的回复，实际会通过 llama-server 再次推理。</p>' +
        '<span class="meta-time">' + new Date().toTimeString().slice(0, 5) + '</span>';
      showToast('已重新生成回复');
    }, 1500);
  }
}

function ctxSaveMemory() {
  document.getElementById('msgContextMenu').style.display = 'none';
  if (!_ctxTargetMsg) return;
  var text = _getMsgText();
  if (!text) return;
  showToast('已存入记忆 · ' + (text.length > 20 ? text.slice(0, 20) + '…' : text));
}

// 回复预览条
var _pendingQuote = null;

function _showReplyPreview() {
  var existing = document.getElementById('replyPreview');
  if (existing) existing.remove();

  var bar = document.createElement('div');
  bar.id = 'replyPreview';
  bar.className = 'reply-preview';
  bar.innerHTML =
    '<div class="reply-preview-text">' +
      '<span class="msg-quote-sender">' + _pendingQuote.sender + '</span>' +
      '<span>' + escapeHtml(_pendingQuote.text) + '</span>' +
    '</div>' +
    '<button class="reply-preview-close" onclick="clearReplyPreview()">' +
      '<svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>' +
    '</button>';

  var inputArea = document.querySelector('.chat-input');
  inputArea.parentNode.insertBefore(bar, inputArea);
}

function clearReplyPreview() {
  _pendingQuote = null;
  var bar = document.getElementById('replyPreview');
  if (bar) bar.remove();
}

document.addEventListener('DOMContentLoaded', initContextMenu);

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ════════════════════════════════════════════════════════════════
// 记忆侧栏 · DeepSeek 式对话摘要
// ════════════════════════════════════════════════════════════════
var _memoryPoints = [
  {
    msgIdx: 0,
    title: '\u6574\u7406\u6458\u8981',
    badge: '\u8bb0\u5fc6',
    summary: '\u8fd9\u91cc\u4f1a\u663e\u793a\u4ece\u5bf9\u8bdd\u4e2d\u63d0\u53d6\u7684\u8bb0\u5fc6\u6458\u8981\u3002',
    original: '\u7b49\u5f85\u540e\u7aef\u8bb0\u5fc6\u52a0\u8f7d\u3002',
    turn: 1,
    time: '-'
  },
  {
    msgIdx: 1,
    title: '\u6574\u7406\u5907\u5fd8',
    badge: '\u8bb0\u5fc6',
    summary: '\u771f\u5b9e\u6570\u636e\u52a0\u8f7d\u540e\u4f1a\u81ea\u52a8\u66ff\u6362\u8fd9\u4e9b\u5360\u4f4d\u5185\u5bb9\u3002',
    original: '\u7b49\u5f85\u540e\u7aef\u8bb0\u5fc6\u52a0\u8f7d\u3002',
    turn: 2,
    time: '-'
  }
];

function initMemoryPanel() {
  var panel = document.getElementById('memoryPanel');
  if (!panel) return;

  var html = '<div class="memory-panel-header">\u5bf9\u8bdd\u8bb0\u5fc6</div>';

  _memoryPoints.forEach(function(mp) {
    html +=
      '<div class="mem-item" data-msg-idx="' + mp.msgIdx + '" onclick="scrollToMessage(' + mp.msgIdx + ')">' +
        '<div class="mem-title">' + escapeHtml(mp.title) + '</div>' +
        '<button class="mem-del" onclick="event.stopPropagation(); deleteMemoryPoint(' + mp.msgIdx + ')" title="\u5220\u9664">' +
          '<svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"><path d="M5 12h14"/></svg>' +
        '</button>' +
        '<div class="mem-expand">' +
          '<div class="mem-label">\u6458\u8981</div>' +
          '<div class="mem-summary">' + escapeHtml(mp.summary) + '</div>' +
          '<div class="mem-label">\u539f\u59cb\u6d88\u606f</div>' +
          '<div class="mem-original">' + escapeHtml(mp.original) + '</div>' +
          '<div class="mem-meta">' +
            '<span>\u7b2c ' + mp.turn + ' \u8f6e\u5bf9\u8bdd</span>' +
            '<span class="mem-meta-dot"></span>' +
            '<span>' + escapeHtml(mp.time) + '</span>' +
          '</div>' +
        '</div>' +
      '</div>';
  });

  panel.innerHTML = html;
  var badge = document.getElementById('memoryCount');
  if (badge) badge.textContent = _memoryPoints.length;

  var trigger = document.getElementById('memoryTrigger');
  if (!trigger || trigger.dataset.memoryHoverBound === '1') return;
  trigger.dataset.memoryHoverBound = '1';
  var hoverTimer = null;

  function openPanel() {
    clearTimeout(hoverTimer);
    panel.classList.add('open');
    trigger.classList.add('active');
  }

  function scheduleClose() {
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(function() {
      panel.classList.remove('open');
      trigger.classList.remove('active');
    }, 300);
  }

  trigger.addEventListener('mouseenter', openPanel);
  trigger.addEventListener('mouseleave', scheduleClose);
  panel.addEventListener('mouseenter', openPanel);
  panel.addEventListener('mouseleave', scheduleClose);
}

function deleteMemoryPoint(msgIdx) {
  _memoryPoints = _memoryPoints.filter(function(mp) { return mp.msgIdx !== msgIdx; });
  initMemoryPanel();
  showToast('已删除记忆点');
}

function scrollToMessage(msgIdx) {
  var msg = document.getElementById('chatMessages').querySelector('[data-msg-idx="' + msgIdx + '"]');
  if (!msg) return;
  msg.scrollIntoView({ behavior: 'smooth', block: 'center' });

  // flash highlight
  var bubble = msg.querySelector('.msg-bubble');
  if (bubble) {
    bubble.style.transition = 'box-shadow 0.3s';
    bubble.style.boxShadow = '0 0 0 3px var(--accent)';
    setTimeout(function() { bubble.style.boxShadow = ''; }, 1200);
  }

  // highlight the item
  document.querySelectorAll('.mem-item').forEach(function(d) { d.classList.remove('active'); });
  var item = document.querySelector('.mem-item[data-msg-idx="' + msgIdx + '"]');
  if (item) item.classList.add('active');
}

// init on DOM ready
document.addEventListener('DOMContentLoaded', initMemoryPanel);

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.opacity = '1'; t.style.transform = 'translate(-50%,-50%) scale(1)';
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.style.opacity = '0'; t.style.transform = 'translate(-50%,-50%) scale(0.95)'; }, 2000);
}

var _memFilter = '全部';
var _memSearch = '';
var _memDateFrom = '';
var _memDateTo = '';
var _memDateCustomized = false;
var _memDefaultDateKey = '';

function formatLocalDate(date) {
  function pad(value) { return String(value).padStart(2, '0'); }
  return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate());
}

function defaultMemoryDateRange(referenceDate) {
  var year = referenceDate.getFullYear() - 1;
  var month = referenceDate.getMonth();
  var day = Math.min(referenceDate.getDate(), new Date(year, month + 1, 0).getDate());
  return {
    from: formatLocalDate(new Date(year, month, day)),
    to: formatLocalDate(referenceDate)
  };
}

function refreshDefaultMemoryDateRange() {
  if (_memDateCustomized) return;
  var range = defaultMemoryDateRange(new Date());
  var key = range.from + ':' + range.to;
  if (_memDefaultDateKey === key) return;
  _memDefaultDateKey = key;
  _memDateFrom = range.from;
  _memDateTo = range.to;
  var from = document.getElementById('dateFrom');
  var to = document.getElementById('dateTo');
  if (from) from.value = _memDateFrom;
  if (to) to.value = _memDateTo;
  updateDateTexts();
  var clear = document.getElementById('dateClear');
  if (clear) clear.style.display = 'flex';
  applyMemoryFilter();
}

document.addEventListener('DOMContentLoaded', refreshDefaultMemoryDateRange);
window.addEventListener('focus', refreshDefaultMemoryDateRange);

function updateDateTexts() {
  var from = document.getElementById('dateFrom');
  var to = document.getElementById('dateTo');
  var fromText = document.getElementById('dateFromText');
  var toText = document.getElementById('dateToText');
  if (fromText) fromText.textContent = from && from.value ? from.value : '开始日期';
  if (toText) toText.textContent = to && to.value ? to.value : '结束日期';
}

function toggleFilterDropdown() {
  var menu = document.getElementById('filterDropdownMenu');
  menu.classList.toggle('open');
}

// close dropdown when clicking outside
document.addEventListener('click', function(e) {
  var dropdown = document.getElementById('filterDropdown');
  var menu = document.getElementById('filterDropdownMenu');
  if (dropdown && menu && !dropdown.contains(e.target)) {
    menu.classList.remove('open');
  }
});

function onMemorySearch(query) {
  _memSearch = query.trim().toLowerCase();
  document.getElementById('searchClear').style.display = _memSearch ? 'flex' : 'none';
  applyMemoryFilter();
}

function clearMemorySearch() {
  var input = document.getElementById('memorySearch');
  input.value = '';
  _memSearch = '';
  document.getElementById('searchClear').style.display = 'none';
  applyMemoryFilter();
  input.focus();
}

function filterMemoryType(el, type) {
  document.querySelectorAll('.filter-dropdown-item').forEach(function(c) { c.classList.remove('active'); });
  el.classList.add('active');
  _memFilter = type;
  document.getElementById('filterDropdownLabel').textContent = type;
  document.getElementById('filterDropdownMenu').classList.remove('open');
  applyMemoryFilter();
}

function onDateChange() {
  _memDateCustomized = true;
  _memDateFrom = document.getElementById('dateFrom').value || '';
  _memDateTo = document.getElementById('dateTo').value || '';
  updateDateTexts();
  document.getElementById('dateClear').style.display = (_memDateFrom || _memDateTo) ? 'flex' : 'none';
  applyMemoryFilter();
}

function clearDateRange() {
  _memDateCustomized = true;
  document.getElementById('dateFrom').value = '';
  document.getElementById('dateTo').value = '';
  _memDateFrom = '';
  _memDateTo = '';
  updateDateTexts();
  document.getElementById('dateClear').style.display = 'none';
  applyMemoryFilter();
}

function applyMemoryFilter() {
  var cards = document.querySelectorAll('#memoryCardList .memory-card');
  var visible = 0;

  cards.forEach(function(card) {
    var cardType = card.dataset.type || '';
    var content = (card.querySelector('.memory-content') || {}).textContent || '';
    var tags = [];
    try { tags = JSON.parse(card.dataset.tags || '[]'); } catch (e) {}
    var source = card.dataset.source || '';
    var created = (card.dataset.created || '').slice(0, 10); // YYYY-MM-DD

    // type filter
    var typeMatch = (_memFilter === '全部') || (cardType === _memFilter);

    // search: match content, tags, source, type
    var searchMatch = true;
    if (_memSearch) {
      var haystack = (content + ' ' + tags.join(' ') + ' ' + source + ' ' + cardType).toLowerCase();
      searchMatch = haystack.includes(_memSearch);
    }

    // date range filter
    var dateMatch = true;
    if (_memDateFrom && created < _memDateFrom) dateMatch = false;
    if (_memDateTo && created > _memDateTo) dateMatch = false;

    var show = typeMatch && searchMatch && dateMatch;
    card.style.display = show ? '' : 'none';
    if (show) visible++;
  });

  // empty state
  var existingEmpty = document.getElementById('memoryEmptyState');
  if (visible === 0) {
    if (!existingEmpty) {
      var emptyDiv = document.createElement('div');
      emptyDiv.id = 'memoryEmptyState';
      emptyDiv.className = 'memory-empty';
      emptyDiv.innerHTML =
        '<div class="memory-empty-icon">🔍</div>' +
        '<div class="memory-empty-text">没有匹配的记忆</div>';
      document.getElementById('memoryCardList').appendChild(emptyDiv);
    }
  } else if (existingEmpty) {
    existingEmpty.remove();
  }

  // update count in header
  var subtitle = document.querySelector('[data-view="memory"] .view-subtitle');
  if (subtitle) {
    var total = cards.length;
    var filtering = _memSearch || _memFilter !== '全部' || _memDateFrom || _memDateTo;
    subtitle.textContent = visible + ' 条' + (filtering ? ' / ' + total + ' 条' : '');
  }
}

// ════════════════════════════════════════════════════════════════
// 人格数据注册表
// ════════════════════════════════════════════════════════════════
var _personaRegistry = {};

var _oceanLabels = ['开放性', '尽责性', '外向性', '宜人性', '神经质'];

function selectPersona(el, name) {
  document.querySelectorAll('.persona-chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');

  renderPersonaDetail(name);

  showToast('已切换到人格 · ' + name);
}

function renderPersonaDetail(name) {
  var p = _personaRegistry[name];
  if (!p) return;
  var card = document.getElementById('personaDetailCard');
  var labels = ['开放性', '尽责性', '外向性', '宜人性', '神经质'];
  card.innerHTML =
    '<div class="persona-card-header">' +
      '<div class="persona-avatar-lg">' + p.avatar + '</div>' +
      '<div class="persona-meta">' +
        '<h2>' + name + '</h2>' +
        '<p>' + p.desc + '</p>' +
      '</div>' +
      '<div class="persona-card-actions">' +
        '<button class="icon-btn" id="personaEditBtn" onclick="togglePersonaEdit()" title="编辑">' +
          '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>' +
        '</button>' +
        '<button class="icon-btn del" onclick="deletePersona()" title="删除">' +
          '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>' +
        '</button>' +
      '</div>' +
    '</div>' +
    '<div class="ocean-section">' +
      '<h3>OCEAN 人格向量</h3>' +
      p.ocean.map(function(val, i) {
        return '<div class="ocean-bar">' +
          '<span class="ocean-label">' + labels[i] + '</span>' +
          '<div class="ocean-track"><div class="ocean-fill" style="width:' + val + '%"></div></div>' +
          '<span class="ocean-value">' + val + '</span>' +
        '</div>';
      }).join('') +
    '</div>' +
    '<div class="ocean-section">' +
      '<h3>性格标签</h3>' +
      '<div class="persona-traits">' +
        p.traits.map(function(t) { return '<span class="trait-tag">' + t + '</span>'; }).join('') +
      '</div>' +
    '</div>' +
    '<div class="ocean-section">' +
      '<h3>人设锚语</h3>' +
      '<div class="persona-anchor">' + p.anchor + '</div>' +
    '</div>';
}

var _personaEditMode = false;

function togglePersonaEdit() {
  if (_personaEditMode) { savePersonaEdit(); return; }

  var name = getActivePersonaName();
  if (!name || !_personaRegistry[name]) return;
  var p = _personaRegistry[name];
  var card = document.getElementById('personaDetailCard');
  _personaEditMode = true;

  // avatar → keep as is (not editable inline)

  // name → input
  var h2 = card.querySelector('.persona-meta h2');
  h2.outerHTML = '<input class="persona-edit-name" id="peName" value="' + name + '" maxlength="6">';

  // desc → textarea
  var descP = card.querySelector('.persona-meta p');
  descP.outerHTML = '<textarea class="persona-edit-desc" id="peDesc">' + p.desc + '</textarea>';

  // OCEAN → number inputs
  var bars = card.querySelectorAll('.ocean-bar');
  p.ocean.forEach(function(val, i) {
    var valEl = bars[i].querySelector('.ocean-value');
    valEl.outerHTML = '<input type="number" class="ocean-edit-input ocean-value" min="0" max="100" value="' + val + '" data-idx="' + i + '" oninput="onOceanEdit(this)">';
  });

  // traits → chip editor
  var traitsBox = card.querySelector('.persona-traits');
  traitsBox.className = 'persona-traits tag-editor';
  traitsBox.innerHTML = '';
  p.traits.forEach(function(t) { _addTagChip(traitsBox, t); });
  _appendTagInput(traitsBox);

  // anchor → textarea
  var anchor = card.querySelector('.persona-anchor');
  anchor.outerHTML = '<textarea class="persona-edit-anchor persona-anchor" id="peAnchor">' + p.anchor + '</textarea>';

  // button → save
  var btn = document.getElementById('personaEditBtn');
  btn.title = '保存';
  btn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>';
}

function onOceanEdit(input) {
  var idx = parseInt(input.dataset.idx);
  var val = parseInt(input.value);
  if (isNaN(val)) val = 0;
  val = Math.max(0, Math.min(100, val));
  input.value = val;
  // update fill width
  var bar = input.closest('.ocean-bar');
  var fill = bar.querySelector('.ocean-fill');
  if (fill) fill.style.width = val + '%';
}

async function savePersonaEdit() {
  var oldName = getActivePersonaName();
  if (!oldName || !_personaRegistry[oldName]) return;
  var personaId = getActivePersonaId();

  var newName = document.getElementById('peName').value.trim() || oldName;
  var desc = document.getElementById('peDesc').value.trim();
  var anchor = document.getElementById('peAnchor').value.trim();

  // collect OCEAN values
  var ocean = [];
  document.querySelectorAll('.ocean-edit-input').forEach(function(inp) {
    var v = parseInt(inp.value);
    if (isNaN(v)) v = 50;
    ocean.push(Math.max(0, Math.min(100, v)));
  });

  // collect traits from chips
  var traits = [];
  document.querySelectorAll('.persona-traits .tag-edit-chip span').forEach(function(s) {
    traits.push(s.textContent);
  });

  if (personaId && typeof updatePersonaApi === 'function') {
    try {
      await updatePersonaApi(personaId, {
        name: newName,
        desc: desc,
        ocean: ocean,
        traits: traits,
        anchor: anchor
      });
      _personaEditMode = false;
      var updatedChip = document.querySelector('.persona-chip[data-persona-id="' + personaId + '"]');
      if (updatedChip) updatedChip.click();
      showToast('Persona saved');
    } catch (error) {
      showToast('Persona save failed: ' + error.message);
    }
    return;
  }

  // update registry (handle name change)
  if (newName !== oldName) {
    if (_personaRegistry[newName]) {
      showToast('人格名称已存在');
      return;
    }
    _personaRegistry[newName] = _personaRegistry[oldName];
    delete _personaRegistry[oldName];
    // update chip text
    var chip = document.querySelector('.persona-chip.active');
    if (chip) {
      chip.querySelector('span:last-child').textContent = newName;
      chip.setAttribute('onclick', "selectPersona(this, '" + newName + "')");
    }
  }
  _personaRegistry[newName].desc = desc;
  _personaRegistry[newName].ocean = ocean;
  _personaRegistry[newName].traits = traits;
  _personaRegistry[newName].anchor = anchor;

  _personaEditMode = false;

  // re-render card
  renderPersonaDetail(newName);
  showToast('人格已保存');
}

// ════════════════════════════════════════════════════════════════
// 通用确认弹窗
// ════════════════════════════════════════════════════════════════
var _confirmCallback = null;
var _confirmCancelCallback = null;

function showConfirm(title, msg, onConfirm, onCancel, variant) {
  document.getElementById('confirmTitle').textContent = title;
  document.getElementById('confirmMsg').textContent = msg;
  _confirmCallback = onConfirm;
  _confirmCancelCallback = onCancel;
  var okBtn = document.getElementById('confirmOkBtn');
  okBtn.onclick = function() {
    var cb = _confirmCallback;
    closeConfirm(false);
    if (cb) cb();
  };
  var cancelBtn = document.querySelector('#confirmOverlay .confirm-cancel');
  if (cancelBtn) {
    cancelBtn.onclick = function() {
      closeConfirm(true);
    };
  }
  // variant: 'success' = green, default = red (danger)
  okBtn.classList.toggle('success', variant === 'success');
  document.getElementById('confirmOverlay').classList.add('open');
}

function closeConfirm(triggerCancel) {
  var cb = triggerCancel ? _confirmCancelCallback : null;
  document.getElementById('confirmOverlay').classList.remove('open');
  _confirmCallback = null;
  _confirmCancelCallback = null;
  if (cb) cb();
}

function getActivePersonaName() {
  var active = document.querySelector('.persona-chip.active');
  if (!active) return null;
  return active.querySelector('span:last-child').textContent.trim();
}

function getActivePersonaId() {
  var active = document.querySelector('.persona-chip.active');
  return active ? active.getAttribute('data-persona-id') : null;
}

function deletePersona() {
  var chips = document.querySelectorAll('.persona-chip');
  if (chips.length <= 1) {
    showToast('至少需保留一个人格');
    return;
  }

  var name = getActivePersonaName();
  if (!name) return;

  showConfirm('删除人格', '确定要删除人格「' + name + '」吗？此操作不可撤销。', async function() {
    var personaId = getActivePersonaId();
    if (personaId && typeof deletePersonaApi === 'function') {
      try {
        await deletePersonaApi(personaId);
        var firstApiChip = document.querySelector('.persona-chip');
        if (firstApiChip) firstApiChip.click();
        showToast('Persona deleted · ' + name);
      } catch (error) {
        showToast('Persona delete failed: ' + error.message);
      }
      return;
    }
    delete _personaRegistry[name];
    var activeChip = document.querySelector('.persona-chip.active');
    if (activeChip) activeChip.remove();
    var firstChip = document.querySelector('.persona-chip');
    if (firstChip) firstChip.click();
    showToast('已删除人格 · ' + name);
  });
}

// ════════════════════════════════════════════════════════════════
// 新建人格 · 交互式五维雷达图
// ════════════════════════════════════════════════════════════════
var _radarCfg = {
  cx: 140, cy: 140, R: 95,
  labels: ['开放性', '尽责性', '外向性', '宜人性', '神经质'],
  // 5 axes, starting from top (-90°), clockwise every 72°
  angles: [-90, -18, 54, 126, 198].map(function(d) { return d * Math.PI / 180; })
};
var _radarValues = [50, 50, 50, 50, 50]; // default OCEAN
var _radarDragIdx = -1;

function _radarPos(i, val) {
  var r = (val / 100) * _radarCfg.R;
  return {
    x: _radarCfg.cx + r * Math.cos(_radarCfg.angles[i]),
    y: _radarCfg.cy + r * Math.sin(_radarCfg.angles[i])
  };
}

function _renderRadar() {
  var svg = document.getElementById('radarSvg');
  if (!svg) return;
  var cx = _radarCfg.cx, cy = _radarCfg.cy, R = _radarCfg.R;
  var parts = [];

  // grid pentagons at 20/40/60/80/100
  for (var g = 5; g >= 1; g--) {
    var pts = [];
    for (var i = 0; i < 5; i++) {
      var r = (g / 5) * R;
      var x = cx + r * Math.cos(_radarCfg.angles[i]);
      var y = cy + r * Math.sin(_radarCfg.angles[i]);
      pts.push(x.toFixed(1) + ',' + y.toFixed(1));
    }
    parts.push('<polygon class="radar-grid' + (g === 5 ? ' outer' : '') + '" points="' + pts.join(' ') + '"/>');
  }

  // axes
  for (var i = 0; i < 5; i++) {
    var ex = cx + R * Math.cos(_radarCfg.angles[i]);
    var ey = cy + R * Math.sin(_radarCfg.angles[i]);
    parts.push('<line class="radar-axis" x1="' + cx + '" y1="' + cy + '" x2="' + ex.toFixed(1) + '" y2="' + ey.toFixed(1) + '"/>');
  }

  // filled polygon
  var polyPts = [];
  for (var i = 0; i < 5; i++) {
    var p = _radarPos(i, _radarValues[i]);
    polyPts.push(p.x.toFixed(1) + ',' + p.y.toFixed(1));
  }
  parts.push('<polygon class="radar-polygon" points="' + polyPts.join(' ') + '"/>');

  // vertices
  for (var i = 0; i < 5; i++) {
    var p = _radarPos(i, _radarValues[i]);
    parts.push(
      '<circle class="radar-vertex" cx="' + p.x.toFixed(1) + '" cy="' + p.y.toFixed(1) +
      '" data-idx="' + i + '"/>'
    );
  }

  // labels + values
  for (var i = 0; i < 5; i++) {
    var lr = R + 22;
    var lx = cx + lr * Math.cos(_radarCfg.angles[i]);
    var ly = cy + lr * Math.sin(_radarCfg.angles[i]);
    parts.push(
      '<text class="radar-label" x="' + lx.toFixed(1) + '" y="' + (ly - 2).toFixed(1) + '" dy="0.35em">' + _radarCfg.labels[i] + '</text>'
    );
    parts.push(
      '<text class="radar-label-val" x="' + lx.toFixed(1) + '" y="' + (ly + 11).toFixed(1) + '" dy="0.35em">' + _radarValues[i] + '</text>'
    );
  }

  svg.innerHTML = parts.join('');

  // sync input values
  _syncRadarInputs();

  // attach drag handlers
  svg.querySelectorAll('.radar-vertex').forEach(function(v) {
    v.addEventListener('mousedown', _radarDragStart);
    v.addEventListener('touchstart', _radarDragStart, { passive: false });
    v.addEventListener('dblclick', function() {
      var idx = parseInt(v.dataset.idx);
      _radarValues[idx] = 50;
      _renderRadar();
      _updateTraitsPreview();
    });
  });
}

function _syncRadarInputs() {
  var container = document.getElementById('radarInputs');
  if (!container) return;
  // build once, then just update values
  if (container.children.length === 0) {
    var html = [];
    for (var i = 0; i < 5; i++) {
      html.push(
        '<div class="radar-input-item">' +
        '<label>' + _radarCfg.labels[i] + '</label>' +
        '<input type="number" min="0" max="100" value="50" data-idx="' + i + '" id="radarInput' + i + '">' +
        '</div>'
      );
    }
    container.innerHTML = html.join('');
    // wire up input listeners
    container.querySelectorAll('input').forEach(function(inp) {
      inp.addEventListener('input', function() {
        var idx = parseInt(inp.dataset.idx);
        var v = parseInt(inp.value);
        if (isNaN(v)) v = 0;
        v = Math.max(0, Math.min(100, v));
        _radarValues[idx] = v;
        // update only the polygon + vertex + value text (not the inputs)
        _renderRadarPolygon();
        _updateTraitsPreview();
      });
      inp.addEventListener('blur', function() {
        var idx = parseInt(inp.dataset.idx);
        inp.value = _radarValues[idx];
      });
    });
  }
  // update current values
  for (var i = 0; i < 5; i++) {
    var el = document.getElementById('radarInput' + i);
    if (el && document.activeElement !== el) el.value = _radarValues[i];
  }
}

// lightweight re-render of polygon/vertices/values without rebuilding inputs
function _renderRadarPolygon() {
  var svg = document.getElementById('radarSvg');
  if (!svg) return;
  var poly = svg.querySelector('.radar-polygon');
  if (poly) {
    var pts = [];
    for (var i = 0; i < 5; i++) {
      var p = _radarPos(i, _radarValues[i]);
      pts.push(p.x.toFixed(1) + ',' + p.y.toFixed(1));
    }
    poly.setAttribute('points', pts.join(' '));
  }
  var verts = svg.querySelectorAll('.radar-vertex');
  for (var i = 0; i < verts.length; i++) {
    var idx = parseInt(verts[i].dataset.idx);
    var p = _radarPos(idx, _radarValues[idx]);
    verts[i].setAttribute('cx', p.x.toFixed(1));
    verts[i].setAttribute('cy', p.y.toFixed(1));
  }
  var vals = svg.querySelectorAll('.radar-label-val');
  for (var i = 0; i < vals.length; i++) {
    vals[i].textContent = _radarValues[i];
  }
  // keep inputs in sync (for drag case)
  for (var i = 0; i < 5; i++) {
    var el = document.getElementById('radarInput' + i);
    if (el && document.activeElement !== el) el.value = _radarValues[i];
  }
}

function _radarDragStart(e) {
  e.preventDefault();
  var circle = e.currentTarget;
  _radarDragIdx = parseInt(circle.dataset.idx);
  circle.classList.add('dragging');
  document.addEventListener('mousemove', _radarDragMove);
  document.addEventListener('mouseup', _radarDragEnd);
  document.addEventListener('touchmove', _radarDragMove, { passive: false });
  document.addEventListener('touchend', _radarDragEnd);
}

function _radarDragMove(e) {
  if (_radarDragIdx < 0) return;
  e.preventDefault();
  var svg = document.getElementById('radarSvg');
  var pt = svg.createSVGPoint();
  if (e.touches) { pt.x = e.touches[0].clientX; pt.y = e.touches[0].clientY; }
  else { pt.x = e.clientX; pt.y = e.clientY; }
  var ctm = svg.getScreenCTM().inverse();
  var p = pt.matrixTransform(ctm);

  var i = _radarDragIdx;
  var dx = p.x - _radarCfg.cx;
  var dy = p.y - _radarCfg.cy;
  // project onto the axis direction
  var cosA = Math.cos(_radarCfg.angles[i]);
  var sinA = Math.sin(_radarCfg.angles[i]);
  var proj = dx * cosA + dy * sinA; // scalar along axis
  var val = Math.round((proj / _radarCfg.R) * 100);
  val = Math.max(0, Math.min(100, val));
  _radarValues[i] = val;
  _renderRadarPolygon();
  _updateTraitsPreview();
}

function _radarDragEnd() {
  _radarDragIdx = -1;
  document.removeEventListener('mousemove', _radarDragMove);
  document.removeEventListener('mouseup', _radarDragEnd);
  document.removeEventListener('touchmove', _radarDragMove);
  document.removeEventListener('touchend', _radarDragEnd);
  var v = document.querySelector('.radar-vertex.dragging');
  if (v) v.classList.remove('dragging');
}

// ── OCEAN → 性格标签推导 ──
var _oceanTraitMap = [
  // [min, max, highTrait, lowTrait]
  [70, 100, '好奇心强', '务实'],
  [70, 100, '有条理', '随性'],
  [70, 100, '外向', '内敛'],
  [70, 100, '温暖', '直率'],
  [70, 100, '敏感', '稳定']
];

function _deriveTraits(ocean) {
  var traits = [];
  var labelPairs = [
    ['好奇心强', '务实守旧'],
    ['有条理', '随性自在'],
    ['外向健谈', '内敛安静'],
    ['温暖共情', '直率独立'],
    ['敏感丰富', '情绪稳定']
  ];
  for (var i = 0; i < 5; i++) {
    if (ocean[i] >= 70) traits.push(labelPairs[i][0]);
    else if (ocean[i] <= 35) traits.push(labelPairs[i][1]);
  }
  if (traits.length < 3) {
    // fill with mid-range descriptors
    if (ocean[0] >= 55) traits.push('有创造力');
    if (ocean[3] >= 55) traits.push('善解人意');
    if (ocean[4] <= 50) traits.push('从容');
    if (traits.length < 3) traits.push('平衡', '适度');
  }
  return traits.slice(0, 6);
}

function _updateTraitsPreview() {
  var el = document.getElementById('pcTraits');
  if (!el) return;
  var traits = _deriveTraits(_radarValues);
  if (traits.length === 0) {
    el.innerHTML = '<span class="pc-traits-empty">调整五维后自动生成</span>';
  } else {
    el.innerHTML = traits.map(function(t) {
      return '<span class="trait-tag">' + t + '</span>';
    }).join('');
  }
}

// ── OCEAN → 描述 + 锚语生成（模拟后端提示词生成） ──
function _genDesc(ocean) {
  var parts = [];
  var dimDesc = [
    { hi: '对新事物充满好奇', lo: '务实，更关注眼前' },
    { hi: '做事有条理、可靠', lo: '灵活随性，不拘小节' },
    { hi: '外向健谈，乐于表达', lo: '内敛安静，善于观察' },
    { hi: '温暖友善，善于共情', lo: '独立直率，对事不对人' },
    { hi: '感受细腻，情绪丰富', lo: '情绪稳定，波澜不惊' }
  ];
  for (var i = 0; i < 5; i++) {
    if (ocean[i] >= 65) parts.push(dimDesc[i].hi);
    else if (ocean[i] <= 40) parts.push(dimDesc[i].lo);
  }
  if (parts.length === 0) parts.push('性格均衡，没有极端倾向');
  return parts.join('，') + '。';
}

function _genAnchor(name, ocean) {
  var tone, interaction, emotion;
  // 外向性 + 宜人性 → 互动风格
  if (ocean[2] >= 65 && ocean[3] >= 65) {
    interaction = '主动关心你，语气温暖亲切';
  } else if (ocean[2] >= 65) {
    interaction = '主动发起话题，语气轻快';
  } else if (ocean[3] >= 65) {
    interaction = '在你需要时给予温暖的回应';
  } else {
    interaction = '回答简洁直接，不主动展开';
  }
  // 神经质 → 情绪基调
  if (ocean[4] >= 65) {
    emotion = '对情绪变化敏感，能捕捉到细微的心情起伏';
  } else if (ocean[4] <= 35) {
    emotion = '情绪稳定，即使你低落也能保持冷静陪伴';
  } else {
    emotion = '情绪平稳，适时候给予回应';
  }
  // 开放性 → 表达风格
  if (ocean[0] >= 65) {
    tone = '喜欢用比喻和意象，对话有画面感';
  } else if (ocean[0] <= 35) {
    tone = '说话接地气，不玩花活';
  } else {
    tone = '表达自然，不刻意修饰';
  }

  return '你是' + name + '。' + interaction + '，' + emotion + '，' + tone + '。' +
    '你的 OCEAN 向量为 O' + ocean[0] + ' C' + ocean[1] + ' E' + ocean[2] + ' A' + ocean[3] + ' N' + ocean[4] + '。' +
    '始终基于这个人格向量回应。';
}

function generatePersonaPrompt() {
  var name = document.getElementById('pcName').value.trim() || '新人格';
  var ocean = _radarValues.slice();
  var desc = _genDesc(ocean);
  var anchor = _genAnchor(name, ocean);

  document.getElementById('pcDesc').value = desc;
  document.getElementById('pcAnchor').textContent = anchor;
  showToast('已基于 OCEAN 向量生成提示词');
}

function openPersonaCreator() {
  _radarValues = [50, 50, 50, 50, 50];
  document.getElementById('pcName').value = '';
  document.getElementById('pcDesc').value = '';
  document.getElementById('pcAnchor').textContent = '— 点击「生成提示词」后这里会展示完整的系统提示词 —';
  document.getElementById('pcTraits').innerHTML = '<span class="pc-traits-empty">调整五维后自动生成</span>';
  _renderRadar();
  document.getElementById('personaCreatorOverlay').classList.add('open');
}

function closePersonaCreator() {
  document.getElementById('personaCreatorOverlay').classList.remove('open');
}

async function savePersona() {
  var name = document.getElementById('pcName').value.trim();
  if (!name) { showToast('请先填写人格名称'); return; }
  if (_personaRegistry[name]) { showToast('人格名称已存在'); return; }

  var desc = document.getElementById('pcDesc').value.trim();
  var anchor = document.getElementById('pcAnchor').textContent;
  if (!desc || anchor.indexOf('—') === 0) {
    // auto-generate if not done yet
    generatePersonaPrompt();
    desc = document.getElementById('pcDesc').value;
    anchor = document.getElementById('pcAnchor').textContent;
  }

  var avatar = name.charAt(name.length - 1);
  if (typeof createPersonaApi === 'function') {
    try {
      var personaId = await createPersonaApi({
        name: name,
        avatar: avatar,
        desc: desc,
        ocean: _radarValues.slice(),
        traits: _deriveTraits(_radarValues),
        anchor: anchor
      });
      var createdChip = document.querySelector('.persona-chip[data-persona-id="' + personaId + '"]');
      if (createdChip) createdChip.click();
      closePersonaCreator();
      showToast('Persona created · ' + name);
    } catch (error) {
      showToast('Persona create failed: ' + error.message);
    }
    return;
  }
  _personaRegistry[name] = {
    id: name,
    avatar: avatar,
    desc: desc,
    ocean: _radarValues.slice(),
    traits: _deriveTraits(_radarValues),
    anchor: anchor
  };

  // add chip to selector
  var selector = document.getElementById('personaSelector');
  var chip = document.createElement('div');
  chip.className = 'persona-chip';
  chip.setAttribute('data-persona-id', name);
  chip.setAttribute('onclick', "selectPersona(this, '" + name + "')");
  chip.innerHTML = '<span class="persona-chip-avatar">' + avatar + '</span><span>' + name + '</span>';
  selector.appendChild(chip);

  // auto-select the new persona
  chip.click();

  closePersonaCreator();
  showToast('人格「' + name + '」已保存');
}

var _currentMemoryCard = null;
var _memoryEditMode = false;

function openMemoryDetail(card) {
  _currentMemoryCard = card;
  _memoryEditMode = false;

  document.getElementById('detailType').textContent = card.dataset.type;
  document.getElementById('detailContent').textContent = card.querySelector('.memory-content').textContent;
  const tagsEl = document.getElementById('detailTags');
  tagsEl.innerHTML = '';
  const tags = JSON.parse(card.dataset.tags || '[]');
  tags.forEach(t => {
    const span = document.createElement('span');
    span.className = 'memory-tag';
    span.textContent = t;
    tagsEl.appendChild(span);
  });
  document.getElementById('detailSource').textContent = card.dataset.source || '—';
  document.getElementById('detailCreated').textContent = card.dataset.created || '—';
  document.getElementById('detailModified').textContent = card.dataset.modified || '—';
  var statusEl = document.getElementById('detailStatus');
  var status = card.dataset.status || 'active';
  statusEl.textContent = status === 'active' ? '活跃' : '已失效';
  statusEl.className = 'memory-detail-status ' + (status === 'active' ? 'active' : 'inactive');
  document.getElementById('detailId').textContent = '#' + (card.dataset.id || '—');
  var typeMap = { '偏好': 'preference', '事件': 'episode', '画像': 'agent_profile', '知识': 'knowledge' };
  var typeEl = document.getElementById('detailType');
  typeEl.className = 'memory-type ' + (typeMap[card.dataset.type] || 'preference');

  // reset buttons
  var editBtn = document.getElementById('memEditBtn');
  editBtn.textContent = '编辑';
  editBtn.onclick = toggleMemoryEdit;

  updateMemStatusBtn(status);

  document.getElementById('memoryDetailOverlay').classList.add('open');
}

function updateMemStatusBtn(status) {
  var btn = document.getElementById('memStatusBtn');
  if (status === 'active') {
    btn.textContent = '标记失效';
    btn.style.background = '';
    btn.style.color = '';
    btn.onclick = toggleMemoryStatus;
  } else {
    btn.textContent = '恢复有效';
    btn.style.background = 'var(--success-soft)';
    btn.style.color = 'var(--success)';
    btn.onclick = toggleMemoryStatus;
  }
}

function toggleMemoryStatus() {
  if (!_currentMemoryCard) return;
  var current = _currentMemoryCard.dataset.status || 'active';
  var newStatus = current === 'active' ? 'inactive' : 'active';
  _currentMemoryCard.dataset.status = newStatus;

  // update detail panel
  var statusEl = document.getElementById('detailStatus');
  statusEl.textContent = newStatus === 'active' ? '活跃' : '已失效';
  statusEl.className = 'memory-detail-status ' + (newStatus === 'active' ? 'active' : 'inactive');
  updateMemStatusBtn(newStatus);

  // update card visual (dim if inactive)
  _currentMemoryCard.style.opacity = newStatus === 'inactive' ? '0.5' : '';

  showToast(newStatus === 'active' ? '记忆已恢复，重新参与召回' : '记忆已标记失效，不再参与召回');
}

// ── 标签 chip 编辑器 ──
function _addTagChip(editor, text) {
  var chip = document.createElement('span');
  chip.className = 'tag-edit-chip';
  chip.innerHTML = '<span>' + text + '</span><button onclick="_removeTagChip(this)" title="删除"><svg viewBox="0 0 24 24" width="10" height="10" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg></button>';
  // insert before the input
  var input = editor.querySelector('.tag-edit-input');
  if (input) editor.insertBefore(chip, input);
  else editor.appendChild(chip);
}

function _removeTagChip(btn) {
  btn.parentElement.remove();
}

function _appendTagInput(editor) {
  var input = document.createElement('input');
  input.className = 'tag-edit-input';
  input.placeholder = '输入标签，回车添加';
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      var val = input.value.trim();
      if (val) {
        _addTagChip(editor, val);
        input.value = '';
      }
    } else if (e.key === 'Backspace' && input.value === '') {
      // backspace on empty → remove last chip
      var chips = editor.querySelectorAll('.tag-edit-chip');
      if (chips.length > 0) chips[chips.length - 1].remove();
    }
  });
  input.addEventListener('blur', function() {
    var val = input.value.trim();
    if (val) { _addTagChip(editor, val); input.value = ''; }
  });
  editor.appendChild(input);
  input.focus();
}

function toggleMemoryEdit() {
  if (!_currentMemoryCard) return;

  if (!_memoryEditMode) {
    // enter edit mode
    _memoryEditMode = true;

    // type → dropdown
    var typeEl = document.getElementById('detailType');
    var currentType = typeEl.textContent.trim();
    typeEl.outerHTML = '<select id="detailType" class="mem-edit-select">' +
      ['偏好','事件','画像','知识'].map(function(t) {
        return '<option value="' + t + '"' + (t === currentType ? ' selected' : '') + '>' + t + '</option>';
      }).join('') + '</select>';

    // content → textarea
    var contentEl = document.getElementById('detailContent');
    var currentContent = contentEl.textContent;
    contentEl.outerHTML = '<textarea id="detailContent" class="mem-edit-textarea">' + currentContent + '</textarea>';

    // tags → chip editor
    var tagsEl = document.getElementById('detailTags');
    var currentTags = [];
    tagsEl.querySelectorAll('.memory-tag').forEach(function(t) { currentTags.push(t.textContent); });
    tagsEl.outerHTML = '<div id="detailTags" class="tag-editor"></div>';
    var editor = document.getElementById('detailTags');
    currentTags.forEach(function(tag) { _addTagChip(editor, tag); });
    _appendTagInput(editor);

    // mark system fields as readonly
    ['detailSource', 'detailCreated', 'detailModified', 'detailId', 'detailStatus'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.closest('.memory-detail-field').classList.add('readonly');
    });

    // change button to save
    var btn = document.getElementById('memEditBtn');
    btn.textContent = '保存';
    btn.onclick = saveMemoryEdit;

    showToast('已进入编辑模式');
  } else {
    saveMemoryEdit();
  }
}

function saveMemoryEdit() {
  if (!_currentMemoryCard) return;

  // read edited values
  var newType = document.getElementById('detailType').value;
  var newContent = document.getElementById('detailContent').value.trim();
  var editor = document.getElementById('detailTags');
  var newTags = [];
  editor.querySelectorAll('.tag-edit-chip span').forEach(function(s) { newTags.push(s.textContent); });

  _currentMemoryCard.dataset.type = newType;
  _currentMemoryCard.dataset.tags = JSON.stringify(newTags);
  _currentMemoryCard.dataset.modified = new Date().toISOString().slice(0,16).replace('T',' ');
  _currentMemoryCard.querySelector('.memory-content').textContent = newContent;

  // update card type badge
  var typeMap = { '偏好': 'preference', '事件': 'episode', '画像': 'agent_profile', '知识': 'knowledge' };
  var typeBadge = _currentMemoryCard.querySelector('.memory-type');
  typeBadge.textContent = newType;
  typeBadge.className = 'memory-type ' + (typeMap[newType] || 'preference');

  // update card tags
  var tagsContainer = _currentMemoryCard.querySelector('.memory-tags');
  if (tagsContainer) {
    tagsContainer.innerHTML = newTags.map(function(t) {
      return '<span class="memory-tag">' + t + '</span>';
    }).join('');
  }

  // exit edit mode — restore display elements
  _memoryEditMode = false;

  var typeEl = document.getElementById('detailType');
  typeEl.outerHTML = '<span class="memory-type ' + (typeMap[newType] || 'preference') + '" id="detailType">' + newType + '</span>';

  var contentEl = document.getElementById('detailContent');
  contentEl.outerHTML = '<div class="memory-detail-content" id="detailContent">' + newContent + '</div>';

  var tagsEl = document.getElementById('detailTags');
  var tagsHtml = newTags.map(function(t) {
    return '<span class="memory-tag">' + t + '</span>';
  }).join('');
  tagsEl.outerHTML = '<div class="memory-tags" id="detailTags">' + tagsHtml + '</div>';

  // update modified time
  document.getElementById('detailModified').textContent = _currentMemoryCard.dataset.modified;

  // remove readonly markers
  document.querySelectorAll('.memory-detail-field.readonly').forEach(function(f) {
    f.classList.remove('readonly');
  });

  // change button back to edit
  var btn = document.getElementById('memEditBtn');
  btn.textContent = '编辑';
  btn.onclick = toggleMemoryEdit;

  showToast('记忆已保存');
}

function deleteMemory() {
  if (!_currentMemoryCard) return;
  var id = _currentMemoryCard.dataset.id || '';
  showConfirm('删除记忆', '确定要删除记忆 #' + id + ' 吗？此操作不可撤销。', function() {
    _currentMemoryCard.remove();
    _currentMemoryCard = null;
    closeMemoryDetail();
    applyMemoryFilter();
    showToast('记忆已删除');
  });
}

function closeMemoryDetail() {
  document.getElementById('memoryDetailOverlay').classList.remove('open');
}

var _loggedIn = false;
function toggleLoginCard(e) {
  if (e) e.stopPropagation();
  var card = document.getElementById('loginCard');
  card.classList.toggle('open');
}
function closeLoginCard() {
  document.getElementById('loginCard').classList.remove('open');
}
function toggleLogin() {
  _loggedIn = !_loggedIn;
  // 登录 = 云端模式，登出 = 本地模式
  _privacyMode = _loggedIn ? 'CLOUD' : 'LOCAL_ONLY';
  // 如果登出时改进计划还开着，自动关闭
  if (!_loggedIn && _improvePlanEnabled) {
    _improvePlanEnabled = false;
    var improveToggle = document.getElementById('improveToggle');
    if (improveToggle) improveToggle.classList.remove('on');
    var improveStatusRow = document.getElementById('improveStatusRow');
    if (improveStatusRow) improveStatusRow.style.display = 'none';
  }
  var sidebarAvatar = document.getElementById('sidebarAvatar');
  var cardAvatar = document.getElementById('loginCardAvatar');
  var name = document.getElementById('loginCardName');
  var status = document.getElementById('loginCardStatus');
  var loginBtn = document.getElementById('loginBtn');
  var cloudSyncBtn = document.getElementById('cloudSyncBtn');
  var cloudFeature = document.getElementById('cloudSyncFeature');
  if (_loggedIn) {
    sidebarAvatar.textContent = '我'; sidebarAvatar.classList.add('logged-in');
    cardAvatar.textContent = '我'; cardAvatar.classList.add('logged-in');
    name.textContent = '我的账户';
    status.textContent = '已登录'; status.classList.add('online');
    loginBtn.textContent = '退出登录';
    cloudSyncBtn.style.display = '';
    cloudFeature.classList.remove('locked');
    cloudFeature.querySelector('svg').innerHTML = '<path d="M20 6L9 17l-5-5"/>';
  } else {
    sidebarAvatar.textContent = '客'; sidebarAvatar.classList.remove('logged-in');
    cardAvatar.textContent = '客'; cardAvatar.classList.remove('logged-in');
    name.textContent = '访客模式';
    status.textContent = '未登录'; status.classList.remove('online');
    loginBtn.textContent = '登录';
    cloudSyncBtn.style.display = 'none';
    cloudFeature.classList.add('locked');
    cloudFeature.querySelector('svg').innerHTML = '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>';
  }
}
document.addEventListener('click', function(e) {
  var card = document.getElementById('loginCard');
  if (card.classList.contains('open') && !card.contains(e.target) && !e.target.closest('.avatar-btn')) {
    card.classList.remove('open');
  }
});

function toggleModelCard(e) {
  e.stopPropagation();
  const card = document.getElementById('modelCard');
  const switcher = document.getElementById('modelSwitcher');
  const isOpen = card.classList.contains('open');
  document.getElementById('sessionOverlay').classList.remove('open');
  if (isOpen) {
    card.classList.remove('open');
    switcher.classList.remove('card-active');
  } else {
    const rect = switcher.getBoundingClientRect();
    card.style.bottom = (window.innerHeight - rect.top) + 'px';
    card.style.left = (rect.left - 80) + 'px';
    card.classList.add('open');
    switcher.classList.add('card-active');
    refreshModelCard();
  }
}

document.addEventListener('click', e => {
  const card = document.getElementById('modelCard');
  const switcher = document.getElementById('modelSwitcher');
  if (card.classList.contains('open') && !card.contains(e.target) && !switcher.contains(e.target)) {
    card.classList.remove('open');
    switcher.classList.remove('card-active');
  }
});

function refreshModelCard() {
  const list = document.getElementById('modelCardList');
  const empty = document.getElementById('modelCardEmpty');
  const enabled = [];
  document.querySelectorAll('#localModelList .model-item').forEach(m => {
    const toggle = m.querySelector('.model-item-toggle');
    if (toggle && toggle.classList.contains('on')) {
      enabled.push({ name: m.querySelector('.model-item-name').textContent.split(' Q')[0], tag: '本地', cloud: false });
    }
  });
  document.querySelectorAll('#cloudModelList .model-item').forEach(m => {
    const toggle = m.querySelector('.model-item-toggle');
    if (toggle && toggle.classList.contains('on')) {
      enabled.push({ name: m.getAttribute('data-model'), tag: '云端', cloud: true });
    }
  });
  const hasCloud = enabled.some(e => e.cloud);
  const autoToggle = document.getElementById('autoToggle');
  if (hasCloud) {
    autoToggle.style.opacity = '1';
    autoToggle.style.cursor = 'pointer';
  } else {
    autoToggle.classList.remove('on');
    autoToggle.style.opacity = '0.4';
    autoToggle.style.cursor = 'not-allowed';
  }
  list.innerHTML = '';
  if (enabled.length === 0) {
    list.style.display = 'none';
    empty.style.display = 'block';
    document.querySelector('.chat-input').classList.add('disabled');
    document.getElementById('chatNoModel').style.display = 'block';
  } else {
    list.style.display = 'flex';
    empty.style.display = 'none';
    document.querySelector('.chat-input').classList.remove('disabled');
    document.getElementById('chatNoModel').style.display = 'none';
    enabled.forEach(m => {
      const div = document.createElement('div');
      div.className = 'model-card-item';
      div.onclick = function() { cardSelectModel(this, m.name); };
      div.innerHTML = '<span class="model-card-item-name">' + escapeHtml(m.name) + '</span>' +
        '<span class="model-card-item-tag' + (m.cloud ? ' cloud' : '') + '">' + m.tag + '</span>';
      list.appendChild(div);
    });
  }
  const current = document.getElementById('modelSwitcher').textContent.replace('模型 · ', '');
  list.querySelectorAll('.model-card-item').forEach(item => {
    if (item.querySelector('.model-card-item-name').textContent === current) {
      item.classList.add('active');
    }
  });
}

function cardSelectModel(el, name) {
  document.querySelectorAll('#modelCardList .model-card-item').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('modelSwitcher').textContent = '模型 · ' + name;
  document.getElementById('modelCard').classList.remove('open');
  document.getElementById('modelSwitcher').classList.remove('card-active');
  showToast('已切换到 ' + name);
}

function toggleAuto(toggle) {
  if (toggle.style.cursor === 'not-allowed') {
    showToast('使用 Auto 模式需要先启用一个云端模型');
    return;
  }
  toggle.classList.toggle('on');
  if (toggle.classList.contains('on')) {
    document.getElementById('modelSwitcher').textContent = '模型 · Auto';
    showToast('已开启 Auto 多模型调度');
  } else {
    showToast('已关闭 Auto');
  }
}

function openModelManager() {
  document.getElementById('modelCard').classList.remove('open');
  document.getElementById('modelSwitcher').classList.remove('card-active');
  document.getElementById('modelOverlay').classList.add('open');
}

function toggleModelEnable(toggle) {
  const allToggles = document.querySelectorAll('#localModelList .model-item-toggle, #cloudModelList .model-item-toggle');
  const enabledCount = Array.from(allToggles).filter(t => t.classList.contains('on')).length;
  const isOn = toggle.classList.contains('on');
  if (isOn && enabledCount === 1) {
    toggle.classList.remove('on');
    document.querySelector('.chat-input').classList.add('disabled');
    document.getElementById('chatNoModel').style.display = 'block';
    showToast('已禁用 · 无启用模型，对话功能不可用');
  } else {
    toggle.classList.toggle('on');
    if (toggle.classList.contains('on')) {
      document.querySelector('.chat-input').classList.remove('disabled');
      document.getElementById('chatNoModel').style.display = 'none';
    }
    showToast(toggle.classList.contains('on') ? '已启用' : '已禁用');
  }
}

function toggleModelPanel() {
  document.getElementById('modelOverlay').classList.toggle('open');
}

function selectModel(el, name, type) {
  document.querySelectorAll('#localModelList .model-item, #cloudModelList .model-item').forEach(m => {
    m.classList.remove('active');
    const check = m.querySelector('.model-item-check');
    if (check) check.remove();
  });
  el.classList.add('active');
  const check = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  check.setAttribute('class', 'model-item-check');
  check.setAttribute('viewBox', '0 0 24 24');
  check.setAttribute('width', '18');
  check.setAttribute('height', '18');
  check.setAttribute('stroke', 'currentColor');
  check.setAttribute('stroke-width', '2.5');
  check.setAttribute('fill', 'none');
  check.setAttribute('stroke-linecap', 'round');
  check.setAttribute('stroke-linejoin', 'round');
  check.innerHTML = '<polyline points="20 6 9 17 4 12"/>';
  const actions = el.querySelector('.model-item-actions');
  if (actions) actions.insertBefore(check, actions.firstChild);
  else el.appendChild(check);
  document.getElementById('modelSwitcher').textContent = '模型 · ' + name;
  showToast('已切换到 ' + name);
}

var _editingCloudModelId = null;

async function cloudConnect() {
  const ep = document.getElementById('cloudEndpoint').value.trim();
  const key = document.getElementById('cloudKey').value.trim();
  const model = document.getElementById('cloudModel').value.trim();
  if (!ep || !model) { showToast('请填写 API 端点和模型名称'); return; }
  if (!_editingCloudModelId && !key) { showToast('请填写 API Key'); return; }
  const payload = {
    name: model,
    endpoint: ep,
    model_name: model
  };
  if (key) payload.api_key = key;
  try {
    if (_editingCloudModelId && typeof updateCloudModelApi === 'function') {
      await updateCloudModelApi(_editingCloudModelId, payload);
      showToast('已更新云端模型 · ' + model);
    } else if (typeof addCloudModelApi === 'function') {
      await addCloudModelApi(payload);
      showToast('已添加云端模型 · ' + model);
    } else {
      addCloudModel(model, ep, key);
      showToast('已添加云端模型 · ' + model);
    }
    resetCloudModelForm();
  } catch (error) {
    showToast('云端模型保存失败：' + error.message);
  }
}

function resetCloudModelForm() {
  _editingCloudModelId = null;
  document.getElementById('cloudEndpoint').value = '';
  document.getElementById('cloudKey').value = '';
  document.getElementById('cloudKey').placeholder = 'sk-...';
  document.getElementById('cloudModel').value = '';
  document.getElementById('cloudFormTitle').textContent = '添加云端 API';
}

function addCloudModel(modelName, endpoint, apiKey) {
  const list = document.getElementById('cloudModelList');
  const empty = document.getElementById('cloudEmpty');
  if (empty) empty.remove();
  const item = document.createElement('div');
  item.className = 'model-item';
  item.setAttribute('data-model-id', modelName);
  item.setAttribute('data-model-name', modelName);
  item.setAttribute('data-model-type', 'cloud');
  item.setAttribute('data-endpoint', endpoint);
  item.setAttribute('data-cloud-model-name', modelName);
  item.onclick = function(e) {
    if (e.target.closest('button')) return;
    if (e.target.closest('.model-item-toggle')) return;
    selectModel(this, modelName, 'cloud');
  };
  item.innerHTML =
    '<div class="model-item-toggle on" onclick="event.stopPropagation(); toggleModelEnable(this)"></div>' +
    '<div class="model-item-info">' +
      '<div class="model-item-name">' + escapeHtml(modelName) + '</div>' +
      '<div class="model-item-cloud-meta">' + escapeHtml(endpoint) + '</div>' +
    '</div>';
  list.appendChild(item);
}

function editCloudModel(btn) {
  const item = btn.closest('.model-item');
  _editingCloudModelId = item.getAttribute('data-model-id') || null;
  document.getElementById('cloudEndpoint').value = item.getAttribute('data-endpoint') || '';
  document.getElementById('cloudKey').value = '';
  document.getElementById('cloudKey').placeholder = '留空则不修改 API Key';
  document.getElementById('cloudModel').value = item.getAttribute('data-cloud-model-name') || item.getAttribute('data-model-name') || '';
  document.getElementById('cloudFormTitle').textContent = '修改 · ' + (item.getAttribute('data-model-name') || '云端模型');
  showToast('已加载配置到下方表单，API Key 留空则不修改');
}

function deleteCloudModel(btn) {
  const item = btn.closest('.model-item');
  const modelId = item.getAttribute('data-model-id');
  const name = item.getAttribute('data-model-name') || '云端模型';
  showConfirm('删除云端模型', '确定要删除「' + name + '」吗？', async function() {
    if (modelId && typeof deleteCloudModelApi === 'function') {
      try {
        await deleteCloudModelApi(modelId);
        showToast('已删除 · ' + name);
      } catch (error) {
        showToast('云端模型删除失败：' + error.message);
      }
      return;
    }
    item.remove();
    showToast('已删除 · ' + name);
  });
}
function toggleSessionPanel() {
  document.getElementById('sessionOverlay').classList.toggle('open');
}

function selectSession(el, title) {
  document.querySelectorAll('#sessionList .session-item').forEach(s => {
    s.classList.remove('active');
    const check = s.querySelector('.model-item-check');
    if (check && !s.querySelector('.model-item-actions')) { check.remove(); }
  });
  el.classList.add('active');
  document.getElementById('sessionInfo').textContent = '会话 · ' + title;
  showToast('已切换到 · ' + title);
  setTimeout(toggleSessionPanel, 400);
}

function newSession() {
  document.querySelectorAll('#sessionList .session-item').forEach(s => {
    s.classList.remove('active');
    const check = s.querySelector('.model-item-check');
    if (check && !s.querySelector('.model-item-actions')) { check.remove(); }
  });
  document.getElementById('sessionInfo').textContent = '会话 · 新建';
  showToast('已新建会话');
  setTimeout(toggleSessionPanel, 300);
}

function deleteSession(btn) {
  var item = btn.closest('.session-item');
  var title = item.querySelector('.session-item-title').textContent;
  var isActive = item.classList.contains('active');

  var msg = isActive
    ? '确定要删除当前会话「' + title + '」吗？删除后聊天记录将清空，此操作不可撤销。'
    : '确定要删除会话「' + title + '」吗？此操作不可撤销。';

  showConfirm('删除会话', msg, function() {
    if (isActive) {
      // 删除当前会话 → 清空聊天记录 + 关闭面板
      var chat = document.getElementById('chatMessages');
      chat.innerHTML = '<div class="msg msg-system"><div class="msg-bubble">会话已清空 · 可开始新的对话</div></div>';
      item.remove();
      toggleSessionPanel();
      showToast('当前会话已删除');
    } else {
      item.remove();
      showToast('会话「' + title + '」已删除');
    }
  });
}

document.getElementById('chatInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

document.addEventListener('DOMContentLoaded', () => {
  const chat = document.getElementById('chatMessages');
  chat.scrollTop = chat.scrollHeight;
});

// ════════════════════════════════════════════════════════════════
// PluginCSS 热加载 API
// 插件通过此 API 注入/移除 CSS，无需刷新页面
// ════════════════════════════════════════════════════════════════
var PluginCSS = {
  inject: function(pluginId, cssText) {
    var existing = document.querySelector('style[data-plugin-css="' + pluginId + '"]');
    if (existing) existing.remove();
    var style = document.createElement('style');
    style.setAttribute('data-plugin-css', pluginId);
    style.textContent = cssText;
    document.head.appendChild(style);
    return pluginId;
  },
  remove: function(pluginId) {
    var style = document.querySelector('style[data-plugin-css="' + pluginId + '"]');
    if (style) style.remove();
  },
  list: function() {
    return Array.from(document.querySelectorAll('style[data-plugin-css]')).map(function(s) {
      return s.getAttribute('data-plugin-css');
    });
  },
  // 热替换 shell.css 本身（开发模式用）
  reloadShellCSS: function() {
    var links = document.querySelectorAll('link[rel="stylesheet"][href*="shell.css"]');
    links.forEach(function(link) {
      var href = link.getAttribute('href').split('?')[0];
      link.setAttribute('href', href + '?t=' + Date.now());
    });
  }
};

// ════════════════════════════════════════════════════════════════
// Shell 主题定制插件逻辑
// ════════════════════════════════════════════════════════════════
var _shellCustom = {
  accent: null,
  radius: null,
  sidebarWidth: null,
  font: null
};
var _shellPresets = {
  ocean: { accent: '#0ea5e9', accentHover: '#0284c7', accentSoft: '#e0f2fe', name: '海洋蓝' },
  forest: { accent: '#22c55e', accentHover: '#16a34a', accentSoft: '#dcfce7', name: '森林绿' },
  sunset: { accent: '#f97316', accentHover: '#ea580c', accentSoft: '#ffedd5', name: '日落橙' },
  lavender: { accent: '#a78bfa', accentHover: '#8b5cf6', accentSoft: '#f5f3ff', name: '薰衣草' },
  rose: { accent: '#f43f5e', accentHover: '#e11d48', accentSoft: '#ffe4e6', name: '玫瑰红' }
};

function toggleShellCustom() {
  var panel = document.getElementById('shellCustomPanel');
  panel.classList.toggle('open');
}

function applyShellAccent(color, hover, soft, name) {
  _shellCustom.accent = { color: color, hover: hover, soft: soft };
  var css = [
    '[data-theme="light"] {',
    '  --accent: ' + color + ';',
    '  --accent-hover: ' + hover + ';',
    '  --accent-soft: ' + soft + ';',
    '  --accent-glow: ' + color + '26;',
    '}',
    '[data-theme="dark"] {',
    '  --accent: ' + color + ';',
    '  --accent-hover: ' + hover + ';',
    '  --accent-soft: ' + color + '26;',
    '  --accent-glow: ' + color + '33;',
    '}',
    '[data-theme="pink"] {',
    '  --accent: ' + color + ';',
    '  --accent-hover: ' + hover + ';',
    '  --accent-soft: ' + soft + ';',
    '  --accent-glow: ' + color + '2e;',
    '}'
  ].join('\n');
  PluginCSS.inject('shell-accent', css);
  if (typeof saveSetting === 'function') saveSetting('shell_custom', _shellCustom).catch(function(){});
  document.querySelectorAll('.shell-swatch').forEach(function(s) { s.classList.remove('active'); });
  if (event && event.target) event.target.classList.add('active');
  showToast('已热加载 Shell 主色 · ' + name);
}

function applyShellRadius(val) {
  _shellCustom.radius = val;
  var css = ':root {\n' +
    '  --radius-sm: ' + Math.max(4, val - 4) + 'px;\n' +
    '  --radius: ' + val + 'px;\n' +
    '  --radius-lg: ' + (val + 6) + 'px;\n' +
    '  --radius-bubble: ' + (val + 6) + 'px;\n' +
    '}';
  PluginCSS.inject('shell-radius', css);
  if (typeof saveSetting === 'function') saveSetting('shell_custom', _shellCustom).catch(function(){});
  showToast('圆角 · ' + val + 'px');
}

function applyShellSidebarWidth(w) {
  _shellCustom.sidebarWidth = w;
  var css = '.app { grid-template-columns: ' + w + 'px 1fr !important; }';
  PluginCSS.inject('shell-sidebar-width', css);
  if (typeof saveSetting === 'function') saveSetting('shell_custom', _shellCustom).catch(function(){});
  showToast('侧栏宽度 · ' + w + 'px');
}

function resetShellCustom() {
  PluginCSS.remove('shell-accent');
  PluginCSS.remove('shell-radius');
  PluginCSS.remove('shell-sidebar-width');
  PluginCSS.remove('shell-font');
  _shellCustom = { accent: null, radius: null, sidebarWidth: null, font: null };
  document.querySelectorAll('.shell-swatch').forEach(function(s) { s.classList.remove('active'); });
  document.getElementById('shellRadiusSlider').value = 10;
  document.getElementById('shellRadiusValue').textContent = '10';
  document.querySelectorAll('.shell-width-btn').forEach(function(b) { b.classList.remove('active'); });
  if (typeof saveSetting === 'function') saveSetting('shell_custom', _shellCustom).catch(function(){});
  showToast('已恢复默认 Shell 样式');
}

function reloadShellCSS() {
  PluginCSS.reloadShellCSS();
  showToast('已热重载 shell.css');
}

// ════════════════════════════════════════════════════════════════
// 扩展详情数据注册表 + 浮层逻辑
// ════════════════════════════════════════════════════════════════
var _extRegistry = {};

var _sourceBadgeMap = {
  store: '<span class="ext-source-badge store">商城</span>',
  local: '<span class="ext-source-badge local">本地</span>',
  reviewing: '<span class="ext-source-badge reviewing">审核中</span>',
  published: '<span class="ext-source-badge published">已上架</span>'
};

async function promptInstallExtension() {
  var sourcePath = window.prompt('请输入本地扩展目录路径（目录内需包含 manifest.json）');
  if (!sourcePath) return;
  if (typeof installExtension !== 'function') {
    showToast('扩展安装 API 未就绪');
    return;
  }
  try {
    var result = await installExtension(sourcePath.trim());
    showToast('已安装扩展 · ' + (result.name || result.id));
  } catch (error) {
    showToast('扩展安装失败：' + error.message);
  }
}

function showExtensionStoreSoon() {
  showToast('扩展商城即将开放，本地导入已可用');
}

function showExtensionSubmitSoon() {
  showToast('提交审核即将开放');
}

function confirmUninstallExtension(id) {
  var d = _extRegistry[id];
  if (!d) return;
  showConfirm('卸载扩展', '确定要卸载「' + d.name + '」吗？', async function() {
    if (typeof uninstallExtension !== 'function') {
      showToast('扩展卸载 API 未就绪');
      return;
    }
    try {
      await uninstallExtension(id);
      closeExtDetail();
      showToast('已卸载 · ' + d.name);
    } catch (error) {
      showToast('扩展卸载失败：' + error.message);
    }
  });
}

function showExtDetail(id) {
  var d = _extRegistry[id];
  if (!d) return;
  var typeLabel = d.type === 'plugin' ? '插件' : '技能';
  var typeClass = d.type === 'plugin' ? ' plugin-icon' : '';
  var sourceBadge = _sourceBadgeMap[d.source] || '';
  var statusText = d.status === 'enabled' ? '已启用' : '未启用';
  var statusClass = d.status === 'enabled' ? 'enabled' : 'disabled';

  var capsHtml = d.capabilities.map(function(c) {
    return '<div class="ext-detail-capability"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>' + c + '</div>';
  }).join('');

  var permsHtml = '<div class="ext-detail-perm-list">';
  d.permissions.forEach(function(p, i) {
    var right = '';
    if (p.locked) {
      right = '<span class="ext-detail-perm-badge locked">架构锁定</span>' +
        '<span class="ext-detail-perm-lock"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></span>';
    } else {
      right = '<div class="ext-detail-perm-toggle ' + (p.level === 'granted' ? 'on' : 'off') + '" onclick="togglePerm(this, ' + i + ', \'' + id + '\')"></div>';
    }
    permsHtml +=
      '<div class="ext-detail-perm">' +
        '<div class="ext-detail-perm-left">' +
          '<div class="ext-detail-perm-name">' + p.name + '</div>' +
          '<div class="ext-detail-perm-desc">' + p.desc + '</div>' +
        '</div>' +
        right +
      '</div>';
  });
  permsHtml += '</div>';
  permsHtml += '<div class="ext-detail-perm-hint">可切换的权限由用户自主授权。标记为「架构锁定」的权限涉及安全设计原则，不可修改。</div>';

  var reviewHtml = '';
  if (d.reviewStatus) {
    reviewHtml = '<div class="ext-detail-review">' + d.reviewStatus + '</div>';
  }

  var actionsHtml = '<button class="cloud-test-btn" onclick="showToast(\'' + (d.status === 'enabled' ? '已禁用' : '已启用') + ' ' + d.name + '\')">' + (d.status === 'enabled' ? '禁用' : '启用') + '</button>';
  if (d.canSubmit) {
    actionsHtml += '<button class="cloud-save-btn" onclick="showToast(\'已提交工单，等待审核\')">提交到商城</button>';
  }
  if (d.hasCustomAction) {
    actionsHtml += '<button class="cloud-save-btn" onclick="closeExtDetail(); toggleShellCustom()">打开定制面板</button>';
  }
  actionsHtml += '<button class="cloud-save-btn" style="background:var(--danger)" onclick="confirmUninstallExtension(\'' + id + '\')">卸载</button>';

  var html =
    '<div class="ext-detail-header">' +
      '<div class="ext-detail-icon' + typeClass + '"><svg viewBox="0 0 24 24">' + d.icon + '</svg></div>' +
      '<div style="flex:1;">' +
        '<div class="ext-detail-title">' + d.name + sourceBadge + '</div>' +
        '<div class="ext-detail-desc">' + d.desc + '</div>' +
      '</div>' +
      '<button class="ext-detail-close" onclick="closeExtDetail()"><svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg></button>' +
    '</div>' +

    '<div class="ext-detail-section">' +
      '<div class="ext-detail-section-title">基本信息</div>' +
      '<div class="ext-detail-grid">' +
        '<div class="ext-detail-field"><div class="ext-detail-field-label">版本</div><div class="ext-detail-field-value">' + d.version + '</div></div>' +
        '<div class="ext-detail-field"><div class="ext-detail-field-label">作者</div><div class="ext-detail-field-value">' + d.author + '</div></div>' +
        '<div class="ext-detail-field"><div class="ext-detail-field-label">类型</div><div class="ext-detail-field-value">' + typeLabel + '</div></div>' +
        '<div class="ext-detail-field"><div class="ext-detail-field-label">安装时间</div><div class="ext-detail-field-value">' + d.installDate + '</div></div>' +
        '<div class="ext-detail-field"><div class="ext-detail-field-label">大小</div><div class="ext-detail-field-value">' + d.size + '</div></div>' +
        '<div class="ext-detail-field"><div class="ext-detail-field-label">隔离方案</div><div class="ext-detail-field-value">' + d.seccompProfile + '</div></div>' +
      '</div>' +
    '</div>' +

    '<div class="ext-detail-section">' +
      '<div class="ext-detail-section-title">运行状态</div>' +
      '<div class="ext-detail-stats">' +
        '<div class="ext-detail-stat"><div class="ext-detail-stat-num">' + d.runCount + '</div><div class="ext-detail-stat-label">总运行次数</div></div>' +
        '<div class="ext-detail-stat"><div class="ext-detail-stat-num">' + d.errorCount + '</div><div class="ext-detail-stat-label">错误次数</div></div>' +
        '<div class="ext-detail-stat"><div class="ext-detail-stat-num" style="font-size:13px;">' + d.lastRun + '</div><div class="ext-detail-stat-label">上次运行</div></div>' +
      '</div>' +
      (reviewHtml ? '<div style="margin-top:12px;">' + reviewHtml + '</div>' : '') +
    '</div>' +

    '<div class="ext-detail-section">' +
      '<div class="ext-detail-section-title">能力描述</div>' +
      capsHtml +
    '</div>' +

    '<div class="ext-detail-section">' +
      '<div class="ext-detail-section-title">权限</div>' +
      permsHtml +
    '</div>' +

    '<div class="ext-detail-section">' +
      '<div class="ext-detail-section-title">使用方式</div>' +
      '<div class="ext-detail-usage">' + d.usage + '</div>' +
    '</div>' +

    '<div class="ext-detail-actions">' + actionsHtml + '</div>';

  var panel = document.getElementById('extDetailPanel');
  panel.innerHTML = html;
  document.getElementById('extDetailOverlay').classList.add('open');
}

function closeExtDetail() {
  document.getElementById('extDetailOverlay').classList.remove('open');
}

function togglePerm(el, idx, extId) {
  var d = _extRegistry[extId];
  if (!d || !d.permissions[idx] || !d.permissions[idx].modifiable) return;
  var p = d.permissions[idx];
  var isOn = el.classList.contains('on');
  if (isOn) {
    el.classList.remove('on');
    el.classList.add('off');
    p.level = 'denied';
    showToast('已撤销权限 · ' + p.name);
  } else {
    el.classList.remove('off');
    el.classList.add('on');
    p.level = 'granted';
    showToast('已授予权限 · ' + p.name);
  }
}

