# Contrato de Datos V3 — TCGA-BRCA Hispano/Latino

**Versión del contrato:** `2.0.0`
**Estado:** borrador normativo (reemplaza a `1.2.0`)
**Productor:** `D:\ProyectosIA\etl_tcga` (medallón TCGA: bronze → silver → gold)
**Consumidor:** `D:\ProyectosIA\gemamx_nf` (Nextflow DSL2 → estructuras → docking → MLflow → SPA)
**Fuente de verdad:** GDC Open Access, proyecto `TCGA-BRCA`
**Última auditoría:** [`V3_DNA_AUDIT.md`](V3_DNA_AUDIT.md)

> **Principio de diseño:** los dos proyectos siguen siendo independientes.
> Este documento es el único acoplamiento: un bundle JSON inmutable, versionado
> y validable. El ETL no importa código de GEMAMX y GEMAMX no se conecta a la
> base de datos ni al repositorio del ETL.

---

## 0. Resumen de cambios frente a `1.2.0`

| Cambio | Motivo |
|---|---|
| El ADN sale del medallón (`silver.mutations` / Parquet), no de `/ssms` | El exportador anterior no usaba la tabla de mutaciones del ETL |
| `patient_id` es la llave clínica; `sample_id` deja de ser llave | La clínica es a nivel paciente; un paciente puede tener varias muestras |
| Una fila por `(patient_id, variant_id)` | Evita dobles conteos por muestra y frecuencias infladas |
| Se agregan `variant_id`, alelos, profundidades, `filter_status`, `file_id` | Trazabilidad y reproducibilidad |
| `sample_id` debe ser tumor (`01`–`09`) | Se detectaron 7 mutaciones asignadas a sangre normal (`10A`) |
| El release se lee de `ops.gdc_status` | El valor `41.0` estaba hardcodeado; el real es `46.0` |
| Nulos explícitos (`null`), sin defaults inventados | Evitar `UNKNOWN`/`Not Reported`/histología por defecto |
| El manifiesto declara `mutation_scope` y `data_origin` | Distinguir panel curado de exportación missense completa |
| Validación obligatoria en productor y consumidor | Un bundle inválido no debe llegar al pipeline |

---

## 1. Alcance y definiciones

### 1.1. Cohorte V3

Un caso pertenece a la cohorte V3 si y solo si cumple **las dos** condiciones:

1. `project_id = "TCGA-BRCA"` y `primary_site = "Breast"`.
2. `ethnicity` autorreportada = `"HISPANIC OR LATINO"` (comparación
   `LOWER(TRIM(...))`, sin acentos).

No se incluyen `not hispanic or latino`, `not reported`, `unknown`, `null` ni
casos de otros proyectos.

### 1.2. Qué significa “hispano/latino”

`RACE` y `ETHNICITY` son **atributos autorreportados** por la paciente en TCGA.
No son ancestría genética, no son país de origen y no deben presentarse como
tales. Los subgrupos pueden ser pequeños; el consumidor debe marcar celdas con
`n < clinical_small_cell` y no eliminarlas.

### 1.3. Qué contiene y qué no contiene el V3

**Contiene:** variantes somáticas missense de DNA (MAF masked somatic mutation,
acceso abierto) y atributos clínico-patológicos por paciente.

**No contiene:** expresión, metilación, copias, ARN, ancestría estimada,
subtipos PAM50 calculados por el ETL ni datos protegidos. Si un atributo no
existe en la fuente, se emite `null`; no se imputa.

---

## 2. Llaves y formatos canónicos

### 2.1. Llaves

| Llave | Formato | Uso |
|---|---|---|
| `case_id` | UUID del GDC | Identificador interno del caso |
| `case_code` / `patientId` | `TCGA-XX-XXXX` (12 caracteres) | **Llave de unión entre cohorte, mutaciones y clínica** |
| `sample_id` | `TCGA-XX-XXXX-YY[A-Z]` (15–16) | Muestra; **no** es llave clínica |
| `variant_id` | SHA-256 truncado a 16 hex | Identificador determinista de la variante |
| `(patientId, clinicalAttributeId)` | — | Llave única de clínica |
| `(patient_id, variant_id)` | — | Llave única de mutación en el bundle |

