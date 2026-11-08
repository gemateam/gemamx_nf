# Tareas del Contrato V3 por proyecto

**Contrato:** [`DATA_CONTRACT_V3_TCGA.md`](DATA_CONTRACT_V3_TCGA.md) v2.0.0
**Auditoría:** [`V3_DNA_AUDIT.md`](V3_DNA_AUDIT.md)
**Regla:** cada tarea se cierra con prueba automatizada y evidencia en el
manifiesto. No se copian datos de un proyecto a otro fuera del bundle.

Prioridades: **P0** bloquea el V3 científico; **P1** necesario para publicar;
**P2** mejora de documentación/operación.

---

## 1. Productor — `D:\ProyectosIA\etl_tcga`

### E1. Exportador desde el medallón, no desde `/ssms`

**Prioridad:** P0
**Archivos:** `tcga-medallion/etl/src/tcga/export_contract_v3.py`,
`tcga-medallion/etl/src/tcga/cli.py`

- Eliminar `fetch_gdc_ssms()`, `parse_mutations()` y el uso de
  `urllib.request` en la ruta de exportación.
- Leer de `silver.mutations` (o del Parquet equivalente) unido a
  `silver.cases`, `silver.cases_demographics`, `silver.cases_diagnoses` y
  `silver.samples`.
- Aplicar el doble filtro del contrato: `TCGA-BRCA` + `ethnicity =
  hispanic or latino`.
- Aplicar `variant_classification = 'Missense_Mutation'` y
  `filter_status IN ('PASS', NULL)`.
- Aplicar el alcance `target_panel` o `all_missense` según parámetro.

**Aceptación**

- `tcga export-gemamx` no hace ninguna petición HTTP al GDC.
- Para el release 46.0 produce, como mínimo, las 23 filas missense del panel
  en los 39 casos hispanos (21 variantes distintas, 13 portadoras), incluidas
  `GATA3 M293K` y las dos variantes de `BRCA2`.
- `GATA3 M294K` no aparece.
- Prueba: `pytest tests/test_export_contract_v3.py`.

---

### E2. Conservar la muestra tumoral en bronze y silver

**Prioridad:** P0
**Archivos:** `etl/src/tcga/bronze/mutations.py`,
`etl/src/tcga/silver/mutations.py`, `sql/001_schema.sql`,
`etl/src/tcga/gdc/maf_fields.py`

- Agregar `tumor_sample_barcode` a `_BRONZE_COLS`, `MAF_SCHEMA`,
  `_parse_maf_lines()` y a la tabla `bronze.mutations`.
- Poblar desde la columna MAF `Tumor_Sample_Barcode`.
- Propagar a `silver.mutations` (o a una tabla de muestras por mutación).
- Re-ejecutar la ingesta bronze/silver de `TCGA-BRCA`.

**Aceptación**

- Ninguna fila exportada tiene `sample_id` con código `10`–`19`.
- Las 7 mutaciones que hoy apuntan a `-10A` quedan en su muestra tumoral real
  (`01A`/`01Z`).
- Prueba de que un MAF con `Tumor_Sample_Barcode = ...-10A` se rechaza o se
  marca como inválido.

---

### E3. Release del GDC desde la fuente

**Prioridad:** P0
**Archivos:** `export_contract_v3.py`, `ops/runs.py`

- Leer `data_release` de `ops.gdc_status` (o de `/status` si se permite red).
- Escribirlo en `manifest.gdc_data_release` y en cada registro.
- Abortar si no hay release registrado.

**Aceptación**

- El manifiesto exportado hoy dice `Data Release 46.0 - August 10, 2026`.
- No queda ningún literal `41.0` en el código.
- Prueba que cambia el release simulado y el manifiesto cambia.

---

### E4. Deduplicación y `variant_id`

**Prioridad:** P0
**Archivos:** `export_contract_v3.py`

- Agrupar por `(patient_id, variant_id)`.
- Calcular `variant_id = sha256(patient_id|gen|protein|chrom|start|ref|alt)[:16]`.
- Emitir `sample_ids` (todas las muestras tumorales) y `n_samples`.
- Elegir una `sample_id` representativa determinista (orden lexicográfico).

**Aceptación**

- No hay pares `(patient_id, variant_id)` repetidos.
- `n_samples` coincide con el largo de `sample_ids`.
- Dos ejecuciones con el mismo insumo producen los mismos `variant_id`.

