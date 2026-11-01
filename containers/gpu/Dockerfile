# Imagen GPU para Boltz-1 — gemamx-nf-gpu:1.0.0
#
# Motivo (ver docs/BOLTZ_HPC.md y docs/PROPUESTAS_PLATAFORMA.md, P2):
#   La imagen de la plataforma `gemamx-gpu:1.0.0` (CUDA + Boltz-1) no está
#   publicada en este entorno, y el equipo de desarrollo no tiene GPU.
#   Este Dockerfile NO se construye aquí: se construye una sola vez en un host
#   con GPU y se publica en el registro (o se convierte a .sif para Apptainer).
#
# No se duplica el Dockerfile de la plataforma: parte de la imagen publicada
# por nombre y tag fijo y solo fija la versión de Boltz que se validó.
#
# Construcción (obligatorio fijar la versión verificada):
#   docker build \
#       --build-arg BOLTZ_VERSION=<version-validada> \
#       -t gemamx-nf-gpu:1.0.0 containers/gpu
#
#   docker run --rm --gpus all gemamx-nf-gpu:1.0.0 boltz --help
#
# YUCA (ACARUS, UNISON) usa AMD Instinct MI210 + ROCm 6.2.3, no CUDA. Para esa
# ruta hay que partir de una base con PyTorch ROCm:
#   docker build --build-arg BASE_IMAGE=rocm/pytorch:... \
#                --build-arg BOLTZ_VERSION=<version-validada> \
#                -t gemamx-nf-gpu:1.0.0 containers/gpu
# y convertirla a SIF (no hay daemon Docker en el clúster):
#   apptainer build gemamx-nf-gpu_1.0.0.sif docker-daemon://gemamx-nf-gpu:1.0.0
#
# Con la base CUDA por defecto, sustituir el chequeo final de `cuda` por el
# equivalente ROCm (`torch.cuda.is_available()` sigue siendo la API correcta).

ARG BASE_IMAGE=gemamx-gpu:1.0.0
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="gemamx-nf-gpu" \
      org.opencontainers.image.description="Boltz-1 sobre la imagen GPU de la plataforma" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.base.name="gemamx-gpu:1.0.0"

ARG BOLTZ_VERSION=""

USER root

RUN test -n "${BOLTZ_VERSION}" || \
        (echo "ERROR: pasa --build-arg BOLTZ_VERSION=<versión validada>" >&2 && exit 1)

RUN pip install --no-cache-dir "boltz==${BOLTZ_VERSION}" \
    && boltz --help > /dev/null \
    && python -c "import torch; print('torch', torch.__version__, '| cuda disponible:', torch.cuda.is_available())"
