/**
 * structural.js — visores PDBe Molstar WT/MUT, métricas, RMSD por región
 *
 * Usa PDBeMolstarPlugin (pdbe-molstar-plugin.js) directamente en divs,
 * igual que la versión GEMAMXST que funciona. El plugin se carga una vez
 * en index.html y las tres instancias (wt, mut, docking) comparten el mismo
 * registro de símbolos — los warnings "already added" se suprimen abajo.
 */
import { DATA, loadJSON, fmt, registerLoader, registerReloadFlag } from './app.js';

// Suprimir warnings internos de múltiples instancias
const _origWarn  = console.warn;
const _origError = console.error;
const _skip = ['already added. Call removeSymbol', 'Invalid PDBeMolstarPlugin'];
console.warn  = (...a) => { if (typeof a[0] === 'string' && _skip.some(s => a[0].includes(s))) return; _origWarn.apply(console, a); };
console.error = (...a) => { if (typeof a[0] === 'string' && _skip.some(s => a[0].includes(s))) return; _origError.apply(console, a); };

const state = { loaded: false };
registerReloadFlag('structural', state);

// Instancias globales de los viewers WT y MUT
let wtViewer  = null;
let mutViewer = null;
let viewersReady = false;
let viewerUpdateLock = { wt: false, mut: false };
let activeVariant = null;

// ── Esperar canvas3d de ambos viewers ──────────────────────────────────────
function waitForBothViewers(timeout = 10000) {
  return new Promise(resolve => {
    const t0 = Date.now();
    const id = setInterval(() => {
      if (wtViewer?.plugin?.canvas3d && mutViewer?.plugin?.canvas3d) {
        clearInterval(id); resolve(true);
      } else if (Date.now() - t0 > timeout) {
        clearInterval(id); resolve(false);
      }
    }, 200);
  });
}

const waitForPlugin = (plugin, timeout = 8000) => new Promise((resolve) => {
  if (plugin?.plugin?.canvas3d) { resolve(); return; }
  const t0 = Date.now();
  const id = setInterval(() => {
    if (plugin?.plugin?.canvas3d)       { clearInterval(id); resolve(); }
    else if (Date.now() - t0 > timeout) { clearInterval(id); resolve(); }
  }, 150);
});

// ── Inicializar ambos viewers (una sola vez) ───────────────────────────────
async function initViewers(manifest) {
  if (viewersReady) return true;
  if (typeof PDBeMolstarPlugin === 'undefined') {
    console.error('[Structural] PDBeMolstarPlugin no está disponible');
    return false;
  }

  const wtEl  = document.getElementById('viewer-wt');
  const mutEl = document.getElementById('viewer-mut');
  if (!wtEl || !mutEl) return false;

  // Buscar una estructura seed real para el render() inicial
  // (Molstar necesita una URL válida en el primer render)
  const keys = Object.keys(manifest ?? {});
  const seedKey = keys.find(k => k.endsWith('_WT')) ?? keys[0];
  const seedUrl = seedKey ? manifest[seedKey] : null;

  if (!seedUrl) {
    console.warn('[Structural] Sin estructura seed en el manifest');
    return false;
  }

  const seedFormat = seedUrl.endsWith('.cif') ? 'mmcif' : 'pdb';
  const cfg = {
    customData:    { url: seedUrl, format: seedFormat },
    bgColor:       { r: 10, g: 10, b: 20 },
    hideControls:  true,
    landscape:     false,
    pdbeLink:      false,
    sequencePanel: false,
  };

  try {
    wtViewer  = new PDBeMolstarPlugin();
    mutViewer = new PDBeMolstarPlugin();

    // Renderizar secuencialmente para evitar conflictos WebGL
    await wtViewer.render(wtEl,  cfg);
    await mutViewer.render(mutEl, cfg);

    viewersReady = true;
    return true;
  } catch (e) {
    console.error('[Structural] Error inicializando viewers:', e);
    wtViewer = null; mutViewer = null;
    return false;
  }
}

