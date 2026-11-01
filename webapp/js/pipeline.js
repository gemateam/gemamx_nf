/**
 * pipeline.js — Pipeline Status dashboard
 *
 * Muestra KPIs de la corrida activa leyendo:
 *   run_manifest.json  → parámetros del pipeline
 *   top_variants.json  → variantes priorizadas
 *   structural_metrics.json → pLDDT, RMSD, scores Vina
 *   manifest_structures.json → qué estructuras existen
 *   docking/complex/* → HEAD cacheado para contar complejos
 */
import {
  DATA, loadJSON, fmt, BASE_PATH, contractUrl,
  registerLoader, registerReloadFlag,
} from './app.js';

const state = { loaded: false };
registerReloadFlag('pipeline', state);

// ── Etapas del pipeline ────────────────────────────────────────────────────
const STAGES = [
  { id: 'M1', label: 'GDC API\nIngestion',        key: 'mutations' },
  { id: 'M2', label: 'Variant\nPrioritization',   key: 'variants'  },
  { id: 'M3', label: 'Structural\nPrediction',     key: 'structures'},
  { id: 'M4', label: 'Vina\nDocking',              key: 'docking'   },
  { id: 'M5', label: 'Final\nReport',              key: 'report'    },
];

// ── Helpers ────────────────────────────────────────────────────────────────
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val ?? '—';
}

