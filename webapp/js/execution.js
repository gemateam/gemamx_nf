import { formatLocalDate, registerLoader, registerReloadFlag } from './app.js';

const API_BASE = 'http://localhost:8765/api/v1';
const STAGES = [
  { match: /^VALIDATE_CONTRACT/, label: 'Validación del contrato' },
  { match: /^INGEST/, label: 'Ingesta y priorización' },
  { match: /^FETCH_FASTA_/, label: 'Secuencias FASTA' },
  { match: /^(PREDICT_STRUCTURE_|BOLTZ_)/, label: 'Estructuras 3D' },
  { match: /^ALIGN_WT_MUT/, label: 'Alineamiento WT / mutante' },
  { match: /^PREP_LIGAND/, label: 'Preparación de ligandos' },
  { match: /^(PREP_RECEPTOR|DOCK_CENTER)/, label: 'Preparación del docking' },
  { match: /^RUN_VINA/, label: 'Docking AutoDock Vina' },
  { match: /^BUILD_JSONS/, label: 'Construcción de resultados' },
  { match: /^PUBLISH/, label: 'Publicación' },
  { match: /^LOG_MLFLOW/, label: 'Registro en MLflow' },
];

const form = document.getElementById('exec-form');
const pipelineSelect = document.getElementById('exec-pipeline');
const genesEl = document.getElementById('exec-gene-list');
const startButton = document.getElementById('exec-start');
const errorEl = document.getElementById('exec-error');
const configEl = document.getElementById('exec-config-json');
const logEl = document.getElementById('exec-log');
const resultsBody = document.getElementById('exec-results-body');
const resultsStatus = document.getElementById('exec-results-status');
const resultsSummary = document.getElementById('exec-results-summary');
const resultsCount = document.getElementById('exec-results-count');
const resultsState = { loaded: false, loading: false };
let pipelineOptions = {};
let pollTimer = null;
let estimateTimer = null;
let estimateRequestId = 0;
let optionsLoaded = false;
let lastCompletedResultsRun = '';

registerReloadFlag('pipeline', resultsState);

function bestDockingResult(metrics) {
  let best = null;
  for (const [variant, metric] of Object.entries(metrics ?? {})) {
    if (!metric || variant.endsWith('_WT')) continue;
    const scores = Object.entries(metric.vina_scores ?? {})
      .map(([drug, value]) => [drug, Number(value)])
      .filter(([, score]) => Number.isFinite(score));
    const candidates = scores.length
      ? scores
      : Number.isFinite(Number(metric.best_vina_score)) && metric.best_vina_drug
        ? [[metric.best_vina_drug, Number(metric.best_vina_score)]]
        : [];
    for (const [drug, score] of candidates) {
      if (!best || score < best.score) best = { variant, drug, score };
    }
  }
  return best;
}

