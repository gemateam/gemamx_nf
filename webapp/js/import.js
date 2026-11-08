import {
  DATA, loadJSON, registerLoader, registerReloadFlag,
} from './app.js';

const PAGE_SIZE = 25;
const state = { loaded: false, rows: [], filtered: [], page: 0 };
registerReloadFlag('import', state);

const RAW_COLUMNS = [
  ['patient_id', 'Paciente'],
  ['sample_id', 'Muestra'],
  ['hugo_symbol', 'Gen'],
  ['variant_classification', 'Clasificación'],
  ['protein_change', 'Cambio proteína'],
  ['genomic_dna_change', 'Cambio ADN'],
  ['chromosome', 'Cromosoma'],
  ['start_position', 'Posición'],
  ['mutation_status', 'Estado'],
  ['file_id', 'Archivo fuente'],
];

function pipelineKind(manifest) {
  const experiment = manifest?.params?.mlflow_experiment ?? '';
  const runName = manifest?.run_name ?? '';
  if (experiment.includes('V3') || runName.includes('tcga_brca_hispanic')) return 'v3';
  if (experiment.includes('V2_1')) return 'v2_1';
  if (experiment.includes('V2') || runName.includes('romero')) return 'v2';
  return 'v1';
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = String(text);
  return node;
}

function formatValue(value) {
  if (value == null || value === '') return '—';
  return Array.isArray(value) ? value.join(', ') : String(value);
}

function buildLegacyQuery(kind, manifest, provenance) {
  const params = manifest?.params ?? {};
  if (kind === 'v3') {
    const filter = provenance?.cohort_filter ?? provenance?.filter ?? 'project_id = TCGA-BRCA AND ethnicity = HISPANIC OR LATINO';
    return {
      mode: 'legacy-contract',
      source: 'Bundle ETL etl_tcga',
      cohort_filter: filter,
      files: ['cohort_cases.json', 'somatic_mutations.json', 'clinical_attributes.json'],
      note: 'Esta corrida no guardó data_ingest.json; el filtro se recupera del contrato ETL.',
      bundle_id: provenance?.bundle_id,
    };
  }
  if (kind === 'v2' || kind === 'v2_1') {
    return {
      mode: 'legacy-local-files',
      source: 'Romero-Córdoba 2021 HM (XLSX local)',
      files: [params.romero_maf, params.romero_drivers, params.romero_clinical].filter(Boolean),
      maf_sheet: 'HM maf',
      driver_sheet: 'Driver mutation in HM',
      join: 'Gene/Hugo Symbol, cromosoma, posición, alelo referencia y alelo tumoral',
      filters: {
        genes: params.genes,
        variant_classification_contains: 'missense',
        protein_change_required: true,
        max_variants: params.max_variants,
      },
      note: 'Esta corrida no guardó data_ingest.json; se muestran fuentes y filtros del run_manifest, no un request SQL/API.',
    };
  }
  if (params.mutations_json) {
    return {
      mode: 'legacy-snapshot',
      source: params.mutations_json,
      filters: { genes: params.genes, variant_classification_contains: 'missense', max_variants: params.max_variants },
      note: 'Esta corrida usó un snapshot local; no hubo query de red y no guardó data_ingest.json.',
    };
  }
  const study = params.study_id ?? 'brca_tcga';
  return {
    mode: 'legacy-cbioportal',
    source: `cBioPortal REST · ${study}`,
    requests: [
      { method: 'GET', url: `/studies/${study}/sample-lists`, purpose: 'Enumerar listas de muestras.' },
      { method: 'GET', url: '/sample-lists/{sampleListId}/sample-ids', purpose: 'Elegir lista con “all” (o primera disponible) y leer sus muestras.' },
      { method: 'POST', url: `/molecular-profiles/${study}_mutations/mutations/fetch`, body: { sampleIds: 'lotes de hasta 500 IDs' }, purpose: 'Descargar las mutaciones de las muestras seleccionadas.' },
    ],
    filters: { genes: params.genes, variant_classification_contains: 'missense', protein_change_required: true, max_variants: params.max_variants },
    note: 'Esta corrida no guardó data_ingest.json; los endpoints y filtros se reconstruyen del código/parámetros, no incluyen el sampleListId ni payloads originales.',
  };
}

function appendQueryDetails(query) {
  const container = document.getElementById('import-query-details');
  container.replaceChildren();
  const sections = [];
  if (query.cohort_filter) sections.push(['Filtro de cohorte', query.cohort_filter]);
  if (query.bundle_id) sections.push(['Bundle', query.bundle_id]);
  if (query.files?.length) sections.push(['Archivos fuente', query.files.join('\n')]);
  if (query.inputs?.length) sections.push(['Entradas', query.inputs.map(item => `${item.file} · hoja ${item.sheet} · ${item.selection}`).join('\n')]);
  if (query.join) sections.push(['Cruce', query.join]);
  if (query.filters) sections.push(['Filtros de priorización', JSON.stringify(query.filters, null, 2)]);
  for (const [title, value] of sections) {
    const block = el('div', 'import-query-block');
    block.append(el('strong', '', title), el('pre', '', value));
    container.append(block);
  }

  const requests = query.requests ?? [];
  requests.forEach((request, index) => {
    const details = el('details', 'import-request');
    const requestUrl = request.url ?? request.endpoint ?? '(sin endpoint)';
    const requestMethod = (request.method ?? 'QUERY').toUpperCase();
    const label = `${index + 1}. ${requestMethod} ${requestUrl}`;
    details.append(el('summary', '', label));
    const payload = { ...(request.request !== undefined ? { request: request.request } : {}), ...(request.body !== undefined ? { body: request.body } : {}), ...(request.response_records !== undefined ? { response_records: request.response_records } : {}), ...(request.purpose ? { purpose: request.purpose } : {}) };
    details.append(el('pre', 'import-query-payload', JSON.stringify(payload, null, 2)));
    container.append(details);
  });

  if (query.note) container.append(el('p', 'import-query-note', query.note));
}

