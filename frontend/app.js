const API = "/api";
let state = { activeCaseId: null, activeView: "dashboard" };

// ---------------------------------------------------------------- helpers

async function apiGet(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
async function apiPostForm(path, data) {
  const form = new FormData();
  Object.entries(data || {}).forEach(([k, v]) => form.append(k, v));
  const res = await fetch(API + path, { method: "POST", body: form });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(errText);
  }
  return res.json();
}
async function apiPostFile(path, fieldName, file, extraFields) {
  const form = new FormData();
  form.append(fieldName, file);
  Object.entries(extraFields || {}).forEach(([k, v]) => form.append(k, v));
  const res = await fetch(API + path, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
async function apiDelete(path) {
  const res = await fetch(API + path, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function toast(msg, isError) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " error" : "");
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3500);
}

// Shows an elapsed-time progress bar for slow operations (LLM calls,
// image analysis, etc). Learns from past runs (stored in this browser's
// localStorage) to estimate how long this action usually takes, so the
// bar reflects real timing instead of a meaningless fake animation.
function startProgress(containerEl, label, storageKey) {
  const avgKey = `sentinel_progress_avg_${storageKey}`;
  const estimate = parseFloat(localStorage.getItem(avgKey)) || null;
  const startTime = Date.now();

  containerEl.innerHTML = `
    <div class="progress-wrap">
      <div class="progress-label">${label}</div>
      <div class="progress-bar-track"><div class="progress-bar-fill"></div></div>
      <div class="progress-time muted"></div>
    </div>
  `;
  const fillEl = containerEl.querySelector(".progress-bar-fill");
  const timeEl = containerEl.querySelector(".progress-time");

  const interval = setInterval(() => {
    const elapsed = (Date.now() - startTime) / 1000;
    let pct;
    if (estimate) {
      pct = Math.min(95, (elapsed / estimate) * 100);
      timeEl.textContent = `${elapsed.toFixed(1)}s elapsed — usually takes about ${estimate.toFixed(1)}s`;
    } else {
      pct = Math.min(90, elapsed * 6);
      timeEl.textContent = `${elapsed.toFixed(1)}s elapsed — estimating typical time...`;
    }
    fillEl.style.width = pct + "%";
  }, 200);

  return {
    finish() {
      clearInterval(interval);
      const totalSeconds = (Date.now() - startTime) / 1000;
      const histKey = `sentinel_progress_hist_${storageKey}`;
      let hist = [];
      try { hist = JSON.parse(localStorage.getItem(histKey) || "[]"); } catch (e) { hist = []; }
      hist.push(totalSeconds);
      hist = hist.slice(-3);
      localStorage.setItem(histKey, JSON.stringify(hist));
      const avg = hist.reduce((a, b) => a + b, 0) / hist.length;
      localStorage.setItem(avgKey, avg.toFixed(2));
      if (fillEl) fillEl.style.width = "100%";
    }
  };
}

function el(html) {
  const div = document.createElement("div");
  div.innerHTML = html.trim();
  return div.firstChild;
}

function enableEnterSubmit(inputEl, buttonEl) {
  if (!inputEl || !buttonEl) return;
  inputEl.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      buttonEl.click();
    }
  });
}

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// ------------------------------------------------------------- onboarding

async function checkOnboarding() {
  try {
    const status = await apiGet("/settings/ollama");
    if (status.reachable && status.models_installed.length) {
      document.getElementById("onboarding-screen").classList.add("hidden");
      document.getElementById("app-shell").classList.remove("hidden");
      initShell();
    } else {
      showOnboardingStatus(status);
    }
  } catch (e) {
    showOnboardingStatus(null);
  }
}

function showOnboardingStatus(status) {
  document.getElementById("onboarding-screen").classList.remove("hidden");
  document.getElementById("app-shell").classList.add("hidden");
  const statusEl = document.getElementById("onb-status");
  if (!status) {
    statusEl.textContent = "Cannot reach the Sentinel AI server itself — is `python run.py` running?";
    statusEl.className = "status-msg err";
  } else if (!status.reachable) {
    statusEl.textContent = `Ollama isn't reachable at ${status.base_url}. Run \`ollama serve\`.`;
    statusEl.className = "status-msg err";
  } else if (!status.models_installed.length) {
    statusEl.textContent = "Ollama is running, but no models are pulled yet.";
    statusEl.className = "status-msg err";
  }
}

document.getElementById("onb-retry-btn").addEventListener("click", checkOnboarding);
document.getElementById("onb-skip-btn").addEventListener("click", () => {
  document.getElementById("onboarding-screen").classList.add("hidden");
  document.getElementById("app-shell").classList.remove("hidden");
  initShell();
});

// ------------------------------------------------------------------ shell

function initShell() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", (ev) => {
      ev.preventDefault();
      switchView(item.dataset.view);
    });
  });

  refreshKeyStatus();

  switchView("dashboard");
}

async function refreshKeyStatus() {
  const status = await apiGet("/settings/ollama");
  const el = document.getElementById("key-status");
  if (status.reachable) {
    el.textContent = `Ollama connected — ${status.text_model}`;
    el.style.color = "var(--success)";
  } else {
    el.textContent = "Ollama not reachable";
    el.style.color = "var(--danger)";
  }
}