// ── Cargar estructura en un viewer ─────────────────────────────────────────
async function loadStructure(viewer, structPath, lockKey, mutPos) {
  if (!viewer?.visual || viewerUpdateLock[lockKey]) return;
  if (!structPath) return;

  viewerUpdateLock[lockKey] = true;
  try {
    const format = structPath.endsWith('.cif') ? 'mmcif' : 'pdb';
    await viewer.visual.update({ customData: { url: structPath, format } });

    if (mutPos != null) {
      setTimeout(async () => {
        try {
          await viewer.visual.select({
            data: [{ residue_number: mutPos, color: { r: 255, g: 100, b: 50 }, focus: true }],
            nonSelectedColor: null,
          });
        } catch (_) {}
      }, 600);
    }
  } catch (e) {
    console.warn(`[Structural] Error cargando ${structPath}:`, e);
  } finally {
    setTimeout(() => { viewerUpdateLock[lockKey] = false; }, 200);
  }
}

// ── Parsear posición del residuo mutado ────────────────────────────────────
function modelMutPos(variantId, metrics) {
  return metrics?.[variantId]?.mutation_resseq_model ?? null;
}

// ── Renderizar métricas inline ─────────────────────────────────────────────
function renderMetrics(variantId, metrics) {
  const m  = metrics?.[variantId] ?? {};
  const el = document.getElementById('metrics-inline');
  if (!el) return;
  el.innerHTML = [
    { label: 'pLDDT WT',             value: fmt(m.wt_plddt) },
    { label: 'pLDDT MUT',            value: fmt(m.mut_plddt) },
    { label: 'RMSD global (Å)',       value: fmt(m.rmsd_global) },
    { label: 'RMSD sitio activo (Å)', value: fmt(m.rmsd_active) },
    { label: 'Mejor fármaco',         value: m.best_vina_drug ?? '—' },
    { label: 'Afinidad (kcal/mol)',   value: fmt(m.best_vina_score, 3) },
  ].map(item => `
    <div class="metric-item">
      <span class="m-label">${item.label}</span>
      <span class="m-value">${item.value}</span>
    </div>`).join('');
}

