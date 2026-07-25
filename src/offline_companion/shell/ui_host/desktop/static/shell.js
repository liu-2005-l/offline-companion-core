/* 桌面壳前端：通过 127.0.0.1 HTTP 宿主访问本地 API。 */

const chatEl = document.getElementById("chat");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const clearBtn = document.getElementById("clear-chat");
const memoryChk = document.getElementById("memory-on");
const memoryList = document.getElementById("memory-list");
const statusPrivacy = document.getElementById("status-privacy");
const statusModel = document.getElementById("status-model");
const statusSession = document.getElementById("status-session");
const personaLabel = document.getElementById("persona-label");
const routeBadge = document.getElementById("route-mode");
const routeReason = document.getElementById("route-reason");
const routeConsent = document.getElementById("route-consent");
const routeFallback = document.getElementById("route-fallback");
const consentModal = document.getElementById("consent-modal");
const consentTitle = document.getElementById("consent-title");
const consentBody = document.getElementById("consent-body");
const pluginList = document.getElementById("plugin-list");
const pluginFrame = document.getElementById("plugin-frame");
const pluginFrameTitle = document.getElementById("plugin-frame-title");
const pluginFrameStatus = document.getElementById("plugin-frame-status");

let memoryPage = 1;
const memoryPageSize = 15;
let memoryScrollPos = 0;
let activePluginSession = null;

async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `${path} -> ${res.status}`);
  return data;
}

