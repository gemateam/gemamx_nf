/**
 * structural.js — visores PDBe Molstar WT/MUT, métricas, RMSD por región
 *
 * API PDBe Molstar v3.x:
 *  - render(el, options) es fire-and-forget (no devuelve Promise).
 *    No se puede pasar moleculeId vacío; si no hay estructura inicial
 *    hay que omitir moleculeId y customData del objeto de opciones.
 *  - Para cargar/recargar una estructura se usa visual.update(), que sí
 *    devuelve Promise y se puede await.
 *  - render() dispara plugin.events.loadComplete cuando el canvas está listo.
 *    Hay que esperar ese evento antes de llamar visual.update por primera vez.
 */
import { DATA, loadJSON, fmt, registerLoader, registerReloadFlag } from './app.js';

const state = { loaded: false };
registerReloadFlag('structural', state);
let pluginWT  = null;
let pluginMUT = null;

// ── Esperar a que el visor esté listo (render es fire-and-forget en v3) ────
function waitForPlugin(plugin) {
  return new Promise((resolve) => {
    // loadComplete se dispara una vez que el canvas WebGL está inicializado.
    plugin.events.loadComplete.subscribe(() => resolve(plugin));
  });
}

// ── Inicializar un visor Molstar ───────────────────────────────────────────
// Devuelve una Promise que resuelve cuando el plugin está listo para recibir
// llamadas a visual.update().
function createViewer(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return Promise.resolve(null);

  const plugin = new PDBeMolstarPlugin();
  const ready  = waitForPlugin(plugin);

  // En v3 render() no acepta moleculeId vacío — si no hay estructura inicial
  // simplemente se omiten ambos campos (moleculeId y customData).
  plugin.render(el, {
    bgColor:          { r: 10, g: 10, b: 20 },
    hideControls:     false,
    selectInteraction: false,
    landscape:        false,
    pdbeLink:         false,
    sequencePanel:    false,
  });

  return ready;
}

// ── Cargar estructura en un visor ─────────────────────────────────────────
// plugin aquí ya es el objeto PDBeMolstarPlugin resuelto (post-render).
async function loadStructure(plugin, structPath, mutPos) {
  if (!plugin || !structPath) return;
  try {
    const format = structPath.endsWith('.cif') ? 'mmcif' : 'pdb';
    await plugin.visual.update({
      customData: { url: structPath, format, binary: false },
      bgColor:    { r: 10, g: 10, b: 20 },
    });
    // Resaltar residuo mutado si tenemos posición
    if (mutPos) {
      plugin.visual.select({
        data: [{ residue_number: mutPos, color: { r: 255, g: 100, b: 50 }, focus: true }],
        nonSelectedColor: null,
      });
    }
  } catch (e) {
    console.warn('Error loading structure:', structPath, e);
  }
}

// ── Parsear posición de la mutación desde variante ID (PIK3CA_H1047R → 1047)
function mutationPos(variantId) {
  const m = variantId.match(/_[A-Z](\d+)[A-Z]$/);
  return m ? parseInt(m[1]) : null;
}

// ── Renderizar métricas inline ─────────────────────────────────────────────
function renderMetrics(variantId, metrics) {
  const m = metrics?.[variantId] ?? {};
  const el = document.getElementById('metrics-inline');
  el.innerHTML = [
    { label: 'pLDDT WT',       value: fmt(m.wt_plddt) },
    { label: 'pLDDT MUT',      value: fmt(m.mut_plddt) },
    { label: 'RMSD global (Å)',  value: fmt(m.rmsd_global) },
    { label: 'RMSD sitio activo (Å)', value: fmt(m.rmsd_active) },
    { label: 'Mejor fármaco',   value: m.best_vina_drug ?? '—' },
    { label: 'Afinidad (kcal/mol)', value: fmt(m.best_vina_score, 3) },
  ].map(item => `
    <div class="metric-item">
      <span class="m-label">${item.label}</span>
      <span class="m-value">${item.value}</span>
    </div>`).join('');
}

// ── Renderizar barras RMSD por región ─────────────────────────────────────
function renderRMSD(variantId, metrics) {
  const m = metrics?.[variantId] ?? {};
  const regions = m.rmsd_regions ?? [];
  const el = document.getElementById('rmsd-regions');

  if (!regions.length) {
    el.innerHTML = '<p class="no-data">Sin datos de RMSD por región para esta variante.</p>';
    return;
  }

  const maxVal = Math.max(...regions.map(r => parseFloat(r.value) || 0), 0.1);
  el.innerHTML = `<div class="rmsd-bar-container">` +
    regions.map(r => {
      const val = parseFloat(r.value) || 0;
      const pct = Math.min((val / maxVal) * 100, 100);
      return `
        <div class="rmsd-bar-item">
          <div class="rmsd-bar-label">${r.region}</div>
          <div class="rmsd-bar-track">
            <div class="rmsd-bar-fill" style="width:${pct}%;background:${r.color ?? '#14b8a6'}"></div>
          </div>
          <div class="rmsd-bar-value">${val.toFixed(2)} Å</div>
        </div>`;
    }).join('') + `</div>`;
}

// ── Actualizar todo al cambiar variante ───────────────────────────────────
async function onVariantChange(variantId, manifest, metrics) {
  const wtKey  = variantId.split('_')[0] + '_WT';
  const mutKey = variantId;

  const wtPath  = manifest?.[wtKey]  ?? null;
  const mutPath = manifest?.[mutKey] ?? null;
  const pos     = mutationPos(variantId);

  renderMetrics(variantId, metrics);
  renderRMSD(variantId, metrics);
  await Promise.all([
    loadStructure(pluginWT,  wtPath,  null),
    loadStructure(pluginMUT, mutPath, pos),
  ]);
}

// ── Loader principal ──────────────────────────────────────────────────────
async function loadStructural() {
  if (state.loaded) return;
  state.loaded = true;

  const [variants, metrics, manifest] = await Promise.all([
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.structuralMetrics()),
    loadJSON(DATA.manifestStructures()),
  ]);

  // Inicializar visores y esperar a que el canvas WebGL esté listo antes de
  // intentar cargar estructuras (render() en v3 es fire-and-forget).
  [pluginWT, pluginMUT] = await Promise.all([
    createViewer('viewer-wt'),
    createViewer('viewer-mut'),
  ]);

  // Poblar selector: variantes que tienen estructura MUT disponible
  const sel = document.getElementById('sel-variant');
  const available = (variants ?? []).filter(v => {
    const key = `${v.hugo_symbol}_${v.protein_change}`;
    return manifest?.[key];
  });

  if (!available.length) {
    sel.innerHTML = '<option>Sin estructuras disponibles</option>';
    return;
  }

  sel.innerHTML = available.map(v =>
    `<option value="${v.hugo_symbol}_${v.protein_change}">
      ${v.hugo_symbol} ${v.protein_change}
    </option>`).join('');

  sel.addEventListener('change', () =>
    onVariantChange(sel.value, manifest, metrics));

  // Cargar primera variante
  onVariantChange(sel.value, manifest, metrics);
}

registerLoader('structural', loadStructural);
