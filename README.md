# GEMA MX — Genomic Analysis of Mammary Cancer

[![Pipeline](https://img.shields.io/badge/pipeline-Nextflow%20DSL2-brightgreen)](https://nextflow.io)
[![MLflow](https://img.shields.io/badge/tracking-MLflow-blue)](https://mlflow.org)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

Pipeline bioinformático completo para el análisis genómico de cáncer de mama (TCGA-BRCA).
Cubre desde la ingesta de datos del GDC hasta docking molecular con AutoDock Vina, con una
webapp interactiva para exploración de resultados y conexión en vivo a ChEMBL y CiViC.

![Arquitectura GEMA MX](docs/architecture.html)

---

## Tabla de contenidos

1. [Requisitos](#1-requisitos)
2. [Instalación rápida](#2-instalación-rápida)
3. [Estructura del proyecto](#3-estructura-del-proyecto)
4. [Ejecutar el pipeline](#4-ejecutar-el-pipeline)
5. [Levantar la webapp](#5-levantar-la-webapp)
6. [Selector de corridas (MLflow)](#6-selector-de-corridas-mlflow)
7. [Fuentes de datos externas](#7-fuentes-de-datos-externas)
8. [Desarrollo local de la webapp](#8-desarrollo-local-de-la-webapp)
9. [Generador de diagramas (Archify)](#9-generador-de-diagramas-archify)
10. [Variables de entorno y configuración](#10-variables-de-entorno-y-configuración)
11. [Solución de problemas comunes](#11-solución-de-problemas-comunes)
12. [Contribuir](#12-contribuir)

---

## 1. Requisitos

| Herramienta | Versión mínima | Propósito |
|---|---|---|
| [Nextflow](https://nextflow.io/docs/latest/install.html) | 23.10+ | Orquestador del pipeline |
| [Docker](https://docs.docker.com/get-docker/) | 24+ | Contenedores CPU/GPU |
| [Docker Compose](https://docs.docker.com/compose/install/) | 2.20+ | Stack webapp + MLflow |
| [Node.js](https://nodejs.org/) | 18+ | Archify (diagramas) |
| Git | 2.40+ | Control de versiones |
| GPU opcional | NVIDIA con CUDA | Módulo Boltz-1 (M3) |

> **Windows**: se recomienda WSL2 + Docker Desktop. El pipeline Nextflow corre dentro de
> contenedores, por lo que WSL2 no es estrictamente necesario para la webapp.

---

## 2. Instalación rápida

```bash
# 1. Clonar el repositorio
git clone https://github.com/gemateam/gemamx_nf.git
cd gemamx_nf

# 2. (Opcional) Construir imágenes Docker locales
#    Solo necesario si no se usan las imágenes publicadas en el registry
docker build -t gemamx-cpu:1.0.0  containers/cpu/
docker build -t gemamx-gpu:1.0.0  containers/gpu/
docker build -t gemamx-nf-docking:1.0.0  containers/docking/

# 3. Levantar MLflow (necesario para el pipeline)
docker compose --profile standalone up -d mlflow

# 4. Verificar que MLflow esté listo
curl http://localhost:5000/health

# 5. Ejecutar el pipeline con datos de prueba
nextflow run main.nf -profile test
```

---

## 3. Estructura del proyecto

```
gemamx_nf/
├── main.nf                     # Punto de entrada del pipeline Nextflow
├── nextflow.config             # Configuración global (perfiles, recursos)
├── nextflow_schema.json        # Schema JSON para validación de parámetros
├── assets/
│   └── drug_catalog.csv        # Catálogo de 11 fármacos con ChEMBL IDs
├── bin/                        # Scripts Python auxiliares del pipeline
│   └── prep_boltz_yaml.py
├── conf/                       # Configs por perfil (cpu, gpu, hpc)
│   ├── base.config
│   ├── cpu.config
│   └── gpu.config
├── containers/                 # Dockerfiles
│   ├── cpu/                    # Imagen CPU (variant prioritization, report)
│   ├── gpu/                    # Imagen GPU (Boltz-1 structural prediction)
│   └── docking/                # Imagen AutoDock Vina 1.2.3
├── docs/
│   └── architecture.html       # Diagrama de arquitectura interactivo (Archify)
├── modules/
│   ├── ingestion/              # M1: GDC API → mutations JSON
│   ├── variants/               # M2: priorización clínica
│   ├── structure/              # M3: Boltz-1 / AlphaFold / ESMFold
│   ├── docking/                # M4: AutoDock Vina
│   └── report/                 # M5: publicación del contrato de datos
├── results/
│   ├── data/                   # Contrato vigente (JSON + CIF/PDB)
│   │   ├── top_variants.json
│   │   ├── structural_metrics.json
│   │   ├── manifest_structures.json
│   │   ├── mutation_stats.json
│   │   ├── raw_mutations.json
│   │   ├── run_manifest.json
│   │   ├── drug_catalog.csv
│   │   ├── docking/
│   │   │   ├── vina_affinities.json
│   │   │   ├── complex/        # PDB proteína+ligando por fármaco
│   │   │   └── results/        # PDBQT crudos de Vina
│   │   └── structures/         # CIF/PDB de variantes WT y MUT
│   └── runs/                   # Historial de corridas archivadas
│       ├── index.json          # Índice de corridas con pipeline_version
│       └── <run_name>/
│           ├── data/           # Snapshot del contrato de esa corrida
│           └── run_manifest.json
├── tests/
│   └── reference/              # Datos de referencia para pruebas
├── webapp/                     # Frontend SPA
│   ├── index.html
│   ├── molstar-viewer.html
│   ├── favicon.svg
│   ├── css/style.css
│   ├── js/
│   │   ├── app.js              # Navegación SPA, loadJSON, BASE_PATH
│   │   ├── dashboard.js        # Dashboard general
│   │   ├── explore.js          # Exploración TCGA (tabla completa)
│   │   ├── pipeline.js         # Pipeline Status + MLflow params
│   │   ├── structural.js       # Visores PDBe Molstar WT/MUT
│   │   ├── docking.js          # Ranking fármacos + visor de poses
│   │   ├── drug-sources.js     # ChEMBL REST + CiViC GraphQL en vivo
│   │   ├── analysis.js         # Análisis mutacional
│   │   └── report.js           # Reporte por variante
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml
└── .claude/
    └── skills/archify/         # Skill Archify para generación de diagramas
```

---

## 4. Ejecutar el pipeline

### Parámetros principales

| Parámetro | Default | Descripción |
|---|---|---|
| `--study_id` | `brca_tcga` | ID del estudio TCGA |
| `--genes` | `PIK3CA,TP53,ERBB2,...` | Genes a analizar (comma-separated) |
| `--max_variants` | `1` | Variantes por gen para estructuras/docking |
| `--structures_mode` | `precomputed` | `precomputed` o `boltz` o `alphafold` |
| `--exhaustiveness` | `1` | Exhaustividad AutoDock Vina (1-32) |
| `--num_modes` | `5` | Poses de docking por fármaco |
| `--outdir` | `results` | Directorio de salida |
| `--mlflow_tracking_uri` | `http://localhost:5000` | URI del servidor MLflow |
| `--mlflow_experiment` | `GEMAMX-V1-NF` | Nombre del experimento en MLflow |

### Perfiles disponibles

```bash
# Prueba rápida con datos de referencia (no requiere GPU)
nextflow run main.nf -profile test

# Producción con CPU (estructuras precomputadas)
nextflow run main.nf \
  --study_id brca_tcga \
  --genes "PIK3CA,TP53,ERBB2,BRCA1,BRCA2" \
  --max_variants 5 \
  --structures_mode precomputed \
  --exhaustiveness 8 \
  -profile cpu

# Producción con GPU (Boltz-1 para predicción estructural)
nextflow run main.nf \
  --study_id brca_tcga \
  --genes "PIK3CA,TP53,ERBB2,BRCA1,BRCA2" \
  --max_variants 5 \
  --structures_mode boltz \
  --exhaustiveness 16 \
  -profile gpu

# Reanudar una corrida interrumpida
nextflow run main.nf -resume -profile cpu
```

### Ver logs de MLflow

Una vez que el pipeline termina, abre `http://localhost:5000` para ver las métricas,
parámetros y artefactos registrados bajo el experimento `GEMAMX-V1-NF`.

---

## 5. Levantar la webapp

```bash
# Primera vez: construir la imagen y levantar
docker compose up -d webapp

# Actualizar tras cambios en webapp/
docker compose build webapp
docker compose up -d webapp

# Ver logs
docker compose logs -f webapp

# Parar
docker compose down
```

La webapp queda disponible en **http://localhost:8080**.

### Vistas disponibles

| Vista | Descripción |
|---|---|
| **Dashboard** | KPIs generales: variantes, hotspot #1, estructuras, mejor afinidad |
| **Pipeline Status** | Estado por etapa (M1–M5), parámetros de la corrida, info MLflow |
| **Exploración TCGA** | Tabla completa de variantes con filtros; botones WT/MUT → visor 3D |
| **Análisis** | Distribución de mutaciones por gen y tipo |
| **Estructuras 3D** | Visor PDBe Molstar WT vs MUT, pLDDT, RMSD por región |
| **Docking** | Ranking de fármacos, tabla WT vs MUT, visor de poses, fuentes de datos |
| **Reporte** | Perfil completo por variante |

---

## 6. Selector de corridas (MLflow)

El selector **Pipeline / Corrida** en el navbar permite cambiar entre:

- **Corrida vigente** — datos en `results/data/` (los más recientes)
- **Corridas archivadas** — listadas desde `results/runs/index.json`, agrupadas por
  versión del pipeline (campo `pipeline_version`)

Cuando el pipeline termina con `--publish_run_archive true` (default), archiva
automáticamente un snapshot en `results/runs/<run_name>/`.

### Agregar una corrida al índice manualmente

Edita `results/runs/index.json`:

```json
[
  {
    "run_name": "mi_corrida",
    "published_at": "2026-11-01T00:00:00Z",
    "git_commit": "abc1234",
    "pipeline_version": "GEMAMX-V1-NF",
    "path": "runs/mi_corrida/data"
  }
]
```

---

## 7. Fuentes de datos externas

La webapp conecta en vivo (sin autenticación) a:

| Fuente | Tipo | URL | Datos |
|---|---|---|---|
| **ChEMBL** | REST JSON | `https://www.ebi.ac.uk/chembl/api/data/` | Fases clínicas, mecanismo de acción |
| **CiViC** | GraphQL v2 | `https://civicdb.org/api/graphql` | Evidencia clínica por variante |
| **PDBe Molstar** | CDN JS | `https://cdn.jsdelivr.net/npm/pdbe-molstar@3.2.0/` | Visor 3D CIF/PDB |

DrugBank y OncoKB requieren licencia; se muestran como pendientes en el panel de fuentes.

---

## 8. Desarrollo local de la webapp

La webapp es HTML/CSS/JS puro (sin bundler). Para desarrollo sin Docker:

```bash
# Servir localmente con cualquier servidor estático
# Opción 1: Python
cd webapp
python -m http.server 8080

# Opción 2: Node.js
npx serve webapp -p 8080

# Opción 3: Live Server (VS Code / Kiro extension)
# Abrir webapp/index.html con Live Server
```

> Los archivos de datos deben estar en `webapp/data/` o montar `results/data/` en esa ruta.
> Con Docker Compose esto se hace automáticamente vía el volumen `:ro`.

---

## 9. Generador de diagramas (Archify)

El proyecto incluye [Archify](https://github.com/tt-a1i/archify) instalado como skill de Kiro
en `.claude/skills/archify/`. Permite generar diagramas de arquitectura interactivos.

```bash
# Verificar instalación
node .claude/skills/archify/bin/archify.mjs doctor

# Regenerar el diagrama de arquitectura
node .claude/skills/archify/bin/archify.mjs finalize architecture \
  .archify/architecture-gemamx-20261031-222552/candidate.json \
  docs/architecture.html \
  --repo-root . \
  --quality showcase \
  --json
```

El diagrama `docs/architecture.html` es un HTML standalone interactivo con tema oscuro/claro.

---

## 10. Variables de entorno y configuración

El pipeline no requiere variables de entorno obligatorias, pero puede configurarse vía
`nextflow.config` o parámetros en línea de comandos.

Para usar un servidor MLflow remoto:

```bash
nextflow run main.nf \
  --mlflow_tracking_uri http://mi-servidor-mlflow:5000 \
  --mlflow_experiment GEMAMX-V1-NF \
  -profile cpu
```

Para HPC con SLURM, añade un perfil en `nextflow.config`:

```groovy
profiles {
  slurm {
    process.executor = 'slurm'
    process.queue    = 'gpu'
    process.clusterOptions = '--gres=gpu:1'
  }
}
```

---

## 11. Solución de problemas comunes

| Problema | Causa probable | Solución |
|---|---|---|
| `PDBeMolstarPlugin is not defined` | CSS de Molstar no cargado | Verificar `<link>` de `pdbe-molstar.css` en `index.html` |
| Visor 3D negro sin estructura | `postMessage` antes de init | Ya resuelto en v1 con `render()` secuencial + `waitForBothViewers` |
| `manifest_structures.json` vacío | Pipeline no completó M3 | Ejecutar con `--structures_mode precomputed` y estructuras en `tests/reference/structures/` |
| MLflow `unhealthy` | Puerto 5000 en uso | Cambiar puerto en `docker-compose.yml` o cerrar el proceso que usa 5000 |
| `vina_affinities.json` no encontrado | M4 no ejecutado | Usar `-profile test` para datos de prueba precalculados |
| CiViC sin respuesta | CORS en desarrollo local | Usar Docker Compose (Nginx maneja CORS) o un proxy local |

---

## 12. Contribuir

1. Haz fork del repositorio en GitHub
2. Crea una rama: `git checkout -b feature/mi-mejora`
3. Commitea tus cambios con mensajes descriptivos
4. Abre un Pull Request describiendo el cambio y lo que se probó

### Estándares de código

- **Nextflow**: seguir convenciones DSL2 (módulos en `modules/`, procesos con `container`)
- **JavaScript**: ES modules (`import/export`), sin bundler, compatible con Chrome 100+
- **CSS**: variables CSS (`--teal`, `--bg`, etc.), BEM-like para clases específicas
- **Datos**: el contrato de datos (`results/data/`) debe ser backward-compatible entre versiones

---

## Créditos

Proyecto desarrollado en la **Universidad de Sonora (UNISON)** por el equipo GEMA MX.

- Pipeline bioinformático: Nextflow DSL2 + Docker
- Predicción estructural: [Boltz-1](https://github.com/jwohlwend/boltz), AlphaFold, ESMFold
- Docking molecular: [AutoDock Vina 1.2.3](https://github.com/ccsb-scripps/AutoDock-Vina)
- Visor 3D: [PDBe Molstar](https://github.com/PDBeurope/pdbe-molstar)
- Datos clínicos: [NCI GDC](https://portal.gdc.cancer.gov/) · TCGA-BRCA
- Farmacología: [ChEMBL](https://www.ebi.ac.uk/chembl/) · [CiViC](https://civicdb.org)
- Diagramas: [Archify](https://github.com/tt-a1i/archify)
