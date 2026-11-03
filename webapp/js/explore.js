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
  DATA, loadJSON, fmt, contractUrl, BASE_PATH, registerLoader, registerReloadFlag,
} from './app.js';
import {
  getProteinInfo, fetchProteinInfo, proteinDisplayName,
} from './proteins.js';

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

// Escape mínimo para valores que vienen de JSON
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
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

// Posición del residuo en una variante tipo «R1275Q» (numeración UniProt, la
// misma que usan los modelos AlphaFold DB de secuencia completa).
function mutationPosition(proteinChange) {
  const m = /^[A-Z*](\d+)/.exec(proteinChange ?? '');
  return m ? Number(m[1]) : null;
}

// Resolver estructura WT/MUT publicada para una variante.
// Orden WT: WT específico de la variante (V2.1) → alias canónico del gen →
// estructura WT antigua (V1/V2.0). Las rutas del contrato se reescriben para
// que funcionen también al navegar a una corrida histórica.
// Si la corrida no trae ninguna estructura del gen, se usa el modelo WT de
// AlphaFold DB descargado con bin/fetch_external_structures.py (índice `external`).
function resolveStructures(gene, proteinChange, manifest, external) {
  const key = `${gene}_${proteinChange}`;
  const wtRaw = manifest?.[`${gene}_WT_${proteinChange}`]
    ?? manifest?.[`${gene}_WT`]
    ?? manifest?.[`WT__${key}`]
    ?? null;
  const mutRaw = manifest?.[key] ?? null;
  const ext = (!wtRaw && !mutRaw) ? (external?.[gene] ?? null) : null;
  return {
    wt:  ext ? `external/${ext.file}` : contractUrl(wtRaw),
    mut: contractUrl(mutRaw),
    wtKey:  wtRaw,
    mutKey: mutRaw,
    external: ext,
  };
}

// ── Construir tabla completa desde raw_mutations ───────────────────────────
function buildVariantTable(rawMutations, topVariants, manifest, metrics, affinities, external) {
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
    const structures = resolveStructures(entry.hugo_symbol, entry.protein_change, manifest, external);

    // Docking: afinidades MUT de la variante y WT canónico del gen.
    const mutAffinity = affinities?.[key] ?? metricM.vina_scores ?? {};
    const wtAffinity  = affinities?.[`${gene}_WT`]
      ?? affinities?.[`${gene}_WT_${entry.protein_change}`]
      ?? null;

    return {
      key,
      hugo_symbol:    entry.hugo_symbol,
      protein_change: entry.protein_change,
      protein:        getProteinInfo(entry.hugo_symbol),
      chromosome:     entry.chromosome,
      start_position: entry.start_position,
      frequency:      entry.frequency,
      cohort_pct:     (entry.frequency / totalSamples) * 100,
      classification: topData.classification ?? 'Hotspot',
      rank:           topData.rank ?? (idx + 1),
      // Los botones WT/MUT de la fila navegan a Estructuras 3D, que solo conoce
      // las estructuras del pipeline: un modelo externo se ve desde «Selección».
      hasWT:          !!structures.wt && !structures.external,
      hasMUT:         !!structures.mut,
      structures,
      wt_plddt:       metricM.wt_plddt ?? structures.external?.plddt ?? null,
      mut_plddt:      metricM.mut_plddt ?? null,
      best_drug:      metricM.best_vina_drug ?? null,
      best_score:     metricM.best_vina_score ?? null,
      mut_residue:    metricM.mutation_resseq_model
                      ?? (structures.external ? mutationPosition(entry.protein_change) : null),
      docking:        { mut: mutAffinity, wt: wtAffinity },
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
    tbody.innerHTML = `<tr><td colspan="10" class="no-data">Sin variantes para los filtros aplicados.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map((v, idx) => {
    const cls    = clsLabel(v.classification);
    const badgeCls = clsBadge(v.classification);
    const gPos   = genomicPos(v.chromosome, v.start_position);
    const pct    = v.cohort_pct.toFixed(1);
    const p      = v.protein;

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
      <tr class="exp-row" data-row-key="${esc(v.key)}" ${metricTip}>
        <td class="exp-rank">${v.rank}</td>
        <td>
          <span class="exp-gene-badge"
                style="background:${geneColor(v.hugo_symbol)}22;color:${geneColor(v.hugo_symbol)};border-color:${geneColor(v.hugo_symbol)}55;">
            ${esc(v.hugo_symbol)}
          </span>
        </td>
        <td class="exp-protein-cell">
          <span class="exp-protein-name">${esc(p.name)}</span>
          ${p.type ? `<span class="exp-protein-type">${esc(p.type)}</span>` : ''}
        </td>
        <td class="exp-mono">${esc(v.protein_change)}</td>
        <td>${freqBar(v.frequency, _maxFreq)}</td>
        <td class="exp-pct">${pct}%</td>
        <td class="exp-mono exp-pos">${gPos}</td>
        <td><span class="badge ${badgeCls}">${esc(cls)}</span></td>
        <td class="exp-struct-btns">${wtBtn}${mutBtn}</td>
        <td class="exp-select-cell">
          <button class="exp-select-btn" data-select-key="${esc(v.key)}"
                  aria-expanded="false" title="Ver ficha de ${esc(p.name)} y estructura 3D">
            <span>Selección</span><span class="exp-select-caret">▾</span>
          </button>
        </td>
      </tr>`;
  }).join('');
}

