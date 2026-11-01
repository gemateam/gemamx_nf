# GEMAMX v2 — Resumen Técnico del Pipeline

Resumen consolidado a partir de los tres PDFs del directorio `DocumentacionPipeline/v2/`:
- `GEMAMX_v2_Reporte_Tecnico.pdf` (visión general, 18 págs)
- `GEMAMX_v2_Pipeline_M3_M5.pdf` (detalle IA estructural, docking, clínico, 10 págs)
- `GEMAMX_v2_Integracion_Romero_Detallado_M1_M3.pdf` (detalle ingestión, priorización, FASTA, 11 págs)

Cohorte fuente: **Romero-Córdoba et al., Nature Communications 2021** · DOI `10.1038/s41467-021-22478-y`
Tipo de tumor: cáncer de mama hormono-dependiente (HM) · 134 pacientes · 28,114 eventos somáticos · Fecha ejecución: Abril 2026

---

## 1. Contexto y diferencia respecto a v1

| Aspecto | GEMAMX v1 | GEMAMX v2 |
|---|---|---|
| Fuente de datos | Datos públicos TCGA / cBioPortal | Cohorte clínica Romero-Córdoba 2021 (población mexicana, relevancia translacional) |
| Parser de datos | (no documentado) | Parser XLSX nativo (sin pandas/openpyxl): `zipfile` + `xml.etree.ElementTree` |
| Predicción estructural | (no documentado) | Boltz-1 (IA/deep learning) en GPU (Google Colab) |
| Entorno | Local | Híbrido: local Python + cómputo en nube (Colab GPU T4/A100) |

Motivos del parser nativo sin pandas: portabilidad (funciona sin conda/pip), control de encoding (resolución manual de `sharedStrings.xml`), determinismo (no depende de versiones de openpyxl ni inferencia de tipos).

---

## 2. Arquitectura: fases y módulos

El reporte técnico organiza el pipeline en **6 fases secuenciales**. Los documentos detallados usan un esquema de **módulos M1–M5**. Mapeo:

| Reporte (Fase) | Módulo | Nombre | Script principal | Salida clave |
|---|---|---|---|---|
| Fase 1 | M1 | Ingestión y Normalización | `ingest_romero.py` | `raw_mutations.json` |
| Fase 2 | M2 | Priorización de Variantes | `ingest_romero.py` | `top_variants.json`, `mutation_stats.json` |
| Fase 3 | (puente) | Generación de secuencias FASTA | `fetch_fasta_romero.py` | `fasta/*.fasta`, `fasta_sequences.json` |
| Fase 4 | M3 | Predicción de Estructuras (GPU) | `predict_structures_romero_boltz.py` + notebook Colab | `structures/*.cif/*.pdb` |
| Fase 5 | M3b | Métricas Estructurales | `calc_structural_metrics_romero.py` | `structural_metrics.json` |
| Fase 6 | M4 | Preparación y Docking | `prepare_docking_romero.py`, `run_docking_romero.py`, `build_docking_complexes_romero.py` | `docking/results/*.pdbqt`, `vina_affinities.json` |
| — | M5 | Insights Clínicos | `build_variant_clinical_summary.py` | `variant_clinical_summary.json` |

Nota: la numeración de "M" tiene un solapamiento en M3. El doc M1–M3 cubre las Fases 1–3 (ingestión, priorización, FASTA); el doc M3–M5 llama "M3" a la IA estructural (Fases 4–5 del reporte), cuyo punto de partida son los FASTA generados en Fase 3.

---

## 3. M1 / Fase 1 — Ingestión y Normalización

**Script:** `ingest_romero.py`

**Entradas:**
- `data/romero/41467_2021_22478_MOESM8_ESM.xlsx` — hoja `HM maf` (MAF completo: 28,114 eventos)
- `data/romero/41467_2021_22478_MOESM9_ESM.xlsx` — hoja `Driver mutation in HM` (mutaciones driver curadas)

**Bibliotecas:** `zipfile`, `xml.etree.ElementTree`, `collections.Counter/defaultdict`, `re`, `json`, `pathlib` (sin pandas).