function switchView(viewName) {
  state.activeView = viewName;
  document.querySelectorAll(".nav-item").forEach((i) => i.classList.toggle("active", i.dataset.view === viewName));
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));

  if (viewName === "dashboard") { document.getElementById("view-dashboard").classList.remove("hidden"); renderDashboard(); }
  else if (viewName === "cross-case") { document.getElementById("view-cross-case").classList.remove("hidden"); renderCrossCase(); }
  else if (viewName === "settings") { document.getElementById("view-settings").classList.remove("hidden"); renderSettings(); }
}

function openCase(caseId) {
  state.activeCaseId = caseId;
  document.querySelectorAll(".nav-item").forEach((i) => i.classList.remove("active"));
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  document.getElementById("view-case").classList.remove("hidden");
  renderCaseWorkspace(caseId);
}

// --------------------------------------------------------------- dashboard

async function renderDashboard() {
  const root = document.getElementById("view-dashboard");
  root.innerHTML = `
    <h1>Investigation Dashboard</h1>
    <p class="view-subtitle">Local, private, no cloud upload.</p>
    <div class="top-actions">
      <input type="text" id="global-search" placeholder="Search by name, location, keyword..." />
      <button class="btn primary" id="new-case-btn">+ New case</button>
      <button class="btn secondary" id="sample-case-btn">Load sample demo case</button>
    </div>
    <div id="new-case-form-holder"></div>
    <div id="case-list"></div>
  `;

  document.getElementById("new-case-btn").addEventListener("click", () => renderNewCaseForm());
  document.getElementById("sample-case-btn").addEventListener("click", async () => {
    try {
      await apiPostForm("/sample-case", {});
      toast("Sample case created");
      renderDashboard();
    } catch (e) { toast("Failed: " + e.message, true); }
  });
  document.getElementById("global-search").addEventListener("input", debounce(async (ev) => {
    await loadCaseList(ev.target.value);
  }, 300));

  await loadCaseList("");
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

async function loadCaseList(query) {
  const cases = await apiGet("/cases" + (query ? `?q=${encodeURIComponent(query)}` : ""));
  const listEl = document.getElementById("case-list");
  if (!cases.length) {
    listEl.innerHTML = `<div class="empty-state">No cases yet. Create one above, or load the sample demo case.</div>`;
    return;
  }
  const groups = { active: [], pending: [], closed: [] };
  cases.forEach((c) => { (groups[c.status] || groups.active).push(c); });

  let html = "";
  for (const [label, group] of Object.entries({ Active: groups.active, Pending: groups.pending, Closed: groups.closed })) {
    if (!group.length) continue;
    html += `<div class="section-title">${label}</div>`;
    group.forEach((c) => {
      html += `
        <div class="card case-card">
          <div>
            <div class="case-card-title">${escapeHtml(c.title)}</div>
            <div class="case-card-meta">${escapeHtml(c.id)} — ${escapeHtml(c.location || "")}</div>
          </div>
          <div class="case-card-actions">
            <span class="badge ${c.priority_label}">${c.priority_label}</span>
            <button class="btn small" onclick="recomputeRisk('${c.id}')">Recompute risk</button>
            <button class="btn small primary" onclick="openCase('${c.id}')">Open</button>
          </div>
        </div>`;
    });
  }
  listEl.innerHTML = html;
}

async function recomputeRisk(caseId) {
  const breakdown = await apiPostForm(`/cases/${caseId}/risk`, {});
  toast(`Risk score: ${breakdown.score_0_100}`);
  loadCaseList("");
}

function renderNewCaseForm() {
  const holder = document.getElementById("new-case-form-holder");
  holder.innerHTML = `
    <div class="card">
      <h3>New case</h3>
      <div class="form-grid">
        <div class="form-field"><label>Case title</label><input id="nc-title" type="text" /></div>
        <div class="form-field"><label>Victim name</label><input id="nc-victim" type="text" /></div>
        <div class="form-field"><label>Location</label><input id="nc-location" type="text" /></div>
        <div class="form-field"><label>Incident date/time</label><input id="nc-datetime" type="text" placeholder="2026-07-20 18:00" /></div>
        <div class="form-field"><label>Assigned officer</label><input id="nc-officer" type="text" /></div>
        <div class="form-field"><label>Import case PDF (optional)</label><input id="nc-pdf" type="file" accept="application/pdf" /></div>
      </div>
      <div class="form-field full" style="margin-top:16px;"><label>Description</label><textarea id="nc-desc" rows="3"></textarea></div>
      <div class="form-field full" style="margin-top:16px;">
        <label>Where should this case's files be stored?</label>
        <div class="card-row">
          <span id="nc-folder-path" class="muted">Default location (inside the app's data folder)</span>
          <button class="btn small secondary" id="nc-choose-folder-btn" type="button">Choose folder...</button>
        </div>
      </div>
      <div class="top-actions" style="margin-top:16px;">
        <button class="btn primary" id="nc-submit">Create case</button>
        <button class="btn secondary" id="nc-cancel">Cancel</button>
      </div>
    </div>`;

  let chosenFolder = null;
  document.getElementById("nc-choose-folder-btn").addEventListener("click", async () => {
    const btn = document.getElementById("nc-choose-folder-btn");
    btn.textContent = "Waiting for folder selection...";
    btn.disabled = true;
    try {
      const result = await apiPostForm("/pick-folder", {});
      if (result.path) {
        chosenFolder = result.path;
        document.getElementById("nc-folder-path").textContent = chosenFolder;
      }
    } catch (e) {
      toast("Could not open folder picker: " + e.message, true);
    } finally {
      btn.textContent = "Choose folder...";
      btn.disabled = false;
    }
  });

  document.getElementById("nc-cancel").addEventListener("click", () => { holder.innerHTML = ""; });
  const submitBtn = document.getElementById("nc-submit");
  ["nc-title", "nc-victim", "nc-location", "nc-datetime", "nc-officer"].forEach((id) => {
    enableEnterSubmit(document.getElementById(id), submitBtn);
  });
  submitBtn.addEventListener("click", async () => {
    const fields = {
      title: document.getElementById("nc-title").value || "Untitled case",
      victim_name: document.getElementById("nc-victim").value,
      location: document.getElementById("nc-location").value,
      incident_datetime: document.getElementById("nc-datetime").value,
      assigned_officer: document.getElementById("nc-officer").value,
      description: document.getElementById("nc-desc").value,
    };
    if (chosenFolder) fields.custom_root = chosenFolder;
    const pdfInput = document.getElementById("nc-pdf");
    try {
      let result;
      if (pdfInput.files.length) {
        const form = new FormData();
        Object.entries(fields).forEach(([k, v]) => form.append(k, v));
        form.append("pdf_file", pdfInput.files[0]);
        const res = await fetch(API + "/cases", { method: "POST", body: form });
        result = await res.json();
      } else {
        result = await apiPostForm("/cases", fields);
      }
      toast("Case created: " + result.id);
      holder.innerHTML = "";
      loadCaseList("");
    } catch (e) { toast("Failed: " + e.message, true); }
  });
}

// ---------------------------------------------------------- case workspace

async function renderCaseWorkspace(caseId) {
  const root = document.getElementById("view-case");
  const c = await apiGet(`/cases/${caseId}`);
  root.innerHTML = `
    <button class="btn small secondary" onclick="switchView('dashboard')">← Back to dashboard</button>
    <h1 style="margin-top:16px;">${escapeHtml(c.title)}</h1>
    <p class="view-subtitle">ID: ${c.id} · Status: ${c.status} · Priority: ${c.priority}</p>

    <div class="tabs">
      <button class="tab-btn active" data-tab="overview">Overview</button>
      <button class="tab-btn" data-tab="timeline">Timeline</button>
      <button class="tab-btn" data-tab="evidence">Evidence</button>
      <button class="tab-btn" data-tab="graph">Correlation graph</button>
      <button class="tab-btn" data-tab="gmail">Gmail</button>
      <button class="tab-btn" data-tab="chat">Case chat</button>
      <button class="tab-btn" data-tab="log">Update log</button>
    </div>

    <div class="tab-panel active" id="panel-overview"></div>
    <div class="tab-panel" id="panel-timeline"></div>
    <div class="tab-panel" id="panel-evidence"></div>
    <div class="tab-panel" id="panel-graph"></div>
    <div class="tab-panel" id="panel-gmail"></div>
    <div class="tab-panel" id="panel-chat"></div>
    <div class="tab-panel" id="panel-log"></div>
  `;

  root.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      root.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      root.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("panel-" + btn.dataset.tab).classList.add("active");
    });
  });

  renderOverviewTab(caseId, c);
  renderTimelineTab(caseId);
  renderEvidenceTab(caseId);
  renderGraphTab(caseId);
  renderGmailTab(caseId);
  renderChatTab(caseId);
  renderLogTab(caseId);
}

