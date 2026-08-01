'use strict';

// Fuente unica de estados: lib/states.py -> app.py -> dashboard.html.
const TARGET_STATES = window.TARGET_STATES || [];

let allTargets = [];
let currentFilter = 'all';
let searchQuery = '';
let openFormId = null;
let jobHistory = [];

// ── INIT ──────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadTargets('all');
  loadTargetFiles();
  loadSesiones();
  initSearch();
});

// ── CMD TOGGLE ────────────────────────────────────────────

function toggleCmd(id) {
  const form = document.getElementById(id);
  if (!form) return;
  const isOpen = form.classList.contains('open');

  document.querySelectorAll('.cmd-form').forEach(f => f.classList.remove('open'));
  document.querySelectorAll('.cmd-item').forEach(i => i.classList.remove('active'));

  if (!isOpen) {
    form.classList.add('open');
    document.querySelector(`[data-form="${id}"]`)?.classList.add('active');
    openFormId = id;
  } else {
    openFormId = null;
  }
}

// ── PROSPECTOS TABLE ──────────────────────────────────────

async function loadTargets(filtro) {
  if (filtro) currentFilter = filtro;
  try {
    const res = await fetch('/api/targets');
    allTargets = await res.json();
    renderTable();
  } catch (e) {
    console.error('loadTargets', e);
  }
}

function targetState(t) {
  const st = (t.status || '').toLowerCase();
  return TARGET_STATES.includes(st) ? st : (TARGET_STATES[0] || 'queued');
}

function renderTable() {
  const q = searchQuery.toLowerCase();
  const rows = allTargets.filter(t => {
    const mf = currentFilter === 'all' ? true : targetState(t) === currentFilter;
    const ms = !q
      || t.dominio.toLowerCase().includes(q)
      || (t.name || '').toLowerCase().includes(q);
    return mf && ms;
  });

  const counter = document.getElementById('counter');
  if (counter) counter.textContent = `${rows.length} / ${allTargets.length}`;

  const tbody = document.getElementById('targets-body');
  if (!tbody) return;

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:24px">NO_TARGETS_FOUND</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map(rowHtml).join('');
  renderMetrics();
}

// ── METRICS ───────────────────────────────────────────────
// Solo metricas tecnicas: trabajos por estado, hallazgos por severidad y
// tasa de error de los jobs. Nada de conversion ni de embudo.

function renderMetrics() {
  const box = document.getElementById('metrics');
  if (!box) return;

  const porEstado = {};
  TARGET_STATES.forEach(st => { porEstado[st] = 0; });
  let high = 0, medium = 0, total = 0, conScan = 0;

  allTargets.forEach(t => {
    porEstado[targetState(t)] += 1;
    if (t.total_findings != null) {
      conScan += 1;
      total += t.total_findings || 0;
      high += t.high_findings || 0;
      medium += t.medium_findings || 0;
    }
  });

  const terminados = jobHistory.filter(j => j.status === 'SUCCESS' || j.status === 'FAILED');
  const fallidos = terminados.filter(j => j.status === 'FAILED').length;
  const errRate = terminados.length
    ? Math.round((fallidos / terminados.length) * 100) : null;

  const cells = TARGET_STATES.map(st =>
    metricCell(st.toUpperCase(), porEstado[st]));
  cells.push(metricCell('FINDINGS', total));
  cells.push(metricCell('HIGH', high));
  cells.push(metricCell('MEDIUM', medium));
  cells.push(metricCell('SCANNED', conScan));
  cells.push(metricCell('JOB_ERR', errRate == null ? '—' : errRate + '%'));

  box.innerHTML = cells.join('');
}

function metricCell(label, value) {
  return `<div class="metric">
    <span class="metric-val">${esc(value)}</span>
    <span class="metric-label">${esc(label)}</span>
  </div>`;
}

function riskCell(t) {
  if (t.risk_score == null) return '<span style="color:var(--text-dim)">—</span>';
  const lvl = (t.risk_level || '').toLowerCase();
  let cls = 'risk-none';
  if (lvl.includes('crít') || lvl.includes('crit')) cls = 'risk-critico';
  else if (lvl.includes('alto')) cls = 'risk-alto';
  else if (lvl.includes('medio')) cls = 'risk-medio';
  return `<span class="risk ${cls}" title="${esc(t.risk_level || '')}">${esc(t.risk_score)}</span>`;
}

