const views = ["feedback", "architecture", "runs", "sessions", "qa", "improvements"];
const VIEW_SEGMENTS = {
  feedback: "",
  architecture: "architecture",
  runs: "runs",
  sessions: "sessions",
  qa: "qa",
  improvements: "improvements",
};
const VIEW_SUBTITLES = {
  feedback: "Konuşmalar · QA değerlendirmeleri · kod iyileştirmeleri · tam feedback döngüsü",
  architecture: "CrewAI mimarisi · agent promptları · veri akışı",
  runs: "Tamamlanan döngü geçmişi (her döngü = bir session + QA + fix)",
  sessions: "Advisor konuşma kayıtları",
  qa: "QA Agent değerlendirme raporları",
  improvements: "Coding Agent iyileştirme önerileri",
};
let exportContext = null;
let pollTimer = null;
let promptEditorWired = false;
let repoEditorWired = false;

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
  const token =
    sessionStorage.getItem("ql_session_token") ||
    localStorage.getItem("ql_api_token") ||
    new URLSearchParams(window.location.search).get("token") ||
    "";
  return { base, token, remote: Boolean(base) };
}

function setApiConfig(base, token) {
  localStorage.setItem("ql_api_base", base.trim());
  localStorage.setItem("ql_api_token", token.trim());
  updateRemoteTokenVisibility();
}

function updateRemoteTokenVisibility() {
  const { remote } = getApiConfig();
  document.getElementById("remote-token-wrap")?.classList.toggle("hidden", !remote);
}

function fetchOptions(extra = {}) {
  const { base, token, remote } = getApiConfig();
  const opts = { credentials: remote ? "omit" : "include", ...extra };
  const headers = { ...(extra.headers || {}) };
  // Same-origin: cookie session. Header fallback for ?token= URL and cookie-blocked browsers.
  if (token) headers["X-Quality-Loop-Token"] = token;
  if (Object.keys(headers).length) opts.headers = headers;
  return opts;
}

function formatApiErrorDetail(detail) {
  if (!detail) return "Giriş başarısız";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg || d).join(", ");
  return String(detail);
}

function showLoginOverlay(message = "") {
  const overlay = document.getElementById("login-overlay");
  const err = document.getElementById("login-error");
  overlay?.classList.remove("hidden");
  if (err) {
    if (message) {
      err.textContent = message;
      err.classList.remove("hidden");
    } else {
      err.textContent = "";
      err.classList.add("hidden");
    }
  }
  document.getElementById("login-password")?.focus();
}

function hideLoginOverlay() {
  document.getElementById("login-overlay")?.classList.add("hidden");
  document.getElementById("login-error")?.classList.add("hidden");
}

async function checkAuthStatus() {
  const res = await fetch("api/auth/status", fetchOptions());
  if (!res.ok) return { auth_required: false, authenticated: true };
  return res.json();
}

async function loginWithPassword(password) {
  const res = await fetch(
    "api/auth/login",
    fetchOptions({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    })
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(formatApiErrorDetail(err.detail) || "Giriş başarısız");
  }
  return res.json();
}

async function establishSession(password) {
  const data = await loginWithPassword(password);
  // Cookie set by server; also keep header fallback in sessionStorage (not localStorage).
  sessionStorage.setItem("ql_session_token", password.trim());
  return data;
}

async function logoutSession() {
  await fetch("api/auth/logout", fetchOptions({ method: "POST" }));
  showLoginOverlay();
}

async function api(path) {
  const { base } = getApiConfig();
  const rel = path.startsWith("/") ? path.slice(1) : path;
  const url = base ? `${base.replace(/\/$/, "")}/${rel}` : rel;
  const res = await fetch(url, fetchOptions());
  if (res.status === 401) {
    const data = await res.json().catch(() => ({}));
    if (!getApiConfig().remote) {
      const msg =
        data.detail === "invalid password"
          ? "Şifre hatalı"
          : data.detail === "login required"
            ? "Oturum gerekli"
            : "Giriş gerekli";
      showLoginOverlay(msg);
    }
    throw new Error(`${url} → 401`);
  }
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return res.json();
}

function getMountBase() {
  const path = window.location.pathname;
  const marker = "/quality-loop";
  const idx = path.indexOf(marker);
  if (idx >= 0) return path.slice(0, idx + marker.length);
  return "";
}

function viewFromLocation() {
  const base = getMountBase();
  let rest = window.location.pathname;
  if (base) rest = rest.slice(base.length);
  rest = rest.replace(/^\/+/, "").replace(/\/+$/, "");
  if (!rest) return "feedback";
  return views.find((v) => VIEW_SEGMENTS[v] === rest || v === rest) || "feedback";
}

function buildViewUrl(view) {
  const base = getMountBase();
  const seg = VIEW_SEGMENTS[view];
  const path = seg ? `${base}/${seg}` : `${base || ""}/`;
  const token = new URLSearchParams(window.location.search).get("token");
  return token ? `${path}?token=${encodeURIComponent(token)}` : path;
}

function setView(name, { replace = false, syncUrl = true } = {}) {
  views.forEach((v) => {
    document.getElementById(`view-${v}`).classList.toggle("hidden", v !== name);
    document.querySelector(`.nav-btn[data-view="${v}"]`)?.classList.toggle("active", v === name);
  });
  if (syncUrl) {
    const url = buildViewUrl(name);
    const state = { view: name };
    if (replace) history.replaceState(state, "", url);
    else history.pushState(state, "", url);
  }
  const subtitle = document.getElementById("subtitle");
  if (subtitle && VIEW_SUBTITLES[name]) subtitle.textContent = VIEW_SUBTITLES[name];
}

async function navigateToView(view, { syncUrl = true } = {}) {
  setView(view, { replace: !syncUrl, syncUrl });
  if (view === "feedback") await loadFeedback();
  if (view === "architecture") await loadArchitecture();
  if (view === "runs") await loadRuns();
  if (view === "sessions") await loadSessions();
  if (view === "qa") await loadQaBoard();
  if (view === "improvements") await loadImprovements();
}

