/**
 * docking.js — ranking de fármacos, tabla WT vs MUT y visor 3D de poses
 *
 * El pipeline publica, por variante y fármaco:
 *   docking/complex/<variante>_<fármaco>_complex.pdb   → proteína (cadena A) + pose 1 (cadena L)
 *   docking/results/<variante>_<fármaco>_out.pdbqt     → pose cruda de AutoDock Vina
 * Molstar no parsea PDBQT, así que el visor usa el complejo y, si no existe,
 * cae a la estructura proteica del manifest.
 */
import {
  DATA, loadJSON, PLOTLY_LAYOUT, DRUG_META, BASE_PATH, contractUrl,
  registerLoader, registerReloadFlag,
} from './app.js';

const state = {
  loaded: false,
  metrics: null,
  affinities: null,
  variantId: null,
  poseCache: new Map(),   // url -> bool (HEAD del complejo)
  viewerUrl: null,        // estructura cargada actualmente en el visor
};

registerReloadFlag('docking', state);

const POSE_DEFAULT_LABEL =
  'Pulsa «Ver pose» en el ranking o en la tabla para cargar el complejo de AutoDock Vina.';

// ── Visor 3D ───────────────────────────────────────────────────────────────
function viewerContainer() {
  return document.getElementById('viewer-docking');
}

function setPoseLabel(text) {
  const el = document.getElementById('docking-pose-label');
  if (el) el.textContent = text;
}

/** Crea el plugin en la primera pose y reutiliza el visor en las siguientes. */
let viewerPromise = null;

function renderOptions(url, format) {
  return {
    customData:    { url, format, binary: false },
    bgColor:       { r: 10, g: 10, b: 20 },
    hideControls:  true,
    selectInteraction: false,
    landscape:     false,
    pdbeLink:      false,
    sequencePanel: false,
  };
}

async function ensureViewer(url, format) {
  const el = viewerContainer();
  if (!el || typeof PDBeMolstarPlugin === 'undefined') return null;

  if (!viewerPromise) {
    viewerPromise = (async () => {
      const plugin = new PDBeMolstarPlugin();
      const loaded = new Promise((resolve) => {
        let settled = false;
        const done = () => { if (!settled) { settled = true; resolve(); } };
        try { plugin.events.loadComplete.subscribe(done); } catch { /* v3 opcional */ }
        setTimeout(done, 15000);   // red lenta o evento no emitido
      });
      plugin.render(el, renderOptions(url, format));
      await loaded;
      return plugin;
    })().catch((e) => {
      console.warn('Molstar no pudo inicializarse:', e);
      viewerPromise = null;
      return null;
    });
  }

  const plugin = await viewerPromise;
  if (!plugin) return null;
  if (state.viewerUrl !== url) {
    await plugin.visual.update({
      customData: { url, format, binary: false },
      bgColor:    { r: 10, g: 10, b: 20 },
    });
  }
  state.viewerUrl = url;
  return plugin;
}

function complexUrl(variantId, drug) {
  const drugSafe = drug.replace(/ /g, '_');
  // Convención del pipeline: <variante>_x_<fármaco>_complex.pdb
  return `${BASE_PATH}/docking/complex/${variantId}_x_${drugSafe}_complex.pdb`;
}

/** HEAD cacheado: los complejos no cambian dentro de una misma corrida. */
async function hasComplex(url) {
  if (state.poseCache.has(url)) return state.poseCache.get(url);
  let ok = false;
  try {
    ok = (await fetch(url, { method: 'HEAD' })).ok;
  } catch {
    ok = false;
  }
  state.poseCache.set(url, ok);
  return ok;
}

/**
 * resSeq del residuo mutado en el modelo (chain A del complejo).
 * Sólo el contrato conoce el mapeo posición-proteína → resSeq del modelo;
 * sin él no se resalta nada (mejor que resaltar el residuo equivocado).
 */
function mutationModelResidue(variantId) {
  const pos = state.metrics?.[variantId]?.mutation_resseq_model;
  return pos === null || pos === undefined ? null : Number(pos);
}