function renderOverviewTab(caseId, c) {
  const panel = document.getElementById("panel-overview");
  panel.innerHTML = `
    <div class="card">
      <div class="form-grid">
        <div><strong>Victim / subject:</strong><br>${escapeHtml(c.victim_name || "—")}</div>
        <div><strong>Location:</strong><br>${escapeHtml(c.location || "—")}</div>
        <div><strong>Incident time:</strong><br>${escapeHtml(c.incident_datetime || "—")}</div>
        <div><strong>Assigned officer:</strong><br>${escapeHtml(c.assigned_officer || "—")}</div>
      </div>
      <div style="margin-top:16px;"><strong>Description:</strong><br>${escapeHtml(c.description || "—")}</div>
    </div>
    <div class="card">
      <button class="btn primary" id="recompute-btn">Recompute risk score</button>
      <div id="risk-result" style="margin-top:16px;"></div>
      <button class="btn secondary" id="draft-report-btn" style="margin-top:16px;">Generate draft report</button>
    </div>
    <div class="card">
      <h3>Full Case Summary file</h3>
      <p class="muted">Generates a complete CaseSummary with case details, timeline, log, and every evidence photo embedded.</p>
      <div class="top-actions">
        <button class="btn secondary" id="summary-docx-btn">Download as .docx</button>
        <button class="btn secondary" id="summary-pdf-btn">Download as .pdf</button>
      </div>
      <div id="summary-progress" style="margin-top:12px;"></div>
    </div>
    <div class="card" style="border-color: var(--danger);">
      <h3 style="color: var(--danger);">Danger zone</h3>
      <p class="muted">Permanently deletes this case's database records AND its entire folder (evidence, photos, everything) from this computer. This cannot be undone.</p>
      <button class="btn danger" id="delete-case-btn">Delete this case...</button>
      <div id="delete-case-confirm" style="margin-top:12px;"></div>
    </div>
  `;
  document.getElementById("recompute-btn").addEventListener("click", async () => {
    const breakdown = await apiPostForm(`/cases/${caseId}/risk`, {});
    const factorsHtml = Object.entries(breakdown.factors)
      .map(([k, v]) => `<div>• <strong>${k}</strong>: ${v} × weight ${breakdown.weights[k]} = ${(v * breakdown.weights[k]).toFixed(3)}</div>`)
      .join("");
    document.getElementById("risk-result").innerHTML = `
      <div class="badge ${breakdown.score_0_100 >= 60 ? "high" : breakdown.score_0_100 >= 30 ? "medium" : "low"}" style="font-size:16px; padding:8px 16px;">
        Risk score: ${breakdown.score_0_100} / 100
      </div>
      <div style="margin-top:12px; color: var(--text-muted); font-size:13px;">${factorsHtml}</div>
    `;
  });
  document.getElementById("draft-report-btn").addEventListener("click", async () => {
    const res = await fetch(`${API}/cases/${caseId}/report`, { method: "POST" });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "draft_report.md"; a.click();
    toast("Draft report downloaded — review before distributing.");
  });

  const downloadSummary = async (format) => {
    const progressEl = document.getElementById("summary-progress");
    const progress = startProgress(progressEl, `Generating CaseSummary.${format} (embedding photos, this can take a moment)...`, `summary_${format}`);
    try {
      const res = await fetch(`${API}/cases/${caseId}/summary-file`, {
        method: "POST",
        body: (() => { const f = new FormData(); f.append("file_format", format); return f; })(),
      });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      progress.finish();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `CaseSummary.${format}`; a.click();
      toast("Case summary downloaded");
      progressEl.innerHTML = "";
    } catch (e) {
      progress.finish();
      progressEl.innerHTML = `<div style="color:var(--danger);">Failed: ${escapeHtml(e.message)}</div>`;
    }
  };
  document.getElementById("summary-docx-btn").addEventListener("click", () => downloadSummary("docx"));
  document.getElementById("summary-pdf-btn").addEventListener("click", () => downloadSummary("pdf"));

  document.getElementById("delete-case-btn").addEventListener("click", () => {
    const confirmEl = document.getElementById("delete-case-confirm");
    confirmEl.innerHTML = `
      <p>This will permanently delete <strong>everything</strong> for this case, including all files on disk. Type the exact case title to confirm:</p>
      <p class="muted">"${escapeHtml(c.title)}"</p>
      <input type="text" id="delete-confirm-input" placeholder="Type the case title exactly" style="max-width:400px;" />
      <div class="top-actions" style="margin-top:10px;">
        <button class="btn danger" id="delete-confirm-btn">Permanently delete</button>
        <button class="btn secondary" id="delete-cancel-btn">Cancel</button>
      </div>
    `;
    document.getElementById("delete-cancel-btn").addEventListener("click", () => { confirmEl.innerHTML = ""; });
    const confirmBtn = document.getElementById("delete-confirm-btn");
    const confirmInput = document.getElementById("delete-confirm-input");
    enableEnterSubmit(confirmInput, confirmBtn);
    confirmBtn.addEventListener("click", async () => {
      const typed = confirmInput.value;
      try {
        const form = new FormData();
        form.append("confirm_title", typed);
        const res = await fetch(`${API}/cases/${caseId}`, { method: "DELETE", body: form });
        if (!res.ok) throw new Error(await res.text());
        toast("Case deleted");
        switchView("dashboard");
      } catch (e) {
        toast("Delete failed: " + e.message, true);
      }
    });
  });
}