**Arquitectura interna del parser XLSX (3 pasos):**
1. **Resolución de sharedStrings** — construye lista indexada de strings desde `xl/sharedStrings.xml`; concatena todos los elementos `<t>` dentro de cada `<si>` (evita truncado de celdas con runs formateados).
2. **Mapeo de hojas por nombre** — combina `workbook.xml` + `workbook.xml.rels` para resolver `name` → archivo XML físico de la hoja.
3. **Extracción de filas con padding** — resuelve celdas `t="s"` contra sharedStrings; rellena filas cortas con strings vacíos para mantener alineación con el header.
   - Header en `row[1]` (índice base 1; la fila 0 contiene el título del archivo). Datos desde `row[2]`.

**Driver lookup (cruce de los dos XLSX):** clave compuesta de 5 campos `(gene, chromosome, start_position, ref, alt)`. Coordenadas genómicas derivadas de la notación HGVS de DNA con regex: `chr(?P<chr>[^:]+):g.(?P<pos>\d+)(?P<ref>[A-Z-]+)>(?P<alt>[A-Z-]+)`. Si hay coincidencia, la mutación se enriquece con `protein_change`, `driver`, `gene_role_mutation`, `known_variant_reference`; si no, quedan `None` (preserva las 28,114 mutaciones).

**`normalize_protein_change()`** — convierte HGVS de 3 letras a 1 letra:
- Modo 1 (HGVS completo): `p.His1047Arg` → regex `p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})` → `H1047R`
- Modo 2 (fallback): `A/G` + posición del campo "Protein" → `A{pos}G`
- Sin datos → `None` (excluida en priorización)

**Columnas normalizadas del MAF:**

| Campo normalizado | Columna original (xlsx) | Descripción |
|---|---|---|
| hugo_symbol | Hugo_Symbol | Símbolo oficial del gen (HGNC) |
| protein_change | HGVSp_Short | Cambio aminoacídico (ej. H1047R) |
| chromosome | Chromosome | Cromosoma de la mutación |
| start_position | Start_Position | Posición genómica de inicio |
| sample_id | Tumor_Sample_Barcode | ID único de paciente/muestra |
| variant_classification | Variant_Classification | Tipo de variante somática |

**Salidas:**
- `v2/data/raw_mutations.json` (14.95 MB) — 28,114 mutaciones normalizadas con todos los campos del MAF + enriquecimiento driver_lookup
- `v2/data/mutation_stats.json` (1.02 KB) — distribución por gen (top 20) y por tipo; total muestras 134, total mutaciones 28,114

**Estadísticas del dataset:**

| Tipo de variante | Conteo | % | Accionabilidad |
|---|---|---|---|
| Missense_Mutation | 5,668 | 20.2% | Principal clase accionable para docking |
| Silent | 2,395 | 8.5% | Excluida (no cambia aminoácido) |
| Nonsense_Mutation | 402 | 1.4% | Incluida en filtro |
| Splice_Site | 206 | 0.7% | Incluida en filtro |
| Frame_Shift_Del/Ins | 80 | 0.3% | Incluida en filtro |
| Intron/IGR/UTR/lincRNA/RNA | 18,378 | 65.4% | Excluida completamente |

Observación: la distribución global del MAF está dominada por genes no oncológicos (Unknown 3,929; ERBB4 188; ALK 122; EPHA6 115). PIK3CA aparece en posición 20 (42 entradas). El filtrado por KEY_GENES es una necesidad técnica.

---

## 4. M2 / Fase 2 — Priorización de Variantes

**Script:** `ingest_romero.py` (mismo script)

**15 genes clave (KEY_GENES)** — conocimiento experto codificado directamente, no algorítmico:
PIK3CA, TP53, ERBB2, BRCA1, BRCA2, CDH1, GATA3, MAP3K1, KMT2C, PTEN, RB1, ARID1A, SF3B1, AKT1, CBFB

**Tres filtros encadenados:**
1. `hugo_symbol in KEY_GENES` — elimina 99%+ de mutaciones sin relevancia terapéutica
2. `"missense" in variant_classification.lower()` — solo cambios de aminoácido modelables con Boltz-1 y docking (Nonsense/frameshift se preservan en raw pero no entran a fase estructural)
3. `protein_change is not None` — solo variantes con cambio aminoacídico identificable

**Agrupación y frecuencia:** clave `(hugo_symbol, protein_change)`. `cohort_percentage = frequency / total_samples * 100`, donde `total_samples = len({sample_id únicos}) = 134` (denominador fijo, evita inflación).

