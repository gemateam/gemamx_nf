# gemamx_nf — GEMA MX · pipeline V1 (TCGA-BRCA)

Primer pipeline **Nextflow DSL2** de GEMA MX: variantes de TCGA-BRCA → FASTA
WT/MUT → estructuras 3D → docking con **AutoDock Vina** → métricas y **JSON de
contrato** que consume la app web estática de GEMXMXv1 (sin modificarla).

- **Orquestación:** Nextflow DSL2 (paralelismo, `-resume`, recursos por proceso).
- **Aislamiento:** Docker, imágenes por **nombre y tag fijo** (nunca `latest`).
- **Trazabilidad:** MLflow (servidor de la plataforma, experimento `GEMAMX-V1-NF`).
- **Sin MongoDB.** Los JSON son el contrato de datos.

> Este repositorio es **autocontenido**: no importa, incluye ni monta nada de
> `Gemacont/` ni de `GEMXMXv1/`. Lo rescatado está copiado y adaptado, con su
> trazabilidad en [`docs/LEGACY_MAP.md`](docs/LEGACY_MAP.md).

---

## Estado por fases

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Auditoría del legado y del entorno | ✅ completada y aprobada |
| 1 | Estructura, `git init`, configuración de imágenes/MLflow, catálogo verificado, `LEGACY_MAP.md` y `ALMACENAMIENTO.md` | ✅ completada |
| 2 | Scripts CLI (`bin/`) + imagen de docking + pruebas aisladas | ✅ completada |
| 3 | Workflow con `-stub-run` y DAG | ⏳ pendiente |
| 4 | Perfil `test` (3 variantes, estructuras precomputadas) | ⏳ pendiente |
| 5 | Validación contra GEMXMXv1 | ⏳ pendiente |
| 6 | Resiliencia (`-resume`) | ⏳ pendiente |
| 7 | MLflow (run padre + hijas + artefactos) | ⏳ pendiente |
| 8 | Verificación de independencia | ⏳ pendiente |
| 9 | `structures_mode=boltz` (solo configuración: no hay GPU) | ⏳ pendiente |

---

## Requisitos

| Componente | Versión | Estado en el equipo de desarrollo |
|---|---|---|
| WSL2 + Ubuntu | — | ✅ |
| Java | 17+ | ❌ instalar |
| Nextflow | ≥ 24.04 | ❌ instalar |
| Docker | cualquiera reciente | ✅ 29.5.3 (Docker Desktop) |
| GPU NVIDIA | opcional | ❌ no hay (solo Intel UHD) |

Instalación (no ejecutada por el proyecto):

```bash
sudo apt update && sudo apt install -y openjdk-17-jre-headless
curl -s https://get.nextflow.io | bash && sudo mv nextflow /usr/local/bin/
nextflow -version
```

---

## Estructura

```
gemamx_nf/
├── main.nf                  # workflow (Fase 3)
├── nextflow.config          # params, perfiles, recursos
├── nextflow_schema.json     # validación de parámetros
├── bin/                     # scripts CLI (uno por unidad de trabajo)
├── modules/{ingest,fasta,structure,docking,metrics,mlflow}/main.nf
├── conf/{test,gpu,local}.config
├── containers/docking/      # única imagen propia (derivada, ver PROPUESTAS)
├── assets/
│   └── drug_catalog.csv     # 11 fármacos (ChEMBL ID verificado, SMILES canónico)
├── tests/reference/         # fixtures: contratos legados, snapshot, estructuras
├── tests/                   # run_phase2_data.sh, run_phase2_docking.sh
├── docs/{LEGACY_MAP.md,ALMACENAMIENTO.md,PROPUESTAS_PLATAFORMA.md}
└── .gitignore
```

---

## Imágenes

| Parámetro | Imagen | Uso |
|---|---|---|
| `image_cpu` | `gemamx-cpu:1.0.0` | INGEST, FETCH_FASTA, PREDICT_STRUCTURE (esmfold/precomputed), ALIGN, PREP_RECEPTOR, DOCK_CENTER, RUN_VINA, BUILD_JSONS |
| `image_docking` | `gemamx-nf-docking:1.0.0` | PREP_LIGAND (Meeko 0.8 + gemmi, ver abajo) |
| `image_gpu` | `gemamx-gpu:1.0.0` | PREDICT_STRUCTURE con `structures_mode=boltz` |
| `image_mlflow` | `gemamx-cpu:1.0.0` | LOG_MLFLOW (cliente mlflow 2.19) |