Definición de `variant_id`:

```
variant_id = sha256(
  patient_id + "|" + hugo_symbol + "|" + protein_change + "|" +
  chromosome + "|" + start_position + "|" + reference_allele + "|" +
  tumor_seq_allele2
)[:16]
```

Si `reference_allele` o `tumor_seq_allele2` son `null`, se usa la cadena vacía
en el hash. El `variant_id` no cambia entre releases si la variante es la misma.

### 2.2. Formatos

| Campo | Formato | Ejemplo |
|---|---|---|
| `chromosome` | Sin prefijo `chr`; `1`–`22`, `X`, `Y`, `MT` | `"3"` |
| `start_position`, `end_position` | Entero positivo, coordenadas 1-based | `179234297` |
| `protein_change` | Sin prefijo `p.`; letra, posición, letra; `*` para stop | `"H1047R"` |
| `variant_classification` | Vocabulario MAF | `"Missense_Mutation"` |
| `mutation_status` | `"Somatic"` | `"Somatic"` |
| `sample_id` | Barcode TCGA; en mutaciones, código tumoral `01`–`09` | `"TCGA-EW-A1IX-01A"` |
| `gdc_data_release` | Texto exacto del GDC | `"Data Release 46.0 - August 10, 2026"` |
| Fechas | ISO-8601 UTC | `2026-11-07T18:56:16Z` |
| Texto | UTF-8, sin BOM, sin espacios de relleno | — |
| Nulos | `null` JSON; nunca `""`, `"NA"`, `"N/A"`, `"Not Reported"` | — |

### 2.3. Política de nulos

- Un dato ausente se representa con `null`, no con un valor inventado.
- `RACE`, `HISTOLOGY`, `STAGE`: `not reported`, `unknown`, `not available`,
  `not applicable`, `NA`, `N/A`, `.` se normalizan a `null`.
- `ETHNICITY`: es la excepción; `not reported` es una categoría real de la
  fuente, pero queda fuera de la cohorte V3.
- No se aplican defaults como `"UNKNOWN"` ni
  `"Infiltrating duct carcinoma, NOS"`. Si se necesita el valor crudo, se
  conserva en `raw_value`.
- El consumidor interpreta `null` como “sin dato” y lo etiqueta `Sin dato`.

---

## 3. Bundle de exportación

Cada exportación genera un directorio **inmutable**:

```
exports/tcga_brca_hispanic/
  <bundle_id>/
    manifest.json
    cohort_cases.json
    somatic_mutations.json
    clinical_attributes.json
```

Reglas:

- `bundle_id` = `TCGA-BRCA-HISPANIC__GDC-<major.minor>__<YYYYMMDDTHHMMSSZ>__<sha8>`.
- Un bundle nunca se sobrescribe. Si cambia el release, la cohorte o el
  alcance, se crea otro directorio.
- Los cuatro archivos son obligatorios, incluso si una lista queda vacía
  (`[]`).
- El bundle se puede copiar a `gemamx_nf/tests/reference/` para pruebas, pero
  se conserva el original y el manifiesto.

---

## 4. `manifest.json`

### 4.1. Esquema

