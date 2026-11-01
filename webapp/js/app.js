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
  runManifest:          () => dataUrl('run_manifest.json'),
  rawMutations:         () => dataUrl('raw_mutations.json'),
  clinicalMetadata:     () => dataUrl('clinical_metadata.json'),
  variantClinicalSummary: () => dataUrl('variant_clinical_summary.json'),
  romeroGeoSummary:     () => dataUrl('romero_geo_summary.json'),
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
const VIEWS = ['dashboard','analysis','structural','docking','report','pipeline','explore','clinical'];

// ── Detección de versión del pipeline ─────────────────────────────────────
export function isV2() {
  return BASE_PATH.includes('romero_v2') ||
    document.getElementById('sel-run')?.value?.includes('romero');
}

// Dispatch de carga por vista (se registra desde cada módulo)
const loaders = {};
export function registerLoader(view, fn) { loaders[view] = fn; }

// Vista activa actualmente
let activeView = 'dashboard';

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

async function loadRunIndex() {
  const index = await loadJSON('runs/index.json');
  return Array.isArray(index) ? index : [];
}

async function populateRunSelector() {
  const sel = document.getElementById('sel-run');
  if (!sel) return;

  const runs = await loadRunIndex();

  // Primera opción = contrato vigente (data/)
  const liveOpt = document.createElement('option');
  liveOpt.value = 'data';
  liveOpt.textContent = '⬤ Corrida vigente';
  liveOpt.selected = true;
  sel.innerHTML = '';
  sel.appendChild(liveOpt);

  if (!runs.length) return;

  // Agrupar por pipeline_version
  const byVersion = {};
  runs.forEach(r => {
    const v = r.pipeline_version ?? 'Sin versión';
    (byVersion[v] = byVersion[v] ?? []).push(r);
  });

  Object.entries(byVersion).forEach(([version, vRuns]) => {
    const group = document.createElement('optgroup');
    group.label = `📦 ${version}`;
    vRuns.forEach(r => {
      const opt = document.createElement('option');
      opt.value = r.path;
      const date = r.published_at?.slice(0, 10) ?? '';
      const commit = r.git_commit ? ` · ${r.git_commit.slice(0, 7)}` : '';
      opt.textContent = `${r.run_name} · ${date}${commit}`;
      group.appendChild(opt);
    });
    sel.appendChild(group);
  });

  sel.addEventListener('change', () => switchRun(sel.value));
}

function switchRun(path) {
  // Actualizar BASE_PATH global
  BASE_PATH = path;

  // Invalidar caché completo
  Object.keys(cache).forEach(k => delete cache[k]);

  // Resetear flags de carga de cada módulo
  Object.values(reloadFlags).forEach(f => { f.loaded = false; });

  // Mostrar/ocultar tab Clínico según pipeline version
  const clinicalTab = document.getElementById('nav-clinical');
  if (clinicalTab) {
    const isRomero = path.includes('romero');
    clinicalTab.style.display = isRomero ? '' : 'none';
    // Si estamos en la vista clínica y cambiamos a v1, volver a dashboard
    if (!isRomero && activeView === 'clinical') {
      activateView('dashboard');
    }
  }

  // Actualizar footer con versión de pipeline
  loadJSON(DATA.runManifest()).then(m => {
    const footerEl = document.getElementById('footer-run');
    if (!footerEl) return;
    footerEl.textContent = m?.run_name
      ? `Run: ${m.run_name}  ·  ${m.published_at?.slice(0,10) ?? ''}  ·  ${m.params?.mlflow_experiment ?? ''}`
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
        `Run: ${m.run_name}  ·  ${m.published_at?.slice(0,10) ?? ''}  ·  ${m.params?.mlflow_experiment ?? ''}`;
    }
  });

  // Poblar selector de corridas
  populateRunSelector();

  // Vista inicial
  activateView('dashboard');
});
