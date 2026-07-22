"use strict";

const $ = (id) => document.getElementById(id);

// The selectable MCP sources. Mail/Teams are Agent365 (one server each); Work IQ
// is a single unified endpoint with generic path-based tools. Keep in sync with
// the toggles in index.html and SOURCES in pipeline/config.py.
const SOURCE_KEYS = ["mail", "teams", "workiq"];

// Per-source "connected" (has a valid token) state, so we only (re)load a
// source's tool list when it first becomes connected.
const connectedState = { mail: false, teams: false, workiq: false };

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

function log(msg, cls) {
  const el = $("log");
  const line = document.createElement("div");
  if (cls) line.className = cls;
  line.textContent = msg;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function selectedSources() {
  return SOURCE_KEYS.filter((key) => {
    const el = $("src-" + key);
    return el && el.checked;
  });
}

function todayISO(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

async function refreshStatus() {
  try {
    const st = await api("/api/status");
    $("llmChip").textContent = `LLM: ${st.llm || "미설정"}`;
    $("authChip").textContent = `auth: ${st.authMode}`;
    const signedIn = Boolean(st.signedIn);
    const anyConnected = Object.values(st.sources).some((s) => s.signedIn);
    $("statusDot").className = "dot " + (anyConnected ? "ok" : signedIn ? "err" : "");

    for (const key of SOURCE_KEYS) {
      const info = st.sources[key] || {};
      const dot = $("dot-" + key);
      if (dot) dot.className = "dot " + (info.signedIn ? "ok" : signedIn ? "err" : "");

      // Per-source "연결" link: shown once signed in overall but this resource
      // isn't consented/connected yet (incremental consent).
      const connect = $("connect-" + key);
      if (connect) {
        connect.href = "/auth/login?source=" + key;
        connect.hidden = !signedIn || Boolean(info.signedIn);
      }

      // Load the tool list the moment a checked source becomes connected.
      const nowConnected = Boolean(info.signedIn);
      if (nowConnected && !connectedState[key] && $("src-" + key).checked) {
        loadTools(key);
      }
      if (!nowConnected) $("tools-" + key).hidden = true;
      connectedState[key] = nowConnected;
    }

    const user = st.user || {};
    $("userLabel").textContent = signedIn ? user.name || user.username || "로그인됨" : "";
    $("userLabel").hidden = !signedIn;
    $("loginBtn").hidden = signedIn;
    $("logoutBtn").hidden = !signedIn;
  } catch (e) {
    $("statusDot").className = "dot err";
  }
}

async function refreshDocs() {
  try {
    const { docs } = await api("/api/docs");
    const ul = $("docList");
    ul.innerHTML = "";
    if (!docs.length) {
      ul.innerHTML = '<li class="sub">아직 문서가 없습니다.</li>';
      return;
    }
    for (const d of docs) {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.className = "doc-label";
      label.innerHTML = `${d.title}<span class="fn">${d.filename}</span>`;
      label.onclick = () => loadDoc(d.filename);
      const del = document.createElement("button");
      del.className = "doc-del";
      del.type = "button";
      del.title = "문서 삭제";
      del.textContent = "🗑";
      del.onclick = (e) => {
        e.stopPropagation();
        deleteDoc(d.filename, d.title);
      };
      li.appendChild(label);
      li.appendChild(del);
      ul.appendChild(li);
    }
  } catch (e) {
    /* ignore */
  }
}

async function loadDoc(filename) {
  try {
    const { markdown } = await api("/api/docs/" + encodeURIComponent(filename));
    $("editor").value = markdown;
    $("slug").value = filename.replace(/\.md$/, "").replace(/^\d{4}-\d{2}-\d{2}-/, "");
    $("commitMsg").value = `docs(wiki): update ${filename}`;
    $("commitBtn").disabled = false;
    $("draftMeta").textContent = `불러옴: ${filename}`;
  } catch (e) {
    log("문서 로드 실패: " + e.message, "err");
  }
}

async function deleteDoc(filename, title) {
  const name = title ? `${title}\n(${filename})` : filename;
  if (!confirm(`이 위키 문서를 삭제하고 삭제 커밋을 만들까요?\n\n${name}`)) return;
  try {
    const out = await api("/api/docs/" + encodeURIComponent(filename), { method: "DELETE" });
    const c = out.commit || null;
    if (c && c.committed) {
      log(`삭제 + 커밋 완료: ${filename}\n${c.output || ""}`, "ok");
    } else if (c) {
      log(`삭제됨 (커밋할 변경 없음): ${filename} — ${c.output || ""}`, "ok");
    } else {
      log(`삭제됨: ${filename}`, "ok");
    }
    // If the editor is currently showing the deleted doc, clear it.
    if ($("draftMeta").textContent.includes(filename)) {
      $("editor").value = "";
      $("commitBtn").disabled = true;
      $("draftMeta").textContent = "";
    }
    refreshDocs();
  } catch (e) {
    log("문서 삭제 실패: " + e.message, "err");
  }
}

async function runPipeline() {
  const query = $("query").value.trim();
  if (!query) {
    $("runHint").textContent = "질의를 입력하세요.";
    return;
  }
  const sources = selectedSources();
  if (!sources.length) {
    $("runHint").textContent = "소스를 하나 이상 선택하세요.";
    return;
  }
  $("runBtn").disabled = true;
  $("runHint").textContent = "추출 시작…";
  log("추출 시작…", "ok");
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        start: $("startDate").value || null,
        end: $("endDate").value || null,
        sources,
      }),
    });

    // Pre-stream validation errors come back as plain JSON (non-200).
    const ctype = res.headers.get("content-type") || "";
    if (!ctype.includes("text/event-stream")) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `${res.status} ${res.statusText}`);
    }

    // Read the Server-Sent Events stream and surface progress live.
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let finalResult = null;
    let streamErr = null;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!dataLine) continue;
        let evt;
        try {
          evt = JSON.parse(dataLine.slice(5).trim());
        } catch (_) {
          continue;
        }
        if (evt.type === "progress") {
          $("runHint").textContent = evt.message;
          log("… " + evt.message);
        } else if (evt.type === "error") {
          streamErr = evt.error;
        } else if (evt.type === "result") {
          finalResult = evt;
        }
      }
    }

    if (streamErr) throw new Error(streamErr);
    if (!finalResult) throw new Error("결과를 받지 못했습니다.");

    const out = finalResult;
    const tokenErrs = out.tokenErrors || {};
    const srcErrs = out.sourceErrors || {};
    Object.entries(tokenErrs).forEach(([k, v]) => log(`[${k}] ${v}`, "err"));
    Object.entries(srcErrs).forEach(([k, v]) => log(`[${k}] ${v}`, "err"));

    if (!out.doc) {
      $("runHint").textContent =
        "초안을 생성하지 못했습니다. 인증/소스 상태를 확인하세요 (로그 참고).";
      return;
    }
    $("editor").value = out.doc.markdown;
    $("slug").value = out.doc.slug || "wiki-doc";
    $("commitMsg").value = `docs(wiki): add ${out.doc.title}`;
    $("commitBtn").disabled = false;
    $("draftMeta").textContent = `${out.doc.title} · ${out.start}..${out.end} · ${out.sources.join(", ")}`;
    $("runHint").textContent = "초안 생성 완료. 검토 후 커밋하세요.";
    log("초안 생성 완료: " + out.doc.title, "ok");
  } catch (e) {
    $("runHint").textContent = "실패: " + e.message;
    log("추출 실패: " + e.message, "err");
  } finally {
    $("runBtn").disabled = false;
  }
}