```json
{
  "contract_version": "2.0.0",
  "bundle_id": "TCGA-BRCA-HISPANIC__GDC-46.0__20261107T185616Z__a1b2c3d4",
  "dataset_id": "tcga_brca_hispanic",
  "project_id": "TCGA-BRCA",
  "disease_type": "Breast Invasive Carcinoma",
  "primary_site": "Breast",

  "gdc_data_release": "Data Release 46.0 - August 10, 2026",
  "gdc_api_tag": "8.5.0",
  "exported_at": "2026-11-07T18:56:16Z",

  "producer": {
    "name": "etl_tcga",
    "version": "2.0.0",
    "git_commit": "2d59bab",
    "command": "tcga export-gemamx --outdir exports/tcga_brca_hispanic"
  },

  "source": {
    "layer": "silver.mutations",
    "mutations_parquet": "data/bronze/mutations/TCGA-BRCA/mutations.parquet",
    "cases_parquet": "data/bronze/cases/TCGA-BRCA/cases.parquet",
    "diagnoses_parquet": "data/bronze/cases/TCGA-BRCA/cases_diagnoses.parquet",
    "samples_parquet": "data/bronze/cases/TCGA-BRCA/cases_samples.parquet"
  },

  "cohort": {
    "filter": "project_id = TCGA-BRCA AND ethnicity = HISPANIC OR LATINO",
    "ethnicity_values": ["HISPANIC OR LATINO"],
    "total_cases": 39,
    "cases_with_mutations": 31,
    "cases_without_mutations": 8
  },

  "mutation_scope": "target_panel",
  "target_genes": [
    "PIK3CA", "TP53", "AKT1", "CDH1", "PTEN", "ESR1",
    "GATA3", "MAP3K1", "ERBB2", "BRCA1", "BRCA2"
  ],

  "data_origin": "gdc_open_access",
  "curated": false,

  "counts": {
    "cohort_cases": 39,
    "mutation_records": 23,
    "mutation_patients": 13,
    "clinical_records": 234
  },

  "files": {
    "cohort_cases.json": {
      "sha256": "<64 hex>",
      "records": 39,
      "bytes": 12122
    },
    "somatic_mutations.json": {
      "sha256": "<64 hex>",
      "records": 23,
      "bytes": 8123
    },
    "clinical_attributes.json": {
      "sha256": "<64 hex>",
      "records": 234,
      "bytes": 33923
    }
  },

  "validation": {
    "passed": true,
    "checked_at": "2026-11-07T18:56:16Z",
    "rules": [
      "cohort_count",
      "cohort_ethnicity",
      "mutation_patient_fk",
      "clinical_patient_fk",
      "unique_clinical_key",
      "unique_mutation_key",
      "tumor_sample_only",
      "protein_change_format",
      "chromosome_format",
      "release_from_source",
      "sha256_match"
    ]
  },

  "notes": [
    "RACE/ETHNICITY son autorreportados; no son ancestría genética.",
    "mutation_scope=target_panel: el bundle no contiene todas las missense de la cohorte."
  ]
}
```

### 4.2. Campos obligatorios

`contract_version`, `bundle_id`, `project_id`, `gdc_data_release`,
`exported_at`, `cohort.total_cases`, `mutation_scope`, `data_origin`,
`counts`, `files` y `validation.passed`.

### 4.3. Reglas

- `gdc_data_release` debe ser el valor devuelto por
  `GET https://api.gdc.cancer.gov/status` en el momento de la exportación, o el
  registrado en `ops.gdc_status`. **Prohibido hardcodearlo.**
- `mutation_scope` ∈ `{"target_panel", "all_missense"}`.
  - `target_panel`: solo missense en `target_genes`.
  - `all_missense`: todas las missense de la cohorte, sin filtro de gen.
- `data_origin` ∈ `{"gdc_open_access", "derived"}`.
  - `gdc_open_access`: exportación directa del medallón.
  - `derived`: cualquier recorte, unión o corrección manual. En ese caso
    `curated` debe ser `true` y `notes` debe explicar el recorte.
- `curated` no puede ser `true` en un bundle usado para resultados
  científicos; solo para smoke tests.
- `counts` debe coincidir con `files[*].records` y con el contenido real.
- `validation.passed = false` invalida el bundle.

---

## 5. `cohort_cases.json`

Array de objetos, uno por caso. Es la tabla maestra de la cohorte.

