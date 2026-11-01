/**
 * explore.js — Exploración TCGA
 *
 * Construye la tabla completa de variantes a partir de:
 *   raw_mutations.json  → todas las ocurrencias por muestra
 *   top_variants.json   → variantes priorizadas con clasificación y rank
 *   manifest_structures.json → qué estructuras WT/MUT están disponibles
 *   structural_metrics.json  → pLDDT y scores para tooltip/badge
 *
 * Está ligada al experimento/corrida activo (BASE_PATH).
 * Al pulsar WT o MUT navega a Estructuras 3D con la variante pre-seleccionada.
 */
import {
  DATA, loadJSON, fmt, registerLoader, registerReloadFlag,
} from './app.js';

const state = { loaded: false };
registerReloadFlag('explore', state);

// Clasificación → clase CSS badge
function clsBadge(cls) {
  if (!cls) return 'badge-hotspot';
  const c = cls.toLowerCase();
  if (c.includes('patog')) return 'badge-patogenica';
  if (c.includes('hotspot')) return 'badge-hotspot';
  if (c.includes('vus'))     return 'badge-vus';
  if (c.includes('baja'))    return 'badge-baja';
  return 'badge-hotspot';
}

// Clasificación → texto limpio (decodifica caracteres mal codificados)
function clsLabel(cls) {
  if (!cls) return '—';
  return cls
    .replace('PatogÃ©nica', 'Patogénica')
    .replace('patogÃ©nica', 'patogénica');
}

// Barra de frecuencia proporcional al máximo
function freqBar(freq, maxFreq) {
  const pct = maxFreq > 0 ? Math.min((freq / maxFreq) * 100, 100) : 0;
  const color = pct > 50 ? 'var(--teal-light)' : pct > 20 ? '#60a5fa' : '#475569';
  return `
    <div class="exp-freq-cell">
      <div class="exp-freq-bar-track">
        <div class="exp-freq-bar-fill" style="width:${pct}%;background:${color};"></div>
      </div>
      <span class="exp-freq-num">${freq}</span>
    </div>`;
}

// Posición genómica formateada
function genomicPos(chr, pos) {
  if (!chr || chr === '?' || !pos || pos === 0) return 'Chr?:0';
  return `Chr${chr}:${Number(pos).toLocaleString('en-US')}`;
}

// ── Construir tabla completa desde raw_mutations ───────────────────────────
function buildVariantTable(rawMutations, topVariants, manifest, metrics) {
  // Agregar raw_mutations por (hugo_symbol + protein_change)
  const aggMap = new Map();
  (rawMutations ?? []).forEach(m => {
    const key = `${m.hugo_symbol}_${m.protein_change}`;
    if (!aggMap.has(key)) {
      aggMap.set(key, {
        hugo_symbol:     m.hugo_symbol,
        protein_change:  m.protein_change,
        chromosome:      m.chromosome,
        start_position:  m.start_position,
        frequency:       0,
        samples:         new Set(),
      });
    }
    const entry = aggMap.get(key);
    entry.frequency++;
    entry.samples.add(m.sample_id);
    // Usar la posición más reciente no-cero
    if (m.start_position && m.start_position !== 0) {
      entry.start_position = m.start_position;
      entry.chromosome     = m.chromosome;
    }
  });

  // Mapa de variantes priorizadas por key
  const topMap = new Map();
  (topVariants ?? []).forEach(v => {
    topMap.set(`${v.hugo_symbol}_${v.protein_change}`, v);
  });

  // Combinar y enriquecer
  const totalSamples = new Set(
    (rawMutations ?? []).map(m => m.sample_id)
  ).size || 1;

  const rows = Array.from(aggMap.values()).map((entry, idx) => {
    const key     = `${entry.hugo_symbol}_${entry.protein_change}`;
    const topData = topMap.get(key) ?? {};
    const metricM = metrics?.[key] ?? {};
    const gene    = key.split('_')[0];
    const wtKeyV1 = `${gene}_WT`;
    const wtKeyV2 = `WT__${key}`;
    const hasWT   = !!(manifest?.[wtKeyV2] ?? manifest?.[wtKeyV1]);
    const hasMUT  = !!(manifest?.[key]);

    return {
      key,
      hugo_symbol:    entry.hugo_symbol,
      protein_change: entry.protein_change,
      chromosome:     entry.chromosome,
      start_position: entry.start_position,
      frequency:      entry.frequency,
      cohort_pct:     (entry.frequency / totalSamples) * 100,
      classification: topData.classification ?? 'Hotspot',
      rank:           topData.rank ?? (idx + 1),
      hasWT,
      hasMUT,
      wt_plddt:       metricM.wt_plddt ?? null,
      mut_plddt:      metricM.mut_plddt ?? null,
      best_drug:      metricM.best_vina_drug ?? null,
      best_score:     metricM.best_vina_score ?? null,
    };
  });

  // Ordenar: primero las priorizadas (tienen rank), luego por frecuencia
  rows.sort((a, b) => {
    const aInTop = topMap.has(a.key) ? 0 : 1;
    const bInTop = topMap.has(b.key) ? 0 : 1;
    if (aInTop !== bInTop) return aInTop - bInTop;
    return b.frequency - a.frequency;
  });

  return rows;
}

