/**
 * drug-sources.js — Conexiones en vivo a bases de datos de fármacos
 *
 * APIs públicas usadas:
 *   ChEMBL  → https://www.ebi.ac.uk/chembl/api/data/  (REST, sin auth)
 *   CiViC   → https://civicdb.org/api/graphql          (GraphQL v2, sin auth)
 *
 * DrugBank y OncoKB requieren licencia/token → no se consultan en vivo,
 * se muestran como "Pendiente" con enlace al registro.
 */

// ── Caché de sesión para evitar llamadas repetidas ─────────────────────────
const _cache = new Map();
async function fetchCached(url, opts = {}) {
  if (_cache.has(url)) return _cache.get(url);
  try {
    const res = await fetch(url, opts);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _cache.set(url, data);
    return data;
  } catch (e) {
    console.warn('[DrugSources]', url, e.message);
    return null;
  }
}

// ── ChEMBL ─────────────────────────────────────────────────────────────────
const CHEMBL_BASE = 'https://www.ebi.ac.uk/chembl/api/data';

/**
 * Obtiene datos de molécula desde ChEMBL por chembl_id.
 * Devuelve: { pref_name, max_phase, usan_stem_definition, withdrawn_flag,
 *             first_approval, molecule_synonyms, molecule_type }
 */
export async function fetchChEMBLMolecule(chemblId) {
  if (!chemblId) return null;
  return fetchCached(`${CHEMBL_BASE}/molecule/${chemblId}.json`);
}

/**
 * Obtiene indicaciones clínicas de un fármaco desde ChEMBL.
 * Devuelve array de { efo_term, max_phase_for_ind, mesh_heading }
 */
export async function fetchChEMBLIndications(chemblId) {
  if (!chemblId) return [];
  const data = await fetchCached(
    `${CHEMBL_BASE}/drug_indication.json?molecule_chembl_id=${chemblId}&limit=20`
  );
  return data?.drug_indications ?? [];
}

/**
 * Enriquece el catálogo local con datos de ChEMBL.
 * @param {Array} drugs  — [{ name, chembl_id, target, status, smiles }]
 * @returns {Promise<Array>}  — misma lista con campos adicionales de ChEMBL
 */
export async function enrichWithChEMBL(drugs) {
  return Promise.all(drugs.map(async drug => {
    if (!drug.chembl_id) return drug;
    const mol = await fetchChEMBLMolecule(drug.chembl_id);
    if (!mol) return drug;

    // Fase clínica: 4=FDA, 3=NDA/BLA, 2=Phase II, 1=Phase I, null=pre-clinical
    const phase = parseFloat(mol.max_phase) || 0;
    const phaseLabel = phase >= 4 ? 'FDA Approved'
                     : phase >= 3 ? 'Phase III'
                     : phase >= 2 ? 'Phase II'
                     : phase >= 1 ? 'Phase I'
                     : 'Pre-clinical';

    return {
      ...drug,
      chembl: {
        pref_name:       mol.pref_name,
        max_phase:       mol.max_phase,
        phase_label:     phaseLabel,
        mechanism:       mol.usan_stem_definition,
        withdrawn:       mol.withdrawn_flag,
        first_approval:  mol.first_approval,
        mol_type:        mol.molecule_type,
        synonyms:        (mol.molecule_synonyms ?? [])
                           .filter(s => s.syn_type === 'INN' || s.syn_type === 'USAN')
                           .map(s => s.molecule_synonym)
                           .slice(0, 3),
        url: `https://www.ebi.ac.uk/chembl/compound_report_card/${drug.chembl_id}/`,
      },
    };
  }));
}

// ── CiViC ──────────────────────────────────────────────────────────────────
const CIVIC_GQL = 'https://civicdb.org/api/graphql';

/**
 * Consulta CiViC por nombre de gen + nombre de variante proteica.
 * @param {string} geneSymbol   — ej. "PIK3CA"
 * @param {string} variantName  — ej. "H1047R"
 * @returns {Promise<Object|null>} — { variantId, evidenceCount, diseases[], therapies[], civicUrl }
 */