---

### E5. Campos completos de mutación

**Prioridad:** P1
**Archivos:** `export_contract_v3.py`

Incluir `end_position`, `reference_allele`, `tumor_seq_allele2`,
`genomic_dna_change`, `hgvsc`, `hgvsp_short`, `transcript_id`, `file_id`,
`filter_status`, `t_depth`, `t_ref_count`, `t_alt_count`.

**Aceptación**

- Todos los campos del esquema 6.1 están presentes (aunque sean `null`).
- `genomic_dna_change` conserva el prefijo `chr`; `chromosome` no.
- El consumidor puede ignorar los campos extra sin romperse.

---

### E6. Política de nulos y valores crudos

**Prioridad:** P1
**Archivos:** `export_contract_v3.py`

- Eliminar defaults `"UNKNOWN"`, `"Infiltrating duct carcinoma, NOS"` y
  `"Not Reported"`.
- Normalizar marcadores de ausencia a `null`.
- Emitir `raw_value` en clínica cuando el valor original sea un marcador de
  ausencia.
- Emitir un registro por atributo aunque `value` sea `null`.

**Aceptación**

- `TCGA-AQ-A54N`: `HISTOLOGY.value = null`, `raw_value = "Not Reported"`.
- `TCGA-AQ-A54N`: `STAGE.value = null`.
- `TCGA-AO-A0JM`: `RACE.value = null`, `raw_value = "not reported"`.
- `clinical_attributes.json` tiene `casos × atributos` registros.

---

### E7. Manifiesto 2.0.0

**Prioridad:** P0
**Archivos:** `export_contract_v3.py`

Implementar todos los campos del apartado 4 del contrato:
`contract_version`, `bundle_id`, `gdc_api_tag`, `producer`, `source`,
`cohort`, `mutation_scope`, `target_genes`, `data_origin`, `curated`,
`counts`, `files` (sha256, records, bytes), `validation` y `notes`.

**Aceptación**

- `contract_version = "2.0.0"`.
- `bundle_id` incluye release, timestamp y hash corto.
- `counts` y hashes coinciden con los archivos.
- `curated = false` y `data_origin = "gdc_open_access"` en el bundle real.

---

### E8. Validación automática y pruebas

**Prioridad:** P0
**Archivos:** `etl/src/tcga/contract_validation.py` (nuevo),
`tests/test_export_contract_v3.py` (nuevo)

Implementar las 10 reglas del apartado 9.1 del contrato.

Casos de prueba mínimos:

1. Cohorte de 39 casos, todos hispanos.
2. Toda mutación tiene `patient_id` en la cohorte.
3. Toda clínica tiene `patientId` en la cohorte.
4. No hay muestras `10`–`19`.
5. `GATA3 M293K` presente; `M294K` ausente.
6. `BRCA2 E1158Q` y `K1191N` presentes en `target_panel`.
7. SHA-256 correctos y detecta un byte alterado.
8. Release tomado de la fuente.
9. `mutation_scope` respetado.
10. `curated = true` bloquea el modo científico.

**Aceptación**

- `pytest tests/test_export_contract_v3.py` en verde.
- Un bundle manipulado falla la validación.

---

### E9. CLI de exportación

**Prioridad:** P1
**Archivos:** `etl/src/tcga/cli.py`

Opciones:

```text
tcga export-gemamx \
  --outdir exports/tcga_brca_hispanic \
  --project TCGA-BRCA \
  --ethnicity "HISPANIC OR LATINO" \
  --scope target_panel \
  --release-from-status
```

- `--scope {target_panel,all_missense}`.
- `--release-from-status` por defecto.
- `--offline` para usar solo Parquet.
- Código de salida distinto de cero si la validación falla.

**Aceptación**

- `--help` documenta las opciones.
- El comando es idempotente y no sobrescribe bundles existentes.

---

### E10. Documentación y procedencia

**Prioridad:** P2
**Archivos:** `README.md`, `docs/` del ETL

- Documentar el comando, el esquema y el procedimiento de publicación.
- Copiar la versión 2.0.0 del contrato al repo del ETL o enlazarla.
- Registrar el commit y el release en cada bundle.

**Aceptación**

- Un tercero puede reproducir el bundle con el README.
- El bundle incluye `producer.git_commit`.

---