async function commitDoc() {
  const markdown = $("editor").value;
  if (!markdown.trim()) return;
  $("commitBtn").disabled = true;
  try {
    const out = await api("/api/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        markdown,
        slug: $("slug").value.trim() || "wiki-doc",
        message: $("commitMsg").value.trim() || null,
      }),
    });
    const c = out.commit || {};
    if (c.committed) {
      log(`커밋 완료: ${out.filename}\n${c.output}`, "ok");
    } else if (c.ok) {
      log(`저장됨(변경 없음): ${out.filename} — ${c.output}`, "ok");
    } else {
      log(`커밋 실패: ${c.output}`, "err");
    }
    await refreshDocs();
  } catch (e) {
    log("커밋 실패: " + e.message, "err");
  } finally {
    $("commitBtn").disabled = false;
  }
}

// ---------- Microsoft 로그인 / 로그아웃 ----------
function showModal(id, show) {
  $(id).hidden = !show;
}

// Interactive user login (Authorization Code flow): full-page redirect to
// Entra, then back to /auth/callback. Mail establishes the account; Teams is an
// incremental "연결" link once signed in.
function startLogin() {
  window.location.href = "/auth/login?source=mail";
}

async function doLogout() {
  $("logoutBtn").disabled = true;
  try {
    await api("/api/logout", { method: "POST" });
    for (const key of SOURCE_KEYS) {
      $("tools-" + key).hidden = true;
      connectedState[key] = false;
    }
    log("로그아웃 완료", "ok");
    window.location.reload();
  } catch (e) {
    log("로그아웃 실패: " + e.message, "err");
    $("logoutBtn").disabled = false;
  }
}