// ── Renderizar filas ──────────────────────────────────────────────────────
let _allRows = [];
let _maxFreq = 1;
let _totalRows = 0;

function renderRows(rows) {
  const tbody = document.getElementById('exp-tbody');
  const badge = document.getElementById('exp-count-badge');
  if (!tbody) return;

  if (badge) badge.textContent = `MOSTRANDO: ${rows.length} / ${_totalRows}`;

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="no-data">Sin variantes para los filtros aplicados.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map((v, idx) => {
    const cls    = clsLabel(v.classification);
    const badgeCls = clsBadge(v.classification);
    const gPos   = genomicPos(v.chromosome, v.start_position);
    const pct    = v.cohort_pct.toFixed(1);

    // Botones WT / MUT
    const wtBtn  = v.hasWT
      ? `<button class="exp-struct-btn exp-struct-btn--wt"
            data-variant-key="${v.key}" data-struct-type="wt"
            title="Ver estructura Wild-Type de ${v.hugo_symbol}">WT</button>`
      : `<button class="exp-struct-btn exp-struct-btn--disabled" disabled title="Sin estructura WT">WT</button>`;

    const mutBtn = v.hasMUT
      ? `<button class="exp-struct-btn exp-struct-btn--mut"
            data-variant-key="${v.key}" data-struct-type="mut"
            title="Ver estructura Mutada de ${v.hugo_symbol} ${v.protein_change}">MUT</button>`
      : `<button class="exp-struct-btn exp-struct-btn--disabled" disabled title="Sin estructura MUT">MUT</button>`;

    // Tooltip con métricas si existen
    const metricTip = v.wt_plddt
      ? `title="pLDDT WT: ${v.wt_plddt} · MUT: ${v.mut_plddt ?? '—'} · Best: ${v.best_drug ?? '—'} ${v.best_score ? v.best_score + ' kcal/mol' : ''}"`
      : '';

    return `
      <tr class="exp-row" ${metricTip}>
        <td class="exp-rank">${v.rank}</td>
        <td>
          <span class="exp-gene-badge"
                style="background:${geneColor(v.hugo_symbol)}22;color:${geneColor(v.hugo_symbol)};border-color:${geneColor(v.hugo_symbol)}55;">
            ${v.hugo_symbol}
          </span>
        </td>
        <td class="exp-mono">${v.protein_change}</td>
        <td>${freqBar(v.frequency, _maxFreq)}</td>
        <td class="exp-pct">${pct}%</td>
        <td class="exp-mono exp-pos">${gPos}</td>
        <td><span class="badge ${badgeCls}">${cls}</span></td>
        <td class="exp-struct-btns">${wtBtn}${mutBtn}</td>
      </tr>`;
  }).join('');
}

// Colores por gen (consistente con la imagen de referencia)
const GENE_COLORS = {
  PIK3CA: '#38bdf8', TP53:   '#f87171', ERBB2:  '#60a5fa',
  BRCA1:  '#a78bfa', BRCA2:  '#e879f9', CDH1:   '#34d399',
  PTEN:   '#fbbf24', AKT1:   '#fb923c', RB1:    '#94a3b8',
  GATA3:  '#4ade80', MAP3K1: '#f472b6', ARID1A: '#c084fc',
  SF3B1:  '#67e8f9', KMT2C:  '#86efac', CBFB:   '#fda4af',
};
function geneColor(gene) {
  return GENE_COLORS[gene] ?? '#94a3b8';
}