async function renderTimelineTab(caseId) {
  const panel = document.getElementById("panel-timeline");
  const events = await apiGet(`/cases/${caseId}/timeline`);
  if (!events.length) { panel.innerHTML = `<div class="empty-state">No timeline events yet.</div>`; return; }
  panel.innerHTML = events.map((e) => `
    <div class="timeline-item">
      <div class="timeline-source">${escapeHtml(e.source)}</div>
      <div class="timeline-desc">${escapeHtml(e.description)} ${e.uncertain ? '<span class="uncertain-flag">⚠ uncertain timestamp</span>' : ""}</div>
    </div>`).join("");
}

function renderEvidenceTab(caseId) {
  const panel = document.getElementById("panel-evidence");
  panel.innerHTML = `
    <div class="card">
      <h3>Upload evidence photo</h3>
      <input type="file" id="ev-photo-input" accept="image/*" />
      <div id="ev-photo-result" style="margin-top:12px;"></div>
    </div>
    <div class="card">
      <h3>Upload evidence document</h3>
      <input type="file" id="ev-doc-input" accept=".pdf,.txt" />
      <div id="ev-doc-result" style="margin-top:12px;"></div>
    </div>
  `;
  document.getElementById("ev-photo-input").addEventListener("change", async (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    const resultDiv = document.getElementById("ev-photo-result");
    const progress = startProgress(resultDiv, "Uploading and analyzing (face matching + local vision description)...", "photo_upload");
    try {
      const result = await apiPostFile(`/cases/${caseId}/evidence/photo`, "file", file);
      progress.finish();
      const reader = new FileReader();
      reader.onload = () => {
        resultDiv.innerHTML = `
          <div class="card-row" style="align-items:flex-start;">
            <img src="${reader.result}" style="max-width:200px; border-radius:8px;" />
            <div style="flex:1;">
              <div style="color:var(--success); font-weight:600; margin-bottom:6px;">✔ Saved to case evidence/images/</div>
              ${result.faces.length ? result.faces.map(f => `<div>${f.is_new ? "🆕 New face" : `🔗 Matched existing face (distance ${f.distance.toFixed(3)})`} — id ${f.face_id.slice(0,8)}</div>`).join("") : (result.face_matching_available ? "No faces detected." : "face_recognition not available.")}
              ${result.hash_match.matched ? `<div style="color:var(--danger); margin-top:8px;">⚠ Known-hash match (demo list): ${escapeHtml(result.hash_match.label)}</div>` : ""}
              <div style="margin-top:10px; padding:10px; background:var(--bg-elevated); border-radius:8px; font-size:13px;">
                <strong>Local vision description:</strong><br>${escapeHtml(result.caption)}
              </div>
            </div>
          </div>
        `;
      };
      reader.readAsDataURL(file);
      toast("Photo saved and analyzed");
    } catch (e) {
      progress.finish();
      resultDiv.innerHTML = `<div style="color:var(--danger);">Upload failed: ${escapeHtml(e.message)}</div>`;
      toast("Upload failed: " + e.message, true);
    }
  });
  document.getElementById("ev-doc-input").addEventListener("change", async (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    const resultDiv = document.getElementById("ev-doc-result");
    const progress = startProgress(resultDiv, "Uploading and reading document...", "doc_upload");
    try {
      const result = await apiPostFile(`/cases/${caseId}/evidence/doc`, "file", file);
      progress.finish();
      resultDiv.innerHTML = `
        <div style="color:var(--success); font-weight:600; margin-bottom:6px;">✔ Saved to case evidence folder</div>
        <div>${result.text_extracted ? "Text extracted and indexed for search/chat." : "No text could be extracted (e.g. scanned/image-only PDF) — file is still saved, just not searchable."}</div>
        ${Object.keys(result.flags || {}).length ? `<pre style="white-space:pre-wrap; font-size:13px; margin-top:8px;">${escapeHtml(JSON.stringify(result.flags, null, 2))}</pre>` : ""}
      `;
      toast("Document saved");
    } catch (e) {
      progress.finish();
      resultDiv.innerHTML = `<div style="color:var(--danger);">Upload failed: ${escapeHtml(e.message)}</div>`;
      toast("Upload failed: " + e.message, true);
    }
  });
}

