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

// ── Etiquetas legibles para las categorías autorreportadas (TCGA) ──────────
const ETHNICITY_LABELS = {
  'HISPANIC OR LATINO': 'Hispano/Latino',
  'NOT HISPANIC OR LATINO': 'No hispano/Latino',
  'SIN DATO': 'Sin dato',
};
const RACE_LABELS = {
  'WHITE': 'Blanca',
  'BLACK OR AFRICAN AMERICAN': 'Negra/Afroamericana',
  'ASIAN': 'Asiática',
  'AMERICAN INDIAN OR ALASKA NATIVE': 'Indígena americana',
  'NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER': 'Isleña del Pacífico',
  'OTHER': 'Otra',
  'SIN DATO': 'Sin dato',
};

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function hasField(rows, field) {
  return (rows ?? []).some(row => Object.prototype.hasOwnProperty.call(row, field));
}

function humanLabel(kind, raw) {
  const key = String(raw ?? 'Sin dato').trim();
  const dict = kind === 'ethnicity' ? ETHNICITY_LABELS : RACE_LABELS;
  return dict[key.toUpperCase()] ?? key;
}

function distribution(rows, field) {
  const counts = new Map();
  (rows ?? []).forEach(row => {
    const raw = row?.[field];
    const label = raw == null || String(raw).trim() === '' ? 'Sin dato' : String(raw).trim();
    counts.set(label, (counts.get(label) ?? 0) + 1);
  });
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

function pct(n, total) {
  return total ? `${((n / total) * 100).toFixed(1)}%` : '—';
}

// Celda con la distribución completa de una variante; las celdas pequeñas se
// marcan con * y en ámbar, sin eliminar el conteo.
function distributionCell(dist, kind, row) {
  if (!dist || !Object.keys(dist).length) return '—';
  const threshold = row.small_cell_threshold ?? 5;
  const items = Object.entries(dist)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([label, count]) => {
      const dimension = kind === 'ethnicity' ? 'ethnicity' : 'race';
      const small = (row.small_cells ?? []).includes(`${dimension}:${label}`) || count < threshold;
      const mark = small ? '*' : '';
      return `<span class="dist-item${small ? ' dist-item--small' : ''}"
          title="${esc(label)}: ${count} muestras${small ? ` (n < ${threshold})` : ''}">${esc(humanLabel(kind, label))} <span class="dist-n">${count}${mark}</span></span>`;
    });
  return `<div class="dist-cell">${items.join('')}</div>`;
}

// Barras horizontales de una distribución categórica; las celdas con n bajo
// umbral se pintan en gris y con asterisco, sin eliminar el conteo.
function renderCategoryChart(elementId, entries, kind, threshold) {
  const el = document.getElementById(elementId);
  if (!el) return;
  if (!entries.length) {
    el.innerHTML = '<p class="no-data">Sin datos.</p>';
    return;
  }
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  const ordered = [...entries].reverse(); // mayor arriba en barras horizontales
  const values = ordered.map(([, value]) => value);
  Plotly.newPlot(elementId, [{
    type: 'bar',
    orientation: 'h',
    x: values,
    y: ordered.map(([raw]) => humanLabel(kind, raw)),
    marker: { color: values.map(value => value < threshold ? '#64748b' : '#14b8a6') },
    text: values.map(value => `${value} (${((value / total) * 100).toFixed(1)}%)` +
      (value < threshold ? ' *' : '')),
    textposition: 'outside',
    textfont: { color: '#94a3b8', size: 11 },
    hovertemplate: '<b>%{y}</b><br>%{x:,} muestras<extra></extra>',
    cliponaxis: false,
  }], {
    ...PLOTLY_LAYOUT,
    height: 250,
    margin: { l: 155, r: 75, t: 15, b: 40 },
    xaxis: { title: 'Muestras', color: '#94a3b8', gridcolor: '#334155' },
    yaxis: { color: '#94a3b8', tickfont: { size: 11 } },
    showlegend: false,
  }, { responsive: true, displayModeBar: false });
}