// ── Renderizar barras RMSD por región ─────────────────────────────────────
function renderRMSD(variantId, metrics) {
  const m       = metrics?.[variantId] ?? {};
  const regions = m.rmsd_regions ?? [];
  const el      = document.getElementById('rmsd-regions');
  if (!el) return;

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
  activeVariant = variantId;

  renderMetrics(variantId, metrics);
  renderRMSD(variantId, metrics);

  const wtKey  = variantId.split('_')[0] + '_WT';
  const wtPath  = manifest?.[wtKey]     ?? null;
  const mutPath = manifest?.[variantId] ?? null;
  const pos     = modelMutPos(variantId, metrics);

  // Esperar canvas3d antes de cargar estructuras
  await Promise.all([
    waitForPlugin(wtViewer),
    waitForPlugin(mutViewer),
  ]);

  if (activeVariant !== variantId) return; // cambio de variante mientras cargaba

  await Promise.all([
    loadStructure(wtViewer,  wtPath,  'wt',  null),
    loadStructure(mutViewer, mutPath, 'mut', pos),
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

  const sel       = document.getElementById('sel-variant');
  const selBottom = document.getElementById('sel-variant-bottom');
  if (!sel) return;

  const available = (variants ?? []).filter(v =>
    manifest?.[`${v.hugo_symbol}_${v.protein_change}`]
  );

  if (!available.length) {
    sel.innerHTML = '<option>Sin estructuras disponibles</option>';
    if (selBottom) selBottom.innerHTML = sel.innerHTML;
    return;
  }

  const optionsHtml = available.map(v =>
    `<option value="${v.hugo_symbol}_${v.protein_change}">
      ${v.hugo_symbol} ${v.protein_change}
    </option>`).join('');

  sel.innerHTML       = optionsHtml;
  if (selBottom) selBottom.innerHTML = optionsHtml;

  // Sincronizar selectores
  const syncSelectors = (val) => {
    sel.value       = val;
    if (selBottom) selBottom.value = val;
  };

  const onChange = (val) => { syncSelectors(val); onVariantChange(val, manifest, metrics); };

  if (!sel.dataset.listenerAttached) {
    sel.addEventListener('change', () => onChange(sel.value));
    sel.dataset.listenerAttached = 'true';
  }
  if (selBottom && !selBottom.dataset.listenerAttached) {
    selBottom.addEventListener('change', () => onChange(selBottom.value));
    selBottom.dataset.listenerAttached = 'true';
  }

  // ── Botón Modo Científico ───────────────────────────────────────────────
  const sciBtn = document.getElementById('btn-scientific-mode');
  if (sciBtn && !sciBtn._bound) {
    sciBtn._bound = true;
    sciBtn.addEventListener('click', () => {
      sciBtn.dataset.active = sciBtn.dataset.active === 'true' ? 'false' : 'true';
      const on = sciBtn.dataset.active === 'true';
      sciBtn.textContent = `🔬 Modo Científico: ${on ? 'ON' : 'OFF'}`;
      sciBtn.classList.toggle('struct-action-btn--active', on);
      // pLDDT coloring cuando está ON
      const applyColor = (viewer) => {
        if (!viewer?.visual) return;
        viewer.visual.update({ visual: { color: on ? 'plddt-confidence' : 'sequence-id' } })
          .catch(() => {});
      };
      applyColor(wtViewer);
      applyColor(mutViewer);
    });
  }

  // ── Botón Superimpose WT/Mut ────────────────────────────────────────────
  let superimposed = false;
  const supBtn = document.getElementById('btn-superimpose');
  if (supBtn && !supBtn._bound) {
    supBtn._bound = true;
    supBtn.addEventListener('click', async () => {
      superimposed = !superimposed;
      supBtn.classList.toggle('struct-action-btn--active', superimposed);
      supBtn.textContent = superimposed ? '⧗ Superimpose: ON' : '⧗ Superimpose WT/Mut';

      const variantId = sel.value;
      if (!variantId) return;

      const wtKey = variantId.split('_')[0] + '_WT';
      const wtPath = manifest?.[wtKey] ?? null;
      const mutPath = manifest?.[variantId] ?? null;

      if (superimposed) {
        // Cargar WT en ambos viewers para comparación visual
        if (wtPath) {
          await Promise.all([
            loadStructure(wtViewer,  wtPath, 'wt',  null),
            loadStructure(mutViewer, wtPath, 'mut', null),
          ]);
        }
      } else {
        // Restaurar WT y MUT normales
        const pos = modelMutPos(variantId, metrics);
        await Promise.all([
          loadStructure(wtViewer,  wtPath,  'wt',  null),
          loadStructure(mutViewer, mutPath, 'mut', pos),
        ]);
      }
    });
  }

  // ── Botón Continue to Docking ───────────────────────────────────────────
  const dockingBtn = document.getElementById('btn-continue-docking');
  if (dockingBtn && !dockingBtn._bound) {
    dockingBtn._bound = true;
    dockingBtn.addEventListener('click', () => {
      // Pasar la variante activa al selector de docking
      const activeVariantId = sel.value;
      if (activeVariantId) {
        const dockingSel = document.getElementById('sel-docking-variant');
        if (dockingSel) {
          dockingSel.value = activeVariantId;
          dockingSel.dispatchEvent(new Event('change'));
        }
      }
      // Navegar a la vista docking
      document.querySelector('[data-view="docking"]')?.click();
    });
  }

  // Inicializar viewers
  const ok = await initViewers(manifest);
  if (!ok) {
    document.getElementById('viewer-wt')?.insertAdjacentHTML('afterbegin',
      '<p style="color:#94a3b8;padding:1rem;">Error iniciando Molstar.</p>');
    return;
  }

  await waitForBothViewers(10000);
  onVariantChange(sel.value, manifest, metrics);
}

registerLoader('structural', loadStructural);
