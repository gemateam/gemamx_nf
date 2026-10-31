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

export const DATA = {
  topVariants:        () => dataUrl('top_variants.json'),
  structuralMetrics:  () => dataUrl('structural_metrics.json'),
  manifestStructures: () => dataUrl('manifest_structures.json'),
  vinaAffinities:     () => dataUrl('docking/vina_affinities.json'),
  mutationStats:      () => dataUrl('mutation_stats.json'),
  runManifest:        () => dataUrl('run_manifest.json'),
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
const VIEWS = ['dashboard','analysis','structural','docking','report'];

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
  const index = await loadJSON('data/runs/index.json');
  return Array.isArray(index) ? index : [];
}

async function populateRunSelector() {
  const sel = document.getElementById('sel-run');
  if (!sel) return;

  const runs = await loadRunIndex();
  if (!runs.length) {
    sel.innerHTML = '<option value="">Sin corridas archivadas</option>';
    sel.disabled = true;
    return;
  }

  sel.innerHTML = runs.map((r, i) =>
    `<option value="${r.path}"${i === 0 ? '' : ''}>
      ${r.run_name} · ${r.published_at.slice(0, 10)}
    </option>`
  ).join('');

  // Primera opción = contrato vigente (data/)
  const liveOpt = document.createElement('option');
  liveOpt.value = 'data';
  liveOpt.textContent = '⬤ Corrida vigente';
  liveOpt.selected = true;
  sel.insertBefore(liveOpt, sel.firstChild);

  sel.addEventListener('change', () => switchRun(sel.value));
}

function switchRun(path) {
  // Actualizar BASE_PATH global
  BASE_PATH = path;

  // Invalidar caché completo
  Object.keys(cache).forEach(k => delete cache[k]);

  // Resetear flags de carga de cada módulo
  Object.values(reloadFlags).forEach(f => { f.loaded = false; });

  // Actualizar footer
  loadJSON(DATA.runManifest()).then(m => {
    if (m?.run_name) {
      document.getElementById('footer-run').textContent =
        `Run: ${m.run_name}  ·  ${m.published_at ?? ''}`;
    }
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
        `Run: ${m.run_name}  ·  ${m.published_at ?? ''}`;
    }
  });

  // Poblar selector de corridas
  populateRunSelector();

  // Vista inicial
  activateView('dashboard');
});
