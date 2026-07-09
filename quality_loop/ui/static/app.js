const views = ["feedback", "architecture", "runs", "sessions", "qa", "improvements"];
let exportContext = null;
let pollTimer = null;

function esc(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtDate(value) {
  return fmtDateTime(value);
}

function fmtDateTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function fmtMessageTs(value) {
  if (value == null || value === "") return null;
  let d;
  if (typeof value === "number") {
    const n = value;
    if (n > 1e15) d = new Date(n / 1000);
    else if (n > 1e12) d = new Date(n);
    else if (n > 1e9) d = new Date(n * 1000);
    else return null;
  } else {
    d = new Date(value);
  }
  if (Number.isNaN(d.getTime())) return null;
  const now = Date.now();
  const diffMin = Math.round((now - d.getTime()) / 60000);
  const absolute = d.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  if (diffMin < 1) return `${absolute} · az önce`;
  if (diffMin < 60) return `${absolute} · ${diffMin} dk önce`;
  if (diffMin < 1440) return `${absolute} · ${Math.round(diffMin / 60)} sa önce`;
  return absolute;
}

function shortSessionId(id) {
  const s = String(id || "");
  if (s.length <= 18) return s;
  return `${s.slice(0, 10)}…${s.slice(-6)}`;
}

function clipText(text, max = 100) {
  const t = String(text || "").replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

function getApiConfig() {
  const base = (localStorage.getItem("ql_api_base") || "").replace(/\/$/, "");
  const token = localStorage.getItem("ql_api_token") || "";
  return { base, token };
}

function setApiConfig(base, token) {
  localStorage.setItem("ql_api_base", base.trim());
  localStorage.setItem("ql_api_token", token.trim());
}

async function api(path) {
  const { base, token } = getApiConfig();
  const rel = path.startsWith("/") ? path.slice(1) : path;
  const url = base ? `${base.replace(/\/$/, "")}/${rel}` : rel;
  const headers = {};
  if (token) headers["X-Quality-Loop-Token"] = token;
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return res.json();
}

function setView(name) {
  views.forEach((v) => {
    document.getElementById(`view-${v}`).classList.toggle("hidden", v !== name);
    document.querySelector(`.nav-btn[data-view="${v}"]`)?.classList.toggle("active", v === name);
  });
}

function severityChip(sev) {
  const s = String(sev || "low").toLowerCase();
  return `<span class="chip ${esc(s)}">${esc(s)}</span>`;
}

function renderScores(qa) {
  const scores = qa?.scores || {};
  const keys = [
    ["context_management", "Bağlam"],
    ["tool_usage", "Tool"],
    ["response_quality", "Yanıt"],
    ["error_handling", "Hata"],
  ];
  const scoreClass = (v) => {
    if (v == null || v === "" || Number.isNaN(Number(v))) return "score-na";
    const n = Number(v);
    if (n <= 3) return "score-low";
    if (n <= 6) return "score-mid";
    return "score-high";
  };
  const fmtScore = (v) => {
    if (v == null || v === "" || Number.isNaN(Number(v))) return "—";
    return `${Number(v)}/10`;
  };
  return `<div class="score-grid">${keys
    .map(
      ([k, label]) => `
      <div class="score-box ${scoreClass(scores[k])}">
        <div class="num">${esc(fmtScore(scores[k]))}</div>
        <div class="lbl">${esc(label)}</div>
      </div>`
    )
    .join("")}</div>`;
}

function renderIssues(issues, { compact = false } = {}) {
  if (!issues?.length) return `<div class="empty">Sorun kaydı yok</div>`;
  return `<div class="issue-list">${issues
    .map((issue) => {
      const hint = issue.fix_hint
        ? `<p class="issue-fix"><strong>Fix:</strong> ${esc(issue.fix_hint)}</p>`
        : "";
      const evidence = issue.evidence
        ? compact
          ? `<details class="issue-evidence-fold"><summary>Kanıt</summary><p>${esc(issue.evidence)}</p></details>`
          : `<details class="issue-evidence-fold" open><summary>Kanıt</summary><p>${esc(issue.evidence)}</p></details>`
        : "";
      const idx = issue.message_index;
      const idxLabel = Array.isArray(idx)
        ? idx.map((n) => `#${n}`).join(", ")
        : idx != null
          ? `#${idx}`
          : "?";
      return `
      <article class="issue-card ${esc(String(issue.severity || "low").toLowerCase())}">
        <div class="issue-card-head">
          ${severityChip(issue.severity)}
          <span class="issue-category">${esc(issue.category || "issue")}</span>
          <span class="issue-idx muted-small">mesaj ${esc(idxLabel)}</span>
        </div>
        <p class="issue-desc">${esc(issue.description || "")}</p>
        ${evidence}
        ${hint}
      </article>`;
    })
    .join("")}</div>`;
}

function renderFixes(fixes, { showScenarios = true } = {}) {
  const applied = fixes?.fixes_applied || [];
  const skipped = fixes?.fixes_skipped || [];
  const scenarios = fixes?.next_test_scenarios || [];
  if (!applied.length && !skipped.length) return `<div class="empty">Fix kaydı yok</div>`;
  const appliedHtml = applied
    .map((f) => {
      const deploy = String(f.deploy_status || "unknown").toLowerCase();
      const deployChip =
        deploy === "skipped" || deploy === "not_applied"
          ? `<span class="chip warn">öneri — uygulanmadı</span>`
          : deploy === "deployed" || deploy === "applied"
            ? `<span class="chip success">uygulandı</span>`
            : `<span class="chip">${esc(f.deploy_status || "unknown")}</span>`;
      return `
    <article class="fix-card">
      <div class="fix-card-head">
        ${deployChip}
        <code class="fix-file">${esc(f.file || "?")}</code>
      </div>
      <p class="fix-desc">${esc(f.issue_fixed || "")}</p>
    </article>`;
    })
    .join("");
  const skippedHtml = skipped
    .map((s) => `<div class="chip skip">${esc(s)}</div>`)
    .join("");
  const scenarioHtml =
    showScenarios && scenarios.length
      ? `<div class="fix-scenarios">
          <h5 class="muted-small">Sonraki test senaryoları</h5>
          <ul>${scenarios.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
        </div>`
      : "";
  const note =
    applied.some((f) => String(f.deploy_status || "").toLowerCase() === "skipped")
      ? `<p class="fix-note muted-small">Coding Agent fix önerdi; sunucuda <code>QUALITY_LOOP_ALLOW_GIT_PUSH</code> kapalı olduğu için dosyalara yazılmadı.</p>`
      : "";
  return `${note}${appliedHtml}${skipped.length ? `<div class="meta-block"><h4>Atlanan</h4><div class="chips">${skippedHtml}</div></div>` : ""}${scenarioHtml}`;
}

function renderFixesSummary(fixes) {
  const applied = fixes?.fixes_applied || [];
  if (!applied.length) return "";
  const files = applied.map((f) => f.file).filter(Boolean);
  return `
    <section class="run-section fix-summary-section">
      <h4 class="run-section-title">Coding Agent — ${applied.length} fix önerisi</h4>
      ${renderFixes(fixes, { showScenarios: false })}
    </section>`;
}

function renderTurns(turns, autoIssues, { collapsibleReasoning = true } = {}) {
  const issueHtml = autoIssues?.length
    ? `<div class="meta-block"><h4>Otomatik Uyarılar</h4><div class="chips">${autoIssues
        .map((i) => `<span class="chip issue">${esc(i)}</span>`)
        .join("")}</div></div>`
    : "";

  const turnsHtml = (turns || [])
    .map((turn) => {
      const user = turn.user || {};
      const assistant = turn.assistant || {};
      const tools = assistant.toolActions || [];
      const qaIssues = turn.qa_issues || [];
      const userTs = fmtMessageTs(user.ts);
      const assistantTs = fmtMessageTs(assistant.ts);
      const dashSel = user.dashboardSelection;
      const dashChip = dashSel
        ? `<span class="chip tool">dashboard: ${esc(dashSel.name || dashSel.id)} (${esc(dashSel.id)})</span>`
        : "";
      const followups = assistant.suggestedFollowups || [];
      const reasoningBlock = assistant.reasoning
        ? collapsibleReasoning
          ? `<details class="reasoning-fold"><summary>Reasoning (${esc(String(assistant.reasoning).length)} karakter)</summary><div class="reasoning-body">${esc(assistant.reasoning)}</div></details>`
          : `<div class="meta-block"><h4>Reasoning</h4><div class="reasoning-body">${esc(assistant.reasoning)}</div></div>`
        : "";
      return `
      <article class="turn">
        <div class="turn-header">
          <span class="turn-num">Tur ${turn.turn}</span>
          <span class="turn-meta">${tools.length} tool · ${qaIssues.length} QA issue</span>
        </div>
        <div class="turn-thread">
          <div class="msg msg-right">
            <div class="msg-stack">
              <div class="msg-meta">
                <span class="chat-role cx">CX Director</span>
                ${userTs ? `<time class="chat-time">${esc(userTs)}</time>` : ""}
              </div>
              <div class="bubble user">${esc(user.content || "")}</div>
              ${dashChip ? `<div class="chips msg-chips">${dashChip}</div>` : ""}
            </div>
            <div class="avatar cx-avatar" title="CX Director">CX</div>
          </div>
          <div class="msg msg-left">
            <div class="avatar advisor-avatar" title="Pivony Advisor">A</div>
            <div class="msg-stack">
              <div class="msg-meta">
                <span class="chat-role advisor">Advisor</span>
                ${assistantTs ? `<time class="chat-time">${esc(assistantTs)}</time>` : ""}
              </div>
              <div class="bubble assistant">${esc(assistant.content || "(boş)")}</div>
              ${tools.length ? `<div class="chips msg-chips">${tools.map((t) => `<span class="chip tool">${esc(t)}</span>`).join("")}</div>` : ""}
              ${followups.length ? `<div class="followups msg-chips"><span class="muted-small">Önerilen:</span> ${followups.map((f) => `<span class="chip">${esc(f)}</span>`).join("")}</div>` : ""}
              ${assistant.guidance ? `<p class="guidance-box">${esc(assistant.guidance)}</p>` : ""}
              ${reasoningBlock}
            </div>
          </div>
        </div>
        ${qaIssues.length ? `<div class="turn-footer"><h4>QA Issues (bu tur)</h4>${renderIssues(qaIssues, { compact: true })}</div>` : ""}
      </article>`;
    })
    .join("");
  return issueHtml + turnsHtml;
}

function renderSessionHeader(detail) {
  const duration =
    detail.created_at && detail.updated_at
      ? (() => {
          const a = new Date(detail.created_at).getTime();
          const b = new Date(detail.updated_at).getTime();
          if (Number.isNaN(a) || Number.isNaN(b) || b <= a) return null;
          const sec = Math.round((b - a) / 1000);
          if (sec < 60) return `${sec} sn`;
          return `${Math.floor(sec / 60)} dk ${sec % 60} sn`;
        })()
      : null;
  return `
    <div class="session-header-card">
      <div class="session-header-top">
        <div>
          <h3 class="session-title">${esc(shortSessionId(detail.session_id))}</h3>
          <p class="session-subid muted-small" title="${esc(detail.session_id)}">${esc(detail.session_id)}</p>
        </div>
        <div class="session-times">
          <div><span class="time-label">Başlangıç</span> ${esc(fmtDateTime(detail.created_at))}</div>
          <div><span class="time-label">Son güncelleme</span> ${esc(fmtDateTime(detail.updated_at || detail.modified_at))}</div>
          ${duration ? `<div><span class="time-label">Süre</span> ${esc(duration)}</div>` : ""}
        </div>
      </div>
      <div class="chips">
        <span class="chip">${esc(detail.turn_count || 0)} tur</span>
        <span class="chip">${esc(detail.sector || "?")}</span>
        ${detail.user_email ? `<span class="chip">${esc(detail.user_email)}</span>` : ""}
        ${detail.user_id ? `<span class="chip muted-chip" title="Firebase ID">${esc(shortSessionId(detail.user_id))}</span>` : ""}
      </div>
    </div>`;
}

function renderPhaseSummary(run) {
  const phases = run.phases || [];
  const phaseMap = Object.fromEntries(phases.map((p) => [p.phase, p]));
  const cards = [
    ["conversation", "1. Konuşma", "CX Director → Advisor", "conversation"],
    ["qa", "2. QA", "Quality Checker", "qa"],
    ["coding", "3. İyileştirme", "Coding Agent", "coding"],
  ];
  return `<div class="phase-summary">${cards
    .map(([key, title, sub, cls]) => {
      const p = phaseMap[key];
      const parsed = p?.parsed_output;
      let stat = "—";
      let detail = p?.agent || "?";
      if (key === "conversation" && parsed && typeof parsed === "object") {
        stat = `${parsed.turn_count ?? "?"} tur`;
        const issues = parsed.notable_issues || [];
        detail = issues.length ? `${issues.length} not` : "tamamlandı";
      } else if (key === "qa" && parsed && typeof parsed === "object") {
        stat = parsed.overall_verdict || run.qa_report?.overall_verdict || "—";
        detail = `${(parsed.issues || run.qa_report?.issues || []).length} issue`;
      } else if (key === "coding" && parsed && typeof parsed === "object") {
        const applied = parsed.fixes_applied || run.fixes?.fixes_applied || [];
        stat = `${applied.length} fix`;
        const files = applied.map((f) => f.file).filter(Boolean);
        detail = files.length ? files.map((f) => f.split("/").pop()).join(", ") : "review";
      } else if (p?.raw_output) {
        stat = "çıktı var";
      }
      return `
      <div class="phase-summary-card ${cls}">
        <div class="phase-summary-title">${esc(title)}</div>
        <div class="phase-summary-stat">${esc(String(stat))}</div>
        <div class="phase-summary-sub">${esc(sub)} · ${esc(detail)}</div>
      </div>`;
    })
    .join("")}</div>`;
}

function renderPhaseTechnical(run) {
  const phases = run.phases || [];
  if (!phases.length) return "";
  return `<details class="tech-fold">
    <summary>Teknik faz çıktıları (JSON)</summary>
    <div class="pipeline-tech">${phases
      .map((p) => {
        const body = p.parsed_output
          ? `<pre class="json-view">${esc(JSON.stringify(p.parsed_output, null, 2))}</pre>`
          : `<div class="bubble assistant">${esc((p.raw_output || "—").slice(0, 2000))}</div>`;
        return `<div class="phase-tech-block">
          <h5>${esc(p.phase)} · ${esc(p.agent || "?")}</h5>
          ${body}
        </div>`;
      })
      .join("")}</div>
  </details>`;
}

function renderRunHero(run) {
  const qa = run.qa_report || {};
  const verdict = qa.overall_verdict || run.summary?.verdict;
  if (!verdict && !qa.priority_fix) return "";
  return `
    <div class="run-hero ${verdict ? `verdict-${esc(verdict)}` : ""}">
      <div class="run-hero-top">
        ${verdict ? `<span class="verdict ${esc(verdict)}">${esc(verdict)}</span>` : ""}
        <span class="muted-small">${esc(run.run_id)} · ${esc(run.session_id || "—")}</span>
      </div>
      ${qa.priority_fix ? `<p class="run-hero-fix">${esc(qa.priority_fix)}</p>` : ""}
    </div>`;
}

function renderRunDetail(run, targetId, { includeSession = true } = {}) {
  const qa = run.qa_report || {};
  const fixes = run.fixes || {};
  const verdict = qa.overall_verdict || run.summary?.verdict;
  const sessionBlock =
    includeSession && run.session_detail?.turns?.length
      ? `<section class="run-section">
        <h4 class="run-section-title">Konuşma <span class="muted-small">${esc(run.session_id || "")}</span></h4>
        <div class="conversation-thread">${renderTurns(run.session_detail.turns, run.session_detail.auto_issues)}</div>
      </section>`
      : includeSession && run.session_id
        ? `<div class="empty">Session dosyası henüz sync edilmemiş: ${esc(run.session_id)}</div>`
        : "";

  document.getElementById(targetId).innerHTML = `
    <div class="run-detail">
      ${
        includeSession && run.session_detail?.turns?.length
          ? `<div class="detail-toolbar">
        <button class="btn ghost" type="button" onclick="openExportModal()">↓ Export</button>
      </div>`
          : ""
      }
      <div class="chips run-chips">
        <span class="chip">${esc(run.mode)}</span>
        ${run.iteration != null ? `<span class="chip">iter ${esc(run.iteration)}</span>` : ""}
        ${verdict ? `<span class="verdict ${esc(verdict)}">${esc(verdict)}</span>` : ""}
        <span class="chip">${esc(run.summary?.issue_count ?? 0)} issue</span>
        <span class="chip ${(run.summary?.fixes_applied ?? 0) > 0 ? "warn" : ""}">${esc(run.summary?.fixes_applied ?? 0)} fix önerisi</span>
      </div>
      ${renderRunHero(run)}
      ${renderPhaseSummary(run)}
      ${renderFixesSummary(fixes)}
      ${sessionBlock}
      <section class="run-section">
        <h4 class="run-section-title">QA Değerlendirmesi</h4>
        ${qa.scores ? renderScores(qa) : ""}
        ${qa.priority_fix && verdict ? "" : qa.priority_fix ? `<p class="priority-fix">${esc(qa.priority_fix)}</p>` : ""}
        ${renderIssues(qa.issues || [], { compact: true })}
      </section>
      <section class="run-section">
        <h4 class="run-section-title">İyileştirmeler — detay</h4>
        ${renderFixes(fixes)}
      </section>
      ${renderPhaseTechnical(run)}
    </div>
  `;
  if (includeSession && run.session_detail?.turns?.length) {
    setExportContext(
      buildExportPayloadFromDetail(run.session_detail, {
        run_id: run.run_id,
        qa_report: run.qa_report,
      })
    );
  }
}

function renderSessionDetailBody(detail) {
  const linked = (detail.linked_runs || [])
    .map((r) => `<span class="chip">${esc(r.run_id)}</span>`)
    .join("");
  const qa = detail.qa_report || {};
  const qaBlock = qa.overall_verdict
    ? `<div class="meta-block verdict-box">
        <h4>QA Raporu ${detail.run_id ? `<span class="chip">${esc(detail.run_id)}</span>` : ""}
          <span class="verdict ${esc(qa.overall_verdict)}">${esc(qa.overall_verdict)}</span>
        </h4>
        ${qa.priority_fix ? `<p>${esc(qa.priority_fix)}</p>` : ""}
        ${renderScores(qa)}
        ${renderIssues(qa.issues || [], { compact: true })}
      </div>`
    : "";
  return `
    ${renderSessionHeader(detail)}
    ${linked ? `<div class="meta-block"><h4>Bağlı Run'lar</h4><div class="chips">${linked}</div></div>` : ""}
    ${qaBlock}
    <div class="conversation-thread">
      ${renderTurns(detail.turns, detail.auto_issues)}
    </div>`;
}

function showSessionDetail(detail, { runId = null, listContainerId = null } = {}) {
  activeSessionId = detail.session_id;
  const title = shortSessionId(detail.session_id);
  const body = renderSessionDetailBody(detail);
  const exportPayload = buildExportPayloadFromDetail(detail, {
    run_id: runId || detail.run_id,
    qa_report: detail.qa_report,
  });
  setExportContext(exportPayload);

  const feedbackTitle = document.getElementById("feedback-session-title");
  const feedbackDetail = document.getElementById("feedback-session-detail");
  const feedbackToolbar = document.getElementById("feedback-session-toolbar");
  if (feedbackTitle) feedbackTitle.textContent = title;
  if (feedbackDetail) {
    feedbackDetail.classList.remove("empty");
    feedbackDetail.innerHTML = body;
  }
  if (feedbackToolbar) feedbackToolbar.classList.remove("hidden");

  const sessionTitle = document.getElementById("session-title");
  const sessionDetail = document.getElementById("session-detail");
  const sessionToolbar = document.getElementById("session-toolbar");
  if (sessionTitle) sessionTitle.textContent = title;
  if (sessionDetail) {
    sessionDetail.classList.remove("empty");
    sessionDetail.innerHTML = body;
  }
  if (sessionToolbar) sessionToolbar.classList.remove("hidden");
  document.getElementById("session-export-btn")?.classList.remove("hidden");
  updateExportButtons(Boolean(detail.turns?.length));

  if (listContainerId) {
    const el = document.getElementById(listContainerId);
    el?.querySelectorAll(".list-item").forEach((node) => {
      node.classList.toggle(
        "selected",
        node.dataset.sessionId === detail.session_id
      );
    });
  }
}

let activeSessionId = null;

function renderStats(overview) {
  const c = overview.counts;
  const stats = [
    ["Run", c.runs],
    ["Konuşma", c.sessions],
    ["QA Issue", c.total_issues],
    ["Fix", c.total_fixes_applied],
  ];
  document.getElementById("stats").innerHTML = stats
    .map(([label, value]) => `<div class="stat-card"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`)
    .join("");
}

function renderList(containerId, items, onClick, labelFn, metaFn, { idKey = null } = {}) {
  const el = document.getElementById(containerId);
  if (!items.length) {
    el.innerHTML = `<div class="empty">Kayıt yok</div>`;
    return;
  }
  el.innerHTML = items
    .map(
      (item, idx) => `
    <div class="list-item" data-idx="${idx}"${idKey && item[idKey] ? ` data-session-id="${esc(item[idKey])}"` : ""}>
      <div class="title">${esc(labelFn(item))}</div>
      <div class="meta">${esc(metaFn ? metaFn(item) : fmtDateTime(item.created_at || item.modified_at))}</div>
    </div>`
    )
    .join("");
  el.querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", () => {
      el.querySelectorAll(".list-item").forEach((n) => n.classList.remove("selected"));
      node.classList.add("selected");
      onClick(items[Number(node.dataset.idx)]);
    });
  });
}

function sessionListLabel(item) {
  return `${shortSessionId(item.session_id)} · ${item.turn_count} tur`;
}

function sessionListMeta(item) {
  const start = fmtDateTime(item.created_at);
  const end = fmtDateTime(item.updated_at || item.modified_at);
  const preview = item.preview ? clipText(item.preview, 72) : "";
  const sector = item.sector ? ` · ${item.sector}` : "";
  return `${start}${end !== start ? ` → ${end}` : ""}${sector}${preview ? ` · ${preview}` : ""}`;
}

async function selectSessionById(sessionId, { runId = null, listContainerId = null } = {}) {
  if (!sessionId) return;
  const detail = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  showSessionDetail(detail, { runId, listContainerId });
}

function autoSelectSessionItem(containerId, sessionId) {
  const el = document.getElementById(containerId);
  if (!el || !sessionId) return;
  const node =
    el.querySelector(`.list-item[data-session-id="${sessionId}"]`) ||
    el.querySelector(".list-item");
  node?.click();
}

async function loadFeedback() {
  const [runs, sessions] = await Promise.all([api("/api/runs"), api("/api/sessions")]);
  const runBlock = document.getElementById("feedback-run-block");
  const sessionGrid = document.getElementById("feedback-session-grid");

  if (!runs.length) {
    runBlock.innerHTML =
      `<div class="empty">Henüz run yok. Sunucuda loop çalıştır veya <button class="btn" onclick="document.getElementById('sync-hint-btn').click()">sync</button> yap.</div>`;
    sessionGrid?.classList.add("hidden");
    return;
  }

  const latest = runs[0];
  const detail = await api(`/api/runs/${encodeURIComponent(latest.run_id)}`);
  document.getElementById("feedback-run-meta").textContent = `${detail.run_id} · ${fmtDate(detail.created_at)}`;
  renderRunDetail(detail, "feedback-run-block", { includeSession: false });

  if (!sessions.length) {
    sessionGrid?.classList.add("hidden");
    return;
  }

  sessionGrid?.classList.remove("hidden");
  renderList(
    "feedback-session-list",
    sessions,
    async (item) => {
      await selectSessionById(item.session_id, {
        runId: detail.run_id,
        listContainerId: "feedback-session-list",
      });
    },
    sessionListLabel,
    sessionListMeta,
    { idKey: "session_id" }
  );
  autoSelectSessionItem("feedback-session-list", detail.session_id || sessions[0]?.session_id);
}

async function loadRuns() {
  const runs = await api("/api/runs");
  renderList(
    "run-list",
    runs,
    async (item) => {
      const detail = await api(`/api/runs/${encodeURIComponent(item.run_id)}`);
      document.getElementById("run-title").textContent = item.run_id;
      renderRunDetail(detail, "run-detail");
    },
    (r) => `${r.run_id} (${r.mode}${r.iteration != null ? ` #${r.iteration}` : ""})`
  );
  if (runs[0]) document.querySelector("#run-list .list-item")?.click();
}

async function loadSessions() {
  const sessions = await api("/api/sessions");
  renderList(
    "session-list",
    sessions,
    async (item) => {
      await selectSessionById(item.session_id, { listContainerId: "session-list" });
    },
    sessionListLabel,
    sessionListMeta,
    { idKey: "session_id" }
  );
  if (activeSessionId) {
    autoSelectSessionItem("session-list", activeSessionId);
  } else if (sessions[0]) {
    autoSelectSessionItem("session-list", sessions[0].session_id);
  }
}

async function loadQaBoard() {
  const runs = await api("/api/runs");
  if (!runs.length) {
    document.getElementById("qa-board").innerHTML = `<div class="empty">QA raporu yok</div>`;
    return;
  }
  const blocks = await Promise.all(
    runs.slice(0, 20).map((r) => api(`/api/runs/${encodeURIComponent(r.run_id)}`))
  );
  document.getElementById("qa-board").innerHTML = blocks
    .map((run) => {
      const qa = run.qa_report || {};
      const verdict = qa.overall_verdict;
      return `
      <div class="qa-board-card">
        <div class="qa-board-head">
          <h4>${esc(run.run_id)}</h4>
          ${verdict ? `<span class="verdict ${esc(verdict)}">${esc(verdict)}</span>` : ""}
        </div>
        ${qa.priority_fix ? `<p class="run-hero-fix">${esc(qa.priority_fix)}</p>` : ""}
        ${renderScores(qa)}
        ${renderIssues(qa.issues || [], { compact: true })}
      </div>`;
    })
    .join("");
}

async function loadImprovements() {
  const runs = await api("/api/runs");
  if (!runs.length) {
    document.getElementById("improvements-board").innerHTML = `<div class="empty">Fix kaydı yok</div>`;
    return;
  }
  const blocks = await Promise.all(
    runs.slice(0, 20).map((r) => api(`/api/runs/${encodeURIComponent(r.run_id)}`))
  );
  document.getElementById("improvements-board").innerHTML = blocks
    .map(
      (run) => `
    <div class="meta-block" style="margin-bottom:0.75rem;border:1px solid var(--border);border-radius:12px">
      <h4>${esc(run.run_id)} · session ${esc(run.session_id || "—")}</h4>
      ${renderFixes(run.fixes || {})}
      ${run.fixes?.next_test_scenarios?.length ? `<div class="chips">${run.fixes.next_test_scenarios.map((s) => `<span class="chip">${esc(s)}</span>`).join("")}</div>` : ""}
    </div>`
    )
    .join("");
}

async function apiPost(path, body) {
  const { base, token } = getApiConfig();
  const rel = path.startsWith("/") ? path.slice(1) : path;
  const url = base ? `${base.replace(/\/$/, "")}/${rel}` : rel;
  const headers = { "Content-Type": "application/json" };
  if (token) headers["X-Quality-Loop-Token"] = token;
  const res = await fetch(url, { method: "POST", headers, body: JSON.stringify(body) });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `${url} → ${res.status}`);
  }
  return res.json();
}

function renderFlowSteps(flow) {
  return `<div class="flow-steps">${(flow || [])
    .map(
      (s) => `
    <div class="flow-step ${s.active ? "active" : ""} ${s.done ? "done" : ""}">
      <div class="flow-num">${s.step}</div>
      <div>
        <div class="flow-title">${esc(s.title)} <span class="muted">· ${esc(s.agent)}</span></div>
        <div class="flow-desc">${esc(s.desc)}</div>
      </div>
    </div>`
    )
    .join("")}</div>`;
}

function updateExportButtons(hasMessages) {
  document.getElementById("export-btn")?.classList.toggle("hidden", !hasMessages);
  document.getElementById("session-export-btn")?.classList.toggle("hidden", !hasMessages);
}

function setExportContext(ctx) {
  exportContext = ctx;
  updateExportButtons(Boolean(ctx?.messages?.length));
  const subtitle = document.getElementById("export-modal-subtitle");
  if (subtitle) {
    subtitle.textContent = ctx?.title
      ? `${ctx.title}${ctx.messages?.length ? ` · ${ctx.messages.length} mesaj` : ""}`
      : "";
  }
}

function buildExportPayloadFromDetail(detail, extra = {}) {
  const turns = detail.turns || [];
  const messages = window.QlExport.turnsToMessages(turns);
  const linked = detail.linked_runs || [];
  const runId = extra.run_id || detail.run_id || linked[0]?.run_id || null;
  return {
    sessionId: detail.session_id,
    title: shortSessionId(detail.session_id),
    messages,
    meta: {
      session_id: detail.session_id,
      sector: detail.sector,
      user_email: detail.user_email,
      user_id: detail.user_id,
      run_id: runId,
      qa_report: detail.qa_report || extra.qa_report || null,
      ...extra,
    },
  };
}

function openExportModal() {
  if (!exportContext?.messages?.length) return;
  document.getElementById("export-modal")?.classList.remove("hidden");
}

function closeExportModal() {
  document.getElementById("export-modal")?.classList.add("hidden");
}

function downloadExportJson() {
  if (!exportContext) return;
  window.QlExport.downloadConversationJson(exportContext);
  closeExportModal();
}

function downloadExportMarkdown() {
  if (!exportContext) return;
  window.QlExport.downloadConversationMarkdown(exportContext);
  closeExportModal();
}

function exportDownloadUrl(sessionId, format = "json", jobId = null) {
  const { base, token } = getApiConfig();
  const params = new URLSearchParams();
  if (token) params.set("token", token);
  if (jobId) params.set("job_id", jobId);
  const ext = format === "md" ? "export.md" : "export.json";
  const root = base ? `${base.replace(/\/$/, "")}` : "";
  const qs = params.toString();
  return `${root}/api/sessions/${encodeURIComponent(sessionId)}/${ext}${qs ? `?${qs}` : ""}`;
}

function downloadAllTurns(sessionId, jobId = null) {
  const sid =
    sessionId ||
    exportContext?.sessionId ||
    exportContext?.meta?.session_id ||
    null;
  if (!sid) return;
  const url = exportDownloadUrl(sid, "json", jobId || exportContext?.meta?.job_id || null);
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  a.click();
}

function downloadActiveSessionJson() {
  downloadAllTurns(
    activeSessionId,
    exportContext?.meta?.job_id || exportContext?.meta?.run_id || null
  );
}

window.downloadAllTurns = downloadAllTurns;
window.downloadActiveSessionJson = downloadActiveSessionJson;

window.openExportModal = openExportModal;

function updateRunButtons(job) {
  const running = job && ["queued", "running"].includes(job.status);
  document.getElementById("start-run-btn").classList.toggle("hidden", running);
  document.getElementById("stop-run-btn").classList.toggle("hidden", !running);
}

function renderLangSmithBlock(obs, jobId) {
  if (!obs) return "";
  const enabled = obs.enabled;
  const configured = obs.configured;
  const status = !enabled ? "API key yok" : configured ? "Aktif" : "Paket/kurulum bekliyor";
  const statusClass = configured ? "chip success" : enabled ? "chip warn" : "chip muted";
  const url = obs.ui_url;
  const filterHint = jobId
    ? `LangSmith'te <code>${esc(jobId)}</code> etiketiyle filtreleyin`
    : "Run başladığında job_id ile filtreleyebilirsiniz";

  return `
    <div class="meta-block langsmith-block">
      <h4>LangSmith — Runtime Trace</h4>
      <p class="flow-desc">
        Ajan akışı, tool çağrıları, reasoning ve token/maliyet ağacı LangSmith dashboard'unda görünür.
        Kendi UI'mız özet ve QA kararını gösterir; derin trace için LangSmith kullanın.
      </p>
      <div class="chips" style="margin:0.5rem 0">
        <span class="${statusClass}">${esc(status)}</span>
        ${obs.project ? `<span class="chip">${esc(obs.project)}</span>` : ""}
      </div>
      <p class="muted-small">${filterHint}</p>
      ${
        url && enabled
          ? `<a class="btn secondary" href="${esc(url)}" target="_blank" rel="noopener">LangSmith'te Aç ↗</a>`
          : `<p class="muted-small">Sunucu <code>.env</code> dosyasına <code>LANGSMITH_API_KEY</code> ekleyin.</p>`
      }
    </div>`;
}

function renderVertexBanner(job) {
  const vtx = job?.vertex;
  if (!vtx || vtx.state === "ok") return "";
  const state = vtx.state || "";
  const msg = vtx.message || job.message || "";
  const cls =
    state === "exhausted" ? "vertex-banner danger" : "vertex-banner warn";
  const icon = state === "throttle" ? "⏸" : state === "retry" ? "↻" : "⚠";
  const detail =
    state === "throttle" && vtx.remaining_seconds
      ? `Kalan bekleme: ~${Math.ceil(vtx.remaining_seconds)} sn`
      : state === "retry" && vtx.attempt
        ? `Deneme ${vtx.attempt}/${vtx.max_attempts || "?"}`
        : "";
  return `
    <div class="${cls}">
      <div class="vertex-banner-title">${icon} Vertex AI</div>
      <p>${esc(msg)}</p>
      ${detail ? `<p class="muted-small">${esc(detail)}</p>` : ""}
    </div>`;
}

function renderLiveRun(job) {
  const panel = document.getElementById("live-run-panel");
  const body = document.getElementById("live-run-body");
  const statusEl = document.getElementById("live-run-status");
  const titleEl = document.getElementById("live-run-title");

  updateRunButtons(job);

  if (!job || !["queued", "running"].includes(job.status)) {
    panel.classList.add("hidden");
    return;
  }

  panel.classList.remove("hidden");
  titleEl.textContent = `Canlı Run — ${job.job_id}`;
  const vtx = job.vertex;
  const statusSuffix =
    vtx && vtx.state && vtx.state !== "ok" ? ` · vertex:${vtx.state}` : "";
  statusEl.textContent = `${job.phase} · ${job.message || ""}${statusSuffix}`;

  const turns = job.session_detail?.turns || [];
  const qa = job.qa_preview;

  body.innerHTML = `
    <div style="margin-bottom:0.75rem;display:flex;gap:0.5rem;flex-wrap:wrap">
      <button class="btn danger" onclick="stopRun()">■ Run'ı Durdur</button>
      ${job.session_id && turns.length ? `<button class="btn primary" type="button" data-session-id="${esc(job.session_id)}" data-job-id="${esc(job.job_id || "")}" onclick="downloadAllTurns(this.dataset.sessionId, this.dataset.jobId || null)">↓ Tüm turları indir (JSON)</button>` : ""}
      ${turns.length ? `<button class="btn ghost" type="button" onclick="openExportModal()">↓ Export (JSON/MD)</button>` : ""}
      ${job.langsmith_url ? `<a class="btn secondary" href="${esc(job.langsmith_url)}" target="_blank" rel="noopener">LangSmith Trace ↗</a>` : ""}
    </div>
    ${renderVertexBanner(job)}
    ${renderLangSmithBlock(job.observability, job.job_id)}
    ${renderFlowSteps(job.flow)}
    <div class="meta-block">
      <h4>Karar mekanizması</h4>
      <p class="flow-desc">
        <strong>QA Agent (Quality Checker)</strong> Advisor'ın hangi noktada gelişmesi gerektiğine karar verir:
        skorlar, severity, kanıt ve <code>fix_hint</code> üretir.
        <strong>Coding Agent</strong> bu kararı koda dönüştürür.
      </p>
    </div>
    <div class="chips" style="margin-bottom:0.75rem">
      <span class="chip">${esc(job.turn_count || 0)} tur</span>
      ${job.session_id ? `<span class="chip">${esc(job.session_id)}</span>` : ""}
    </div>
    ${turns.length ? `<div class="meta-block"><h4>Konuşma (canlı)</h4>${renderTurns(turns, job.session_detail?.auto_issues)}</div>` : `<div class="empty">Konuşma başlıyor…</div>`}
    ${qa?.priority_fix ? `<div class="meta-block verdict-box"><h4>QA Kararı — Advisor nerede gelişmeli?</h4><p>${esc(qa.priority_fix)}</p>${renderIssues(qa.issues || [], { compact: true })}</div>` : ""}
  `;
  if (job.session_detail?.turns?.length) {
    setExportContext(
      buildExportPayloadFromDetail(job.session_detail, {
        job_id: job.job_id,
        session_id: job.session_id,
      })
    );
  }
}

async function pollActiveJob() {
  try {
    const job = await api("/api/jobs/active");
    renderLiveRun(job);
    if (job && ["queued", "running"].includes(job.status)) {
      if (!pollTimer) pollTimer = setInterval(pollActiveJob, 4000);
    } else {
      updateRunButtons(null);
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      if (job && job.status === "completed") await refreshAll();
    }
  } catch (err) {
    console.error(err);
    updateRunButtons(null);
  }
}

async function stopRun() {
  if (!confirm("Aktif run durdurulsun mu?")) return;
  const btn = document.getElementById("stop-run-btn");
  btn.disabled = true;
  try {
    await apiPost("/api/jobs/stop", {});
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    document.getElementById("live-run-panel").classList.add("hidden");
    updateRunButtons(null);
    await refreshAll();
  } catch (err) {
    alert(`Durdurulamadı: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
}
window.stopRun = stopRun;

