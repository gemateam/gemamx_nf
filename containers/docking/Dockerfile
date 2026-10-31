# Imagen derivada para PREP_LIGAND — gemamx-nf-docking:1.0.0
#
# Motivo (ver docs/PROPUESTAS_PLATAFORMA.md, propuesta P1):
#   La imagen de la plataforma `gemamx-cpu:1.0.0` incluye meeko 0.5.0, que
#   importa `rdkit.six`; RDKit 2026.03.1 ya no expone ese módulo, por lo que
#   `import meeko` falla y PREP_LIGAND no puede ejecutarse.
#
#   Meeko 0.8.0 (+ gemmi 0.7.5) funciona con el RDKit de la imagen base.
#   Verificado: preparación de ligando desde SMILES → PDBQT con Meeko 0.8.0.
#
# No se duplica el Dockerfile de la plataforma: esta imagen parte de la imagen
# publicada por nombre y tag fijo y solo añade la capa mínima necesaria.
#
# Construcción:
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
