/**
 * clinical.js — Vista Clínico (exclusiva pipeline v2 Romero)
 *
 * Datos:
 *   clinical_metadata.json       → perfil clínico por muestra (IHC, PAM50, TNM, edad)
 *   variant_clinical_summary.json → distribuciones clínicas por variante
 *   romero_geo_summary.json       → metadatos de datasets GEO asociados
 *   top_variants.json             → clasificación y frecuencia
 */
import {
  DATA, loadJSON, fmt, badgeClass, PLOTLY_LAYOUT,
  registerLoader, registerReloadFlag,
} from './app.js';

const state = { loaded: false };
registerReloadFlag('clinical', state);

// ── Helpers ────────────────────────────────────────────────────────────────
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val ?? '—';
}

function pct(n, total) {
  if (!total) return '—';
  return `${((n / total) * 100).toFixed(1)}%`;
}

// ── KPIs desde clinical_metadata ──────────────────────────────────────────
function renderKPIs(clinical) {
  const total   = clinical.length;
  const withWES = clinical.filter(c => c.mutation_wes === 'Yes').length;
  const ages    = clinical.map(c => c.age).filter(a => a != null && !isNaN(a));
  const avgAge  = ages.length ? (ages.reduce((s, a) => s + a, 0) / ages.length).toFixed(1) : '—';
  const lumaCnt = clinical.filter(c =>
    (c.ihc_subtype ?? '').toLowerCase().includes('luminal a') ||
    (c.pam50 ?? '').toLowerCase() === 'luma'
  ).length;

  setText('cl-kpi-samples', total);
  setText('cl-kpi-wes',     withWES);
  setText('cl-kpi-age',     avgAge);
  setText('cl-kpi-luma',    total ? `${((lumaCnt / total) * 100).toFixed(0)}%` : '—');
}

// ── Gráfica distribución IHC ───────────────────────────────────────────────
function renderIHCChart(clinical) {
  const dist = {};
  clinical.forEach(c => {
    const k = c.ihc_subtype ?? 'Desconocido';
    dist[k] = (dist[k] ?? 0) + 1;
  });
  const sorted = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  Plotly.newPlot('chart-ihc-dist', [{
    type: 'bar',
    x: sorted.map(([k]) => k),
    y: sorted.map(([, v]) => v),
    marker: { color: '#14b8a6' },
    hovertemplate: '<b>%{x}</b><br>%{y} muestras<extra></extra>',
  }], {
    ...PLOTLY_LAYOUT, height: 280,
    xaxis: { tickangle: -30, color: '#94a3b8' },
    yaxis: { title: 'Muestras', color: '#94a3b8', gridcolor: '#334155' },
  }, { responsive: true, displayModeBar: false });
}

// ── Gráfica distribución PAM50 ─────────────────────────────────────────────
function renderPAM50Chart(clinical) {
  const dist = {};
  clinical.forEach(c => {
    const k = c.pam50 ?? 'N/D';
    dist[k] = (dist[k] ?? 0) + 1;
  });
  const sorted = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  Plotly.newPlot('chart-pam50-dist', [{
    type: 'pie',
    labels: sorted.map(([k]) => k),
    values: sorted.map(([, v]) => v),
    hole: 0.42,
    textinfo: 'label+percent',
    hovertemplate: '<b>%{label}</b><br>%{value} muestras<extra></extra>',
    marker: { colors: ['#14b8a6','#60a5fa','#f87171','#fbbf24','#a78bfa','#94a3b8'] },
  }], {
    ...PLOTLY_LAYOUT, height: 280, showlegend: false,
  }, { responsive: true, displayModeBar: false });
}