async function loadArchitecture() {
  const arch = await api("/api/architecture");
  const obs = arch.observability_live || arch.observability || {};
  const agentsHtml = (arch.agents || [])
    .map(
      (a) => `
    <div class="arch-agent ${a.decision_maker ? "decision" : ""}">
      <div class="arch-agent-head">
        <h4>${esc(a.role)}</h4>
        ${a.decision_maker ? '<span class="chip critical">Karar verici</span>' : ""}
      </div>
      <p class="flow-desc">${esc(a.goal)}</p>
      <div class="chips">${(a.tools || []).map((t) => `<span class="chip tool">${esc(t.name)}</span>`).join("")}</div>
      <p class="muted-small">LLM: ${esc(arch.llm_config?.[a.llm_env] || a.llm_default)}</p>
      <p class="muted-small">Çıktı: ${esc((a.outputs || []).join(", "))}</p>
    </div>`
    )
    .join("");

  const tasksHtml = (arch.tasks || [])
    .map(
      (t) => `
    <div class="arch-task">
      <strong>${esc(t.agent)}</strong> · ${esc(t.phase)}
      ${t.context?.length ? `<span class="muted-small">context: ${esc(t.context.join(" → "))}</span>` : ""}
    </div>`
    )
    .join("");

  const flowHtml = (arch.flow || [])
    .map(
      (f) => `
    <div class="arch-flow-row">
      <span class="chip">${esc(f.from)}</span>
      <span class="arch-arrow">→ ${esc(f.label)} →</span>
      <span class="chip">${esc(f.to)}</span>
      <span class="muted-small">via ${esc(f.via)}</span>
    </div>`
    )
    .join("");

  document.getElementById("architecture-board").innerHTML = `
    <p class="flow-desc">${esc(arch.description)}</p>
    <div class="chips" style="margin-bottom:1rem">
      <span class="chip">${esc(arch.framework)}</span>
      <span class="chip">process: ${esc(arch.process)}</span>
    </div>

    <div class="arch-diagram">
      <div class="arch-layer advisor-layer">
        <h4>Test hedefi</h4>
        <div class="arch-box">${esc(arch.layers?.[0]?.title || "Pivony Advisor")}</div>
        <p class="muted-small">${esc(arch.layers?.[0]?.endpoint || "")}</p>
      </div>
      <div class="arch-connector">↕ pivony_advisor_chat</div>
      <div class="arch-agents-row">${agentsHtml}</div>
      <div class="arch-connector">→ sequential context →</div>
      <div class="arch-tasks">${tasksHtml}</div>
    </div>

    <div class="meta-block"><h4>Veri akışı</h4>${flowHtml}</div>

    <div class="meta-block"><h4>Katmanlar</h4>
      ${(arch.layers || [])
        .map(
          (l) => `<div class="arch-layer-card"><strong>${esc(l.title)}</strong> — ${esc(l.subtitle || "")}</div>`
        )
        .join("")}
    </div>

    ${renderLangSmithBlock(obs)}
  `;
}