**Clasificación clínica por frecuencia (`classify_variant`):**

| Umbral (cohort_pct) | Clasificación | Ejemplos |
|---|---|---|
| >= 5.0% | Patogénica | PIK3CA H1047R (11.19%), AKT1 E17K (7.46%) |
| >= 1.0% | Probable Patogénica | PIK3CA E542K/E545K/H1047L, TP53 C135F/I195T, ERBB2 S310F |
| >= 0.5% | VUS | Mayoría con freq=1 (0.746%) |
| < 0.5% | Baja Frecuencia | (ninguna en este cohorte) |

**Salidas:**
- `v2/data/top_variants.json` (13.74 KB) — 49 variantes priorizadas ordenadas por frecuencia descendente, con coordenadas genómicas y clasificación clínica

**Top 10 variantes (datos reales, con discrepancias vs reporte inicial):**

| Rank | Gen | Variante | Freq | % Cohorte | Clasificación | Coordenada (chr:pos) |
|---|---|---|---|---|---|---|
| 1 | PIK3CA | H1047R | 15 | 11.194% | Patogénica | 3:178952085 |
| 2 | AKT1 | E17K | 10 | 7.463% | Patogénica | 14:105246551 |
| 3 | PIK3CA | E542K | 6 | 4.478% | Probable Patogénica | 3:178936082 |
| 4 | PIK3CA | E545K | 6 | 4.478% | Probable Patogénica | 3:178936091 |
| 5 | PIK3CA | H1047L | 5 | 3.731% | Probable Patogénica | 3:178952085 |
| 6 | PIK3CA | C420R | 2 | 1.493% | Probable Patogénica | 3:178927980 |
| 7 | TP53 | C135F | 2 | 1.493% | Probable Patogénica | 17:7578526 |
| 8 | TP53 | I195T | 2 | 1.493% | Probable Patogénica | 17:7578265 |
| 9 | ERBB2 | S310F | 2 | 1.493% | Probable Patogénica | 17:37868208 |
| 10 | TP53 | C176R | 2 | 1.493% | Probable Patogénica | 17:7578404 |

Las variantes rank 11–49 tienen frecuencia=1 (0.746%) y clasificación VUS. El corte práctico para docking fue `freq >= 1` dentro de KEY_GENES → 41 receptores procesados (no 10).

---

## 5. Fase 3 — Generación de Secuencias FASTA (puente a M3)

**Script:** `fetch_fasta_romero.py`

**Entradas:** `v2/data/top_variants.json` · API externa: UniProt REST API (`https://rest.uniprot.org/uniprotkb/`)

**Flujo:**
1. Consulta UniProt: `query= "gene:{symbol} AND organism_id:9606 AND reviewed:true"`, fields `accession,gene_primary,protein_name`, formato json, size 3. Selecciona el primer resultado (mayor anotación, Swiss-Prot canónica).
2. Descarga FASTA canónico WT desde `rest.uniprot.org/uniprotkb/{accession}.fasta`.
3. `apply_mutation()` — mutagénesis programática con validación de integridad: regex `([A-Z])(\d+)([A-Z])`; comprueba `wt_seq[idx] == wt_aa` (si no coincide con UniProt, retorna None y se salta la variante). Sustitución puntual en lista de chars.
4. Escritura WT reutilizable (solo si no existe) + MUT siempre sobreescribe (idempotente).

**Convención de nombres de archivos FASTA:**
- WT: `{GEN}_WT.fasta` (ej. `PIK3CA_WT.fasta`) — escrito una sola vez por gen
- MUT: `{GEN}_{VARIANTE}.fasta` (ej. `PIK3CA_H1047R.fasta`)
- Header: `>{GEN}_{VAR} | {accession}`

**Bibliotecas:** `requests`, `json`, `re`, `pathlib`

**Accessions UniProt y longitudes:**

| Gen | UniProt ID | Long. (aa) | Proteína canónica |
|---|---|---|---|
| PIK3CA | P42336 | 1,068 | PI3K catalítica alfa |
| AKT1 | P31749 | 480 | RAC-alpha ser/thr kinase |
| TP53 | P04637 | 393 | Cellular tumor antigen p53 |
| ERBB2 | P04626 | 1,255 | Receptor tyrosine kinase erbB-2 (HER2) |
| PTEN | P60484 | 403 | Phosphatase and tensin homolog |
| GATA3 | P23771 | 444 | T-cell-specific transcription factor GATA-3 |
| MAP3K1 | Q13233 | 1,512 | MAPK kinase kinase 1 |