| Campo | Tipo | Obligatorio | Regla |
|---|---|---|---|
| `case_id` | string UUID | sí | Debe existir en `silver.cases` |
| `case_code` | string | sí | `^TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}$`; único |
| `project_id` | string | sí | `"TCGA-BRCA"` |
| `primary_site` | string | sí | `"Breast"` |
| `disease_type` | string | no | `"Breast Invasive Carcinoma"` |
| `race` | string \| null | sí | Normalizado a mayúsculas o `null` |
| `ethnicity` | string | sí | `"HISPANIC OR LATINO"` |
| `age` | integer \| null | sí | 0–120; `age_at_index` |
| `vital_status` | string \| null | no | `Alive` / `Dead` / `null` |
| `histology` | string \| null | sí | `primary_diagnosis`; sin default |
| `stage` | string \| null | sí | `ajcc_pathologic_stage`; sin default |
| `n_samples` | integer | no | Muestras del caso |
| `gdc_data_release` | string | sí | Igual al manifiesto |

Ejemplo:

```json
{
  "case_id": "01674b2c-5cf2-478f-84a1-f69c39f47bd4",
  "case_code": "TCGA-EW-A1P7",
  "project_id": "TCGA-BRCA",
  "primary_site": "Breast",
  "race": "WHITE",
  "ethnicity": "HISPANIC OR LATINO",
  "age": 59,
  "vital_status": "Alive",
  "histology": "Infiltrating duct carcinoma, NOS",
  "stage": "Stage IIA",
  "n_samples": 3,
  "gdc_data_release": "Data Release 46.0 - August 10, 2026"
}
```

Reglas:

- `case_code` es único. Si hay varios diagnósticos, se consolida en un registro.
- No se permiten defaults de histología ni estadio.
- La suma de `counts.cohort_cases` debe ser igual al largo del array.

---

## 6. `somatic_mutations.json`

Array de objetos. **Una fila por `(patient_id, variant_id)`**, no por muestra.

### 6.1. Campos

| Campo | Tipo | Consumidor | Regla |
|---|---|---|---|
| `variant_id` | string | recomendado | 16 hex; determinista |
| `patient_id` | string | **obligatorio** | Debe existir en la cohorte |
| `sample_id` | string | **obligatorio** | Muestra tumoral representativa (`01`–`09`) |
| `sample_ids` | string[] | no | Todas las muestras tumorales donde se observó |
| `n_samples` | integer | no | `len(sample_ids)` |
| `hugo_symbol` | string | **obligatorio** | Gen HUGO |
| `variant_classification` | string | **obligatorio** | `"Missense_Mutation"` en V3 |
| `protein_change` | string | **obligatorio** | Sin `p.`; regex `^[A-Z*]\d+[A-Z*]$` |
| `chromosome` | string | **obligatorio** | `1`–`22`, `X`, `Y`, `MT` |
| `start_position` | integer | **obligatorio** | > 0 |
| `end_position` | integer \| null | no | > 0 |
| `reference_allele` | string \| null | no | Alelo de referencia |
| `tumor_seq_allele2` | string \| null | no | Alelo alterno |
| `genomic_dna_change` | string \| null | no | HGVS del GDC, p. ej. `chr3:g.179234297A>T` |
| `mutation_status` | string | no | `"Somatic"` |
| `filter_status` | string \| null | no | `"PASS"` o `null`; nunca un filtro fallido |
| `t_depth` | integer \| null | no | Profundidad tumoral |
| `t_ref_count` | integer \| null | no | Lecturas de referencia |
| `t_alt_count` | integer \| null | no | Lecturas alternas |
| `hgvsc` | string \| null | no | — |
| `hgvsp_short` | string \| null | no | Con `p.` si viene de MAF |
| `transcript_id` | string \| null | no | — |
| `file_id` | string \| null | no | MAF de origen |
| `gdc_data_release` | string | sí | Igual al manifiesto |

### 6.2. Ejemplo

