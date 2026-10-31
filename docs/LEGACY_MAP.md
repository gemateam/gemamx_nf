# LEGACY_MAP — qué se rescató de GEMXMXv1 y por qué

Origen auditado (solo lectura, Paso 0):

- `D:\ProyectosIA\Gemacont\Pipelines\GEMXMXv1\` (copia parcial)
- `D:\ProyectosIA\GEMXMXv1\` (repositorio original completo)
- `D:\RespaldoLaptopHP\ProyectosIA\GEMAMX\data\` (activos reales: estructuras y docking)
- `H:\Mi unidad\GEMAMX\data\` (estructuras Boltz, 81 MB)

El proyecto **no contiene** rutas, `include`, `import`, volúmenes ni symlinks hacia
esos directorios. Todo lo reutilizado se copió y adaptó aquí dentro.

---

## 1. Código rescatado (adaptado)

| Origen | Destino | Motivo / cambio |
|---|---|---|
| `GEMXMXv1/ingest_data.py` | `bin/ingest_cbioportal.py` | Única fuente real de TCGA-BRCA (cBioPortal). Se elimina MongoDB; salidas y parámetros explícitos; se conserva el mapeo de campos, el ranking por frecuencia y `classify()`. |
| `GEMXMXv1/fetch_fasta.py` | `bin/fetch_fasta.py` | UniProt + aplicación de mutación. Se elimina MongoDB; una variante (o un WT) por invocación; valida el aminoácido esperado. |
| `GEMXMXv1/generate_structures.py` | `bin/predict_structure.py` | Lógica `mutate()` y `get_domain_fragment()`. Una secuencia por invocación; escribe sidecar con `start/end/offset`; pLDDT desde el factor B; elimina la lista hardcodeada de 13 variantes. |
| `GEMXMXv1/prepare_docking.py` → `structure_to_pdbqt_receptor` | `bin/prep_receptor.py` | Misma idea (OpenBabel `--addh -p 7.4`) sin `OBABEL_EXE` ni rutas Windows. Añade semilla de OpenBabel y verificación de determinismo. |
| `GEMXMXv1/prepare_docking.py` → `get_mutation_center` | `bin/dock_center.py` | **Corrige el bug de offset de fragmento** y verifica el residuo; falla explícito en vez de caer al centro de masa. |
| `GEMXMXv1/prepare_docking.py` → SDF/OpenBabel | `bin/prep_ligand.py` | Sustituye los SDF heredados: RDKit ETKDGv3 + MMFF94 + Meeko 0.8 desde el SMILES del catálogo, con `randomSeed=vina_seed`. |
| `GEMXMXv1/prepare_docking.py` → `run_vina` | `bin/run_vina.py` | Un par receptor×fármaco por invocación; añade `--seed`; sin backend de escritura. |
| `GEMXMXv1/prepare_docking.py` → `parse_vina_log` | `bin/parse_vina.py` | Mismos regex (Vina 1.1.x y 1.2.x), reutilizados por RUN_VINA y BUILD_JSONS. |
| `GEMXMXv1/run_docking.py` | `bin/build_jsons.py` | Actualización de `structural_metrics.json` y `vina_affinities.json`, ahora como paso determinista desde archivos. Copia además estructuras, poses y complejos al contrato. |
| `GEMXMXv1/rebuild_stats.py` | `bin/build_stats.py` | Idéntico, con `--in/--out` explícitos. |
| `GEMXMXv1/merge_poses.py` | `bin/merge_pose.py` | **Necesario**: la app pide `data/docking/complex/<var>_<drug>_complex.pdb` (comprobación `HEAD`). |
| `GEMXMXv1/scan_boltz.py` | `bin/build_manifest.py` | Indexado de estructuras para `structures_mode=precomputed`; ya no reescribe rutas absolutas. |
| — (no existía) | `bin/align_wt_mut.py` | RMSD real WT/MUT con SVD sobre CA emparejados y radio de sitio activo. |
| — (no existía) | `bin/publish_results.py` | Archivo inmutable por corrida + promoción atómica del contrato vigente. |
| `GEMXMXv1/prepare_docking.py` → `DRUG_CATALOG` | `assets/drug_catalog.csv` | 11 fármacos con ChEMBL ID, target, estado y SMILES canónico. **Los IDs del legado estaban cruzados** (p. ej. `CHEMBL3301610` era Abemaciclib, no Alpelisib); el catálogo se reconstruyó y verificó 11/11 contra la API de ChEMBL (ID + `pref_name` + SMILES). |
| `Gemacont/v2/scripts/gemamx/docking.py` | — (solo referencia) | Se descarta la lógica (caja en `0,0,0`, `prepare_receptor` inexistente, MLflow dentro del job). |

## 2. Datos rescatados

| Origen | Destino | Motivo |
|---|---|---|
| `GEMXMXv1/data/top_variants.json` | `tests/reference/legacy/top_variants.json` | Referencia de **esquema** del contrato. |
| `GEMXMXv1/data/structural_metrics.json` | `tests/reference/legacy/structural_metrics.json` | Referencia de esquema (⚠ valores de RMSD sintéticos). |
| `GEMXMXv1/data/manifest_structures.json` | `tests/reference/legacy/manifest_structures.json` | Referencia de esquema. |
| `GEMXMXv1/data/mutation_stats.json` | `tests/reference/legacy/mutation_stats.json` | Referencia de esquema y magnitudes reales del cohorte (982 muestras, 60,864 mutaciones). |
| `GEMAMX/data/docking/vina_affinities.json` | `tests/reference/legacy/vina_affinities.json` | Referencia para la validación de Fase 5 (ranking por variante). |
| `GEMAMX/data/docking/results/PIK3CA_H1047R_Pictilisib_log.txt` | `tests/reference/legacy/vina_log/` | Fixture del parser de logs de Vina 1.2.3. |
| `GEMAMX/data/docking/ligands/*.sdf` | **no copiado** | Descartados: el nombre no corresponde a la molécula (`Alpelisib.sdf` = C27H32F2N8, que es Abemaciclib; `Everolimus.sdf` = C18H18N2OS3; `Gedatolisib.sdf` = C9H9ClO3). Eran 2D y de otro compuesto. `PREP_LIGAND` genera el ligando desde el SMILES del catálogo con RDKit ETKDGv3 (`randomSeed=vina_seed`) y Meeko 0.8. |
| `GEMAMX/data/structures/*` | **no copiado** | 1.25 GB; se documenta su ubicación. Las estructuras del perfil `test` se generan con `bin/predict_esmfold.py` para que WT y MUT sean consistentes. |
| `v2/data/reference/fasta/AKT1_E17K.fasta` | `tests/reference/fasta/AKT1_E17K.fasta` | FASTA del perfil test que no existe en GEMXMXv1. |

## 3. Descartado explícitamente

MongoDB (`pymongo`, `export_db.py`, `mongod_local.cfg`), `inject_*.py`,
`update_nb.py`, `setup_env.py`, `test_schema.py`, `fix_pdb_files.py`,
`generate_all_dummies.py`, `fix_cif_receptors.py`, `generate_missing.py`,
`prepare_netlify.py`, `build_raw_pages.py`, `scripts/predict_structures.py`,
`instaladores/` (MSI/EXE de Windows), `GEMAMXST/` (build de Netlify),
`.agent/`, las 7 apps JS, `banner.png`, `raw_mutations.json` completo (14 MB) y
cualquier Dockerfile de `Gemacont/`.

Motivos: dependencia de MongoDB, rutas Windows, artefactos fabricados (PDBs
"dummy"), utilidades de notebook/Netlify o simple duplicación del front-end.

## 4. Defectos del legado que este proyecto corrige

1. **Offset de fragmento**: `get_mutation_center` comparaba la posición proteica
   con el número de residuo del modelo (ESMFold renumera desde 1) y caía en
   silencio al centro de masa. DOCK_CENTER aplica el offset y valida el residuo.
2. **Sin semilla de Vina**: ahora `--seed` es parámetro (42 por defecto).
3. **WT por variante**: ahora el WT se predice y se dockea una vez por gen.
4. **Mezcla de fuentes**: el legado emparejaba WT de AlphaFold (longitud completa)
   con MUT de ESMFold (fragmento), haciendo el RMSD incomparable. El pipeline
   genera ambas con el mismo predictor y la misma ventana.
5. **RMSD inexistente**: no había código; `rmsd_active` llegaba a ser negativo
   (`ZXDB_R528H: -7.5`). Se implementa con Biopython sobre CA emparejados.
6. **`top_variants.json` no reproducible**: TP53 R248Q y AKT1 E17K no existen en
   `raw_mutations.json` (solo TP53 R248W); varias entradas tienen
   `chromosome="?"`, `start_position=0`. El pipeline deriva el ranking de datos
   reales y el perfil `test` usa un snapshot declarado como fixture.
7. **Catálogo de fármacos cruzado**: los ChEMBL ID de `prepare_docking.py`
   apuntaban a otros compuestos (Alpelisib→Abemaciclib, Palbociclib→un compuesto
   con Br₂, Capivasertib→Encorafenib). El catálogo se verificó contra la API de
   ChEMBL y ahora incluye SMILES canónico.
8. **Ligandos SDF ajenos**: los `*.sdf` de `data/docking/ligands/` no
   correspondían a los nombres y eran 2D. Se descartan; el ligando se genera
   desde SMILES, sin dependencia de red y con semilla fija.
9. **Sin capa de publicación**: el legado escribía directamente en `data/`, así
   que una corrida fallida podía dejar el contrato a medias. Ahora se publica un
   archivo inmutable por corrida y `data/` se reemplaza de forma atómica
   (ver `docs/ALMACENAMIENTO.md`).
10. **Protonación no reproducible**: OpenBabel 3.2.1 con `-p 7.4` colocaba dos
    hidrógenos de amida en posiciones aleatorias (se detectó comparando
    ejecuciones). PREP_RECEPTOR fija `OB_RANDOM_SEED` y ejecuta Obabel dos veces:
    si los bytes difieren, el proceso falla.
11. **Todos los H como `HD`**: el legado asignaba el tipo AD4 `HD` a cualquier
    hidrógeno, perdiendo los donadores polares. Ahora los H unidos a N/O/S se
    escriben como `H` y los unidos a carbono como `HD`.
12. **pLDDT sin escala**: la API de ESMFold escribe pLDDT en 0..1; el legado lo
    trataba como 0..100. `PREDICT_STRUCTURE` detecta el rango y escala ×100.