function addMsg(cls, text) {
  const item = document.createElement("div");
  item.className = "msg " + cls;
  item.textContent = text;
  chatEl.appendChild(item);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function clearChatView() {
  chatEl.innerHTML = "";
}

function renderRouteState(state) {
  const routePanel = document.getElementById("route-panel");
  if (!state || Object.keys(state).length === 0) {
    routePanel.style.display = "none";
    return;
  }
  routePanel.style.display = "flex";
  const decision = state.route_decision || state;
  routeBadge.textContent = "route · " + (decision.mode || state.mode || "-");
  routeReason.textContent = decision.reason ? `reason · ${decision.reason}` : "reason · -";
  routeConsent.textContent = "consent · " + ((decision.requires_consent || state.requires_consent) ? "需要" : "不需要");
  routeFallback.textContent = "fallback · " + ((decision.fallback_chain || state.fallback_chain || []).join(" -> ") || "-");
}

async function refreshStatus() {
  const data = await apiGet("/api/status");
  memoryChk.checked = !!data.memory_on;
  statusPrivacy.textContent = "隐私 · " + data.privacy_mode;
  statusModel.textContent = "模型 · " + data.model_label;
  statusSession.textContent = "会话 · " + data.session_id.slice(0, 8) + "...";
  personaLabel.textContent = data.persona_name;
  renderRouteState(data.route_state || {});
}

function validatePluginMessageEnvelope(data) {
  if (!data || typeof data !== "object") return false;
  const required = ["type", "plugin_id", "session_id", "session_token", "request_id", "capability", "payload"];
  return required.every((key) => Object.prototype.hasOwnProperty.call(data, key));
}

async function destroyPluginSession() {
  if (!activePluginSession) return;
  try {
    await apiPost(`/api/plugins/session/${activePluginSession.session_id}/destroy`, {});
  } catch (err) {
    addMsg("system", "Plugin 会话销毁失败: " + err.message);
  } finally {
    activePluginSession = null;
    pluginFrame.removeAttribute("src");
    pluginFrameTitle.textContent = "未加载 Plugin";
    pluginFrameStatus.textContent = "待命";
  }
}

async function loadPlugin(pluginId, title) {
  await destroyPluginSession();
  const session = await apiPost("/api/plugins/session", { plugin_id: pluginId });
  activePluginSession = session;
  const params = new URLSearchParams({
    plugin_id: pluginId,
    session_id: session.session_id,
    session_token: session.session_token,
  });
  const sandbox = session.sandbox || "allow-scripts";
  if (sandbox.includes("allow-same-origin")) {
    throw new Error("安全违规：sandbox 包含 allow-same-origin");
  }
  pluginFrame.setAttribute("sandbox", sandbox);
  pluginFrame.src = `${session.frame_path}?${params.toString()}`;
  pluginFrameTitle.textContent = title;
  pluginFrameStatus.textContent = "沙箱已挂载";
}

async function refreshPlugins() {
  if (!pluginList) return;
  const data = await apiGet("/api/plugins");
  pluginList.innerHTML = "";
  (data.items || []).forEach((item) => {
    const card = document.createElement("div");
    card.className = "plugin-card-item";

    const title = document.createElement("h3");
    title.textContent = item.plugin_id;
    card.appendChild(title);

    const desc = document.createElement("p");
    desc.textContent = item.description || "";
    card.appendChild(desc);

    const meta = document.createElement("div");
    meta.className = "plugin-meta";
    [...(item.permissions || []), ...(item.capabilities || [])].forEach((text) => {
      const chip = document.createElement("span");
      chip.className = "plugin-chip";
      chip.textContent = text;
      meta.appendChild(chip);
    });
    card.appendChild(meta);

    const action = document.createElement("button");
    action.type = "button";
    action.className = "plugin-load-btn";
    action.textContent = "加载到沙箱";
    action.addEventListener("click", () => {
      loadPlugin(item.plugin_id, item.plugin_id).catch((err) => addMsg("system", "Plugin 加载失败: " + err.message));
    });
    card.appendChild(action);
    pluginList.appendChild(card);
  });
}

function memoryStatusBadge(status) {
  const badge = document.createElement("span");
  const invalid = status === "invalid";
  badge.className = "status-badge " + (invalid ? "invalid" : "active");
  badge.textContent = invalid ? "无效" : "有效";
  return badge;
}

async function refreshMemories() {
  if (!memoryList) return;
  memoryScrollPos = memoryList.scrollTop;
  const data = await apiGet(`/api/memories?page=${memoryPage}&page_size=${memoryPageSize}`);
  const grouped = data.grouped || {};
  const total = data.total || 0;
  const keys = Object.keys(grouped);
  if (keys.length === 0 && memoryPage > 1) {
    memoryPage -= 1;
    await refreshMemories();
    return;
  }

  memoryList.innerHTML = "";
  const pager = document.createElement("div");
  pager.className = "memory-pager";
  const navLeft = document.createElement("div");
  navLeft.className = "memory-pager-left";
  const prev = document.createElement("button");
  prev.type = "button";
  prev.className = "memory-page-btn";
  prev.textContent = "上一页";
  prev.disabled = memoryPage <= 1;
  prev.addEventListener("click", async () => {
    if (memoryPage > 1) {
      memoryPage -= 1;
      memoryScrollPos = 0;
      await refreshMemories();
    }
  });
  const next = document.createElement("button");
  next.type = "button";
  next.className = "memory-page-btn";
  next.textContent = "下一页";
  next.disabled = memoryPage * memoryPageSize >= total;
  next.addEventListener("click", async () => {
    if (memoryPage * memoryPageSize < total) {
      memoryPage += 1;
      memoryScrollPos = 0;
      await refreshMemories();
    }
  });
  navLeft.appendChild(prev);
  navLeft.appendChild(next);
  const pageInfo = document.createElement("div");
  pageInfo.className = "memory-page-info";
  pageInfo.textContent = `第 ${memoryPage} 页 / 每页 ${memoryPageSize} 条`;
  const totalInfo = document.createElement("div");
  totalInfo.className = "memory-page-info";
  totalInfo.textContent = `共 ${total} 条`;
  pager.appendChild(navLeft);
  pager.appendChild(pageInfo);
  pager.appendChild(totalInfo);
  memoryList.appendChild(pager);

  if (!keys.length) {
    const empty = document.createElement("div");
    empty.className = "memory-empty";
    empty.textContent = "暂无记忆。你可以直接说“记住我喜欢……”或“你以后叫……”";
    memoryList.appendChild(empty);
    return;
  }

  keys.forEach((groupKey) => {
    const group = document.createElement("div");
    group.className = "memory-group";
    const heading = document.createElement("div");
    heading.className = "memory-group-title";
    heading.textContent = groupKey;
    group.appendChild(heading);

    const table = document.createElement("div");
    table.className = "memory-table";
    const header = document.createElement("div");
    header.className = "memory-row memory-row-header";
    ["status", "id", "content", "memory_type", "source", "created_at", "modified_at", "metadata", "toggle", "delete"].forEach((name) => {
      const cell = document.createElement("div");
      cell.className = "memory-cell memory-cell-header";
      cell.textContent = name;
      header.appendChild(cell);
    });
    table.appendChild(header);

    (grouped[groupKey] || []).forEach((item) => {
      const row = document.createElement("div");
      const isInvalid = (item.status || "active") === "invalid";
      row.className = "memory-row" + (isInvalid ? " invalid" : "");
      const meta = item.meta || {};
      const cells = [
        item.status || "active",
        `#${item.id}`,
        item.content || item.body || "",
        item.memory_type || meta.memory_type || "",
        item.source || "",
        item.created_at || "",
        item.modified_at || "",
        JSON.stringify(item.metadata || meta || {}),
      ];
      cells.forEach((text, idx) => {
        const cell = document.createElement("div");
        cell.className = "memory-cell";
        if (idx === 0) {
          cell.appendChild(memoryStatusBadge(text));
        } else {
          cell.textContent = String(text ?? "");
        }
        row.appendChild(cell);
      });

      const toggleCell = document.createElement("div");
      toggleCell.className = "memory-cell memory-ops";
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "memory-op-btn";
      toggle.textContent = isInvalid ? "恢复" : "无效";
      toggle.addEventListener("click", async () => {
        try {
          const action = isInvalid ? "restore" : "invalidate";
          await apiPost(`/api/memories/${item.id}/${action}`, {});
          await refreshMemories();
        } catch (err) {
          addMsg("system", `记忆状态更新失败: ${err.message}`);
        }
      });
      toggleCell.appendChild(toggle);
      row.appendChild(toggleCell);

      const deleteCell = document.createElement("div");
      deleteCell.className = "memory-cell memory-ops";
      const permanentDelete = document.createElement("button");
      permanentDelete.type = "button";
      permanentDelete.className = "memory-op-btn memory-op-danger";
      permanentDelete.textContent = "删除";
      permanentDelete.addEventListener("click", async () => {
        if (!confirm(`永久删除记忆 #${item.id}？此操作不可恢复。`)) return;
        try {
          await apiPost(`/api/memories/${item.id}/delete`, {});
          await refreshMemories();
        } catch (err) {
          addMsg("system", `永久删除失败: ${err.message}`);
        }
      });
      deleteCell.appendChild(permanentDelete);
      row.appendChild(deleteCell);
      table.appendChild(row);
    });
    group.appendChild(table);
    memoryList.appendChild(group);
  });

  if (memoryScrollPos > 0) {
    memoryList.scrollTop = memoryScrollPos;
  }
}

document.getElementById("composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  const msg = inputEl.value.trim();
  if (!msg) return;
  addMsg("user", msg);
  inputEl.value = "";
  sendBtn.disabled = true;
  try {
    const data = await apiPost("/api/chat", { message: msg });
    if (data.memory_saved && data.memory_saved.length) {
      addMsg("system", "已保存记忆：" + data.memory_saved.join("，"));
      await refreshMemories();
    }
    addMsg(data.blocked ? "blocked" : "bot", data.reply || "（无回复）");
    await refreshStatus();
  } catch (err) {
    addMsg("system", "发送失败: " + err.message);
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
});

clearBtn.addEventListener("click", async () => {
  if (!confirm("清空当前会话的所有对话记录？\n（记忆库中的 #remember 内容不会删除）")) {
    return;
  }
  try {
    const data = await apiPost("/api/clear", {});
    clearChatView();
    addMsg("system", "已清空对话（删除 " + (data.deleted || 0) + " 条消息）");
  } catch (err) {
    addMsg("system", "清空失败: " + err.message);
  }
});

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.disabled) return;
    const panel = btn.dataset.panel;
    document.querySelectorAll(".nav-btn").forEach((item) => item.classList.toggle("active", item === btn));
    document.querySelectorAll(".workspace-view").forEach((view) => {
      view.classList.toggle("active", view.id === "view-" + panel);
    });
    if (panel === "memory") {
      memoryPage = 1;
      memoryScrollPos = 0;
      refreshMemories().catch((err) => addMsg("system", "记忆加载失败: " + err.message));
    }
    if (panel === "chat") {
      refreshStatus().catch((err) => addMsg("system", "状态刷新失败: " + err.message));
    }
    if (panel === "skill") {
      refreshPlugins().catch((err) => addMsg("system", "Plugin 列表加载失败: " + err.message));
    }
  });
});

