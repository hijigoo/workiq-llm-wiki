const $ = (id) => document.getElementById(id);
let allTools = [];
let signedIn = false;
const history = [];

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function setStatus(s) {
  signedIn = Boolean(s.signedIn);
  $("serverUrl").textContent = s.mcpServerUrl || "";
  const dot = $("statusDot");
  dot.className = "dot" + (s.mcpConnected ? " ok" : s.signedIn ? " err" : "");

  if (s.signedIn) {
    $("userLabel").textContent = s.user?.name || s.user?.username || "로그인됨";
    $("loginBtn").hidden = true;
    $("logoutBtn").hidden = false;
  } else {
    $("userLabel").textContent = "로그인 필요";
    $("loginBtn").hidden = false;
    $("logoutBtn").hidden = true;
  }

  $("toolCount").textContent = s.toolCount || 0;
  $("llmHint").textContent = s.llm
    ? `자연어 에이전트: ${s.llm} 사용 중`
    : "LLM 미설정 — 채팅창은 안내만 표시됩니다. 좌측 도구를 클릭해 직접 실행하세요.";
  if (s.mcpError) addMessage("error", `MCP 오류: ${s.mcpError}`);

  // Prominent gate when not signed in.
  const gate = $("loginGate");
  if (!s.signedIn) {
    gate.hidden = false;
  } else {
    gate.hidden = true;
    if (!s.mcpConnected) {
      addMessage(
        "error",
        "로그인은 됐지만 Teams MCP에 연결되지 않았습니다. 권한/동의 상태를 확인하세요."
      );
    }
  }
}

function renderTools(tools) {
  const filter = $("toolFilter").value.toLowerCase();
  const list = $("toolList");
  list.innerHTML = "";
  tools
    .filter((t) => t.name.toLowerCase().includes(filter) || (t.description || "").toLowerCase().includes(filter))
    .forEach((t) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="tname">${t.name}</span><span class="tdesc">${t.description || ""}</span>`;
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
      d.innerHTML =
        `<summary>🔧 ${step.tool}</summary>` +
        `<pre>args: ${JSON.stringify(step.args, null, 2)}\n\n${step.result}</pre>`;
      wrap.appendChild(d);
    });
    div.appendChild(wrap);
  }
  $("messages").appendChild(div);
  $("messages").scrollTop = $("messages").scrollHeight;
  return div;
}

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
  input.value = "";
  addMessage("user", message);
  history.push({ role: "user", content: message });

  const pending = addMessage("assistant", "…");
  try {
    const data = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: history.slice(-10) }),
    });
    pending.remove();
    addMessage("assistant", data.answer, data.trace);
    history.push({ role: "assistant", content: data.answer });
  } catch (err) {
    pending.remove();
    addMessage("error", err.message);
  }
});

// ---- Direct tool modal ----
let currentTool = null;
function openToolModal(tool) {
  currentTool = tool;
  $("toolModalName").textContent = tool.name;
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
      body: JSON.stringify({ name: currentTool.name, args }),
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
  try {
    const status = await api("/api/status");
    setStatus(status);
    if (status.signedIn && status.mcpConnected) {
      const { tools } = await api("/api/tools");
      allTools = tools;
      renderTools(tools);
    }
  } catch (err) {
    addMessage("error", "초기화 실패: " + err.message);
  }
})();