```json
{
  "variant_id": "9f2c1a7b4e8d0c31",
  "patient_id": "TCGA-EW-A1IX",
  "sample_id": "TCGA-EW-A1IX-01A",
  "sample_ids": ["TCGA-EW-A1IX-01A"],
  "n_samples": 1,
  "hugo_symbol": "PIK3CA",
  "variant_classification": "Missense_Mutation",
  "protein_change": "H1047R",
  "chromosome": "3",
  "start_position": 179234297,
  "end_position": 179234297,
  "reference_allele": "A",
  "tumor_seq_allele2": "G",
  "genomic_dna_change": "chr3:g.179234297A>G",
  "mutation_status": "Somatic",
  "filter_status": "PASS",
  "t_depth": 120,
  "t_ref_count": 78,
  "t_alt_count": 42,
  "hgvsc": "c.3140A>G",
  "hgvsp_short": "p.H1047R",
  "transcript_id": "ENST00000263967",
  "file_id": "002c911e-0d8a-4bce-84af-341a32cae334",
  "gdc_data_release": "Data Release 46.0 - August 10, 2026"
}
```

### 6.3. Reglas

1. Solo `variant_classification = "Missense_Mutation"` en V3.
2. Solo `filter_status` `"PASS"` o `null`. Un `FILTER` distinto se excluye y se
   reporta en el log de exportación.
3. `sample_id` debe ser tumoral: código de muestra `01`–`09`. Se rechazan
   `10`–`19` (normal), `20`+ (control) y cualquier barcode que no sea TCGA.
4. `sample_id` se toma de `Tumor_Sample_Barcode` del MAF. **Nunca** de
   `occurrence.case.samples[0]` del endpoint `/ssms`.
5. `protein_change` se toma de `HGVSp_Short` sin `p.`. Si el MAF no lo trae, se
   puede derivar del `HGVSp`, pero debe validarse contra el MAF.
6. No se permiten cambios de aminoácido que no existan en el MAF o en el GDC
   para ese `ssm_id`. La validación debe comparar contra la fuente.
7. `chromosome` se normaliza sin `chr`; `genomic_dna_change` conserva el prefijo
   del GDC.
8. Si el mismo paciente tiene la misma variante en varias muestras tumorales,
   se emite **una** fila con `sample_ids` y `n_samples`.
9. `patient_id` debe existir en `cohort_cases.json`.
10. `hugo_symbol` debe pertenecer a `target_genes` cuando
    `mutation_scope = "target_panel"`.

---

## 7. `clinical_attributes.json`

Array de registros “largo” (una fila por atributo). Formato compatible con
cBioPortal y con `bin/ingest_cbioportal.py`.

### 7.1. Campos

| Campo | Tipo | Obligatorio | Regla |
|---|---|---|---|
| `studyId` | string | sí | `"TCGA-BRCA-HISPANIC"` (namespace del dataset) |
| `patientId` | string | sí | `TCGA-XX-XXXX`; debe existir en la cohorte |
| `clinicalAttributeId` | string | sí | Mayúsculas; ver catálogo |
| `value` | string \| null | sí | Valor normalizado o `null` |
| `raw_value` | string \| null | no | Valor original, para auditoría |
| `value_type` | string | no | `"STRING"`, `"NUMBER"`, `"CATEGORICAL"` |
| `source` | string | no | `"GDC:demographics"`, `"GDC:diagnoses"` |
| `gdc_data_release` | string | sí | Igual al manifiesto |

### 7.2. Catálogo de atributos

| `clinicalAttributeId` | Fuente | Nulo permitido | Nota |
|---|---|---|---|
| `PRIMARY_SITE` | cases | no | `"Breast"` |
| `ETHNICITY` | demographics | no | `"HISPANIC OR LATINO"` |
| `RACE` | demographics | sí | Autorreportado |
| `AGE` | demographics | sí | `age_at_index`, entero |
| `HISTOLOGY` | diagnoses | sí | `primary_diagnosis` |
| `STAGE` | diagnoses | sí | `ajcc_pathologic_stage` |
| `VITAL_STATUS` | demographics | sí | Opcional |
| `SUBTYPE_PAM50` | externo | sí | Opcional; **no** lo calcula el ETL V3 |

### 7.3. Reglas

