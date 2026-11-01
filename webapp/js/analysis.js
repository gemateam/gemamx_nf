/**
 * analysis.js — Análisis Genómico y Perfil Clínico Integrado
 *
 * Muestra las distribuciones mutacionales de la cohorte activa, y si la
 * corrida cuenta con datos clínicos (como Romero-Córdoba 2021 HM), activa
 * e integra los KPIs clínicos, gráficos IHC/PAM50, datasets GEO y la tabla clínica.
 */
import { DATA, loadJSON, fmt, badgeClass, PLOTLY_LAYOUT, registerLoader, registerReloadFlag, isV2 } from './app.js';

const state = { loaded: false };
registerReloadFlag('analysis', state);

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val ?? '—';
}

async function loadAnalysis() {
  if (state.loaded) return;
  state.loaded = true;

  const [stats, clinical, variantSummary, geoSummary, topVariants, runManifest] = await Promise.all([
    loadJSON(DATA.mutationStats()),
    loadJSON(DATA.clinicalMetadata()),
    loadJSON(DATA.variantClinicalSummary()),
    loadJSON(DATA.romeroGeoSummary()),
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.runManifest()),
  ]);

  const statsCohortEl = document.getElementById('stats-cohort');
  if (!stats && statsCohortEl) {
    statsCohortEl.innerHTML = '<p class="no-data">No se encontraron estadísticas del cohorte.</p>';
    return;
  }

  // ── Gráfica: distribución por gen ─────────────────────────────────────
  const geneDist = stats?.gene_distribution ?? {};
  const geneEntries = Object.entries(geneDist)
    .sort((a, b) => b[1] - a[1]).slice(0, 20);

  Plotly.newPlot('chart-gene-dist', [{
    type: 'bar',
    orientation: 'h',
    x: geneEntries.map(e => e[1]).reverse(),
    y: geneEntries.map(e => e[0]).reverse(),
    marker: {
      color: geneEntries.map((_, i) => i < 5 ? '#0d9488' : '#334155').reverse(),
    },
    hovertemplate: '<b>%{y}</b>: %{x} mutaciones<extra></extra>',
  }], {
    ...PLOTLY_LAYOUT,
    height: 420,
    margin: { l: 90, r: 20, t: 20, b: 50 },
    xaxis: { title: 'Mutaciones', color: '#94a3b8', gridcolor: '#334155' },
    yaxis: { color: '#94a3b8', tickfont: { size: 11 } },
  }, { responsive: true, displayModeBar: false });

  // ── Gráfica: tipos de mutación ────────────────────────────────────────
  const typeDist = stats?.type_distribution ?? {};
  const typeEntries = Object.entries(typeDist).sort((a, b) => b[1] - a[1]);

  const typeLabels = {
    Missense_Mutation:       'Missense',
    Nonsense_Mutation:       'Nonsense',
    Frame_Shift_Del:         'Frameshift Del',
    Frame_Shift_Ins:         'Frameshift Ins',
    Splice_Site:             'Splice Site',
    Splice_Region:           'Splice Region',
    In_Frame_Del:            'In-Frame Del',
    In_Frame_Ins:            'In-Frame Ins',
    Nonstop_Mutation:        'Nonstop',
    Translation_Start_Site:  'Start Site',
  };

  Plotly.newPlot('chart-type-dist', [{
    type: 'pie',
    labels: typeEntries.map(e => typeLabels[e[0]] ?? e[0]),
    values: typeEntries.map(e => e[1]),
    hole: 0.4,
    textinfo: 'label+percent',
    hovertemplate: '<b>%{label}</b><br>%{value:,} mutaciones<extra></extra>',
    marker: {
      colors: ['#14b8a6','#60a5fa','#a78bfa','#f87171','#fbbf24',
               '#34d399','#fb923c','#e879f9','#38bdf8','#4ade80'],
    },
  }], {
    ...PLOTLY_LAYOUT,
    height: 420,
    showlegend: true,
    legend: { font: { color: '#94a3b8', size: 10 }, orientation: 'v' },
  }, { responsive: true, displayModeBar: false });

  // ── Estadísticas del cohorte ──────────────────────────────────────────
  const statsItems = [
    { label: 'Total muestras',   value: (stats?.total_samples  ?? '—').toLocaleString() },
    { label: 'Total mutaciones', value: (stats?.total_mutations ?? '—').toLocaleString() },
    { label: 'Genes analizados', value: Object.keys(geneDist).length },
    { label: 'Tipo predominante', value: typeLabels[typeEntries[0]?.[0]] ?? '—' },
    { label: 'Missense (%)',
      value: stats?.total_mutations
        ? ((typeDist.Missense_Mutation / stats.total_mutations) * 100).toFixed(1) + '%'
        : '—' },
  ];

  if (statsCohortEl) {
    statsCohortEl.innerHTML = statsItems.map(s => `
      <div class="stat-item">
        <div class="s-label">${s.label}</div>
        <div class="s-value">${s.value}</div>
      </div>`).join('');
  }

  // ── MÓDULO CLÍNICO INTEGRADO (si la corrida tiene datos clínicos) ────────
  const clinicalKpiGrid = document.getElementById('clinical-kpi-grid');
  const clinicalSection = document.getElementById('clinical-integrated-section');

  const hasClinical = Array.isArray(clinical) && clinical.length > 0;

  if (hasClinical) {
    if (clinicalKpiGrid) clinicalKpiGrid.style.display = 'grid';
    if (clinicalSection) clinicalSection.style.display = 'block';

    // KPIs
    const totalSamples = clinical.length;
    const withWES = clinical.filter(c => c.mutation_wes === 'Yes').length;
    const ages = clinical.map(c => c.age).filter(a => a != null && !isNaN(a));
    const avgAge = ages.length ? (ages.reduce((s, a) => s + a, 0) / ages.length).toFixed(1) : '—';
    const lumaCnt = clinical.filter(c =>
      (c.ihc_subtype ?? '').toLowerCase().includes('luminal a') ||
      (c.pam50 ?? '').toLowerCase() === 'luma'
    ).length;

    setText('cl-kpi-samples', totalSamples);
    setText('cl-kpi-wes',     withWES);
    setText('cl-kpi-age',     `${avgAge} años`);
    setText('cl-kpi-luma',    totalSamples ? `${((lumaCnt / totalSamples) * 100).toFixed(0)}%` : '—');

    // Gráfica IHC
    const ihcDist = {};
    clinical.forEach(c => {
      const k = c.ihc_subtype ?? 'Desconocido';
      ihcDist[k] = (ihcDist[k] ?? 0) + 1;
    });
    const ihcSorted = Object.entries(ihcDist).sort((a, b) => b[1] - a[1]);
    Plotly.newPlot('chart-ihc-dist', [{
      type: 'bar',
      x: ihcSorted.map(([k]) => k),
      y: ihcSorted.map(([, v]) => v),
      marker: { color: '#14b8a6' },
      hovertemplate: '<b>%{x}</b><br>%{y} muestras<extra></extra>',
    }], {
      ...PLOTLY_LAYOUT, height: 280,
      xaxis: { tickangle: -25, color: '#94a3b8' },
      yaxis: { title: 'Muestras', color: '#94a3b8', gridcolor: '#334155' },
    }, { responsive: true, displayModeBar: false });

    // Gráfica PAM50
    const pamDist = {};
    clinical.forEach(c => {
      const k = c.pam50 ?? 'N/D';
      pamDist[k] = (pamDist[k] ?? 0) + 1;
    });
    const pamSorted = Object.entries(pamDist).sort((a, b) => b[1] - a[1]);
    Plotly.newPlot('chart-pam50-dist', [{
      type: 'pie',
      labels: pamSorted.map(([k]) => k),
      values: pamSorted.map(([, v]) => v),
      hole: 0.42,
      textinfo: 'label+percent',
      hovertemplate: '<b>%{label}</b><br>%{value} muestras<extra></extra>',
      marker: { colors: ['#14b8a6','#60a5fa','#f87171','#fbbf24','#a78bfa','#94a3b8'] },
    }], {
      ...PLOTLY_LAYOUT, height: 280, showlegend: false,
    }, { responsive: true, displayModeBar: false });

    // Datasets GEO
    const geoGrid = document.getElementById('geo-datasets-grid');
    if (geoGrid && geoSummary?.datasets) {
      const datasets = Object.values(geoSummary.datasets);
      geoGrid.innerHTML = `<div class="geo-grid">` + datasets.map(ds => `
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

    // Tabla clínica
    const tbody = document.getElementById('tbody-clinical');
    if (tbody) {
      const topMap = new Map((topVariants ?? []).map(v => [`${v.hugo_symbol}_${v.protein_change}`, v]));
      const allRows = (variantSummary ?? []).map(vs => ({
        ...vs,
        classification: topMap.get(vs.variant_id)?.classification ?? null,
      }));

      const renderRows = rows => {
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
              <td>${v.highlights?.top_histology ?? (v.histology_distribution ? Object.keys(v.histology_distribution)[0] ?? '—' : '—')}</td>
              <td>${badge}</td>
            </tr>`;
        }).join('');
      };

      renderRows(allRows);

      const filterEl = document.getElementById('filter-clinical-variant');
      if (filterEl && !filterEl.dataset.listenerAttached) {
        filterEl.addEventListener('input', e => {
          const q = e.target.value.toLowerCase().trim();
          renderRows(q
            ? allRows.filter(v =>
                v.hugo_symbol?.toLowerCase().includes(q) ||
                v.protein_change?.toLowerCase().includes(q)
              )
            : allRows
          );
        });
        filterEl.dataset.listenerAttached = 'true';
      }
    }
  } else {
    // Si la corrida no tiene clínica (ej. V1 TCGA), ocultar sección clínica
    if (clinicalKpiGrid) clinicalKpiGrid.style.display = 'none';
    if (clinicalSection) clinicalSection.style.display = 'none';
  }
}

registerLoader('analysis', loadAnalysis);