**Salidas:**
- `v2/data/fasta/*.fasta` (37.56 KB total) — 54 archivos: 7 WT + 47 MUT
- `v2/data/fasta_sequences.json` (10.11 KB) — índice de 47 pares (WT+MUT) con accession, posición de mutación, rutas relativas

Variantes MUT por gen: PIK3CA 13, TP53 20, PTEN 6, GATA3 3, AKT1 2, ERBB2 2, MAP3K1 2.

---

## 6. M3 / Fases 4-5 — IA Estructural (Boltz-1)

**Scripts:** `predict_structures_romero_boltz.py`, `calc_structural_metrics_romero.py`
**Notebook Colab:** `v2/01_romero_structures_colab_gpu.ipynb`
**Script de escaneo:** `scan_boltz_v2.py` (monitorea progreso de predicciones en Colab)
**Runtime:** T4 GPU (Colab Pro) o A100 · **Modelo:** Boltz-1

**Lógica de decisión secuencia completa vs fragmento:**
- `BOLTZ_LIMIT = 390` aa — umbral de longitud completa
- `FRAGMENT_WINDOW = 180` aa a cada lado de la posición mutada
- `get_fragment(seq, mut_pos, window)`: retorna `(secuencia, start_1based, end_1based)`
- Si `len(wt_seq) <= 390 and len(mut_seq) <= 390` → `mode = 'full'`; si no → `mode = 'fragment'`

**Modo por gen:**

| Gen | Long. (aa) | Modo | Fragmento predicho | Justificación |
|---|---|---|---|---|
| TP53 | 393 | full | 1–393 | Cabe completa; pLDDT uniforme |
| PTEN | 403 | full | 1–403 | Justo bajo el límite |
| GATA3 | 444 | full* | 1–444 | Supera límite pero algunos jobs muestran mode=full |
| AKT1 | 480 | fragment | 1–197 (E17K) | Mutación N-terminal; cubre dominio PH |
| PIK3CA | 1,068 | fragment | 867–1068 (H1047R) | Dominio kinasa; 202 aa centrado en pos 1047 |
| ERBB2 | 1,255 | fragment | 230–430 (S310F) | Dominio extracelular; 200 aa |
| MAP3K1 | 1,512 | fragment | ±180 aa | Proteína más larga; fragmentación necesaria |

**Gestión de jobs, caché y deduplicación de WT:** el WT de un gen se predice una sola vez aunque haya múltiples variantes (control con set `generated_wt` y flag `--only-missing`). El MUT siempre se predice (único por variante).

**Convención de nombres de estructuras:**
- WT: `WT__{GEN}_{VARIANTE}.pdb` (ej. `WT__PIK3CA_H1047R.pdb`)
- MUT: `{GEN}_{VARIANTE}.pdb` (ej. `PIK3CA_H1047R.pdb`)

**Ejecución de Boltz CLI:**
```
boltz predict <fasta_path> --out_dir <run_dir> --output_format mmcif
```
Búsqueda robusta de salida CIF en múltiples rutas candidatas; fallback: `rglob('*.cif')` ordenado por tamaño (el más grande). Estructuras copiadas a `v2/data/structures/`; JSON de confianza a `v2/data/structures/meta/`.

**Flujo en Colab (6 pasos):**
1. Generar localmente `top_variants.json` + `fasta_sequences.json`
2. Subir a Google Drive con `upload_v2_to_drive.ps1`
3. Abrir notebook con runtime GPU en Colab
4. Ejecutar Boltz-1 para cada variante WT y MUT (secuencial o batch)
5. Descargar estructuras (.cif/.pdb) a `v2/data/structures/`
6. Actualizar `manifest_structures.json` y calcular métricas con `calc_structural_metrics_romero.py`

