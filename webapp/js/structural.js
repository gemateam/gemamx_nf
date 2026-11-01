/**
 * structural.js — visores PDBe Molstar WT/MUT, métricas, RMSD por región
 *
 * Usa el Web Component <pdbe-molstar> en lugar del JS Plugin para evitar
 * el warning "Symbol already added" que ocurre con múltiples instancias
 * del plugin JS en la misma página.
 *
 * Carga de estructura: se actualiza el atributo custom-data-url del elemento
 * <pdbe-molstar> y el componente se re-renderiza automáticamente.
 */
import { DATA, loadJSON, fmt, registerLoader, registerReloadFlag } from './app.js';

const state = { loaded: false };
registerReloadFlag('structural', state);

// ── Cargar estructura en un visor iframe ─────────────────────────────────
// Cada iframe corre su propia instancia de Molstar en contexto aislado,
// eliminando la colisión del registro global de símbolos.
function loadStructure(viewerId, structPath, mutPos) {
  const iframe = document.getElementById(viewerId);
  if (!iframe || !structPath) return;

  const format = structPath.endsWith('.cif') ? 'mmcif' : 'pdb';

  // Convertir la ruta relativa a URL absoluta para postMessage cross-origin
  const absoluteUrl = new URL(structPath, window.location.href).href;

  const send = () => iframe.contentWindow?.postMessage(
    { type: 'loadStructure', url: absoluteUrl, format, mutPos: mutPos ?? null },
    window.location.origin
  );

  // Si el iframe ya cargó su documento, enviar de inmediato; si no, esperar load
  if (iframe.contentDocument?.readyState === 'complete') {
    send();
  } else {
    iframe.addEventListener('load', send, { once: true });
  }
}

// ── Parsear posición del residuo mutado en el modelo ─────────────────────
function modelMutPos(variantId, metrics) {
  // Usar mutation_resseq_model del contrato si existe (numeración del modelo)
  return metrics?.[variantId]?.mutation_resseq_model ?? null;
}

// ── Renderizar métricas inline ─────────────────────────────────────────────
function renderMetrics(variantId, metrics) {
  const m = metrics?.[variantId] ?? {};
  const el = document.getElementById('metrics-inline');
  el.innerHTML = [
    { label: 'pLDDT WT',                  value: fmt(m.wt_plddt) },
    { label: 'pLDDT MUT',                 value: fmt(m.mut_plddt) },
    { label: 'RMSD global (Å)',            value: fmt(m.rmsd_global) },
    { label: 'RMSD sitio activo (Å)',      value: fmt(m.rmsd_active) },
    { label: 'Mejor fármaco',              value: m.best_vina_drug ?? '—' },
    { label: 'Afinidad (kcal/mol)',        value: fmt(m.best_vina_score, 3) },
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
function onVariantChange(variantId, manifest, metrics) {
  const wtKey  = variantId.split('_')[0] + '_WT';
  const wtPath  = manifest?.[wtKey]       ?? null;
  const mutPath = manifest?.[variantId]   ?? null;
  const pos     = modelMutPos(variantId, metrics);

  renderMetrics(variantId, metrics);
  renderRMSD(variantId, metrics);
  loadStructure('viewer-wt',  wtPath,  null);
  loadStructure('viewer-mut', mutPath, pos);
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

  const sel = document.getElementById('sel-variant');
  const available = (variants ?? []).filter(v => manifest?.[`${v.hugo_symbol}_${v.protein_change}`]);

  if (!available.length) {
    sel.innerHTML = '<option>Sin estructuras disponibles</option>';
    return;
  }

  sel.innerHTML = available.map(v =>
    `<option value="${v.hugo_symbol}_${v.protein_change}">
      ${v.hugo_symbol} ${v.protein_change}
    </option>`).join('');

  // Registrar listener solo una vez
  if (!sel.dataset.listenerAttached) {
    sel.addEventListener('change', () => onVariantChange(sel.value, manifest, metrics));
    sel.dataset.listenerAttached = 'true';
  }

  // Cargar primera variante
  onVariantChange(sel.value, manifest, metrics);
}

registerLoader('structural', loadStructural);
