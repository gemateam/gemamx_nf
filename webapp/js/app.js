/**
 * app.js — navegación SPA, carga de datos compartidos, utilidades globales
 */

// ── Rutas de datos (relativas al origin del servidor) ──────────────────────
// BASE_PATH apunta al directorio de datos activo.
// Cuando el usuario selecciona una corrida histórica se actualiza a
// 'data/runs/<runName>/data' y se notifica a todos los módulos para recargar.
export let BASE_PATH = 'data';

export function dataUrl(file) {
  return `${BASE_PATH}/${file}`;
}

// El contrato publica rutas relativas al árbol de datos ("data/...").
// Al navegar a una corrida histórica (BASE_PATH = "runs/<run>/data") hay que
// reescribir el prefijo; si no, se cargarían los ficheros de la vigente.
export function contractUrl(path) {
  if (!path) return null;
  const prefix = 'data/';
  return path.startsWith(prefix) ? `${BASE_PATH}/${path.slice(prefix.length)}` : path;
}

export const DATA = {
  topVariants:          () => dataUrl('top_variants.json'),
  structuralMetrics:    () => dataUrl('structural_metrics.json'),
  manifestStructures:   () => dataUrl('manifest_structures.json'),
  vinaAffinities:       () => dataUrl('docking/vina_affinities.json'),
  mutationStats:        () => dataUrl('mutation_stats.json'),
  runManifest:          () => BASE_PATH.startsWith('runs/')
    ? BASE_PATH.replace(/\/data$/, '/run_manifest.json')
    : dataUrl('run_manifest.json'),
  rawMutations:         () => dataUrl('raw_mutations.json'),
  dataIngest:           () => dataUrl('data_ingest.json'),
  clinicalMetadata:     () => dataUrl('clinical_metadata.json'),
  variantClinicalSummary: () => dataUrl('variant_clinical_summary.json'),
  contractProvenance:   () => dataUrl('contract_provenance.json'),
  romeroGeoSummary:     () => dataUrl('romero_geo_summary.json'),
  // Modelos AlphaFold DB de genes sin estructura propia: independiente de la
  // corrida activa (no depende de BASE_PATH).
  externalStructures:   () => 'external/index.json',
};

// ── Catálogo de fármacos (targets y estado, sin red) ──────────────────────
export const DRUG_META = {
  Alpelisib:   { target: 'PI3Kα',    status: 'FDA' },
  Abemaciclib: { target: 'CDK4/6',   status: 'FDA' },
  Palbociclib: { target: 'CDK4/6',   status: 'FDA' },
  Ribociclib:  { target: 'CDK4/6',   status: 'FDA' },
  Copanlisib:  { target: 'Pan-PI3K', status: 'FDA' },
  Capivasertib:{ target: 'AKT1/2/3', status: 'FDA' },
  Everolimus:  { target: 'mTOR',     status: 'FDA' },
  Gedatolisib: { target: 'PI3K/mTOR',status: 'Ensayo' },
  Taselisib:   { target: 'PI3Kα',    status: 'Ensayo' },
  Pictilisib:  { target: 'PI3K',     status: 'Ensayo' },
  Buparlisib:  { target: 'Pan-PI3K', status: 'Ensayo' },
};

// ── Cache global de datos ──────────────────────────────────────────────────
export const cache = {};

// ── Fetch con cache ────────────────────────────────────────────────────────
export async function loadJSON(url) {
  if (cache[url]) return cache[url];
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    cache[url] = await res.json();
    return cache[url];
  } catch (e) {
    console.warn(`loadJSON failed: ${url}`, e);
    return null;
  }
}

// ── Clasificación → clase CSS ──────────────────────────────────────────────
export function badgeClass(cls) {
  if (!cls) return '';
  const c = cls.toLowerCase();
  if (c.includes('patogénica') && c.includes('prob')) return 'badge-prob-patogenica';
  if (c.includes('patogénica')) return 'badge-patogenica';
  if (c.includes('vus'))        return 'badge-vus';
  if (c.includes('baja'))       return 'badge-baja';
  return 'badge-hotspot';
}

// ── Formato numérico seguro ────────────────────────────────────────────────
export function fmt(v, decimals = 2) {
  if (v === null || v === undefined || v === '--') return '—';
  const n = parseFloat(v);
  return isNaN(n) ? '—' : n.toFixed(decimals);
}

export function formatLocalDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

// ── Colores Plotly alineados con CSS vars ─────────────────────────────────
export const PLOTLY_LAYOUT = {
  paper_bgcolor: 'transparent',
  plot_bgcolor:  'transparent',
  font:   { color: '#e2e8f0', size: 11 },
  margin: { l: 50, r: 20, t: 30, b: 80 },
  colorway: ['#14b8a6','#60a5fa','#a78bfa','#f87171','#fbbf24','#34d399',
             '#fb923c','#e879f9','#38bdf8','#4ade80','#f472b6'],
};

// ── Navegación SPA ─────────────────────────────────────────────────────────
const VIEWS = ['import','pipeline','dashboard','explore','analysis','structural','docking','report'];

