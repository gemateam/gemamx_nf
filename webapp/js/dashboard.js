/**
 * dashboard.js — KPIs, tabla de variantes, gráficas resumen
 */
import { DATA, loadJSON, badgeClass, fmt, PLOTLY_LAYOUT, registerLoader, registerReloadFlag } from './app.js';

const state = { loaded: false };
registerReloadFlag('dashboard', state);

async function loadDashboard() {
  if (state.loaded) return;
  state.loaded = true;

  const [variants, metrics, manifest] = await Promise.all([
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.structuralMetrics()),
    loadJSON(DATA.manifestStructures()),
  ]);

  if (!variants) {
    document.getElementById('tbody-variants').innerHTML =
      '<tr><td colspan="7" class="no-data">No se encontraron datos de variantes.</td></tr>';
    return;
  }

  // ── KPIs ───────────────────────────────────────────────────────────────
  document.getElementById('kpi-total').textContent = variants.length;

  const top = variants[0];
  document.getElementById('kpi-hotspot').textContent =
    top ? `${top.hugo_symbol} ${top.protein_change}` : '—';

  const structCount = manifest
    ? Object.values(manifest).filter(v => v !== null).length
    : '—';
  document.getElementById('kpi-structs').textContent = structCount;

  let bestScore = null;
  if (metrics) {
    Object.values(metrics).forEach(m => {
      if (m.best_vina_score != null) {
        const s = parseFloat(m.best_vina_score);
        if (!isNaN(s) && (bestScore === null || s < bestScore)) bestScore = s;
      }
    });
  }
  document.getElementById('kpi-affinity').textContent =
    bestScore !== null ? bestScore.toFixed(3) : '—';

  // ── Gráfica: Top variantes por frecuencia ─────────────────────────────
  const top15 = [...variants].sort((a, b) => b.frequency - a.frequency).slice(0, 15);
  Plotly.newPlot('chart-top-variants', [{
    type: 'bar',
    x: top15.map(v => `${v.hugo_symbol} ${v.protein_change}`),
    y: top15.map(v => v.frequency),
    marker: { color: '#14b8a6' },
    hovertemplate: '<b>%{x}</b><br>Frecuencia: %{y}<extra></extra>',
  }], {
    ...PLOTLY_LAYOUT,
    xaxis: { tickangle: -40, color: '#94a3b8' },
    yaxis: { title: 'Frecuencia', color: '#94a3b8', gridcolor: '#334155' },
    height: 320,
  }, { responsive: true, displayModeBar: false });

  // ── Gráfica: distribución por clasificación ───────────────────────────
  const clsDist = {};
  variants.forEach(v => { clsDist[v.classification] = (clsDist[v.classification] ?? 0) + 1; });
  Plotly.newPlot('chart-classification', [{
    type: 'pie',
    labels: Object.keys(clsDist),
    values: Object.values(clsDist),
    hole: 0.45,
    textinfo: 'label+percent',
    hovertemplate: '<b>%{label}</b><br>%{value} variantes<extra></extra>',
    marker: { colors: ['#f87171','#fbbf24','#60a5fa','#34d399','#a78bfa'] },
  }], {
    ...PLOTLY_LAYOUT,
    height: 320,
    showlegend: false,
  }, { responsive: true, displayModeBar: false });

  // ── Tabla ──────────────────────────────────────────────────────────────
  renderTable(variants);

  // Filtro en tiempo real
  document.getElementById('filter-variants').addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    renderTable(variants.filter(v =>
      v.hugo_symbol.toLowerCase().includes(q) ||
      v.protein_change.toLowerCase().includes(q)
    ));
  });
}

function renderTable(rows) {
  const tbody = document.getElementById('tbody-variants');
  tbody.innerHTML = rows.map(v => `
    <tr>
      <td>${v.rank}</td>
      <td><strong>${v.hugo_symbol}</strong></td>
      <td>${v.protein_change}</td>
      <td>${v.frequency}</td>
      <td>${fmt(v.cohort_percentage)}%</td>
      <td>${v.chromosome !== '?' ? v.chromosome : '—'}</td>
      <td><span class="badge ${badgeClass(v.classification)}">${v.classification}</span></td>
    </tr>`).join('');
}

registerLoader('dashboard', loadDashboard);
