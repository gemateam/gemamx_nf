#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_DIR="${YUCA_BASE_DIR:?Define YUCA_BASE_DIR según las instrucciones de tu sitio}"
SLURM_ACCOUNT="${YUCA_SLURM_ACCOUNT:?Define YUCA_SLURM_ACCOUNT según tu asignación}"
SLURM_PARTITION="${YUCA_SLURM_PARTITION:?Define YUCA_SLURM_PARTITION según tu clúster}"
SIF_PATH="${YUCA_SIF_PATH:-${BASE_DIR}/containers/gemamx-nf-docking-1.0.0.sif}"

if [[ -f /etc/profile ]]; then
    # HPC module functions are commonly initialized by the login profile.
    # shellcheck disable=SC1091
    set +u
    source /etc/profile
    set -euo pipefail
fi

if ! command -v apptainer >/dev/null 2>&1; then
    if ! type module >/dev/null 2>&1; then
        printf 'No se encontró Apptainer ni el comando module.\n' >&2
        exit 2
    fi
    module load apptainer/1.5.3-3.el8
fi

for command in java nextflow apptainer sbatch squeue; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        printf 'Falta %s en PATH. Instala Java/Nextflow en espacio de usuario o carga los módulos aprobados.\n' "${command}" >&2
        exit 2
    fi
done

for path in \
    "${SIF_PATH}" \
    "${ROOT}/tests/reference/romero_v2/raw/41467_2021_22478_MOESM8_ESM.xlsx" \
    "${ROOT}/tests/reference/romero_v2/raw/41467_2021_22478_MOESM9_ESM.xlsx" \
    "${ROOT}/tests/reference/romero_v2/raw/41467_2021_22478_MOESM4_ESM.xlsx" \
    "${ROOT}/tests/reference/romero_v2/fasta/PIK3CA_WT.fasta" \
    "${ROOT}/tests/reference/romero_v2/structures/PIK3CA_H1047R.pdb" \
    "${ROOT}/assets/drug_catalog.csv" \
    "${ROOT}/assets/binding_sites.csv" \
    "${ROOT}/assets/target_drug_map.csv"; do
    if [[ ! -r "${path}" ]]; then
        printf 'Falta un archivo requerido o no es legible: %s\n' "${path}" >&2
        exit 3
    fi
done

mkdir -p "${BASE_DIR}/work" "${BASE_DIR}/apptainer-cache"
probe="${BASE_DIR}/work/.write-test-${USER}-$$"
touch "${probe}"
rm -f "${probe}"

printf '%s\n' '=== Versiones en el controlador ==='
java -version 2>&1 | head -n 2
nextflow -version
apptainer --version
printf '%s\n' '=== Herramientas dentro del SIF ==='
apptainer exec "${SIF_PATH}" vina --version
apptainer exec "${SIF_PATH}" obabel -V
apptainer exec "${SIF_PATH}" python3 -c 'import Bio, mlflow, rdkit; print("Python stack OK | Bio", Bio.__version__, "| MLflow", mlflow.__version__, "| RDKit", rdkit.__version__)'
printf '%s\n' '=== SLURM ==='
sinfo -p "${SLURM_PARTITION}" -o '%P %a %l %D %c'
printf 'Cuenta configurada: %s\n' "${SLURM_ACCOUNT}"
printf 'SIF verificado: %s\n' "${SIF_PATH}"
printf 'Raíz del release: %s\n' "${ROOT}"
