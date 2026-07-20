"use strict";

const $ = (id) => document.getElementById(id);

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
  const s = [];
  if ($("src-mail").checked) s.push("mail");
  if ($("src-teams").checked) s.push("teams");
  return s;
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
    const anyOk = Object.values(st.sources).some((s) => s.signedIn);
    $("statusDot").className = "dot " + (anyOk ? "ok" : "err");
    for (const key of ["mail", "teams"]) {
      const info = st.sources[key];
      const dot = $("dot-" + key);
      if (dot && info) dot.className = "dot " + (info.signedIn ? "ok" : "err");
    }
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
      li.innerHTML = `${d.title}<span class="fn">${d.filename}</span>`;
      li.onclick = () => loadDoc(d.filename);
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
  $("runHint").textContent = "추출 중… (MCP 검색 + LLM 생성)";
  try {
    const out = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        start: $("startDate").value || null,
        end: $("endDate").value || null,
        sources,
      }),
    });

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

function init() {
  $("startDate").value = todayISO(-1);
  $("endDate").value = todayISO(0);
  $("runBtn").onclick = runPipeline;
  $("commitBtn").onclick = commitDoc;
  refreshStatus();
  refreshDocs();
  setInterval(refreshStatus, 30000);
}

init();
