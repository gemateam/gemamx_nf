# Imagen derivada para PREP_LIGAND — gemamx-nf-docking:1.0.0
#
# La imagen base `gemamx-cpu:1.0.0` ya incluye RDKit 2026.03.1 y Meeko 0.8.0
# (ver containers/cpu/environment.yml). Esta capa fija explícitamente Meeko
# 0.8.0 + gemmi 0.7.5 para que PREP_LIGAND no dependa de lo que resuelva pip
# en el futuro.
#
# No se duplica el Dockerfile de la plataforma: esta imagen parte de la imagen
# construida por `containers/cpu/Dockerfile` y solo añade la capa mínima.
#
# Construcción (primero la base):
#   docker build -t gemamx-cpu:1.0.0 containers/cpu
#   docker build -t gemamx-nf-docking:1.0.0 containers/docking

FROM gemamx-cpu:1.0.0

LABEL org.opencontainers.image.title="gemamx-nf-docking" \
      org.opencontainers.image.description="Meeko 0.8 compatible con RDKit 2026.03 para PREP_LIGAND" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.base.name="gemamx-cpu:1.0.0"

USER root

RUN pip install --no-cache-dir \
        "meeko==0.8.0" \
        "gemmi==0.7.5" \
    && python -c "import meeko, gemmi, rdkit; print('meeko', meeko.__version__, '| gemmi', gemmi.__version__, '| rdkit', rdkit.__version__)"