// ---------- MCP 툴 탐색 / 직접 호출 ----------
let currentTool = null;

async function loadTools(key) {
  const group = $("tools-" + key);
  const list = $("tool-list-" + key);
  const count = $("tools-" + key + "-count");
  group.hidden = false;
  count.textContent = "";
  list.innerHTML = '<li class="loading">불러오는 중…</li>';
  try {
    const { tools } = await api("/api/tools/" + key);
    count.textContent = `(${tools.length})`;
    list.innerHTML = "";
    if (!tools.length) {
      list.innerHTML = '<li class="empty">툴이 없습니다.</li>';
      return;
    }
    for (const t of tools) {
      const li = document.createElement("li");
      const nm = document.createElement("span");
      nm.className = "tname";
      nm.textContent = t.name;
      const ds = document.createElement("span");
      ds.className = "tdesc";
      ds.textContent = t.description || "";
      li.appendChild(nm);
      li.appendChild(ds);
      li.title = t.description || t.name;
      li.onclick = () => openToolModal(key, t);
      list.appendChild(li);
    }
  } catch (e) {
    list.innerHTML = `<li class="empty">${e.message}</li>`;
  }
}

function syncTools(key) {
  if ($("src-" + key).checked && connectedState[key]) loadTools(key);
  else $("tools-" + key).hidden = true;
}

function schemaFields(schema) {
  const props = (schema && schema.properties) || {};
  const required = (schema && schema.required) || [];
  return Object.entries(props).map(([name, def]) => ({
    name,
    type: (def && def.type) || "string",
    desc: (def && (def.description || def.title)) || "",
    enumVals: def && def.enum,
    required: required.includes(name),
  }));
}