**Cálculo de métricas (`calc_structural_metrics_romero.py`):**
- Parser PDB línea a línea: registros `ATOM` con nombre `CA` (Cα). B-factor (columnas 60-66) = proxy pLDDT. Escala: si valor <= 1.5 → ×100 (rango 0-1 → 0-100).
- `LOCAL_WINDOW = 12` residuos a cada lado de la mutación.
- Mapeo resseq → posición genómica del fragmento: `genomic_like = frag_start + (resseq - 1)`
- **RMSD global**: todos los Cα alineados en orden de resseq.
- **RMSD activo**: ventana ±12 aa alrededor de la posición mutada.

**Significado biofísico:**
- RMSD global < 1.0 Å: la mutación no perturba la arquitectura global (buen predictor de unión de fármaco)
- RMSD activo < 1.5 Å (ámbar): cambio local moderado; bolsillo ligeramente alterado pero accesible
- RMSD activo >= 2.0 Å (rojo): reorganización conformacional significativa; mayor incertidumbre en docking

**Salidas:**
- `v2/data/structures/` (87 PDB, 16.77 MB) — 44 MUT + 43 WT
- `v2/data/manifest_structures.json` (5.06 KB) — índice variant_key → ruta relativa PDB
- `v2/data/structure_jobs.json` (24.43 KB) — metadatos por job: fragmento, posición mutada, rutas WT/MUT, modo
- `v2/data/structural_metrics.json` (18.79 KB) — pLDDT WT/MUT, RMSD global/activo, best_vina_drug y vina_scores por variante

**Resultados estructurales seleccionados:**

| Variante | pLDDT WT | pLDDT MUT | RMSD global (Å) | RMSD activo (Å) | Fragmento |
|---|---|---|---|---|---|
| PIK3CA_H1047R | 84.8 | 85.3 | 0.78 | 0.91 | 867–1068 (202 aa) |
| AKT1_E17K | 85.4 | 85.2 | 0.94 | 0.67 | 1–197 (197 aa) |
| PIK3CA_E542K | 90.2 | 90.2 | 1.50 | 1.80 ⚠ | 362–722 (361 aa) |
| ERBB2_S310F | 86.1 | 86.4 | 0.65 | 0.73 | 230–430 (200 aa) |
| TP53_R175H | 78.5 | 77.9 | 1.12 | 1.35 | full (393 aa) |
| PTEN_R173H | 81.2 | 80.8 | 0.95 | 1.10 | full (403 aa) |

---

## 7. M4 / Fase 6 — Docking Molecular

Tres sub-fases con scripts independientes. La fase más voluminosa: 902 archivos (log + pdbqt) cubriendo 41 receptores × 11 fármacos.

### 7.1 M4a — Preparación (`prepare_docking_romero.py`)

**Ligandos (11 fármacos con ChEMBL IDs):**

| Fármaco | ChEMBL ID | Diana | Estatus |
|---|---|---|---|
| Alpelisib | CHEMBL2396661 | PI3Kα | FDA |
| Capivasertib | CHEMBL2325741 | AKT1/2/3 | FDA |
| Palbociclib | CHEMBL189963 | CDK4/6 | FDA |
| Abemaciclib | CHEMBL3301610 | CDK4/6 | FDA |
| Ribociclib | CHEMBL3545110 | CDK4/6 | FDA |
| Copanlisib | CHEMBL3218576 | Pan-PI3K | FDA |
| Everolimus | CHEMBL1908360 | mTOR | FDA |
| Pictilisib | CHEMBL521851 | Pan-PI3K | Trial |
| Gedatolisib | CHEMBL592445 | PI3K/mTOR | Trial |
| Taselisib | CHEMBL2387080 | PI3Kα | Trial |
| Buparlisib | CHEMBL2017974 | Pan-PI3K | Trial |

> **Fe de erratas:** los ChEMBL IDs de esta tabla fueron corregidos. Los PDFs originales (`docs/docs_legados/`) contenían identificadores que no corresponden a estos fármacos. Los valores actuales coinciden con `assets/drug_catalog.csv` y fueron verificados contra fuentes públicas (Wikipedia, RCSB PDB, Pharos/NIH, DrugBank) el 2026-11-01.

**Conversión de ligandos:** SDF descargado de API ChEMBL → RDKit (`LargestFragmentChooser`, `AddHs`, embed 3D ETKDG, minimización MMFF) → Meeko → PDBQT (cargas Gasteiger implícitas en formato AutoDock).