// ── Ficha expandible «Selección» ──────────────────────────────────────────
let _rowsByKey = new Map();
let detailViewer = null;
let detailViewerToken = 0;
let openDetailKey = null;

function infoSections(p) {
  if (p.pending) {
    return `<div class="exp-detail-loading">Buscando información de ${esc(p.name)} en UniProt…</div>`;
  }
  if (p.unknown) {
    return `<p class="exp-detail-empty">El gen no está identificado en la anotación de esta corrida, por lo que no hay ficha de proteína disponible.</p>`;
  }
  const section = (title, text) => text
    ? `<div class="exp-detail-section"><h4>${title}</h4><p>${esc(text)}</p></div>`
    : '';
  const html = [
    section('Función', p.function),
    section('Función catalítica', p.catalytic),
    section('Regulación', p.regulation),
    section('Localización subcelular', p.localization),
    section('Relevancia en cáncer de mama', p.disease),
    section('Dominios', p.domains),
  ].join('');
  const source = p.source === 'UniProt'
    ? `<p class="exp-detail-source">Resumen recuperado de UniProt (texto original en inglés).</p>`
    : '';
  return (html || `<p class="exp-detail-empty">Sin ficha detallada disponible para este gen.</p>`) + source;
}

// ── Inhibidores (docking) dentro de la ficha ──────────────────────────────
function dockingSectionHTML(v) {
  const mut = v.docking?.mut ?? {};
  const wt  = v.docking?.wt ?? null;
  const drugs = Object.keys(mut).sort((a, b) => (mut[a] ?? 0) - (mut[b] ?? 0));
  if (!drugs.length) return '';

  const deltaCell = (mutScore, wtScore) => {
    if (mutScore == null || wtScore == null) return '<td class="exp-docking-delta">—</td>';
    const diff = mutScore - wtScore;
    const cls = diff <= -0.15 ? 'is-better' : diff >= 0.15 ? 'is-worse' : 'is-neutral';
    const sign = diff > 0 ? '+' : '';
    return `<td class="exp-docking-delta ${cls}">${sign}${diff.toFixed(2)}</td>`;
  };

  const rows = drugs.map(drug => {
    const mutScore = mut[drug];
    const wtScore  = wt?.[drug] ?? null;
    const active = v.best_drug === drug ? ' is-best' : '';
    return `
      <tr class="exp-docking-row${active}">
        <td class="exp-docking-drug">
          ${esc(drug)}${v.best_drug === drug ? ' <span class="exp-docking-best">mejor</span>' : ''}
        </td>
        <td class="exp-docking-score">${fmt(wtScore)}</td>
        <td class="exp-docking-score">${fmt(mutScore)}</td>
        ${deltaCell(mutScore, wtScore)}
        <td class="exp-docking-action">
          <button class="exp-pose-btn" data-detail-pose="${esc(drug)}"
                  title="Ver ${esc(drug)} acoplado a ${esc(v.hugo_symbol)} ${esc(v.protein_change)}">Ver 3D</button>
        </td>
      </tr>`;
  }).join('');

  const wtNote = wt
    ? 'WT canónico del gen'
    : 'sin docking de WT en esta corrida';

  return `
    <div class="exp-detail-section exp-docking">
      <h4>Inhibidores <span class="exp-section-hint">docking molecular · kcal/mol</span></h4>
      <div class="exp-docking-table-wrap">
        <table class="exp-docking-table">
          <thead>
            <tr>
              <th>Inhibidor</th>
              <th title="${wtNote}">WT</th>
              <th>MUT</th>
              <th title="MUT − WT">Δ</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <p class="exp-docking-note">
        Más negativo = mayor afinidad. Δ &lt; 0 indica que el mutante une mejor el fármaco
        (referencia: ${wtNote}). «Ver 3D» abre el complejo proteína–ligando de AutoDock Vina.
      </p>
      <button class="exp-docking-chart-btn" data-docking-chart>
        Ver gráfica WT vs MUT
      </button>
      <div class="exp-docking-chart" data-docking-chart-box hidden></div>
    </div>`;
}

function renderDockingChart(box, v) {
  if (!box || typeof Plotly === 'undefined') return;
  const mut = v.docking?.mut ?? {};
  const wt  = v.docking?.wt ?? {};
  const drugs = Object.keys(mut)
    .sort((a, b) => (mut[a] ?? 0) - (mut[b] ?? 0))
    .reverse();  // Plotly dibuja las categorías de abajo hacia arriba

  const traces = [
    {
      type: 'bar', orientation: 'h', name: 'WT',
      y: drugs, x: drugs.map(d => wt[d] ?? null),
      marker: { color: '#60a5fa' },
      hovertemplate: '<b>%{y}</b><br>WT: %{x:.2f} kcal/mol<extra></extra>',
    },
    {
      type: 'bar', orientation: 'h', name: 'MUT',
      y: drugs, x: drugs.map(d => mut[d] ?? null),
      marker: { color: '#14b8a6' },
      hovertemplate: '<b>%{y}</b><br>MUT: %{x:.2f} kcal/mol<extra></extra>',
    },
  ];

  Plotly.newPlot(box, traces, {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: '#cbd5e1', size: 10 },
    margin: { l: 92, r: 12, t: 8, b: 34 },
    barmode: 'group',
    bargap: .25,
    bargroupgap: .08,
    height: Math.max(220, drugs.length * 26 + 60),
    xaxis: {
      title: { text: 'kcal/mol', font: { size: 9 } },
      gridcolor: 'rgba(148,163,184,.15)',
      zerolinecolor: 'rgba(148,163,184,.3)',
      tickfont: { size: 9 },
    },
    yaxis: { automargin: true, tickfont: { size: 9 } },
    legend: { orientation: 'h', x: 0, y: 1.06, font: { size: 9 } },
  }, { displayModeBar: false, responsive: true });
}

