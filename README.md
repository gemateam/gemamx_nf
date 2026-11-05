# GEMA MX — Genomic Analysis of Mammary Cancer

[![Pipeline](https://img.shields.io/badge/pipeline-Nextflow%20DSL2-brightgreen)](https://www.nextflow.io/)
[![Tracking](https://img.shields.io/badge/tracking-MLflow%202.19-blue)](https://mlflow.org/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

Pipeline bioinformático y plataforma genómico-estructural reproducible para cáncer de mama, orquestado con [Nextflow DSL2](https://www.nextflow.io/) y registrado en [MLflow](https://mlflow.org/). 

Soporta dos pipelines bioinformáticos complementarios:
- **V1 (TCGA-BRCA)**: Ingesta pública del GDC/NCI, priorización ACMG, predicción estructural y docking molecular con AutoDock Vina.
- **V2 (Romero-Córdoba 2021 HM)**: Cohorte clínica de mujeres hispanas/mexicanas del FUCAM (*Nature Communications 2021*), incorporando WES, subclasificación clínica (IHC: Luminal A/B, HER2+, TNBC; PAM50: LumA, LumB, Basal, Her2, Normal) y catálogo de fármacos optimizado para México.

Incluye una **WebApp interactiva SPA (6 vistas dinámicas e integradas)** con selector reactivo de corridas, visor modal del snapshot de código real ejecutado por corrida, visores macromoleculares 3D ([PDBe Molstar](https://github.com/PDBeurope/pdbe-molstar)) y enriquecimiento en vivo con [ChEMBL](https://www.ebi.ac.uk/chembl/) y [CiViC](https://civicdb.org).

> 🏛️ **Diagrama de Arquitectura Interactivo en Vivo**:  
> Puedes consultar el diagrama de arquitectura interactivo (con zoom, pan y trazabilidad de componentes) siempre actualizado en:  
> 🔗 **[https://gemateam.github.io/gemamx_nf/architecture.html](https://gemateam.github.io/gemamx_nf/architecture.html)**  
> *(O abrir directamente el archivo local [`docs/architecture.html`](docs/architecture.html) en cualquier navegador)*

---

## Tabla de contenidos

1. [Arquitectura del Sistema](#1-arquitectura-del-sistema)
2. [Pipelines V1, V2 y V2.1](#2-pipelines-v1-v2-y-v21)
3. [Requisitos e Infraestructura](#3-requisitos-e-infraestructura)
4. [Instalación Rápida](#4-instalación-rápida)
5. [Estructura del Proyecto](#5-estructura-del-proyecto)
6. [Ejecución del Pipeline](#6-ejecución-del-pipeline)
   - [Pipeline V1 (TCGA-BRCA)](#pipeline-v1-tcga-brca)
   - [Pipeline V2 (Romero-Córdoba 2021 HM)](#pipeline-v2-romero-córdoba-2021-hm)
   - [Pipeline V2.1 (un WT por variante · solo CPU)](#pipeline-v21-un-wt-por-variante--solo-cpu)
7. [Servicios Docker y MLflow](#7-servicios-docker-y-mlflow)
8. [WebApp Interactiva (6 Vistas Integradas)](#8-webapp-interactiva-6-vistas-integradas)
9. [Pipelines Nextflow y Herramientas Relacionadas](#9-pipelines-nextflow-y-herramientas-relacionadas)
10. [Referencias y Tecnologías](#10-referencias-y-tecnologías)
11. [Licencia y Créditos](#11-licencia-y-créditos)

---

## 1. Arquitectura del Sistema

El sistema implementa una arquitectura desacoplada en cuatro capas principales:

1. **Orquestación y Cómputo Bioinformático ([Nextflow DSL2](https://www.nextflow.io/))**:
   - `main.nf`: Flujo V1 para la cohorte TCGA-BRCA.
   - `main_v2.nf`: Flujo V2 para la cohorte Romero-Córdoba 2021 (FUCAM HM), agregando extracción clínica e integración WES.
   - `main_v2_1.nf`: Flujo V2.1 (solo CPU) sobre la misma cohorte: un WT por variante, ventana que cubre el bolsillo y docking restringido a pares fármaco-diana. Ver `docs/V2_1.md`.
   - Procesamiento modular en contenedores Docker dedicados: CPU (`gemamx-cpu:1.0.0`), GPU (`gemamx-gpu:1.0.0`) y Docking (`gemamx-nf-docking:1.0.0`).

2. **Seguimiento de Experimentos y Linaje ([MLflow Tracking](https://mlflow.org/))**:
   - Servidor MLflow 2.19 autónomo con backend en PostgreSQL (`gemamx_postgres:5432`) y almacén de artefactos (`gemamx_mlflow:5000`).
   - Trazabilidad de 145+ corridas históricas con registro de métricas pLDDT, RMSD, puntuaciones de afinidad AutoDock Vina, reportes Nextflow y trazabilidad Git.

3. **Contrato de Datos Inmutable (`results/data/`)**:
   - Interfaz desacoplada basada en esquemas JSON (`top_variants.json`, `structural_metrics.json`, `vina_affinities.json`, `variant_clinical_summary.json`, etc.) y archivos PDB/CIF.
   - Versionado histórico por corrida en `results/runs/<run_name>/data`.

4. **Visualización y Exploración SPA (Nginx :8080)**:
   - WebApp reactiva sin dependencias de compilación pesada.
   - Selector reactivo de corridas que commuta en caliente el espacio de datos (`#sel-run`).
   - Integración REST/GraphQL viva con [ChEMBL](https://www.ebi.ac.uk/chembl/) y [CiViC](https://civicdb.org).

---

## 2. Pipelines V1, V2 y V2.1

| Característica | Pipeline V1 (`main.nf`) | Pipeline V2 (`main_v2.nf`) |
|---|---|---|
| **Cohorte** | TCGA-BRCA (Internacional) | Romero-Córdoba 2021 (FUCAM · México) |
| **Insumo Genómico** | API NCI GDC / MAF preprocesado | WES somático curado (MOESM8 / MOESM9) |
| **Metadatos Clínicos** | Parámetros estándar TCGA | IHC, PAM50, rangos de edad, WES (MOESM4) |
| **Priorización de Variantes** | Frecuencia de cohorte + ClinVar/ACMG | Frecuencia en mujeres mexicanas + Hotspots |
| **Modelado 3D** | Boltz-1 / AlphaFold / ESMFold | Boltz-1 / AlphaFold / PDB precomputados |
| **Docking Molecular** | AutoDock Vina 1.2.7 (11 fármacos) | AutoDock Vina 1.2.7 (11 fármacos curados) |
| **Experimento [MLflow](https://mlflow.org/)** | `GEMAMX-V1-NF` | `GEMAMX-V2-ROMERO` |
| **Módulo Clínico Web** | Oculto / No aplicable | Integrado directamente en la vista **Análisis** |

### V2.0 vs V2.1

`main_v2_1.nf` es un **entrypoint independiente**: `main_v2.nf` (V2.0) no cambia de
comportamiento y ambos comparten los mismos módulos. V2.1 añade dos procesos de plegado
(`PREDICT_STRUCTURE_WT_PAIR` / `PREDICT_STRUCTURE_MUT_PAIR`) y corrige los supuestos que en
V2.0 producían métricas inválidas o cómputo innecesario.

| Aspecto | V2.0 (`main_v2.nf`) | V2.1 (`main_v2_1.nf`) |
|---|---|---|
| **WT por variante** | Un solo WT por gen; todas las variantes del gen se alinean contra él | Un WT por variante (`<GEN>_WT_<CAMBIO>`), plegado en la misma región que su mutación |
| **RMSD WT/MUT** | 15–20 Å (o error «0 residuos CA en común») cuando la variante cae fuera de la ventana del WT | 0.1–0.8 Å (medido: PIK3CA_H1047R 0.303 Å, PIK3CA_E542K 0.125 Å, AKT1_E17K 0.837 Å) |
| **Ventana de plegado** | Centrada en la mutación | Cubre mutación **y** bolsillo (`foldWindow()`), con la misma ventana para WT y MUT |
| **Caja de docking** | Centrada en la mutación | Centroide de los residuos del bolsillo (`assets/binding_sites.csv`, `box_center_mode=binding_site`) |
| **Pares a acoplar** | Producto cartesiano gen × 11 fármacos | Solo los pares de `assets/target_drug_map.csv`, con `role` (`on_target` / `off_target_control`) |
| **Backend estructural** | Boltz-1 / AlphaFold / precomputadas | Solo CPU: `precomputed` o `esmfold`; `boltz` se rechaza al inicio |
| **Cobertura del sitio** | No se evalúa | `site_on_missing` (`fail` \| `centroid`) y `site_covered` en `vina_roles.json` |
| **Salidas** | `vina_affinities.json` | Añade `vina_roles.json` y `wt_structure` en `structural_metrics.json` (contrato aditivo) |

**Mejoras concretas**

1. **RMSD válido.** Al plegar un WT por variante, cada comparación WT/MUT ocurre sobre la
   misma región. Es la corrección de fondo: sin ella, el RMSD de variantes como PIK3CA_E542K
   no era interpretable.
2. **Docking con sentido biológico.** La caja se centra en el bolsillo ATP y no en la mutación,
   de modo que el ligando se acopla donde realmente se une. El par se marca como `on_target`
   o `off_target_control`.
3. **Menos cómputo inútil.** Se elimina el producto cartesiano: TP53, PTEN, GATA3 y MAP3K1
   quedan fuera por no tener bolsillo farmacológico mapeado. Además, solo se acopla el WT
   canónico de cada gen (el de menor `rank`); el resto de WT se usa únicamente para el RMSD.
4. **Trazabilidad.** `<GEN>_WT` se conserva como alias canónico, de modo que la WebApp sigue
   leyendo el mismo contrato sin cambios, y `wt_structure` deja explícito qué WT se usó.
5. **Límites de tiempo coherentes.** `RUN_VINA` declara `time = '1h'` con `exhaustiveness=1` y
   `4h` con `exhaustiveness≥8`; el perfil `v2_1` fija `vina_timeout_sec = 12600` (3.5 h). El
   timeout interno de Vina siempre dispara antes que el del scheduler, así que en YUCA el
   error es diagnosticable en lugar de un *job killed* sin traza.

**Limitación conocida.** Los fixtures actuales se plegaron con la ventana de V2 y no contienen
el bolsillo completo: con `site_on_missing=fail` la producción aborta hasta regenerarlos, y
PIK3CA_E542K no puede cubrirlo porque mutación y bolsillo quedan a más de 388 aa. La prueba de
humo usa `site_on_missing=centroid` y registra `site_covered=false`. Detalle completo en
[`docs/V2_1.md`](docs/V2_1.md).

---

## 3. Requisitos e Infraestructura

| Herramienta | Versión mínima | Propósito | Referencia |
|---|---|---|---|
| **Nextflow** | 26.10.5 | Orquestador de flujos bioinformáticos | [https://www.nextflow.io/](https://www.nextflow.io/) |
| **MLflow** | 2.19+ | Registro de experimentos y métricas | [https://mlflow.org/](https://mlflow.org/) |
| **Docker Engine** | 24+ | Ejecución aislada de módulos | [Docker Docs](https://docs.docker.com/) |
| **Docker Compose** | 2.20+ | Orquestación de servicios (Web, MLflow, Postgres) | [Compose Docs](https://docs.docker.com/compose/) |
| **Python** | 3.10+ | Scripts auxiliares y APIs bioinformáticas | [Python.org](https://www.python.org/) |
| **NVIDIA GPU (Opcional)** | CUDA 12+ | Aceleración de predicción estructural (Boltz-1) | [NVIDIA CUDA](https://developer.nvidia.com/cuda-zone) |

> **Nextflow 26+ es obligatorio.** `modules/docking/main.nf` usa sintaxis estricta que
> Nextflow 24.10.5 rechaza al compilar (`Variable meta_json already defined in the process
> scope`). La versión validada es **26.10.5**. Si el host no tiene Java ni Nextflow, el
> orquestador puede ejecutarse con la imagen oficial `nextflow/nextflow:26.10.5` montando el
> socket de Docker; ver [§6](#ejecución-sin-java-ni-nextflow-en-el-host).

---

## 4. Instalación Rápida

```bash
# 1. Clonar el repositorio
git clone https://github.com/gemateam/gemamx_nf.git
cd gemamx_nf

# 2. Levantar el stack completo (Postgres, MLflow y WebApp)
docker compose up -d

# 2b. Construir las imágenes de los procesos Nextflow (CPU y docking)
docker compose --profile images build
# También se pueden reconstruir los servicios del stack:
# docker compose build mlflow webapp

# 3. Verificar estado de los servicios y las imágenes
docker compose ps
# gemamx_postgres -> localhost:5432 (healthy)
# gemamx_mlflow   -> http://localhost:5000 (healthy)
# gemamx_webapp   -> http://localhost:8080 (healthy)

docker images --format "{{.Repository}}:{{.Tag}}" | grep gemamx
# gemamx-cpu:1.0.0         (procesos CPU: FASTA, estructuras, métricas, MLflow)
# gemamx-nf-docking:1.0.0  (preparación de ligandos/receptores y AutoDock Vina)
# gemamx-mlflow:1.0.0      (servidor MLflow 2.19.0 + UI)
# gemamx-webapp:1.0.0      (Nginx + SPA)
```

Las versiones exactas de cada imagen están en [§7](#7-servicios-docker-y-mlflow).

---

## 5. Estructura del Proyecto

```
gemamx_nf/
├── main.nf                     # Pipeline V1 (TCGA-BRCA) en Nextflow DSL2
├── main_v2.nf                  # Pipeline V2 (Romero-Córdoba HM) en Nextflow DSL2
├── main_v2_1.nf                # Pipeline V2.1 (un WT por variante, solo CPU)
├── nextflow.config             # Configuración central (perfiles: docker, test, gpu, romero-v2, v2_1, smoke…)
├── docker-compose.yml          # Stack de infraestructura: Postgres, MLflow, WebApp
├── assets/
│   └── drug_catalog.csv        # Catálogo curado de 11 fármacos oncológicos
├── bin/                        # Lógica ejecutable de los procesos Nextflow
│   ├── build_jsons.py          # Ensamblador del contrato JSON inmutable
│   ├── extract_clinical_romero.py # Extractor de metadatos clínicos FUCAM
│   ├── build_clinical_summary.py  # Generador de resúmenes variantes × clínica
│   └── ingest_romero.py        # Ingestor WES para cohorte mexicana
├── conf/                       # Esbozos de perfiles (no incluidos por nextflow.config)
│   ├── gpu.config
│   ├── local.config
│   └── test.config
├── containers/                 # Dockerfiles de los entornos del pipeline
│   ├── cpu/                    # gemamx-cpu:1.0.0
│   ├── gpu/                    # gemamx-gpu:1.0.0
│   └── docking/                # gemamx-nf-docking:1.0.0
├── docs/                       # Documentación y diagramas
│   ├── index.html              # Portal de documentación en GitHub Pages
│   ├── architecture.html       # Diagrama de arquitectura interactivo (Archify)
│   ├── V2_1.md                 # Contrato y diferencias de V2.1
│   ├── LEGACY_MAP.md           # Origen del código y auditoría de rutas
│   └── PIPELINES_RELACIONADOS.md # Pipelines Nextflow y herramientas relacionadas
├── infra/                      # Almacén de infraestructura autónoma
│   ├── mlflow/                 # Artefactos y volúmenes de MLflow
│   └── postgres-init/          # Scripts de inicialización SQL
├── modules/                    # Módulos modulares Nextflow DSL2
│   ├── clinical/               # Extracción y resumen clínico V2
│   ├── docking/                # Preparación de ligandos/receptores y Vina
│   ├── fasta/                  # Descarga y formateo de secuencias
│   ├── ingest/ & ingest_v2/    # Ingesta GDC (V1) y Romero WES (V2)
│   ├── metrics/ & metrics_v2/  # Cálculo de RMSD y alineamiento WT/MUT
│   ├── report/                 # Publicación de contratos y registro MLflow
│   └── structure/              # Predicción 3D (Boltz-1 / AlphaFold)
├── papers/                     # Artículos de referencia (PDF), p. ej. PredictONCO (Khan et al., 2024)
├── results/
│   ├── data/                   # Contrato de datos vigente servido a la WebApp
│   └── runs/                   # Histórico de corridas archivadas con index.json
├── results_v1*/                # Salidas de corridas V1 de validación (ignoradas por git)
├── structures/
│   └── external/               # Modelos AlphaFold DB para genes sin estructura en la corrida
│       ├── <GEN>_AF.cif        # modelo mmCIF de la secuencia completa
│       └── index.json          # gen → archivo, UniProt, pLDDT y versión
├── tests/reference/            # Insumos de referencia y datos preprocesados
│   ├── romero_v2/              # Archivos MOESM crudos, WES y fasta V2
│   └── structures/             # PDBs y predicciones validadas
└── webapp/                     # Frontend SPA en Vanilla JS + PDBe Molstar
    ├── index.html              # Plantilla base y layout
    ├── css/style.css           # Tema oscuro bioinformático
    └── js/                     # Módulos reactivos (app, dashboard, clinical, etc.)
```

**Repositorio autocontenido.** Código, configuración, contenedores y documentación no
dependen de otros proyectos ni de rutas del host: los únicos recursos externos son APIs
públicas (cBioPortal, UniProt, ChEMBL, CiViC, AlphaFold DB) y CDN para la WebApp. Las rutas
absolutas que aparecen en `tests/reference/` e `infra/mlflow/` son metadatos históricos de
corridas ya ejecutadas, no se resuelven en ejecución (ver
[`docs/LEGACY_MAP.md`](docs/LEGACY_MAP.md#5-auditoría-de-rutas-absolutas-2026-11-03)).

---

## 6. Ejecución del Pipeline

Ambos pipelines están implementados bajo la especificación [Nextflow DSL2](https://www.nextflow.io/).

### Pipeline V1 (TCGA-BRCA)

Ejecuta el flujo para la cohorte internacional TCGA-BRCA utilizando los insumos incluidos en el repositorio (`tests/reference/`):

```bash
# Prueba de humo con 1 variante y datos precalculados (rápida, sin GPU).
# --outdir results_v1 evita sobrescribir el contrato V2 de results/data.
nextflow run main.nf -profile docker,test \
  --outdir results_v1

# Validación V1 con 3 variantes y exhaustiveness 2, 100 % offline:
# FASTA y estructuras salen de tests/reference/romero_v2/ (sin consultar UniProt).
nextflow run main.nf -profile docker,test \
  --outdir results_v1_quick \
  --max_variants 3 \
  --exhaustiveness 2 \
  --fasta_dir tests/reference/romero_v2/fasta \
  --structures_dir tests/reference/romero_v2/structures \
  --mlflow_tracking_uri http://gemamx_mlflow:5000

# Modo producción con CPU usando el snapshot de mutaciones y catálogo de fármacos del repo
nextflow run main.nf \
  --study_id brca_tcga \
  --mutations_json tests/reference/mutations_snapshot.json \
  --fasta_dir tests/reference/romero_v2/fasta \
  --structures_dir tests/reference/romero_v2/structures \
  --drug_catalog assets/drug_catalog.csv \
  --genes "PIK3CA,TP53,AKT1" \
  --max_variants 3 \
  --structures_mode precomputed \
  --exhaustiveness 8 \
  -profile docker

# Reanudar ejecución previa
nextflow run main.nf -resume -profile docker
```

> `-profile docker` es necesario en todas las invocaciones: los procesos declaran sus contenedores
> (`gemamx-cpu:1.0.0`, `gemamx-nf-docking:1.0.0`) y sin ese perfil Nextflow los ejecutaría en el
> host. El perfil `test` no activa Docker por sí solo, por eso va como `docker,test`.
>
> **Contrato V2 intacto.** El perfil `test` escribe por defecto en `results/`, el mismo `outdir`
> que producción. Para validar sin tocar `results/data`, pasa siempre `--outdir results_v1`
> (o `results_v1_quick`): esos directorios están ignorados por git y la WebApp no los lee.
>
> **Red inestable.** `--fasta_dir` usa FASTA locales y evita la consulta a UniProt; las
> estructuras de `tests/reference/romero_v2/structures` cubren PIK3CA, TP53 y AKT1 (WT y MUT).
> Sin `--fasta_dir`, `FETCH_FASTA_WT` puede fallar con `SSLZeroReturnError` si UniProt cierra
> la conexión.

### Pipeline V2 (Romero-Córdoba 2021 HM)

Ejecuta el flujo para la cohorte de pacientes mexicanas con integración clínica, utilizando los insumos oficiales del estudio (*Nature Comms 2021*) incluidos en `tests/reference/romero_v2/`.

El perfil `romero-v2` ya fija los insumos dentro del repo (`romero_maf`, `romero_drivers`,
`romero_clinical`, `fasta_dir`, `structures_dir`, `drug_catalog`, `genes` y `max_variants`), así
que **no hace falta pasar rutas por CLI**:

```bash
# Cohorte completa (49 variantes) — ejecución canónica
nextflow run main_v2.nf -profile docker,romero-v2

# Equivalente con el wrapper: añade -name y reintenta la subida de los
# reportes HTML a MLflow. El archivo en results/runs/<run>/, el índice y la
# promoción de results/data/ los hace el pipeline al terminar.
bash run_pipeline_v2.sh

# Prueba rápida aislada (2 variantes, outdir results/smoke, sin tocar results/data)
bash tests/run_smoke_v2.sh
```

> `-profile docker` **no es opcional**: los procesos declaran sus contenedores
> (`gemamx-cpu:1.0.0`, `gemamx-nf-docking:1.0.0`) y, sin ese perfil, Nextflow los ejecuta
> nativamente en el host y falla al no encontrar Vina, Open Babel, RDKit ni Meeko.
>
> Para sobrescribir un valor concreto (p. ej. limitar variantes) se puede añadir
> `--max_variants 2` después del `-profile`; el resto de rutas se heredan del perfil.
> Los reportes `report.html`, `timeline.html`, `trace.tsv` y `dag.html` se generan siempre
> en `<outdir>/pipeline_info/` (ver `nextflow.config`).

### Pipeline V2.1 (un WT por variante · solo CPU)

Corrige el WT único por gen de V2 (cada variante se compara contra su propio WT),
centra el plegado en una ventana que cubre bolsillo y mutación, y limita el docking
a los pares de `assets/target_drug_map.csv`. `main_v2.nf` no se modifica.
Comparativa completa en [V2.0 vs V2.1](#v20-vs-v21).

```bash
nextflow run main_v2_1.nf -profile docker,romero-v2,v2_1

# Prueba de humo aislada (3 variantes)
bash tests/run_smoke_v2_1.sh -stub-run
```

> **Límites de tiempo**: `RUN_VINA` declara `time = '1h'` con `exhaustiveness=1` y `4h`
> con `exhaustiveness≥8`; el perfil `v2_1` fija `vina_timeout_sec = 12600` (3.5 h). El
> `time` de Nextflow solo lo aplica el scheduler (SLURM/SGE/PBS): en el executor local
> el corte real lo da el timeout interno de Vina.

Detalles, contrato y limitación de cobertura de los fragmentos: `docs/V2_1.md`.

### Ejecución sin Java ni Nextflow en el host

Si el host solo tiene Docker (Windows/macOS con Docker Desktop, o un servidor sin JDK), el
orquestador puede correr dentro de la imagen oficial conectada al daemon:

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /run/desktop/mnt/host/d/ProyectosIA/gemamx_nf:/run/desktop/mnt/host/d/ProyectosIA/gemamx_nf \
  -v /run/desktop/mnt/host/d/ProyectosIA/gemamx_work:/run/desktop/mnt/host/d/ProyectosIA/gemamx_work \
  -v /run/desktop/mnt/host/d/ProyectosIA/nextflow_home:/nxf_home \
  -e HOME=/root -e NXF_HOME=/nxf_home -e NXF_ANSI_LOG=false \
  -w /run/desktop/mnt/host/d/ProyectosIA/gemamx_nf \
  nextflow/nextflow:26.10.5 \
  nextflow run main.nf -profile docker,test \
    --outdir results_v1 --fasta_dir tests/reference/romero_v2/fasta
```

- Los bind mounts deben usar la ruta que ve el **daemon**. En Docker Desktop es
  `/run/desktop/mnt/host/<unidad>/...`; en Linux coincide con la ruta del host.
- `NXF_HOME` y el `workDir` (`-w`) deben ser persistentes para permitir `-resume` y caché.
- Nextflow 26 exige **run names únicos** dentro del mismo `NXF_HOME`: usa `-name` distinto por
  corrida (p. ej. `v1_smoke_20261104b`, `v1_quick_20261104b`) o limpia la caché.
- El repositorio no tiene que estar dentro del contenedor de Nextflow si se monta con la
  misma ruta que usa el daemon; los contenedores de proceso se lanzan por el socket.
- `git_commit` queda como `unknown` si `git` no está disponible en el contenedor orquestador;
  no afecta los resultados ni el contrato.

---

## 7. Servicios Docker y MLflow

El proyecto cuenta con un stack Docker autónomo en `docker-compose.yml`:

```yaml
services:
  gemamx_postgres:  # Base de datos relacional para MLflow (puerto 5432)
  gemamx_mlflow:    # Servidor MLflow Tracking UI (puerto 5000)
  gemamx_webapp:    # Servidor Nginx para la WebApp (puerto 8080)
```

- **Interfaz [MLflow](https://mlflow.org/)**: Accede a `http://localhost:5000` para comparar corridas, inspeccionar curvas de afinidad, descargar artefactos PDBQT o auditar el rendimiento entre `GEMAMX-V1-NF` y `GEMAMX-V2-ROMERO`.

### Imágenes verificadas (corrida de validación 2026-11-04)

| Imagen | Tamaño | Contenido validado | Uso |
|---|---|---|---|
| `gemamx-cpu:1.0.0` | 2.44 GB | Python 3.12.15, Biopython 1.88, NumPy 2.5.4, pandas 2.3.3, RDKit 2026.03.1, Meeko 0.8.0, gemmi 0.7.5, MLflow 2.19.0, Open Babel 3.2.1, AutoDock Vina 1.2.7 | FASTA, estructuras, alineamiento, métricas y registro MLflow |
| `gemamx-nf-docking:1.0.0` | 2.44 GB | Python 3.12.15, RDKit 2026.03.1, Meeko 0.8.0, gemmi 0.7.5, AutoDock Vina 1.2.7 | `PREP_LIGAND`, `PREP_RECEPTOR`, `DOCK_CENTER`, `RUN_VINA` |
| `gemamx-mlflow:1.0.0` | 1.26 GB | MLflow 2.19.0, driver PostgreSQL y parche de UI | Servidor de tracking (`:5000`) |
| `gemamx-webapp:1.0.0` | 74 MB | Nginx + SPA (Vanilla JS, PDBe Molstar) | WebApp (`:8080`) |
| `nextflow/nextflow:26.10.5` | 1.36 GB | Nextflow 26.10.5 | Orquestador cuando el host no tiene Java/Nextflow |
| `postgres:16.4-bookworm` | 617 MB | PostgreSQL 16.4 | Backend de MLflow (`:5432`) |

- **Construcción de imágenes**: `gemamx-mlflow:1.0.0` se construye desde `containers/mlflow/Dockerfile` y `gemamx-webapp:1.0.0` desde `webapp/Dockerfile`. Las imágenes de los procesos Nextflow se construyen desde `containers/cpu/Dockerfile` y `containers/docking/Dockerfile`. Para reconstruirlas: `docker compose build mlflow webapp` y `docker compose --profile images build`; para levantar el stack usando lo recién construido: `docker compose up -d --build`. La imagen GPU (`gemamx-gpu:1.0.0`) queda fuera de este flujo porque requiere una base CUDA/ROCm que no se construye en CPU.
- **Mirror APT con reintentos**: `containers/cpu/Dockerfile` redirige `security.ubuntu.com` a `archive.ubuntu.com` y usa `Acquire::Retries=5` con timeouts de 30 s. Evita que un corte intermitente del CDN de seguridad aborte la construcción de la imagen.
- **Reportes Nextflow automáticos**: `nextflow.config` genera `report.html`, `timeline.html`, `trace.tsv` y `dag.html` en `<outdir>/pipeline_info/`, y `workflow.onComplete` lanza `bin/nf_reports_hook.sh` para adjuntarlos al run padre de MLflow. No hacen falta flags ni wrappers; el log de la subida queda en `<outdir>/pipeline_info/upload.log`. Los `-stub-run` se omiten.
- **Independencia de Entorno**: El stack no depende de contenedores externos ni servicios en la nube de pago para la persistencia.
- **Red por defecto**: el perfil `docker` de Nextflow usa la red `gemamx_net` y resuelve MLflow como `gemamx_mlflow:5000`, igual que los wrappers `run_pipeline*.sh`. No hay perfiles ni redes de otros proyectos.
- **Estructuras externas (AlphaFold DB)**: los genes del explorador que no tienen estructura en la corrida vigente (p. ej. `ERBB4`) usan el modelo WT de AlphaFold DB. Se descargan una sola vez con `python3 bin/fetch_external_structures.py --genes ERBB4` y quedan en `structures/external/` (`<GEN>_AF.cif` + `index.json`). La WebApp monta esa carpeta como `/external` y la usa como respaldo en la ficha y en el visor 3D; no depende de `results/` ni se pierde al relanzar el pipeline. Para refrescar todos los genes sin estructura de la corrida: `python3 bin/fetch_external_structures.py --from-data --top 40`.

---

## 8. WebApp Interactiva (6 Vistas Integradas)

La WebApp está disponible en **`http://localhost:8080`**. Al cambiar de corrida en el selector superior (`#sel-run`), la aplicación conmuta reactivamente todas las vistas y actualiza los títulos y métricas en función del pipeline activo (TCGA-BRCA o Romero HM):

1. **Pipeline Status (Vista Principal)**: Trazabilidad completa del flujo Nextflow (M1-M5), resumen de parámetros, enlace directo a la corrida en [MLflow](https://mlflow.org/) local (`http://localhost:5000`) y **visor modal interactivo con el código fuente real ejecutado** en cada etapa.
2. **Exploración de Datasets**: Tabla dinámica y filtrable de mutaciones somáticas (frecuencias, porcentajes de cohorte, clasificaciones ACMG/Hotspot y botones interactivos para inspeccionar estructuras WT y MUT). La columna **PROTEÍNA** muestra el nombre funcional del gen y el botón **Selección** abre una ficha en español con función, regulación, dominios y relevancia clínica; incluye la tabla de **inhibidores con afinidades WT/MUT, Δ y gráfica comparativa**, además de un **visor 3D grande** con la proteína coloreada N→C, el residuo mutado resaltado y el acoplamiento de cada fármaco (pose de AutoDock Vina). Si la corrida no trae estructura para el gen (p. ej. ERBB4), la ficha usa el modelo WT de AlphaFold DB de `structures/external/` y lo indica en el visor. Sincronizada dinámicamente con los insumos del pipeline seleccionado.
3. **Análisis (Genómico y Clínico Integrado)**: Vista unificada que combina las distribuciones de variantes por gen/tipo con el módulo clínico FUCAM cuando la corrida corresponde a V2 (IHC: Luminal A/B, HER2+, TNBC; PAM50: LumA, LumB, Basal, Her2, Normal; rangos de edad y correlación por variante).
4. **Estructuras 3D**: Visores moleculares interactivos con [PDBe Molstar](https://github.com/PDBeurope/pdbe-molstar) para comparar Wild-Type (WT) vs Mutado (MUT), inspeccionar scores de confianza pLDDT y métricas de RMSD activo.
5. **Docking Molecular**: Evaluación y ranking de afinidad para los 11 fármacos antineoplásicos con AutoDock Vina, cálculo de deltas $\Delta = \text{MUT} - \text{WT}$, panel de disponibilidad en México y visualización 3D del complejo receptor-ligando.
6. **Reporte por Variante**: Ficha técnica descargable de impacto clínico, estructural y farmacológico para oncología de precisión y medicina personalizada.

---

## 9. Pipelines Nextflow y Herramientas Relacionadas

Proyectos de la comunidad Nextflow y de oncología genómica que complementan a GEMA MX o abordan un problema similar, y que pueden inspirar futuras extensiones (tipificación HLA, neoantígenos, anotación clínica de variantes, predicción del efecto de mutaciones *missense*). Ninguno forma parte del pipeline actual.

| Proyecto | Qué hace | Relación con GEMA MX |
|---|---|---|
| [**NeoFlow**](https://github.com/bzhanglab/neoflow) ([Wen et al., *Nat Commun* 2020](https://doi.org/10.1038/s41467-020-15456-w)) | Pipeline Nextflow de proteogenómica para el descubrimiento de neoantígenos: anotación de variantes, identificación de péptidos variantes por MS/MS, tipificación HLA y predicción de neoantígenos | Convertir las variantes somáticas priorizadas en neoepítopos |
| [**nf-core/hlatyping**](https://nf-co.re/hlatyping/2.2.0/) | Tipificación HLA a partir de datos NGS con [OptiType](https://github.com/FRED-2/OptiType) (DNA/RNA, DSL2) | Genotipo HLA de las pacientes; los alelos HLA varían entre poblaciones |
| [**WiGiTS (hmftools)**](https://github.com/hartwigmedical/hmftools) | Suite abierta de análisis de genoma y transcriptoma para cáncer (Sage, Pave, Purple, Lilac, Neo, Linx, Protect, entre otras), ejecutable con [Oncoanalyser](https://nf-co.re/oncoanalyser) | Llamado, anotación y accionabilidad clínica de variantes (licencia GPL-3.0) |
| [**PredictONCO**](https://loschmidt.chemi.muni.cz/predictonco/) ([Khan et al., *J Cheminform* 2024](https://doi.org/10.1186/s13321-024-00876-3)) | Servidor web (Loschmidt Laboratories, Masaryk University) con un flujo de trabajo para analizar el efecto de mutaciones *missense* sobre la estabilidad y la función de proteínas oncogénicas conocidas. Combina modelado rápido de proteínas, predicción de estabilidad, análisis evolutivo y cribado virtual de fármacos aprobados por FDA/EMA, y resume las salidas en una única probabilidad (exactitud balanceada > 86 %) | Proyecto más cercano en objetivo: variante *missense* → estructura → efecto → fármacos candidatos. GEMA MX añade una cohorte mexicana (Romero-Córdoba 2021), docking Vina por par fármaco-diana y trazabilidad de corridas con Nextflow + MLflow. El artículo está en [`papers/`](papers/) |

Descripción detallada, entradas requeridas, consideraciones de compatibilidad y posibles líneas de integración en **[`docs/PIPELINES_RELACIONADOS.md`](docs/PIPELINES_RELACIONADOS.md)**.

---

## 10. Referencias y Tecnologías

- **[Nextflow](https://www.nextflow.io/)**: Di Tommaso, P., et al. (2017). *Nextflow enables reproducible computational workflows*. Nature Biotechnology, 35(4), 316-319.
- **[MLflow](https://mlflow.org/)**: Zaharia, M., et al. (2018). *Accelerating the Machine Learning Lifecycle with MLflow*. IEEE Micro.
- **Cohorte Mexicana (Romero-Córdoba 2021)**: Romero-Córdoba, S. L., et al. (2021). *The landscape of somatic mutations and clinical phenotypes in Mexican patients with breast cancer*. Nature Communications, 12(1), 22478. [DOI: 10.1038/s41467-021-22478-5](https://doi.org/10.1038/s41467-021-22478-5).
- **AutoDock Vina**: Trott, O., & Olson, A. J. (2010). *AutoDock Vina: improving the speed and accuracy of docking with a new scoring function, efficient optimization, and multithreading*. Journal of computational chemistry, 31(2), 455-461.
- **ChEMBL**: Gaulton, A., et al. (2012). *ChEMBL: a large-scale bioactivity database for drug discovery*. Nucleic Acids Research, 40(D1), D1100-D1107.
- **CiViC**: Griffith, M., et al. (2017). *CIViC is a community knowledgebase for expert crowdsourcing the clinical interpretation of variants in cancer*. Nature Genetics, 49(2), 170-174.
- **NeoFlow**: Wen, B., et al. (2020). *Cancer neoantigen prioritization through sensitive and reliable proteogenomics analysis*. Nature Communications, 11, 1759. [DOI: 10.1038/s41467-020-15456-w](https://doi.org/10.1038/s41467-020-15456-w).
- **PredictONCO**: Khan, R. T., Pokorná, P., Štourač, J., Borko, S., Arefiev, I., Planas-Iglesias, J., Dobiáš, A., Pinto, G., Szotkowská, V., Štěrba, J., Slabý, O., Damborský, J., Mazurenko, S., & Bednář, D. (2024). *A computational workflow for analysis of missense mutations in precision oncology*. Journal of Cheminformatics, 16(1), 1-10. [DOI: 10.1186/s13321-024-00876-3](https://doi.org/10.1186/s13321-024-00876-3). Servidor web: [loschmidt.chemi.muni.cz/predictonco](https://loschmidt.chemi.muni.cz/predictonco/). PDF en [`papers/`](papers/).
- **nf-core**: Ewels, P. A., et al. (2020). *The nf-core framework for community-curated bioinformatics pipelines*. Nature Biotechnology. [DOI: 10.1038/s41587-020-0439-x](https://doi.org/10.1038/s41587-020-0439-x).

---

## 11. Licencia y Créditos

Proyecto desarrollado por el equipo de investigación **GEMA MX** en la **Universidad de Sonora (UNISON)**. Distribuido bajo la licencia [MIT](LICENSE).
