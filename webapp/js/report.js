/**
 * report.js — reporte integrado por variante
 */
import { DATA, loadJSON, fmt, badgeClass, DRUG_META, PLOTLY_LAYOUT, registerLoader, registerReloadFlag } from './app.js';

const state = { loaded: false };
registerReloadFlag('report', state);

async function loadReport() {
  if (state.loaded) return;
  state.loaded = true;

  const [variants, metrics, affinities, variantSummary] = await Promise.all([
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.structuralMetrics()),
    loadJSON(DATA.vinaAffinities()),
    loadJSON(DATA.variantClinicalSummary()),
  ]);

  if (!variants?.length) {
    document.getElementById('report-content').innerHTML =
      '<p class="no-data">No se encontraron variantes.</p>';
    return;
  }

  const sel = document.getElementById('sel-report-variant');
  sel.innerHTML = variants.map(v =>
    `<option value="${v.hugo_symbol}_${v.protein_change}">
      ${v.hugo_symbol} ${v.protein_change}
    </option>`).join('');

  sel.addEventListener('change', () =>
    renderReport(sel.value, variants, metrics, affinities, variantSummary));
  renderReport(sel.value, variants, metrics, affinities, variantSummary);
}

// ── Perfil clínico agregado para la variante activa ────────────────────────
const CLINICAL_LABELS = {
  'HISPANIC OR LATINO': 'Hispano/Latino',
  'NOT HISPANIC OR LATINO': 'No hispano/Latino',
  'WHITE': 'Blanca',
  'BLACK OR AFRICAN AMERICAN': 'Negra/Afroamericana',
  'ASIAN': 'Asiática',
  'AMERICAN INDIAN OR ALASKA NATIVE': 'Indígena americana',
  'NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER': 'Isleña del Pacífico',
  'OTHER': 'Otra',
  'SIN DATO': 'Sin dato',
};

function clinicalLabel(raw) {
  const key = String(raw ?? 'Sin dato').trim();
  return CLINICAL_LABELS[key.toUpperCase()] ?? key;
}

function clinicalChips(dist, dimension, threshold, smallCells) {
  return Object.entries(dist)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([label, count]) => {
      const small = dimension
        ? (smallCells ?? []).includes(`${dimension}:${label}`) || count < threshold
        : false;
      return `<span class="clinical-chip${small ? ' clinical-chip--small' : ''}"
          title="${label}: ${count} muestras${small ? ` (n < ${threshold})` : ''}">${clinicalLabel(label)}
          <span class="chip-n">${count}${small ? '*' : ''}</span></span>`;
    }).join('');
}

function renderClinicalProfile(summary) {
  if (!summary) return '';
  const threshold = summary.small_cell_threshold ?? 5;
  const blocks = [
    ['Etnia autorreportada', summary.ethnicity_distribution, 'ethnicity'],
    ['Raza autorreportada',  summary.race_distribution,     'race'],
    ['Subtipo IHC',          summary.ihc_subtype_distribution, null],
    ['Subtipo PAM50',        summary.pam50_distribution,    null],
    ['Grado histológico',    summary.grade_distribution,    null],
    ['Histología',           summary.histology_distribution, null],
  ].filter(([, dist]) => dist && Object.keys(dist).length);

  if (!blocks.length && summary.age?.mean == null) return '';

  const age = summary.age;
  return `
    <div class="card report-section">
      <h3>Perfil Clínico de las Portadoras</h3>
      <div class="report-kpi-row">
        <div class="report-kpi">
          <div class="rk-label">Muestras con clínica</div>
          <div class="rk-value">${summary.matched_clinical_count ?? '—'}</div>
        </div>
        ${age?.mean != null ? `
        <div class="report-kpi">
          <div class="rk-label">Edad media (rango)</div>
          <div class="rk-value">${Number(age.mean).toFixed(1)} (${age.min}–${age.max})</div>
        </div>` : ''}
      </div>
      ${blocks.map(([title, dist, dimension]) => `
        <div class="clinical-block">
          <div class="clinical-block-label">${title}</div>
          <div class="clinical-chips">${clinicalChips(dist, dimension, threshold, summary.small_cells)}</div>
        </div>`).join('')}
      ${summary.clinical_data_note
        ? `<p class="chart-note" style="margin-top:.75rem">${summary.clinical_data_note}</p>` : ''}
      ${summary.clinical_source
        ? `<p class="clinical-source">Fuente: ${summary.clinical_source}</p>` : ''}
    </div>`;
}