`gemamx-cpu:1.0.0` ya incluye **Vina 1.2.7, OpenBabel 3.2.1, RDKit 2026.03.1,
Biopython 1.88 y MLflow 2.19.0** (verificado en el Paso 0).

Reproducibilidad del receptor: OpenBabel 3.2.1 con `-p 7.4` coloca algunos
hidrógenos de forma aleatoria. `PREP_RECEPTOR` fija `OB_RANDOM_SEED` y ejecuta
Obabel dos veces; si los bytes no coinciden, el proceso falla. Los hidrógenos
unidos a N/O/S se tipan como `H` (polares) y los unidos a carbono como `HD`.

La única imagen propia se construye así:

```bash
docker build -t gemamx-nf-docking:1.0.0 containers/docking
```

Motivo: `meeko==0.5.0` de la imagen base importa `rdkit.six`, eliminado en RDKit
moderno. Ver [`docs/PROPUESTAS_PLATAFORMA.md`](docs/PROPUESTAS_PLATAFORMA.md) (P1).

---

## MLflow

- Experimento: `GEMAMX-V1-NF` (nuevo; no se toca `GEMAMX-M1-M8`).
- Run padre: `workflow.runName`; hijas anidadas por variante.
- Artefactos: el experimento se crea con `artifact_location="mlflow-artifacts:/"`
  para que viajen por HTTP al servidor (sin volúmenes compartidos).
- URI por defecto: `http://host.docker.internal:5000`.
  Con `--profile platform-net`: `http://mlflow:5000` sobre `gemacont_default`.

Si MLflow no responde, `LOG_MLFLOW` falla con un mensaje claro **sin invalidar**
los resultados ya publicados en `--outdir`.

---

## Almacenamiento y resultados

Tres capas, ninguna base de datos (detalle en
[`docs/ALMACENAMIENTO.md`](docs/ALMACENAMIENTO.md)):

| Capa | Ruta | Qué es | Vida útil |
|---|---|---|---|
| Caché de ejecución | `~/gemamx-work` (`work_dir`) | Intermedios por tarea, en directorios por hash | Efímera (`-resume`) |
| Archivo por corrida | `<outdir>/runs/<runName>/` | Copia inmutable de todo lo publicado + `run_manifest.json` | Permanente |
| Contrato vigente | `<outdir>/data/` | Los seis JSON + estructuras + docking de la última corrida exitosa | Se reemplaza al publicar |
| Tracking | MLflow | Parámetros, métricas y artefactos pequeños | Histórico |

`PUBLISH` (último paso) sella la corrida y promueve `runs/<runName>/data` a
`data/` con reemplazo atómico: si falla, la app sigue viendo la corrida
anterior. Las estructuras y poses **no** se suben a MLflow; solo los JSON, los
logs de Vina y un checksum con la ruta.

**No se usa MongoDB.** En el legado era un cuaderno de trabajo
(`mutations`, `top_variants`, `fasta_sequences`) que después se volcaba a JSON;
en Nextflow esa función la cumplen los canales y el cacheo por archivos.

## Catálogo de fármacos

`assets/drug_catalog.csv`: 11 fármacos con ChEMBL ID, target, estado y **SMILES
canónico**. Los ChEMBL ID del legado estaban cruzados (Alpelisib apuntaba a
Abemaciclib, Palbociclib a un compuesto con Br₂, Capivasertib a Encorafenib);
el catálogo actual se verificó 11/11 contra la API de ChEMBL (ID + `pref_name` +
equivalencia de SMILES con RDKit).

`PREP_LIGAND` no descarga nada: parte del SMILES, genera el conformero 3D con
RDKit **ETKDGv3** (`randomSeed = vina_seed`), lo optimiza con MMFF94 y lo
convierte a PDBQT con **Meeko 0.8.0**. Los SDF del legado se descartaron porque
sus moléculas no correspondían a los nombres (ver `docs/LEGACY_MAP.md`).