async function showPose(variantId, drug) {
  const complex = complexUrl(variantId, drug);
  const fromComplex = await hasComplex(complex);
  const variantLabel = variantId.replace(/_/g, ' ');

  let target = complex;
  if (!fromComplex) {
    const manifest = await loadJSON(DATA.manifestStructures());
    const key = manifest?.[variantId] ? variantId : `${variantId.split('_')[0]}_WT`;
    target = contractUrl(manifest?.[key] ?? null);
  }

  if (!target) {
    setPoseLabel(`Sin pose ni estructura disponible para ${variantLabel} · ${drug}.`);
    return;
  }

  setPoseLabel(fromComplex
    ? `⚛ Complejo proteína + ligando (pose 1 de Vina) · ${drug} → ${variantLabel}`
    : `🧬 Estructura proteica (sin ligando) · ${drug} → ${variantLabel}`);

  const format = target.endsWith('.cif') ? 'mmcif' : 'pdb';
  let plugin;
  try {
    plugin = await ensureViewer(target, format);
  } catch (e) {
    console.warn('No se pudo cargar la pose:', target, e);
    plugin = null;
  }
  if (!plugin) {
    setPoseLabel('Visor 3D no disponible (revisa la carga de PDBe Molstar).');
    return;
  }

  // Resaltado: ligando en naranja y residuo mutado en rojo.
  // PDBe Molstar no entiende `chain_id`; la cadena es `auth_asym_id`/
  // `struct_asym_id` y el resSeq de PDB es `auth_seq_id` (no `residue_number`,
  // que compara label_seq_id).
  const selection = [];
  if (fromComplex) {
    selection.push({ label_comp_id: 'LIG', color: { r: 251, g: 146, b: 60 } });
  }
  const mutResidue = mutationModelResidue(variantId);
  if (mutResidue !== null) {
    selection.push({
      ...(fromComplex ? { auth_asym_id: 'A' } : {}),
      auth_seq_id: mutResidue,
      color: { r: 239, g: 68, b: 68 },
    });
  }
  if (selection.length) {
    try {
      await plugin.visual.select({ data: selection, nonSelectedColor: null });
    } catch { /* decorativo */ }
  }

  viewerContainer()?.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// ── Carga de datos y render ────────────────────────────────────────────────
async function loadDocking() {
  if (state.loaded) return;
  state.loaded = true;
  state.poseCache.clear();
  setPoseLabel(POSE_DEFAULT_LABEL);

  const [variants, metrics, affinities] = await Promise.all([
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.structuralMetrics()),
    loadJSON(DATA.vinaAffinities()),
  ]);
  state.metrics = metrics;
  state.affinities = affinities;

  if (!affinities) {
    document.getElementById('chart-docking-ranking').innerHTML =
      '<p class="no-data">No se encontraron datos de docking.</p>';
    return;
  }

  const available = Object.keys(affinities).sort();
  const fromMetrics = metrics
    ? Object.entries(metrics).filter(([, m]) => m.vina_scores).map(([k]) => k)
    : [];
  const allVariants = [...new Set([...available, ...fromMetrics])].sort();

  const sel = document.getElementById('sel-docking-variant');
  if (!allVariants.length) {
    sel.innerHTML = '<option>Sin datos de docking</option>';
    return;
  }
  sel.innerHTML = allVariants.map(v =>
    `<option value="${v}">${v.replace('_', ' ')}</option>`).join('');

  if (!sel.dataset.listenerAttached) {
    sel.addEventListener('change', () => renderDocking(sel.value, metrics, affinities));
    sel.dataset.listenerAttached = 'true';
  }
  renderDocking(sel.value, metrics, affinities);
}