**Conversión de receptores (2 pasos):**
1. OpenBabel: limpia estructura (elimina aguas, añade hidrógenos a pH 7.4, regenera PDB canónico): `obabel <struct> -O <tmp_pdb> -xr --addh -p 7.4`
2. Parser PDB propio → PDBQT: asigna tipo AutoDock4 por elemento (`HD` si H, sino `element[:2]`), columnas fijas FORTRAN.

**Convención de nombres de receptores:**
- `{VARIANTE}_clean.pdb` (reutilizado en M5 para complejos)
- `{VARIANTE}.pdbqt`

**Salidas:**
- `v2/data/docking/ligands/` (22 archivos, 65.19 KB) — 11 SDF + 11 PDBQT
- `v2/data/docking/receptors/` (82 archivos, 44.11 MB) — 41 `_clean.pdb` + 41 `.pdbqt`
- `v2/data/docking/prepared_receptors.json` (2.59 KB) — índice variante → ruta PDBQT, centro de masa, estado

### 7.2 M4b — Ejecución de Docking (`run_docking_romero.py`)

**AutoDock Vina:**
- Ejecutable: `vina123.exe` (AutoDock Vina 1.2.3) en la raíz del proyecto
- `exhaustiveness=8`, `num_modes=5`
- Caja de búsqueda: centro de masa del receptor (calculado automáticamente) ± 20 Å (25 Å total por dimensión): `--size_x 25 --size_y 25 --size_z 25`

**`center_of_mass(pdbqt_path)`:** promedia coordenadas x,y,z de líneas `ATOM`/`HETATM`.

**Parsing del score:** extrae score del Modo 1 (mejor pose) con 3 regex de fallback (compatibilidad entre versiones de Vina). Solo acepta valores entre -20 y 0 kcal/mol.
```
r'^\s+1\s+([-\d]+\.\d+)'       # Vina 1.2.x estándar
r'^\s+1\s+\|\s+([-\d]+\.\d+)'  # Vina con separador |
r'^   1\s+([-\d]+\.\d+)'        # formato compacto
```

**Caché:** si `log_file` ya existe con score válido, el par se salta sin relanzar Vina (reanudable). Resultados escritos incrementalmente a `vina_affinities.json` tras cada receptor; al finalizar, `structural_metrics.json` se actualiza con `best_vina_drug` y `best_vina_score`.

**Convención de nombres de resultados:**
- Poses: `{GEN}_{VAR}_{FÁRMACO}_out.pdbqt`
- Logs: `{GEN}_{VAR}_{FÁRMACO}_log.txt`
- Affinities consolidadas: `vina_affinities.json` (12.96 KB)

**Salidas:** `v2/data/docking/results/` (902 archivos, 8.42 MB) — 451 `_log.txt` + 451 `_out.pdbqt`

### 7.3 M4c — Complejos (`build_docking_complexes_romero.py`)

Fusiona receptor `_clean.pdb` + mejor pose del ligando (extrae `MODEL 1` del `*_out.pdbqt`). Tres etapas:
1. Extrae MODEL 1 (mejor pose); si no hay marcadores MODEL/ENDMDL, asume todo es la primera pose.
2. Lee receptor `clean.pdb` línea a línea, renumerando átomos secuencialmente.
3. Convierte cada línea ATOM/HETATM del ligando PDBQT a PDB estándar: añade `chain L`, `resname LIG`, deduce elemento del tipo AutoDock4 (HD→H, CL→Cl, etc.).

Header del complejo:
```
HEADER    GEMAMX V2 DOCKING COMPLEX
TITLE     {variant_id} WITH {drug_safe}
REMARK   2 BEST_VINA_AFFINITY {affinity:.3f} KCAL/MOL
```

Score también parseado desde `REMARK VINA RESULT:` en el pdbqt de salida.

**Salidas:** `v2/data/docking/complex/*_complex.pdb` + `docking/complex/index.json` (índice variante → fármaco → {ruta, afinidad}).

### 7.4 Resultados consolidados de docking

- 451 pares únicos válidos (41 receptores × 11 fármacos, 1 null en PTEN_I28F+Palbociclib)
- Umbral de relevancia clínica: -7.0 kcal/mol. ≤ -8.0 = afinidad muy alta (★★); -7.5 a -8.0 = alta (★)

**Ranking global por tier:**

