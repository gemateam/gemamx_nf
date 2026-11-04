# Imagen CPU de GEMA MX — gemamx-cpu:1.0.0
#
# Base reproducible para todos los procesos Nextflow que no requieren GPU:
#   FETCH_FASTA, PREDICT_STRUCTURE (ESMFold/precomputed), ALIGN_WT_MUT,
#   BUILD_JSONS, PUBLISH, LOG_MLFLOW y los procesos de ingestión clínica.
#
# Herramientas:
#   - Python 3.12 + Biopython, NumPy, pandas, requests
#   - RDKit 2026.03.1 + Meeko 0.8.0 + gemmi (PREP_LIGAND)
#   - Open Babel 3.2.1 (PREP_RECEPTOR)
#   - AutoDock Vina 1.2.7 (RUN_VINA)
#   - MLflow 2.19.0 (LOG_MLFLOW)
#
# Construcción:
#   docker build -t gemamx-cpu:1.0.0 containers/cpu
#   # o, desde compose:
#   docker compose --profile images build cpu-base
#
# La imagen derivada de docking se construye después:
#   docker build -t gemamx-nf-docking:1.0.0 containers/docking
FROM mambaorg/micromamba:2.9.0-ubuntu24.04

USER root
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git tini \
    && rm -rf /var/lib/apt/lists/*

COPY containers/cpu/environment.yml /tmp/environment.yml
RUN micromamba create -p /opt/conda/envs/gemamx -y -f /tmp/environment.yml \
    && micromamba clean --all --yes \
    && rm -f /tmp/environment.yml

ENV PATH=/opt/conda/envs/gemamx/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Falla en tiempo de build si falta una herramienta que usan los procesos.
RUN python --version \
    && python -c "import Bio, numpy, pandas, requests, rdkit, meeko, gemmi, mlflow; \
print('Bio', Bio.__version__, '| numpy', numpy.__version__, \
      '| pandas', pandas.__version__, '| rdkit', rdkit.__version__, \
      '| meeko', meeko.__version__, '| gemmi', gemmi.__version__, \
      '| mlflow', mlflow.__version__)" \
    && obabel -V \
    && vina --version

WORKDIR /workspace

# Nextflow ejecuta el script del proceso directamente; no hay entrypoint de API.
ENTRYPOINT []
CMD ["/bin/bash"]