async function renderDocking(variantId, metrics, affinities) {
  state.variantId = variantId;
  const m   = metrics?.[variantId] ?? {};
  const mut = affinities?.[variantId] ?? m.vina_scores ?? {};

  // Para WT, buscar el gen WT en affinities (clave GEN_WT)
  const gene  = variantId.split('_')[0];
  const wtKey = `${gene}_WT`;
  const wt    = affinities?.[wtKey] ?? null;

  const drugs = Object.keys(mut).sort((a, b) => (mut[a] ?? 0) - (mut[b] ?? 0));
  if (!drugs.length) {
    document.getElementById('chart-docking-ranking').innerHTML =
      '<p class="no-data">Sin datos de afinidad para esta variante.</p>';
    document.getElementById('tbody-docking').innerHTML = '';
    return;
  }

  // Disponibilidad de complejos (para marcar los botones «Ver pose»)
  const poseAvailable = {};
  await Promise.all(drugs.map(async drug => {
    poseAvailable[drug] = await hasComplex(complexUrl(variantId, drug));
  }));

  // ── Gráfica: barras MUT (y WT si disponible) ──────────────────────────
  const traces = [{
    name: 'MUT',
    type: 'bar',
    x: drugs,
    y: drugs.map(d => mut[d] ?? null),
    marker: { color: '#14b8a6' },
    hovertemplate: '<b>%{x}</b><br>MUT: %{y:.3f} kcal/mol<extra></extra>',
  }];

  if (wt) {
    traces.push({
      name: 'WT',
      type: 'bar',
      x: drugs,
      y: drugs.map(d => wt[d] ?? null),
      marker: { color: '#334155' },
      hovertemplate: '<b>%{x}</b><br>WT: %{y:.3f} kcal/mol<extra></extra>',
    });
  }

  const chartEl = document.getElementById('chart-docking-ranking');
  Plotly.newPlot(chartEl, traces, {
    ...PLOTLY_LAYOUT,
    barmode: 'group',
    height: 380,
    xaxis: { tickangle: -35, color: '#94a3b8' },
    yaxis: {
      title: 'Afinidad (kcal/mol)',
      color: '#94a3b8', gridcolor: '#334155',
      hoverformat: '.3f',
    },
    legend: { font: { color: '#94a3b8' } },
  }, { responsive: true, displayModeBar: false });

  // Clic en una barra → cargar la pose de ese fármaco
  chartEl.removeAllListeners?.('plotly_click');
  chartEl.on?.('plotly_click', (ev) => {
    const drug = ev?.points?.[0]?.x;
    if (drug) showPose(variantId, drug);
  });

  // ── Tabla ──────────────────────────────────────────────────────────────
  const tbody = document.getElementById('tbody-docking');
  tbody.innerHTML = drugs.map(drug => {
    const mutScore = mut[drug] ?? null;
    const wtScore  = wt?.[drug] ?? null;
    const delta    = (mutScore !== null && wtScore !== null)
      ? (mutScore - wtScore) : null;
    const deltaStr = delta !== null
      ? `<span class="${delta <= -0.5 ? 'delta-negative' : delta >= 0.5 ? 'delta-positive' : ''}">${delta.toFixed(3)}</span>`
      : '—';
    const meta = DRUG_META[drug] ?? {};
    const disabled = poseAvailable[drug] ? '' : ' disabled title="Sin complejo de docking"';
    return `
      <tr>
        <td><strong>${drug}</strong></td>
        <td>${meta.target ?? '—'}</td>
        <td>${meta.status ?? '—'}</td>
        <td>${wtScore !== null ? wtScore.toFixed(3) : '—'}</td>
        <td>${mutScore !== null ? mutScore.toFixed(3) : '—'}</td>
        <td>${deltaStr}</td>
        <td>
          <button class="btn-pose" data-pose-variant="${variantId}" data-pose-drug="${drug}"${disabled}>
            Ver pose
          </button>
        </td>
      </tr>`;
  }).join('');

  if (!tbody.dataset.listenerAttached) {
    tbody.addEventListener('click', (ev) => {
      const btn = ev.target.closest('button[data-pose-drug]');
      if (!btn || btn.disabled) return;
      showPose(btn.dataset.poseVariant, btn.dataset.poseDrug);
    });
    tbody.dataset.listenerAttached = 'true';
  }

  const withComplex = Object.values(poseAvailable).filter(Boolean).length;
  setPoseLabel(withComplex
    ? `${withComplex}/${drugs.length} fármacos con complejo proteína–ligando · pulsa «Ver pose»`
    : POSE_DEFAULT_LABEL);
}

registerLoader('docking', loadDocking);
