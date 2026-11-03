/**
 * proteins.js — fichas de proteína para la vista de Exploración.
 *
 * Cada fila de la tabla muestra el nombre corto de la proteína y puede
 * expandir una ficha detallada en español con función, actividad catalítica,
 * regulación y relevancia clínica.
 *
 * Para los genes con ficha curada se usa información local (sin red).
 * Para el resto se consulta UniProt REST una sola vez y se cachea el
 * resultado; si la consulta falla se muestra una ficha mínima.
 */

// ── Nombres cortos para la columna PROTEÍNA ────────────────────────────────
export const PROTEIN_NAMES = {
  PIK3CA: 'PI3Kα',
  TP53:   'p53',
  AKT1:   'AKT1',
  ERBB2:  'HER2',
  PTEN:   'PTEN',
  GATA3:  'GATA3',
  MAP3K1: 'MEKK1',
  BRCA1:  'BRCA1',
  BRCA2:  'BRCA2',
  CDH1:   'E-cadherina',
  RB1:    'pRB',
  ARID1A: 'BAF250A',
  SF3B1:  'SF3B1',
  KMT2C:  'MLL3',
  CBFB:   'CBFβ',
  EGFR:   'EGFR',
  ERBB4:  'HER4',
  ALK:    'ALK',
  MET:    'MET',
  KMT2A:  'MLL1',
  RUNX1:  'RUNX1',
  TSC1:   'Hamartina',
  TSC2:   'Tuberina',
  STK11:  'LKB1',
  SMAD4:  'SMAD4',
  NFE2L2: 'NRF2',
  CTNNB1: 'β-catenina',
  IDH1:   'IDH1',
  IDH2:   'IDH2',
  VHL:    'VHL',
  APC:    'APC',
  BRAF:   'BRAF',
  KRAS:   'KRAS',
  NRAS:   'NRAS',
  HRAS:   'HRAS',
  ATM:    'ATM',
  CHEK2:  'CHK2',
  PALB2:  'PALB2',
  RAD51C: 'RAD51C',
  BARD1:  'BARD1',
  MSH2:   'MSH2',
  MSH6:   'MSH6',
  MLH1:   'MLH1',
  PMS2:   'PMS2',
};

export function proteinDisplayName(gene) {
  if (!gene || gene === 'Unknown') return 'No identificada';
  return PROTEIN_NAMES[gene] ?? gene;
}

