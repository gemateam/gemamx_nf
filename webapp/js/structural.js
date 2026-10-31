/**
 * structural.js — visores PDBe Molstar WT/MUT, métricas, RMSD por región
 *
 * API PDBe Molstar v3.x:
 *  - render() es fire-and-forget; loadComplete se dispara solo si hay
 *    customData en render(). Se pasa la estructura inicial directamente.
 *  - Los plugins se crean una sola vez y se reutilizan en recargas
 *    (cambio de corrida) para evitar la doble inicialización de Molstar
 *    que produce "Symbol already added".
 */
import { DATA, loadJSON, fmt, registerLoader, registerReloadFlag } from './app.js';

const state = { loaded: false };
registerReloadFlag('structural', state);
let pluginWT  = null;
let pluginMUT = null;

// ── Inicializar visor y cargar estructura inicial ─────────────────────────
function createViewer(containerId, structPath) {
  const el = document.getElementById(containerId);
  if (!el) return Promise.resolve(null);

  const plugin = new PDBeMolstarPlugin();
  const format = (structPath ?? '').endsWith('.cif') ? 'mmcif' : 'pdb';

  const ready = new Promise((resolve) => {
    plugin.events.loadComplete.subscribe(() => resolve(plugin));
  });

  plugin.render(el, {
    customData:        structPath ? { url: structPath, format, binary: false } : undefined,
    bgColor:           { r: 10, g: 10, b: 20 },
    hideControls:      false,
    selectInteraction: false,
    landscape:         false,
    pdbeLink:          false,
    sequencePanel:     false,
  });

  if (!structPath) {
    return new Promise(resolve => setTimeout(() => resolve(plugin), 400));
  }
  return ready;
}

// ── Cargar/recargar estructura en un visor ya inicializado ────────────────
async function loadStructure(plugin, structPath, mutPos) {
  if (!plugin || !structPath) return;
  try {
    const format = structPath.endsWith('.cif') ? 'mmcif' : 'pdb';
    await plugin.visual.update({
      customData: { url: structPath, format, binary: false },
      bgColor:    { r: 10, g: 10, b: 20 },
    });
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
  // Usar mutation_resseq_model del contrato si existe; si no, omitir highlight
  const pos = metrics?.[variantId]?.mutation_resseq_model ?? null;

  renderMetrics(variantId, metrics);
  renderRMSD(variantId, metrics);
  await Promise.all([
    loadStructure(pluginWT,  wtPath,  null),
    loadStructure(pluginMUT, mutPath, pos),
  ]);
}

// ── Loader principal ──────────────────────────────────────────────────────
// Guard contra ejecuciones concurrentes: una Promise compartida evita que
// dos llamadas simultáneas entren antes de que la primera haga await.
let _structuralLoading = null;

async function loadStructural() {
  if (state.loaded) return;
  // Si ya hay una ejecución en curso, esperarla en lugar de lanzar otra
  if (_structuralLoading) return _structuralLoading;

  state.loaded = true;
  _structuralLoading = _doLoadStructural();
  try {
    await _structuralLoading;
  } finally {
    _structuralLoading = null;
  }
}

async function _doLoadStructural() {

  const [variants, metrics, manifest] = await Promise.all([
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.structuralMetrics()),
    loadJSON(DATA.manifestStructures()),
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

  // Paths de la primera variante
  const firstVariantId = `${available[0].hugo_symbol}_${available[0].protein_change}`;
  const firstWtKey     = available[0].hugo_symbol + '_WT';
  const firstWtPath    = manifest?.[firstWtKey]     ?? null;
  const firstMutPath   = manifest?.[firstVariantId] ?? null;

  if (pluginWT && pluginMUT) {
    // ── Recarga (cambio de corrida): plugins ya existen, solo actualizar datos
    await Promise.all([
      loadStructure(pluginWT,  firstWtPath,  null),
      loadStructure(pluginMUT, firstMutPath, mutationPos(firstVariantId)),
    ]);
  } else {
    // ── Primera carga: crear los visores con la estructura inicial en render()
    [pluginWT, pluginMUT] = await Promise.all([
      createViewer('viewer-wt',  firstWtPath),
      createViewer('viewer-mut', firstMutPath),
    ]);
    // El highlight del MUT — usar mutation_resseq_model del contrato
    const firstPos = metrics?.[firstVariantId]?.mutation_resseq_model ?? null;
    if (firstPos && pluginMUT) {
      try {
        pluginMUT.visual.select({
          data: [{ residue_number: firstPos, color: { r: 255, g: 100, b: 50 }, focus: true }],
          nonSelectedColor: null,
        });
      } catch (e) { /* highlight es decorativo — no bloquear si falla */ }
    }
  }

  renderMetrics(firstVariantId, metrics);
  renderRMSD(firstVariantId, metrics);

  // Registrar listener del selector solo la primera vez
  if (!sel.dataset.listenerAttached) {
    sel.addEventListener('change', () => onVariantChange(sel.value, manifest, metrics));
    sel.dataset.listenerAttached = 'true';
  }
}

registerLoader('structural', loadStructural);
