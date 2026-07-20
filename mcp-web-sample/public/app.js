const $ = (id) => document.getElementById(id);
const SOURCE_KEYS = ["mail", "teams"];
let allTools = [];
let signedIn = false;
const history = [];

function loadSelectedSources() {
  try {
    const saved = JSON.parse(localStorage.getItem("mcpSelectedSources"));
    if (Array.isArray(saved) && saved.some((k) => SOURCE_KEYS.includes(k))) {
      return saved.filter((k) => SOURCE_KEYS.includes(k));
    }
  } catch {
    /* ignore */
  }
  return [...SOURCE_KEYS]; // default: both enabled
}

function saveSelectedSources(keys) {
  localStorage.setItem("mcpSelectedSources", JSON.stringify(keys));
}

function selectedSources() {
  return SOURCE_KEYS.filter((k) => $(`src-${k}`).checked);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function setStatus(s) {
  signedIn = Boolean(s.signedIn);
  const dot = $("statusDot");
  const anyConnected = SOURCE_KEYS.some((k) => s.sources?.[k]?.connected);
  dot.className = "dot" + (anyConnected ? " ok" : signedIn ? " err" : "");

  if (s.signedIn) {
    $("userLabel").textContent = s.user?.name || s.user?.username || "로그인됨";
    $("loginBtn").hidden = true;
    $("logoutBtn").hidden = false;
  } else {
    $("userLabel").textContent = "로그인 필요";
    $("loginBtn").hidden = false;
    $("logoutBtn").hidden = true;
  }

  const selected = new Set(selectedSources());
  let selectedTools = 0;
  SOURCE_KEYS.forEach((k) => {
    const src = s.sources?.[k] || {};
    if (selected.has(k)) selectedTools += src.toolCount || 0;
    const sdot = $(`dot-${k}`);
    sdot.className = "dot" + (src.connected ? " ok" : signedIn ? " err" : "");
    const connectLink = $(`connect-${k}`);
    // Show the per-source "connect" link only once the user is signed in
    // overall but this specific resource hasn't been consented/connected yet
    // (incremental consent — each MCP is a different OAuth resource).
    connectLink.hidden = !signedIn || src.connected;
    const toggle = document.querySelector(`.source-toggle[data-source="${k}"]`);
    toggle.classList.toggle("disabled", signedIn && !src.connected);
  });

  // Badge reflects only the currently CHECKED sources, matching what's
  // actually visible in the sidebar list below — not every connected source.
  $("toolCount").textContent = selectedTools;
  $("llmHint").textContent = s.llm
    ? `자연어 에이전트: ${s.llm} 사용 중`
    : "LLM 미설정 — 채팅창은 안내만 표시됩니다. 좌측 도구를 클릭해 직접 실행하세요.";

  const gate = $("loginGate");
  if (!s.signedIn) {
    gate.hidden = false;
  } else {
    gate.hidden = true;
    if (!anyConnected) {
      addMessage(
        "error",
        "로그인은 됐지만 선택된 MCP에 연결되지 않았습니다. 각 소스의 '연결' 링크로 권한을 동의하세요."
      );
    }
  }
}

function renderTools(tools) {
  const filter = $("toolFilter").value.toLowerCase();
  const selected = new Set(selectedSources());
  const list = $("toolList");
  list.innerHTML = "";
  tools
    .filter((t) => selected.has(t.source))
    .filter((t) => t.name.toLowerCase().includes(filter) || (t.description || "").toLowerCase().includes(filter))
    .forEach((t) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="tname">[${t.sourceLabel}] ${t.name}</span><span class="tdesc">${t.description || ""}</span>`;
      li.onclick = () => openToolModal(t);
      list.appendChild(li);
    });
}

function addMessage(role, text, trace) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.textContent = text;
  if (trace && trace.length) {
    const wrap = document.createElement("div");
    wrap.className = "trace";
    trace.forEach((step) => {
      const d = document.createElement("details");
      const label = step.source ? `[${step.source}] ${step.tool}` : step.tool;
      d.innerHTML =
        `<summary>🔧 ${label}</summary>` +
        `<pre>args: ${JSON.stringify(step.args, null, 2)}\n\n${step.result}</pre>`;
      wrap.appendChild(d);
    });
    div.appendChild(wrap);
  }
  $("messages").appendChild(div);
  $("messages").scrollTop = $("messages").scrollHeight;
  return div;
}

async function refreshTools() {
  if (!signedIn) return;
  const sources = selectedSources();
  if (sources.length === 0) {
    allTools = [];
    renderTools(allTools);
    $("toolCount").textContent = 0;
    return;
  }
  try {
    const { tools, errors } = await api(`/api/tools?sources=${sources.join(",")}`);
    allTools = tools;
    renderTools(tools);
    // Keep the badge in sync with the checkbox selection, not just the
    // initial /api/status snapshot (which doesn't re-run on checkbox toggle).
    $("toolCount").textContent = tools.length;
    Object.entries(errors || {}).forEach(([src, msg]) => addMessage("error", `${src}: ${msg}`));
  } catch (err) {
    addMessage("error", "도구 목록 불러오기 실패: " + err.message);
  }
}

// ---- Source checkboxes ----
SOURCE_KEYS.forEach((k) => {
  $(`src-${k}`).addEventListener("change", () => {
    const selected = selectedSources();
    if (selected.length === 0) {
      // Never allow zero sources selected — revert this toggle.
      $(`src-${k}`).checked = true;
      addMessage("error", "적어도 하나의 MCP는 선택되어 있어야 합니다.");
      return;
    }
    saveSelectedSources(selected);
    refreshTools();
    // If the open direct-tool modal belongs to a source that was just
    // deselected, close it — otherwise the user could still click "실행"
    // and call a tool from a source that's supposed to be inactive.
    if (currentTool && !selected.includes(currentTool.source)) {
      $("toolModal").hidden = true;
      currentTool = null;
    }
  });
});

// ---- Chat ----
$("chatForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("chatInput");
  const message = input.value.trim();
  if (!message) return;
  if (!signedIn) {
    addMessage("error", "먼저 상단의 'Microsoft 로그인'을 눌러 로그인하세요.");
    return;
  }
  const sources = selectedSources();
  if (sources.length === 0) {
    addMessage("error", "상단에서 사용할 MCP(Mail/Teams)를 하나 이상 선택하세요.");
    return;
  }
  input.value = "";
  addMessage("user", message);
  history.push({ role: "user", content: message });

  const pending = addMessage("assistant", "…");
  try {
    const data = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: history.slice(-10), sources }),
    });
    pending.remove();
    addMessage("assistant", data.answer, data.trace);
    history.push({ role: "assistant", content: data.answer });
    Object.entries(data.sourceErrors || {}).forEach(([src, msg]) => addMessage("error", `${src}: ${msg}`));
  } catch (err) {
    pending.remove();
    addMessage("error", err.message);
  }
});

// ---- Direct tool modal ----
let currentTool = null;
function openToolModal(tool) {
  currentTool = tool;
  $("toolModalName").textContent = `[${tool.sourceLabel}] ${tool.name}`;
  $("toolModalDesc").textContent = tool.description || "";
  $("toolArgs").value = JSON.stringify(exampleArgs(tool), null, 2);
  $("toolResult").textContent = "";
  $("toolModal").hidden = false;
}
function exampleArgs(tool) {
  const props = tool.inputSchema?.properties || {};
  const out = {};
  Object.keys(props).forEach((k) => {
    out[k] = props[k].type === "number" ? 0 : "";
  });
  return out;
}
$("toolModalClose").onclick = () => ($("toolModal").hidden = true);
$("toolRun").onclick = async () => {
  if (!signedIn) {
    $("toolResult").textContent = "먼저 상단의 'Microsoft 로그인'을 눌러 로그인하세요.";
    return;
  }
  if (!currentTool) {
    $("toolResult").textContent = "먼저 좌측 목록에서 도구를 선택하세요.";
    return;
  }
  let args;
  try {
    args = JSON.parse($("toolArgs").value || "{}");
  } catch {
    $("toolResult").textContent = "arguments가 올바른 JSON이 아닙니다.";
    return;
  }
  $("toolResult").textContent = "실행 중…";
  try {
    const data = await api("/api/tool", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: currentTool.source, name: currentTool.name, args }),
    });
    $("toolResult").textContent = data.text || JSON.stringify(data.result, null, 2);
  } catch (err) {
    $("toolResult").textContent = "오류: " + err.message;
  }
};

$("toolFilter").addEventListener("input", () => renderTools(allTools));
$("logoutBtn").addEventListener("click", async () => {
  await api("/auth/logout", { method: "POST" });
  location.reload();
});

// ---- Init ----
(async function init() {
  const selected = loadSelectedSources();
  SOURCE_KEYS.forEach((k) => {
    $(`src-${k}`).checked = selected.includes(k);
  });
  try {
    const status = await api("/api/status");
    setStatus(status);
    await refreshTools();
  } catch (err) {
    addMessage("error", "초기화 실패: " + err.message);
  }
})();