function openToolModal(source, tool) {
  currentTool = { source, tool: tool.name };
  $("toolTitle").textContent = `${source} · ${tool.name}`;
  $("toolDesc").textContent = tool.description || "";
  $("toolState").textContent = "";
  $("toolResult").textContent = "";
  const form = $("toolForm");
  form.innerHTML = "";
  const fields = schemaFields(tool.inputSchema);
  if (!fields.length) {
    form.innerHTML = '<p class="tool-empty">파라미터가 없습니다. 바로 호출하세요.</p>';
  } else {
    for (const f of fields) {
      const wrap = document.createElement("div");
      wrap.className = "tool-field";
      const label = document.createElement("label");
      label.innerHTML =
        `${f.name}${f.required ? ' <span class="req">*</span>' : ""}` +
        ` <span class="ftype">(${f.type})</span>`;
      wrap.appendChild(label);
      let input;
      if (Array.isArray(f.enumVals) && f.enumVals.length) {
        input = document.createElement("select");
        const o0 = document.createElement("option");
        o0.value = "";
        o0.textContent = "(선택 안 함)";
        input.appendChild(o0);
        for (const v of f.enumVals) {
          const o = document.createElement("option");
          o.value = v;
          o.textContent = v;
          input.appendChild(o);
        }
      } else if (f.type === "boolean") {
        input = document.createElement("select");
        for (const v of ["", "true", "false"]) {
          const o = document.createElement("option");
          o.value = v;
          o.textContent = v === "" ? "(선택 안 함)" : v;
          input.appendChild(o);
        }
      } else if (f.type === "object" || f.type === "array") {
        input = document.createElement("textarea");
        input.placeholder = f.type === "array" ? '예: ["a", "b"]' : '예: {"key": "value"}';
      } else {
        input = document.createElement("input");
        input.type = "text";
      }
      input.dataset.fname = f.name;
      input.dataset.ftype = f.type;
      wrap.appendChild(input);
      if (f.desc) {
        const hint = document.createElement("div");
        hint.className = "sub";
        hint.style.fontSize = "11px";
        hint.textContent = f.desc;
        wrap.appendChild(hint);
      }
      form.appendChild(wrap);
    }
  }
  showModal("toolModal", true);
}

function collectToolArgs() {
  const args = {};
  const inputs = $("toolForm").querySelectorAll("[data-fname]");
  for (const el of inputs) {
    const name = el.dataset.fname;
    const type = el.dataset.ftype;
    const raw = el.value;
    if (raw === "" || raw == null) continue; // 비어있는(선택) 필드는 생략
    if (type === "number" || type === "integer") {
      const n = Number(raw);
      args[name] = Number.isNaN(n) ? raw : n;
    } else if (type === "boolean") {
      args[name] = raw === "true";
    } else if (type === "object" || type === "array") {
      try {
        args[name] = JSON.parse(raw);
      } catch (e) {
        throw new Error(`'${name}' 값은 올바른 JSON이어야 합니다.`);
      }
    } else {
      args[name] = raw;
    }
  }
  return args;
}

async function callTool() {
  if (!currentTool) return;
  let args;
  try {
    args = collectToolArgs();
  } catch (e) {
    $("toolState").textContent = e.message;
    return;
  }
  $("toolCallBtn").disabled = true;
  $("toolState").textContent = "호출 중…";
  $("toolResult").textContent = "";
  try {
    const out = await api("/api/tools/call", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: currentTool.source, tool: currentTool.tool, args }),
    });
    $("toolState").textContent = out.isError ? "결과 (오류 포함):" : "결과:";
    $("toolResult").textContent = out.text || "(빈 응답)";
  } catch (e) {
    $("toolState").textContent = "호출 실패: " + e.message;
  } finally {
    $("toolCallBtn").disabled = false;
  }
}

function init() {
  $("startDate").value = todayISO(-1);
  $("endDate").value = todayISO(0);
  $("runBtn").onclick = runPipeline;
  $("commitBtn").onclick = commitDoc;
  $("loginBtn").onclick = startLogin;
  $("logoutBtn").onclick = doLogout;
  $("toolClose").onclick = () => showModal("toolModal", false);
  $("toolCallBtn").onclick = callTool;
  for (const key of SOURCE_KEYS) {
    $("src-" + key).addEventListener("change", () => syncTools(key));
  }
  $("toolModal").addEventListener("click", (e) => {
    if (e.target === $("toolModal")) showModal("toolModal", false);
  });
  refreshStatus();
  refreshDocs();
  setInterval(refreshStatus, 30000);
}

init();