## Salidas (contrato de datos)

El directorio `--outdir` reproduce el árbol que espera la app web:

```
results/
├── data/
│   ├── top_variants.json          # [{rank, hugo_symbol, protein_change, frequency,
│   │                              #   cohort_percentage, chromosome, start_position, classification}]
│   ├── structural_metrics.json    # { "GEN_CAMBIO": {wt_plddt, mut_plddt, rmsd_global,
│   │                              #   rmsd_active, rmsd_regions[], best_vina_drug,
│   │                              #   best_vina_score, vina_scores{}} }
│   ├── manifest_structures.json   # { "GEN_CAMBIO": "data/structures/<archivo>.cif" | null }
│   ├── raw_mutations.json
│   ├── mutation_stats.json
│   ├── structures/                # WT y MUT
│   └── docking/
│       ├── vina_affinities.json   # { variante: { fármaco: kcal/mol } }
│       ├── results/               # poses *_out.pdbqt
│       └── complex/               # <var>_<drug>_complex.pdb (visor Molstar)
├── runs/<runName>/                # archivo inmutable de cada corrida
│   ├── data/…                     # mismo árbol que data/
│   └── run_manifest.json          # params + commit + checksums
└── pipeline_info/<runName>/       # report, trace, timeline, dag
```

La estructura de los seis JSON **no cambia**: es el contrato que consume la app.

---

## Perfiles

```bash
nextflow run . -profile docker,test            # 3 variantes, estructuras locales

nextflow run . -profile docker,platform-net,test   # + MLflow por red compartida

nextflow run . -profile docker --structures_mode esmfold   # API ESMFold, sin GPU

nextflow run . -profile docker,gpu --structures_mode boltz # requiere GPU (no disponible aquí)
```

`workDir` se coloca por defecto en `~/gemamx-work` (filesystem Linux) porque
ejecutar Nextflow desde `/mnt/d` es muy lento (9p).

---

## Pruebas de los scripts

```bash
bash tests/run_phase2_data.sh                    # ingesta, FASTA y estructuras (red)
RECEPTOR=/ruta/receptor.pdb bash tests/run_phase2_docking.sh
```

Detalle en [`tests/README.md`](tests/README.md). La prueba de docking verifica
determinismo byte a byte de ligando y receptor, y afinidades/poses idénticas de
Vina con la misma semilla.

---

## Independencia

```bash
grep -r "Gemacont\|GEMXMXv1" . --exclude-dir=.git
```

Debe devolver solo documentación (`docs/LEGACY_MAP.md`, este README). Las dos
únicas dependencias de runtime son:

1. **Imágenes Docker** referenciadas por nombre y tag fijo.
2. **Servidor MLflow**, accedido por `params.mlflow_tracking_uri`.

---

## Limitaciones conocidas

- **Sin GPU** en el equipo de desarrollo: `structures_mode=boltz` queda
  configurado y documentado, pero no ejecutable aquí. `esmfold` y `precomputed`
  no necesitan GPU.
- **`gemamx-gpu:1.0.0` no está construida** en el daemon actual (propuesta P2).
- **AKT1_E17K no tiene estructura** en el legado; se generará con ESMFold y se
  guardará como fixture del perfil `test`.
- **El legado no es reproducible**: `top_variants.json` contiene variantes que no
  existen en `raw_mutations.json` (TP53 R248Q, AKT1 E17K) y varias entradas con
  `chromosome="?"`. El pipeline deriva el ranking de datos reales.
- **Los RMSD del legado son sintéticos** (uno es negativo); se sustituyen por un
  cálculo real con Biopython.
- **RAM del equipo: 7.6 GB**. Los recursos por proceso están dimensionados para
  ese límite.

---

## Fuera de alcance (siguientes pasos)

GEMAGENTICDI M1–M8, agentes, LLM/Ollama/BioReason, chats, observabilidad,
medallón GEO, MongoDB, PostgreSQL de aplicaciones, API clínica, Seqera
Platform/Turret y disparo desde API.
