# Auditoría del ADN usado en el Pipeline V3

**Fecha de auditoría:** 2026-11-07
**Alcance:** `tests/reference/tcga_hispanic_v3/` (consumidor) contra
`etl_tcga/tcga-medallion/data/bronze/` (productor) y la API pública del GDC.
**Pregunta:** ¿el ADN del V3 es real, derivado del ETL o inventado?

---

## 1. Veredicto ejecutivo

**No hay una cohorte inventada, pero el ADN del V3 tampoco es una exportación
completa y reproducible del ETL.**

- La cohorte de **39 casos** es real: los 39 `case_id` (UUID) y los 39
  `case_code` (barcode TCGA de 12 caracteres) coinciden exactamente con los
  casos `TCGA-BRCA` con `ethnicity = hispanic or latino` de la capa bronze.
- El archivo de mutaciones es un **subconjunto curado** de 21 registros, no el
  resultado reproducible del exportador que está en el repositorio. La consulta
  exacta del exportador contra el GDC devuelve **1,676 SSM / 1,678 filas**, no
  21.
- De esos 21 registros, **20 son reales** y trazables al MAF del GDC. **1 es
  inexistente**: `GATA3 M294K`; el GDC y el MAF tienen `GATA3 M293K` en la misma
  posición. Además se omitieron 2 variantes reales de `BRCA2` y la propia
  `GATA3 M293K`.
- El `sample_id` de **7 de 21** mutaciones apunta a muestra normal (`-10A`,
  sangre), lo cual es biológicamente imposible para una mutación somática de
  tumor. Es un defecto del exportador, no datos inventados.
- El manifiesto declara `Data Release 41.0`, pero el dato real es
  `Data Release 46.0 - August 10, 2026`. El release está **hardcodeado** en el
  exportador.

**Conclusión:** el V3 usa ADN real del GDC, pero el bundle actual es un
**fixture curado y parcial**, con un error tipográfico y metadatos de release
incorrectos. No debe presentarse como una exportación completa ni usarse para
frecuencias poblacionales sin regenerarlo.

---

## 2. Evidencia de la cohorte (real)

Fuente: `data/bronze/cases/TCGA-BRCA/cases.parquet` (1,098 casos).

| Etnia autorreportada | Casos |
|---|---:|
| not hispanic or latino | 884 |
| not reported | 166 |
| **hispanic or latino** | **39** |
| Unknown | 8 |
| null | 1 |

- 39 casos hispanos, 39 `submitter_id` distintos.
- Los 39 registros de `cohort_cases.json` tienen `case_id` UUID presentes en
  bronze: **39/39**.
- Los 39 `case_code` son exactamente el conjunto hispano: **39/39**, sin
  sobrantes ni faltantes.
- Edad: 32–80 años. `age` entero en el fixture vs `float` en Parquet: diferencia
  de tipo, no de dato.

Diferencias menores introducidas por los `COALESCE` del exportador:

| Caso | Campo | Fixture | Bronze | Causa |
|---|---|---|---|---|
| `TCGA-AO-A0JM` | `race` | `UNKNOWN` | `not reported` | default del exportador |
| `TCGA-AQ-A54N` | `histology` | `Infiltrating duct carcinoma, NOS` | `Not Reported` | default del exportador |
| `TCGA-AQ-A54N` | `stage` | `Not Reported` | `null` | default del exportador |

Estos defaults no son datos inventados, pero **ocultan el nulo real** y deben
eliminarse en la versión 2.0.0 del contrato.

---

## 3. Evidencia del ADN (parcialmente real)

Fuente: `data/bronze/mutations/TCGA-BRCA/mutations.parquet`.

| Métrica | Valor |
|---|---:|
| Mutaciones totales (todos los genes) | 89,568 |
| Casos con MAF | 968 |
| Mutaciones missense | 56,027 |
| Mutaciones en los 39 casos hispanos | 3,072 |
| Casos hispanos con alguna mutación | 31 |
| Casos hispanos sin mutación | 8 |
| Missense en los 39 casos hispanos | 1,652 |
| Missense en genes del panel (11 genes) | 23 filas |
| Variantes distintas del panel (gen + cambio) | 21 |
| Release del Parquet | `Data Release 46.0 - August 10, 2026` |
| Ingesta bronze | 2026-11-08T00:41–00:51 UTC |

El fixture tiene 21 filas y 13 pacientes portadores. Geografía del panel:
`PIK3CA` 11, `MAP3K1` 4, `TP53` 3, `GATA3` 1, `ERBB2` 1, `ESR1` 1.

### 3.1 Reconciliación de las 21 filas