- Se emite un registro por cada `(patientId, clinicalAttributeId)` del catálogo
  base (`PRIMARY_SITE`, `ETHNICITY`, `RACE`, `AGE`, `HISTOLOGY`, `STAGE`),
  incluso si `value` es `null`. Con 39 casos son `39 × 6 = 234` registros. Los
  atributos opcionales (`VITAL_STATUS`, `SUBTYPE_PAM50`) agregan registros y se
  declaran en `manifest.notes`.
- `(studyId, patientId, clinicalAttributeId)` es único.
- No se inventan valores. Si `primary_diagnosis` es `"Not Reported"`, `value`
  es `null` y `raw_value` es `"Not Reported"`.
- `studyId` es un namespace del contrato; no implica un estudio nuevo de
  cBioPortal.
- El consumidor debe unir por `patientId`, no por `sampleId`.

---

## 8. Versionado

### 8.1. Semver del contrato

| Cambio | Versión |
|---|---|
| Rompe llaves, nombres, tipos o semántica | **MAJOR** |
| Agrega campos opcionales o atributos | **MINOR** |
| Corrige documentación, validación o un valor sin cambiar esquema | **PATCH** |

Reglas de compatibilidad:

- El consumidor **rechaza** un bundle con `MAJOR` distinto de `2`.
- El consumidor **acepta** `MINOR` mayor o igual a `0` e ignora campos
  desconocidos.
- Un `PATCH` no cambia el esquema; solo corrige datos o documentación.

### 8.2. Versión de datos

La versión de datos es independiente del contrato:

- `gdc_data_release`: release del GDC (p. ej. `46.0`).
- `bundle_id`: release + fecha + hash corto.
- Un cambio de release del GDC **no** cambia `contract_version`; cambia
  `bundle_id` y `gdc_data_release`.
- El consumidor debe registrar ambos en MLflow y en el manifiesto de la
  corrida.

### 8.3. Inmutabilidad

- Un bundle publicado no se edita.
- Cualquier corrección genera un bundle nuevo con `exported_at` nuevo.
- Los hashes SHA-256 del manifiesto cubren el contenido exacto de los tres
  archivos de datos.

---

## 9. Validación

### 9.1. Productor (obligatoria antes de publicar)

1. **Cohorte:** exactamente los casos `TCGA-BRCA` + `HISPANIC OR LATINO`;
   `counts.cohort_cases` coincide con el array.
2. **Integridad referencial:** todo `patient_id` de mutaciones y clínica existe
   en `cohort_cases.json`.
3. **Unicidad:** `case_code` único; `(patientId, clinicalAttributeId)` único;
   `(patient_id, variant_id)` único.
4. **Muestras:** todo `sample_id` de mutación es tumoral (`01`–`09`).
5. **Formato:** `chromosome`, `protein_change`, `start_position` y `patient_id`
   cumplen las regex del contrato.
6. **Fidelidad al MAF:** cada `(patient_id, hugo_symbol, protein_change,
   start_position)` existe en `silver.mutations`; cada `variant_id` es
   determinista.
7. **Release:** `gdc_data_release` coincide con `ops.gdc_status` o con
   `/status`; no está hardcodeado.
8. **Manifiesto:** `counts` y `files[*].records` coinciden; los SHA-256
   coinciden; `validation.passed = true`.
9. **Alcance:** si `mutation_scope = "target_panel"`, todos los genes están en
   `target_genes`; si es `"all_missense"`, no se filtra por gen.
10. **Sin datos sintéticos:** `data_origin = "gdc_open_access"` y
    `curated = false` para un bundle científico.

### 9.2. Consumidor (obligatoria antes de INGEST)

1. Verificar `contract_version` (MAJOR = 2).
2. Verificar SHA-256 de los tres archivos contra el manifiesto.
3. Verificar `counts` contra el largo real de los arrays.
4. Verificar que todo `patient_id` de mutaciones/clínica esté en la cohorte.
5. Rechazar `sample_id` con código normal (`10`–`19`).
6. Usar `manifest.cohort.total_cases` como denominador de frecuencia
   (`--total-samples`), no el número de muestras únicas del JSON.