function renderSummary(rows, manifest, stats, provenance, ingest) {
  const host = document.getElementById('import-summary');
  host.replaceChildren();
  const params = manifest?.params ?? {};
  const source = ingest?.query?.source ?? ingest?.query?.bundle?.bundle_id ?? provenance?.bundle_id ?? ingest?.source ?? params.study_id ?? 'Fuente no identificada';
  const cards = [
    ['Pipeline', params.mlflow_experiment ?? manifest?.pipeline_version ?? '—'],
    ['Fuente', source],
    ['Registros crudos', ingest?.counts?.raw_mutation_records ?? rows.length],
    ['Cohorte', ingest?.counts?.cohort_units ?? stats?.total_samples ?? provenance?.cohort_total_cases ?? '—'],
    ['Release', ingest?.query?.bundle?.gdc_data_release ?? provenance?.gdc_data_release ?? '—'],
  ];
  cards.forEach(([label, value]) => {
    const card = el('div', 'import-summary-item');
    card.append(el('span', 'import-summary-label', label), el('strong', 'import-summary-value', value));
    host.append(card);
  });
}

function filteredRows() {
  return state.filtered;
}

function renderPage() {
  const filtered = filteredRows();
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  state.page = Math.min(state.page, totalPages - 1);
  const start = state.page * PAGE_SIZE;
  const pageRows = filtered.slice(start, start + PAGE_SIZE);
  const head = document.getElementById('import-table-head');
  const body = document.getElementById('import-table-body');
  head.replaceChildren();
  body.replaceChildren();

  const headerRow = el('tr');
  RAW_COLUMNS.forEach(([, label]) => headerRow.append(el('th', '', label)));
  headerRow.append(el('th', '', 'Registro completo'));
  head.append(headerRow);

  if (!pageRows.length) {
    const row = el('tr');
    const cell = el('td', 'import-empty', state.rows.length ? 'Sin coincidencias.' : 'La corrida no contiene raw_mutations.json.');
    cell.colSpan = RAW_COLUMNS.length + 1;
    row.append(cell);
    body.append(row);
  }

  pageRows.forEach(record => {
    const row = el('tr');
    RAW_COLUMNS.forEach(([key]) => row.append(el('td', '', formatValue(record[key]))));
    const detailCell = el('td');
    const details = el('details', 'import-record-details');
    details.append(el('summary', '', 'JSON'));
    details.append(el('pre', '', JSON.stringify(record, null, 2)));
    detailCell.append(details);
    row.append(detailCell);
    body.append(row);
  });

  document.getElementById('import-raw-count').textContent = `${filtered.length.toLocaleString()} de ${state.rows.length.toLocaleString()} registros`;
  document.getElementById('import-page-label').textContent = `Página ${state.page + 1} de ${totalPages}`;
  document.getElementById('import-prev').disabled = state.page === 0;
  document.getElementById('import-next').disabled = state.page >= totalPages - 1;
}

async function loadImport() {
  const [rows, manifest, stats, provenance, ingest] = await Promise.all([
    loadJSON(DATA.rawMutations()),
    loadJSON(DATA.runManifest()),
    loadJSON(DATA.mutationStats()),
    loadJSON(DATA.contractProvenance()),
    loadJSON(DATA.dataIngest()),
  ]);
  const kind = pipelineKind(manifest);
  const params = manifest?.params ?? {};
  const query = ingest?.query ?? buildLegacyQuery(kind, manifest, provenance);
  const sourceMode = ingest?.mode ?? query.mode;
  document.getElementById('import-subtitle').textContent = `${manifest?.run_name ?? 'Corrida vigente'} · ${manifest?.pipeline_version ?? params.mlflow_experiment ?? 'pipeline no identificado'}`;
  document.getElementById('import-query-kind').textContent = sourceMode ?? 'Criterios reconstruidos';
  document.getElementById('import-query-summary').textContent = query.source ?? query.cohort_filter ?? 'Fuente de datos no declarada en esta corrida.';
  appendQueryDetails(query);
  state.rows = Array.isArray(rows) ? rows : [];
  state.filtered = state.rows;
  state.page = 0;
  renderSummary(state.rows, manifest, stats, provenance, ingest);
  renderPage();
}

function initialize() {
  document.getElementById('import-search').addEventListener('input', event => {
    const query = event.target.value.trim().toLowerCase();
    state.filtered = query
      ? state.rows.filter(record => JSON.stringify(record).toLowerCase().includes(query))
      : state.rows;
    state.page = 0;
    renderPage();
  });
  document.getElementById('import-prev').addEventListener('click', () => { state.page--; renderPage(); });
  document.getElementById('import-next').addEventListener('click', () => { state.page++; renderPage(); });
}

initialize();
registerLoader('import', loadImport);
