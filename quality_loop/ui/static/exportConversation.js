/** Export quality loop conversations (CX Director ↔ Advisor) with reasoning. */
(function () {
  const slugifyFilename = (title) =>
    String(title || "conversation")
      .trim()
      .slice(0, 48)
      .replace(/[^\w\s-]/g, "")
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "")
      .toLowerCase() || "conversation";

  const messagePlainText = (msg) => String(msg?.content ?? "").trim();

  const normalizeDashboardPicker = (picker) => {
    if (!picker || typeof picker !== "object") return null;
    const dashboards = Array.isArray(picker.dashboards)
      ? picker.dashboards
          .filter((d) => d && d.id != null)
          .map((d) => ({
            id: d.id,
            name: d.name,
            ...(d.group_id != null ? { group_id: d.group_id } : {}),
          }))
      : [];
    if (!dashboards.length) return null;
    const groups = Array.isArray(picker.groups)
      ? picker.groups
          .filter((g) => g && g.id != null)
          .map((g) => ({
            id: g.id,
            name: g.name,
            ...(g.color != null ? { color: g.color } : {}),
          }))
      : [];
    const normalized = { dashboards, groups };
    if (picker.default_dashboard_id != null) {
      normalized.default_dashboard_id = picker.default_dashboard_id;
    }
    return normalized;
  };

  const normalizeDashboardSelection = (selection) => {
    if (!selection || typeof selection !== "object" || selection.id == null) {
      return null;
    }
    const name =
      typeof selection.name === "string" && selection.name.trim()
        ? selection.name.trim()
        : null;
    return {
      id: selection.id,
      ...(name ? { name } : {}),
    };
  };

  const normalizeExportMessage = (msg, index) => {
    const content = messagePlainText(msg);
    const ts = typeof msg.ts === "number" ? msg.ts : Date.now();
    const role = msg.role === "assistant" ? "advisor" : "cx_director";
    const entry = {
      id: `msg_${ts}_${index}`,
      role,
      content: content || "",
      timestamp: new Date(ts).toISOString(),
    };

    if (msg.turn != null) entry.turn = msg.turn;

    if (Array.isArray(msg.suggestedFollowups) && msg.suggestedFollowups.length) {
      entry.suggested_followups = msg.suggestedFollowups
        .filter((item) => typeof item === "string" && item.trim())
        .map((item) => item.trim());
    }

    if (typeof msg.guidance === "string" && msg.guidance.trim()) {
      entry.guidance = msg.guidance.trim();
    }

    if (typeof msg.reasoning === "string" && msg.reasoning.trim()) {
      entry.reasoning = msg.reasoning.trim();
    }

    if (Array.isArray(msg.toolActions) && msg.toolActions.length) {
      entry.tool_actions = msg.toolActions
        .filter((item) => typeof item === "string" && item.trim())
        .map((item) => item.trim());
    }

    const dashboardPicker = normalizeDashboardPicker(msg.dashboardPicker);
    if (dashboardPicker) entry.dashboard_picker = dashboardPicker;

    const dashboardSelection = normalizeDashboardSelection(msg.dashboardSelection);
    if (dashboardSelection) entry.dashboard_selection = dashboardSelection;

    if (Array.isArray(msg.qa_issues) && msg.qa_issues.length) {
      entry.qa_issues = msg.qa_issues.map((issue) => ({
        category: issue.category,
        severity: issue.severity,
        description: issue.description,
        evidence: issue.evidence,
        fix_hint: issue.fix_hint,
        message_index: issue.message_index,
      }));
    }

    if (
      !entry.content &&
      !entry.dashboard_picker &&
      !entry.dashboard_selection &&
      !entry.suggested_followups?.length &&
      !entry.reasoning &&
      !entry.qa_issues?.length
    ) {
      return null;
    }

    return entry;
  };

  const normalizeMessages = (messages) =>
    (messages || [])
      .filter((msg) => msg && (msg.role === "user" || msg.role === "assistant"))
      .map((msg, index) => normalizeExportMessage(msg, index))
      .filter(Boolean);

  function turnsToMessages(turns) {
    const messages = [];
    for (const turn of turns || []) {
      const user = turn.user;
      const assistant = turn.assistant;
      if (user) {
        messages.push({
          role: "user",
          content: user.content,
          ts: user.ts,
          dashboardSelection: user.dashboardSelection,
          turn: turn.turn,
        });
      }
      if (assistant) {
        messages.push({
          role: "assistant",
          content: assistant.content,
          ts: assistant.ts,
          reasoning: assistant.reasoning,
          toolActions: assistant.toolActions,
          suggestedFollowups: assistant.suggestedFollowups,
          guidance: assistant.guidance,
          dashboardPicker: assistant.dashboardPicker,
          turn: turn.turn,
          qa_issues: turn.qa_issues,
        });
      }
    }
    return messages;
  }

  function buildConversationExportJson({
    sessionId,
    title,
    messages,
    meta = {},
  }) {
    const body = {
      exported_at: new Date().toISOString(),
      product: "pivony-quality-loop",
      session_id: sessionId || "",
      title: title || "Quality Loop Conversation",
      sector: meta.sector || null,
      user_email: meta.user_email || null,
      user_id: meta.user_id || null,
      job_id: meta.job_id || null,
      run_id: meta.run_id || null,
      messages: normalizeMessages(messages),
    };
    return body;
  }

  function buildQaExportJson({ sessionId, meta = {} }) {
    const qa = meta.qa_report;
    const body = {
      exported_at: new Date().toISOString(),
      product: "pivony-quality-loop-qa",
      session_id: sessionId || "",
      sector: meta.sector || null,
      user_email: meta.user_email || null,
      user_id: meta.user_id || null,
      job_id: meta.job_id || null,
      run_id: meta.run_id || null,
      turn_count: meta.turn_count || null,
      qa_report: qa
        ? {
            overall_verdict: qa.overall_verdict || null,
            priority_fix: qa.priority_fix || null,
            scores: qa.scores || null,
            issues: (qa.issues || []).map((issue) => ({
              category: issue.category,
              severity: issue.severity,
              description: issue.description,
              evidence: issue.evidence,
              fix_hint: issue.fix_hint,
              message_index: issue.message_index,
            })),
          }
        : null,
    };
    return body;
  }

  function buildQaExportMarkdown({ sessionId, meta = {} }) {
    const qa = meta.qa_report || {};
    const lines = [
      `# Pivony Quality Loop — QA Report`,
      `Session: ${sessionId || "—"}`,
      `Exported: ${new Date().toLocaleString("tr-TR")}`,
    ];
    if (meta.run_id) lines.push(`Run: ${meta.run_id}`);
    if (qa.overall_verdict) lines.push(`Verdict: ${qa.overall_verdict}`);
    if (qa.priority_fix) lines.push(`Priority fix: ${qa.priority_fix}`);
    if (qa.scores) {
      lines.push("", "**Scores:**");
      Object.entries(qa.scores).forEach(([k, v]) => lines.push(`- ${k}: ${v}`));
    }
    if (qa.issues?.length) {
      lines.push("", "**Issues:**");
      qa.issues.forEach((issue) => {
        const sev = issue.severity ? `[${issue.severity}] ` : "";
        lines.push(`- ${sev}${issue.category || "issue"}: ${issue.description || ""}`);
        if (issue.fix_hint) lines.push(`  - Fix: ${issue.fix_hint}`);
      });
    }
    return lines.join("\n").trimEnd() + "\n";
  }

  const roleLabel = (role) => {
    if (role === "cx_director") return "CX Director";
    if (role === "advisor") return "Advisor";
    return role;
  };

  const formatMarkdownTime = (iso) => {
    try {
      return new Date(iso).toLocaleTimeString("tr-TR", {
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_) {
      return "";
    }
  };

  function buildConversationExportMarkdown({ title, messages, meta = {} }) {
    const normalized = normalizeMessages(messages);
    const exportDate = new Date().toLocaleString("tr-TR", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
    const lines = [
      `# Pivony Quality Loop — ${title || "Conversation"}`,
      `Exported: ${exportDate}`,
    ];
    if (meta.session_id) lines.push(`Session: ${meta.session_id}`);
    if (meta.sector) lines.push(`Sector: ${meta.sector}`);
    if (meta.user_email) lines.push(`User: ${meta.user_email}`);
    if (meta.job_id) lines.push(`Job: ${meta.job_id}`);
    if (meta.run_id) lines.push(`Run: ${meta.run_id}`);
    lines.push("", "---", "");

    normalized.forEach((msg) => {
      const label = roleLabel(msg.role);
      const time = formatMarkdownTime(msg.timestamp);
      const turnPrefix = msg.turn != null ? ` · Tur ${msg.turn}` : "";
      lines.push(`**${label}** · ${time}${turnPrefix}`);
      if (msg.content) lines.push(msg.content);
      if (msg.dashboard_selection) {
        lines.push("");
        const dashLabel =
          msg.dashboard_selection.name || `Dashboard ${msg.dashboard_selection.id}`;
        lines.push(
          `**Dashboard selected:** ${dashLabel} (id: ${msg.dashboard_selection.id})`
        );
      }
      if (typeof msg.reasoning === "string" && msg.reasoning.trim()) {
        lines.push("");
        lines.push("**Reasoning:**");
        lines.push(msg.reasoning.trim());
      }
      if (Array.isArray(msg.tool_actions) && msg.tool_actions.length) {
        lines.push("");
        lines.push("**Tool actions:**");
        msg.tool_actions.forEach((tool) => lines.push(`- ${tool}`));
      }
      if (Array.isArray(msg.suggested_followups) && msg.suggested_followups.length) {
        lines.push("");
        lines.push("**Suggested follow-ups:**");
        msg.suggested_followups.forEach((q) => lines.push(`- ${q}`));
      }
      if (typeof msg.guidance === "string" && msg.guidance.trim()) {
        lines.push("");
        lines.push("**Guidance:**");
        lines.push(msg.guidance.trim());
      }
      if (msg.dashboard_picker?.dashboards?.length) {
        lines.push("");
        lines.push("**Dashboards:**");
        msg.dashboard_picker.dashboards.forEach((d) => {
          lines.push(`- ${d.name} (id: ${d.id})`);
        });
      }
      if (Array.isArray(msg.qa_issues) && msg.qa_issues.length) {
        lines.push("");
        lines.push("**QA issues:**");
        msg.qa_issues.forEach((issue) => {
          const sev = issue.severity ? `[${issue.severity}] ` : "";
          lines.push(`- ${sev}${issue.category || "issue"}: ${issue.description || ""}`);
          if (issue.evidence) lines.push(`  - Evidence: ${issue.evidence}`);
          if (issue.fix_hint) lines.push(`  - Fix: ${issue.fix_hint}`);
        });
      }
      lines.push("");
    });

    if (meta.qa_report?.issues?.length) {
      lines.push("---", "", "## QA Report (özet)", "");
      if (meta.qa_report.scores) {
        lines.push("**Scores:**");
        Object.entries(meta.qa_report.scores).forEach(([k, v]) => lines.push(`- ${k}: ${v}`));
        lines.push("");
      }
      lines.push("**Tüm issue'lar:**");
      meta.qa_report.issues.forEach((issue) => {
        const sev = issue.severity ? `[${issue.severity}] ` : "";
        lines.push(`- ${sev}${issue.category || "issue"}: ${issue.description || ""}`);
        if (issue.fix_hint) lines.push(`  - Fix: ${issue.fix_hint}`);
      });
      lines.push("");
    }

    return lines.join("\n").trimEnd() + "\n";
  }

  const triggerDownload = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  function downloadConversationJson(payload) {
    const body = buildConversationExportJson(payload);
    const blob = new Blob([JSON.stringify(body, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const date = new Date().toISOString().slice(0, 10);
    triggerDownload(
      blob,
      `pivony-quality-loop-conversation-${slugifyFilename(payload.title || payload.sessionId)}-${date}.json`
    );
  }

  function downloadQaJson(payload) {
    const body = buildQaExportJson({
      sessionId: payload.sessionId,
      meta: payload.meta || {},
    });
    const blob = new Blob([JSON.stringify(body, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const date = new Date().toISOString().slice(0, 10);
    triggerDownload(
      blob,
      `pivony-quality-loop-qa-${slugifyFilename(payload.sessionId || "qa")}-${date}.json`
    );
  }

  function downloadConversationMarkdown(payload) {
    const markdown = buildConversationExportMarkdown(payload);
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const date = new Date().toISOString().slice(0, 10);
    triggerDownload(
      blob,
      `pivony-quality-loop-conversation-${slugifyFilename(payload.title || payload.sessionId)}-${date}.md`
    );
  }

  function downloadQaMarkdown(payload) {
    const markdown = buildQaExportMarkdown({
      sessionId: payload.sessionId,
      meta: payload.meta || {},
    });
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const date = new Date().toISOString().slice(0, 10);
    triggerDownload(
      blob,
      `pivony-quality-loop-qa-${slugifyFilename(payload.sessionId || "qa")}-${date}.md`
    );
  }

  function exportShortcutLabel() {
    const isMac =
      typeof navigator !== "undefined" &&
      /Mac|iPod|iPhone|iPad/.test(navigator.platform || "");
    return isMac ? "⌘⇧E" : "Ctrl⇧E";
  }

  window.QlExport = {
    turnsToMessages,
    buildConversationExportJson,
    buildConversationExportMarkdown,
    buildQaExportJson,
    buildQaExportMarkdown,
    downloadConversationJson,
    downloadConversationMarkdown,
    downloadQaJson,
    downloadQaMarkdown,
    exportShortcutLabel,
  };
})();