// ── Bloque de datasets GEO ────────────────────────────────────────────────
function renderGEO(geoSummary) {
  const grid = document.getElementById('geo-datasets-grid');
  if (!grid || !geoSummary?.datasets) return;

  const datasets = Object.values(geoSummary.datasets);
  grid.innerHTML = `<div class="geo-grid">` + datasets.map(ds => `
    <div class="geo-card">
      <div class="geo-id">
        <a href="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=${ds.dataset}"
           target="_blank" rel="noopener" class="geo-link">${ds.dataset}</a>
        <span class="geo-kind-badge geo-kind--${ds.omics_kind}">${ds.omics_kind}</span>
      </div>
      <div class="geo-title">${ds.series_title}</div>
      <div class="geo-meta">
        <span>${ds.sample_count} muestras</span>
        <span>${ds.platform_manufacturer ?? ''} · ${Array.isArray(ds.platform_id) ? ds.platform_id.join(', ') : ds.platform_id}</span>
        ${ds.pubmed_id ? `<a href="https://pubmed.ncbi.nlm.nih.gov/${ds.pubmed_id}/" target="_blank" rel="noopener" class="geo-link">PubMed ${ds.pubmed_id}</a>` : ''}
      </div>
      ${ds.inferred_subtype_counts && ds.omics_kind !== 'cnv'
        ? `<div class="geo-subtypes">${
            Object.entries(ds.inferred_subtype_counts)
              .filter(([k]) => k !== 'UNK')
              .map(([k, v]) => `<span class="geo-subtype-chip">${k}: ${v}</span>`)
              .join('')
          }</div>`
        : ''}
    </div>`).join('') + `</div>`;
}

// ── Tabla variante × clínico ───────────────────────────────────────────────
let _allClinicalRows = [];

function renderClinicalTable(rows) {
  const tbody = document.getElementById('tbody-clinical');
  if (!tbody) return;

  tbody.innerHTML = rows.map(v => {
    const badge = v.classification
      ? `<span class="badge ${badgeClass(v.classification)}">${v.classification}</span>`
      : '—';

    const ageStr = v.age?.mean != null
      ? `${v.age.mean.toFixed(0)} (${v.age.min}–${v.age.max})`
      : '—';

    return `
      <tr>
        <td><strong>${v.hugo_symbol}</strong> <span style="font-family:monospace;font-size:.82rem">${v.protein_change}</span></td>
        <td>${v.sample_count ?? '—'}</td>
        <td>${v.matched_clinical_count ?? '—'}</td>
        <td>${ageStr}</td>
        <td>${v.highlights?.top_ihc_subtype ?? '—'}</td>
        <td>${v.highlights?.top_pam50 ?? '—'}</td>
        <td>${v.highlights?.top_histology ?? v.histology_distribution ? Object.keys(v.histology_distribution ?? {})[0] ?? '—' : '—'}</td>
        <td>${badge}</td>
      </tr>`;
  }).join('');
}

// ── Loader principal ──────────────────────────────────────────────────────
async function loadClinical() {
  if (state.loaded) return;
  state.loaded = true;

  const [clinical, variantSummary, geoSummary, topVariants, runManifest] = await Promise.all([
    loadJSON(DATA.clinicalMetadata()),
    loadJSON(DATA.variantClinicalSummary()),
    loadJSON(DATA.romeroGeoSummary()),
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.runManifest()),
  ]);

  if (!clinical) {
    document.getElementById('view-clinical').innerHTML +=
      '<p class="no-data" style="padding:2rem">Sin datos clínicos para esta corrida.</p>';
    return;
  }

  // Actualizar subtitle con info de la corrida
  const subtitle = document.getElementById('clinical-subtitle');
  if (subtitle && runManifest) {
    subtitle.textContent = `${runManifest.description ?? 'Análisis clínico'} · ${clinical.length} muestras`;
  }

  renderKPIs(clinical);
  renderIHCChart(clinical);
  renderPAM50Chart(clinical);
  renderGEO(geoSummary);

  // Construir filas: combinar variantSummary con topVariants para clasificación
  const topMap = new Map((topVariants ?? []).map(v => [`${v.hugo_symbol}_${v.protein_change}`, v]));
  _allClinicalRows = (variantSummary ?? []).map(vs => ({
    ...vs,
    classification: topMap.get(vs.variant_id)?.classification ?? null,
  }));

  renderClinicalTable(_allClinicalRows);

  // Filtro
  const filterEl = document.getElementById('filter-clinical-variant');
  if (filterEl && !filterEl.dataset.listenerAttached) {
    filterEl.addEventListener('input', e => {
      const q = e.target.value.toLowerCase().trim();
      renderClinicalTable(q
        ? _allClinicalRows.filter(v =>
            v.hugo_symbol?.toLowerCase().includes(q) ||
            v.protein_change?.toLowerCase().includes(q)
          )
        : _allClinicalRows
      );
    });
    filterEl.dataset.listenerAttached = 'true';
  }
}

registerLoader('clinical', loadClinical);