function rowHtml(t) {
  const st = targetState(t);
  const badge = `<span class="badge st-${esc(st)}">${esc(st.toUpperCase())}</span>`;
  const risk = riskCell(t);

  let assets = '';
  if (t.report_pdf)
    assets += `<a href="/reportes/${encodeURI(t.report_pdf)}" target="_blank">[REPORT]</a>`;
  if (t.detailed_report_pdf)
    assets += `<a href="/reportes/${encodeURI(t.detailed_report_pdf)}" target="_blank">[DETAILED]</a>`;
  if (t.remediation_pdf)
    assets += `<a href="/reportes/${encodeURI(t.remediation_pdf)}" target="_blank">[REMEDIATION]</a>`;
  if (!assets) assets = '<span style="color:var(--text-dim)">—</span>';

  const findings = t.total_findings == null
    ? '<span style="color:var(--text-dim)">—</span>'
    : esc(t.total_findings);

  return `<tr>
    <td class="domain-cell" onclick="fillDomain('${esc(t.dominio)}')" title="${esc(t.dominio)}">${esc(t.dominio)}</td>
    <td>${esc(t.name || '—')}</td>
    <td>${badge}</td>
    <td>${risk}</td>
    <td>${findings}</td>
    <td class="action-links">${assets}</td>
  </tr>`;
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ── FILTERS ───────────────────────────────────────────────

function setFilter(btn, filtro) {
  document.querySelectorAll('.tag').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  currentFilter = filtro;
  renderTable();
}

function initSearch() {
  const inp = document.getElementById('search');
  if (!inp) return;
  inp.addEventListener('input', () => {
    searchQuery = inp.value;
    renderTable();
  });
}

// ── DOMAIN FILL ───────────────────────────────────────────

function fillDomain(dominio) {
  if (!openFormId) return;
  const form = document.getElementById(openFormId);
  if (!form) return;
  const field = form.querySelector('input[type="text"]');
  if (field) field.value = dominio;
}

// ── COMMAND RUNNERS ───────────────────────────────────────

async function runCommand(cmd, params, btn) {
  const origText = btn.textContent.trim();
  btn.disabled = true;
  btn.textContent = 'EJECUTANDO...';

  appendTerminal(`INICIANDO: ${cmd.toUpperCase()} ${JSON.stringify(params)}`);

  try {
    const res = await fetch(`/api/run/${cmd}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(params),
    });
    const json = await res.json();
    if (json.error) {
      appendTerminal(`[✗] ERROR: ${json.error}`, 'error');
      btn.disabled = false;
      btn.textContent = origText;
      return;
    }

    const jobId = json.job_id;
    const domain = params.dominio || params.target_file || '';
    addJobHistory(jobId, cmd, domain);

    const es = new EventSource(`/api/stream/${jobId}`);

    es.onmessage = e => {
      appendTerminal(e.data.replace(/\\n/g, '\n'));
    };

    es.addEventListener('done', e => {
      const code = parseInt(e.data);
      const ok = code === 0;
      appendTerminal(
        ok ? `[✓] COMPLETADO (${cmd.toUpperCase()})` : `[✗] FALLÓ (código ${code})`,
        ok ? 'success' : 'error',
      );
      updateJobHistoryStatus(jobId, ok ? 'SUCCESS' : 'FAILED');
      es.close();
      btn.disabled = false;
      btn.textContent = origText;
      if (ok) setTimeout(() => loadTargets(currentFilter), 1200);
    });

    es.onerror = () => {
      appendTerminal('[✗] ERROR DE CONEXIÓN SSE', 'error');
      updateJobHistoryStatus(jobId, 'FAILED');
      es.close();
      btn.disabled = false;
      btn.textContent = origText;
    };

  } catch (e) {
    appendTerminal(`[✗] ERROR: ${e.message}`, 'error');
    btn.disabled = false;
    btn.textContent = origText;
  }
}

function runReport(btn) {
  const dominio = document.getElementById('report-dominio')?.value.trim();
  const nombre = document.getElementById('report-nombre')?.value.trim();
  if (!dominio || !nombre) { alert('Dominio y nombre son requeridos'); return; }
  runCommand('report', { dominio, nombre }, btn);
}

function runDiagnostico(btn) {
  const sel = document.getElementById('sel-sesiones');
  const dominio = sel?.value;
  if (!dominio) { alert('Selecciona una sesión'); return; }
  runCommand('diagnostico', { dominio }, btn);
}

function runBatch(btn) {
  const sel = document.getElementById('sel-targets');
  const target_file = sel?.value;
  const workers = parseInt(document.getElementById('batch-workers')?.value || '3');
  if (!target_file) { alert('Selecciona un archivo de targets'); return; }
  if (!confirm(`¿Ejecutar batch con ${target_file} (${workers} workers)?`)) return;
  runCommand('batch', { target_file, workers }, btn);
}

function runTrabajo(btn) {
  const dominio  = document.getElementById('trabajo-dominio')?.value.trim();
  const cliente  = document.getElementById('trabajo-cliente')?.value.trim();
  const auth_ref = document.getElementById('trabajo-auth')?.value.trim();
  if (!dominio || !cliente || !auth_ref) { alert('Todos los campos son requeridos'); return; }
  if (!confirm(`¿Ejecutar trabajo completo para ${dominio}?`)) return;
  runCommand('trabajo', { dominio, cliente, auth_ref }, btn);
}

// ── TERMINAL ──────────────────────────────────────────────

function appendTerminal(text, forcedClass) {
  const el = document.getElementById('output-content');
  if (!el) return;

  const p = document.createElement('p');
  p.textContent = '> ' + text;

  if (forcedClass) {
    p.className = forcedClass;
  } else if (/[✓]|SUCCESS/.test(text)) {
    p.className = 'success';
  } else if (/\[!\]|WARN/i.test(text)) {
    p.className = 'warn';
  } else if (/[✗]|ERROR/i.test(text)) {
    p.className = 'error';
  }

  el.appendChild(p);
  el.scrollTop = el.scrollHeight;
}

// ── JOB HISTORY ──────────────────────────────────────────

function addJobHistory(id, cmd, domain) {
  const now = new Date();
  const hhmm = now.toTimeString().slice(0, 5);
  jobHistory.unshift({ id, cmd, domain, status: 'running', time: hhmm });
  renderJobHistory();
}

function updateJobHistoryStatus(id, status) {
  const j = jobHistory.find(x => x.id === id);
  if (j) j.status = status;
  renderJobHistory();
  renderMetrics();
}

function renderJobHistory() {
  const el = document.getElementById('job-list');
  if (!el) return;

  if (!jobHistory.length) {
    el.innerHTML = '<li style="color:var(--text-dim)">Sin jobs activos</li>';
    return;
  }

  el.innerHTML = jobHistory.slice(0, 10).map(j => {
    const stClass = j.status === 'SUCCESS' ? 'ji-success'
                  : j.status === 'FAILED'  ? 'ji-failed'
                  : '';
    const stText = j.status === 'SUCCESS' ? '[✓]'
                 : j.status === 'FAILED'  ? '[✗]'
                 : '[●]';
    return `<li>
      <span class="timestamp">${j.time}</span>
      <span class="${stClass}">${stText}</span>
      <span>${esc(j.cmd)} ${esc(j.domain || '')}</span>
    </li>`;
  }).join('');
}

// ── DROPDOWNS ─────────────────────────────────────────────

async function loadTargetFiles() {
  try {
    const res = await fetch('/api/target-files');
    const files = await res.json();
    const sel = document.getElementById('sel-targets');
    if (!sel) return;
    if (!files.length) {
      sel.innerHTML = '<option value="">— sin archivos —</option>';
      return;
    }
    sel.innerHTML = files.map(f => `<option value="${esc(f)}">${esc(f)}</option>`).join('');
  } catch (e) {
    console.error('loadTargetFiles', e);
  }
}

async function loadSesiones() {
  try {
    const res = await fetch('/api/sesiones');
    const sessions = await res.json();
    const sel = document.getElementById('sel-sesiones');
    if (!sel) return;
    if (!sessions.length) {
      sel.innerHTML = '<option value="">— sin sesiones —</option>';
      return;
    }
    sel.innerHTML = '<option value="">— elegir sesión —</option>' +
      sessions.map(s => {
        const parts = s.split('_');
        const domain = parts.slice(0, -2).join('.');
        return `<option value="${esc(domain)}">${esc(s)}</option>`;
      }).join('');
  } catch (e) {
    console.error('loadSesiones', e);
  }
}