// ── Detección de versión del pipeline ─────────────────────────────────────
export function isV2() {
  return BASE_PATH.includes('romero_v2') ||
    document.getElementById('sel-run')?.value?.includes('romero');
}

export function isV3() {
  return BASE_PATH.includes('tcga_brca_hispanic') ||
    document.getElementById('sel-run')?.value?.includes('tcga_brca_hispanic');
}

// Dispatch de carga por vista (se registra desde cada módulo)
const loaders = {};
export function registerLoader(view, fn) { loaders[view] = fn; }

// Vista activa actualmente
let activeView = 'import';

function activateView(name) {
  VIEWS.forEach(v => {
    document.getElementById(`view-${v}`)?.classList.toggle('active', v === name);
    document.querySelector(`[data-view="${v}"]`)?.classList.toggle('active', v === name);
  });
  activeView = name;
  if (loaders[name]) loaders[name]();
}

// ── Selector de corridas ───────────────────────────────────────────────────
// Invalida la caché de todos los módulos y los fuerza a recargar al cambiar de run.
const reloadFlags = {};
export function registerReloadFlag(view, flagObj) { reloadFlags[view] = flagObj; }

const MLFLOW_EXPERIMENTS = new Set([
  'GEMAMX-V1-NF',
  'GEMAMX-V2-ROMERO',
  'GEMAMX-V2_1-ROMERO',
  'GEMAMX-V3-TCGA-HISPANIC',
]);
let runSelectorRefreshing = false;