async function startRun() {
  const btn = document.getElementById("start-run-btn");
  btn.disabled = true;
  btn.textContent = "Başlatılıyor…";
  try {
    setView("feedback");
    const job = await apiPost("/api/jobs/start", { mode: "full", iterations: 1 });
    renderLiveRun(job);
    if (!pollTimer) pollTimer = setInterval(pollActiveJob, 4000);
  } catch (err) {
    alert(`Run başlatılamadı: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "▶ Run Başlat";
  }
}

function updateSourceBadge() {
  const { base } = getApiConfig();
  document.getElementById("source-badge").textContent = base ? `Kaynak: ${base}` : "Kaynak: local";
}

async function refreshAll() {
  const overview = await api("/api/overview");
  renderStats(overview);
  await loadFeedback();
  await pollActiveJob();
  updateSourceBadge();
}

async function boot() {
  const urlToken = new URLSearchParams(window.location.search).get("token");
  if (urlToken) {
    localStorage.setItem("ql_api_token", urlToken);
  }

  const { base, token } = getApiConfig();
  document.getElementById("api-base").value = base;
  document.getElementById("api-token").value = token;
  document.getElementById("sync-command").textContent =
    "cd pivony-advisor && bash scripts/sync_quality_loop_outputs.sh";

  document.getElementById("settings-btn").addEventListener("click", () => {
    document.getElementById("settings-panel").classList.toggle("hidden");
  });
  document.getElementById("settings-save").addEventListener("click", async () => {
    setApiConfig(document.getElementById("api-base").value, document.getElementById("api-token").value);
    document.getElementById("settings-panel").classList.add("hidden");
    await refreshAll();
  });

  document.getElementById("sync-hint-btn").addEventListener("click", () => {
    document.getElementById("sync-modal").classList.remove("hidden");
  });
  document.getElementById("sync-close").addEventListener("click", () => {
    document.getElementById("sync-modal").classList.add("hidden");
  });

  document.getElementById("export-btn")?.addEventListener("click", openExportModal);
  document.getElementById("session-export-btn")?.addEventListener("click", openExportModal);
  document.getElementById("feedback-session-export-btn")?.addEventListener("click", openExportModal);
  document.getElementById("session-json-btn")?.addEventListener("click", downloadActiveSessionJson);
  document.getElementById("feedback-session-json-btn")?.addEventListener("click", downloadActiveSessionJson);
  document.getElementById("export-json-btn")?.addEventListener("click", downloadExportJson);
  document.getElementById("export-md-btn")?.addEventListener("click", downloadExportMarkdown);
  document.getElementById("export-close")?.addEventListener("click", closeExportModal);
  document.getElementById("export-modal")?.addEventListener("click", (e) => {
    if (e.target?.id === "export-modal") closeExportModal();
  });
  const shortcutEl = document.getElementById("export-shortcut-hint");
  if (shortcutEl && window.QlExport) {
    shortcutEl.textContent = window.QlExport.exportShortcutLabel();
  }
  window.addEventListener(
    "keydown",
    (e) => {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod || !e.shiftKey) return;
      if (e.key !== "e" && e.key !== "E") return;
      if (!exportContext?.messages?.length) return;
      e.preventDefault();
      openExportModal();
    },
    true
  );

  document.getElementById("start-run-btn").addEventListener("click", startRun);
  document.getElementById("stop-run-btn").addEventListener("click", stopRun);

  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const view = btn.dataset.view;
      setView(view);
      try {
        if (view === "feedback") await loadFeedback();
        if (view === "architecture") await loadArchitecture();
        if (view === "runs") await loadRuns();
        if (view === "sessions") await loadSessions();
        if (view === "qa") await loadQaBoard();
        if (view === "improvements") await loadImprovements();
      } catch (err) {
        console.error(err);
      }
    });
  });

  try {
    await refreshAll();
  } catch (err) {
    document.getElementById("subtitle").textContent = `Bağlantı hatası: ${err.message}`;
  }
}

boot();