async function renderGraphTab(caseId) {
  const panel = document.getElementById("panel-graph");
  const data = await apiGet(`/cases/${caseId}/graph`);
  panel.innerHTML = `<div class="graph-container"><canvas id="case-graph-canvas" width="800" height="400"></canvas></div>`;
  drawSimpleGraph(document.getElementById("case-graph-canvas"), data);
}

function drawSimpleGraph(canvas, data) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!data.nodes.length) {
    ctx.fillStyle = "#8b93a7";
    ctx.font = "14px sans-serif";
    ctx.fillText("No graph data yet.", 20, 40);
    return;
  }
  const cx = canvas.width / 2, cy = canvas.height / 2, radius = Math.min(cx, cy) - 60;
  const positions = {};
  data.nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / data.nodes.length;
    positions[n.id] = { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });
  ctx.strokeStyle = "#2f3a52";
  ctx.lineWidth = 1.5;
  data.edges.forEach((e) => {
    const a = positions[e.source], b = positions[e.target];
    if (a && b) { ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
  });
  data.nodes.forEach((n) => {
    const p = positions[n.id];
    ctx.beginPath();
    ctx.arc(p.x, p.y, 20, 0, 2 * Math.PI);
    ctx.fillStyle = n.type === "case" ? "#5b8cff" : "#8b6bff";
    ctx.fill();
    ctx.fillStyle = "#e8ebf2";
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(n.label.slice(0, 14), p.x, p.y + 34);
  });
}

