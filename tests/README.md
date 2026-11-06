# Pruebas de los scripts CLI (Fase 2)

Las pruebas se ejecutan en WSL2 con Docker y las imágenes de la plataforma:

| Imagen | Uso |
|---|---|
| `gemamx-cpu:1.0.0` | Python 3.12, Biopython, Vina, OpenBabel, MLflow |
| `gemamx-nf-docking:1.0.0` | `gemamx-cpu` + Meeko 0.8 + gemmi (ligandos) |

Ninguna prueba lee rutas de otros proyectos: solo usan `bin/`, `assets/` y
`tests/reference/`.

## 1. Ingesta, FASTA y estructuras

```bash
bash tests/run_phase2_data.sh
```

Requiere red (UniProt y API de ESMFold). Comprueba:

- el ranking determinista del snapshot de 12 mutaciones;
- `mutation_stats.json`;
- descarga de PIK3CA (P42336) y aplicación verificada de H1047R;
- predicción WT/MUT con la **misma ventana** y `mutation_resseq_model = 181`;
- pLDDT en escala 0..100 (la API de ESMFold lo emite en 0..1);
- RMSD WT/MUT con CA emparejados.

Si la API de ESMFold no responde, la prueba falla en `PREDICT_STRUCTURE` (no se
generan resultados parciales). El perfil `test` de Nextflow sustituirá esta
llamada por estructuras precomputadas cuando el fixture esté disponible.

## 2. Docking determinista

```bash
RECEPTOR=/ruta/al/receptor.pdb bash tests/run_phase2_docking.sh
```

Opcional, para centrar la caja en un residuo concreto:

```bash
RECEPTOR=/ruta/al/receptor.pdb \
MUTATION_POS=1047 MODEL_START=867 EXPECTED_AA=R \
bash tests/run_phase2_docking.sh
```

Comprueba, en ejecuciones **independientes**:

- `PREP_LIGAND` (RDKit ETKDGv3 + Meeko) produce el mismo PDBQT;
- `PREP_RECEPTOR` produce el mismo PDBQT (OpenBabel con `OB_RANDOM_SEED`
  fijo y verificación interna de dos pasadas);
- `RUN_VINA` con `--seed` fija da la misma afinidad y poses idénticas;
- `MERGE_POSE` genera un complejo con proteína y ligando.

Variables admitidas: `WORK`, `IMG`, `DOCK_IMG`, `SEED`, `DRUG`, `BOX_SIZE`,
`EXHAUSTIVENESS`, `MUTATION_POS`, `MODEL_START`, `EXPECTED_AA`.

## 3. Contratos y publicación

El flujo completo (`BUILD_JSONS` + `PUBLISH`) se valida en la Fase 3 con
Nextflow. La promoción y el archivo por corrida tienen su propia prueba:

```bash
python3 bin/build_jsons.py --help
python3 tests/test_publish_contract.py
```

`bin/publish_contract.py` exige los seis contratos:

```
top_variants.json
structural_metrics.json
manifest_structures.json
raw_mutations.json
mutation_stats.json
docking/vina_affinities.json
```

y la promoción falla sin tocar `data/` si falta alguno.

## 4. Parser XLSX (celdas vacías)

```bash
python3 tests/test_xlsx_parser.py
```

Sin Docker ni red. Construye un XLSX mínimo y comprueba que el lector
compartido por `INGEST_ROMERO` y `EXTRACT_CLINICAL`:

- coloca cada celda por su referencia `r`, de modo que una celda omitida en
  medio de la fila no desplaza el resto de columnas;
- lee cadenas en línea (`t="inlineStr"`);
- descarta filas compuestas solo por marcadores de vacío;
- normaliza `-`, `.`, `NA`, `N/A`, `#N/A` y `—` a celda vacía al extraer campos
  textuales, conservando el `-` de las columnas de alelos MAF (deleción o
  inserción);
- da el mismo resultado en las dos rutas de lectura (un solo lector, sin copias);
- elige la cabecera por su **número de fila de Excel** (2 en el MAF, 3 en drivers
  y clínico), así que una fila vacía intercalada no la desplaza, y `required`
  falla con un mensaje explícito si el fichero cambia de forma;
- da clave posicional (`_col_<n>`) a las columnas sin nombre —el clínico tiene
  tres— y rechaza dos columnas con el mismo nombre;
- en la capa clínica (`clean`), convierte los marcadores en `None` pero
  **conserva el cero**: `0` embarazos es un dato, no un valor ausente;
- una ingesta sin variantes priorizadas falla con código 1 sin escribir nada, y
  `build_jsons.py` rechaza un `top_variants.json` vacío: es la guarda que impide
  reemplazar los datos vigentes de `results/data` con listas vacías.

El directorio temporal se crea con los permisos por defecto del padre, no con
`tempfile.mkdtemp()` (modo `0700`): en Windows ese modo puede dejar el directorio
sin permisos heredados e inaccesible incluso para quien lo creó.

## 5. Filtro de la tabla de exploración (WebApp)

```bash
node tests/test_variant_filter.mjs
```

Sin navegador ni jsdom: `webapp/js/variant-filter.js` no toca el DOM. Comprueba:

- el filtro por defecto deja fuera las filas sin `protein_change` (en el contrato
  actual, **67 de 11 233** filas tienen cambio proteico);
- buscar por variante **no lanza** aunque haya filas con `protein_change` nulo,
  que era el `TypeError` que rompía la vista;
- los filtros por gen, variante y clasificación, sin distinguir mayúsculas;
- que al desactivar «Solo codificantes» entran todas las filas.

El interruptor `#exp-only-coding` está en la barra de filtros de la vista
Exploración y el contador `MOSTRANDO: x / y` usa el denominador del ámbito activo.

## 6. Ingesta clínica V1 (`clinical_ingest`)

```bash
python3 tests/test_clinical_ingest.py
```

Sin Docker ni red. Usa `tests/reference/mutations_snapshot.json` y
`tests/reference/clinical_snapshot.json` y comprueba:

- la normalización de `RACE`/`ETHNICITY` (mayúsculas, espacios, `NA`) y de `AGE`;
- el cruce paciente → muestra y los atributos de nivel muestra;
- `clinical_metadata.json`: una fila por muestra, `missing_attributes` explícito
  y `mutation_wes = Yes` en la cohorte secuenciada;
- `variant_clinical_summary.json`: `sample_count` cuenta muestras únicas (no
  mutaciones), distribuciones con `Sin dato`, resumen de edad y `small_cells`
  para las celdas con `n < clinical_small_cell`;
- que sin los flags `--clinical`/`--clinical-json` no se escriban los dos JSON
  clínicos.

## 7. Regla de código y reportes por corrida en MLflow

```bash
python3 tests/test_mlflow_source_snapshot.py
```

Este guard debe pasar para **cada** entrypoint `main*.nf`. Verifica que cada
etapa guarde su snapshot real en `Artifacts/source_code/` con un manifiesto de
hashes, y que los workflows mantengan activados los reportes de Nextflow y el
hook que los publica en el run padre bajo `Artifacts/nextflow_reports/`. No se
aceptan URLs a GitHub como sustituto del código fuente almacenado.