## 2. Consumidor — `D:\ProyectosIA\gemamx_nf`

### G1. Validador de contrato antes de INGEST

**Prioridad:** P0
**Archivos:** `bin/validate_contract.py` (nuevo),
`modules/ingest/main.nf`, `tests/test_validate_contract.py` (nuevo)

Implementar las 9 reglas del apartado 9.2 del contrato:

- MAJOR = 2.
- SHA-256 de los tres archivos.
- `counts` contra el largo real.
- Integridad referencial de `patient_id`.
- Rechazo de muestras normales.
- `validation.passed = true`.
- `curated = false` en modo científico.

**Aceptación**

- Un bundle con un hash alterado aborta antes de INGEST.
- Un bundle con `sample_id = ...-10A` aborta con mensaje claro.
- `pytest tests/test_validate_contract.py` en verde.

---

### G2. Ingesta a nivel paciente

**Prioridad:** P0
**Archivos:** `bin/ingest_cbioportal.py`

- `normalize()` debe conservar `patient_id` y `variant_id`.
- `--contract-manifest` para leer `cohort.total_cases` y usarlo como
  `total_samples`.
- Unir clínica por `patient_id`, no por prefijo de `sample_id`.
- En V3, contar portadoras por paciente; no inflar por muestras.
- Mantener compatibilidad con V1/cBioPortal (sin `patient_id`, usar el
  barcode de 12 caracteres).

**Aceptación**

- V3 reporta `cohorte = 39`, no 20 ni 21.
- `variant_clinical_summary` tiene 13 portadoras para el panel actual.
- No hay muestras `-10A` en las métricas.
- V1 sigue funcionando con su snapshot.

---

### G3. Perfil Nextflow V3

**Prioridad:** P0
**Archivos:** `nextflow.config`, `main_v3.nf`, `run_pipeline_v3.sh`

- Agregar `params.contract_dir` y `params.contract_manifest`.
- Quitar el `total_samples = 39` hardcodeado; leerlo del manifiesto (dejar 39
  solo como fallback documentado).
- Ejecutar `validate_contract.py` antes de `INGEST`.
- Unificar el nombre del perfil: `v3-tcga-hispanic` en config, docs y wrapper.
- Pasar `contract_version`, `bundle_id`, `gdc_data_release` y
  `mutation_scope` a `BUILD_JSONS`/`LOG_MLFLOW`.

**Aceptación**

- `nextflow run main_v3.nf -profile docker,v3-tcga-hispanic` valida el bundle
  y arranca.
- Si el manifiesto falta o es inválido, falla con mensaje accionable.
- `run_pipeline_v3.sh` usa el mismo nombre de perfil.

---

### G4. Etiquetas de procedencia en MLflow

**Prioridad:** P1
**Archivos:** `modules/mlflow/main.nf`, `bin/log_mlflow.py` (o equivalente),
`bin/publish.py`/`BUILD_JSONS`

Registrar como tags/params:

- `contract_version`
- `bundle_id`
- `gdc_data_release`
- `mutation_scope`
- `cohort_size`
- `data_origin`
- `curated`

**Aceptación**

- El run de MLflow muestra los siete valores.
- El manifiesto de la corrida incluye los mismos valores.

---

### G5. Webapp: procedencia y alcance

**Prioridad:** P1
**Archivos:** `webapp/index.html`, `webapp/js/analysis.js`,
`webapp/js/report.js`, `webapp/css/style.css`

- Mostrar en el encabezado o en “Fuente”: `bundle_id`, `gdc_data_release`,
  `contract_version` y `mutation_scope`.
- Si `mutation_scope = "target_panel"`, etiquetar “panel de 11 genes” y no
  “todas las mutaciones”.
- Mostrar `n` de portadoras y `N` de la cohorte (39).
- Ocultar PAM50/IHC/GEO si el bundle no los trae (ya implementado para V1/V2;
  extender a V3).
- Mantener la nota de autorreporte de RACE/ETHNICITY.

**Aceptación**

- La vista V3 no afirma que las 21 variantes sean todas las mutaciones de la
  cohorte.
- Se ve el release 46.0 y el `bundle_id`.
- No aparece PAM50 si no existe en el bundle.

---

### G6. Reemplazar el fixture curado por un bundle real

**Prioridad:** P0
**Archivos:** `tests/reference/tcga_hispanic_v3/`,
`tests/reference/tcga_hispanic_v3/PROVENANCE.md` (nuevo)