async function renderGmailTab(caseId) {
  const panel = document.getElementById("panel-gmail");
  const { configured } = await apiGet("/gmail/status");
  const departments = await apiGet("/settings/departments");
  const threads = await apiGet(`/cases/${caseId}/gmail/threads`);

  if (!configured) {
    panel.innerHTML = `<div class="card">⚠ Gmail not authorized yet. Run <code>python -m modules.gmail_client --authorize</code> once from the terminal, then restart the server.</div>`;
    return;
  }

  panel.innerHTML = `
    <div class="card">
      <h3>Request evidence</h3>
      ${departments.length ? `
        <div class="form-field"><label>Department</label>
          <select id="gm-dept">${departments.map(d => `<option value="${d.id}">${escapeHtml(d.label)}</option>`).join("")}</select>
        </div>
        <div class="form-field" style="margin-top:12px;"><label>What are you requesting?</label>
          <textarea id="gm-request" rows="3" placeholder="e.g. CCTV footage, Dimna area, Jamshedpur, ~6PM on 2026-07-20"></textarea>
        </div>
        <button class="btn secondary" id="gm-draft-btn" style="margin-top:12px;">Draft email</button>
        <div class="form-field" style="margin-top:12px;"><label>Draft (edit before sending)</label>
          <textarea id="gm-draft-text" rows="8"></textarea>
        </div>
        <button class="btn primary" id="gm-send-btn">Send email</button>
      ` : `<div class="empty-state">No departments configured — add some in Settings.</div>`}
    </div>
    <div class="card">
      <h3>Threads</h3>
      <div id="gm-threads">${threads.length ? threads.map(t => `<div>• <strong>${escapeHtml(t.department_label)}</strong> — ${t.status} — ${escapeHtml(t.subject)}</div>`).join("") : `<div class="empty-state">No requests sent yet.</div>`}</div>
    </div>
  `;

  if (departments.length) {
    document.getElementById("gm-draft-btn").addEventListener("click", async () => {
      const deptId = document.getElementById("gm-dept").value;
      const dept = departments.find(d => d.id === deptId);
      const request_desc = document.getElementById("gm-request").value;
      try {
        const { draft } = await apiPostForm(`/cases/${caseId}/gmail/draft`, { department_label: dept.label, request_desc });
        document.getElementById("gm-draft-text").value = draft;
      } catch (e) { toast("Draft failed: " + e.message, true); }
    });
    document.getElementById("gm-send-btn").addEventListener("click", async () => {
      const deptId = document.getElementById("gm-dept").value;
      const dept = departments.find(d => d.id === deptId);
      const body = document.getElementById("gm-draft-text").value;
      if (!body) { toast("Draft an email first.", true); return; }
      try {
        await apiPostForm(`/cases/${caseId}/gmail/send`, {
          department_label: dept.label, department_email: dept.email,
          subject: `Case ${caseId} request`, body,
        });
        toast("Sent.");
        renderGmailTab(caseId);
      } catch (e) { toast("Send failed: " + e.message, true); }
    });
  }
}

async function renderChatTab(caseId) {
  const panel = document.getElementById("panel-chat");
  panel.innerHTML = `
    <div class="card">
      <div class="chat-box" id="chat-box"></div>
      <div id="chat-progress"></div>
      <div class="chat-input-row">
        <input type="file" id="chat-image-input" accept="image/*" style="display:none;" />
        <button class="btn secondary" id="chat-attach-btn" title="Share an image">📷</button>
        <input type="text" id="chat-input" placeholder="Ask, share info, or say 'email x@y.com about...'" />
        <button class="btn primary" id="chat-send-btn">Send</button>
      </div>
    </div>
  `;
  const history = await apiGet(`/cases/${caseId}/chat`);
  const box = document.getElementById("chat-box");
  history.forEach((m) => box.appendChild(el(`<div class="chat-msg ${m.role}">${escapeHtml(m.content)}</div>`)));
  box.scrollTop = box.scrollHeight;

  function renderEmailDraftCard(draft) {
    const card = el(`
      <div class="chat-msg assistant" style="max-width:90%;">
        <div style="font-weight:600; margin-bottom:8px;">✉️ Drafted email</div>
        <div class="form-field"><label>To</label><input class="draft-to" type="text" value="${escapeHtml(draft.to)}" /></div>
        <div class="form-field" style="margin-top:8px;"><label>Subject</label><input class="draft-subject" type="text" value="${escapeHtml(draft.subject)}" /></div>
        <div class="form-field" style="margin-top:8px;"><label>Body</label><textarea class="draft-body" rows="6">${escapeHtml(draft.body)}</textarea></div>
        <div class="top-actions" style="margin-top:10px;">
          <button class="btn primary draft-send-btn">Send email</button>
          <button class="btn secondary draft-discard-btn">Discard</button>
        </div>
        <div class="draft-status" style="margin-top:8px;"></div>
      </div>
    `);
    card.querySelector(".draft-discard-btn").addEventListener("click", () => card.remove());
    card.querySelector(".draft-send-btn").addEventListener("click", async () => {
      const to = card.querySelector(".draft-to").value;
      const subject = card.querySelector(".draft-subject").value;
      const body = card.querySelector(".draft-body").value;
      const statusEl = card.querySelector(".draft-status");
      try {
        await apiPostForm(`/cases/${caseId}/gmail/send`, {
          department_label: draft.to_label, department_email: to, subject, body,
        });
        statusEl.innerHTML = `<span style="color:var(--success);">Sent ✔</span>`;
        card.querySelectorAll("input, textarea, button").forEach(elm => elm.disabled = true);
      } catch (e) {
        statusEl.innerHTML = `<span style="color:var(--danger);">Failed: ${escapeHtml(e.message)}</span>`;
      }
    });
    box.appendChild(card);
    box.scrollTop = box.scrollHeight;
  }

  const send = async () => {
    const input = document.getElementById("chat-input");
    const question = input.value.trim();
    if (!question) return;
    box.appendChild(el(`<div class="chat-msg user">${escapeHtml(question)}</div>`));
    input.value = "";
    box.scrollTop = box.scrollHeight;

    const progressEl = document.getElementById("chat-progress");
    const progress = startProgress(progressEl, "Thinking (local LLM)...", "chat_reply");
    try {
      const result = await apiPostForm(`/cases/${caseId}/chat`, { question });
      progress.finish();
      progressEl.innerHTML = "";
      box.appendChild(el(`<div class="chat-msg assistant">${escapeHtml(result.answer)}</div>`));
      box.scrollTop = box.scrollHeight;
      if (result.email_draft) renderEmailDraftCard(result.email_draft);
    } catch (e) {
      progress.finish();
      progressEl.innerHTML = "";
      toast("Chat failed: " + e.message, true);
    }
  };
  document.getElementById("chat-send-btn").addEventListener("click", send);
  document.getElementById("chat-input").addEventListener("keydown", (ev) => { if (ev.key === "Enter") send(); });

  document.getElementById("chat-attach-btn").addEventListener("click", () => {
    document.getElementById("chat-image-input").click();
  });
  document.getElementById("chat-image-input").addEventListener("change", async (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    box.appendChild(el(`<div class="chat-msg user">[shared image: ${escapeHtml(file.name)}]</div>`));
    box.scrollTop = box.scrollHeight;

    const progressEl = document.getElementById("chat-progress");
    const progress = startProgress(progressEl, "Analyzing image (local vision model)...", "chat_image");
    try {
      const result = await apiPostFile(`/cases/${caseId}/chat/image`, "file", file);
      progress.finish();
      progressEl.innerHTML = "";
      box.appendChild(el(`<div class="chat-msg assistant">${escapeHtml(result.reply)}</div>`));
      box.scrollTop = box.scrollHeight;
    } catch (e) {
      progress.finish();
      progressEl.innerHTML = "";
      toast("Image analysis failed: " + e.message, true);
    }
  });
}