export async function fetchCiVICVariant(geneSymbol, variantName) {
  const cacheKey = `civic:${geneSymbol}:${variantName}`;
  if (_cache.has(cacheKey)) return _cache.get(cacheKey);

  const query = `{
    browseVariants(variantName: "${variantName}", featureName: "${geneSymbol}", first: 3) {
      nodes {
        id
        name
        featureName
        evidenceItemCount
        diseases { id name }
        therapies { id name }
      }
    }
  }`;

  try {
    const res = await fetch(CIVIC_GQL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const nodes = json?.data?.browseVariants?.nodes ?? [];

    // Filtrar nodo que corresponda exactamente al gen y variante
    const match = nodes.find(n =>
      n.featureName?.toUpperCase() === geneSymbol.toUpperCase() &&
      n.name?.toUpperCase() === variantName.toUpperCase()
    ) ?? nodes[0] ?? null;

    if (!match) { _cache.set(cacheKey, null); return null; }

    const result = {
      variantId:     match.id,
      evidenceCount: match.evidenceItemCount,
      diseases:      (match.diseases ?? []).map(d => d.name),
      therapies:     (match.therapies ?? []).map(t => t.name),
      civicUrl:      `https://civicdb.org/links/variant/${match.id}`,
    };
    _cache.set(cacheKey, result);
    return result;
  } catch (e) {
    console.warn('[DrugSources] CiViC error:', e.message);
    _cache.set(cacheKey, null);
    return null;
  }
}

// ── Renderizado del panel de fuentes ───────────────────────────────────────
/**
 * Actualiza el bloque .drug-sources-card con datos en vivo.
 * Se llama desde docking.js al cargar una variante.
 *
 * @param {string}  geneSymbol  — ej. "PIK3CA"
 * @param {string}  variantName — ej. "H1047R"
 * @param {Array}   drugs       — catálogo local enriquecido con enrichWithChEMBL()
 */
export async function renderDrugSources(geneSymbol, variantName, drugs) {
  // ── Panel de estado de fuentes ────────────────────────────────────────
  const noteEl = document.querySelector('.drug-sources-note');
  if (noteEl) {
    noteEl.innerHTML = `
      <p><strong>Drug ranking:</strong> catálogo local GEMA con metadatos de 
         <a href="https://www.ebi.ac.uk/chembl/" target="_blank" rel="noopener" class="ds-link">ChEMBL</a> y 
         <a href="https://go.drugbank.com/" target="_blank" rel="noopener" class="ds-link">DrugBank</a>. 
         Fase clínica actualizada en vivo desde ChEMBL.
      </p>
      <p><strong>Validación clínica:</strong> 
         <a href="https://civicdb.org" target="_blank" rel="noopener" class="ds-link">CiViC</a> — 
         consultando evidencia para <strong>${geneSymbol} ${variantName}</strong>…
      </p>
      <p><strong>VICC Meta-knowledgebase:</strong> pendiente de integración.</p>
      <p><strong>Disponibilidad México (IMSS/CAUSES):</strong> pendiente como filtro verificable.</p>`;
  }

  // ── Consultas en paralelo ────────────────────────────────────────────
  const [civicData, ...drugData] = await Promise.all([
    fetchCiVICVariant(geneSymbol, variantName),
    ...drugs.map(d => fetchChEMBLMolecule(d.chembl_id).then(mol => ({ drug: d, mol }))),
  ]);

  // ── Actualizar nota de CiViC ──────────────────────────────────────────
  if (noteEl) {
    const civicLine = civicData
      ? `<strong>CiViC</strong>: ${civicData.evidenceCount} ítems de evidencia para 
         <strong>${geneSymbol} ${variantName}</strong> · 
         ${civicData.diseases.slice(0, 3).join(', ')} · 
         <a href="${civicData.civicUrl}" target="_blank" rel="noopener" class="ds-link">Ver en CiViC →</a>`
      : `<strong>CiViC</strong>: sin evidencia registrada para ${geneSymbol} ${variantName}.`;

    const lines = noteEl.querySelectorAll('p');
    if (lines[1]) lines[1].innerHTML = `<strong>Validación clínica:</strong> ${civicLine}`;
  }

  // ── Tarjetas de fuentes ───────────────────────────────────────────────
  const grid = document.querySelector('.drug-sources-grid');
  if (!grid) return;

  // Estadísticas del catálogo local
  const fdaCount   = drugs.filter(d => d.status === 'FDA').length;
  const trialCount = drugs.filter(d => d.status === 'Trial').length;

  // Fase máxima por fármaco desde ChEMBL (para la nota dinámica)
  const phaseMap = {};
  drugData.forEach(({ drug, mol }) => {
    if (mol) phaseMap[drug.name] = parseFloat(mol.max_phase) || 0;
  });
  const fda4Count = Object.values(phaseMap).filter(p => p >= 4).length;

  // Terapias confirmadas en CiViC que coinciden con el catálogo
  const civicTherapiesInCatalog = civicData
    ? drugs.filter(d => civicData.therapies.some(t =>
        t.toLowerCase().includes(d.name.toLowerCase()) ||
        d.name.toLowerCase().includes(t.toLowerCase())
      )).map(d => d.name)
    : [];

  grid.innerHTML = `
    <!-- Catálogo GEMA -->
    <div class="drug-source-card">
      <div class="ds-title">Catálogo local GEMA</div>
      <div class="ds-status ds-status--active">Activo · ${drugs.length} fármacos</div>
      <div class="ds-desc">
        Fuente primaria del ranking actual. Reúne ${drugs.length} fármacos curados
        para el pipeline de docking AutoDock Vina 1.2.3.
        <br><span style="color:#94a3b8;font-size:.78rem;">
          ${fdaCount} aprobados FDA · ${trialCount} en ensayo clínico
        </span>
      </div>
      <div class="ds-tags">
        <span class="ds-tag ds-tag--fda">FDA: ${fdaCount}</span>
        <span class="ds-tag ds-tag--live">Trial: ${trialCount}</span>
      </div>
    </div>

    <!-- ChEMBL -->
    <div class="drug-source-card">
      <div class="ds-title">ChEMBL
        <a href="https://www.ebi.ac.uk/chembl/" target="_blank" rel="noopener"
           class="ds-link" style="font-size:.75rem;margin-left:.4rem;">↗</a>
      </div>
      <div class="ds-status ds-status--live">✓ Conectado en vivo</div>
      <div class="ds-desc">
        Fases clínicas y mecanismo de acción actualizados en tiempo real.
        <br><span style="color:#94a3b8;font-size:.78rem;">
          ${fda4Count} fármacos con fase 4 (aprobación) en el catálogo · EBI EMBL-EBI
        </span>
      </div>
      <div class="ds-tags">
        <span class="ds-tag ds-tag--live">Live REST API</span>
        ${fda4Count > 0 ? `<span class="ds-tag ds-tag--fda">Fase 4: ${fda4Count}</span>` : ''}
      </div>
    </div>

    <!-- DrugBank -->
    <div class="drug-source-card">
      <div class="ds-title">DrugBank
        <a href="https://go.drugbank.com/" target="_blank" rel="noopener"
           class="ds-link" style="font-size:.75rem;margin-left:.4rem;">↗</a>
      </div>
      <div class="ds-status ds-status--restricted">Licencia / API requerida</div>
      <div class="ds-desc">
        Puede enriquecer el catálogo con interacciones, metabolismo y contraindicaciones.
        No se consulta como fuente abierta en vivo en GEMA.
      </div>
      <div class="ds-tags">
        <span class="ds-tag ds-tag--restricted">Acceso restringido</span>
      </div>
    </div>

    <!-- CiViC -->
    <div class="drug-source-card">
      <div class="ds-title">CiViC
        ${civicData ? `<a href="${civicData.civicUrl}" target="_blank" rel="noopener"
           class="ds-link" style="font-size:.75rem;margin-left:.4rem;">↗ Ver ${geneSymbol} ${variantName}</a>` : ''}
      </div>
      <div class="ds-status ${civicData ? 'ds-status--active' : 'ds-status--restricted'}">
        ${civicData ? `✓ ${civicData.evidenceCount} ítems de evidencia` : 'Sin evidencia registrada'}
      </div>
      <div class="ds-desc">
        ${civicData
          ? `Terapias validadas en catálogo GEMA: <strong>${civicTherapiesInCatalog.length > 0 ? civicTherapiesInCatalog.join(', ') : 'ninguna directamente'}</strong>.
             <br><span style="color:#94a3b8;font-size:.78rem;">
               Enfermedades: ${civicData.diseases.slice(0, 3).join(' · ')}
             </span>`
          : `Consulta opcional para validación clínica pública de variantes de cáncer.`}
      </div>
      <div class="ds-tags">
        <span class="ds-tag ds-tag--${civicData ? 'in-use' : 'restricted'}">
          ${civicData ? 'En uso · GraphQL v2' : 'Sin datos'}
        </span>
        ${civicTherapiesInCatalog.length > 0
          ? `<span class="ds-tag ds-tag--fda">${civicTherapiesInCatalog.length} overlap</span>` : ''}
      </div>
    </div>`;
}

// ── Parser del CSV del catálogo local ─────────────────────────────────────
export function parseDrugCatalogCSV(csvText) {
  const lines = csvText.trim().split('\n');
  const headers = lines[0].split(',');
  return lines.slice(1).map(line => {
    const parts = line.split(',');
    return Object.fromEntries(headers.map((h, i) => [h.trim(), (parts[i] ?? '').trim()]));
  });
}
