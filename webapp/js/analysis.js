/**
 * analysis.js — distribuciones mutacionales del cohorte TCGA-BRCA
 */
import { DATA, loadJSON, PLOTLY_LAYOUT, registerLoader, registerReloadFlag } from './app.js';

const state = { loaded: false };
registerReloadFlag('analysis', state);

async function loadAnalysis() {
  if (state.loaded) return;
  state.loaded = true;

  const stats = await loadJSON(DATA.mutationStats());
  if (!stats) {
    document.getElementById('stats-cohort').innerHTML =
      '<p class="no-data">No se encontraron estadísticas del cohorte.</p>';
    return;
  }

  // ── Gráfica: distribución por gen ─────────────────────────────────────
  const geneDist = stats.gene_distribution ?? {};
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
    height: 480,
    margin: { l: 90, r: 20, t: 20, b: 50 },
    xaxis: { title: 'Mutaciones', color: '#94a3b8', gridcolor: '#334155' },
    yaxis: { color: '#94a3b8', tickfont: { size: 11 } },
  }, { responsive: true, displayModeBar: false });

  // ── Gráfica: tipos de mutación ────────────────────────────────────────
  const typeDist = stats.type_distribution ?? {};
  const typeEntries = Object.entries(typeDist).sort((a, b) => b[1] - a[1]);

  // Etiquetas legibles
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
    height: 480,
    showlegend: true,
    legend: { font: { color: '#94a3b8', size: 10 }, orientation: 'v' },
  }, { responsive: true, displayModeBar: false });

  // ── Estadísticas del cohorte ──────────────────────────────────────────
  const statsItems = [
    { label: 'Total muestras',   value: (stats.total_samples  ?? '—').toLocaleString() },
    { label: 'Total mutaciones', value: (stats.total_mutations ?? '—').toLocaleString() },
    { label: 'Genes con 15+ drivers', value: Object.keys(geneDist).length },
    { label: 'Tipo predominante', value: typeLabels[typeEntries[0]?.[0]] ?? '—' },
    { label: 'Missense (%)',
      value: stats.total_mutations
        ? ((typeDist.Missense_Mutation / stats.total_mutations) * 100).toFixed(1) + '%'
        : '—' },
  ];

  document.getElementById('stats-cohort').innerHTML = statsItems.map(s => `
    <div class="stat-item">
      <div class="s-label">${s.label}</div>
      <div class="s-value">${s.value}</div>
    </div>`).join('');
}

registerLoader('analysis', loadAnalysis);
