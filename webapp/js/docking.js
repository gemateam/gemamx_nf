/**
 * docking.js — ranking de fármacos, tabla WT vs MUT, gráfica de afinidades
 */
import { DATA, loadJSON, fmt, PLOTLY_LAYOUT, DRUG_META, registerLoader, registerReloadFlag } from './app.js';

const state = { loaded: false };
registerReloadFlag('docking', state);

async function loadDocking() {
  if (state.loaded) return;
  state.loaded = true;

  const [variants, metrics, affinities] = await Promise.all([
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.structuralMetrics()),
    loadJSON(DATA.vinaAffinities()),
  ]);

  if (!affinities) {
    document.getElementById('chart-docking-ranking').innerHTML =
      '<p class="no-data">No se encontraron datos de docking.</p>';
    return;
  }

  // Variantes con datos de docking
  const available = Object.keys(affinities).sort();

  // También incluir variantes del ranking con datos de métricas
  const fromMetrics = metrics
    ? Object.entries(metrics)
        .filter(([_, m]) => m.vina_scores)
        .map(([k]) => k)
    : [];

  const allVariants = [...new Set([...available, ...fromMetrics])].sort();

  // Poblar selector
  const sel = document.getElementById('sel-docking-variant');
  if (!allVariants.length) {
    sel.innerHTML = '<option>Sin datos de docking</option>';
    return;
  }
  sel.innerHTML = allVariants.map(v =>
    `<option value="${v}">${v.replace('_', ' ')}</option>`).join('');

  sel.addEventListener('change', () => renderDocking(sel.value, metrics, affinities));
  renderDocking(sel.value, metrics, affinities);
}

function renderDocking(variantId, metrics, affinities) {
  const m   = metrics?.[variantId] ?? {};
  const mut = affinities?.[variantId] ?? m.vina_scores ?? {};

  // Para WT, buscar el gen WT en affinities  (clave GEN_WT)
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

  Plotly.newPlot('chart-docking-ranking', traces, {
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
    return `
      <tr>
        <td><strong>${drug}</strong></td>
        <td>${meta.target ?? '—'}</td>
        <td>${meta.status ?? '—'}</td>
        <td>${wtScore !== null ? wtScore.toFixed(3) : '—'}</td>
        <td>${mutScore !== null ? mutScore.toFixed(3) : '—'}</td>
        <td>${deltaStr}</td>
      </tr>`;
  }).join('');
}

registerLoader('docking', loadDocking);