// ── Fichas curadas (español) ───────────────────────────────────────────────
// Textos redactados a partir de UniProt, COSMIC y revisiones de la vía
// PI3K/AKT/mTOR. La longitud corresponde a la isoforma canónica.
export const PROTEIN_INFO = {
  PIK3CA: {
    name: 'PI3Kα',
    fullName: 'Fosfatidilinositol 4,5-bisfosfato 3-cinasa, subunidad catalítica alfa (p110α)',
    type: 'Cinasa lipídica · PI3K clase IA',
    length: 1068,
    localization: 'Citoplasma; se recluta a la membrana plasmática',
    function:
      'Subunidad catalítica de PI3K clase IA. Convierte PIP2 en PIP3 en la cara interna de la membrana, generando un segundo mensajero que recluta proteínas con dominio PH, como AKT y PDK1. Regula supervivencia, crecimiento, proliferación, metabolismo y migración celular.',
    catalytic:
      'Fosforila el grupo hidroxilo en posición 3 del anillo de fosfatidilinositol 4,5-bisfosfato (PIP2) para producir fosfatidilinositol 3,4,5-trisfosfato (PIP3).',
    regulation:
      'Se une a la subunidad reguladora p85α (PIK3R1), que mantiene la enzima en estado autoinhibido. La activación de receptores tirosina cinasa o RAS libera esa inhibición y recluta PI3K a la membrana. PTEN revierte la señal al desfosforilar PIP3.',
    disease:
      'Mutaciones activadoras frecuentes en cáncer de mama: E542K y E545K (dominio helicoidal) y H1047R (dominio cinasa). Confieren activación constitutiva de la vía PI3K/AKT/mTOR y son diana de inhibidores como alpelisib.',
    domains:
      'Unión a p85 (1–108) · ABD (109–309) · RBD (310–420) · C2 (421–650) · helicoidal (651–800) · cinasa (801–1068).',
    uniprot: 'P42336',
  },

  TP53: {
    name: 'p53',
    fullName: 'Proteína supresora de tumores p53 (TP53)',
    type: 'Factor de transcripción',
    length: 393,
    localization: 'Núcleo; transita entre núcleo y citoplasma',
    function:
      'Factor de transcripción maestro de la respuesta al daño del ADN. Induce parada del ciclo celular, reparación, senescencia y apoptosis. Mantiene la estabilidad genómica y es el gen más frecuentemente mutado en cáncer.',
    catalytic:
      'No posee actividad enzimática; actúa como factor de transcripción secuencia-específico. Se une a elementos de respuesta (p53 RE) y activa genes como CDKN1A (p21), MDM2, BAX y PUMA.',
    regulation:
      'Se mantiene a niveles bajos por MDM2, que lo ubiquitina y degrada. El daño al ADN activa ATM/ATR y CHK1/2, que estabilizan p53 por fosforilación. Forma tetrámeros mediante su dominio de oligomerización.',
    disease:
      'Mutaciones missense en el dominio de unión al ADN (R175, R248, R273, R282) producen pérdida de función y, a menudo, ganancia de función oncogénica. R248Q/W y R273H son hotspots.',
    domains:
      'TAD (1–61) · PRD (62–94) · dominio de unión al ADN (95–288) · tetramerización (323–356) · CTD (357–393).',
    uniprot: 'P04637',
  },

  AKT1: {
    name: 'AKT1',
    fullName: 'RAC-alpha serina/treonina cinasa (AKT1)',
    type: 'Serina/treonina cinasa · efector de PI3K',
    length: 480,
    localization: 'Citoplasma; membrana plasmática; núcleo',
    function:
      'Efector central de PI3K. Promueve supervivencia, crecimiento, proliferación, metabolismo de glucosa y angiogénesis. Fosforila sustratos como FOXO, GSK3β, TSC2, PRAS40, eNOS y MDM2.',
    catalytic:
      'Fosforila residuos de serina/treonina en motivos RXRXXS/T. Su activación completa requiere fosforilación en Thr308 (PDK1) y Ser473 (mTORC2).',
    regulation:
      'El dominio PH (1–108) se une a PIP3 y recluta AKT a la membrana. PTEN y PHLPP desfosforilan PIP3 y AKT, respectivamente. La mutación E17K en el dominio PH aumenta la unión a PIP3 y produce activación constitutiva independiente de PI3K.',
    disease:
      'E17K es la mutación activadora más frecuente en mama y otros tumores; también se describen amplificaciones. Inhibidores en desarrollo clínico: capivasertib, ipatasertib y miransertib.',
    domains:
      'Dominio PH (1–108) · dominio cinasa (150–408) · región hidrofóbica C-terminal (409–480).',
    uniprot: 'P31749',
  },

  ERBB2: {
    name: 'HER2',
    fullName: 'Receptor tirosina cinasa ERBB2 (HER2/neu)',
    type: 'Receptor tirosina cinasa · familia EGFR',
    length: 1255,
    localization: 'Membrana plasmática',
    function:
      'Receptor de la familia EGFR sin ligando conocido. Heterodimeriza con EGFR, ERBB3 y ERBB4 y amplifica señales de proliferación y supervivencia a través de MAPK y PI3K/AKT.',
    catalytic:
      'Posee actividad tirosina cinasa intrínseca; autofosforila residuos del dominio citoplasmático que sirven de anclaje a adaptadores como GRB2 y PI3K.',
    regulation:
      'Se activa por sobreexpresión, amplificación génica o mutaciones. ERBB3 es el compañero preferente porque posee sitios de unión a PI3K. Inhibidores: trastuzumab, pertuzumab, lapatinib, neratinib y tucatinib.',
    disease:
      'Amplificación en ~20% de carcinomas de mama (HER2-positivo). Mutaciones activadoras en el dominio cinasa (V777L, S310F) aparecen en cáncer de mama HER2-negativo.',
    domains:
      'Dominio extracelular I–IV (1–652) · transmembrana (653–675) · yuxtamembrana (676–712) · cinasa (713–966) · cola C-terminal (967–1255).',
    uniprot: 'P04626',
  },

  PTEN: {
    name: 'PTEN',
    fullName: 'Fosfatasa y homólogo de tensina (PTEN)',
    type: 'Fosfatasa lipídica · supresor tumoral',
    length: 403,
    localization: 'Citoplasma; membrana; núcleo',
    function:
      'Supresor tumoral que antagoniza la vía PI3K/AKT. Desfosforila PIP3 a PIP2 y regula proliferación, supervivencia, migración y reparación del ADN.',
    catalytic:
      'Fosfatasa de fosfatidilinositol 3,4,5-trisfosfato (PIP3) con un motivo catalítico C2. También posee actividad proteína fosfatasa, aunque su función tumoral principal es lipídica.',
    regulation:
      'Se recluta a la membrana por su dominio C2 y se regula por fosforilación, ubiquitinación y localización subcelular. La pérdida de PTEN aumenta PIP3 y activa AKT.',
    disease:
      'Mutaciones nonsense, frameshift y missense en el dominio fosfatasa (C124S, R130Q, R173C) y deleciones. Es uno de los genes más mutados en cáncer de mama y endometrio.',
    domains:
      'Dominio de unión a PIP2 (1–185) · dominio fosfatasa (186–351) · dominio C2 (352–403).',
    uniprot: 'P60484',
  },

  GATA3: {
    name: 'GATA3',
    fullName: 'Factor de transcripción GATA3',
    type: 'Factor de transcripción con dedos de zinc',
    length: 443,
    localization: 'Núcleo',
    function:
      'Regulador maestro del linaje luminal mamario. Controla la diferenciación, la identidad epitelial y la expresión de receptores hormonales (ESR1, PGR).',
    catalytic:
      'Sin actividad enzimática; se une al ADN mediante dos dedos de zinc y recluta coactivadores o co-represores para remodelar la cromatina.',
    regulation:
      'Se regula por la vía ERα y por factores de transcripción luminales. Sus mutaciones pueden alterar la unión al ADN o la transactivación.',
    disease:
      'Mutaciones en el segundo dedo de zinc y en regiones reguladoras se asocian a cáncer de mama luminal, especialmente en tumores ER-positivos.',
    domains:
      'Dominio de transactivación (1–70) · dedos de zinc (264–287 y 294–317) · región C-terminal.',
    uniprot: 'P23771',
  },

  MAP3K1: {
    name: 'MEKK1',
    fullName: 'Cinasa de cinasa de cinasa 1 activada por mitógenos (MAP3K1)',
    type: 'Serina/treonina cinasa · cascada MAPK',
    length: 1512,
    localization: 'Citoplasma; membrana; núcleo',
    function:
      'Cinasa de la cascada MAPK. Activa JNK y ERK a través de MKK4/MKK7 y regula apoptosis, proliferación y respuesta al estrés. También participa en la vía de TGF-β.',
    catalytic:
      'Fosforila y activa MKK4/MKK7 (JNK) y, en menor medida, MKK1/2 (ERK). Su dominio cinasa está en el extremo C-terminal.',
    regulation:
      'Se regula por autoinhibición intramolecular, ubiquitinación y fosforilación. Forma complejos con TRAF2 y otras proteínas adaptadoras.',
    disease:
      'Mutaciones de pérdida de función en el dominio cinasa y sitios de empalme son frecuentes en cáncer de mama luminal y se asocian con mejor pronóstico.',
    domains:
      'Dominio de unión a proteínas adaptadoras (1–300) · región rica en serina/prolina · dominio cinasa (1317–1493).',
    uniprot: 'Q13233',
  },
};