- Conservar el fixture actual en
  `tests/reference/tcga_hispanic_v3_curated_smoke/` o renombrarlo y marcarlo
  `curated_smoke` en su manifiesto.
- Copiar el bundle 2.0.0 generado por el ETL a
  `tests/reference/tcga_hispanic_v3/`.
- Agregar `PROVENANCE.md` con: release, commit del ETL, comando, fecha,
  hashes y alcance.
- Actualizar el perfil V3 para apuntar al nuevo bundle.

**Aceptación**

- El manifiesto del bundle de prueba tiene `contract_version = "2.0.0"` y
  `curated = false`.
- `GATA3 M293K` presente, `M294K` ausente, `BRCA2` presente.
- `validate_contract.py` pasa.
- El fixture viejo queda identificado como histórico, no como dato real.

---

### G7. Pruebas de contrato en GEMAMX

**Prioridad:** P0
**Archivos:** `tests/test_validate_contract.py`,
`tests/test_v3_contract_ingest.py` (nuevo)

Casos mínimos:

1. Bundle válido → INGEST produce 39 de cohorte y 13 portadoras.
2. Hash alterado → aborta.
3. `patient_id` fuera de cohorte → aborta.
4. `sample_id = -10A` → aborta.
5. `contract_version = 1.2.0` → aborta por MAJOR.
6. `curated = true` sin `--allow-curated` → aborta.
7. `total_samples` se toma del manifiesto, no del JSON.
8. `GATA3 M293K` entra y `M294K` no.

**Aceptación**

- `pytest tests/test_validate_contract.py tests/test_v3_contract_ingest.py` en
  verde.
- La suite no requiere red.

---

### G8. Documentación del V3

**Prioridad:** P2
**Archivos:** `README.md`, `docs/`

- Enlazar el contrato 2.0.0 y la auditoría.
- Documentar el perfil `v3-tcga-hispanic`, el bundle y el modo `smoke`.
- Aclarar que V3 es CPU y que GPU/Boltz solo están documentados.

**Aceptación**

- Un usuario nuevo puede ejecutar el V3 siguiendo el README.
- No hay referencias a `v3-tcga-brca-hispanic`.

---

### G9. Comparación V1 (cBioPortal) vs V3 (GDC)

**Prioridad:** P1
**Archivos:** `docs/V3_CROSSCHECK.md` (nuevo)

- Correr V1 con cBioPortal en vivo y V3 con el bundle 2.0.0.
- Comparar frecuencias por gen y variante.
- Explicar la diferencia de cohortes: 34 hispanos en `brca_tcga` de
  cBioPortal vs 39 en GDC 46.0 (release, anotación y consentimiento).
- Documentar que las frecuencias no son directamente comparables si cambia el
  denominador.

**Aceptación**

- El documento lista casos, variantes, diferencias y causa probable.
- Toda diferencia está explicada por release/cohorte, no por un error de unión.

---

## 3. Orden de ejecución

```text
ETL:      E2 → E1 → E3 → E4 → E7 → E8 → E5 → E6 → E9 → E10
GEMAMX:   G1 → G2 → G3 → G7 → G6 → G4 → G5 → G9 → G8
```

- **E2** primero: sin muestra tumoral, cualquier exportación arrastra el defecto.
- **E1/E3/E4/E7/E8** producen el primer bundle válido.
- **G1/G2/G3** permiten consumirlo sin romper V1.
- **G6** recién cuando E8 esté en verde; el fixture actual no se usa para
  ciencia.
- **G9** cierra la validación cruzada.

---

## 4. Definición de terminado (V3 científico)

- [ ] `export-gemamx` lee del medallón y no llama a `/ssms`.
- [ ] El manifiesto declara release 46.0 (o el vigente) desde la fuente.
- [ ] El 100% de las mutaciones tiene muestra tumoral.
- [ ] `GATA3 M293K` presente; `M294K` ausente; `BRCA2` presente.
- [ ] El bundle 2.0.0 valida en productor y consumidor.
- [ ] V3 corre con 39 casos y 13 portadoras del panel.
- [ ] MLflow y webapp muestran contrato, release, bundle y alcance.
- [ ] El fixture viejo está marcado como `curated_smoke`.
- [ ] La comparación V1 vs V3 está documentada.