async function loadAnalysis() {
  if (state.loaded) return;
  state.loaded = true;

  const [stats, clinical, variantSummary, geoSummary, topVariants, runManifest, contractProvenance] = await Promise.all([
    loadJSON(DATA.mutationStats()),
    loadJSON(DATA.clinicalMetadata()),
    loadJSON(DATA.variantClinicalSummary()),
    loadJSON(DATA.romeroGeoSummary()),
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.runManifest()),
    loadJSON(DATA.contractProvenance()),
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
  const cohortUnit = stats?.cohort_unit === 'patient' ? 'pacientes' : 'muestras';
  const statsItems = [
    { label: `Total ${cohortUnit}`, value: (stats?.total_samples ?? '—').toLocaleString() },
    ...(stats?.cohort_units_with_mutations != null ? [{
      label: `${cohortUnit[0].toUpperCase()}${cohortUnit.slice(1)} con mutaciones`,
      value: `${stats.cohort_units_with_mutations} / ${stats.total_samples}`,
    }] : []),
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
  const demographicsGrid = document.getElementById('clinical-demographics-grid');

  const hasClinical = Array.isArray(clinical) && clinical.length > 0;

  const toggleBlock = (el, visible) => {
    if (el) el.style.display = visible ? 'block' : 'none';
  };
  const toggleColumns = (selector, visible) => {
    document.querySelectorAll(selector).forEach(el => {
      el.style.display = visible ? '' : 'none';
    });
  };

  if (hasClinical) {
    if (clinicalKpiGrid) clinicalKpiGrid.style.display = 'grid';
    if (clinicalSection) clinicalSection.style.display = 'block';

    // Qué perfiles trae realmente esta corrida (V1 TCGA vs V2 Romero).
    const hasIHC = clinical.some(c => c.ihc_subtype && String(c.ihc_subtype).trim());
    const hasPAM = clinical.some(c => c.pam50 && String(c.pam50).trim());
    const hasHistology = (variantSummary ?? []).some(v =>
      v.highlights?.top_histology ||
      (v.histology_distribution && Object.keys(v.histology_distribution).length));
    const hasEthnicity = hasField(clinical, 'ethnicity');
    const hasRace = hasField(clinical, 'race');
    const threshold = (variantSummary ?? [])
      .find(v => Number.isFinite(v?.small_cell_threshold))?.small_cell_threshold ?? 5;

    const totalSamples = clinical.length;
    const withWES = clinical.filter(c => c.mutation_wes === 'Yes').length;
    const ages = clinical.map(c => c.age).filter(a => a != null && !isNaN(a));
    const avgAge = ages.length ? (ages.reduce((s, a) => s + a, 0) / ages.length).toFixed(1) : '—';
    const lumaCnt = clinical.filter(c =>
      (c.ihc_subtype ?? '').toLowerCase().includes('luminal a') ||
      (c.pam50 ?? '').toLowerCase() === 'luma'
    ).length;

    const ethnicityEntries = hasEthnicity ? distribution(clinical, 'ethnicity') : [];
    const raceEntries = hasRace ? distribution(clinical, 'race') : [];
    const knownEthnicity = ethnicityEntries
      .filter(([label]) => label.toUpperCase() !== 'SIN DATO')
      .reduce((sum, [, value]) => sum + value, 0);
    const hispanicCount = ethnicityEntries
      .find(([label]) => label.toUpperCase() === 'HISPANIC OR LATINO')?.[1] ?? 0;
    const hasReportedEthnicity = knownEthnicity > 0;
    const highlightEl = document.getElementById('cl-kpi-highlight');

    setText('cl-kpi-samples', totalSamples);
    setText('cl-kpi-wes',     withWES);
    setText('cl-kpi-age',     `${avgAge} años`);

    // Cuarto KPI adaptativo: etnia autorreportada si existe; si no, Luminal A.
    if (hasReportedEthnicity) {
      setText('cl-kpi-highlight', pct(hispanicCount, knownEthnicity));
      setText('cl-kpi-highlight-label', 'Hispanos/Latinos (% conocido)');
      if (highlightEl) {
        highlightEl.title =
          `${hispanicCount} de ${knownEthnicity} muestras con etnia reportada; ` +
          `${totalSamples - knownEthnicity} sin dato`;
      }
    } else {
      setText('cl-kpi-highlight', pct(lumaCnt, totalSamples));
      setText('cl-kpi-highlight-label', hasIHC || hasPAM ? 'Luminal A (%)' : 'Sin subtipo');
      if (highlightEl) {
        highlightEl.title = hasIHC || hasPAM
          ? 'Muestras Luminal A / LumA sobre el total clínico'
          : 'Esta corrida no ingiere IHC ni PAM50';
      }
    }

    // ── Etnia y raza autorreportadas (V1 TCGA) ───────────────────────────
    const showDemographics = hasEthnicity || hasRace;
    if (demographicsGrid) demographicsGrid.style.display = showDemographics ? 'grid' : 'none';
    if (hasEthnicity) renderCategoryChart('chart-ethnicity-dist', ethnicityEntries,
                                          'ethnicity', threshold);
    if (hasRace) renderCategoryChart('chart-race-dist', raceEntries, 'race', threshold);

    // ── Procedencia y alcance ────────────────────────────────────────────
    const summary = variantSummary ?? [];
    const note = summary.find(v => v?.clinical_data_note)?.clinical_data_note;
    const source = summary.find(v => v?.clinical_source)?.clinical_source ||
                   clinical.find(c => c.clinical_source)?.clinical_source;
    const provenanceCard = document.getElementById('clinical-provenance-card');
    const smallCellNote = document.getElementById('clinical-small-cell-note');
    const contractLabel = document.getElementById('clinical-contract-label');
    if (note || source || contractProvenance) {
      toggleBlock(provenanceCard, true);
      setText('clinical-data-note', note ?? 'Datos clínicos de la cohorte activa.');
      setText('clinical-source-label', source ? `Fuente: ${source}` : '');
      if (contractLabel) {
        if (contractProvenance) {
          contractLabel.style.display = '';
          contractLabel.textContent =
            `Contrato ${contractProvenance.contract_version ?? '—'} · ` +
            `bundle ${contractProvenance.bundle_id ?? '—'} · ` +
            `${contractProvenance.gdc_data_release ?? 'release desconocido'} · ` +
            `alcance ${contractProvenance.mutation_scope ?? '—'} · ` +
            `origen ${contractProvenance.data_origin ?? '—'}`;
        } else {
          contractLabel.style.display = 'none';
        }
      }
      if (smallCellNote) {
        smallCellNote.style.display = '';
        smallCellNote.textContent =
          `En la tabla por variante, las categorías con n < ${threshold} se marcan ` +
          'con * y en ámbar. Los conteos no se eliminan; solo se señala que la celda es pequeña.';
      }
    } else {
      toggleBlock(provenanceCard, false);
    }

    // ── Gráficas de subtipo: solo si la corrida trae IHC / PAM50 ─────────
    const subtypeGrid = document.getElementById('clinical-subtype-grid');
    const ihcCard = document.getElementById('card-ihc-dist');
    const pamCard = document.getElementById('card-pam50-dist');
    toggleBlock(ihcCard, hasIHC);
    toggleBlock(pamCard, hasPAM);
    toggleBlock(subtypeGrid, hasIHC || hasPAM);

    if (hasIHC) {
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
    }

    if (hasPAM) {
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
    }

    // ── Datasets GEO (solo V2) ───────────────────────────────────────────
    const geoGrid = document.getElementById('geo-datasets-grid');
    const geoCard = document.getElementById('geo-datasets-card');
    const geoDatasets = geoSummary?.datasets ? Object.values(geoSummary.datasets) : [];
    toggleBlock(geoCard, geoDatasets.length > 0);
    if (geoGrid && geoDatasets.length) {
      geoGrid.innerHTML = `<div class="geo-grid">` + geoDatasets.map(ds => `
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

    // ── Tabla clínica por variante ───────────────────────────────────────
    setText('clinical-table-title', showDemographics
      ? 'Perfil clínico autorreportado por variante (TCGA-BRCA)'
      : 'Perfil Clínico por Variante (Romero-Córdoba HM)');
    toggleColumns('.col-ethnicity', hasEthnicity);
    toggleColumns('.col-race', hasRace);
    toggleColumns('.col-ihc', hasIHC);
    toggleColumns('.col-pam50', hasPAM);
    toggleColumns('.col-histology', hasHistology);

    const tbody = document.getElementById('tbody-clinical');
    if (tbody) {
      const topMap = new Map((topVariants ?? []).map(v => [`${v.hugo_symbol}_${v.protein_change}`, v]));
      const allRows = (variantSummary ?? []).map(vs => ({
        ...vs,
        classification: topMap.get(vs.variant_id)?.classification ?? null,
      }));

      const renderRows = rows => {
        tbody.innerHTML = rows.length ? rows.map(v => {
          const badge = v.classification
            ? `<span class="badge ${badgeClass(v.classification)}">${v.classification}</span>`
            : '—';
          const ageStr = v.age?.mean != null
            ? `${Number(v.age.mean).toFixed(0)} (${v.age.min}–${v.age.max})`
            : '—';
          const ethnicityCell = hasEthnicity
            ? `<td class="col-ethnicity">${distributionCell(v.ethnicity_distribution, 'ethnicity', v)}</td>`
            : '';
          const raceCell = hasRace
            ? `<td class="col-race">${distributionCell(v.race_distribution, 'race', v)}</td>`
            : '';
          const ihcCell = hasIHC
            ? `<td class="col-ihc">${v.highlights?.top_ihc_subtype ?? '—'}</td>` : '';
          const pamCell = hasPAM
            ? `<td class="col-pam50">${v.highlights?.top_pam50 ?? '—'}</td>` : '';
          const histologyCell = hasHistology
            ? `<td class="col-histology">${v.highlights?.top_histology ??
                (v.histology_distribution ? Object.keys(v.histology_distribution)[0] ?? '—' : '—')}</td>`
            : '';
          return `
            <tr>
              <td><strong>${v.hugo_symbol}</strong> <span style="font-family:monospace;font-size:.82rem">${v.protein_change}</span></td>
              <td>${v.sample_count ?? '—'}</td>
              <td>${v.matched_clinical_count ?? '—'}</td>
              <td>${ageStr}</td>
              ${ethnicityCell}
              ${raceCell}
              ${ihcCell}
              ${pamCell}
              ${histologyCell}
              <td>${badge}</td>
            </tr>`;
        }).join('') : `<tr><td colspan="10" class="no-data">Sin variantes para mostrar.</td></tr>`;
      };

      renderRows(allRows);

      // oninput reemplaza el listener para que el filtro no conserve el
      // conjunto de filas de la corrida anterior al cambiar de run.
      const filterEl = document.getElementById('filter-clinical-variant');
      if (filterEl) {
        filterEl.oninput = e => {
          const q = e.target.value.toLowerCase().trim();
          renderRows(q
            ? allRows.filter(v =>
                v.hugo_symbol?.toLowerCase().includes(q) ||
                v.protein_change?.toLowerCase().includes(q)
              )
            : allRows
          );
        };
      }
    }
  } else {
    // Si la corrida no tiene clínica (ej. V1 TCGA sin clinical_ingest), ocultar
    // el módulo clínico completo.
    if (clinicalKpiGrid) clinicalKpiGrid.style.display = 'none';
    if (clinicalSection) clinicalSection.style.display = 'none';
    if (demographicsGrid) demographicsGrid.style.display = 'none';
  }
}

registerLoader('analysis', loadAnalysis);