window.addEventListener("message", async (event) => {
  if (!activePluginSession || !pluginFrame.contentWindow) return;
  if (event.source !== pluginFrame.contentWindow) return;
  const data = event.data;
  if (!validatePluginMessageEnvelope(data)) {
    addMsg("system", "已拦截非法 Plugin 消息包。");
    return;
  }
  if (data.session_id !== activePluginSession.session_id || data.plugin_id !== activePluginSession.plugin_id) {
    addMsg("system", "已拦截跨会话 Plugin 消息。");
    return;
  }
  if (data.session_token !== activePluginSession.session_token) {
    addMsg("system", "已拦截 session_token 不匹配的 Plugin 消息。");
    return;
  }
  try {
    const result = await apiPost("/api/plugins/message", data);
    pluginFrame.contentWindow.postMessage(result, "*");
    pluginFrameStatus.textContent = result.ok ? "Bridge 调用成功" : "Bridge 已拒绝请求";
    await refreshStatus();
  } catch (err) {
    pluginFrameStatus.textContent = "Bridge 调用失败";
    addMsg("system", "Plugin Bridge 调用失败: " + err.message);
  }
});

document.getElementById("consent-demo").addEventListener("click", async () => {
  try {
    const data = await apiGet("/api/consent-placeholder");
    consentTitle.textContent = data.title;
    consentBody.textContent = data.body;
    consentModal.classList.add("open");
  } catch (err) {
    addMsg("system", "Consent 占位加载失败: " + err.message);
  }
});

document.getElementById("consent-close").addEventListener("click", () => {
  consentModal.classList.remove("open");
});

window.addEventListener("beforeunload", () => {
  if (!activePluginSession) return;
  navigator.sendBeacon(
    `/api/plugins/session/${activePluginSession.session_id}/destroy`,
    new Blob([JSON.stringify({})], { type: "application/json" }),
  );
});

document.addEventListener("DOMContentLoaded", () => {
  refreshStatus()
    .then(() => refreshMemories())
    .catch((err) => addMsg("system", "状态加载失败: " + err.message))
    .finally(() => inputEl.focus());
});