async function fetchFreshJson(url) {
  const response = await fetch(`${url}?_=${Date.now()}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
  return response.json();
}

function appendResultCell(row, value, className = '') {
  const cell = document.createElement('td');
  if (className) cell.className = className;
  cell.textContent = value;
  row.appendChild(cell);
}

function renderRunResults(results) {
  if (!resultsBody) return;
  const selectedRun = document.getElementById('sel-run')?.value;
  resultsBody.replaceChildren();

  for (const { run, best, error } of results) {
    const row = document.createElement('tr');
    const runCell = document.createElement('td');
    runCell.className = 'exec-results-run';
    const name = document.createElement('strong');
    name.textContent = run.run_name;
    const date = document.createElement('small');
    date.textContent = formatLocalDate(run.published_at) || 'Fecha no disponible';
    runCell.append(name, date);
    row.appendChild(runCell);

    appendResultCell(row, best ? best.variant.replace('_', ' ') : error ? 'No disponible' : 'Sin docking');
    appendResultCell(row, best?.drug ?? '—', best ? 'exec-results-drug' : '');
    appendResultCell(row, best ? `${best.score.toFixed(3)} kcal/mol` : '—', best ? 'exec-results-score' : '');

    const actionCell = document.createElement('td');
    const selectButton = document.createElement('button');
    selectButton.type = 'button';
    selectButton.className = 'exec-results-select';
    selectButton.textContent = selectedRun === run.path ? 'Seleccionada' : 'Ver corrida';
    selectButton.disabled = selectedRun === run.path;
    selectButton.addEventListener('click', () => {
      const selector = document.getElementById('sel-run');
      if (!selector || ![...selector.options].some(option => option.value === run.path)) return;
      selector.value = run.path;
      selector.dispatchEvent(new Event('change', { bubbles: true }));
    });
    actionCell.appendChild(selectButton);
    row.appendChild(actionCell);
    resultsBody.appendChild(row);
  }
}

async function loadRunResults() {
  if (!resultsBody || resultsState.loaded || resultsState.loading) return;
  resultsState.loading = true;
  resultsStatus.textContent = 'Cargando resultados archivados…';
  try {
    const index = await fetchFreshJson('runs/index.json');
    const runs = (Array.isArray(index) ? index : []).filter(run =>
      run.run_name && /^runs\/[^/]+\/data$/.test(run.path ?? ''),
    );
    let nextRun = 0;
    const results = new Array(runs.length);
    const workers = Array.from({ length: Math.min(6, runs.length) }, async () => {
      while (nextRun < runs.length) {
        const index = nextRun++;
        const run = runs[index];
        try {
          const metrics = await fetchFreshJson(`${run.path}/structural_metrics.json`);
          results[index] = { run, best: bestDockingResult(metrics) };
        } catch (error) {
          results[index] = { run, best: null, error };
        }
      }
    });
    await Promise.all(workers);
    renderRunResults(results);
    resultsCount.textContent = String(results.length);
    resultsSummary.textContent = results.length
      ? 'Mejor score de docking por corrida archivada; el score más negativo ocupa el primer lugar.'
      : 'No hay corridas archivadas.';
    resultsStatus.textContent = results.length ? '' : 'Las corridas nuevas aparecerán después de publicarse.';
    resultsState.loaded = true;
  } catch (error) {
    resultsStatus.textContent = `No se pudieron cargar los resultados: ${error.message}`;
    resultsCount.textContent = '—';
  } finally {
    resultsState.loading = false;
  }
}

registerLoader('pipeline', loadRunResults);

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    cache: 'no-store',
    ...options,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers ?? {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error ?? `HTTP ${response.status}`);
  return payload;
}

function selectedGenes() {
  return [...genesEl.querySelectorAll('input:checked')].map(input => input.value);
}

function readForm() {
  return {
    pipeline: pipelineSelect.value,
    genes: selectedGenes(),
    max_variants: Number(document.getElementById('exec-max-variants').value),
    exhaustiveness: Number(document.getElementById('exec-exhaustiveness').value),
    num_modes: Number(document.getElementById('exec-num-modes').value),
    vina_timeout_sec: Number(document.getElementById('exec-timeout').value),
    max_parallel_vina: Number(document.getElementById('exec-parallel').value),
    box_size: Number(document.getElementById('exec-box-size').value),
    vina_seed: Number(document.getElementById('exec-seed').value),
    resume: document.getElementById('exec-resume').checked,
  };
}

function showError(message) {
  errorEl.textContent = message;
  errorEl.hidden = !message;
}

function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(Number(seconds))) return '—';
  const roundedMinutes = Math.max(1, Math.round(Number(seconds) / 60));
  const hours = Math.floor(roundedMinutes / 60);
  const minutes = roundedMinutes % 60;
  return hours ? `${hours} h ${minutes} min` : `${minutes} min`;
}

function renderEstimate(summary) {
  const valueEl = document.getElementById('exec-estimate-value');
  const noteEl = document.getElementById('exec-estimate-note');
  if (summary.estimate.kind === 'historical') {
    valueEl.textContent = `Esperado ${formatDuration(summary.estimate.total_seconds_estimate)} · cota ${formatDuration(summary.estimate.total_seconds_high)}`;
  } else {
    valueEl.textContent = `Hasta ${formatDuration(summary.estimate.total_seconds_high)} (cota por timeout)`;
  }
  const warning = summary.estimate.warnings?.join(' ');
  noteEl.textContent = `${summary.variant_count_estimate} variantes + ${summary.wild_type_receptors_estimate} receptores WT · ${summary.drug_count_estimate} fármacos · ${summary.docking_pairs_estimate} dockings · ${summary.profile}. ${summary.estimate.note}${warning ? ` ${warning}` : ''}`;
  noteEl.classList.toggle('exec-estimate-warning', Boolean(warning));
}

async function updateEstimate() {
  if (!pipelineSelect.value || !selectedGenes().length) return;
  const requestId = ++estimateRequestId;
  const requestPayload = readForm();
  try {
    const summary = await api('/estimate', { method: 'POST', body: JSON.stringify(requestPayload) });
    if (requestId !== estimateRequestId) return;
    renderEstimate(summary);
    document.getElementById('exec-profile-label').textContent = `${summary.pipeline_label} · ${summary.profile}`;
    document.getElementById('exec-config-summary').textContent = `${summary.workflow} · ${summary.docking_pairs_estimate} pares receptor–fármaco estimados`;
    configEl.textContent = JSON.stringify({ ...summary, resume: requestPayload.resume }, null, 2);
    showError('');
  } catch (error) {
    if (requestId !== estimateRequestId) return;
    document.getElementById('exec-estimate-value').textContent = 'No disponible';
    document.getElementById('exec-estimate-note').textContent = error.message;
    showError(error.message);
  }
}

function scheduleEstimate() {
  clearTimeout(estimateTimer);
  estimateTimer = window.setTimeout(updateEstimate, 250);
}

function renderPipelineDefaults(pipelineId) {
  const pipeline = pipelineOptions[pipelineId];
  if (!pipeline) return;
  document.getElementById('exec-profile-label').textContent = `${pipeline.label} · ${pipeline.profile}`;
  document.getElementById('exec-config-summary').textContent = `${pipeline.workflow} · calculando pares receptor–fármaco`;
  genesEl.replaceChildren();
  pipeline.genes.forEach(gene => {
    const label = document.createElement('label');
    label.className = 'exec-gene-option';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = gene;
    checkbox.checked = pipeline.defaults.genes.includes(gene);
    checkbox.addEventListener('change', scheduleEstimate);
    const text = document.createElement('span');
    text.textContent = gene;
    label.append(checkbox, text);
    genesEl.append(label);
  });
  document.getElementById('exec-max-variants').max = pipeline.max_variants_limit;
  document.getElementById('exec-max-variants').value = pipeline.defaults.max_variants;
  document.getElementById('exec-exhaustiveness').value = pipeline.defaults.exhaustiveness;
  document.getElementById('exec-num-modes').value = pipeline.defaults.num_modes;
  document.getElementById('exec-timeout').value = pipeline.defaults.vina_timeout_sec;
  document.getElementById('exec-parallel').value = pipeline.defaults.max_parallel_vina;
  document.getElementById('exec-box-size').value = pipeline.defaults.box_size;
  document.getElementById('exec-seed').value = pipeline.defaults.vina_seed;
  scheduleEstimate();
}

function renderStages(traceText) {
  const target = document.getElementById('exec-stage-list');
  const lines = traceText.trim().split(/\r?\n/);
  if (lines.length < 2) {
    target.textContent = 'Esperando tareas de Nextflow…';
    return;
  }
  const headers = lines[0].split('\t');
  const nameIndex = headers.indexOf('name');
  const statusIndex = headers.indexOf('status');
  if (nameIndex < 0 || statusIndex < 0) {
    target.textContent = 'La traza todavía no contiene tareas.';
    return;
  }
  const counts = new Map();
  for (const line of lines.slice(1)) {
    if (!line.trim()) continue;
    const fields = line.split('\t');
    const name = (fields[nameIndex] ?? '').replace(/\s*\(.*$/, '').trim();
    const stage = STAGES.find(item => item.match.test(name));
    if (!stage) continue;
    const entry = counts.get(stage.label) ?? { done: 0, failed: 0, active: 0 };
    const state = (fields[statusIndex] ?? '').toUpperCase();
    if (['COMPLETED', 'CACHED'].includes(state)) entry.done++;
    else if (['FAILED', 'ABORTED'].includes(state)) entry.failed++;
    else entry.active++;
    counts.set(stage.label, entry);
  }
  target.replaceChildren(...STAGES.flatMap(stage => {
    const entry = counts.get(stage.label);
    if (!entry) return [];
    const row = document.createElement('div');
    row.className = `exec-stage${entry.failed ? ' exec-stage--failed' : ''}`;
    const label = document.createElement('span');
    label.textContent = stage.label;
    const value = document.createElement('span');
    value.textContent = `${entry.done} completadas${entry.active ? ` · ${entry.active} en curso` : ''}${entry.failed ? ` · ${entry.failed} fallidas` : ''}`;
    row.append(label, value);
    return [row];
  }));
}

function renderStatus(status) {
  const stateEl = document.getElementById('exec-live-state');
  const labels = { idle: 'Sin ejecución', starting: 'Preparando', running: 'En ejecución', completed: 'Completada', failed: 'Falló' };
  stateEl.textContent = labels[status.status] ?? 'Estado desconocido';
  stateEl.dataset.status = status.status ?? 'unknown';
  document.getElementById('exec-live-summary').textContent = status.run_name ?? 'Sin ejecución activa';
  document.getElementById('exec-live-meta').textContent = status.run_name
    ? `${status.pipeline_label ?? ''} · ${status.profile ?? ''} · iniciado ${new Date(status.started_at).toLocaleString()}`
    : 'Selecciona los parámetros y lanza una ejecución.';

  const mlflowLink = document.getElementById('exec-mlflow-link');
  if (status.mlflow_run_id && status.mlflow_experiment_id) {
    mlflowLink.href = `http://localhost:5000/#/experiments/${encodeURIComponent(status.mlflow_experiment_id)}/runs/${encodeURIComponent(status.mlflow_run_id)}`;
    mlflowLink.hidden = false;
  } else {
    mlflowLink.hidden = true;
  }

  if (status.config && Object.keys(status.config).length) {
    configEl.textContent = JSON.stringify(status.config, null, 2);
    document.getElementById('exec-profile-label').textContent = `${status.pipeline_label} · ${status.profile}`;
  }
  renderStages(status.trace_tail ?? '');

  const wasAtBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 48;
  logEl.textContent = status.log_tail || 'El log aparecerá cuando inicie Nextflow.';
  document.getElementById('exec-log-meta').textContent = status.log_file
    ? `${status.log_file} · actualizado ${new Date(status.updated_at).toLocaleTimeString()}`
    : 'Se actualizará al iniciar una ejecución.';
  if (wasAtBottom) logEl.scrollTop = logEl.scrollHeight;

  const running = ['starting', 'running'].includes(status.status);
  startButton.disabled = running || !pipelineSelect.options.length;
  startButton.textContent = running ? 'Pipeline en ejecución' : 'Iniciar pipeline';
}