| Tier | Variante | Mejor fármaco | Score | 2° fármaco | Observación |
|---|---|---|---|---|---|
| S | GATA3_Q83L | Pictilisib | -10.22 | Alpelisib -10.02 | Mejor score absoluto |
| S | TP53_D57N | Pictilisib | -10.20 | Alpelisib -9.549 | Todos 11 fármacos < -5.3 |
| S | PTEN_D297H | Pictilisib | -9.455 | Palbociclib -9.283 | Palbociclib también > -9.0 |
| S | PIK3CA_E545G | Pictilisib | -9.417 | Taselisib -8.978 | E545G más potente que E545K |
| S | AKT1_L52R | Alpelisib | -9.086 | Pictilisib -9.069 | Único caso donde Alpelisib > Pictilisib |
| A | PIK3CA_E453K | Pictilisib | -8.912 | Copanlisib -8.693 | Mayor RMSD local |
| A | AKT1_E17K | Pictilisib | -8.345 | Alpelisib -7.967 | Variante más frecuente con alta afinidad |
| ⚠ | PIK3CA_M1004I | Buparlisib | -8.670 | Palbociclib -2.293 | Anomalía: delta 6.4 kcal/mol, Palbociclib no convergió |

**Dominio de Pictilisib:** mejor score en 29/41 receptores (70.7%). Score promedio -7.8 kcal/mol (el mejor del panel). Alpelisib gana en 7, Palbociclib en 2, Abemaciclib en 2.

---

## 8. M5 — Insights Clínicos

**Script:** `build_variant_clinical_summary.py`

**Entradas (cruce de 3 archivos):**
- `raw_mutations.json` (28,114 muts) — mapeo sample_id → variante
- `clinical_metadata.json` (130.94 KB) — metadatos clínicos (edad, subtipo IHC, PAM50, grado SBR, histología)
- `top_variants.json` — define las 49 variantes incluidas

**Lógica:**
1. Índice clínico por muestra: `clinical_by_sample = {row['sample_id']: row}`
2. Identificación de muestras portadoras: `variant_id = f"{hugo_symbol}_{protein_change}"`
3. Cruce: extrae fila clínica de cada muestra portadora

**Campos clínicos analizados:**

| Campo | Tipo de análisis | Descripción |
|---|---|---|
| age | Media, min, max | Edad al diagnóstico |
| age_class | Counter + top | Older/Younger (corte de edad del estudio) |
| ihc_subtype | Counter + top | Luminal A, Luminal B, HER2-enriched, Triple Negativo |
| class_ihc | Counter + top | HR+/HER2−, HR+/HER2+, HER2+, TNBC |
| pam50 | Counter + top | LumA, LumB, HER2, Basal, Normal-like |
| grade_sbr | Counter + top | Grado histológico SBR: I, II, III |
| histology | Counter + top | IDC, IL (lobulillar), Other |

**Salida:** `v2/data/variant_clinical_summary.json` (61.67 KB) — 49 variantes con perfil clínico completo + highlights (top_age_class, top_ihc_subtype, top_class_ihc, top_pam50).

**Ejemplo PIK3CA H1047R** (15 casos, 11.19%): edad media 56.71 (39–92); 80% HR+/HER2−; predominio Luminal A (12) y grado II (10); IDC 12. Clínicamente consistente: PIK3CA H1047R activa constitutivamente el eje PI3K/AKT (mecanismo de escape a terapia endocrina en tumores luminales). Docking: Pictilisib -7.73 y Alpelisib -7.73 kcal/mol refuerzan relevancia de inhibidores PI3K.

---

## 9. Flujo de datos completo M3–M5 (reproducible y reanudable)

| Fase | Script | Entrada clave | Salidas principales |
|---|---|---|---|
| M3a | `predict_structures_romero_boltz.py` | `fasta_sequences.json` | `structures/WT__*.pdb` + `{VAR}.pdb` (87 PDB) · `manifest_structures.json` · `structure_jobs.json` |
| M3b | `calc_structural_metrics_romero.py` | `structure_jobs.json` | `structural_metrics.json` (pLDDT WT/MUT, RMSD global/activo) |
| M4a | `prepare_docking_romero.py` | `manifest_structures.json` | `ligands/*.pdbqt` (22) · `receptors/*_clean.pdb + *.pdbqt` (82) · `prepared_receptors.json` |
| M4b | `run_docking_romero.py` | `receptors/*.pdbqt`, `ligands/*.pdbqt` | `results/*_log.txt + *_out.pdbqt` (902) · `vina_affinities.json` · `structural_metrics.json` (actualizado) |
| M4c | `build_docking_complexes_romero.py` | `*_clean.pdb`, `*_out.pdbqt` | `complex/*_complex.pdb` · `complex/index.json` |
| M5 | `build_variant_clinical_summary.py` | `raw_mutations.json`, `clinical_metadata.json`, `top_variants.json` | `variant_clinical_summary.json` (61.67 KB) |