| # | Paciente | Gen | Cambio | Posición | Estado |
|---:|---|---|---|---:|---|
| 1 | TCGA-EW-A1IX | MAP3K1 | A801T | 56,881,601 | coincide |
| 2 | TCGA-5L-AAT1 | PIK3CA | E542K | 179,218,294 | coincide |
| 3 | TCGA-A2-A04N | PIK3CA | E542K | 179,218,294 | coincide |
| 4 | TCGA-EW-A1OV | PIK3CA | E81K | 179,199,066 | coincide |
| 5 | TCGA-5L-AAT1 | PIK3CA | R88Q | 179,199,088 | coincide |
| 6 | TCGA-5L-AAT1 | GATA3 | **M294K** | 8,064,095 | **NO EXISTE** (real: M293K) |
| 7 | TCGA-5L-AAT0 | PIK3CA | H1047L | 179,234,297 | coincide |
| 8 | TCGA-A2-A04N | MAP3K1 | C1437F | 56,888,278 | coincide |
| 9 | TCGA-EW-A1J1 | PIK3CA | N1044Y | 179,234,287 | coincide |
| 10 | TCGA-EW-A1P1 | TP53 | R273H | 7,673,802 | coincide |
| 11 | TCGA-EW-A1P4 | TP53 | H179R | 7,675,076 | coincide |
| 12 | TCGA-EW-A1PE | PIK3CA | T1025A | 179,234,230 | coincide |
| 13 | TCGA-EW-A1IX | MAP3K1 | E1419K | 56,887,518 | coincide |
| 14 | TCGA-A2-A04N | MAP3K1 | N1374S | 56,887,384 | coincide |
| 15 | TCGA-EW-A6SD | TP53 | E286K | 7,673,764 | coincide |
| 16 | TCGA-EW-A1PD | ERBB2 | H470Q | 39,715,836 | coincide |
| 17 | TCGA-AR-A1AV | PIK3CA | H1047R | 179,234,297 | coincide |
| 18 | TCGA-EW-A1IX | PIK3CA | H1047R | 179,234,297 | coincide |
| 19 | TCGA-5L-AAT1 | ESR1 | Q17H | 151,807,963 | coincide |
| 20 | TCGA-EW-A1PE | PIK3CA | Q546K | 179,218,306 | coincide |
| 21 | TCGA-EW-A1IW | PIK3CA | Q546R | 179,218,307 | coincide |

### 3.2 Variantes reales omitidas

| Paciente | Gen | Cambio | Posición | Estado |
|---|---|---|---:|---|
| TCGA-5L-AAT1 | GATA3 | M293K | 8,064,095 | real, no está |
| TCGA-EW-A1PE | BRCA2 | E1158Q | 32,337,827 | real, no está |
| TCGA-EW-A1PE | BRCA2 | K1191N | 32,337,928 | real, no está |

La variante `GATA3 M293K` existe en el GDC con `ssm_id =
841678df-435b-5a14-b3f9-a159401007db` y `genomic_dna_change =
chr10:g.8064095T>A`. El fixture escribió `M294K`, que no aparece en bronce,
silver ni GDC. Es un error de curaduría/transcripción.

### 3.3 El exportador no produce 21 filas

Se replicó la consulta exacta de
`etl/src/tcga/export_contract_v3.py::fetch_gdc_ssms` contra
`https://api.gdc.cancer.gov/ssms` con los 39 `case_code`:

```
pagination: {'count': 1676, 'total': 1676, 'size': 3000, 'from': 0, 'pages': 1}
hits: 1676
filas parseadas: 1678
```

Por tanto, el fixture **no se generó ejecutando el exportador tal como está en
el repositorio**. Fue filtrado después (probablemente a mano o con un script no
versionado) al panel de 11 genes, con un cambio incorrecto y sin las dos
variantes de BRCA2.

### 3.4 Muestras normales

| Sufijo TCGA | Tipo | Filas |
|---|---|---:|
| `01A` | tumor primario | 10 |
| `01Z` | tumor primario | 4 |
| `10A` | **sangre normal** | **7** |

El exportador toma `occurrence.case.samples[0]` del endpoint `/ssms`. Ese
arreglo no está ordenado y no identifica la muestra en la que se llamó la
variante. El MAF sí trae `Tumor_Sample_Barcode`, pero bronze no la conserva
(no está en `_BRONZE_COLS`). Consecuencia: 7 mutaciones somáticas quedan
asignadas a una muestra normal.

---

## 4. Evidencia de la clínica

`clinical_attributes.json` tiene 234 registros = 39 casos × 6 atributos:

`PRIMARY_SITE`, `ETHNICITY`, `RACE`, `AGE`, `HISTOLOGY`, `STAGE`.