async function renderLogTab(caseId) {
  const panel = document.getElementById("panel-log");
  const { markdown } = await apiGet(`/cases/${caseId}/update-log`);
  panel.innerHTML = `
    <button class="btn secondary" id="regen-summary-btn" style="margin-bottom:16px;">Regenerate AI summary</button>
    <div class="markdown-view">${escapeHtml(markdown)}</div>
  `;
  document.getElementById("regen-summary-btn").addEventListener("click", async (ev) => {
    ev.target.textContent = "Generating (this calls the local LLM, may take a few seconds)...";
    ev.target.disabled = true;
    try {
      await apiPostForm(`/cases/${caseId}/update-log/regenerate`, {});
      toast("Summary updated");
      renderLogTab(caseId);
    } catch (e) {
      toast("Failed: " + e.message, true);
      ev.target.textContent = "Regenerate AI summary";
      ev.target.disabled = false;
    }
  });
}

// ------------------------------------------------------------ cross-case

async function renderCrossCase() {
  const root = document.getElementById("view-cross-case");
  root.innerHTML = `
    <h1>Correlation &amp; People</h1>
    <p class="view-subtitle">Cross-case links, tagged individuals, and victims — all in one place.</p>
    <div class="tabs">
      <button class="tab-btn active" data-tab="cc-links">Cross-case links</button>
      <button class="tab-btn" data-tab="cc-people">Tagged individuals</button>
      <button class="tab-btn" data-tab="cc-victims">Victims</button>
    </div>
    <div class="tab-panel active" id="panel-cc-links"></div>
    <div class="tab-panel" id="panel-cc-people"></div>
    <div class="tab-panel" id="panel-cc-victims"></div>
  `;
  root.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      root.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      root.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("panel-" + btn.dataset.tab).classList.add("active");
    });
  });

  renderCrossCaseLinksTab();
  renderTaggedIndividualsTab();
  renderVictimsTab();
}

async function renderCrossCaseLinksTab() {
  const panel = document.getElementById("panel-cc-links");
  const edges = await apiGet("/cross-case/edges");
  const graphData = await apiGet("/cross-case/graph");

  panel.innerHTML = `
    <div id="cc-edges"></div>
    <div class="graph-container" style="margin-top:24px;"><canvas id="cc-graph-canvas" width="900" height="500"></canvas></div>
  `;
  const edgesEl = document.getElementById("cc-edges");
  edgesEl.innerHTML = edges.length
    ? edges.map(e => `<div class="card">⚠ <strong>${escapeHtml(e.case_a_title)}</strong> ↔ <strong>${escapeHtml(e.case_b_title)}</strong> — shared ${e.entity_type} (${e.entity_value.slice(0,12)})</div>`).join("")
    : `<div class="empty-state">No cross-case links found yet.</div>`;

  drawSimpleGraph(document.getElementById("cc-graph-canvas"), graphData);
}

async function renderTaggedIndividualsTab() {
  const panel = document.getElementById("panel-cc-people");
  const faces = await apiGet("/faces");
  if (!faces.length) {
    panel.innerHTML = `<div class="empty-state">No faces indexed yet — they'll appear here automatically as you upload evidence photos.</div>`;
    return;
  }
  panel.innerHTML = faces.map(f => `
    <div class="card card-row">
      <div>${f.id.slice(0,8)}</div>
      <input type="text" id="tag-${f.id}" value="${escapeHtml(f.name_tag || "")}" placeholder="Name / tag" style="max-width:200px;" />
      <button class="btn small" onclick="saveTag('${f.id}')">Save</button>
      <div style="color:var(--text-muted); font-size:13px;">Seen in: ${f.cases.map(escapeHtml).join(", ") || "—"}</div>
    </div>
  `).join("");
}

