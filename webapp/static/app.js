'use strict';

let allProspectos = [];
let currentFilter = 'all';
let searchQuery = '';
let openFormId = null;
let jobHistory = [];

// ── INIT ──────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadProspectos('all');
  loadTargets();
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

async function loadProspectos(filtro) {
  if (filtro) currentFilter = filtro;
  try {
    const res = await fetch('/api/prospectos');
    allProspectos = await res.json();
    renderTable();
  } catch (e) {
    console.error('loadProspectos', e);
  }
}

const OUTREACH_ESTADOS = ['pendiente', 'enviado', 'respondido', 'descartado'];

function outreachEstado(p) {
  const e = (p.outreach_estado || '').toLowerCase();
  return OUTREACH_ESTADOS.includes(e) ? e : 'pendiente';
}

function renderTable() {
  const q = searchQuery.toLowerCase();
  const rows = allProspectos.filter(p => {
    const est = outreachEstado(p);
    const mf = currentFilter === 'all'
      ? est !== 'descartado'
      : est === currentFilter;
    const ms = !q
      || p.dominio.toLowerCase().includes(q)
      || (p.nombre || '').toLowerCase().includes(q)
      || (p.email_contacto || '').toLowerCase().includes(q);
    return mf && ms;
  });

  const counter = document.getElementById('counter');
  if (counter) counter.textContent = `${rows.length} / ${allProspectos.length}`;

  const tbody = document.getElementById('prospectos-body');
  if (!tbody) return;

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-dim);padding:24px">NO_TARGETS_FOUND</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map(rowHtml).join('');
}

function outreachBadge(dominio, est) {
  const opts = OUTREACH_ESTADOS.map(e =>
    `<option value="${e}"${e === est ? ' selected' : ''}>${e.toUpperCase()}</option>`
  ).join('');
  return `<select class="outreach-badge ob-${est}"
    onchange="patchOutreach('${esc(dominio)}', this.value, this)"
    title="Cambiar estado de outreach">${opts}</select>`;
}

function riskCell(p) {
  if (p.risk_score == null) return '<span style="color:var(--text-dim)">—</span>';
  const lvl = (p.risk_level || '').toLowerCase();
  let cls = 'risk-none';
  if (lvl.includes('crít') || lvl.includes('crit')) cls = 'risk-critico';
  else if (lvl.includes('alto')) cls = 'risk-alto';
  else if (lvl.includes('medio')) cls = 'risk-medio';
  return `<span class="risk ${cls}" title="${esc(p.risk_level || '')}">${esc(p.risk_score)}</span>`;
}

function rowHtml(p) {
  let badgeClass, badgeText;
  if (p.trabajo_pdf)     { badgeClass = 'trabajo';    badgeText = 'TRABAJO'; }
  else if (p.diagnostico_pdf) { badgeClass = 'diagnostico'; badgeText = 'DIAG'; }
  else if (p.flash_pdf)  { badgeClass = 'flash';      badgeText = 'FLASH'; }
  else                   { badgeClass = 'nuevo';      badgeText = 'NUEVO'; }

  const badge = `<span class="badge ${badgeClass}">${badgeText}</span>`;
  const email = p.email_contacto
    ? `<a href="mailto:${esc(p.email_contacto)}" class="email-link">${esc(p.email_contacto)}</a>`
    : '<span style="color:var(--text-dim)">—</span>';
  const outreach = outreachBadge(p.dominio, outreachEstado(p));
  const risk = riskCell(p);

  let assets = '';
  if (p.flash_pdf)       assets += `<a href="/reportes/${encodeURI(p.flash_pdf)}" target="_blank">[VIEW_FLASH]</a>`;
  if (p.diagnostico_pdf) assets += `<a href="/reportes/${encodeURI(p.diagnostico_pdf)}" target="_blank">[FULL_DIAG]</a>`;
  if (p.trabajo_pdf)     assets += `<a href="/reportes/${encodeURI(p.trabajo_pdf)}" target="_blank">[TRABAJO]</a>`;
  if (outreachEstado(p) === 'descartado')
    assets += `<a href="#" class="restaurar-link" onclick="restaurarOutreach(event, '${esc(p.dominio)}')">[RESTAURAR]</a>`;
  if (!assets)           assets = '<span style="color:var(--text-dim)">—</span>';

  return `<tr>
    <td class="domain-cell" onclick="fillDomain('${esc(p.dominio)}')" title="${esc(p.dominio)}">${esc(p.dominio)}</td>
    <td>${esc(p.nombre || '—')}</td>
    <td class="email-cell">${email}</td>
    <td>${badge}</td>
    <td class="outreach-cell">${outreach}</td>
    <td>${risk}</td>
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

// ── OUTREACH ──────────────────────────────────────────────

async function patchOutreach(dominio, estado, el) {
  if (el) el.disabled = true;
  try {
    const res = await fetch(`/api/prospectos/${encodeURIComponent(dominio)}/outreach`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ estado }),
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const p = allProspectos.find(x => x.dominio === dominio);
    if (p) p.outreach_estado = estado;
    appendTerminal(`OUTREACH ${dominio} → ${estado.toUpperCase()}`);
    renderTable();
  } catch (e) {
    appendTerminal(`[✗] No se pudo actualizar outreach de ${dominio}: ${e.message}`, 'error');
    if (el) el.disabled = false;
  }
}

function restaurarOutreach(ev, dominio) {
  ev.preventDefault();
  patchOutreach(dominio, 'pendiente', null);
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
      if (ok) setTimeout(() => loadProspectos(currentFilter), 1200);
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

function runFlash(btn) {
  const dominio = document.getElementById('flash-dominio')?.value.trim();
  const cliente = document.getElementById('flash-cliente')?.value.trim();
  const ciber = document.getElementById('flash-ciber')?.checked || false;
  if (!dominio || !cliente) { alert('Dominio y cliente son requeridos'); return; }
  runCommand('flash', { dominio, cliente, ciber }, btn);
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

async function loadTargets() {
  try {
    const res = await fetch('/api/targets');
    const files = await res.json();
    const sel = document.getElementById('sel-targets');
    if (!sel) return;
    if (!files.length) {
      sel.innerHTML = '<option value="">— sin archivos —</option>';
      return;
    }
    sel.innerHTML = files.map(f => `<option value="${esc(f)}">${esc(f)}</option>`).join('');
  } catch (e) {
    console.error('loadTargets', e);
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