function renderReport(variantId, variants, metrics, affinities, variantSummary) {
  const gene  = variantId.split('_')[0];
  const pc    = variantId.replace(`${gene}_`, '');
  const v     = variants.find(x => x.hugo_symbol === gene && x.protein_change === pc);
  const m     = metrics?.[variantId] ?? {};
  const scores= affinities?.[variantId] ?? m.vina_scores ?? {};
  const clinical = (variantSummary ?? []).find(x => x.variant_id === variantId);

  const drugs = Object.entries(scores)
    .filter(([_, s]) => s !== null)
    .sort((a, b) => a[1] - b[1]);

  const el = document.getElementById('report-content');

  el.innerHTML = `
    <!-- ── Encabezado ── -->
    <div class="card report-section">
      <h3>Perfil Genómico — ${gene} ${pc}</h3>
      <div class="report-kpi-row">
        <div class="report-kpi">
          <div class="rk-label">Rank</div>
          <div class="rk-value">#${v?.rank ?? '—'}</div>
        </div>
        <div class="report-kpi">
          <div class="rk-label">Frecuencia</div>
          <div class="rk-value">${v?.frequency ?? '—'}</div>
        </div>
        <div class="report-kpi">
          <div class="rk-label">Cohorte %</div>
          <div class="rk-value">${fmt(v?.cohort_percentage)}%</div>
        </div>
        <div class="report-kpi">
          <div class="rk-label">Cromosoma</div>
          <div class="rk-value">${v?.chromosome !== '?' ? v?.chromosome : '—'}</div>
        </div>
        <div class="report-kpi">
          <div class="rk-label">Clasificación</div>
          <div class="rk-value">
            <span class="badge ${badgeClass(v?.classification)}">
              ${v?.classification ?? '—'}
            </span>
          </div>
        </div>
      </div>
    </div>

    ${renderClinicalProfile(clinical)}

    <!-- ── Métricas estructurales ── -->
    <div class="card report-section">
      <h3>Métricas Estructurales</h3>
      <div class="report-kpi-row">
        <div class="report-kpi">
          <div class="rk-label">pLDDT WT</div>
          <div class="rk-value">${fmt(m.wt_plddt)}</div>
        </div>
        <div class="report-kpi">
          <div class="rk-label">pLDDT MUT</div>
          <div class="rk-value">${fmt(m.mut_plddt)}</div>
        </div>
        <div class="report-kpi">
          <div class="rk-label">RMSD Global (Å)</div>
          <div class="rk-value">${fmt(m.rmsd_global)}</div>
        </div>
        <div class="report-kpi">
          <div class="rk-label">RMSD Sitio Activo (Å)</div>
          <div class="rk-value">${fmt(m.rmsd_active)}</div>
        </div>
      </div>
      ${renderRMSDRegions(m.rmsd_regions ?? [])}
    </div>

    <!-- ── Candidatos farmacológicos ── -->
    <div class="card report-section">
      <h3>Candidatos Farmacológicos</h3>
      ${drugs.length ? `
        <div id="chart-report-docking-${variantId}" style="height:300px;margin-bottom:1rem;"></div>
        <div class="table-wrapper">
          <table>
            <thead>
              <tr><th>#</th><th>Fármaco</th><th>Target</th><th>Estado</th><th>Afinidad (kcal/mol)</th></tr>
            </thead>
            <tbody>
              ${drugs.map(([drug, score], i) => {
                const meta = DRUG_META[drug] ?? {};
                return `<tr>
                  <td>${i + 1}</td>
                  <td><strong>${drug}</strong></td>
                  <td>${meta.target ?? '—'}</td>
                  <td>${meta.status ?? '—'}</td>
                  <td>${score.toFixed(3)}</td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>` : '<p class="no-data">Sin datos de docking para esta variante.</p>'}
    </div>

    <!-- ── Síntesis diagnóstica ── -->
    <div class="card report-section">
      <h3>Síntesis Diagnóstica</h3>
      ${renderSynthesis(v, m, drugs)}
    </div>
  `;

  // Renderizar gráfica de docking del reporte
  if (drugs.length) {
    Plotly.newPlot(`chart-report-docking-${variantId}`, [{
      type: 'bar',
      x: drugs.map(([d]) => d),
      y: drugs.map(([_, s]) => s),
      marker: {
        color: drugs.map(([_, s]) => s <= -8 ? '#14b8a6' : s <= -6 ? '#60a5fa' : '#334155'),
      },
      hovertemplate: '<b>%{x}</b><br>%{y:.3f} kcal/mol<extra></extra>',
    }], {
      ...PLOTLY_LAYOUT,
      height: 280,
      xaxis: { tickangle: -35, color: '#94a3b8' },
      yaxis: { title: 'Afinidad (kcal/mol)', color: '#94a3b8', gridcolor: '#334155' },
    }, { responsive: true, displayModeBar: false });
  }
}

function renderRMSDRegions(regions) {
  if (!regions.length) return '';
  const maxVal = Math.max(...regions.map(r => parseFloat(r.value) || 0), 0.1);
  return `<div class="rmsd-bar-container" style="margin-top:.75rem">` +
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

function renderSynthesis(v, m, drugs) {
  const lines = [];

  if (v) {
    lines.push(`La variante <strong>${v.hugo_symbol} ${v.protein_change}</strong> 
      fue detectada en <strong>${v.frequency}</strong> muestras de la cohorte analizada 
      (${fmt(v.cohort_percentage)}%), clasificada como 
      <span class="badge ${badgeClass(v.classification)}">${v.classification}</span>.`);
  }

  const plddt = parseFloat(m.mut_plddt);
  if (!isNaN(plddt)) {
    const conf = plddt >= 80 ? 'alta confianza estructural' :
                 plddt >= 60 ? 'confianza moderada' : 'baja confianza estructural';
    lines.push(`La estructura mutada presenta pLDDT = <strong>${plddt.toFixed(1)}</strong> 
      (${conf}). RMSD global respecto al WT: <strong>${fmt(m.rmsd_global)} Å</strong>.`);
  }

  if (drugs.length) {
    const [bestDrug, bestScore] = drugs[0];
    const meta = DRUG_META[bestDrug] ?? {};
    lines.push(`El fármaco con mayor afinidad predicha es <strong>${bestDrug}</strong> 
      (${meta.target ?? '—'}, ${meta.status ?? '—'}) con 
      <strong>${bestScore.toFixed(3)} kcal/mol</strong>.`);

    const repositionable = drugs.filter(([_, s]) => s <= -8);
    if (repositionable.length) {
      lines.push(`<strong>${repositionable.length}</strong> fármaco(s) muestran afinidad 
        ≤ −8.0 kcal/mol, candidatos para repositionamiento terapéutico: 
        ${repositionable.map(([d]) => d).join(', ')}.`);
    }
  }

  return lines.map(l => `<p style="margin-bottom:.6rem;line-height:1.6">${l}</p>`).join('');
}

registerLoader('report', loadReport);
