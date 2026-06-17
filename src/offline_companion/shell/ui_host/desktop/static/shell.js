/* 桌面壳：经内嵌 127.0.0.1 HTTP 调用 API（与 Flask 开发宿主同路径） */

const chatEl = document.getElementById("chat");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const clearBtn = document.getElementById("clear-chat");
const memoryChk = document.getElementById("memory-on");
const statusPrivacy = document.getElementById("status-privacy");
const statusModel = document.getElementById("status-model");
const statusSession = document.getElementById("status-session");
const personaLabel = document.getElementById("persona-label");
const consentModal = document.getElementById("consent-modal");
const consentTitle = document.getElementById("consent-title");
const consentBody = document.getElementById("consent-body");

async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

function addMsg(cls, text) {
  const d = document.createElement("div");
  d.className = "msg " + cls;
  d.textContent = text;
  chatEl.appendChild(d);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function clearChatView() {
  chatEl.innerHTML = "";
}

async function refreshStatus() {
  const data = await apiGet("/api/status");
  memoryChk.checked = !!data.memory_on;
  statusPrivacy.textContent = "隐私 · " + data.privacy_mode;
  statusModel.textContent = "模型 · " + data.model_label;
  statusSession.textContent = "会话 · " + data.session_id.slice(0, 8) + "…";
  personaLabel.textContent = data.persona_name;
}

memoryChk.addEventListener("change", async () => {
  try {
    await apiPost("/api/memory", { enabled: memoryChk.checked });
    addMsg("system", memoryChk.checked ? "记忆已开启" : "记忆已关闭");
  } catch (err) {
    addMsg("system", "记忆开关失败: " + err.message);
  }
});

document.getElementById("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = inputEl.value.trim();
  if (!msg) return;
  addMsg("user", msg);
  inputEl.value = "";
  sendBtn.disabled = true;
  try {
    const data = await apiPost("/api/chat", { message: msg });
    if (data.memory_saved && data.memory_saved.length) {
      addMsg("system", "已保存记忆：" + data.memory_saved.join("；"));
    }
    if (data.memory_recall_count > 0) {
      addMsg("system", "本轮召回记忆 " + data.memory_recall_count + " 条");
    }
    const cls = data.blocked ? "blocked" : "bot";
    addMsg(cls, data.reply || "（无回复）");
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
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".panel-section").forEach((sec) => {
      sec.classList.toggle("active", sec.id === "panel-" + panel);
    });
  });
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

document.addEventListener("DOMContentLoaded", () => {
  refreshStatus()
    .catch((err) => addMsg("system", "状态加载失败: " + err.message))
    .finally(() => inputEl.focus());
});