- Los valores de paciente son reales y provienen de la cohorte.
- `studyId = "TCGA-BRCA-HISPANIC"` es un espacio de nombres sintético del
  contrato, aceptable si se documenta.
- No hay `SUBTYPE_PAM50`, aunque la versión anterior del documento lo prometía.
- `RACE` y `ETHNICITY` son **autorreportados**, no ancestría genética.

---

## 5. Evidencia del manifiesto y del release

`manifest.json`:

- `contract_version`: `1.2.0`
- `gdc_data_release`: `Data Release 41.0 - GDC Open Access` ← **hardcodeado**
- `exported_at`: `2026-11-07T18:56:16.087596+00:00`
- `total_cases`: 39
- `total_mutations`: 21
- SHA-256 de los tres archivos: **coinciden** con el contenido actual.

Los hashes solo prueban integridad del bundle, no origen. El release real del
GDC hoy es:

```json
{
  "data_release": "Data Release 46.0 - August 10, 2026",
  "data_release_version": {"major": 46, "minor": 0, "release_date": "2026-08-10"},
  "tag": "8.5.0"
}
```

Además, `exported_at` (2026-11-07 18:56 UTC) es anterior a la ingesta bronze
(2026-11-08 00:41 UTC). El fixture se creó antes de que existiera el Parquet de
mutaciones; por eso el exportador consultó el GDC en vivo en lugar del
medallón.

---

## 6. Causa raíz

El exportador `export_contract_v3.py` se escribió en el commit inicial
`fb504bb`, antes del módulo MAF (`2d59bab`). Nunca se actualizó para leer
`silver.mutations` ni el Parquet. Sigue haciendo una consulta directa a
`/ssms`, sin filtro efectivo de genes, sin deduplicación, sin muestra tumoral y
con el release hardcodeado. El fixture se produjo en esa etapa y luego se
recortó al panel.

---

## 7. Qué se conserva y qué se corrige

**Se conserva** `tests/reference/tcga_hispanic_v3/` como procedencia histórica
del primer intento V3, pero debe etiquetarse como `curated_smoke`, no como
exportación real.

**Se corrige** en la versión 2.0.0 del contrato:

1. El exportador lee del medallón (`silver.mutations` / Parquet), no de
   `/ssms`.
2. El release se toma de `ops.gdc_status`, no se escribe a mano.
3. La muestra se toma de `Tumor_Sample_Barcode` y se rechazan códigos normales.
4. Se deduplica por paciente + variante + muestra.
5. Se incluyen `BRCA2` y `GATA3 M293K`; se elimina `M294K`.
6. Se declara en el manifiesto si el alcance es panel o missense completo.
7. Se agrega validación automática de llaves, hashes, cohorte y muestras.

Los detalles normativos están en
[`DATA_CONTRACT_V3_TCGA.md`](DATA_CONTRACT_V3_TCGA.md) y las tareas en
[`V3_TASKS.md`](V3_TASKS.md).

---

## 8. Cómo reproducir esta auditoría

```bash
# 1. Cohorte
python - <<'PY'
import pandas as pd
c = pd.read_parquet(r"D:/ProyectosIA/etl_tcga/tcga-medallion/data/bronze/cases/TCGA-BRCA/cases.parquet")
h = c[c.ethnicity.str.upper().str.strip() == "HISPANIC OR LATINO"]
print(len(h), h.submitter_id.nunique())
PY

# 2. Universo de mutaciones
python - <<'PY'
import pandas as pd
m = pd.read_parquet(r"D:/ProyectosIA/etl_tcga/tcga-medallion/data/bronze/mutations/TCGA-BRCA/mutations.parquet")
c = pd.read_parquet(r"D:/ProyectosIA/etl_tcga/tcga-medallion/data/bronze/cases/TCGA-BRCA/cases.parquet")
h = set(c[c.ethnicity.str.upper().str.strip() == "HISPANIC OR LATINO"].submitter_id)
x = m[m.case_submitter_id.isin(h)]
print(len(x), (x.variant_classification == "Missense_Mutation").sum())
PY

# 3. Release real del GDC
curl -s https://api.gdc.cancer.gov/status
```

---

## 9. Conclusión para la toma de decisiones

El pipeline V3 **sí está integrado** (`main_v3.nf`, perfil
`v3-tcga-hispanic`, `run_pipeline_v3.sh`), y el ADN que consume es
mayoritariamente real. Lo que no es real es la **presentación** del bundle como
exportación completa: es un recorte de 21 variantes con un error y metadatos de
release incorrectos.

Antes de usar el V3 para comparar frecuencias con la cohorte mexicana del V2,
hay que regenerar el bundle desde el medallón y validarlo con el contrato
2.0.0. Mientras tanto, el V3 sirve como *smoke test* de integración, no como
resultado científico.