async function refreshStatus() {
  try {
    const status = await api('/status');
    renderStatus(status);
    if (status.status === 'completed' && status.run_name && lastCompletedResultsRun !== status.run_name) {
      lastCompletedResultsRun = status.run_name;
      resultsState.loaded = false;
      loadRunResults();
    }
  } catch (error) {
    startButton.disabled = true;
    showError(`API local no disponible: ${error.message}`);
    document.getElementById('exec-live-state').textContent = 'API desconectada';
    document.getElementById('exec-live-state').dataset.status = 'failed';
  }
}

async function startRun(event) {
  event.preventDefault();
  showError('');
  startButton.disabled = true;
  startButton.textContent = 'Registrando en MLflow…';
  try {
    const result = await api('/start', { method: 'POST', body: JSON.stringify(readForm()) });
    document.getElementById('exec-live-summary').textContent = result.run_name;
    await refreshStatus();
  } catch (error) {
    showError(error.message);
    startButton.disabled = false;
    startButton.textContent = 'Iniciar pipeline';
  }
}

async function initialize() {
  form.addEventListener('submit', startRun);
  pipelineSelect.addEventListener('change', () => renderPipelineDefaults(pipelineSelect.value));
  form.addEventListener('input', scheduleEstimate);
  document.getElementById('exec-log-bottom').addEventListener('click', () => { logEl.scrollTop = logEl.scrollHeight; });
  const loadOptions = async () => {
    const response = await api('/options');
    pipelineOptions = response.pipelines;
    pipelineSelect.replaceChildren(...Object.entries(pipelineOptions).map(([id, pipeline]) => {
      const option = document.createElement('option');
      option.value = id;
      option.textContent = pipeline.label;
      return option;
    }));
    pipelineSelect.value = 'tcga-v3';
    optionsLoaded = true;
    renderPipelineDefaults(pipelineSelect.value);
  };
  const refresh = async () => {
    try {
      if (!optionsLoaded) await loadOptions();
      showError('');
      await refreshStatus();
    } catch (error) {
      showError(`API local no disponible: ${error.message}`);
      document.getElementById('exec-live-state').textContent = 'API desconectada';
      document.getElementById('exec-live-state').dataset.status = 'failed';
      startButton.disabled = true;
    }
  };
  await refresh();
  if (!pollTimer) pollTimer = window.setInterval(refresh, 2000);
}

initialize();
