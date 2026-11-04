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
Nextflow. Mientras tanto, los scripts se pueden probar a mano:

```bash
python3 bin/build_jsons.py --help
python3 bin/publish_results.py --help
```

`PUBLISH` exige los seis contratos:

```
top_variants.json
structural_metrics.json
manifest_structures.json
raw_mutations.json
mutation_stats.json
docking/vina_affinities.json
```

y falla sin tocar `data/` si falta alguno.

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
  **conserva el cero**: `0` embarazos es un dato, no un valor ausente.

El directorio temporal se crea con los permisos por defecto del padre, no con
`tempfile.mkdtemp()` (modo `0700`): en Windows ese modo puede dejar el directorio
sin permisos heredados e inaccesible incluso para quien lo creó.