async function fetchFreshJson(url) {
  const response = await fetch(`${url}?_=${Date.now()}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
  return response.json();
}

async function searchMlflow(resource, body, collectionKey) {
  const items = [];
  let pageToken;
  do {
    const response = await fetch(`/mlflow-api/${resource}`, {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, max_results: 1000, ...(pageToken ? { page_token: pageToken } : {}) }),
    });
    if (!response.ok) throw new Error(`MLflow HTTP ${response.status}: ${resource}`);
    const page = await response.json();
    items.push(...(page[collectionKey] ?? []));
    pageToken = page.next_page_token;
  } while (pageToken);
  return items;
}

async function loadMlflowRuns() {
  const experiments = await searchMlflow('experiments/search', {}, 'experiments');
  const relevant = experiments.filter(experiment => MLFLOW_EXPERIMENTS.has(experiment.name));
  const runsByExperiment = await Promise.all(relevant.map(async experiment => {
    const runs = await searchMlflow('runs/search', { experiment_ids: [experiment.experiment_id] }, 'runs');
    return runs.flatMap(run => {
      const tags = Object.fromEntries((run.data?.tags ?? []).map(tag => [tag.key, tag.value]));
      if (tags['mlflow.parentRunId']) return [];
      const timestamp = Number(run.info?.end_time || run.info?.start_time);
      return [{
        run_name: run.info?.run_name || tags['gemamx.run_name'],
        published_at: Number.isFinite(timestamp) && timestamp > 0
          ? new Date(timestamp).toISOString() : '',
        git_commit: tags['gemamx.git_commit'] ?? '',
        pipeline_version: experiment.name,
        start_time: Number(run.info?.start_time) || 0,
      }];
    });
  }));
  return runsByExperiment.flat().filter(run => run.run_name)
    .sort((a, b) => b.start_time - a.start_time);
}

async function populateRunSelector() {
  const sel = document.getElementById('sel-run');
  if (!sel || runSelectorRefreshing) return;
  runSelectorRefreshing = true;
  const selectedValue = sel.value || 'data';

  try {
    const [index, manifest] = await Promise.all([
      fetchFreshJson('runs/index.json').catch(() => []),
      fetchFreshJson('data/run_manifest.json').catch(() => null),
    ]);
    const archivedRuns = Array.isArray(index) ? index : [];
    const archivesByName = new Map(archivedRuns.map(run => [run.run_name, run]));

    let runs;
    try {
      const mlflowRuns = await loadMlflowRuns();
      const seen = new Set();
      runs = mlflowRuns.map(run => {
        seen.add(run.run_name);
        const archived = archivesByName.get(run.run_name);
        return {
          ...archived,
          ...run,
          path: archived?.path ?? (manifest?.run_name === run.run_name ? 'data' : null),
        };
      }).filter(run => run.path);
      runs.push(...archivedRuns.filter(run => !seen.has(run.run_name) && run.path));
    } catch (error) {
      console.warn('MLflow no disponible; se usa el índice local de corridas.', error);
      runs = archivedRuns;
    }

    const byVersion = {};
    runs.forEach(run => {
      const version = run.pipeline_version ?? 'Sin versión';
      (byVersion[version] = byVersion[version] ?? []).push(run);
    });

    const liveOpt = document.createElement('option');
    liveOpt.value = 'data';
    liveOpt.textContent = manifest?.run_name
      ? `⬤ Corrida vigente · ${manifest.run_name}`
      : '⬤ Corrida vigente';
    sel.replaceChildren(liveOpt);

    Object.entries(byVersion).forEach(([version, versionRuns]) => {
      const group = document.createElement('optgroup');
      group.label = `📦 ${version}`;
      versionRuns.forEach(run => {
        const option = document.createElement('option');
        const date = formatLocalDate(run.published_at);
        const commit = run.git_commit ? ` · ${run.git_commit.slice(0, 7)}` : '';
        option.value = run.path;
        option.textContent = `${run.run_name} · ${date}${commit}`;
        group.appendChild(option);
      });
      sel.appendChild(group);
    });

    sel.value = [...sel.options].some(option => option.value === selectedValue)
      ? selectedValue : 'data';
    sel.onchange = () => switchRun(sel.value);
  } finally {
    runSelectorRefreshing = false;
  }
}


export async function updateGlobalHeader() {
  const [manifest, stats] = await Promise.all([
    loadJSON(DATA.runManifest()),
    loadJSON(DATA.mutationStats())
  ]);

  const experiment = manifest?.params?.mlflow_experiment ?? '';
  const isV2Run = isV2() || experiment === 'GEMAMX-V2-ROMERO' || experiment === 'GEMAMX-V2_1-ROMERO';
  const isV3Run = isV3() || experiment === 'GEMAMX-V3-TCGA-HISPANIC';
  const datasetName = isV2Run
    ? (stats?.dataset ?? 'Romero-Córdoba 2021 HM (FUCAM)')
    : isV3Run ? 'TCGA-BRCA Hispano/Latino' : (manifest?.params?.study_id?.toUpperCase() ?? 'TCGA-BRCA');

  // Navbar brand sub
  const brandSub = document.getElementById('brand-sub');
  if (brandSub) {
    brandSub.textContent = 'Genomic Analysis of Mammary Cancer · ' + datasetName;
  }



  // Explore title
  const expTitle = document.getElementById('explore-title');
  if (expTitle) {
    expTitle.textContent = isV2Run ? 'Exploración Romero HM' : 'Exploración TCGA';
  }

  // Analysis subtitle
  const anaSub = document.getElementById('analysis-subtitle');
  if (anaSub) {
    anaSub.textContent = 'Distribuciones y estadísticas de la cohorte ' + datasetName;
  }

  // Pipeline status subtitle & label
  const pipeSub = document.getElementById('pipeline-subtitle');
  if (pipeSub) {
    pipeSub.textContent = 'Resumen ejecutivo del proyecto GEMA MX sobre la cohorte ' + datasetName + '.';
  }
  const datasetLabel = document.getElementById('ps-dataset-label');
  if (datasetLabel) {
    datasetLabel.textContent = 'Dataset: ' + datasetName + ' activo';
  }

  // Footer brand
  const footerBrand = document.getElementById('footer-brand');
  if (footerBrand) {
    const pipelineLabel = isV3Run ? 'Pipeline V3 · TCGA Hispano/Latino' : isV2Run ? 'Pipeline V2 · Romero HM' : 'Pipeline V1 · TCGA-BRCA';
    footerBrand.textContent = `GEMA MX · ${pipelineLabel} · Universidad de Sonora`;
  }
}

function switchRun(path) {
  // Actualizar BASE_PATH global
  BASE_PATH = path;

  // Invalidar caché completo
  Object.keys(cache).forEach(k => delete cache[k]);

  // Resetear flags de carga de cada módulo
  Object.values(reloadFlags).forEach(f => { f.loaded = false; });

  // Actualizar cabeceras globales y textos de cohorte
  updateGlobalHeader();

  // Mostrar/ocultar tab Clínico según pipeline version
  const clinicalTab = document.getElementById('nav-clinical');
  if (clinicalTab) {
    const isRomero = path.includes('romero');
    clinicalTab.style.display = isRomero ? '' : 'none';
    // Si estamos en la vista clínica y cambiamos a v1, volver a dashboard
    if (!isRomero && activeView === 'clinical') {
      activateView('pipeline');
    }
  }

  // Actualizar footer con versión de pipeline
  loadJSON(DATA.runManifest()).then(m => {
    const footerEl = document.getElementById('footer-run');
    if (!footerEl) return;
    footerEl.textContent = m?.run_name
      ? `Run: ${m.run_name}  ·  ${formatLocalDate(m.published_at)}  ·  ${m.params?.mlflow_experiment ?? ''}`
      : '';
  });

  // Recargar la vista activa
  if (loaders[activeView]) loaders[activeView]();
}

// ── Bootstrap ─────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Navegación
  document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      activateView(link.dataset.view);
    });
  });

  // Cargar run name en footer
  loadJSON(DATA.runManifest()).then(m => {
    if (m?.run_name) {
      document.getElementById('footer-run').textContent =
        `Run: ${m.run_name}  ·  ${formatLocalDate(m.published_at)}  ·  ${m.params?.mlflow_experiment ?? ''}`;
    }
  });

  // Poblar selector de corridas
  populateRunSelector();
  window.addEventListener('focus', populateRunSelector);
  window.setInterval(populateRunSelector, 60_000);

  // Actualizar textos globales dinámicos de cohorte
  updateGlobalHeader();

  // Vista inicial
  activateView('import');
});