// ── Filtrado reactivo ─────────────────────────────────────────────────────
function applyFilters() {
  const geneQ    = (document.getElementById('exp-search-gene')?.value   ?? '').toLowerCase().trim();
  const variantQ = (document.getElementById('exp-search-variant')?.value ?? '').toLowerCase().trim();
  const classQ   = (document.getElementById('exp-filter-class')?.value   ?? '').toLowerCase();

  const filtered = _allRows.filter(v => {
    if (geneQ    && !v.hugo_symbol.toLowerCase().includes(geneQ))       return false;
    if (variantQ && !v.protein_change.toLowerCase().includes(variantQ)) return false;
    if (classQ) {
      const cls = v.classification?.toLowerCase() ?? '';
      if (classQ === 'patog'    && !cls.includes('patog'))   return false;
      if (classQ === 'hotspot'  && !cls.includes('hotspot')) return false;
      if (classQ === 'vus'      && !cls.includes('vus'))     return false;
      if (classQ === 'baja'     && !cls.includes('baja'))    return false;
    }
    return true;
  });

  renderRows(filtered);
}

// ── Navegación al visor estructural ───────────────────────────────────────
function handleStructClick(e) {
  const btn = e.target.closest('[data-variant-key]');
  if (!btn || btn.disabled) return;

  const variantKey = btn.dataset.variantKey;
  const structType = btn.dataset.structType; // 'wt' | 'mut'

  // Pre-seleccionar variante en el selector estructural
  const selVariant = document.getElementById('sel-variant');
  if (selVariant) {
    selVariant.value = variantKey;
    selVariant.dispatchEvent(new Event('change'));
  }

  // También sincronizar selector inferior si existe
  const selBottom = document.getElementById('sel-variant-bottom');
  if (selBottom) {
    selBottom.value = variantKey;
  }

  // Navegar a la vista estructural
  document.querySelector('[data-view="structural"]')?.click();
}

// ── Loader principal ──────────────────────────────────────────────────────
async function loadExplore() {
  if (state.loaded) return;
  state.loaded = true;

  const [rawMutations, topVariants, manifest, metrics, runManifest] = await Promise.all([
    loadJSON(DATA.rawMutations()),
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.manifestStructures()),
    loadJSON(DATA.structuralMetrics()),
    loadJSON(DATA.runManifest()),
  ]);

  // Nota de épica con datos reales del pipeline
  const epicNote = document.getElementById('exp-epic-note');
  if (epicNote) {
    const totalSamples = new Set((rawMutations ?? []).map(m => m.sample_id)).size;
    const study        = runManifest?.params?.study_id?.toUpperCase() ?? 'TCGA-BRCA';
    const genes        = (runManifest?.params?.genes ?? '').split(',').length;
    epicNote.textContent =
      `Épica 1: Ingesta de ${totalSamples} muestras (${study}), ` +
      `${genes} genes analizados · pipeline ${runManifest?.params?.mlflow_experiment ?? ''} ` +
      `· run: ${runManifest?.run_name ?? ''}`;
  }

  // Construir tabla
  _allRows   = buildVariantTable(rawMutations, topVariants, manifest, metrics);
  _maxFreq   = Math.max(..._allRows.map(r => r.frequency), 1);
  _totalRows = _allRows.length;

  renderRows(_allRows);

  // Actualizar badge inicial
  const badge = document.getElementById('exp-count-badge');
  if (badge) badge.textContent = `MOSTRANDO: ${_allRows.length} / ${_allRows.length}`;

  // Listeners de filtros (una sola vez)
  const filterIds = ['exp-search-gene', 'exp-search-variant', 'exp-filter-class'];
  filterIds.forEach(id => {
    const el = document.getElementById(id);
    if (el && !el.dataset.listenerAttached) {
      el.addEventListener('input',  applyFilters);
      el.addEventListener('change', applyFilters);
      el.dataset.listenerAttached = 'true';
    }
  });

  // Listener de clicks en botones WT/MUT (delegado en tbody)
  const tbody = document.getElementById('exp-tbody');
  if (tbody && !tbody.dataset.listenerAttached) {
    tbody.addEventListener('click', handleStructClick);
    tbody.dataset.listenerAttached = 'true';
  }
}

registerLoader('explore', loadExplore);