function toggleDockingChart(button) {
  const detail = button.closest('.exp-detail');
  const v = _rowsByKey.get(detail?.dataset.detailKey);
  const box = detail?.querySelector('[data-docking-chart-box]');
  if (!v || !box) return;

  if (!box.hidden) {
    box.hidden = true;
    button.textContent = 'Ver gráfica WT vs MUT';
    if (typeof Plotly !== 'undefined') {
      try { Plotly.purge(box); } catch (_) { /* noop */ }
    }
    return;
  }
  box.hidden = false;
  button.textContent = 'Ocultar gráfica';
  renderDockingChart(box, v);
}

function infoPanelHTML(v, p) {
  const color = geneColor(v.hugo_symbol);
  const chips = [
    p.length ? `<span class="exp-detail-chip">${p.length} aa</span>` : '',
    p.type ? `<span class="exp-detail-chip">${esc(p.type)}</span>` : '',
    p.uniprot
      ? `<a class="exp-detail-chip exp-detail-chip--link"
            href="https://www.uniprot.org/uniprotkb/${esc(p.uniprot)}"
            target="_blank" rel="noopener">UniProt ${esc(p.uniprot)} ↗</a>`
      : '',
  ].join('');
  const best = v.best_drug
    ? `<span>Mejor fármaco <b>${esc(v.best_drug)}</b>${v.best_score ? ` · ${fmt(v.best_score)} kcal/mol` : ''}</span>`
    : '';
  const plddt = v.wt_plddt
    ? `<span>pLDDT WT <b>${fmt(v.wt_plddt)}</b> · MUT <b>${fmt(v.mut_plddt)}</b></span>`
    : '';

  return `
    <div class="exp-detail-hero">
      <span class="exp-detail-gene"
            style="background:${color}22;color:${color};border-color:${color}55;">
        ${esc(v.hugo_symbol)}
      </span>
      <div class="exp-detail-heading">
        <h3 class="exp-detail-title">${esc(p.name)}
          <span class="exp-detail-full">${esc(p.fullName)}</span>
        </h3>
        <div class="exp-detail-chips">${chips}</div>
      </div>
    </div>
    <div class="exp-detail-body">${infoSections(p)}${dockingSectionHTML(v)}</div>
    <div class="exp-detail-variant">
      <span>Variante <b class="exp-mono">${esc(v.protein_change)}</b></span>
      <span>Frecuencia <b>${v.frequency}</b> · cohorte <b>${v.cohort_pct.toFixed(1)}%</b></span>
      <span>Clasificación <b>${esc(clsLabel(v.classification))}</b></span>
      ${plddt}${best}
    </div>`;
}

function structureToggleHTML(v, activeKind) {
  const { wt, mut } = v.structures;
  if (!wt && !mut) return '';
  const btn = (kind, label, url) => url
    ? `<button class="exp-detail-struct-btn exp-detail-struct-btn--${kind}
          ${kind === activeKind ? 'is-active' : ''}"
          data-detail-struct="${kind}">${label}</button>`
    : '';
  return `<div class="exp-detail-struct-toggle">${btn('wt', 'WT', wt)}${btn('mut', 'MUT', mut)}</div>`;
}

function detailRowHTML(v) {
  const defaultKind = v.structures.wt ? 'wt' : 'mut';
  return `
    <td colspan="10">
      <div class="exp-detail" data-detail-key="${esc(v.key)}">
        <div class="exp-detail-info" data-detail-info>
          ${infoPanelHTML(v, v.protein)}
        </div>
        <div class="exp-detail-viewer">
          <div class="exp-detail-viewer-head">
            <span class="exp-detail-viewer-title">Estructura de la proteína</span>
            <div class="exp-detail-viewer-actions">
              ${structureToggleHTML(v, defaultKind)}
              <button class="exp-open-viewer-btn" data-open-viewer
                      title="Abrir el visor 3D grande con inhibidores">⤢ Visor</button>
            </div>
          </div>
          <div class="exp-molstar" data-exp-molstar></div>
          <p class="exp-detail-legend">
            ${v.structures.external
              ? `Modelo WT de AlphaFold DB (UniProt ${esc(v.structures.external.uniprot)}), coloreado arcoíris de N a C.
                 La variante ${esc(v.protein_change)} no se modeló en el pipeline: en el visor grande se marca su posición sobre el WT.`
              : `Coloreado arcoíris de N a C (azul → rojo). Abre el visor para superponer el
                 residuo mutado y probar los inhibidores acoplados.`}
          </p>
        </div>
      </div>
    </td>`;
}