7. Unir clínica por `patient_id`; no inferir el paciente solo del `sample_id`.
8. Registrar `contract_version`, `bundle_id`, `gdc_data_release` y
   `mutation_scope` en MLflow y en el manifiesto de la corrida.
9. Si `validation.passed = false` o `curated = true`, abortar salvo que se
   ejecute explícitamente en modo `smoke`.

---

## 10. Integración en el consumidor (`gemamx_nf`)

### 10.1. Perfil Nextflow

```groovy
'v3-tcga-hispanic' {
    docker.enabled = true
    params {
        study_id         = 'TCGA-BRCA-HISPANIC'
        disease_type     = 'Breast Invasive Carcinoma'
        cohort_ethnicity = 'HISPANIC OR LATINO'
        contract_dir     = "${projectDir}/tests/reference/tcga_hispanic_v3"
        mutations_json   = "${params.contract_dir}/somatic_mutations.json"
        clinical_json    = "${params.contract_dir}/clinical_attributes.json"
        clinical_ingest  = true
        // total_samples se toma de manifest.cohort.total_cases
    }
}
```

`run_pipeline_v3.sh` debe usar exactamente el perfil `v3-tcga-hispanic`
(no `v3-tcga-brca-hispanic`).

### 10.2. Cambios requeridos en `bin/ingest_cbioportal.py`

- `normalize()` debe conservar `patient_id` y `variant_id`.
- La clínica debe unirse por `patient_id`.
- `--total-samples` debe poder leerse del manifiesto
  (`--contract-manifest`).
- `build_variant_clinical_summary()` debe contar portadoras por paciente, no
  por muestra, cuando el contrato es V3.
- El denominador debe ser `cohort.total_cases`.

### 10.3. Webapp

- Mostrar `bundle_id`, `gdc_data_release`, `contract_version` y
  `mutation_scope`.
- En `mutation_stats.json`, `total_samples` refleja
  `manifest.cohort.total_cases`; `cohort_units_with_mutations` y
  `cohort_units_without_mutations` reflejan los casos portadores y no
  portadores declarados por el manifiesto (`cohort_unit = "patient"`).
- Si `mutation_scope = "target_panel"`, etiquetar “panel de 11 genes” y no
  “todas las mutaciones”.
- Mostrar `n` de portadoras y `N` de la cohorte.
- Ocultar PAM50 si no viene; no inventarlo.
- Mantener la nota de que `RACE`/`ETHNICITY` son autorreportados.

---

## 11. Procedimiento de publicación

1. El ETL ejecuta `tcga export-gemamx --outdir exports/tcga_brca_hispanic`.
2. El ETL valida y escribe el manifiesto con hashes.
3. Se publica el directorio `<bundle_id>/` (sin sobrescribir).
4. Se copia el bundle a `gemamx_nf/tests/reference/` solo para pruebas, con el
   manifiesto intacto.
5. GEMAMX valida el bundle y ejecuta `main_v3.nf` con el perfil
   `v3-tcga-hispanic`.
6. MLflow registra contrato, release, bundle y métricas.
7. La webapp muestra la procedencia y el alcance.

---

## 12. Fuera de alcance

- Fusionar los dos repositorios o las dos páginas.
- Que GEMAMX consulte PostgreSQL, Parquet o la API del GDC directamente.
- Que el ETL importe código de GEMAMX.
- Datos protegidos, ancestría genética o inferencia de país de origen.
- Expresión, metilación, CNV o ARN en el V3.
- GPU/Boltz: solo documentados; la ejecución es CPU.

---

## 13. Referencias

- Auditoría de procedencia: [`V3_DNA_AUDIT.md`](V3_DNA_AUDIT.md)
- Tareas por proyecto: [`V3_TASKS.md`](V3_TASKS.md)
- GDC MAF: <https://docs.gdc.cancer.gov/Data/File_Formats/MAF_Format/>
- GDC API status: <https://api.gdc.cancer.gov/status>
- GDC SSM: <https://api.gdc.cancer.gov/ssms>
