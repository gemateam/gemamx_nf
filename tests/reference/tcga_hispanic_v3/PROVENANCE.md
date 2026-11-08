# Procedencia del bundle TCGA-BRCA Hispano/Latino (Contrato 2.0.0)

Este directorio contiene el **bundle real** que consume el Pipeline V3. No se
edita a mano: se copia desde la exportación inmutable del ETL.

## Identificación

| Campo | Valor |
|---|---|
| `contract_version` | `2.0.0` |
| `bundle_id` | `TCGA-BRCA-HISPANIC__GDC-46.0__20261108T025940Z__de39c9eb` |
| `dataset_id` | `tcga_brca_hispanic` |
| `project_id` | `TCGA-BRCA` |
| `gdc_data_release` | `Data Release 46.0 - August 10, 2026` |
| `gdc_api_tag` | `8.5.0` |
| `exported_at` | `2026-11-08T02:59:40Z` |
| `mutation_scope` | `target_panel` (11 genes) |
| `data_origin` | `gdc_open_access` |
| `curated` | `false` |
| `validation.passed` | `true` |

## Conteos

| Entidad | Registros |
|---|---:|
| Casos de la cohorte | 39 |
| Registros de mutación | 23 |
| Pacientes portadores | 13 |
| Variantes distintas | 21 |
| Registros clínicos (formato largo) | 234 |

## Procedencia

- **Fuente primaria:** GDC / TCGA-BRCA, datos abiertos.
- **Productor:** `D:\ProyectosIA\etl_tcga\tcga-medallion` (`etl_tcga`).
- **Commit del productor declarado en el manifiesto:** `2d59bab411e3ccbba3cdf18c7a64bec8fed8552f`.
  El bundle se generó con el exportador 2.0.0 sobre el medallón local; al
  momento de exportar, el árbol de trabajo del ETL tenía cambios locales del
  propio exportador aún sin commitear. El commit de publicación se registra en
  el repositorio del ETL.
- **Comando de regeneración (desde el ETL):**

  ```bash
  tcga export-gemamx \
      --data-dir /data \
      --outdir exports/tcga_brca_hispanic \
      --project TCGA-BRCA \
      --ethnicity "HISPANIC OR LATINO" \
      --scope target_panel
  ```

  Sin PostgreSQL, la función `tcga.export_contract_v3.export_bundle()` produce
  el mismo bundle leyendo `bronze/cases` y `bronze/mutations`.
- **Insumos del medallón:**
  - `data/bronze/cases/TCGA-BRCA/cases.parquet`
  - `data/bronze/cases/TCGA-BRCA/cases_diagnoses.parquet`
  - `data/bronze/cases/TCGA-BRCA/cases_samples.parquet`
  - `data/bronze/mutations/TCGA-BRCA/mutations.parquet`
  - `data/bronze/mutations/TCGA-BRCA/maf_samples.parquet`
    (`file_id → tumor_sample_barcode`, obtenido de `associated_entities` del GDC)
- **Bundle original:**
  `D:\ProyectosIA\etl_tcga\tcga-medallion\exports\tcga_brca_hispanic\TCGA-BRCA-HISPANIC__GDC-46.0__20261108T025940Z__de39c9eb\`

## Hashes SHA-256

Los hashes de los tres archivos de datos están declarados dentro de
`manifest.json` y se verifican con `bin/validate_contract.py`. Hashes del
contenido copiado a este directorio:

| Archivo | SHA-256 |
|---|---|
| `cohort_cases.json` | `6efc81f628509b102253e6ecc016280455d509429872f9bc3da13c131d02a85c` |
| `somatic_mutations.json` | `c4722ba4d6e8f20485770ac7a5abb734e34fcfd7c5b82ac642df226bc0480b4f` |
| `clinical_attributes.json` | `12328fe13d0aabd4ca1ba639d28e5148f5b5c274ebfb4a60988b45569db66042` |
| `manifest.json` | `4bd47c8f1f3dce61280ee0f0edb8c3a883b9ababbf34f265b988e847827aea56` |

## Reglas del bundle

- Una fila por `(patient_id, variant_id)`; la unión con clínica es por
  `patient_id` de 12 caracteres.
- La muestra de cada mutación es **tumoral** (`01`–`09`); las muestras normales
  (`10`–`19`) se excluyen y se registran como rechazadas si aparecen.
- `mutation_scope = target_panel`: el bundle contiene las mutaciones missense
  de los 11 genes del panel, **no** todas las missense de la cohorte.
- `RACE` y `ETHNICITY` son **autorreportados**. No son ancestría genética ni
  país de origen.
- Los nulos clínicos son explícitos (`value: null`) y conservan el valor crudo
  en `raw_value` cuando existe.
- El release y los hashes provienen de la fuente y del archivo, no de valores
  hardcodeados.

## Uso

```bash
python bin/validate_contract.py --contract-dir tests/reference/tcga_hispanic_v3
```

El fixture histórico `../tcga_hispanic_v3_curated_smoke/` **no** es un bundle
válido para ciencia: se conserva solo como procedencia de la auditoría.