function safeScore(v) {
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

// Mejor score entre todos los drugs de un metric entry
function bestScore(m) {
  const scores = Object.values(m.vina_scores ?? {}).map(Number).filter(n => !isNaN(n));
  if (!scores.length) return safeScore(m.best_vina_score);
  return Math.min(...scores);
}

function bestDrug(m) {
  const scores = m.vina_scores ?? {};
  const entries = Object.entries(scores).map(([d, s]) => [d, Number(s)]).filter(([, s]) => !isNaN(s));
  if (!entries.length) return m.best_vina_drug ?? '—';
  return entries.sort((a, b) => a[1] - b[1])[0][0];
}

// Contar complejos disponibles vía HEAD cacheado
const complexCache = new Map();
async function countComplexes(variantId) {
  const drugs = ['Abemaciclib','Alpelisib','Buparlisib','Capivasertib','Copanlisib',
                 'Everolimus','Gedatolisib','Palbociclib','Pictilisib','Ribociclib','Taselisib'];
  let count = 0;
  await Promise.all(drugs.map(async drug => {
    const url = `${BASE_PATH}/docking/complex/${variantId}_x_${drug}_complex.pdb`;
    if (complexCache.has(url)) { if (complexCache.get(url)) count++; return; }
    try {
      const ok = (await fetch(url, { method: 'HEAD' })).ok;
      complexCache.set(url, ok);
      if (ok) count++;
    } catch { complexCache.set(url, false); }
  }));
  return count;
}

// ── Loader principal ──────────────────────────────────────────────────────
async function loadPipeline() {
  if (state.loaded) return;
  state.loaded = true;

  const [variants, metrics, manifest, runManifest] = await Promise.all([
    loadJSON(DATA.topVariants()),
    loadJSON(DATA.structuralMetrics()),
    loadJSON(DATA.manifestStructures()),
    loadJSON(DATA.runManifest()),
  ]);

  // ── Run badge ────────────────────────────────────────────────────────────
  const pipelineVersion = runManifest?.params?.mlflow_experiment ?? '—';
  const runName         = runManifest?.run_name ?? '—';
  const publishedAt     = runManifest?.published_at?.slice(0, 10) ?? '';
  setText('ps-run-chip', `${pipelineVersion} · ${runName}`);
  setText('ps-dataset-label', `Dataset: ${(runManifest?.params?.study_id ?? 'TCGA-BRCA').toUpperCase()} activo`);

  // ── Datos de variantes ───────────────────────────────────────────────────
  const varList = variants ?? [];
  const metricEntries = Object.entries(metrics ?? {});

  // Hotspot #1
  const top = varList[0];
  const topKey = top ? `${top.hugo_symbol}_${top.protein_change}` : null;
  const topMetric = topKey ? metrics?.[topKey] : null;

  // Clasificación de variantes
  const pathogenic = varList.filter(v => v.classification?.toLowerCase().includes('patog')).length;
  const hotspots   = varList.filter(v => v.classification?.toLowerCase().includes('hotspot')).length;

  // Estructuras
  const structCount = manifest ? Object.keys(manifest).filter(k => !k.endsWith('_WT')).length : 0;
  const totalPossible = varList.length;

  // Métricas docking
  let globalBestScore = null;
  let globalBestDrug  = '—';
  let globalBestVariant = '—';
  let repoCandidates  = 0;

  // Calcular WT scores para Δ
  const wtKeys = Object.keys(metrics ?? {}).filter(k => k.endsWith('_WT'));

  metricEntries.forEach(([id, m]) => {
    if (id.endsWith('_WT')) return;
    const score = bestScore(m);
    if (score !== null && (globalBestScore === null || score < globalBestScore)) {
      globalBestScore   = score;
      globalBestDrug    = bestDrug(m);
      globalBestVariant = id.replace('_', ' ');
    }

    // Candidatos repositionables: cualquier drug con Δ ≤ -0.5
    const gene = id.split('_')[0];
    const wtId = `${gene}_WT`;
    const wtM  = metrics?.[wtId];
    if (wtM?.vina_scores) {
      Object.entries(m.vina_scores ?? {}).forEach(([drug, mutScore]) => {
        const wtScore = safeScore(wtM.vina_scores?.[drug]);
        if (wtScore !== null && safeScore(mutScore) !== null) {
          const delta = safeScore(mutScore) - wtScore;
          if (delta <= -0.5) repoCandidates++;
        }
      });
    }
  });

  // Variante con mayor RMSD activo
  let maxRmsd = 0, maxRmsdId = '—';
  metricEntries.forEach(([id, m]) => {
    if (id.endsWith('_WT')) return;
    const r = parseFloat(m.rmsd_active);
    if (!isNaN(r) && r > maxRmsd) { maxRmsd = r; maxRmsdId = id.replace('_', ' '); }
  });

  // Fármacos únicos testeados
  const drugsSet = new Set();
  metricEntries.forEach(([, m]) => Object.keys(m.vina_scores ?? {}).forEach(d => drugsSet.add(d)));

  // ── KPIs ─────────────────────────────────────────────────────────────────
  setText('ps-kpi-variants', varList.length);
  document.getElementById('ps-kpi-variants-sub').innerHTML =
    pathogenic ? `<span class="ps-badge ps-badge--danger">${pathogenic} Patogénica${pathogenic>1?'s':''}</span>`
               + (hotspots ? ` <span class="ps-badge ps-badge--warn">${hotspots} Hotspot${hotspots>1?'s':''}</span>` : '')
               : '—';

  if (top) {
    setText('ps-kpi-hotspot', `${top.hugo_symbol} ${top.protein_change}`);
    const pct = fmt(top.cohort_percentage);
    setText('ps-kpi-hotspot-sub', `${top.frequency} casos · ${pct}%`);
  }

  setText('ps-kpi-structs',  `${structCount} / ${totalPossible * 2}`);

  setText('ps-kpi-rmsd',     maxRmsd > 0 ? `${maxRmsd.toFixed(2)} Å` : '—');
  setText('ps-kpi-rmsd-sub', maxRmsd > 0 ? maxRmsdId : '');

  const variantsWithDocking = metricEntries.filter(([id,]) => !id.endsWith('_WT')).length;
  setText('ps-kpi-docking-vars', variantsWithDocking || '—');
  setText('ps-kpi-docking-sub',  drugsSet.size ? `AutoDock Vina 1.2.3 · ${drugsSet.size} drugs` : '');

  setText('ps-kpi-affinity',     globalBestScore !== null ? `${globalBestScore.toFixed(3)} kcal/mol` : '—');
  setText('ps-kpi-affinity-sub', globalBestScore !== null ? `${globalBestDrug} → ${globalBestVariant}` : '');

  setText('ps-kpi-repro', repoCandidates || '0');

  // ── Quick access links ────────────────────────────────────────────────────
  document.querySelectorAll('.ps-qlink').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      const view = link.dataset.view;
      document.querySelector(`[data-view="${view}"]`)?.click();
    });
  });

  // ── Timeline ──────────────────────────────────────────────────────────────
  // Inferir estado de cada etapa desde los datos disponibles
  const stageStatus = {
    mutations:  varList.length > 0 ? 'complete' : 'pending',
    variants:   varList.length > 0 ? 'complete' : 'pending',
    structures: structCount > 0    ? (structCount < totalPossible ? 'partial' : 'complete') : 'pending',
    docking:    variantsWithDocking > 0 ? (variantsWithDocking < totalPossible ? 'partial' : 'complete') : 'pending',
    report:     variantsWithDocking > 0 ? 'complete' : 'pending',
  };
  const stageLabel = { complete: '✓ Complete', partial: `${Math.round((structCount/Math.max(totalPossible,1))*100)}%`, pending: '—' };
  const dockPct = totalPossible > 0 ? Math.round((variantsWithDocking / totalPossible) * 100) : 0;
  stageLabel.docking_partial = `${dockPct}%`;

  const timelineEl = document.getElementById('ps-timeline');
  if (timelineEl) {
    timelineEl.innerHTML = STAGES.map((s, i) => {
      const status = stageStatus[s.key] ?? 'pending';
      const labelText = s.key === 'docking' && status === 'partial'
        ? stageLabel.docking_partial
        : stageLabel[status];
      const cls = `ps-stage ps-stage--${status}`;
      const lines = s.label.split('\n');
      return `
        <div class="${cls}">
          <div class="ps-stage-node">${s.id}</div>
          <div class="ps-stage-label">${lines[0]}<br><span>${lines[1] ?? ''}</span></div>
          <div class="ps-stage-status">${labelText}</div>
          ${i < STAGES.length - 1 ? '<div class="ps-stage-connector"></div>' : ''}
        </div>`;
    }).join('');
  }

  // ── Parámetros de la corrida ───────────────────────────────────────────────
  const params = runManifest?.params ?? {};
  const paramRows = [
    { label: 'Study ID',           value: params.study_id ?? '—' },
    { label: 'Genes analizados',   value: (params.genes ?? '').split(',').length + ' genes' },
    { label: 'Max variants/gen',   value: params.max_variants ?? '—' },
    { label: 'Structures mode',    value: params.structures_mode ?? '—' },
    { label: 'Exhaustiveness',     value: params.exhaustiveness ?? '—' },
    { label: 'Num modes (Vina)',    value: params.num_modes ?? '—' },
    { label: 'Box size',           value: params.box_size ? `${params.box_size} Å` : '—' },
    { label: 'Box center mode',    value: params.box_center_mode ?? '—' },
    { label: 'Vina seed',          value: params.vina_seed ?? '—' },
    { label: 'Git commit',         value: runManifest?.git_commit?.slice(0,7) ?? '—' },
    { label: 'Publicado',          value: publishedAt },
    { label: 'Run name',           value: runName },
  ];

  const paramsGrid = document.getElementById('ps-params-grid');
  if (paramsGrid) {
    paramsGrid.innerHTML = paramRows.map(p => `
      <div class="ps-param-row">
        <span class="ps-param-label">${p.label}</span>
        <span class="ps-param-value">${p.value}</span>
      </div>`).join('');
  }

  // ── MLflow block ─────────────────────────────────────────────────────────
  const mlflowBlock = document.getElementById('ps-mlflow-block');
  if (mlflowBlock) {
    const trackingUri = params.mlflow_tracking_uri ?? '—';
    const experiment  = params.mlflow_experiment ?? '—';
    mlflowBlock.innerHTML = `
      <div class="ps-mlflow-row">
        <span class="ps-mlflow-label">Experiment</span>
        <span class="ps-mlflow-value ps-accent">${experiment}</span>
      </div>
      <div class="ps-mlflow-row">
        <span class="ps-mlflow-label">Run name</span>
        <span class="ps-mlflow-value">${runName}</span>
      </div>
      <div class="ps-mlflow-row">
        <span class="ps-mlflow-label">Tracking URI</span>
        <span class="ps-mlflow-value ps-mono">${trackingUri}</span>
      </div>
      <div class="ps-mlflow-row">
        <span class="ps-mlflow-label">Published</span>
        <span class="ps-mlflow-value">${runManifest?.published_at ?? '—'}</span>
      </div>
      <div class="ps-mlflow-row">
        <span class="ps-mlflow-label">Images</span>
        <span class="ps-mlflow-value ps-mono" style="font-size:.75rem;line-height:1.6;">
          ${Object.entries(runManifest?.images ?? {}).map(([k,v]) => `${k}: ${v}`).join('<br>')}
        </span>
      </div>
      <div class="ps-mlflow-row">
        <span class="ps-mlflow-label">Drug catalog</span>
        <span class="ps-mlflow-value ps-mono">${params.drug_catalog ?? '—'}</span>
      </div>`;
  }

  // ── Tabla integrada Top Variants ──────────────────────────────────────────
  const tbody = document.getElementById('ps-tbody-metrics');
  if (tbody) {
    // Contar complejos para cada variante (en paralelo)
    const complexCounts = {};
    await Promise.all(
      varList.map(async v => {
        const id = `${v.hugo_symbol}_${v.protein_change}`;
        complexCounts[id] = await countComplexes(id);
      })
    );

    const top5 = varList.slice(0, 5);
    tbody.innerHTML = top5.map((v, i) => {
      const id  = `${v.hugo_symbol}_${v.protein_change}`;
      const m   = metrics?.[id] ?? {};
      const score = bestScore(m);
      const drug  = bestDrug(m);
      const hasDocking = score !== null;
      const scoreClass = hasDocking ? (score <= -7 ? 'ps-score--good' : score <= -5 ? 'ps-score--mid' : '') : '';
      const clsBadge = v.classification?.toLowerCase().includes('patog')
        ? 'ps-badge ps-badge--danger' : 'ps-badge ps-badge--warn';
      const clsLabel = v.classification ?? '—';

      return `
        <tr>
          <td class="ps-rank-cell">
            <span class="ps-rank">#${i + 1}</span>
            <a href="#" class="ps-gene-link" data-view="structural">${v.hugo_symbol}</a>
          </td>
          <td class="ps-mono">${v.protein_change}</td>
          <td><strong>${v.frequency}</strong></td>
          <td><span class="${clsBadge}">${clsLabel}</span></td>
          <td class="ps-mono ${scoreClass}">${hasDocking ? score.toFixed(3) + ' kcal/mol' : '—'}</td>
          <td>${drug}</td>
          <td>${complexCounts[id] ?? 0} / ${drugsSet.size}</td>
        </tr>`;
    }).join('');

    // Botón View all → vista análisis
    document.getElementById('ps-view-all-btn')?.addEventListener('click', e => {
      e.preventDefault();
      document.querySelector('[data-view="analysis"]')?.click();
    });

    // Links de genes → structural
    document.querySelectorAll('.ps-gene-link').forEach(a => {
      a.addEventListener('click', e => {
        e.preventDefault();
        document.querySelector('[data-view="structural"]')?.click();
      });
    });
  }
}

registerLoader('pipeline', loadPipeline);