function disposeDetailViewer() {
  const viewer = detailViewer;
  detailViewer = null;
  detailViewerToken++;
  if (!viewer) return;
  try { viewer.plugin?.dispose?.(); } catch (_) { /* noop */ }
  try { viewer.dispose?.(); } catch (_) { /* noop */ }
}

function closeDetail() {
  if (typeof Plotly !== 'undefined') {
    document.querySelectorAll('#exp-tbody [data-docking-chart-box]').forEach(el => {
      try { Plotly.purge(el); } catch (_) { /* noop */ }
    });
  }
  document.querySelectorAll('#exp-tbody tr.exp-detail-row').forEach(el => el.remove());
  document.querySelectorAll('#exp-tbody tr.exp-row--open').forEach(el => {
    el.classList.remove('exp-row--open');
  });
  document.querySelectorAll('#exp-tbody .exp-select-btn').forEach(btn => {
    btn.setAttribute('aria-expanded', 'false');
    btn.classList.remove('exp-select-btn--open');
    const label = btn.querySelector('span');
    if (label) label.textContent = 'Selección';
  });
  disposeDetailViewer();
  openDetailKey = null;
}

function structureFormat(url) {
  return url.endsWith('.cif') ? 'mmcif' : 'pdb';
}

// ── Arcoíris N→C ──────────────────────────────────────────────────────────
// El tema `sequence-id` de Mol* necesita metadatos de entidad que los CIF de
// ESMFold no traen, así que se colorea por tramos de residuos con
// `visual.select`. Es el mismo helper que ya usa la vista de Estructuras 3D.
function rainbowColor(t) {
  // Matiz 270° (violeta/azul) → 0° (rojo)
  const h = 270 - 270 * t;
  const s = 0.8;
  const l = 0.55;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let r = 0, g = 0, b = 0;
  if      (h < 60)  [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else              [r, g, b] = [c, 0, x];
  return {
    r: Math.round((r + m) * 255),
    g: Math.round((g + m) * 255),
    b: Math.round((b + m) * 255),
  };
}

// La jerarquía puede tardar en poblarse tras render(); esperar antes de colorear.
function structureReady(viewer) {
  const structures = viewer?.plugin?.managers?.structure?.hierarchy?.current?.structures ?? [];
  return structures.length > 0
    && (structures[0]?.cell?.obj?.data?.models?.length ?? 0) > 0;
}

async function waitForStructure(viewer, timeout = 8000) {
  const t0 = performance.now();
  while (performance.now() - t0 < timeout) {
    if (structureReady(viewer)) return true;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  return structureReady(viewer);
}

function collectResidueIds(viewer) {
  const structures = viewer?.plugin?.managers?.structure?.hierarchy?.current?.structures ?? [];
  const model = structures[0]?.cell?.obj?.data?.models?.[0];
  const residues = model?.atomicHierarchy?.residues;
  const rowCount = residues?._rowCount ?? 0;
  const ids = [];
  if (rowCount > 0 && residues?.auth_seq_id?.value) {
    const seen = new Set();
    for (let i = 0; i < rowCount; i++) {
      const id = residues.auth_seq_id.value(i);
      if (id == null || seen.has(id)) continue;
      seen.add(id);
      ids.push(id);
    }
  }
  if (!ids.length) {
    const len = model?.sequence?.byEntityKey?.[0]?.sequence?.length ?? 0;
    for (let i = 1; i <= len; i++) ids.push(i);
  }
  return ids;
}

function rainbowSelectionData(viewer) {
  const ids = collectResidueIds(viewer);
  if (!ids.length) return [];

  const bins = Math.min(24, ids.length);
  const per = Math.ceil(ids.length / bins);
  const data = [];
  for (let i = 0; i < bins; i++) {
    const start = ids[i * per];
    if (start === undefined) break;
    const end = ids[Math.min((i + 1) * per - 1, ids.length - 1)];
    data.push({
      start_residue_number: start,
      end_residue_number: end,
      color: rainbowColor(bins > 1 ? i / (bins - 1) : 0),
      focus: false,
    });
  }
  return data;
}

async function applyRainbow(viewer) {
  await waitForStructure(viewer);
  const data = rainbowSelectionData(viewer);
  if (!data.length) return;

  try {
    await viewer.visual.clearSelection?.();
    await viewer.visual.select({ data, nonSelectedColor: null });
  } catch (e) {
    console.warn('[Explore] No se pudo aplicar el coloreado arcoíris:', e);
  }
}

async function mountDetailViewer(detailTr, v, kind) {
  const container = detailTr.querySelector('[data-exp-molstar]');
  if (!container) return;

  const url = v.structures[kind];
  container.innerHTML = '';

  if (!url) {
    container.innerHTML = '<div class="exp-molstar-empty">No hay estructura 3D publicada para esta variante.</div>';
    return;
  }
  if (typeof PDBeMolstarPlugin === 'undefined') {
    container.innerHTML = '<div class="exp-molstar-empty">El visor 3D no está disponible (PDBe Mol* no cargó).</div>';
    return;
  }

  disposeDetailViewer();
  const token = detailViewerToken;
  const plugin = new PDBeMolstarPlugin();
  detailViewer = plugin;

  try {
    await plugin.render(container, {
      customData: { url, format: structureFormat(url) },
      bgColor: { r: 15, g: 23, b: 42 },
      hideControls: true,
      landscape: true,
      pdbeLink: false,
      sequencePanel: false,
      lighting: 'matte',
    });
    if (token !== detailViewerToken) return;
    await applyRainbow(plugin);
    // Ajustar la cámara al tamaño real de la celda tras el montaje
    try { await plugin.visual.reset({ camera: true }); } catch (_) { /* noop */ }
  } catch (e) {
    console.warn('[Explore] No se pudo mostrar la estructura:', e);
    if (token === detailViewerToken) {
      container.innerHTML = '<div class="exp-molstar-empty">No se pudo cargar la estructura 3D.</div>';
    }
  }
}

async function switchDetailStructure(button) {
  const detail = button.closest('.exp-detail');
  const detailTr = button.closest('tr.exp-detail-row');
  const v = _rowsByKey.get(detail?.dataset.detailKey);
  const kind = button.dataset.detailStruct;
  if (!v || !detailTr || !kind) return;

  detail.querySelectorAll('.exp-detail-struct-btn').forEach(btn => {
    btn.classList.toggle('is-active', btn === button);
  });

  const url = v.structures[kind];
  if (!url) return;

  if (detailViewer?.visual) {
    const token = detailViewerToken;
    try {
      await detailViewer.visual.update({
        customData: { url, format: structureFormat(url) },
      }, true);
      if (token !== detailViewerToken) return;
      await applyRainbow(detailViewer);
      try { await detailViewer.visual.reset({ camera: true }); } catch (_) { /* noop */ }
      return;
    } catch (e) {
      console.warn('[Explore] Falló el cambio de estructura, se recarga el visor:', e);
    }
  }
  await mountDetailViewer(detailTr, v, kind);
}

function toggleDetail(row, button) {
  const key = row.dataset.rowKey;
  if (!key) return;

  // Cerrar si ya está abierta la misma fila
  if (openDetailKey === key) {
    closeDetail();
    return;
  }
  closeDetail();

  const v = _rowsByKey.get(key);
  if (!v) return;

  const detailTr = document.createElement('tr');
  detailTr.className = 'exp-detail-row';
  detailTr.innerHTML = detailRowHTML(v);
  row.after(detailTr);

  row.classList.add('exp-row--open');
  button.setAttribute('aria-expanded', 'true');
  button.classList.add('exp-select-btn--open');
  const label = button.querySelector('span');
  if (label) label.textContent = 'Cerrar';
  openDetailKey = key;

  requestAnimationFrame(() => {
    detailTr.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
    // La tabla puede estar desplazada a la derecha (el botón «Selección» vive
    // en la última columna): devolver el scroll al inicio para que la ficha
    // no aparezca recortada por la izquierda.
    const wrapper = detailTr.closest('.explore-table-wrapper');
    if (wrapper) wrapper.scrollLeft = 0;
    mountDetailViewer(detailTr, v, v.structures.wt ? 'wt' : 'mut');
  });

  // Ficha UniProt para genes sin texto curado
  if (v.protein.pending) {
    fetchProteinInfo(v.hugo_symbol).then(info => {
      if (openDetailKey !== key) return;
      if (!info) {
        // Sin red o sin entrada revisada: se muestra una ficha mínima.
        info = { ...getProteinInfo(v.hugo_symbol), pending: false };
        info.fullName = info.fullName || v.hugo_symbol;
      }
      v.protein = info;
      const panel = detailTr.querySelector('[data-detail-info]');
      if (panel) panel.innerHTML = infoPanelHTML(v, info);
    });
  }
}

// ── Visor 3D grande (estilo «Open structure viewer») ──────────────────────
const modalState = {
  open: false,
  variantKey: null,
  model: 'mut',
  style: 'cartoon',
  target: null,          // null = estructura; { drug } = complejo con ligando
  highlightMut: true,
  highlightLigand: true,
  viewer: null,
  token: 0,
};
const modalComplexCache = new Map();

function getModalVariant() {
  return modalState.variantKey ? _rowsByKey.get(modalState.variantKey) : null;
}

async function modalHead(url) {
  if (modalComplexCache.has(url)) return modalComplexCache.get(url);
  let ok = false;
  try {
    ok = (await fetch(url, { method: 'HEAD' })).ok;
  } catch (_) {
    ok = false;
  }
  modalComplexCache.set(url, ok);
  return ok;
}

// Los complejos V2.1 se publican como <variante>_x_<fármaco>_complex.pdb; las
// corridas V1/V2.0 usan <variante>_<fármaco>_complex.pdb. Se prueban ambas.
async function resolveModalComplex(v, model, drug) {
  const variantKey = model === 'wt' ? `${v.hugo_symbol}_WT` : v.key;
  const drugSafe   = drug.replace(/ /g, '_');
  const candidates = [
    `${BASE_PATH}/docking/complex/${variantKey}_x_${drugSafe}_complex.pdb`,
    `${BASE_PATH}/docking/complex/${variantKey}_${drugSafe}_complex.pdb`,
  ];
  for (const url of candidates) {
    if (await modalHead(url)) return url;
  }
  return null;
}

function renderModalControls() {
  const v = getModalVariant();
  if (!v) return;

  const models = document.getElementById('exp-modal-models');
  if (models) {
    const btn = (kind, label) => `
      <button class="exp-modal-opt ${modalState.model === kind ? 'is-active' : ''}"
              data-modal-model="${kind}" ${v.structures[kind] ? '' : 'disabled'}
              title="Ver la estructura ${label}">${label}</button>`;
    models.innerHTML = btn('wt', 'WT') + btn('mut', 'MUT');
  }

  const styles = document.getElementById('exp-modal-styles');
  if (styles) {
    const options = [
      ['cartoon', 'Cartoon'],
      ['ball-and-stick', 'Bolas y varillas'],
      ['molecular-surface', 'Superficie'],
    ];
    styles.innerHTML = options.map(([value, label]) => `
      <button class="exp-modal-opt ${modalState.style === value ? 'is-active' : ''}"
              data-modal-style="${value}">${label}</button>`).join('');
  }

  const mutCb = document.getElementById('exp-modal-mutres');
  if (mutCb) {
    mutCb.disabled = v.mut_residue == null;
    mutCb.checked = modalState.highlightMut && v.mut_residue != null;
  }
  const ligCb = document.getElementById('exp-modal-ligand');
  if (ligCb) {
    ligCb.disabled = !modalState.target?.drug;
    ligCb.checked = modalState.highlightLigand;
  }
  const focusLig = document.querySelector('[data-modal-focus-ligand]');
  if (focusLig) focusLig.disabled = !modalState.target?.drug;
  const focusMut = document.querySelector('[data-modal-focus-mut]');
  if (focusMut) focusMut.disabled = v.mut_residue == null;
}

function renderModalInhibitors(v) {
  const box = document.getElementById('exp-modal-inhibitor-list');
  if (!box) return;

  const mut = v.docking?.mut ?? {};
  const wt  = v.docking?.wt ?? {};
  const drugs = Object.keys(mut).sort((a, b) => (mut[a] ?? 0) - (mut[b] ?? 0));
  if (!drugs.length) {
    box.innerHTML = '<p class="exp-modal-empty">Sin datos de docking para esta variante.</p>';
    return;
  }

  const activeDrug = modalState.target?.drug ?? null;
  const clear = activeDrug
    ? `<button class="exp-modal-clear" data-modal-clear-ligand>✕ Quitar ligando</button>`
    : '';

  box.innerHTML = clear + drugs.map(drug => {
    const mutScore = mut[drug];
    const wtScore  = wt[drug];
    const diff = (mutScore != null && wtScore != null) ? mutScore - wtScore : null;
    const deltaCls = diff == null ? '' : diff <= -0.15 ? 'is-better' : diff >= 0.15 ? 'is-worse' : 'is-neutral';
    const deltaTxt = diff == null ? '—' : `${diff > 0 ? '+' : ''}${diff.toFixed(2)}`;
    return `
      <button class="exp-modal-inh ${activeDrug === drug ? 'is-active' : ''}"
              data-modal-inh="${esc(drug)}"
              title="Cargar ${esc(drug)} acoplado a ${esc(v.hugo_symbol)} ${esc(v.protein_change)}">
        <span class="exp-modal-inh-name">${esc(drug)}</span>
        <span class="exp-modal-inh-scores">
          <span><b>WT</b> ${fmt(wtScore)}</span>
          <span><b>MUT</b> ${fmt(mutScore)}</span>
          <span class="exp-modal-inh-delta ${deltaCls}">Δ ${deltaTxt}</span>
        </span>
      </button>`;
  }).join('');
}

function updateModalSubtitle(isComplex) {
  const v = getModalVariant();
  const sub = document.getElementById('exp-modal-sub');
  if (!v || !sub) return;
  const kindLabel = modalState.model === 'wt' ? 'WT' : 'MUT';
  if (!isComplex && v.structures.external) {
    sub.textContent = `Modelo AlphaFold DB (WT) · ${v.hugo_symbol} ${v.protein_change} (posición marcada en rojo)`;
    return;
  }
  sub.textContent = isComplex && modalState.target?.drug
    ? `Complejo ${kindLabel} · ${modalState.target.drug} (pose 1 de AutoDock Vina)`
    : `Estructura ${kindLabel} · ${v.hugo_symbol} ${v.protein_change} (plegada con ESMFold)`;
}

async function applyModalStyle() {
  const viewer = modalState.viewer;
  if (!viewer?.visual) return;
  try {
    await viewer.visual.update({ visual: { style: modalState.style } });
  } catch (e) {
    console.warn('[Explore] No se pudo cambiar la representación 3D:', e);
  }
}

async function applyModalAppearance() {
  const viewer = modalState.viewer;
  const v = getModalVariant();
  if (!viewer || !v) return;

  await waitForStructure(viewer);

  try { await viewer.visual.clearHighlight?.(); } catch (_) { /* noop */ }
  const data = rainbowSelectionData(viewer);
  const isComplex = !!modalState.target?.drug;

  // El residuo mutado se pinta al final para que gane sobre el arcoíris.
  if (modalState.highlightMut && v.mut_residue != null) {
    data.push({
      start_residue_number: v.mut_residue,
      end_residue_number: v.mut_residue,
      color: { r: 239, g: 68, b: 68 },
      focus: false,
    });
  }
  if (isComplex && modalState.highlightLigand) {
    data.push({ label_comp_id: 'LIG', color: { r: 251, g: 146, b: 60 }, focus: false });
  }

  try { await viewer.visual.clearSelection?.(); } catch (_) { /* noop */ }
  if (data.length) {
    try {
      await viewer.visual.select({ data, nonSelectedColor: null });
    } catch (e) {
      console.warn('[Explore] No se pudo aplicar el coloreado del visor:', e);
    }
  }
}

async function loadModalTarget({ resetCamera = true } = {}) {
  const v = getModalVariant();
  if (!v) return;

  const container = document.getElementById('exp-modal-molstar');
  if (!container) return;

  let url = null;
  let format = 'pdb';
  let isComplex = false;

  if (modalState.target?.drug) {
    url = await resolveModalComplex(v, modalState.model, modalState.target.drug);
    if (url) {
      isComplex = true;
    } else {
      modalState.target = null;
    }
  }

  if (!url) {
    if (!v.structures[modalState.model]) {
      modalState.model = v.structures.mut ? 'mut' : 'wt';
    }
    url = v.structures[modalState.model];
    if (url) format = structureFormat(url);
  }

  if (!url) {
    container.innerHTML = '<div class="exp-molstar-empty">No hay estructura 3D publicada para esta variante.</div>';
    modalState.target = null;
    renderModalControls();
    return;
  }
  if (typeof PDBeMolstarPlugin === 'undefined') {
    container.innerHTML = '<div class="exp-molstar-empty">El visor 3D no está disponible (PDBe Mol* no cargó).</div>';
    return;
  }

  renderModalControls();
  renderModalInhibitors(v);
  updateModalSubtitle(isComplex);

  const token = ++modalState.token;
  try {
    if (!modalState.viewer) {
      container.innerHTML = '';
      const plugin = new PDBeMolstarPlugin();
      modalState.viewer = plugin;
      await plugin.render(container, {
        customData: { url, format },
        bgColor: { r: 10, g: 15, b: 30 },
        hideControls: true,
        landscape: true,
        pdbeLink: false,
        sequencePanel: false,
        lighting: 'matte',
      });
    } else {
      await modalState.viewer.visual.update({ customData: { url, format } }, true);
    }
    if (token !== modalState.token) return;

    await waitForStructure(modalState.viewer);
    await applyModalStyle();
    await applyModalAppearance();
    if (resetCamera) {
      try { await modalState.viewer.visual.reset({ camera: true }); } catch (_) { /* noop */ }
    }
  } catch (e) {
    console.warn('[Explore] Error en el visor 3D grande:', e);
    if (token === modalState.token) {
      container.innerHTML = '<div class="exp-molstar-empty">No se pudo cargar la estructura 3D.</div>';
      disposeModalViewer();
    }
  }
}

function disposeModalViewer() {
  const viewer = modalState.viewer;
  modalState.viewer = null;
  if (!viewer) return;
  try { viewer.plugin?.dispose?.(); } catch (_) { /* noop */ }
  try { viewer.dispose?.(); } catch (_) { /* noop */ }
}

function openStructureModal(v, opts = {}) {
  const modal = document.getElementById('exp-structure-modal');
  if (!modal || !v) return;

  modalState.open = true;
  modalState.variantKey = v.key;
  modalState.model = opts.model ?? (v.structures.wt ? 'wt' : 'mut');
  if (!v.structures[modalState.model]) modalState.model = v.structures.mut ? 'mut' : 'wt';
  modalState.style = 'cartoon';
  modalState.target = opts.drug ? { drug: opts.drug } : null;
  modalState.highlightMut = true;
  modalState.highlightLigand = true;

  const title = document.getElementById('exp-modal-title');
  if (title) title.textContent = `${v.protein.name} · ${v.hugo_symbol} ${v.protein_change}`;

  modal.hidden = false;
  document.body.classList.add('exp-modal-open');
  renderModalControls();
  renderModalInhibitors(v);
  updateModalSubtitle(!!modalState.target);

  // Esperar a que el diálogo tenga layout antes de crear el canvas WebGL.
  requestAnimationFrame(() => {
    loadModalTarget({ resetCamera: true });
  });
}

function closeStructureModal() {
  const modal = document.getElementById('exp-structure-modal');
  if (!modal) return;
  modalState.open = false;
  modalState.token++;
  modalState.target = null;
  modal.hidden = true;
  document.body.classList.remove('exp-modal-open');
  disposeModalViewer();
  const container = document.getElementById('exp-modal-molstar');
  if (container) container.innerHTML = '';
}

function initStructureModal() {
  const modal = document.getElementById('exp-structure-modal');
  if (!modal) return;

  modal.addEventListener('click', e => {
    if (e.target.closest('[data-exp-modal-close]')) {
      closeStructureModal();
      return;
    }

    const modelBtn = e.target.closest('[data-modal-model]');
    if (modelBtn && !modelBtn.disabled) {
      if (modalState.model === modelBtn.dataset.modalModel && !modalState.target) return;
      modalState.model = modelBtn.dataset.modalModel;
      modalState.target = null;
      renderModalControls();
      const v = getModalVariant();
      if (v) renderModalInhibitors(v);
      loadModalTarget({ resetCamera: true });
      return;
    }

    const styleBtn = e.target.closest('[data-modal-style]');
    if (styleBtn) {
      modalState.style = styleBtn.dataset.modalStyle;
      renderModalControls();
      applyModalStyle().then(() => applyModalAppearance());
      return;
    }

    const inhBtn = e.target.closest('[data-modal-inh]');
    if (inhBtn) {
      const v = getModalVariant();
      const drug = inhBtn.dataset.modalInh;
      if (!v || !drug) return;
      // Sin docking de WT para este fármaco, el complejo se muestra en MUT.
      if (modalState.model === 'wt' && v.docking?.wt?.[drug] == null) {
        modalState.model = 'mut';
      }
      modalState.target = { drug };
      loadModalTarget({ resetCamera: true });
      return;
    }

    if (e.target.closest('[data-modal-clear-ligand]')) {
      modalState.target = null;
      loadModalTarget({ resetCamera: true });
      return;
    }

    if (e.target.closest('[data-modal-focus-mut]')) {
      const v = getModalVariant();
      if (v?.mut_residue != null && modalState.viewer?.visual) {
        try {
          modalState.viewer.visual.highlight({
            data: [{
              start_residue_number: v.mut_residue,
              end_residue_number: v.mut_residue,
            }],
            focus: true,
          });
        } catch (_) { /* noop */ }
      }
      return;
    }

    if (e.target.closest('[data-modal-focus-ligand]')) {
      if (modalState.target?.drug && modalState.viewer?.visual) {
        try {
          modalState.viewer.visual.highlight({
            data: [{ label_comp_id: 'LIG' }],
            focus: true,
          });
        } catch (_) { /* noop */ }
      }
    }
  });

  modal.querySelector('#exp-modal-mutres')?.addEventListener('change', e => {
    modalState.highlightMut = e.target.checked;
    applyModalAppearance();
  });
  modal.querySelector('#exp-modal-ligand')?.addEventListener('change', e => {
    modalState.highlightLigand = e.target.checked;
    applyModalAppearance();
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && modalState.open) closeStructureModal();
  });
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
  // Cualquier cambio de filtro reconstruye la tabla: se cierra la ficha abierta
  // para no dejar un visor huérfano.
  closeDetail();

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

// ── Delegación de clicks de la tabla ──────────────────────────────────────
function handleTableClick(e) {
  // Botón «Selección»: abre/cierra la ficha
  const selectBtn = e.target.closest('[data-select-key]');
  if (selectBtn) {
    e.preventDefault();
    const row = selectBtn.closest('tr.exp-row');
    if (row) toggleDetail(row, selectBtn);
    return;
  }

  // Toggle WT/MUT dentro de la ficha
  const structToggle = e.target.closest('[data-detail-struct]');
  if (structToggle) {
    e.preventDefault();
    switchDetailStructure(structToggle);
    return;
  }

  // Abrir el visor 3D grande desde la ficha
  const openViewer = e.target.closest('[data-open-viewer]');
  if (openViewer) {
    e.preventDefault();
    const detail = openViewer.closest('.exp-detail');
    const v = _rowsByKey.get(detail?.dataset.detailKey);
    if (v) {
      const kind = detail.querySelector('.exp-detail-struct-btn.is-active')?.dataset.detailStruct;
      openStructureModal(v, { model: kind });
    }
    return;
  }

  // Ver en 3D un inhibidor acoplado (ficha)
  const poseBtn = e.target.closest('[data-detail-pose]');
  if (poseBtn) {
    e.preventDefault();
    const detail = poseBtn.closest('.exp-detail');
    const v = _rowsByKey.get(detail?.dataset.detailKey);
    if (v) openStructureModal(v, { model: 'mut', drug: poseBtn.dataset.detailPose });
    return;
  }

  // Gráfica WT vs MUT de la sección de inhibidores
  const chartBtn = e.target.closest('[data-docking-chart]');
  if (chartBtn) {
    e.preventDefault();
    toggleDockingChart(chartBtn);
    return;
  }

  // Botones WT/MUT de la fila: navegar a Estructuras 3D
  handleStructClick(e);
}

// ── Loader principal ──────────────────────────────────────────────────────
async function loadExplore() {
  if (state.loaded) return;
  state.loaded = true;
  closeDetail();
  closeStructureModal();
  modalComplexCache.clear();

  const [rawMutations, topVariants, manifest, metrics, runManifest, affinities, external] = await Promise.all([
    loadJSON(DATA.rawMutations()),
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.manifestStructures()),
    loadJSON(DATA.structuralMetrics()),
    loadJSON(DATA.runManifest()),
    loadJSON(DATA.vinaAffinities()),
    loadJSON(DATA.externalStructures()),
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
  _allRows   = buildVariantTable(rawMutations, topVariants, manifest, metrics, affinities, external);
  _rowsByKey = new Map(_allRows.map(r => [r.key, r]));
  _maxFreq   = Math.max(..._allRows.map(r => r.frequency), 1);
  _totalRows = _allRows.length;

  // Respetar los filtros que el usuario ya tenía al cambiar de corrida.
  applyFilters();

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

  // Listener de clicks: botones WT/MUT y ficha «Selección» (delegado en tbody)
  const tbody = document.getElementById('exp-tbody');
  if (tbody && !tbody.dataset.listenerAttached) {
    tbody.addEventListener('click', handleTableClick);
    tbody.dataset.listenerAttached = 'true';
  }
}

registerLoader('explore', loadExplore);
initStructureModal();