function selectedPromptSector() {
  const custom = document.getElementById("prompt-sector-custom")?.value?.trim();
  if (custom) return custom;
  return document.getElementById("prompt-sector")?.value || localStorage.getItem("ql_run_sector") || "default";
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

function deployStatusChip(status) {
  const s = String(status || "unknown").toLowerCase();
  const labels = {
    committed_and_pushed: ["success", "commit + push"],
    committed_not_pushed: ["warn", "commit (push yok)"],
    commit_push_failed: ["warn", "push başarısız"],
    file_written: ["success", "dosyaya yazıldı"],
    success: ["success", "uygulandı"],
    applied: ["success", "uygulandı"],
    deployed: ["success", "uygulandı"],
    skipped: ["warn", "öneri — uygulanmadı"],
    not_applied: ["warn", "öneri — uygulanmadı"],
  };
  const entry = labels[s];
  if (entry) {
    return `<span class="chip ${entry[0]}">${esc(entry[1])}</span>`;
  }
  return `<span class="chip">${esc(status || "unknown")}</span>`;
}

function fixMetaChips(f) {
  const chips = [];
  if (f.repo) chips.push(`<span class="chip repo">${esc(f.repo)}</span>`);
  if (f.commit_hash) {
    chips.push(
      `<span class="chip commit" title="${esc(f.commit_message || "")}">${esc(f.commit_hash)}</span>`
    );
  }
  if (f.qa_issue_index != null && f.qa_issue_index !== "") {
    const n = Number(f.qa_issue_index);
    chips.push(
      `<span class="chip qa-ref" title="${esc(f.qa_issue_description || "")}">QA #${esc(Number.isFinite(n) ? n + 1 : f.qa_issue_index)}</span>`
    );
  }
  if (f.qa_severity) chips.push(severityChip(f.qa_severity));
  if (f.qa_category) chips.push(`<span class="chip muted-chip">${esc(f.qa_category)}</span>`);
  return chips.join(" ");
}

function renderFixes(fixes, { showScenarios = true, showDiffs = false } = {}) {
  const applied = fixes?.fixes_applied || [];
  const skipped = fixes?.fixes_skipped || [];
  const scenarios = fixes?.next_test_scenarios || [];
  if (!applied.length && !skipped.length) return `<div class="empty">Fix kaydı yok</div>`;
  const appliedHtml = applied
    .map((f) => {
      const deployChip = deployStatusChip(f.deploy_status);
      const stats =
        f.lines_added != null || f.lines_removed != null
          ? `<span class="muted-small fix-stats">+${f.lines_added || 0} / -${f.lines_removed || 0} satır</span>`
          : "";
      const diffBlock =
        showDiffs && f.diff
          ? `<details class="fix-diff-fold"><summary>Kod değişikliği</summary><pre class="fix-diff">${esc(f.diff)}</pre></details>`
          : "";
      return `
    <article class="fix-card">
      <div class="fix-card-head">
        ${deployChip}
        ${fixMetaChips(f)}
        <code class="fix-file">${esc(f.file || "?")}</code>
        ${stats}
      </div>
      <p class="fix-desc">${esc(f.issue_fixed || f.qa_issue_description || "")}</p>
      ${f.commit_message ? `<p class="muted-small fix-commit-msg">${esc(f.commit_message)}</p>` : ""}
      ${diffBlock}
    </article>`;
    })
    .join("");
  const skippedHtml = skipped
    .map((s) => {
      const file = typeof s === "string" ? "N/A" : s.file || "N/A";
      const issue = typeof s === "string" ? s : s.issue || "";
      const reason = typeof s === "string" ? "" : s.reason || "";
      return `
      <article class="fix-card fix-card-skipped">
        <div class="fix-card-head">
          <span class="chip warn">atlandı</span>
          ${fixMetaChips(s)}
          <code class="fix-file">${esc(file)}</code>
        </div>
        <p class="fix-desc">${esc(issue)}</p>
        ${reason ? `<p class="muted-small">${esc(reason)}</p>` : ""}
      </article>`;
    })
    .join("");
  const scenarioHtml =
    showScenarios && scenarios.length
      ? `<div class="fix-scenarios">
          <h5 class="muted-small">Sonraki test senaryoları</h5>
          <ul>${scenarios.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
        </div>`
      : "";
  const note =
    applied.some(
      (f) =>
        ["skipped", "not_applied"].includes(String(f.deploy_status || "").toLowerCase()) &&
        !f.commit_hash &&
        !f.diff
    )
      ? `<p class="fix-note muted-small">Coding Agent fix önerdi; dosyaya yazılmadı veya git kapalı.</p>`
      : "";
  return `${note}${appliedHtml}${skipped.length ? `<div class="meta-block"><h4>Atlanan</h4><div class="fix-skipped-list">${skippedHtml}</div></div>` : ""}${scenarioHtml}`;
}

async function openSessionFromImprovement(sessionId, runId = null) {
  if (!sessionId) return;
  await navigateToView("sessions");
  await selectSessionById(sessionId, { runId, listContainerId: "session-list" });
  autoSelectSessionItem("session-list", sessionId);
}

function downloadImprovementsExport(runId) {
  const url = apiUrl(`api/runs/${encodeURIComponent(runId)}/improvements/export.json`);
  fetch(url, fetchOptions())
    .then((res) => {
      if (res.status === 401) {
        showLoginOverlay();
        throw new Error("401");
      }
      if (!res.ok) throw new Error(`${res.status}`);
      return res.blob();
    })
    .then((blob) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `pivony-quality-loop-${runId}-improvements.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    })
    .catch((err) => alert(`İndirilemedi: ${err.message}`));
}
window.downloadImprovementsExport = downloadImprovementsExport;
window.openSessionFromImprovement = openSessionFromImprovement;

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

function normalizeDashboardPicker(picker) {
  if (!picker || typeof picker !== "object") return null;
  const dashboards = (picker.dashboards || []).filter((d) => d && d.id != null);
  if (!dashboards.length) return null;
  const groups = (picker.groups || []).filter((g) => g && g.id != null);
  return {
    dashboards,
    groups,
    default_dashboard_id: picker.default_dashboard_id,
  };
}

function renderDashboardSelection(sel) {
  if (!sel || sel.id == null) return "";
  const name =
    typeof sel.name === "string" && sel.name.trim()
      ? sel.name.trim()
      : `Dashboard ${sel.id}`;
  return `
    <div class="dashboard-selection-block">
      <span class="dashboard-selection-label">CX Director seçimi</span>
      <span class="dashboard-selection-name">${esc(name)}</span>
      <span class="dashboard-selection-id">id ${esc(sel.id)}</span>
    </div>`;
}

function renderDashboardPicker(picker) {
  const norm = normalizeDashboardPicker(picker);
  if (!norm) return "";
  const groupMap = Object.fromEntries(norm.groups.map((g) => [g.id, g]));
  const items = norm.dashboards
    .map((d) => {
      const group = d.group_id != null ? groupMap[d.group_id] : null;
      const isDefault =
        norm.default_dashboard_id != null && d.id === norm.default_dashboard_id;
      const dashName = d.name || `Dashboard ${d.id}`;
      return `
        <div class="dashboard-picker-item${isDefault ? " is-default" : ""}">
          <span class="dashboard-picker-name">${esc(dashName)}</span>
          <span class="dashboard-picker-meta">
            #${esc(d.id)}${group?.name ? ` · ${esc(group.name)}` : ""}${isDefault ? " · önerilen" : ""}
          </span>
        </div>`;
    })
    .join("");
  const groupChips = norm.groups.length
    ? `<div class="chips dashboard-picker-groups">${norm.groups
        .map(
          (g) =>
            `<span class="chip muted-chip" style="${g.color ? `--chip-color:${esc(g.color)}` : ""}">${esc(g.name)}</span>`
        )
        .join("")}</div>`
    : "";
  return `
    <div class="dashboard-picker-block">
      <div class="dashboard-picker-head">
        <span class="dashboard-picker-title">Dashboard seçenekleri</span>
        <span class="muted-small">${esc(norm.dashboards.length)} dashboard</span>
      </div>
      ${groupChips}
      <div class="dashboard-picker-grid">${items}</div>
    </div>`;
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
      const dashSelectionHtml = renderDashboardSelection(dashSel);
      const dashPicker = assistant.dashboardPicker;
      const dashPickerHtml = renderDashboardPicker(dashPicker);
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
              ${dashSelectionHtml}
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
              ${dashPickerHtml}
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
  const lockedDash = detail.last_dashboard_selection;
  const lockedDashChip =
    lockedDash && lockedDash.id != null
      ? `<span class="chip tool" title="Kilitli dashboard">🔒 ${esc(lockedDash.name || `Dashboard ${lockedDash.id}`)} (#${esc(lockedDash.id)})</span>`
      : "";
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
        ${lockedDashChip}
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
  const el = document.getElementById(targetId);
  if (!el) return;
  el.classList.remove("empty");

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

  el.innerHTML = `
    <div class="run-detail">
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
        job_id: run.job_id,
        qa_report: run.qa_report,
        fixes: run.fixes,
        summary: run.summary,
      })
    );
  } else {
    syncRunExportContext(run);
  }

  if (targetId === "feedback-run-block") {
    const title = document.getElementById("feedback-run-tab-title");
    const meta = document.getElementById("feedback-run-tab-meta");
    if (title) title.textContent = run.run_id || "QA & İyileştirme";
    if (meta) {
      const parts = [fmtDate(run.created_at)];
      if (verdict) parts.push(verdict);
      if (run.summary?.issue_count != null) parts.push(`${run.summary.issue_count} issue`);
      meta.textContent = parts.filter(Boolean).join(" · ");
    }
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
  const feedbackMeta = document.getElementById("feedback-session-meta");
  const feedbackDetail = document.getElementById("feedback-session-detail");
  if (feedbackTitle) feedbackTitle.textContent = title;
  if (feedbackMeta) {
    feedbackMeta.textContent = `${detail.turn_count || 0} tur · ${detail.sector || "?"}`;
  }
  if (feedbackDetail) {
    feedbackDetail.classList.remove("empty");
    feedbackDetail.innerHTML = body;
  }

  const sessionTitle = document.getElementById("session-title");
  const sessionDetail = document.getElementById("session-detail");
  const sessionToolbar = document.getElementById("session-toolbar");
  if (sessionTitle) sessionTitle.textContent = title;
  if (sessionDetail) {
    sessionDetail.classList.remove("empty");
    sessionDetail.innerHTML = body;
  }
  if (sessionToolbar) sessionToolbar.classList.remove("hidden");
  updateExportButtons();

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
let activeRunId = null;
let activeRunDetail = null;
let activeLiveJob = null;
let lastLiveTurnCount = 0;

const POLL_ACTIVE_MS = 2000;

function phaseLabelTr(phase) {
  const map = {
    queued: "Kuyruk",
    conversation: "Konuşma",
    qa: "QA",
    coding: "İyileştirme",
    done: "Bitti",
    error: "Hata",
  };
  return map[phase] || phase || "—";
}

function isJobLive(job) {
  return Boolean(job && ["queued", "running"].includes(job.status));
}

function updateActiveJobChrome(job) {
  if (!isJobLive(job)) return false;
  const line = job.session_id
    ? `${shortSessionId(job.session_id)} · ${phaseLabelTr(job.phase)} · ${job.turn_count || 0} konuşma turu`
    : `Yeni session hazırlanıyor · ${phaseLabelTr(job.phase)}`;
  const meta = document.getElementById("feedback-run-meta");
  const runTabTitle = document.getElementById("feedback-run-tab-title");
  const runTabMeta = document.getElementById("feedback-run-tab-meta");
  if (meta) meta.textContent = line;
  if (runTabTitle) runTabTitle.textContent = "Canlı session";
  if (runTabMeta) runTabMeta.textContent = line;
  return true;
}

function renderLiveWaitingPanel(job) {
  const msg =
    job.phase === "queued"
      ? "Yeni session kuyruğa alındı, CX Director başlatılıyor…"
      : job.message || "Yeni session oluşturuluyor — CX Director ilk senaryoyu hazırlıyor…";
  return `
    <div class="live-waiting">
      <div class="live-waiting-pulse" aria-hidden="true"></div>
      <p class="live-waiting-title">Yeni session başlıyor</p>
      <p class="live-waiting-desc">${esc(msg)}</p>
      <div class="chips live-waiting-chips">
        <span class="chip running">${esc(phaseLabelTr(job.phase))}</span>
        ${job.session_id ? `<span class="chip">${esc(shortSessionId(job.session_id))}</span>` : `<span class="chip">session bekleniyor</span>`}
      </div>
    </div>`;
}

function scrollLiveContainersToBottom() {
  ["feedback-session-detail", "live-run-body"].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  });
}

function highlightSessionInList(sessionId, containerId = "feedback-session-list") {
  const el = document.getElementById(containerId);
  if (!el || !sessionId) return;
  el.querySelectorAll(".list-item").forEach((node) => {
    node.classList.toggle("selected", node.dataset.sessionId === sessionId);
  });
}

function showLiveWaitingInConversation(job, sessionId = job.session_id) {
  if (sessionId) activeSessionId = sessionId;
  const feedbackTitle = document.getElementById("feedback-session-title");
  const feedbackMeta = document.getElementById("feedback-session-meta");
  const feedbackDetail = document.getElementById("feedback-session-detail");
  if (feedbackTitle) {
    feedbackTitle.textContent = sessionId ? shortSessionId(sessionId) : "Yeni session";
  }
  if (feedbackMeta) {
    feedbackMeta.textContent = `${job.turn_count || 0} tur · ${phaseLabelTr(job.phase)}`;
  }
  if (feedbackDetail) {
    feedbackDetail.classList.remove("empty");
    feedbackDetail.innerHTML = renderLiveWaitingPanel(job);
  }
  if (sessionId) {
    activeSessionId = sessionId;
    highlightSessionInList(sessionId);
  }
  updateWorkbenchToolbar({ job });
}

function syncLiveSessionFromJob(job) {
  if (!isJobLive(job)) return;
  updateActiveJobChrome(job);

  const sessionId = job.session_id;
  const turns = job.session_detail?.turns || [];
  if (turns.length) {
    const grew = turns.length > lastLiveTurnCount;
    lastLiveTurnCount = turns.length;
    showSessionDetail(job.session_detail, {
      runId: job.job_id,
      listContainerId: "feedback-session-list",
    });
    updateWorkbenchToolbar({ job });
    if (grew) scrollLiveContainersToBottom();
    return;
  }

  showLiveWaitingInConversation(job, sessionId);
}

function startActivePolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollActiveJob, POLL_ACTIVE_MS);
  pollActiveJob();
}

function stopActivePolling() {
  if (!pollTimer) return;
  clearInterval(pollTimer);
  pollTimer = null;
}

function setWorkbenchTab(tabName) {
  document.querySelectorAll(".workbench-tabs .tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  document.querySelectorAll(".workbench-panels .tab-panel").forEach((panel) => {
    const active = panel.id === `tab-${tabName}`;
    panel.classList.toggle("active", active);
    panel.classList.toggle("hidden", !active);
    if (active) {
      const body = panel.querySelector(".tab-panel-body");
      if (body) body.scrollTop = 0;
    }
  });
  if (tabName === "run-qa" && activeSessionId) {
    if (!activeRunDetail || activeRunDetail.session_id !== activeSessionId) {
      loadSessionRunPanel(activeSessionId).catch(() => {});
    } else {
      syncRunExportContext(activeRunDetail);
    }
  }
}

function updateWorkbenchToolbar({ job = activeLiveJob } = {}) {
  const liveBadge = document.getElementById("workbench-live-badge");
  const stopBtn = document.getElementById("toolbar-stop-btn");
  const langsmithLink = document.getElementById("toolbar-langsmith-link");
  const liveTabBtn = document.getElementById("live-tab-btn");

  const running = job && ["queued", "running"].includes(job.status);
  if (liveBadge) {
    if (running) {
      const vtx = job.vertex?.state && job.vertex.state !== "ok" ? ` · ${job.vertex.state}` : "";
      liveBadge.textContent = `${job.phase}${vtx}`;
      liveBadge.className = "badge running";
      liveBadge.title = job.message || "";
    } else {
      liveBadge.textContent = "Hazır";
      liveBadge.className = "badge";
      liveBadge.title = "";
    }
  }

  stopBtn?.classList.toggle("hidden", !running);
  liveTabBtn?.classList.toggle("hidden", !running);
  updateExportButtons();

  if (langsmithLink) {
    if (running && job.langsmith_url) {
      langsmithLink.href = job.langsmith_url;
      langsmithLink.classList.remove("hidden");
    } else {
      langsmithLink.classList.add("hidden");
    }
  }
}

function initWorkbenchTabs() {
  document.querySelectorAll(".workbench-tabs .tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => setWorkbenchTab(btn.dataset.tab));
  });
}

function renderStats(overview) {
  const c = overview.counts;
  const stats = [
    ["Session", c.sessions, "Toplam konuşma session sayısı"],
    ["Tamamlanan döngü", c.runs, "QA + coding bitmiş tam döngü sayısı"],
  ];
  if (c.ongoing_sessions > 0) {
    stats.push(["Devam eden", c.ongoing_sessions]);
  }
  stats.push(
    ["QA Issue", c.total_issues],
    ["Fix", c.total_fixes_applied]
  );
  document.getElementById("stats").innerHTML = stats
    .map(([label, value, hint]) => `<div class="stat-card"${hint ? ` title="${esc(hint)}"` : ""}><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`)
    .join("");
}

function renderList(containerId, items, onClick, labelFn, metaFn, { idKey = null, labelHtmlFn = null } = {}) {
  const el = document.getElementById(containerId);
  if (!items.length) {
    el.innerHTML = `<div class="empty">Kayıt yok</div>`;
    return;
  }
  el.innerHTML = items
    .map(
      (item, idx) => `
    <div class="list-item" data-idx="${idx}"${idKey && item[idKey] ? ` data-session-id="${esc(item[idKey])}"` : ""}>
      <div class="title">${labelHtmlFn ? labelHtmlFn(item) : esc(labelFn(item))}</div>
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

function sessionStatusChip(item) {
  const st = item.status || "";
  if (st === "ongoing") {
    const phase = item.job_phase ? ` · ${esc(item.job_phase)}` : "";
    return `<span class="chip running">${esc(item.status_label || "Devam")}${phase}</span>`;
  }
  if (st === "completed") {
    return `<span class="chip done">${esc(item.status_label || "Bitti")}</span>`;
  }
  if (st === "conversation_only") {
    return `<span class="chip muted-chip">${esc(item.status_label || "QA yok")}</span>`;
  }
  if (st === "empty") {
    return `<span class="chip muted-chip">${esc(item.status_label || "Boş")}</span>`;
  }
  return "";
}

function sessionPerfChips(item) {
  const chips = [];
  if (item.qa_verdict) {
    chips.push(`<span class="chip verdict ${esc(item.qa_verdict)}">${esc(item.qa_verdict)}</span>`);
  }
  if (item.issue_count > 0) {
    chips.push(`<span class="chip issue">${esc(item.issue_count)} issue</span>`);
  }
  if (item.avg_score != null && item.avg_score !== "") {
    chips.push(`<span class="chip score">${esc(item.avg_score)}/10</span>`);
  }
  if (!item.qa_verdict && item.warning_count > 0) {
    chips.push(`<span class="chip warn">${esc(item.warning_count)} uyarı</span>`);
  }
  return chips.join(" ");
}

function sessionListLabelHtml(item) {
  const isLiveSession =
    isJobLive(activeLiveJob) && activeLiveJob.session_id === item.session_id;
  return [
    isLiveSession ? `<span class="chip running">Yeni session</span>` : "",
    `<span class="session-id">${esc(shortSessionId(item.session_id))}</span>`,
    `<span class="chip">${esc(item.turn_count)} tur</span>`,
    sessionStatusChip(item),
    sessionPerfChips(item),
  ]
    .filter(Boolean)
    .join(" ");
}

function sessionListMeta(item) {
  const start = fmtDateTime(item.created_at);
  const end = fmtDateTime(item.updated_at || item.modified_at);
  const preview = item.preview ? clipText(item.preview, 72) : "";
  const sector = item.sector ? ` · ${item.sector}` : "";
  return `${start}${end !== start ? ` → ${end}` : ""}${sector}${preview ? ` · ${preview}` : ""}`;
}

function renderSessionQaEmptyState(detail, { statusLabel = null } = {}) {
  const sid = detail?.session_id || "—";
  const turns = detail?.turn_count || 0;
  const label = statusLabel || (turns > 0 ? "QA yok" : "Boş session");
  const reason =
    label === "Devam ediyor"
      ? "Quality loop döngüsü hâlâ çalışıyor. QA raporu döngü bitince burada görünür."
      : turns > 0
        ? "Konuşma kaydedildi ama tamamlanmış bir döngü (run) yok. Döngü hata vermiş veya henüz QA aşamasına geçilmemiş olabilir."
        : "Bu session'da henüz konuşma yok.";
  return `
    <div class="qa-empty-state">
      <h4>Bu session için QA yok</h4>
      <p>${esc(reason)}</p>
      <div class="meta-block muted-small">
        <p><strong>Session</strong> = tek konuşma kaydı (CX Director ↔ Advisor mesajları)</p>
        <p><strong>Run</strong> = o session üzerinde tamamlanan tam döngü (konuşma + QA + coding)</p>
        <p>Session: <code>${esc(sid)}</code> · ${esc(turns)} tur · ${esc(label)}</p>
      </div>
    </div>`;
}

function updateSessionRunChrome(sessionId, { runDetail = null, emptyReason = null } = {}) {
  const meta = document.getElementById("feedback-run-meta");
  const runTabMeta = document.getElementById("feedback-run-tab-meta");
  if (runDetail?.run_id) {
    const qa = runDetail.qa_report || {};
    const verdict = qa.overall_verdict || runDetail.summary?.verdict;
    if (meta) {
      meta.textContent = `${runDetail.run_id} · ${shortSessionId(sessionId)} · ${fmtDate(runDetail.created_at)}`;
    }
    if (runTabMeta) {
      const parts = [verdict, runDetail.summary?.issue_count != null ? `${runDetail.summary.issue_count} issue` : null];
      runTabMeta.textContent = parts.filter(Boolean).join(" · ");
    }
    return;
  }
  activeRunId = null;
  activeRunDetail = null;
  if (meta) meta.textContent = `${shortSessionId(sessionId)} · QA yok`;
  if (runTabMeta) runTabMeta.textContent = emptyReason || "Tamamlanmış döngü yok";
}

async function loadSessionRunPanel(sessionId, sessionDetail = null, { statusLabel = null } = {}) {
  const runBlock = document.getElementById("feedback-run-block");
  if (!sessionId || !runBlock) return;

  let detail = sessionDetail;
  if (!detail) {
    detail = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  }
  const runId = detail.run_id || detail.linked_runs?.[0]?.run_id || null;

  if (!runId) {
    runBlock.classList.add("empty");
    runBlock.innerHTML = renderSessionQaEmptyState(detail, { statusLabel });
    updateSessionRunChrome(sessionId, { emptyReason: statusLabel || "QA raporu yok" });
    return;
  }

  try {
    const run = await api(`/api/runs/${encodeURIComponent(runId)}`);
    renderRunDetail(run, "feedback-run-block", { includeSession: false });
    updateSessionRunChrome(sessionId, { runDetail: run });
  } catch (err) {
    runBlock.classList.add("empty");
    runBlock.innerHTML = `<div class="empty">Run yüklenemedi: ${esc(err.message)}</div>`;
    updateSessionRunChrome(sessionId, { emptyReason: "Run yüklenemedi" });
  }
}

async function selectSessionById(sessionId, { runId = null, listContainerId = null, statusLabel = null } = {}) {
  if (!sessionId) return;
  const detail = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  showSessionDetail(detail, { runId: runId || detail.run_id, listContainerId });
  await loadSessionRunPanel(sessionId, detail, { statusLabel });
}

function autoSelectSessionItem(containerId, sessionId) {
  const el = document.getElementById(containerId);
  if (!el || !sessionId) return;
  const node =
    el.querySelector(`.list-item[data-session-id="${sessionId}"]`) ||
    el.querySelector(".list-item");
  node?.click();
}

async function loadFeedback({ preserveActiveJob = false } = {}) {
  const sessions = await api("/api/sessions");
  const runBlock = document.getElementById("feedback-run-block");
  const countBadge = document.getElementById("session-count-badge");
  if (countBadge) countBadge.textContent = String(sessions.length);
  const keepActiveChrome =
    preserveActiveJob && isJobLive(activeLiveJob) && updateActiveJobChrome(activeLiveJob);

  if (!sessions.length) {
    document.getElementById("feedback-session-list").innerHTML =
      `<div class="empty">Henüz konuşma yok</div>`;
  } else {
    renderList(
      "feedback-session-list",
      sessions,
      async (item) => {
        await selectSessionById(item.session_id, {
          listContainerId: "feedback-session-list",
          statusLabel: item.status_label,
        });
        setWorkbenchTab("conversation");
      },
      sessionListLabel,
      sessionListMeta,
      { idKey: "session_id", labelHtmlFn: sessionListLabelHtml }
    );
  }

  if (!sessions.length) {
    runBlock.classList.add("empty");
    runBlock.innerHTML =
      `<div class="empty">Henüz session yok. Sunucuda döngü çalıştır veya <button class="btn" onclick="document.getElementById('sync-hint-btn').click()">sync</button> yap.</div>`;
    document.getElementById("feedback-run-meta").textContent = "";
    const runTabTitle = document.getElementById("feedback-run-tab-title");
    const runTabMeta = document.getElementById("feedback-run-tab-meta");
    if (runTabTitle) runTabTitle.textContent = "QA & İyileştirme";
    if (runTabMeta) runTabMeta.textContent = "";
    return;
  }

  const preferId =
    (keepActiveChrome && activeLiveJob?.session_id) ||
    activeSessionId ||
    sessions[0]?.session_id;
  if (preferId) {
    highlightSessionInList(preferId);
    if (!keepActiveChrome) {
      if (activeSessionId && activeSessionId === preferId) {
        const sessionItem = sessions.find((s) => s.session_id === preferId);
        await selectSessionById(preferId, {
          listContainerId: "feedback-session-list",
          statusLabel: sessionItem?.status_label,
        });
      } else {
        autoSelectSessionItem("feedback-session-list", preferId);
      }
    }
  }
}

async function loadRuns() {
  const runs = await api("/api/runs");
  renderList(
    "run-list",
    runs,
    async (item) => {
      const detail = await api(`/api/runs/${encodeURIComponent(item.run_id)}`);
      document.getElementById("run-title").textContent = item.run_id;
      if (detail.session_id) {
        activeSessionId = detail.session_id;
        updateExportButtons();
      }
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
    { idKey: "session_id", labelHtmlFn: sessionListLabelHtml }
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
  const withFixes = runs.filter(
    (r) => (r.summary?.fixes_applied || 0) > 0 || (r.summary?.fixes_skipped || 0) > 0
  );
  if (!withFixes.length) {
    document.getElementById("improvements-board").innerHTML = `<div class="empty">Fix kaydı yok</div>`;
    return;
  }
  const blocks = await Promise.all(
    withFixes.slice(0, 20).map((r) => api(`/api/runs/${encodeURIComponent(r.run_id)}`))
  );
  document.getElementById("improvements-board").innerHTML = blocks
    .map((run) => {
      const sessionId = run.session_id || "";
      const sessionLink = sessionId
        ? `<button type="button" class="link-btn session-link" data-open-session="${esc(sessionId)}" data-run-id="${esc(run.run_id)}">${esc(shortSessionId(sessionId))}</button>`
        : `<span class="muted-small">—</span>`;
      const verdict = run.qa_report?.overall_verdict;
      const verdictChip = verdict
        ? `<span class="verdict ${esc(verdict)}">${esc(verdict)}</span>`
        : "";
      return `
    <article class="improvement-card">
      <div class="improvement-card-head">
        <div>
          <h4 class="improvement-run-id">${esc(run.run_id)}</h4>
          <p class="improvement-meta">
            <span>${esc(fmtDateTime(run.created_at))}</span>
            · Konuşma: ${sessionLink}
            · ${esc(run.summary?.issue_count ?? 0)} QA issue
          </p>
        </div>
        <div class="improvement-card-actions">
          ${verdictChip}
          <button type="button" class="btn ghost btn-sm improvement-download" data-run-id="${esc(run.run_id)}">↓ İndir</button>
        </div>
      </div>
      ${renderFixes(run.fixes || {}, { showScenarios: true, showDiffs: true })}
    </article>`;
    })
    .join("");

  const board = document.getElementById("improvements-board");
  board.querySelectorAll("[data-open-session]").forEach((btn) => {
    btn.addEventListener("click", () => {
      openSessionFromImprovement(btn.dataset.openSession, btn.dataset.runId || null);
    });
  });
  board.querySelectorAll(".improvement-download").forEach((btn) => {
    btn.addEventListener("click", () => downloadImprovementsExport(btn.dataset.runId));
  });
}

async function apiPost(path, body) {
  const { base } = getApiConfig();
  const rel = path.startsWith("/") ? path.slice(1) : path;
  const url = base ? `${base.replace(/\/$/, "")}/${rel}` : rel;
  const res = await fetch(
    url,
    fetchOptions({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
  if (res.status === 401) {
    if (!getApiConfig().remote) showLoginOverlay();
    throw new Error("login required");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `${url} → ${res.status}`);
  }
  return res.json();
}

async function apiPut(path, body) {
  const { base } = getApiConfig();
  const rel = path.startsWith("/") ? path.slice(1) : path;
  const url = base ? `${base.replace(/\/$/, "")}/${rel}` : rel;
  const res = await fetch(
    url,
    fetchOptions({
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
  if (res.status === 401) {
    if (!getApiConfig().remote) showLoginOverlay();
    throw new Error("login required");
  }
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

function hasQaExportData(ctx = exportContext) {
  const qa = ctx?.meta?.qa_report;
  return Boolean(qa?.overall_verdict || qa?.issues?.length || qa?.priority_fix);
}

function getActiveWorkbenchTab() {
  const btn = document.querySelector(".workbench-tabs .tab-btn.active");
  return btn?.dataset?.tab || "conversation";
}

function canExportAnything() {
  return Boolean(activeSessionId || activeRunId || activeRunDetail?.run_id);
}

function updateExportButtons() {
  const visible = canExportAnything();
  document.getElementById("toolbar-export-btn")?.classList.toggle("hidden", !visible);
  document.getElementById("session-export-btn")?.classList.toggle("hidden", !visible);
}

async function refreshExportContextFromRun(runId) {
  if (!runId) return null;
  const run = await api(`/api/runs/${encodeURIComponent(runId)}`);
  activeRunDetail = run;
  activeRunId = run.run_id || runId;
  syncRunExportContext(run);
  return exportContext;
}

async function refreshExportContextForSession(sessionId) {
  if (!sessionId) return null;
  const detail = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  const payload = buildExportPayloadFromDetail(detail, {
    run_id: detail.run_id,
    qa_report: detail.qa_report,
  });
  setExportContext(payload);
  return payload;
}

async function refreshExportContext() {
  const tab = getActiveWorkbenchTab();
  if (tab === "run-qa" && activeSessionId) {
    const detail = await api(`/api/sessions/${encodeURIComponent(activeSessionId)}`);
    const runId = detail.run_id || detail.linked_runs?.[0]?.run_id || null;
    if (runId) {
      return refreshExportContextFromRun(runId);
    }
    const payload = buildExportPayloadFromDetail(detail, {
      run_id: detail.run_id,
      qa_report: detail.qa_report,
    });
    setExportContext(payload);
    return payload;
  }
  if (activeSessionId) {
    return refreshExportContextForSession(activeSessionId);
  }
  if (activeRunId || activeRunDetail?.run_id) {
    return refreshExportContextFromRun(activeRunId || activeRunDetail.run_id);
  }
  return null;
}

function updateExportModalState() {
  const hasConv = Boolean(exportContext?.messages?.length);
  const hasQa = hasQaExportData();
  const qaHint = document.getElementById("export-qa-hint");
  if (qaHint) {
    if (hasQa) {
      const run = exportContext?.meta?.run_id;
      const issueCount = (exportContext?.meta?.qa_report?.issues || []).length;
      const verdict = exportContext?.meta?.qa_report?.overall_verdict || "—";
      qaHint.textContent = run
        ? `${run} · ${issueCount} issue · ${verdict}`
        : `${issueCount} issue · ${verdict}`;
    } else {
      qaHint.textContent =
        getActiveWorkbenchTab() === "run-qa"
          ? "Görüntülenen run için QA verisi yüklenemedi"
          : "Bu session için QA raporu yok";
    }
  }
  document.getElementById("export-qa-section")?.classList.toggle("export-unavailable", !hasQa);
  document.getElementById("export-full-section")?.classList.toggle("export-unavailable", !hasConv || !hasQa);
  for (const id of [
    "export-conversation-json-btn",
    "export-conversation-md-btn",
    "export-full-json-btn",
  ]) {
    document.getElementById(id)?.toggleAttribute("disabled", !hasConv);
  }
  for (const id of ["export-qa-json-btn", "export-qa-md-btn"]) {
    document.getElementById(id)?.toggleAttribute("disabled", !hasQa);
  }
}

function syncRunExportContext(run) {
  if (!run) return;
  activeRunId = run.run_id || null;
  activeRunDetail = run;
  const sessionDetail = run.session_detail;
  const messages = sessionDetail?.turns?.length
    ? window.QlExport.turnsToMessages(sessionDetail.turns)
    : [];
  setExportContext({
    sessionId: run.session_id || sessionDetail?.session_id || null,
    title: run.run_id || shortSessionId(run.session_id || "qa"),
    messages,
    meta: {
      session_id: run.session_id || sessionDetail?.session_id || null,
      sector: sessionDetail?.sector || null,
      user_email: sessionDetail?.user_email || null,
      user_id: sessionDetail?.user_id || null,
      run_id: run.run_id || null,
      job_id: run.job_id || null,
      turn_count: sessionDetail?.turns?.length || null,
      qa_report: run.qa_report || null,
      fixes: run.fixes || null,
      summary: run.summary || null,
    },
  });
}

function setExportContext(ctx) {
  exportContext = ctx;
  const subtitle = document.getElementById("export-modal-subtitle");
  if (subtitle) {
    const parts = [];
    if (ctx?.meta?.run_id) parts.push(ctx.meta.run_id);
    const sid = ctx?.sessionId || ctx?.meta?.session_id || activeSessionId;
    if (sid) parts.push(shortSessionId(sid));
    if (ctx?.messages?.length) parts.push(`${ctx.messages.length} mesaj`);
    if (hasQaExportData(ctx)) parts.push("QA raporu");
    subtitle.textContent = parts.join(" · ");
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
      job_id: extra.job_id || null,
      turn_count: turns.length,
      qa_report: detail.qa_report || extra.qa_report || null,
      fixes: extra.fixes || null,
      summary: extra.summary || null,
      ...extra,
    },
  };
}

async function openExportModal() {
  if (!canExportAnything()) return;
  try {
    await refreshExportContext();
  } catch (err) {
    alert(`Export verisi yüklenemedi: ${err.message}`);
    return;
  }
  if (!exportContext?.messages?.length && !hasQaExportData()) {
    alert("İndirilebilir konuşma veya QA verisi yok.");
    return;
  }
  updateExportModalState();
  document.getElementById("export-modal")?.classList.remove("hidden");
}

function closeExportModal() {
  document.getElementById("export-modal")?.classList.add("hidden");
}

function currentExportSessionId() {
  return (
    exportContext?.sessionId ||
    exportContext?.meta?.session_id ||
    activeRunDetail?.session_id ||
    activeSessionId ||
    null
  );
}

function currentExportRunId() {
  return exportContext?.meta?.run_id || activeRunId || activeRunDetail?.run_id || null;
}

async function downloadRunQaExport(runId, format = "json") {
  const ext = format === "md" ? "export.md" : "export.json";
  const url = apiUrl(`api/runs/${encodeURIComponent(runId)}/qa/${ext}`);
  const res = await fetch(url, fetchOptions());
  if (res.status === 401) {
    showLoginOverlay();
    throw new Error("login required");
  }
  if (!res.ok) throw new Error(`${res.status}`);
  const blob = await res.blob();
  const disp = res.headers.get("Content-Disposition") || "";
  const match = disp.match(/filename="?([^";]+)"?/);
  const fallback = `pivony-quality-loop-qa-${String(runId).slice(0, 24)}.${format === "md" ? "md" : "json"}`;
  const filename = match?.[1] || fallback;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function downloadExportConversationJson() {
  const sid = currentExportSessionId();
  if (!sid) return;
  try {
    await downloadSessionExport(sid, "json", null, "conversation", currentExportRunId());
    closeExportModal();
  } catch (err) {
    alert(`Konuşma indirilemedi: ${err.message}`);
  }
}

async function downloadExportConversationMarkdown() {
  const sid = currentExportSessionId();
  if (!sid) return;
  try {
    await downloadSessionExport(sid, "md", null, "conversation", currentExportRunId());
    closeExportModal();
  } catch (err) {
    alert(`Konuşma indirilemedi: ${err.message}`);
  }
}

async function downloadExportQaJson() {
  const runId = currentExportRunId();
  const sid = currentExportSessionId();
  try {
    if (runId && hasQaExportData()) {
      await downloadRunQaExport(runId, "json");
    } else if (sid) {
      await downloadSessionExport(sid, "json", null, "qa", runId);
    } else {
      return;
    }
    closeExportModal();
  } catch (err) {
    alert(`QA indirilemedi: ${err.message}`);
  }
}

async function downloadExportQaMarkdown() {
  const runId = currentExportRunId();
  const sid = currentExportSessionId();
  try {
    if (runId && hasQaExportData()) {
      await downloadRunQaExport(runId, "md");
    } else if (sid) {
      await downloadSessionExport(sid, "md", null, "qa", runId);
    } else {
      return;
    }
    closeExportModal();
  } catch (err) {
    alert(`QA indirilemedi: ${err.message}`);
  }
}

async function downloadExportFullJson() {
  const sid = currentExportSessionId();
  if (!sid) return;
  try {
    await downloadSessionExport(sid, "json", null, "all", currentExportRunId());
    closeExportModal();
  } catch (err) {
    alert(`Tam paket indirilemedi: ${err.message}`);
  }
}

function apiUrl(path) {
  const { base } = getApiConfig();
  const rel = path.startsWith("/") ? path.slice(1) : path;
  if (base) return `${base.replace(/\/$/, "")}/${rel}`;
  const mount = getMountBase();
  if (mount) return `${mount}/${rel}`;
  return rel;
}

async function downloadSessionExport(
  sessionId,
  format = "json",
  jobId = null,
  scope = "conversation",
  runId = null
) {
  const ext = format === "md" ? "export.md" : "export.json";
  const params = new URLSearchParams({ scope });
  if (runId) params.set("run_id", runId);
  else if (jobId) params.set("job_id", jobId);
  const url = apiUrl(`api/sessions/${encodeURIComponent(sessionId)}/${ext}?${params}`);
  const res = await fetch(url, fetchOptions());
  if (res.status === 401) {
    showLoginOverlay();
    throw new Error("login required");
  }
  if (!res.ok) throw new Error(`${res.status}`);
  const blob = await res.blob();
  const disp = res.headers.get("Content-Disposition") || "";
  const match = disp.match(/filename="?([^";]+)"?/);
  const fallback =
    scope === "qa"
      ? `pivony-quality-loop-qa-${String(runId || sessionId).slice(0, 20)}.${format === "md" ? "md" : "json"}`
      : scope === "all"
        ? `pivony-quality-loop-full-${String(sessionId).slice(0, 12)}.${format === "md" ? "md" : "json"}`
        : `pivony-quality-loop-conversation-${String(sessionId).slice(0, 12)}.${format === "md" ? "md" : "json"}`;
  const filename = match?.[1] || fallback;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

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
  const body = document.getElementById("live-run-body");
  activeLiveJob = job || null;
  updateRunButtons(job);
  updateWorkbenchToolbar({ job });

  if (!isJobLive(job)) {
    lastLiveTurnCount = 0;
    if (body) body.innerHTML = `<div class="empty">Aktif session yok</div>`;
    return;
  }

  syncLiveSessionFromJob(job);

  const qa = job.qa_preview;
  const liveThread = job.session_detail?.turns?.length
    ? `<section class="live-thread-section">
        <h4 class="run-section-title">Canlı konuşma</h4>
        <div class="conversation-thread live-embedded-thread">${renderTurns(
          job.session_detail.turns,
          job.session_detail.auto_issues,
          { collapsibleReasoning: false }
        )}</div>
      </section>`
    : `<section class="live-thread-section">${renderLiveWaitingPanel(job)}</section>`;

  if (body) {
    body.innerHTML = `
      ${renderVertexBanner(job)}
      <div class="live-compact-flow">${renderFlowSteps(job.flow)}</div>
      <details class="live-meta-fold">
        <summary>LangSmith &amp; izleme detayı</summary>
        ${renderLangSmithBlock(job.observability, job.job_id)}
      </details>
      <div class="chips" style="margin:0.75rem 0">
        <span class="chip running">${esc(phaseLabelTr(job.phase))}</span>
        <span class="chip">${esc(job.turn_count || 0)} tur</span>
        ${job.session_id ? `<span class="chip">${esc(shortSessionId(job.session_id))}</span>` : `<span class="chip">session bekleniyor</span>`}
      </div>
      ${qa?.priority_fix ? `<div class="meta-block verdict-box"><h4>QA önizleme</h4><p>${esc(qa.priority_fix)}</p>${renderIssues(qa.issues || [], { compact: true })}</div>` : ""}
      ${liveThread}
      <p class="muted-small">Konuşma akışı <strong>Konuşma</strong> sekmesinde de canlı güncellenir.</p>
    `;
    if (job.session_detail?.turns?.length) scrollLiveContainersToBottom();
  }

  if (job.session_id && job.session_detail?.turns?.length) {
    const livePayload = buildExportPayloadFromDetail(job.session_detail, {
      job_id: job.job_id,
      session_id: job.session_id,
    });
    setExportContext(livePayload);
  }
}

async function refreshSessionListsIfVisible() {
  const view = viewFromLocation();
  const selected = activeSessionId;
  if (view === "feedback") {
    await loadFeedback({ preserveActiveJob: true });
    if (isJobLive(activeLiveJob) && activeLiveJob.session_id) {
      highlightSessionInList(activeLiveJob.session_id);
    } else if (selected) {
      autoSelectSessionItem("feedback-session-list", selected);
    }
  } else if (view === "sessions") {
    await loadSessions();
    if (selected) autoSelectSessionItem("session-list", selected);
  }
}

async function pollActiveJob() {
  try {
    const [job, sessions] = await Promise.all([
      api("/api/jobs/active"),
      api("/api/sessions").catch(() => []),
    ]);
    renderLiveRun(job);
    const jobActive = job && ["queued", "running"].includes(job.status);
    const hasOngoing = (sessions || []).some((s) => s.status === "ongoing");
    updateRunButtons(jobActive ? job : null);

    if (jobActive || hasOngoing) {
      if (!pollTimer) pollTimer = setInterval(pollActiveJob, POLL_ACTIVE_MS);
      await refreshSessionListsIfVisible();
      const overview = await api("/api/overview");
      renderStats(overview);
    } else {
      stopActivePolling();
      lastLiveTurnCount = 0;
      if (job && job.status === "completed") await refreshAll();
    }
  } catch (err) {
    console.error(err);
    updateRunButtons(null);
  }
}

async function stopRun() {
  if (!confirm("Aktif session durdurulsun mu?")) return;
  const btn = document.getElementById("stop-run-btn");
  btn.disabled = true;
  try {
    await apiPost("/api/jobs/stop", {});
    stopActivePolling();
    lastLiveTurnCount = 0;
    updateWorkbenchToolbar({ job: null });
    updateRunButtons(null);
    await refreshAll();
  } catch (err) {
    alert(`Durdurulamadı: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
}
window.stopRun = stopRun;

async function loadPromptIntoEditor() {
  const sector = selectedPromptSector();
  const agent = document.getElementById("prompt-agent")?.value || "qa";
  const data = await api(`/api/prompts/${agent}?sector=${encodeURIComponent(sector)}`);
  const textarea = document.getElementById("prompt-content");
  if (textarea) textarea.value = data.content;
  const meta = document.getElementById("prompt-meta");
  if (meta) {
    let hint = data.path || "";
    if (data.uses_default) hint += " · varsayılan kullanılıyor (bu sektör için override yok)";
    if (data.is_override) hint += " · sektör override aktif";
    meta.textContent = hint;
  }
  localStorage.setItem("ql_run_sector", sector);
}

async function savePrompt() {
  const sector = selectedPromptSector();
  const agent = document.getElementById("prompt-agent")?.value || "qa";
  const content = document.getElementById("prompt-content")?.value || "";
  const status = document.getElementById("prompt-save-status");
  if (!content.trim()) {
    if (status) status.textContent = "Prompt boş olamaz";
    return;
  }
  if (status) status.textContent = "Kaydediliyor…";
  try {
    const data = await apiPut(`/api/prompts/${agent}?sector=${encodeURIComponent(sector)}`, { content });
    if (status) status.textContent = `Kaydedildi · ${data.path}`;
    localStorage.setItem("ql_run_sector", sector);
    await loadPromptIntoEditor();
  } catch (err) {
    if (status) status.textContent = `Hata: ${err.message}`;
  }
}

function renderRepoScopeEditor(scope) {
  const repos = scope?.repos || [];
  const blocked = new Set(scope?.blocked_write_repos || ["pivony-api-dev", "pivony-api"]);
  const writeRepo = scope?.write_repo || "pivony-advisor";
  const readRepos = new Set(scope?.read_repos || []);
  const writeOptions = repos.filter((r) => !blocked.has(r.id));
  const readOptions = repos
    .filter((r) => r.id !== writeRepo)
    .map(
      (r) =>
        `<option value="${esc(r.id)}"${readRepos.has(r.id) ? " selected" : ""}>${esc(r.label)}</option>`
    )
    .join("");
  return `
    <div class="repo-scope-editor">
      <div class="panel-header panel-header-split">
        <h3>Coding Agent Repoları</h3>
        <span id="repo-save-status" class="muted-small"></span>
      </div>
      <p class="flow-desc">masterr altındaki repolar. <strong>Write</strong> = fix yazılır; <strong>Read</strong> = salt okunur keşif. MCP fix'leri <code>pivony-mcp/</code> prefix ile yazılabilir. <code>pivony-api-dev</code> bloklu.</p>
      <p class="muted-small">Kök: ${esc(scope?.masterr_root || "—")}</p>
      <div class="prompt-controls">
        <label>Fix yazılacak repo
          <select id="repo-write">${writeOptions
            .map(
              (r) =>
                `<option value="${esc(r.id)}"${r.id === writeRepo ? " selected" : ""}>${esc(r.label)}</option>`
            )
            .join("")}</select>
        </label>
        <label>İncelenecek repolar
          <select id="repo-read" class="repo-read-multi" multiple size="8">${readOptions || '<option disabled>—</option>'}</select>
        </label>
        <button id="repo-save-btn" class="btn primary btn-sm" type="button">Kaydet</button>
      </div>
      <p class="muted-small">${esc(scope?.prefix_help || "")}</p>
    </div>`;
}

function selectedReadRepos() {
  const el = document.getElementById("repo-read");
  if (!el) return [];
  return Array.from(el.selectedOptions).map((o) => o.value);
}

async function saveRepoScope() {
  const writeRepo = document.getElementById("repo-write")?.value || "";
  const readRepos = selectedReadRepos();
  const status = document.getElementById("repo-save-status");
  if (!writeRepo) {
    if (status) status.textContent = "Write repo seçin";
    return;
  }
  if (status) status.textContent = "Kaydediliyor…";
  try {
    const data = await apiPut("/api/repos/scope", { write_repo: writeRepo, read_repos: readRepos });
    if (status) {
      status.textContent = `Kaydedildi · write: ${data.write_repo}, read: ${(data.read_repos || []).join(", ") || "—"}`;
    }
    localStorage.setItem("ql_write_repo", data.write_repo);
    localStorage.setItem("ql_read_repos", JSON.stringify(data.read_repos || []));
  } catch (err) {
    if (status) status.textContent = `Hata: ${err.message}`;
  }
}

function wireRepoScopeEditor() {
  if (repoEditorWired) return;
  repoEditorWired = true;
  document.getElementById("repo-write")?.addEventListener("change", () => {
    const writeRepo = document.getElementById("repo-write")?.value;
    const readEl = document.getElementById("repo-read");
    if (!readEl || !writeRepo) return;
    const selected = new Set(selectedReadRepos());
    Array.from(readEl.options).forEach((opt) => {
      if (opt.value === writeRepo) {
        opt.selected = false;
        opt.disabled = true;
      } else {
        opt.disabled = false;
        opt.selected = selected.has(opt.value);
      }
    });
  });
  document.getElementById("repo-save-btn")?.addEventListener("click", () => saveRepoScope());
}

function renderPromptEditor(meta) {
  const sectors = meta?.sectors || [{ id: "default", label: "Varsayılan (genel)" }];
  const agents = meta?.agents || [];
  const savedSector = localStorage.getItem("ql_run_sector") || "default";
  return `
    <div class="prompt-editor">
      <div class="panel-header panel-header-split">
        <h3>Agent Promptları</h3>
        <span id="prompt-save-status" class="muted-small"></span>
      </div>
      <p class="flow-desc">Run başlatırken seçilen sektörün QA rubric ve CX persona dosyaları kullanılır.</p>
      <div class="prompt-controls">
        <label>Sektör
          <select id="prompt-sector">${sectors
            .map(
              (s) =>
                `<option value="${esc(s.id)}"${s.id === savedSector ? " selected" : ""}>${esc(s.label)}</option>`
            )
            .join("")}</select>
        </label>
        <label>Yeni sektör slug
          <input id="prompt-sector-custom" type="text" placeholder="örn. insurance" />
        </label>
        <label>Agent
          <select id="prompt-agent">${agents
            .map((a) => `<option value="${esc(a.id)}">${esc(a.label)}</option>`)
            .join("")}</select>
        </label>
        <button id="prompt-save-btn" class="btn primary btn-sm" type="button">Kaydet</button>
      </div>
      <p id="prompt-meta" class="muted-small"></p>
      <textarea id="prompt-content" class="prompt-textarea" rows="18" spellcheck="false"></textarea>
    </div>`;
}

function wirePromptEditor() {
  if (promptEditorWired) return;
  promptEditorWired = true;
  document.getElementById("prompt-sector")?.addEventListener("change", () => loadPromptIntoEditor());
  document.getElementById("prompt-sector-custom")?.addEventListener("input", () => loadPromptIntoEditor());
  document.getElementById("prompt-agent")?.addEventListener("change", () => loadPromptIntoEditor());
  document.getElementById("prompt-save-btn")?.addEventListener("click", () => savePrompt());
}

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

    ${renderRepoScopeEditor(arch.repo_scope)}
    ${renderPromptEditor(arch.prompts)}
  `;
  promptEditorWired = false;
  repoEditorWired = false;
  wireRepoScopeEditor();
  wirePromptEditor();
  await loadPromptIntoEditor();
}

async function startRun() {
  const btn = document.getElementById("start-run-btn");
  btn.disabled = true;
  btn.textContent = "Başlatılıyor…";
  try {
    setView("feedback");
    lastLiveTurnCount = 0;
    const sector = localStorage.getItem("ql_run_sector") || "default";
    const job = await apiPost("/api/jobs/start", { mode: "full", iterations: 1, sector });
    renderLiveRun(job);
    setWorkbenchTab("conversation");
    startActivePolling();
  } catch (err) {
    alert(`Session başlatılamadı: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "▶ Yeni Session Başlat";
  }
}

function updateSourceBadge() {
  const { base } = getApiConfig();
  document.getElementById("source-badge").textContent = base ? `Kaynak: ${base}` : "Kaynak: local";
}

async function refreshCurrentView() {
  const overview = await api("/api/overview");
  renderStats(overview);
  const view = viewFromLocation();
  await navigateToView(view, { syncUrl: false });
  await pollActiveJob();
  updateSourceBadge();
}

async function manualRefresh() {
  const btn = document.getElementById("refresh-btn");
  if (btn?.disabled) return;
  const label = btn?.textContent || "↻ Yenile";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Yenileniyor…";
  }
  try {
    await refreshCurrentView();
  } catch (err) {
    console.error(err);
    const subtitle = document.getElementById("subtitle");
    if (subtitle) subtitle.textContent = `Yenileme hatası: ${err.message}`;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = label;
    }
  }
}

async function refreshAll() {
  await refreshCurrentView();
}

async function boot() {
  const urlToken = new URLSearchParams(window.location.search).get("token");
  if (urlToken) sessionStorage.setItem("ql_session_token", urlToken.trim());

  const { base, token } = getApiConfig();
  document.getElementById("api-base").value = base;
  document.getElementById("api-token").value = token;
  updateRemoteTokenVisibility();
  document.getElementById("sync-command").textContent =
    "cd pivony-advisor && bash scripts/sync_quality_loop_outputs.sh";

  document.getElementById("login-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const password = document.getElementById("login-password")?.value || "";
    try {
      await establishSession(password);
      hideLoginOverlay();
      document.getElementById("login-password").value = "";
      document.getElementById("logout-btn")?.classList.remove("hidden");
      const cleanUrl = window.location.pathname + window.location.hash;
      history.replaceState(history.state, "", cleanUrl);
      await refreshAll();
    } catch (err) {
      showLoginOverlay(formatApiErrorDetail(err.message) || "Giriş başarısız");
    }
  });

  document.getElementById("logout-btn")?.addEventListener("click", async () => {
    await logoutSession();
    sessionStorage.removeItem("ql_session_token");
    document.getElementById("logout-btn")?.classList.add("hidden");
  });

  document.getElementById("settings-btn").addEventListener("click", () => {
    document.getElementById("settings-panel").classList.toggle("hidden");
  });
  document.getElementById("settings-save").addEventListener("click", async () => {
    setApiConfig(document.getElementById("api-base").value, document.getElementById("api-token").value);
    document.getElementById("settings-panel").classList.add("hidden");
    await refreshAll();
  });

  document.getElementById("refresh-btn")?.addEventListener("click", () => {
    manualRefresh().catch(console.error);
  });
  document.getElementById("sync-hint-btn").addEventListener("click", () => {
    document.getElementById("sync-modal").classList.remove("hidden");
  });
  document.getElementById("sync-close").addEventListener("click", () => {
    document.getElementById("sync-modal").classList.add("hidden");
  });

  document.getElementById("session-export-btn")?.addEventListener("click", openExportModal);
  document.getElementById("toolbar-export-btn")?.addEventListener("click", openExportModal);
  document.getElementById("toolbar-stop-btn")?.addEventListener("click", stopRun);
  initWorkbenchTabs();
  document.getElementById("export-conversation-json-btn")?.addEventListener("click", downloadExportConversationJson);
  document.getElementById("export-conversation-md-btn")?.addEventListener("click", downloadExportConversationMarkdown);
  document.getElementById("export-qa-json-btn")?.addEventListener("click", downloadExportQaJson);
  document.getElementById("export-qa-md-btn")?.addEventListener("click", downloadExportQaMarkdown);
  document.getElementById("export-full-json-btn")?.addEventListener("click", downloadExportFullJson);
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
      if (!canExportAnything()) return;
      e.preventDefault();
      openExportModal();
    },
    true
  );

  document.getElementById("start-run-btn").addEventListener("click", startRun);
  document.getElementById("stop-run-btn").addEventListener("click", stopRun);

  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await navigateToView(btn.dataset.view);
      } catch (err) {
        console.error(err);
      }
    });
  });

  window.addEventListener("popstate", () => {
    navigateToView(viewFromLocation(), { syncUrl: false }).catch(console.error);
  });

  const auth = await checkAuthStatus();
  if (auth.auth_required && !auth.authenticated && !getApiConfig().remote) {
    const urlToken =
      new URLSearchParams(window.location.search).get("token") ||
      sessionStorage.getItem("ql_session_token");
    if (urlToken) {
      try {
        await establishSession(urlToken);
        hideLoginOverlay();
        document.getElementById("logout-btn")?.classList.remove("hidden");
        const cleanUrl = window.location.pathname + window.location.hash;
        history.replaceState(history.state, "", cleanUrl);
      } catch {
        showLoginOverlay("Şifre hatalı veya oturum açılamadı");
        document.getElementById("logout-btn")?.classList.add("hidden");
        return;
      }
    } else {
      showLoginOverlay();
      document.getElementById("logout-btn")?.classList.add("hidden");
      return;
    }
  } else if (auth.authenticated || getApiConfig().token) {
    document.getElementById("logout-btn")?.classList.remove("hidden");
  }

  try {
    const initialView = viewFromLocation();
    setView(initialView, { replace: true, syncUrl: false });
    if (initialView === "feedback") {
      await refreshAll();
    } else {
      const overview = await api("/api/overview");
      renderStats(overview);
      await navigateToView(initialView, { syncUrl: false });
      await pollActiveJob();
      updateSourceBadge();
    }
  } catch (err) {
    document.getElementById("subtitle").textContent = `Bağlantı hatası: ${err.message}`;
  }
}

boot();