// ── Caché de consultas a UniProt ───────────────────────────────────────────
const uniProtCache = new Map();

function emptyInfo(gene) {
  const unknown = !gene || gene === 'Unknown';
  return {
    name: proteinDisplayName(gene),
    fullName: unknown ? 'Gen no identificado en la anotación' : gene,
    type: '',
    length: null,
    localization: null,
    function: null,
    catalytic: null,
    regulation: null,
    disease: null,
    domains: null,
    uniprot: null,
    curated: false,
    pending: !unknown,
    unknown,
  };
}

/** Ficha inmediata: curada si existe; si no, marcador pendiente de UniProt. */
export function getProteinInfo(gene) {
  const curated = PROTEIN_INFO[gene];
  if (curated) return { ...curated, curated: true, pending: false, unknown: false };
  return emptyInfo(gene);
}

/**
 * Consulta UniProt REST para genes sin ficha curada (una sola vez por gen).
 * Devuelve null si no hay resultado o si la red falla.
 */
export async function fetchProteinInfo(gene) {
  if (!gene || gene === 'Unknown' || PROTEIN_INFO[gene]) return null;
  if (uniProtCache.has(gene)) return uniProtCache.get(gene);

  const promise = (async () => {
    try {
      const query = encodeURIComponent(
        `gene_exact:${gene} AND organism_id:9606 AND reviewed:true`
      );
      const fields = 'accession,protein_name,length,cc_function,cc_catalytic_activity,cc_subcellular_location';
      const url = `https://rest.uniprot.org/uniprotkb/search?query=${query}&fields=${fields}&format=json&size=1`;
      const res = await fetch(url, { headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const entry = json?.results?.[0];
      if (!entry) return null;

      const comments = entry.comments ?? [];
      const commentText = (type) => {
        const c = comments.find(x => x.commentType === type);
        if (!c) return null;
        if (type === 'CATALYTIC ACTIVITY') {
          const reaction = c.reaction?.name?.value ?? c.reaction?.name;
          return reaction ?? null;
        }
        if (type === 'SUBCELLULAR LOCATION') {
          const locs = (c.subcellularLocations ?? [])
            .map(l => l.location?.value)
            .filter(Boolean);
          return locs.length ? [...new Set(locs)].join('; ') : null;
        }
        const texts = (c.texts ?? []).map(t => t.value).filter(Boolean);
        return texts.length ? texts.join(' ') : null;
      };

      const info = {
        ...emptyInfo(gene),
        name: proteinDisplayName(gene),
        fullName: entry.proteinDescription?.recommendedName?.fullName?.value
          ?? entry.proteinDescription?.submissionNames?.[0]?.fullName?.value
          ?? gene,
        type: 'Proteína humana revisada (UniProt)',
        length: entry.sequence?.length ?? null,
        localization: commentText('SUBCELLULAR LOCATION'),
        function: commentText('FUNCTION'),
        catalytic: commentText('CATALYTIC ACTIVITY'),
        regulation: null,
        disease: null,
        domains: null,
        uniprot: entry.primaryAccession ?? null,
        curated: false,
        pending: false,
        unknown: false,
        source: 'UniProt',
      };
      return info;
    } catch (e) {
      console.warn(`[proteins] UniProt no disponible para ${gene}:`, e);
      return null;
    }
  })();

  uniProtCache.set(gene, promise);
  return promise;
}