---

## 10. Inventario completo de scripts (`v2/scripts/`)

| Script | Fase | Función |
|---|---|---|
| `ingest_romero.py` | M1/M2 | Ingestión del XLSX y priorización de variantes |
| `fetch_fasta_romero.py` | Fase 3 | Descarga FASTA de UniProt y generación de mutantes |
| `generate_structures_romero.py` | M3 | Orquestación local de preparación para Boltz |
| `predict_structures_romero_boltz.py` | M3 | Predicción de estructuras con Boltz-1 (Colab) |
| `scan_boltz_v2.py` | M3 | Monitoreo del progreso de predicciones en Colab |
| `calc_structural_metrics_romero.py` | M3b | Cálculo de pLDDT y RMSD WT vs MUT |
| `prepare_docking_romero.py` | M4a | Conversión de estructuras a PDBQT para Vina |
| `run_docking_romero.py` | M4b | Ejecución de AutoDock Vina y extracción de scores |
| `build_docking_complexes_romero.py` | M4c | Construcción de complejos receptor-ligando |
| `build_variant_clinical_summary.py` | M5 | Consolidación de resultados clínicos y computacionales |
| `extract_clinical_romero.py` | — | Extracción de metadatos clínicos del dataset Romero |
| `upload_v2_to_drive.ps1` | — | PowerShell: sincronización de v2/data/ a Google Drive |

---

## 11. Discrepancias entre el reporte inicial y los datos reales (MCP)

| Aspecto | Reporte inicial | Datos reales (MCP) |
|---|---|---|
| PIK3CA C420R — frecuencia y clasificación | Freq=4 (3.0%), VUS | Freq=2 (1.493%), Probable Patogénica (rank 6) |
| Top 10 variantes — TP53 R175H | Mencionada como caso 8 | Rank 27 real; rank 7=C135F, 8=I195T, 10=C176R |
| Variantes procesadas en docking | "10 variantes" | 41 receptores con resultados reales |
| FASTAs generados | No documentado | 54 archivos: 7 WT + 47 MUT; `fasta_sequences.json` con 47 entradas |
| Variante MAP3K1 secundaria | Solo M1442I documentada | También E929Q en `fasta_sequences.json` y estructuras |
| Estructuras generadas | Reporte técnico citaba .cif | 87 PDB en disco (44 MUT + 43 WT) |

---

## 12. Conclusiones (hallazgos principales)

- El pipeline v2 procesó 28,114 mutaciones del cohorte Romero-Córdoba 2021 (134 muestras HM).
- Se priorizaron variantes en PIK3CA (13 variantes únicas), TP53 (20), PTEN (6), GATA3 (3), AKT1 (2), ERBB2 (2), MAP3K1 (2).
- PIK3CA H1047R fue la más frecuente (15 casos, 11.19%).
- Pictilisib mostró el mejor score general (-8.345 kcal/mol en AKT1 E17K), dominando en 70.7% de receptores. Mejor score absoluto: GATA3_Q83L Pictilisib -10.22.
- Métricas estructurales (RMSD activo 0.6–1.8 Å, pLDDT >80) validan calidad de estructuras Boltz-1.
- Se generaron 902 archivos de docking (451 pares log+pdbqt) cubriendo 41 receptores × 11 fármacos.

**Siguientes pasos recomendados:** validación experimental in vitro (Pictilisib/Alpelisib en PIK3CA H1047R y AKT1 E17K); análisis de resistencia (PIK3CA E245Q, E365K); docking de precisión con Glide/Schrödinger; integración con respuesta clínica del cohorte; UI web multi-dataset para comparar v1 (TCGA) vs v2 (Romero).