async function renderVictimsTab() {
  const panel = document.getElementById("panel-cc-victims");
  const victims = await apiGet("/victims");
  if (!victims.length) {
    panel.innerHTML = `<div class="empty-state">No victim names recorded yet — add one in a case's intake form.</div>`;
    return;
  }
  panel.innerHTML = victims.map(v => `
    <div class="card card-row">
      <div>
        <div class="case-card-title">${escapeHtml(v.victim_name)}</div>
        <div class="case-card-meta">Case: ${escapeHtml(v.title)} — ${escapeHtml(v.location || "")}</div>
      </div>
      <button class="btn small" onclick="openCase('${v.id}')">Open case</button>
    </div>
  `).join("");
}

async function saveTag(faceId) {
  const value = document.getElementById(`tag-${faceId}`).value;
  await apiPostForm(`/faces/${faceId}/tag`, { name: value });
  toast("Tag saved");
}

// --------------------------------------------------------------- settings

async function renderSettings() {
  const root = document.getElementById("view-settings");
  const departments = await apiGet("/settings/departments");
  const general = await apiGet("/settings/general");
  const ollama = await apiGet("/settings/ollama");

  root.innerHTML = `
    <h1>Settings</h1>

    <div class="section-title">Local AI (Ollama)</div>
    <div class="card">
      <p class="muted">No cloud, no API keys — everything runs on this machine through Ollama.</p>
      <div class="form-grid">
        <div class="form-field"><label>Text model</label>
          <select id="ollama-text-model"></select>
        </div>
        <div class="form-field"><label>Vision model (for photo descriptions)</label>
          <select id="ollama-vision-model"></select>
        </div>
      </div>
      <div class="form-field" style="margin-top:12px;"><label>Ollama base URL</label>
        <input id="ollama-base-url" type="text" value="${escapeHtml(ollama.base_url)}" />
      </div>
      <div class="top-actions" style="margin-top:16px;">
        <button class="btn secondary" id="ollama-test-btn">Test connection</button>
        <button class="btn primary" id="ollama-save-btn">Save</button>
      </div>
      <div id="ollama-status" class="status-msg"></div>
    </div>

    <div class="section-title">Department directory</div>
    <div class="card">
      <div class="form-grid">
        <div class="form-field"><label>Label</label><input id="dept-label" type="text" placeholder="Police Station - Jamshedpur" /></div>
        <div class="form-field"><label>Email</label><input id="dept-email" type="text" /></div>
      </div>
      <button class="btn primary" id="add-dept-btn" style="margin-top:12px;">Add department</button>
    </div>
    <div id="dept-list"></div>

    <div class="section-title">General</div>
    <div class="card">
      <p>Follow-up interval: every ${(general.real_interval_seconds/3600).toFixed(1)}h</p>
      <p>Data root: <code>${escapeHtml(general.data_root)}</code></p>
      <p>Gmail: ${general.gmail_configured ? "✅ authorized" : "❌ not authorized — run the authorize command from AGENT_SETUP.md"}</p>
    </div>
  `;

  const textSelect = document.getElementById("ollama-text-model");
  const visionSelect = document.getElementById("ollama-vision-model");
  const models = ollama.models_installed.length ? ollama.models_installed : [ollama.text_model, ollama.vision_model];
  models.forEach((m) => {
    textSelect.appendChild(new Option(m, m, m === ollama.text_model, m === ollama.text_model));
    visionSelect.appendChild(new Option(m, m, m === ollama.vision_model, m === ollama.vision_model));
  });

  document.getElementById("ollama-test-btn").addEventListener("click", async () => {
    const statusEl = document.getElementById("ollama-status");
    const result = await apiPostForm("/settings/ollama/test", {});
    statusEl.textContent = result.message;
    statusEl.className = "status-msg " + (result.ok ? "ok" : "err");
  });

  document.getElementById("ollama-save-btn").addEventListener("click", async () => {
    await apiPostForm("/settings/ollama", {
      text_model: textSelect.value,
      vision_model: visionSelect.value,
      base_url: document.getElementById("ollama-base-url").value,
    });
    toast("Ollama settings saved");
    refreshKeyStatus();
    renderSettings();
  });

  document.getElementById("dept-list").innerHTML = departments.length
    ? `<div class="card">${departments.map(d => `<div>• <strong>${escapeHtml(d.label)}</strong> — ${escapeHtml(d.email)}</div>`).join("")}</div>`
    : `<div class="empty-state">No departments yet.</div>`;

  document.getElementById("add-dept-btn").addEventListener("click", async () => {
    const label = document.getElementById("dept-label").value;
    const email = document.getElementById("dept-email").value;
    if (!label || !email) return;
    await apiPostForm("/settings/departments", { label, email });
    renderSettings();
  });

  enableEnterSubmit(document.getElementById("dept-email"), document.getElementById("add-dept-btn"));
  enableEnterSubmit(document.getElementById("dept-label"), document.getElementById("add-dept-btn"));
}

// ------------------------------------------------------------------- init

checkOnboarding();
